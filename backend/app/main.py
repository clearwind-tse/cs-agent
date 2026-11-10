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
from app.models.media import MediaAsset  # noqa: F401  AI 创作素材表（文件落本地磁盘）
from app.models.media_category import MediaCategory  # noqa: F401  素材库二级目录
from app.models.media_kind_label import MediaKindLabel  # noqa: F401  一级目录自定义显示名
from app.models.studio_task import StudioTask  # noqa: F401  两阶段出图任务表
from app.models.model_setting import ModelSetting  # noqa: F401  各板块模型选择（DB override）
from app.models.image_endpoint import ImageEndpoint, ImageEndpointBinding, ImageProcessJob  # noqa: F401  图像端点池 / 绑定 / 即席处理
from app.routers import chats, search, knowledge, export, filter, labeling, admin, custom, auth, extractor, quiz, cs_quality, qc_calibration, dialogue, agent, ticket, skills, mcp, training, media, studio, model_settings, image_endpoints as image_endpoints_router  # noqa: F401
from app.services.schema_sync import (
    ensure_legacy_raw_chat_schema,
    ensure_ticket_schema,
    ensure_session_schema,
    ensure_agent_session_schema,
    ensure_media_asset_schema,
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
        added_media_cols = ensure_media_asset_schema(engine)
        if added_media_cols:
            print(f"[INFO] Patched legacy media_assets columns: {', '.join(added_media_cols)}")
        print("[INFO] Database tables ready")
    except Exception as e:
        print(f"[WARN] Database init failed: {e}")
        print("[INFO] Some features may not work without database")

    # 预置素材库二级目录；只补缺失项，用户自建的自定义目录不受影响
    try:
        from app.services import media_categories

        seed_db = get_session_local()()
        try:
            seeded = media_categories.seed_builtin_categories(seed_db)
            if seeded:
                print(f"[INFO] Seeded {seeded} builtin media categories")
        finally:
            seed_db.close()
    except Exception as e:
        print(f"[WARN] Media categories seed skipped: {e}")

    # 图像端点池：只保证内置兜底端点与每个服务的默认链存在，不覆盖用户自建端点/绑定
    try:
        from app.services import image_endpoints

        endpoint_db = get_session_local()()
        try:
            seeded = image_endpoints.seed_mock_endpoint(endpoint_db)
            if seeded:
                print(f"[INFO] Seeded {seeded} image endpoint/binding defaults")
        finally:
            endpoint_db.close()
    except Exception as e:
        print(f"[WARN] Image endpoint seed skipped: {e}")

    # 进程重启后，上一轮被打断的 generating 任务不会有任何回调。
    # 启动即扫一次，把它们标成 failed，前端就能直接点「重跑」。
    try:
        from app.services import studio_task_service

        startup_db = get_session_local()()
        try:
            swept = studio_task_service.recover_interrupted_tasks(startup_db)
            if swept:
                print(f"[INFO] Recovered {swept} interrupted studio task(s)")
        finally:
            startup_db.close()
    except Exception as e:
        print(f"[WARN] Studio stale sweep skipped: {e}")

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
app.include_router(media.router)     # 新增：AI 创作素材库（本地磁盘存储）
app.include_router(studio.router)    # 新增：两阶段出图任务（规划 → 确认 → 执行）
app.include_router(model_settings.router)  # 新增：设置页 · 各板块模型选择
app.include_router(image_endpoints_router.router)  # 新增：AI 创作 · 图像端点池 / 绑定 / 单图即席处理

# 素材文件静态直出：/api/media/files/{年}/{月}/{uuid}.{ext}
# 必须放在 media.router 之后注册：router 的 /api/media/{asset_id} 只吃一段，
# 不会抢 /api/media/files/... 这类多段路径，但仍按顺序排好避免以后改动时踩到。
from fastapi.staticfiles import StaticFiles  # noqa: E402
from app.services.media_store import get_media_root  # noqa: E402

app.mount(
    settings.media_url_prefix.rstrip("/"),
    StaticFiles(directory=str(get_media_root())),
    name="media",
)


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
    import os
    import uvicorn

    # 开发态只监听代码目录。data/media 每写出一张图都会变化，一旦被 reload 监控到，
    # 出图过程中进程就会重启，进程内的 BackgroundTasks 直接被打死（任务永远卡在 generating）。
    # 命令行启动时同样要带 --reload-dir app，见 README「本地开发」。
    reload_kwargs = {}
    if settings.debug:
        reload_kwargs = {
            "reload_dirs": [os.path.dirname(os.path.abspath(__file__))],
            "reload_excludes": ["*/data/media/*"],
        }
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        **reload_kwargs,
    )
