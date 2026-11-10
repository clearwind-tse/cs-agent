# -*- coding: utf-8 -*-
"""两阶段任务服务的纯函数单测（不连库、不启服务）"""
import io
import os
import sys
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import HTTPException
from PIL import Image

from app.services import studio_task_service as svc


class TaskServiceTests(unittest.TestCase):
    def test_engine_is_explicitly_mock(self):
        info = svc.engine_info()
        self.assertTrue(info["is_mock"])
        self.assertEqual(info["planner"], "rule")
        self.assertEqual(info["image_engine"], "mock")
        self.assertIn("1:1", info["ratios"])

    def test_normalize_payload_clamps_and_filters(self):
        out = svc.normalize_payload(
            "set",
            {"asset_ids": ["9", 10, "bad", None], "count": 99, "ratio": "999:1", "note": "  hi  "},
        )
        self.assertEqual(out["asset_ids"], [9, 10])
        self.assertEqual(out["count"], 8)          # 上限 8
        self.assertEqual(out["ratio"], "1:1")      # 非法比例回落
        self.assertEqual(out["note"], "hi")

    def test_normalize_payload_rejects_unknown_kind(self):
        with self.assertRaises(HTTPException) as ctx:
            svc.normalize_payload("canvas", {})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_plan_has_one_shot_per_count_with_prompt(self):
        payload = svc.normalize_payload("set", {"asset_ids": [9], "count": 3, "ratio": "3:4", "note": "突出质感"})
        plan = svc.build_plan("set", payload, [])

        self.assertEqual(len(plan["shots"]), 3)
        self.assertEqual(plan["shots"][0]["size"], "1080x1440")
        self.assertEqual([s["index"] for s in plan["shots"]], [1, 2, 3])
        for shot in plan["shots"]:
            self.assertIn("突出质感", shot["prompt"])
            self.assertIn("1080x1440", shot["prompt"])
            self.assertTrue(shot["title"])
        # 没选素材必须给出警告，不能静默出图
        self.assertTrue(any("商品图" in w or "素材" in w for w in plan["warnings"]))

    def test_plan_cycles_templates_when_count_exceeds(self):
        payload = svc.normalize_payload("sku", {"asset_ids": [], "count": 5, "ratio": "1:1"})
        plan = svc.build_plan("sku", payload, [])
        self.assertEqual(len(plan["shots"]), 5)
        self.assertTrue(any("循环复用" in w for w in plan["warnings"]))
        # 第 3 张应回到第 1 个模板
        self.assertEqual(plan["shots"][2]["title"], plan["shots"][0]["title"])

    def test_plan_inputs_carry_static_url(self):
        asset = SimpleNamespace(id=9, original_name="a.png", rel_path="2026/11/x.png")
        payload = svc.normalize_payload("set", {"asset_ids": [9], "count": 1})
        plan = svc.build_plan("set", payload, [asset])
        self.assertEqual(plan["inputs"][0]["url"].endswith("/2026/11/x.png"), True)

    def test_mock_render_produces_png_of_requested_size(self):
        shot = {
            "index": 1,
            "title": "主图 · 正面",
            "size": "600x400",
            "composition": "主体居中",
            "copy": "",
            "prompt": "",
        }
        task = SimpleNamespace(task_no="ST20261108-999")
        png = svc._render_shot(shot, None, task, 4)
        with Image.open(io.BytesIO(png)) as img:
            self.assertEqual(img.size, (600, 400))
            self.assertEqual(img.format, "PNG")


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return [row for row in self.rows if row.status == "generating"]


class FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.commits = 0

    def query(self, model):
        return FakeQuery(self.rows)

    def commit(self):
        self.commits += 1


def make_task(status="generating", age_seconds=0, **extra):
    data = {
        "status": status,
        "updated_at": datetime.utcnow() - timedelta(seconds=age_seconds),
        "started_at": None,
        "created_at": datetime.utcnow() - timedelta(seconds=age_seconds),
        "finished_at": None,
        "error": None,
    }
    data.update(extra)
    return SimpleNamespace(**data)


def fake_asset(asset_id: int, name: str):
    return SimpleNamespace(id=asset_id, original_name=name, rel_path=f"2026/11/{asset_id}.png")


class KindDifferentiationTests(unittest.TestCase):
    """五个出图功能的输入契约与规划内容必须真的不同，不能只换个标题"""

    def test_config_is_whitelisted_and_asset_ids_come_from_slots(self):
        payload = svc.normalize_payload(
            "sku",
            {
                "asset_ids": [999],  # 前端乱传，服务端应以 slots 为准
                "count": 1,
                "config": {
                    "slots": {"base": [1], "new_sku": [2, 3], "bogus": [4]},
                    "fields": {"shadow": "非法值", "region": "画面中央", "bogus": "x"},
                },
            },
        )
        self.assertEqual(payload["asset_ids"], [1, 2, 3])
        self.assertEqual(payload["config"]["slots"], {"base": [1], "new_sku": [2, 3]})
        self.assertEqual(payload["config"]["fields"]["shadow"], "沿用底图投影")
        self.assertNotIn("bogus", payload["config"]["fields"])

    def test_fallback_to_asset_ids_when_no_config(self):
        # 旧调用方（脚本 / 外部集成）不带 config 时仍要能用
        payload = svc.normalize_payload("set", {"asset_ids": ["9", 10], "count": 2})
        self.assertEqual(payload["asset_ids"], [9, 10])
        self.assertEqual(payload["config"]["slots"], {"product": [], "reference": []})

    def test_sku_emits_one_shot_per_new_product(self):
        assets = [fake_asset(1, "base.png"), fake_asset(2, "sku-a.png"), fake_asset(3, "sku-b.png")]
        payload = svc.normalize_payload(
            "sku", {"count": 1, "config": {"slots": {"base": [1], "new_sku": [2, 3]}}}
        )
        plan = svc.build_plan("sku", payload, assets)
        self.assertEqual(len(plan["shots"]), 2)
        self.assertIn("sku-a.png", plan["shots"][0]["title"])
        self.assertIn("sku-b.png", plan["shots"][1]["title"])
        self.assertTrue(all(any(m["label"] == "底图" for m in s["meta"]) for s in plan["shots"]))

    def test_retouch_uses_checked_fixes_not_lens_templates(self):
        payload = svc.normalize_payload(
            "retouch",
            {
                "count": 1,
                "config": {
                    "slots": {"source": [1]},
                    "fields": {"fixes": ["去瑕疵", "换背景"], "background": "纯暖白"},
                },
            },
        )
        plan = svc.build_plan("retouch", payload, [fake_asset(1, "raw.png")])
        self.assertEqual([shot["title"] for shot in plan["shots"]], ["去瑕疵", "换背景"])
        self.assertTrue(any(m["value"] == "纯暖白" for shot in plan["shots"] for m in shot["meta"]))

    def test_outfit_combines_tops_and_bottoms(self):
        assets = [fake_asset(1, "tee.png"), fake_asset(2, "jeans.png")]
        payload = svc.normalize_payload(
            "outfit",
            {
                "count": 1,
                "config": {
                    "slots": {"top": [1], "bottom": [2]},
                    "fields": {"pose": "坐姿", "scene": "街拍", "scope": "成套 + 单品"},
                },
            },
        )
        plan = svc.build_plan("outfit", payload, assets)
        self.assertEqual(len(plan["shots"]), 1)
        self.assertIn("tee.png", plan["shots"][0]["title"])
        self.assertIn("街拍", plan["shots"][0]["composition"])

    def test_five_kinds_produce_distinct_summaries_and_meta_labels(self):
        assets = [fake_asset(1, "a.png"), fake_asset(2, "b.png"), fake_asset(3, "c.png")]
        configs = {
            "set": {"slots": {"product": [1]}, "fields": {"platform": "淘宝主图", "modules": ["尺寸标注"]}},
            "style": {"slots": {"reference": [1], "product": [2]}, "fields": {"lock": ["色板", "光线"]}},
            "sku": {"slots": {"base": [1], "new_sku": [2]}},
            "outfit": {"slots": {"top": [1], "bottom": [2]}},
            "retouch": {"slots": {"source": [1]}, "fields": {"fixes": ["去水印"]}},
        }
        plans = {
            kind: svc.build_plan(kind, svc.normalize_payload(kind, {"count": 2, "config": cfg}), assets)
            for kind, cfg in configs.items()
        }
        self.assertEqual(len({p["summary"] for p in plans.values()}), 5)
        label_sets = {
            frozenset(meta["label"] for shot in p["shots"] for meta in shot["meta"])
            for p in plans.values()
        }
        self.assertEqual(len(label_sets), 5)
        for plan in plans.values():
            self.assertTrue(plan["shots"])
            self.assertTrue(all("meta" in shot and "prompt" in shot for shot in plan["shots"]))

    def test_plan_is_capped_and_warns(self):
        assets = [fake_asset(i, f"{i}.png") for i in range(1, 8)]
        payload = svc.normalize_payload(
            "sku",
            {"count": 8, "config": {"slots": {"base": [1], "new_sku": [2, 3, 4, 5, 6, 7]}}},
        )
        plan = svc.build_plan("sku", payload, assets)
        self.assertEqual(len(plan["shots"]), svc.MAX_PLAN_SHOTS)
        self.assertTrue(any("截断" in warning for warning in plan["warnings"]))


class StaleTaskRecoveryTests(unittest.TestCase):
    """--reload / 进程被杀会留下永远 generating 的孤儿任务，必须能自愈"""

    def test_is_stale_only_for_old_generating_tasks(self):
        self.assertTrue(svc.is_stale(make_task(age_seconds=svc.STALE_AFTER_SECONDS + 1)))
        self.assertFalse(svc.is_stale(make_task(age_seconds=1)))
        self.assertFalse(svc.is_stale(make_task(status="done", age_seconds=9999)))
        self.assertTrue(svc.is_stale(make_task(updated_at=None, started_at=None, created_at=None)))

    def test_sweep_only_fails_stale_tasks(self):
        stale = make_task(age_seconds=1000)
        fresh = make_task(age_seconds=2)
        db = FakeDB([stale, fresh])
        self.assertEqual(svc.sweep_stale_tasks(db), 1)
        self.assertEqual(stale.status, "failed")
        self.assertIn("重跑", stale.error)
        self.assertEqual(fresh.status, "generating")   # 正常执行中的任务不能被误杀
        self.assertIsNotNone(stale.finished_at)
        self.assertEqual(db.commits, 1)

    def test_recover_on_startup_fails_all_generating(self):
        # 新进程一起来，库里的 generating 必然是上一轮进程留下的，不可能还活着
        rows = [make_task(age_seconds=1), make_task(age_seconds=1000), make_task(status="done")]
        db = FakeDB(rows)
        self.assertEqual(svc.recover_interrupted_tasks(db), 2)
        self.assertTrue(all(row.status == "failed" for row in rows[:2]))
        self.assertIn("服务重启", rows[0].error)
        self.assertEqual(rows[2].status, "done")

    def test_sweep_with_nothing_to_do_does_not_commit(self):
        db = FakeDB([make_task(status="planned")])
        self.assertEqual(svc.sweep_stale_tasks(db), 0)
        self.assertEqual(db.commits, 0)

    def test_generated_results_land_in_second_level_categories(self):
        # 这三个 key 都是 result 下的预置二级目录，写错就会落进「未归类」
        self.assertEqual(svc._result_category("主图 · 正面"), "main")
        self.assertEqual(svc._result_category("详情图 · 尺寸"), "detail")
        self.assertEqual(svc._result_category("场景图"), "variant")
        self.assertEqual(svc._result_category("风格套用 · 侧面"), "variant")


if __name__ == "__main__":
    unittest.main()
