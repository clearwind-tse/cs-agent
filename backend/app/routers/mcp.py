# -*- coding: utf-8 -*-
"""
MCP Server 配置管理路由

设计参考 DataClaw backend/app/api/mcp.py：
- 存储在 data/mcp_servers.json（JSON 文件，无 DB 表）
- 支持 stdio / SSE / streamableHttp 三种连接模式
- GET 列表时批量异步健康检查（使用 mcp SDK 实际连接测试）
- 健康状态自动持久化回 JSON
"""
import asyncio
import json
import os
import uuid
from contextlib import AsyncExitStack
from typing import List, Optional
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.data_root import get_data_root

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    HAS_MCP_SDK = True
except ImportError:
    HAS_MCP_SDK = False

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

MCP_FILE = str(get_data_root() / "mcp_servers.json")


# ==================== Pydantic 模型 ====================

class McpServerCreate(BaseModel):
    name: str
    description: Optional[str] = None
    type: str = Field(..., pattern="^(stdio|sse|streamableHttp)$", description="连接模式：stdio / sse / streamableHttp")
    command: Optional[str] = None          # stdio 模式：可执行命令
    args: Optional[list] = None            # stdio 模式：命令行参数
    url: Optional[str] = None              # sse/streamableHttp 模式：服务地址
    headers: Optional[dict] = None         # SSE/HTTP 请求头
    env: Optional[dict] = None             # 环境变量（stdio 模式）
    project_id: Optional[int] = None


class McpServerUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list] = None
    url: Optional[str] = None
    headers: Optional[dict] = None
    env: Optional[dict] = None
    status: Optional[str] = None


class McpServer(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    type: str
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    headers: Optional[dict] = None
    env: Optional[dict] = None
    project_id: Optional[int] = None
    status: str = "disconnected"          # connected / disconnected / error:...
    created_at: str = ""
    updated_at: str = ""


# ==================== 工具函数 ====================

def _load() -> List[dict]:
    if not os.path.exists(MCP_FILE):
        return []
    try:
        with open(MCP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save(data: List[dict]):
    os.makedirs(os.path.dirname(MCP_FILE), exist_ok=True)
    with open(MCP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_response(item: dict) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "description": item.get("description"),
        "type": item.get("type") or item.get("server_type", "stdio"),
        "command": item.get("command"),
        "args": item.get("args"),
        "url": item.get("url"),
        "headers": item.get("headers"),
        "env": item.get("env"),
        "project_id": item.get("project_id"),
        "status": item.get("status", "disconnected"),
        "created_at": item.get("created_at", ""),
        "updated_at": item.get("updated_at", ""),
    }


async def _check_single_mcp_health(server: dict) -> str:
    """对单个 MCP Server 做实际连接健康检查，返回 status 字符串"""
    if not HAS_MCP_SDK:
        # 无 SDK 时退化为配置完整性检查
        st = server.get("type") or server.get("server_type")
        if st == "stdio":
            return "connected" if server.get("command") else "error: config incomplete"
        return "connected" if server.get("url") else "error: config incomplete"
    try:
        async with AsyncExitStack() as stack:
            server_type = server.get("type") or server.get("server_type", "stdio")
            if server_type == "stdio":
                params = StdioServerParameters(
                    command=server.get("command") or "",
                    args=server.get("args") or [],
                    env=server.get("env"),
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif server_type in ("sse", "streamableHttp"):
                url = server.get("url") or ""
                extra_headers = server.get("headers") or {}
                read, write = await stack.enter_async_context(
                    sse_client(url, headers=extra_headers if extra_headers else None)
                )
            else:
                return "error: unsupported type"

            session = await stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(session.initialize(), timeout=5.0)
            return "connected"
    except asyncio.TimeoutError:
        return "error: connection timeout"
    except Exception as e:
        err_msg = str(e)
        if "unhandled errors in a TaskGroup" in err_msg:
            return "error: connection refused"
        return f"error: {err_msg or 'unknown'}"


async def _batch_check_health(servers: List[dict]) -> List[tuple]:
    """批量并发健康检查，返回 (index, status) 列表"""
    tasks = [_check_single_mcp_health(s) for s in servers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [(i, r if isinstance(r, str) else f"error: {r}") for i, r in enumerate(results)]


# ==================== API 端点 ====================

@router.get("/servers", response_model=List[McpServer])
@router.get("", response_model=List[McpServer])
async def list_servers(project_id: Optional[int] = None):
    """列出所有 MCP Server 配置，并自动执行批量健康检查"""
    servers = _load()
    if project_id is not None:
        # 与 skills 接口保持一致：项目过滤时也包含全局（project_id 为 null）配置，
        # 否则全局 MCP Server 在带 project_id 的请求下会被错误过滤掉。
        servers = [s for s in servers if s.get("project_id") == project_id or s.get("project_id") is None]

    # 批量异步健康检查
    if servers and HAS_MCP_SDK:
        results = await _batch_check_health(servers)
        for idx, status in results:
            servers[idx]["status"] = status
            servers[idx]["updated_at"] = _now_str()
        _save(servers)
    elif servers:
        # 无 SDK 时做配置完整性检查
        for s in servers:
            st = s.get("type") or s.get("server_type")
            if st == "stdio":
                s["status"] = "connected" if s.get("command") else "error: config incomplete"
            elif st in ("sse", "streamableHttp"):
                s["status"] = "connected" if s.get("url") else "error: config incomplete"
            else:
                s["status"] = "disconnected"
            s["updated_at"] = _now_str()
        _save(servers)

    return [_to_response(s) for s in servers]


@router.get("/servers/{server_id}", response_model=McpServer)
@router.get("/{server_id}", response_model=McpServer)
def get_server(server_id: str):
    """查询单个 MCP Server"""
    for s in _load():
        if s["id"] == server_id:
            return _to_response(s)
    raise HTTPException(status_code=404, detail="MCP Server not found")


@router.post("/servers", response_model=McpServer)
@router.post("", response_model=McpServer)
def create_server(req: McpServerCreate):
    """创建 MCP Server 配置"""
    servers = _load()
    now = _now_str()
    entry = {
        "id": str(uuid.uuid4()),
        "name": req.name,
        "description": req.description,
        "type": req.type,
        "command": req.command,
        "args": req.args or [],
        "url": req.url,
        "headers": req.headers,
        "env": req.env,
        "project_id": req.project_id,
        "status": "disconnected",
        "created_at": now,
        "updated_at": now,
    }
    servers.append(entry)
    _save(servers)
    return _to_response(entry)


@router.put("/servers/{server_id}", response_model=McpServer)
@router.put("/{server_id}", response_model=McpServer)
def update_server(server_id: str, req: McpServerUpdate):
    """更新 MCP Server 配置"""
    servers = _load()
    for i, s in enumerate(servers):
        if s["id"] == server_id:
            update = req.model_dump(exclude_unset=True)
            servers[i].update(update)
            servers[i]["updated_at"] = _now_str()
            _save(servers)
            return _to_response(servers[i])
    raise HTTPException(status_code=404, detail="MCP Server not found")


@router.delete("/servers/{server_id}")
@router.delete("/{server_id}")
def delete_server(server_id: str):
    """删除 MCP Server 配置"""
    servers = _load()
    before = len(servers)
    servers = [s for s in servers if s["id"] != server_id]
    if len(servers) == before:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    _save(servers)
    return {"message": "deleted"}
