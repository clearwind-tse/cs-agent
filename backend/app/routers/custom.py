# -*- coding: utf-8 -*-
"""
自定义对话数据 API
支持手动添加、编辑、删除对话数据
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import desc
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from datetime import datetime
import json

from app.models.database import get_db
from app.models.chat import CustomConversation
from app.services.data_generator import get_generator

router = APIRouter(prefix="/api/custom", tags=["custom"])


# ==================== 请求/响应模型 ====================

class ConversationTurn(BaseModel):
    """对话轮次"""
    role: str = Field(..., description="角色: user/assistant/system")
    content: str = Field(..., description="对话内容")


class CustomConversationCreate(BaseModel):
    """创建自定义对话"""
    conversation_json: List[ConversationTurn] = Field(..., description="对话内容（至少2轮）")
    category: str = Field("sales", description="分类: sales/course/objection/closing/followup/qa/knowledge")
    quality: str = Field("high", description="质量: high/medium/low")
    system_prompt: Optional[str] = Field(None, description="自定义系统提示词（可选，为空则使用默认）")
    title: Optional[str] = Field(None, description="标题（可选）")
    description: Optional[str] = Field(None, description="描述（可选）")
    tags: Optional[List[str]] = Field(None, description="标签列表（可选）")
    source: str = Field("manual", description="来源标记")
    created_by: Optional[str] = Field("admin", description="创建人")


class CustomConversationUpdate(BaseModel):
    """更新自定义对话"""
    conversation_json: Optional[List[ConversationTurn]] = None
    category: Optional[str] = None
    quality: Optional[str] = None
    system_prompt: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None


class CustomConversationResponse(BaseModel):
    """自定义对话响应"""
    id: int
    conversation_json: List[dict]
    category: str
    quality: str
    system_prompt: Optional[str]
    title: Optional[str]
    description: Optional[str]
    tags: Optional[List[str]]
    source: str
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


# ==================== API 端点 ====================

@router.post("/conversations", response_model=CustomConversationResponse)
def create_custom_conversation(
    data: CustomConversationCreate,
    db: DBSession = Depends(get_db)
):
    """
    创建自定义对话数据

    要求：
    - 至少包含 2 轮对话
    - role 必须是 user/assistant/system
    - content 不能为空
    """
    # 验证对话数据
    if len(data.conversation_json) < 2:
        raise HTTPException(status_code=400, detail="对话至少需要 2 轮")

    valid_roles = {"user", "assistant", "system"}
    for turn in data.conversation_json:
        if turn.role not in valid_roles:
            raise HTTPException(
                status_code=400,
                detail=f"无效的角色: {turn.role}，必须是 user/assistant/system"
            )
        if not turn.content.strip():
            raise HTTPException(status_code=400, detail="对话内容不能为空")

    # 验证分类
    valid_categories = ["sales", "course", "objection", "closing", "followup", "qa", "knowledge", "casual"]
    if data.category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"无效的分类: {data.category}，必须是 {', '.join(valid_categories)}"
        )

    # 验证质量
    valid_qualities = ["high", "medium", "low"]
    if data.quality not in valid_qualities:
        raise HTTPException(
            status_code=400,
            detail=f"无效的质量: {data.quality}，必须是 {', '.join(valid_qualities)}"
        )

    # 转换为字典格式存储
    conversation_dict = [turn.dict() for turn in data.conversation_json]

    # 创建记录
    custom_conv = CustomConversation(
        conversation_json=conversation_dict,
        category=data.category,
        quality=data.quality,
        system_prompt=data.system_prompt,
        title=data.title,
        description=data.description,
        tags=data.tags,
        source=data.source,
        created_by=data.created_by,
        is_active=True
    )

    db.add(custom_conv)
    db.commit()
    db.refresh(custom_conv)

    return custom_conv


@router.get("/conversations", response_model=List[CustomConversationResponse])
def list_custom_conversations(
    category: Optional[str] = Query(None, description="按分类筛选"),
    quality: Optional[str] = Query(None, description="按质量筛选"),
    is_active: Optional[bool] = Query(None, description="按状态筛选"),
    search: Optional[str] = Query(None, description="搜索标题或描述"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: DBSession = Depends(get_db)
):
    """
    获取自定义对话列表
    支持分类、质量、状态筛选和搜索
    """
    query = db.query(CustomConversation)

    # 筛选条件
    if category:
        query = query.filter(CustomConversation.category == category)
    if quality:
        query = query.filter(CustomConversation.quality == quality)
    if is_active is not None:
        query = query.filter(CustomConversation.is_active == is_active)
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (CustomConversation.title.ilike(search_pattern)) |
            (CustomConversation.description.ilike(search_pattern))
        )

    # 按创建时间倒序
    query = query.order_by(desc(CustomConversation.created_at))

    total = query.count()
    items = query.offset(skip).limit(limit).all()

    return items


@router.get("/conversations/{conversation_id}", response_model=CustomConversationResponse)
def get_custom_conversation(
    conversation_id: int,
    db: DBSession = Depends(get_db)
):
    """获取单个自定义对话详情"""
    conv = db.query(CustomConversation).filter(
        CustomConversation.id == conversation_id
    ).first()

    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    return conv


@router.put("/conversations/{conversation_id}", response_model=CustomConversationResponse)
def update_custom_conversation(
    conversation_id: int,
    data: CustomConversationUpdate,
    db: DBSession = Depends(get_db)
):
    """更新自定义对话"""
    conv = db.query(CustomConversation).filter(
        CustomConversation.id == conversation_id
    ).first()

    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 更新字段
    if data.conversation_json is not None:
        if len(data.conversation_json) < 2:
            raise HTTPException(status_code=400, detail="对话至少需要 2 轮")

        valid_roles = {"user", "assistant", "system"}
        for turn in data.conversation_json:
            if turn.role not in valid_roles:
                raise HTTPException(
                    status_code=400,
                    detail=f"无效的角色: {turn.role}"
                )
            if not turn.content.strip():
                raise HTTPException(status_code=400, detail="对话内容不能为空")

        conv.conversation_json = [turn.dict() for turn in data.conversation_json]

    if data.category is not None:
        conv.category = data.category
    if data.quality is not None:
        conv.quality = data.quality
    if data.system_prompt is not None:
        conv.system_prompt = data.system_prompt
    if data.title is not None:
        conv.title = data.title
    if data.description is not None:
        conv.description = data.description
    if data.tags is not None:
        conv.tags = data.tags
    if data.is_active is not None:
        conv.is_active = data.is_active

    conv.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(conv)

    return conv


@router.delete("/conversations/{conversation_id}")
def delete_custom_conversation(
    conversation_id: int,
    db: DBSession = Depends(get_db)
):
    """删除自定义对话"""
    conv = db.query(CustomConversation).filter(
        CustomConversation.id == conversation_id
    ).first()

    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    db.delete(conv)
    db.commit()

    return {"message": "删除成功", "id": conversation_id}


@router.post("/conversations/{conversation_id}/toggle")
def toggle_custom_conversation(
    conversation_id: int,
    db: DBSession = Depends(get_db)
):
    """切换自定义对话的启用状态"""
    conv = db.query(CustomConversation).filter(
        CustomConversation.id == conversation_id
    ).first()

    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    conv.is_active = not conv.is_active
    conv.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(conv)

    return {
        "message": "状态已更新",
        "id": conversation_id,
        "is_active": conv.is_active
    }


@router.get("/stats")
def get_custom_stats(db: DBSession = Depends(get_db)):
    """获取自定义数据统计"""
    total = db.query(CustomConversation).count()
    active = db.query(CustomConversation).filter(
        CustomConversation.is_active == True
    ).count()

    # 按分类统计
    from sqlalchemy import func
    by_category = db.query(
        CustomConversation.category,
        func.count(CustomConversation.id)
    ).filter(
        CustomConversation.is_active == True
    ).group_by(CustomConversation.category).all()

    # 按质量统计
    by_quality = db.query(
        CustomConversation.quality,
        func.count(CustomConversation.id)
    ).filter(
        CustomConversation.is_active == True
    ).group_by(CustomConversation.quality).all()

    return {
        "total": total,
        "active": active,
        "inactive": total - active,
        "by_category": {cat: count for cat, count in by_category},
        "by_quality": {qual: count for qual, count in by_quality}
    }


@router.post("/conversations/batch-create")
def batch_create_conversations(
    conversations: List[CustomConversationCreate],
    db: DBSession = Depends(get_db)
):
    """批量创建自定义对话"""
    created_ids = []
    errors = []

    for idx, data in enumerate(conversations):
        try:
            # 验证
            if len(data.conversation_json) < 2:
                errors.append({"index": idx, "error": "对话至少需要 2 轮"})
                continue

            # 转换并创建
            conversation_dict = [turn.dict() for turn in data.conversation_json]
            custom_conv = CustomConversation(
                conversation_json=conversation_dict,
                category=data.category,
                quality=data.quality,
                system_prompt=data.system_prompt,
                title=data.title,
                description=data.description,
                tags=data.tags,
                source=data.source,
                created_by=data.created_by,
                is_active=True
            )
            db.add(custom_conv)
            db.flush()
            created_ids.append(custom_conv.id)
        except Exception as e:
            errors.append({"index": idx, "error": str(e)})

    db.commit()

    return {
        "message": f"成功创建 {len(created_ids)} 条对话",
        "created_ids": created_ids,
        "errors": errors
    }


# ==================== AI 数据生成 ====================

class GenerateRequest(BaseModel):
    """AI 生成请求"""
    target_count: int = Field(200, ge=1, le=500, description="目标生成数量")
    categories: Optional[List[str]] = Field(None, description="指定分类 (None=全部)")


@router.post("/conversations/generate")
def generate_conversations(
    req: GenerateRequest,
    db: DBSession = Depends(get_db)
):
    """
    使用 LLM 批量生成训练对话数据

    异步启动生成任务, 通过 /generate/progress 查询进度
    """
    generator = get_generator()

    if generator.progress.is_running:
        raise HTTPException(
            status_code=409,
            detail="已有生成任务在运行中 请等待完成后再启动新任务"
        )

    if not generator.client:
        raise HTTPException(
            status_code=500,
            detail="LLM 客户端未初始化 请检查 DeepSeek/OpenAI API Key 配置"
        )

    # 启动异步生成
    generator.generate_batch_async(
        target_count=req.target_count,
        categories=req.categories,
    )

    return {
        "message": f"已启动生成任务 目标 {req.target_count} 条",
        "status": "running",
    }


@router.get("/conversations/generate/progress")
def get_generate_progress():
    """获取 AI 生成任务的进度"""
    generator = get_generator()
    return generator.get_progress()


@router.get("/conversations/generate/results")
def get_generated_results():
    """
    获取已生成的对话数据用于预览审核

    每条数据包含 index, category, title, description, conversation_json
    """
    generator = get_generator()

    if generator.progress.is_running:
        raise HTTPException(
            status_code=409,
            detail="生成任务还在运行中 请等待完成后查看"
        )

    results = generator.progress.results
    preview = []
    for idx, data in enumerate(results):
        preview.append({
            "index": idx,
            "category": data.get("category", "sales"),
            "title": data.get("title", ""),
            "description": data.get("description", ""),
            "tags": data.get("tags", []),
            "conversation_json": data["conversation_json"],
            "turn_count": len(data["conversation_json"]),
        })

    return {
        "total": len(preview),
        "results": preview,
    }


class SaveApprovedRequest(BaseModel):
    """保存审核通过的数据"""
    approved_indices: List[int] = Field(..., description="审核通过的对话索引列表")
    edits: Optional[Dict[str, List[dict]]] = Field(None, description="编辑过的对话内容 key为索引字符串 value为修改后的消息列表")


@router.post("/conversations/generate/save")
def save_generated_conversations(
    req: SaveApprovedRequest,
    db: DBSession = Depends(get_db)
):
    """
    将审核通过的对话数据保存到数据库

    只保存 approved_indices 中指定的对话
    """
    generator = get_generator()

    if generator.progress.is_running:
        raise HTTPException(
            status_code=409,
            detail="生成任务还在运行中 请等待完成后再保存"
        )

    results = generator.progress.results
    if not results:
        raise HTTPException(
            status_code=400,
            detail="没有可保存的生成结果 请先运行生成任务"
        )

    created_ids = []
    errors = []

    for idx in req.approved_indices:
        if idx < 0 or idx >= len(results):
            errors.append({"index": idx, "error": "索引超出范围"})
            continue

        data = results[idx]
        try:
            # 如果用户编辑过这条对话 使用编辑后的内容
            conversation_dict = data["conversation_json"]
            if req.edits and str(idx) in req.edits:
                conversation_dict = req.edits[str(idx)]
            custom_conv = CustomConversation(
                conversation_json=conversation_dict,
                category=data.get("category", "sales"),
                quality=data.get("quality", "high"),
                system_prompt=None,
                title=data.get("title"),
                description=data.get("description"),
                tags=data.get("tags"),
                source=data.get("source", "llm_generated"),
                created_by=data.get("created_by", "auto_generator"),
                is_active=True
            )
            db.add(custom_conv)
            db.flush()
            created_ids.append(custom_conv.id)
        except Exception as e:
            errors.append({"index": idx, "error": str(e)})

    db.commit()

    # 清空结果
    generator.progress.results = []

    return {
        "message": f"成功保存 {len(created_ids)} 条对话到数据库",
        "created_ids": created_ids,
        "approved_count": len(req.approved_indices),
        "errors": errors,
    }


@router.post("/conversations/generate/stop")
def stop_generation():
    """停止正在运行的生成任务"""
    generator = get_generator()

    if not generator.progress.is_running:
        return {"message": "当前没有运行中的任务"}

    generator.progress.is_running = False

    return {
        "message": "已发送停止信号",
        "completed": generator.progress.completed,
        "passed": generator.progress.passed,
    }
