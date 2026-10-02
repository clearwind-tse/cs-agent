# -*- coding: utf-8 -*-
"""
认证路由
注册、登录、刷新 Token、获取当前用户
"""
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.user import User
from app.services.auth import (
    authenticate_user, create_user, create_access_token,
    create_refresh_token, decode_token
)
from app.deps import get_current_user
from app.config import get_settings

settings = get_settings()

router = APIRouter(prefix="/api/auth", tags=["认证"])


# ---- Request / Response Schemas ----

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    nickname: str | None = Field(None, max_length=50, description="昵称")


class LoginRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="刷新 Token")


class UserInfo(BaseModel):
    id: int
    username: str
    nickname: str | None
    role: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserInfo


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int


# ---- API Endpoints ----

@router.post("/register", response_model=UserInfo)
def register(request: RegisterRequest, db: DBSession = Depends(get_db)):
    """用户注册"""
    import traceback
    try:
        # 检查用户名是否已存在
        existing = db.query(User).filter(User.username == request.username).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": 40104, "message": "用户名已存在"}
            )

        user = create_user(
            db=db,
            username=request.username,
            password=request.password,
            nickname=request.nickname
        )

        return UserInfo(
            id=user.id,
            username=user.username,
            nickname=user.nickname,
            role=user.role
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Register failed: {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": 50000, "message": f"注册失败: {str(e)}"}
        )


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: DBSession = Depends(get_db)):
    """用户登录"""
    user = authenticate_user(db, request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": 40103, "message": "用户名或密码错误"}
        )

    access_token = create_access_token(data={"sub": user.username})
    refresh_token = create_refresh_token(data={"sub": user.username})

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserInfo(
            id=user.id,
            username=user.username,
            nickname=user.nickname,
            role=user.role
        )
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh_token(request: RefreshRequest, db: DBSession = Depends(get_db)):
    """刷新 access_token"""
    payload = decode_token(request.refresh_token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": 40101, "message": "Refresh Token 已过期或无效"}
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": 40102, "message": "Token 类型错误"}
        )

    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": 40102, "message": "用户不存在或已被禁用"}
        )

    new_access_token = create_access_token(data={"sub": user.username})

    return RefreshResponse(
        access_token=new_access_token,
        expires_in=settings.access_token_expire_minutes * 60
    )


@router.get("/me", response_model=UserInfo)
def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return UserInfo(
        id=current_user.id,
        username=current_user.username,
        nickname=current_user.nickname,
        role=current_user.role
    )
