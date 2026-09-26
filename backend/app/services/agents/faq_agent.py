# -*- coding: utf-8 -*-
"""
FAQ回答子Agent

职责：
- 基于RAG知识库回答常见问题
- 提供准确、有引用的答案
- 支持流式输出
"""
from typing import Optional
import json

from app.services.agent_registry import BaseAgent, AgentContext, AgentResult, AgentStatus
from app.services.rag import RAGService


class FAQAgent(BaseAgent):
    """FAQ回答子Agent"""

    agent_id = "faq_agent"
    name = "FAQ回答Agent"
    description = "基于RAG知识库回答常见问题"
    agent_type = "faq"
    supported_intents = ["order_status", "logistics", "product_inquiry", "general_faq"]
    supported_emotions: list = []
    supported_phases = ["intake", "gathering", "diagnosis", "solution", "action", "closing"]
    status = AgentStatus.ACTIVE
    priority = 10

    def execute(self, context: AgentContext) -> AgentResult:
        """执行FAQ回答逻辑"""
        rag_service = RAGService(self.db)

        # 构建检索查询
        retrieve_query = context.message
        if context.sub_intent:
            retrieve_query = f"{context.message} {context.sub_intent}"

        # 调用RAG服务
        result = rag_service.answer(
            question=retrieve_query,
            session_id=context.session_id,
            top_k=3
        )

        # 构建结果
        return AgentResult(
            answer=result["answer"],
            agent_name=self.name,
            intent=context.intent,
            confidence=context.intent_confidence,
            sources=result.get("sources") or [],
            emotion_detected=context.emotion_type,
            emotion_intensity=context.emotion_intensity,
            next_action="continue",
            updated_phase="solution"
        )

    def execute_stream(self, context: AgentContext):
        """
        流式执行（用于SSE推送）

        直接透传 RAGService.answer_stream() 产出的原始 SSE 事件。
        这些事件已经是合法的 SSE 数据行（含 "data: " 前缀），
        由 MainAgent 的流式处理器统一解析为 {type: token/content/sources/error}，
        前端通过 useSSE hook 的 onToken / onDone 统一消费。
        """
        rag_service = RAGService(self.db)
        retrieve_query = context.message

        yield from rag_service.answer_stream(
            question=retrieve_query,
            session_id=context.session_id,
            top_k=3,
        )

        # 补充检索来源元数据（前端可在 onDone 后展示来源卡片）
        articles, _ = rag_service._retrieve(retrieve_query, context.session_id, top_k=3)
        if articles:
            sources = rag_service._format_sources(articles, [])
            yield "data: " + json.dumps({"type": "sources", "sources": sources}, ensure_ascii=False) + "\n\n"
