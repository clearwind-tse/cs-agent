# -*- coding: utf-8 -*-
"""
AI 创作任务表

两阶段生成的落点：一次出图请求 = 一条任务。
  planning → planned（等人工确认）→ generating → done / failed

为什么必须落表、不能用一个同步请求跑完：
- 出图是几十秒级的操作，同步请求必然超时，且用户一刷新就丢；
- 「规划」是可审的一等产物：先看清楚要出哪几张、每张什么构图，再决定花不花额度；
- 失败要能单张重试，得知道哪张失败、为什么。
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from datetime import datetime

from .database import Base

# 任务类型：与前端 StudioPane 对齐（canvas 暂不走任务链路）
TASK_KINDS = ("set", "style", "sku", "outfit", "retouch")

# 状态机：queued → planning → planned → generating → done / failed；planned → cancelled
TASK_STATUSES = ("queued", "planning", "planned", "generating", "done", "failed", "cancelled")


class StudioTask(Base):
    __tablename__ = "studio_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_no = Column(String(40), unique=True, nullable=False, index=True)
    kind = Column(String(20), nullable=False, index=True)
    status = Column(String(20), default="queued", nullable=False, index=True)

    # 输入：{"asset_ids": [1,2], "count": 4, "ratio": "1:1", "note": "…"}
    input = Column(JSON, nullable=True)
    # 规划：{"engine": "rule", "summary": "…", "shots": [{index,title,size,composition,copy,prompt}], "warnings": []}
    plan = Column(JSON, nullable=True)
    # 产出：{"engine": "mock", "assets": [{media_id, url, index, shot_title}]}
    outputs = Column(JSON, nullable=True)

    progress = Column(Integer, default=0)     # 0-100，按已完成张数推进
    total_shots = Column(Integer, default=0)
    done_shots = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    owner_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "task_no": self.task_no,
            "kind": self.kind,
            "status": self.status,
            "input": self.input or {},
            "plan": self.plan,
            "outputs": self.outputs,
            "progress": self.progress or 0,
            "total_shots": self.total_shots or 0,
            "done_shots": self.done_shots or 0,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
