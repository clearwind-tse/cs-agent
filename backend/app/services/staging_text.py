# -*- coding: utf-8 -*-
"""
暂存区文本规范化
"""
from typing import Any, Dict, List


def dedupe_consecutive_lines(text: str) -> str:
    """去掉同一段内容里连续重复的文本行。"""
    if not text:
        return text

    result: List[str] = []
    previous_normalized: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized = line
        if normalized == previous_normalized:
            continue

        result.append(line)
        previous_normalized = normalized

    return "\n".join(result)


def normalize_conversation_json(conversation_json: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """规范化对话 turns，去掉每个 turn 内部的连续重复行。"""
    normalized_turns: List[Dict[str, Any]] = []

    for item in conversation_json:
        normalized_item = dict(item)
        normalized_item["content"] = dedupe_consecutive_lines(str(item.get("content") or ""))
        normalized_turns.append(normalized_item)

    return normalized_turns


def rebuild_cleaned_text(conversation_json: List[Dict[str, Any]]) -> str:
    """根据 conversation_json 重新构建 cleaned_text。"""
    lines: List[str] = []
    for item in conversation_json:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        speaker = item.get("sender_name") or item.get("role") or "unknown"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)
