# -*- coding: utf-8 -*-
"""
投诉处理子Agent

职责：
- 处理客户投诉
- 情绪安抚
- 升级转人工
"""
from typing import Optional

from app.services.agent_registry import BaseAgent, AgentContext, AgentResult, AgentStatus


class ComplaintAgent(BaseAgent):
    """投诉处理子Agent"""

    agent_id = "complaint_agent"
    name = "投诉处理Agent"
    description = "处理客户投诉和负面情绪，必要时转人工"
    agent_type = "complaint"
    supported_intents = ["complaint"]
    supported_emotions = ["anger", "anxiety", "disappointment"]
    supported_phases: list = ["gathering", "diagnosis", "solution"]
    status = AgentStatus.ACTIVE
    priority = 5  # 高优先级
    tools: list = []  # 投诉 Agent 不需要调用外部工具

    def execute(self, context: AgentContext) -> AgentResult:
        """执行投诉处理逻辑"""
        # 检查是否需要立即转人工
        if self._should_transfer_immediately(context):
            return AgentResult(
                answer=self._generate_escalation_response(context),
                agent_name=self.name,
                intent=context.intent,
                confidence=context.intent_confidence,
                needs_transfer=True,
                transfer_reason=f"情绪等级{context.emotion_intensity}，需立即升级",
                next_action="transfer"
            )

        # 尝试安抚情绪
        answer = self._generate_empathy_response(context)
        return AgentResult(
            answer=answer,
            agent_name=self.name,
            intent=context.intent,
            confidence=context.intent_confidence,
            emotion_detected=context.emotion_type,
            emotion_intensity=context.emotion_intensity,
            next_action="continue"
        )

    def _should_transfer_immediately(self, context: AgentContext) -> bool:
        """判断是否需要立即转人工"""
        # 情绪强度≥4且包含投诉关键词
        if context.emotion_intensity >= 4:
            return True
        # 包含升级威胁词
        threat_keywords = ["12315", "律师", "媒体", "曝光", "起诉"]
        return any(kw in context.message for kw in threat_keywords)

    def _generate_empathy_response(self, context: AgentContext) -> str:
        """生成共情回复"""
        emotion = context.emotion_type or "负面情绪"
        intensity = context.emotion_intensity

        if intensity >= 4:
            return "我理解您现在非常生气/着急，这个问题我会立即为您处理。" \
                   "让我先记录下来，马上为您升级处理。"
        elif intensity >= 3:
            return "非常抱歉给您带来了不好的体验。" \
                   "我来帮您解决这个问题，请问您能告诉我具体的情况吗？"
        else:
            return "感谢您的反馈。请问具体是什么问题呢？" \
                   "我会尽力帮您解决。"

    def _generate_escalation_response(self, context: AgentContext) -> str:
        """生成升级转人工回复"""
        return "您的情况我已经记录下来了。" \
               "由于您的问题比较复杂，我将立即为您转接资深客服专员处理。" \
               "请稍等，马上为您接通。"
