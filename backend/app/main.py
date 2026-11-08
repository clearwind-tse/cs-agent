# -*- coding: utf-8 -*-
"""
Agent CS Playbook 后端主入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import sqlalchemy

from app.config import get_settings
from app.models.database import get_engine, Base
# 导入所有模型以确保表被创建
from app.models.chat import RawChat, KnowledgeChunk, Session, Contact, LabeledConversation, StagingConversation, CustomConversation, KnowledgeArticle, Quiz, QuizAttempt
from app.models.quality import QualityInspectionConfigModel, QualityInspection
from app.models.user import User
from app.models.dialogue import DialogueSession, DialogueSet  # noqa: F401  确保 create_all 创建对话实训表
from app.models.agent_config import AgentConfig, IntentRecord, EmotionRecord, TransferDecision, AgentSession  # noqa: F401  新增子Agent相关模型
from app.models.ticket import Ticket  # noqa: F401  工单表
from app.models.dpo import DpoPreferencePair, SftTrainingSample, TrainingJob  # noqa: F401  DPO训练数据模型
from app.routers import chats, search, knowledge, export, filter, labeling, admin, custom, auth, extractor, quiz, cs_quality, qc_calibration, dialogue, agent, ticket, skills, mcp, training  # noqa: F401
from app.services.schema_sync import (
    ensure_legacy_raw_chat_schema,
    ensure_ticket_schema,
    ensure_session_schema,
    ensure_agent_session_schema,
)
from app.services.agent_initializer import load_all_agents_from_db
from app.models.database import get_session_local

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时创建数据库表
    print("[INFO] Creating database tables...")
    try:
        engine = get_engine()
        # 尝试启用 pgvector 扩展（仅 PostgreSQL 有效，SQLite 会跳过）
        try:
            with engine.connect() as conn:
                conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
                print("[INFO] pgvector extension enabled")
        except Exception as e:
            print(f"[INFO] pgvector extension skipped (non-PostgreSQL or not available): {e}")
        # 无论 pgvector 是否成功，都要创建表
        Base.metadata.create_all(bind=engine)
        added_columns = ensure_legacy_raw_chat_schema(engine)
        if added_columns:
            print(f"[INFO] Patched legacy raw_chats columns: {', '.join(added_columns)}")
        added_ticket_cols = ensure_ticket_schema(engine)
        if added_ticket_cols:
            print(f"[INFO] Patched legacy tickets columns: {', '.join(added_ticket_cols)}")
        added_session_cols = ensure_session_schema(engine)
        if added_session_cols:
            print(f"[INFO] Patched legacy sessions columns: {', '.join(added_session_cols)}")
        added_agent_cols = ensure_agent_session_schema(engine)
        if added_agent_cols:
            print(f"[INFO] Patched legacy agent_sessions columns: {', '.join(added_agent_cols)}")
        print("[INFO] Database tables ready")
    except Exception as e:
        print(f"[WARN] Database init failed: {e}")
        print("[INFO] Some features may not work without database")

    # 启动时从 DB 加载所有 active Agent（动态注册）
    try:
        db_session = get_session_local()()
        load_all_agents_from_db(db_session)
        db_session.close()
    except Exception as e:
        print(f"[WARN] Agent 初始化失败（非致命）: {e}")
        # 降级：只注册硬编码默认 Agent
        from app.services.agent_initializer import register_all_agents
        register_all_agents()
    yield
    # 关闭时清理
    print("[INFO] Shutting down...")


# 创建应用
app = FastAPI(
    title="Agent CS Playbook API",
    description="微信聊天记录知识库 API",
    version="1.0.0",
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Tos-Key", "X-Total-Examples", "X-Total-Rows", "X-Total-Tags", "X-Format", "X-Knowledge-Items", "Content-Disposition"],
)

# 注册路由
app.include_router(chats.router)
app.include_router(search.router)
app.include_router(knowledge.router)
app.include_router(export.router)
app.include_router(filter.router)
app.include_router(labeling.router)
app.include_router(admin.router)
app.include_router(custom.router)
app.include_router(auth.router)
app.include_router(extractor.router)
app.include_router(quiz.router)
app.include_router(qc_calibration.router)  # 注册在 cs_quality 之前：避免 /api/qc/{id} 抢占校准路径
app.include_router(cs_quality.router)
app.include_router(dialogue.router)
app.include_router(agent.router)  # 新增：子Agent管理路由
app.include_router(ticket.router)  # 新增：工单管理路由
app.include_router(skills.router)  # 新增：技能中心路由
app.include_router(mcp.router)     # 新增：MCP 配置管理路由
app.include_router(training.router)  # 新增：SFT/DPO 训练数据管理路由


@app.get("/")
def root():
    """根路径"""
    return {
        "name": "Agent CS Playbook API",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
def health_check():
    """健康检查"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug
    )
