# -*- coding: utf-8 -*-
"""
知识库和 AI 相关 API
"""
from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session as DBSession
from typing import List, Optional
from pydantic import BaseModel

from app.models.database import get_db
from app.services.knowledge import KnowledgeBuilder, SemanticSearch
from app.services.rag import RAGService

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# ==================== 请求/响应模型 ====================

class BuildRequest(BaseModel):
    """构建知识库请求"""
    session_id: Optional[str] = None  # 指定会话，为空则全部构建
    limit: Optional[int] = None  # 限制会话数量


class SearchRequest(BaseModel):
    """语义搜索请求"""
    query: str
    limit: int = 5
    session_id: Optional[str] = None


class AskRequest(BaseModel):
    """RAG 问答请求"""
    question: str
    session_id: Optional[str] = None
    top_k: int = 3
    original_question: Optional[str] = None  # 优化反馈时传入原始问题，用于检索


class ChunkResponse(BaseModel):
    """知识分块响应"""
    id: int
    topic_summary: Optional[str]
    content_block: str
    session_id: str
    start_time: Optional[int]
    end_time: Optional[int]
    keywords: Optional[List[str]]
    similarity: float = 0


class AnswerResponse(BaseModel):
    """RAG 回答响应"""
    answer: str
    sources: List[dict]
    query: str


# ==================== API 端点 ====================

@router.post("/build")
def build_knowledge_base(
    request: BuildRequest,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db)
):
    """
    构建知识库（异步后台任务）
    立即返回，后台执行切片和向量化
    """
    if request.session_id:
        # 单个会话：同步执行（快）
        builder = KnowledgeBuilder(db)
        count = builder.build_chunks_for_session(request.session_id)
        return {"message": f"从聊天记录创建了 {count} 个知识块（会话 {request.session_id}）"}
    else:
        # 全量/批量构建：异步后台执行
        def _build_task(limit: Optional[int]):
            from app.models.database import get_session_local
            _SessionLocal = get_session_local()
            _db = _SessionLocal()
            try:
                builder = KnowledgeBuilder(_db)
                stats = builder.build_all_sessions(limit=limit)
                total = sum(stats.values())
                print(f"[后台任务] 知识库构建完成: 创建了 {total} 个知识块（{len(stats)} 个会话）")
            except Exception as e:
                print(f"[后台任务] 知识库构建失败: {e}")
            finally:
                _db.close()

        background_tasks.add_task(_build_task, request.limit)
        return {
            "message": "知识库构建任务已启动，正在后台执行...",
            "status": "processing"
        }


@router.post("/build-from-labeled")
def build_knowledge_from_labeled(
    db: DBSession = Depends(get_db),
    clear_existing: bool = True
):
    """
    从已标注数据构建知识库（推荐）
    使用人工审核通过的高质量数据构建知识库
    
    Args:
        clear_existing: 是否清空现有知识库，默认True
    """
    builder = KnowledgeBuilder(db)
    
    try:
        stats = builder.build_from_labeled_data(clear_existing=clear_existing)
        return {
            "success": True,
            "message": f"成功从 {stats['total_approved']} 条已标注数据创建了 {stats['chunks_created']} 个知识块",
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=List[ChunkResponse])
def semantic_search(
    request: SearchRequest,
    db: DBSession = Depends(get_db)
):
    """
    语义搜索
    根据自然语言查询搜索相关的聊天记录
    """
    search = SemanticSearch(db)
    results = search.search(
        query=request.query,
        limit=request.limit,
        session_id=request.session_id
    )
    
    return [
        ChunkResponse(
            id=r['id'],
            topic_summary=r['topic_summary'],
            content_block=r['content_block'],
            session_id=r['session_id'],
            start_time=r['start_time'],
            end_time=r['end_time'],
            keywords=r['keywords'],
            similarity=r['similarity']
        )
        for r in results
    ]


@router.post("/ask", response_model=AnswerResponse)
def ask_question(
    request: AskRequest,
    db: DBSession = Depends(get_db)
):
    """
    RAG 问答（非流式，向后兼容）
    """
    rag = RAGService(db)
    result = rag.answer(
        question=request.question,
        session_id=request.session_id,
        top_k=request.top_k,
        original_question=request.original_question
    )
    
    return AnswerResponse(**result)


@router.post("/ask/stream")
def ask_question_stream(
    request: AskRequest,
    db: DBSession = Depends(get_db)
):
    """
    RAG 流式问答
    通过 SSE (Server-Sent Events) 逐 token 返回回答
    """
    from fastapi.responses import StreamingResponse
    
    rag = RAGService(db)
    
    return StreamingResponse(
        rag.answer_stream(
            question=request.question,
            session_id=request.session_id,
            top_k=request.top_k,
            original_question=request.original_question
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/stats")
def get_knowledge_stats(db: DBSession = Depends(get_db)):
    """
    获取知识库统计信息
    """
    from app.models.chat import KnowledgeChunk, Session
    from sqlalchemy import func
    
    total_chunks = db.query(func.count(KnowledgeChunk.id)).scalar()
    total_sessions = db.query(func.count(Session.id)).scalar()
    
    # 每个会话的分块数
    chunks_per_session = db.query(
        KnowledgeChunk.session_id,
        func.count(KnowledgeChunk.id).label('count')
    ).group_by(KnowledgeChunk.session_id).all()
    
    return {
        "total_chunks": total_chunks,
        "total_sessions": total_sessions,
        "sessions_with_chunks": len(chunks_per_session),
        "avg_chunks_per_session": total_chunks / len(chunks_per_session) if chunks_per_session else 0
    }
