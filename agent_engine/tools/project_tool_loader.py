"""Project-local tool loader.

Loads approved tools from a project's tools/active/ directory.
Each tool is a .py file containing a class that inherits from BaseTool.

Tools are stored as:
    <project_output_dir>/tools/active/<tool_name>.py

Pending tools live in:
    <project_output_dir>/tools/pending/<tool_name>.py

The engine passes the project's output_dir so tools can be scoped per-project.
"""

import importlib.util
import os
import sys
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Set, Type

from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root, validate_tool_params, SecurityError, ToolError


class ProjectToolLoader:
    """Loads project-local tools from a project's tools/active/ directory."""

    def __init__(self, project_output_dir: str, disabled_tools: Optional[Set[str]] = None):
        """
        Args:
            project_output_dir: The project's output_dir (from projects.json).
            disabled_tools: Set of built-in tool names to disable for this project.
        """
        self.project_output_dir = project_output_dir
        self.disabled_tools = disabled_tools or set()
        self._dynamic_tools: Dict[str, Type[BaseTool]] = {}
        self._load_active_tools()

    def _pending_dir(self) -> str:
        return os.path.join(self.project_output_dir, "tools", "pending")

    def _active_dir(self) -> str:
        return os.path.join(self.project_output_dir, "tools", "active")

    def _load_active_tools(self):
        """Load all approved tools from the project's tools/active/ directory."""
        active_dir = self._active_dir()
        if not os.path.isdir(active_dir):
            return
        for fname in os.listdir(active_dir):
            if fname.endswith(".py") and not fname.startswith("_"):
                tool_name = fname[:-3]
                # Skip tools that are disabled for this project
                if tool_name in self.disabled_tools:
                    continue
                tool_path = os.path.join(active_dir, fname)
                self._load_tool_from_file(tool_path, tool_name)

    def _load_tool_from_file(self, tool_path: str, tool_name: str):
        """Load a single tool .py file."""
        try:
            spec = importlib.util.spec_from_file_location(
                f"project_tool_{uuid.uuid4().hex[:8]}", tool_path
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                # Find the tool class (inherits from BaseTool)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseTool)
                        and attr.__name__ != "BaseTool"
                        and getattr(attr, "name", None) == tool_name
                    ):
                        self._dynamic_tools[tool_name] = attr
                        return
        except Exception as e:
            pass  # Silently skip broken tool files

    def get_pending_tools(self) -> List[Dict[str, Any]]:
        """Return all pending (awaiting approval) tools for this project."""
        pending_dir = self._pending_dir()
        if not os.path.isdir(pending_dir):
            return []
        tools = []
        for fname in os.listdir(pending_dir):
            if fname.endswith(".py"):
                tool_path = os.path.join(pending_dir, fname)
                try:
                    with open(tool_path, "r") as f:
                        code = f.read()
                    # Extract tool name from the code
                    tool_name = fname[:-3]
                    # Try to extract description from class docstring
                    description = ""
                    import re
                    m = re.search(r'class\s+\w+\(BaseTool\):\s*"""(.*?)"""', code, re.DOTALL)
                    if m:
                        description = m.group(1).strip()
                    tools.append({
                        "name": tool_name,
                        "description": description,
                        "code": code,
                        "submitted_at": "",
                    })
                except Exception:
                    pass
        return tools

    def get_tool_names(self) -> Set[str]:
        """Return all registered tool names (built-in + dynamic)."""
        return set(self._dynamic_tools.keys())

    def create_tool_instance(self, tool_name: str, root_dir: str,
                             output_dir: str = "", job_id: str = "") -> Optional[BaseTool]:
        """Create a tool instance for execution."""
        if tool_name in self.disabled_tools:
            return None
        if tool_name in self._dynamic_tools:
            cls = self._dynamic_tools[tool_name]
            try:
                return cls(root_dir, output_dir=output_dir or self.project_output_dir, job_id=job_id)
            except Exception:
                return None
        return None

    def approve_tool(self, tool_name: str) -> Dict[str, Any]:
        """Move a pending tool to active."""
        pending_dir = self._pending_dir()
        active_dir = self._active_dir()
        os.makedirs(active_dir, exist_ok=True)

        src = os.path.join(pending_dir, f"{tool_name}.py")
        dst = os.path.join(active_dir, f"{tool_name}.py")

        if not os.path.exists(src):
            return {"status": "not_found", "tool_name": tool_name}

        import shutil
        shutil.move(src, dst)
        # Reload to pick up the newly approved tool
        self._load_active_tools()
        return {"status": "approved", "tool_name": tool_name}

    def reject_tool(self, tool_name: str) -> Dict[str, Any]:
        """Delete a pending tool."""
        pending_dir = self._pending_dir()
        tool_path = os.path.join(pending_dir, f"{tool_name}.py")

        if not os.path.exists(tool_path):
            return {"status": "not_found", "tool_name": tool_name}

        os.remove(tool_path)
        return {"status": "rejected", "tool_name": tool_name}

    def delete_tool(self, tool_name: str) -> Dict[str, Any]:
        """Delete an approved tool."""
        active_dir = self._active_dir()
        tool_path = os.path.join(active_dir, f"{tool_name}.py")

        if not os.path.exists(tool_path):
            return {"status": "not_found", "tool_name": tool_name}

        os.remove(tool_path)
        # Remove from registry
        self._dynamic_tools.pop(tool_name, None)
        return {"status": "deleted", "tool_name": tool_name}

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for the LLM prompt."""
        defs = []
        for name, cls in self._dynamic_tools.items():
            if name not in self.disabled_tools:
                try:
                    defs.append(cls("/tmp").get_definition())
                except Exception:
                    pass
        return defs
