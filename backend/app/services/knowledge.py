# -*- coding: utf-8 -*-
"""
知识库构建服务
负责对话切片、摘要提取、向量入库
"""
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import and_

from app.config import get_settings
from app.models.chat import Contact, Session, RawChat, KnowledgeChunk, HAS_PGVECTOR
from app.services.embedding import get_embedding_service

settings = get_settings()

# 时间过滤：只处理 2025年10月 及以后的数据（与 admin.py 保持一致）
MIN_TIMESTAMP = 1759248000  # 2025-10-01 00:00:00 CST


class KnowledgeBuilder:
    """知识库构建器"""
    
    # 噪音词/短回复集合（这些单独不构成有价值的知识）
    FILLER_WORDS = {
        '好的', '好', '嗯', '嗯嗯', '哦', '哦哦', 'ok', 'OK', 'Ok',
        '收到', '谢谢', '感谢', '了解', '明白', '知道了', '好吧',
        '是的', '对', '对的', '没错', '行', '行的', '可以', '好嘞',
        '哈哈', '哈哈哈', '哈哈哈哈', '呵呵', '嘿嘿', '666', '👍',
        '抱歉', '不好意思', '没事', '没关系', '客气', '不客气',
        '早', '晚安', '你好', '在吗', '在', '嗯呢', '好哒', '好滴',
        '是吗', '真的吗', '这样啊', '原来如此', '好吧好吧',
    }
    
    # 小蚕客服领域高价值关键词（用于关键词提取 + 质量评分）
    SALES_KEYWORDS = {
        '红包', '优惠', '折扣', '活动', '限时', '福利', '力度', '券', '神券',
        '返利', '霸王餐', '外卖', '到店', '探店', '提现', '积分', '盲盒',
        '下单', '订单', '支付', '退款', '到账', '账号', '登录', '绑定',
        '美团', '饿了么', '京东', '淘宝闪购', '茶百道', '沪上阿姨', '霸王茶姬', '奈雪', '茶颜悦色',
        '怎么领', '怎么用', '怎么参加', '适合', '新人', '怎么省钱',
        '投诉', '中签', '评价', '代金券', '五折',
    }
    
    def __init__(self, db_session: DBSession, use_filter: bool = True):
        self.db = db_session
        self.embedding_service = get_embedding_service()
        self.use_filter = use_filter
        # 从配置读取参数（替代硬编码）
        self.TIME_WINDOW_SECONDS = settings.chunk_time_window_seconds
        self.MIN_CHUNK_MESSAGES = settings.chunk_min_messages
        self.MAX_CHUNK_MESSAGES = settings.chunk_max_messages
        self.MIN_CHUNK_CONTENT_LENGTH = settings.chunk_min_content_length
        self.MIN_CHUNK_QUALITY_SCORE = settings.chunk_min_quality_score
        if use_filter:
            from app.services.filter import get_data_filter
            self.data_filter = get_data_filter()
        else:
            self.data_filter = None
    
    def build_chunks_for_session(self, session_id: str) -> int:
        """
        为指定会话构建知识分块
        返回: 创建的分块数量
        """
        # 过滤群聊：session_id 以 @chatroom 结尾的是群聊
        if session_id.endswith('@chatroom'):
            return 0
        
        # 检查会话是否在黑名单
        if self.data_filter and self.data_filter.filter_session(session_id):
            return 0
        
        # 获取该会话的所有文本消息（过滤时间）
        messages = self.db.query(RawChat).filter(
            RawChat.session_id == session_id,
            RawChat.msg_type == 1,  # 只处理文本消息
            RawChat.timestamp >= MIN_TIMESTAMP  # 只处理2025年10月以后的数据
        ).order_by(RawChat.timestamp).all()
        
        # 过滤消息
        if self.data_filter:
            filtered_messages = []
            for msg in messages:
                should_include, _ = self.data_filter.should_include(
                    msg.content or '', msg.msg_type
                )
                if should_include:
                    filtered_messages.append(msg)
            messages = filtered_messages
        
        if len(messages) < self.MIN_CHUNK_MESSAGES:
            return 0
        
        # 清理该会话旧的 chat 类型知识块
        self.db.query(KnowledgeChunk).filter(
            KnowledgeChunk.session_id == session_id,
            KnowledgeChunk.chunk_type == 'chat'
        ).delete()
        
        # 按时间窗口切片
        chunks = self._split_by_time_window(messages)
        
        # 为每个分块生成向量
        created = 0
        for chunk_messages in chunks:
            chunk = self._create_chunk(session_id, chunk_messages)
            if chunk:
                self.db.add(chunk)
                created += 1
        
        self.db.commit()
        return created
    
    def _split_by_time_window(self, messages: List[RawChat]) -> List[List[RawChat]]:
        """
        按时间窗口切分消息
        规则: 同一会话中，时间间隔不超过 5 分钟的连续对话合并为一个 Chunk
        """
        if not messages:
            return []
        
        chunks = []
        current_chunk = [messages[0]]
        
        for i in range(1, len(messages)):
            prev_msg = messages[i - 1]
            curr_msg = messages[i]
            
            time_diff = curr_msg.timestamp - prev_msg.timestamp
            
            # 如果时间差超过窗口，或者当前分块已满，开始新分块
            if time_diff > self.TIME_WINDOW_SECONDS or len(current_chunk) >= self.MAX_CHUNK_MESSAGES:
                if len(current_chunk) >= self.MIN_CHUNK_MESSAGES:
                    chunks.append(current_chunk)
                current_chunk = [curr_msg]
            else:
                current_chunk.append(curr_msg)
        
        # 处理最后一个分块
        if len(current_chunk) >= self.MIN_CHUNK_MESSAGES:
            chunks.append(current_chunk)
        
        return chunks
    
    def _create_chunk(self, session_id: str, messages: List[RawChat]) -> Optional[KnowledgeChunk]:
        """
        创建知识分块
        """
        import json
        
        if not messages:
            return None
        
        # 构建对话文本块（带发送者前缀，用于展示）
        content_lines = []
        for msg in messages:
            sender = msg.sender_name or msg.sender_wxid or '未知'
            content = msg.content or ''
            content_lines.append(f"{sender}: {content}")
        
        content_block = "\n".join(content_lines)
        
        # 内容长度门槛：过短的 chunk 没有知识价值
        if len(content_block.strip()) < self.MIN_CHUNK_CONTENT_LENGTH:
            return None
        
        # 质量评分门槛：整块内容是否有价值
        quality_score = self._score_chunk_quality(messages)
        if quality_score < self.MIN_CHUNK_QUALITY_SCORE:
            return None
        
        # 清洗文本后再生成 embedding（去噪音，提升语义精度）
        clean_text = self._clean_text_for_embedding(messages)
        embedding = self.embedding_service.embed_text(clean_text)
        
        # 智能摘要：取最长的实质消息作为摘要，而非简单截断
        topic_summary = self._generate_smart_summary(messages)
        
        # 增强版关键词提取（正则 + 销售领域术语）
        keywords = self._extract_keywords(content_block)
        
        # pgvector 直接传 list，SQLite 需要 JSON 序列化
        if HAS_PGVECTOR:
            embedding_data = embedding if embedding else None
            source_ids_data = [msg.id for msg in messages]
            keywords_data = keywords if keywords else None
        else:
            embedding_data = json.dumps(embedding) if embedding else None
            source_ids_data = json.dumps([msg.id for msg in messages])
            keywords_data = json.dumps(keywords) if keywords else None
        
        # 创建分块记录
        chunk = KnowledgeChunk(
            topic_summary=topic_summary,
            content_block=content_block,
            embedding=embedding_data,
            source_ids=source_ids_data,
            session_id=session_id,
            start_time=messages[0].timestamp,
            end_time=messages[-1].timestamp,
            keywords=keywords_data,
            entities=None,
            chunk_type='chat'
        )
        
        return chunk
    
    def _clean_text_for_embedding(self, messages: List[RawChat]) -> str:
        """
        清洗文本用于 embedding 生成（去除噪音，提升语义精度）
        - 去掉发送者名字前缀
        - 过滤 FILLER_WORDS
        - 去掉微信表情 [表情]
        - 只保留有实质内容的消息
        """
        clean_lines = []
        for msg in messages:
            content = (msg.content or '').strip()
            # 去掉微信表情标签
            content = re.sub(r'\[.+?\]', '', content).strip()
            # 跳过噪音词和过短内容
            if not content or content in self.FILLER_WORDS or len(content) <= 3:
                continue
            clean_lines.append(content)
        
        # 如果清洗后内容太少，退回用全量文本
        if len(clean_lines) < 2:
            return '\n'.join((msg.content or '') for msg in messages)
        
        return '\n'.join(clean_lines)
    
    def _generate_smart_summary(self, messages: List[RawChat]) -> str:
        """
        智能摘要：从 chunk 中提取最有代表性的内容作为摘要
        策略：取最长的实质消息（而非简单截断前 100 字）
        """
        # 找出最长的实质消息
        best_msg = ''
        best_len = 0
        for msg in messages:
            content = (msg.content or '').strip()
            clean = re.sub(r'\[.+?\]', '', content).strip()
            if clean and clean not in self.FILLER_WORDS and len(clean) > best_len:
                best_msg = content
                best_len = len(clean)
        
        if best_msg:
            # 截断到 200 字
            summary = best_msg[:200]
            if len(best_msg) > 200:
                summary += '...'
            return summary
        
        # 降级：前 100 字截断
        content_block = '\n'.join(f"{msg.sender_name or '未知'}: {msg.content or ''}" for msg in messages)
        return content_block[:100] + '...' if len(content_block) > 100 else content_block
    
    def _score_chunk_quality(self, messages: List[RawChat]) -> float:
        """
        对 chunk 进行规则质量评分（0~1）
        
        评分维度：
        1. 实质内容消息占比（非噪音词）
        2. 独立发言者数量（至少 2 人说明是对话）
        3. 平均消息长度
        4. 长消息数量（>20字的消息，代表有实际内容）
        5. 销售价值（命中销售领域关键词的消息数）
        """
        if not messages:
            return 0.0
        
        total = len(messages)
        
        # 维度1: 实质内容消息占比（权重 0.25）
        substantial_count = 0
        for msg in messages:
            content = (msg.content or '').strip()
            # 去除微信表情后判断
            clean = re.sub(r'\[.+?\]', '', content).strip()
            if clean and clean not in self.FILLER_WORDS and len(clean) > 5:
                substantial_count += 1
        substantial_ratio = substantial_count / total
        score_substantial = min(substantial_ratio / 0.5, 1.0)  # 50%+ 实质消息得满分
        
        # 维度2: 独立发言者数量（权重 0.15）
        speakers = set()
        for msg in messages:
            speaker = msg.sender_name or msg.sender_wxid or ''
            if speaker:
                speakers.add(speaker)
        if len(speakers) >= 2:
            score_speakers = 1.0  # 有对话交互
        elif len(speakers) == 1:
            score_speakers = 0.3  # 单人独白，价值有限
        else:
            score_speakers = 0.0
        
        # 维度3: 平均消息长度（权重 0.15）
        total_length = sum(len((msg.content or '').strip()) for msg in messages)
        avg_length = total_length / total if total > 0 else 0
        if avg_length >= 30:
            score_avg_len = 1.0
        elif avg_length >= 15:
            score_avg_len = 0.6
        elif avg_length >= 8:
            score_avg_len = 0.3
        else:
            score_avg_len = 0.1
        
        # 维度4: 长消息数量（>20字，权重 0.20）
        long_msg_count = sum(1 for msg in messages if len((msg.content or '').strip()) > 20)
        long_msg_ratio = long_msg_count / total
        score_long = min(long_msg_ratio / 0.3, 1.0)  # 30%+ 长消息得满分
        
        # 维度5: 销售价值 — 命中领域关键词的消息占比（权重 0.25）
        sales_hit_count = 0
        for msg in messages:
            content = (msg.content or '').strip()
            for keyword in self.SALES_KEYWORDS:
                if keyword in content:
                    sales_hit_count += 1
                    break  # 每条消息只计一次
        sales_hit_ratio = sales_hit_count / total
        score_sales = min(sales_hit_ratio / 0.3, 1.0)  # 30%+ 消息含销售关键词得满分
        
        # 加权总分
        quality_score = (
            score_substantial * 0.25 +
            score_speakers * 0.15 +
            score_avg_len * 0.15 +
            score_long * 0.20 +
            score_sales * 0.25
        )
        
        return round(quality_score, 3)
    
    def _extract_keywords(self, text: str) -> List[str]:
        """
        增强版关键词提取：
        - 正则提取 @mentions / #topics / URLs
        - 匹配销售领域高价值关键词
        """
        keywords = []
        
        # 提取 @mentions
        mentions = re.findall(r'@(\w+)', text)
        keywords.extend([f"@{m}" for m in mentions[:5]])
        
        # 提取 #topics
        topics = re.findall(r'#(\w+)', text)
        keywords.extend([f"#{t}" for t in topics[:5]])
        
        # 提取 URLs
        urls = re.findall(r'https?://\S+', text)
        keywords.extend(urls[:3])
        
        # 匹配销售领域关键词
        text_lower = text.lower()
        matched_sales = [kw for kw in self.SALES_KEYWORDS if kw in text_lower]
        keywords.extend(matched_sales[:10])  # 最多 10 个
        
        # 去重并返回
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)
        
        return unique_keywords
    
    def build_all_sessions(self, limit: Optional[int] = None) -> Dict[str, int]:
        """
        为所有会话构建知识分块
        自动排除群聊会话
        """
        from app.models.chat import Session
        
        query = self.db.query(Session).filter(
            ~Session.session_id.like('%@chatroom')  # 排除群聊
        )
        if limit:
            query = query.limit(limit)
        
        sessions = query.all()
        stats = {}
        skipped = 0
        
        for i, session in enumerate(sessions):
            print(f"[{i+1}/{len(sessions)}] Building chunks for: {session.session_id}")
            count = self.build_chunks_for_session(session.session_id)
            if count > 0:
                stats[session.session_id] = count
                print(f"  Created {count} chunks")
            else:
                skipped += 1
        
        print(f"\n[Summary] Created chunks for {len(stats)} sessions, skipped {skipped} sessions")
        return stats
    
    def build_from_labeled_data(self, clear_existing: bool = True) -> Dict[str, int]:
        """
        从已标注（已通过）的暂存区数据构建知识库
        只清理 labeled 类型的旧数据，不影响 chat 类型
        
        Args:
            clear_existing: 是否清空现有 labeled 知识块
            
        Returns:
            构建统计信息
        """
        import json
        from app.models.chat import StagingConversation
        
        # 1. 只清理 labeled 类型的旧知识块
        deleted = 0
        if clear_existing:
            deleted = self.db.query(KnowledgeChunk).filter(
                KnowledgeChunk.chunk_type == 'labeled'
            ).delete()
            self.db.commit()
            print(f"Deleted {deleted} existing labeled chunks")
        
        # 2. 获取已通过的标注数据
        approved = self.db.query(StagingConversation).filter(
            StagingConversation.status == 'approved'
        ).all()
        
        print(f"Found {len(approved)} approved conversations")
        
        # 3. 为每条构建知识块
        created = 0
        for i, staging in enumerate(approved):
            chunk = self._create_chunk_from_staging(staging)
            if chunk:
                self.db.add(chunk)
                created += 1
            
            if (i + 1) % 50 == 0:
                print(f"  Processed {i + 1}/{len(approved)}")
        
        self.db.commit()
        print(f"Created {created} chunks from labeled data")
        
        return {
            'total_approved': len(approved),
            'chunks_created': created,
            'deleted_old': deleted
        }
    
    def _create_chunk_from_staging(self, staging) -> Optional[KnowledgeChunk]:
        """
        从暂存区对话创建知识分块
        """
        import json
        
        # 使用清洗后的文本，如果没有则使用原始文本
        content_block = staging.cleaned_text or staging.original_text
        
        if not content_block or len(content_block.strip()) < 20:
            return None
        
        # 生成向量
        embedding = self.embedding_service.embed_text(content_block)
        
        # 生成摘要 - 优先使用 AI 生成的问题作为摘要
        if staging.auto_question:
            topic_summary = staging.auto_question[:200]
        elif staging.human_question:
            topic_summary = staging.human_question[:200]
        else:
            topic_summary = content_block[:100] + "..." if len(content_block) > 100 else content_block
        
        # 提取关键词
        keywords = self._extract_keywords(content_block)
        
        # pgvector 直接传 list，SQLite 需要 JSON 序列化
        if HAS_PGVECTOR:
            embedding_data = embedding if embedding else None
            source_ids_data = staging.source_message_ids or []
            keywords_data = keywords if keywords else None
        else:
            embedding_data = json.dumps(embedding) if embedding else None
            source_ids_data = json.dumps(staging.source_message_ids) if staging.source_message_ids else "[]"
            keywords_data = json.dumps(keywords) if keywords else None
        
        # 创建分块记录
        chunk = KnowledgeChunk(
            topic_summary=topic_summary,
            content_block=content_block,
            embedding=embedding_data,
            source_ids=source_ids_data,
            session_id=staging.session_id,
            start_time=staging.start_time,
            end_time=staging.end_time,
            keywords=keywords_data,
            entities=None,
            chunk_type='labeled'  # 标记为来自标注数据
        )
        
        return chunk


class SemanticSearch:
    """语义搜索服务"""
    
    def __init__(self, db_session: DBSession):
        self.db = db_session
        self.embedding_service = get_embedding_service()
    
    def _parse_json_field(self, value):
        """解析可能是 JSON 字符串或原生 list 的字段"""
        import json
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except:
                return []
        return []
    
    def search(
        self,
        query: str,
        limit: int = 5,
        session_id: Optional[str] = None
    ) -> List[Dict]:
        """
        语义搜索
        返回最相关的知识分块
        - pgvector: 使用 SQL 原生向量距离排序（高效）
        - SQLite: 全量加载 + Python 计算余弦（降级）
        """
        import json
        import numpy as np

        from app.models.chat import KnowledgeChunk

        # 生成查询向量
        query_embedding = self.embedding_service.embed_text(query)

        if HAS_PGVECTOR:
            return self._search_pgvector(query_embedding, limit, session_id)
        else:
            return self._search_fallback(query_embedding, limit, session_id)

    def _search_pgvector(
        self,
        query_embedding: List[float],
        limit: int,
        session_id: Optional[str]
    ) -> List[Dict]:
        """pgvector 原生查询：SQL 层完成向量排序 + limit"""
        import json
        from sqlalchemy import text, literal_column
        from app.models.chat import KnowledgeChunk

        # 多取一些候选，以便后续加权后重排
        fetch_limit = limit * 3

        # 构建 SQL — 使用 pgvector 的 <=> 余弦距离算子
        # cosine_distance = 1 - cosine_similarity，所以 similarity = 1 - distance
        vec_str = '[' + ','.join(str(v) for v in query_embedding) + ']'

        filters = []
        params: dict = {'vec': vec_str, 'fetch_limit': fetch_limit}

        if session_id:
            filters.append("session_id = :session_id")
            params['session_id'] = session_id

        where_clause = ('WHERE ' + ' AND '.join(filters)) if filters else ''

        sql = text(f"""
            SELECT id, topic_summary, content_block, source_ids,
                   session_id, start_time, end_time, keywords, chunk_type,
                   1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM knowledge_chunks
            {where_clause}
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :fetch_limit
        """)

        rows = self.db.execute(sql, params).fetchall()

        results = []
        for row in rows:
            sim = float(row.similarity)
            # labeled 类型加权
            if row.chunk_type == 'labeled':
                sim *= 1.2
            results.append({
                'id': row.id,
                'topic_summary': row.topic_summary,
                'content_block': row.content_block,
                'source_ids': self._parse_json_field(row.source_ids),
                'session_id': row.session_id,
                'start_time': row.start_time,
                'end_time': row.end_time,
                'keywords': self._parse_json_field(row.keywords),
                'similarity': sim,
                'source': row.chunk_type or 'chat'
            })

        # 加权后重排
        results.sort(key=lambda x: x['similarity'], reverse=True)
        print(f"[Search/pgvector] Returning {min(limit, len(results))} of {len(results)} candidates")
        return results[:limit]

    def _search_fallback(
        self,
        query_embedding: List[float],
        limit: int,
        session_id: Optional[str]
    ) -> List[Dict]:
        """SQLite 降级：内存计算余弦相似度"""
        import json
        import numpy as np
        from app.models.chat import KnowledgeChunk

        query_vec = np.array(query_embedding)

        db_query = self.db.query(KnowledgeChunk)
        if session_id:
            db_query = db_query.filter(KnowledgeChunk.session_id == session_id)

        chunks = db_query.all()
        print(f"[Search/fallback] Found {len(chunks)} chunks, query dim: {query_vec.shape}")

        results = []
        for chunk in chunks:
            if chunk.embedding is None:
                continue
            try:
                raw = chunk.embedding
                if isinstance(raw, str):
                    if not raw.strip():
                        continue
                    chunk_vec = np.array(json.loads(raw))
                elif isinstance(raw, list):
                    chunk_vec = np.array(raw)
                else:
                    chunk_vec = np.array(raw)

                if chunk_vec.size == 0:
                    continue

                similarity = float(
                    np.dot(query_vec, chunk_vec)
                    / (np.linalg.norm(query_vec) * np.linalg.norm(chunk_vec))
                )
                weighted_similarity = similarity * (1.2 if chunk.chunk_type == 'labeled' else 1.0)

                results.append({
                    'id': chunk.id,
                    'topic_summary': chunk.topic_summary,
                    'content_block': chunk.content_block,
                    'source_ids': self._parse_json_field(chunk.source_ids),
                    'session_id': chunk.session_id,
                    'start_time': chunk.start_time,
                    'end_time': chunk.end_time,
                    'keywords': self._parse_json_field(chunk.keywords),
                    'similarity': weighted_similarity,
                    'source': chunk.chunk_type or 'chat'
                })
            except Exception as e:
                print(f"[Search/fallback] Error processing chunk {chunk.id}: {e}")
                continue

        results.sort(key=lambda x: x['similarity'], reverse=True)
        print(f"[Search/fallback] Returning {min(limit, len(results))} of {len(results)} results")
        return results[:limit]

