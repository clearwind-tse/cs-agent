# -*- coding: utf-8 -*-
"""
工单处理子Agent（对应教材 Ch7）

职责：
- 从对话上下文提取工单字段
- 调用工具获取订单/物流信息
- 自动分类（LLM 驱动，目标准确率 ≥80%）
- 创建工单并返回工单编号
- 支持 SLA 优先级匹配
"""
from typing import Optional, Dict, Any
import json
import uuid
from datetime import datetime

from app.services.agent_registry import BaseAgent, AgentContext, AgentResult, AgentStatus
from app.services.tools.registry import get_tool_registry


class TicketAgent(BaseAgent):
    """工单处理子Agent"""

    agent_id = "ticket_agent"
    name = "工单处理Agent"
    description = "自动创建工单、分类路由、跟进处理状态"
    agent_type = "ticket"
    supported_intents = ["refund_return", "complaint", "logistics"]
    supported_emotions: list = []
    supported_phases = ["gathering", "diagnosis", "solution", "action"]
    status = AgentStatus.ACTIVE
    priority = 15  # 高于 FAQ(10)，低于 Complaint(5)
    tools = ["query_order", "create_ticket", "check_logistics"]

    def execute(self, context: AgentContext) -> AgentResult:
        # 1. 调用工具获取订单信息（如有 order_id）
        order_info = self._call_tool("query_order", context)

        # 2. 提取工单字段
        fields = self._extract_ticket_fields(context, order_info)

        # 3. LLM 自动分类（temperature=0.1，参考教材 Ch7）
        category = self._classify_ticket(context, fields)

        # 4. 匹配 SLA 优先级
        priority = self._match_sla_priority(category, context.emotion_intensity)

        # 5. 创建工单并写入 DB
        ticket = self._create_ticket(context, category, priority, fields)

        # 6. 生成回复
        answer = self._generate_ticket_response(ticket, context)

        return AgentResult(
            answer=answer,
            agent_name=self.name,
            intent=context.intent,
            confidence=context.intent_confidence,
            next_action="ticket_created",
            updated_phase="action",
            updated_entities={**context.entities, "ticket_no": ticket.ticket_no},
            debug_info={"category": category, "priority": priority, "ticket_id": ticket.id}
        )

    def _call_tool(self, tool_name: str, context: AgentContext) -> dict:
        """调用工具（统一接口，失败时降级返回空）"""
        tool = get_tool_registry().get(tool_name)
        if not tool:
            return {}
        params = self._prepare_tool_params(tool_name, context)
        try:
            result = tool.execute(params, context)
            return result.get("data", {})
        except Exception as e:
            print(f"[TicketAgent] 工具 {tool_name} 调用失败: {e}")
            return {}

    def _prepare_tool_params(self, tool_name: str, context: AgentContext) -> dict:
        """根据工具名准备参数"""
        if tool_name == "query_order":
            return {"order_id": context.entities.get("order_id", "")}
        elif tool_name == "check_logistics":
            order_info = context.order_info or {}
            return {
                "order_id": context.entities.get("order_id", ""),
                "logistics_no": order_info.get("logistics_no", ""),
            }
        return {}

    def _extract_ticket_fields(self, context: AgentContext, order_info: dict = None) -> dict:
        """从对话上下文提取工单字段"""
        fields = {"user_message": context.message}
        if order_info:
            fields["order_id"] = order_info.get("order_id")
            fields["product_name"] = order_info.get("product_name")
            fields["logistics_status"] = order_info.get("status")
        # 补充用户提到的实体
        fields.update(context.entities)
        return fields

    def _classify_ticket(self, context: AgentContext, fields: dict) -> str:
        """
        自动分类（简化版，教材 Ch7 要求 LLM 驱动）
        实际项目应调用 LLM API，此处用关键词规则兜底保证可用性
        """
        message = (context.message or "").lower()
        # 基于意图 + 消息内容的规则分类（教材 Ch7 对比基线：关键词 60-70% vs LLM 92-95%）
        if context.intent == "refund_return" or any(kw in message for kw in ["退款", "退货", "退钱"]):
            return "退款申请"
        if context.intent == "logistics" or any(kw in message for kw in ["物流", "快递", "发货", "配送", "没收到"]):
            return "物流异常"
        if context.intent == "complaint" or any(kw in message for kw in ["投诉", "差评", "举报"]):
            return "投诉建议"
        if any(kw in message for kw in ["质量", "破损", "瑕疵", "坏了", "不好用"]):
            return "商品问题"
        # 默认按意图映射
        intent_category_map = {
            "refund_return": "退款申请",
            "logistics": "物流异常",
            "complaint": "投诉建议",
            "order_status": "订单查询",
        }
        return intent_category_map.get(context.intent, "其他")

    def _match_sla_priority(self, category: str, emotion_intensity: int) -> int:
        """
        SLA 优先级匹配（教材 Ch7）
        基础优先级 + 情绪加成（情绪越高优先级越高，上限 5）
        """
        base_priority = {
            "物流异常": 3,
            "退款申请": 4,
            "商品问题": 2,
            "投诉建议": 5,
            "订单查询": 1,
        }.get(category, 2)
        # 情绪强度 ≥3 时提高一级（上限 5）
        emotion_bonus = max(0, emotion_intensity - 2)
        return min(5, base_priority + emotion_bonus)

    def _create_ticket(self, context: AgentContext, category: str, priority: int, fields: dict):
        """创建工单并写入 DB"""
        from app.models.ticket import Ticket
        ticket_no = f"TK-{context.session_id[:8].upper()}-{uuid.uuid4().hex[:6].upper()}"
        ticket = Ticket(
            ticket_no=ticket_no,
            session_id=context.session_id,
            intent=context.intent,
            category=category,
            priority=priority,
            source="agent",
            summary=(context.message or "")[:300],
            extracted_fields=fields,
            created_at=datetime.utcnow(),
        )
        if self.db:
            self.db.add(ticket)
            self.db.commit()
            self.db.refresh(ticket)
        return ticket

    def _generate_ticket_response(self, ticket, context: AgentContext) -> str:
        """生成工单创建成功回复"""
        return (
            f"已为您创建工单，工单编号：**{ticket.ticket_no}**\n\n"
            f"问题分类：{ticket.category}（优先级 {ticket.priority}/5）\n"
            f"我们将在 24 小时内处理并回复您。如有紧急问题，可点击「转人工」即时联系专员。"
        )
