# -*- coding: utf-8 -*-
"""
聊天记录相关 API
"""
import os
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import desc, func
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.models.database import get_db
from app.models.chat import RawChat, Session, Contact
from app.config import get_settings

settings = get_settings()

router = APIRouter(prefix="/api/chats", tags=["chats"])

# 时间过滤：只显示 2025年10月 及以后的数据
MIN_TIMESTAMP = 1759248000  # 2025-10-01 00:00:00 CST (秒级)


# ==================== 响应模型 ====================

class SessionResponse(BaseModel):
    """会话响应"""
    id: int
    session_id: str
    display_name: Optional[str]
    is_chatroom: bool
    last_message: Optional[str]
    last_time: Optional[int]
    message_count: int
    
    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    """消息响应"""
    id: int
    local_id: Optional[int]
    session_id: str
    sender_wxid: Optional[str]
    sender_name: Optional[str]
    content: Optional[str]
    msg_type: int
    is_sender: bool
    timestamp: int
    display_content: Optional[str]
    voice_path: Optional[str] = None
    
    class Config:
        from_attributes = True


class ContactResponse(BaseModel):
    """联系人响应"""
    id: int
    wxid: str
    alias: Optional[str]
    nickname: Optional[str]
    remark: Optional[str]
    display_name: Optional[str]
    avatar_url: Optional[str]
    is_chatroom: bool
    
    class Config:
        from_attributes = True


class PaginatedResponse(BaseModel):
    """分页响应"""
    items: List
    total: int
    page: int
    page_size: int
    has_more: bool


# ==================== API 端点 ====================

@router.get("/sessions", response_model=PaginatedResponse)
def get_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    session_type: Optional[str] = Query(None, description="会话类型: all, private, chatroom"),
    exclude_chatroom: bool = Query(True, description="是否排除群聊（默认排除）"),
    db: DBSession = Depends(get_db)
):
    """
    获取会话列表
    - 默认只显示私聊（exclude_chatroom=True）
    - 默认只显示2025年10月之后有消息的会话
    """
    query = db.query(Session)
    
    # 时间过滤：只显示 2025年10月 及以后有消息的会话
    query = query.filter(Session.last_time >= MIN_TIMESTAMP)
    
    # 群聊过滤
    if session_type == "private":
        query = query.filter(Session.is_chatroom == False)
    elif session_type == "chatroom":
        query = query.filter(Session.is_chatroom == True)
    elif exclude_chatroom:
        # 默认排除群聊
        query = query.filter(Session.is_chatroom == False)
    
    # 搜索过滤
    if search:
        query = query.filter(Session.display_name.ilike(f"%{search}%"))
    
    # 统计总数
    total = query.count()
    
    # 分页查询
    sessions = query.order_by(desc(Session.last_time))\
        .offset((page - 1) * page_size)\
        .limit(page_size)\
        .all()
    
    return PaginatedResponse(
        items=[SessionResponse.model_validate(s) for s in sessions],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, db: DBSession = Depends(get_db)):
    """获取单个会话详情"""
    session = db.query(Session).filter(Session.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse.model_validate(session)


@router.get("/history/{session_id}", response_model=PaginatedResponse)
def get_chat_history(
    session_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    before_time: Optional[int] = None,
    after_time: Optional[int] = None,
    msg_type: Optional[int] = None,
    db: DBSession = Depends(get_db)
):
    """获取聊天历史记录"""
    query = db.query(RawChat).filter(RawChat.session_id == session_id)
    
    # 时间筛选
    if before_time:
        query = query.filter(RawChat.timestamp < before_time)
    if after_time:
        query = query.filter(RawChat.timestamp > after_time)
    
    # 消息类型筛选
    if msg_type is not None:
        query = query.filter(RawChat.msg_type == msg_type)
    
    # 统计总数
    total = query.count()
    
    # 分页查询 (按时间倒序)
    messages = query.order_by(desc(RawChat.timestamp))\
        .offset((page - 1) * page_size)\
        .limit(page_size)\
        .all()
    
    # 反转顺序，使最新消息在最后
    messages.reverse()
    
    return PaginatedResponse(
        items=[MessageResponse.model_validate(m) for m in messages],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total
    )


@router.get("/contacts", response_model=PaginatedResponse)
def get_contacts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    db: DBSession = Depends(get_db)
):
    """获取联系人列表"""
    query = db.query(Contact).filter(Contact.is_chatroom == False)
    
    if search:
        query = query.filter(
            (Contact.display_name.ilike(f"%{search}%")) |
            (Contact.nickname.ilike(f"%{search}%")) |
            (Contact.remark.ilike(f"%{search}%"))
        )
    
    total = query.count()
    
    contacts = query.order_by(Contact.display_name)\
        .offset((page - 1) * page_size)\
        .limit(page_size)\
        .all()
    
    return PaginatedResponse(
        items=[ContactResponse.model_validate(c) for c in contacts],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total
    )


@router.get("/contacts/{wxid}", response_model=ContactResponse)
def get_contact(wxid: str, db: DBSession = Depends(get_db)):
    """获取单个联系人详情"""
    contact = db.query(Contact).filter(Contact.wxid == wxid).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return ContactResponse.model_validate(contact)


@router.get("/voice/{filename}")
def get_voice_file(filename: str):
    """提供语音文件下载/播放"""
    # 安全校验：只允许 .mp3 文件，防止路径遍历
    if not filename.endswith('.mp3') or '/' in filename or '..' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    file_path = os.path.join(settings.voice_file_path, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Voice file not found")
    
    return FileResponse(
        file_path, 
        media_type="audio/mpeg",
        headers={"Accept-Ranges": "bytes"}
    )


@router.get("/context/{message_id}")
def get_message_context(
    message_id: int,
    context_size: int = Query(25, ge=5, le=100, description="目标消息前后各取多少条"),
    db: DBSession = Depends(get_db)
):
    """
    获取消息上下文：返回目标消息前后各 context_size 条消息
    用于搜索结果跳转定位
    """
    # 1. 查找目标消息
    target = db.query(RawChat).filter(RawChat.id == message_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # 2. 查询该消息之前的消息（含自身）
    before = db.query(RawChat).filter(
        RawChat.session_id == target.session_id,
        RawChat.timestamp <= target.timestamp,
        RawChat.id <= target.id
    ).order_by(desc(RawChat.timestamp), desc(RawChat.id)).limit(context_size + 1).all()
    
    # 3. 查询该消息之后的消息
    after = db.query(RawChat).filter(
        RawChat.session_id == target.session_id,
        (RawChat.timestamp > target.timestamp) | 
        ((RawChat.timestamp == target.timestamp) & (RawChat.id > target.id))
    ).order_by(RawChat.timestamp, RawChat.id).limit(context_size).all()
    
    # 4. 合并并按时间排序
    all_messages = list(reversed(before)) + after
    # 去重（target 可能在 before 和 after 中都出现）
    seen_ids = set()
    unique_messages = []
    for msg in all_messages:
        if msg.id not in seen_ids:
            seen_ids.add(msg.id)
            unique_messages.append(msg)
    
    unique_messages.sort(key=lambda m: (m.timestamp, m.id))
    
    return {
        "target_message_id": message_id,
        "session_id": target.session_id,
        "items": [MessageResponse.model_validate(m) for m in unique_messages],
        "total": len(unique_messages)
    }
