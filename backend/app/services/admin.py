# -*- coding: utf-8 -*-
"""
后台管理服务
用于数据预处理、会话流构建、Q&A提取等
"""
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json

from app.models.chat import RawChat, StagingConversation, LabelStatus
from app.services.filter import DataFilter, get_data_filter
from app.services.quality_scorer import LLMQualityScorer
from app.services.staging_text import normalize_conversation_json, rebuild_cleaned_text
from app.config import get_settings

settings = get_settings()

# 时间过滤：只处理 2025年10月 及以后的数据
# 2025-10-01 00:00:00 北京时间 的 Unix 时间戳（秒级）
MIN_TIMESTAMP = 1759248000  # 2025-10-01 00:00:00 CST


class AdminService:
    """后台管理服务"""
    
    def __init__(self):
        self.data_filter = get_data_filter()
        self.quality_scorer = LLMQualityScorer() if (settings.deepseek_api_key or settings.openai_api_key) else None
    
    def preprocess_session(self, db_session, session_id: str, 
                          window_seconds: int = 300) -> int:
        """
        预处理会话：将原始消息转换为暂存区对话块
        
        Args:
            db_session: 数据库会话
            session_id: 会话ID
            window_seconds: 对话窗口（秒），超过此时间间隔视为新对话
        
        Returns:
            创建的暂存区对话块数量
        """
        # 过滤群聊：session_id 以 @chatroom 结尾的是群聊
        if session_id.endswith('@chatroom'):
            return 0
        
        # 获取该会话的所有消息（按时间排序），过滤时间
        messages = db_session.query(RawChat).filter(
            RawChat.session_id == session_id,
            RawChat.timestamp >= MIN_TIMESTAMP  # 只处理2025年10月以后的数据
        ).order_by(RawChat.timestamp).all()
        
        if not messages:
            return 0
        
        conversation_blocks = self._build_conversation_blocks(messages, window_seconds)
        
        if not conversation_blocks:
            # All messages were filtered out — create a rejected marker
            # so this session won't be re-processed in future batches.
            marker = StagingConversation(
                original_text='',
                cleaned_text='',
                conversation_json=[],
                session_id=session_id,
                source_message_ids=[],
                start_time=messages[0].timestamp,
                end_time=messages[-1].timestamp,
                auto_category='junk',
                auto_quality_score=0,
                auto_flags={'empty_session': True, 'all_filtered': True},
                status=LabelStatus.REJECTED.value
            )
            db_session.add(marker)
            db_session.commit()
            return 0
        
        created_count = 0
        for block in conversation_blocks:
            existing = db_session.query(StagingConversation).filter(
                StagingConversation.session_id == session_id,
                StagingConversation.start_time == block['start_time'],
                StagingConversation.end_time == block['end_time']
            ).first()
            
            if existing:
                continue
            
            auto_category, auto_flags = self._auto_classify_block(block['cleaned_text'])
            auto_quality = self._auto_quality_score(block['cleaned_text'])
            question, answer = self._extract_qa(block['cleaned_text'])
            
            staging = StagingConversation(
                original_text=block['original_text'],
                cleaned_text=block['cleaned_text'],
                conversation_json=block['conversation_json'],
                session_id=session_id,
                source_message_ids=block['message_ids'],
                start_time=block['start_time'],
                end_time=block['end_time'],
                auto_question=question,
                auto_answer=answer,
                auto_category=auto_category,
                auto_quality_score=auto_quality,
                auto_flags=auto_flags,
                status=LabelStatus.PENDING.value
            )
            
            db_session.add(staging)
            created_count += 1
        
        db_session.commit()
        return created_count
    
    def _build_conversation_blocks(self, messages: List[RawChat], 
                                   window_seconds: int) -> List[Dict]:
        """
        将消息列表构建为对话块
        
        规则：
        1. 按时间窗口切分（超过window_seconds视为新对话）
        2. 过滤掉垃圾、系统消息等
        3. 合并连续的消息（同一人连续发送）
        """
        blocks = []
        current_block = {
            'messages': [],
            'start_time': None,
            'end_time': None,
            'original_text': '',
            'cleaned_text': '',
            'conversation_json': [],
            'message_ids': []
        }
        
        last_timestamp = None
        
        for msg in messages:
            # 过滤规则
            should_include, category = self.data_filter.should_include(
                msg.content or '', msg.msg_type or 1
            )
            
            if not should_include:
                # 标记为垃圾
                if msg.status == 'pending':
                    msg.status = 'rejected'
                    msg.auto_category = category.value
                    msg.auto_flags = {'reason': 'filtered_by_rule'}
                continue
            
            # 判断是否开始新对话块
            if (last_timestamp and 
                (msg.timestamp - last_timestamp) > window_seconds * 1000):
                # 保存当前块
                if current_block['messages']:
                    blocks.append(self._finalize_block(current_block))
                    current_block = {
                        'messages': [],
                        'start_time': None,
                        'end_time': None,
                        'original_text': '',
                        'cleaned_text': '',
                        'conversation_json': [],
                        'message_ids': []
                    }
            
            # 添加到当前块
            if not current_block['start_time']:
                current_block['start_time'] = msg.timestamp
            
            current_block['end_time'] = msg.timestamp
            current_block['messages'].append(msg)
            current_block['message_ids'].append(msg.id)
            
            # 构建文本
            role = 'assistant' if msg.is_sender else 'user'
            content = msg.content or ''
            
            # 脱敏处理
            clean_content = self.data_filter.desensitize(content)
            
            current_block['original_text'] += f"{msg.sender_name or role}: {content}\n"
            current_block['cleaned_text'] += f"{msg.sender_name or role}: {clean_content}\n"
            
            current_block['conversation_json'].append({
                'role': role,
                'content': clean_content,
                'sender_name': msg.sender_name,
                'msg_id': msg.id,
                'timestamp': msg.timestamp
            })
            
            last_timestamp = msg.timestamp
        
        # 保存最后一个块
        if current_block['messages']:
            blocks.append(self._finalize_block(current_block))
        
        return blocks
    
    def _finalize_block(self, block: Dict) -> Dict:
        """完成对话块的构建"""
        # 合并同一人连续的消息
        merged_json = []
        last_role = None
        
        for item in block['conversation_json']:
            if item['role'] == last_role:
                # 合并到上一条
                merged_json[-1]['content'] += '\n' + item['content']
            else:
                merged_json.append(item)
                last_role = item['role']
        
        block['conversation_json'] = normalize_conversation_json(merged_json)
        
        # 重新构建文本
        block['cleaned_text'] = rebuild_cleaned_text(block['conversation_json'])
        
        return block
    
    def _auto_classify_block(self, text: str) -> Tuple[str, Dict]:
        """自动分类对话块"""
        category = self.data_filter.classify_content(text, 1)
        
        flags = {}
        if category.value == 'sensitive':
            flags['has_sensitive'] = True
        if category.value == 'spam':
            flags['is_junk'] = True
        if len(text) < 50:
            flags['too_short'] = True
        
        return category.value, flags
    
    def _auto_quality_score(self, text: str) -> Optional[float]:
        """自动质量评分"""
        if not self.quality_scorer:
            # 简单规则评分
            score = 5.0
            if len(text) > 100:
                score += 1.0
            if '?' in text or '？' in text:
                score += 1.0
            return min(score, 10.0)
        
        try:
            result = self.quality_scorer.score_conversation(text[:2000])
            return result.get('score', 5.0)
        except:
            return 5.0
    
    def _extract_qa(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        提取Q&A（简单规则，后续可用LLM优化）
        """
        lines = text.split('\n')
        questions = []
        answers = []
        
        for line in lines:
            if '?' in line or '？' in line:
                questions.append(line.strip())
            elif line.strip() and len(line.strip()) > 10:
                answers.append(line.strip())
        
        question = questions[0] if questions else None
        answer = '\n'.join(answers[:3]) if answers else None  # 取前3条作为答案
        
        return question, answer
    
    def merge_messages(self, message_ids: List[int], 
                      db_session) -> Optional[StagingConversation]:
        """
        合并多条消息为一个对话块
        """
        messages = db_session.query(RawChat).filter(
            RawChat.id.in_(message_ids),
            RawChat.timestamp >= MIN_TIMESTAMP  # 只处理2025年10月以后的数据
        ).order_by(RawChat.timestamp).all()
        
        if not messages:
            return None
        
        # 检查是否是群聊
        if messages[0].session_id.endswith('@chatroom'):
            return None
        
        # 构建对话块
        block = {
            'messages': messages,
            'start_time': messages[0].timestamp,
            'end_time': messages[-1].timestamp,
            'original_text': '',
            'cleaned_text': '',
            'conversation_json': [],
            'message_ids': [m.id for m in messages]
        }
        
        for msg in messages:
            role = 'assistant' if msg.is_sender else 'user'
            clean_content = self.data_filter.desensitize(msg.content or '')
            
            block['original_text'] += f"{msg.sender_name or role}: {msg.content}\n"
            block['cleaned_text'] += f"{msg.sender_name or role}: {clean_content}\n"
            
            block['conversation_json'].append({
                'role': role,
                'content': clean_content,
                'sender_name': msg.sender_name,
                'msg_id': msg.id,
                'timestamp': msg.timestamp
            })
        
        block = self._finalize_block(block)
        
        # 创建暂存区记录
        auto_category, auto_flags = self._auto_classify_block(block['cleaned_text'])
        auto_quality = self._auto_quality_score(block['cleaned_text'])
        question, answer = self._extract_qa(block['cleaned_text'])
        
        session_id = messages[0].session_id
        staging = StagingConversation(
            original_text=block['original_text'],
            cleaned_text=block['cleaned_text'],
            conversation_json=block['conversation_json'],
            session_id=session_id,
            source_message_ids=block['message_ids'],
            start_time=block['start_time'],
            end_time=block['end_time'],
            auto_question=question,
            auto_answer=answer,
            auto_category=auto_category,
            auto_quality_score=auto_quality,
            auto_flags=auto_flags,
            status=LabelStatus.PENDING.value
        )
        
        db_session.add(staging)
        db_session.commit()
        
        return staging
    
    def publish_to_production(self, staging_id: int, db_session) -> bool:
        """
        发布暂存区对话到生产区（创建LabeledConversation）
        """
        staging = db_session.query(StagingConversation).filter(
            StagingConversation.id == staging_id
        ).first()
        
        if not staging or staging.status != LabelStatus.APPROVED.value:
            return False
        
        # 创建LabeledConversation（如果不存在）
        from app.models.chat import LabeledConversation
        
        existing = db_session.query(LabeledConversation).filter(
            LabeledConversation.session_id == staging.session_id,
            LabeledConversation.start_time == staging.start_time,
            LabeledConversation.end_time == staging.end_time
        ).first()
        
        if existing:
            # 更新现有记录
            existing.conversation_text = staging.cleaned_text
            existing.conversation_json = staging.conversation_json
            existing.human_category = staging.human_category or staging.auto_category
            existing.human_quality = 'high' if staging.auto_quality_score and staging.auto_quality_score >= 7 else 'medium'
            existing.status = LabelStatus.APPROVED.value
        else:
            # 创建新记录
            labeled = LabeledConversation(
                conversation_text=staging.cleaned_text,
                conversation_json=staging.conversation_json,
                session_id=staging.session_id,
                source_message_ids=staging.source_message_ids,
                start_time=staging.start_time,
                end_time=staging.end_time,
                auto_category=staging.auto_category,
                auto_quality_score=staging.auto_quality_score,
                auto_flags=staging.auto_flags,
                human_category=staging.human_category or staging.auto_category,
                human_quality='high' if staging.auto_quality_score and staging.auto_quality_score >= 7 else 'medium',
                status=LabelStatus.APPROVED.value,
                labeled_by=staging.reviewed_by,
                labeled_at=staging.reviewed_at or datetime.utcnow()
            )
            db_session.add(labeled)
        
        db_session.commit()
        return True
