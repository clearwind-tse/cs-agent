# -*- coding: utf-8 -*-
"""
工单服务（简单工单系统的核心领域逻辑）

职责：
- 生成工单号、按优先级计算 SLA 到期时间
- 创建工单 + 初始事件（时间线）
- 查询列表 / 详情（含事件）
- 状态流转（写 resolved_at / resolution + 事件）
- 指派、追加备注事件
- 统计（按状态/分类/SLA 超时）
"""
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.models.ticket import Ticket, TicketEvent


# SLA：优先级数字越大越紧急（5=最高），到期时长越短
SLA_HOURS_BY_PRIORITY = {5: 2, 4: 4, 3: 8, 2: 24, 1: 48}
VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}

CATEGORY_BASE_PRIORITY = {
    "物流异常": 3,
    "退款申请": 4,
    "商品问题": 2,
    "投诉建议": 5,
    "订单查询": 1,
    "其他": 2,
}


def classify_category(intent: Optional[str], message: str = "") -> str:
    """根据意图 + 关键词做简单工单分类"""
    msg = (message or "").lower()
    if intent == "refund_return" or any(k in msg for k in ["退款", "退货", "退钱", "换货"]):
        return "退款申请"
    if intent == "logistics" or any(k in msg for k in ["物流", "快递", "发货", "配送", "没收到"]):
        return "物流异常"
    if intent == "complaint" or any(k in msg for k in ["投诉", "差评", "举报", "12315"]):
        return "投诉建议"
    if any(k in msg for k in ["质量", "破损", "瑕疵", "坏了", "不好用"]):
        return "商品问题"
    return {
        "refund_return": "退款申请",
        "logistics": "物流异常",
        "complaint": "投诉建议",
        "order_status": "订单查询",
    }.get(intent or "", "其他")


def normalize_category(category: Optional[str]) -> Optional[str]:
    """把 LLM 自由填写的分类归一到固定枚举，避免工单池里出现「退款」「退款申请」两种写法"""
    if not category:
        return None
    c = category.strip()
    if c in CATEGORY_BASE_PRIORITY:
        return c
    mapping = {
        "退款": "退款申请", "退货退款": "退款申请", "退货": "退款申请", "售后": "退款申请",
        "物流": "物流异常", "快递": "物流异常", "配送": "物流异常",
        "投诉": "投诉建议", "建议": "投诉建议",
        "商品": "商品问题", "质量": "商品问题",
        "订单": "订单查询", "查询": "订单查询",
    }
    for key, val in mapping.items():
        if key in c:
            return val
    return "其他"


# 同一诉求线程内允许「合并而不是另开单」的分类映射。
# 只允许 投诉建议 并入已开的业务单（客户在退款/物流单上继续表达不满），
# 反向不合并：投诉单在跟进中，客户再发起退款，仍应另开退款单走审批。
_MERGE_INTO: Dict[str, set] = {
    "投诉建议": {"退款申请", "物流异常", "商品问题"},
}


def match_priority(category: str, emotion_intensity: int = 1) -> int:
    """基础优先级 + 情绪加成（上限 5）"""
    base = CATEGORY_BASE_PRIORITY.get(category, 2)
    return max(1, min(5, base + max(0, (emotion_intensity or 1) - 2)))


def sla_due(priority: int) -> datetime:
    hours = SLA_HOURS_BY_PRIORITY.get(priority, 24)
    return datetime.utcnow() + timedelta(hours=hours)


class TicketService:
    def __init__(self, db: Session):
        self.db = db

    # ---------- 工单号 ----------
    def _generate_ticket_no(self) -> str:
        for _ in range(6):
            no = f"TK{datetime.now().strftime('%Y%m%d')}-{random.randint(100000, 999999)}"
            exists = self.db.query(Ticket.id).filter(Ticket.ticket_no == no).first()
            if not exists:
                return no
        return f"TK{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # ---------- 创建 ----------
    def create_ticket(
        self,
        *,
        session_id: Optional[str],
        intent: Optional[str],
        summary: str,
        category: Optional[str] = None,
        priority: Optional[int] = None,
        emotion_intensity: int = 1,
        source: str = "agent",
        extracted_fields: Optional[dict] = None,
        transfer_reason: Optional[str] = None,
        assigned_to: Optional[str] = None,
    ) -> Ticket:
        category = normalize_category(category) or classify_category(intent, summary)
        priority = priority or match_priority(category, emotion_intensity)
        due = sla_due(priority)
        ticket = Ticket(
            ticket_no=self._generate_ticket_no(),
            session_id=session_id,
            intent=intent,
            category=category,
            priority=priority,
            status="open",
            source=source,
            summary=(summary or "")[:500],
            extracted_fields=extracted_fields or {},
            transfer_reason=transfer_reason,
            assigned_to=assigned_to,
            sla_due_at=due,
            created_at=datetime.utcnow(),
        )
        self.db.add(ticket)
        self.db.flush()
        self.db.add(TicketEvent(
            ticket_id=ticket.id,
            event_type="created",
            content=f"工单创建：{category}（优先级 P{priority}，SLA 至 {due.strftime('%m-%d %H:%M')}）",
            operator=source,
        ))
        self.db.commit()
        self.db.refresh(ticket)
        return ticket

    # ---------- 查询 ----------
    def append_context(self, ticket: Ticket, extra: str, operator: str = "agent") -> Ticket:
        """
        把对话中新获得的关键信息补进已有工单（教材 Ch7：工单随对话持续跟进）

        避免"第一轮就建单、后面问到订单号却写不进工单"的信息丢失。
        """
        extra = (extra or "").strip()
        if not extra:
            return ticket
        # 同样的补充信息只记一次，避免多轮重复刷时间线
        if extra in (ticket.summary or ""):
            return ticket
        merged = f"{ticket.summary}｜{extra}" if ticket.summary else extra
        ticket.summary = merged[:500]
        self.db.add(TicketEvent(
            ticket_id=ticket.id,
            event_type="comment",
            content=f"对话补充：{extra}",
            operator=operator,
        ))
        self.db.commit()
        self.db.refresh(ticket)
        return ticket

    def get_ticket(self, ticket_id: int) -> Optional[dict]:
        ticket = self.db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return None
        events = (
            self.db.query(TicketEvent)
            .filter(TicketEvent.ticket_id == ticket_id)
            .order_by(TicketEvent.created_at.asc(), TicketEvent.id.asc())
            .all()
        )
        data = ticket.to_dict()
        data["events"] = [e.to_dict() for e in events]
        return data

    def list_tickets(self, *, status=None, category=None, keyword=None, session_id=None, page=1, page_size=20):
        q = self.db.query(Ticket)
        if status:
            q = q.filter(Ticket.status == status)
        if category:
            q = q.filter(Ticket.category == category)
        if session_id:
            # 精确匹配：会话 → 工单的唯一关联键，不做模糊，避免跨会话串号
            q = q.filter(Ticket.session_id == session_id)
        if keyword:
            like = f"%{keyword}%"
            q = q.filter(or_(Ticket.ticket_no.ilike(like), Ticket.summary.ilike(like)))
        total = q.count()
        rows = (
            q.order_by(Ticket.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "items": [t.to_dict() for t in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        }

    def has_open_ticket(self, session_id: Optional[str], category: Optional[str] = None) -> bool:
        return self.get_open_ticket(session_id, category) is not None

    def get_open_ticket(self, session_id: Optional[str],
                        category: Optional[str] = None) -> Optional[Ticket]:
        """取该会话（同分类）最近一张未关闭工单，用于建单幂等"""
        if not session_id:
            return None
        q = self.db.query(Ticket).filter(
            Ticket.session_id == session_id,
            Ticket.status.notin_(("resolved", "closed")),
        )
        if category:
            q = q.filter(Ticket.category == category)
        return q.order_by(Ticket.id.desc()).first()

    def get_issue_thread_ticket(self, session_id: Optional[str],
                                category: Optional[str]) -> Optional[Ticket]:
        """
        取「同一诉求线程」的未关闭工单：同分类，或可合并的相近分类。

        客户已经开了退款单，后面又补一句「你们太差了我要投诉」——这是同一件事
        的情绪升级，不是新的一件事。另开一张投诉单只会让两个坐席重复处理。
        """
        if not session_id:
            return None
        t = self.get_open_ticket(session_id, category)
        if t is not None:
            return t
        for alt in _MERGE_INTO.get(category or "", set()):
            t = self.get_open_ticket(session_id, alt)
            if t is not None:
                return t
        return None

    def escalate_priority(self, ticket: Ticket, priority: Optional[int],
                          reason: str = "") -> Ticket:
        """合并进已有工单时，若新问题更紧急则提升优先级并重算 SLA"""
        priority = int(priority or 0)
        if not ticket or priority <= (ticket.priority or 0):
            return ticket
        old = ticket.priority
        ticket.priority = priority
        ticket.sla_due_at = sla_due(priority)
        self.db.add(TicketEvent(
            ticket_id=ticket.id,
            event_type="priority_changed",
            content=f"优先级 P{old} → P{priority}" + (f"（{reason}）" if reason else ""),
            operator="agent",
        ))
        self.db.commit()
        self.db.refresh(ticket)
        return ticket

    # ---------- 待人工确认的动作（HITL） ----------
    def set_pending_action(self, ticket: Ticket, action: Dict) -> Ticket:
        """
        挂起一个待确认动作。

        `action` 里必须带 thread_id：坐席点确认时，要靠它把同一张图从断点拉起来。
        同时附上人话描述（动作、对象、金额、原因），否则工单页只能显示一堆 JSON。
        """
        ticket.pending_action = dict(action or {})
        self.db.add(TicketEvent(
            ticket_id=ticket.id,
            event_type="awaiting_approval",
            content=f"待确认动作：{action.get('title') or action.get('tool')}",
            operator="agent",
        ))
        self.db.commit()
        self.db.refresh(ticket)
        return ticket

    def resolve_pending(self, ticket: Ticket, *, decision: str, operator: str = "human",
                        result: Optional[Dict] = None) -> Ticket:
        """记录确认结果并清空待办（保留 decision 供审计与幂等判断）"""
        pa = dict(ticket.pending_action or {})
        if not pa:
            return ticket
        pa["decision"] = decision
        pa["decided_by"] = operator
        pa["decided_at"] = datetime.utcnow().isoformat()
        pa["awaiting"] = False
        if result:
            pa["result"] = result
        ticket.pending_action = pa
        self.db.add(TicketEvent(
            ticket_id=ticket.id,
            event_type="approval_decided",
            content=f"坐席{ '批准' if decision == 'approve' else '驳回' }：{pa.get('title') or pa.get('tool')}"
                    + (f"｜{result.get('rma_no')}" if result and result.get("rma_no") else ""),
            operator=operator,
        ))
        self.db.commit()
        self.db.refresh(ticket)
        return ticket

    def find_pending_ticket(self, session_id: Optional[str]) -> Optional[Ticket]:
        """该会话当前是否有一张挂着待确认动作的工单"""
        if not session_id:
            return None
        rows = (
            self.db.query(Ticket)
            .filter(Ticket.session_id == session_id,
                    Ticket.status.notin_(("resolved", "closed")),
                    Ticket.pending_action.isnot(None))
            .order_by(Ticket.id.desc())
            .all()
        )
        for t in rows:
            pa = t.pending_action or {}
            if pa.get("awaiting"):
                return t
        return None

    # ---------- 状态流转 ----------
    def update_status(self, ticket_id: int, status: str, operator: str = "system",
                      resolution: Optional[str] = None) -> Optional[Ticket]:
        if status not in VALID_STATUSES:
            raise ValueError(f"无效状态，可选: {VALID_STATUSES}")
        ticket = self.db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return None
        old = ticket.status
        ticket.status = status
        if status in ("resolved", "closed"):
            ticket.resolved_at = datetime.utcnow()
            if resolution:
                ticket.resolution = resolution
        ticket.updated_at = datetime.utcnow()
        self.db.add(TicketEvent(
            ticket_id=ticket.id,
            event_type="closed" if status == "closed" else "resolved" if status == "resolved" else "status_changed",
            content=f"状态 {old} → {status}" + (f"；结论：{resolution}" if resolution else ""),
            operator=operator,
        ))
        self.db.commit()
        self.db.refresh(ticket)
        return ticket

    def assign(self, ticket_id: int, assigned_to: str, operator: str = "system") -> Optional[Ticket]:
        ticket = self.db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return None
        old = ticket.assigned_to
        ticket.assigned_to = assigned_to
        ticket.updated_at = datetime.utcnow()
        self.db.add(TicketEvent(
            ticket_id=ticket.id,
            event_type="assigned",
            content=f"指派：{old or '未分配'} → {assigned_to}",
            operator=operator,
        ))
        self.db.commit()
        self.db.refresh(ticket)
        return ticket

    def add_event(self, ticket_id: int, content: str, event_type: str = "comment",
                  operator: str = "人工坐席") -> Optional[dict]:
        ticket = self.db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return None
        ev = TicketEvent(ticket_id=ticket_id, event_type=event_type, content=content, operator=operator)
        self.db.add(ev)
        ticket.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(ev)
        return ev.to_dict()

    # ---------- 统计 ----------
    def stats(self) -> dict:
        by_status = {s: c for s, c in self.db.query(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status).all()}
        by_category = {s: c for s, c in self.db.query(Ticket.category, func.count(Ticket.id)).group_by(Ticket.category).all()}
        total = sum(by_status.values())
        now = datetime.utcnow()
        sla_breached = (
            self.db.query(func.count(Ticket.id))
            .filter(Ticket.sla_due_at.isnot(None),
                    Ticket.sla_due_at < now,
                    Ticket.status.notin_(("resolved", "closed")))
            .scalar()
        ) or 0
        return {
            "by_status": by_status,
            "by_category": by_category,
            "total": total,
            "sla_breached": sla_breached,
            "open_total": by_status.get("open", 0) + by_status.get("in_progress", 0),
            "resolved_total": by_status.get("resolved", 0) + by_status.get("closed", 0),
        }
