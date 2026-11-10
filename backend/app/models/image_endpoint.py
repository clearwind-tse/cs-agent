# -*- coding: utf-8 -*-
"""
AI 图片动态处理：端点池 / 服务绑定 / 即席处理任务

和「按板块选文本模型」不是一回事：
  - 端点是**一等公民**，可以任意多个，UI 里增删改，不写在代码里；
  - 端点声明自己能做什么（能力标签）与怎么调（协议），而不是被某个功能写死；
  - 服务（五个出图功能 + 素材即席处理）只绑定「候选端点有序链」；
  - 真正用哪个端点在运行时选：任务里可覆盖，镜头能力不同也会分派到不同端点。

密钥策略沿用项目约定但支持三种模式：
  none  —— 本地自托管服务不需要认证；
  env   —— 只在 .env / 环境变量里，DB 存变量名，不存密钥（推荐）；
  inline—— 存 DB，但接口只回显掩码（方便本地试用；共享实例不建议）。
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, JSON, UniqueConstraint

from .database import Base

# 能力标签：镜头要用什么动作，而不是「哪个模型」。端点声明自己支持哪些。
IMAGE_CAPABILITIES: dict[str, str] = {
    "txt2img": "文生图",
    "img2img": "图生图 / 参考生图",
    "inpaint": "局部重绘 / 主体替换",
    "remove_bg": "抠图 / 换背景",
    "upscale": "高清放大 / 超分",
    "outpaint": "扩图 / 补边",
    "style_transfer": "风格迁移",
    "tryon": "换装 / 搭配合成",
}

# 协议适配器：绝大多数生图/改图服务都能归到这三类之一
IMAGE_PROTOCOLS: dict[str, str] = {
    "openai_images": "OpenAI 兼容图像接口（/images/generations 与 /images/edits）",
    "volc_ark": "火山方舟 / Seedream 系（/images/generations，支持参考图）",
    "webhook": "通用 HTTP JSON（自托管服务、ComfyUI 代理、内部封装）",
    "mock": "内置占位图，永远可用，只作链路兜底",
}

# 可绑定端点的服务：五个出图功能 + 素材库单图即席处理
IMAGE_SERVICES: dict[str, str] = {
    "set": "商品套图",
    "style": "风格复刻",
    "sku": "SKU 替换",
    "outfit": "服装组图",
    "retouch": "精修",
    "adhoc": "素材即席处理",
}

MOCK_ENDPOINT_KEY = "_mock"


class ImageEndpoint(Base):
    __tablename__ = "image_endpoints"

    key = Column(String(40), primary_key=True)
    name = Column(String(60), nullable=False)
    protocol = Column(String(24), nullable=False, default="webhook")
    base_url = Column(String(500), nullable=False, default="")
    model = Column(String(120), nullable=False, default="")

    auth_mode = Column(String(12), nullable=False, default="none")  # none | env | inline
    api_key_env = Column(String(80), nullable=False, default="")     # env 模式：变量名
    api_key_inline = Column(Text, nullable=False, default="")        # inline 模式：密文（接口不回显）

    capabilities = Column(JSON, nullable=False, default=list)
    params = Column(JSON, nullable=False, default=dict)   # 默认参数：size / strength / seed / guidance…
    max_refs = Column(Integer, nullable=False, default=4)
    timeout_s = Column(Integer, nullable=False, default=60)
    enabled = Column(Boolean, nullable=False, default=True)
    priority = Column(Integer, nullable=False, default=100)  # 数字小的先试
    note = Column(Text, nullable=False, default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def secret_source(self) -> str:
        if self.auth_mode == "env":
            return f"env:{self.api_key_env}" if self.api_key_env else "env:(未指定变量)"
        if self.auth_mode == "inline":
            return "inline"
        return "none"

    def has_secret(self) -> bool:
        from app.services.image_endpoints import resolve_secret
        return bool(resolve_secret(self))

    def to_dict(self) -> dict:
        """接口返回：绝不携带完整密钥，只给来源与掩码"""
        secret = ""
        if self.auth_mode == "inline" and self.api_key_inline:
            secret = self.api_key_inline
        masked = f"••••{secret[-4:]}" if len(secret) > 4 else ("••••" if secret else "")
        return {
            "key": self.key,
            "name": self.name,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "model": self.model,
            "auth_mode": self.auth_mode,
            "api_key_env": self.api_key_env,
            "secret_source": self.secret_source(),
            "secret_masked": masked,
            "secret_ready": self.protocol == "mock" or self.auth_mode == "none" or self.has_secret(),
            "capabilities": list(self.capabilities or []),
            "params": dict(self.params or {}),
            "max_refs": self.max_refs or 0,
            "timeout_s": self.timeout_s or 60,
            "enabled": bool(self.enabled),
            "priority": self.priority if self.priority is not None else 100,
            "note": self.note or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ImageEndpointBinding(Base):
    """服务 → 候选端点有序链。capability 为空表示「该服务默认链」，具体能力链优先。"""
    __tablename__ = "image_endpoint_bindings"
    __table_args__ = (
        UniqueConstraint("service", "capability", "endpoint_key", name="uq_image_binding_service_cap_ep"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    service = Column(String(24), nullable=False, index=True)
    capability = Column(String(40), nullable=False, default="", index=True)
    endpoint_key = Column(String(40), nullable=False)
    priority = Column(Integer, nullable=False, default=100)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service": self.service,
            "capability": self.capability,
            "endpoint_key": self.endpoint_key,
            "priority": self.priority,
            "enabled": bool(self.enabled),
        }


class ImageProcessJob(Base):
    """素材库里对单张图做一次即席处理的记录（不需要走完整出图任务）"""
    __tablename__ = "image_process_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_no = Column(String(40), unique=True, nullable=False, index=True)
    asset_id = Column(Integer, nullable=False, index=True)
    operation = Column(String(40), nullable=False)
    endpoint_key = Column(String(40), nullable=True)   # 用户指定；空 = 按绑定链自动选
    params = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="queued", index=True)  # queued/running/done/failed
    result_asset_id = Column(Integer, nullable=True)
    engine = Column(String(24), nullable=True)         # 实际命中的协议
    used_endpoint = Column(String(40), nullable=True)  # 实际命中的端点（可能经过 fallback）
    latency_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    owner_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "job_no": self.job_no,
            "asset_id": self.asset_id,
            "operation": self.operation,
            "endpoint_key": self.endpoint_key,
            "params": self.params or {},
            "status": self.status,
            "result_asset_id": self.result_asset_id,
            "engine": self.engine,
            "used_endpoint": self.used_endpoint,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
