# -*- coding: utf-8 -*-
"""
数据库连接配置
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from typing import Optional

# 延迟初始化
_engine = None
_SessionLocal = None
Base = declarative_base()


def get_engine():
    """获取数据库引擎 (延迟初始化)"""
    global _engine
    if _engine is None:
        from app.config import get_settings
        settings = get_settings()
        
        # 根据数据库类型配置不同参数
        if settings.database_url.startswith("sqlite"):
            _engine = create_engine(
                settings.database_url,
                connect_args={"check_same_thread": False}
            )
        else:
            _engine = create_engine(
                settings.database_url,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20
            )
    return _engine


def get_session_local():
    """获取会话工厂"""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


# 兼容性别名
@property
def engine():
    return get_engine()


@property  
def SessionLocal():
    return get_session_local()


def get_db():
    """获取数据库会话"""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
