# -*- coding: utf-8 -*-
"""
轻量工具协议（MCP 概念简化版）

教材 Ch11/Ch14 提及 MCP 作为 Agent 连接外部系统的标准协议。
本项目不引入完整 MCP 服务端，而是定义简化的 BaseTool ABC，
让子 Agent 声明可调用的工具列表，由 MainAgent 在执行时按需调用。
"""
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseTool(ABC):
    """工具基类"""

    tool_name: str = ""  # 子类必须声明唯一工具名
    description: str = ""
    parameters: Dict[str, Any] = {}  # JSON Schema 格式参数描述

    @abstractmethod
    def execute(self, params: Dict[str, Any], context: 'AgentContext') -> Dict[str, Any]:
        """
        执行工具

        Returns:
            {
                "success": bool,
                "data": Any,           # 工具返回数据
                "error": Optional[str], # 失败原因
                "tool_output": Any      # 供 LLM 调用的结构化输出
            }
        """
        ...


class MockOrderTool(BaseTool):
    """
    订单查询工具（订单服务统一走 order_store，与 DST 动态注入共用同一份数据）

    教材 Ch7：TicketAgent 需要先查订单信息再创建工单
    """
    tool_name = "query_order"
    description = "按订单号查询订单详情（商品、金额、状态、物流单号、退款资格）。订单号未知时不要反复索要，改用 list_recent_orders。"
    parameters = {
        "order_id": {"type": "string", "description": "订单号（字母+数字组合，如 XX20250803-1287）"}
    }

    def execute(self, params: Dict[str, Any], context) -> Dict[str, Any]:
        from app.services import order_store
        order_id = params.get("order_id", "")
        order = order_store.get_order(order_id)
        if not order:
            return {
                "success": False,
                "data": None,
                "error": f"未找到订单 {order_id}（请核对单号，或改用 list_recent_orders 按客户查）",
            }
        verdict = order_store.evaluate_refund(order)
        data = dict(order)
        data["refund_eligible"] = verdict["eligible"]
        data["refund_rule"] = verdict["reason"]
        return {"success": True, "data": data, "error": None}


class ListRecentOrdersTool(BaseTool):
    """
    按客户查最近订单——「客户忘了订单号」的兜底工具

    教材 Ch5.2.3：关键标识拿不到时，系统应主动查得到，而不是把同一个问题
    重复问第二遍。LLM 在 DST 状态块提示「客户已表示记不清订单号」时调用本工具。
    """
    tool_name = "list_recent_orders"
    description = "列出该客户名下最近的订单（订单号/商品/金额/状态）。当客户说忘记订单号、找不到单号、只记得商品时调用，然后把候选订单列给客户确认。"
    parameters = {
        "limit": {"type": "integer", "description": "返回条数，默认 3"},
    }

    def execute(self, params: Dict[str, Any], context) -> Dict[str, Any]:
        from app.services import order_store
        try:
            limit = int(params.get("limit") or 3)
        except (TypeError, ValueError):
            limit = 3
        uid = None
        if isinstance(context, dict):
            uid = context.get("user_id")
        else:
            uid = getattr(context, "user_id", None)
        items = order_store.list_recent_orders(uid, limit=limit)
        return {
            "success": True,
            "data": {
                "count": len(items),
                "orders": [
                    {
                        "order_id": o["order_id"],
                        "product_name": o["product_name"],
                        "amount": o["amount"],
                        "status": o["status"],
                        "pay_time": o["pay_time"],
                    }
                    for o in items
                ],
                "hint": "请把这几单列给客户，让客户确认是哪一单，不要再次索要订单号。",
            },
            "error": None,
        }


class MockLogisticsTool(BaseTool):
    """
    模拟物流查询工具
    """
    tool_name = "check_logistics"
    description = "查询物流轨迹详情"
    parameters = {
        "order_id": {"type": "string", "description": "订单号"},
        "logistics_no": {"type": "string", "description": "物流单号（可选，优先用物流单号）"}
    }

    _mock_tracks = {
        "ZTO1234567890": [
            {"time": "2025-08-04 08:00", "status": "已揽收", "location": "广州市白云区"},
            {"time": "2025-08-04 18:00", "status": "运输中", "location": "广州市转运中心"},
            {"time": "2025-08-05 10:00", "status": "派送中", "location": "深圳市南山区"},
            {"time": "2025-08-05 14:30", "status": "已签收", "location": "深圳市南山区XX小区"},
        ],
        "SF9876543210": [
            {"time": "2025-09-01 12:00", "status": "已揽收", "location": "上海市浦东新区"},
            {"time": "2025-09-02 08:00", "status": "运输中", "location": "杭州市分拨中心"},
            {"time": "2025-09-02 16:00", "status": "派送中", "location": "杭州市西湖区"},
        ],
    }

    def execute(self, params: Dict[str, Any], context) -> Dict[str, Any]:
        logistics_no = params.get("logistics_no", "")
        if not logistics_no:
            # 尝试从 context 推断
            order_id = params.get("order_id", "")
            order_info = getattr(context, 'order_info', None) or {}
            logistics_no = order_info.get("logistics_no", "")
        track = self._mock_tracks.get(logistics_no, [])
        return {"success": True, "data": {"logistics_no": logistics_no, "tracks": track}, "error": None}


class CreateTicketTool(BaseTool):
    """
    创建客服工单工具（真实落库版）

    调用 TicketService 写入 tickets 表并生成 TicketEvent，返回真实工单号与 SLA 到期时间。
    这样对话中 LLM 调用 create_ticket 后，工单会真正出现在工单系统里，而非返回假号。
    """
    tool_name = "create_ticket"
    description = "创建客服工单并写入工单系统，返回真实工单号与 SLA 到期时间。涉及退款/物流异常/投诉等需跟进的问题时调用。"
    parameters = {
        "category": {"type": "string", "description": "工单分类：退款申请/物流异常/投诉建议/商品问题/其他（可留空自动判定）"},
        "summary": {"type": "string", "description": "问题摘要（通常为用户诉求）"},
        "priority": {"type": "integer", "description": "优先级 1-5（5 最紧急），可留空自动判定"},
        "session_id": {"type": "string", "description": "关联会话ID，可留空从上下文取"},
        "assigned_to": {"type": "string", "description": "指派对象（可选）"},
    }

    def execute(self, params: Dict[str, Any], context) -> Dict[str, Any]:
        from app.services.ticket_service import TicketService, normalize_category
        from app.models.database import get_session_local

        db = get_session_local()()
        try:
            ctx_sid = None
            if isinstance(context, dict):
                ctx_sid = context.get("session_id")
            else:
                ctx_sid = getattr(context, "session_id", None)
            sid = params.get("session_id") or ctx_sid

            priority = params.get("priority")
            try:
                priority = int(priority) if priority not in (None, "") else None
            except (TypeError, ValueError):
                priority = None

            svc = TicketService(db)
            category = normalize_category(params.get("category"))

            # 幂等：同一会话同一诉求线程（含可合并分类）已有未关闭工单时，
            # 直接返回已有工单，避免对话里既自动建单、LLM 又手动建单造成工单池重复。
            if sid:
                existing = svc.get_issue_thread_ticket(sid, category)
                if existing is not None:
                    d = existing.to_dict()
                    return {
                        "success": True,
                        "data": {
                            "ticket_no": existing.ticket_no,
                            "ticket_id": existing.id,
                            "category": existing.category,
                            "priority": existing.priority,
                            "status": existing.status,
                            "sla_due_at": d.get("sla_due_at"),
                            "duplicated": True,
                        },
                        "error": None,
                    }

            ticket = svc.create_ticket(
                session_id=sid,
                intent=None,
                summary=params.get("summary") or "",
                category=category,
                priority=priority,
                source="agent",
                assigned_to=params.get("assigned_to") or None,
            )
            d = ticket.to_dict()
            return {
                "success": True,
                "data": {
                    "ticket_no": ticket.ticket_no,
                    "ticket_id": ticket.id,
                    "category": ticket.category,
                    "priority": ticket.priority,
                    "status": ticket.status,
                    "sla_due_at": d.get("sla_due_at"),
                },
                "error": None,
            }
        except Exception as e:
            return {"success": False, "data": None, "error": str(e)}
        finally:
            db.close()


class SubmitRefundTool(BaseTool):
    """
    发起退款（不可逆的资金动作）

    教材 Ch7/Ch8 的落地：AI 可以「发起」，但不能「自己批准」。
    本工具在 deepagents 侧被 `HumanInTheLoopMiddleware` 拦截——模型调用后图会
    停在审批点，等坐席在工单页确认，再用 `Command(resume=...)` 续跑，工具才真正
    生成受理号。

    金额一律取订单实付，不接受模型传值：模型只负责「哪个订单、什么原因」。
    """

    tool_name = "submit_refund"
    description = (
        "对指定订单发起退款申请（真实受理，返回 RMA 受理号）。"
        "仅在客户明确要求退款、且订单符合退款条件时调用；"
        "调用前应先 query_order 核实订单与退款资格。"
        "该操作需要坐席审批，调用后会挂起等待确认，不要把未返回的受理号说成已办妥。"
    )
    parameters = {
        "order_id": {"type": "string", "description": "订单号（需已核实存在）"},
        "reason": {"type": "string", "description": "退款原因，如「发错货/与描述不符」「质量问题」"},
    }

    def execute(self, params: Dict[str, Any], context) -> Dict[str, Any]:
        from app.services import refund_store
        from app.models.database import get_session_local

        ctx_sid = None
        ctx_uid = None
        if isinstance(context, dict):
            ctx_sid = context.get("session_id")
            ctx_uid = context.get("user_id")
        else:
            ctx_sid = getattr(context, "session_id", None)
            ctx_uid = getattr(context, "user_id", None)

        order_id = (params.get("order_id") or "").strip()
        if not order_id:
            return {"success": False, "data": None, "error": "缺少订单号，无法发起退款"}

        db = get_session_local()()
        try:
            result = refund_store.create_refund(
                db,
                session_id=ctx_sid,
                order_id=order_id,
                reason=params.get("reason") or "",
                user_id=ctx_uid,
                source="agent",
                approved_by=params.get("approved_by") or None,
            )
            if not result.get("success"):
                return {"success": False, "data": None, "error": result.get("error")}
            return {"success": True, "data": result, "error": None}
        except Exception as e:
            return {"success": False, "data": None, "error": str(e)}
        finally:
            db.close()


class RagKnowledgeTool(BaseTool):
    """
    知识库检索工具（RAG）

    让 LLM 在回答时按需检索知识库（而不是盲目注入全部上下文）。
    替代原先 FAQAgent 里硬编码的 RAG 调用，使其成为可声明的工具。
    """

    tool_name = "rag_knowledge"
    description = "从知识库中检索与用户问题相关的销售话术、政策、FAQ 等事实片段。当需要依据公司政策/知识回答时调用。"
    parameters = {
        "query": {"type": "string", "description": "检索查询（通常是用户问题或子意图）"},
        "top_k": {"type": "integer", "description": "返回的最大片段数，默认 3"},
    }

    def execute(self, params: Dict[str, Any], context) -> Dict[str, Any]:
        from app.services.rag import RAGService
        from app.models.database import get_session_local

        db = get_session_local()()
        try:
            svc = RAGService(db)
            result = svc.answer(
                question=params.get("query", ""),
                session_id=getattr(context, "session_id", None) if not isinstance(context, dict) else context.get("session_id"),
                top_k=int(params.get("top_k", 3)),
            )
            return {
                "success": True,
                "data": {
                    "answer": result.get("answer", ""),
                    "sources": result.get("sources", []),
                },
                "error": None,
            }
        except Exception as e:
            return {"success": False, "data": None, "error": str(e)}
        finally:
            db.close()


class SkillTool(BaseTool):
    """
    技能（Skill）包装工具

    读取 workspace/skills/{skill_id}/SKILL.md 内容，注入到对话上下文。
    Agent 绑定 Skill 后，此工具自动注册到 ToolRegistry，LLM 可通过
    tool_name 调用该技能，返回技能内容和简要说明。
    """

    def __init__(self, skill_id: str, skill_name: str, skill_description: str, skill_content: str):
        self.skill_id = skill_id
        self.tool_name = f"skill_{skill_id}"
        self.description = f"调用技能「{skill_name}」：{skill_description}"
        self.parameters: Dict[str, Any] = {
            "query": {"type": "string", "description": "用户问题或任务描述（用于限定技能内容的哪个部分）"}
        }
        self._content = skill_content

    def execute(self, params: Dict[str, Any], context) -> Dict[str, Any]:
        query = params.get("query", "")
        # 缺陷8修复：长 SOP 直接注入会撑爆上下文，做长度保护（截断 + 提示）
        MAX_LEN = 4000
        content = self._content or ""
        truncated = False
        if len(content) > MAX_LEN:
            content = content[:MAX_LEN]
            truncated = True
        note = "（内容已截断，仅展示前段；如需特定步骤请明确说明）" if truncated else ""

        # 【内外部分层】技能返回的是「内部处置手册」，只供 Agent 推理，绝不进入发送体。
        # 之前直接把 skill_content 明文返回，模型会原样/分节粘贴给客户，造成 SOP 泄露。
        # 现在把手册包裹进 internal_only 信封，并用 output_contract 明确要求 Agent
        # 单独生成 customer_message（面向客户的自然语言结论）。
        internal_manual = (
            "【内部处置手册·严禁外发】以下内容仅供你推理与决策参考。"
            "禁止把原文、整段、分节标题、分级定性、升级阈值、内部工具名或任何内部字段"
            "复述给客户。请先按手册判断需要哪些事实（订单号/商品/问题），用工具核实后，"
            "只输出一段 2-4 句、面向客户的自然语言回复。\n\n"
            + content + note
        )
        return {
            "success": True,
            "data": {
                "skill_id": self.skill_id,
                "skill_name": self.tool_name,
                "query_hint": query,
                "usage": "internal_only",
                "internal_manual": internal_manual,
                # 由 Agent 生成；禁止把 internal_manual 填到这里
                "customer_message": None,
                "output_contract": (
                    "internal_manual 仅供推理，绝不外发。customer_message 由你生成，"
                    "只写面向客户的自然语言结论（2-4 句），不得包含 SOP、P0-P3 分级、"
                    "升级阈值、内部工具名、「话术要点」「避免」等内部内容。"
                ),
            },
            "error": None,
        }


class McpServerTool(BaseTool):
    """
    MCP Server 工具包装

    当 Agent 绑定了一个 MCP Server 时，此工具暴露一个统一的入口：
    调用 MCP server 的工具并返回结果。工具名为 mcp_{server_id}。
    """

    def __init__(self, server_id: str, server_name: str, server_description: Optional[str], connected_tools: Optional[List[Dict[str, Any]]] = None):
        self.server_id = server_id
        self.tool_name = f"mcp_{server_id}"
        display = server_name or server_id
        self._connected_tools = connected_tools or []
        if self._connected_tools:
            # 把 MCP Server 实际暴露的子工具写进描述，供 LLM 选择 tool_name
            lines = []
            for t in self._connected_tools:
                nm = t.get("name", "")
                ds = (t.get("description") or "").strip().replace("\n", " ")
                lines.append(f"  - {nm}: {ds}")
            tool_block = "\n".join(lines)
            self.description = (
                f"通过 MCP Server「{display}」调用外部业务系统（{server_description or '订单/售后/物流等'}）。\n"
                f"调用方式：tool_name 填子工具名，arguments 填其参数对象（JSON）。可用子工具：\n"
                f"{tool_block}"
            )
        else:
            self.description = f"通过 MCP Server「{display}」调用远程工具（{server_description or ''}）"
        self.parameters: Dict[str, Any] = {
            "tool_name": {"type": "string", "description": "要调用的 MCP 子工具名（见工具描述中的可用列表）"},
            "arguments": {"type": "object", "description": "子工具的参数对象（JSON），键名见工具描述中各子工具的说明"},
        }

    def execute(self, params: Dict[str, Any], context) -> Dict[str, Any]:
        from app.services.tools.mcp_client import call_mcp_tool as _call
        tool_name = params.get("tool_name", "")
        arguments = params.get("arguments", {})
        result = _call(self.server_id, tool_name, arguments)
        if result.get("success"):
            return {"success": True, "data": result.get("data"), "error": None}
        return {"success": False, "data": None, "error": result.get("error", "mcp call failed")}
