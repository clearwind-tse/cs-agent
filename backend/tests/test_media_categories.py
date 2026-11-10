# -*- coding: utf-8 -*-
"""
素材库二级目录的单测（纯 SQLite 内存库，不启服务、不连生产 PG）

覆盖的是这轮改动最容易出错的几处契约：
  - seed 幂等，重复启动不会把预置目录插两遍
  - 目录树计数 / 未归类计数
  - 二级目录必须属于当前一级，跨一级的 key 要拒绝
  - 删目录只把素材移到未归类，绝不删素材行（更不该删文件）
  - 改一级时自动清掉二级，避免留下「商品图 / 主图」这种看不见的组合
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base
from app.models.media import BUILTIN_CATEGORIES, MEDIA_KIND_LABELS, UNCATEGORIZED, MediaAsset
from app.models.media_category import MediaCategory
from app.models.media_kind_label import MediaKindLabel
from app.routers import media as media_router
from app.services import media_categories


class MediaCategoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            bind=self.engine,
            tables=[MediaAsset.__table__, MediaCategory.__table__, MediaKindLabel.__table__],
        )
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        media_categories.seed_builtin_categories(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _asset(self, name: str, kind: str = "product", category: str | None = None) -> MediaAsset:
        asset = MediaAsset(
            sha256=f"hash-{name}",
            original_name=f"{name}.png",
            stored_name=f"{name}.png",
            rel_path=f"2026/11/{name}.png",
            mime="image/png",
            size=100,
            kind=kind,
            category=category,
            source="upload",
        )
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def test_seed_is_idempotent(self):
        expected = sum(len(entries) for entries in BUILTIN_CATEGORIES.values())
        self.assertEqual(self.db.query(MediaCategory).count(), expected)
        self.assertEqual(media_categories.seed_builtin_categories(self.db), 0)
        self.assertEqual(self.db.query(MediaCategory).count(), expected)
        self.assertTrue(
            self.db.query(MediaCategory).filter_by(key="white_bg", builtin=True).first()
        )

    def test_tree_counts_children_and_uncategorized(self):
        self._asset("a", category="white_bg")
        self._asset("b", category="white_bg")
        self._asset("c")
        self._asset("d", kind="result", category="main")

        tree = media_categories.category_tree(self.db)
        product = next(group for group in tree["groups"] if group["kind"] == "product")
        white_bg = next(child for child in product["children"] if child["key"] == "white_bg")
        result = next(group for group in tree["groups"] if group["kind"] == "result")
        main = next(child for child in result["children"] if child["key"] == "main")

        self.assertEqual(product["count"], 3)
        self.assertEqual(white_bg["count"], 2)
        self.assertEqual(main["count"], 1)
        self.assertEqual(tree["uncategorized"], 1)
        self.assertEqual(tree["total"], 4)

    def test_normalize_category_validates_ownership(self):
        self.assertEqual(media_categories.normalize_category(self.db, "product", "white_bg"), "white_bg")
        self.assertIsNone(media_categories.normalize_category(self.db, "product", None))
        self.assertIsNone(media_categories.normalize_category(self.db, "product", UNCATEGORIZED))
        # main 是 result 下的目录，不能塞进 product
        for bad in ("main", "not-exist"):
            with self.assertRaises(HTTPException) as ctx:
                media_categories.normalize_category(self.db, "product", bad)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_create_category_is_idempotent_by_label_and_rejects_bad_input(self):
        created = media_categories.create_category(self.db, "product", "  秋季新款  ")
        self.assertEqual(created.label, "秋季新款")
        self.assertFalse(created.builtin)
        self.assertTrue(created.key.startswith("c"))
        self.assertEqual(media_categories.create_category(self.db, "product", "秋季新款").id, created.id)
        with self.assertRaises(HTTPException):
            media_categories.create_category(self.db, "product", "   ")
        with self.assertRaises(HTTPException):
            media_categories.create_category(self.db, "nope", "x")

    def test_delete_category_moves_assets_to_uncategorized_without_deleting_them(self):
        custom = media_categories.create_category(self.db, "product", "待整理")
        self._asset("x", category=custom.key)
        self._asset("y", category="white_bg")

        result = media_router.remove_category(custom.id, db=self.db, current_user=None)
        self.assertEqual(result["moved"], 1)
        self.assertEqual(self.db.query(MediaAsset).count(), 2)  # 素材行必须还在
        self.assertIsNone(self.db.get(MediaAsset, 1).category)
        self.assertIsNone(self.db.query(MediaCategory).filter_by(key=custom.key).first())

        with self.assertRaises(HTTPException) as ctx:
            media_router.remove_category(1, db=self.db, current_user=None)
        self.assertEqual(ctx.exception.status_code, 409)  # 预置目录不可删

    def test_list_filter_and_move_between_directories(self):
        inside = self._asset("in", category="white_bg")
        self._asset("out")

        listed = media_router.list_media(
            kind="product", category="white_bg", q=None, page=1, page_size=24,
            db=self.db, current_user=None,
        )
        self.assertEqual([row["original_name"] for row in listed["items"]], ["in.png"])

        uncategorized = media_router.list_media(
            kind="product", category=UNCATEGORIZED, q=None, page=1, page_size=24,
            db=self.db, current_user=None,
        )
        self.assertEqual([row["original_name"] for row in uncategorized["items"]], ["out.png"])

        moved = media_router.update_media(
            inside.id,
            media_router.MediaUpdateRequest(kind="result", category="main"),
            db=self.db, current_user=None,
        )
        self.assertEqual(moved["item"]["kind"], "result")
        self.assertEqual(moved["item"]["category"], "main")

        # 只改一级、不传二级：旧的二级目录必须被清掉，否则素材会藏进看不见的目录
        moved_again = media_router.update_media(
            inside.id,
            media_router.MediaUpdateRequest(kind="product"),
            db=self.db, current_user=None,
        )
        self.assertEqual(moved_again["item"]["category"], "")

    def test_list_by_ids_ignores_other_filters_for_task_replay(self):
        first = self._asset("first", category="white_bg")
        self._asset("second", kind="style", category="color")
        third = self._asset("third")

        listed = media_router.list_media(
            kind=None, category=None, q=None, ids=[third.id, first.id], page=1, page_size=24,
            db=self.db, current_user=None,
        )
        # 旧任务回显不受「最近 N 张」和当前目录筛选影响，只按 id 精确取
        self.assertEqual({row["id"] for row in listed["items"]}, {first.id, third.id})
        self.assertEqual(listed["total"], 2)

    def test_list_rejects_second_level_category_without_kind(self):
        self._asset("loose")  # 未归类素材，用于验证虚拟目录可以跨一级查
        # detail 同时属于 product 和 result，不带 kind 会把两个一级的素材混在一起
        with self.assertRaises(HTTPException) as ctx:
            media_router.list_media(
                kind=None, category="detail", q=None, ids=None, page=1, page_size=24,
                db=self.db, current_user=None,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        # 虚拟目录「未归类」可以跨一级查，不受这个约束
        ok = media_router.list_media(
            kind=None, category=UNCATEGORIZED, q=None, ids=None, page=1, page_size=24,
            db=self.db, current_user=None,
        )
        self.assertEqual(ok["total"], 1)

    def test_kind_labels_default_to_code_values(self):
        tree = media_categories.category_tree(self.db)
        for group in tree["groups"]:
            self.assertEqual(group["label"], MEDIA_KIND_LABELS[group["kind"]])
            self.assertEqual(group["default_label"], MEDIA_KIND_LABELS[group["kind"]])
            self.assertFalse(group["custom"])

    def test_rename_kind_only_changes_label_not_keys_or_data(self):
        asset = self._asset("kept", category="white_bg")

        response = media_router.rename_kind(
            "product", media_router.KindLabelRequest(label="  货品图片  "),
            db=self.db, current_user=None,
        )
        self.assertEqual(response["item"]["label"], "货品图片")
        self.assertEqual(response["item"]["custom"], True)
        product = next(g for g in response["tree"]["groups"] if g["kind"] == "product")
        self.assertEqual(product["label"], "货品图片")
        self.assertEqual(product["default_label"], "商品图")
        self.assertTrue(product["custom"])
        # 其它一级不受影响，素材的 kind / category 和二级目录也没被动过
        self.assertEqual(next(g for g in response["tree"]["groups"] if g["kind"] == "style")["label"], "风格参考")
        self.assertEqual(self.db.get(MediaAsset, asset.id).kind, "product")
        self.assertEqual(self.db.get(MediaAsset, asset.id).category, "white_bg")
        self.assertEqual(self.db.query(MediaCategory).filter_by(kind="product").count(), 3)

    def test_rename_kind_is_idempotent_and_validated(self):
        media_categories.set_kind_label(self.db, "product", "货品")
        media_categories.set_kind_label(self.db, "product", "货品")
        self.assertEqual(self.db.query(MediaKindLabel).count(), 1)
        for bad_key, bad_label in (("nope", "x"), ("product", "   ")):
            with self.assertRaises(HTTPException) as ctx:
                media_categories.set_kind_label(self.db, bad_key, bad_label)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_reset_kind_restores_default(self):
        media_categories.set_kind_label(self.db, "result", "成品")
        self.assertTrue(media_categories.resolve_kind_label(self.db, "result")[1])
        response = media_router.reset_kind("result", db=self.db, current_user=None)
        self.assertEqual(response["item"]["label"], MEDIA_KIND_LABELS["result"])
        self.assertFalse(response["item"]["custom"])
        result = next(g for g in response["tree"]["groups"] if g["kind"] == "result")
        self.assertFalse(result["custom"])
        self.assertEqual(self.db.query(MediaKindLabel).count(), 0)
        with self.assertRaises(HTTPException):
            media_router.reset_kind("nope", db=self.db, current_user=None)

    def test_add_category_route_returns_fresh_tree(self):
        response = media_router.add_category(
            media_router.CategoryCreateRequest(kind="style", label="国风"),
            db=self.db, current_user=None,
        )
        self.assertEqual(response["item"]["kind"], "style")
        style = next(group for group in response["tree"]["groups"] if group["kind"] == "style")
        self.assertIn("国风", [child["label"] for child in style["children"]])


if __name__ == "__main__":
    unittest.main()
