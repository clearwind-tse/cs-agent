# -*- coding: utf-8 -*-
"""
多轮对话实训服务

- generate_scenarios: 从「已审核真实对话」1:1 提炼客户情景
                      （人设/背景/开场白/隐藏诉求/考察点 + 来源绑定 + 真实客服回复参考答案）
- customer_turn:      AI 扮演客户，按已有对话产出下一句

评分/评测不在此模块，由后续独立的会话质检服务消费对话记录。
"""
import json
import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session as DBSession

from app.models.chat import StagingConversation
from app.services.quiz import _get_llm_client
from app.services.xiaocan_persona import (
    BUSINESS_CONTEXT,
    CATEGORY_LABELS,
    FORBIDDEN_TOPICS,
)

# 单次会话客户轮次上限，达到即自动结束
MAX_TURNS = 12

# 提炼素材的最小轮数：低于此值的真实对话提炼不出背景/诉求，人设只能靠编
MIN_SOURCE_TURNS = 3

# 送进 LLM 的真实对话截断上限（控制 token）
MAX_SOURCE_TURNS = 20
MAX_SOURCE_CHARS = 2000


DISTILL_SCENARIO_PROMPT = """你是「小蚕惠生活（小蚕霸王餐）」的客服培训情景设计师。下面给你【一场真实发生的小蚕客服对话】，请依据它提炼出 1 个用于多轮对话实训的客户情景。

【业务背景·必须严格贴合】
{BUSINESS_CONTEXT}

【本情景分类】
「{cat_label}」

【严禁出现的题材】
{FORBIDDEN_TOPICS}

【真实对话原文】
{conversation}

【客户开口的第一句·已由系统固定，不要改写】
{customer_first_line}

【提炼要求】
1. customer_persona：依据这场对话推断客户是谁（学生/外卖重度用户/上班族/宝妈等），写具体
2. customer_background：依据对话推断事发背景（领了什么券、在哪下的单、订单状态等）
3. hidden_needs：客户没说出口的真实诉求与情绪（供扮演参考，学员看不到）
4. expected_points：这场对话考察客服哪些点（本期不评分，仅供人工/质检参考）
5. difficulty：easy / medium / hard 之一
6. 一切以这场真实对话为据，不要发明对话里没有的业务事实

【输出格式】
严格输出 JSON 对象，不要输出其他内容：
{{
  "customer_persona": "学生党，大三，几乎天天点外卖",
  "customer_background": "在小蚕领了红包但外卖是在美团 App 直接下的单",
  "hidden_needs": "想要回这笔返利，有点不爽但还不算激动",
  "expected_points": "讲清必须从小蚕跳转下单才有返利；给出下次的正确操作",
  "difficulty": "easy"
}}"""


CUSTOMER_ROLEPLAY_PROMPT = """你现在要扮演一位找「小蚕惠生活」客服咨询的客户。你只看得到客服的回复，要像真人一样继续对话。

【你的人设】
{persona}

【你的背景】
{background}

【你真正的诉求和情绪（不会直说，要靠对话体现）】
{hidden_needs}

【你开口说的第一句（已发生）】
{opening_line}

【对话规则】
1. 只输出"客户"这一句要说的话，不要旁白、不要括号动作、不要替客服回答
2. 口语化、简短，一般 1~3 句，像微信聊天
3. 根据客服的回答自然地推进：
   - 客服讲清楚且让你满意 → 表示感谢并收尾
   - 客服答非所问 / 敷衍 / 说错规则 → 追问、质疑，情绪可适度升级
   - 客服给出下一步操作 → 可以确认"那我这样弄就行是吧"，或表示自己不会操作
4. 不要一次说太多，不要自问自答，不要跳出角色
5. 当对话自然结束（你已满意告别，或明确表示不用了/不说了）时，把 is_end 设为 true

【输出格式】
严格输出 JSON 对象，不要输出其他内容：
{{"reply": "客户这一句要说的话", "is_end": false}}"""


def _strip_fence(content: str) -> str:
    """剥掉 ```json 围栏（兼容 LLM 输出）"""
    content = content.strip()
    fence = re.search(r'```(?:json)?\s*(.+?)```', content, re.DOTALL)
    return fence.group(1).strip() if fence else content


def _first_customer_line(conversation_json: Optional[list]) -> str:
    """真实对话里客户说的第一句（情景开场白以它为准，1:1 的硬保证）"""
    for t in conversation_json or []:
        if t.get("role") == "user" and (t.get("content") or "").strip():
            return t["content"].strip()
    return ""


def _extract_reference_replies(conversation_json: Optional[list]) -> List[str]:
    """真实对话里客服的每一句回复（参考答案，不经 LLM，逐字保真）"""
    return [
        t["content"].strip()
        for t in (conversation_json or [])
        if t.get("role") == "assistant" and (t.get("content") or "").strip()
    ]


def _normalize_transcript(conversation_json: Optional[list]) -> List[Dict]:
    """真实对话规整为与实训 transcript 一致的结构（role: customer/agent）"""
    role_map = {"user": "customer", "assistant": "agent"}
    return [
        {"role": role_map.get(t.get("role"), "customer"), "content": (t.get("content") or "").strip()}
        for t in (conversation_json or [])
        if (t.get("content") or "").strip()
    ]


def _render_conversation(conversation_json: Optional[list]) -> str:
    """把真实对话渲染成「客户: …/客服: …」文本供提炼 prompt 使用（有截断）"""
    lines = []
    for t in (conversation_json or [])[:MAX_SOURCE_TURNS]:
        speaker = "客服" if t.get("role") == "assistant" else "客户"
        lines.append(f"{speaker}: {(t.get('content') or '').strip()}")
    return "\n".join(lines)[:MAX_SOURCE_CHARS]


def _select_source_conversations(
    db: DBSession, category: str, count: int, *, min_turns: int = MIN_SOURCE_TURNS
) -> Tuple[List[StagingConversation], Dict]:
    """按分类挑选「已审核」真实对话作为提炼素材。

    - 分类取 human_category（auto_category 全部是 'valuable'，不可用）
    - 同 session_id 去重：一场真实对话在同一情景集里只出现一次
    - 轮数 < min_turns 的丢弃：素材太薄，提炼不出背景/诉求
    - 排序不依赖质量分：auto_quality_score 当前全部并列，改用时间 + id 稳定序
    """
    rows = (
        db.query(StagingConversation)
        .filter(
            StagingConversation.status == "approved",
            StagingConversation.human_category == category,
            StagingConversation.conversation_json.isnot(None),
        )
        .order_by(StagingConversation.created_at.desc(), StagingConversation.id.asc())
        .all()
    )

    picked: List[StagingConversation] = []
    seen_sessions = set()
    dropped_short = 0
    dropped_duplicate = 0
    for row in rows:
        turns = len(row.conversation_json or [])
        if turns < min_turns:
            dropped_short += 1
            continue
        if row.session_id in seen_sessions:
            dropped_duplicate += 1
            continue
        seen_sessions.add(row.session_id)
        picked.append(row)
        if len(picked) >= count:
            break

    stats = {
        "available": len(rows),
        "matched": len(picked),
        "dropped_short": dropped_short,
        "dropped_duplicate": dropped_duplicate,
    }
    return picked, stats


def _distill_one(
    client, model: str, category: str, cat_label: str, src: StagingConversation
) -> Dict:
    """把一条真实对话提炼成一个客户情景（opening_line/来源由调用方强制回填）"""
    system_prompt = DISTILL_SCENARIO_PROMPT.format(
        BUSINESS_CONTEXT=BUSINESS_CONTEXT,
        cat_label=cat_label,
        FORBIDDEN_TOPICS=FORBIDDEN_TOPICS,
        conversation=_render_conversation(src.conversation_json),
        customer_first_line=_first_customer_line(src.conversation_json) or "（缺失）",
    )
    user_prompt = f"请依据上面这场真实对话，提炼 1 个「{cat_label}」客户情景。"

    last_err: Optional[Exception] = None
    # 第一次 0.7；解析失败降到 0.3 重试一次
    for temperature in (0.7, 0.3):
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=1200,
        )
        content = _strip_fence(response.choices[0].message.content)
        obj_match = re.search(r'\{.*\}', content, re.DOTALL)
        if obj_match:
            content = obj_match.group()
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                return data
            last_err = ValueError("LLM 未返回 JSON 对象")
        except (json.JSONDecodeError, AttributeError) as exc:
            last_err = exc

    raise last_err or RuntimeError("情景提炼失败")


def generate_scenarios(
    db: DBSession, category: str, count: int, *, min_turns: int = MIN_SOURCE_TURNS
) -> Tuple[List[Dict], Dict]:
    """从该分类的「已审核真实对话」1:1 提炼客户情景。

    返回 (scenarios, stats)。素材不足时少生成（不跨分类填充）；
    该分类一条可用素材都没有时抛 ValueError（由路由转 400）。
    """
    client, model = _get_llm_client()
    if not client:
        raise RuntimeError("LLM 客户端未初始化，请检查 API Key 配置")

    cat_label = CATEGORY_LABELS.get(category, "省钱讲解")
    rows, stats = _select_source_conversations(db, category, count, min_turns=min_turns)
    if not rows:
        raise ValueError(
            f"分类「{cat_label}」暂无已审核的真实对话可用，"
            f"请改选分类，或先在数据审核页审核该类素材"
        )

    scenarios: List[Dict] = []
    errors: List[Dict] = []
    for src in rows:
        try:
            sc = _distill_one(client, model, category, cat_label, src)
        except Exception as exc:  # 单条失败不影响其余素材
            errors.append({"conversation_id": src.id, "error": str(exc)})
            continue

        sc["category"] = category
        sc["difficulty"] = sc.get("difficulty") or "medium"
        # opening_line 与参考答案一律以真实对话为准，不信任 LLM 复述（1:1 的硬保证）
        sc["opening_line"] = _first_customer_line(src.conversation_json) or sc.get("opening_line", "")
        sc["source"] = {
            "conversation_id": src.id,
            "session_id": src.session_id,
            "quality_score": src.auto_quality_score,
            "turn_count": len(src.conversation_json or []),
        }
        sc["reference_replies"] = _extract_reference_replies(src.conversation_json)
        sc["source_transcript"] = _normalize_transcript(src.conversation_json)
        scenarios.append(sc)

    if not scenarios:
        raise RuntimeError(f"全部情景提炼失败：{errors[:3]}")

    # 重编号必须在过滤之后，避免 id 空洞（前端 key 与 _find_scenario 依赖连续 id）
    for i, s in enumerate(scenarios):
        s["id"] = i + 1

    stats = {**stats, "requested": count, "produced": len(scenarios), "failed": len(errors)}
    if errors:
        stats["errors"] = errors[:5]
    return scenarios, stats


def customer_turn(scenario: Dict, transcript: List[Dict]) -> Dict:
    """AI 扮演客户，按已有对话产出下一句。返回 {reply, is_end}"""
    client, model = _get_llm_client()
    if not client:
        raise RuntimeError("LLM 客户端未初始化，请检查 API Key 配置")

    system_prompt = CUSTOMER_ROLEPLAY_PROMPT.format(
        persona=scenario.get("customer_persona", "普通用户"),
        background=scenario.get("customer_background", ""),
        hidden_needs=scenario.get("hidden_needs", ""),
        opening_line=scenario.get("opening_line", ""),
    )

    history = [
        f"{'客服' if t.get('role') == 'agent' else '客户'}: {t.get('content', '')}"
        for t in transcript
    ]
    user_prompt = "以下是到目前为止的对话：\n\n" + "\n".join(history) + "\n\n请输出客户这一句。"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
        max_tokens=500,
    )

    content = _strip_fence(response.choices[0].message.content)
    obj_match = re.search(r'\{.*\}', content, re.DOTALL)
    if obj_match:
        content = obj_match.group()

    try:
        data = json.loads(content)
        reply = str(data.get("reply", "")).strip()
        is_end = bool(data.get("is_end", False))
    except (json.JSONDecodeError, AttributeError):
        # 兜底：LLM 没按 JSON 输出时，把整段当作客户的话
        reply, is_end = content.strip(), False

    return {"reply": reply or "……", "is_end": is_end}
