# -*- coding: utf-8 -*-
"""
离线数据闭环自动流水线

给定 raw_chats 的 session_id，串起三步：
  1) 清洗   —— 复用 labeling 的 TrainingDataPipeline，生成待标注对话（LabeledConversation）
  2) 质检   —— 复用 QualityInspectionService，对会话评分
  3) 知识提炼 —— 复用 KnowledgeExtractor，从原始会话抽取知识条目

全部复用既有服务的核心实现，本模块只负责"按会话编排 + 串联"。
"""
import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from app.config import get_settings
from app.models.chat import RawChat, LabeledConversation, LabelStatus
from app.models.quality import QualityInspection, QualityInspectionConfigModel
from app.services.training_data import (
    TrainingDataPipeline,
    ConversationBuilder,
    DataQuality,
)
from app.services.quality_inspection import (
    QualityInspectionService,
    default_qc_config,
    config_from_dict,
)
from app.services.extractor import KnowledgeExtractor

settings = get_settings()

# 与 labeling / chats 保持一致的时间下限（2025-10-01 起，避免污染知识库）
MIN_TIMESTAMP = 1759248000


def _resolve_qc_config(db: DBSession):
    """取系统唯一一份质检配置；未配置则回退代码内置默认。返回 (config, config_id)。"""
    row = (
        db.query(QualityInspectionConfigModel)
        .order_by(
            QualityInspectionConfigModel.is_default.desc(),
            QualityInspectionConfigModel.id,
        )
        .first()
    )
    if row and row.config_json:
        return config_from_dict(row.config_json), row.id
    return default_qc_config(), None


def _store_inspection(db, result, session_id, cfg, config_id, agent_name, start_time, end_time):
    """把一次质检结果落库（与 cs_quality._store_inspection 同口径）。"""
    row = QualityInspection(
        session_id=session_id,
        agent_name=agent_name,
        config_id=config_id,
        config_name=cfg.name,
        conversation_snapshot=result.conversation_json,
        start_time=start_time,
        end_time=end_time,
        scores=result.scores,
        overall_score=result.overall_score,
        violations=result.violations,
        summary=result.summary,
        suggestions=result.suggestions,
        llm_raw=result.llm_raw,
        scored=result.scored,
        status="pending",
    )
    db.add(row)
    db.flush()
    return row


def clean_session(
    db: DBSession,
    session_id: str,
    *,
    time_window_seconds: int = 300,
    max_turns: int = 20,
    min_quality: str = "low",
    limit: int = 1000,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
) -> int:
    """
    对单个会话执行清洗，生成待标注对话（LabeledConversation）。
    已存在该会话的标注则跳过（幂等）。返回新建条数。
    """
    # 已处理过则跳过，避免重复清洗
    existing = (
        db.query(LabeledConversation)
        .filter(LabeledConversation.session_id == session_id)
        .first()
    )
    if existing:
        return 0

    pipeline = TrainingDataPipeline(
        builder=ConversationBuilder(
            time_window_seconds=time_window_seconds,
            max_turns_per_conversation=max_turns,
        ),
        min_quality=DataQuality(min_quality),
    )

    msg_q = db.query(RawChat).filter(RawChat.session_id == session_id)
    if start_time is not None:
        msg_q = msg_q.filter(RawChat.timestamp >= start_time)
    if end_time is not None:
        msg_q = msg_q.filter(RawChat.timestamp <= end_time)
    messages = msg_q.order_by(RawChat.timestamp).limit(limit).all()

    if not messages:
        return 0

    msg_dicts = [
        {
            "id": m.id,
            "sender_name": m.sender_name or m.sender_wxid,
            "content": m.content,
            "timestamp": m.timestamp,
            "is_sender": m.is_sender,
        }
        for m in messages
    ]

    examples = pipeline.process_session(session_id, msg_dicts)
    created = 0
    for ex in examples:
        conv_text = "\n".join(
            f"{'本平台' if t.role == 'assistant' else '客户'}: {t.content}"
            for t in ex.conversations
        )
        conv_json = [
            {"role": t.role, "content": t.content, "sender": t.sender}
            for t in ex.conversations
        ]
        labeled = LabeledConversation(
            conversation_text=conv_text,
            conversation_json=json.dumps(conv_json, ensure_ascii=False),
            session_id=session_id,
            source_message_ids=json.dumps(ex.metadata.get("source_ids", [])),
            auto_category=ex.category.value,
            auto_quality_score=ex.metadata.get("score", 5.0),
            status=LabelStatus.PENDING.value,
            created_at=datetime.utcnow(),
        )
        db.add(labeled)
        created += 1

    db.commit()
    return created


def run_pipeline(
    db: DBSession,
    session_id: str,
    *,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    do_clean: bool = True,
    do_qc: bool = True,
    do_knowledge: bool = True,
) -> dict:
    """
    对一个 raw_chats 的 session_id 串起 清洗 → 质检 → 知识提炼。
    返回各阶段统计与错误信息。
    """
    stats = {
        "session_id": session_id,
        "cleaned": 0,
        "qc": None,
        "knowledge": 0,
        "errors": [],
    }

    # 时间窗：优先参数，否则取该会话真实消息范围
    ts_rows = db.query(RawChat.timestamp).filter(RawChat.session_id == session_id).all()
    ts_list = [t[0] for t in ts_rows if t[0] is not None]
    if not ts_list:
        stats["errors"].append("该会话没有可处理的消息")
        return stats

    s_time = start_time if start_time is not None else min(ts_list)
    e_time = end_time if end_time is not None else max(ts_list)

    if do_clean:
        try:
            stats["cleaned"] = clean_session(
                db, session_id, start_time=s_time, end_time=e_time
            )
        except Exception as e:  # 单阶段失败不影响其余阶段
            stats["errors"].append(f"清洗失败: {e}")

    if do_qc:
        try:
            cfg, cfg_id = _resolve_qc_config(db)
            svc = QualityInspectionService(cfg)
            result = svc.inspect_session(session_id, db, s_time, e_time)
            _store_inspection(
                db, result, session_id, cfg, cfg_id,
                result.agent_name, s_time, e_time,
            )
            db.commit()
            stats["qc"] = {
                "overall_score": result.overall_score,
                "scored": result.scored,
                "violations": len(result.violations or []),
            }
        except Exception as e:
            stats["errors"].append(f"质检失败: {e}")

    if do_knowledge:
        try:
            extractor = KnowledgeExtractor(db)
            articles = extractor.extract_from_raw_session(session_id)
            stats["knowledge"] = len(articles)
        except Exception as e:
            stats["errors"].append(f"知识提炼失败: {e}")

    return stats
