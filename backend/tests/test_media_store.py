# -*- coding: utf-8 -*-
"""
本地媒体存储的单测

只测「落盘层」的安全与正确性，不启服务、不连库：
  - mime 白名单（尤其 SVG / HTML 必须拒绝，否则同源静态直出就是存储型 XSS）
  - 落盘路径、尺寸解析、sha256
  - 路径穿越
  - 大小上限且不留残留文件
"""
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import HTTPException
from PIL import Image

from app.config import get_settings
from app.services import media_store


def _png_bytes(size=(40, 30), color=(30, 28, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class MediaStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="media-test-")
        os.environ["MEDIA_ROOT"] = self.tmp
        os.environ["MEDIA_MAX_MB"] = "20"
        get_settings.cache_clear()

    def tearDown(self):
        os.environ.pop("MEDIA_ROOT", None)
        os.environ.pop("MEDIA_MAX_MB", None)
        get_settings.cache_clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_normalize_mime_accepts_images_and_derives_suffix(self):
        # 后缀必须由 mime 决定，不看客户端给的文件名（avatar.txt 也得存成 .png）
        self.assertEqual(media_store.normalize_mime("image/png", "x.txt"), ("image/png", ".png"))
        self.assertEqual(media_store.normalize_mime("image/jpeg; charset=binary", None), ("image/jpeg", ".jpg"))
        # 客户端不带类型时用后缀兜底
        self.assertEqual(media_store.normalize_mime(None, "a.webp"), ("image/webp", ".webp"))

    def test_normalize_mime_rejects_svg_and_html(self):
        for mime in ("image/svg+xml", "text/html", "application/javascript"):
            with self.assertRaises(HTTPException) as ctx:
                media_store.normalize_mime(mime, "x.png")
            self.assertEqual(ctx.exception.status_code, 415)

    def test_normalize_mime_rejects_unknown_type(self):
        with self.assertRaises(HTTPException) as ctx:
            media_store.normalize_mime("application/pdf", "a.pdf")
        self.assertEqual(ctx.exception.status_code, 415)

    def test_save_stream_writes_file_and_reads_size(self):
        data = _png_bytes((64, 48))
        saved = media_store.save_stream(io.BytesIO(data), "image/png", "礼盒.png")

        self.assertEqual(saved["mime"], "image/png")
        self.assertEqual(saved["size"], len(data))
        self.assertEqual((saved["width"], saved["height"]), (64, 48))
        self.assertEqual(len(saved["sha256"]), 64)
        # 落盘名与原始文件名解耦，避免中文/穿越
        self.assertNotIn("礼盒", saved["stored_name"])
        self.assertTrue(saved["stored_name"].endswith(".png"))

        path = media_store.safe_join(saved["rel_path"])
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes(), data)
        # 不留 .part 临时文件
        self.assertEqual([p.name for p in path.parent.iterdir() if p.name.endswith(".part")], [])

    def test_same_content_same_hash(self):
        data = _png_bytes()
        first = media_store.save_stream(io.BytesIO(data), "image/png", "a.png")
        second = media_store.save_stream(io.BytesIO(data), "image/png", "b.png")
        # 落盘名不同，但指纹相同 —— 去重靠指纹，路由层据此复用记录
        self.assertNotEqual(first["stored_name"], second["stored_name"])
        self.assertEqual(first["sha256"], second["sha256"])

    def test_safe_join_blocks_traversal(self):
        for bad in ("../app/main.py", "../../etc/passwd", "2026/11/../../../x.png"):
            with self.assertRaises(HTTPException) as ctx:
                media_store.safe_join(bad)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_save_stream_rejects_oversized_and_cleans_up(self):
        os.environ["MEDIA_MAX_MB"] = "1"
        get_settings.cache_clear()

        big = b"\x89PNG\r\n\x1a\n" + b"0" * (1024 * 1024 + 10)
        with self.assertRaises(HTTPException) as ctx:
            media_store.save_stream(io.BytesIO(big), "image/png", "big.png")
        self.assertEqual(ctx.exception.status_code, 413)

        root = media_store.get_media_root()
        leftovers = [p for p in root.rglob("*") if p.is_file()]
        self.assertEqual(leftovers, [])

    def test_save_stream_rejects_empty(self):
        with self.assertRaises(HTTPException) as ctx:
            media_store.save_stream(io.BytesIO(b""), "image/png", "empty.png")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_delete_file_is_idempotent(self):
        saved = media_store.save_stream(io.BytesIO(_png_bytes()), "image/png", "a.png")
        media_store.delete_file(saved["rel_path"])
        self.assertFalse(media_store.safe_join(saved["rel_path"]).exists())
        # 再删一次不抛异常
        media_store.delete_file(saved["rel_path"])


if __name__ == "__main__":
    unittest.main()
