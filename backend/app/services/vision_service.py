# -*- coding: utf-8 -*-
"""
豆包视觉理解服务
通过火山方舟 API 调用 doubao-vision 模型，从图片中提取学生信息
"""
import json
import base64
import re
from typing import List, Dict, Any, Optional
from openai import OpenAI

from app.config import get_settings

# 提取学生信息的 System Prompt
EXTRACT_PROMPT = """你是一个专业的数据提取助手。请仔细识别图片中的所有人员信息，提取以下字段：

- name: 姓名
- phone: 电话号码（11位手机号）
- douyin_order: 抖音订单号（如果有）
- channel: 渠道（"微信" 或 "抖音"，根据上下文判断）
- class_name: 班级名称（如果有）
- job_title: 岗位（如果有）
- enroll_date: 入学日期（格式 YYYY-MM-DD，如果有）

## 规则
1. 一张图片可能包含多条学员记录，请全部提取
2. 电话号码请确保是 11 位数字，去掉空格和横线
3. 如果某个字段在图片中找不到，设为 null
4. 如果图片是抖音订单截图，channel 设为 "抖音"；否则默认 "微信"
5. 仅输出 JSON 数组，不要输出其他任何文字

## 输出格式
严格输出 JSON 数组，例如：
```json
[
  {
    "name": "张三",
    "phone": "13800138000",
    "douyin_order": "DY202309018821",
    "channel": "抖音",
    "class_name": "销售特训一期",
    "job_title": "销售代表",
    "enroll_date": "2024-01-10"
  }
]
```"""

_client: Optional[OpenAI] = None


def _get_vision_client() -> OpenAI:
    """获取 OpenAI 兼容客户端（火山方舟）"""
    global _client
    if _client is None:
        settings = get_settings()
        # 优先使用视觉模型专用 Key，回退到通用 Key
        api_key = settings.ark_vision_api_key or settings.ark_api_key
        if not api_key:
            raise RuntimeError(
                "火山方舟 API Key 未配置。请设置环境变量 ARK_VISION_API_KEY 或 ARK_API_KEY。"
            )
        _client = OpenAI(
            api_key=api_key,
            base_url=settings.ark_vision_base_url,
        )
    return _client


def _parse_json_from_response(text: str) -> List[Dict[str, Any]]:
    """从模型响应中解析 JSON 数组，兼容 markdown 代码块包裹"""
    # 尝试从 ```json ... ``` 代码块中提取
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if code_block:
        text = code_block.group(1).strip()

    # 尝试直接解析
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            # 模型可能返回 {"students": [...]} 的格式
            for key in ("students", "data", "items", "records", "results"):
                if key in result and isinstance(result[key], list):
                    return result[key]
            return [result]
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # 尝试逐行找 JSON 数组
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("["):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    raise ValueError(f"无法从模型响应中解析出 JSON 数据。原始响应: {text[:500]}")


def extract_students_from_image(
    image_data: bytes,
    content_type: str = "image/png",
) -> Dict[str, Any]:
    """
    从图片中提取学生信息

    Args:
        image_data: 图片二进制数据
        content_type: 图片 MIME 类型

    Returns:
        {
            "students": [...],  # 识别出的学生数据列表
            "raw_text": "...",  # 模型原始响应（用于调试）
        }
    """
    settings = get_settings()
    client = _get_vision_client()

    # 将图片转为 base64 data URL
    b64 = base64.b64encode(image_data).decode("utf-8")
    image_url = f"data:{content_type};base64,{b64}"

    # 调用豆包视觉模型
    response = client.chat.completions.create(
        model=settings.ark_vision_model,
        messages=[
            {
                "role": "system",
                "content": EXTRACT_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                    {
                        "type": "text",
                        "text": "请识别这张图片中的所有学员信息，提取姓名、电话号码、抖音订单号等字段，以 JSON 数组格式返回。",
                    },
                ],
            },
        ],
        max_tokens=4096,
        temperature=0.1,  # 低温度以提高准确性
    )

    raw_text = response.choices[0].message.content or ""
    print(f"[AI Vision] Raw response: {raw_text[:300]}...")

    # 解析结构化数据
    students = _parse_json_from_response(raw_text)

    # 清洗和标准化
    cleaned = []
    for s in students:
        record = {
            "name": (s.get("name") or "").strip(),
            "phone": _clean_phone(s.get("phone")),
            "douyin_order": (s.get("douyin_order") or s.get("order") or "").strip() or None,
            "channel": s.get("channel", "微信"),
            "class_name": (s.get("class_name") or s.get("class") or "").strip() or None,
            "job_title": (s.get("job_title") or s.get("job") or "").strip() or None,
            "enroll_date": (s.get("enroll_date") or "").strip() or None,
        }
        # 至少有姓名或电话才保留
        if record["name"] or record["phone"]:
            cleaned.append(record)

    return {
        "students": cleaned,
        "raw_text": raw_text,
    }


def _clean_phone(phone: Any) -> Optional[str]:
    """清洗电话号码：去掉非数字字符，验证 11 位"""
    if not phone:
        return None
    digits = re.sub(r"\D", "", str(phone))
    # 如果开头是 86 国际区号，去掉
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return digits if len(digits) == 11 else str(phone).strip() or None
