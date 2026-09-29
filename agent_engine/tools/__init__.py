"""Tool registry - aggregates all tools."""

import logging
from typing import Any, Dict, List
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root, validate_tool_params, SecurityError, ToolError
from agent_engine.tools.files import (
    ListDirectoryTool, SearchFilesTool, GrepCodeTool,
    ReadFileTool, WriteFileTool, EditFileTool, DeleteFileTool,
)
from agent_engine.tools.search import FindSymbolTool, DecompileJarTool
from agent_engine.tools.checkers import CheckSyntaxTool
from agent_engine.tools.misc import ListDependenciesTool, GetFileInfoTool


class ToolRegistry:
    """Registry of all available tools."""

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self._tools: Dict[str, BaseTool] = {}
        self._register_tools()

    def _register_tools(self):
        """Register all tool classes."""
        tool_classes = [
            ListDirectoryTool,
            SearchFilesTool,
            GrepCodeTool,
            ReadFileTool,
            WriteFileTool,
            EditFileTool,
            DeleteFileTool,
            FindSymbolTool,
            DecompileJarTool,
            ListDependenciesTool,
            CheckSyntaxTool,
            GetFileInfoTool,
        ]
        for tool_cls in tool_classes:
            tool = tool_cls(self.root_dir)
            self._tools[tool.name] = tool

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for the LLM prompt."""
        return [t.get_definition() for t in self._tools.values()]

    def execute(self, tool_name: str, params: Dict[str, Any]) -> ToolResult:
        """Execute a tool by name with validated parameters."""
        tool = self._tools.get(tool_name)
        if not tool:
            available = [t.name for t in self._tools.values()]
            raise ToolError(f"Unknown tool: {tool_name}. Available: {available}")

        # Validate required params (schema defines which are required)
        schema = tool.parameters
        validated = validate_tool_params(params, schema)

        # Merge validated + any extra optional params the tool might need
        merged = {**validated}
        for k, v in params.items():
            if k not in merged:
                merged[k] = v

        # Execute
        try:
            return tool.execute(merged)
        except SecurityError:
            raise
        except ToolError:
            raise
        except Exception as e:
            return ToolResult(False, "", error=f"Unexpected error: {e}")
