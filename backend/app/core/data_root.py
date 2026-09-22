# -*- coding: utf-8 -*-
"""
数据文件根路径工具

与 DataClaw 保持一致的约定：data/ 目录下存放 skills.json / mcp_servers.json 等 JSON 配置
"""
from pathlib import Path
from functools import lru_cache

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # backend/app/core → ai-sale-course


@lru_cache()
def get_data_root() -> Path:
    """返回 data/ 目录，自动创建"""
    p = PROJECT_ROOT / "data"
    p.mkdir(exist_ok=True)
    return p


@lru_cache()
def get_workspace_root() -> Path:
    """返回 workspace/ 目录（类似 DataClaw），存放 SKILL.md 文件夹"""
    p = PROJECT_ROOT / "workspace"
    p.mkdir(exist_ok=True)
    return p
