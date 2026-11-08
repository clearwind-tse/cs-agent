# -*- coding: utf-8 -*-
"""
RAG (检索增强生成) 服务
结合语义搜索和 LLM 生成回答

升级版：优先从 knowledge_articles（结构化知识条目）检索，
命中不足时再从 knowledge_chunks（原始对话切片）补充。
"""
import json
import numpy as np
from typing import List, Dict, Optional, Generator
from sqlalchemy.orm import Session as DBSession

from app.config import get_settings
from app.models.chat import KnowledgeArticle, KnowledgeChunk, HAS_PGVECTOR
from app.services.knowledge import SemanticSearch
from app.services.embedding import get_embedding_service

settings = get_settings()

# 缓存：SQLite 模式下缓存 article embeddings 矩阵，避免每次查询全表加载
_article_cache: dict = {'embeddings': None, 'ids': None, 'version': 0}


class ArticleSearch:
    """从 knowledge_articles 表进行语义检索"""

    def __init__(self, db_session: DBSession):
        self.db = db_session
        self.embedding_service = get_embedding_service()

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        """语义搜索知识条目，返回按相似度排序的结果"""
        try:
            query_embedding = self.embedding_service.embed_text(query)
        except Exception as e:
            print(f"[ArticleSearch] Embedding 生成失败: {e}")
            return []

        if HAS_PGVECTOR:
            try:
                return self._search_pgvector(query_embedding, limit)
            except Exception as e:
                print(f"[ArticleSearch] pgvector 查询失败，降级到 fallback: {e}")
                self.db.rollback()  # 清除 aborted 事务状态
                return self._search_fallback(query_embedding, limit)
        else:
            return self._search_fallback(query_embedding, limit)

    def _search_pgvector(self, query_embedding: List[float], limit: int) -> List[Dict]:
        """使用 pgvector 原生向量距离排序（高效）"""
        from sqlalchemy import text

        fetch_limit = limit * 3
        vec_str = '[' + ','.join(str(v) for v in query_embedding) + ']'

        sql = text("""
            SELECT id, scene, scene_category, customer_says, recommended_response,
                   key_points, confidence, is_verified, source_type,
                   1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM knowledge_articles
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :fetch_limit
        """)

        rows = self.db.execute(sql, {'vec': vec_str, 'fetch_limit': fetch_limit}).fetchall()

        results = []
        for row in rows:
            sim = float(row.similarity)
            # 人工验证的条目加权
            if row.is_verified:
                sim *= 1.3
            # 已审核数据来源加权
            if row.source_type == 'labeled':
                sim *= 1.2

            results.append({
                'type': 'article',
                'id': row.id,
                'scene': row.scene,
                'scene_category': row.scene_category,
                'customer_says': row.customer_says,
                'recommended_response': row.recommended_response,
                'key_points': self._parse_json(row.key_points),
                'confidence': row.confidence or 0.0,
                'is_verified': row.is_verified,
                'similarity': sim,
            })

        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:limit]

    def _search_fallback(self, query_embedding: List[float], limit: int) -> List[Dict]:
        """全表加载 + 内存计算余弦相似度（SQLite 降级）"""
        query_vec = np.array(query_embedding)

        articles = self.db.query(KnowledgeArticle).all()
        if not articles:
            return []

        results = []
        for article in articles:
            if article.embedding is None:
                continue
            try:
                raw = article.embedding
                if isinstance(raw, np.ndarray):
                    vec = raw
                elif isinstance(raw, str):
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
                    np.dot(query_vec, vec)
                    / (np.linalg.norm(query_vec) * np.linalg.norm(vec))
                )

                # 人工验证的条目额外加权
                if article.is_verified:
                    similarity *= 1.3
                # 已审核数据来源加权
                if article.source_type == 'labeled':
                    similarity *= 1.2

                results.append({
                    'type': 'article',
                    'id': article.id,
                    'scene': article.scene,
                    'scene_category': article.scene_category,
                    'customer_says': article.customer_says,
                    'recommended_response': article.recommended_response,
                    'key_points': self._parse_json(article.key_points),
                    'confidence': article.confidence or 0.0,
                    'is_verified': article.is_verified,
                    'similarity': similarity,
                })
            except Exception as e:
                print(f"[ArticleSearch] Error processing article {article.id}: {e}")
                continue

        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:limit]

    @staticmethod
    def _parse_json(value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return []
        return []


class RAGService:
    """RAG 服务 — 优先知识条目，不足时降级对话切片"""

    def __init__(self, db_session: DBSession):
        self.db = db_session
        self.article_search = ArticleSearch(db_session)
        self.chunk_search = SemanticSearch(db_session)

    def answer(
        self,
        question: str,
        session_id: Optional[str] = None,
        top_k: int = 5,
        original_question: Optional[str] = None,
    ) -> Dict:
        """基于 RAG 回答问题（非流式）"""
        # 1. 检索（优先用原始问题）
        retrieve_query = original_question or question
        articles, chunks = self._retrieve(retrieve_query, session_id, top_k)

        if not articles and not chunks:
            return {
                'answer': '未找到相关的聊天记录。',
                'sources': [],
                'query': question,
            }

        # 2. 构建上下文
        context = self._build_context(articles, chunks)

        # 3. LLM 生成回答
        answer = self._generate_answer(question, context)

        return {
            'answer': answer,
            'sources': self._format_sources(articles, chunks),
            'query': question,
        }

    def answer_stream(
        self,
        question: str,
        session_id: Optional[str] = None,
        top_k: int = 5,
        original_question: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """基于 RAG 流式回答问题"""
        # 1. 检索（优先用原始问题）
        retrieve_query = original_question or question
        articles, chunks = self._retrieve(retrieve_query, session_id, top_k)

        if not articles and not chunks:
            yield f"data: {json.dumps({'type': 'sources', 'sources': []}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'content', 'content': '未找到相关的聊天记录。'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return

        # 2. 先发送 sources
        sources = self._format_sources(articles, chunks)
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"

        # 3. 构建上下文
        context = self._build_context(articles, chunks)

        # 4. 流式 LLM
        try:
            for token in self._generate_answer_stream(question, context):
                yield f"data: {json.dumps({'type': 'content', 'content': token}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': f'生成回答时出错: {str(e)}'}, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    # ------------------------------------------------------------------ #
    #  检索层
    # ------------------------------------------------------------------ #

    def _retrieve(
        self, question: str, session_id: Optional[str], top_k: int
    ) -> tuple:
        """
        混合检索：优先 knowledge_articles，不足再补 knowledge_chunks
        返回 (articles, chunks)
        阈值从配置读取，支持 .env 调整
        """
        article_threshold = settings.rag_article_similarity_threshold
        chunk_threshold = settings.rag_chunk_similarity_threshold
        
        # 先搜索知识条目
        try:
            articles = self.article_search.search(question, limit=top_k)
            good_articles = [a for a in articles if a['similarity'] >= article_threshold]
        except Exception as e:
            print(f"[RAG] ArticleSearch 失败: {e}")
            good_articles = []

        # 再搜索知识分块
        chunks = []
        try:
            need_supplement = max(top_k - len(good_articles), 2)
            all_chunks = self.chunk_search.search(
                query=question, limit=need_supplement, session_id=session_id
            )
            chunks = [c for c in all_chunks if c.get('similarity', 0) >= chunk_threshold]
        except Exception as e:
            print(f"[RAG] ChunkSearch 失败: {e}")

        return good_articles, chunks

    # ------------------------------------------------------------------ #
    #  上下文构建
    # ------------------------------------------------------------------ #

    def _build_context(self, articles: List[Dict], chunks: List[Dict]) -> str:
        """构建给 LLM 的上下文 — 结构化知识 + 原始对话补充，带字符数限制"""
        max_chars = settings.rag_context_max_chars
        parts = []
        total_chars = 0

        if articles:
            parts.append("## 匹配的销售知识\n")
            for i, a in enumerate(articles, 1):
                key_points_str = '、'.join(a.get('key_points', [])) if a.get('key_points') else ''
                block = f"""### 知识条目 {i}（匹配度 {a['similarity']:.2f}）
- 场景：{a['scene']}
- 客户原话：{a.get('customer_says', '无')}
- 推荐话术：
  {a.get('recommended_response', '无')}
- 要点：{key_points_str}"""
                if total_chars + len(block) > max_chars:
                    break
                parts.append(block)
                total_chars += len(block)

        if chunks and total_chars < max_chars:
            parts.append("\n## 补充的原始聊天记录\n")
            for i, c in enumerate(chunks, 1):
                block = f"[来源 {i}]\n{c['content_block']}"
                if total_chars + len(block) > max_chars:
                    # 截断最后一个 chunk 以填充剩余空间
                    remaining = max_chars - total_chars - 50
                    if remaining > 100:
                        parts.append(f"[来源 {i}]\n{c['content_block'][:remaining]}...")
                    break
                parts.append(block)
                total_chars += len(block)

        return "\n\n".join(parts)

    def _format_sources(self, articles: List[Dict], chunks: List[Dict]) -> List[Dict]:
        """格式化来源元数据"""
        sources = []
        for a in articles:
            sources.append({
                'id': a['id'],
                'type': 'article',
                'session_id': None,
                'summary': a['scene'],
                'similarity': a['similarity'],
            })
        for c in chunks:
            sources.append({
                'id': c['id'],
                'type': 'chunk',
                'session_id': c.get('session_id'),
                'summary': c.get('topic_summary'),
                'similarity': c.get('similarity', 0),
                'source_ids': c.get('source_ids', []),
            })
        return sources

    # ------------------------------------------------------------------ #
    #  LLM 调用
    # ------------------------------------------------------------------ #

    def _generate_answer(self, question: str, context: str) -> str:
        if settings.ark_api_key and settings.ark_base_url:
            return self._call_llm(question, context,
                api_key=settings.ark_api_key, base_url=settings.ark_base_url, model="qwen-plus")
        if settings.deepseek_api_key:
            return self._call_llm(question, context,
                api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url, model="deepseek-chat")
        if settings.openai_api_key:
            return self._call_llm(question, context,
                api_key=settings.openai_api_key, base_url=settings.openai_base_url, model="gpt-4o-mini")
        return f"[未配置 LLM API，以下是相关聊天记录]\n\n{context}"

    def _generate_answer_stream(self, question: str, context: str) -> Generator[str, None, None]:
        if settings.ark_api_key and settings.ark_base_url:
            yield from self._call_llm_stream(question, context,
                api_key=settings.ark_api_key, base_url=settings.ark_base_url, model="qwen-plus")
        elif settings.deepseek_api_key:
            yield from self._call_llm_stream(question, context,
                api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url, model="deepseek-chat")
        elif settings.openai_api_key:
            yield from self._call_llm_stream(question, context,
                api_key=settings.openai_api_key, base_url=settings.openai_base_url, model="gpt-4o-mini")
        else:
            yield f"[未配置 LLM API，以下是相关聊天记录]\n\n{context}"

    def _get_system_prompt(self) -> str:
        """融合版系统提示词 — 知识准确 + 本平台客服风格"""
        return """你是「本平台」，本平台（本平台霸王餐）的智能客服助手。你的回答要做到两个目标：

## 目标 1：知识准确
- 回答必须基于下方提供的「知识库」和「话术参考」
- 事实性信息（红包力度、返利规则、到账时间、活动门槛等）必须严格引用知识库内容
- 知识库没有的信息，直接说"这个我得帮你问一下，稍等"

## 目标 2：说话风格
- 专业又亲和，像微信聊天而不是生硬的客服机器人
- 不要用"亲"、"亲亲"等称呼，可称"您"
- 简洁有力，不啰嗦，能一句话说清楚的不用三句话
- 可以用标点，偶尔可用 emoji
- 涉及红包力度、返利金额可如实说明，不回避

## 风格示例
❌ "亲，您好，关于返利我们会在订单完成后为您处理的哦"
✅ "返利是按实付金额算的，订单完成后24小时内到账，您在本平台里下单才有返利"

## 回答策略
- 简单问题：直接回答，不超过3行
- 复杂问题：先给结论，再补充细节
- 报错/异常：先安抚，再给明确的处理办法
- 不确定的问题：坦诚说不知道，不编造"""

    def _get_user_prompt(self, question: str, context: str) -> str:
        return f"""## 数据源

{context}

---

## 用户问题
{question}

---

请基于数据源回答。要求：
- 事实准确，不编造
- 说话口语化，像微信聊天
- 简短有力，不啰嗦"""

    def _call_llm(self, question: str, context: str, *, api_key: str, base_url: str, model: str) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": self._get_user_prompt(question, context)},
            ],
            temperature=0.1,
            max_tokens=settings.rag_llm_max_tokens,
        )
        return response.choices[0].message.content

    def _call_llm_stream(self, question: str, context: str, *, api_key: str, base_url: str, model: str) -> Generator[str, None, None]:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": self._get_user_prompt(question, context)},
            ],
            temperature=0.1,
            max_tokens=settings.rag_llm_max_tokens,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
