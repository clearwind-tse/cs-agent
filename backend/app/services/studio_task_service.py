# -*- coding: utf-8 -*-
"""
AI 创作任务服务：规划 → 确认 → 执行

当前阶段（P1/P2）的取舍，写清楚免得以后误读：
1. **规划用规则引擎，不接大模型**。同一个输入每次产出同一份规划，便于测试与比对；
   结构（shots / size / composition / prompt）与将来 LLM 产出的完全一致，
   换 LLM 只替换 `build_plan` 里 rule 那一段，路由与前端不用动。
2. **出图走图像网关，不再写死一个模型**：每张镜头带 `capability`（要做什么动作），
   执行时由 `image_gateway.process_image()` 按「服务 + 能力 + 本次指定端点」解析候选链，
   逐个走协议适配器、失败自动 fallback；全部失败才回落到 PIL 占位图。
   端点池与服务绑定都是数据，UI 可增删改，不用改这里的代码。
3. 引擎信息通过 /api/studio/engine 暴露，前端会显式标「有没有真实端点」——
   即使配了端点，单次调用失败回落占位图时也会在产出里如实标注，不让人误以为是真成图。
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_session_local
from app.models.media import MediaAsset
from app.models.studio_task import StudioTask, TASK_KINDS
from app.services import media_assets, media_store

# 长边固定：出图比这更大在 UI 里也只是缩略图，白占磁盘
RATIO_SIZES = {
    "1:1": (1200, 1200),
    "3:4": (1080, 1440),
    "4:3": (1440, 1080),
    "16:9": (1600, 900),
}

# 每种任务出图序列：不同功能该出哪几张，是这个产品最核心的知识
SHOT_TEMPLATES: dict[str, list[dict]] = {
    "set": [
        {"title": "主图 · 正面", "composition": "主体居中，正面平视，白底留白 12%", "copy": "核心卖点一句话"},
        {"title": "主图 · 45°", "composition": "左前 45° 视角，柔和侧光，展示厚度", "copy": "材质与工艺"},
        {"title": "主图 · 细节", "composition": "局部微距，突出五金 / 走线 / 纹理", "copy": "细节特写"},
        {"title": "场景图", "composition": "生活场景摆放，浅景深，环境光自然", "copy": "使用场景"},
        {"title": "详情图 · 尺寸", "composition": "竖版信息图，主体 + 尺寸标注线", "copy": "尺寸与容量"},
        {"title": "详情图 · 卖点", "composition": "竖版分栏，左侧主体右侧三条卖点", "copy": "三个卖点短句"},
    ],
    "style": [
        {"title": "风格套用 · 正面", "composition": "沿用参考图的色温与留白比例，主体正面", "copy": "沿用参考图文案节奏"},
        {"title": "风格套用 · 侧面", "composition": "同风格，换角度，保持光位一致", "copy": "延续同一调性"},
        {"title": "风格套用 · 场景", "composition": "同风格场景化，保持色板一致", "copy": "场景延展"},
    ],
    "sku": [
        {"title": "替换图 · 原版式", "composition": "锁定底图版式与投影，只换画面主体", "copy": "沿用底图文案"},
        {"title": "替换图 · 光影校准", "composition": "同上，投影方向与底图对齐", "copy": "沿用底图文案"},
    ],
    "outfit": [
        {"title": "成套 · 正面", "composition": "上下装同框，模特正面，版型清晰", "copy": "搭配组合名"},
        {"title": "成套 · 侧面", "composition": "同一次生成内锁定人物与场景", "copy": "延续搭配"},
        {"title": "单品 · 上装", "composition": "上装单穿，白底，与成套图同款", "copy": "上装卖点"},
        {"title": "单品 · 下装", "composition": "下装单穿，白底，与成套图同款", "copy": "下装卖点"},
    ],
    "retouch": [
        {"title": "精修 · 去瑕疵", "composition": "保持原构图，去除瑕疵与水印", "copy": ""},
        {"title": "精修 · 换背景", "composition": "主体抠出，替换为纯净背景", "copy": ""},
        {"title": "精修 · 提清晰度", "composition": "原图超分，边缘锐化但不过度", "copy": ""},
    ],
}

KIND_LABELS = {
    "set": "商品套图",
    "style": "风格复刻",
    "sku": "SKU 替换",
    "outfit": "服装组图",
    "retouch": "精修",
}

# 与前端 studioKinds.ts 一一对应的输入契约。
# 前端负责按它渲染表单，后端负责按它做白名单清洗与规划——改 key 两边要同步。
# slots 是有角色的素材位（「底图」和「新商品图」不是同一堆图）；
# fields 规则：(类型, 允许值或 None, 默认值或 None)。未知 key 一律丢弃，不报错也不误用。
KIND_CONFIG: dict[str, dict] = {
    "set": {
        "slots": ("product", "reference"),
        "fields": {
            "platform": ("choice", ("通用", "淘宝主图", "抖音竖版", "小红书"), "通用"),
            "modules": ("multi", ("尺寸标注", "卖点分栏", "材质特写", "场景"), None),
            "selling_point": ("text", None, ""),
        },
    },
    "style": {
        "slots": ("reference", "product"),
        "fields": {
            "lock": ("multi", ("色板", "光线", "构图", "材质"), None),
            "similarity": ("choice", ("严格", "平衡", "只要感觉"), "平衡"),
        },
    },
    "sku": {
        "slots": ("base", "new_sku"),
        "fields": {
            "region": ("text", None, ""),
            "shadow": ("choice", ("沿用底图投影", "按新品重算"), "沿用底图投影"),
        },
    },
    "outfit": {
        "slots": ("top", "bottom", "model"),
        "fields": {
            "pose": ("choice", ("站姿", "坐姿", "行走"), "站姿"),
            "scene": ("choice", ("棚拍", "街拍", "居家"), "棚拍"),
            "scope": ("choice", ("成套 + 单品", "只要成套"), "成套 + 单品"),
        },
    },
    "retouch": {
        "slots": ("source",),
        "fields": {
            "fixes": ("multi", ("去瑕疵", "去水印", "换背景", "提清晰度"), None),
            "background": ("text", None, ""),
        },
    },
}

# 精修是按勾选项出图的，构图逐项不同，不能套用统一的镜头模板
FIX_COMPOSITIONS = {
    "去瑕疵": "保持原构图，去除表面瑕疵、划痕与水印，不改变材质纹理",
    "去水印": "局部重绘覆盖水印区域，周边纹理自然衔接",
    "换背景": "主体抠出，替换为指定背景，边缘与投影重新匹配",
    "提清晰度": "原图超分，边缘适度锐化，保留细节不过曝",
}

# 规划上限：SKU / 组图 / 精修会按「素材数 × 每项张数」放大，避免一次排几十张
MAX_PLAN_SHOTS = 8

# 后台任务是进程内的：进程被 kill / uvicorn reload / 机器重启时，
# 任务不会收到任何回调，会永远停在 generating。查询时顺手把这些「僵尸任务」收掉。
# run_generation 每出一张图就 commit 一次，updated_at 会被 onupdate 刷新，
# 所以「90 秒没推进」等价于「执行卡死了」。
# 注意：接真实图像模型后单张可能超过 90 秒，这个值要跟着调大或改成心跳上报。
STALE_AFTER_SECONDS = 90


def is_stale(task: StudioTask) -> bool:
    if task.status != "generating":
        return False
    stamp = task.updated_at or task.started_at or task.created_at
    if not stamp:
        return True
    return datetime.utcnow() - stamp > timedelta(seconds=STALE_AFTER_SECONDS)


def sweep_stale_tasks(db: DBSession) -> int:
    """查询时顺手收掉「超时未推进」的 generating，让用户可以重跑，而不是永远转圈"""
    return _fail_generating(
        db,
        lambda t: is_stale(t),
        "执行超时：后台进程可能已中断，请重跑",
    )


def recover_interrupted_tasks(db: DBSession) -> int:
    """
    进程启动时调用：BackgroundTasks 是进程内的，新进程一起来，
    库里所有 generating 都必然是上一轮进程留下的孤儿，不可能还在跑。

    注意前提是单 worker；将来如果改成多 worker / 独立任务队列（Celery、RQ），
    这里要换成按 worker 心跳判断，不能一刀切。
    """
    return _fail_generating(
        db,
        lambda t: True,
        "服务重启：后台任务已中断，请重跑",
    )


def _fail_generating(db: DBSession, predicate, reason: str) -> int:
    rows = [
        t
        for t in db.query(StudioTask).filter(StudioTask.status == "generating").all()
        if predicate(t)
    ]
    for task in rows:
        task.status = "failed"
        task.error = reason
        task.finished_at = datetime.utcnow()
    if rows:
        db.commit()
    return len(rows)


def engine_info(db: Optional[DBSession] = None) -> dict:
    """当前引擎：前端据此显式标注「有没有真实端点」，不能让人以为是真出图"""
    has_real = False
    endpoint_count = 0
    if db is not None:
        try:
            from app.services import image_endpoints
            rows = image_endpoints.list_endpoints(db)
            endpoint_count = len([e for e in rows if e["protocol"] != "mock"])
            has_real = any(e["protocol"] != "mock" and e["enabled"] and e["secret_ready"] for e in rows)
        except Exception:
            pass
    return {
        "planner": "rule",
        "planner_label": "规则规划（未接 LLM）",
        "image_engine": "gateway" if has_real else "mock",
        "image_engine_label": (
            "图像端点网关（按镜头能力分派，失败回落占位图）" if has_real else "占位图合成（还没有可用端点）"
        ),
        "is_mock": not has_real,
        "endpoint_count": endpoint_count,
        "ratios": list(RATIO_SIZES.keys()),
        "max_shots": 8,
        "kinds": [{"kind": k, "label": v} for k, v in KIND_LABELS.items()],
    }


def _next_task_no(db: DBSession) -> str:
    day = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"ST{day}-"
    last = (
        db.query(StudioTask)
        .filter(StudioTask.task_no.like(f"{prefix}%"))
        .order_by(StudioTask.task_no.desc())
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.task_no.rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            seq = 1
    return f"{prefix}{seq:03d}"


def _clean_config(kind: str, raw: object) -> dict:
    """按 KIND_CONFIG 白名单清洗专属配置：未知 key 丢弃，非法选项回落默认"""
    spec = KIND_CONFIG[kind]
    if not isinstance(raw, dict):
        raw = {}
    raw_slots = raw.get("slots") if isinstance(raw.get("slots"), dict) else {}
    raw_fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}

    slots: dict[str, list[int]] = {}
    for key in spec["slots"]:
        values = raw_slots.get(key)
        if not isinstance(values, list):
            values = []
        ids: list[int] = []
        for value in values[:8]:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        slots[key] = ids[:8]

    fields: dict[str, object] = {}
    for key, rule in spec["fields"].items():
        rule_type, allowed, default = rule
        value = raw_fields.get(key)
        if rule_type == "multi":
            picked = value if isinstance(value, list) else []
            fields[key] = [str(v)[:40] for v in picked if str(v) in set(allowed or ())][:8]
        elif rule_type == "choice":
            text = str(value or "")[:40]
            fields[key] = text if text in set(allowed or ()) else default
        else:
            fields[key] = str(value or "").strip()[:120]
    return {"slots": slots, "fields": fields}


def normalize_payload(kind: str, payload: dict) -> dict:
    """收敛输入：kind / 比例 / 专属配置都做白名单，避免前端传什么就用什么"""
    if kind not in TASK_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 40010, "message": f"未知任务类型：{kind}"},
        )

    config = _clean_config(kind, payload.get("config"))
    # asset_ids 以服务端重算为准：前端只是把 slots 扁平化方便校验，
    # 真正决定「哪张图是哪个角色」的是 config.slots。
    slot_ids: list[int] = list(
        dict.fromkeys(asset_id for ids in config["slots"].values() for asset_id in ids)
    )
    fallback_ids: list[int] = []
    for value in payload.get("asset_ids") or []:
        try:
            fallback_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    asset_ids = (slot_ids or fallback_ids)[:8]

    ratio = payload.get("ratio") or "1:1"
    if ratio not in RATIO_SIZES:
        ratio = "1:1"

    try:
        count = int(payload.get("count") or 4)
    except (TypeError, ValueError):
        count = 4
    count = max(1, min(8, count))

    note = (payload.get("note") or "").strip()[:500]

    # 运行时选择：本次任务指定用哪个端点（空 = 按服务绑定链自动挑）。
    # 它只是一次覆盖，不改绑定数据；后续 fallback 链仍然生效。
    endpoint_key = (str(payload.get("endpoint_key") or "").strip()[:40]) or None
    raw_params = payload.get("endpoint_params")
    endpoint_params = (
        {str(k)[:40]: v for k, v in list(raw_params.items())[:20]}
        if isinstance(raw_params, dict) else {}
    )

    return {
        "asset_ids": asset_ids,
        "count": count,
        "ratio": ratio,
        "note": note,
        "config": config,
        "endpoint_key": endpoint_key,
        "endpoint_params": endpoint_params,
    }


def infer_capability(kind: str, title: str, has_assets: bool) -> str:
    """把「这一镜头要做的动作」翻译成能力标签，供网关挑端点。

    这是「动态分派」的关键：同一个任务里，换背景镜头会去找 remove_bg 端点，
    超分镜头去找 upscale 端点，而不是整单绑死一个模型。
    """
    if "换背景" in title or "抠" in title:
        return "remove_bg"
    if "提清晰度" in title or "超分" in title or "锐化" in title:
        return "upscale"
    if "去瑕疵" in title or "去水印" in title or "精修" in title:
        return "inpaint"
    if "扩图" in title or "补边" in title:
        return "outpaint"
    if kind == "sku" or "替换" in title:
        return "inpaint"
    if kind == "style":
        return "style_transfer"
    if kind == "outfit":
        return "tryon"
    return "img2img" if has_assets else "txt2img"


def annotate_plan_endpoints(db: DBSession, kind: str, plan: dict, preferred_key: Optional[str]) -> dict:
    """规划阶段就把「每张镜头将用哪个端点」摊开给人看，确认前能改，不用等跑完才知道。

    端点表还没建好 / DB 异常时静默回落到 mock 标注，不能让建任务失败。
    """
    try:
        from app.services import image_endpoints
        for shot in plan.get("shots") or []:
            chain = image_endpoints.resolve_chain(db, kind, shot.get("capability") or "img2img", preferred_key)
            real = [ep for ep in chain if ep["protocol"] != "mock"]
            picked = real[0] if real else None
            shot["endpoint_key"] = picked["key"] if picked else "_mock"
            shot["endpoint_name"] = picked["name"] if picked else "内置占位图（兜底）"
            shot["endpoint_ready"] = bool(picked)
            shot["endpoint_options"] = [
                {"key": ep["key"], "name": ep["name"], "protocol": ep["protocol"]} for ep in real
            ][:6]
    except Exception as exc:
        for shot in plan.get("shots") or []:
            shot.setdefault("endpoint_key", "_mock")
            shot.setdefault("endpoint_name", "内置占位图（兜底）")
            shot.setdefault("endpoint_ready", False)
            shot.setdefault("endpoint_options", [])
        plan["endpoint_warning"] = f"端点解析失败，已回落占位图：{str(exc)[:160]}"
    plan["endpoint_key"] = preferred_key or "auto"
    return plan


def build_plan(kind: str, payload: dict, assets: list[MediaAsset]) -> dict:
    """
    规则规划器：按功能专属配置把「要出哪几张、每张用什么、按什么规则」摊开给人看。

    这里刻意**不共用一套镜头循环**：SKU 替换是按新商品图逐个出图、精修是按勾选项出图、
    组图是按上下装组合出图，硬套同一个模板就会让五个功能的规划长得一模一样。
    每张 shot 带 meta（专属元信息），前端只负责渲染，不用为每个功能写一套卡片。

    prompt 字段仍然保留：将来换成 LLM 产出规划时结构一致，出图侧只认 prompt。
    """
    width, height = RATIO_SIZES[payload["ratio"]]
    size = f"{width}x{height}"
    config = payload.get("config") or {}
    slots = config.get("slots") or {}
    fields = config.get("fields") or {}
    count = payload["count"]
    note = payload.get("note") or ""
    by_id = {a.id: a for a in assets}

    def names(key: str) -> list[str]:
        return [by_id[i].original_name for i in slots.get(key, []) if i in by_id]

    def first(key: str) -> str:
        values = names(key)
        return values[0] if values else ""

    templates = SHOT_TEMPLATES.get(kind, SHOT_TEMPLATES["set"])
    shots: list[dict] = []
    warnings: list[str] = []
    summary = ""
    truncated = False

    def add(title: str, composition: str, copy: str, meta_pairs: list[tuple]) -> bool:
        """统一收口：限量、编号、拼 prompt、生成 meta"""
        if len(shots) >= MAX_PLAN_SHOTS:
            return False
        shots.append(
            {
                "index": len(shots) + 1,
                "title": title[:60],
                "size": size,
                "composition": composition[:200],
                "copy": copy[:120],
                "prompt": (
                    f"{KIND_LABELS.get(kind, kind)}，{title}。"
                    f"构图：{composition}。尺寸 {size}。"
                    + (f"文案：{copy}。" if copy else "")
                    + (f"补充要求：{note}。" if note else "")
                    + "画质：商业级，光线干净，主体清晰。"
                ),
                "capability": infer_capability(kind, title, bool(assets)),
                "meta": [
                    {"label": label, "value": str(value)}
                    for label, value in meta_pairs
                    if value
                ],
            }
        )
        return True

    if kind == "set":
        products, refs = names("product"), names("reference")
        platform = fields.get("platform") or "通用"
        modules = fields.get("modules") or []
        selling = fields.get("selling_point") or ""
        for index in range(count):
            template = templates[index % len(templates)]
            module = modules[(index // 2) % len(modules)] if modules else ""
            ok = add(
                template["title"],
                f"{platform} · {template['composition']}" + (f" · 详情模块：{module}" if module else ""),
                selling or template["copy"],
                [
                    ("目标平台", platform),
                    ("详情模块", module),
                    ("商品图", first("product")),
                    ("风格参考", first("reference")),
                    ("核心卖点", selling),
                ],
            )
            if not ok:
                truncated = True
                break
        if not products:
            warnings.append("还没有商品图，本任务只能产出构图占位图；建议先从素材库选图")
        if not modules:
            warnings.append("没有勾选详情模块，本次只出主图序列")
        summary = f"商品套图 · {len(products)} 张商品图 / {len(refs)} 张参考 · {platform} · 产出 {len(shots)} 张"

    elif kind == "style":
        locks = fields.get("lock") or []
        similarity = fields.get("similarity") or "平衡"
        refs, products = names("reference"), names("product")
        for index in range(count):
            template = templates[index % len(templates)]
            ok = add(
                template["title"],
                f'锁定 {"、".join(locks) or "未指定维度"} · {similarity}；{template["composition"]}',
                template["copy"],
                [
                    ("锁定维度", " / ".join(locks)),
                    ("复刻强度", similarity),
                    ("风格参考", first("reference")),
                    ("目标商品", first("product")),
                ],
            )
            if not ok:
                truncated = True
                break
        if not refs:
            warnings.append("没有风格参考图，风格画像无从提取")
        if not products:
            warnings.append("没有目标商品图，只能产出风格示意占位图")
        if not locks:
            warnings.append("未勾选锁定维度，跨图一致性会比较差")
        summary = f'风格复刻 · 锁定 {"、".join(locks) or "无"} · {similarity} · 产出 {len(shots)} 张'

    elif kind == "sku":
        base = first("base")
        new_skus = names("new_sku")[:6]
        shadow = fields.get("shadow") or "沿用底图投影"
        region = fields.get("region") or ""
        if not base:
            warnings.append("没有底图，无法沿用版式与光影")
        if not new_skus:
            warnings.append("没有新商品图，本次只产出 1 张版式示意占位图")
            new_skus = ["未指定新品"]
        sku_templates = SHOT_TEMPLATES["sku"]
        for sku in new_skus:
            for offset in range(count):
                template = sku_templates[offset % len(sku_templates)]
                ok = add(
                    f'{sku} · {template["title"]}',
                    f'沿用底图「{base or "未提供"}」的版式；{template["composition"]}；{shadow}'
                    + (f"；替换区域：{region}" if region else ""),
                    template["copy"],
                    [("底图", base), ("新 SKU", sku), ("投影", shadow), ("替换区域", region)],
                )
                if not ok:
                    truncated = True
                    break
            if truncated:
                break
        summary = f"SKU 替换 · 1 张底图 × {len(new_skus)} 个新品 · {shadow} · 产出 {len(shots)} 张"

    elif kind == "outfit":
        tops, bottoms = names("top"), names("bottom")
        pose = fields.get("pose") or "站姿"
        scene = fields.get("scene") or "棚拍"
        scope = fields.get("scope") or "成套 + 单品"
        model = first("model")
        if not tops:
            warnings.append("没有上装图，已用占位搭配生成规划")
            tops = ["未指定上装"]
        if not bottoms:
            warnings.append("没有下装图，已用占位搭配生成规划")
            bottoms = ["未指定下装"]
        for top in tops[:2]:
            for bottom in bottoms[:2]:
                for offset in range(count):
                    template = templates[offset % len(templates)]
                    if scope == "只要成套" and "单品" in template["title"]:
                        continue
                    ok = add(
                        f'{top} × {bottom} · {template["title"]}',
                        f"{pose} · {scene} · 同批锁定人物与场景；{template['composition']}",
                        template["copy"],
                        [
                            ("上装", top),
                            ("下装", bottom),
                            ("姿势 / 场景", f"{pose} / {scene}"),
                            ("模特图", model),
                            ("产出范围", scope),
                        ],
                    )
                    if not ok:
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break
        summary = f"服装组图 · {len(tops)} 上装 × {len(bottoms)} 下装 · {pose}/{scene} · 产出 {len(shots)} 张"

    elif kind == "retouch":
        fixes = fields.get("fixes") or []
        background = fields.get("background") or ""
        source = first("source")
        if not fixes:
            warnings.append("没有勾选修复项，已按「去瑕疵」生成基础规划")
            fixes = ["去瑕疵"]
        if "换背景" in fixes and not background:
            warnings.append("勾选了换背景但没写目标背景，将用纯净背景占位")
        if not source:
            warnings.append("还没有原图，本任务只能产出修复项占位图")
        for fix in fixes:
            for offset in range(count):
                title = fix if count == 1 else f"{fix} · 第 {offset + 1} 版"
                ok = add(
                    title,
                    FIX_COMPOSITIONS.get(fix, "按修复项处理原图"),
                    "",
                    [
                        ("原图", source),
                        ("修复项", fix),
                        ("目标背景", background if fix == "换背景" else ""),
                    ],
                )
                if not ok:
                    truncated = True
                    break
            if truncated:
                break
        summary = f'精修 · {"、".join(fixes)} · 产出 {len(shots)} 张'

    if count > len(templates) and kind in ("set", "style", "sku", "outfit"):
        warnings.append(f"该功能预置了 {len(templates)} 个镜头，超出部分会按顺序循环复用")
    if truncated:
        warnings.append(f"一次最多规划 {MAX_PLAN_SHOTS} 张，超出部分已截断；可拆成多次任务")

    return {
        "engine": "rule",
        "kind": kind,
        "summary": summary or f"{KIND_LABELS.get(kind, kind)} · 产出 {len(shots)} 张",
        "shots": shots,
        "warnings": warnings,
        "inputs": [
            {"id": a.id, "name": a.original_name, "url": f"{media_store_prefix()}/{a.rel_path}"}
            for a in assets
        ],
    }


def _endpoint_size(raw: str) -> str:
    """内部尺寸 → 常见图像端点接受的规格。端点自己的 params.size 优先，可任意覆盖。"""
    try:
        width, height = (int(v) for v in str(raw).split("x"))
    except (TypeError, ValueError):
        return "1024x1024"
    if width == height:
        return "1024x1024"
    return "1024x1536" if height > width else "1536x1024"


def _result_category(title: str) -> str:
    """按镜头标题给生成结果分二级目录；这三个 key 都是 result 下的预置目录"""
    if title.startswith("主图"):
        return "main"
    if "详情" in title:
        return "detail"
    return "variant"


def like_multi(kind: str) -> bool:
    return kind in ("set", "outfit", "style")


def create_task(db: DBSession, kind: str, payload: dict, owner_id: Optional[int]) -> StudioTask:
    normalized = normalize_payload(kind, payload)

    assets: list[MediaAsset] = []
    if normalized["asset_ids"]:
        assets = db.query(MediaAsset).filter(MediaAsset.id.in_(normalized["asset_ids"])).all()
        if len(assets) != len(normalized["asset_ids"]):
            missing = set(normalized["asset_ids"]) - {a.id for a in assets}
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": 40011, "message": f"素材不存在：{sorted(missing)}"},
            )

    plan = build_plan(kind, normalized, assets)
    annotate_plan_endpoints(db, kind, plan, normalized.get("endpoint_key"))
    task = StudioTask(
        task_no=_next_task_no(db),
        kind=kind,
        status="planned",          # 规划同步算完，直接进「待确认」
        input=normalized,
        plan=plan,
        progress=0,
        total_shots=len(plan["shots"]),
        done_shots=0,
        owner_id=owner_id,
        created_at=datetime.utcnow(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ==================== 执行 ====================

def _load_font(size: int):
    """中文字体优先，找不到就退回默认字体并改用英文，避免渲染出一排方框"""
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size), path.endswith(("PingFang.ttc", "NotoSansCJK-Regular.ttc", "Songti.ttc"))
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size), False
    except TypeError:
        return ImageFont.load_default(), False


def _render_shot_base(shot: dict, base_asset: Optional[MediaAsset]) -> Image.Image:
    """
    渐变底 + 右下角贴一张输入素材缩略图。

    不把底图铺满：底图若本身就是带文字的截图 / 上一轮的占位图，
    铺满后再叠水印会出现两层文字打架，反而看不清这张图代表什么。
    """
    width, height = (int(v) for v in shot["size"].split("x"))
    canvas = Image.new("RGB", (width, height), (21, 20, 49))
    draw = ImageDraw.Draw(canvas)
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line(
            [(0, y), (width, y)],
            fill=(int(24 + 40 * t), int(22 + 26 * t), int(52 + 70 * t)),
        )

    if base_asset:
        path = media_store.safe_join(base_asset.rel_path)
        if path.exists():
            try:
                pad = max(16, max(width, height) // 34)
                thumb_w = max(80, width // 5)
                thumb_h = max(60, height // 5)
                with Image.open(path) as source:
                    thumb = ImageOps.fit(source.convert("RGB"), (thumb_w, thumb_h), Image.LANCZOS)
                tx = width - thumb_w - pad
                ty = int(height * 0.30)
                canvas.paste(thumb, (tx, ty))
                draw.rectangle(
                    [tx - 2, ty - 2, tx + thumb_w + 1, ty + thumb_h + 1],
                    outline=(139, 123, 255),
                    width=2,
                )
                draw.text(
                    (tx + thumb_w, ty + thumb_h + pad // 2),
                    "INPUT",
                    font=ImageFont.load_default(),
                    fill=(169, 155, 255),
                    anchor="ra",
                )
            except Exception:
                pass
    return canvas


def _render_shot(shot: dict, base_asset: Optional[MediaAsset], task: StudioTask, total: int) -> bytes:
    """把一张规划渲染成 PNG 字节。接真实模型时，替换这个函数即可。"""
    canvas = _render_shot_base(shot, base_asset)
    width, height = canvas.size
    draw = ImageDraw.Draw(canvas, "RGBA")

    long_edge = max(width, height)
    title_font, has_cjk = _load_font(max(20, long_edge // 22))
    big_font, _ = _load_font(max(26, long_edge // 12))
    small_font, _ = _load_font(max(14, long_edge // 44))

    pad = max(16, long_edge // 34)
    label = "MOCK · 占位图" if has_cjk else "MOCK PREVIEW"
    # 标题现在会带 SKU 名 / 上下装组合名，不截断会顶出画布
    raw_headline = shot["title"] if has_cjk else f"SHOT {shot['index']}/{total}"
    headline = raw_headline[:16] + ("…" if len(raw_headline) > 16 else "")

    # 顶部标签
    draw.rectangle([0, 0, width, pad * 2.6], fill=(11, 10, 31, 190))
    draw.text((pad, pad * 0.75), label, font=small_font, fill=(255, 196, 107, 255))
    draw.text((width - pad, pad * 0.75), task.task_no, font=small_font, fill=(195, 190, 230, 230), anchor="ra")

    # 中间主题
    draw.text((pad, height * 0.40), headline, font=big_font, fill=(244, 242, 255, 255))
    draw.text(
        (pad, height * 0.40 + long_edge // 10),
        f"{shot['index']:02d} / {total:02d} · {shot['size']}",
        font=title_font,
        fill=(169, 155, 255, 255),
    )

    # 底部说明条
    bar_top = height - pad * 3.2
    draw.rectangle([0, bar_top, width, height], fill=(11, 10, 31, 200))
    composition = shot["composition"][:44]
    draw.text((pad, bar_top + pad * 0.55), composition, font=small_font, fill=(195, 190, 230, 235))
    draw.text(
        (pad, bar_top + pad * 1.55),
        "未接图像模型 · 仅验证链路" if has_cjk else "no image model attached",
        font=small_font,
        fill=(255, 107, 138, 230),
    )

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def run_generation(task_id: int) -> None:
    """
    后台执行出图。自己在内部开 session：
    BackgroundTasks 跑在线程池里，不能复用请求的 session（可能已关闭）。
    """
    db = get_session_local()()
    try:
        task = db.get(StudioTask, task_id)
        if task is None or task.status not in ("planned", "generating"):
            return

        plan = task.plan or {}
        shots = plan.get("shots") or []
        if not shots:
            task.status = "failed"
            task.error = "任务没有可执行的规划"
            db.commit()
            return

        input_payload = task.input or {}
        base_ids = input_payload.get("asset_ids") or []
        base_asset = db.get(MediaAsset, base_ids[0]) if base_ids else None

        task.status = "generating"
        task.started_at = datetime.utcnow()
        task.error = None
        task.progress = 0
        db.commit()

        from app.services import image_gateway
        from app.services.image_process import _to_png

        # 参考图从本地素材库读，最多 4 张；端点自己的 max_refs 还会再截一次
        refs = []
        for asset_id in base_ids[:4]:
            row = db.get(MediaAsset, asset_id)
            ref = image_gateway.read_asset_bytes(row) if row else None
            if ref:
                refs.append(ref)

        preferred = input_payload.get("endpoint_key")
        shared_params = dict(input_payload.get("endpoint_params") or {})
        produced: list[dict] = []
        routes: list[dict] = []
        real_count = 0

        def outputs_snapshot() -> dict:
            return {
                "engine": "gateway" if real_count else "mock",
                "assets": produced,
                "routes": routes,
                "endpoint_key": preferred or "auto",
            }

        for shot in shots:
            index = int(shot.get("index") or len(produced) + 1)
            capability = shot.get("capability") or "img2img"
            try:
                params = dict(shared_params)
                params.setdefault("size", _endpoint_size(shot.get("size", "1:1")))
                result = image_gateway.process_image(
                    service=task.kind,
                    capability=capability,
                    prompt=shot.get("prompt") or shot.get("title", ""),
                    refs=refs,
                    params=params,
                    preferred_key=preferred,
                    db=db,
                )
                if result.image:
                    png = _to_png(result.image)
                    real_count += 1
                else:
                    png = _render_shot(shot, base_asset, task, len(shots))

                # 同 sha256 只存一份：重跑任务 / 端点返回同一张图时复用已有素材，
                # 否则 UniqueViolation 会让整个 session 失效，任务永远停在 generating。
                asset, _reused = media_assets.create_generated_asset(
                    db,
                    blob=png,
                    filename=f"{task.task_no}-{index:02d}-{shot.get('title', 'shot')}.png",
                    fields={
                        # 生成结果也进二级目录，别让素材库里堆一片「未归类」。
                        "category": _result_category(shot.get("title", "")),
                        "note": f"{task.task_no} · {shot.get('title', '')} · 端点 {result.endpoint_key}"[:255],
                        "tags": [task.kind, capability, result.endpoint_key],
                        "owner_id": task.owner_id,
                        "parent_id": base_asset.id if base_asset else None,
                        "created_at": datetime.utcnow(),
                    },
                )
                produced.append(
                    {
                        "media_id": asset.id,
                        "url": f"{media_store_prefix()}/{asset.rel_path}",
                        "index": index,
                        "shot_title": shot.get("title"),
                        "capability": capability,
                        "endpoint_key": result.endpoint_key,
                        "endpoint_name": result.endpoint_name,
                        "is_mock": result.is_mock,
                    }
                )
                routes.append({"index": index, "capability": capability, **result.to_dict()})
            except Exception as exc:  # 单张失败不整单失败，记下来继续
                task.error = f"第 {index} 张失败：{exc}"

            task.done_shots = index
            task.progress = int(index / len(shots) * 100)
            task.outputs = outputs_snapshot()
            db.commit()

        task.status = "done" if len(produced) == len(shots) else "failed"
        task.progress = 100 if task.status == "done" else task.progress
        task.finished_at = datetime.utcnow()
        task.outputs = outputs_snapshot()
        db.commit()
    except Exception as exc:
        try:
            task = db.get(StudioTask, task_id)
            if task:
                task.status = "failed"
                task.error = str(exc)
                task.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def media_store_prefix() -> str:
    from app.config import get_settings

    return get_settings().media_url_prefix.rstrip("/")
