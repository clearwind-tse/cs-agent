# -*- coding: utf-8 -*-
"""
知识提炼服务
用 LLM 从原始对话中提炼结构化销售知识条目
"""
import json
import re
import traceback
from datetime import datetime
from typing import List, Dict, Optional

from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func

from app.config import get_settings
from app.models.chat import (
    KnowledgeChunk, KnowledgeArticle, StagingConversation, HAS_PGVECTOR,
)
from app.services.embedding import get_embedding_service

settings = get_settings()

# LLM 提炼 Prompt
EXTRACT_SYSTEM_PROMPT = """你是一个销售话术分析专家。请从以下对话中提炼出可复用的销售知识条目。

对话内容：
{conversation_text}

请提取出所有有价值的销售技巧，每条按以下 JSON 格式输出（返回一个 JSON 数组）：
[
  {{
    "scene": "一句话描述客户触发的场景",
    "scene_category": "分类（sales/objection/closing/followup/course/qa）",
    "customer_says": "客户的原话或典型说法",
    "recommended_response": "销售的回复话术（保持原始口语风格）",
    "key_points": ["要点1", "要点2"],
    "confidence": 0.0
  }}
]

规则：
1. 只提取对话中实际出现的话术，禁止编造
2. recommended_response 保持原始口语风格，不要书面化
3. 如果对话没有可提取的销售价值，返回空数组 []
4. confidence 根据对话完整性和话术质量打分（0.0~1.0）
5. 只返回 JSON 数组，不要有多余文字"""


class KnowledgeExtractor:
    """知识提炼器 — 用 LLM 从对话中提炼结构化知识条目"""

    def __init__(self, db_session: DBSession):
        self.db = db_session
        self.embedding_service = get_embedding_service()

    # ------------------------------------------------------------------ #
    #  公开方法
    # ------------------------------------------------------------------ #

    def extract_from_chunk(self, chunk_id: int) -> List[KnowledgeArticle]:
        """从单个 KnowledgeChunk 提炼知识条目"""
        chunk = self.db.query(KnowledgeChunk).get(chunk_id)
        if not chunk:
            return []

        articles = self._call_llm_extract(chunk.content_block)
        saved = []
        for item in articles:
            article = self._save_article(
                item,
                source_chunk_id=chunk.id,
                source_session_id=chunk.session_id,
                source_type='chat',
            )
            if article:
                saved.append(article)

        if saved:
            self.db.commit()
        return saved

    def extract_from_staging(self, staging_id: int) -> List[KnowledgeArticle]:
        """从一条已审核的 StagingConversation 提炼"""
        staging = self.db.query(StagingConversation).get(staging_id)
        if not staging:
            return []

        text = staging.cleaned_text or staging.original_text
        articles = self._call_llm_extract(text)
        saved = []
        for item in articles:
            article = self._save_article(
                item,
                source_chunk_id=None,
                source_session_id=staging.session_id,
                source_type='labeled',
            )
            if article:
                saved.append(article)

        if saved:
            self.db.commit()
        return saved

    def extract_all(self, source: str = 'both') -> Dict:
        """
        批量提炼全部数据

        Args:
            source: 'chat' — 仅 knowledge_chunks
                    'labeled' — 仅 approved staging
                    'both' — 两者并行
        Returns:
            统计信息
        """
        stats = {
            'chunks_processed': 0,
            'staging_processed': 0,
            'articles_created': 0,
            'errors': 0,
        }

        # 1) 从已审核的 staging 提炼（权重更高）
        if source in ('labeled', 'both'):
            approved = (
                self.db.query(StagingConversation)
                .filter(StagingConversation.status == 'approved')
                .all()
            )
            for staging in approved:
                try:
                    articles = self.extract_from_staging(staging.id)
                    stats['staging_processed'] += 1
                    stats['articles_created'] += len(articles)
                except Exception as e:
                    print(f"[Extractor] staging#{staging.id} 提炼失败: {e}")
                    traceback.print_exc()
                    stats['errors'] += 1

        # 2) 从 knowledge_chunks 提炼
        if source in ('chat', 'both'):
            chunks = self.db.query(KnowledgeChunk).all()
            for chunk in chunks:
                try:
                    articles = self.extract_from_chunk(chunk.id)
                    stats['chunks_processed'] += 1
                    stats['articles_created'] += len(articles)
                except Exception as e:
                    print(f"[Extractor] chunk#{chunk.id} 提炼失败: {e}")
                    traceback.print_exc()
                    stats['errors'] += 1

        return stats

    def get_stats(self) -> Dict:
        """获取提炼统计"""
        total = self.db.query(func.count(KnowledgeArticle.id)).scalar() or 0
        verified = (
            self.db.query(func.count(KnowledgeArticle.id))
            .filter(KnowledgeArticle.is_verified == True)
            .scalar()
        ) or 0
        by_category = (
            self.db.query(
                KnowledgeArticle.scene_category,
                func.count(KnowledgeArticle.id),
            )
            .group_by(KnowledgeArticle.scene_category)
            .all()
        )
        avg_confidence = (
            self.db.query(func.avg(KnowledgeArticle.confidence)).scalar()
        ) or 0.0

        return {
            'total_articles': total,
            'verified_articles': verified,
            'unverified_articles': total - verified,
            'avg_confidence': round(float(avg_confidence), 3),
            'by_category': {cat: cnt for cat, cnt in by_category},
        }

    # ------------------------------------------------------------------ #
    #  内部方法
    # ------------------------------------------------------------------ #

    def _call_llm_extract(self, conversation_text: str) -> List[Dict]:
        """调用 LLM 对一段对话做知识提炼，返回结构化 JSON 列表"""
        prompt = EXTRACT_SYSTEM_PROMPT.format(conversation_text=conversation_text)

        raw_text = self._call_llm(prompt)

        # 解析 JSON — 容忍 LLM 返回 markdown 代码块
        return self._parse_json_response(raw_text)

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM（优先 ark/dashscope → deepseek → openai）"""
        from openai import OpenAI

        if settings.ark_api_key and settings.ark_base_url:
            api_key, base_url, model = settings.ark_api_key, settings.ark_base_url, "qwen-plus"
        elif settings.deepseek_api_key:
            api_key, base_url, model = settings.deepseek_api_key, settings.deepseek_base_url, "deepseek-chat"
        elif settings.openai_api_key:
            api_key, base_url, model = settings.openai_api_key, settings.openai_base_url, "gpt-4o-mini"
        else:
            raise RuntimeError("未配置任何 LLM API (ark/deepseek/openai)")

        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _parse_json_response(text: str) -> List[Dict]:
        """从 LLM 返回中提取 JSON 数组，兼容 markdown 包裹"""
        # 去掉 markdown 代码块
        text = text.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'```\s*$', '', text)
        text = text.strip()

        if not text:
            return []
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return [result]
            return []
        except json.JSONDecodeError as e:
            print(f"[Extractor] JSON 解析失败: {e}\n原文: {text[:300]}")
            return []

    def _save_article(
        self,
        item: Dict,
        source_chunk_id: Optional[int],
        source_session_id: Optional[str],
        source_type: str,
    ) -> Optional[KnowledgeArticle]:
        """将 LLM 提炼的一条知识保存到数据库（带去重检查）"""
        scene = (item.get('scene') or '').strip()
        if not scene:
            return None

        customer_says = (item.get('customer_says') or '').strip()
        recommended_response = (item.get('recommended_response') or '').strip()
        if not recommended_response:
            return None

        # 向量：用 scene + customer_says 拼接
        embed_text = f"{scene} {customer_says}".strip()
        embedding = self.embedding_service.embed_text(embed_text)

        # 去重检查：与现有条目做余弦相似度比较
        if embedding and self._is_duplicate(embedding):
            return None

        # key_points 序列化（兼容 SQLite/PG）
        key_points_raw = item.get('key_points', [])
        if HAS_PGVECTOR:
            key_points_data = key_points_raw
            embedding_data = embedding if embedding else None
        else:
            key_points_data = json.dumps(key_points_raw, ensure_ascii=False) if key_points_raw else None
            embedding_data = json.dumps(embedding) if embedding else None

        article = KnowledgeArticle(
            scene=scene,
            scene_category=item.get('scene_category', 'sales'),
            customer_says=customer_says,
            recommended_response=recommended_response,
            key_points=key_points_data,
            embedding=embedding_data,
            source_chunk_id=source_chunk_id,
            source_session_id=source_session_id,
            source_type=source_type,
            confidence=float(item.get('confidence', 0.5)),
            is_verified=False,
            created_at=datetime.utcnow(),
        )
        self.db.add(article)
        return article

    def _is_duplicate(
        self, new_embedding: list, threshold: float = 0.90
    ) -> bool:
        """
        检查新条目是否与已有知识条目重复
        - PostgreSQL + pgvector: 使用原生 <=> 余弦距离算子（高效）
        - SQLite: 降级为全表加载 + Python 计算
        """
        if not new_embedding:
            return False

        if HAS_PGVECTOR:
            return self._is_duplicate_pgvector(new_embedding, threshold)
        else:
            return self._is_duplicate_fallback(new_embedding, threshold)

    def _is_duplicate_pgvector(
        self, new_embedding: list, threshold: float
    ) -> bool:
        """pgvector 原生去重：用 SQL 查最相似的一条，看是否超阈值"""
        from sqlalchemy import text

        vec_str = '[' + ','.join(str(v) for v in new_embedding) + ']'
        # cosine_distance = 1 - cosine_similarity
        # 所以 similarity >= threshold  等价于  distance <= 1 - threshold
        max_distance = 1.0 - threshold

        sql = text("""
            SELECT id, 1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM knowledge_articles
            WHERE embedding IS NOT NULL
              AND (embedding <=> CAST(:vec AS vector)) <= :max_distance
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT 1
        """)

        row = self.db.execute(
            sql, {'vec': vec_str, 'max_distance': max_distance}
        ).fetchone()

        if row:
            print(f"[Extractor] 跳过重复条目 (相似度={row.similarity:.3f}，已有 article#{row.id})")
            return True
        return False

    def _is_duplicate_fallback(
        self, new_embedding: list, threshold: float
    ) -> bool:
        """SQLite 降级：全表加载 + Python 余弦计算"""
        import numpy as np

        new_vec = np.array(new_embedding)
        if new_vec.size == 0:
            return False

        existing = self.db.query(KnowledgeArticle).all()
        for article in existing:
            if article.embedding is None:
                continue
            try:
                raw = article.embedding
                if isinstance(raw, str):
                    if not raw.strip():
                        continue
                    vec = np.array(json.loads(raw))
                elif isinstance(raw, list):
                    vec = np.array(raw)
                else:
                    vec = np.array(raw)

                if vec.size == 0:
                    continue

                similarity = float(
                    np.dot(new_vec, vec)
                    / (np.linalg.norm(new_vec) * np.linalg.norm(vec))
                )
                if similarity >= threshold:
                    print(f"[Extractor] 跳过重复条目 (相似度={similarity:.3f}，已有 article#{article.id})")
                    return True
            except Exception:
                continue

        return False


