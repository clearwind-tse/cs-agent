# -*- coding: utf-8 -*-
"""
本地媒体存储

定位：AI 创作素材库的「文件落地层」，当前落本地磁盘。
换 OSS / TOS 时只改这个文件（save_stream 与 build_url 两处），
上层路由、表结构、前端契约都不动 —— 这也是先不上 OSS 的前提。

安全约束（都是踩过的坑，别省）：
1. 文件名完全由服务端生成（uuid + 由 mime 推出的后缀），不采信客户端的 filename，
   否则 `../../app/main.py` 这类名字能直接覆盖代码；
2. **拒绝 SVG**：SVG 里可嵌 <script>，一旦通过同源静态路径直出，就是存储型 XSS；
3. 只收白名单 mime，且后缀由 mime 决定 —— 不按客户端给的 .png 决定类型；
4. 落盘前先写 .part 临时文件，校验通过再原子 rename，避免半截文件被读到；
5. 读取时 resolve 后必须仍在 media_root 下，防止 rel_path 被构造成穿越路径。
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Optional, Tuple

from fastapi import HTTPException, status

from app.config import get_settings

# mime → 后缀（白名单，不在表里的直接拒绝）
ALLOWED_IMAGE_MIME: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}
# 明确拉黑：可执行脚本 / 可嵌脚本的矢量图 / 网页
BLOCKED_MIME = {
    "image/svg+xml",
    "text/html",
    "application/xhtml+xml",
    "application/javascript",
    "text/javascript",
}

CHUNK_SIZE = 1024 * 1024  # 1MB


def get_media_root() -> Path:
    """媒体根目录：config.media_root 优先，否则 backend/data/media"""
    settings = get_settings()
    if settings.media_root:
        root = Path(settings.media_root).expanduser()
        if not root.is_absolute():
            root = (Path(__file__).resolve().parents[2] / root).resolve()
    else:
        root = Path(__file__).resolve().parents[2] / "data" / "media"
    root.mkdir(parents=True, exist_ok=True)
    return root


def max_bytes() -> int:
    return max(1, get_settings().media_max_mb) * 1024 * 1024


def normalize_mime(content_type: Optional[str], filename: Optional[str]) -> Tuple[str, str]:
    """返回 (mime, 后缀)。不合规直接 415。"""
    mime = (content_type or "").split(";")[0].strip().lower()
    if not mime or mime == "application/octet-stream":
        # 有些客户端不带类型，用后缀兜底推断
        guessed, _ = mimetypes.guess_type(filename or "")
        mime = (guessed or "").lower()

    if mime in BLOCKED_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": 41501, "message": "不支持该文件类型（出于安全考虑拒绝 SVG / 网页）"},
        )
    suffix = ALLOWED_IMAGE_MIME.get(mime)
    if not suffix:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": 41502,
                "message": f"仅支持图片：{'、'.join(sorted(ALLOWED_IMAGE_MIME))}",
            },
        )
    return mime, suffix


def safe_join(rel_path: str) -> Path:
    """把 rel_path 拼到 root 下，并确保没跑出去"""
    root = get_media_root().resolve()
    target = (root / rel_path).resolve()
    if root != target and root not in target.parents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 40001, "message": "非法路径"},
        )
    return target


def read_image_size(path: Path) -> Tuple[Optional[int], Optional[int]]:
    """只读文件头拿宽高，失败返回 (None, None) —— 尺寸不该阻塞上传"""
    try:
        from PIL import Image  # 本地依赖，缺失时降级

        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def save_stream(
    stream: BinaryIO,
    content_type: Optional[str],
    filename: Optional[str],
) -> dict:
    """
    把上传流写到本地，返回落盘结果：
      {sha256, stored_name, rel_path, size, mime, width, height}
    超限 / 类型不符抛 HTTPException，且不留残留文件。
    """
    mime, suffix = normalize_mime(content_type, filename)
    root = get_media_root()
    limit = max_bytes()

    now = datetime.utcnow()
    rel_dir = f"{now.year:04d}/{now.month:02d}"
    abs_dir = root / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex}{suffix}"
    final_path = abs_dir / stored_name
    part_path = final_path.with_suffix(final_path.suffix + ".part")

    digest = hashlib.sha256()
    size = 0
    try:
        with open(part_path, "wb") as out:
            while True:
                chunk = stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        # 用字面量而非 status.HTTP_413_*：Starlette 在较新版本把该常量改名，
                        # 项目要同时兼容 uv 锁的旧版本
                        status_code=413,
                        detail={
                            "code": 41301,
                            "message": f"文件超过 {get_settings().media_max_mb}MB 上限",
                        },
                    )
                digest.update(chunk)
                out.write(chunk)

        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": 40002, "message": "空文件"},
            )

        os.replace(part_path, final_path)
    except HTTPException:
        part_path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # 磁盘满 / 权限
        part_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": 50001, "message": f"写入失败：{exc}"},
        ) from exc

    width, height = read_image_size(final_path)
    return {
        "sha256": digest.hexdigest(),
        "stored_name": stored_name,
        "rel_path": f"{rel_dir}/{stored_name}",
        "size": size,
        "mime": mime,
        "width": width,
        "height": height,
    }


def delete_file(rel_path: str) -> None:
    """删除落盘文件；文件已不在不算错（先删文件再删记录，失败可从表重建）"""
    try:
        safe_join(rel_path).unlink(missing_ok=True)
    except HTTPException:
        return


def disk_usage() -> Tuple[int, int]:
    """(文件数, 总字节)。只统计 media_root 下的常规文件，用于素材库页头。"""
    root = get_media_root()
    count = 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.endswith(".part"):
                continue
            count += 1
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return count, total


def clear_root_for_tests() -> None:  # pragma: no cover - 仅测试用
    root = get_media_root()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
