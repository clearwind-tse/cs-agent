# -*- coding: utf-8 -*-
"""
模型注册表 —— 全站「哪个板块用哪个模型」的唯一真源。

背景：改造前 deepseek-chat / gpt-4o-mini / qwen-plus / ep-2026… 硬编码散落在十几个
service 里，每个还各自写一遍 `if settings.deepseek_api_key else ...`。结果是：
  1) 想换个模型得改代码、重启服务；
  2) 自托管用户接本地 Ollama / 第三方兼容端点时，代码里的端点 ID 根本用不了；
  3) 同一个「质检」在不同入口可能跑在不同模型上，没人说得清。

分层约定（对应「设置页 vs 代码配置」的取舍）：
  - 密钥 / base_url 只在 .env，本模块只读不写，接口也绝不回显密钥；
  - 「板块 → provider + 模型名」放在 DB（model_settings 表），设置页可改、改完即生效；
  - 本文件的 SLOTS / PROVIDERS 是代码默认值，空库、DB 挂掉时全站仍能跑。

默认 provider 优先级刻意保持改造前每个服务各自的顺序，避免「配了 ARK_API_KEY 给
embedding 用，结果质检突然切到 qwen-plus」这类意外。想换就在设置页显式选。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.config import Settings, get_settings

# --------------------------------------------------------------------------- #
#  Provider：连接信息一律来自 .env；这里只描述「去哪里取」
# --------------------------------------------------------------------------- #

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "label": "DeepSeek",
        "key_fields": ["deepseek_api_key"],
        "base_field": "deepseek_base_url",
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "env_base": "DEEPSEEK_BASE_URL",
        "capability": "chat",
    },
    "openai": {
        "label": "OpenAI 兼容端点",
        "key_fields": ["openai_api_key"],
        "base_field": "openai_base_url",
        "default_model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
        "env_base": "OPENAI_BASE_URL",
        "capability": "chat",
        "hint": "把 OPENAI_BASE_URL 指向本地 Ollama / vLLM 即可用自托管模型",
    },
    "ark": {
        "label": "阿里云百炼 / DashScope",
        "key_fields": ["ark_api_key"],
        "base_field": "ark_base_url",
        "default_model": "qwen-plus",
        "env_key": "ARK_API_KEY",
        "env_base": "ARK_BASE_URL",
        "capability": "chat",
    },
    "ark_vision": {
        "label": "火山方舟",
        "key_fields": ["ark_vision_api_key", "ark_api_key"],  # 专用 Key 优先，回退通用 Key
        "base_field": "ark_vision_base_url",
        "default_model_field": "ark_vision_model",
        "default_model": "",
        "env_key": "ARK_VISION_API_KEY",
        "env_base": "ARK_VISION_BASE_URL",
        "capability": "chat",
    },
    "ark_embedding": {
        "label": "DashScope Embedding",
        "key_fields": ["ark_api_key"],
        "base_field": "ark_base_url",
        "default_model_field": "ark_embedding_model",
        "default_model": "text-embedding-v3",
        "env_key": "ARK_API_KEY",
        "env_base": "ARK_BASE_URL",
        "capability": "embedding",
    },
}

TEXT_FIRST_DEEPSEEK = ["deepseek", "openai"]
TEXT_FIRST_ARK = ["ark", "deepseek", "openai"]

# --------------------------------------------------------------------------- #
#  Slot：按业务板块划分，不按代码文件划分
# --------------------------------------------------------------------------- #

MODEL_GROUPS: List[Dict[str, str]] = [
    {"id": "run", "label": "在线服务", "hint": "直接面对客户，优先低延迟"},
    {"id": "data", "label": "数据与评测", "hint": "离线批量跑，通常更看重成本"},
    {"id": "special", "label": "专用能力与预留", "hint": "非对话模型，以及尚未接模型的能力位"},
]


def _slot(label: str, desc: str, group: str, preference: List[str],
          *, capability: str = "chat", status: str = "active",
          default_model: str = "", hint: str = "") -> Dict[str, Any]:
    return {
        "label": label,
        "desc": desc,
        "group": group,
        "preference": preference,
        "capability": capability,
        "status": status,                 # active = 已接模型；planned = 目前仍是规则/mock
        "default_model": default_model,  # 仅用于前端展示；空则从 provider 取
        "hint": hint,
    }


SLOTS: Dict[str, Dict[str, Any]] = {
    "chat": _slot(
        "在线客服对话", "客户话术生成、意图识别、对话状态跟踪", "run", TEXT_FIRST_DEEPSEEK,
        default_model="deepseek-chat",
    ),
    "agent": _slot(
        "Agent 编排", "Deep Agent / LangGraph Agent 的推理与工具调用", "run", TEXT_FIRST_DEEPSEEK,
        default_model="deepseek-chat",
    ),
    "rag": _slot(
        "知识库问答", "RAG 检索增强问答与流式回答", "run", TEXT_FIRST_ARK,
        default_model="qwen-plus",
    ),
    "qc": _slot(
        "质检与质量评分", "客服质检打分、红线检查、对话质量评分", "data", TEXT_FIRST_DEEPSEEK,
        default_model="deepseek-chat",
    ),
    "extract": _slot(
        "知识抽取", "从聊天记录抽取文章/知识点（LLM 精炼）", "data", TEXT_FIRST_ARK,
        default_model="qwen-plus",
    ),
    "distill": _slot(
        "知识蒸馏与改写", "RAG 知识条目蒸馏、Q/A 标准化改写", "data", TEXT_FIRST_DEEPSEEK,
        default_model="deepseek-chat",
    ),
    "filter": _slot(
        "数据清洗判定", "垃圾/广告消息的 LLM 分类判定", "data", TEXT_FIRST_DEEPSEEK,
        default_model="deepseek-chat",
    ),
    "quiz": _slot(
        "考核出题与评分", "培训考核题目生成、答案 AI 评分", "data", TEXT_FIRST_DEEPSEEK,
        default_model="deepseek-chat",
    ),
    "training_data": _slot(
        "训练数据生成", "SFT / DPO 样本与合成对话生成", "data", TEXT_FIRST_DEEPSEEK,
        default_model="deepseek-chat",
    ),
    "embedding": _slot(
        "文本向量化", "知识库切片与检索用的 Embedding", "special", ["ark_embedding"],
        capability="embedding", default_model="text-embedding-v3",
        hint="换模型会改变向量维度，需重建 knowledge_chunks / knowledge_articles 的向量列",
    ),
    "vision": _slot(
        "图片信息提取", "从截图识别学员名单等结构化信息", "special", ["ark_vision"],
        default_model="ep-…（ARK_VISION_MODEL）",
        hint="方舟模型名通常是 ep-xxxx 端点 ID，在 .env 的 ARK_VISION_MODEL 里配",
    ),
    "studio_plan": _slot(
        "AI 创作 · 出图规划", "逐镜头规划（当前为规则引擎，尚未调用 LLM）", "special",
        TEXT_FIRST_DEEPSEEK, status="planned", default_model="deepseek-chat",
    ),
    "studio_image": _slot(
        "AI 创作 · 图像生成", "实际出图（当前为 PIL mock 占位图，尚未接入图像模型）", "special",
        ["ark_vision"], capability="image", status="planned", default_model="",
        hint="预留位：接入 seedream 等生图模型后在此选择",
    ),
}

SLOT_KEYS = tuple(SLOTS.keys())


# --------------------------------------------------------------------------- #
#  解析结果
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ResolvedModel:
    slot: str
    provider: str
    model: str
    api_key: str
    base_url: str
    configured: bool
    source: str                 # override | default
    capability: str
    label: str

    @property
    def is_embedding(self) -> bool:
        return self.capability == "embedding"

    def public_dict(self) -> dict:
        """给 API/日志用：绝不带 api_key"""
        return {
            "slot": self.slot,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "configured": self.configured,
            "source": self.source,
        }


def _provider_key(settings: Settings, provider: str) -> str:
    for field in PROVIDERS[provider]["key_fields"]:
        value = (getattr(settings, field, "") or "").strip()
        if value:
            return value
    return ""


def _provider_model(settings: Settings, provider: str) -> str:
    spec = PROVIDERS[provider]
    field = spec.get("default_model_field")
    if field:
        return (getattr(settings, field, "") or "").strip() or spec.get("default_model", "")
    return spec.get("default_model", "")


def _provider_base(settings: Settings, provider: str) -> str:
    return (getattr(settings, PROVIDERS[provider]["base_field"], "") or "").strip()


def resolve(slot: str, override: Optional[Dict[str, str]] = None,
            settings: Optional[Settings] = None) -> ResolvedModel:
    """把「板块」解析成一组可直接建 client 的连接参数。

    override 为 None 时读 DB 覆盖（带 TTL 缓存）；传入 dict 时用于「设置页还没保存就先测一下」。
    任何异常（表未建、DB 挂了、slot 拼错）都回落到代码默认值，绝不让业务调用点崩掉。
    """
    s = settings or get_settings()
    spec = SLOTS.get(slot) or SLOTS["chat"]
    slot_key = slot if slot in SLOTS else "chat"
    ov = override if override is not None else get_overrides().get(slot_key, {})

    preference = list(spec["preference"])
    requested = (ov.get("provider") or "auto").strip()
    if requested != "auto" and requested in PROVIDERS and requested not in preference:
        # 允许用户在设置页把某板块切到未列入默认优先级的 provider
        preference = [requested] + preference

    if requested != "auto" and requested in PROVIDERS:
        provider = requested
    else:
        provider = preference[0]
        for candidate in preference:
            if _provider_key(s, candidate):
                provider = candidate
                break

    custom_model = (ov.get("model") or "").strip()
    model = custom_model[:120] or _provider_model(s, provider)
    api_key = _provider_key(s, provider)
    base_url = _provider_base(s, provider)

    # 用户显式选了某个 provider 但没配 key：保留 provider/model 供前端显示，configured=False
    return ResolvedModel(
        slot=slot_key,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        configured=bool(api_key and base_url),
        source="override" if ov else "default",
        capability=spec["capability"],
        label=spec["label"],
    )


# --------------------------------------------------------------------------- #
#  DB override：短 TTL 进程缓存，避免每次 LLM 调用都查一次库
# --------------------------------------------------------------------------- #

_OVERRIDE_TTL = 20.0
_cache_lock = threading.Lock()
_cache: Dict[str, Tuple[float, Dict[str, Dict[str, str]]]] = {}


def invalidate_cache() -> None:
    """设置页保存后调用；多实例部署时其余实例最多 20 秒后自动跟上"""
    with _cache_lock:
        _cache.clear()


def _load_overrides() -> Dict[str, Dict[str, str]]:
    try:
        from app.models.model_setting import ModelSetting
        from app.models.database import get_session_local

        db = get_session_local()()
        try:
            return {
                row.slot: {"provider": row.provider or "auto", "model": row.model or ""}
                for row in db.query(ModelSetting).all()
                if row.slot in SLOTS
            }
        finally:
            db.close()
    except Exception:
        # 表尚未创建 / DB 不可用 → 全部走代码默认，不阻断业务
        return {}


def get_overrides() -> Dict[str, Dict[str, str]]:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get("all")
        if hit and now - hit[0] < _OVERRIDE_TTL:
            return hit[1]
    data = _load_overrides()
    with _cache_lock:
        _cache["all"] = (now, data)
    return data


# --------------------------------------------------------------------------- #
#  调用点 helper：让十几个 service 的改动收敛成一行
# --------------------------------------------------------------------------- #

def credentials(slot: str) -> Tuple[str, str, str]:
    """返回 (api_key, base_url, model)；供直接拼 OpenAI(...) 的调用点使用"""
    r = resolve(slot)
    return r.api_key, r.base_url, r.model


def openai_client(slot: str, **client_kwargs):
    """返回 (OpenAI client | None, model_name)。

    没配 key 时返回 (None, model)，调用方原有的 `if not self.client: return …` 降级逻辑照常工作。
    额外 kwargs（timeout、max_retries 等）透传给 OpenAI 构造函数。
    """
    r = resolve(slot)
    if not r.configured:
        return None, r.model
    from openai import OpenAI
    return OpenAI(api_key=r.api_key, base_url=r.base_url, **client_kwargs), r.model


def chat_model(slot: str, fallback: str = "") -> str:
    """只要模型名（例如质检配置里已有 model 字段，但希望默认跟随设置页）"""
    return resolve(slot).model or fallback


# --------------------------------------------------------------------------- #
#  设置页视图
# --------------------------------------------------------------------------- #

def describe() -> dict:
    """给前端的完整描述。密钥不回显，只回显是否已配置 / 环境变量名 / base_url。"""
    s = get_settings()
    overrides = get_overrides()

    providers = []
    for key, spec in PROVIDERS.items():
        providers.append({
            "key": key,
            "label": spec["label"],
            "capability": spec["capability"],
            "configured": bool(_provider_key(s, key)),
            "base_url": _provider_base(s, key),
            "default_model": _provider_model(s, key),
            "env_key": spec["env_key"],
            "env_base": spec["env_base"],
            "hint": spec.get("hint", ""),
        })

    slots = []
    for key, spec in SLOTS.items():
        ov = overrides.get(key, {})
        effective = resolve(key, override=ov or None, settings=s)
        # 可选项 ≠ auto 优先级：auto 只在 preference 里挑，但用户应能显式选任意
        # 「能力兼容」的 provider（例如把质检切到百炼、把对话切到自托管 Ollama）。
        slot_cap = spec["capability"]
        compatible = [
            pkey for pkey, pspec in PROVIDERS.items()
            if pspec["capability"] == slot_cap
            or (slot_cap == "image" and pspec["capability"] == "chat")
        ]
        allowed = ["auto"] + (compatible or list(spec["preference"]))
        slots.append({
            "key": key,
            "label": spec["label"],
            "desc": spec["desc"],
            "group": spec["group"],
            "capability": spec["capability"],
            "status": spec["status"],
            "hint": spec.get("hint", ""),
            "provider": ov.get("provider", "auto"),
            "model": ov.get("model", ""),
            "custom": bool(ov),
            "allowed_providers": allowed,
            "default_model": spec["default_model"] or _provider_model(s, spec["preference"][0]),
            "effective_provider": effective.provider,
            "effective_model": effective.model,
            "effective_base_url": effective.base_url,
            "configured": effective.configured,
            "source": effective.source,
        })

    return {
        "groups": MODEL_GROUPS,
        "providers": providers,
        "slots": slots,
        "note": "API Key 与 base_url 只在 .env 配置，本页不保存也不回显密钥；改完模型即时生效，无需重启。",
    }
