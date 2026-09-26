# -*- coding: utf-8 -*-
"""
主Agent编排服务

职责：
1. 协调多个子Agent协作完成复杂任务
2. 管理对话状态和上下文传递
3. 处理转人工决策（五信号融合，教材 Ch8）
4. 提供统一的执行接口（同步 + 流式）
"""
from typing import Optional, Dict, Any, List
import json
from sqlalchemy import text as sql_text

from app.services.agent_registry import (
    AgentRegistry, AgentContext, AgentResult, get_agent_registry
)
from app.services.intent_recognition import IntentRecognitionService, IntentResult
from app.models.agent_config import AgentConfig, IntentRecord, EmotionRecord, TransferDecision, AgentSession, AgentMessage
from app.models.database import get_session_local


class MainAgent:
    """
    主Agent：协调多个子Agent完成客服任务
    """

    # 五信号关键词（教材 Ch8）
    EXPLICIT_TRANSFER_KEYWORDS = ["人工", "客服", "转人工", "真人", "找人工", "电话"]
    SENSITIVE_KEYWORDS = ["律师", "起诉", "12315", "曝光", "欺诈", "医疗", "报警", "媒体", "纪检"]

    def __init__(self, db=None):
        self.db = db
        self.registry = get_agent_registry()
        self.intent_service = IntentRecognitionService(self.registry)
        self._conversations: Dict[str, AgentContext] = {}

    # ------------------------------------------------------------------ #
    #  公开接口
    # ------------------------------------------------------------------ #

    def process_message(self, message: str, session_id: str,
                        user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        处理用户消息，返回结构化响应（非流式）
        """
        context = self.intent_service.build_context(message, user_id)
        context.session_id = session_id
        context.user_id = user_id

        self._ensure_session(session_id, user_id)
        self._update_history(session_id, "user", message)
        self._save_user_message(session_id, context.turn_count + 1, message)

        agent = self.registry.resolve_agent(
            intent=context.intent,
            emotion=context.emotion_type,
            phase=context.dialog_phase
        )

        if agent is None:
            return self._error_response("未找到合适的子Agent")

        result = agent.execute(context)

        # 转人工决策（五信号融合）
        should_transfer, signals = self._should_transfer(context, result)
        if should_transfer:
            result.needs_transfer = True
            result.transfer_reason = self._format_transfer_reason(signals)

        self._update_conversation_state(session_id, result)
        self._save_intent_record(session_id, context)
        self._save_emotion_record(session_id, context)
        self._save_transfer_decision(session_id, signals, should_transfer, context.emotion_intensity)

        self._update_history(session_id, "agent", result.answer)
        self._touch_session(session_id, message, result.answer)
        self._save_assistant_message(
            session_id=session_id,
            turn_number=context.turn_count + 1,
            content=result.answer,
            intent=result.intent or context.intent,
            confidence=result.confidence or context.intent_confidence,
            emotion=result.emotion_detected or context.emotion_type,
            emotion_intensity=result.emotion_intensity or context.emotion_intensity,
            needs_transfer=result.needs_transfer or False,
            ticket_no=result.updated_entities.get("ticket_no") if result.updated_entities else None,
        )

        return {
            "answer": result.answer,
            "intent": result.intent or context.intent,
            "confidence": result.confidence,
            "emotion": result.emotion_detected or context.emotion_type,
            "emotion_intensity": result.emotion_intensity or context.emotion_intensity,
            "agent_name": result.agent_name,
            "next_action": result.next_action,
            "needs_transfer": result.needs_transfer,
            "transfer_reason": result.transfer_reason,
            "sources": result.sources,
            "updated_entities": result.updated_entities,
            "updated_phase": result.updated_phase,
            "signals": signals,
        }

    def process_message_stream(self, message: str, session_id: str,
                                user_id: Optional[str] = None):
        """
        流式处理用户消息（用于 SSE 推送）

        与 process_message 的区别：
        - 逐 token 输出（子 Agent 有 execute_stream 时）
        - 每条 metadata/token/answer 均对应一条 SSE data 事件
        - 最终同步落库（IntentRecord / EmotionRecord / TransferDecision）
        """
        context = self.intent_service.build_context(message, user_id)
        context.session_id = session_id

        self._ensure_session(session_id, user_id)

        # ── 元数据事件 ──────────────────────────────────────────────────
        yield json.dumps({
            "type": "metadata",
            "intent": context.intent,
            "confidence": round(context.intent_confidence, 4),
            "emotion": context.emotion_type,
            "emotion_intensity": context.emotion_intensity,
            "agent": "routing"
        }, ensure_ascii=False) + "\n\n"

        # ── 路由到子 Agent ─────────────────────────────────────────────
        agent = self.registry.resolve_agent(
            intent=context.intent,
            emotion=context.emotion_type,
            phase=context.dialog_phase
        )

        if agent is None:
            yield json.dumps({"type": "error", "message": "未找到合适的子Agent"}) + "\n\n"
            return

        should_transfer = False
        signals: List[str] = []

        # ── 初始化 result（stream 分支需先赋值，避免未定义引用）────────────
        result = AgentResult(
            answer="",
            agent_name=getattr(agent, "name", "unknown"),
        )
        full_answer = ""

        # ── 执行子 Agent（优先流式） ────────────────────────────────────
        try:
            if hasattr(agent, "execute_stream") and callable(getattr(agent, "execute_stream")):
                async_gen = agent.execute_stream(context)
                # 同步驱动异步生成器（send None 逐次推进）
                _agen = async_gen
                _sent = _agen.send(None)  # 启动
                while True:
                    try:
                        chunk = _sent
                        if isinstance(chunk, dict):
                            ev_type = chunk.get("type", "")
                            if ev_type == "token":
                                tok = chunk.get("content", "")
                                full_answer += tok
                                yield json.dumps({"type": "token", "content": tok}, ensure_ascii=False) + "\n\n"
                            elif ev_type == "answer":
                                full_answer = chunk.get("content", full_answer)
                                result.answer = full_answer
                                yield json.dumps({"type": "answer", "content": full_answer, "agent": result.agent_name}, ensure_ascii=False) + "\n\n"
                            elif ev_type == "metadata":
                                yield json.dumps(chunk, ensure_ascii=False) + "\n\n"
                            elif ev_type == "error":
                                yield json.dumps({"type": "error", "message": chunk.get("message", str(chunk))}, ensure_ascii=False) + "\n\n"
                                return
                        _sent = _agen.send(None)
                    except StopIteration:
                        break
                if not full_answer:
                    full_answer = "（子Agent流式输出为空）"
                    result.answer = full_answer
            else:
                result = agent.execute(context).copy()
                full_answer = result.answer or ""
                yield json.dumps({"type": "answer", "content": full_answer, "agent": result.agent_name}, ensure_ascii=False) + "\n\n"

            # ── 转人工决策 ──────────────────────────────────────────────
            should_transfer, signals = self._should_transfer(context, result)
            if should_transfer:
                result = result.copy()
                result.needs_transfer = True
                result.transfer_reason = self._format_transfer_reason(signals)

            self._update_conversation_state(session_id, result)
            self._save_intent_record(session_id, context)
            self._save_emotion_record(session_id, context)
            self._save_transfer_decision(session_id, signals, should_transfer, context.emotion_intensity)
            self._update_history(session_id, "agent", result.answer)
            self._touch_session(session_id, message, result.answer)
            self._save_assistant_message(
                session_id=session_id,
                turn_number=context.turn_count + 1,
                content=result.answer,
                intent=result.intent or context.intent,
                confidence=result.confidence or context.intent_confidence,
                emotion=result.emotion_detected or context.emotion_type,
                emotion_intensity=result.emotion_intensity or context.emotion_intensity,
                needs_transfer=result.needs_transfer or False,
                ticket_no=result.updated_entities.get("ticket_no") if result.updated_entities else None,
            )

            yield json.dumps({
                "type": "done",
                "needs_transfer": result.needs_transfer or False,
                "signals": signals,
                "agent": result.agent_name,
                "ticket_no": result.updated_entities.get("ticket_no") if result.updated_entities else None,
            }, ensure_ascii=False) + "\n\n"

        except Exception as exc:
            import traceback
            yield json.dumps({"type": "error", "message": f"子Agent执行异常: {exc}"}, ensure_ascii=False) + "\n\n"
            print(f"[MainAgent] stream error: {exc}\n{traceback.format_exc()}")

    def _should_transfer(self, context: "AgentContext", result: "AgentResult"):
        """五信号融合转人工决策（教材 Ch8）

        信号来源：
          1. explicit_request   用户显式要求转人工
          2. low_confidence     意图置信度低于阈值
          3. emotion_escalation 情绪连续上升且 ≥4
          4. sensitive_topic    涉及敏感主题（法律/媒体/12315 等）
          5. repeated_failure   同一问题连续多轮未解决

        决策规则：
          - 任一强信号（explicit_request / emotion_escalation / sensitive_topic）→ 转人工
          - 至少两个弱信号 → 转人工
        """
        signals: List[str] = []
        msg = context.message or ""

        # 信号 1：显式请求
        if any(kw in msg for kw in self.EXPLICIT_TRANSFER_KEYWORDS):
            signals.append("explicit_request")

        # 信号 2：置信度不足（高风险意图阈值更严格）
        high_risk_intents = {"refund_return", "complaint", "logistics"}
        threshold = 0.8 if context.intent in high_risk_intents else 0.4
        if context.intent_confidence < threshold:
            signals.append("low_confidence")

        # 信号 3：情绪恶化（查历史）
        if self._is_escalating_emotion(context.session_id, context.emotion_intensity):
            signals.append("emotion_escalation")

        # 信号 4：敏感主题
        if any(kw in msg for kw in self.SENSITIVE_KEYWORDS):
            signals.append("sensitive_topic")

        # 信号 5：重复失败
        if self._has_repeated_failure(context.session_id, context.intent):
            signals.append("repeated_failure")

        strong = {"explicit_request", "emotion_escalation", "sensitive_topic"}
        if set(signals) & strong or len(signals) >= 2:
            return True, signals
        return False, signals

    def _format_transfer_reason(self, signals: List[str]) -> str:
        signal_label = {
            "explicit_request": "用户明确要求人工",
            "low_confidence": "意图置信度不足",
            "emotion_escalation": "情绪持续恶化",
            "sensitive_topic": "涉及敏感主题",
            "repeated_failure": "同一问题多次未解决",
        }
        return "；".join(signal_label.get(s, s) for s in signals)

    def _is_escalating_emotion(self, session_id: str, current_intensity: int) -> bool:
        """情绪是否连续上升且达到 ≥4"""
        if not self.db or current_intensity < 4:
            return False
        from sqlalchemy import text
        rows = self.db.execute(text(
            "SELECT intensity FROM emotion_records WHERE session_id=:sid "
            "ORDER BY turn_number DESC LIMIT 3"
        ), {"sid": session_id}).fetchall()
        if len(rows) < 2:
            return False
        intensities = [r[0] for r in rows]
        # 最近两轮递增，且当前（第一根）≥4
        return intensities[0] > intensities[1] and intensities[0] >= 4

    def _has_repeated_failure(self, session_id: str, intent: str) -> bool:
        """同一意图连续 ≥3 轮低置信度（未解决）"""
        if not self.db:
            return False
        from sqlalchemy import text
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM intent_records "
            "WHERE session_id=:sid AND intent=:intent AND confidence < 50"
        ), {"sid": session_id, "intent": intent}).scalar()
        return int(count) >= 3

    # ------------------------------------------------------------------ #
    #  辅助方法
    # ------------------------------------------------------------------ #

    def _error_response(self, reason: str) -> Dict[str, Any]:
        return {
            "answer": "抱歉，我暂时无法理解您的问题。请稍后再试或联系人工客服。",
            "intent": "unknown",
            "confidence": 0.0,
            "needs_transfer": True,
            "transfer_reason": reason,
            "signals": [],
        }

    def _update_conversation_state(self, session_id: str, result: AgentResult):
        if session_id not in self._conversations:
            return
        context = self._conversations[session_id]
        context.turn_count += 1
        if result.updated_entities:
            context.entities.update(result.updated_entities)
        if result.updated_phase:
            context.dialog_phase = result.updated_phase

    def _ensure_session(self, session_id: str, user_id: Optional[str] = None):
        """确保 agent_sessions 存在，缺失则初始化；同时更新 display_name / updated_at"""
        if not self.db or not session_id:
            return
        try:
            existing = self.db.execute(
                sql_text("SELECT session_id FROM agent_sessions WHERE session_id = :sid"),
                {"sid": session_id},
            ).fetchone()
            if existing:
                self.db.execute(
                    sql_text("UPDATE agent_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = :sid"),
                    {"sid": session_id},
                )
            else:
                self.db.execute(
                    sql_text("""
                        INSERT INTO agent_sessions (session_id, user_id, display_name, message_count, created_at)
                        VALUES (:sid, :uid, :name, 0, CURRENT_TIMESTAMP)
                    """),
                    {"sid": session_id, "uid": user_id, "name": f"Agent · {user_id or 'anonymous'}"},
                )
            self.db.commit()
        except Exception as e:
            print(f"[MainAgent] ensure_session failed: {e}")
            if self.db:
                self.db.rollback()

    def _touch_session(self, session_id: str, user_message: str, agent_answer: str):
        """更新会话 last_message / message_count"""
        if not self.db or not session_id:
            return
        try:
            self.db.execute(
                sql_text("""
                    UPDATE agent_sessions
                    SET last_message = :msg,
                        message_count = message_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE session_id = :sid
                """),
                {"sid": session_id, "msg": (agent_answer or user_message)[:200]},
            )
            self.db.commit()
        except Exception as e:
            print(f"[MainAgent] touch_session failed: {e}")
            if self.db:
                self.db.rollback()

    def _save_user_message(self, session_id: str, turn_number: int, content: str):
        """保存用户消息到历史"""
        if not self.db or not session_id:
            return
        try:
            record = AgentMessage(
                session_id=session_id,
                turn_number=turn_number,
                role="user",
                content=content,
            )
            self.db.add(record)
            self.db.commit()
        except Exception as e:
            print(f"[MainAgent] save_user_message failed: {e}")
            if self.db:
                self.db.rollback()

    def _save_assistant_message(self, session_id: str, turn_number: int, content: str,
                                 intent: Optional[str], confidence: float,
                                 emotion: Optional[str], emotion_intensity: int,
                                 needs_transfer: bool, ticket_no: Optional[str]):
        """保存助手消息到历史"""
        if not self.db or not session_id:
            return
        try:
            record = AgentMessage(
                session_id=session_id,
                turn_number=turn_number,
                role="assistant",
                content=content or "",
                intent=intent,
                confidence=int(confidence * 100) if confidence else None,
                emotion_type=emotion,
                emotion_intensity=emotion_intensity,
                needs_transfer=needs_transfer,
                ticket_no=ticket_no,
            )
            self.db.add(record)
            self.db.commit()
        except Exception as e:
            print(f"[MainAgent] save_assistant_message failed: {e}")
            if self.db:
                self.db.rollback()

    def _save_intent_record(self, session_id: str, context: AgentContext):
        if not self.db:
            return
        try:
            record = IntentRecord(
                session_id=session_id,
                turn_number=context.turn_count,
                user_message=context.message,
                intent=context.intent or "unknown",
                sub_intent=context.sub_intent,
                confidence=int(context.intent_confidence * 100),
                emotion_type=context.emotion_type,
                emotion_intensity=context.emotion_intensity,
                frustration_signals=json.dumps(context.frustration_signals) if context.frustration_signals else None,
            )
            self.db.add(record)
            self.db.commit()
        except Exception as e:
            print(f"[MainAgent] save_intent_record failed: {e}")
            if self.db:
                self.db.rollback()

    def _save_emotion_record(self, session_id: str, context: AgentContext):
        if not self.db:
            return
        try:
            record = EmotionRecord(
                session_id=session_id,
                turn_number=context.turn_count,
                user_message=context.message,
                emotion_type=context.emotion_type or "neutral",
                intensity=context.emotion_intensity,
                frustration_signals=json.dumps(context.frustration_signals) if context.frustration_signals else None,
            )
            self.db.add(record)
            self.db.commit()
        except Exception as e:
            print(f"[MainAgent] save_emotion_record failed: {e}")
            if self.db:
                self.db.rollback()

    def _save_transfer_decision(self, session_id: str, signals: List[str], needs_transfer: bool,
                                 emotion_intensity: int = 1):
        if not self.db:
            return
        try:
            record = TransferDecision(
                session_id=session_id,
                decision_action="transfer" if needs_transfer else "continue",
                decision_reason=self._format_transfer_reason(signals) if needs_transfer else None,
                triggered_signals=json.dumps(signals),
                risk_score=min(100, emotion_intensity * 20),
            )
            self.db.add(record)
            self.db.commit()
        except Exception as e:
            print(f"[MainAgent] save_transfer_decision failed: {e}")
            if self.db:
                self.db.rollback()

    def _update_history(self, session_id: str, role: str, content: str):
        if session_id not in self._conversations:
            self._conversations[session_id] = AgentContext(
                session_id=session_id,
                message=content,
            )
        context = self._conversations[session_id]
        context.conversation_history.append({
            "role": role,
            "content": content,
            "turn": context.turn_count,
        })
        # 滑动窗口：只保留最近 10 轮
        if len(context.conversation_history) > 10:
            context.conversation_history = context.conversation_history[-10:]

    def get_conversation_state(self, session_id: str) -> Optional[AgentContext]:
        return self._conversations.get(session_id)

    def reset_conversation(self, session_id: str):
        if session_id in self._conversations:
            del self._conversations[session_id]


# 全局主Agent实例
_main_agent: Optional[MainAgent] = None


def get_main_agent(db=None) -> MainAgent:
    global _main_agent
    if _main_agent is None:
        _main_agent = MainAgent(db)
    return _main_agent
