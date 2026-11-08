# -*- coding: utf-8 -*-
"""
数据标注 API
支持数据清洗、人工标注、批量操作
"""
from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func, and_
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import json

from app.models.database import get_db
from app.models.chat import RawChat, LabeledConversation, LabelStatus, DataCategory
from app.services.training_data import (
    TrainingDataPipeline, 
    ConversationBuilder,
    DataQuality
)

router = APIRouter(prefix="/api/labeling", tags=["labeling"])

# 时间过滤：只处理 2025年10月 及以后的数据
MIN_TIMESTAMP = 1759248000  # 2025-10-01 00:00:00 CST (秒级)


# ==================== 请求模型 ====================

class CleaningConfig(BaseModel):
    """清洗配置"""
    time_window_seconds: int = 300
    max_turns: int = 20
    min_quality: str = "low"  # 初次清洗用低门槛
    session_ids: Optional[List[str]] = None
    limit: int = 1000  # 每次处理数量
    start_time: Optional[int] = None  # 时间窗起点（秒级时间戳），不填则取 2025-10-01 下限
    end_time: Optional[int] = None  # 时间窗终点（秒级时间戳）


class LabelRequest(BaseModel):
    """标注请求"""
    category: str  # 分类
    quality: str = "medium"  # high/medium/low
    notes: Optional[str] = None  # 备注
    modified_text: Optional[str] = None  # 修改后的文本


class BatchLabelRequest(BaseModel):
    """批量标注请求"""
    ids: List[int]
    action: str  # approve/reject/set_category
    category: Optional[str] = None
    quality: Optional[str] = None


# ==================== 统计 API ====================

@router.delete("/clear")
def clear_all_labeled_data(db: DBSession = Depends(get_db)):
    """清空所有标注数据（重新开始）"""
    count = db.query(LabeledConversation).delete()
    db.commit()
    return {"message": f"已清空 {count} 条标注数据"}


@router.get("/stats")
def get_labeling_stats(db: DBSession = Depends(get_db)):
    """获取标注统计信息"""
    
    # 原始数据统计
    raw_count = db.query(RawChat).count()
    raw_sessions = db.query(func.count(func.distinct(RawChat.session_id))).scalar()
    
    # 已标注数据统计
    labeled_total = db.query(LabeledConversation).count()
    
    # 按状态统计
    status_counts = dict(
        db.query(
            LabeledConversation.status, 
            func.count(LabeledConversation.id)
        ).group_by(LabeledConversation.status).all()
    )
    
    # 按分类统计（已通过的）
    category_counts = dict(
        db.query(
            LabeledConversation.human_category, 
            func.count(LabeledConversation.id)
        ).filter(
            LabeledConversation.status == LabelStatus.APPROVED.value
        ).group_by(LabeledConversation.human_category).all()
    )
    
    return {
        "raw_messages": raw_count,
        "raw_sessions": raw_sessions,
        "labeled_total": labeled_total,
        "by_status": {
            "pending": status_counts.get(LabelStatus.PENDING.value, 0),
            "approved": status_counts.get(LabelStatus.APPROVED.value, 0),
            "rejected": status_counts.get(LabelStatus.REJECTED.value, 0),
            "modified": status_counts.get(LabelStatus.MODIFIED.value, 0),
        },
        "by_category": category_counts,
        "progress": {
            "total": labeled_total,
            "done": status_counts.get(LabelStatus.APPROVED.value, 0) + status_counts.get(LabelStatus.REJECTED.value, 0),
            "pending": status_counts.get(LabelStatus.PENDING.value, 0),
        }
    }


# ==================== 数据清洗 API ====================

@router.post("/clean")
def clean_raw_data(
    config: CleaningConfig,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db)
):
    """
    清洗原始数据，生成待标注的对话
    这是第一步：把原始消息转换成对话块
    """
    # 检查是否已有未处理的数据
    pending_count = db.query(LabeledConversation).filter(
        LabeledConversation.status == LabelStatus.PENDING.value
    ).count()
    
    # 构建处理管道
    pipeline = TrainingDataPipeline(
        builder=ConversationBuilder(
            time_window_seconds=config.time_window_seconds,
            max_turns_per_conversation=config.max_turns
        ),
        min_quality=DataQuality(config.min_quality)
    )
    
    # 获取会话（只获取时间窗内有消息的会话）
    time_floor = config.start_time if config.start_time is not None else MIN_TIMESTAMP
    session_query = db.query(RawChat.session_id).filter(
        RawChat.timestamp >= time_floor
    ).distinct()
    if config.session_ids:
        session_query = session_query.filter(RawChat.session_id.in_(config.session_ids))
    if config.end_time is not None:
        session_query = session_query.filter(RawChat.timestamp <= config.end_time)

    sessions = session_query.limit(50).all()  # 限制会话数

    created_count = 0

    for (session_id,) in sessions:
        # 检查该会话是否已处理过
        existing = db.query(LabeledConversation).filter(
            LabeledConversation.session_id == session_id
        ).first()
        if existing:
            continue

        # 获取消息（按时间窗过滤）
        msg_q = db.query(RawChat).filter(
            RawChat.session_id == session_id,
            RawChat.timestamp >= time_floor,
        )
        if config.end_time is not None:
            msg_q = msg_q.filter(RawChat.timestamp <= config.end_time)
        messages = msg_q.order_by(RawChat.timestamp).limit(config.limit).all()
        
        if not messages:
            continue
        
        # 转换为字典
        msg_dicts = [
            {
                "id": m.id,
                "sender_name": m.sender_name or m.sender_wxid,
                "content": m.content,
                "timestamp": m.timestamp,
                "is_sender": m.is_sender
            }
            for m in messages
        ]
        
        # 处理
        examples = pipeline.process_session(session_id, msg_dicts)
        
        # 保存到标注表
        for ex in examples:
            # 构建对话文本
            conv_text = "\n".join([
                f"{'本平台' if t.role == 'assistant' else '客户'}: {t.content}"
                for t in ex.conversations
            ])
            
            # 构建结构化数据
            conv_json = [
                {"role": t.role, "content": t.content, "sender": t.sender}
                for t in ex.conversations
            ]
            
            labeled = LabeledConversation(
                conversation_text=conv_text,
                conversation_json=json.dumps(conv_json, ensure_ascii=False) if not isinstance(conv_json, str) else conv_json,
                session_id=session_id,
                source_message_ids=json.dumps(ex.metadata.get("source_ids", [])),
                auto_category=ex.category.value,
                auto_quality_score=ex.metadata.get("score", 5.0),
                status=LabelStatus.PENDING.value,
                created_at=datetime.utcnow()
            )
            db.add(labeled)
            created_count += 1
        
        if created_count >= config.limit:
            break
    
    db.commit()
    
    return {
        "message": "清洗完成",
        "created": created_count,
        "pending_total": pending_count + created_count
    }


# ==================== 列表查询 API ====================

@router.get("/list")
def list_labeled_data(
    status: Optional[str] = Query(None, description="状态筛选"),
    category: Optional[str] = Query(None, description="分类筛选"),
    start_time: Optional[int] = Query(None, description="时间窗起点（秒级时间戳，按记录创建时间）"),
    end_time: Optional[int] = Query(None, description="时间窗终点（秒级时间戳，按记录创建时间）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db)
):
    """获取待标注/已标注数据列表"""
    
    query = db.query(LabeledConversation)
    
    if status:
        query = query.filter(LabeledConversation.status == status)
    if category:
        query = query.filter(
            (LabeledConversation.human_category == category) | 
            (LabeledConversation.auto_category == category)
        )
    if start_time is not None:
        query = query.filter(LabeledConversation.created_at >= datetime.utcfromtimestamp(start_time))
    if end_time is not None:
        query = query.filter(LabeledConversation.created_at <= datetime.utcfromtimestamp(end_time))
    
    total = query.count()
    
    items = query.order_by(
        LabeledConversation.created_at.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": item.id,
                "conversation_text": item.conversation_text[:500] + "..." if len(item.conversation_text or "") > 500 else item.conversation_text,
                "session_id": item.session_id,
                "auto_category": item.auto_category,
                "auto_quality_score": item.auto_quality_score,
                "human_category": item.human_category,
                "human_quality": item.human_quality,
                "human_notes": item.human_notes,
                "status": item.status,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "labeled_at": item.labeled_at.isoformat() if item.labeled_at else None,
            }
            for item in items
        ]
    }


@router.get("/item/{item_id}")
def get_labeled_item(item_id: int, db: DBSession = Depends(get_db)):
    """获取单个标注项详情"""
    
    item = db.query(LabeledConversation).filter(
        LabeledConversation.id == item_id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="数据不存在")
    
    return {
        "id": item.id,
        "conversation_text": item.conversation_text,
        "conversation_json": json.loads(item.conversation_json) if isinstance(item.conversation_json, str) else item.conversation_json,
        "session_id": item.session_id,
        "auto_category": item.auto_category,
        "auto_quality_score": item.auto_quality_score,
        "auto_flags": item.auto_flags,
        "human_category": item.human_category,
        "human_quality": item.human_quality,
        "human_notes": item.human_notes,
        "modified_text": item.modified_text,
        "status": item.status,
        "labeled_by": item.labeled_by,
        "labeled_at": item.labeled_at.isoformat() if item.labeled_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


# ==================== 标注操作 API ====================

@router.post("/item/{item_id}/label")
def label_item(
    item_id: int, 
    request: LabelRequest,
    db: DBSession = Depends(get_db)
):
    """对单个数据进行标注"""
    
    item = db.query(LabeledConversation).filter(
        LabeledConversation.id == item_id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="数据不存在")
    
    item.human_category = request.category
    item.human_quality = request.quality
    item.human_notes = request.notes
    item.status = LabelStatus.APPROVED.value
    item.labeled_at = datetime.utcnow()
    
    if request.modified_text:
        item.modified_text = request.modified_text
        item.status = LabelStatus.MODIFIED.value
    
    db.commit()
    
    return {"message": "标注成功", "id": item_id}


@router.post("/item/{item_id}/reject")
def reject_item(item_id: int, db: DBSession = Depends(get_db)):
    """拒绝/删除数据"""
    
    item = db.query(LabeledConversation).filter(
        LabeledConversation.id == item_id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="数据不存在")
    
    item.status = LabelStatus.REJECTED.value
    item.labeled_at = datetime.utcnow()
    db.commit()
    
    return {"message": "已拒绝", "id": item_id}


@router.post("/batch")
def batch_label(request: BatchLabelRequest, db: DBSession = Depends(get_db)):
    """批量操作"""
    
    items = db.query(LabeledConversation).filter(
        LabeledConversation.id.in_(request.ids)
    ).all()
    
    if not items:
        raise HTTPException(status_code=404, detail="未找到数据")
    
    count = 0
    for item in items:
        if request.action == "approve":
            item.status = LabelStatus.APPROVED.value
            if request.category:
                item.human_category = request.category
            if request.quality:
                item.human_quality = request.quality
        elif request.action == "reject":
            item.status = LabelStatus.REJECTED.value
        elif request.action == "set_category" and request.category:
            item.human_category = request.category
            item.status = LabelStatus.APPROVED.value
        
        item.labeled_at = datetime.utcnow()
        count += 1
    
    db.commit()
    
    return {"message": f"批量操作完成", "count": count}


# ==================== 导出已标注数据 ====================

@router.get("/export")
def export_labeled_data(
    format: str = Query("sharegpt", description="导出格式"),
    status: str = Query("approved", description="状态筛选"),
    categories: Optional[str] = Query(None, description="分类筛选，逗号分隔"),
    db: DBSession = Depends(get_db)
):
    """导出已标注的数据"""
    
    query = db.query(LabeledConversation).filter(
        LabeledConversation.status == status
    )
    
    if categories:
        cat_list = categories.split(",")
        query = query.filter(LabeledConversation.human_category.in_(cat_list))
    
    items = query.all()
    
    if not items:
        raise HTTPException(status_code=404, detail="没有符合条件的数据")
    
    # 根据分类选择 system prompt
    SYSTEM_PROMPTS = {
        "savings_explain": "我是本平台（本平台霸王餐）的客服本平台，负责给用户讲清楚怎么点外卖更省钱、返利怎么算。说话专业亲和、简洁直接，可称「您」，红包力度和返利金额如实说明。",
        "rebate_query": "我是本平台客服本平台，负责帮用户查返利到账情况。先安抚再给准话：返利按实付金额比例计算，订单完成后到账。说话专业亲和、直接爽快，可称「您」。",
        "coupon_issue": "我是本平台客服本平台，负责处理外卖红包和优惠券问题（领不到、用不了、过期）。一步步教用户领券入口、使用门槛和有效期规则，可称「您」。",
        "order_problem": "我是本平台客服本平台，负责处理订单异常（没跳转、没返利、券没用上、地址错误）。先问清订单号和时间再判断原因，说话负责、专业，可称「您」。",
        "complaint": "我是本平台客服本平台，负责处理用户投诉。先共情道歉、承认问题，再给出明确补偿或处理方案，不推诿、不争对错，语气真诚，可称「您」。",
        "merchant": "我是本平台客服本平台，负责到店霸王餐与探店体验。讲清中签规则、到店流程、内容要求：按时到店、拍图写真实体验、审核通过即返现，可称「您」。",
        "brand_promo": "我是本平台客服本平台，负责介绍平台大牌特惠与合作品牌（茶百道、沪上阿姨、霸王茶姬、奈雪、茶颜悦色、夸父炸串等）。直接讲清优惠和参与方式，可称「您」。",
        "points_box": "我是本平台客服本平台，负责积分和盲盒玩法。讲清规则：做任务攒积分、积分兑券、五折盲盒开品牌代金券。说话清楚有条理，可称「您」。",
        "onboarding": "我是本平台客服本平台，负责带新用户上手。按步骤讲：下载App、注册登录、领红包、下单返利、提现。语气友好亲切，可称「您」。",
        "chitchat": "我是本平台客服本平台，负责日常闲聊和礼貌性对话。简短热情回应，并顺势引导到省钱话题，可称「您」。",
    }
    DEFAULT_PROMPT = "我是本平台（本平台霸王餐）的客服本平台，帮用户点外卖省钱、领红包、拿返利、参加到店霸王餐。说话专业亲和、简洁直接，可称「您」。"
    
    dataset = []
    
    for item in items:
        # 使用修改后的文本（如果有）
        text = item.modified_text or item.conversation_text
        category = item.human_category or item.auto_category
        
        if format == "sharegpt":
            # 解析对话
            conversations = [{"from": "system", "value": SYSTEM_PROMPTS.get(category, DEFAULT_PROMPT)}]
            
            for line in text.split("\n"):
                if ": " in line:
                    role, content = line.split(": ", 1)
                    from_role = "gpt" if role in ["本平台", "助手", "我"] else "human"
                    conversations.append({"from": from_role, "value": content})
            
            dataset.append({
                "id": str(item.id),
                "conversations": conversations,
                "category": category,
                "quality": item.human_quality
            })
        
        elif format == "alpaca":
            # 提取问答对
            lines = text.split("\n")
            for i in range(len(lines) - 1):
                if "客户: " in lines[i] and "本平台: " in lines[i+1]:
                    q = lines[i].replace("客户: ", "")
                    a = lines[i+1].replace("本平台: ", "")
                    dataset.append({
                        "instruction": q,
                        "input": "",
                        "output": a,
                        "category": category
                    })
    
    return {
        "format": format,
        "count": len(dataset),
        "data": dataset
    }
