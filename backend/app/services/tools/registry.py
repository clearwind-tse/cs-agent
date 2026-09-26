# -*- coding: utf-8 -*-
"""
工具注册表（单例）

管理所有可被子Agent调用的工具，类似教材 Ch11/Ch14 提到的 MCP 协议。
"""
from typing import Dict, List, Optional

from . import BaseTool


class ToolRegistry:
    """工具注册表（单例）"""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        if not tool.tool_name:
            raise ValueError("Tool must have a tool_name")
        self._tools[tool.tool_name] = tool

    def unregister(self, tool_name: str):
        self._tools.pop(tool_name, None)

    def get(self, tool_name: str) -> Optional[BaseTool]:
        return self._tools.get(tool_name)

    def list_all(self) -> List[BaseTool]:
        return list(self._tools.values())

    def has(self, tool_name: str) -> bool:
        return tool_name in self._tools


# 全局单例
_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
        _register_default_tools()
    return _tool_registry


def _register_default_tools():
    """注册默认工具（模拟数据，实际项目替换为真实服务调用）"""
    from . import (
        MockOrderTool,
        MockLogisticsTool,
        CreateTicketTool,
        ListRecentOrdersTool,
        SubmitRefundTool,
    )
    registry = get_tool_registry()
    registry.register(MockOrderTool())
    registry.register(MockLogisticsTool())
    registry.register(CreateTicketTool())
    registry.register(ListRecentOrdersTool())
    registry.register(SubmitRefundTool())
    print(f"[ToolRegistry] 已注册 {len(registry.list_all())} 个默认工具")
