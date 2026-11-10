# -*- coding: utf-8 -*-
"""
图像端点注册中心：端点是数据，不是代码常量。

三件事：
  1) 端点 CRUD（可任意多个），密钥按 none / env / inline 三种模式解析，接口只回显掩码；
  2) 服务绑定：每个出图功能 / 即席处理各有一条「候选端点有序链」，运行时按能力挑；
  3) resolve_chain()：把「服务 + 镜头能力 + 本次指定端点」解析成一条可依次尝试的端点链，
     任何环节缺配置都自动落到内置 mock 端点，保证链路永远能跑完。
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session as DBSession

from app.config import get_settings
from app.models.image_endpoint import (
    IMAGE_CAPABILITIES,
    IMAGE_PROTOCOLS,
    IMAGE_SERVICES,
    MOCK_ENDPOINT_KEY,
    ImageEndpoint,
    ImageEndpointBinding,
)

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")


def resolve_secret(row: ImageEndpoint) -> str:
    """取真实密钥。env 模式优先读进程环境，再回退 pydantic-settings 读到的 .env 字段。"""
    mode = (row.auth_mode or "none").strip()
    if mode == "inline":
        return (row.api_key_inline or "").strip()
    if mode == "env":
        name = (row.api_key_env or "").strip()
        if not name:
            return ""
        direct = os.environ.get(name)
        if direct:
            return direct.strip()
        settings = get_settings()
        return (getattr(settings, name.lower(), "") or "").strip()
    return ""


def seed_mock_endpoint(db: DBSession) -> int:
    """启动时保证有一个永远可用的兜底端点，并给每个服务建一条指向它的默认链。"""
    created = 0
    row = db.get(ImageEndpoint, MOCK_ENDPOINT_KEY)
    if row is None:
        db.add(ImageEndpoint(
            key=MOCK_ENDPOINT_KEY,
            name="内置占位图（兜底）",
            protocol="mock",
            base_url="",
            model="mock",
            auth_mode="none",
            capabilities=list(IMAGE_CAPABILITIES.keys()),
            params={},
            max_refs=8,
            timeout_s=1,
            enabled=True,
            priority=9999,
            note="没有可用端点或全部调用失败时回落到这里，产出带 MOCK 标识的占位图",
        ))
        db.flush()
        created += 1

    for service in IMAGE_SERVICES:
        exists = (
            db.query(ImageEndpointBinding)
            .filter(
                ImageEndpointBinding.service == service,
                ImageEndpointBinding.capability == "",
            )
            .first()
        )
        if exists is None:
            db.add(ImageEndpointBinding(
                service=service,
                capability="",
                endpoint_key=MOCK_ENDPOINT_KEY,
                priority=9999,
                enabled=True,
            ))
            created += 1
    db.commit()
    return created


def _validate(payload: dict, *, creating: bool) -> dict:
    key = (payload.get("key") or "").strip().lower()
    if creating:
        if not KEY_RE.match(key):
            raise HTTPException(
                status_code=400,
                detail={"code": 41001, "message": "端点 key 需为 2-40 位小写字母/数字/下划线/连字符，且以字母数字开头"},
            )
        if key == MOCK_ENDPOINT_KEY:
            raise HTTPException(status_code=400, detail={"code": 41002, "message": "内置兜底端点的 key 不可占用"})

    name = (payload.get("name") or "").strip()[:60]
    if not name:
        raise HTTPException(status_code=400, detail={"code": 41003, "message": "端点名称不能为空"})

    protocol = (payload.get("protocol") or "webhook").strip()
    if protocol not in IMAGE_PROTOCOLS or protocol == "mock":
        raise HTTPException(status_code=400, detail={"code": 41004, "message": f"未知协议：{protocol}"})

    base_url = (payload.get("base_url") or "").strip()[:500]
    if protocol != "mock" and not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail={"code": 41005, "message": "base_url 需以 http:// 或 https:// 开头"})

    auth_mode = (payload.get("auth_mode") or "none").strip()
    if auth_mode not in ("none", "env", "inline"):
        raise HTTPException(status_code=400, detail={"code": 41006, "message": "auth_mode 只能是 none / env / inline"})
    if auth_mode == "env" and not (payload.get("api_key_env") or "").strip():
        raise HTTPException(status_code=400, detail={"code": 41007, "message": "env 模式必须填写环境变量名，如 ARK_API_KEY"})

    caps = payload.get("capabilities")
    caps = [c for c in caps if c in IMAGE_CAPABILITIES] if isinstance(caps, list) else []
    if protocol != "mock" and not caps:
        raise HTTPException(status_code=400, detail={"code": 41008, "message": "至少勾选一个能力标签"})

    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    clean_params = {str(k)[:40]: v for k, v in list(params.items())[:20]}

    try:
        max_refs = max(0, min(8, int(payload.get("max_refs") or 4)))
        timeout_s = max(3, min(300, int(payload.get("timeout_s") or 60)))
        priority = max(0, min(9998, int(payload.get("priority") or 100)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail={"code": 41009, "message": "数值参数不合法"})

    return {
        "key": key,
        "name": name,
        "protocol": protocol,
        "base_url": base_url,
        "model": (payload.get("model") or "").strip()[:120],
        "auth_mode": auth_mode,
        "api_key_env": (payload.get("api_key_env") or "").strip()[:80],
        "api_key_inline": (payload.get("api_key_inline") or "").strip()[:2000],
        "capabilities": caps,
        "params": clean_params,
        "max_refs": max_refs,
        "timeout_s": timeout_s,
        "enabled": bool(payload.get("enabled", True)),
        "priority": priority,
        "note": (payload.get("note") or "").strip()[:500],
    }


def list_endpoints(db: DBSession) -> List[dict]:
    rows = db.query(ImageEndpoint).order_by(ImageEndpoint.priority, ImageEndpoint.key).all()
    return [row.to_dict() for row in rows]


def save_endpoint(db: DBSession, payload: dict, *, creating: bool) -> dict:
    data = _validate(payload, creating=creating)
    key = data.pop("key")
    row = db.get(ImageEndpoint, key)
    if creating and row is not None:
        raise HTTPException(status_code=409, detail={"code": 41010, "message": f"端点 {key} 已存在"})
    if not creating and row is None:
        raise HTTPException(status_code=404, detail={"code": 41011, "message": f"端点 {key} 不存在"})

    # inline 模式下留空表示「不改密钥」，避免前端拿不到明文就把已有密钥清空
    if not creating and data["auth_mode"] == "inline" and not data["api_key_inline"] and row:
        data["api_key_inline"] = row.api_key_inline

    if row is None:
        row = ImageEndpoint(key=key, **data)
        db.add(row)
    else:
        for field, value in data.items():
            setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row.to_dict()


def delete_endpoint(db: DBSession, key: str) -> None:
    if key == MOCK_ENDPOINT_KEY:
        raise HTTPException(status_code=400, detail={"code": 41012, "message": "内置兜底端点不可删除"})
    row = db.get(ImageEndpoint, key)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": 41011, "message": f"端点 {key} 不存在"})
    db.query(ImageEndpointBinding).filter(ImageEndpointBinding.endpoint_key == key).delete(synchronize_session=False)
    db.delete(row)
    db.commit()


def list_bindings(db: DBSession) -> List[dict]:
    rows = db.query(ImageEndpointBinding).order_by(
        ImageEndpointBinding.service, ImageEndpointBinding.capability, ImageEndpointBinding.priority
    ).all()
    return [row.to_dict() for row in rows]


def set_bindings(db: DBSession, service: str, keys: List[str], capability: str = "") -> List[dict]:
    """替换某服务（某能力）的候选链；keys 顺序即 fallback 顺序。"""
    if service not in IMAGE_SERVICES:
        raise HTTPException(status_code=400, detail={"code": 41013, "message": f"未知服务：{service}"})
    if capability and capability not in IMAGE_CAPABILITIES:
        raise HTTPException(status_code=400, detail={"code": 41014, "message": f"未知能力：{capability}"})

    known = {row.key for row in db.query(ImageEndpoint).all()}
    clean: List[str] = []
    for key in keys:
        key = (key or "").strip()
        if key in known and key not in clean:
            clean.append(key)

    db.query(ImageEndpointBinding).filter(
        ImageEndpointBinding.service == service,
        ImageEndpointBinding.capability == capability,
    ).delete(synchronize_session=False)
    for index, key in enumerate(clean):
        db.add(ImageEndpointBinding(
            service=service,
            capability=capability,
            endpoint_key=key,
            priority=(index + 1) * 10,
            enabled=True,
        ))
    db.commit()
    return [row.to_dict() for row in (
        db.query(ImageEndpointBinding)
        .filter(ImageEndpointBinding.service == service, ImageEndpointBinding.capability == capability)
        .order_by(ImageEndpointBinding.priority)
        .all()
    )]


def resolve_chain(
    db: DBSession,
    service: str,
    capability: str = "",
    preferred_key: Optional[str] = None,
) -> List[Dict]:
    """解析成一条可依次尝试的端点链（内部用，含真实密钥，绝不直接返回给前端）。

    优先用「具体能力」的绑定链，再补「服务默认链」；
    本次任务指定了端点就把它提到最前，但保留后面的 fallback；
    末尾永远追加内置 mock，保证无配置也能把流程跑完。
    """
    if service not in IMAGE_SERVICES:
        service = "adhoc"

    caps_to_try = [capability, ""] if capability else [""]
    keys: List[str] = []
    for cap in caps_to_try:
        rows = (
            db.query(ImageEndpointBinding)
            .filter(
                ImageEndpointBinding.service == service,
                ImageEndpointBinding.capability == cap,
                ImageEndpointBinding.enabled.is_(True),
            )
            .order_by(ImageEndpointBinding.priority)
            .all()
        )
        for row in rows:
            if row.endpoint_key not in keys:
                keys.append(row.endpoint_key)

    if preferred_key and preferred_key in keys:
        keys.remove(preferred_key)
        keys.insert(0, preferred_key)
    elif preferred_key:
        # 允许任务临时指定一个「没绑定但要试」的端点；仍保留原链兜底
        keys.insert(0, preferred_key)

    if MOCK_ENDPOINT_KEY not in keys:
        keys.append(MOCK_ENDPOINT_KEY)

    chain: List[Dict] = []
    for key in keys:
        row = db.get(ImageEndpoint, key)
        if row is None or not row.enabled:
            continue
        if key != MOCK_ENDPOINT_KEY and capability and capability not in (row.capabilities or []):
            continue
        if key != MOCK_ENDPOINT_KEY and not resolve_secret(row) and row.auth_mode != "none":
            continue  # 密钥没配好就别浪费一次超时
        chain.append({
            **row.to_dict(),
            "secret": resolve_secret(row),
        })
    if not chain:
        row = db.get(ImageEndpoint, MOCK_ENDPOINT_KEY)
        if row:
            chain = [{**row.to_dict(), "secret": ""}]
    return chain


def describe(db: DBSession) -> dict:
    """设置页数据：端点（脱敏）、能力/协议/服务字典、绑定矩阵。"""
    return {
        "capabilities": [{"key": k, "label": v} for k, v in IMAGE_CAPABILITIES.items()],
        "protocols": [{"key": k, "label": v} for k, v in IMAGE_PROTOCOLS.items()],
        "services": [{"key": k, "label": v} for k, v in IMAGE_SERVICES.items()],
        "endpoints": list_endpoints(db),
        "bindings": list_bindings(db),
        "note": (
            "端点可任意添加；每个服务绑定一条有序候选链，运行时按镜头能力分派并可临时覆盖。"
            "密钥推荐用 env 模式只存变量名，接口不回显明文。"
        ),
    }
