# -*- coding: utf-8 -*-
"""
多轮对话实训 数据模型

AI 扮演客户、学员扮演本平台客服的多轮会话记录。
本期只负责"把对话完整落库"，评分/评测由后续独立的会话质检服务消费 transcript_json。
"""
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String

from .database import Base

try:
    from sqlalchemy.dialects.postgresql import JSONB
    HAS_JSONB = True
except ImportError:
    JSONB = JSON
    HAS_JSONB = False

# JSONB（PostgreSQL）/ JSON（SQLite）兼容
JSONType = JSONB if HAS_JSONB else JSON


class DialogueSet(Base):
    """对话实训情景集 —— 一组 N 个客户情景，学员逐条练习"""
    __tablename__ = "dialogue_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    category = Column(String(50), index=True)  # 10 类 slug
    # [{id, category, difficulty, customer_persona, customer_background,
    #   opening_line, hidden_needs, expected_points}]
    scenarios_json = Column(JSONType, nullable=False)
    scenario_count = Column(Integer, default=0)
    status = Column(String(20), default='generated', index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DialogueSession(Base):
    """一条多轮会话记录（对应情景集里的一个情景）"""
    __tablename__ = "dialogue_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    set_id = Column(Integer, nullable=False, index=True)
    scenario_id = Column(Integer, nullable=False)  # 对应 scenarios_json 里的 id
    category = Column(String(50))
    status = Column(String(20), default='in_progress', index=True)  # in_progress / finished
    transcript_json = Column(JSONType)  # [{role: 'customer'|'agent', content}]
    turn_count = Column(Integer, default=0)  # 客户轮次计数
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_dialogue_session_set', 'set_id', 'scenario_id'),
    )
