# -*- coding: utf-8 -*-
"""
deepagents 版客服 Agent 编排

为什么换：原来的 LangGraph 版是「手写状态机」——classify → route → agent ⇄ tools →
transfer → finalize 全靠自己拼。deepagents 把这一层抽象成「带规划与子代理的深度
Agent」：

  - planning：TodoListMiddleware 提供 write_todos，多步任务先列计划
  - subagents：本项目的 4 个客服子 Agent 直接映射成 deepagents 的 subagents，
    主 Agent 通过 task 工具委派（比我们自己 if/else 路由更贴近真实 Agent 协作）
  - filesystem：deepagents 默认带文件工具；客服场景不需要写盘，这里只保留
    只读的 ls/read_file，禁掉 write/edit/execute（避免模型"把结论写进文件"）

保持不变的是「对话状态追踪（DST）」这条管道：载状态 → 抽实体 → 动态注入 →
意图延续 → 滑动窗口/摘要 → 生成 → 质量闸门 → 落盘。deepagents 只负责"生成"
这一段，前后处理与 LangGraph 版共用同一份实现，避免两个引擎行为漂移。

外部契约与 langgraph_agent.LangGraphCustomerAgent.process_message 完全一致，
路由层可以用 AGENT_ENGINE 环境变量在两者之间切换。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field, create_model

from deepagents import create_deep_agent
from deepagents.middleware.filesystem import FilesystemMiddleware

from app.services import dialog_state, order_store
from app.services.agent_registry import get_agent_registry
from app.services.xiaocan_persona import BUSINESS_CONTEXT, FORBIDDEN_TOPICS
from app.models.agent_config import AgentConfig

# 复用 LangGraph 版的「prompt 规则 / 质量闸门 / 落盘 / 建单」实现——
# 这些是与引擎无关的业务规则，两套引擎必须完全一致。
from app.services.langgraph_agent import (
    _build_system_prompt,
    _build_tool_context,
    _collect_tools,
    _evaluate_transfer,
    _load_agent_config,
    _maybe_auto_ticket,
    _maybe_summarize,
    _persist,
    _repair_answer,
    _sanitize_answer,
    _slot_diff,
    _slot_snapshot,
    _get_intent_service,
    resolve_session_ticket,
)


# 需要"先规划再执行"的意图：多步业务流，值一次 write_todos
MULTI_STEP_INTENTS = {"refund_return", "complaint", "logistics"}

# 允许暴露给模型的文件工具（只读；客服不需要写盘，更不能执行 shell）
READONLY_FS_TOOLS = ["ls", "read_file"]

# ==================== 人在环（HITL）：哪些动作必须先问人 ====================
#
# 判定标准不是"写操作"，而是「不可逆 + 对外承诺 + 动钱」：
#   query_order / list_recent_orders / check_logistics / rag_knowledge → 只读，直接放行
#   create_ticket            → 可逆，工单本来就是给人看的队列，AI 建单不越权
#   submit_refund            → 真动钱、真出受理号 → 必须坐席确认
#
# 注意：不要用 interrupt 做"多轮追问"，那是 DST 的职责（教材 Ch5）；
# interrupt 只回答一个问题：「这个动作现在能不能执行」。
HITL_TOOLS = {
    "submit_refund": {
        "allowed_decisions": ["approve", "reject"],
        "description": "退款受理（不可逆资金动作）",
    }
}


def _refund_needs_approval(request) -> bool:
    """
    条件拦截：只有「真的会动钱」的调用才停。

    不符合退款条件的订单（如已核销的券），工具本身会返回拒绝原因——
    这种没必要惊动坐席，让它直接执行、由模型解释即可。
    判断不出来时倾向于拦（宁可多问一句，不可擅自退钱）。
    """
    try:
        call = getattr(request, "tool_call", None) or {}
        args = (call.get("args") if isinstance(call, dict) else None) or {}
        order = order_store.get_order(str(args.get("order_id") or ""))
        if not order:
            return True
        return bool(order_store.evaluate_refund(order).get("eligible"))
    except Exception:
        return True


def _hitl_enabled() -> bool:
    """DEEPAGENTS_HITL=0 可关闭审批（用于对照演示"不拦会怎样"）"""
    env = os.getenv("DEEPAGENTS_HITL", "").strip().lower()
    return env not in ("0", "false", "off")


# ==================== 持久化 checkpointer ====================
#
# 停下来的图存在 checkpointer 里，靠 thread_id 索引。坐席可能是两小时后、
# 甚至在服务重启之后才点确认，所以必须落 Postgres——内存版只能撑到进程退出。
_CHECKPOINTER = None
_CHECKPOINTER_CM = None   # 连接上下文必须保活，否则连接被关掉


def get_checkpointer():
    global _CHECKPOINTER, _CHECKPOINTER_CM
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER
    try:
        from app.config import get_settings
        from langgraph.checkpoint.postgres import PostgresSaver

        url = get_settings().database_url
        # from_conn_string 返回的是上下文管理器，必须 enter 并保持引用
        _CHECKPOINTER_CM = PostgresSaver.from_conn_string(url)
        saver = _CHECKPOINTER_CM.__enter__()
        saver.setup()
        _CHECKPOINTER = saver
        print("[DeepAgent] checkpointer = PostgresSaver（挂起状态可跨进程恢复）")
    except Exception as e:
        from langgraph.checkpoint.memory import InMemorySaver

        _CHECKPOINTER = InMemorySaver()
        print(f"[DeepAgent] checkpointer = InMemorySaver（{type(e).__name__}: {e}）")
    return _CHECKPOINTER


# ==================== 模型 ====================

def _get_chat_model(temperature: float = 0.3):
    """
    把项目统一的 DeepSeek 客户端配置转成 LangChain ChatModel。

    注意：deepagents 内部走 LangChain 的 tool-calling，不能用裸 openai.OpenAI。
    base_url 指向 DeepSeek 的 OpenAI 兼容端点，因此必须显式关掉 responses API，
    否则 langchain-openai 会按 OpenAI 官方端点发请求。
    """
    from app.config import get_settings
    from langchain_openai import ChatOpenAI

    s = get_settings()
    if s.deepseek_api_key:
        return ChatOpenAI(
            model="deepseek-chat",
            api_key=s.deepseek_api_key,
            base_url=s.deepseek_base_url,
            temperature=temperature,
            timeout=90,
            max_retries=1,
            use_responses_api=False,
        )
    if s.openai_api_key:
        return ChatOpenAI(
            model="gpt-4o-mini",
            api_key=s.openai_api_key,
            base_url=s.openai_base_url,
            temperature=temperature,
            timeout=90,
            max_retries=1,
        )
    return None


# ==================== 工具适配：项目 BaseTool → LangChain Tool ====================

_PY_TYPES = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _args_schema(tool) -> type:
    """用工具的 JSON-Schema 参数描述动态生成 pydantic 模型（LangChain 需要 schema）"""
    fields: Dict[str, Any] = {}
    for name, meta in (tool.parameters or {}).items():
        py_type = _PY_TYPES.get(meta.get("type", "string"), str)
        desc = meta.get("description", "")
        if meta.get("required"):
            fields[name] = (py_type, Field(..., description=desc))
        else:
            fields[name] = (Optional[py_type], Field(default=None, description=desc))
    safe_name = f"{tool.tool_name}_args".replace("-", "_")
    return create_model(safe_name, **fields)


def _to_lc_tool(tool, ctx):
    """
    把 BaseTool 包成 StructuredTool。

    工具执行用的 ctx（session_id / user_id / entities）按请求注入，
    而不是让模型"传会话信息"——模型不该知道也不需要知道 session_id。
    """

    def _run(**kwargs) -> str:
        params = {k: v for k, v in kwargs.items() if v is not None}
        try:
            result = tool.execute(params, ctx)
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:  # 工具异常不能让整个 Agent 崩掉
            return json.dumps({"success": False, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)

    return _lc_structured_tool(
        _run,
        name=tool.tool_name,
        description=tool.description or tool.tool_name,
        args_schema=_args_schema(tool),
    )


def _lc_structured_tool(fn, **kwargs):
    from langchain_core.tools import StructuredTool
    return StructuredTool.from_function(func=fn, **kwargs)


# ==================== 子代理 ====================

def _subagent_prompt(agent, desc: str) -> str:
    return (
        f"你是「小蚕惠生活」的客服子代理「{agent.name}」。\n"
        f"职责：{desc or agent.name}\n\n"
        f"## 业务事实（不得超出范围承诺）\n{BUSINESS_CONTEXT}\n"
        f"不属于本平台：{FORBIDDEN_TOPICS}\n\n"
        "## 规则\n"
        "1. 订单、物流、退款资格、政策、余额必须来自工具返回，不得编造。\n"
        "2. 客户已经提供过的信息不要重复询问；缺失信息一次只问一项。\n"
        "3. 回复 2-4 句中文，口语化，不要用「亲亲」。\n"
    )


def _build_subagents(main_agent_id: Optional[str], db) -> List[Dict[str, Any]]:
    """
    把除主 Agent 之外的客服子 Agent 暴露成 deepagents 子代理。

    主 Agent 判断「这活儿不归我」时，用 task(task_name) 委派，而不是硬编码 if/else。
    """
    subs: List[Dict[str, Any]] = []
    for agent in get_agent_registry().list_all():
        if agent.agent_id == main_agent_id:
            continue
        cfg = _load_agent_config(agent.agent_id, db)
        tools = _collect_tools(cfg)
        subs.append({
            "name": agent.agent_id,
            "description": agent.description or agent.name,
            "system_prompt": _subagent_prompt(agent, agent.description),
            "tools": tools,
        })
    return subs


# ==================== 结果解析 ====================

def _last_ai_text(messages) -> str:
    """取最后一条不带 tool_calls 的 AI 文本回复"""
    for m in reversed(list(messages or [])):
        if getattr(m, "type", "") != "ai":
            continue
        if getattr(m, "tool_calls", None):
            continue
        content = getattr(m, "content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", ""))
                else:
                    parts.append(str(block))
            text = "".join(parts).strip()
            if text:
                return text
    return ""


def _tool_names_called(messages) -> List[str]:
    names = []
    for m in messages or []:
        if getattr(m, "type", "") == "tool":
            n = getattr(m, "name", None)
            if n:
                names.append(n)
    return names


def _split_result(result):
    """
    兼容两种返回形态：
    - 普通 invoke → dict，中断信息在 `__interrupt__`
    - version="v2" → GraphOutput，中断信息在 `.interrupts`
    """
    value = result if isinstance(result, dict) else (getattr(result, "value", None) or {})
    interrupts = getattr(result, "interrupts", None)
    if not interrupts and isinstance(result, dict):
        interrupts = result.get("__interrupt__") or ()
    return value, list(interrupts or ())


def _find_rma_in_messages(messages) -> Optional[str]:
    """从工具返回里捞真实受理号（RMAxxxxxxxx-xxxx）"""
    import re

    pat = re.compile(r"RMA\d{8}-\d{3,4}")
    for m in messages or []:
        if getattr(m, "type", "") != "tool":
            continue
        content = getattr(m, "content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, default=str)
        hit = pat.search(content)
        if hit:
            return hit.group(0)
    return None


# ==================== 编排器 ====================

class DeepAgentCustomerAgent:
    """
    deepagents 版客服编排器（无状态，可复用）

    每轮按「路由到的子 Agent」构建一次主 Agent：工具集 = 该 Agent 绑定的
    Skill/MCP/内置工具；其余子 Agent 作为 subagents 供 task 委派。
    构建耗时约 80ms，相对 LLM 生成可忽略，因此不做缓存——避免状态/prompt 串味。
    """

    def process_message(self, message: str, session_id: str,
                        user_id: Optional[str] = None,
                        history: Optional[List[Dict[str, str]]] = None,
                        db=None) -> Dict[str, Any]:
        # ---- 1~5：与 LangGraph 版完全一致的 DST 管道 ----
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

        service = _get_intent_service()
        intent_result = service.detect_intent(message, user_id)
        final_intent = dialog_state.apply_intent_continuation(dst, intent_result.intent, message)
        if final_intent != intent_result.intent:
            dst.sub_intent = intent_result.intent
            intent_confidence = max(intent_result.confidence, 0.8)
        else:
            dst.sub_intent = intent_result.sub_intent
            intent_confidence = intent_result.confidence
        dst.intent_confidence = intent_confidence
        dst.phase = dst.compute_phase()

        raw_history = history or []
        if dst.turn_count >= 6:
            _maybe_summarize(dst, raw_history)
        windowed = dialog_state.trim_history(raw_history, dst.current_intent)

        # ---- 路由：仍由意图决定主 Agent（可解释、可测试）----
        registry = get_agent_registry()
        routed = registry.resolve_agent(
            intent=dst.current_intent,
            emotion=intent_result.emotion_type,
            phase=dst.phase,
        )
        agent_id = routed.agent_id if routed else None
        agent_cfg = _load_agent_config(agent_id, db)

        state: Dict[str, Any] = {
            "session_id": session_id,
            # 每轮一个 thread：checkpoint 只服务「本轮可能被挂起」的场景。
            # 若整会话共用一个 thread，每轮又把历史重放进去，历史会在 checkpoint 里
            # 越滚越多；按轮隔离才能既支持 resume、又不破坏滑动窗口。
            "thread_id": f"{session_id}:t{dst.turn_count}",
            "user_id": user_id,
            "user_message": message,
            "intent": dst.current_intent,
            "sub_intent": dst.sub_intent,
            "intent_confidence": intent_confidence,
            "emotion_type": intent_result.emotion_type,
            "emotion_intensity": intent_result.emotion_intensity,
            "agent_id": agent_id,
            "agent_name": routed.name if routed else None,
            "entities": {},
            "order_info": dst.order_snapshot or {},
            "needs_transfer": False,
            "transfer_reason": None,
            "final_answer": None,
            "dst": dst,
            "dst_context": dst.to_context_string(),
            "db": db,
        }

        # ---- 6：deepagents 生成（可能停在审批点）----
        try:
            answer, called_tools, interrupts = self._invoke(
                message=message,
                windowed=windowed,
                state=state,
                agent_cfg=agent_cfg,
                agent_id=agent_id,
                db=db,
            )
        except Exception as e:
            print(f"[DeepAgent] 生成失败，回退 LangGraph 引擎: {type(e).__name__}: {e}")
            from app.services.langgraph_agent import get_langgraph_agent
            return get_langgraph_agent().process_message(
                message=message, session_id=session_id, user_id=user_id,
                history=history, db=db,
            )

        # ---- 6.5：被审批闸门拦下 → 挂起到工单，等坐席确认后再 resume ----
        if interrupts:
            return self._pause_for_approval(
                db=db, state=state, dst=dst, interrupts=interrupts,
                agent_id=agent_id, session_id=session_id, before=before,
            )

        # ---- 7：质量闸门 → 转人工 → 建单 → 落盘（与 LangGraph 版同一套）----
        state["messages"] = [{"role": "tool", "name": n} for n in called_tools]
        answer = _sanitize_answer(answer, state)
        violation = dialog_state.needs_repair(answer, dst)
        if violation:
            repaired = _repair_answer(state, answer, violation)
            if repaired:
                answer = _sanitize_answer(repaired, state)
        dialog_state.record_asked_slots(answer, dst)

        transfer = _evaluate_transfer(state)
        state["needs_transfer"] = transfer["needs_transfer"]
        state["transfer_reason"] = transfer.get("reason")
        state["final_answer"] = answer

        dst.phase = dst.compute_phase(suggest_transfer=state["needs_transfer"])
        dialog_state.save_state(db, dst)

        _maybe_auto_ticket(state)
        _persist(state)

        ticket = resolve_session_ticket(db, session_id)

        return {
            "answer": answer or "（无有效回复）",
            "intent": dst.current_intent,
            "confidence": intent_confidence,
            "emotion": intent_result.emotion_type,
            "emotion_intensity": intent_result.emotion_intensity,
            "agent_name": (routed.name if routed else None) or "智能客服助手",
            "agent_id": agent_id,
            "needs_transfer": state["needs_transfer"],
            "transfer_reason": state.get("transfer_reason"),
            "error": None,
            "dialog_state": dst.to_dict(),
            "updated_entities": _slot_diff(before, dst),
            "updated_phase": dst.phase,
            "ticket": ticket,
            "ticket_no": (ticket or {}).get("ticket_no"),
            "engine": "deepagents",
        }

    # ---------- 构建图（process / resume 共用同一份构建逻辑） ----------
    def _build_graph(self, *, state: Dict[str, Any], agent_cfg: Optional[AgentConfig],
                     agent_id: Optional[str], db):
        model = _get_chat_model()
        if model is None:
            raise RuntimeError("未配置 LLM（deepseek/openai api key 缺失）")

        ctx = _build_tool_context(state)
        main_tools = [_to_lc_tool(t, ctx) for t in _collect_tools(agent_cfg)]

        subagents = []
        for spec in _build_subagents(agent_id, db):
            subagents.append({
                **spec,
                "tools": [_to_lc_tool(t, ctx) for t in spec.get("tools", [])],
            })

        system_prompt = _build_system_prompt(state, agent_cfg)
        system_prompt += self._deep_agent_addendum(state, subagents)

        middleware = [FilesystemMiddleware(tools=READONLY_FS_TOOLS)]
        if self._todos_enabled(state.get("intent")):
            try:
                from langchain.agents.middleware import TodoListMiddleware
                middleware.append(TodoListMiddleware())
            except Exception as e:
                print(f"[DeepAgent] 规划中间件不可用，跳过: {e}")

        hitl = self._hitl_middleware()
        if hitl is not None:
            middleware.append(hitl)

        return create_deep_agent(
            model=model,
            tools=main_tools,
            system_prompt=system_prompt,
            subagents=subagents or None,
            middleware=middleware,
            checkpointer=get_checkpointer(),
            name=f"xiaocan_cs_{agent_id or 'default'}",
        )

    @staticmethod
    def _hitl_middleware():
        """
        给不可逆动作挂审批闸门。

        用了 `when` 做条件拦截——不是每次调 submit_refund 都惊动坐席，
        只有「这单真的符合退款条件」时才停（不符合的让它直接返回拒绝原因）。
        """
        if not _hitl_enabled():
            return None
        try:
            from langchain.agents.middleware import HumanInTheLoopMiddleware
        except Exception as e:
            print(f"[DeepAgent] HITL 中间件不可用，敏感动作不拦截: {e}")
            return None

        interrupt_on: Dict[str, Any] = {}
        for name, spec in HITL_TOOLS.items():
            conf: Dict[str, Any] = {"allowed_decisions": list(spec["allowed_decisions"])}
            if spec.get("description"):
                conf["description"] = spec["description"]
            if name == "submit_refund":
                conf["when"] = _refund_needs_approval
            interrupt_on[name] = conf
        return HumanInTheLoopMiddleware(
            interrupt_on=interrupt_on,
            description_prefix="该动作需要坐席确认后才能执行",
        )

    # ---------- deepagents 调用 ----------
    def _invoke(self, *, message: str, windowed: List[Dict[str, str]],
                state: Dict[str, Any], agent_cfg: Optional[AgentConfig],
                agent_id: Optional[str], db):
        graph = self._build_graph(state=state, agent_cfg=agent_cfg, agent_id=agent_id, db=db)

        messages: List[Dict[str, str]] = [
            {"role": h.get("role"), "content": h.get("content", "")}
            for h in windowed
        ]
        messages.append({"role": "user", "content": message})

        # thread_id 按「会话+轮次」隔离：同一轮可以反复 resume，跨轮互不污染
        config = {"configurable": {"thread_id": state.get("thread_id") or state["session_id"]}}
        result = graph.invoke({"messages": messages}, config)
        value, interrupts = _split_result(result)
        out = value.get("messages", [])
        return _last_ai_text(out), _tool_names_called(out), interrupts

    # ---------- 挂起：等待坐席确认 ----------
    def _pause_for_approval(self, *, db, state: Dict[str, Any], dst, interrupts: List[Any],
                            agent_id: Optional[str], session_id: str,
                            before: Dict[str, Any]) -> Dict[str, Any]:
        """
        图停在审批点 → 把「待批条」落到工单上，并给客户一句确定性回复。

        这里**不能**用模型原文：模型在被中断前往往已经说了「我这就帮您提交」，
        客户会以为退款已受理。话术必须由系统按真实状态生成。
        """
        it = interrupts[0]
        payload = getattr(it, "value", None) or {}
        action = (payload.get("action_requests") or [{}])[0]
        args = action.get("args") or {}
        order_id = str(args.get("order_id") or dst.order_id or "")
        order = order_store.get_order(order_id) or {}
        amount = order.get("amount") or 0
        product = order.get("product_name") or dst.product_name or "该订单"
        reason = args.get("reason") or dst.refund_reason or "客户申请退款"

        thread_id = state.get("thread_id") or state["session_id"]
        pending = {
            "awaiting": True,
            "type": "tool_approval",
            "tool": action.get("name") or "submit_refund",
            "title": f"发起退款：{order_id}（{product}）¥{amount}",
            "args": args,
            "reason": reason,
            "order_id": order_id,
            "amount": float(amount or 0),
            "thread_id": thread_id,
            "interrupt_id": getattr(it, "id", None),
            "session_id": session_id,
            "agent_id": agent_id,
            "requested_at": datetime.utcnow().isoformat(),
            "allowed_decisions": (payload.get("review_configs") or [{}])[0].get("allowed_decisions")
            or ["approve", "reject"],
        }

        answer = (
            f"退款单我已经填好了：{order_id}（{product}）¥{amount}，原因「{reason}」。"
            "因为涉及资金，要坐席确认后才会真正提交，确认完我马上把受理号发您，"
            "一般 1 个工作日内出审核结果。"
        )

        state["final_answer"] = answer
        dialog_state.save_state(db, dst)
        _persist(state)

        ticket = self._attach_pending_to_ticket(
            db, session_id=session_id, dst=dst, pending=pending,
            intent=state.get("intent"),
        )

        return {
            "answer": answer,
            "intent": dst.current_intent,
            "confidence": state.get("intent_confidence", 0.0),
            "emotion": state.get("emotion_type"),
            "emotion_intensity": state.get("emotion_intensity", 1),
            "agent_name": state.get("agent_name") or "智能客服助手",
            "agent_id": agent_id,
            "needs_transfer": False,
            "transfer_reason": None,
            "error": None,
            "dialog_state": dst.to_dict(),
            "updated_entities": _slot_diff(before, dst),
            "updated_phase": dst.phase,
            "ticket": ticket,
            "ticket_no": (ticket or {}).get("ticket_no"),
            "pending_approval": True,
            "pending": pending,
            "engine": "deepagents",
        }

    @staticmethod
    def _attach_pending_to_ticket(db, *, session_id: str, dst, pending: Dict[str, Any],
                                  intent: Optional[str]) -> Optional[Dict[str, Any]]:
        """把待批动作挂到该会话的退款工单上（没有就建一张）"""
        from app.services.ticket_service import TicketService, classify_category

        if db is None:
            return None
        try:
            svc = TicketService(db)
            category = classify_category(intent or "refund_return", "退款")
            ticket = svc.get_issue_thread_ticket(session_id, category)
            if ticket is None:
                ticket = svc.create_ticket(
                    session_id=session_id,
                    intent=intent or "refund_return",
                    summary=pending.get("title") or "退款受理待确认",
                    category=category,
                    emotion_intensity=1,
                    source="auto",
                )
            svc.set_pending_action(ticket, pending)
            return ticket.to_dict()
        except Exception as e:
            print(f"[DeepAgent] 挂待批动作到工单失败: {e}")
            return None

    # ---------- 恢复：坐席确认后续跑 ----------
    def resume_pending(self, db, ticket, *, decision: str, operator: str = "human",
                       message: str = "") -> Dict[str, Any]:
        """
        坐席在工单页点「批准/驳回」→ 用同一个 thread_id 把图拉起来接着跑。

        要点：
        - `Command(resume=...)` 必须配同一 thread_id，否则是在开新对话而不是续跑
        - 幂等：已决策的工单再点一次，直接返回上次结果，绝不重复执行资金动作
        """
        from langgraph.types import Command

        pa = dict(ticket.pending_action or {})
        if not pa.get("awaiting"):
            return {
                "status": "already_decided",
                "decision": pa.get("decision"),
                "result": pa.get("result"),
                "message": "这个动作已经处理过了",
            }

        thread_id = pa.get("thread_id") or ticket.session_id
        agent_id = pa.get("agent_id")

        dst = dialog_state.load_state(db, ticket.session_id)
        state: Dict[str, Any] = {
            "session_id": ticket.session_id,
            "user_id": dst.user_id,
            "user_message": pa.get("title") or "",
            "intent": dst.current_intent or "refund_return",
            "sub_intent": dst.sub_intent,
            "emotion_type": None,
            "emotion_intensity": 1,
            "agent_id": agent_id,
            "agent_name": None,
            "entities": {},
            "order_info": dst.order_snapshot or {},
            "needs_transfer": False,
            "final_answer": None,
            "dst": dst,
            "dst_context": dst.to_context_string(),
            "db": db,
        }
        graph = self._build_graph(
            state=state,
            agent_cfg=_load_agent_config(agent_id, db),
            agent_id=agent_id,
            db=db,
        )
        dec = {"type": "approve"} if decision == "approve" else {
            "type": "reject",
            "message": message or "坐席驳回该操作",
        }
        config = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(Command(resume={"decisions": [dec]}), config)
        value, interrupts = _split_result(result)
        out = value.get("messages", [])
        answer = _last_ai_text(out)
        tools = _tool_names_called(out)

        # 真实受理号只从「工具返回 / 退款仓」取，不信模型自述
        rma_no = _find_rma_in_messages(out)
        if not rma_no:
            from app.services import refund_store as _rs
            rows = _rs.list_refunds(db, session_id=ticket.session_id, limit=1)
            if rows:
                rma_no = rows[0].get("rma_no")

        outcome = {
            "rma_no": rma_no,
            "answer": answer,
            "tools": tools,
            "still_interrupted": bool(interrupts),
        }

        from app.services.ticket_service import TicketService
        svc = TicketService(db)
        svc.resolve_pending(ticket, decision=decision, operator=operator, result=outcome)

        if decision == "approve" and rma_no:
            svc.add_event(
                ticket.id,
                f"退款已受理，受理号 {rma_no}（{pa.get('title')}）",
                event_type="comment",
                operator=operator,
            )

        # 续跑产生的话术要写回会话消息表：客户回到聊天页才能看到
        # 「退款已受理 RMA…」。checkpoint 里的 t1 存档只有图自己能读，
        # 不落 agent_messages 的话，这段回复对客户就是不可见的。
        if answer:
            self._persist_resume_message(db, session_id=ticket.session_id, answer=answer)

        return {
            "status": "executed" if decision == "approve" else "rejected",
            "decision": decision,
            "rma_no": rma_no,
            "answer": answer,
            "tools": tools,
            "interrupted_again": bool(interrupts),
        }

    @staticmethod
    def _persist_resume_message(db, *, session_id: str, answer: str) -> None:
        """把坐席确认后续跑出的回复，作为一条 assistant 消息补进会话记录"""
        if db is None or not session_id:
            return
        try:
            from sqlalchemy import func

            from app.models.agent_config import AgentMessage
            max_turn = db.query(func.max(AgentMessage.turn_number)).filter_by(
                session_id=session_id).scalar()
            db.add(AgentMessage(
                session_id=session_id,
                turn_number=(max_turn or 0) + 1,
                role="assistant",
                content=answer,
            ))
            db.commit()
        except Exception as e:
            print(f"[DeepAgent] 续跑回复落库失败: {e}")
            db.rollback()

    # ---------- 能力开关 / 提示词补充 ----------
    @staticmethod
    def _todos_enabled(intent: Optional[str]) -> bool:
        """
        规划开关：多步业务流（退款/投诉/物流异常）默认开，单步查询默认关。

        客服是"一问一答"场景，每轮都先写 todo 会白烧一次 LLM 调用；
        但退款要经历"查单→判资格→发起→建单"，先列计划确实更稳。
        环境变量 DEEPAGENTS_TODOS=1/0 可强制开关。
        """
        env = os.getenv("DEEPAGENTS_TODOS", "").strip().lower()
        if env in ("1", "true", "on"):
            return True
        if env in ("0", "false", "off"):
            return False
        return (intent or "") in MULTI_STEP_INTENTS

    @staticmethod
    def _deep_agent_addendum(state: Dict[str, Any], subagents: List[Dict[str, Any]]) -> str:
        names = "、".join(s["name"] for s in subagents) if subagents else "无"
        return (
            "\n## 协作方式（deepagents）\n"
            f"你是本轮主 Agent：{(state.get('agent_name') or '客服助手')}。\n"
            f"可委派的子代理：{names}。\n"
            "- 如果判断客户诉求不属于你的职责域，用 task 工具委派给对应子代理，不要自己硬答。\n"
            "- 属于你职责域的，直接调用工具处理，不要为了走流程而委派。\n"
            "- 多步任务可先用 write_todos 列计划（同一轮内完成，不要向客户播报内部计划）。\n"
            "- 不要把内部工具名、状态字段、计划文本直接展示给客户。\n"
        )


# 全局入口（无状态，可复用）
_deep_agent: Optional[DeepAgentCustomerAgent] = None


def get_deep_agent(db=None) -> DeepAgentCustomerAgent:
    global _deep_agent
    if _deep_agent is None:
        _deep_agent = DeepAgentCustomerAgent()
    return _deep_agent
