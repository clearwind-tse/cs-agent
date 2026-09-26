# -*- coding: utf-8 -*-
"""
子Agent动态注册与初始化模块

负责：
1. 启动时从 DB 加载所有 active Agent（热更新）
2. 运行时动态注册/注销 Agent（路由调用）
3. 维护 agent_type → Python class 映射表
"""
import json
from typing import Optional
import sqlalchemy

from app.services.agent_registry import get_agent_registry
from app.services.agents.faq_agent import FAQAgent
from app.services.agents.dialogue_agent import DialogueAgent
from app.services.agents.complaint_agent import ComplaintAgent
from app.services.agents.ticket_agent import TicketAgent
from app.services.tools.registry import get_tool_registry
from app.services.tools import SkillTool, McpServerTool


def register_all_agents():
    """注册所有硬编码默认子Agent"""
    registry = get_agent_registry()
    registry.register(FAQAgent())
    registry.register(DialogueAgent())
    registry.register(ComplaintAgent())
    registry.register(TicketAgent())
    print(f"[AgentRegistry] 已注册 {len(registry.list_all())} 个子Agent（硬编码默认）")


def register_agent_from_db(agent_id: str, db=None):
    """
    从数据库动态注册/热更新子Agent

    流程：
    1. 查询 DB 中 agent_configs 表获取配置（含 agent_type）
    2. 根据 agent_type 从映射表实例化对应 Python 类
    3. 用 DB 配置覆盖实例字段（supported_intents/supported_emotions/priority/status）
    4. 反注册旧实例（如有）后重新注册 → 实现热更新
    """
    # 先从 DB 拿记录，取出真实 agent_type
    target_type = None
    if db:
        from app.models.agent_config import AgentConfig
        config = db.query(AgentConfig).filter_by(agent_id=agent_id).first()
        if config:
            target_type = config.agent_type
        else:
            print(f"[AgentRegistry] agent_configs 中不存在 {agent_id}，跳过 DB 注册")
            return

    # agent_type → Python class 映射表
    agent_type_map = {
        "faq": FAQAgent,
        "dialogue": DialogueAgent,
        "ticket": TicketAgent,
        "complaint": ComplaintAgent,
    }

    agent_type = target_type or ""
    if agent_type not in agent_type_map:
        print(f"[AgentRegistry] 未知 Agent 类型 '{agent_type}'（{agent_id}），跳过")
        return

    cls = agent_type_map[agent_type]
    instance = cls()

    # 从 DB 加载配置并覆盖
    if db:
        from app.models.agent_config import AgentConfig
        config = db.query(AgentConfig).filter_by(agent_id=agent_id).first()
        if config:
            # 兼容：DB 列可能是 str（原始 JSON）或已反序列化的 list（SQLAlchemy JSON）
            if config.supported_intents:
                instance.supported_intents = config.supported_intents if isinstance(config.supported_intents, list) else json.loads(config.supported_intents)
            if config.supported_emotions:
                instance.supported_emotions = config.supported_emotions if isinstance(config.supported_emotions, list) else json.loads(config.supported_emotions)
            if config.priority:
                instance.priority = config.priority
            if config.status == "inactive":
                instance.status = __import__("app.services.agent_registry", fromlist=["AgentStatus"]).AgentStatus.INACTIVE
            elif config.status == "draft":
                instance.status = __import__("app.services.agent_registry", fromlist=["AgentStatus"]).AgentStatus.DRAFT
            else:
                instance.status = __import__("app.services.agent_registry", fromlist=["AgentStatus"]).AgentStatus.ACTIVE

    registry = get_agent_registry()
    # 先反注册（防止重复），再注册 → 实现热更新
    registry.unregister(agent_id)
    registry.register(instance)
    print(f"[AgentRegistry] 热注册 Agent: {agent_id} ({instance.name}, type={agent_type})")

    # 加载绑定的 Skill 和 MCP 工具
    _load_bound_tools(agent_id, config, db)


def _load_bound_tools(agent_id: str, config, db):
    """根据 agent_configs 的 skill_ids / mcp_server_ids 动态注册工具到 ToolRegistry"""
    from app.routers.skills import load_skills
    from app.routers.mcp import _load as _load_mcp_servers

    tool_reg = get_tool_registry()

    # 解析 skill_ids
    skill_ids_raw = config.skill_ids
    skill_ids = skill_ids_raw if isinstance(skill_ids_raw, list) else (json.loads(skill_ids_raw) if skill_ids_raw else [])
    if skill_ids:
        all_skills = load_skills()
        valid_ids = {s["id"] for s in all_skills}
        for sid in skill_ids:
            skill = next((s for s in all_skills if s["id"] == sid), None)
            if skill:
                tool_name = f"skill_{sid}"
                tool_reg.unregister(tool_name)
                tool_reg.register(SkillTool(
                    skill_id=sid,
                    skill_name=skill.get("name", sid),
                    skill_description=skill.get("description") or "",
                    skill_content=skill.get("content") or "",
                ))
                print(f"[ToolRegistry] 注册 Skill 工具: {tool_name} ← {skill.get('name')}")
            else:
                # 缺陷5修复：绑定了不存在的 Skill，记录悬空引用告警
                print(f"[ToolRegistry][WARN] Agent '{agent_id}' 绑定的 Skill '{sid}' 不存在（已忽略，疑似悬空引用）")

    # 解析 mcp_server_ids
    mcp_ids_raw = config.mcp_server_ids
    mcp_ids = mcp_ids_raw if isinstance(mcp_ids_raw, list) else (json.loads(mcp_ids_raw) if mcp_ids_raw else [])
    if mcp_ids:
        from app.services.tools.mcp_client import list_mcp_tools
        all_mcp = _load_mcp_servers()
        valid_ids = {s["id"] for s in all_mcp}
        for mid in mcp_ids:
            ms = next((s for s in all_mcp if s["id"] == mid), None)
            if ms:
                tool_name = f"mcp_{mid}"
                tool_reg.unregister(tool_name)
                # 拉取该 MCP Server 的子工具清单，写进工具描述（让 LLM 知道能调什么）
                connected = list_mcp_tools(mid)
                tool_reg.register(McpServerTool(
                    server_id=mid,
                    server_name=ms.get("name") or mid,
                    server_description=ms.get("description"),
                    connected_tools=connected,
                ))
                names = ", ".join(t["name"] for t in connected) if connected else "（未获取到工具清单）"
                print(f"[ToolRegistry] 注册 MCP 工具: {tool_name} ← {ms.get('name')} 子工具[{len(connected)}]: {names}")
            else:
                print(f"[ToolRegistry][WARN] Agent '{agent_id}' 绑定的 MCP Server '{mid}' 不存在（已忽略，疑似悬空引用）")


def load_all_agents_from_db(db=None):
    """
    启动时从 DB 加载所有 active Agent

    策略：
    1. 清空 Registry（避免与硬编码重复）
    2. 从 DB 加载 active Agent 并注册（修复：只遍历一次）
    3. 对 DB 中不存在记录的 agent，补充注册硬编码默认 Agent
    """
    registry = get_agent_registry()
    for agent in registry.list_all():
        registry.unregister(agent.agent_id)

    db_agent_ids: set = set()
    if db:
        from app.models.agent_config import AgentConfig
        configs = db.execute(
            sqlalchemy.text("SELECT agent_id FROM agent_configs WHERE status = 'active'")
        ).fetchall()
        for row in configs:
            aid = row[0]
            db_agent_ids.add(aid)
            register_agent_from_db(aid, db)
            print(f"[AgentRegistry] 启动加载 DB Agent: {aid}")

    # 仅对 DB 中没有的 agent 注册硬编码默认版本（避免 DB 记录被删除后静默消失）
    hardcoded_ids = {"faq_agent", "dialogue_agent", "complaint_agent", "ticket_agent"}
    for aid in hardcoded_ids:
        if aid not in db_agent_ids:
            register_agent_from_db(aid, db)

    print(f"[AgentRegistry] 启动完成，共 {len(registry.list_all())} 个子Agent")
