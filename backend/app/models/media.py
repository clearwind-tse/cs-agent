# -*- coding: utf-8 -*-
"""
媒体素材模型

AI 创作工作区的共享底座：商品图、风格参考、成图、精修结果都落在这一张表里，
文件本体放本地磁盘（见 app/services/media_store.py），这里只存元数据。

为什么不直接扫目录：
- 需要 kind / note / tags / 来源血缘，目录名装不下这些；
- 去重要靠 sha256 查得到（同图重复上传不该产生第二份文件）；
- 后面换 OSS 时，表结构不用动，只换 rel_path 的解析方式。
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, BigInteger
from datetime import datetime

from .database import Base


# 一级目录：与前端「素材库」的分组一致
MEDIA_KINDS = ("product", "style", "result", "reference", "other")
MEDIA_KIND_LABELS = {
    "product": "商品图",
    "style": "风格参考",
    "result": "成图",
    "reference": "参考图",
    "other": "其他",
}
MEDIA_SOURCES = ("upload", "generated")

# 二级目录：预置项启动时 seed 进 media_categories，用户可在其下继续新建自定义目录。
# key 在所属一级内唯一；(kind, key) 才确定一个目录，所以不同一级下可以有同名 key。
BUILTIN_CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "product": [("white_bg", "白底图"), ("live", "实拍图"), ("detail", "细节图")],
    "style": [("color", "配色参考"), ("lighting", "光线参考"), ("layout", "版式参考")],
    "result": [("main", "主图"), ("detail", "详情图"), ("variant", "变体图")],
    "reference": [("competitor", "竞品参考"), ("mood", "氛围参考"), ("typography", "排版参考")],
    "other": [("misc", "杂项")],
}

# 没有二级目录的素材统一归到这里，列表筛选时它是一个虚拟目录（不是表里的真实记录）
UNCATEGORIZED = "_uncategorized"


class MediaAsset(Base):
    """素材表 — 文件落本地磁盘，元数据在这里"""
    __tablename__ = "media_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 内容指纹：同一文件重复上传时直接复用，不再占磁盘
    sha256 = Column(String(64), unique=True, nullable=False, index=True)
    original_name = Column(String(255), nullable=False)
    # 落盘名（uuid.ext），与原始文件名解耦，避免中文/特殊字符与前缀穿越
    stored_name = Column(String(120), nullable=False)
    # 相对 media_root 的路径：2026/11/uuid.png
    rel_path = Column(String(255), nullable=False, index=True)
    mime = Column(String(100), nullable=False)
    size = Column(BigInteger, default=0)          # 字节
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    kind = Column(String(20), default="other", index=True)      # 一级：product/style/result/reference/other
    # 二级目录 key，属于上面的 kind；NULL / 空串 = 未归类。
    # 不存目录 id 是为了让目录删除后素材自动落到「未归类」，不产生外键级联删图。
    category = Column(String(40), nullable=True, index=True)
    source = Column(String(20), default="upload", index=True)   # upload/generated
    note = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)            # ["白底", "鞋"]
    owner_id = Column(Integer, nullable=True, index=True)       # users.id，可为空（系统生成）
    # 生成类素材可回溯到产出它的任务 / 底图，先留字段，出图链路接上后写入
    parent_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self, url_prefix: str = "/api/media/files"):
        return {
            "id": self.id,
            "original_name": self.original_name,
            "url": f"{url_prefix}/{self.rel_path}",
            "mime": self.mime,
            "size": self.size or 0,
            "width": self.width,
            "height": self.height,
            "kind": self.kind or "other",
            "category": self.category or "",
            "source": self.source or "upload",
            "note": self.note,
            "tags": self.tags or [],
            "parent_id": self.parent_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
