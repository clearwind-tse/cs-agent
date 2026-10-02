# -*- coding: utf-8 -*-
"""
知识提炼 API
触发 LLM 提炼、查看 / 编辑 / 删除知识条目
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session as DBSession
from typing import Optional, List
from pydantic import BaseModel, Field

from app.models.database import get_db
from app.models.chat import KnowledgeArticle, HAS_PGVECTOR
from app.services.extractor import KnowledgeExtractor

router = APIRouter(prefix="/api/extractor", tags=["extractor"])


# ==================== 请求 / 响应模型 ====================

class ExtractRequest(BaseModel):
    """触发提炼请求"""
    source: str = Field(
        default="both",
        description="数据来源: chat | labeled | both",
    )


class ArticleResponse(BaseModel):
    """知识条目响应"""
    id: int
    scene: str
    scene_category: Optional[str] = None
    customer_says: Optional[str] = None
    recommended_response: Optional[str] = None
    key_points: Optional[list] = None
    source_chunk_id: Optional[int] = None
    source_session_id: Optional[str] = None
    source_type: Optional[str] = None
    confidence: float = 0.0
    is_verified: bool = False
    created_at: Optional[str] = None


class ArticleUpdateRequest(BaseModel):
    """编辑知识条目"""
    scene: Optional[str] = None
    scene_category: Optional[str] = None
    customer_says: Optional[str] = None
    recommended_response: Optional[str] = None
    key_points: Optional[list] = None
    is_verified: Optional[bool] = None


# ==================== 辅助函数 ====================

def _parse_json_field(value):
    """解析 JSON 或原生 list 字段"""
    import json as _json
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return _json.loads(value)
        except Exception:
            return None
    return value


def _article_to_response(article: KnowledgeArticle) -> ArticleResponse:
    return ArticleResponse(
        id=article.id,
        scene=article.scene,
        scene_category=article.scene_category,
        customer_says=article.customer_says,
        recommended_response=article.recommended_response,
        key_points=_parse_json_field(article.key_points),
        source_chunk_id=article.source_chunk_id,
        source_session_id=article.source_session_id,
        source_type=article.source_type,
        confidence=article.confidence or 0.0,
        is_verified=article.is_verified or False,
        created_at=article.created_at.isoformat() if article.created_at else None,
    )


# ==================== API 端点 ====================

@router.post("/extract")
def trigger_extraction(
    request: ExtractRequest,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db),
):
    """
    触发知识提炼（后台异步执行）
    """
    def _extract_task(source: str):
        from app.models.database import get_session_local
        _SessionLocal = get_session_local()
        _db = _SessionLocal()
        try:
            extractor = KnowledgeExtractor(_db)
            stats = extractor.extract_all(source=source)
            print(f"[后台任务] 知识提炼完成: {stats}")
        except Exception as e:
            print(f"[后台任务] 知识提炼失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            _db.close()

    background_tasks.add_task(_extract_task, request.source)
    return {
        "message": "知识提炼任务已启动，正在后台执行...",
        "source": request.source,
        "status": "processing",
    }


@router.get("/articles", response_model=List[ArticleResponse])
def list_articles(
    category: Optional[str] = Query(None, description="按分类过滤"),
    verified: Optional[bool] = Query(None, description="按验证状态过滤"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: DBSession = Depends(get_db),
):
    """查看提炼的知识条目列表"""
    query = db.query(KnowledgeArticle)

    if category:
        query = query.filter(KnowledgeArticle.scene_category == category)
    if verified is not None:
        query = query.filter(KnowledgeArticle.is_verified == verified)

    query = query.order_by(KnowledgeArticle.confidence.desc())
    articles = query.offset(skip).limit(limit).all()

    return [_article_to_response(a) for a in articles]


@router.put("/articles/{article_id}", response_model=ArticleResponse)
def update_article(
    article_id: int,
    request: ArticleUpdateRequest,
    db: DBSession = Depends(get_db),
):
    """编辑 / 验证知识条目"""
    article = db.query(KnowledgeArticle).get(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="知识条目不存在")

    update_data = request.dict(exclude_unset=True)
    need_re_embed = False

    for field, value in update_data.items():
        if field == "key_points" and value is not None:
            import json as _json
            if not HAS_PGVECTOR:
                value = _json.dumps(value, ensure_ascii=False)
        if field in ("scene", "customer_says"):
            need_re_embed = True
        setattr(article, field, value)

    # 更新向量
    if need_re_embed:
        from app.services.embedding import get_embedding_service
        embed_svc = get_embedding_service()
        embed_text = f"{article.scene} {article.customer_says or ''}".strip()
        embedding = embed_svc.embed_text(embed_text)
        if HAS_PGVECTOR:
            article.embedding = embedding if embedding else None
        else:
            import json as _json
            article.embedding = _json.dumps(embedding) if embedding else None

    db.commit()
    db.refresh(article)
    return _article_to_response(article)


@router.delete("/articles/{article_id}")
def delete_article(
    article_id: int,
    db: DBSession = Depends(get_db),
):
    """删除知识条目"""
    article = db.query(KnowledgeArticle).get(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="知识条目不存在")

    db.delete(article)
    db.commit()
    return {"message": f"已删除知识条目 #{article_id}"}


@router.get("/stats")
def get_extractor_stats(db: DBSession = Depends(get_db)):
    """获取提炼统计信息"""
    extractor = KnowledgeExtractor(db)
    return extractor.get_stats()
