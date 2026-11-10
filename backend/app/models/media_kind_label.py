# -*- coding: utf-8 -*-
"""
一级目录的自定义显示名

五个一级 key（product/style/result/reference/other）是代码契约，不能改：
studioKinds 的默认上传目录、后端白名单、生成结果归类都按 key 走。
这里只覆盖「显示给人看的名字」，表里只存被用户改过的项，
没改过的继续用 media.py 的 MEDIA_KIND_LABELS，代码里改默认名也能自动生效。
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, String

from .database import Base


class MediaKindLabel(Base):
    __tablename__ = "media_kind_labels"

    key = Column(String(20), primary_key=True)
    label = Column(String(40), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label}
