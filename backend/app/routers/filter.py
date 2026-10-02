# -*- coding: utf-8 -*-
"""
数据过滤配置 API
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DBSession
from typing import List, Optional
from pydantic import BaseModel

from app.models.database import get_db
from app.models.chat import RawChat, Session
from app.services.filter import get_data_filter, DataFilter, ContentCategory

router = APIRouter(prefix="/api/filter", tags=["filter"])


# ==================== 请求/响应模型 ====================

class FilterConfig(BaseModel):
    """过滤配置"""
    blacklist_sessions: List[str] = []
    whitelist_sessions: List[str] = []
    spam_keywords: List[str] = []


class FilterTestRequest(BaseModel):
    """过滤测试请求"""
    content: str
    msg_type: int = 1


class FilterTestResponse(BaseModel):
    """过滤测试响应"""
    category: str
    should_include: bool
    desensitized: str


class SessionFilterStats(BaseModel):
    """会话过滤统计"""
    session_id: str
    display_name: Optional[str]
    total_messages: int
    valuable: int
    chitchat: int
    sensitive: int
    spam: int
    system: int
    media: int
    short: int
    valuable_ratio: float


# ==================== API 端点 ====================

@router.get("/config")
def get_filter_config():
    """获取当前过滤配置"""
    filter = get_data_filter()
    return {
        "blacklist_sessions": filter.BLACKLIST_SESSIONS,
        "whitelist_sessions": filter.WHITELIST_SESSIONS,
        "spam_keywords": filter.SPAM_KEYWORDS,
        "sensitive_patterns": list(filter.SENSITIVE_PATTERNS.keys())
    }


@router.post("/config")
def update_filter_config(config: FilterConfig):
    """更新过滤配置"""
    filter = get_data_filter()
    
    if config.blacklist_sessions:
        filter.BLACKLIST_SESSIONS = config.blacklist_sessions
    if config.whitelist_sessions:
        filter.WHITELIST_SESSIONS = config.whitelist_sessions
    if config.spam_keywords:
        filter.SPAM_KEYWORDS.extend(config.spam_keywords)
    
    return {"message": "Config updated", "config": get_filter_config()}


@router.post("/test", response_model=FilterTestResponse)
def test_filter(request: FilterTestRequest):
    """测试过滤效果"""
    filter = get_data_filter()
    
    should_include, category = filter.should_include(request.content, request.msg_type)
    desensitized = filter.desensitize(request.content)
    
    return FilterTestResponse(
        category=category.value,
        should_include=should_include,
        desensitized=desensitized
    )


@router.post("/blacklist/add")
def add_to_blacklist(session_ids: List[str]):
    """添加会话到黑名单"""
    filter = get_data_filter()
    for sid in session_ids:
        if sid not in filter.BLACKLIST_SESSIONS:
            filter.BLACKLIST_SESSIONS.append(sid)
    return {"blacklist": filter.BLACKLIST_SESSIONS}


@router.post("/blacklist/remove")
def remove_from_blacklist(session_ids: List[str]):
    """从黑名单移除会话"""
    filter = get_data_filter()
    filter.BLACKLIST_SESSIONS = [
        s for s in filter.BLACKLIST_SESSIONS if s not in session_ids
    ]
    return {"blacklist": filter.BLACKLIST_SESSIONS}


@router.get("/analyze/{session_id}", response_model=SessionFilterStats)
def analyze_session(session_id: str, db: DBSession = Depends(get_db)):
    """
    分析会话的内容分布
    返回各类型消息的数量和比例
    """
    filter = get_data_filter()
    
    # 获取会话信息
    session = db.query(Session).filter(Session.session_id == session_id).first()
    
    # 获取所有消息
    messages = db.query(RawChat).filter(RawChat.session_id == session_id).all()
    
    # 统计各类型
    stats = {cat.value: 0 for cat in ContentCategory}
    
    for msg in messages:
        category = filter.classify_content(msg.content or '', msg.msg_type)
        stats[category.value] += 1
    
    total = len(messages)
    valuable = stats['valuable']
    
    return SessionFilterStats(
        session_id=session_id,
        display_name=session.display_name if session else None,
        total_messages=total,
        valuable=valuable,
        chitchat=stats['chitchat'],
        sensitive=stats['sensitive'],
        spam=stats['spam'],
        system=stats['system'],
        media=stats['media'],
        short=stats['short'],
        valuable_ratio=valuable / total if total > 0 else 0
    )


@router.get("/analyze-all")
def analyze_all_sessions(
    limit: int = Query(100, ge=1, le=1000),
    min_messages: int = Query(10, ge=1),
    db: DBSession = Depends(get_db)
):
    """
    分析所有会话的内容质量
    返回按有价值内容比例排序的会话列表
    """
    from sqlalchemy import func, desc
    
    filter = get_data_filter()
    
    # 获取消息数量 >= min_messages 的会话
    sessions = db.query(Session).filter(
        Session.message_count >= min_messages
    ).order_by(desc(Session.message_count)).limit(limit).all()
    
    results = []
    for session in sessions:
        # 采样分析（只分析前100条消息以提高速度）
        messages = db.query(RawChat).filter(
            RawChat.session_id == session.session_id
        ).limit(100).all()
        
        stats = {cat.value: 0 for cat in ContentCategory}
        for msg in messages:
            category = filter.classify_content(msg.content or '', msg.msg_type)
            stats[category.value] += 1
        
        total = len(messages)
        valuable = stats['valuable']
        
        results.append({
            'session_id': session.session_id,
            'display_name': session.display_name,
            'total_messages': session.message_count,
            'sampled': total,
            'valuable': valuable,
            'valuable_ratio': valuable / total if total > 0 else 0,
            'is_chatroom': session.is_chatroom
        })
    
    # 按有价值比例排序
    results.sort(key=lambda x: x['valuable_ratio'], reverse=True)
    
    return {
        "total_sessions": len(results),
        "sessions": results
    }
