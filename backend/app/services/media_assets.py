# -*- coding: utf-8 -*-
"""
生成图入库的统一入口。

media_assets.sha256 上有唯一索引：同一个端点反复返回同一张图、或用户重跑一次任务时，
直接 INSERT 会触发 UniqueViolation。而生成链路跑在 BackgroundTasks 里，异常一旦让
SQLAlchemy session 进入 failed 状态，后续 commit 全部失败，任务就永远卡在 generating/running。

所以这里复用上传链路的同一套语义：**同内容只存一份**。命中已有记录时删掉刚落盘的副本，
直接返回旧素材，不让异常有机会污染 session。
"""
from __future__ import annotations

import io
from typing import Optional, Tuple

from sqlalchemy.orm import Session as DBSession

from app.models.media import MediaAsset
from app.services import media_store


def create_generated_asset(
    db: DBSession,
    *,
    blob: bytes,
    filename: str,
    fields: dict,
    mime: str = "image/png",
) -> Tuple[MediaAsset, bool]:
    """返回 (素材记录, 是否复用了已有记录)。fields 里的键会覆盖默认值。"""
    saved = media_store.save_stream(io.BytesIO(blob), mime, filename)
    existing: Optional[MediaAsset] = (
        db.query(MediaAsset).filter(MediaAsset.sha256 == saved["sha256"]).first()
    )
    if existing is not None:
        media_store.delete_file(saved["rel_path"])
        return existing, True

    payload = {
        "sha256": saved["sha256"],
        "original_name": filename[:255],
        "stored_name": saved["stored_name"],
        "rel_path": saved["rel_path"],
        "mime": mime,
        "size": saved["size"],
        "width": saved["width"],
        "height": saved["height"],
        "kind": "result",
        "source": "generated",
    }
    payload.update(fields)
    asset = MediaAsset(**payload)
    db.add(asset)
    db.flush()
    return asset, False
