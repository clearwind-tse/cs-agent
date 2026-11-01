# -*- coding: utf-8 -*-
"""
DPO 偏好对数据库模型

用于两阶段训练：
1. SFT：用清洗后的对话数据微调客服语气
2. DPO：用标注的 chosen/rejected 偏好对训练优劣区分
"""
from sqlalchemy import Column, Integer, String, Text, BigInteger, Boolean, DateTime, Float, Index, JSON
from datetime import datetime
import enum
import uuid

from .database import Base

# 尝试导入 PostgreSQL 特定类型，如果失败则使用通用类型
try:
    from sqlalchemy.dialects.postgresql import JSONB
    HAS_PGVECTOR = True
except ImportError:
    JSONB = JSON  # 使用通用 JSON 类型
    HAS_PGVECTOR = False


class PreferenceType(str, enum.Enum):
    """偏好类型"""
    COMPLIANCE = "compliance"         # 合规性偏好（算账准确、话术合规）
    TONE = "tone"                      # 语气偏好（亲切、专业、避免生硬）
    EFFICIENCY = "efficiency"          # 效率偏好（简洁直接 vs 啰嗦）
    EMPATHY = "empathy"                # 共情偏好（安抚情绪、理解用户）


class AnnotationStatus(str, enum.Enum):
    """标注状态"""
    PENDING = "pending"        # 待标注
    ANNOTATED = "annotated"    # 已标注
    REVIEWED = "reviewed"      # 已审核
    REJECTED = "rejected"      # 已拒绝


class DpoPreferencePair(Base):
    """
    DPO 偏好对表

    存储同一业务问题下的多条回复及人工标注的偏好选择：
    - prompt: 用户原始问题/上下文
    - candidate_replies: 多条候选回复
    - chosen: 选中的最优回复（索引）
    - rejected_indices: 被拒绝的回复索引列表
    - annotation: 标注信息（标注人、时间、备注）
    """
    __tablename__ = "dpo_preference_pairs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 业务问题
    prompt = Column(Text, nullable=False)                    # 用户原始问题
    business_category = Column(String(50), index=True)       # 业务分类（complaint/refund/logistics等）
    scenario_description = Column(Text)                      # 场景描述
    
    # 候选回复
    candidate_replies = Column(JSONB if HAS_PGVECTOR else JSON, nullable=False)
    # 格式: [
    #   {"index": 0, "reply": "回复内容", "source": "agent/complaint_agent"},
    #   {"index": 1, "reply": "回复内容", "source": "agent/ticket_agent"},
    # ]
    
    # 标注结果
    chosen_index = Column(Integer, nullable=False)           # 选中的回复索引
    rejected_indices = Column(JSONB if HAS_PGVECTOR else JSON, default=list)  # 被拒绝的索引列表
    preference_type = Column(String(50), default="compliance")  # 偏好类型
    
    # 标注信息
    annotation_status = Column(String(20), default=AnnotationStatus.PENDING.value, index=True)
    annotated_by = Column(String(100))                       # 标注人（业务主管）
    annotated_at = Column(DateTime)                          # 标注时间
    annotation_notes = Column(Text)                          # 标注备注
    
    # 质量评估
    quality_score = Column(Float)                            # 整体质量分 0-10
    difficulty_level = Column(String(20))                    # 难度: easy/medium/hard
    
    # 来源追溯
    source_session_id = Column(String(100), index=True)      # 来源会话ID
    source_message_ids = Column(JSONB if HAS_PGVECTOR else JSON)  # 原始消息ID列表
    
    # 元数据
    version = Column(Integer, default=1)                     # 版本（可修订）
    is_active = Column(Boolean, default=True)                # 是否启用
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_dpo_category_status', 'business_category', 'annotation_status'),
        Index('idx_dpo_active', 'is_active'),
    )


class SftTrainingSample(Base):
    """
    SFT 训练样本表
    
    存储用于监督微调的单条训练样本
    """
    __tablename__ = "sft_training_samples"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 训练数据
    instruction = Column(Text, nullable=False)               # 指令/问题
    input_context = Column(Text, default="")                 # 上下文输入
    output = Column(Text, nullable=False)                    # 期望回复
    system_prompt = Column(Text)                             # 系统提示词
    
    # 分类和质量
    category = Column(String(50), index=True)                # 业务分类
    quality_score = Column(Float)                            # 质量分 0-10
    difficulty_level = Column(String(20))                    # 难度
    
    # 来源
    source_type = Column(String(20), default="chat")         # chat/labeled/custom/generated
    source_id = Column(String(100))                          # 来源ID
    source_session_id = Column(String(100), index=True)
    
    # 状态
    is_approved = Column(Boolean, default=True)              # 是否已审核
    reviewed_by = Column(String(100))
    reviewed_at = Column(DateTime)
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_sft_category_approved', 'category', 'is_approved'),
    )


class TrainingJob(Base):
    """
    训练任务表
    
    记录 SFT/DPO 训练任务的执行状态和结果
    """
    __tablename__ = "training_jobs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 任务信息
    job_type = Column(String(20), nullable=False)            # sft/dpo
    job_name = Column(String(200), nullable=False)           # 任务名称
    base_model = Column(String(200))                         # 基础模型
    dataset_id = Column(String(100), index=True)             # 数据集ID
    
    # 训练配置
    config_json = Column(JSONB if HAS_PGVECTOR else JSON)    # 训练参数配置
    
    # 执行状态
    status = Column(String(20), default="pending", index=True)  # pending/running/success/failed/cancelled
    progress = Column(Float, default=0.0)                    # 进度 0-100
    logs = Column(Text)                                      # 训练日志
    
    # 结果
    model_path = Column(String(500))                         # 输出模型路径
    metrics_json = Column(JSONB if HAS_PGVECTOR else JSON)   # 评估指标
    
    # 元数据
    created_by = Column(String(100))
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_training_status', 'status'),
    )
