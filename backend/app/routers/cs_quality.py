# -*- coding: utf-8 -*-
"""
客服质检路由（API 入口之一）

注意：质检服务本身在 services/quality_inspection.py，是完全可复用的独立模块；
本路由只是它的「其中一个调用方」——负责人工触发、结果查看、报表统计、规则配置管理。
其他调用方（admin 暂存区预处理、labeling 清洗、export 导出精炼等）也可直接调用同一服务。

质检规则：系统中只维护「一份」配置（quality_inspection_configs 表第一条/默认记录），
维度、权重、违规项、业务人设、模型、及格线全部可配置。前端用可视化表单编辑，无需手写 JSON。
"""
from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func, or_
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime
import json

from app.models.database import get_db, get_session_local
from app.models.quality import QualityInspectionConfigModel, QualityInspection
from app.services.quality_inspection import (
    QualityInspectionService,
    default_qc_config,
    config_from_dict,
    config_to_dict,
    QualityInspectionConfig,
)
from app.deps import get_optional_user

router = APIRouter(prefix="/api/qc", tags=["quality-inspection"])


# ===================== 请求/响应模型 =====================

class DimensionSchema(BaseModel):
    key: str
    name: str
    weight: float
    description: str = ""
    scale: int = 100


class ViolationSchema(BaseModel):
    key: str
    name: str
    severity: str = "medium"
    description: str = ""


class ConfigSchema(BaseModel):
    name: str
    description: str = ""
    business_persona: str = "你是某平台的在线客服。"
    model: str = ""                 # 空 = 跟随设置页「质检与质量评分」板块；填了则这套标准单独指定
    dimensions: List[DimensionSchema]
    violations: List[ViolationSchema]
    pass_threshold: float = 60.0
    timeout_seconds: int = 60
    max_retries: int = 1
    language: str = "zh"


class InspectRequest(BaseModel):
    session_id: str
    start_time: Optional[int] = None
    end_time: Optional[int] = None


class BatchInspectRequest(BaseModel):
    session_ids: List[str]


class ReviewRequest(BaseModel):
    human_override_score: Optional[float] = None
    human_notes: Optional[str] = None


# ===================== 配置解析工具 =====================

def _get_single_config_row(db: DBSession):
    """系统中只维护一份质检配置，取第一条（默认优先、id 升序）。"""
    return db.query(QualityInspectionConfigModel).order_by(
        QualityInspectionConfigModel.is_default.desc(),
        QualityInspectionConfigModel.id,
    ).first()


def resolve_config(db: DBSession) -> QualityInspectionConfig:
    """取系统唯一一份质检配置；若未配置则回退到代码内置默认。"""
    row = _get_single_config_row(db)
    if row and row.config_json:
        return config_from_dict(row.config_json)
    return default_qc_config()


# ===================== 配置版本化 =====================

def _config_content_hash(config_json: Optional[Dict[str, Any]]) -> str:
    """规范化 JSON 的 sha256，用于版本去重（前端频繁保存/seed 幂等 → 不产生冗余版本）。"""
    import hashlib
    canon = json.dumps(config_json or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def snapshot_config_version(db: DBSession, row: QualityInspectionConfigModel,
                            note: Optional[str] = None) -> "QcConfigVersion":
    """把当前配置追加为一个版本快照（content_hash 相同则复用最新版本，不新增）。

    (config_id, version) 上有唯一索引：并发保存若撞车会抛 IntegrityError，由调用方重试。
    """
    from app.models.quality import QcConfigVersion
    chash = _config_content_hash(row.config_json)
    latest = (
        db.query(QcConfigVersion)
        .filter(QcConfigVersion.config_id == row.id)
        .order_by(QcConfigVersion.version.desc())
        .first()
    )
    if latest and latest.content_hash == chash:
        return latest
    ver = QcConfigVersion(
        config_id=row.id,
        version=(latest.version + 1) if latest else 1,
        name=row.name,
        description=row.description,
        config_json=row.config_json,
        content_hash=chash,
        note=note,
    )
    db.add(ver)
    db.flush()
    return ver


# ===================== 存储工具 =====================

def _store_inspection(db: DBSession, result, session_id: str, cfg: QualityInspectionConfig,
                      config_id: Optional[int], agent_name: Optional[str],
                      start_time=None, end_time=None) -> QualityInspection:
    row = QualityInspection(
        session_id=session_id,
        agent_name=agent_name,
        config_id=config_id,
        config_name=cfg.name,
        conversation_snapshot=result.conversation_json,
        start_time=start_time,
        end_time=end_time,
        scores=result.scores,
        overall_score=result.overall_score,
        violations=result.violations,
        summary=result.summary,
        suggestions=result.suggestions,
        llm_raw=result.llm_raw,
        scored=result.scored,
        status="pending",
    )
    db.add(row)
    db.flush()
    return row


def serialize_inspection(row: QualityInspection, full: bool = False) -> Dict[str, Any]:
    data = {
        "id": row.id,
        "session_id": row.session_id,
        "agent_name": row.agent_name,
        "config_id": row.config_id,
        "config_name": row.config_name,
        "overall_score": row.overall_score,
        "scores": row.scores,
        "violations": row.violations,
        "scored": row.scored,
        "status": row.status,
        "human_override_score": row.human_override_score,
        "human_notes": row.human_notes,
        "reviewer": row.reviewer,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }
    if full:
        data.update({
            "conversation_snapshot": row.conversation_snapshot,
            "summary": row.summary,
            "suggestions": row.suggestions,
            "llm_raw": row.llm_raw,
            "start_time": row.start_time,
            "end_time": row.end_time,
        })
    return data


# ===================== 单一配置（系统中只维护一份） =====================

@router.get("/config")
def get_current_config(db: DBSession = Depends(get_db)):
    """返回当前已保存的配置（若有）与代码内置默认，供前端表单初始化。"""
    row = _get_single_config_row(db)
    current = None
    if row:
        current = {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "is_default": row.is_default,
            "is_active": row.is_active,
            "config": row.config_json,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
    return {
        "current": current,
        "default": config_to_dict(default_qc_config()),
    }


@router.post("/config/seed-default")
def seed_default_config(db: DBSession = Depends(get_db)):
    """把代码内置的默认配置写入数据库（已存在则覆盖）。"""
    cfg = default_qc_config()
    row = _get_single_config_row(db)
    if row:
        row.name = cfg.name
        row.description = cfg.description
        row.is_default = True
        row.is_active = True
        row.config_json = config_to_dict(cfg)
    else:
        row = QualityInspectionConfigModel(
            name=cfg.name,
            description=cfg.description,
            is_default=True,
            is_active=True,
            config_json=config_to_dict(cfg),
        )
        db.add(row)
    db.flush()
    ver = snapshot_config_version(db, row, note="恢复默认配置")
    db.commit()
    db.refresh(row)
    return {"message": "已恢复默认质检配置", "id": row.id,
            "config_version_id": ver.id, "config_version": ver.version}


@router.put("/config")
def save_config(payload: ConfigSchema, db: DBSession = Depends(get_db)):
    """保存（覆盖）系统唯一一份质检配置。"""
    row = _get_single_config_row(db)
    if row:
        row.name = payload.name
        row.description = payload.description
        row.is_default = True
        row.is_active = True
        row.config_json = payload.model_dump()
    else:
        row = QualityInspectionConfigModel(
            name=payload.name,
            description=payload.description,
            is_default=True,
            is_active=True,
            config_json=payload.model_dump(),
        )
        db.add(row)
    db.flush()
    ver = snapshot_config_version(db, row, note="保存配置")
    db.commit()
    db.refresh(row)
    return {"id": row.id, "message": "已保存质检配置",
            "config_version_id": ver.id, "config_version": ver.version}


@router.get("/config/versions")
def list_config_versions(db: DBSession = Depends(get_db)):
    """质检配置的版本历史（供校准分析按版本复现与跨版本对比）。"""
    from app.models.quality import QcConfigVersion
    rows = (
        db.query(QcConfigVersion)
        .order_by(QcConfigVersion.created_at.desc(), QcConfigVersion.id.desc())
        .all()
    )
    current_row = _get_single_config_row(db)
    current_hash = _config_content_hash(current_row.config_json) if current_row else None
    return {
        "items": [
            {
                "id": r.id,
                "config_id": r.config_id,
                "version": r.version,
                "name": r.name,
                "note": r.note,
                "content_hash": r.content_hash,
                "is_current": r.content_hash == current_hash,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


# ===================== 质检执行 =====================

@router.post("/inspect")
def inspect_session(req: InspectRequest, db: DBSession = Depends(get_db)):
    """对单个会话执行质检（同步，LLM 调用可能较慢）。"""
    cfg = resolve_config(db)
    row_cfg = _get_single_config_row(db)
    svc = QualityInspectionService(cfg)
    result = svc.inspect_session(req.session_id, db, req.start_time, req.end_time)
    row = _store_inspection(
        db, result, req.session_id, cfg,
        config_id=(row_cfg.id if row_cfg else None),
        agent_name=result.agent_name,
        start_time=req.start_time, end_time=req.end_time,
    )
    db.commit()
    return serialize_inspection(row, full=True)


@router.post("/batch")
def batch_inspect(req: BatchInspectRequest, background_tasks: BackgroundTasks, db: DBSession = Depends(get_db)):
    """批量质检：后台异步执行，立即返回已接受。"""
    if not req.session_ids:
        raise HTTPException(status_code=400, detail="session_ids 不能为空")
    session_ids = list(dict.fromkeys(req.session_ids))  # 去重
    background_tasks.add_task(_run_batch_inspections, session_ids)
    return {"message": "已提交批量质检", "accepted": len(session_ids)}


def _run_batch_inspections(session_ids: List[str]):
    """后台任务：使用独立 DB 会话执行批量质检。"""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        cfg = resolve_config(db)
        row_cfg = _get_single_config_row(db)
        cfg_id = row_cfg.id if row_cfg else None
        svc = QualityInspectionService(cfg)
        for sid in session_ids:
            try:
                result = svc.inspect_session(sid, db)
                _store_inspection(db, result, sid, cfg, cfg_id, result.agent_name)
            except Exception as e:
                print(f"[WARN] 批量质检失败 {sid}: {e}")
        db.commit()
    finally:
        db.close()


# ===================== 结果查询 =====================

@router.get("/list")
def list_inspections(
    session_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    violation_type: Optional[str] = None,
    status: Optional[str] = None,
    config_id: Optional[int] = None,
    scored: Optional[bool] = None,
    start_time: Optional[int] = Query(None, description="时间窗起点（秒级时间戳，按创建时间）"),
    end_time: Optional[int] = Query(None, description="时间窗终点（秒级时间戳，按创建时间）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db),
):
    query = db.query(QualityInspection)
    if session_id:
        query = query.filter(QualityInspection.session_id == session_id)
    if agent_name:
        query = query.filter(QualityInspection.agent_name == agent_name)
    if min_score is not None:
        query = query.filter(QualityInspection.overall_score >= min_score)
    if max_score is not None:
        query = query.filter(QualityInspection.overall_score <= max_score)
    if status:
        query = query.filter(QualityInspection.status == status)
    if config_id is not None:
        query = query.filter(QualityInspection.config_id == config_id)
    if scored is not None:
        query = query.filter(QualityInspection.scored == scored)
    if start_time is not None:
        query = query.filter(QualityInspection.created_at >= datetime.utcfromtimestamp(start_time))
    if end_time is not None:
        query = query.filter(QualityInspection.created_at <= datetime.utcfromtimestamp(end_time))
    # violation_type 过滤（violations 为 JSON 数组，DB 无关，统一在内存做，避免 JSONB/SQLite 差异）
    if violation_type:
        candidate = query.all()
        filtered = [
            r for r in candidate
            if isinstance(r.violations, list)
            and any((v.get("type") or v.get("key")) == violation_type for v in r.violations)
        ]
        total = len(filtered)
        start = (page - 1) * page_size
        items = filtered[start:start + page_size]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [serialize_inspection(i) for i in items],
        }

    total = query.count()
    items = query.order_by(QualityInspection.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [serialize_inspection(i) for i in items],
    }


# 注意：用 :int 转换器约束，否则单段的动态路由会抢占 /feedback（静态单段路径）导致其 422
@router.get("/{inspection_id:int}")
def get_inspection(inspection_id: int, db: DBSession = Depends(get_db)):
    row = db.query(QualityInspection).filter(QualityInspection.id == inspection_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="质检记录不存在")
    return serialize_inspection(row, full=True)


@router.post("/{inspection_id}/review")
def review_inspection(
    inspection_id: int,
    req: ReviewRequest,
    db: DBSession = Depends(get_db),
    user=Depends(get_optional_user),
):
    row = db.query(QualityInspection).filter(QualityInspection.id == inspection_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="质检记录不存在")
    if req.human_override_score is not None:
        row.human_override_score = req.human_override_score
    if req.human_notes is not None:
        row.human_notes = req.human_notes
    row.status = "reviewed"
    row.reviewer = user.username if user else None
    row.reviewed_at = datetime.utcnow()
    db.commit()
    return serialize_inspection(row, full=True)


# ===================== 统计报表 =====================

@router.get("/stats/summary")
def qc_stats(db: DBSession = Depends(get_db)):
    total = db.query(QualityInspection).count()
    if total == 0:
        return {
            "total": 0,
            "avg_score": None,
            "pass_rate": None,
            "score_distribution": {},
            "top_violations": [],
            "agent_leaderboard": [],
            "by_status": {},
        }

    # 平均分（仅统计已评分且有总分）
    avg = db.query(func.avg(QualityInspection.overall_score)).filter(
        QualityInspection.scored == True,  # noqa: E712
        QualityInspection.overall_score.isnot(None),
    ).scalar() or 0

    # 及格率：用唯一一份配置的及格线
    row = _get_single_config_row(db)
    threshold = (row.config_json or {}).get("pass_threshold", 60) if row else 60
    passed = db.query(QualityInspection).filter(
        QualityInspection.scored == True,  # noqa: E712
        QualityInspection.overall_score >= threshold,
    ).count()
    scored_total = db.query(QualityInspection).filter(QualityInspection.scored == True).count()  # noqa: E712
    pass_rate = round(passed / scored_total, 3) if scored_total else 0

    # 评分分布
    rows = db.query(QualityInspection.overall_score).filter(
        QualityInspection.scored == True,  # noqa: E712
        QualityInspection.overall_score.isnot(None),
    ).all()
    dist = {"low(<60)": 0, "mid(60-79)": 0, "high(80+)": 0}
    for (s,) in rows:
        if s < 60:
            dist["low(<60)"] += 1
        elif s < 80:
            dist["mid(60-79)"] += 1
        else:
            dist["high(80+)"] += 1

    # 违规 TOP
    viol_counter: Dict[str, int] = {}
    all_rows = db.query(QualityInspection.violations).filter(
        QualityInspection.violations.isnot(None)
    ).all()
    for (v,) in all_rows:
        if isinstance(v, list):
            for item in v:
                t = item.get("type") or item.get("key")
                if t:
                    viol_counter[t] = viol_counter.get(t, 0) + 1
    top_violations = sorted(viol_counter.items(), key=lambda x: x[1], reverse=True)[:8]

    # 客服排行（按 agent_name 聚合）
    agent_rows = db.query(
        QualityInspection.agent_name,
        func.avg(QualityInspection.overall_score),
        func.count(QualityInspection.id),
    ).filter(
        QualityInspection.scored == True,  # noqa: E712
        QualityInspection.overall_score.isnot(None),
    ).group_by(QualityInspection.agent_name).all()
    leaderboard = [
        {"agent_name": a, "avg_score": round(avg_s, 1), "count": c}
        for (a, avg_s, c) in agent_rows
    ]
    leaderboard.sort(key=lambda x: x["avg_score"], reverse=True)

    # 状态分布
    status_rows = db.query(QualityInspection.status, func.count(QualityInspection.id)).group_by(
        QualityInspection.status
    ).all()
    by_status = {s: c for (s, c) in status_rows}

    return {
        "total": total,
        "avg_score": round(avg, 1) if avg else None,
        "pass_rate": pass_rate,
        "threshold": threshold,
        "score_distribution": dist,
        "top_violations": [{"type": t, "count": c} for t, c in top_violations],
        "agent_leaderboard": leaderboard,
        "by_status": by_status,
    }


# ===================== 数据回流 / 反向优化 =====================

@router.get("/feedback")
def qc_feedback(db: DBSession = Depends(get_db)):
    """将质检结果回流数据中心，聚合为「优化数据包」：
    - 错题场景（低分/含违规的会话）
    - 低分维度（各维度均值，升序=最弱优先）
    - 主管复核结果（人工分与 AI 分差异 + 复核备注）
    - 高频培训问题（违规 TOP + 最弱维度推导）
    并据此反向给出：培训素材 / 客服话术 / 知识库切片 / 内容生产方向 的优化建议。
    """
    rows = db.query(QualityInspection).all()
    total = len(rows)
    if total == 0:
        return {
            "total": 0, "threshold": 60,
            "weak_dimensions": [], "top_violations": [], "wrong_cases": [],
            "supervisor_corrections": [], "training_topics": [], "optimization": {},
        }

    # 维度名映射 + 及格线（取自唯一一份配置）
    cfg_row = _get_single_config_row(db)
    dim_name_map = (
        {d.get("key"): d.get("name", d.get("key")) for d in (cfg_row.config_json or {}).get("dimensions", [])}
        if cfg_row else {}
    )
    threshold = (cfg_row.config_json or {}).get("pass_threshold", 60) if cfg_row else 60

    # 1) 低分维度：各维度均值
    dim_scores: Dict[str, List[float]] = {}
    for r in rows:
        if isinstance(r.scores, dict):
            for k, v in r.scores.items():
                try:
                    dim_scores.setdefault(k, []).append(float(v))
                except (TypeError, ValueError):
                    pass
    weak_dimensions = [
        {"key": k, "name": dim_name_map.get(k, k), "avg": round(sum(v) / len(v), 1), "sample_count": len(v)}
        for k, v in dim_scores.items()
    ]
    weak_dimensions.sort(key=lambda x: x["avg"])

    # 2) 高频违规
    viol_counter: Dict[str, int] = {}
    for r in rows:
        if isinstance(r.violations, list):
            for item in r.violations:
                t = item.get("type") or item.get("key")
                if t:
                    viol_counter[t] = viol_counter.get(t, 0) + 1
    top_violations = sorted(viol_counter.items(), key=lambda x: x[1], reverse=True)[:10]

    # 3) 错题场景：低分或含违规
    wrong_cases = []
    for r in rows:
        overall = r.overall_score
        has_viol = isinstance(r.violations, list) and len(r.violations) > 0
        is_low = overall is not None and overall < threshold
        if is_low or has_viol:
            weak = None
            if isinstance(r.scores, dict) and r.scores:
                wk = min(r.scores.items(), key=lambda kv: kv[1])[0]
                weak = dim_name_map.get(wk, wk)
            wrong_cases.append({
                "inspection_id": r.id,
                "session_id": r.session_id,
                "agent_name": r.agent_name,
                "overall_score": overall,
                "weak_dimension": weak,
                "violations": [v.get("type") or v.get("key") for v in r.violations] if isinstance(r.violations, list) else [],
                "summary": r.summary,
            })
    wrong_cases.sort(key=lambda x: (x["overall_score"] is not None, x["overall_score"] or 0))

    # 4) 主管复核结果：已复核且有最终人工分
    supervisor_corrections = []
    for r in rows:
        if r.status == "reviewed" and r.human_override_score is not None:
            ai = r.overall_score
            supervisor_corrections.append({
                "inspection_id": r.id,
                "session_id": r.session_id,
                "ai_score": ai,
                "human_score": r.human_override_score,
                "delta": round(r.human_override_score - ai, 1) if ai is not None else None,
                "human_notes": r.human_notes,
            })
    supervisor_corrections.sort(key=lambda x: abs(x["delta"] or 0), reverse=True)

    # 5) 高频培训问题：违规 TOP + 最弱维度推导
    training_topics: List[str] = []
    for t, c in top_violations[:5]:
        training_topics.append(f"违规项《{t}》高频出现（{c} 次），建议作为专项培训主题")
    for d in weak_dimensions[:3]:
        training_topics.append(f"维度《{d['name']}》均值仅 {d['avg']}，建议加强相关培训")

    # 6) 反向优化建议（四个方向）
    optimization: Dict[str, List[str]] = {
        "training_materials": [],
        "scripts": [],
        "knowledge_slices": [],
        "content_direction": [],
    }
    if wrong_cases:
        top_case = wrong_cases[0]
        optimization["training_materials"].append(
            f"将低分会话（如会话 {top_case['session_id']}，{top_case['overall_score']} 分）整理为正反案例培训素材"
        )
    for t, c in top_violations[:3]:
        optimization["scripts"].append(f"针对《{t}》生成规避话术与标准应对模板（出现 {c} 次）")
        optimization["knowledge_slices"].append(f"核查《{t}》相关知识库切片是否缺失，补充对应知识点")
    for d in weak_dimensions[:2]:
        optimization["content_direction"].append(f"内容生产向《{d['name']}》倾斜（当前均值 {d['avg']}）")

    return {
        "total": total,
        "threshold": threshold,
        "weak_dimensions": weak_dimensions,
        "top_violations": [{"type": t, "count": c} for t, c in top_violations],
        "wrong_cases": wrong_cases[:50],
        "supervisor_corrections": supervisor_corrections[:50],
        "training_topics": training_topics,
        "optimization": optimization,
    }
