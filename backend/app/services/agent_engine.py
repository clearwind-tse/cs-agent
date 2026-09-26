# -*- coding: utf-8 -*-
"""
客服 Agent 引擎选择器

支持两套编排引擎，对外契约完全一致（都有 process_message）：
  - deepagents（默认）：deepagents 框架，规划 + 子代理 + 虚拟文件系统
  - langgraph：手写 StateGraph 状态机（旧实现，保留作对照/回退）

切换方式：环境变量 AGENT_ENGINE=deepagents|langgraph（默认 deepagents）。
"""

from __future__ import annotations

import os
from typing import Any, Optional


def current_engine() -> str:
    return (os.getenv("AGENT_ENGINE", "deepagents") or "deepagents").strip().lower()


def get_customer_agent(db=None) -> Any:
    """返回当前引擎的编排器实例"""
    if current_engine() == "langgraph":
        from app.services.langgraph_agent import get_langgraph_agent
        return get_langgraph_agent(db)
    from app.services.deep_agent import get_deep_agent
    return get_deep_agent(db)
