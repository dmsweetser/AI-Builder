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
from agent_engine.tools.list_directory import ListDirectoryTool
from agent_engine.tools.list_directory_deep import ListDirectoryDeepTool
from agent_engine.tools.search_files import SearchFilesTool, SearchFilesDirTool
from agent_engine.tools.grep_code import GrepCodeTool, GrepCodeDirTool
from agent_engine.tools.read_file import ReadFileTool, ReadFileRangeTool
from agent_engine.tools.write_file import WriteFileTool
from agent_engine.tools.edit_file import EditFileTool
from agent_engine.tools.delete_file import DeleteFileTool
from agent_engine.tools.find_symbol import FindSymbolTool
from agent_engine.tools.decompile_jar import DecompileJarTool
from agent_engine.tools.check_syntax import CheckSyntaxTool
from agent_engine.tools.list_dependencies import ListDependenciesTool
from agent_engine.tools.get_file_info import GetFileInfoTool
from agent_engine.tools.create_tool import CreateToolTool
from agent_engine.tools.compress_context import CompressContextTool
from agent_engine.tools.respond_to_user import RespondToUserTool
from agent_engine.tools.request_user_input import RequestUserInputTool
from agent_engine.tools.task_completed import TaskCompletedTool

# ------------------------------------------------------------------
# Module-level singleton: shared across ALL projects and agent engines.
# Every engine uses this SAME registry — tools are always up-to-date.
# ------------------------------------------------------------------
_shared_registry: Optional["ToolRegistry"] = None


def get_registry(root_dir: str = None, enabled_tools=None) -> "ToolRegistry":
    """Return the shared ToolRegistry singleton.

    Always returns the same instance.  The first call creates it with
    the given root_dir; subsequent calls ignore root_dir and enabled_tools
    because the registry is global and unfiltered.

    NOTE: For tests that need a fresh registry, call ``_reset_registry()``
    first or use ``ToolRegistry(root_dir)`` directly.
    """
    global _shared_registry
    if _shared_registry is None:
        _shared_registry = ToolRegistry(root_dir or os.getcwd())
    return _shared_registry


def _reset_registry():
    """Reset the singleton.  For tests only."""
    global _shared_registry
    _shared_registry = None


class ToolRegistry:
    """Registry of all available tools.

    A true singleton shared by every agent engine and every API endpoint.
    All built-in tools are always registered.  Approved dynamic tools are
    loaded from disk and registered automatically — no filtering, no
    per-project tool lists.
    """

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self._tools: Dict[str, BaseTool] = {}
        self._register_tools()
        self._load_approved_tools()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _register_tools(self):
        """Register all built-in tool classes.  All tools are always available."""
        tool_classes = [
            ListDirectoryTool,
            ListDirectoryDeepTool,
            SearchFilesTool,
            SearchFilesDirTool,
            GrepCodeTool,
            GrepCodeDirTool,
            ReadFileTool,
            ReadFileRangeTool,
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
            RespondToUserTool,
            RequestUserInputTool,
            TaskCompletedTool,
        ]
        for tool_cls in tool_classes:
            tool = tool_cls(self.root_dir)
            self._tools[tool.name] = tool

    # ------------------------------------------------------------------
    # Dynamic tool loading (approved from pending)
    # ------------------------------------------------------------------

    @staticmethod
    def _pending_tools_file(root_dir: str) -> str:
        """Return the global pending tools file path (app-level, not per-project)."""
        from agent_engine.config import EngineConfig
        # Use the configured global path, but fall back to root_dir/output
        # for backwards compatibility with tests and legacy setups
        try:
            return EngineConfig.get_pending_tools_file()
        except Exception:
            return os.path.join(root_dir, "output", "pending_tools.json")

    def _load_approved_tools(self):
        """Load any previously-approved dynamic tools from disk.

        Approved tools are always loaded regardless of enabled_tools filter,
        because approval is an explicit user action that should make the tool
        available immediately.
        """
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

    def reload_approved_tools(self):
        """Reload approved tools from disk and register any new ones.

        Called after tool approval to make approved tools immediately
        available.  Since the registry is a shared singleton, this
        automatically makes new tools visible to ALL running engines.
        """
        self._load_approved_tools()

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
        """Register a dynamically-created tool from a pending entry.

        Supports two code styles:
        1. Class-based: defines a ``Tool`` class inheriting from ``BaseTool``.
        2. Function-based: defines an ``execute(**kwargs)`` function (legacy
           ``execute_python`` style).  A wrapper class is created automatically.
        """
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

        # Try class-based approach first
        tool_cls = ns.get('Tool')
        if tool_cls and isinstance(tool_cls, type) and issubclass(tool_cls, BaseTool):
            try:
                tool_instance = tool_cls(self.root_dir)
                self._tools[tool_name] = tool_instance
                return
            except Exception as e:
                logging.warning(f"Failed to instantiate dynamic tool class: {e}")

        # Fallback: function-based execute(**kwargs) wrapper
        execute_fn = ns.get('execute')
        if callable(execute_fn):
            class _DynamicFunctionTool(BaseTool):
                """Wrapper for function-based dynamic tools."""
                name = tool_name
                description = entry.get("description", "")
                parameters = entry.get("parameters", {})

                def __init__(self, root_dir: str):
                    super().__init__(root_dir)
                    self._execute_fn = execute_fn

                def execute(self, params: Dict[str, Any]) -> ToolResult:
                    try:
                        result = self._execute_fn(params=params)
                        if isinstance(result, ToolResult):
                            return result
                        return ToolResult(
                            success=True,
                            content=str(result),
                            summary=f"Executed {self.name}",
                        )
                    except Exception as e:
                        return ToolResult(
                            success=False,
                            content="",
                            error=str(e),
                            summary=f"Failed to execute {self.name}",
                        )

            try:
                tool_instance = _DynamicFunctionTool(self.root_dir)
                self._tools[tool_name] = tool_instance
                return
            except Exception as e:
                logging.warning(f"Failed to instantiate function-based dynamic tool: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for the LLM prompt."""
        return [t.get_definition() for t in self._tools.values()]

    def tool_names(self) -> set:
        """Return a set of all registered tool names (built-in + dynamic)."""
        return set(self._tools.keys())

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
