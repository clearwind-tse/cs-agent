# -*- coding: utf-8 -*-
"""
多轮对话子Agent

职责：
- 管理退货退款等复杂场景的多轮交互
- 维护对话状态
- 收集必要信息
- 执行业务流程
"""
from typing import Optional, Dict, Any

from app.services.agent_registry import BaseAgent, AgentContext, AgentResult, AgentStatus


class DialogueAgent(BaseAgent):
    """多轮对话子Agent"""

    agent_id = "dialogue_agent"
    name = "多轮对话Agent"
    description = "管理复杂场景的多轮对话和状态追踪"
    agent_type = "dialogue"
    supported_intents = ["refund_return"]
    supported_emotions: list = []
    supported_phases = ["gathering", "diagnosis", "solution", "action"]
    status = AgentStatus.ACTIVE
    priority = 20

    def execute(self, context: AgentContext) -> AgentResult:
        """执行多轮对话逻辑"""
        # 检查是否需要收集更多信息
        missing_entities = self._check_missing_entities(context)

        if missing_entities:
            # 需要追问用户
            answer = self._generate_followup_question(missing_entities, context)
            return AgentResult(
                answer=answer,
                agent_name=self.name,
                intent=context.intent,
                confidence=context.intent_confidence,
                next_action="wait_for_user",
                updated_phase="gathering",
                debug_info={"missing_entities": missing_entities}
            )

        # 实体齐全，执行退款流程
        answer = self._generate_refund_response(context)
        return AgentResult(
            answer=answer,
            agent_name=self.name,
            intent=context.intent,
            confidence=context.intent_confidence,
            next_action="action",
            updated_phase="action",
            updated_entities=context.entities
        )

    def _check_missing_entities(self, context: AgentContext) -> list:
        """检查缺失的实体"""
        required = ["order_id"]
        if context.intent == "refund_return":
            required.extend(["product_name", "issue_desc"])

        return [e for e in required if not context.entities.get(e)]

    def _generate_followup_question(self, missing: list, context: AgentContext) -> str:
        """生成追问问题"""
        question_map = {
            "order_id": "请告诉我您的订单号，例如：GM20250803-1287",
            "product_name": "请问是哪款商品需要退货？",
            "issue_desc": "请问商品有什么问题？（如：质量问题、尺寸不符、不喜欢等）"
        }

        questions = [question_map.get(e, f"请提供{e}") for e in missing]
        return f"我需要一些信息才能帮您处理退款：\n\n" + "\n".join(questions)

    def _generate_refund_response(self, context: AgentContext) -> str:
        """生成退款响应"""
        order_id = context.entities.get("order_id", "未知订单")
        return f"好的，我已收到您的退款申请。订单号：{order_id}\n\n" \
               f"请稍等，我正在为您查询退款政策并准备申请..."
