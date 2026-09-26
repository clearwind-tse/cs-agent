# -*- coding: utf-8 -*-
"""
统一订单仓库（进程内 Mock）

为什么要单独抽出这一层（对应教材 Ch5.2.3「动态上下文注入」）：
- 工具调用是「LLM 决定之后」才发生的行为；
- 而 DST 的动态注入必须由**系统在 LLM 之外主动执行**——一旦拿到订单号，
  就要立刻查订单详情并写入状态槽位，让后续每一轮 prompt 都带着它。
两者必须读同一份订单数据，否则会出现「Agent 说 A、注入说 B」的自相矛盾。

真实项目：替换为订单中心 / OMS 接口即可，函数签名保持不变。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 数据集（与 workspace/mcp_servers/order_aftersales_mcp.py 保持镜像）
# ---------------------------------------------------------------------------

_ORDERS: Dict[str, Dict[str, Any]] = {
    "GM20250803-1287": {
        "order_id": "GM20250803-1287",
        "product_name": "小蚕红包券 10元",
        "amount": 10.00,
        "status": "已签收",
        "pay_time": "2025-08-03 14:30:00",
        "logistics_company": "中通快递",
        "logistics_no": "ZTO1234567890",
        "receiver": "深圳市南山区**小区 138****8888",
        "customer_id": "default",
        "is_virtual": True,
        "activated": True,          # 红包券已核销
        "days_since_purchase": 88,
    },
    "GM20250901-0042": {
        "order_id": "GM20250901-0042",
        "product_name": "霸王餐体验券",
        "amount": 0.00,
        "status": "配送中",
        "pay_time": "2025-09-01 09:15:00",
        "logistics_company": "顺丰速运",
        "logistics_no": "SF9876543210",
        "receiver": "杭州市西湖区**路 139****6666",
        "customer_id": "default",
        "is_virtual": True,
        "activated": False,         # 未到店核销
        "days_since_purchase": 59,
    },
    "GM20251010-5521": {
        "order_id": "GM20251010-5521",
        "product_name": "智能体会员年卡",
        "amount": 199.00,
        "status": "已签收",
        "pay_time": "2025-10-10 20:05:00",
        "logistics_company": "京东物流",
        "logistics_no": "JD0099887766",
        "receiver": "上海市浦东新区**路 137****2222",
        "customer_id": "default",
        "is_virtual": True,
        "activated": False,         # 未激活
        "days_since_purchase": 20,
    },
}


# ---------------------------------------------------------------------------
# 查询接口
# ---------------------------------------------------------------------------

def get_order(order_id: str) -> Optional[Dict[str, Any]]:
    """按订单号查订单，未找到返回 None"""
    if not order_id:
        return None
    return _ORDERS.get(order_id.strip().upper()) or _ORDERS.get(order_id.strip())


def list_recent_orders(customer_key: Optional[str] = None, limit: int = 3) -> List[Dict[str, Any]]:
    """
    列出客户名下最近订单——这是「客户忘了订单号」的兜底路径。

    教材 Ch5.3 的核心体验原则：客户提供不了标识时，系统应该主动"查得到"，
    而不是把同一个问题重复问三遍。真实项目按 user_id / 手机号 / open_id 查询。
    """
    items = list(_ORDERS.values())
    if customer_key:
        hit = [o for o in items if o.get("customer_id") == customer_key]
        if hit:
            items = hit
    items.sort(key=lambda o: o.get("pay_time", ""), reverse=True)
    return items[: max(1, limit)]


def search_orders_by_product(keyword: str) -> List[Dict[str, Any]]:
    """按商品名模糊匹配（客户只记得"我买的那个红包券"时用）"""
    kw = (keyword or "").strip()
    if not kw:
        return []
    return [o for o in _ORDERS.values() if kw in o.get("product_name", "")]


def evaluate_refund(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    退款资格判定：返回 {eligible, reason}

    规则（业务方口径示例）：
    - 虚拟券/卡：未核销、未激活 → 可退；已核销 → 不支持无理由退（可转客服介入）
    - 实物：签收 7 天内可退
    """
    if not order:
        return {"eligible": None, "reason": "订单不存在"}

    if order.get("is_virtual"):
        if order.get("activated"):
            return {
                "eligible": False,
                "reason": "虚拟权益已核销/已激活，按规则不支持七天无理由退款，可申请客服人工介入",
            }
        return {"eligible": True, "reason": "虚拟权益未核销，符合退款条件"}

    days = order.get("days_since_purchase") or 0
    if days <= 7:
        return {"eligible": True, "reason": f"签收 {days} 天，符合七天无理由退款"}
    return {"eligible": False, "reason": f"签收已 {days} 天，超出七天无理由期限"}


def brief(order: Dict[str, Any], index: Optional[int] = None) -> str:
    """订单的一句话摘要（供 prompt / 候选列表使用）"""
    prefix = f"{index}. " if index else ""
    return (
        f"{prefix}{order.get('order_id')}｜{order.get('product_name')}"
        f"｜¥{float(order.get('amount') or 0):.2f}｜{order.get('status')}"
        f"｜下单 {str(order.get('pay_time') or '')[:10]}"
    )


def snapshot(order: Dict[str, Any]) -> Dict[str, Any]:
    """转成可 JSON 序列化的订单快照（写入 DST.order_snapshot）"""
    if not order:
        return {}
    keys = (
        "order_id", "product_name", "amount", "status", "pay_time",
        "logistics_company", "logistics_no", "receiver", "is_virtual", "activated",
    )
    return {k: order.get(k) for k in keys}
