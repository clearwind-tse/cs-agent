# -*- coding: utf-8 -*-
"""
各业务板块的模型选择（DB override）

分工：
  - API Key / base_url 等连接信息只在 .env（config.Settings），本表绝不存密钥；
  - 本表只存「哪个板块选哪个 provider / 哪个模型」，表里没有记录的板块用代码默认值。

之所以不把 key 放进来：开源自托管项目，密钥进 DB 会随备份/导出泄露，
多实例部署还会各自持有一份不一致的凭据。设置页只显示「是否已配置」和环境变量名。
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, String

from .database import Base


class ModelSetting(Base):
    __tablename__ = "model_settings"

    slot = Column(String(40), primary_key=True)
    # auto = 按板块的 provider 优先级自动挑第一个已配置的；否则必须是具体 provider key
    provider = Column(String(30), nullable=False, default="auto")
    # 空字符串 = 用所选 provider 的默认模型
    model = Column(String(120), nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "slot": self.slot,
            "provider": self.provider,
            "model": self.model,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
