# -*- coding: utf-8 -*-
"""
后台管理 API
用于数据清洗、会话流管理、批量操作等
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.chat import RawChat, StagingConversation, LabelStatus
from app.services.admin import AdminService

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# ==================== Request/Response Models ====================

class PreprocessRequest(BaseModel):
    session_ids: Optional[List[str]] = None  # 如果为空，处理所有会话
    window_seconds: int = 300  # 对话窗口（秒）
    limit: Optional[int] = None  # 限制处理的会话数量（用于分批处理）
    process_all: bool = False  # 是否处理全部剩余会话（忽略 limit）


class MergeMessagesRequest(BaseModel):
    message_ids: List[int]


class UpdateStagingRequest(BaseModel):
    cleaned_text: Optional[str] = None
    human_question: Optional[str] = None
    human_answer: Optional[str] = None
    human_category: Optional[str] = None
    human_notes: Optional[str] = None


class BatchActionRequest(BaseModel):
    staging_ids: List[int]
    action: str  # approve/reject/delete
    category: Optional[str] = None
    notes: Optional[str] = None


class BulkFilterRequest(BaseModel):
    keyword: str
    action: str  # reject/approve
    session_ids: Optional[List[str]] = None


# ==================== API Endpoints ====================

@router.post("/preprocess")
def preprocess_sessions(
    request: PreprocessRequest,
    db: DBSession = Depends(get_db)
):
    """
    预处理会话：将原始消息转换为暂存区对话块
    支持分批处理，避免超时
    """
    admin_service = AdminService()
    
    # 获取要处理的会话列表（过滤群聊和时间）
    from app.services.admin import MIN_TIMESTAMP
    
    # 获取已经有暂存记录的会话ID（避免重复处理）
    processed_session_ids = db.query(StagingConversation.session_id).distinct().subquery()
    
    if request.session_ids:
        # 过滤掉群聊
        filtered_session_ids = [sid for sid in request.session_ids if not sid.endswith('@chatroom')]
        if not filtered_session_ids:
            return {
                'total_created': 0,
                'results': [],
                'processed': 0,
                'total': 0,
                'has_more': False
            }
        session_query = db.query(RawChat.session_id).filter(
            RawChat.session_id.in_(filtered_session_ids),
            RawChat.timestamp >= MIN_TIMESTAMP,  # 只处理2025年10月以后的数据
            ~RawChat.session_id.in_(processed_session_ids)  # 排除已处理的会话
        ).distinct()
    else:
        # 过滤掉群聊（session_id 不以 @chatroom 结尾）
        # 排除已经处理过的会话
        session_query = db.query(RawChat.session_id).filter(
            ~RawChat.session_id.like('%@chatroom'),  # 排除群聊
            RawChat.timestamp >= MIN_TIMESTAMP,  # 只处理2025年10月以后的数据
            ~RawChat.session_id.in_(processed_session_ids)  # 排除已处理的会话
        ).distinct()
    
    all_sessions = [sid for (sid,) in session_query.all()]
    total_sessions = len(all_sessions)
    
    if not request.process_all and request.limit and request.limit > 0:
        all_sessions = all_sessions[:request.limit]
    
    processed_count = 0
    total_created = 0
    results = []
    
    # 分批处理，每批处理10个会话后提交一次
    batch_size = 10
    for i in range(0, len(all_sessions), batch_size):
        batch_sessions = all_sessions[i:i+batch_size]
        
        for session_id in batch_sessions:
            try:
                count = admin_service.preprocess_session(
                    db, session_id, request.window_seconds
                )
                total_created += count
                results.append({
                    'session_id': session_id,
                    'created': count
                })
                processed_count += 1
            except Exception as e:
                results.append({
                    'session_id': session_id,
                    'error': str(e)
                })
                processed_count += 1
        
        # 每批处理后提交数据库
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[WARN] Batch commit failed: {e}")
    
    return {
        'total_created': total_created,
        'results': results,
        'processed': processed_count,
        'total': total_sessions,
        'has_more': processed_count < total_sessions
    }


# ==================== 质检结果（会话级）辅助 ====================

def _serialize_qc_brief(row) -> Dict[str, Any]:
    """把一条 quality_inspections 记录精简为清洗/审核界面可直接展示的质检结果。"""
    return {
        "id": row.id,
        "agent_name": row.agent_name,
        "config_name": row.config_name,
        "overall_score": row.overall_score,       # 0-100
        "scores": row.scores,                     # {维度key: 0-100}
        "violations": row.violations,             # [{type,severity,evidence,suggestion}]
        "scored": row.scored,                     # False = LLM不可用/未评分
        "status": row.status,
        "summary": row.summary,
        "suggestions": row.suggestions,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _pick_qc(rows, start_time=None, end_time=None):
    """从同一会话的质检记录中挑选最匹配的一条：优先精确时间窗，否则取最新。"""
    if not rows:
        return None
    if start_time is not None and end_time is not None:
        for r in rows:
            if r.start_time == start_time and r.end_time == end_time:
                return r
    return rows[0]


def _qc_by_sessions(db, session_ids) -> Dict[str, list]:
    """批量取若干会话的质检记录（按时间倒序），供列表页一次查询。"""
    from app.models.quality import QualityInspection
    out: Dict[str, list] = {}
    ids = list({s for s in session_ids if s})
    if not ids:
        return out
    rows = db.query(QualityInspection).filter(
        QualityInspection.session_id.in_(ids)
    ).order_by(QualityInspection.created_at.desc()).all()
    for r in rows:
        out.setdefault(r.session_id, []).append(r)
    return out


def _serialize_staging_item(conv, qc_rows) -> Dict[str, Any]:
    """暂存区对话序列化（附带该会话最新的质检结果）。"""
    qc_row = _pick_qc(qc_rows, conv.start_time, conv.end_time)
    return {
        'id': conv.id,
        'session_id': conv.session_id,
        'original_text': conv.original_text,
        'cleaned_text': conv.cleaned_text,
        'conversation_json': conv.conversation_json,
        'auto_question': conv.auto_question,
        'auto_answer': conv.auto_answer,
        'human_question': conv.human_question,
        'human_answer': conv.human_answer,
        'auto_category': conv.auto_category,
        'human_category': conv.human_category,
        'auto_quality_score': conv.auto_quality_score,
        'auto_flags': conv.auto_flags,
        'human_notes': conv.human_notes,
        'status': conv.status,
        'start_time': conv.start_time,
        'end_time': conv.end_time,
        'source_message_ids': conv.source_message_ids,
        'created_at': conv.created_at.isoformat() if conv.created_at else None,
        'qc': _serialize_qc_brief(qc_row) if qc_row else None,
    }


@router.get("/staging/list")
def get_staging_conversations(
    status: str = Query("pending", description="状态: pending/approved/rejected"),
    session_id: Optional[str] = Query(None, description="会话ID"),
    category: Optional[str] = Query(None, description="分类"),
    min_quality: Optional[float] = Query(None, description="最低质量分"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db)
):
    """
    获取暂存区对话列表
    自动过滤群聊和2025年10月以前的数据
    """
    from app.services.admin import MIN_TIMESTAMP
    
    query = db.query(StagingConversation)
    
    # 过滤群聊（session_id 不以 @chatroom 结尾）
    query = query.filter(~StagingConversation.session_id.like('%@chatroom'))
    
    # 过滤时间（只显示2025年10月以后的数据）
    query = query.filter(StagingConversation.start_time >= MIN_TIMESTAMP)
    
    if status != "all":
        query = query.filter(StagingConversation.status == status)
    if session_id:
        query = query.filter(StagingConversation.session_id == session_id)
    if category:
        query = query.filter(
            (StagingConversation.auto_category == category) |
            (StagingConversation.human_category == category)
        )
    if min_quality is not None:
        query = query.filter(StagingConversation.auto_quality_score >= min_quality)
    
    total = query.count()
    conversations = query.order_by(
        StagingConversation.created_at.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()
    
    qc_map = _qc_by_sessions(db, [c.session_id for c in conversations])
    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'items': [_serialize_staging_item(c, qc_map.get(c.session_id, [])) for c in conversations],
    }


@router.get("/staging/{staging_id}")
def get_staging_detail(
    staging_id: int,
    db: DBSession = Depends(get_db)
):
    """
    获取暂存区对话详情（包含原始消息）
    """
    staging = db.query(StagingConversation).filter(
        StagingConversation.id == staging_id
    ).first()
    
    if not staging:
        raise HTTPException(status_code=404, detail="暂存区对话不存在")
    
    # 获取原始消息（虽然预处理时已过滤，但这里再次过滤确保数据正确）
    from app.services.admin import MIN_TIMESTAMP
    
    original_messages = []
    if staging.source_message_ids:
        messages = db.query(RawChat).filter(
            RawChat.id.in_(staging.source_message_ids),
            ~RawChat.session_id.like('%@chatroom'),  # 排除群聊
            RawChat.timestamp >= MIN_TIMESTAMP  # 只显示2025年10月以后的数据
        ).order_by(RawChat.timestamp).all()
        
        original_messages = [
            {
                'id': msg.id,
                'sender_name': msg.sender_name,
                'content': msg.content,
                'clean_content': msg.clean_content,
                'timestamp': msg.timestamp,
                'msg_type': msg.msg_type,
                'is_sender': msg.is_sender,
                'status': msg.status,
                'auto_category': msg.auto_category,
            }
            for msg in messages
        ]
    
    from app.models.quality import QualityInspection
    qc_rows = db.query(QualityInspection).filter(
        QualityInspection.session_id == staging.session_id
    ).order_by(QualityInspection.created_at.desc()).all()
    qc_row = _pick_qc(qc_rows, staging.start_time, staging.end_time)

    return {
        'staging': {
            'id': staging.id,
            'session_id': staging.session_id,
            'original_text': staging.original_text,
            'cleaned_text': staging.cleaned_text,
            'conversation_json': staging.conversation_json,
            'auto_question': staging.auto_question,
            'auto_answer': staging.auto_answer,
            'human_question': staging.human_question,
            'human_answer': staging.human_answer,
            'auto_category': staging.auto_category,
            'human_category': staging.human_category,
            'auto_quality_score': staging.auto_quality_score,
            'auto_flags': staging.auto_flags,
            'human_notes': staging.human_notes,
            'status': staging.status,
            'start_time': staging.start_time,
            'end_time': staging.end_time,
            'created_at': staging.created_at.isoformat() if staging.created_at else None,
            'qc': _serialize_qc_brief(qc_row) if qc_row else None,
        },
        'original_messages': original_messages
    }


@router.put("/staging/{staging_id}")
def update_staging(
    staging_id: int,
    request: UpdateStagingRequest,
    db: DBSession = Depends(get_db)
):
    """
    更新暂存区对话（编辑内容、Q&A等）
    """
    staging = db.query(StagingConversation).filter(
        StagingConversation.id == staging_id
    ).first()
    
    if not staging:
        raise HTTPException(status_code=404, detail="暂存区对话不存在")
    
    if request.cleaned_text is not None:
        staging.cleaned_text = request.cleaned_text
        staging.status = LabelStatus.MODIFIED.value
    
    if request.human_question is not None:
        staging.human_question = request.human_question
    if request.human_answer is not None:
        staging.human_answer = request.human_answer
    if request.human_category is not None:
        staging.human_category = request.human_category
    if request.human_notes is not None:
        staging.human_notes = request.human_notes
    
    db.commit()
    
    return {'success': True, 'message': '更新成功'}


@router.post("/staging/{staging_id}/approve")
def approve_staging(
    staging_id: int,
    category: Optional[str] = Query(None),
    db: DBSession = Depends(get_db)
):
    """
    审核通过暂存区对话
    """
    staging = db.query(StagingConversation).filter(
        StagingConversation.id == staging_id
    ).first()
    
    if not staging:
        raise HTTPException(status_code=404, detail="暂存区对话不存在")
    
    staging.status = LabelStatus.APPROVED.value
    if category:
        staging.human_category = category
    staging.reviewed_by = "admin"  # TODO: 从认证中获取
    staging.reviewed_at = datetime.utcnow()
    
    db.commit()
    
    return {'success': True, 'message': '审核通过'}


@router.post("/staging/{staging_id}/reject")
def reject_staging(
    staging_id: int,
    notes: Optional[str] = Query(None),
    db: DBSession = Depends(get_db)
):
    """
    拒绝暂存区对话
    """
    staging = db.query(StagingConversation).filter(
        StagingConversation.id == staging_id
    ).first()
    
    if not staging:
        raise HTTPException(status_code=404, detail="暂存区对话不存在")
    
    staging.status = LabelStatus.REJECTED.value
    if notes:
        staging.human_notes = notes
    staging.reviewed_by = "admin"
    staging.reviewed_at = datetime.utcnow()
    
    db.commit()
    
    return {'success': True, 'message': '已拒绝'}


@router.post("/staging/batch")
def batch_action_staging(
    request: BatchActionRequest,
    db: DBSession = Depends(get_db)
):
    """
    批量操作暂存区对话
    """
    stagings = db.query(StagingConversation).filter(
        StagingConversation.id.in_(request.staging_ids)
    ).all()
    
    if not stagings:
        raise HTTPException(status_code=404, detail="未找到暂存区对话")
    
    updated_count = 0
    for staging in stagings:
        if request.action == 'approve':
            staging.status = LabelStatus.APPROVED.value
            if request.category:
                staging.human_category = request.category
        elif request.action == 'reject':
            staging.status = LabelStatus.REJECTED.value
        elif request.action == 'delete':
            db.delete(staging)
            continue
        
        if request.notes:
            staging.human_notes = request.notes
        staging.reviewed_by = "admin"
        staging.reviewed_at = datetime.utcnow()
        updated_count += 1
    
    db.commit()
    
    return {
        'success': True,
        'updated': updated_count,
        'deleted': len(request.staging_ids) - updated_count
    }


@router.post("/messages/merge")
def merge_messages(
    request: MergeMessagesRequest,
    db: DBSession = Depends(get_db)
):
    """
    合并多条消息为一个对话块
    """
    admin_service = AdminService()
    
    staging = admin_service.merge_messages(request.message_ids, db)
    
    if not staging:
        raise HTTPException(status_code=400, detail="合并失败")
    
    return {
        'success': True,
        'staging_id': staging.id,
        'message': '合并成功'
    }


@router.post("/bulk-filter")
def bulk_filter(
    request: BulkFilterRequest,
    db: DBSession = Depends(get_db)
):
    """
    批量过滤：根据关键词批量标记消息
    自动过滤群聊和2025年10月以前的数据
    """
    from app.services.admin import MIN_TIMESTAMP
    
    query = db.query(RawChat).filter(
        RawChat.content.like(f"%{request.keyword}%"),
        ~RawChat.session_id.like('%@chatroom'),  # 排除群聊
        RawChat.timestamp >= MIN_TIMESTAMP  # 只处理2025年10月以后的数据
    )
    
    if request.session_ids:
        # 过滤掉群聊
        filtered_session_ids = [sid for sid in request.session_ids if not sid.endswith('@chatroom')]
        if filtered_session_ids:
            query = query.filter(RawChat.session_id.in_(filtered_session_ids))
        else:
            # 如果所有都是群聊，返回空结果
            return {
                'success': True,
                'updated': 0,
                'keyword': request.keyword
            }
    
    messages = query.all()
    
    updated_count = 0
    for msg in messages:
        if request.action == 'reject':
            msg.status = 'rejected'
            msg.auto_flags = {'bulk_filtered': request.keyword}
        elif request.action == 'approve':
            msg.status = 'approved'
        updated_count += 1
    
    db.commit()
    
    return {
        'success': True,
        'updated': updated_count,
        'keyword': request.keyword
    }


@router.post("/staging/{staging_id}/publish")
def publish_staging(
    staging_id: int,
    db: DBSession = Depends(get_db)
):
    """
    发布暂存区对话到生产区
    """
    admin_service = AdminService()
    
    success = admin_service.publish_to_production(staging_id, db)
    
    if not success:
        raise HTTPException(status_code=400, detail="发布失败，请先审核通过")
    
    return {
        'success': True,
        'message': '发布成功'
    }


@router.post("/clean-old-data")
def clean_old_data(
    db: DBSession = Depends(get_db)
):
    """
    清理旧数据：删除2025年10月以前和群聊的暂存区数据
    """
    from app.services.admin import MIN_TIMESTAMP
    
    # 删除2025年10月以前的数据
    deleted_old = db.query(StagingConversation).filter(
        StagingConversation.start_time < MIN_TIMESTAMP
    ).delete()
    
    # 删除群聊数据
    deleted_chatroom = db.query(StagingConversation).filter(
        StagingConversation.session_id.like('%@chatroom')
    ).delete()
    
    db.commit()
    
    return {
        'success': True,
        'deleted_old_time': deleted_old,
        'deleted_chatroom': deleted_chatroom,
        'total_deleted': deleted_old + deleted_chatroom,
        'message': f'已清理 {deleted_old + deleted_chatroom} 条旧数据（时间过滤: {deleted_old}, 群聊过滤: {deleted_chatroom}）'
    }


@router.get("/stats")
def get_admin_stats(
    db: DBSession = Depends(get_db)
):
    """
    获取后台管理统计信息
    自动过滤群聊和2025年10月以前的数据
    包含会话级别统计（已处理/未处理会话数）
    """
    try:
        from app.services.admin import MIN_TIMESTAMP
        from sqlalchemy import inspect, func
        inspector = inspect(db.bind)
        raw_chat_columns = [col['name'] for col in inspector.get_columns('raw_chats')] if 'raw_chats' in inspector.get_table_names() else []
        has_status_field = 'status' in raw_chat_columns
        
        base_query = db.query(RawChat).filter(
            ~RawChat.session_id.like('%@chatroom'),
            RawChat.timestamp >= MIN_TIMESTAMP
        )
        
        total_raw = base_query.count()
        if has_status_field:
            pending_raw = base_query.filter(RawChat.status == 'pending').count()
            approved_raw = base_query.filter(RawChat.status == 'approved').count()
            rejected_raw = base_query.filter(RawChat.status == 'rejected').count()
        else:
            pending_raw = total_raw
            approved_raw = 0
            rejected_raw = 0
        
        staging_table_exists = 'staging_conversations' in inspector.get_table_names()
        
        # 会话级别统计
        total_sessions = db.query(func.count(func.distinct(RawChat.session_id))).filter(
            ~RawChat.session_id.like('%@chatroom'),
            RawChat.timestamp >= MIN_TIMESTAMP
        ).scalar() or 0
        
        if staging_table_exists:
            processed_session_ids_subq = db.query(
                func.distinct(StagingConversation.session_id)
            ).subquery()
            
            processed_sessions = db.query(
                func.count(func.distinct(StagingConversation.session_id))
            ).filter(
                ~StagingConversation.session_id.like('%@chatroom'),
                StagingConversation.start_time >= MIN_TIMESTAMP
            ).scalar() or 0
            
            unprocessed_sessions = db.query(
                func.count(func.distinct(RawChat.session_id))
            ).filter(
                ~RawChat.session_id.like('%@chatroom'),
                RawChat.timestamp >= MIN_TIMESTAMP,
                ~RawChat.session_id.in_(processed_session_ids_subq)
            ).scalar() or 0
            
            staging_base_query = db.query(StagingConversation).filter(
                ~StagingConversation.session_id.like('%@chatroom'),
                StagingConversation.start_time >= MIN_TIMESTAMP
            )
            
            total_staging = staging_base_query.count()
            pending_staging = staging_base_query.filter(
                StagingConversation.status == LabelStatus.PENDING.value
            ).count()
            approved_staging = staging_base_query.filter(
                StagingConversation.status == LabelStatus.APPROVED.value
            ).count()
            rejected_staging = staging_base_query.filter(
                StagingConversation.status == LabelStatus.REJECTED.value
            ).count()
        else:
            total_staging = 0
            pending_staging = 0
            approved_staging = 0
            rejected_staging = 0
            processed_sessions = 0
            unprocessed_sessions = total_sessions
        
        return {
            'raw_chats': {
                'total': total_raw,
                'pending': pending_raw,
                'approved': approved_raw,
                'rejected': rejected_raw
            },
            'sessions': {
                'total': total_sessions,
                'processed': processed_sessions,
                'unprocessed': unprocessed_sessions,
            },
            'staging_conversations': {
                'total': total_staging,
                'pending': pending_staging,
                'approved': approved_staging,
                'rejected': rejected_staging
            }
        }
    except Exception as e:
        import traceback
        error_detail = str(e)
        traceback_str = traceback.format_exc()
        print(f"[ERROR] Admin stats error: {error_detail}")
        print(traceback_str)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get admin stats: {error_detail}. Please check if database tables are created. Restart the backend to create tables."
        )


@router.post("/relink-voice")
def relink_voice_files(
    db: DBSession = Depends(get_db)
):
    """
    语音文件补链：扫描 Voice 目录，更新数据库中语音消息的 voice_path
    用于 ETL 导入后补充上传的语音文件
    """
    import os
    from app.config import get_settings
    settings = get_settings()

    voice_dir = settings.voice_file_path
    if not os.path.exists(voice_dir):
        raise HTTPException(status_code=400, detail=f"语音目录不存在: {voice_dir}")

    # 1. 加载所有 mp3 文件名（不含后缀）
    voice_keys = set()
    for f in os.listdir(voice_dir):
        if f.endswith('.mp3'):
            voice_keys.add(f[:-4])

    if not voice_keys:
        return {"success": True, "linked": 0, "message": "语音目录为空，无文件可链接"}

    # 2. 查询所有 voice_path 为空的语音消息 (msg_type=34)
    voice_messages = db.query(RawChat).filter(
        RawChat.msg_type == 34,
        (RawChat.voice_path == None) | (RawChat.voice_path == '')
    ).all()

    # 3. 匹配并更新
    linked = 0
    for msg in voice_messages:
        if msg.msg_server_id and str(msg.msg_server_id) in voice_keys:
            msg.voice_path = f"Voice/{msg.msg_server_id}.mp3"
            linked += 1

    db.commit()

    return {
        "success": True,
        "voice_files_found": len(voice_keys),
        "voice_messages_without_path": len(voice_messages),
        "linked": linked,
        "message": f"成功补链 {linked} 条语音消息"
    }


@router.post("/etl")
def trigger_etl(
    clear_existing: bool = Query(False, description="是否先清除现有数据再导入（用于数据源更换/更新）"),
    db: DBSession = Depends(get_db)
):
    """
    手动触发 ETL 数据导入：从微信 SQLite 导入到 PostgreSQL
    
    - clear_existing=false: 增量导入（默认，联系人使用 upsert）
    - clear_existing=true: 清除旧数据后全量重新导入（用于切换数据源或数据更新）
    """
    from app.services.etl import WeChatETL
    
    try:
        etl = WeChatETL()
        stats = etl.run_full_etl(db, clear_existing=clear_existing)
        return {
            'success': True,
            'message': 'ETL 导入完成' + ('（已清除旧数据）' if clear_existing else ''),
            'stats': stats
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"ETL 导入失败: {str(e)}"
        )
