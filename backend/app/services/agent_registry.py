# -*- coding: utf-8 -*-
"""
子Agent注册表与基类

设计原则：
1. 每个子Agent封装单一职责（FAQ回答、多轮对话、工单创建、情绪安抚等）
2. 子Agent通过数据库配置表管理，支持运行时热更新
3. 意图识别服务通过注册表路由消息到合适的子Agent
4. 主Agent协调多个子Agent协作完成复杂任务
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import json

from sqlalchemy.orm import Session


class AgentStatus(Enum):
    """子Agent状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DRAFT = "draft"


class AgentContext:
    """
    子Agent执行上下文
    """
    def __init__(self,
                 session_id: str,
                 message: str,
                 user_id: Optional[str] = None,
                 intent: Optional[str] = None,
                 intent_confidence: float = 0.0,
                 sub_intent: Optional[str] = None,
                 emotion_type: Optional[str] = None,
                 emotion_intensity: int = 1,
                 frustration_signals: List[str] = None,
                 turn_count: int = 0,
                 dialog_phase: str = "intake",
                 conversation_history: List[Dict[str, str]] = None,
                 entities: Dict[str, Any] = None,
                 user_profile: Optional[Dict[str, Any]] = None,
                 order_info: Optional[Dict[str, Any]] = None,
                 config: Dict[str, Any] = None):
        self.session_id = session_id
        self.user_id = user_id
        self.message = message
        self.intent = intent
        self.intent_confidence = intent_confidence
        self.sub_intent = sub_intent
        self.emotion_type = emotion_type
        self.emotion_intensity = emotion_intensity
        self.frustration_signals = frustration_signals or []
        self.turn_count = turn_count
        self.dialog_phase = dialog_phase
        self.conversation_history = conversation_history or []
        self.entities = entities or {}
        self.user_profile = user_profile
        self.order_info = order_info
        self.config = config or {}


class AgentResult:
    """
    子Agent执行结果
    """
    def __init__(self,
                 answer: str,
                 agent_name: str,
                 needs_transfer: bool = False,
                 transfer_reason: Optional[str] = None,
                 intent: Optional[str] = None,
                 confidence: float = 0.0,
                 sources: List[Dict] = None,
                 emotion_detected: Optional[str] = None,
                 emotion_intensity: int = 1,
                 next_action: Optional[str] = None,
                 updated_entities: Dict[str, Any] = None,
                 updated_phase: Optional[str] = None,
                 debug_info: Dict[str, Any] = None):
        self.answer = answer
        self.agent_name = agent_name
        self.needs_transfer = needs_transfer
        self.transfer_reason = transfer_reason
        self.intent = intent
        self.confidence = confidence
        self.sources = sources or []
        self.emotion_detected = emotion_detected
        self.emotion_intensity = emotion_intensity
        self.next_action = next_action
        self.updated_entities = updated_entities or {}
        self.updated_phase = updated_phase
        self.debug_info = debug_info or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "needs_transfer": self.needs_transfer,
            "transfer_reason": self.transfer_reason,
            "agent_name": self.agent_name,
            "intent": self.intent,
            "confidence": self.confidence,
            "sources": self.sources,
            "emotion_detected": self.emotion_detected,
            "emotion_intensity": self.emotion_intensity,
            "next_action": self.next_action,
            "updated_entities": self.updated_entities,
            "updated_phase": self.updated_phase,
            "debug_info": self.debug_info,
        }

    def copy(self) -> "AgentResult":
        """浅拷贝，用于流式场景下修改结果不污染原始对象"""
        import copy
        return copy.copy(self)


@dataclass
class BaseAgent(ABC):
    """
    子Agent抽象基类

    所有子Agent必须继承此类并实现 execute() 方法
    """

    agent_id: str = ""
    name: str = ""
    description: str = ""
    agent_type: str = ""  # faq / dialogue / ticket / emotion
    supported_intents: List[str] = field(default_factory=list)
    supported_emotions: List[str] = field(default_factory=list)
    supported_phases: List[str] = field(default_factory=list)
    status: AgentStatus = AgentStatus.INACTIVE
    priority: int = 50
    config_schema: Dict[str, Any] = field(default_factory=dict)

    def __init__(self, db: Optional[Session] = None, config: Optional[Dict[str, Any]] = None):
        self.db = db
        self._config = config or {}

    @abstractmethod
    def execute(self, context: AgentContext) -> AgentResult:
        """执行子Agent的核心逻辑"""
        pass

    def can_handle(self, intent: Optional[str], emotion: Optional[str] = None) -> bool:
        """判断是否可以处理该意图/情绪"""
        if intent and intent in self.supported_intents:
            return True
        if emotion and emotion in self.supported_emotions:
            return True
        return False

    def get_config(self) -> Dict[str, Any]:
        return self._config.copy()

    def update_config(self, config: Dict[str, Any]):
        self._config.update(config)


class AgentRegistry:
    """
    子Agent注册表
    """

    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}
        self._intent_index: Dict[str, List[str]] = {}
        self._emotion_index: Dict[str, List[str]] = {}

    def register(self, agent: BaseAgent):
        """注册子Agent"""
        if agent.agent_id in self._agents:
            self._unindex_agent(self._agents[agent.agent_id].agent_id)

        self._agents[agent.agent_id] = agent
        self._index_agent(agent.agent_id, agent.supported_intents, agent.supported_emotions)

    def unregister(self, agent_id: str):
        """注销子Agent"""
        if agent_id in self._agents:
            self._unindex_agent(agent_id)
            del self._agents[agent_id]

    def get(self, agent_id: str) -> Optional[BaseAgent]:
        return self._agents.get(agent_id)

    def list_all(self) -> List[BaseAgent]:
        return list(self._agents.values())

    def list_active(self) -> List[BaseAgent]:
        return [a for a in self._agents.values() if a.status == AgentStatus.ACTIVE]

    def resolve_agent(self, intent: Optional[str],
                      emotion: Optional[str] = None,
                      phase: Optional[str] = None) -> Optional[BaseAgent]:
        """
        根据意图/情绪/阶段解析最合适的子Agent
        """
        candidates = []

        # 第一优先级：意图匹配
        if intent:
            for agent_id in self._intent_index.get(intent, []):
                agent = self._agents.get(agent_id)
                if agent and agent.status == AgentStatus.ACTIVE:
                    candidates.append((agent.priority, agent, 'intent'))

        # 第二优先级：情绪匹配
        if emotion:
            for agent_id in self._emotion_index.get(emotion, []):
                agent = self._agents.get(agent_id)
                if agent and agent.status == AgentStatus.ACTIVE:
                    candidates.append((agent.priority + 10, agent, 'emotion'))

        # 第三优先级：阶段匹配
        if phase:
            for agent in self.list_active():
                if phase in agent.supported_phases:
                    candidates.append((agent.priority + 20, agent, 'phase'))

        if not candidates:
            return self._get_default_agent()

        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def _index_agent(self, agent_id: str, intents: List[str], emotions: List[str]):
        for intent in intents:
            if intent not in self._intent_index:
                self._intent_index[intent] = []
            self._intent_index[intent].append(agent_id)

        for emotion in emotions:
            if emotion not in self._emotion_index:
                self._emotion_index[emotion] = []
            self._emotion_index[emotion].append(agent_id)

    def _unindex_agent(self, agent_id: str):
        for intents in self._intent_index.values():
            if agent_id in intents:
                intents.remove(agent_id)
        for emotions in self._emotion_index.values():
            if agent_id in emotions:
                emotions.remove(agent_id)

    def _get_default_agent(self) -> Optional[BaseAgent]:
        for agent in self.list_active():
            if 'faq' in agent.agent_id.lower() or 'default' in agent.agent_id.lower():
                return agent
        active = self.list_active()
        if active:
            return min(active, key=lambda a: a.priority)
        return None


# 全局注册表单例
_registry: Optional[AgentRegistry] = None


def get_agent_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
