# -*- coding: utf-8 -*-
"""
子Agent管理API

提供子Agent的注册、查询、更新接口
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session as DBSession
from typing import Dict, List, Optional
from pydantic import BaseModel
from datetime import datetime
import json

from app.models.database import get_db
from app.models.agent_config import AgentConfig, AgentSession
from app.services.agent_registry import get_agent_registry
from app.services.agent_engine import get_customer_agent, current_engine
from app.services.intent_recognition import IntentRecognitionService
from app.config import get_settings
from sqlalchemy import text as sql_text

settings = get_settings()

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ==================== 请求/响应模型 ====================

class AgentRegisterRequest(BaseModel):
    """子Agent注册请求"""
    agent_id: str
    name: str
    description: Optional[str] = None
    agent_type: str  # faq / dialogue / ticket / emotion
    supported_intents: List[str] = []
    supported_emotions: List[str] = []
    priority: int = 50
    config: dict = {}
    skill_ids: List[str] = []
    mcp_server_ids: List[str] = []


class AgentUpdateRequest(BaseModel):
    """子Agent更新请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None  # active / inactive / draft
    priority: Optional[int] = None
    supported_intents: Optional[List[str]] = None
    supported_emotions: Optional[List[str]] = None
    config: Optional[dict] = None
    skill_ids: Optional[List[str]] = None
    mcp_server_ids: Optional[List[str]] = None


class IntentDetectRequest(BaseModel):
    """意图识别请求"""
    message: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None


class IntentDetectResponse(BaseModel):
    """意图识别响应"""
    intent: str
    confidence: float
    sub_intent: Optional[str] = None
    emotion_type: Optional[str] = None
    emotion_intensity: int = 1
    frustration_signals: List[str] = []
    routed_agent: Optional[str] = None


class MessageProcessRequest(BaseModel):
    """消息处理请求"""
    message: str
    session_id: str
    user_id: Optional[str] = None
    stream: bool = False  # 是否流式响应


class MessageProcessResponse(BaseModel):
    """消息处理响应"""
    answer: str
    intent: str
    confidence: float
    emotion: Optional[str] = None
    emotion_intensity: int = 1
    agent_name: str
    next_action: Optional[str] = None
    needs_transfer: bool = False
    transfer_reason: Optional[str] = None
    sources: List[dict] = []
    updated_entities: dict = {}
    updated_phase: Optional[str] = None
    # 本轮该会话的未关闭工单（LLM 建单或兜底建单都回传，前端据此显示工单卡片）
    ticket_no: Optional[str] = None
    ticket: Optional[dict] = None
    # 是否挂在「等待坐席确认」的动作上（如退款受理），确认入口在工单详情
    pending_approval: bool = False
    pending: Optional[dict] = None
    engine: Optional[str] = None
    error: Optional[str] = None


class AgentSessionCreateRequest(BaseModel):
    session_id: str
    user_id: Optional[str] = None
    display_name: Optional[str] = None


class AgentSessionUpdateRequest(BaseModel):
    user_id: Optional[str] = None
    display_name: Optional[str] = None


# ==================== API端点 ====================

@router.get("/list")
def list_agents(
    status: Optional[str] = Query(None, description="过滤状态：active/inactive/draft"),
    db: DBSession = Depends(get_db)
):
    """
    列出所有子Agent（按 agent_id 去重合并）

    之前该接口把「注册表 Agent」与「DB 配置」各返回一份，导致同一 Agent 出现
    两条、且只有 DB 那条带 skill_ids/mcp_server_ids，绑定界面很混乱。
    现改为：以 agent_id 为主键合并，DB 配置字段（含绑定）覆盖注册表默认值，
    保证每个 Agent 只有一条、且携带完整的 skill/mcp 绑定。
    """
    from sqlalchemy import text

    def _parse_json_field(v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return []
        return [] if v is None else v

    merged: dict = {}

    # 1) 注册表：基础运行时字段（无绑定，先占位）
    for agent in get_agent_registry().list_all():
        merged[agent.agent_id] = {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "description": agent.description,
            "agent_type": agent.agent_type,
            "status": agent.status.value,
            "priority": agent.priority,
            "supported_intents": agent.supported_intents,
            "supported_emotions": getattr(agent, "supported_emotions", []),
            "supported_phases": getattr(agent, "supported_phases", []),
            "skill_ids": [],
            "mcp_server_ids": [],
        }

    # 2) DB 配置：覆盖/补充（DB 为准，含 skill_ids / mcp_server_ids 绑定）
    for row in db.execute(text("SELECT * FROM agent_configs")).fetchall():
        d = dict(row._mapping)
        for k in ("skill_ids", "mcp_server_ids", "supported_intents",
                  "supported_emotions", "supported_phases"):
            d[k] = _parse_json_field(d.get(k))
        aid = d.get("agent_id")
        base = merged.get(aid) or {"agent_id": aid}
        # DB 的非空字段优先
        for k, v in d.items():
            if v is not None:
                base[k] = v
        merged[aid] = base

    result = list(merged.values())
    if status:
        result = [a for a in result if a.get("status") == status]
    return {"agents": result}


@router.post("/register")
def register_agent(
    request: AgentRegisterRequest,
    db: DBSession = Depends(get_db)
):
    """
    注册新的子Agent
    """
    # 检查是否已存在
    from sqlalchemy import text
    existing = db.execute(
        text("SELECT id FROM agent_configs WHERE agent_id = :agent_id"),
        {"agent_id": request.agent_id}
    ).fetchone()

    if existing:
        raise HTTPException(status_code=400, detail="Agent ID已存在")

    # 插入数据库
    db.execute(
        text("""
            INSERT INTO agent_configs
            (agent_id, name, description, agent_type, status, priority,
             supported_intents, supported_emotions, config_json, skill_ids, mcp_server_ids)
            VALUES (:agent_id, :name, :description, :agent_type, 'active', :priority,
                    :supported_intents, :supported_emotions, :config_json, :skill_ids, :mcp_server_ids)
        """),
        {
            "agent_id": request.agent_id,
            "name": request.name,
            "description": request.description,
            "agent_type": request.agent_type,
            "priority": request.priority,
            "supported_intents": json.dumps(request.supported_intents, ensure_ascii=False),
            "supported_emotions": json.dumps(request.supported_emotions, ensure_ascii=False),
            "config_json": json.dumps(request.config, ensure_ascii=False),
            "skill_ids": json.dumps(request.skill_ids, ensure_ascii=False),
            "mcp_server_ids": json.dumps(request.mcp_server_ids, ensure_ascii=False),
        }
    )
    db.commit()

    # 热更新 Registry（新增动态注册实现）
    from app.services.agent_initializer import register_agent_from_db
    register_agent_from_db(request.agent_id, db)

    return {"message": f"子Agent '{request.agent_id}' 注册成功", "agent_id": request.agent_id}


@router.put("/update/{agent_id}")
def update_agent(
    agent_id: str,
    request: AgentUpdateRequest,
    db: DBSession = Depends(get_db)
):
    """
    更新子Agent配置
    """
    from sqlalchemy import text

    # 检查是否存在
    existing = db.execute(
        text("SELECT id FROM agent_configs WHERE agent_id = :agent_id"),
        {"agent_id": agent_id}
    ).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="子Agent不存在")

    # 构建更新语句
    updates = []
    params = {"agent_id": agent_id}

    if request.name is not None:
        updates.append("name = :name")
        params["name"] = request.name

    if request.description is not None:
        updates.append("description = :description")
        params["description"] = request.description

    if request.status is not None:
        updates.append("status = :status")
        params["status"] = request.status

    if request.priority is not None:
        updates.append("priority = :priority")
        params["priority"] = request.priority

    if request.supported_intents is not None:
        updates.append("supported_intents = :supported_intents")
        params["supported_intents"] = json.dumps(request.supported_intents, ensure_ascii=False)

    if request.supported_emotions is not None:
        updates.append("supported_emotions = :supported_emotions")
        params["supported_emotions"] = json.dumps(request.supported_emotions, ensure_ascii=False)

    if request.config is not None:
        updates.append("config_json = :config_json")
        params["config_json"] = json.dumps(request.config, ensure_ascii=False)

    if request.skill_ids is not None:
        updates.append("skill_ids = :skill_ids")
        params["skill_ids"] = json.dumps(request.skill_ids, ensure_ascii=False)

    if request.mcp_server_ids is not None:
        updates.append("mcp_server_ids = :mcp_server_ids")
        params["mcp_server_ids"] = json.dumps(request.mcp_server_ids, ensure_ascii=False)

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        db.execute(
            text(f"UPDATE agent_configs SET {', '.join(updates)} WHERE agent_id = :agent_id"),
            params
        )
        db.commit()

    # 热更新 Registry
    from app.services.agent_initializer import register_agent_from_db
    register_agent_from_db(agent_id, db)

    return {"message": "子Agent更新成功", "agent_id": agent_id}


@router.post("/intent/detect")
def detect_intent(
    request: IntentDetectRequest,
    db: DBSession = Depends(get_db)
):
    """
    识别用户消息的意图
    """
    service = IntentRecognitionService()
    result = service.detect_intent(request.message, request.user_id)

    # 路由到合适的Agent
    registry = get_agent_registry()
    agent = registry.resolve_agent(
        intent=result.intent,
        emotion=result.emotion_type
    )

    return IntentDetectResponse(
        intent=result.intent,
        confidence=result.confidence,
        sub_intent=result.sub_intent,
        emotion_type=result.emotion_type,
        emotion_intensity=result.emotion_intensity,
        frustration_signals=result.frustration_signals,
        routed_agent=agent.agent_id if agent else None
    )


def _load_history(db: DBSession, session_id: str, limit: int = 40) -> List[Dict[str, str]]:
    """
    从 agent_messages 读取该会话最近的历史（旧→新）。

    这里故意多读一些（40 条 ≈ 20 轮），真正的「滑动窗口 + 摘要压缩」在
    LangGraphCustomerAgent 里按意图自适应裁剪（教材 Ch5.2.2）——
    读取层不做业务判断，避免窗口策略散落在多处。
    """
    from sqlalchemy import text
    rows = db.execute(
        text("SELECT role, content FROM agent_messages WHERE session_id=:sid ORDER BY turn_number DESC LIMIT :lim"),
        {"sid": session_id, "lim": limit},
    ).fetchall()
    rows = list(rows)[::-1]  # 翻转为时间正序
    return [{"role": r.role, "content": r.content} for r in rows]


@router.get("/engine")
def engine_info():
    """当前生效的客服编排引擎（deepagents / langgraph），便于前端与排障确认"""
    return {"engine": current_engine()}


@router.post("/message/process", response_model=MessageProcessResponse)
def process_message(
    request: MessageProcessRequest,
    db: DBSession = Depends(get_db)
):
    """
    处理用户消息（默认 deepagents 编排：意图识别→路由→深度 Agent 规划/工具→转人工→持久化）

    引擎可通过环境变量 AGENT_ENGINE 在 deepagents / langgraph 之间切换。
    多轮上下文：自动从 DB 载入本会话历史，再由 DST 做槽位抽取与滑动窗口。
    """
    history = _load_history(db, request.session_id)
    agent = get_customer_agent(db)
    r = agent.process_message(
        message=request.message,
        session_id=request.session_id,
        user_id=request.user_id,
        history=history,
        db=db,
    )

    return MessageProcessResponse(
        answer=r.get("answer", "（无有效回复）"),
        intent=r.get("intent"),
        confidence=r.get("confidence", 0.0),
        emotion=r.get("emotion"),
        emotion_intensity=r.get("emotion_intensity", 1),
        agent_name=r.get("agent_name") or "智能客服助手",
        needs_transfer=r.get("needs_transfer", False),
        transfer_reason=r.get("transfer_reason"),
        updated_entities=r.get("updated_entities") or {},
        updated_phase=r.get("updated_phase"),
        ticket_no=r.get("ticket_no"),
        ticket=r.get("ticket"),
        pending_approval=bool(r.get("pending_approval")),
        pending=r.get("pending"),
        engine=r.get("engine") or current_engine(),
        error=r.get("error"),
    )


@router.post("/message/stream")
async def process_message_stream(
    request: MessageProcessRequest,
    db: DBSession = Depends(get_db)
):
    """
    流式处理用户消息（SSE，真·逐 token 推送）

    协议：
      metadata  {type, intent, confidence, emotion, emotion_intensity, agent, phase, slots, engine}
      token     {type, content}
      answer    {type, content, agent}
      error     {type, message}
      done      {type, needs_transfer, signals, agent, ticket_no?, ticket?, pending_approval, pending}

    底层由当前引擎（deepagents / langgraph）的 process_message_stream 真·逐 token 推送：
    LLM 一边生成一边通过 SSE 下发 token，首字延迟 = 意图识别+路由+首个 token，
    而非整轮链路（意图→路由→工具循环→生成→落库）跑完再切片回放。
    """
    import json as _json
    from fastapi.responses import StreamingResponse

    history = _load_history(db, request.session_id)
    agent = get_customer_agent(db)

    async def event_stream():
        async for event in agent.process_message_stream(
            message=request.message,
            session_id=request.session_id,
            user_id=request.user_id,
            history=history,
            db=db,
        ):
            yield _json.dumps(event, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history/{session_id}")
def get_conversation_history(
    session_id: str,
    limit: int = Query(10, ge=1, le=50),
    db: DBSession = Depends(get_db)
):
    """
    获取会话历史
    """
    from sqlalchemy import text

    # 获取意图记录
    intents = db.execute(
        text("""
            SELECT turn_number, user_message, intent, confidence,
                   emotion_type, emotion_intensity
            FROM intent_records
            WHERE session_id = :session_id
            ORDER BY turn_number DESC
            LIMIT :limit
        """),
        {"session_id": session_id, "limit": limit}
    ).fetchall()

    # 获取情绪记录
    emotions = db.execute(
        text("""
            SELECT turn_number, emotion_type, intensity, risk_score
            FROM emotion_records
            WHERE session_id = :session_id
            ORDER BY turn_number DESC
            LIMIT :limit
        """),
        {"session_id": session_id, "limit": limit}
    ).fetchall()

    return {
        "session_id": session_id,
        "intents": [dict(row._mapping) for row in intents],
        "emotions": [dict(row._mapping) for row in emotions]
    }


@router.post("/transfer/decision")
def make_transfer_decision(
    session_id: str,
    db: DBSession = Depends(get_db)
):
    """
    评估是否需要转人工
    """
    from sqlalchemy import text
    from app.services.intent_recognition import IntentRecognitionService

    # 获取最近的意图和情绪记录
    intent_record = db.execute(
        text("""
            SELECT intent, confidence, emotion_type, emotion_intensity,
                   frustration_signals
            FROM intent_records
            WHERE session_id = :session_id
            ORDER BY turn_number DESC
            LIMIT 1
        """),
        {"session_id": session_id}
    ).fetchone()

    if not intent_record:
        return {"needs_transfer": False, "reason": "无历史记录"}

    record = dict(intent_record._mapping)

    # 简单的转人工决策逻辑
    needs_transfer = False
    reason = None

    # 条件1：情绪强度≥4
    if record.get("emotion_intensity", 1) >= 4:
        needs_transfer = True
        reason = f"情绪等级{record['emotion_intensity']}，需升级处理"

    # 条件2：包含投诉关键词
    if record.get("intent") == "complaint":
        needs_transfer = True
        reason = "投诉意图，建议转人工"

    # 条件3：置信度低且情绪负面
    if record.get("confidence", 1.0) < 0.5 and record.get("emotion_intensity", 1) >= 3:
        needs_transfer = True
        reason = "意图不明确且情绪负面"

    return {
        "needs_transfer": needs_transfer,
        "reason": reason,
        "risk_score": record.get("emotion_intensity", 1) * 20 + (100 - record.get("confidence", 1.0) * 100)
    }


@router.get("/tools")
def list_tools():
    """列出所有已注册工具（Skill/MCP + 内置）"""
    from app.services.tools.registry import get_tool_registry
    registry = get_tool_registry()
    tools = [
        {"tool_name": t.tool_name, "description": t.description, "parameters": t.parameters}
        for t in registry.list_all()
    ]
    return {"tools": tools}


@router.get("/tools/available")
def list_available_tools():
    """
    列出可绑定到 Agent 的 Skill / MCP 可用列表（供前端多选使用）
    - skills: 全部 skill 列表（含内置与用户上传）
    - mcp_servers: 全部 MCP Server 配置列表（含健康状态）
    """
    from app.routers.skills import load_skills
    from app.routers.mcp import _load as _load_mcp_servers

    skills = load_skills()
    mcp_servers = _load_mcp_servers()
    return {
        "skills": [{"id": s["id"], "name": s.get("name") or s["id"], "description": s.get("description")} for s in skills],
        "mcp_servers": [{"id": s["id"], "name": s.get("name") or s["id"], "description": s.get("description"), "status": s.get("status", "disconnected")} for s in mcp_servers],
    }


# ==================== Agent 会话管理 ====================

@router.get("/sessions")
def list_agent_sessions(
    user_id: Optional[str] = Query(None, description="按 user_id 过滤"),
    limit: int = Query(50, ge=1, le=200),
    db: DBSession = Depends(get_db),
):
    """列出所有 Agent 会话（可筛选）"""
    from sqlalchemy import text
    where = "WHERE 1=1"
    params: dict = {}
    if user_id is not None:
        where += " AND user_id = :user_id"
        params["user_id"] = user_id
    rows = db.execute(
        text(f"SELECT * FROM agent_sessions {where} ORDER BY updated_at DESC LIMIT :limit"),
        {**params, "limit": limit},
    ).fetchall()
    return {"sessions": [dict(r._mapping) for r in rows]}


@router.get("/sessions/{session_id}")
def get_agent_session(
    session_id: str,
    db: DBSession = Depends(get_db),
):
    """查询单个 Agent 会话"""
    from sqlalchemy import text
    row = db.execute(
        text("SELECT * FROM agent_sessions WHERE session_id = :sid"),
        {"sid": session_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")
    return dict(row._mapping)


@router.post("/sessions")
def create_agent_session(
    request: AgentSessionCreateRequest,
    db: DBSession = Depends(get_db),
):
    """创建新的 Agent 会话"""
    from sqlalchemy import text
    existing = db.execute(
        text("SELECT 1 FROM agent_sessions WHERE session_id = :sid"),
        {"sid": request.session_id},
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="session_id 已存在")
    display_name = request.display_name or f"Agent · {request.user_id or 'anonymous'}"
    db.execute(
        text("""
            INSERT INTO agent_sessions (session_id, user_id, display_name, message_count, created_at)
            VALUES (:sid, :uid, :name, 0, CURRENT_TIMESTAMP)
        """),
        {"sid": request.session_id, "uid": request.user_id, "name": display_name},
    )
    db.commit()
    row = db.execute(
        text("SELECT * FROM agent_sessions WHERE session_id = :sid"),
        {"sid": request.session_id},
    ).fetchone()
    return dict(row._mapping)


@router.put("/sessions/{session_id}")
def update_agent_session(
    session_id: str,
    request: AgentSessionUpdateRequest,
    db: DBSession = Depends(get_db),
):
    """更新会话属性（user_id / display_name）"""
    from sqlalchemy import text
    existing = db.execute(
        text("SELECT 1 FROM agent_sessions WHERE session_id = :sid"),
        {"sid": session_id},
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="会话不存在")
    sets: list[str] = []
    params: dict = {"sid": session_id}
    if request.user_id is not None:
        sets.append("user_id = :user_id")
        params["user_id"] = request.user_id
    if request.display_name is not None:
        sets.append("display_name = :display_name")
        params["display_name"] = request.display_name
    if sets:
        sets.append("updated_at = CURRENT_TIMESTAMP")
        db.execute(text(f"UPDATE agent_sessions SET {', '.join(sets)} WHERE session_id = :sid"), params)
        db.commit()
    row = db.execute(
        text("SELECT * FROM agent_sessions WHERE session_id = :sid"),
        {"sid": session_id},
    ).fetchone()
    return dict(row._mapping)


@router.post("/sessions/{session_id}/close")
def close_agent_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db),
):
    """
    关闭智能客服会话，并把对话整段推送进「会话记录」(raw_chats)，标注来源。
    推送后若开启 AUTO_PIPELINE_ON_PUSH，自动在后台跑 清洗→质检→知识提炼。
    """
    from datetime import timezone
    from app.models.chat import Session as ChatSession, RawChat
    from app.services.pipeline_service import run_pipeline

    row = db.execute(
        text("SELECT * FROM agent_sessions WHERE session_id = :sid"),
        {"sid": session_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")
    sess = dict(row._mapping)
    if sess.get("status") == "closed":
        raise HTTPException(status_code=400, detail="会话已关闭")

    msgs = db.execute(
        text(
            "SELECT turn_number, role, content, created_at "
            "FROM agent_messages WHERE session_id = :sid ORDER BY turn_number ASC"
        ),
        {"sid": session_id},
    ).fetchall()

    raw_session_id = f"agent:{session_id}"

    def _to_ts(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    pushed = 0
    # 幂等：已推送过则跳过重复写入
    already = db.execute(
        text("SELECT 1 FROM sessions WHERE session_id = :sid"),
        {"sid": raw_session_id},
    ).fetchone()
    if not already and msgs:
        times = [t for t in (_to_ts(m.created_at) for m in msgs) if t is not None]
        start_ts = min(times) if times else int(datetime.utcnow().timestamp())
        end_ts = max(times) if times else start_ts

        db.execute(
            text(
                "INSERT INTO sessions "
                "(session_id, display_name, is_chatroom, last_message, last_time, "
                " message_count, push_source, created_at, updated_at) "
                "VALUES (:sid, :name, FALSE, :last, :last_time, :cnt, "
                " 'agent_service', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "sid": raw_session_id,
                "name": sess.get("display_name") or f"智能客服会话 {session_id}",
                "last": (msgs[-1].content or "")[:500],
                "last_time": end_ts,
                "cnt": len(msgs),
            },
        )
        for m in msgs:
            db.execute(
                text(
                    "INSERT INTO raw_chats "
                    "(session_id, sender_wxid, sender_name, content, msg_type, "
                    " is_sender, timestamp, push_source, source_db, created_at) "
                    "VALUES (:sid, :wxid, :name, :content, 1, :is_sender, :ts, "
                    " 'agent_service', 'agent_service', CURRENT_TIMESTAMP)"
                ),
                {
                    "sid": raw_session_id,
                    "wxid": m.role,
                    "name": "智能客服" if m.role == "assistant" else "客户",
                    "content": m.content or "",
                    "is_sender": m.role == "assistant",
                    "ts": _to_ts(m.created_at) or start_ts,
                },
            )
            pushed += 1

        db.execute(
            text(
                "UPDATE agent_sessions SET status='closed', closed_at=CURRENT_TIMESTAMP, "
                "updated_at=CURRENT_TIMESTAMP WHERE session_id=:sid"
            ),
            {"sid": session_id},
        )
        db.commit()

    # 自动流水线（后台执行，避免阻塞关闭请求）
    pipeline_triggered = False
    if settings.auto_pipeline_on_push and msgs:
        background_tasks.add_task(_run_pipeline_task, raw_session_id)
        pipeline_triggered = True

    return {
        "session_id": session_id,
        "raw_session_id": raw_session_id,
        "messages_pushed": pushed,
        "pipeline_triggered": pipeline_triggered,
        "message": "会话已关闭并推送至会话记录" if pushed else "该会话已推送过，未重复写入",
    }


def _run_pipeline_task(raw_session_id: str):
    """后台任务：对推送进来的会话跑 清洗→质检→知识提炼。"""
    from app.models.database import get_session_local
    SessionLocal = get_session_local()
    _db = SessionLocal()
    try:
        from app.services.pipeline_service import run_pipeline
        stats = run_pipeline(_db, raw_session_id)
        print(f"[流水线] {raw_session_id} 完成: {stats}")
    except Exception as e:
        print(f"[流水线] {raw_session_id} 失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _db.close()


@router.get("/sessions/{session_id}/messages")
def list_agent_messages(
    session_id: str,
    limit: int = Query(100, ge=1, le=500),
    db: DBSession = Depends(get_db),
):
    """获取会话消息历史"""
    from sqlalchemy import text
    rows = db.execute(
        text("""
            SELECT id, session_id, turn_number, role, content,
                   intent, confidence, emotion_type as emotion,
                   emotion_intensity, needs_transfer, ticket_no,
                   created_at
            FROM agent_messages
            WHERE session_id = :sid
            ORDER BY turn_number ASC
            LIMIT :limit
        """),
        {"sid": session_id, "limit": limit},
    ).fetchall()
    return {"messages": [dict(r._mapping) for r in rows]}


@router.delete("/sessions/{session_id}")
def delete_agent_session(
    session_id: str,
    db: DBSession = Depends(get_db),
):
    """删除 Agent 会话及其关联记录"""
    from sqlalchemy import text
    existing = db.execute(
        text("SELECT 1 FROM agent_sessions WHERE session_id = :sid"),
        {"sid": session_id},
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="会话不存在")
    for table in ("agent_messages", "intent_records", "emotion_records", "transfer_decisions"):
        db.execute(text(f"DELETE FROM {table} WHERE session_id = :sid"), {"sid": session_id})
    db.execute(text("DELETE FROM agent_sessions WHERE session_id = :sid"), {"sid": session_id})
    db.commit()
    return {"message": f"会话 {session_id} 已删除"}
