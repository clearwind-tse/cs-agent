# -*- coding: utf-8 -*-
"""
素材库单图「即席处理」：选中一张图 → 选动作（抠图 / 换背景 / 超分…）→ 选端点 → 出图回库。

和 studio_tasks 的区别：那边是一次出一套图、带逐镜头规划与人工确认闸门；
这里是对一张已有图做一次即时处理，没有规划阶段，但走的是**同一个图像网关**，
端点池、服务绑定、fallback、结果标注来源全部复用。
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_session_local
from app.models.image_endpoint import IMAGE_CAPABILITIES, ImageProcessJob
from app.models.media import MediaAsset
from app.services import image_gateway, media_assets, media_store

JOB_STATUSES = ("queued", "running", "done", "failed")


def _next_job_no(db: DBSession) -> str:
    day = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"IP{day}-"
    last = (
        db.query(ImageProcessJob)
        .filter(ImageProcessJob.job_no.like(f"{prefix}%"))
        .order_by(ImageProcessJob.job_no.desc())
        .first()
    )
    seq = int(last.job_no.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:03d}"


def create_job(
    db: DBSession,
    *,
    asset_id: int,
    operation: str,
    endpoint_key: Optional[str],
    params: Optional[dict],
    owner_id: Optional[int],
) -> ImageProcessJob:
    if operation not in IMAGE_CAPABILITIES:
        raise HTTPException(status_code=400, detail={"code": 42001, "message": f"未知处理动作：{operation}"})
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail={"code": 42002, "message": f"素材 {asset_id} 不存在"})
    job = ImageProcessJob(
        job_no=_next_job_no(db),
        asset_id=asset_id,
        operation=operation,
        endpoint_key=(endpoint_key or "").strip()[:40] or None,
        params=params if isinstance(params, dict) else {},
        status="queued",
        owner_id=owner_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _fallback_png(asset: Optional[MediaAsset], title: str, reason: str) -> bytes:
    """没有可用端点时也要产出可预览的图，并且明确写清这是占位图"""
    from app.services.studio_task_service import _load_font, _render_shot_base

    shot = {
        "title": title,
        "composition": reason[:80],
        "size": "1024x1024",
        "index": 1,
    }
    canvas = _render_shot_base(shot, asset)
    draw = ImageDraw.Draw(canvas, "RGBA")
    font, has_cjk = _load_font(max(18, canvas.width // 32))
    draw.rectangle([0, 0, canvas.width, max(52, canvas.width // 16)], fill=(11, 10, 31, 200))
    draw.text(
        (canvas.width // 32, canvas.width // 40),
        "MOCK · 未命中真实端点" if has_cjk else "MOCK · no endpoint",
        font=font,
        fill=(255, 196, 107, 255),
    )
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _to_png(blob: bytes) -> bytes:
    """统一转 PNG 落盘，避免各家返回 jpeg/webp 时后缀与内容对不上"""
    image = Image.open(io.BytesIO(blob)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def run_job(job_id: int) -> None:
    db = get_session_local()()
    try:
        job = db.get(ImageProcessJob, job_id)
        if job is None or job.status in ("done", "failed"):
            return
        job.status = "running"
        db.commit()

        asset = db.get(MediaAsset, job.asset_id)
        if asset is None:
            raise RuntimeError("源素材已不存在")

        ref = image_gateway.read_asset_bytes(asset)
        label = IMAGE_CAPABILITIES.get(job.operation, job.operation)
        params = dict(job.params or {})
        prompt = f"{label}。{str(params.pop('prompt', '') or '').strip()}"[:1000]

        result = image_gateway.process_image(
            service="adhoc",
            capability=job.operation,
            prompt=prompt,
            refs=[ref] if ref else [],
            params=params,
            preferred_key=job.endpoint_key,
            db=db,
        )
        blob = _to_png(result.image) if result.image else _fallback_png(asset, label, result.reason)
        # 同 sha256 只存一份：端点反复返回同一张图时复用已有素材，避免唯一索引冲突污染事务
        produced, _reused = media_assets.create_generated_asset(
            db,
            blob=blob,
            filename=f"{job.job_no}-{label}.png",
            fields={
                "category": "variant",
                "note": f"{job.job_no} · {label} · 端点 {result.endpoint_key}"[:255],
                "tags": ["adhoc", job.operation, result.endpoint_key],
                "owner_id": job.owner_id,
                "parent_id": asset.id,
                "created_at": datetime.utcnow(),
            },
        )

        job.status = "done"
        job.result_asset_id = produced.id
        job.engine = result.protocol
        job.used_endpoint = result.endpoint_key
        job.latency_ms = result.latency_ms
        job.error = result.reason if result.is_mock else None
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        # 后台任务没有 HTTP 响应能把错误带给用户，静默吞异常只会让任务永远卡在 running。
        # 所以这里必须留痕，并把状态落回 failed（用新 session，避免被污染的事务连回滚都做不了）。
        import traceback
        print(f"[ERROR] image process job {job_id} failed: {exc}", flush=True)
        traceback.print_exc()
        try:
            db.rollback()
            job = db.get(ImageProcessJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(exc)[:500]
                job.finished_at = datetime.utcnow()
                db.commit()
        except Exception as write_err:
            print(f"[ERROR] failed to persist job {job_id} status: {write_err}", flush=True)
    finally:
        db.close()
