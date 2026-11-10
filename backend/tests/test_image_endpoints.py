# -*- coding: utf-8 -*-
"""
图像端点体系的单测（SQLite 内存库，不连生产 PG、不发真实请求）

覆盖这轮最容易出错的契约：
  - 端点是一等数据：可任意多个，密钥不回显明文；
  - 服务绑定是「有序候选链」而不是「单选一个模型」；
  - 按镜头能力分派，本次指定端点只提前、不砍掉 fallback；
  - 任何环节缺配置都回落 mock，链路跑得完；
  - 任务规划会预先把「每张用哪个端点」摊开。
"""
import base64
import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base
from app.models.image_endpoint import (
    MOCK_ENDPOINT_KEY,
    ImageEndpoint,
    ImageEndpointBinding,
    ImageProcessJob,
)
from app.models.media import MediaAsset
from app.services import image_endpoints as ie
from app.services import image_gateway as gw
from app.services import image_process
from app.services import studio_task_service as tasks


def sample_png(color=(80, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class ImageEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(
            bind=self.engine,
            tables=[
                ImageEndpoint.__table__, ImageEndpointBinding.__table__,
                ImageProcessJob.__table__, MediaAsset.__table__,
            ],
        )
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        ie.seed_mock_endpoint(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _endpoint(self, key="ep-a", **overrides):
        payload = {
            "key": key,
            "name": f"端点 {key}",
            "protocol": "webhook",
            "base_url": "https://example.com/generate",
            "model": "test-model",
            "auth_mode": "none",
            "capabilities": ["img2img", "remove_bg"],
            "params": {},
            "max_refs": 2,
            "timeout_s": 20,
            "enabled": True,
            "priority": 50,
        }
        payload.update(overrides)
        ie.save_endpoint(self.db, payload, creating=True)
        return self.db.get(ImageEndpoint, key)

    def test_seed_is_idempotent(self):
        count_before = self.db.query(ImageEndpoint).count()
        bindings_before = self.db.query(ImageEndpointBinding).count()
        ie.seed_mock_endpoint(self.db)
        self.assertEqual(self.db.query(ImageEndpoint).count(), count_before)
        self.assertEqual(self.db.query(ImageEndpointBinding).count(), bindings_before)

    def test_seed_creates_default_chain_for_every_service(self):
        services = {row.service for row in self.db.query(ImageEndpointBinding).all()}
        self.assertEqual(len(services), 6)
        self.assertIn("adhoc", services)

    def test_can_add_many_endpoints(self):
        for index in range(12):
            self._endpoint(f"ep-{index:02d}")
        self.assertEqual(self.db.query(ImageEndpoint).count(), 13)  # 12 + mock
        self.assertEqual(len(ie.list_endpoints(self.db)), 13)

    def test_inline_secret_never_returned_in_cleartext(self):
        self._endpoint("ep-secret", auth_mode="inline", api_key_inline="sk-super-secret-1234")
        item = ie.describe(self.db)["endpoints"]
        row = next(e for e in item if e["key"] == "ep-secret")
        self.assertNotIn("sk-super-secret-1234", str(row))
        self.assertEqual(row["secret_source"], "inline")
        self.assertTrue(row["secret_masked"].startswith("••••"))
        self.assertEqual(ie.resolve_secret(self.db.get(ImageEndpoint, "ep-secret")), "sk-super-secret-1234")

    def test_env_secret_resolves_from_environment(self):
        self._endpoint("ep-env", auth_mode="env", api_key_env="UNIT_TEST_IMAGE_KEY")
        with patch.dict(os.environ, {"UNIT_TEST_IMAGE_KEY": "env-key-value"}):
            row = self.db.get(ImageEndpoint, "ep-env")
            self.assertEqual(ie.resolve_secret(row), "env-key-value")
            self.assertTrue(row.to_dict()["secret_ready"])

    def test_env_endpoint_without_key_is_skipped_in_chain(self):
        self._endpoint("ep-env", auth_mode="env", api_key_env="UNIT_TEST_MISSING_KEY")
        ie.set_bindings(self.db, "retouch", ["ep-env"])
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UNIT_TEST_MISSING_KEY", None)
            chain = ie.resolve_chain(self.db, "retouch", "remove_bg")
        self.assertEqual([ep["key"] for ep in chain], [MOCK_ENDPOINT_KEY])

    def test_invalid_key_and_protocol_are_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            ie.save_endpoint(self.db, {"key": "BAD KEY", "name": "x", "protocol": "webhook",
                                       "base_url": "https://a.b", "capabilities": ["img2img"]}, creating=True)
        self.assertEqual(ctx.exception.detail["code"], 41001)
        with self.assertRaises(HTTPException):
            ie.save_endpoint(self.db, {"key": "ep-x", "name": "x", "protocol": "unknown",
                                       "base_url": "https://a.b", "capabilities": ["img2img"]}, creating=True)

    def test_env_mode_requires_variable_name(self):
        with self.assertRaises(HTTPException) as ctx:
            ie.save_endpoint(self.db, {"key": "ep-x", "name": "x", "protocol": "webhook",
                                       "base_url": "https://a.b", "auth_mode": "env",
                                       "capabilities": ["img2img"]}, creating=True)
        self.assertEqual(ctx.exception.detail["code"], 41007)

    def test_mock_endpoint_cannot_be_deleted(self):
        with self.assertRaises(HTTPException) as ctx:
            ie.delete_endpoint(self.db, MOCK_ENDPOINT_KEY)
        self.assertEqual(ctx.exception.detail["code"], 41012)

    def test_deleting_endpoint_also_removes_its_bindings(self):
        self._endpoint("ep-a")
        ie.set_bindings(self.db, "retouch", ["ep-a"])
        self.assertTrue(self.db.query(ImageEndpointBinding).filter_by(endpoint_key="ep-a").count())
        ie.delete_endpoint(self.db, "ep-a")
        self.assertEqual(self.db.query(ImageEndpointBinding).filter_by(endpoint_key="ep-a").count(), 0)


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine, tables=[ImageEndpoint.__table__, ImageEndpointBinding.__table__])
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        ie.seed_mock_endpoint(self.db)
        for key, caps in (("ep-a", ["img2img", "remove_bg"]), ("ep-b", ["upscale", "img2img"]), ("ep-c", ["img2img"])):
            ie.save_endpoint(self.db, {
                "key": key, "name": key, "protocol": "webhook", "base_url": "https://a.b",
                "auth_mode": "none", "capabilities": caps,
            }, creating=True)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_binding_order_becomes_fallback_order(self):
        rows = ie.set_bindings(self.db, "retouch", ["ep-c", "ep-a", "ep-b"])
        self.assertEqual([row["endpoint_key"] for row in rows], ["ep-c", "ep-a", "ep-b"])
        self.assertLess(rows[0]["priority"], rows[1]["priority"])

    def test_chain_filters_by_capability(self):
        ie.set_bindings(self.db, "retouch", ["ep-a", "ep-b", "ep-c"])
        keys = [ep["key"] for ep in ie.resolve_chain(self.db, "retouch", "upscale")]
        self.assertEqual(keys, ["ep-b", MOCK_ENDPOINT_KEY])

    def test_capability_specific_chain_takes_priority(self):
        ie.set_bindings(self.db, "retouch", ["ep-a"])
        ie.set_bindings(self.db, "retouch", ["ep-b"], capability="img2img")
        keys = [ep["key"] for ep in ie.resolve_chain(self.db, "retouch", "img2img")]
        self.assertEqual(keys[0], "ep-b")
        self.assertIn("ep-a", keys)  # 默认链仍作 fallback

    def test_preferred_endpoint_moves_first_but_keeps_fallback(self):
        ie.set_bindings(self.db, "set", ["ep-a", "ep-c"])
        keys = [ep["key"] for ep in ie.resolve_chain(self.db, "set", "img2img", preferred_key="ep-c")]
        self.assertEqual(keys[0], "ep-c")
        self.assertIn("ep-a", keys)

    def test_preferred_endpoint_not_bound_is_still_tried(self):
        ie.set_bindings(self.db, "set", ["ep-a"])
        keys = [ep["key"] for ep in ie.resolve_chain(self.db, "set", "img2img", preferred_key="ep-c")]
        self.assertEqual(keys[0], "ep-c")
        self.assertIn("ep-a", keys)

    def test_mock_is_always_last_resort(self):
        ie.set_bindings(self.db, "sku", ["ep-a"])
        keys = [ep["key"] for ep in ie.resolve_chain(self.db, "sku", "img2img")]
        self.assertEqual(keys[-1], MOCK_ENDPOINT_KEY)

    def test_unknown_service_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            ie.set_bindings(self.db, "not-a-service", ["ep-a"])
        self.assertEqual(ctx.exception.detail["code"], 41013)

    def test_describe_never_leaks_secrets(self):
        ie.save_endpoint(self.db, {
            "key": "ep-secret", "name": "secret", "protocol": "webhook", "base_url": "https://a.b",
            "auth_mode": "inline", "api_key_inline": "plaintext-dont-leak", "capabilities": ["img2img"],
        }, creating=True)
        self.assertNotIn("plaintext-dont-leak", str(ie.describe(self.db)))


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine, tables=[ImageEndpoint.__table__, ImageEndpointBinding.__table__])
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        ie.seed_mock_endpoint(self.db)
        for key in ("ep-a", "ep-b"):
            ie.save_endpoint(self.db, {
                "key": key, "name": key, "protocol": "webhook", "base_url": f"https://{key}.example/generate",
                "auth_mode": "none", "capabilities": ["img2img", "remove_bg"],
            }, creating=True)
        ie.set_bindings(self.db, "retouch", ["ep-a", "ep-b"])

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_first_successful_endpoint_wins(self):
        png = sample_png()
        with patch.object(gw.requests, "post", return_value=_FakeResponse({"b64_json": base64.b64encode(png).decode()})):
            result = gw.process_image(service="retouch", capability="remove_bg", prompt="x", refs=[], db=self.db)
        self.assertFalse(result.is_mock)
        self.assertEqual(result.endpoint_key, "ep-a")
        self.assertEqual(result.image, png)

    def test_failure_falls_back_to_next_endpoint(self):
        png = sample_png((200, 80, 80))
        calls = []

        def fake_post(url, **kwargs):
            calls.append(url)
            if "ep-a" in url:
                raise RuntimeError("endpoint down")
            return _FakeResponse({"image_base64": base64.b64encode(png).decode()})

        with patch.object(gw.requests, "post", side_effect=fake_post):
            result = gw.process_image(service="retouch", capability="remove_bg", prompt="x", refs=[], db=self.db)
        self.assertFalse(result.is_mock)
        self.assertEqual(result.endpoint_key, "ep-b")
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.attempts[0]["ok"], False)

    def test_all_fail_falls_back_to_mock(self):
        with patch.object(gw.requests, "post", side_effect=RuntimeError("all down")):
            result = gw.process_image(service="retouch", capability="remove_bg", prompt="x", refs=[], db=self.db)
        self.assertTrue(result.is_mock)
        self.assertEqual(result.endpoint_key, MOCK_ENDPOINT_KEY)
        self.assertIn("all down", result.reason)

    def test_single_mode_does_not_fallback(self):
        with patch.object(gw.requests, "post", side_effect=RuntimeError("down")) as post:
            result = gw.process_image(service="retouch", capability="remove_bg", prompt="x",
                                      refs=[], preferred_key="ep-a", single=True, db=self.db)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(result.is_mock)

    def test_decode_handles_nested_data_url_response(self):
        png = sample_png()
        blob, mime = gw._decode_payload({"data": [{"b64_json": base64.b64encode(png).decode()}]})
        self.assertEqual(blob, png)
        self.assertEqual(mime, "image/png")

    def test_reference_limit_is_applied(self):
        seen = {}

        def fake_post(url, **kwargs):
            seen["images"] = kwargs["json"]["images"]
            return _FakeResponse({"b64_json": base64.b64encode(sample_png()).decode()})

        refs = [("image/png", sample_png()) for _ in range(6)]
        self.db.get(ImageEndpoint, "ep-a").max_refs = 2
        self.db.commit()
        with patch.object(gw.requests, "post", side_effect=fake_post):
            gw.process_image(service="retouch", capability="remove_bg", prompt="x", refs=refs,
                             preferred_key="ep-a", db=self.db)
        self.assertEqual(len(seen["images"]), 2)

    def test_localhost_endpoint_bypasses_http_proxy(self):
        """自托管端点跑在 127.0.0.1 时必须绕过 HTTP_PROXY，外部端点仍走系统代理"""
        png = sample_png()
        row = self.db.get(ImageEndpoint, "ep-a")
        row.base_url = "http://127.0.0.1:8199/generate"
        self.db.commit()
        local = MagicMock()
        local.__enter__.return_value = local
        local.post.return_value = _FakeResponse({"b64_json": base64.b64encode(png).decode()})
        with patch.object(gw.requests, "Session", return_value=local), \
                patch.object(gw.requests, "post") as external:
            result = gw.process_image(service="retouch", capability="remove_bg", prompt="x", db=self.db)
        self.assertFalse(result.is_mock)
        self.assertTrue(local.post.called)
        self.assertEqual(local.trust_env, False)
        self.assertFalse(external.called)


class StudioIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine, tables=[ImageEndpoint.__table__, ImageEndpointBinding.__table__])
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        ie.seed_mock_endpoint(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_infer_capability_varies_by_shot(self):
        self.assertEqual(tasks.infer_capability("retouch", "精修 · 换背景", True), "remove_bg")
        self.assertEqual(tasks.infer_capability("retouch", "精修 · 提清晰度", True), "upscale")
        self.assertEqual(tasks.infer_capability("sku", "替换图 · 原版式", True), "inpaint")
        self.assertEqual(tasks.infer_capability("style", "风格套用 · 正面", True), "style_transfer")
        self.assertEqual(tasks.infer_capability("outfit", "成套 · 正面", True), "tryon")
        self.assertEqual(tasks.infer_capability("set", "主图 · 正面", False), "txt2img")

    def test_plan_shots_carry_capability(self):
        payload = tasks.normalize_payload("retouch", {"count": 3, "config": {"fields": {"fixes": ["换背景", "提清晰度"]}}})
        plan = tasks.build_plan("retouch", payload, [])
        caps = {shot["capability"] for shot in plan["shots"]}
        self.assertIn("remove_bg", caps)
        self.assertIn("upscale", caps)
        self.assertTrue(all("capability" in shot for shot in plan["shots"]))

    def test_normalize_payload_keeps_endpoint_choice(self):
        payload = tasks.normalize_payload("sku", {
            "endpoint_key": "ep-a",
            "endpoint_params": {"strength": 0.7, "size": "1024x1024"},
        })
        self.assertEqual(payload["endpoint_key"], "ep-a")
        self.assertEqual(payload["endpoint_params"]["strength"], 0.7)
        self.assertIsNone(tasks.normalize_payload("sku", {})["endpoint_key"])

    def test_annotate_plan_marks_endpoints(self):
        ie.save_endpoint(self.db, {
            "key": "ep-a", "name": "主端点", "protocol": "webhook", "base_url": "https://a.b",
            "auth_mode": "none", "capabilities": ["img2img", "inpaint", "remove_bg", "upscale"],
        }, creating=True)
        ie.set_bindings(self.db, "sku", ["ep-a"])
        payload = tasks.normalize_payload("sku", {"count": 2, "endpoint_key": "ep-a"})
        plan = tasks.annotate_plan_endpoints(
            self.db, "sku", tasks.build_plan("sku", payload, []), "ep-a",
        )
        self.assertEqual(plan["shots"][0]["endpoint_key"], "ep-a")
        self.assertTrue(plan["shots"][0]["endpoint_ready"])
        self.assertEqual(plan["endpoint_key"], "ep-a")

    def test_endpoint_size_is_normalized(self):
        self.assertEqual(tasks._endpoint_size("1200x1200"), "1024x1024")
        self.assertEqual(tasks._endpoint_size("1080x1440"), "1024x1536")
        self.assertEqual(tasks._endpoint_size("1600x900"), "1536x1024")

    def test_engine_info_reflects_endpoints(self):
        self.assertTrue(tasks.engine_info(self.db)["is_mock"])
        ie.save_endpoint(self.db, {
            "key": "ep-a", "name": "x", "protocol": "webhook", "base_url": "https://a.b",
            "auth_mode": "none", "capabilities": ["img2img"],
        }, creating=True)
        info = tasks.engine_info(self.db)
        self.assertFalse(info["is_mock"])
        self.assertEqual(info["endpoint_count"], 1)


class AdhocProcessTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(
            bind=self.engine,
            tables=[ImageEndpoint.__table__, ImageEndpointBinding.__table__,
                    ImageProcessJob.__table__, MediaAsset.__table__],
        )
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        ie.seed_mock_endpoint(self.db)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patchers = [
            patch.object(image_process.media_store, "get_media_root", return_value=self.root),
            patch.object(gw.media_store, "get_media_root", return_value=self.root),
            patch.object(image_process, "get_session_local", return_value=self.Session),
            patch.object(gw, "get_session_local", return_value=self.Session),
        ]
        for p in self.patchers:
            p.start()
        (self.root / "2026" / "11").mkdir(parents=True, exist_ok=True)
        (self.root / "2026" / "11" / "source.png").write_bytes(sample_png())
        self.asset = MediaAsset(
            sha256="src-hash", original_name="source.png", stored_name="source.png",
            rel_path="2026/11/source.png", mime="image/png", size=100, kind="product",
            source="upload",
        )
        self.db.add(self.asset)
        self.db.commit()

    def tearDown(self):
        # image_process.media_store 与 gw.media_store 是同一个模块对象，
        # 两个 patch 叠在同一属性上：必须后进先出，否则会残留一个 MagicMock 污染别的测试模块
        for p in reversed(self.patchers):
            p.stop()
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def test_create_job_validates_operation_and_asset(self):
        with self.assertRaises(HTTPException) as ctx:
            image_process.create_job(self.db, asset_id=self.asset.id, operation="not-real",
                                     endpoint_key=None, params={}, owner_id=None)
        self.assertEqual(ctx.exception.detail["code"], 42001)
        with self.assertRaises(HTTPException):
            image_process.create_job(self.db, asset_id=99999, operation="remove_bg",
                                     endpoint_key=None, params={}, owner_id=None)

    def test_run_job_writes_result_back_to_media_library(self):
        job = image_process.create_job(self.db, asset_id=self.asset.id, operation="remove_bg",
                                       endpoint_key=None, params={"prompt": "白底"}, owner_id=None)
        with patch.object(gw.requests, "post", return_value=_FakeResponse(
            {"b64_json": base64.b64encode(sample_png((10, 200, 10))).decode()}
        )):
            ie.save_endpoint(self.db, {
                "key": "ep-live", "name": "live", "protocol": "webhook",
                "base_url": "https://live.example/generate", "auth_mode": "none",
                "capabilities": ["remove_bg", "img2img"],
            }, creating=True)
            ie.set_bindings(self.db, "adhoc", ["ep-live"])
            image_process.run_job(job.id)

        self.db.expire_all()
        done = self.db.get(ImageProcessJob, job.id)
        self.assertEqual(done.status, "done")
        self.assertEqual(done.used_endpoint, "ep-live")
        result = self.db.get(MediaAsset, done.result_asset_id)
        self.assertIsNotNone(result)
        self.assertEqual(result.parent_id, self.asset.id)
        self.assertEqual(result.category, "variant")
        self.assertIn("ep-live", result.note)

    def test_repeated_identical_result_reuses_existing_asset(self):
        """端点反复返回同一张图时不能撞 sha256 唯一索引，更不能把任务卡在 running"""
        ie.save_endpoint(self.db, {
            "key": "ep-live", "name": "live", "protocol": "webhook",
            "base_url": "https://live.example/generate", "auth_mode": "none",
            "capabilities": ["remove_bg"],
        }, creating=True)
        ie.set_bindings(self.db, "adhoc", ["ep-live"])
        payload = _FakeResponse({"b64_json": base64.b64encode(sample_png((10, 200, 10))).decode()})
        with patch.object(gw.requests, "post", return_value=payload):
            first = image_process.create_job(self.db, asset_id=self.asset.id, operation="remove_bg",
                                             endpoint_key=None, params={}, owner_id=None)
            image_process.run_job(first.id)
            second = image_process.create_job(self.db, asset_id=self.asset.id, operation="remove_bg",
                                              endpoint_key=None, params={}, owner_id=None)
            image_process.run_job(second.id)

        self.db.expire_all()
        a = self.db.get(ImageProcessJob, first.id)
        b = self.db.get(ImageProcessJob, second.id)
        self.assertEqual(a.status, "done")
        self.assertEqual(b.status, "done", b.error)
        self.assertIsNotNone(a.result_asset_id)
        self.assertEqual(a.result_asset_id, b.result_asset_id)
        self.assertEqual(
            self.db.query(MediaAsset).filter(MediaAsset.source == "generated").count(), 1,
        )

    def test_run_job_falls_back_to_mock_image_when_no_endpoint(self):
        job = image_process.create_job(self.db, asset_id=self.asset.id, operation="upscale",
                                       endpoint_key=None, params={}, owner_id=None)
        image_process.run_job(job.id)
        self.db.expire_all()
        done = self.db.get(ImageProcessJob, job.id)
        self.assertEqual(done.status, "done")
        self.assertEqual(done.used_endpoint, MOCK_ENDPOINT_KEY)
        result = self.db.get(MediaAsset, done.result_asset_id)
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
