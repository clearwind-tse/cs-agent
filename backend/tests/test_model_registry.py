# -*- coding: utf-8 -*-
"""
模型注册表的单测（SQLite 内存库 + 假 settings，不连生产库、不发真实请求）

重点覆盖这轮改造最容易出错的契约：
  - 默认 provider 优先级保持改造前顺序，避免「配了 embedding 的 ARK_API_KEY，
    质检就莫名切到 qwen-plus」这类串线；
  - 设置页覆盖只对指定板块生效，空库回落代码默认；
  - 密钥绝不出现在设置页返回值里；
  - 保存 / 恢复默认 / 未知板块 / 能力不匹配的校验；
  - 缓存失效即时生效。
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.models.database import Base
from app.models.model_setting import ModelSetting
from app.routers import model_settings as router
from app.services import model_registry as mr


def fake_settings(**overrides):
    """只提供 registry 会 getattr 的字段，不碰 .env"""
    base = {
        "deepseek_api_key": "", "deepseek_base_url": "https://ds.example/v1",
        "openai_api_key": "", "openai_base_url": "https://oa.example/v1",
        "ark_api_key": "", "ark_base_url": "https://ark.example/v1",
        "ark_vision_api_key": "", "ark_vision_base_url": "https://vision.example/v1",
        "ark_embedding_model": "text-embedding-v3",
        "ark_vision_model": "ep-test-001",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class ResolveTests(unittest.TestCase):
    def test_auto_picks_first_configured_in_preference(self):
        s = fake_settings(deepseek_api_key="ds-key", openai_api_key="oa-key", ark_api_key="ark-key")
        self.assertEqual(mr.resolve("chat", override={}, settings=s).provider, "deepseek")
        # rag 改造前是 ark → deepseek → openai，保持原样
        self.assertEqual(mr.resolve("rag", override={}, settings=s).provider, "ark")

    def test_embedding_key_does_not_hijack_chat_slots(self):
        """只配了给 embedding 用的 ARK_API_KEY 时，质检仍走原来的 openai，而不是 qwen-plus"""
        s = fake_settings(ark_api_key="ark-key", openai_api_key="oa-key")
        qc = mr.resolve("qc", override={}, settings=s)
        self.assertEqual(qc.provider, "openai")
        self.assertEqual(qc.model, "gpt-4o-mini")

    def test_no_key_marks_unconfigured_but_keeps_model_name(self):
        s = fake_settings()
        qc = mr.resolve("qc", override={}, settings=s)
        self.assertFalse(qc.configured)
        self.assertEqual(qc.model, "deepseek-chat")
        self.assertEqual(qc.api_key, "")

    def test_explicit_provider_and_model_override(self):
        s = fake_settings(ark_api_key="ark-key")
        r = mr.resolve("qc", override={"provider": "ark", "model": "qwen-max"}, settings=s)
        self.assertEqual((r.provider, r.model, r.configured), ("ark", "qwen-max", True))
        self.assertEqual(r.source, "override")

    def test_empty_model_uses_provider_default(self):
        s = fake_settings(openai_api_key="oa-key")
        r = mr.resolve("qc", override={"provider": "openai", "model": ""}, settings=s)
        self.assertEqual(r.model, "gpt-4o-mini")

    def test_vision_key_falls_back_to_generic_ark_key(self):
        s = fake_settings(ark_api_key="ark-key")
        r = mr.resolve("vision", override={}, settings=s)
        self.assertEqual(r.provider, "ark_vision")
        self.assertEqual(r.model, "ep-test-001")
        self.assertTrue(r.configured)

    def test_embedding_model_comes_from_env_setting(self):
        s = fake_settings(ark_api_key="ark-key", ark_embedding_model="my-embedding-v2")
        r = mr.resolve("embedding", override={}, settings=s)
        self.assertEqual(r.model, "my-embedding-v2")
        self.assertTrue(r.is_embedding)

    def test_unknown_slot_falls_back_instead_of_crashing(self):
        s = fake_settings(deepseek_api_key="ds-key")
        r = mr.resolve("not-a-slot", override={}, settings=s)
        self.assertEqual(r.slot, "chat")

    def test_public_dict_never_carries_key(self):
        s = fake_settings(deepseek_api_key="super-secret-key")
        public = mr.resolve("chat", override={}, settings=s).public_dict()
        self.assertNotIn("api_key", public)
        self.assertNotIn("super-secret-key", str(public))


class DescribeTests(unittest.TestCase):
    def setUp(self):
        self.patcher = patch.object(mr, "get_overrides", return_value={})
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_all_slots_and_groups_are_described(self):
        d = mr.describe()
        self.assertEqual(len(d["slots"]), len(mr.SLOTS))
        self.assertTrue(d["groups"])
        self.assertTrue(d["providers"])

    def test_describe_never_exposes_any_api_key(self):
        d = mr.describe()
        settings = get_settings()
        keys = [
            settings.deepseek_api_key, settings.openai_api_key,
            settings.ark_api_key, settings.ark_vision_api_key,
        ]
        for key in keys:
            if key:
                self.assertNotIn(key, str(d))

    def test_allowed_providers_include_compatible_ones_beyond_auto_preference(self):
        """auto 只在 preference 里挑，但用户应能显式把对话切到百炼 / 自托管端点"""
        d = mr.describe()
        chat = next(s for s in d["slots"] if s["key"] == "chat")
        self.assertIn("ark", chat["allowed_providers"])
        self.assertIn("openai", chat["allowed_providers"])

    def test_override_is_reflected_in_describe(self):
        with patch.object(mr, "get_overrides", return_value={"qc": {"provider": "openai", "model": "gpt-4o"}}):
            d = mr.describe()
        qc = next(s for s in d["slots"] if s["key"] == "qc")
        self.assertTrue(qc["custom"])
        self.assertEqual(qc["effective_model"], "gpt-4o")
        self.assertEqual(qc["effective_provider"], "openai")
        rest = next(s for s in d["slots"] if s["key"] == "chat")
        self.assertFalse(rest["custom"])

    def test_invalidate_cache_clears_snapshot(self):
        mr._cache["all"] = (0.0, {"qc": {"provider": "openai", "model": "x"}})
        mr.invalidate_cache()
        self.assertEqual(mr._cache, {})


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine, tables=[ModelSetting.__table__])
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        def overrides_from_test_db():
            return {
                row.slot: {"provider": row.provider, "model": row.model}
                for row in self.db.query(ModelSetting).all()
            }

        self.patcher = patch.object(mr, "get_overrides", side_effect=overrides_from_test_db)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.db.close()
        self.engine.dispose()
        mr.invalidate_cache()

    def test_save_then_read_back(self):
        result = router.update_model_settings(
            router.UpdateRequest(slots={"qc": router.SlotChoice(provider="openai", model="gpt-4o")}),
            db=self.db, current_user=None,
        )
        qc = next(s for s in result["slots"] if s["key"] == "qc")
        self.assertEqual(qc["effective_model"], "gpt-4o")
        self.assertEqual(qc["effective_provider"], "openai")
        self.assertTrue(qc["custom"])
        self.assertEqual(self.db.query(ModelSetting).count(), 1)

    def test_partial_update_keeps_other_slots(self):
        router.update_model_settings(
            router.UpdateRequest(slots={"qc": router.SlotChoice(provider="deepseek")}),
            db=self.db, current_user=None,
        )
        router.update_model_settings(
            router.UpdateRequest(slots={"chat": router.SlotChoice(provider="openai")}),
            db=self.db, current_user=None,
        )
        self.assertEqual(
            {row.slot for row in self.db.query(ModelSetting).all()}, {"qc", "chat"}
        )

    def test_reset_falls_back_to_code_default(self):
        router.update_model_settings(
            router.UpdateRequest(slots={"qc": router.SlotChoice(provider="openai", model="gpt-4o")}),
            db=self.db, current_user=None,
        )
        result = router.reset_model_setting("qc", db=self.db, current_user=None)
        qc = next(s for s in result["slots"] if s["key"] == "qc")
        self.assertFalse(qc["custom"])
        self.assertEqual(self.db.query(ModelSetting).count(), 0)

    def test_unknown_slot_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            router.update_model_settings(
                router.UpdateRequest(slots={"nope": router.SlotChoice()}),
                db=self.db, current_user=None,
            )
        self.assertEqual(ctx.exception.detail["code"], 40010)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            router.update_model_settings(
                router.UpdateRequest(slots={"qc": router.SlotChoice(provider="some-llm")}),
                db=self.db, current_user=None,
            )
        self.assertEqual(ctx.exception.detail["code"], 40011)

    def test_embedding_slot_rejects_chat_provider(self):
        with self.assertRaises(HTTPException) as ctx:
            router.update_model_settings(
                router.UpdateRequest(slots={"embedding": router.SlotChoice(provider="deepseek")}),
                db=self.db, current_user=None,
            )
        self.assertEqual(ctx.exception.detail["code"], 40012)

    def test_chat_slot_rejects_embedding_provider(self):
        with self.assertRaises(HTTPException) as ctx:
            router.update_model_settings(
                router.UpdateRequest(slots={"chat": router.SlotChoice(provider="ark_embedding")}),
                db=self.db, current_user=None,
            )
        self.assertEqual(ctx.exception.detail["code"], 40012)

    def test_planned_slot_skips_connectivity_test(self):
        result = router.test_model_setting(
            router.TestRequest(slot="studio_image"), current_user=None,
        )
        self.assertTrue(result["skipped"])
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
