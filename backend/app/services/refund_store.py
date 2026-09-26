# -*- coding: utf-8 -*-
"""
退款受理仓（真实动作层）

为什么需要这一层：
之前 Agent 会直接说「已帮您提交退款，受理单号 RMA1001」——但系统里**根本
没有退款工具**，这个 RMA 号是模型编的。没有真实动作，就没有"坐席确认之后
再 invoke 什么"的问题。

三层职责：
- `order_store`：订单事实（只读快照）
- `refund_store`：退款受理单（写；不可逆动作的落地凭证）
- `ticket_service`：工单（人工跟进队列 + 待确认动作的载体）

受理号规则：RMA + 受理日期 + 4 位序号，例如 RMA20261031-0003。
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.services import order_store

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS refund_requests (
    id              SERIAL PRIMARY KEY,
    rma_no          VARCHAR(40) UNIQUE NOT NULL,
    session_id      VARCHAR(100),
    order_id        VARCHAR(60),
    user_id         VARCHAR(100),
    product_name    VARCHAR(200),
    amount          NUMERIC(10, 2) DEFAULT 0,
    reason          VARCHAR(200),
    status          VARCHAR(20) DEFAULT 'pending_review',
    source          VARCHAR(20) DEFAULT 'agent',
    approved_by     VARCHAR(100),
    approved_at     TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_refund_session ON refund_requests (session_id);
CREATE INDEX IF NOT EXISTS idx_refund_order ON refund_requests (order_id);
"""


def ensure_table(db) -> None:
    if db is None:
        return
    try:
        for stmt in [s.strip() for s in _CREATE_SQL.split(";") if s.strip()]:
            db.execute(text(stmt))
        db.commit()
    except Exception as e:
        print(f"[RefundStore] 建表失败: {e}")
        db.rollback()


def _next_rma_no(db) -> str:
    """RMA + 日期 + 4 位序号（同日递增，冲突则随机重试）"""
    day = datetime.now().strftime("%Y%m%d")
    try:
        row = db.execute(
            text("SELECT COUNT(*) FROM refund_requests WHERE rma_no LIKE :p"),
            {"p": f"RMA{day}-%"},
        ).first()
        seq = int(row[0]) + 1 if row else 1
    except Exception:
        seq = 1
    for _ in range(20):
        no = f"RMA{day}-{seq:04d}"
        exists = db.execute(
            text("SELECT 1 FROM refund_requests WHERE rma_no = :n"), {"n": no}
        ).first()
        if not exists:
            return no
        seq += 1
    return f"RMA{day}-{random.randint(1000, 9999)}"


def create_refund(db, *, session_id: Optional[str], order_id: str,
                  reason: str = "", user_id: Optional[str] = None,
                  source: str = "agent", approved_by: Optional[str] = None) -> Dict[str, Any]:
    """
    生成一张真实的退款受理单。

    金额取订单实付（`order_store`），不接受模型随口给的数字——
    这是资金动作，金额只能来自订单事实，不能来自 LLM 的推测。
    """
    ensure_table(db)
    order = order_store.get_order(order_id) or {}
    verdict = order_store.evaluate_refund(order)
    if not verdict.get("eligible"):
        return {
            "success": False,
            "error": verdict.get("reason") or "不符合退款条件",
            "order_id": order_id,
            "eligible": False,
        }

    amount = float(order.get("amount") or 0)
    rma_no = _next_rma_no(db)
    db.execute(
        text(
            "INSERT INTO refund_requests "
            "(rma_no, session_id, order_id, user_id, product_name, amount, reason, status, source, approved_by, approved_at) "
            "VALUES (:rma, :sid, :oid, :uid, :prod, :amt, :reason, :status, :src, :by, :at)"
        ),
        {
            "rma": rma_no,
            "sid": session_id,
            "oid": order_id,
            "uid": user_id,
            "prod": order.get("product_name"),
            "amt": amount,
            "reason": (reason or "客户申请退款")[:200],
            "status": "pending_review",
            "src": source,
            "by": approved_by,
            "at": datetime.utcnow() if approved_by else None,
        },
    )
    db.commit()
    return {
        "success": True,
        "rma_no": rma_no,
        "order_id": order_id,
        "product_name": order.get("product_name"),
        "amount": amount,
        "status": "pending_review",
        "eta": "1 个工作日内审核完成，通过后 1-3 个工作日原路退回",
    }


def get_refund(db, rma_no: str) -> Optional[Dict[str, Any]]:
    if db is None or not rma_no:
        return None
    ensure_table(db)
    row = db.execute(
        text(
            "SELECT rma_no, session_id, order_id, product_name, amount, reason, "
            "status, source, approved_by, created_at FROM refund_requests WHERE rma_no = :n"
        ),
        {"n": rma_no},
    ).mappings().first()
    return dict(row) if row else None


def list_refunds(db, session_id: Optional[str] = None, order_id: Optional[str] = None,
                 limit: int = 20) -> List[Dict[str, Any]]:
    if db is None:
        return []
    ensure_table(db)
    sql = ("SELECT rma_no, session_id, order_id, product_name, amount, reason, status, "
           "source, created_at FROM refund_requests WHERE 1=1")
    params: Dict[str, Any] = {}
    if session_id:
        sql += " AND session_id = :sid"
        params["sid"] = session_id
    if order_id:
        sql += " AND order_id = :oid"
        params["oid"] = order_id
    sql += " ORDER BY id DESC LIMIT :lim"
    params["lim"] = limit
    return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def known_rma_nos(db, session_id: Optional[str] = None) -> set:
    """
    真实存在的受理号集合（回复质量闸门用）。

    模型偶尔会编 RMA 号；没有这条校验，客户会拿着一个查不到的号去催客服。
    """
    rows = list_refunds(db, session_id=session_id, limit=50) if session_id else []
    if not rows and db is not None:
        rows = list_refunds(db, limit=200)
    return {r["rma_no"] for r in rows if r.get("rma_no")}
