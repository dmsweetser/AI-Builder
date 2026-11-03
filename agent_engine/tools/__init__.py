"""Tool registry - aggregates all tools.

A module-level static registry (created once at import).
Tool *definitions* (classes + dynamic tools) are shared.
Tool *instances* are created per-execution with the correct project root_dir,
so each project's tools operate on its own directory.

Global enable/disable is managed via the ``_enabled_tools`` set — when
non-empty, only those tools are available; when empty, all are available.
"""

import json
import logging
import os
import tempfile
import importlib.util
import uuid
from typing import Any, Dict, List, Optional, Set, Type
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
# Module-level static registry — created exactly once at import.
# No singleton pattern, no reset, no recreation.
# ------------------------------------------------------------------
_registry: Optional["ToolRegistry"] = None

# ------------------------------------------------------------------
# Global built-in tool class registry — maps name → class.
# Populated once at module import and never changes.
# ------------------------------------------------------------------
_BUILTIN_TOOL_CLASSES: Dict[str, Type[BaseTool]] = {}


def _init_builtin_classes():
    """Populate _BUILTIN_TOOL_CLASSES with all built-in tool classes."""
    for _cls in [
        ListDirectoryTool, ListDirectoryDeepTool,
        SearchFilesTool, SearchFilesDirTool,
        GrepCodeTool, GrepCodeDirTool,
        ReadFileTool, ReadFileRangeTool,
        WriteFileTool, EditFileTool, DeleteFileTool,
        FindSymbolTool, DecompileJarTool,
        ListDependenciesTool, CheckSyntaxTool, GetFileInfoTool,
        CreateToolTool, CompressContextTool,
        RespondToUserTool, RequestUserInputTool, TaskCompletedTool,
    ]:
        _instance = _cls("/tmp")
        _BUILTIN_TOOL_CLASSES[_instance.name] = _cls


_init_builtin_classes()


def get_registry(_root_dir=None):
    """Return the module-level static ToolRegistry.

    This is created exactly once at module import and never recreated.
    All agent engines share this same instance.

    The ``_root_dir`` parameter is accepted for backward compatibility
    but is ignored — the registry is shared across all projects.
    """
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def _reset_registry():
    """Reset the registry for tests only.

    Clears the singleton and reloads approved tools from disk.
    This ensures tests start with a clean slate.
    """
    global _registry
    _registry = None
    # Force re-initialization on next get_registry() call
    # The ToolRegistry.__init__ will call _load_approved_tools()


class ToolRegistry:
    """Registry of all available tools.

    A module-level static instance shared by every agent engine and
    every API endpoint. Tool *definitions* (classes + dynamic entries)
    are shared. Tool *instances* are created per-execution with the
    correct root_dir.

    Global enable/disable: when ``_enabled_tools`` is non-empty, only
    those tools are available; when empty, all are available.
    """

    def __init__(self):
        # Dynamic tool entries loaded from disk (approved tools)
        self._dynamic_entries: Dict[str, Dict[str, Any]] = {}
        # Global enabled/disabled set — empty means "all enabled"
        self._enabled_tools: Set[str] = set()
        # One-time load: populate _dynamic_entries from disk immediately
        self._load_approved_tools()

    # ------------------------------------------------------------------
    # Dynamic tool loading (approved from pending)
    # ------------------------------------------------------------------

    @staticmethod
    def _pending_tools_file() -> str:
        """Return the global pending tools file path (app-level)."""
        from agent_engine.config import EngineConfig
        try:
            return EngineConfig.get_pending_tools_file()
        except Exception:
            return os.path.join(os.getcwd(), "output", "pending_tools.json")

    def _load_approved_tools(self):
        """Load any previously-approved dynamic tools from disk.

        Only ADDS new approved tools — never removes or clears existing
        entries. This is idempotent and safe to call multiple times.
        """
        pending_file = self._pending_tools_file()
        if not os.path.exists(pending_file):
            return
        try:
            with open(pending_file, 'r') as f:
                pending_tools = json.load(f)
        except Exception:
            return

        for entry in pending_tools:
            if entry.get("status") == "approved":
                # Only add if not already present (idempotent)
                if entry["name"] not in self._dynamic_entries:
                    self._dynamic_entries[entry["name"]] = entry

    def approve_tool(self, tool_id: str) -> Dict[str, Any]:
        """Approve a pending tool: mark it approved and register it."""
        pending_file = self._pending_tools_file()
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
                # Register immediately — no need to wait for reload
                self._dynamic_entries[entry["name"]] = entry
                return {"status": "approved", "tool_id": tool_id, "tool_name": entry["name"]}

        return {"status": "not_found", "tool_id": tool_id}

    def reload_approved_tools(self):
        """Reload approved tools from disk and register any new ones.

        Safe to call multiple times — only adds new approved tools,
        never removes existing ones.
        """
        self._load_approved_tools()

    def reject_tool(self, tool_id: str) -> Dict[str, Any]:
        """Reject a pending tool: mark it rejected and unregister if loaded."""
        pending_file = self._pending_tools_file()
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
                self._dynamic_entries.pop(entry["name"], None)
                return {"status": "rejected", "tool_id": tool_id, "tool_name": entry["name"]}

        return {"status": "not_found", "tool_id": tool_id}

    def get_pending_tools(self) -> List[Dict[str, Any]]:
        """Return all pending (awaiting approval) tools."""
        pending_file = self._pending_tools_file()
        if not os.path.exists(pending_file):
            return []
        try:
            with open(pending_file, 'r') as f:
                pending_tools = json.load(f)
            return [t for t in pending_tools if t.get("status") == "pending"]
        except Exception:
            return []

    def get_approved_tools(self) -> List[Dict[str, Any]]:
        """Return all approved dynamic tool entries."""
        return list(self._dynamic_entries.values())

    # ------------------------------------------------------------------
    # Global enable/disable
    # ------------------------------------------------------------------

    def set_tool_enabled(self, tool_name: str, enabled: bool) -> Dict[str, Any]:
        """Enable or disable a built-in tool globally."""
        if tool_name in _BUILTIN_TOOL_CLASSES:
            if enabled:
                self._enabled_tools.discard(tool_name)
            else:
                self._enabled_tools.add(tool_name)
            return {"status": "updated", "tool": tool_name, "enabled": enabled}
        elif tool_name in self._dynamic_entries:
            if enabled:
                self._enabled_tools.discard(tool_name)
            else:
                self._enabled_tools.add(tool_name)
            return {"status": "updated", "tool": tool_name, "enabled": enabled}
        else:
            return {"status": "not_found", "tool": tool_name}

    def get_enabled_tools(self) -> List[str]:
        """Return the list of currently enabled tool names."""
        all_names = set(_BUILTIN_TOOL_CLASSES.keys()) | set(self._dynamic_entries.keys())
        if not self._enabled_tools:
            return sorted(all_names)
        return sorted(all_names - self._enabled_tools)

    def get_tool_status(self) -> Dict[str, bool]:
        """Return a dict of tool_name → enabled for all known tools."""
        all_names = set(_BUILTIN_TOOL_CLASSES.keys()) | set(self._dynamic_entries.keys())
        return {name: name not in self._enabled_tools for name in sorted(all_names)}

    # ------------------------------------------------------------------
    # Tool instance creation (per-execution with correct root_dir)
    # ------------------------------------------------------------------

    def _create_tool_instance(self, tool_name: str, root_dir: str) -> Optional[BaseTool]:
        """Create a tool instance for execution.

        Returns None if the tool is disabled or not found.
        """
        # Check if disabled
        if tool_name in self._enabled_tools:
            return None

        # Built-in tool
        if tool_name in _BUILTIN_TOOL_CLASSES:
            cls = _BUILTIN_TOOL_CLASSES[tool_name]
            try:
                return cls(root_dir)
            except Exception as e:
                logging.warning(f"Failed to instantiate built-in tool '{tool_name}': {e}")
                return None

        # Dynamic tool — instantiate from entry
        if tool_name in self._dynamic_entries:
            entry = self._dynamic_entries[tool_name]
            tool_code = entry["code"]
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
                return None

            tool_cls = ns.get('Tool')
            if tool_cls and isinstance(tool_cls, type) and issubclass(tool_cls, BaseTool):
                try:
                    return tool_cls(root_dir)
                except Exception as e:
                    logging.warning(f"Failed to instantiate dynamic tool class: {e}")
                    return None

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
                    return _DynamicFunctionTool(root_dir)
                except Exception as e:
                    logging.warning(f"Failed to instantiate function-based dynamic tool: {e}")
                    return None

        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for the LLM prompt.

        Only includes tools that are enabled (not in _enabled_tools set).
        """
        defs = []
        for name, cls in _BUILTIN_TOOL_CLASSES.items():
            if name not in self._enabled_tools:
                try:
                    defs.append(cls("/tmp").get_definition())
                except Exception:
                    pass
        for name, entry in self._dynamic_entries.items():
            if name not in self._enabled_tools:
                defs.append({
                    "name": entry["name"],
                    "description": entry.get("description", ""),
                    "parameters": entry.get("parameters", {}),
                })
        return defs

    def tool_names(self) -> set:
        """Return a set of all registered tool names (built-in + dynamic)."""
        return set(_BUILTIN_TOOL_CLASSES.keys()) | set(self._dynamic_entries.keys())

    def execute(self, tool_name: str, params: Dict[str, Any], root_dir: str) -> ToolResult:
        """Execute a tool by name with validated parameters.

        Creates a tool instance with the given root_dir for this execution.
        """
        tool = self._create_tool_instance(tool_name, root_dir)
        if not tool:
            available = [t for t in _BUILTIN_TOOL_CLASSES.keys() if t not in self._enabled_tools]
            available += [n for n in self._dynamic_entries.keys() if n not in self._enabled_tools]
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
