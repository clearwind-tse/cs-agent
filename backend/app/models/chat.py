# -*- coding: utf-8 -*-
"""
聊天相关数据模型
"""
from sqlalchemy import Column, Integer, String, Text, BigInteger, Boolean, DateTime, Index, JSON, Float
from datetime import datetime
import enum

from .database import Base


class LabelStatus(str, enum.Enum):
    """标注状态"""
    PENDING = "pending"      # 待审核
    APPROVED = "approved"    # 已通过
    REJECTED = "rejected"    # 已拒绝
    MODIFIED = "modified"    # 已修改


class DataCategory(str, enum.Enum):
    """数据分类 - 小蚕惠生活客服场景"""
    SAVINGS_EXPLAIN = "savings_explain"   # 省钱讲解
    REBATE_QUERY = "rebate_query"         # 返利查询
    COUPON_ISSUE = "coupon_issue"         # 优惠券问题
    ORDER_PROBLEM = "order_problem"       # 订单问题
    COMPLAINT = "complaint"               # 投诉处理
    MERCHANT = "merchant"                 # 到店霸王餐
    BRAND_PROMO = "brand_promo"           # 品牌活动
    POINTS_BOX = "points_box"             # 积分盲盒
    ONBOARDING = "onboarding"             # 新人引导
    CHITCHAT = "chitchat"                 # 闲聊
    KNOWLEDGE = "knowledge"               # 知识分享
    JUNK = "junk"                         # 垃圾数据

# 尝试导入 PostgreSQL 特定类型，如果失败则使用通用类型
try:
    from sqlalchemy.dialects.postgresql import JSONB
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    JSONB = JSON  # 使用通用 JSON 类型
    Vector = None
    HAS_PGVECTOR = False


class Contact(Base):
    """联系人表"""
    __tablename__ = "contacts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    wxid = Column(String(100), unique=True, nullable=False, index=True)  # 微信ID
    alias = Column(String(100))  # 微信号
    nickname = Column(String(200))  # 昵称
    remark = Column(String(200))  # 备注名
    display_name = Column(String(200))  # 显示名称 (备注 > 昵称)
    avatar_url = Column(Text)  # 头像URL
    is_chatroom = Column(Boolean, default=False)  # 是否是群聊
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Session(Base):
    """会话表"""
    __tablename__ = "sessions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)  # 会话ID (wxid 或 群ID)
    display_name = Column(String(200))  # 显示名称
    is_chatroom = Column(Boolean, default=False)  # 是否是群聊
    last_message = Column(Text)  # 最后一条消息
    last_time = Column(BigInteger)  # 最后消息时间戳
    message_count = Column(Integer, default=0)  # 消息数量
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RawChat(Base):
    """原始聊天记录表"""
    __tablename__ = "raw_chats"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    local_id = Column(Integer)  # 原始消息ID
    session_id = Column(String(100), nullable=False, index=True)  # 会话ID
    sender_wxid = Column(String(100))  # 发送者wxid
    sender_name = Column(String(200))  # 发送者名称
    content = Column(Text)  # 消息内容（原始内容，不可修改）
    msg_type = Column(Integer)  # 消息类型 (1=文本, 3=图片, 34=语音, 43=视频, 47=表情, 49=链接/文件)
    is_sender = Column(Boolean, default=False)  # 是否是自己发送
    timestamp = Column(BigInteger, nullable=False, index=True)  # 时间戳
    display_content = Column(Text)  # 显示内容 (如引用消息)
    extra_data = Column(JSONB if HAS_PGVECTOR else JSON)  # 额外数据
    source_db = Column(String(20))  # 来源数据库 (MSG0, MSG1 等)
    msg_server_id = Column(BigInteger, index=True)  # 微信服务器消息ID (MsgSvrID)，用于关联媒体文件
    voice_path = Column(String(300))  # 语音文件相对路径（如 Voice/xxx.mp3）
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 后台管理字段
    status = Column(String(20), default='pending', index=True)  # pending/approved/rejected/edited
    clean_content = Column(Text)  # 清洗后的内容（人工修改后的内容）
    auto_category = Column(String(50))  # 自动分类（机器预测）
    auto_flags = Column(JSONB if HAS_PGVECTOR else JSON)  # 自动标记 {sensitive, junk, incomplete, ...}
    reviewed_by = Column(String(100))  # 审核人
    reviewed_at = Column(DateTime)  # 审核时间
    
    # 复合索引，优化按会话+时间查询
    __table_args__ = (
        Index('idx_session_timestamp', 'session_id', 'timestamp'),
        Index('idx_status_session', 'status', 'session_id'),
    )


class KnowledgeChunk(Base):
    """知识库分块表"""
    __tablename__ = "knowledge_chunks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    topic_summary = Column(Text)  # AI 总结的主题
    content_block = Column(Text, nullable=False)  # 对话块内容
    # 向量数据 - 使用 Text 存储 JSON 格式，兼容 SQLite
    # PostgreSQL 使用 pgvector，维度根据模型调整 (384 for multilingual-MiniLM)
    embedding = Column(Vector(1024) if HAS_PGVECTOR else Text)
    source_ids = Column(JSONB if HAS_PGVECTOR else JSON)  # 来源消息ID列表
    session_id = Column(String(100), index=True)  # 会话ID
    start_time = Column(BigInteger)  # 对话块开始时间
    end_time = Column(BigInteger)  # 对话块结束时间
    keywords = Column(JSONB if HAS_PGVECTOR else JSON)  # 关键词列表
    entities = Column(JSONB if HAS_PGVECTOR else JSON)  # 实体信息
    chunk_type = Column(String(50))  # 分块类型
    created_at = Column(DateTime, default=datetime.utcnow)


class LabeledConversation(Base):
    """
    已标注的对话数据表
    存储经过清洗和人工标注的训练数据
    """
    __tablename__ = "labeled_conversations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 对话内容
    conversation_text = Column(Text, nullable=False)  # 原始对话文本
    conversation_json = Column(JSONB if HAS_PGVECTOR else JSON)  # 结构化对话 [{role, content}]
    
    # 来源信息
    session_id = Column(String(100), index=True)  # 来源会话
    source_message_ids = Column(JSONB if HAS_PGVECTOR else JSON)  # 原始消息ID列表
    start_time = Column(BigInteger)  # 对话开始时间
    end_time = Column(BigInteger)  # 对话结束时间
    
    # 自动标注（规则/AI）
    auto_category = Column(String(50))  # 自动分类
    auto_quality_score = Column(Float)  # 自动质量分 0-10
    auto_flags = Column(JSONB if HAS_PGVECTOR else JSON)  # 自动标记 {sensitive, incomplete, ...}
    
    # 人工标注
    human_category = Column(String(50))  # 人工分类
    human_quality = Column(String(20))  # 人工质量评级 high/medium/low
    human_notes = Column(Text)  # 人工备注
    modified_text = Column(Text)  # 人工修改后的文本
    
    # 状态
    status = Column(String(20), default=LabelStatus.PENDING.value, index=True)  # pending/approved/rejected/modified
    
    # 元数据
    labeled_by = Column(String(100))  # 标注人
    labeled_at = Column(DateTime)  # 标注时间
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_labeled_status_category', 'status', 'human_category'),
    )


class StagingConversation(Base):
    """
    暂存区对话块表
    存储经过第一轮粗清洗后的对话块，等待人工审核
    """
    __tablename__ = "staging_conversations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 对话内容
    original_text = Column(Text, nullable=False)  # 原始对话文本（未清洗）
    cleaned_text = Column(Text)  # 清洗后的对话文本
    conversation_json = Column(JSONB if HAS_PGVECTOR else JSON)  # 结构化对话 [{role, content, msg_id}]
    
    # 来源信息
    session_id = Column(String(100), nullable=False, index=True)  # 会话ID
    source_message_ids = Column(JSONB if HAS_PGVECTOR else JSON)  # 原始消息ID列表
    start_time = Column(BigInteger)  # 对话开始时间
    end_time = Column(BigInteger)  # 对话结束时间
    
    # AI 辅助标注
    auto_question = Column(Text)  # 自动提取的问题
    auto_answer = Column(Text)  # 自动总结的答案
    auto_category = Column(String(50))  # 自动分类
    auto_quality_score = Column(Float)  # 自动质量分 0-10
    auto_flags = Column(JSONB if HAS_PGVECTOR else JSON)  # 自动标记
    
    # 人工标注
    human_question = Column(Text)  # 人工修正的问题
    human_answer = Column(Text)  # 人工修正的答案
    human_category = Column(String(50))  # 人工分类
    human_notes = Column(Text)  # 人工备注
    
    # 状态
    status = Column(String(20), default=LabelStatus.PENDING.value, index=True)  # pending/approved/rejected/modified
    reviewed_by = Column(String(100))  # 审核人
    reviewed_at = Column(DateTime)  # 审核时间
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_staging_status_session', 'status', 'session_id'),
        Index('idx_staging_created', 'created_at'),
    )


class CustomConversation(Base):
    """
    自定义对话数据表
    用于手动添加高质量的对话数据，可直接用于训练
    """
    __tablename__ = "custom_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 对话内容（结构化格式，必填）
    conversation_json = Column(JSONB if HAS_PGVECTOR else JSON, nullable=False)  # [{role, content}]

    # 分类和质量
    category = Column(String(50), default='sales', index=True)  # 数据分类
    quality = Column(String(20), default='high')  # 质量等级：high/medium/low

    # 系统提示词（可选，导出时使用）
    system_prompt = Column(Text)  # 自定义系统提示词，为空则使用默认

    # 附加信息
    title = Column(String(200))  # 标题（可选，便于管理）
    description = Column(Text)  # 描述说明（可选）
    tags = Column(JSONB if HAS_PGVECTOR else JSON)  # 标签列表（可选）

    # 元数据
    source = Column(String(100))  # 数据来源标记（如：manual, imported, generated等）
    created_by = Column(String(100))  # 创建人
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 状态（是否启用）
    is_active = Column(Boolean, default=True, index=True)  # 是否在导出时包含

    __table_args__ = (
        Index('idx_custom_category_active', 'category', 'is_active'),
    )


class KnowledgeArticle(Base):
    """
    结构化知识条目表
    存储 LLM 从原始对话中提炼出的可复用知识
    """
    __tablename__ = "knowledge_articles"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 知识内容
    scene = Column(Text, nullable=False)                    # 销售场景描述
    scene_category = Column(String(50), index=True)         # 场景分类（sales/objection/closing 等）
    customer_says = Column(Text)                            # 客户典型说法
    recommended_response = Column(Text)                     # 推荐话术回复
    key_points = Column(JSONB if HAS_PGVECTOR else JSON)    # 话术要点列表

    # 向量 — 用 scene + customer_says 拼接生成
    embedding = Column(Vector(1024) if HAS_PGVECTOR else Text)

    # 来源追溯
    source_chunk_id = Column(Integer)                       # 来源 KnowledgeChunk ID
    source_session_id = Column(String(100))                 # 来源会话 ID
    source_type = Column(String(20), default='chat')        # 来源类型：chat / labeled

    # 质量
    confidence = Column(Float, default=0.0)                 # 提炼置信度 0~1
    is_verified = Column(Boolean, default=False)            # 是否人工验证

    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_article_category', 'scene_category'),
        Index('idx_article_verified', 'is_verified'),
    )


class Quiz(Base):
    """AI 考核试卷"""
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    category = Column(String(50), default='sales', index=True)
    questions_json = Column(JSONB if HAS_PGVECTOR else JSON, nullable=False)
    question_count = Column(Integer, default=10)
    status = Column(String(20), default='generated', index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class QuizAttempt(Base):
    """考核作答记录"""
    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    quiz_id = Column(Integer, nullable=False, index=True)
    user_answers_json = Column(JSONB if HAS_PGVECTOR else JSON)
    ai_evaluation_json = Column(JSONB if HAS_PGVECTOR else JSON)
    ai_total_score = Column(Float)
    human_score = Column(Float)
    human_feedback = Column(Text)
    status = Column(String(20), default='answering', index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    submitted_at = Column(DateTime)
    graded_at = Column(DateTime)

