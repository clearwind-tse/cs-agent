# -*- coding: utf-8 -*-
"""
用户模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.models.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True, comment="用户名")
    hashed_password = Column(String(128), nullable=False, comment="加密后的密码")
    nickname = Column(String(50), nullable=True, comment="显示昵称")
    role = Column(String(20), nullable=False, default="user", comment="角色: user/admin")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否启用")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"
