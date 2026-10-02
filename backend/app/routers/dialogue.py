# -*- coding: utf-8 -*-
"""
多轮对话实训 API

生成客户情景 → 逐条多轮对话 → 落库。
不含评分/评测：由后续独立的会话质检服务消费 transcript_json。
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.dialogue import DialogueSession, DialogueSet
from app.services.dialogue import MAX_TURNS, customer_turn, generate_scenarios
from app.services.xiaocan_persona import CATEGORY_LABELS

router = APIRouter(prefix="/api/dialogue", tags=["dialogue"])


# ==================== 请求模型 ====================

class GenerateDialogueRequest(BaseModel):
    category: str = Field("savings_explain", description="实训分类")
    count: int = Field(3, ge=1, le=10, description="情景数量")
    title: Optional[str] = Field(None, description="情景集标题（可选）")


class StartSessionRequest(BaseModel):
    scenario_id: int = Field(..., description="情景集内的情景 id")


class ReplyRequest(BaseModel):
    content: str = Field(..., min_length=1, description="客服这一句的回复")


# ==================== 内部工具 ====================

def _find_scenario(dset: Optional[DialogueSet], scenario_id: int) -> Optional[dict]:
    for sc in (dset.scenarios_json if dset else []) or []:
        if sc.get("id") == scenario_id:
            return sc
    return None


def _public_scenario(scenario: Optional[dict]) -> dict:
    """剔除练习链路不该下发的字段（参考答案/原始真实对话），保留 source 供列表页展示。

    参考答案只允许在会话结束后的 get_session 里下发，见该端点。
    """
    item = dict(scenario or {})
    item.pop("reference_replies", None)
    item.pop("source_transcript", None)
    return item


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


# ==================== 情景集 ====================

@router.post("/generate")
def generate_set(req: GenerateDialogueRequest, db: DBSession = Depends(get_db)):
    """从该分类的「已审核真实对话」提炼一组客户情景并落库"""
    try:
        scenarios, source_stats = generate_scenarios(db, category=req.category, count=req.count)
    except ValueError as e:
        # 该分类没有可用的真实对话 → 客户端可修正的输入问题
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"情景生成失败: {str(e)}")

    title = req.title or (
        f"{CATEGORY_LABELS.get(req.category, '小蚕客服')}对话实训 "
        f"#{db.query(func.count(DialogueSet.id)).scalar() + 1}"
    )
    dset = DialogueSet(
        title=title,
        category=req.category,
        scenarios_json=scenarios,
        scenario_count=len(scenarios),
        status="generated",
    )
    db.add(dset)
    db.commit()
    db.refresh(dset)

    return {
        "id": dset.id,
        "title": dset.title,
        "category": dset.category,
        "scenario_count": dset.scenario_count,
        "scenarios": [_public_scenario(s) for s in scenarios],
        "source_stats": source_stats,
    }


@router.get("/sets")
def list_sets(
    category: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db),
):
    """情景集列表"""
    q = db.query(DialogueSet)
    if category:
        q = q.filter(DialogueSet.category == category)
    total = q.count()
    items = q.order_by(desc(DialogueSet.created_at)).offset(skip).limit(limit).all()

    result = []
    for s in items:
        total_sessions = (
            db.query(func.count(DialogueSession.id))
            .filter(DialogueSession.set_id == s.id)
            .scalar()
        )
        finished = (
            db.query(func.count(DialogueSession.id))
            .filter(DialogueSession.set_id == s.id, DialogueSession.status == "finished")
            .scalar()
        )
        result.append({
            "id": s.id,
            "title": s.title,
            "category": s.category,
            "scenario_count": s.scenario_count,
            "status": s.status,
            "session_count": total_sessions,
            "finished_count": finished,
            "created_at": _iso(s.created_at),
        })

    return {"total": total, "items": result}


@router.get("/sets/{set_id}")
def get_set(set_id: int, db: DBSession = Depends(get_db)):
    """情景集详情（含每个情景最近一次会话的进度）"""
    dset = db.query(DialogueSet).filter(DialogueSet.id == set_id).first()
    if not dset:
        raise HTTPException(status_code=404, detail="情景集不存在")

    sessions = (
        db.query(DialogueSession)
        .filter(DialogueSession.set_id == set_id)
        .order_by(desc(DialogueSession.created_at))
        .all()
    )
    latest: dict = {}
    for sess in sessions:
        latest.setdefault(sess.scenario_id, sess)

    scenarios = []
    for sc in dset.scenarios_json or []:
        item = _public_scenario(sc)
        sess = latest.get(sc.get("id"))
        item["session"] = (
            {"id": sess.id, "status": sess.status, "turn_count": sess.turn_count} if sess else None
        )
        scenarios.append(item)

    return {
        "id": dset.id,
        "title": dset.title,
        "category": dset.category,
        "scenario_count": dset.scenario_count,
        "status": dset.status,
        "created_at": _iso(dset.created_at),
        "scenarios": scenarios,
    }


@router.delete("/sets/{set_id}")
def delete_set(set_id: int, db: DBSession = Depends(get_db)):
    """删除情景集及其所有会话"""
    dset = db.query(DialogueSet).filter(DialogueSet.id == set_id).first()
    if not dset:
        raise HTTPException(status_code=404, detail="情景集不存在")

    db.query(DialogueSession).filter(DialogueSession.set_id == set_id).delete()
    db.delete(dset)
    db.commit()

    return {"message": "删除成功", "id": set_id}


# ==================== 会话 ====================

@router.post("/sets/{set_id}/sessions")
def start_session(set_id: int, req: StartSessionRequest, db: DBSession = Depends(get_db)):
    """按情景开启一次会话，返回客户开场白"""
    dset = db.query(DialogueSet).filter(DialogueSet.id == set_id).first()
    if not dset:
        raise HTTPException(status_code=404, detail="情景集不存在")

    scenario = _find_scenario(dset, req.scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="情景不存在")

    transcript = [{"role": "customer", "content": scenario.get("opening_line", "")}]
    sess = DialogueSession(
        set_id=set_id,
        scenario_id=req.scenario_id,
        category=dset.category,
        status="in_progress",
        transcript_json=transcript,
        turn_count=1,
        started_at=datetime.utcnow(),
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)

    return {
        "session_id": sess.id,
        "set_id": set_id,
        "scenario_id": req.scenario_id,
        "transcript": transcript,
        "turn_count": sess.turn_count,
        "max_turns": MAX_TURNS,
        "status": sess.status,
    }


@router.post("/sessions/{session_id}/reply")
def reply(session_id: int, req: ReplyRequest, db: DBSession = Depends(get_db)):
    """客服发送一句 → AI 客户回一句"""
    sess = db.query(DialogueSession).filter(DialogueSession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    if sess.status != "in_progress":
        raise HTTPException(status_code=400, detail="会话已结束")

    dset = db.query(DialogueSet).filter(DialogueSet.id == sess.set_id).first()
    scenario = _find_scenario(dset, sess.scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="情景不存在")

    transcript = list(sess.transcript_json or [])
    transcript.append({"role": "agent", "content": req.content})

    try:
        result = customer_turn(scenario, transcript)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 客户回复失败: {str(e)}")

    reply_text = result.get("reply") or "……"
    transcript.append({"role": "customer", "content": reply_text})
    sess.turn_count = (sess.turn_count or 0) + 1

    is_end = bool(result.get("is_end")) or sess.turn_count >= MAX_TURNS
    if is_end:
        sess.status = "finished"
        sess.finished_at = datetime.utcnow()

    sess.transcript_json = transcript
    db.commit()
    db.refresh(sess)

    return {
        "customer_reply": reply_text,
        "is_end": is_end,
        "turn_count": sess.turn_count,
        "max_turns": MAX_TURNS,
        "status": sess.status,
    }


@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: int, db: DBSession = Depends(get_db)):
    """学员主动结束会话"""
    sess = db.query(DialogueSession).filter(DialogueSession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")

    if sess.status == "in_progress":
        sess.status = "finished"
        sess.finished_at = datetime.utcnow()
        db.commit()

    return {"session_id": sess.id, "status": sess.status, "turn_count": sess.turn_count}


@router.get("/sessions")
def list_sessions(
    set_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db),
):
    """会话记录列表"""
    q = db.query(DialogueSession)
    if set_id:
        q = q.filter(DialogueSession.set_id == set_id)
    if status:
        q = q.filter(DialogueSession.status == status)

    total = q.count()
    items = q.order_by(desc(DialogueSession.created_at)).offset(skip).limit(limit).all()

    result = []
    for sess in items:
        dset = db.query(DialogueSet).filter(DialogueSet.id == sess.set_id).first()
        scenario = _find_scenario(dset, sess.scenario_id) or {}
        result.append({
            "id": sess.id,
            "set_id": sess.set_id,
            "set_title": dset.title if dset else None,
            "scenario_id": sess.scenario_id,
            "category": sess.category,
            "customer_persona": scenario.get("customer_persona"),
            "opening_line": scenario.get("opening_line"),
            "status": sess.status,
            "turn_count": sess.turn_count,
            "created_at": _iso(sess.created_at),
            "finished_at": _iso(sess.finished_at),
        })

    return {"total": total, "items": result}


@router.get("/sessions/{session_id}")
def get_session(session_id: int, db: DBSession = Depends(get_db)):
    """会话详情（完整对话记录）"""
    sess = db.query(DialogueSession).filter(DialogueSession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")

    dset = db.query(DialogueSet).filter(DialogueSet.id == sess.set_id).first()
    scenario = _find_scenario(dset, sess.scenario_id) or {}

    payload = {
        "id": sess.id,
        "set_id": sess.set_id,
        "set_title": dset.title if dset else None,
        "scenario_id": sess.scenario_id,
        "category": sess.category,
        "scenario": _public_scenario(scenario),
        "status": sess.status,
        "turn_count": sess.turn_count,
        "transcript": sess.transcript_json or [],
        "started_at": _iso(sess.started_at),
        "finished_at": _iso(sess.finished_at),
        "created_at": _iso(sess.created_at),
    }

    # 参考答案 / 原始真实对话仅在会话结束后下发，练习中一律不带（防泄题）
    if sess.status == "finished":
        payload["reference_replies"] = scenario.get("reference_replies") or []
        payload["source_transcript"] = scenario.get("source_transcript") or []
        payload["source"] = scenario.get("source")

    return payload
