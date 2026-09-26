# -*- coding: utf-8 -*-
"""
AI 打码服务 v5 — RapidOCR + OpenCV
精确检测微信聊天截图中的头像 + 昵称，进行高斯模糊打码。

检测策略：
1. RapidOCR 文字检测 → 精确获取所有文字的像素级边框
2. OpenCV 轮廓检测 → 在左右边缘找头像方块
3. 布局规则关联 → 头像旁的文字 = 昵称，需要打码
"""
import cv2
import numpy as np
from io import BytesIO
from typing import List, TypedDict
from PIL import Image, ImageFilter


class Region(TypedDict):
    x: int
    y: int
    w: int
    h: int
    label: str


# ---- 配置 ----
AVATAR_MIN_SIZE = 28
AVATAR_MAX_SIZE = 70
EDGE_SCAN_WIDTH = 100
NICKNAME_LINK_DISTANCE = 80

# RapidOCR 单例
_ocr_engine = None


def _get_ocr():
    """懒加载 RapidOCR 单例"""
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine


# ==================== 头像检测 (OpenCV) ====================

def detect_avatars(img_cv: np.ndarray) -> List[Region]:
    """
    在截图左右边缘，用 OpenCV 轮廓检测找头像方块。
    """
    h, w = img_cv.shape[:2]
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    regions: List[Region] = []
    found_ys: List[int] = []

    scan_zones = [
        (0, min(EDGE_SCAN_WIDTH, w // 3), "avatar_left"),
        (max(w - EDGE_SCAN_WIDTH, w * 2 // 3), w, "avatar_right"),
    ]

    for x_start, x_end, label in scan_zones:
        roi = gray[:, x_start:x_end]
        edges = cv2.Canny(roi, 50, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            bx, by, bw, bh = cv2.boundingRect(cnt)

            if not (AVATAR_MIN_SIZE <= bw <= AVATAR_MAX_SIZE and
                    AVATAR_MIN_SIZE <= bh <= AVATAR_MAX_SIZE):
                continue

            aspect = bw / bh if bh > 0 else 0
            if not (0.7 <= aspect <= 1.4):
                continue

            block = img_cv[by:by+bh, x_start+bx:x_start+bx+bw]
            if block.size == 0:
                continue
            if np.std(block) < 15:
                continue

            abs_y = by
            if any(abs(abs_y - fy) < AVATAR_MIN_SIZE for fy in found_ys):
                continue

            regions.append(Region(
                x=x_start + bx,
                y=by,
                w=bw,
                h=bh,
                label=label,
            ))
            found_ys.append(abs_y)

    print(f"[mask_service] OpenCV 检测到 {len(regions)} 个头像")
    return regions


# ==================== 文字检测 (RapidOCR) ====================

def detect_texts(img_cv: np.ndarray) -> List[dict]:
    """
    用 RapidOCR 检测图片中所有文字区域。
    RapidOCR 返回格式: [[box, text, confidence], ...]
    box = [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    """
    ocr = _get_ocr()
    result, _ = ocr(img_cv)

    texts = []
    if result:
        for item in result:
            box = item[0]   # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            text = item[1]
            confidence = item[2]

            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x, y = int(min(xs)), int(min(ys))
            w = int(max(xs) - min(xs))
            h = int(max(ys) - min(ys))

            texts.append({
                'x': x, 'y': y, 'w': w, 'h': h,
                'text': text,
                'confidence': confidence,
            })

    print(f"[mask_service] RapidOCR 检测到 {len(texts)} 个文字区域")
    for t in texts:
        print(f"  → '{t['text']}' at ({t['x']},{t['y']}) {t['w']}x{t['h']}")
    return texts


# ==================== 布局关联：找出需要打码的昵称 ====================

def find_nicknames(avatars: List[Region], texts: List[dict], img_w: int) -> List[Region]:
    """
    判断哪些文字是「昵称」（而非消息内容）：
    关键区别：昵称在头像**顶部偏上**，消息文字在头像**下方气泡里**。
    """
    nickname_regions: List[Region] = []
    used = set()

    for avatar in avatars:
        ax, ay, aw, ah = avatar['x'], avatar['y'], avatar['w'], avatar['h']

        for i, t in enumerate(texts):
            if i in used:
                continue
            tx, ty, tw, th = t['x'], t['y'], t['w'], t['h']

            # ★ 核心判断：昵称在头像顶部附近
            # 昵称 y 应该在 [头像顶部-20px, 头像顶部+10px] 范围内
            # 如果文字 y > 头像顶部+10，那就是消息气泡里的文字，不是昵称
            if ty > ay + 10:
                continue  # 在头像下方 → 消息文字，跳过
            if ty < ay - 25:
                continue  # 太远了，不是这个头像的昵称

            # 昵称高度通常很小（12~22px 的小字体）
            if th > 25:
                continue

            # 水平方向：昵称在头像旁边
            if avatar['label'] == 'avatar_left':
                h_dist = tx - (ax + aw)
                if not (-10 <= h_dist <= NICKNAME_LINK_DISTANCE):
                    continue
            else:
                h_dist = ax - (tx + tw)
                if not (-10 <= h_dist <= NICKNAME_LINK_DISTANCE):
                    continue

            # 昵称通常是短文本
            if len(t['text']) > 15:
                continue

            pad = 4
            nickname_regions.append(Region(
                x=max(0, tx - pad),
                y=max(0, ty - pad),
                w=tw + 2 * pad,
                h=th + 2 * pad,
                label="nickname",
            ))
            used.add(i)
            print(f"  → 昵称匹配: '{t['text']}' (y={ty}, avatar_y={ay})")

    print(f"[mask_service] 关联出 {len(nickname_regions)} 个昵称区域")
    return nickname_regions


# ==================== 模糊处理 ====================

def apply_blur(img: Image.Image, regions: List[Region]) -> Image.Image:
    """对指定区域做强力高斯模糊"""
    w, h = img.size
    for r in regions:
        rx, ry, rw, rh = r['x'], r['y'], r['w'], r['h']
        rx = max(0, min(rx, w - 1))
        ry = max(0, min(ry, h - 1))
        rw = min(rw, w - rx)
        rh = min(rh, h - ry)
        if rw <= 2 or rh <= 2:
            continue

        box = (rx, ry, rx + rw, ry + rh)
        cropped = img.crop(box)
        blurred = cropped.filter(ImageFilter.GaussianBlur(radius=25))
        blurred = blurred.filter(ImageFilter.GaussianBlur(radius=20))
        img.paste(blurred, box)

    return img


# ==================== 入口 ====================

def mask_image(image_bytes: bytes) -> bytes:
    """
    完整打码流程：
    1. OpenCV 检测头像
    2. RapidOCR 检测所有文字
    3. 布局关联 → 找出需要打码的昵称
    4. 合并（头像 + 昵称区域） → 高斯模糊
    """
    img_array = np.frombuffer(image_bytes, dtype=np.uint8)
    img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    img_pil = Image.open(BytesIO(image_bytes)).convert("RGB")
    h, w = img_cv.shape[:2]
    print(f"[mask_service] 图片尺寸: {w}x{h}")

    avatars = detect_avatars(img_cv)
    texts = detect_texts(img_cv)
    nicknames = find_nicknames(avatars, texts, w)

    all_regions = avatars + nicknames
    print(f"[mask_service] 合计 {len(all_regions)} 个待打码区域")

    if not all_regions:
        print("[mask_service] 未检测到需打码区域，返回原图")
        return image_bytes

    img_pil = apply_blur(img_pil, all_regions)

    output = BytesIO()
    img_pil.save(output, format="PNG", optimize=True)
    return output.getvalue()
