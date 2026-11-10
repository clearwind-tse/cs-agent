# -*- coding: utf-8 -*-
"""
素材库二级目录

一级目录（kind）是固定的五类，写死在 media.py 的 MEDIA_KINDS；
二级目录可维护：预置项启动时 seed，用户可按一级新建自定义目录。

素材表只存 category key（字符串），不引用本表 id：
删目录时只需把该目录的素材 category 清成 NULL，它们自动落到「未归类」，
不会因为删目录连带删文件或留下悬空外键。
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint

from .database import Base


class MediaCategory(Base):
    __tablename__ = "media_categories"
    __table_args__ = (UniqueConstraint("kind", "key", name="uq_media_category_kind_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(20), nullable=False, index=True)
    key = Column(String(40), nullable=False)
    label = Column(String(40), nullable=False)
    builtin = Column(Boolean, default=False, nullable=False)   # 预置目录不允许删除
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "key": self.key,
            "label": self.label,
            "builtin": bool(self.builtin),
        }
