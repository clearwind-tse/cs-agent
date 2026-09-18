# -*- coding: utf-8 -*-
"""
客服质检相关数据模型
- QualityInspectionConfigModel: 质检规则预设（维度/权重/违规项/人设等配置化）
- QualityInspection: 单次会话质检结果
"""
from sqlalchemy import Column, Integer, String, Text, BigInteger, Boolean, DateTime, Index, JSON, Float
from datetime import datetime

from .database import Base

# 与 chat.py 保持一致：尝试导入 PostgreSQL 专用类型，失败则降级为通用 JSON
try:
    from sqlalchemy.dialects.postgresql import JSONB
    HAS_PGVECTOR = True
except ImportError:
    JSONB = JSON
    HAS_PGVECTOR = False


class QualityInspectionConfigModel(Base):
    """
    质检规则预设表
    把"评什么、怎么评、用谁评"全部配置化，可建多套标准（如电商客服/销售话术）。
    config_json 完整存储 QualityInspectionConfig 的序列化内容。
    """
    __tablename__ = "quality_inspection_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)  # 预设名
    description = Column(Text)                                          # 预设说明
    is_default = Column(Boolean, default=False, index=True)             # 是否默认预设
    is_active = Column(Boolean, default=True, index=True)               # 是否启用
    config_json = Column(JSONB if HAS_PGVECTOR else JSON)              # 完整配置对象
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class QualityInspection(Base):
    """
    会话质检结果表
    一次对某会话（某客服）服务质量的评分记录
    """
    __tablename__ = "quality_inspections"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 来源
    session_id = Column(String(100), nullable=False, index=True)   # 会话ID
    agent_name = Column(String(200), index=True)                   # 客服标识（is_sender 一方）
    config_id = Column(Integer, index=True)                        # 使用的预设ID
    config_name = Column(String(100))                              # 使用的预设名（快照）

    # 对话快照（已脱敏，避免库内留存 PII）
    conversation_snapshot = Column(JSONB if HAS_PGVECTOR else JSON)
    start_time = Column(BigInteger)
    end_time = Column(BigInteger)

    # 评分结果
    scores = Column(JSONB if HAS_PGVECTOR else JSON)              # {维度key: 0-100}
    overall_score = Column(Float)                                  # 加权总分 0-100
    violations = Column(JSONB if HAS_PGVECTOR else JSON)           # [{type,severity,evidence,suggestion}]
    summary = Column(Text)                                         # 总体评价
    suggestions = Column(Text)                                     # 改进建议
    llm_raw = Column(Text)                                         # LLM 原始输出（调试用）
    scored = Column(Boolean, default=True, index=True)             # False=LLM 不可用/未评分

    # 状态与人工复核
    status = Column(String(20), default='pending', index=True)      # pending / reviewed
    human_override_score = Column(Float)                           # 人工覆盖总分
    human_notes = Column(Text)                                     # 人工备注
    reviewer = Column(String(100))                                 # 复核人
    reviewed_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_qi_session_created', 'session_id', 'created_at'),
        Index('idx_qi_status_scored', 'status', 'scored'),
    )


# ===================== 质检校准（校准集 / 重跑 / 配置版本） =====================
# 说明：本组表全部为「新增表」，靠 Base.metadata.create_all 自动建，无需 schema_sync 迁移。
# 项目内无 ForeignKey，关联一律用裸 id（与 DialogueSession 一致），
# 因此删除分组时必须由路由手动级联清理 items / runs / run_items。

class QcConfigVersion(Base):
    """
    质检配置版本快照
    - 每次保存质检配置（PUT /qc/config 或 seed-default）后，按 content_hash 去重追加一条
    - config_json 为该版本的完整配置，用于「跨版本对比」时复现当时的评分标准
    """
    __tablename__ = "qc_config_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_id = Column(Integer, index=True)          # 关联 quality_inspection_configs.id（裸 id）
    version = Column(Integer, nullable=False)        # 该 config 下自增版本号
    name = Column(String(100))                       # 配置名快照
    description = Column(Text)
    config_json = Column(JSONB if HAS_PGVECTOR else JSON)   # 完整配置对象快照
    content_hash = Column(String(64), index=True)    # 规范化 JSON 的 sha256，用于去重
    note = Column(Text)
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('uq_qcv_config_version', 'config_id', 'version', unique=True),
    )


class QcCalibrationGroup(Base):
    """校准分组：一组人工标注数据（按业务/客服/场景自由划分）"""
    __tablename__ = "qc_calibration_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text)
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class QcCalibrationItem(Base):
    """
    校准集条目：一条「人工标注真值」（冻结）
    - 以微信会话 session_id 为单元，并冻结时间窗（重跑时用同一窗口，保证可比）
    - gold_scores 按【维度 key】存人工各维度分；gold_total 为人工总分
    - 冻结后不随质检配置/复核改动而变，是校准的分析基准
    """
    __tablename__ = "qc_calibration_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, index=True)               # 关联 qc_calibration_groups.id（裸 id）
    session_id = Column(String(100), nullable=False, index=True)
    agent_name = Column(String(200))
    gold_total = Column(Float)                           # 人工总分 0-100
    gold_scores = Column(JSONB if HAS_PGVECTOR else JSON)  # {维度key: 人工分}
    start_time = Column(BigInteger)                      # 冻结时间窗（与 _pick_qc 口径一致）
    end_time = Column(BigInteger)
    note = Column(Text)
    added_config_version_id = Column(Integer)            # 加入时的配置版本（仅用于追溯维度中文名）
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # 同一分组内同一会话只能有一条真值，否则每条指标都会被静默重复计数
        Index('uq_qci_group_session', 'group_id', 'session_id', unique=True),
    )


class QcCalibrationRun(Base):
    """
    校准运行：用某配置版本重跑某分组，与冻结的人工真值对比
    - 只存聚合指标 metrics_json；逐条明细在 QcCalibrationRunItem
    - 额外快照 config_json / pass_threshold，使运行自描述（版本被裁剪后仍可解释）
    - 校准结果只落本组表，不写 quality_inspections，避免污染主质检统计
    """
    __tablename__ = "qc_calibration_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, index=True)               # 关联 qc_calibration_groups.id（裸 id）
    config_version_id = Column(Integer)                  # 关联 qc_config_versions.id（裸 id）
    config_version = Column(Integer)                     # 版本号快照
    config_name = Column(String(100))
    config_json = Column(JSONB if HAS_PGVECTOR else JSON)  # 配置快照（自描述）
    pass_threshold = Column(Float)                       # 及格线快照（及格一致率依赖它）

    status = Column(String(20), default='pending', index=True)  # pending/running/done/failed
    total = Column(Integer, default=0)
    done_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    metrics_json = Column(JSONB if HAS_PGVECTOR else JSON)      # 聚合指标（禁止 NaN/Inf）
    error = Column(Text)
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)

    __table_args__ = (
        Index('idx_qcr_group_created', 'group_id', 'created_at'),
    )


class QcCalibrationRunItem(Base):
    """校准运行的单条结果：某会话的 AI 重跑分 vs 人工真值"""
    __tablename__ = "qc_calibration_run_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, index=True)                 # 关联 qc_calibration_runs.id（裸 id）
    item_id = Column(Integer)                            # 关联 qc_calibration_items.id（裸 id）
    session_id = Column(String(100), index=True)

    ai_total = Column(Float)                             # AI 重跑总分（未评分时为 None）
    ai_scores = Column(JSONB if HAS_PGVECTOR else JSON)  # {维度key: AI分}
    ai_scored = Column(Boolean, default=True)            # False=LLM 不可用/未评分
    ai_missing_dims = Column(JSONB if HAS_PGVECTOR else JSON)  # LLM 未返回的维度 key（假 0，需剔除）
    ai_error = Column(String(500))

    gold_total = Column(Float)                           # 人工真值总分快照
    gold_scores = Column(JSONB if HAS_PGVECTOR else JSON)  # 人工真值各维度快照
    delta_total = Column(Float)                          # ai_total - gold_total
    per_dim_delta = Column(JSONB if HAS_PGVECTOR else JSON)  # {维度key: ai-gold}
    pass_agree = Column(Boolean)                         # AI 与人工的及格判定是否一致

    violations = Column(JSONB if HAS_PGVECTOR else JSON)
    summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_qcri_run', 'run_id'),
    )
