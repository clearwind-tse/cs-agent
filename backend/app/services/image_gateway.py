# -*- coding: utf-8 -*-
"""
图像网关：把「镜头要做什么」交给「有能力做这件事的端点」。

改造前 studio_task_service._render_shot() 写死用 PIL 画占位图，端点这个概念不存在。
现在执行侧只认一个入口 process_image()：
  - 按服务 + 镜头能力 + 本次指定端点解析出候选链；
  - 逐个走协议适配器，失败自动换下一个（fallback 是数据，不是 if/else）；
  - 全失败回落到内置 mock 端点，调用方仍能产出占位图，链路不会断；
  - 返回「实际命中哪个端点、耗时、每次尝试的成败」，结果进素材库时一并记下来。

适配器只覆盖三类 OpenAI 兼容形态 + 通用 webhook，新增协议加一个 _call_xxx 即可，
不用改任务表、路由或前端。
"""
from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests
from sqlalchemy.orm import Session as DBSession
from urllib.parse import urlparse

from app.models.database import get_session_local
from app.models.image_endpoint import MOCK_ENDPOINT_KEY
from app.services import image_endpoints, media_store

Reference = Tuple[str, bytes]  # (mime, bytes)

# 自托管端点（ComfyUI / 内网封装 / 本机代理）常跑在 127.0.0.1，而部署环境里
# HTTP_PROXY 往往指向公司代理且 NO_PROXY 为空。默认 requests 会把回环请求也塞给代理，
# 表现为「端点明明在跑却连不上」。所以只对本机地址禁用 trust_env，外部端点仍走系统代理。
#
# 注意：requests.Session 不是线程安全的。端点自检（同步接口跑在线程池）与后台出图任务
# 会并发调用这里，共用一个 Session 会互相卡死（表现为任务永远停在 running/generating）。
# 本机调用本身不需要连接池，所以每次开一个短会话即可。
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _is_local(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in _LOCAL_HOSTS


def _http_post(url: str, **kwargs):
    if not _is_local(url):
        return requests.post(url, **kwargs)
    with requests.Session() as session:
        session.trust_env = False
        return session.post(url, **kwargs)


def _http_get(url: str, **kwargs):
    if not _is_local(url):
        return requests.get(url, **kwargs)
    with requests.Session() as session:
        session.trust_env = False
        return session.get(url, **kwargs)


@dataclass
class GatewayResult:
    image: Optional[bytes]
    mime: str = "image/png"
    endpoint_key: str = MOCK_ENDPOINT_KEY
    endpoint_name: str = "内置占位图"
    protocol: str = "mock"
    model: str = "mock"
    latency_ms: int = 0
    attempts: List[Dict] = field(default_factory=list)
    is_mock: bool = True
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "endpoint_key": self.endpoint_key,
            "endpoint_name": self.endpoint_name,
            "protocol": self.protocol,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "is_mock": self.is_mock,
            "reason": self.reason,
            "attempts": self.attempts,
        }


def read_asset_bytes(asset) -> Optional[Reference]:
    """从本地素材库读一张图，给端点当参考图。文件不在了就跳过，不让整单失败。"""
    try:
        path = media_store.safe_join(str(asset.rel_path))
        if not path.exists():
            return None
        raw = path.read_bytes()
        return (asset.mime or "image/png", raw)
    except Exception:
        return None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _decode_payload(data) -> Tuple[Optional[bytes], str]:
    """兼容各家响应：b64_json / image_base64 / data[].url / image_url / 裸 data URL。"""
    if isinstance(data, dict):
        for key in ("b64_json", "image_base64", "image_b64", "base64"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return _decode_base64_image(value), _mime_of(value, "image/png")
        for key in ("image", "output", "result", "data"):
            value = data.get(key)
            if isinstance(value, dict):
                found, mime = _decode_payload(value)
                if found:
                    return found, mime
            if isinstance(value, list) and value:
                found, mime = _decode_payload(value[0])
                if found:
                    return found, mime
            if isinstance(value, str) and value:
                if value.startswith("data:") or len(value) > 200:
                    found = _decode_base64_image(value)
                    if found:
                        return found, _mime_of(value, "image/png")
                if value.startswith(("http://", "https://")):
                    return _download(value)
        for key in ("url", "image_url", "download_url"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return _download(value)
    if isinstance(data, str):
        return _decode_base64_image(data), _mime_of(data, "image/png")
    return None, "image/png"


def _mime_of(value: str, default: str) -> str:
    if value.startswith("data:") and ";" in value:
        return value[5:].split(";", 1)[0] or default
    return default


def _decode_base64_image(value: str) -> Optional[bytes]:
    try:
        raw = value.split(",", 1)[1] if "," in value else value
        blob = base64.b64decode(raw, validate=False)
        if len(blob) < 100:
            return None
        # 只接受真图片，避免把错误 JSON 当图片落盘
        if blob[:8] == b"\x89PNG\r\n\x1a\n" or blob[:3] == b"\xff\xd8\xff" or blob[:4] == b"RIFF":
            return blob
        if blob[:6] in (b"GIF87a", b"GIF89a"):
            return blob
        return None
    except Exception:
        return None


def _download(url: str) -> Tuple[Optional[bytes], str]:
    response = _http_get(url, timeout=30)
    response.raise_for_status()
    return response.content, (response.headers.get("Content-Type") or "image/png").split(";")[0]


def _headers(ep: Dict) -> dict:
    headers = {"Content-Type": "application/json"}
    if ep.get("secret"):
        headers["Authorization"] = f"Bearer {ep['secret']}"
    return headers


def _merged_params(ep: Dict, params: Optional[dict]) -> dict:
    return {**(ep.get("params") or {}), **(params or {})}


def _call_webhook(ep: Dict, *, capability: str, prompt: str,
                  refs: List[Reference], params: dict) -> Tuple[Optional[bytes], str]:
    payload = {
        "operation": capability,
        "prompt": prompt,
        "model": ep.get("model") or "",
        "params": params,
        "images": [
            {"mime": mime, "base64": _b64(blob), "data_url": f"data:{mime};base64,{_b64(blob)}"}
            for mime, blob in refs
        ],
    }
    response = _http_post(ep["base_url"], json=payload, headers=_headers(ep), timeout=ep.get("timeout_s") or 60)
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError:
        return response.content, (response.headers.get("Content-Type") or "image/png").split(";")[0]
    return _decode_payload(body)


def _call_openai_images(ep: Dict, *, capability: str, prompt: str,
                        refs: List[Reference], params: dict) -> Tuple[Optional[bytes], str]:
    base = ep["base_url"].rstrip("/")
    headers = {}
    if ep.get("secret"):
        headers["Authorization"] = f"Bearer {ep['secret']}"
    size = str(params.get("size") or "1024x1024")
    model = ep.get("model") or "gpt-image-1"
    timeout = ep.get("timeout_s") or 60

    if refs:
        files = [("image[]", (f"ref-{i}.png", blob, mime)) for i, (mime, blob) in enumerate(refs)]
        data = {"model": model, "prompt": prompt, "size": size, "n": "1", "response_format": "b64_json"}
        response = _http_post(f"{base}/images/edits", headers=headers, data=data, files=files, timeout=timeout)
    else:
        data = {"model": model, "prompt": prompt, "size": size, "n": 1, "response_format": "b64_json"}
        response = _http_post(f"{base}/images/generations", headers=headers, json=data, timeout=timeout)
    response.raise_for_status()
    return _decode_payload(response.json())


def _call_volc_ark(ep: Dict, *, capability: str, prompt: str,
                   refs: List[Reference], params: dict) -> Tuple[Optional[bytes], str]:
    base = ep["base_url"].rstrip("/")
    payload = {
        "model": ep.get("model") or "",
        "prompt": prompt,
        "size": str(params.get("size") or "1024x1024"),
        "response_format": "b64_json",
        "watermark": False,
        "n": 1,
    }
    if refs:
        payload["image"] = [f"data:{mime};base64,{_b64(blob)}" for mime, blob in refs]
    extra = params.get("extra")
    if isinstance(extra, dict):
        payload.update({str(k): v for k, v in list(extra.items())[:20]})
    response = _http_post(
        f"{base}/images/generations", json=payload, headers=_headers(ep), timeout=ep.get("timeout_s") or 60
    )
    response.raise_for_status()
    return _decode_payload(response.json())


_ADAPTERS = {
    "webhook": _call_webhook,
    "openai_images": _call_openai_images,
    "volc_ark": _call_volc_ark,
}


def process_image(
    *,
    service: str,
    capability: str,
    prompt: str,
    refs: Optional[List[Reference]] = None,
    params: Optional[dict] = None,
    preferred_key: Optional[str] = None,
    single: bool = False,
    db: Optional[DBSession] = None,
) -> GatewayResult:
    """执行一次图像处理。single=True 只试指定端点（用于连通性自检，不触发 fallback）。"""
    own_session = db is None
    session = db or get_session_local()()
    started = time.monotonic()
    try:
        chain = image_endpoints.resolve_chain(session, service, capability, preferred_key)
        attempts: List[Dict] = []
        for ep in chain:
            protocol = ep.get("protocol")
            if protocol == "mock":
                continue
            adapter = _ADAPTERS.get(protocol)
            if adapter is None:
                attempts.append({"endpoint": ep["key"], "ok": False, "error": f"未实现的协议 {protocol}"})
                continue
            usable_refs = (refs or [])[: max(0, ep.get("max_refs") or 0)]
            try:
                blob, mime = adapter(
                    ep,
                    capability=capability,
                    prompt=prompt,
                    refs=usable_refs,
                    params=_merged_params(ep, params),
                )
                if not blob:
                    raise RuntimeError("响应里没有可解码的图片（b64_json / image_base64 / url）")
                attempts.append({"endpoint": ep["key"], "ok": True, "protocol": protocol})
                return GatewayResult(
                    image=blob,
                    mime=mime or "image/png",
                    endpoint_key=ep["key"],
                    endpoint_name=ep["name"],
                    protocol=protocol,
                    model=ep.get("model") or "",
                    latency_ms=round((time.monotonic() - started) * 1000),
                    attempts=attempts,
                    is_mock=False,
                )
            except Exception as exc:
                attempts.append({"endpoint": ep["key"], "ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                if single:
                    break

        reasons = "; ".join(a["error"] for a in attempts if not a["ok"])
        return GatewayResult(
            image=None,
            latency_ms=round((time.monotonic() - started) * 1000),
            attempts=attempts,
            is_mock=True,
            reason=reasons or "没有可用的图像端点，回落内置占位图",
        )
    finally:
        if own_session:
            session.close()
