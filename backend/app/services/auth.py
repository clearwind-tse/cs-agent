# -*- coding: utf-8 -*-
"""
认证服务
JWT Token 生成/校验、密码处理
"""
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
import bcrypt
from sqlalchemy.orm import Session as DBSession

from app.config import get_settings
from app.models.user import User

settings = get_settings()

def hash_password(password: str) -> str:
    """对密码进行 bcrypt 哈希"""
    salt = bcrypt.gensalt()
    pwd_bytes = password.encode('utf-8')
    if len(pwd_bytes) > 72:
        print(f"[WARN] Password length {len(pwd_bytes)} exceeds 72 bytes, truncating.")
        pwd_bytes = pwd_bytes[:72]
    hashed_bytes = bcrypt.hashpw(pwd_bytes, salt)
    return hashed_bytes.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码是否匹配"""
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except ValueError:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 access_token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict) -> str:
    """创建 refresh_token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    """解码并验证 JWT Token"""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        return None


def authenticate_user(db: DBSession, username: str, password: str) -> Optional[User]:
    """验证用户凭证"""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user


def create_user(db: DBSession, username: str, password: str, nickname: Optional[str] = None) -> User:
    """
    创建新用户
    如果是系统中第一个用户，自动设为 admin
    """
    # 检查是否是第一个用户
    user_count = db.query(User).count()
    role = "admin" if user_count == 0 else "user"

    user = User(
        username=username,
        hashed_password=hash_password(password),
        nickname=nickname or username,
        role=role,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
