# -*- coding: utf-8 -*-
"""
SFT 训练数据服务

负责从聊天记录中提取、清洗、格式化 SFT 训练样本
"""
import json
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.database import get_session_local
from app.models.chat import RawChat, Session as ChatSession, LabeledConversation
from app.models.dpo import SftTrainingSample, AnnotationStatus
from app.services.training_data import (
    TrainingDataPipeline, 
    DataCleaner, 
    QualityEvaluator,
    DataQuality,
    ContentCategory,
    TrainingDataExporter
)


class SftDataService:
    """SFT 训练数据服务"""
    
    def __init__(self):
        self.pipeline = TrainingDataPipeline()
        self.cleaner = DataCleaner()
        self.evaluator = QualityEvaluator()
    
    def extract_from_chats(
        self,
        session_id: Optional[str] = None,
        min_quality: str = "medium",
        max_samples: int = 1000,
        include_pending: bool = True
    ) -> List[SftTrainingSample]:
        """
        从聊天记录提取 SFT 样本
        
        Args:
            session_id: 指定会话ID，None 则处理全部
            min_quality: 最低质量等级 high/medium/low
            max_samples: 最大样本数
            include_pending: 是否包含 pending 状态的聊天（默认 True，
                因为实际数据大多处于 pending 且未经人工 approved）
        
        Returns:
            SFT 训练样本列表
        """
        SessionLocal = get_session_local()
        db = SessionLocal()
        
        try:
            # 查询原始消息
            # 默认接受 approved + pending（排除 rejected 和低质），
            # 避免因为聊天记录从未被人工审核(approved)而导致提取为空
            status_filter = ["approved"]
            if include_pending:
                status_filter.append("pending")
            
            query = db.query(RawChat).filter(
                RawChat.status.in_(status_filter),
                RawChat.msg_type == 1  # 只取文本消息
            )
            
            if session_id:
                query = query.filter(RawChat.session_id == session_id)
            
            messages = query.order_by(RawChat.session_id, RawChat.timestamp).all()
            
            # 按会话分组
            sessions: Dict[str, List[Dict]] = {}
            for msg in messages:
                sid = msg.session_id
                if sid not in sessions:
                    sessions[sid] = []
                sessions[sid].append({
                    "sender_name": msg.sender_name,
                    "content": msg.content or "",
                    "timestamp": msg.timestamp,
                    "is_sender": msg.is_sender
                })
            
            # 生成训练样本
            samples = []
            quality_map = {
                "high": DataQuality.HIGH,
                "medium": DataQuality.MEDIUM,
                "low": DataQuality.LOW
            }
            min_q = quality_map.get(min_quality, DataQuality.MEDIUM)
            
            for sid, msgs in sessions.items():
                examples = self.pipeline.process_session(sid, msgs)
                
                for ex in examples:
                    if ex.quality.value == "rejected":
                        continue
                    
                    # 转换为 SFT 格式
                    sample = self._example_to_sft_sample(ex, sid)
                    if sample and len(sample.instruction) > 5:
                        samples.append(sample)
                    
                    if len(samples) >= max_samples:
                        break
                
                if len(samples) >= max_samples:
                    break
            
            return samples
            
        finally:
            db.close()
    
    def _example_to_sft_sample(
        self, 
        example, 
        session_id: str
    ) -> Optional[SftTrainingSample]:
        """将 TrainingExample 转换为 SftTrainingSample"""
        turns = example.conversations
        
        # 找到第一个 user-assistant 问答对
        for i in range(len(turns) - 1):
            if turns[i].role == "user" and turns[i + 1].role == "assistant":
                instruction = turns[i].content.strip()
                output = turns[i + 1].content.strip()
                
                # 收集上下文
                context_parts = []
                for t in turns[:i]:
                    role_label = "用户" if t.role == "user" else "助手"
                    context_parts.append(f"{role_label}: {t.content}")
                input_context = "\n".join(context_parts) if context_parts else ""
                
                # 生成 system prompt
                system_prompt = self._get_system_prompt(example.category)
                
                # 生成唯一 ID（纳入 RawChat 主键 example.id，避免同会话内
                # 重复文本产生相同哈希导致主键冲突）
                sample_id = hashlib.md5(
                    f"{session_id}_{i}_{example.id}_{instruction[:50]}".encode()
                ).hexdigest()[:16]
                
                return SftTrainingSample(
                    id=sample_id,
                    instruction=instruction,
                    input_context=input_context,
                    output=output,
                    system_prompt=system_prompt,
                    category=example.category.value,
                    quality_score=example.metadata.get("score", 0),
                    difficulty_level="medium",
                    source_type="chat",
                    source_id=example.id,
                    source_session_id=session_id,
                    is_approved=True
                )
        
        return None
    
    def _get_system_prompt(self, category: ContentCategory) -> str:
        """根据分类获取系统提示词"""
        prompts = {
            ContentCategory.COMPLAINT: "你是小蚕惠生活客服小蚕，面对用户投诉时要先共情道歉，再给出明确解决方案，绝不推诿。",
            ContentCategory.ORDER_PROBLEM: "你是小蚕惠生活客服小蚕，处理订单异常问题，要耐心询问订单号并给出解决方案。",
            ContentCategory.REBATE_QUERY: "你是小蚕惠生活客服小蚕，帮用户查询返利到账情况，直接给出准确信息。",
            ContentCategory.COUPON_ISSUE: "你是小蚕惠生活客服小蚕，帮助用户解决红包、优惠券使用问题。",
            ContentCategory.MERCHANT: "你是小蚕惠生活客服小蚕，介绍到店霸王餐参与规则和流程。",
            ContentCategory.BRAND_PROMO: "你是小蚕惠生活客服小蚕，介绍大牌特惠活动和优惠力度。",
            ContentCategory.POINTS_BOX: "你是小蚕惠生活客服小蚕，讲解积分积累和盲盒玩法。",
            ContentCategory.ONBOARDING: "你是小蚕惠生活客服小蚕，引导新用户注册并使用平台功能。",
            ContentCategory.SAVINGS_EXPLAIN: "你是小蚕惠生活客服小蚕，讲解省钱玩法和优惠叠加规则。",
        }
        return prompts.get(category, "你是小蚕惠生活客服小蚕，帮用户点外卖省钱、领红包、拿返利。")
    
    def save_samples(self, samples: List[SftTrainingSample]) -> int:
        """保存 SFT 样本到数据库（幂等：已存在则更新，不存在则插入）"""
        SessionLocal = get_session_local()
        db = SessionLocal()

        try:
            count = 0
            for sample in samples:
                # merge: 按主键存在性自动 INSERT 或 UPDATE，
                # 避免重复提取时因确定性哈希 ID 命中唯一约束而报错
                db.merge(sample)
                count += 1

            db.commit()
            return count
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    
    def get_samples(
        self,
        category: Optional[str] = None,
        is_approved: bool = True,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """查询 SFT 样本"""
        SessionLocal = get_session_local()
        db = SessionLocal()
        
        try:
            query = db.query(SftTrainingSample).filter(
                SftTrainingSample.is_approved == is_approved
            )
            
            if category:
                query = query.filter(SftTrainingSample.category == category)
            
            total = query.count()
            samples = query.order_by(
                SftTrainingSample.created_at.desc()
            ).limit(limit).offset(offset).all()
            
            return {
                "total": total,
                "samples": [
                    {
                        "id": s.id,
                        "instruction": s.instruction,
                        "output": s.output[:100] + "..." if len(s.output) > 100 else s.output,
                        "category": s.category,
                        "quality_score": s.quality_score,
                        "created_at": s.created_at.isoformat() if s.created_at else None
                    }
                    for s in samples
                ]
            }
        finally:
            db.close()
    
    def export_for_training(
        self,
        format: str = "sharegpt",
        categories: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        导出 SFT 训练数据
        
        Args:
            format: 导出格式 sharegpt/alpaca/openai
            categories: 筛选类别
        
        Returns:
            训练数据列表
        """
        SessionLocal = get_session_local()
        db = SessionLocal()
        
        try:
            query = db.query(SftTrainingSample).filter(
                SftTrainingSample.is_approved == True
            )
            
            if categories:
                query = query.filter(SftTrainingSample.category.in_(categories))
            
            samples = query.all()
            
            # 转换为 ShareGPT 格式
            dataset = []
            for s in samples:
                messages = []
                
                if s.system_prompt:
                    messages.append({
                        "role": "system",
                        "content": s.system_prompt
                    })
                
                if s.input_context:
                    messages.append({
                        "role": "user",
                        "content": s.input_context
                    })
                
                messages.append({
                    "role": "user",
                    "content": s.instruction
                })
                
                messages.append({
                    "role": "assistant",
                    "content": s.output
                })
                
                dataset.append({
                    "id": s.id,
                    "messages": messages,
                    "category": s.category
                })
            
            return dataset
            
        finally:
            db.close()


# 全局实例
sft_service = SftDataService()
