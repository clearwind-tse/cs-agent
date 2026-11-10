# -*- coding: utf-8 -*-
"""
模型设置 API（设置页 · 模型信息）

只管「板块 → provider + 模型名」，不管密钥：
  - 密钥 / base_url 在 .env，GET 不回显、PUT 不接收，接口里出现 key 一律拒绝；
  - 覆盖值写 model_settings 表，代码默认值在 services/model_registry.py；
  - 保存后清掉 registry 的进程内缓存，业务调用点下一次取模型即生效，不用重启。
"""
import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.deps import get_current_user
from app.models.database import get_db
from app.models.model_setting import ModelSetting
from app.models.user import User
from app.services import model_registry
from app.services.model_registry import PROVIDERS, SLOTS

router = APIRouter(prefix="/api/model-settings", tags=["model-settings"])


class SlotChoice(BaseModel):
    provider: str = Field("auto", description="auto 或具体 provider key")
    model: str = Field("", description="模型名；空串 = 用 provider 默认模型")


class UpdateRequest(BaseModel):
    slots: Dict[str, SlotChoice] = Field(..., description="只提交要改的板块")


def _validate(slot: str, choice: SlotChoice) -> None:
    if slot not in SLOTS:
        raise HTTPException(status_code=400, detail={"code": 40010, "message": f"未知板块: {slot}"})
    provider = (choice.provider or "auto").strip()
    if provider != "auto" and provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail={"code": 40011, "message": f"未知 provider: {provider}"})
    slot_cap = SLOTS[slot]["capability"]
    provider_cap = PROVIDERS[provider]["capability"] if provider != "auto" else slot_cap
    # 只拦「embedding 与对话模型互串」；生图预留位允许走 chat 兼容端点
    if (slot_cap == "embedding") != (provider_cap == "embedding"):
        raise HTTPException(
            status_code=400,
            detail={
                "code": 40012,
                "message": f"「{SLOTS[slot]['label']}」需要 {slot_cap} 能力的 provider，{provider} 是 {provider_cap}",
            },
        )


@router.get("")
def get_model_settings(db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """设置页数据：分组、板块生效配置、provider 连通信息（不含密钥）"""
    return model_registry.describe()


@router.put("")
def update_model_settings(
    payload: UpdateRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量保存板块选择；未提交的板块保持原样"""
    for slot, choice in payload.slots.items():
        _validate(slot, choice)

    saved = []
    for slot, choice in payload.slots.items():
        row = db.get(ModelSetting, slot)
        provider = (choice.provider or "auto").strip()
        model = (choice.model or "").strip()[:120]
        if row:
            row.provider = provider
            row.model = model
        else:
            row = ModelSetting(slot=slot, provider=provider, model=model)
            db.add(row)
        saved.append(slot)
    db.commit()
    model_registry.invalidate_cache()
    return {"saved": saved, **model_registry.describe()}


@router.delete("/{slot}")
def reset_model_setting(
    slot: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删掉覆盖记录 → 回落到代码默认 + 自动挑 provider"""
    if slot not in SLOTS:
        raise HTTPException(status_code=400, detail={"code": 40010, "message": f"未知板块: {slot}"})
    row = db.get(ModelSetting, slot)
    if row:
        db.delete(row)
        db.commit()
    model_registry.invalidate_cache()
    return {"reset": slot, **model_registry.describe()}


class TestRequest(BaseModel):
    slot: str = Field(..., description="板块 key")
    provider: Optional[str] = Field(None, description="可选：临时覆盖 provider（用于保存前试跑）")
    model: Optional[str] = Field(None, description="可选：临时覆盖模型名")


@router.post("/test")
def test_model_setting(
    payload: TestRequest,
    current_user: User = Depends(get_current_user),
):
    """用当前（或临时覆盖的）配置发一个最小请求，验证 key / base_url / 模型名是否真的可用。

    只发 1 次、最多 15 秒、max_tokens=1；不会写库、不会改动生效配置。
    """
    if payload.slot not in SLOTS:
        raise HTTPException(status_code=400, detail={"code": 40010, "message": f"未知板块: {payload.slot}"})

    spec = SLOTS[payload.slot]
    if spec["status"] == "planned":
        return {
            "ok": False,
            "skipped": True,
            "detail": "该板块目前仍是规则引擎 / mock，没有真实模型调用，无需连通性测试",
            "slot": payload.slot,
        }

    override = None
    if payload.provider is not None or payload.model is not None:
        override = {
            "provider": (payload.provider or "auto").strip(),
            "model": (payload.model or "").strip(),
        }
        _validate(payload.slot, SlotChoice(**override))

    resolved = model_registry.resolve(payload.slot, override=override)
    result = {
        "slot": payload.slot,
        "provider": resolved.provider,
        "model": resolved.model,
        "base_url": resolved.base_url,
        "configured": resolved.configured,
    }
    if not resolved.configured:
        provider_spec = PROVIDERS[resolved.provider]
        return {
            **result,
            "ok": False,
            "detail": f"未配置密钥：请在 .env 设置 {provider_spec['env_key']}（base_url 用 {provider_spec['env_base']}）",
        }

    started = time.monotonic()
    try:
        if resolved.is_embedding:
            import requests
            response = requests.post(
                f"{resolved.base_url.rstrip('/')}/embeddings",
                headers={
                    "Authorization": f"Bearer {resolved.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": resolved.model, "input": ["连通性测试"]},
                timeout=15,
            )
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
            vector = response.json()["data"][0]["embedding"]
            sample = f"返回向量维度 {len(vector)}"
        else:
            from openai import OpenAI
            client = OpenAI(api_key=resolved.api_key, base_url=resolved.base_url, timeout=15, max_retries=0)
            response = client.chat.completions.create(
                model=resolved.model,
                messages=[{"role": "user", "content": "请只回复 OK"}],
                max_tokens=8,
                temperature=0,
            )
            sample = (response.choices[0].message.content or "").strip()[:60] or "(空回复)"
        return {
            **result,
            "ok": True,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "sample": sample,
            "detail": "连通正常",
        }
    except Exception as exc:
        return {
            **result,
            "ok": False,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "detail": f"调用失败：{type(exc).__name__}: {str(exc)[:300]}",
        }
