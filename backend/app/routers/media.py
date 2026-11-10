# -*- coding: utf-8 -*-
"""
媒体素材路由（AI 创作 · 素材库）

当前落本地磁盘：backend/data/media/{年}/{月}/{uuid}.{ext}
静态直出：GET /api/media/files/{rel_path}（由 main.py 挂 StaticFiles）

为什么静态路径也放在 /api 下：
生产是 nginx 把 /api 整体反代到后端，这样本地与线上只有一份 URL 规则，
不用在 nginx 里再开一条 /media 的 location。
代价是这类直链不带鉴权 —— 内部部署可接受；换 OSS 时改成带签名与过期的 URL 即可。
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session as DBSession

from app.config import get_settings
from app.deps import get_current_user
from app.models.database import get_db
from app.models.media import MEDIA_KIND_LABELS, MEDIA_KINDS, UNCATEGORIZED, MediaAsset
from app.models.media_category import MediaCategory
from app.models.user import User
from app.services import media_categories, media_store

router = APIRouter(prefix="/api/media", tags=["media"])


def _url_prefix() -> str:
    return get_settings().media_url_prefix.rstrip("/")


def _payload(asset: MediaAsset) -> dict:
    return asset.to_dict(_url_prefix())


class MediaUpdateRequest(BaseModel):
    kind: Optional[str] = Field(None, description="一级目录 product/style/result/reference/other")
    category: Optional[str] = Field(None, description="二级目录 key；_uncategorized 表示移出目录")
    note: Optional[str] = None
    tags: Optional[List[str]] = None


class CategoryCreateRequest(BaseModel):
    kind: str = Field(..., description="一级目录 product/style/result/reference/other")
    label: str = Field(..., description="二级目录显示名，1-20 字")


class KindLabelRequest(BaseModel):
    label: str = Field(..., description="一级目录的新显示名，1-20 字；key 本身不可改")


# ==================== 上传 ====================

@router.post("/upload")
def upload_media(
    file: UploadFile = File(..., description="图片文件"),
    kind: str = Form("other", description="一级目录 product/style/result/reference/other"),
    category: Optional[str] = Form(None, description="二级目录 key，必须属于该一级目录"),
    note: Optional[str] = Form(None),
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    上传一张图进素材库。

    先落盘再查重：sha256 已存在时把刚写的文件删掉、复用已有记录（幂等），
    避免同一张图反复上传把磁盘撑爆。
    """
    if kind not in MEDIA_KINDS:
        kind = "other"
    normalized_category = media_categories.normalize_category(db, kind, category)

    saved = media_store.save_stream(file.file, file.content_type, file.filename)

    existing = db.query(MediaAsset).filter(MediaAsset.sha256 == saved["sha256"]).first()
    if existing:
        media_store.delete_file(saved["rel_path"])
        # 重复上传时允许顺手改目录，但不覆盖已有备注
        changed = False
        if kind != "other" and existing.kind != kind:
            existing.kind = kind
            changed = True
        if normalized_category and existing.category != normalized_category:
            existing.category = normalized_category
            changed = True
        if changed:
            db.commit()
            db.refresh(existing)
        return {"item": _payload(existing), "reused": True}

    asset = MediaAsset(
        sha256=saved["sha256"],
        original_name=(file.filename or saved["stored_name"])[:255],
        stored_name=saved["stored_name"],
        rel_path=saved["rel_path"],
        mime=saved["mime"],
        size=saved["size"],
        width=saved["width"],
        height=saved["height"],
        kind=kind,
        category=normalized_category,
        source="upload",
        note=note,
        tags=[],
        owner_id=getattr(current_user, "id", None),
        created_at=datetime.utcnow(),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {"item": _payload(asset), "reused": False}


# ==================== 查询 ====================

@router.get("/list")
def list_media(
    kind: Optional[str] = Query(None, description="一级目录；all/空 表示全部"),
    category: Optional[str] = Query(None, description="二级目录 key；_uncategorized 表示未归类"),
    q: Optional[str] = Query(None, description="按文件名或备注搜索"),
    ids: Optional[List[int]] = Query(None, description="按 id 精确取，用于任务回显已选素材"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 二级目录 key 只在一级内唯一（product.detail 与 result.detail 是两个目录），
    # 不带 kind 直接按 category 查会把两个一级的素材混在一起。弹窗选图器必须同传。
    if category and category not in ("all", UNCATEGORIZED) and (not kind or kind == "all"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 40007, "message": "按二级目录查询时必须同时指定一级目录"},
        )

    query = db.query(MediaAsset)
    # 直接调用路由函数时 Query(None) 的默认值是 Query 对象而非 None，显式判类型更稳
    if isinstance(ids, (list, tuple)) and len(ids) > 0:
        # 回显路径：任务里存的是素材 id，可能不在「最近 100 张」里，按 id 精确取更可靠
        query = query.filter(MediaAsset.id.in_(ids[:100]))
    else:
        if kind and kind != "all":
            query = query.filter(MediaAsset.kind == kind)
        if category and category != "all":
            if category == UNCATEGORIZED:
                query = query.filter(or_(MediaAsset.category.is_(None), MediaAsset.category == ""))
            else:
                query = query.filter(MediaAsset.category == category)
        if q:
            like = f"%{q.strip()}%"
            query = query.filter(or_(MediaAsset.original_name.ilike(like), MediaAsset.note.ilike(like)))

    total = query.count()
    rows = (
        query.order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [_payload(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/stats")
def media_stats(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """素材库页头用的汇总：条数、占用空间、按分类分布"""
    rows = db.query(MediaAsset.kind, func.count(MediaAsset.id), func.coalesce(func.sum(MediaAsset.size), 0)).group_by(MediaAsset.kind).all()
    by_kind = [{"kind": kind or "other", "count": count, "size": int(size or 0)} for kind, count, size in rows]
    cat_rows = db.query(MediaAsset.kind, MediaAsset.category, func.count(MediaAsset.id)).group_by(MediaAsset.kind, MediaAsset.category).all()
    by_category = [
        {"kind": kind or "other", "category": category or UNCATEGORIZED, "count": count}
        for kind, category, count in cat_rows
    ]
    disk_count, disk_size = media_store.disk_usage()
    return {
        "total": sum(item["count"] for item in by_kind),
        "total_size": sum(item["size"] for item in by_kind),
        "by_kind": by_kind,
        "by_category": by_category,
        # 磁盘实际占用：文件数比表里多，说明有孤儿文件，可据此清理
        "disk_count": disk_count,
        "disk_size": disk_size,
        "max_mb": get_settings().media_max_mb,
    }


def _scan_disk(db: DBSession) -> tuple[list[str], list[str]]:
    """核对表与磁盘：返回 (表里有但文件没了, 磁盘上有但表里没记录)。
    本地磁盘存储特有的运维需求：进程在「文件已落盘、DB 还没 commit」之间被打断，
    就会留下无主文件；反之删库不删文件则留下断链。
    .part 是上传临时文件，不计入一致性。
    """
    rows = db.query(MediaAsset.id, MediaAsset.rel_path).all()
    known = {rel for _id, rel in rows}
    missing = [rel for _id, rel in rows if not media_store.safe_join(rel).exists()]

    root = media_store.get_media_root()
    on_disk = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and not path.name.endswith(".part")
    }
    return missing, sorted(on_disk - known)


@router.get("/files-check")
def media_files_check(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """只读一致性检查，运维排障用"""
    missing, orphan = _scan_disk(db)
    return {"missing": missing, "orphan": orphan, "ok": not missing and not orphan}


@router.post("/files-cleanup")
def media_files_cleanup(
    apply: bool = Query(False, description="默认只预览；显式传 true 才真正删除孤儿文件"),
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    清理无主文件。只删 media_root 内、表里查不到 rel_path 的文件，
    不碰任何已登记素材；删除走 delete_file（自带路径越界校验 + 幂等）。
    默认 dry_run，避免误操作。
    """
    _missing, orphan = _scan_disk(db)
    removed: list[str] = []
    if apply:
        for rel in orphan:
            media_store.delete_file(rel)
            if not media_store.safe_join(rel).exists():
                removed.append(rel)
    return {
        "orphan": orphan,
        "removed": removed,
        "failed": [rel for rel in orphan if rel not in removed] if apply else [],
        "dry_run": not apply,
    }


# ==================== 二级目录 ====================
# 这几个路由必须注册在 /{asset_id} 之前，否则 "categories" 会被当成 asset_id 解析成 422。

@router.get("/categories")
def list_categories(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """两级目录树，每个节点带素材计数；未归类素材单独给出"""
    return media_categories.category_tree(db)


@router.post("/categories")
def add_category(
    payload: CategoryCreateRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """在某个一级下新建自定义二级目录；同名幂等"""
    category = media_categories.create_category(db, payload.kind, payload.label)
    return {"item": category.to_dict(), "tree": media_categories.category_tree(db)}


# ==================== 一级目录显示名 ====================
# 只改显示名，不动 key：五个 key 是 studioKinds 默认目录、后端白名单、生成结果归类的契约。

@router.patch("/kind-labels/{key}")
def rename_kind(
    key: str,
    payload: KindLabelRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """改一级目录的显示名；写入 media_kind_labels，重启后仍然生效"""
    if key not in MEDIA_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 40008, "message": "未知一级目录"},
        )
    label, custom = media_categories.resolve_kind_label(db, key)
    row = media_categories.set_kind_label(db, key, payload.label)
    return {
        "item": {**row.to_dict(), "default_label": MEDIA_KIND_LABELS[key], "custom": True},
        "previous": {"label": label, "custom": custom},
        "tree": media_categories.category_tree(db),
    }


@router.delete("/kind-labels/{key}")
def reset_kind(
    key: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """恢复代码默认显示名；删的只是自定义名记录，不碰任何素材与二级目录"""
    if key not in MEDIA_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 40008, "message": "未知一级目录"},
        )
    label = media_categories.reset_kind_label(db, key)
    return {"item": {"key": key, "label": label, "custom": False}, "tree": media_categories.category_tree(db)}


@router.delete("/categories/{category_id}")
def remove_category(
    category_id: int,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    删除自定义二级目录。预置目录不可删；目录下的素材只清 category 落到「未归类」，
    绝不删文件——删目录不该有删图这种破坏性副作用。
    """
    category = db.get(MediaCategory, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": 40402, "message": "目录不存在"})
    if category.builtin:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": 40901, "message": "预置目录不能删除"},
        )
    moved = (
        db.query(MediaAsset)
        .filter(MediaAsset.kind == category.kind, MediaAsset.category == category.key)
        .update({MediaAsset.category: None}, synchronize_session=False)
    )
    db.delete(category)
    db.commit()
    return {"ok": True, "id": category_id, "moved": moved, "tree": media_categories.category_tree(db)}


# ==================== 修改 / 删除 ====================

@router.patch("/{asset_id}")
def update_media(
    asset_id: int,
    payload: MediaUpdateRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": 40401, "message": "素材不存在"})

    kind_changed = payload.kind is not None and payload.kind != asset.kind
    if payload.kind is not None:
        if payload.kind not in MEDIA_KINDS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": 40003, "message": "未知一级分类"})
        asset.kind = payload.kind
    if payload.category is not None:
        # 校验用「改完之后」的一级目录，避免跨一级塞进看不见的二级目录
        asset.category = media_categories.normalize_category(db, asset.kind, payload.category)
    elif kind_changed:
        asset.category = None
    if payload.note is not None:
        asset.note = payload.note
    if payload.tags is not None:
        asset.tags = payload.tags

    db.commit()
    db.refresh(asset)
    return {"item": _payload(asset)}


@router.delete("/{asset_id}")
def delete_media(
    asset_id: int,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """先删记录再删文件：记录没了但文件还在，最多算孤儿，不会出现死链"""
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": 40401, "message": "素材不存在"})

    rel_path = asset.rel_path
    db.delete(asset)
    db.commit()
    media_store.delete_file(rel_path)
    return {"ok": True, "id": asset_id}
