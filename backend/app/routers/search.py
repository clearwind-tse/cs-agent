# -*- coding: utf-8 -*-
"""
搜索相关 API
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import or_, desc
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.models.database import get_db
from app.models.chat import RawChat, Session, Contact

router = APIRouter(prefix="/api/search", tags=["search"])


# ==================== 响应模型 ====================

class SearchResultItem(BaseModel):
    """搜索结果项"""
    id: int
    session_id: str
    session_name: Optional[str]
    sender_name: Optional[str]
    content: Optional[str]
    timestamp: int
    msg_type: int
    highlight: Optional[str]  # 高亮显示的内容片段
    
    class Config:
        from_attributes = True


class SearchResponse(BaseModel):
    """搜索响应"""
    items: List[SearchResultItem]
    total: int
    query: str
    page: int
    page_size: int
    has_more: bool


# ==================== API 端点 ====================

@router.get("/messages", response_model=SearchResponse)
def search_messages(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session_id: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    exclude_chatroom: bool = Query(True, description="是否排除群聊（默认排除）"),
    db: DBSession = Depends(get_db)
):
    """
    全文搜索消息
    支持按会话、时间范围筛选
    """
    # 基础查询
    query = db.query(RawChat).filter(
        RawChat.content.ilike(f"%{q}%")
    )

    if exclude_chatroom:
        query = query.filter(~RawChat.session_id.like('%@chatroom'))
    
    # 筛选条件
    if session_id:
        query = query.filter(RawChat.session_id == session_id)
    if start_time:
        query = query.filter(RawChat.timestamp >= start_time)
    if end_time:
        query = query.filter(RawChat.timestamp <= end_time)
    
    # 统计总数
    total = query.count()
    
    # 分页查询
    messages = query.order_by(desc(RawChat.timestamp))\
        .offset((page - 1) * page_size)\
        .limit(page_size)\
        .all()
    
    # 构建结果
    items = []
    for msg in messages:
        # 获取会话名称
        session = db.query(Session).filter(Session.session_id == msg.session_id).first()
        session_name = session.display_name if session else msg.session_id
        
        # 生成高亮片段
        highlight = None
        if msg.content:
            # 找到关键词位置，提取前后文
            lower_content = msg.content.lower()
            lower_q = q.lower()
            pos = lower_content.find(lower_q)
            if pos >= 0:
                start = max(0, pos - 30)
                end = min(len(msg.content), pos + len(q) + 30)
                highlight = msg.content[start:end]
                if start > 0:
                    highlight = "..." + highlight
                if end < len(msg.content):
                    highlight = highlight + "..."
        
        items.append(SearchResultItem(
            id=msg.id,
            session_id=msg.session_id,
            session_name=session_name,
            sender_name=msg.sender_name,
            content=msg.content[:200] if msg.content else None,
            timestamp=msg.timestamp,
            msg_type=msg.msg_type,
            highlight=highlight
        ))
    
    return SearchResponse(
        items=items,
        total=total,
        query=q,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total
    )


@router.get("/sessions", response_model=List[dict])
def search_sessions(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50),
    exclude_chatroom: bool = Query(True, description="是否排除群聊（默认排除）"),
    db: DBSession = Depends(get_db)
):
    """
    搜索会话/联系人
    """
    query = db.query(Session).filter(
        Session.display_name.ilike(f"%{q}%")
    )

    if exclude_chatroom:
        query = query.filter(Session.is_chatroom == False)

    sessions = query.limit(limit).all()
    
    return [
        {
            "session_id": s.session_id,
            "display_name": s.display_name,
            "is_chatroom": s.is_chatroom,
            "message_count": s.message_count
        }
        for s in sessions
    ]
