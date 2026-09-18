# -*- coding: utf-8 -*-
"""
工单数据模型

对应教材 Ch7 工单生命周期：创建 → 分类 → 路由 → 处理 → 关闭
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from datetime import datetime

from .database import Base


class Ticket(Base):
    """工单表 — 对应教材 Ch7 工单生命周期"""
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_no = Column(String(50), unique=True, nullable=False, index=True)
    session_id = Column(String(100), index=True)  # 关联对话会话
    intent = Column(String(50), index=True)  # 意图类型
    category = Column(String(50), index=True)  # 物流异常/退款申请/商品问题/投诉建议
    priority = Column(Integer, default=2)  # 1-5（5 最紧急）
    status = Column(String(20), default='open', index=True)  # open/in_progress/resolved/closed
    source = Column(String(50), default='agent')  # agent/auto/manual
    summary = Column(Text)  # 问题摘要
    extracted_fields = Column(JSON, nullable=True)  # 结构化字段快照
    transfer_reason = Column(Text, nullable=True)  # 转人工原因（如有）
    assigned_to = Column(String(100), nullable=True)  # 分配给（坐席/团队）
    sla_due_at = Column(DateTime, nullable=True)  # SLA 到期时间
    resolved_at = Column(DateTime, nullable=True)  # 解决时间
    resolution = Column(Text, nullable=True)  # 处理结论
    # 待人工确认的动作（HITL）：Agent 发起不可逆动作时，图会在这里挂起，
    # 这条记录就是坐席看到的"待批条"——含 thread_id，确认后才能 Command(resume) 续跑。
    pending_action = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        now = datetime.utcnow()
        sla_breached = bool(
            self.sla_due_at
            and self.status not in ("resolved", "closed")
            and now > self.sla_due_at
        )
        return {
            "id": self.id,
            "ticket_no": self.ticket_no,
            "session_id": self.session_id,
            "intent": self.intent,
            "category": self.category,
            "priority": self.priority,
            "status": self.status,
            "source": self.source,
            "summary": self.summary,
            "extracted_fields": self.extracted_fields,
            "transfer_reason": self.transfer_reason,
            "assigned_to": self.assigned_to,
            "sla_due_at": self.sla_due_at.isoformat() if self.sla_due_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution": self.resolution,
            "pending_action": self.pending_action,
            "sla_breached": sla_breached,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TicketEvent(Base):
    """工单事件（时间线）—— 记录创建/状态变更/指派/备注/解决等轨迹"""
    __tablename__ = "ticket_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, index=True, nullable=False)
    event_type = Column(String(30), default="comment")  # created/status_changed/assigned/comment/resolved/closed
    content = Column(Text, nullable=True)
    operator = Column(String(100), nullable=True)  # 操作人（agent/人工坐席名/system）
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "event_type": self.event_type,
            "content": self.content,
            "operator": self.operator,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
