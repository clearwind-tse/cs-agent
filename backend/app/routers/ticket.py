# -*- coding: utf-8 -*-
"""
工单管理路由（简单工单系统）

对应教材 Ch7：工单查询、详情、状态流转、指派、备注、统计
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel, Field
from typing import Optional

from app.models.database import get_db
from app.services.ticket_service import TicketService, VALID_STATUSES

router = APIRouter(prefix="/api/ticket", tags=["ticket"])


class TicketCreateRequest(BaseModel):
    session_id: Optional[str] = None
    intent: Optional[str] = None
    category: Optional[str] = None
    summary: str = Field(..., description="问题摘要")
    priority: Optional[int] = Field(None, ge=1, le=5)
    assigned_to: Optional[str] = None
    source: str = "manual"


class TicketEventRequest(BaseModel):
    content: str
    event_type: str = "comment"
    operator: str = "人工坐席"


class TicketDecisionRequest(BaseModel):
    """坐席对「待确认动作」的决策：批准后 Agent 会续跑那个被挂起的工具"""
    decision: str = Field(..., description="approve / reject")
    operator: str = Field("人工坐席", description="操作人")
    message: Optional[str] = Field(None, description="驳回理由（驳回时建议填写）")


# ==================== 固定路径（需在 /{ticket_id} 之前） ====================

@router.get("/list")
def list_tickets(
    status: Optional[str] = Query(None, description="状态过滤：open/in_progress/resolved/closed"),
    category: Optional[str] = Query(None, description="分类过滤"),
    keyword: Optional[str] = Query(None, description="按工单号/摘要模糊搜索"),
    session_id: Optional[str] = Query(None, description="按会话 ID 过滤（从会话跳工单用）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db),
):
    """分页查询工单列表"""
    return TicketService(db).list_tickets(
        status=status,
        category=category,
        keyword=keyword,
        session_id=session_id,
        page=page,
        page_size=page_size,
    )


@router.get("/stats/summary")
def ticket_stats(db: DBSession = Depends(get_db)):
    """工单统计摘要（状态/分类分布 + SLA 超时）"""
    return TicketService(db).stats()


@router.get("/history/{session_id}")
def ticket_history(session_id: str, db: DBSession = Depends(get_db)):
    """查询某会话关联的所有工单"""
    data = TicketService(db).list_tickets(session_id=session_id, page=1, page_size=100)
    items = data["items"]
    return {
        "session_id": session_id,
        "tickets": [
            {
                "id": t["id"], "ticket_no": t["ticket_no"], "category": t["category"],
                "priority": t["priority"], "status": t["status"], "summary": t["summary"],
                "created_at": t["created_at"],
            }
            for t in items
        ],
    }


@router.post("")
@router.post("/create")
def create_ticket(req: TicketCreateRequest, db: DBSession = Depends(get_db)):
    """手工创建工单"""
    ticket = TicketService(db).create_ticket(
        session_id=req.session_id,
        intent=req.intent,
        summary=req.summary,
        category=req.category,
        priority=req.priority,
        source=req.source,
        assigned_to=req.assigned_to,
    )
    return ticket.to_dict()


# ==================== 详情与操作 ====================

@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, db: DBSession = Depends(get_db)):
    """工单详情（含时间线事件）"""
    data = TicketService(db).get_ticket(ticket_id)
    if not data:
        raise HTTPException(status_code=404, detail="工单不存在")
    return data


@router.put("/{ticket_id}/status")
def update_ticket_status(
    ticket_id: int,
    status: str = Query(..., description="新状态：open/in_progress/resolved/closed"),
    resolution: Optional[str] = Query(None, description="处理结论（解决/关闭时）"),
    operator: str = Query("人工坐席", description="操作人"),
    db: DBSession = Depends(get_db),
):
    """更新工单状态（解决/关闭时记录解决时间与结论）"""
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"无效状态，可选: {sorted(VALID_STATUSES)}")
    try:
        ticket = TicketService(db).update_status(ticket_id, status, operator=operator, resolution=resolution)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    return {"message": "状态已更新", "ticket": ticket.to_dict()}


@router.put("/{ticket_id}/assign")
def assign_ticket(
    ticket_id: int,
    assigned_to: str = Query(..., description="指派给（坐席/团队）"),
    operator: str = Query("系统", description="操作人"),
    db: DBSession = Depends(get_db),
):
    """指派工单"""
    ticket = TicketService(db).assign(ticket_id, assigned_to, operator=operator)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    return {"message": "指派成功", "ticket": ticket.to_dict()}


@router.post("/{ticket_id}/events")
def add_ticket_event(ticket_id: int, req: TicketEventRequest, db: DBSession = Depends(get_db)):
    """追加备注/事件到工单时间线"""
    ev = TicketService(db).add_event(ticket_id, req.content, event_type=req.event_type, operator=req.operator)
    if not ev:
        raise HTTPException(status_code=404, detail="工单不存在")
    return ev


@router.post("/{ticket_id}/decision")
def decide_pending_action(ticket_id: int, req: TicketDecisionRequest, db: DBSession = Depends(get_db)):
    """
    坐席确认「待执行动作」→ 续跑被挂起的 Agent。

    典型链路：Agent 发起退款 → 图在审批点暂停 → 工单出现待批条 →
    坐席在这里点批准 → Command(resume=...) 用同一 thread_id 续跑 →
    submit_refund 真正执行、生成 RMA 受理号 → 结果回写工单时间线。

    幂等：已决策的工单重复调用只会返回上次结果，不会重复退款。
    """
    decision = (req.decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision 只能是 approve 或 reject")

    svc = TicketService(db)
    ticket = svc.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    from app.models.ticket import Ticket
    row = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    pa = row.pending_action or {}
    if not pa:
        raise HTTPException(status_code=400, detail="该工单没有待确认动作")
    if not pa.get("awaiting"):
        return {
            "message": "该动作已处理过（幂等返回）",
            "status": "already_decided",
            "decision": pa.get("decision"),
            "result": pa.get("result"),
            "ticket": svc.get_ticket(ticket_id),
        }

    from app.services.agent_engine import current_engine
    from app.services.deep_agent import get_deep_agent

    if current_engine() != "deepagents":
        raise HTTPException(
            status_code=409,
            detail="当前引擎（langgraph）不支持挂起/恢复，请用 AGENT_ENGINE=deepagents",
        )

    try:
        outcome = get_deep_agent(db).resume_pending(
            db, row, decision=decision, operator=req.operator, message=req.message or "",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"恢复执行失败：{type(e).__name__}: {e}")

    return {
        "message": "已批准并执行" if decision == "approve" else "已驳回，动作未执行",
        **outcome,
        "ticket": svc.get_ticket(ticket_id),
    }
