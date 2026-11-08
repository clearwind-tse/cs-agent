# -*- coding: utf-8 -*-
"""
子Agent配置模型

支持可配置化的子Agent注册和管理
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON
from datetime import datetime
import json

from .database import Base


def _safe_json(value, default=None):
    """兼容 JSON 列：PostgreSQL 自动反序列化为 list/dict，SQLite 仍是 str"""
    if value is None:
        return default if default is not None else []
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


class AgentSession(Base):
    """智能客服 Agent 会话表"""
    __tablename__ = "agent_sessions"

    session_id = Column(String(100), primary_key=True, nullable=False, index=True)
    user_id = Column(String(100), nullable=True, index=True)
    display_name = Column(String(200), nullable=True)
    last_message = Column(Text, nullable=True)
    message_count = Column(Integer, default=0)
    # 会话生命周期：active=进行中 / closed=已关闭并推送
    status = Column(String(20), default='active', index=True)
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "display_name": self.display_name,
            "last_message": self.last_message,
            "message_count": self.message_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentConfig(Base):
    """子Agent配置表"""
    __tablename__ = "agent_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(100), unique=True, nullable=False, index=True)  # 唯一标识
    name = Column(String(200), nullable=False)  # 显示名称
    description = Column(Text, nullable=True)  # 功能描述
    agent_type = Column(String(50), nullable=False)  # 类型：faq/dialogue/ticket/emotion
    status = Column(String(20), default="inactive")  # active/inactive/draft
    priority = Column(Integer, default=50)  # 优先级（数字越小越高）

    # 路由配置
    supported_intents = Column(JSON, nullable=True)  # 支持的意图列表
    supported_emotions = Column(JSON, nullable=True)  # 支持的情绪类型
    supported_phases = Column(JSON, nullable=True)  # 支持的对话阶段

    # Agent逻辑配置
    config_json = Column(Text, nullable=True)  # JSON格式的Agent配置
    prompt_template = Column(Text, nullable=True)  # Prompt模板

    # 绑定工具
    skill_ids = Column(JSON, nullable=True)  # 绑定的 Skill ID 列表
    mcp_server_ids = Column(JSON, nullable=True)  # 绑定的 MCP Server ID 列表

    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(100), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "agent_type": self.agent_type,
            "status": self.status,
            "priority": self.priority,
            "supported_intents": _safe_json(self.supported_intents, []),
            "supported_emotions": _safe_json(self.supported_emotions, []),
            "supported_phases": _safe_json(self.supported_phases, []),
            "config": _safe_json(self.config_json, {}) if self.config_json else {},
            "skill_ids": _safe_json(self.skill_ids, []),
            "mcp_server_ids": _safe_json(self.mcp_server_ids, []),
            "prompt_template": self.prompt_template,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class IntentRecord(Base):
    """意图识别记录表"""
    __tablename__ = "intent_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    turn_number = Column(Integer, nullable=False)
    user_message = Column(Text, nullable=False)
    intent = Column(String(50), nullable=False)
    sub_intent = Column(String(100), nullable=True)
    confidence = Column(Integer, nullable=False)  # 0-100
    emotion_type = Column(String(50), nullable=True)
    emotion_intensity = Column(Integer, nullable=True)  # 1-5
    frustration_signals = Column(JSON, nullable=True)
    routed_to_agent = Column(String(100), nullable=True)  # 路由到的Agent ID
    created_at = Column(DateTime, default=datetime.utcnow)


class EmotionRecord(Base):
    """情绪检测记录表"""
    __tablename__ = "emotion_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    turn_number = Column(Integer, nullable=False)
    user_message = Column(Text, nullable=False)
    emotion_type = Column(String(50), nullable=False)
    intensity = Column(Integer, nullable=False)  # 1-5
    frustration_signals = Column(JSON, nullable=True)
    emotion_trend = Column(String(20), nullable=True)  # improving/stable/worsening
    risk_score = Column(Integer, nullable=True)  # 0-100
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentMessage(Base):
    """Agent 对话消息历史表"""
    __tablename__ = "agent_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    turn_number = Column(Integer, nullable=False)
    role = Column(String(20), nullable=False)  # user / assistant
    content = Column(Text, nullable=False)
    intent = Column(String(50), nullable=True)
    confidence = Column(Integer, nullable=True)  # 0-100
    emotion_type = Column(String(50), nullable=True)
    emotion_intensity = Column(Integer, nullable=True)
    needs_transfer = Column(Boolean, default=False)
    ticket_no = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TransferDecision(Base):
    """转人工决策记录表"""
    __tablename__ = "transfer_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    decision_action = Column(String(20), nullable=False)  # transfer/continue
    decision_reason = Column(String(50), nullable=True)
    risk_score = Column(Integer, nullable=True)
    triggered_signals = Column(JSON, nullable=True)
    handoff_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
