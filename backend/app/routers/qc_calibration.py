# -*- coding: utf-8 -*-
"""
质检校准路由（/api/qc/calibration）

把「人工标注真值」按分组管理，用指定质检配置版本重跑质检服务，
再与冻结的人工分对比，得到偏差指标并支持跨版本横向对比。

约定：
- 校准结果只写 qc_calibration_* 表，不写 quality_inspections（避免污染主质检统计）。
- 项目内无 ForeignKey → 删分组时在此手动级联清理 items / runs / run_items。
- 本路由 prefix 为 /api/qc/calibration，**不暴露裸根**（避免与 /api/qc/{inspection_id}
  的单段 int 路径冲突）；所有端点为 2+ 段，天然安全。
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from typing import Dict, List, Optional, Any
from datetime import datetime

from app.models.database import get_db
from app.models.chat import RawChat, StagingConversation
from app.models.quality import (
    QcCalibrationGroup,
    QcCalibrationItem,
    QcCalibrationRun,
    QcCalibrationRunItem,
    QcConfigVersion,
    QualityInspectionConfigModel,
)
from app.routers.cs_quality import resolve_config, snapshot_config_version
from app.services.qc_calibration import run_calibration
from app.deps import get_optional_user

router = APIRouter(prefix="/api/qc/calibration", tags=["qc-calibration"])


# ===================== 请求模型 =====================

class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class ItemCreate(BaseModel):
    session_id: str = Field(..., min_length=1)
    gold_total: float = Field(..., ge=0, le=100, description="人工总分 0-100")
    gold_scores: Dict[str, float] = Field(default_factory=dict, description="{维度key: 人工分}")
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    agent_name: Optional[str] = None
    note: Optional[str] = None


class ItemUpdate(BaseModel):
    gold_total: Optional[float] = Field(None, ge=0, le=100)
    gold_scores: Optional[Dict[str, float]] = None
    note: Optional[str] = None


class RunCreate(BaseModel):
    config_version_id: Optional[int] = None  # 缺省用最新版本；无版本则用当前配置生成一条


# ===================== 序列化 =====================

def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _serialize_group(db: DBSession, g: QcCalibrationGroup) -> Dict[str, Any]:
    item_count = (
        db.query(QcCalibrationItem).filter(QcCalibrationItem.group_id == g.id).count()
    )
    run_count = (
        db.query(QcCalibrationRun).filter(QcCalibrationRun.group_id == g.id).count()
    )
    return {
        "id": g.id,
        "name": g.name,
        "description": g.description,
        "item_count": item_count,
        "run_count": run_count,
        "created_at": _iso(g.created_at),
        "updated_at": _iso(g.updated_at),
    }


def _serialize_item(i: QcCalibrationItem) -> Dict[str, Any]:
    return {
        "id": i.id,
        "group_id": i.group_id,
        "session_id": i.session_id,
        "agent_name": i.agent_name,
        "gold_total": i.gold_total,
        "gold_scores": i.gold_scores or {},
        "start_time": i.start_time,
        "end_time": i.end_time,
        "note": i.note,
        "added_config_version_id": i.added_config_version_id,
        "created_at": _iso(i.created_at),
    }


def _serialize_run_brief(r: QcCalibrationRun) -> Dict[str, Any]:
    return {
        "id": r.id,
        "group_id": r.group_id,
        "config_version_id": r.config_version_id,
        "config_version": r.config_version,
        "config_name": r.config_name,
        "pass_threshold": r.pass_threshold,
        "status": r.status,
        "total": r.total,
        "done_count": r.done_count,
        "failed_count": r.failed_count,
        "metrics": r.metrics_json,
        "error": r.error,
        "created_at": _iso(r.created_at),
        "finished_at": _iso(r.finished_at),
    }


def _get_group(db: DBSession, group_id: int) -> QcCalibrationGroup:
    g = db.query(QcCalibrationGroup).filter(QcCalibrationGroup.id == group_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="校准分组不存在")
    return g


def _current_dim_keys(db: DBSession) -> List[str]:
    return [d.key for d in resolve_config(db).dimensions]


# ===================== 分组 =====================

@router.get("/groups")
def list_groups(db: DBSession = Depends(get_db)):
    rows = db.query(QcCalibrationGroup).order_by(QcCalibrationGroup.id.asc()).all()
    return {"items": [_serialize_group(db, g) for g in rows]}


@router.post("/groups")
def create_group(
    payload: GroupCreate,
    db: DBSession = Depends(get_db),
    user=Depends(get_optional_user),
):
    name = payload.name.strip()
    exists = db.query(QcCalibrationGroup).filter(QcCalibrationGroup.name == name).first()
    if exists:
        raise HTTPException(status_code=400, detail=f"分组「{name}」已存在")
    g = QcCalibrationGroup(
        name=name,
        description=payload.description,
        created_by=(user.username if user else None),
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return _serialize_group(db, g)


@router.delete("/groups/{group_id}")
def delete_group(group_id: int, db: DBSession = Depends(get_db)):
    """删除分组及其全部标注与运行记录（无 FK → 手动级联）。"""
    g = _get_group(db, group_id)
    run_ids = [
        r.id
        for r in db.query(QcCalibrationRun.id).filter(QcCalibrationRun.group_id == group_id).all()
    ]
    if run_ids:
        db.query(QcCalibrationRunItem).filter(
            QcCalibrationRunItem.run_id.in_(run_ids)
        ).delete(synchronize_session=False)
    db.query(QcCalibrationRun).filter(QcCalibrationRun.group_id == group_id).delete(
        synchronize_session=False
    )
    db.query(QcCalibrationItem).filter(QcCalibrationItem.group_id == group_id).delete(
        synchronize_session=False
    )
    db.delete(g)
    db.commit()
    return {"message": "已删除分组", "id": group_id}


# ===================== 标注数据 =====================

@router.get("/groups/{group_id}/items")
def list_items(group_id: int, db: DBSession = Depends(get_db)):
    _get_group(db, group_id)
    rows = (
        db.query(QcCalibrationItem)
        .filter(QcCalibrationItem.group_id == group_id)
        .order_by(QcCalibrationItem.id.desc())
        .all()
    )
    return {"items": [_serialize_item(i) for i in rows], "total": len(rows)}


def _infer_window(db: DBSession, session_id: str):
    """未显式给时间窗时，从该会话最近的 staging 记录取（与 _pick_qc 匹配口径一致）。"""
    conv = (
        db.query(StagingConversation)
        .filter(StagingConversation.session_id == session_id)
        .order_by(StagingConversation.created_at.desc())
        .first()
    )
    if conv:
        return conv.start_time, conv.end_time, None
    return None, None, None


@router.post("/groups/{group_id}/items")
def add_item(
    group_id: int,
    payload: ItemCreate,
    db: DBSession = Depends(get_db),
    user=Depends(get_optional_user),
):
    """把一条会话标记为标注数据（冻结人工真值）。"""
    _get_group(db, group_id)
    session_id = payload.session_id.strip()

    # 该会话必须在 raw_chats 有内容，否则重跑必 unscored，污染统计
    msg_count = (
        db.query(RawChat).filter(RawChat.session_id == session_id).count()
    )
    if msg_count == 0:
        raise HTTPException(
            status_code=400,
            detail=f"会话 {session_id} 在 raw_chats 中没有任何消息，无法作为标注数据",
        )

    # 维度 key 必须 ⊆ 当前配置维度（按 key 存，避免中文名改动导致错配）
    dim_keys = set(_current_dim_keys(db))
    bad_keys = [k for k in (payload.gold_scores or {}).keys() if k not in dim_keys]
    if bad_keys:
        raise HTTPException(
            status_code=400,
            detail=f"人工分包含未知维度 key：{bad_keys}（当前配置维度：{sorted(dim_keys)}）",
        )

    # 同组同会话唯一
    dup = (
        db.query(QcCalibrationItem)
        .filter(
            QcCalibrationItem.group_id == group_id,
            QcCalibrationItem.session_id == session_id,
        )
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="该会话已在此分组的标注集中")

    start_time, end_time, _ = _infer_window(db, session_id)
    if payload.start_time is not None:
        start_time = payload.start_time
    if payload.end_time is not None:
        end_time = payload.end_time

    # 记录加入时的最新配置版本（仅用于追溯维度中文名）
    latest_ver = (
        db.query(QcConfigVersion).order_by(QcConfigVersion.version.desc()).first()
    )

    item = QcCalibrationItem(
        group_id=group_id,
        session_id=session_id,
        agent_name=payload.agent_name,
        gold_total=payload.gold_total,
        gold_scores=payload.gold_scores or {},
        start_time=start_time,
        end_time=end_time,
        note=payload.note,
        added_config_version_id=(latest_ver.id if latest_ver else None),
        created_by=(user.username if user else None),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize_item(item)


@router.put("/items/{item_id}")
def update_item(item_id: int, payload: ItemUpdate, db: DBSession = Depends(get_db)):
    item = db.query(QcCalibrationItem).filter(QcCalibrationItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="标注数据不存在")
    if payload.gold_total is not None:
        item.gold_total = payload.gold_total
    if payload.gold_scores is not None:
        dim_keys = set(_current_dim_keys(db))
        bad = [k for k in payload.gold_scores.keys() if k not in dim_keys]
        if bad:
            raise HTTPException(status_code=400, detail=f"人工分包含未知维度 key：{bad}")
        item.gold_scores = payload.gold_scores
    if payload.note is not None:
        item.note = payload.note
    db.commit()
    db.refresh(item)
    return _serialize_item(item)


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: DBSession = Depends(get_db)):
    item = db.query(QcCalibrationItem).filter(QcCalibrationItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="标注数据不存在")
    db.delete(item)
    db.commit()
    return {"message": "已删除标注数据", "id": item_id}


# ===================== 校准运行 =====================

def _resolve_config_version(db: DBSession, config_version_id: Optional[int]) -> QcConfigVersion:
    """确定本次重跑使用的配置版本：指定 → 最新版本 → 由当前配置生成一条。"""
    if config_version_id is not None:
        ver = (
            db.query(QcConfigVersion)
            .filter(QcConfigVersion.id == config_version_id)
            .first()
        )
        if not ver:
            raise HTTPException(status_code=404, detail="指定的配置版本不存在")
        return ver

    ver = db.query(QcConfigVersion).order_by(QcConfigVersion.version.desc()).first()
    if ver:
        return ver

    # 首次运行且尚无版本：用当前配置生成一条
    row = (
        db.query(QualityInspectionConfigModel)
        .order_by(QualityInspectionConfigModel.is_default.desc(), QualityInspectionConfigModel.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="系统尚无质检配置，请先在质检规则页保存配置")
    return snapshot_config_version(db, row, note="校准运行时自动生成")


@router.post("/groups/{group_id}/run")
def start_run(
    group_id: int,
    payload: RunCreate,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db),
    user=Depends(get_optional_user),
):
    """用指定配置版本重跑该分组（后台异步），立即返回 run_id。"""
    _get_group(db, group_id)
    item_count = (
        db.query(QcCalibrationItem).filter(QcCalibrationItem.group_id == group_id).count()
    )
    if item_count == 0:
        raise HTTPException(status_code=400, detail="该分组没有标注数据，无法校准")

    running = (
        db.query(QcCalibrationRun)
        .filter(
            QcCalibrationRun.group_id == group_id,
            QcCalibrationRun.status.in_(["pending", "running"]),
        )
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail=f"该分组已有进行中的校准运行 #{running.id}，请稍候")

    ver = _resolve_config_version(db, payload.config_version_id)
    run = QcCalibrationRun(
        group_id=group_id,
        config_version_id=ver.id,
        config_version=ver.version,
        config_name=ver.name,
        config_json=ver.config_json,
        pass_threshold=(ver.config_json or {}).get("pass_threshold", 60.0),
        status="pending",
        total=item_count,
        done_count=0,
        failed_count=0,
        created_by=(user.username if user else None),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(run_calibration, run.id)
    return {"run_id": run.id, "status": run.status, "total": item_count,
            "config_version": ver.version}


@router.get("/groups/{group_id}/runs")
def list_runs(group_id: int, db: DBSession = Depends(get_db)):
    _get_group(db, group_id)
    rows = (
        db.query(QcCalibrationRun)
        .filter(QcCalibrationRun.group_id == group_id)
        .order_by(QcCalibrationRun.created_at.desc())
        .all()
    )
    return {"items": [_serialize_run_brief(r) for r in rows], "total": len(rows)}


@router.get("/groups/{group_id}/compare")
def compare_runs(group_id: int, db: DBSession = Depends(get_db)):
    """跨版本对比：每次运行一行聚合指标（按版本/时间升序）。"""
    _get_group(db, group_id)
    rows = (
        db.query(QcCalibrationRun)
        .filter(
            QcCalibrationRun.group_id == group_id,
            QcCalibrationRun.status == "done",
        )
        .order_by(QcCalibrationRun.created_at.asc())
        .all()
    )
    items = []
    for r in rows:
        m = r.metrics_json or {}
        items.append({
            "run_id": r.id,
            "config_version": r.config_version,
            "config_name": r.config_name,
            "pass_threshold": r.pass_threshold,
            "item_count": m.get("scored_count"),
            "mae_total": m.get("mae_total"),
            "bias": m.get("bias"),
            "rmse": m.get("rmse"),
            "pass_agree_rate": m.get("pass_agree_rate"),
            "false_pass": m.get("false_pass"),
            "false_fail": m.get("false_fail"),
            "ai_dim_mean": m.get("ai_dim_mean"),
            "gold_dim_mean": m.get("gold_dim_mean"),
            "dim_set_changed": m.get("dim_set_changed"),
            "created_at": _iso(r.created_at),
        })
    return {"items": items}


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db),
):
    """运行详情：聚合指标 + 逐条对比（分页）。"""
    run = db.query(QcCalibrationRun).filter(QcCalibrationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="校准运行不存在")

    q = db.query(QcCalibrationRunItem).filter(QcCalibrationRunItem.run_id == run_id)
    total = q.count()
    rows = (
        q.order_by(QcCalibrationRunItem.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "id": x.id,
            "session_id": x.session_id,
            "ai_total": x.ai_total,
            "ai_scores": x.ai_scores,
            "ai_scored": x.ai_scored,
            "ai_missing_dims": x.ai_missing_dims,
            "ai_error": x.ai_error,
            "gold_total": x.gold_total,
            "gold_scores": x.gold_scores,
            "delta_total": x.delta_total,
            "per_dim_delta": x.per_dim_delta,
            "pass_agree": x.pass_agree,
            "violations": x.violations,
            "summary": x.summary,
        }
        for x in rows
    ]
    return {
        "run": _serialize_run_brief(run),
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
