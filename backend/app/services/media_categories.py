# -*- coding: utf-8 -*-
"""素材库目录的读写逻辑：种子、一级显示名、目录树、校验、新建"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.models.media import (
    BUILTIN_CATEGORIES,
    MEDIA_KIND_LABELS,
    MEDIA_KINDS,
    UNCATEGORIZED,
    MediaAsset,
)
from app.models.media_category import MediaCategory
from app.models.media_kind_label import MediaKindLabel


def seed_builtin_categories(db: DBSession) -> int:
    """把预置二级目录补进表里；只在缺失时插入，重复启动不会新增"""
    existing = {(row.kind, row.key) for row in db.query(MediaCategory).all()}
    added = 0
    for kind, entries in BUILTIN_CATEGORIES.items():
        for key, label in entries:
            if (kind, key) in existing:
                continue
            db.add(MediaCategory(kind=kind, key=key, label=label, builtin=True))
            added += 1
    if added:
        db.commit()
    return added


def kind_label_overrides(db: DBSession) -> dict[str, str]:
    """用户改过的一级显示名；没改过的项不落表，继续用代码默认值"""
    return {row.key: row.label for row in db.query(MediaKindLabel).all()}


def resolve_kind_label(db: DBSession, key: str) -> tuple[str, bool]:
    """返回 (显示名, 是否为用户自定义)，供接口回包与目录树复用"""
    custom = kind_label_overrides(db).get(key)
    return (custom or MEDIA_KIND_LABELS.get(key, key), bool(custom))


def set_kind_label(db: DBSession, key: str, label: str) -> MediaKindLabel:
    """改一个一级目录的显示名；key 必须属于固定的五类，不能靠这个接口新增一级"""
    if key not in MEDIA_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 40008, "message": "未知一级目录"},
        )
    clean = (label or "").strip()[:20]
    if not clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 40009, "message": "目录名不能为空"},
        )
    row = db.get(MediaKindLabel, key)
    if row:
        row.label = clean
        row.updated_at = datetime.utcnow()
    else:
        row = MediaKindLabel(key=key, label=clean)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def reset_kind_label(db: DBSession, key: str) -> str:
    """删掉自定义名，恢复代码默认值；返回恢复后的显示名"""
    if key not in MEDIA_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 40008, "message": "未知一级目录"},
        )
    row = db.get(MediaKindLabel, key)
    if row:
        db.delete(row)
        db.commit()
    return MEDIA_KIND_LABELS.get(key, key)


def category_tree(db: DBSession) -> dict:
    """两级目录树 + 每个节点的素材数；未归类素材单独统计"""
    rows = (
        db.query(MediaAsset.kind, MediaAsset.category, func.count(MediaAsset.id))
        .group_by(MediaAsset.kind, MediaAsset.category)
        .all()
    )
    counts: dict[tuple[str, str], int] = {}
    for kind, category, count in rows:
        counts[(kind or "other", category or "")] = int(count)

    overrides = kind_label_overrides(db)
    groups = []
    for kind in MEDIA_KINDS:
        categories = (
            db.query(MediaCategory)
            .filter(MediaCategory.kind == kind)
            .order_by(MediaCategory.builtin.desc(), MediaCategory.id.asc())
            .all()
        )
        children = [
            {
                "id": cat.id,
                "key": cat.key,
                "label": cat.label,
                "builtin": bool(cat.builtin),
                "count": counts.get((kind, cat.key), 0),
            }
            for cat in categories
        ]
        groups.append(
            {
                "kind": kind,
                "label": overrides.get(kind) or MEDIA_KIND_LABELS[kind],
                "default_label": MEDIA_KIND_LABELS[kind],
                "custom": kind in overrides,
                "count": sum(value for (k, _c), value in counts.items() if k == kind),
                "children": children,
            }
        )

    return {
        "groups": groups,
        "uncategorized": sum(value for (_k, category), value in counts.items() if not category),
        "total": sum(counts.values()),
    }


def normalize_category(db: DBSession, kind: str, category: Optional[str]) -> Optional[str]:
    """
    校验二级目录是否属于这个一级，返回落库值（NULL 用 None 表示）。
    上传 / 编辑时严格校验，避免前端传个不存在的 key 把素材塞进看不见的目录。
    """
    if not category or category == UNCATEGORIZED:
        return None
    exists = (
        db.query(MediaCategory.id)
        .filter(MediaCategory.kind == kind, MediaCategory.key == category)
        .first()
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 40004, "message": "二级目录不存在或不属于该一级分类"},
        )
    return category


def create_category(db: DBSession, kind: str, label: str) -> MediaCategory:
    """在某个一级下新建自定义二级目录；同名视为幂等，直接返回已有目录"""
    if kind not in MEDIA_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 40005, "message": "未知一级分类"},
        )
    clean = (label or "").strip()[:20]
    if not clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 40006, "message": "目录名不能为空"},
        )
    existing = (
        db.query(MediaCategory)
        .filter(MediaCategory.kind == kind, MediaCategory.label == clean)
        .first()
    )
    if existing:
        return existing

    # key 用短随机串：中文目录名不做 slug，避免转写规则引入歧义；显示名单独存 label
    category = MediaCategory(kind=kind, key=f"c{uuid.uuid4().hex[:8]}", label=clean, builtin=False)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category
