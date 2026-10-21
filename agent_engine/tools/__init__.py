"""Tool registry - aggregates all tools."""

import json
import logging
import os
import tempfile
import importlib.util
import uuid
from typing import Any, Dict, List, Optional
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root, validate_tool_params, SecurityError, ToolError
from agent_engine.tools.files import (
    ListDirectoryTool, SearchFilesTool, GrepCodeTool,
    ReadFileTool, WriteFileTool, EditFileTool, DeleteFileTool,
)
from agent_engine.tools.search import FindSymbolTool, DecompileJarTool
from agent_engine.tools.checkers import CheckSyntaxTool
from agent_engine.tools.misc import ListDependenciesTool, GetFileInfoTool, CreateToolTool, CompressContextTool


class ToolRegistry:
    """Registry of all available tools.

    Supports dynamically loading approved tools from
    ``aib_instance/pending_tools.json``.  When a tool is approved,
    its code is written to a temp file and imported so the tool
    becomes immediately available without a restart.
    """

    def __init__(self, root_dir: str, enabled_tools=None):
        self.root_dir = root_dir
        self._tools: Dict[str, BaseTool] = {}
        self._register_tools(enabled_tools=enabled_tools)
        self._load_approved_tools()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _register_tools(self, enabled_tools=None):
        """Register all built-in tool classes, optionally filtering."""
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
            CreateToolTool,
            CompressContextTool,
        ]
        # enabled_tools=None or [] means "use all tools"
        use_all = enabled_tools is None or len(enabled_tools) == 0
        for tool_cls in tool_classes:
            tool = tool_cls(self.root_dir)
            if use_all or tool.name in enabled_tools:
                self._tools[tool.name] = tool

    # ------------------------------------------------------------------
    # Dynamic tool loading (approved from pending)
    # ------------------------------------------------------------------

    @staticmethod
    def _pending_tools_file(root_dir: str) -> str:
        from agent_engine.config import EngineConfig
        return EngineConfig.get_pending_tools_file()

    def _load_approved_tools(self):
        """Load any previously-approved dynamic tools from disk."""
        pending_file = self._pending_tools_file(self.root_dir)
        if not os.path.exists(pending_file):
            return
        try:
            with open(pending_file, 'r') as f:
                pending_tools = json.load(f)
        except Exception:
            return

        for entry in pending_tools:
            if entry.get("status") == "approved":
                self._register_dynamic_tool(entry)

    def approve_tool(self, tool_id: str) -> Dict[str, Any]:
        """Approve a pending tool: mark it approved and register it."""
        pending_file = self._pending_tools_file(self.root_dir)
        pending_tools = []
        if os.path.exists(pending_file):
            try:
                with open(pending_file, 'r') as f:
                    pending_tools = json.load(f)
            except Exception:
                pending_tools = []

        for entry in pending_tools:
            if entry.get("id") == tool_id and entry.get("status") == "pending":
                entry["status"] = "approved"
                entry["approved_at"] = __import__("datetime").datetime.now().isoformat()
                with open(pending_file, 'w') as f:
                    json.dump(pending_tools, f, indent=2)
                self._register_dynamic_tool(entry)
                return {"status": "approved", "tool_id": tool_id, "tool_name": entry["name"]}

        return {"status": "not_found", "tool_id": tool_id}

    def reject_tool(self, tool_id: str) -> Dict[str, Any]:
        """Reject a pending tool: mark it rejected and unregister if loaded."""
        pending_file = self._pending_tools_file(self.root_dir)
        pending_tools = []
        if os.path.exists(pending_file):
            try:
                with open(pending_file, 'r') as f:
                    pending_tools = json.load(f)
            except Exception:
                pending_tools = []

        for entry in pending_tools:
            if entry.get("id") == tool_id and entry.get("status") == "pending":
                entry["status"] = "rejected"
                entry["rejected_at"] = __import__("datetime").datetime.now().isoformat()
                with open(pending_file, 'w') as f:
                    json.dump(pending_tools, f, indent=2)
                self._tools.pop(entry["name"], None)
                return {"status": "rejected", "tool_id": tool_id, "tool_name": entry["name"]}

        return {"status": "not_found", "tool_id": tool_id}

    def get_pending_tools(self) -> List[Dict[str, Any]]:
        """Return all pending (awaiting approval) tools."""
        pending_file = self._pending_tools_file(self.root_dir)
        if not os.path.exists(pending_file):
            return []
        try:
            with open(pending_file, 'r') as f:
                pending_tools = json.load(f)
            return [t for t in pending_tools if t.get("status") == "pending"]
        except Exception:
            return []

    def _register_dynamic_tool(self, entry: Dict[str, Any]):
        """Register a dynamically-created tool from a pending entry."""
        tool_name = entry["name"]
        tool_code = entry["code"]

        # Check if already registered
        if tool_name in self._tools:
            return

        # Build a namespace with all required names
        ns = {
            '__name__': f'_dynamic_tool_{uuid.uuid4().hex[:8]}',
            '__builtins__': __builtins__,
            'BaseTool': BaseTool,
            'ToolResult': ToolResult,
            'ToolError': ToolError,
            'ensure_under_root': ensure_under_root,
            'validate_tool_params': validate_tool_params,
            'SecurityError': SecurityError,
            'os': __import__('os'),
            'json': __import__('json'),
            're': __import__('re'),
            'subprocess': __import__('subprocess'),
            'tempfile': __import__('tempfile'),
            'shutil': __import__('shutil'),
            'threading': __import__('threading'),
            'datetime': __import__('datetime'),
        }

        try:
            exec(tool_code, ns)
        except Exception as e:
            logging.warning(f"Failed to execute dynamic tool code: {e}")
            return

        # The module namespace should define a Tool class
        tool_cls = ns.get('Tool')
        if tool_cls and isinstance(tool_cls, type) and issubclass(tool_cls, BaseTool):
            try:
                tool_instance = tool_cls(self.root_dir)
                self._tools[tool_name] = tool_instance
            except Exception as e:
                logging.warning(f"Failed to instantiate dynamic tool: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for the LLM prompt."""
        return [t.get_definition() for t in self._tools.values()]

    def execute(self, tool_name: str, params: Dict[str, Any]) -> ToolResult:
        """Execute a tool by name with validated parameters."""
        tool = self._tools.get(tool_name)
        if not tool:
            available = [t.name for t in self._tools.values()]
            raise ToolError(f"Unknown tool: {tool_name}. Available: {available}")

        schema = tool.parameters
        validated = validate_tool_params(params, schema)
        merged = {**validated}
        for k, v in params.items():
            if k not in merged:
                merged[k] = v

        try:
            return tool.execute(merged)
        except SecurityError:
            raise
        except ToolError:
            raise
        except Exception as e:
            return ToolResult(False, "", error=f"Unexpected error: {e}")
