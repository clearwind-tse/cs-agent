# -*- coding: utf-8 -*-
"""
MCP 客户端工具

提供对已配置的 MCP Server 的工具调用能力。
在 Agent 注册时按需建立连接，调用完毕后断开，避免长连接占用资源。
"""
import asyncio
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from app.routers.mcp import _load as _load_mcp_servers
from app.core.data_root import get_data_root

try:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp.client.sse import sse_client
    HAS_MCP_SDK = True
except ImportError:
    HAS_MCP_SDK = False

# 连接缓存：server_id -> (session, stack) 的异步单例（进程级）
# 由于工具调用是同步的，实际每次调用都会重新建立连接（保证原子性）
_CACHE: Dict[str, Any] = {}


def _find_server(server_id: str) -> Optional[dict]:
    servers = _load_mcp_servers()
    return next((s for s in servers if s["id"] == server_id), None)


def _run_coro_sync(coro):
    """
    在「同步上下文」和「已在事件循环中的异步上下文」下都能安全执行协程。

    - 无运行中的事件循环：直接 asyncio.run
    - 已处于事件循环中（如 async 路由 /message/stream 内同步调用工具）：
      放到独立线程执行，避免 "asyncio.run() cannot be called from a running event loop"
    """
    try:
        asyncio.get_running_loop()
        has_loop = True
    except RuntimeError:
        has_loop = False
    if not has_loop:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


def call_mcp_tool(server_id: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None, retries: int = 2) -> Dict[str, Any]:
    """
    同步调用指定 MCP Server 的工具（内部通过 asyncio.run 包装）。

    Returns:
        {"success": bool, "data": Any, "error": Optional[str]}
    """
    if not HAS_MCP_SDK:
        return {"success": False, "data": None, "error": "MCP SDK 未安装（pip install mcp）"}

    server = _find_server(server_id)
    if not server:
        return {"success": False, "data": None, "error": f"MCP Server '{server_id}' 未找到"}

    last_err = None
    for attempt in range(retries + 1):
        try:
            result = _run_coro_sync(_call_mcp_tool_async(server, tool_name, arguments or {}))
            if result.get("success") or attempt == retries:
                return result
            last_err = result.get("error")
        except Exception as e:
            last_err = str(e)
    return {"success": False, "data": None, "error": last_err or "MCP 调用失败"}


def list_mcp_tools(server_id: str) -> List[Dict[str, Any]]:
    """
    列出指定 MCP Server 暴露的工具（同步包装）。

    用途：Agent 注册 MCP 工具时，把可用子工具清单写进工具描述，
    让 LLM 知道该用哪个 tool_name 调用（否则 LLM 面对统一入口无从下手）。
    失败时返回空列表（降级为通用描述，不影响主流程）。
    """
    if not HAS_MCP_SDK:
        return []
    server = _find_server(server_id)
    if not server:
        return []
    try:
        return _run_coro_sync(_list_mcp_tools_async(server))
    except Exception as e:
        print(f"[mcp_client] list_mcp_tools({server_id}) 失败: {e}")
        return []


async def _list_mcp_tools_async(server: dict) -> List[Dict[str, Any]]:
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
            headers = server.get("headers") or {}
            read, write = await stack.enter_async_context(
                sse_client(url, headers=headers if headers else None)
            )
        else:
            return []
        session = await stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=10.0)
        res = await session.list_tools()
        tools = res.tools if hasattr(res, "tools") else []
        return [
            {"name": t.name, "description": getattr(t, "description", "") or ""}
            for t in tools
        ]


async def _call_mcp_tool_async(server: dict, tool_name: str, arguments: dict) -> Dict[str, Any]:
    """实际异步调用逻辑，外部通过 asyncio.run 包装"""
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
            headers = server.get("headers") or {}
            read, write = await stack.enter_async_context(
                sse_client(url, headers=headers if headers else None)
            )
        else:
            return {"success": False, "data": None, "error": f"不支持的 MCP 类型: {server_type}"}

        session = await stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=10.0)

        # 列出可用工具并查找目标
        list_result = await session.list_tools()
        available_tools = list_result.tools if hasattr(list_result, 'tools') else []
        target = next((t for t in available_tools if t.name == tool_name), None)
        if not target:
            names = [t.name for t in available_tools]
            return {
                "success": False,
                "data": None,
                "error": f"工具 '{tool_name}' 不存在（可用: {', '.join(names[:10])}）",
            }

        # 调用工具：加超时（修复缺陷10：避免 server 挂起导致请求永久阻塞）
        try:
            call_result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments), timeout=15.0
            )
        except asyncio.TimeoutError:
            return {"success": False, "data": None, "error": "MCP 工具调用超时（>15s）"}

        # 解析结果文本
        content_parts = []
        if hasattr(call_result, 'content'):
            for block in call_result.content:
                if hasattr(block, 'text'):
                    content_parts.append(str(block.text))
                elif isinstance(block, dict) and 'text' in block:
                    content_parts.append(str(block['text']))
        text = "\n".join(content_parts)
        return {"success": True, "data": {"text": text, "raw": str(call_result)}, "error": None}
