"""Tool registry — aggregates all tools.

A module-level static registry (created once at import).
Tool *definitions* (classes + dynamic tools) are shared.
Tool *instances* are created per-execution with the correct project root_dir.

Per-project tool loading: each project can have its own set of
project-local tools (stored in its tools/active/ directory) and
can disable specific built-in tools via projects.json disabled_tools field.
"""

import json
import logging
import os
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
from agent_engine.tools.create_tool import CreateToolTool
from agent_engine.tools.respond_to_user import RespondToUserTool
from agent_engine.tools.request_user_input import RequestUserInputTool
from agent_engine.tools.task_completed import TaskCompletedTool
from agent_engine.tools.project_tool_loader import ProjectToolLoader

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
        CheckSyntaxTool,
        CreateToolTool,
        RespondToUserTool, RequestUserInputTool, TaskCompletedTool,
    ]:
        _instance = _cls("/tmp")
        _BUILTIN_TOOL_CLASSES[_instance.name] = _cls


_init_builtin_classes()


def get_registry(_root_dir=None):
    """Return the module-level static ToolRegistry.

    This is created exactly once at module import and never recreated.
    All agent engines share this same instance.
    """
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def _reset_registry():
    """Reset the registry for tests only."""
    global _registry
    _registry = None


class ToolRegistry:
    """Registry of all available tools.

    Per-project tool loading: each project can have its own set of
    project-local tools (stored in its tools/active/ directory) and
    can disable specific built-in tools via projects.json disabled_tools field.
    """

    def __init__(self):
        # Per-project tool loaders: project_output_dir → ProjectToolLoader
        self._project_loaders: Dict[str, ProjectToolLoader] = {}
        # Global enabled/disabled set — empty means "all enabled"
        self._enabled_tools: Set[str] = set()

    # ------------------------------------------------------------------
    # Per-project tool loader management
    # ------------------------------------------------------------------

    def _get_or_create_loader(self, project_output_dir: str,
                              disabled_tools: Optional[Set[str]] = None) -> ProjectToolLoader:
        """Get or create a ProjectToolLoader for a project.

        If a loader already exists, update its disabled_tools set so that
        list_tools() always reflects the current disable state.
        """
        if project_output_dir not in self._project_loaders:
            self._project_loaders[project_output_dir] = ProjectToolLoader(
                project_output_dir, disabled_tools or set()
            )
        else:
            # Update disabled_tools on existing loader (idempotent)
            self._project_loaders[project_output_dir].disabled_tools = disabled_tools or set()
        return self._project_loaders[project_output_dir]

    def reload_project_tools(self, project_output_dir: str,
                             disabled_tools: Optional[Set[str]] = None):
        """Reload project-local tools for a project."""
        self._project_loaders[project_output_dir] = ProjectToolLoader(
            project_output_dir, disabled_tools or set()
        )

    def reload_approved_tools(self):
        """Reload project-local tools and rebuild system prompt.

        Alias for reload_project_tools() — kept for backward compatibility
        with existing code and tests that call this method name.
        """
        # This is a no-op at the registry level; individual engines call
        # reload_approved_tools() which delegates to _reload_project_tool_loader()
        pass

    # ------------------------------------------------------------------
    # Per-project tool operations (approval/rejection)
    # ------------------------------------------------------------------

    def get_project_pending_tools(self, project_output_dir: str) -> List[Dict[str, Any]]:
        """Return pending tools for a specific project."""
        loader = self._get_or_create_loader(project_output_dir)
        return loader.get_pending_tools()

    def approve_project_tool(self, project_output_dir: str, tool_name: str) -> Dict[str, Any]:
        """Approve a pending tool for a specific project."""
        loader = self._get_or_create_loader(project_output_dir)
        return loader.approve_tool(tool_name)

    def reject_project_tool(self, project_output_dir: str, tool_name: str) -> Dict[str, Any]:
        """Reject a pending tool for a specific project."""
        loader = self._get_or_create_loader(project_output_dir)
        return loader.reject_tool(tool_name)

    def delete_project_tool(self, project_output_dir: str, tool_name: str) -> Dict[str, Any]:
        """Delete an approved tool for a specific project."""
        loader = self._get_or_create_loader(project_output_dir)
        return loader.delete_tool(tool_name)

    # ------------------------------------------------------------------
    # Global enable/disable (built-in tools)
    # ------------------------------------------------------------------

    def set_tool_enabled(self, tool_name: str, enabled: bool) -> Dict[str, Any]:
        """Enable or disable a built-in tool globally."""
        if tool_name in _BUILTIN_TOOL_CLASSES:
            if enabled:
                self._enabled_tools.discard(tool_name)
            else:
                self._enabled_tools.add(tool_name)
            return {"status": "updated", "tool": tool_name, "enabled": enabled}
        elif tool_name in self._get_all_dynamic_names():
            if enabled:
                self._enabled_tools.discard(tool_name)
            else:
                self._enabled_tools.add(tool_name)
            return {"status": "updated", "tool": tool_name, "enabled": enabled}
        else:
            return {"status": "not_found", "tool": tool_name}

    def get_enabled_tools(self) -> List[str]:
        """Return the list of currently enabled tool names."""
        all_names = set(_BUILTIN_TOOL_CLASSES.keys()) | self._get_all_dynamic_names()
        if not self._enabled_tools:
            return sorted(all_names)
        return sorted(all_names - self._enabled_tools)

    def get_tool_status(self) -> Dict[str, bool]:
        """Return a dict of tool_name → enabled for all known tools."""
        all_names = set(_BUILTIN_TOOL_CLASSES.keys()) | self._get_all_dynamic_names()
        return {name: name not in self._enabled_tools for name in sorted(all_names)}

    def _get_all_dynamic_names(self) -> Set[str]:
        """Get all dynamic tool names from all project loaders."""
        names = set()
        for loader in self._project_loaders.values():
            names.update(loader.get_tool_names())
        return names

    # ------------------------------------------------------------------
    # Tool instance creation (per-execution with correct root_dir)
    # ------------------------------------------------------------------

    def _create_tool_instance(self, tool_name: str, root_dir: str,
                              project_output_dir: str,
                              disabled_tools: Optional[Set[str]] = None,
                              job_id: str = "") -> Optional[BaseTool]:
        """Create a tool instance for execution.

        Checks project-local tools first, then built-in tools.
        Returns None if the tool is disabled or not found.
        """
        if disabled_tools is None:
            disabled_tools = set()

        # Check if disabled globally
        if tool_name in self._enabled_tools:
            return None

        # Check if disabled for this project
        if tool_name in disabled_tools:
            return None

        # Check project-local tools first
        loader = self._get_or_create_loader(project_output_dir, disabled_tools)
        project_tool = loader.create_tool_instance(tool_name, root_dir, job_id=job_id)
        if project_tool:
            return project_tool

        # Built-in tool
        if tool_name in _BUILTIN_TOOL_CLASSES:
            cls = _BUILTIN_TOOL_CLASSES[tool_name]
            try:
                return cls(root_dir, output_dir=project_output_dir, job_id=job_id)
            except Exception as e:
                logging.warning(f"Failed to instantiate built-in tool '{tool_name}': {e}")
                return None

        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_tools(self, project_output_dir: str = "",
                   disabled_tools: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        """Return tool definitions for the LLM prompt.

        Includes both built-in tools and project-local (approved) tools.
        """
        defs = []
        disabled = disabled_tools or set()
        for name, cls in _BUILTIN_TOOL_CLASSES.items():
            if name not in self._enabled_tools and name not in disabled:
                try:
                    defs.append(cls("/tmp").get_definition())
                except Exception:
                    pass
        # Append project-local approved tools
        if project_output_dir:
            loader = self._get_or_create_loader(project_output_dir, disabled_tools)
            defs.extend(loader.list_tools())
        return defs

    def tool_names(self) -> set:
        """Return a set of all registered tool names (built-in + dynamic)."""
        return set(_BUILTIN_TOOL_CLASSES.keys()) | self._get_all_dynamic_names()

    def execute(self, tool_name: str, params: Dict[str, Any], root_dir: str,
                project_output_dir: str = "", disabled_tools: Optional[Set[str]] = None,
                job_id: str = "") -> ToolResult:
        """Execute a tool by name with validated parameters.

        Creates a tool instance with the given root_dir for this execution.
        Strips JSON Schema structural keys that the LLM might accidentally include.

        Args:
            tool_name: Name of the tool to execute.
            params: Parameter dict for the tool call.
            root_dir: Project root directory.
            project_output_dir: Project output directory (for project-local tools).
            disabled_tools: Set of tool names to disable for this project.
            job_id: Current job ID (for tools that need it).
        """
        if disabled_tools is None:
            disabled_tools = set()
        if not project_output_dir:
            project_output_dir = os.path.join(root_dir, "output")

        tool = self._create_tool_instance(tool_name, root_dir, project_output_dir, disabled_tools, job_id=job_id)
        if not tool:
            available = [t for t in _BUILTIN_TOOL_CLASSES.keys() if t not in self._enabled_tools]
            available += sorted(self._get_all_dynamic_names())
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
