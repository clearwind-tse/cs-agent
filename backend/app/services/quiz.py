# -*- coding: utf-8 -*-
"""
AI 考核出题 & 评判服务
基于知识库内容生成本平台客服场景题目，AI 评判答案合理性
"""
import json
import re
from typing import List, Dict, Optional
from sqlalchemy.orm import Session as DBSession

from app.config import get_settings
from app.models.chat import KnowledgeArticle, KnowledgeChunk, StagingConversation
from app.services.benpingtai_persona import (
    AGENT_PERSONA,
    BUSINESS_CONTEXT,
    CATEGORY_LABELS,
    FORBIDDEN_TOPICS,
)

settings = get_settings()


def _get_llm_client(slot: str = "quiz"):
    """取 LLM 客户端。

    slot 决定用设置页里哪个板块的模型；本项目多个服务复用这个函数，
    调用方显式传自己的板块，避免「改了在线对话模型，考核也跟着变」。
    """
    from app.services.model_registry import openai_client
    return openai_client(slot)


def _load_knowledge_context(db: DBSession, category: Optional[str] = None, limit: int = 30) -> str:
    """从知识库加载参考素材"""
    articles = db.query(KnowledgeArticle)
    if category:
        articles = articles.filter(KnowledgeArticle.scene_category == category)
    articles = articles.order_by(KnowledgeArticle.confidence.desc()).limit(limit).all()

    if articles:
        lines = []
        for a in articles:
            lines.append(f"场景: {a.scene}")
            if a.customer_says:
                lines.append(f"客户说: {a.customer_says}")
            if a.recommended_response:
                lines.append(f"推荐回复: {a.recommended_response}")
            lines.append("---")
        return "\n".join(lines)

    chunks = db.query(KnowledgeChunk).limit(limit).all()
    if chunks:
        return "\n---\n".join(c.content_block for c in chunks if c.content_block)

    # 兜底：知识库尚未蒸馏时，直接用暂存区的真实本平台客服对话做素材
    rows = (
        db.query(StagingConversation)
        .filter(StagingConversation.cleaned_text.isnot(None))
        .order_by(StagingConversation.auto_quality_score.desc())
        .limit(limit)
        .all()
    )
    if rows:
        return "\n---\n".join(r.cleaned_text for r in rows if r.cleaned_text)

    return ""


def generate_quiz_questions(
    db: DBSession,
    category: str = "savings_explain",
    count: int = 10,
) -> List[Dict]:
    """
    AI 生成考核题目
    返回 [{id, question, reference_answer, category, difficulty}]
    """
    client, model = _get_llm_client()
    if not client:
        raise RuntimeError("LLM 客户端未初始化，请检查 API Key 配置")

    context = _load_knowledge_context(db, category)

    cat_label = CATEGORY_LABELS.get(category, "省钱讲解")

    system_prompt = f"""你是「本平台（本平台霸王餐）」的客服培训考官，负责出题考核客服的「{cat_label}」能力。

【业务背景·必须严格贴合，题目不得超出以下范围】
{BUSINESS_CONTEXT}

【本类场景的真实含义·别搞错】
「{cat_label}」对应的是本平台业务里的场景。特别注意：**「订单问题」指没从本平台跳转、跳转失败、下单后没返利、红包没抵扣上、门店/地址选错——不是电商的发货、物流、换货、退差价。**

【严禁出现的题材】
{FORBIDDEN_TOPICS}

【客服人设】
{AGENT_PERSONA}

【出题要求】
1. 每题给一个真实客户说法（口语化，可带「白嫖/回血/神券」等内部黑话）
2. 覆盖难度：简单约 3 题、中等约 4 题、困难约 3 题
3. 参考答话要基于知识库素材，给出可执行的本平台口径
4. 贴近实战，不要学术化

【输出格式】
严格输出 JSON 数组，不要输出其他内容:
[
  {{
    "id": 1,
    "question": "客户说：xxx 你该如何回复？",
    "reference_answer": "推荐回复话术",
    "difficulty": "easy/medium/hard"
  }}
]"""

    if not context:
        context = "（暂无素材，请依据上面的业务背景出题）"

    user_prompt = f"以下是知识库中的本平台客服真实对话素材:\n\n{context}\n\n请基于以上素材出{count}道「{cat_label}」考核题"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=4000,
    )

    content = response.choices[0].message.content.strip()
    json_match = re.search(r'\[.*\]', content, re.DOTALL)
    if json_match:
        content = json_match.group()

    questions = json.loads(content)

    for i, q in enumerate(questions):
        q["id"] = i + 1
        q["category"] = category
        if "difficulty" not in q:
            q["difficulty"] = "medium"

    return questions[:count]


def ai_grade_answers(
    questions: List[Dict],
    user_answers: List[Dict],
) -> List[Dict]:
    """
    AI 评判每道题的答案
    返回 [{question_id, score, feedback, is_reasonable}]
    """
    client, model = _get_llm_client()
    if not client:
        raise RuntimeError("LLM 客户端未初始化，请检查 API Key 配置")

    answer_map = {a["question_id"]: a["answer"] for a in user_answers}

    qa_text = []
    for q in questions:
        qid = q["id"]
        user_ans = answer_map.get(qid, "(未作答)")
        qa_text.append(
            f"题目{qid}: {q['question']}\n"
            f"参考答案: {q.get('reference_answer', '无')}\n"
            f"客服回答: {user_ans}"
        )

    system_prompt = """你是「本平台（本平台霸王餐）」的资深客服培训评审，负责评判客服考核答案。

【评判标准】
1. 业务准确性：返利/红包/跳转/霸王餐/积分的规则是否说对（例如是否讲清「必须从本平台跳转下单才有返利」）
2. 亲和专业：语气是否专业亲和、像本平台本人，可用「您」和 emoji；用「亲亲」这类电商口吻要扣分
3. 可执行性：是否给出具体可操作的下一步（怎么领券、怎么跳转、怎么查返利、怎么提现）
4. 不乱承诺：不得承诺平台没有的能力（如「直接给你补返利」「保证中签」「帮你改价」）
5. 合规：不索要/不泄露密码、验证码等隐私信息

【评分规则】
- 每题 0-10 分
- 8-10: 优秀 可直接使用
- 5-7: 合格 有改进空间
- 0-4: 不合格 需要重新学习

【输出格式】
严格输出 JSON 数组:
[
  {
    "question_id": 1,
    "score": 8,
    "feedback": "具体点评 指出优点和不足",
    "is_reasonable": true
  }
]"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(qa_text)},
        ],
        temperature=0.3,
        max_tokens=4000,
    )

    content = response.choices[0].message.content.strip()
    json_match = re.search(r'\[.*\]', content, re.DOTALL)
    if json_match:
        content = json_match.group()

    return json.loads(content)
