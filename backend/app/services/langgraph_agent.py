# -*- coding: utf-8 -*-
"""
基于 LangGraph 的智能客服 Agent 编排

解决此前缺陷：
- 缺陷1/2/4：真正的工具调用循环 —— 把 Agent 绑定的 Skill / MCP / 内置工具
  以 OpenAI function-calling schema 暴露给 LLM，LLM 决策调用，节点执行后回填，
  再回到 LLM 形成闭环。Skill/MCP 配置从此真正生效。
- 缺陷8：Skill 内容按需检索，避免整篇注入撑爆上下文。

设计要点（无状态编排）：
- 编译后的 StateGraph 全局只构建一次并缓存；节点都是「只读 state」的纯函数，
  不持有任何 per-request 状态，因此可安全在并发请求间复用。
- db 会话通过 state["db"] 在节点间透传，避免把请求级会话缓存在单例里导致
  「Session is closed」的问题。

图结构：
  START → classify → route → agent ⇄ tools → (transfer) → finalize → END
                                  ↘ (无工具调用) ↘

DST（对话状态追踪，教材 Ch5）在进入图之前由 LangGraphCustomerAgent 准备好：
  载入状态 → 实体抽取 → 动态上下文注入（查订单/拉候选单）→ 摘要压缩 → 滑动窗口
图内的 classify 负责「意图延续」判定，agent 负责把状态渲染进 prompt，
finalize 负责「回复质量闸门 + 状态持久化」。
"""
import json
import operator
import re
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, START, END

from app.services import dialog_state, order_store
from app.services.agent_registry import get_agent_registry
from app.services.intent_recognition import IntentRecognitionService
from app.services.tools.registry import get_tool_registry
from app.services.tools import RagKnowledgeTool
from app.services.benpingtai_persona import AGENT_PERSONA, BUSINESS_CONTEXT, FORBIDDEN_TOPICS
from app.models.agent_config import AgentConfig, AgentMessage, IntentRecord, EmotionRecord


# 工具循环最大轮次，防止 LLM 死循环调用工具
MAX_TOOL_ROUNDS = 5

# 对所有 Agent 默认开放的内置 demo 工具（订单/物流/工单/最近订单）。
# 这些 Mock 工具此前是「孤儿」：注册在 ToolRegistry 却从未暴露给 LLM，
# 导致 Agent 答非所问（如「我们不负责物流」）。现在与 rag_knowledge 一样自动挂载。
# list_recent_orders 是「客户忘了订单号」的兜底通道（教材 Ch5.2.3）。
BUILTIN_TOOL_NAMES = [
    "query_order", "list_recent_orders", "check_logistics",
    "create_ticket", "submit_refund",
]


def _extract_chunk_text(chunk) -> str:
    """从 LangChain 的 chat model stream chunk 里提取文本（兼容 str / 多模态 list）"""
    if chunk is None:
        return ""
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            else:
                parts.append(str(block))
        return "".join(parts)
    return ""


# ==================== 状态定义 ====================

class AgentState(TypedDict):
    # 消息流（OpenAI 格式）：system/user/assistant/tool
    messages: Annotated[List[Dict[str, Any]], operator.add]

    session_id: str
    user_id: Optional[str]
    user_message: str

    # 意图 / 情绪
    intent: Optional[str]
    sub_intent: Optional[str]
    intent_confidence: float
    emotion_type: Optional[str]
    emotion_intensity: int
    frustration_signals: List[str]

    # 路由
    agent_id: Optional[str]
    agent_name: Optional[str]

    # 业务
    entities: Dict[str, Any]
    order_info: Dict[str, Any]
    needs_transfer: bool
    transfer_reason: Optional[str]

    # 输出
    final_answer: Optional[str]
    sources: List[Dict[str, Any]]
    error: Optional[str]

    # 对话状态追踪（Ch5）：dst 是可变对象，全程共享同一引用
    dst: Any
    dst_context: Optional[str]

    # 透传（不进入 reducer，仅随 state 流动）
    db: Any


# ==================== 工具 schema 转换 ====================

def _tool_to_openai_schema(tool) -> Dict[str, Any]:
    """把 BaseTool 转成 OpenAI function-calling schema"""
    props = {}
    required = []
    for pname, pmeta in (tool.parameters or {}).items():
        props[pname] = {
            "type": pmeta.get("type", "string"),
            "description": pmeta.get("description", ""),
        }
        if pmeta.get("required"):
            required.append(pname)
    return {
        "type": "function",
        "function": {
            "name": tool.tool_name,
            "description": tool.description or "",
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }


def _get_llm_client():
    """复用项目统一的 LLM 客户端；Agent 编排使用 agent 板块的模型"""
    from app.services.quiz import _get_llm_client as _g
    return _g("agent")


# ==================== 共享服务（懒加载，全局唯一） ====================

_shared_intent_service: Optional[IntentRecognitionService] = None


def _get_intent_service() -> IntentRecognitionService:
    global _shared_intent_service
    if _shared_intent_service is None:
        _shared_intent_service = IntentRecognitionService(get_agent_registry())
    return _shared_intent_service


def _ensure_rag_tool():
    """确保内置 RAG 工具已注册（供 FAQ 类 Agent 绑定）"""
    tr = get_tool_registry()
    if not tr.has(RagKnowledgeTool.tool_name):
        tr.register(RagKnowledgeTool())


# ==================== 图节点（无状态，只读 state） ====================

def _classify(state: AgentState) -> Dict[str, Any]:
    """
    节点：意图识别 + 情绪检测 + 意图延续判定（教材 Ch5.3.2）

    关键修复：此前「是的，订单发错货」被关键词命中 order_status 后短路分类，
    路由到订单查询 Agent，于是又把已提供过的订单号问了一遍。
    现在先看是否属于上一轮意图的合法延续——是则不换路由，只更新子意图。
    """
    service = _get_intent_service()
    dst = state.get("dst")

    result = service.detect_intent(state["user_message"], state.get("user_id"))
    intent = result.intent
    sub_intent = result.sub_intent
    confidence = result.confidence

    if dst is not None:
        # 意图延续规则统一放在 dialog_state，两个引擎共用（deepagents 也用它）
        final_intent = dialog_state.apply_intent_continuation(
            dst, result.intent, state["user_message"])
        if final_intent != result.intent:
            intent = final_intent
            sub_intent = result.intent
            confidence = max(confidence, 0.8)
        else:
            dst.sub_intent = sub_intent
        dst.intent_confidence = confidence
        dst.phase = dst.compute_phase()

    return {
        "intent": intent,
        "sub_intent": sub_intent,
        "intent_confidence": confidence,
        "emotion_type": result.emotion_type,
        "emotion_intensity": result.emotion_intensity,
        "frustration_signals": result.frustration_signals,
        "dst_context": dst.to_context_string() if dst is not None else None,
    }


def _route(state: AgentState) -> Dict[str, Any]:
    """节点：根据意图/情绪/阶段解析目标子 Agent"""
    registry = get_agent_registry()
    dst = state.get("dst")
    agent = registry.resolve_agent(
        intent=state.get("intent"),
        emotion=state.get("emotion_type"),
        phase=getattr(dst, "phase", None),
    )
    if agent is None:
        return {"agent_id": None, "agent_name": None,
                "error": "未找到可处理的子 Agent"}
    return {"agent_id": agent.agent_id, "agent_name": agent.name}


def _load_agent_config(agent_id: Optional[str], db) -> Optional[AgentConfig]:
    if db is None or not agent_id:
        return None
    return db.query(AgentConfig).filter_by(agent_id=agent_id).first()


def _collect_tools(agent_cfg: Optional[AgentConfig]):
    """收集 Agent 可调用工具（内置 demo 工具 + RAG + 绑定的 Skill/MCP）"""
    reg = get_tool_registry()
    tools = []

    # 内置 RAG 工具 + demo 工具对所有 Agent 默认开放（缺陷1/2/4 修复：让 LLM 真正能用）
    for name in (RagKnowledgeTool.tool_name, *BUILTIN_TOOL_NAMES):
        t = reg.get(name)
        if t:
            tools.append(t)

    if agent_cfg is not None:
        sids = agent_cfg.skill_ids
        if sids:
            sids = sids if isinstance(sids, list) else json.loads(sids)
            for sid in sids:
                t = reg.get(f"skill_{sid}")
                if t:
                    tools.append(t)
        mids = agent_cfg.mcp_server_ids
        if mids:
            mids = mids if isinstance(mids, list) else json.loads(mids)
            for mid in mids:
                t = reg.get(f"mcp_{mid}")
                if t:
                    tools.append(t)
    return tools


def _build_system_prompt(state: AgentState, agent_cfg: Optional[AgentConfig]) -> str:
    """
    构造 system prompt（教材 Ch5.2.1 / Ch5.4 _build_prompt_context）

    结构：[人设+业务事实] + [DST 状态块] + [本轮意图/情绪] + [硬性规则]
    DST 状态块是本轮 prompt 的核心——客户已经说过的信息全部在这里，
    并且明确标注"禁止再问"，从结构上消除"反复问订单号"的可能。
    """
    name = state.get("agent_name") or "小助手"
    intent = state.get("intent") or "unknown"
    sub_intent = state.get("sub_intent")
    emotion = state.get("emotion_type") or "neutral"
    desc = agent_cfg.description if agent_cfg else ""
    dst = state.get("dst")
    dst_context = state.get("dst_context") or (dst.to_context_string() if dst is not None else "")

    phase = getattr(dst, "phase", "info_gathering") if dst is not None else "info_gathering"
    try:
        phase_action = dialog_state.PHASE_ACTION[dialog_state.DialogPhase(phase)]
    except Exception:
        phase_action = ""

    return (
        f"你是「本平台」的在线客服「{name}」。{AGENT_PERSONA}\n"
        f"你的职责：{desc}\n\n"
        f"## 业务事实（不得超出这个范围承诺）\n{BUSINESS_CONTEXT}\n"
        f"不属于本平台的业务：{FORBIDDEN_TOPICS}\n\n"
        f"## 本轮对话状态（系统已核实，是唯一权威，优先于你的记忆）\n{dst_context}\n\n"
        f"## 本轮识别结果\n"
        f"意图：{intent}{('（子意图：' + sub_intent + ')') if sub_intent else ''}"
        f"（置信度 {state.get('intent_confidence', 0):.2f}）\n"
        f"情绪：{emotion}（强度 {state.get('emotion_intensity', 1)}/5）\n\n"
        "## 硬性规则（违反任意一条即为严重缺陷）\n"
        "1. 【已知信息不复问】「已知信息」里列出的字段，绝不能再问；客户已经回答过的问题，"
        "禁止换一种说法再问一遍。如果本轮没有新缺失信息，就直接推进方案。\n"
        "2. 【客户记不清订单号】状态块出现「客户已表示记不清订单号」时，禁止再要订单号；"
        "直接列出候选订单请客户确认（如「是 2 号那单吗」）。没有候选时，改为请客户提供"
        "下单手机号后四位或商品名称。\n"
        "3. 【禁止展示示例单号】回复中不得出现「例如 GM2025xxxx-xxxx」这类示例/占位订单号，"
        "只能引用系统查到的真实订单号；没有真实单号就说「订单页显示的那一单」。\n"
        "4. 【代词消解】「它 / 那个 / 这单」等指代，按「已知信息」里的商品与订单理解，"
        "不要反问「您说的是哪个」。\n"
        "5. 【不确定就问口径，不要臆测】客户提到的商品/权益名称（例如「本平台」）若不在已知订单里，"
        "先确认它指的是哪笔订单或哪种资产，不要直接当成实物商品，也不要承诺退款金额。\n"
        "6. 【按阶段行动】"
        f"当前阶段 {phase}：{phase_action}\n"
        "7. 【工具优先】订单、物流、退款资格、政策、余额必须来自工具返回或状态块，"
        "不得编造金额、时效、单号、政策条款。\n"
        "8. 【共情要具体】安抚必须挂住客户的具体问题（复述订单/商品/现象），"
        "禁止只输出「抱歉让您有不愉快的体验」「请问有什么可以帮您」这类空泛话术；"
        "客户骂人时先接住情绪，再落到「哪一单、什么问题」。\n"
        "9. 【退款必须走工具】客户要求退款时，先 query_order 核实资格，符合就调用 "
        "submit_refund 发起真实受理；**没有拿到 submit_refund 返回的 RMA 受理号之前，"
        "绝不能说「已退款/已受理/受理单号是 RMA…」**，也不许自己编 RMA 号。"
        "该工具需要坐席确认，调用后若被告知等待，就告诉客户「已提交坐席确认」。\n"
        "10. 回复 2-4 句，中文，口语化；不要用「亲亲」，不要输出 JSON 或内部字段名。\n"
        "11. 【内部内容绝不外发】技能（Skill）返回的处置手册、SOP、分级定性（P0-P3）、"
        "升级阈值与升级路径、内部工具名（如 escalate_ticket、submit_refund、refund_eligible）、"
        "「话术要点」「避免」「补偿标准」「参考话术」「值班经理」等都属于内部信息；"
        "面向客户的回复里禁止出现这些字样，更不能原文或分节粘贴，只能消化成一句自然语言结论。\n"
        "12. 【单一发言】一条回复只输出一段面向客户的连贯话术；不要输出 Markdown 标题、"
        "分节编号（如「## 1）」「---」）、要点清单或任何内部推理过程。\n"
    ) + _build_rag_references(state)


def _build_rag_references(state: AgentState) -> str:
    """
    把 RAG 检索到的高质量参考话术追加到 system prompt。

    参考话术来自人工审核过的知识条目（is_verified=True），作为类似场景的沟通范例，
    供 Agent 借鉴话术风格和处理思路。检索由 _prepare_state 完成，结果存在 state["rag_refs"]。
    """
    rag_refs = state.get("rag_refs")
    if not rag_refs:
        return "\n"
    lines = ["\n## 参考话术（类似场景的优质沟通范例，仅供参考风格，不要直接复制）\n"]
    for i, ref in enumerate(rag_refs, 1):
        scene = ref.get("scene", "")
        customer_says = ref.get("customer_says", "")
        response = ref.get("recommended_response", "")
        key_points = ref.get("key_points", [])
        lines.append(f"【参考{i}】场景：{scene}")
        if customer_says:
            lines.append(f"客户说：{customer_says}")
        if response:
            lines.append(f"推荐回复：{response}")
        if key_points:
            lines.append(f"要点：{'、'.join(key_points)}")
        lines.append("")
    return "\n".join(lines)


def _build_tool_context(state: AgentState):
    """构造传给工具 execute 的上下文对象"""
    class _Ctx:
        pass
    ctx = _Ctx()
    ctx.session_id = state.get("session_id")
    ctx.user_id = state.get("user_id")
    ctx.order_info = state.get("order_info") or {}
    ctx.entities = state.get("entities") or {}
    return ctx


def _agent(state: AgentState) -> Dict[str, Any]:
    """
    节点：LLM 推理 + 工具调用决策

    把当前 Agent 绑定的工具（Skill / MCP / 内置）以 schema 暴露给 LLM。
    若 LLM 返回 tool_calls → 仅追加 assistant 消息，由 tools 节点执行。
    若没有 tool_calls → 写入 final_answer，进入收尾。
    """
    if state.get("error"):
        return {"final_answer": "抱歉，系统暂时无法处理您的请求，请稍后再试或联系人工客服。"}

    agent_id = state.get("agent_id")
    agent_cfg = _load_agent_config(agent_id, state.get("db"))

    # 1. 收集该 Agent 可用的工具
    tools = _collect_tools(agent_cfg)
    tool_schemas = [_tool_to_openai_schema(t) for t in tools]

    # 2. 构造 system prompt
    system_prompt = _build_system_prompt(state, agent_cfg)

    # 3. 组装消息
    messages = list(state["messages"])
    if not messages or messages[0].get("role") != "system":
        messages = [{"role": "system", "content": system_prompt}] + messages
    if not messages or messages[-1].get("role") != "user":
        messages.append({"role": "user", "content": state["user_message"]})

    # 4. 调用 LLM
    client, model = _get_llm_client()
    if client is None:
        return {"final_answer": "服务未配置 LLM，无法生成回复。"}

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
    }
    if tool_schemas:
        kwargs["tools"] = tool_schemas
        kwargs["tool_choice"] = "auto"

    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        return {"error": f"LLM 调用失败: {e}"}

    msg = resp.choices[0].message
    assistant_msg = {
        "role": "assistant",
        "content": msg.content or "",
    }
    if getattr(msg, "tool_calls", None):
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
        # 有工具调用：暂不写 final_answer，交给 tools 节点
        return {"messages": [assistant_msg]}
    else:
        return {"final_answer": msg.content or "", "messages": [assistant_msg]}


def _tools(state: AgentState) -> Dict[str, Any]:
    """
    节点：执行 LLM 请求的工具调用（缺陷1/2/4 的核心修复点）

    从 ToolRegistry 查找工具 → 执行 → 以 OpenAI tool 消息回填 →
    回到 _agent 节点继续推理（循环）。
    """
    last = state["messages"][-1]
    tool_calls = last.get("tool_calls") or []
    if not tool_calls:
        return {}

    reg = get_tool_registry()
    ctx = _build_tool_context(state)
    new_messages = []

    for tc in tool_calls:
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except Exception:
            args = {}

        tool = reg.get(name)
        if tool is None:
            content = json.dumps({"success": False, "error": f"未知工具: {name}"})
        else:
            try:
                r = tool.execute(args, ctx)
                content = json.dumps(r, ensure_ascii=False)
            except Exception as e:
                content = json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

        new_messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "name": name,
            "content": content,
        })

    return {"messages": new_messages}


# 显式要求人工
_EXPLICIT_HUMAN = ("人工", "真人", "转接", "客服电话", "找你们领导", "经理")
# 敏感主题（法律/监管/曝光）
_SENSITIVE = ("12315", "工商", "消协", "起诉", "律师", "曝光", "报警", "媒体")


def _evaluate_transfer(state: AgentState) -> Dict[str, Any]:
    """
    转人工决策：多信号融合打分（教材 Ch8）

    之前的缺陷：只要 intent==complaint 就转人工，结果一句「sb」也会触发转接话术，
    客户什么问题都没被解决。现在按信号累积分值，达到阈值才转。
    """
    msg = state.get("user_message") or ""
    intensity = state.get("emotion_intensity", 1)
    intent = state.get("intent")
    conf = state.get("intent_confidence", 1.0)
    dst = state.get("dst")
    score = 0
    signals = []

    if any(w in msg for w in _EXPLICIT_HUMAN):
        score += 3
        signals.append("客户显式要求人工")

    if any(w in msg for w in _SENSITIVE):
        score += 2
        signals.append("敏感主题（监管/法律/曝光）")

    if intensity >= 4:
        score += 2
        signals.append("情绪强度过高")
    elif intensity == 3:
        score += 1

    if intent == "complaint" and intensity >= 3:
        score += 1
        signals.append("投诉意图且情绪负面")

    if conf < 0.4:
        score += 1

    # 重复失败：同一意图连续 3 轮没有推进（槽位没变、阶段没前进）
    if dst is not None and dst.turn_count >= 4 and not dst.order_id and intent in (
            "refund_return", "logistics", "order_status"):
        score += 1
        signals.append("多轮未获取关键信息")

    return {
        "needs_transfer": score >= 3,
        "reason": "；".join(signals) if signals else None,
    }


def _transfer(state: AgentState) -> Dict[str, Any]:
    """节点：转人工决策"""
    decision = _evaluate_transfer(state)
    patch = {
        "needs_transfer": decision["needs_transfer"],
        "transfer_reason": decision.get("reason"),
    }
    # 只有「客户明确要人工」或「情绪爆发」才用转接话术覆盖回复；
    # 其余情况保留 LLM 的实质回复（否则客户会觉得"什么都没解决就被踢走"）。
    urgent = (
        any(w in (state.get("user_message") or "") for w in _EXPLICIT_HUMAN)
        or state.get("emotion_intensity", 1) >= 5
    )
    if decision["needs_transfer"] and urgent and not state.get("final_answer"):
        patch["final_answer"] = (
            "您的情况我已记录，正在为您转接人工客服专员处理，请稍候。"
        )
    return patch


def _persist(state: AgentState):
    """持久化意图/情绪/消息记录（按轮次累积，支持多轮上下文）"""
    db = state.get("db")
    if db is None:
        return
    sess = state["session_id"]
    try:
        from sqlalchemy import func
        max_turn = db.query(func.max(AgentMessage.turn_number)).filter_by(session_id=sess).scalar()
        next_turn = (max_turn or 0) + 1
        user_turn = next_turn
        assistant_turn = next_turn + 1

        db.add(IntentRecord(
            session_id=sess,
            turn_number=user_turn,
            user_message=state["user_message"],
            intent=state.get("intent") or "unknown",
            sub_intent=state.get("sub_intent"),
            confidence=int(state.get("intent_confidence", 0) * 100),
            emotion_type=state.get("emotion_type"),
            emotion_intensity=state.get("emotion_intensity"),
            frustration_signals=json.dumps(state.get("frustration_signals", []), ensure_ascii=False),
            routed_to_agent=state.get("agent_id"),
        ))
        db.add(EmotionRecord(
            session_id=sess,
            turn_number=user_turn,
            user_message=state["user_message"],
            emotion_type=state.get("emotion_type") or "neutral",
            intensity=state.get("emotion_intensity", 1),
            frustration_signals=json.dumps(state.get("frustration_signals", []), ensure_ascii=False),
            risk_score=state.get("emotion_intensity", 1) * 20,
        ))
        db.add(AgentMessage(
            session_id=sess,
            turn_number=user_turn,
            role="user",
            content=state["user_message"],
            intent=state.get("intent"),
            confidence=int(state.get("intent_confidence", 0) * 100),
            emotion_type=state.get("emotion_type"),
            emotion_intensity=state.get("emotion_intensity"),
            needs_transfer=state.get("needs_transfer", False),
        ))
        if state.get("final_answer"):
            db.add(AgentMessage(
                session_id=sess,
                turn_number=assistant_turn,
                role="assistant",
                content=state["final_answer"],
                needs_transfer=state.get("needs_transfer", False),
            ))
        db.commit()
    except Exception as e:
        # 持久化失败不应阻断回复
        print(f"[LangGraphAgent] 持久化失败: {e}")


# 需要强制留痕（建单）的意图：退款、投诉
AUTO_TICKET_INTENTS = ("refund_return", "complaint")


def _maybe_auto_ticket(state: AgentState) -> None:
    """
    若本轮 LLM 没有显式调用 create_ticket，但意图属于退款/投诉，
    且该会话没有同类未关闭工单，则自动建单，保证工单系统有真实留痕。

    工单摘要用 DST 做字段预填（教材 Ch7：AI 结构化抽取让坐席不用从零填单）。
    """
    db = state.get("db")
    intent = state.get("intent")
    if db is None or intent not in AUTO_TICKET_INTENTS:
        return

    dst = state.get("dst")
    # 只有「可跟进的实质问题」才建单：纯情绪宣泄（哪怕该会话里有订单号）建单
    # 只会污染工单池、浪费坐席时间。
    substantive = bool(
        (dst is not None and (dst.issue_desc or dst.refund_reason))
        or (intent == "refund_return")
        or len((state.get("user_message") or "").strip()) >= 8
    )
    if not substantive:
        return

    # LLM 本轮已调用过 create_ticket → 不重复建单
    called = any(
        m.get("role") == "tool" and m.get("name") == "create_ticket"
        for m in state.get("messages", [])
    )
    if called:
        return
    try:
        from app.services.ticket_service import (
            TicketService,
            classify_category,
            match_priority,
        )
        svc = TicketService(db)
        category = classify_category(intent, state.get("user_message", ""))

        parts = []
        if dst is not None:
            if dst.order_id:
                parts.append(f"订单号：{dst.order_id}")
            if dst.product_name:
                parts.append(f"商品：{dst.product_name}")
            if dst.refund_reason:
                parts.append(f"原因：{dst.refund_reason}")
            if dst.refund_eligible is not None:
                parts.append("退款资格：" + ("符合" if dst.refund_eligible else "不符合"))
        context = "；".join(parts)

        open_ticket = svc.get_issue_thread_ticket(state.get("session_id"), category)
        if open_ticket is not None:
            # 已有同一诉求线程的未关闭工单 → 不重复建单，但要把本轮新信息补进去
            if context:
                svc.append_context(open_ticket, context)
            # 情绪升级（如退款单跟进中客户要求投诉）→ 提升优先级并重算 SLA
            svc.escalate_priority(
                open_ticket,
                match_priority(category, state.get("emotion_intensity", 1)),
                reason=category,
            )
            return

        summary = "；".join(
            p for p in [state.get("user_message", ""), context] if p
        )

        svc.create_ticket(
            session_id=state.get("session_id"),
            intent=intent,
            summary=summary,
            category=category,
            emotion_intensity=state.get("emotion_intensity", 1),
            source="auto",
            transfer_reason=state.get("transfer_reason"),
        )
    except Exception as e:
        print(f"[LangGraphAgent] 自动建单失败: {e}")


def resolve_session_ticket(db, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    取该会话当前未关闭工单（本轮回复要告诉前端「已建单」）。

    工单可能由两条路径产生：LLM 主动调用 create_ticket，或 _maybe_auto_ticket
    兜底建单。两种情况下都要让 UI 拿到单号，否则坐席根本不知道有单。
    """
    if db is None or not session_id:
        return None
    try:
        from app.services.ticket_service import TicketService
        t = TicketService(db).get_open_ticket(session_id)
        if t is None:
            return None
        return {
            "ticket_no": t.ticket_no,
            "ticket_id": t.id,
            "category": t.category,
            "status": t.status,
            "priority": t.priority,
        }
    except Exception as e:
        print(f"[LangGraphAgent] 查询会话工单失败: {e}")
        return None


# ==================== 回复质量闸门 ====================

_ORDER_ID_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{2,5}\d{6,12}(?:-\d{2,6})?)(?![0-9A-Za-z])"
)
# 这些前缀是工单号/物流单号/受理号，不是订单号，清洗时要放过
_NON_ORDER_PREFIXES = ("TK", "ESC", "RMA", "ZTO", "SF", "JD", "YT", "STO")


def _looks_like_order_id(token: str) -> bool:
    t = token.upper()
    return not any(t.startswith(p) for p in _NON_ORDER_PREFIXES)


def _known_order_ids(state: AgentState) -> set:
    """本轮可安全引用的订单号：DST 槽位 + 客户原话 + 工具返回 + 真实存在的订单"""
    known = set()
    dst = state.get("dst")
    if dst is not None:
        if getattr(dst, "order_id", None):
            known.add(dst.order_id.upper())
        for o in getattr(dst, "recent_orders", []) or []:
            if o.get("order_id"):
                known.add(o["order_id"].upper())
    for m in state.get("messages", []):
        if m.get("role") not in ("user", "tool"):
            continue
        content = m.get("content") or ""
        for t in _ORDER_ID_TOKEN_RE.findall(content):
            known.add(t.upper())
    return known


def _is_real_order(token: str) -> bool:
    """订单库里确实存在该单号 → 允许出现在回复里"""
    try:
        return order_store.get_order(token) is not None
    except Exception:
        return False


# ==================== 内部内容外泄过滤（发送前） ====================
#
# 故障现场：投诉 Agent 调用 skill_complaint-sop 拿到整份 SOP 后，把「五步法 / P0-P3 分级 /
# 升级路径 / 内部工具名 / 话术要点」原样粘贴给客户。这类内容一旦外发，既暴露内部策略，
# 又让客户看到「坐席审批」「升级阈值」等不该知道的细节。这里做一道硬过滤：
# 检出内部特征 → 整条回复替换为基于真实状态的安全话术，绝不外发。

# 只要出现就必定是内部内容的强特征（正常客户话术里不会出现）
_INTERNAL_HARD_MARKERS = (
    "五步法", "投诉受理方案", "升级路径", "升级机制", "话术要点", "工单建议",
    "参考话术", "补偿标准", "定性分类", "内部手册", "内部处置", "内部备注",
    "escalate_ticket", "submit_refund", "refund_eligible",
    "值班经理", "高级客服组",
)


def _contains_internal_leak(text: str) -> bool:
    """判断一段回复是否混入了内部 SOP / 分级 / 工具名等不可外发内容。"""
    if not text:
        return False
    if any(m in text for m in _INTERNAL_HARD_MARKERS):
        return True
    # P0-P3 分级：单独出现可能是巧合，需与「升级/分级/情绪/优先/响应/SOP」语境同现
    if re.search(r"\bP[0-3]\b", text) and any(
        w in text for w in ("升级", "分级", "情绪", "优先", "响应", "SOP")
    ):
        return True
    # 内部手册的典型排版：Markdown 分节标题（## 一、 / ## 1) ）
    if re.search(r"(?m)^#{1,6}\s*(?:[一二三四五六七八九十]+[、.]|\d+\s*[)）.])", text):
        return True
    # 「定性：」「避免：」这类内部备注字段
    if re.search(r"(?:定性|避免)\s*[：:]", text):
        return True
    return False


def _safe_fallback_answer(state: AgentState) -> str:
    """
    内部内容被拦截后，用「系统已知的真实状态」拼一条安全、可执行的客户话术。
    不使用模型原文，避免残留泄露；同时保持对客户的确定性（订单/资格/工单）。
    """
    dst = state.get("dst")
    order_id = getattr(dst, "order_id", None) if dst is not None else None
    product = getattr(dst, "product_name", None) if dst is not None else None
    eligible = getattr(dst, "refund_eligible", None) if dst is not None else None
    ticket = resolve_session_ticket(state.get("db"), state.get("session_id"))
    ticket_no = (ticket or {}).get("ticket_no")

    parts = []
    if order_id:
        seg = f"您反馈的 {order_id} 这单我已经核实"
        if product:
            seg += f"（{product}）"
        if eligible is True:
            seg += "，权益还在、符合退款条件"
        elif eligible is False:
            seg += "，暂时不符合退款条件"
        parts.append(seg + "。")
    else:
        parts.append("您反馈的问题我已经记录下来了。")
    if ticket_no:
        parts.append(f"对商家的意见我已一并记成投诉工单（{ticket_no}）跟进。")
    parts.append("您方便时告诉我具体想怎么处理，我马上帮您推进。")
    return "".join(parts)


def _sanitize_answer(answer: str, state: AgentState) -> str:
    """
    抹掉模型自己编的/抄示例的订单号。

    典型故障：工具参数描述里带了 "例如 GM20250803-1287"，模型把示例原样写进回复，
    客户信以为真。这里只保留「客户说过 / 工具查到 / 状态里存着」的真实单号，
    并且只处理订单号形态的 token（工单号 TK…、物流单号 ZTO… 一律不动）。
    """
    if not answer:
        return answer
    # 【发送前过滤】内部内容外泄 → 直接替换为安全话术，不保留任何原文
    if _contains_internal_leak(answer):
        print("[LangGraphAgent] 检出内部内容外泄，已替换为安全话术")
        return _safe_fallback_answer(state)
    known = _known_order_ids(state)
    for token in set(_ORDER_ID_TOKEN_RE.findall(answer)):
        if token.upper() in known or not _looks_like_order_id(token):
            continue
        if _is_real_order(token):
            continue
        example_ctx = re.search(
            r"(例如|比如|示例|如)[:：]?\s*`?" + re.escape(token), answer) is not None
        paren_ctx = re.search(r"[（(][^（()）]{0,20}" + re.escape(token), answer) is not None
        if example_ctx or paren_ctx:
            # 连同括号说明一起删除，如「（例如 GM20250803-1287）」
            answer = re.sub(
                r"[（(][^（()）]{0,20}" + re.escape(token) + r"[^（()）]{0,20}[)）]", "", answer)
            answer = re.sub(
                r"(例如|比如|示例|如)[:：]?\s*`?" + re.escape(token) + r"`?",
                "您订单页显示的单号", answer)
        elif token.upper().startswith("GM"):
            answer = answer.replace(token, "该订单号")
        else:
            continue
        print(f"[LangGraphAgent] 已抹除无来源订单号: {token}")

    # 受理号同理：没有真实退款记录时，RMA 号一定是编的。
    # 客户拿着查不到的受理号去催，比"暂时没有受理号"糟得多。
    answer = _sanitize_rma_nos(answer, state)

    answer = re.sub(r"[ \t]{2,}", " ", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer)
    return answer.strip()


_RMA_RE = re.compile(r"RMA\d{8}-\d{3,4}")


def _sanitize_rma_nos(answer: str, state: AgentState) -> str:
    """只允许出现退款仓里真实存在的 RMA 号"""
    if not answer or "RMA" not in answer.upper():
        return answer
    db = state.get("db")
    session_id = state.get("session_id")
    real: set = set()
    try:
        from app.services import refund_store
        real = {n.upper() for n in refund_store.known_rma_nos(db, session_id=session_id)}
    except Exception as e:
        print(f"[LangGraphAgent] 查询退款记录失败: {e}")
        return answer

    for token in set(_RMA_RE.findall(answer)):
        if token.upper() in real:
            continue
        answer = _RMA_RE.sub("待受理", answer, count=0)
        print(f"[LangGraphAgent] 已抹除无来源受理号: {token}")
        break
    return answer


def _repair_answer(state: AgentState, answer: str, violation: str) -> Optional[str]:
    """
    低成本改写：只针对「重复询问已知信息」这类上下文断裂做一次修复。
    这是一道硬闸门——不依赖模型自觉，确保客户不会第二次被问同样的问题。
    """
    dst = state.get("dst")
    client, model = _get_llm_client()
    if client is None:
        return None
    prompt = (
        "你上一版客服回复存在缺陷：" + violation + "。\n\n"
        "【本轮系统已核实的对话状态】\n"
        + (dst.to_context_string() if dst is not None else "") + "\n\n"
        "【客户本轮消息】" + state.get("user_message", "") + "\n\n"
        "【你上一版回复】\n" + answer + "\n\n"
        "请重写这条回复，要求：\n"
        "1. 不再询问任何已列在「已知信息」里的内容；\n"
        "2. 保持原回复已经传达的方案与事实，不要新增金额、单号、时效；\n"
        "3. 若确实还需要信息，只能问「本轮缺失信息」里的一项；\n"
        "4. 2-4 句中文，直接输出回复正文。"
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=400,
        )
        new = (resp.choices[0].message.content or "").strip()
        if new and len(new) >= 8:
            print(f"[LangGraphAgent] 回复已修复：{violation}")
            return new
    except Exception as e:
        print(f"[LangGraphAgent] 回复修复失败: {e}")
    return None


def _finalize(state: AgentState) -> Dict[str, Any]:
    """
    节点：回复质量闸门（抹示例单号 / 修复重复追问）→ 状态落盘 → 自动建单 → 持久化
    """
    dst = state.get("dst")
    answer = state.get("final_answer")

    if answer:
        answer = _sanitize_answer(answer, state)
        if dst is not None:
            violation = dialog_state.needs_repair(answer, dst)
            if violation:
                repaired = _repair_answer(state, answer, violation)
                if repaired:
                    answer = _sanitize_answer(repaired, state)
            dialog_state.record_asked_slots(answer, dst)
        state["final_answer"] = answer

    if dst is not None:
        dst.phase = dst.compute_phase(suggest_transfer=state.get("needs_transfer", False))
        dialog_state.save_state(state.get("db"), dst)

    _maybe_auto_ticket(state)
    _persist(state)
    return {"final_answer": answer} if answer else {}


# ==================== 条件边 ====================

def _after_agent(state: AgentState):
    """agent 节点后的分支：有 tool_calls（且未超轮次）→ tools，否则 → transfer"""
    last = state["messages"][-1] if state["messages"] else {}
    if last.get("tool_calls"):
        tool_rounds = sum(1 for m in state["messages"] if m.get("role") == "tool")
        if tool_rounds < MAX_TOOL_ROUNDS:
            return "tools"
        # 超过最大轮次，强制收尾
        return "transfer"
    return "transfer"


def _build_compiled_graph():
    """构建并编译 StateGraph（全局只做一次）"""
    _ensure_rag_tool()
    g = StateGraph(AgentState)
    g.add_node("classify", _classify)
    g.add_node("route", _route)
    g.add_node("agent", _agent)
    g.add_node("tools", _tools)
    g.add_node("transfer", _transfer)
    g.add_node("finalize", _finalize)

    g.add_edge(START, "classify")
    g.add_edge("classify", "route")
    g.add_edge("route", "agent")
    g.add_conditional_edges("agent", _after_agent, {"tools": "tools", "transfer": "transfer"})
    g.add_edge("tools", "agent")  # 工具执行后回到 LLM
    g.add_edge("transfer", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


# 全局唯一编译图
_COMPILED_GRAPH = None


def _get_compiled_graph():
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = _build_compiled_graph()
    return _COMPILED_GRAPH


# ==================== 对外接口 ====================

# 对外暴露给 UI 的槽位（用于在聊天界面展示"当前上下文"）
_SLOT_LABELS = {
    "order_id": "订单号",
    "product_name": "商品",
    "issue_desc": "问题",
    "refund_reason": "原因",
    "refund_eligible": "退款资格",
}


def _slot_snapshot(dst) -> Dict[str, Any]:
    return {k: getattr(dst, k, None) for k in _SLOT_LABELS}


def _slot_diff(before: Dict[str, Any], dst) -> Dict[str, Any]:
    """本轮新填/变化的槽位（供前端显示"这轮记住了什么"）"""
    diff: Dict[str, Any] = {}
    for key, label in _SLOT_LABELS.items():
        now = getattr(dst, key, None)
        if now is None or now == before.get(key):
            continue
        if key == "refund_eligible":
            diff[label] = "符合" if now else "不符合"
        else:
            diff[label] = now
    return diff


def _maybe_summarize(dst, history: List[Dict[str, str]]) -> None:
    """
    对话摘要压缩（教材 Ch5.2.4 / Ch5.4 _generate_summary）

    超过 6 轮时把即将滑出窗口的历史压成 200 字摘要，既控 token 又不丢事实。
    """
    if not history or len(history) < 8:
        return
    if dst.conversation_summary and dst.turn_count % 4 != 2:
        return
    tail_keep = 6  # 最近 3 轮保留原文
    old = history[:-tail_keep] if len(history) > tail_keep else []
    if not old:
        return
    convo = "\n".join(
        f"{'客户' if m.get('role') == 'user' else '客服'}：{(m.get('content') or '')[:160]}"
        for m in old[-12:]
    )
    try:
        client, model = _get_llm_client()
        if client is None:
            return
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": (
                "把下面这段客服对话压缩成 200 字以内的摘要，"
                "必须保留：客户身份线索、订单号、商品、问题描述、已确认的决策、待解决的问题。\n\n"
                + convo
            )}],
            temperature=0.1,
            max_tokens=300,
        )
        summary = (resp.choices[0].message.content or "").strip()
        if summary:
            dst.conversation_summary = summary
    except Exception as e:
        print(f"[LangGraphAgent] 摘要生成失败: {e}")


class LangGraphCustomerAgent:
    """
    无状态 LangGraph 客服编排器。

    说明：编译图在进程内只构建一次（见 _get_compiled_graph），本实例仅作为
    调用入口；db 会话通过 process_message 的 state 透传，不缓存在实例上，
    因此可安全在多请求间复用同一实例。
    """

    def process_message(self, message: str, session_id: str,
                        user_id: Optional[str] = None,
                        history: Optional[List[Dict[str, str]]] = None,
                        db=None) -> Dict[str, Any]:
        """
        处理单条用户消息，返回结构化结果

        DST 管道（顺序严格按教材 Ch5.4）：
          1. 载入历史状态  → 2. 实体抽取  → 3. 动态上下文注入
          → 4. 摘要压缩（>6 轮）→ 5. 滑动窗口拼装 → 6. 进入图生成
        """
        # ---- 1. 载入 DST ----
        dst = dialog_state.load_state(db, session_id)
        dst.turn_count = (dst.turn_count or 0) + 1
        if user_id:
            dst.user_id = user_id
        if not dst.order_count:
            dst.order_count = len(order_store.list_recent_orders(dst.user_id))
        before = _slot_snapshot(dst)

        # ---- 2. 实体抽取（规则为主，LLM 兜底）----
        dialog_state.extract_entities(message, dst)
        if not dst.order_id and not (dst.refund_reason or dst.issue_desc):
            dialog_state.llm_extract_entities(message, dst)

        # ---- 3. 动态上下文注入（查订单 / 拉候选单）----
        dialog_state.enrich_order_context(dst)

        # ---- 4. 摘要压缩 + 5. 滑动窗口 ----
        raw_history = history or []
        if dst.turn_count >= 6:
            _maybe_summarize(dst, raw_history)
        windowed = dialog_state.trim_history(raw_history, dst.current_intent)

        init_messages = [
            {"role": h.get("role"), "content": h.get("content", "")}
            for h in windowed
        ]
        init_messages.append({"role": "user", "content": message})

        state = AgentState(
            messages=init_messages,
            session_id=session_id,
            user_id=user_id,
            user_message=message,
            intent=dst.current_intent,
            sub_intent=dst.sub_intent,
            intent_confidence=dst.intent_confidence,
            emotion_type=None,
            emotion_intensity=1,
            frustration_signals=[],
            agent_id=None,
            agent_name=None,
            entities={},
            order_info=dst.order_snapshot or {},
            needs_transfer=False,
            transfer_reason=None,
            final_answer=None,
            sources=[],
            error=None,
            dst=dst,
            dst_context=dst.to_context_string(),
            db=db,
        )

        result = _get_compiled_graph().invoke(state)

        ticket = resolve_session_ticket(db, session_id)

        return {
            "answer": result.get("final_answer") or "（无有效回复）",
            "intent": result.get("intent"),
            "confidence": result.get("intent_confidence", 0.0),
            "emotion": result.get("emotion_type"),
            "emotion_intensity": result.get("emotion_intensity", 1),
            "agent_name": result.get("agent_name"),
            "agent_id": result.get("agent_id"),
            "needs_transfer": result.get("needs_transfer", False),
            "transfer_reason": result.get("transfer_reason"),
            "error": result.get("error"),
            "dialog_state": dst.to_dict(),
            "updated_entities": _slot_diff(before, dst),
            "updated_phase": dst.phase,
            "ticket": ticket,
            "ticket_no": (ticket or {}).get("ticket_no"),
            "engine": "langgraph",
        }

    # ============ 真·流式（SSE 逐 token 推送） ============
    async def process_message_stream(self, *, message, session_id, user_id=None,
                                     history=None, db=None):
        """
        真流式处理：DST 预处理 → 先推 metadata → 编译图 astream_events 逐 token 推送
        → 收尾（图内部已含质检/转人工/落库）→ 推 answer + done。

        任何异常自动回退到非流式 process_message，保证一定有正确回复。
        """
        # ---- 1~5：DST 管道（与 process_message 一致）----
        dst = dialog_state.load_state(db, session_id)
        dst.turn_count = (dst.turn_count or 0) + 1
        if user_id:
            dst.user_id = user_id
        if not dst.order_count:
            dst.order_count = len(order_store.list_recent_orders(dst.user_id))
        before = _slot_snapshot(dst)

        dialog_state.extract_entities(message, dst)
        if not dst.order_id and not (dst.refund_reason or dst.issue_desc):
            dialog_state.llm_extract_entities(message, dst)
        dialog_state.enrich_order_context(dst)

        raw_history = history or []
        if dst.turn_count >= 6:
            _maybe_summarize(dst, raw_history)
        windowed = dialog_state.trim_history(raw_history, dst.current_intent)

        init_messages = [
            {"role": h.get("role"), "content": h.get("content", "")} for h in windowed
        ]
        init_messages.append({"role": "user", "content": message})

        state = AgentState(
            messages=init_messages,
            session_id=session_id,
            user_id=user_id,
            user_message=message,
            intent=dst.current_intent,
            sub_intent=dst.sub_intent,
            intent_confidence=dst.intent_confidence,
            emotion_type=None,
            emotion_intensity=1,
            frustration_signals=[],
            agent_id=None,
            agent_name=None,
            entities={},
            order_info=dst.order_snapshot or {},
            needs_transfer=False,
            transfer_reason=None,
            final_answer=None,
            sources=[],
            error=None,
            dst=dst,
            dst_context=dst.to_context_string(),
            db=db,
        )

        yield {
            "type": "metadata",
            "intent": dst.current_intent,
            "confidence": round(dst.intent_confidence or 0.0, 4),
            "emotion": None,
            "emotion_intensity": 1,
            "agent": None,
            "phase": dst.phase,
            "slots": _slot_diff(before, dst) or {},
            "engine": "langgraph",
        }

        streamed_any = False
        suppress_tokens = False
        streamed_acc = ""
        try:
            graph = _get_compiled_graph()
            config = {"configurable": {"thread_id": f"{session_id}:t{dst.turn_count}"}}
            final_state = None
            async for ev in graph.astream_events(state, config, version="v2"):
                ev_type = ev.get("event")
                if ev_type == "on_chat_model_stream":
                    content = _extract_chunk_text(ev.get("data", {}).get("chunk"))
                    if content:
                        streamed_any = True
                        if not suppress_tokens:
                            streamed_acc += content
                            if _contains_internal_leak(streamed_acc):
                                suppress_tokens = True
                                print("[LangGraph] 流式检出内部内容外泄，已停止继续下发")
                            else:
                                yield {"type": "token", "content": content}
                elif ev_type == "on_graph_end":
                    final_state = ev.get("data", {}).get("output")

            if final_state is None:
                final_state = graph.invoke(state, config)

            answer = (final_state or {}).get("final_answer") or ""
            ticket = resolve_session_ticket(db, session_id)
            yield {"type": "answer", "content": answer or "（无有效回复）", "agent": (final_state or {}).get("agent_name")}
            yield {
                "type": "done",
                "needs_transfer": (final_state or {}).get("needs_transfer", False),
                "signals": [],
                "agent": (final_state or {}).get("agent_name"),
                "ticket_no": (ticket or {}).get("ticket_no"),
                "ticket": ticket,
                "pending_approval": False,
                "pending": None,
            }
        except Exception as e:
            import traceback
            print(f"[LangGraph] stream 失败: {e}\n{traceback.format_exc()}")
            if not streamed_any:
                # 早期失败（尚未推任何 token）→ 回退非流式，保证一定有回复
                try:
                    result = self.process_message(
                        message=message, session_id=session_id, user_id=user_id,
                        history=history, db=db,
                    )
                    yield {"type": "answer", "content": result.get("answer", ""), "agent": result.get("agent_name")}
                    yield {
                        "type": "done",
                        "needs_transfer": result.get("needs_transfer", False),
                        "signals": [],
                        "agent": result.get("agent_name"),
                        "ticket_no": result.get("ticket_no"),
                        "ticket": result.get("ticket"),
                        "pending_approval": bool(result.get("pending_approval")),
                        "pending": result.get("pending"),
                    }
                    return
                except Exception as e2:
                    yield {"type": "error", "message": f"生成异常: {e2}"}
                    return
            yield {"type": "error", "message": f"流式中止: {e}"}


# 全局入口（无状态，可安全复用）
_lg_agent: Optional[LangGraphCustomerAgent] = None


def get_langgraph_agent(db=None) -> LangGraphCustomerAgent:
    """返回 LangGraph 客服 Agent 单例（db 不在此缓存，经 state 透传）"""
    global _lg_agent
    if _lg_agent is None:
        _lg_agent = LangGraphCustomerAgent()
    return _lg_agent
