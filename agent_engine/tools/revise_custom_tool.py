"""revise_custom_tool tool — proposes a revised version of an existing project-local tool.

The tool replaces a pending tool (if one exists for the same name) or creates
a new pending tool.  The revised code is validated the same way as
create_tool — it must define a class inheriting from BaseTool with name,
description, parameters, and an execute(params) method that returns a
ToolResult.

Use this when a custom tool has failed and you need to fix or completely
rewrite it. You can generate a full unabridged replacement — the entire
Python source code — and submit it here for user approval.
"""
import os
import re
import sys
import tempfile
import types
import importlib.util
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult


class ReviseCustomToolTool(BaseTool):
    """Tool that allows the agent to propose a revised version of an existing
    project-local (custom) tool for user approval.

    This tool works just like create_tool but is specifically for revising
    tools that already exist in the project's tools/active/ directory.
    It replaces any pending tool with the same name, or creates a new
    pending tool if no pending version exists.

    IMPORTANT: You CAN generate a full unabridged replacement for the tool.
    If the tool is broken beyond a simple fix, provide the complete new
    Python source code — the entire class definition — here. Do NOT try to
    provide a "diff" or "patch"; provide the full working code.

    The tool code must define a class that inherits from BaseTool with
    name, description, parameters, and an execute(params) method.
    Your code MUST import: 'from agent_engine.tools.base import BaseTool, ToolResult'.
    Your execute() method MUST return a ToolResult object (not a plain dict).
    Return e.g. ToolResult(True, 'output content') on success or
    ToolResult(False, '', error='error message') on failure.
    """
    name = "revise_custom_tool"
    description = (
        "Propose a revised version of an existing project-local (custom) tool "
        "for user approval. Use this when a custom tool has failed and you need "
        "to fix or rewrite it. You CAN generate a full unabridged replacement — "
        "the entire Python source code — and submit it here for user approval. "
        "The revised tool will NOT be available until approved. Provide the "
        "tool name (must match an existing custom tool), clear description, "
        "parameter schema (simple format like {\"path\": \"string?\"}), and the "
        "complete Python implementation code. The code must define a class that "
        "inherits from BaseTool with name, description, parameters, and an "
        "execute(params) method. Use self.root_dir for the project path. "
        "Your code MUST import: 'from agent_engine.tools.base import BaseTool, ToolResult'. "
        "IMPORTANT: Your execute() method MUST return a ToolResult object (not a plain dict). "
        "Return e.g. ToolResult(True, 'output content') on success or "
        "ToolResult(False, '', error='error message') on failure."
    )
    parameters = {
        "name": "string",
        "description": "string",
        "parameters": "string",
        "code": "string",
    }

    def execute(self, params: Dict[str, str]) -> ToolResult:
        tool_name = params["name"].strip()
        tool_desc = params["description"].strip()
        tool_params_json = params["parameters"].strip()
        tool_code = params["code"]

        # Validate name
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_-]*$', tool_name):
            return ToolResult(False, "", error="Tool name must match: ^[a-zA-Z_][a-zA-Z0-9_-]*$")

        # Validate description
        if len(tool_desc) < 10:
            return ToolResult(False, "", error="Description must be at least 10 characters")

        # Parse parameter schema
        try:
            import json as _json
            param_schema = _json.loads(tool_params_json) if tool_params_json else {}
        except Exception as e:
            return ToolResult(False, "", error=f"Invalid JSON for parameters: {e}")

        # Determine the project's output directory
        output_dir = self.output_dir
        if not output_dir:
            return ToolResult(False, "", error="output_dir not available — cannot revise tool")

        # Build the tool file content
        file_content = self._build_tool_file(tool_name, tool_desc, tool_params_json, tool_code)

        # Ensure sys is available for the project-root lookup
        _project_root = None
        _candidate = os.path.dirname(os.path.abspath(output_dir))
        for _depth in range(10):
            if os.path.isdir(os.path.join(_candidate, "agent_engine")):
                _project_root = _candidate
                break
            _parent = os.path.dirname(_candidate)
            if _parent == _candidate:
                break
            _candidate = _parent
        if _project_root and _project_root not in sys.path:
            sys.path.insert(0, _project_root)

        # Validate the tool code by compiling it in a temporary module
        try:
            # Import shim: map common LLM-generated import paths to the correct
            # AI-Builder paths. LLMs frequently write "from tools.base import
            # BaseTool" (LangChain-ism / generic pattern) instead of the actual
            # "from agent_engine.tools.base import BaseTool".  We intercept the
            # failed import at validation time so the generated code still runs
            # correctly at execution time (where the real path is used).
            if "tools.base" not in sys.modules:
                try:
                    from agent_engine.tools.base import BaseTool, ToolResult as _TB
                    _shim = types.ModuleType("tools.base")
                    _shim.BaseTool = BaseTool
                    _shim.ToolResult = _TB
                    sys.modules["tools.base"] = _shim
                except ImportError:
                    pass  # No shim possible — let the real import fail below

            if "base" not in sys.modules:
                try:
                    from agent_engine.tools.base import BaseTool, ToolResult as _TB
                    _shim = types.ModuleType("base")
                    _shim.BaseTool = BaseTool
                    _shim.ToolResult = _TB
                    sys.modules["base"] = _shim
                except ImportError:
                    pass  # No shim possible — let the real import fail below

            # Also ensure the real module is importable for direct imports
            if "agent_engine.tools.base" not in sys.modules:
                try:
                    import agent_engine.tools.base as _real_base
                    sys.modules["agent_engine.tools.base"] = _real_base
                except ImportError:
                    pass

            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, dir=output_dir) as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name
            spec = importlib.util.spec_from_file_location(f"revise_{tool_name}", tmp_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                module.__package__ = spec.submodule_search_locations[0] if spec.submodule_search_locations else ""
                spec.loader.exec_module(module)
                # Verify it has a class that inherits from BaseTool
                found_class = False
                # Use the BaseTool class from this module's globals to avoid
                # UnboundLocalError in Python 3.14 when the executed module
                # also imports BaseTool (the two names can collide).
                _base_tool_cls = BaseTool
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and attr.__name__ != "BaseTool":
                        # Check if it inherits from BaseTool
                        try:
                            is_sub = issubclass(attr, _base_tool_cls)
                        except TypeError:
                            is_sub = False
                        if is_sub:
                            if getattr(attr, "name", None) == tool_name:
                                found_class = True
                                break
                if not found_class:
                    return ToolResult(False, "", error=f"Tool code must define a class named '{tool_name}' that inherits from BaseTool")

                # Validate that the tool code returns a ToolResult object
                if "ToolResult" not in tool_code or "return ToolResult" not in tool_code:
                    return ToolResult(
                        False, "",
                        error=(
                            "Tool validation failed: execute() must return a ToolResult object. "
                            "Your code must import ToolResult and return it, e.g. "
                            "ToolResult(True, 'success message') or "
                            "ToolResult(False, '', error='error message')."
                        )
                    )
            else:
                return ToolResult(False, "", error="Failed to compile tool code — invalid Python syntax")
        except SyntaxError as e:
            return ToolResult(False, "", error=f"Syntax error in tool code: {e}")
        except ImportError as e:
            return ToolResult(False, "", error=f"Import error in tool code: {e}")
        except Exception as e:
            return ToolResult(False, "", error=f"Tool code validation failed: {e}")
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        # Write the revised tool to the pending directory
        pending_dir = os.path.join(self._tools_dir(), "pending")
        os.makedirs(pending_dir, exist_ok=True)

        tool_file = os.path.join(pending_dir, f"{tool_name}.py")

        with open(tool_file, 'w', encoding='utf-8') as f:
            f.write(file_content)

        return ToolResult(
            True,
            f"Tool '{tool_name}' revised and proposed for approval.\n\n"
            f"Full code:\n{tool_code}\n\n",
            summary=f"Tool '{tool_name}' revised and proposed for approval.",
        )

    def _tools_dir(self) -> str:
        """Return the project-level tools directory for this tool instance."""
        output_dir = self.output_dir
        if not output_dir:
            from agent_engine._paths import get_exe_dir
            return os.path.join(get_exe_dir(), "aib_instance", "tools")
        candidate = output_dir
        for _ in range(10):
            parent = os.path.dirname(candidate)
            if parent == candidate:
                break
            candidate = parent
            if os.path.isdir(os.path.join(candidate, "tools")) and os.path.isdir(os.path.join(candidate, "output")):
                return os.path.join(candidate, "tools")
        return os.path.join(os.path.dirname(output_dir), "tools")

    def _build_tool_file(self, tool_name: str, description: str,
                         parameters_json: str, code: str) -> str:
        """Build the .py file content for a tool."""
        if re.search(r'class\s+\w+', code):
            return code

        class_body = f'''\"\"\"Auto-revised tool: {tool_name}\"\"\"
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any


class {tool_name.title().replace("_", "")}Tool(BaseTool):
    """{description}"""
    name = "{tool_name}"
    description = "{description}"
    parameters = {parameters_json}

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        """Execute the tool logic."""
{self._indent_code(code)}
'''
        return class_body

    def _indent_code(self, code: str, spaces=8) -> str:
        """Indent code blocks for embedding in a class method."""
        lines = code.split('\n')
        indented = []
        for line in lines:
            if line.strip():
                indented.append(' ' * spaces + line)
            else:
                indented.append('')
        return '\n'.join(indented)
