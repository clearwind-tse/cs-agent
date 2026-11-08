# -*- coding: utf-8 -*-
"""
应用配置
"""
from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    """应用设置"""
    
    # 数据库配置（默认与 Docker / 线上保持一致）
    database_url: str = "postgresql://postgres:postgres@localhost:5432/agent_cs_playbook"
    
    # OpenAI 配置
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    
    # DeepSeek 配置
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    
    # 云端 Embedding API（DashScope / Ark，OpenAI 兼容接口）
    ark_api_key: str = ""
    ark_embedding_model: str = "text-embedding-v3"
    ark_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    # 豆包视觉理解模型（火山方舟）
    ark_vision_api_key: str = ""  # 火山方舟独立 API Key（与 DashScope 的 ark_api_key 不同）
    ark_vision_model: str = "ep-20260325211910-2s55z"
    ark_vision_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    
    # 微信数据库路径（默认与 docker-compose 挂载源保持一致）
    wechat_db_path: str = "../Msg/Msg"
    
    # 微信语音文件路径
    voice_file_path: str = "../FileStorage/Voice"
    
    # 火山引擎 OSS (TOS) 配置
    tos_access_key: str = ""
    tos_secret_key: str = ""
    tos_endpoint: str = ""        # e.g. https://tos-cn-beijing.volces.com
    tos_region: str = "cn-beijing"
    tos_bucket: str = ""
    tos_path_prefix: str = ""   # TOS 路径前缀，区分环境（如 dev/ prod/）
    
    # RAG 检索配置
    rag_article_similarity_threshold: float = 0.55   # knowledge_articles 最低相似度
    rag_chunk_similarity_threshold: float = 0.40     # knowledge_chunks 最低相似度
    rag_llm_max_tokens: int = 1500                   # LLM 回答最大 token 数
    rag_context_max_chars: int = 6000                 # 拼给 LLM 的上下文最大字符数
    
    # 知识库构建配置
    chunk_time_window_seconds: int = 300             # 切片时间窗口（秒）
    chunk_min_messages: int = 3                      # 最少消息数
    chunk_max_messages: int = 30                     # 最多消息数
    chunk_min_content_length: int = 80               # chunk 最低字数门槛
    chunk_min_quality_score: float = 0.4             # chunk 最低质量分（0~1）
    
    # JWT 认证配置
    jwt_secret_key: str = "agent-cs-playbook-dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    # 服务配置
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = True
    app_env: str = "dev"       # dev / prod，区分本地和线上环境

    # 自动流水线：智能客服会话关闭推送进 raw_chats 后，是否自动跑 清洗→质检→知识提炼
    auto_pipeline_on_push: bool = True
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
