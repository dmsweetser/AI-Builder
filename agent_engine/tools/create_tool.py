"""create_tool tool — creates a project-local tool for approval.

The tool creates a .py file in the project's tools/pending/ directory.
The code is passed as a plain text param_value block (not JSON).
The resulting tool uses the same class-based format as built-in tools.
"""
import os
import re
import uuid
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult


class CreateToolTool(BaseTool):
    """Tool that allows the agent to propose a new project-local tool for user approval.

    The proposed tool is NOT registered until the user explicitly approves it.
    The tool code is provided as a plain Python class inheriting from BaseTool,
    following the same format as built-in tools.

    Usage: provide a unique name, clear description, parameter schema (simple
    format: {"path": "string?", "content": "string?"}), and the Python code
    as a param_value block.
    """
    name = "create_tool"
    description = (
        "Propose a new project-local tool for user approval. The proposed tool "
        "will NOT be available until approved. Provide a unique name, clear "
        "description, parameter schema (simple format like {\"path\": \"string?\"}), "
        "and the Python implementation code. The code must define a class that "
        "inherits from BaseTool with name, description, parameters, and an "
        "execute(params) method. Use self.root_dir for the project path. "
        "Your code MUST import the following: 'from agent_engine.tools.base import BaseTool, ToolResult'. "
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

        # Parse parameter schema (simple format: {"key": "string?"})
        try:
            import json as _json
            param_schema = _json.loads(tool_params_json) if tool_params_json else {}
        except _json.JSONDecodeError as e:
            return ToolResult(False, "", error=f"Invalid JSON for parameters: {e}")

        # Determine the project's output directory
        output_dir = self.output_dir
        if not output_dir:
            return ToolResult(False, "", error="output_dir not available — cannot create tool")

        # Ensure sys is available for the project-root lookup below
        import sys as _sys

        # Build the tool file content
        file_content = self._build_tool_file(tool_name, tool_desc, tool_params_json, tool_code)

        # Ensure the project root (parent of agent_engine/) is on sys.path so
        # that the generated tool code can resolve imports like
        # "from agent_engine.tools.base import BaseTool" when executed from
        # the temp file.  The temp file lives in output_dir (e.g.
        # aib_instance/output/Project/tools/pending/), so we walk up until we
        # find a directory containing the agent_engine package.
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
        if _project_root and _project_root not in _sys.path:
            _sys.path.insert(0, _project_root)

        # Validate the tool code by compiling it in a temporary module
        try:
            import tempfile as _tempfile
            import importlib.util as _importlib_util
            import types as _types
            import sys as _sys
            # Import shim: map common LLM-generated import paths to the correct
            # AI-Builder paths. LLMs frequently write "from tools.base import
            # BaseTool" (LangChain-ism / generic pattern) instead of the actual
            # "from agent_engine.tools.base import BaseTool".  We intercept the
            # failed import at validation time so the generated code still runs
            # correctly at execution time (where the real path is used).

            if "tools.base" not in _sys.modules:
                try:
                    from agent_engine.tools.base import BaseTool, ToolResult as _TB
                    _shim = _types.ModuleType("tools.base")
                    _shim.BaseTool = BaseTool
                    _shim.ToolResult = _TB
                    _sys.modules["tools.base"] = _shim
                except ImportError:
                    pass  # No shim possible — let the real import fail below

            if "base" not in _sys.modules:
                try:
                    from agent_engine.tools.base import BaseTool, ToolResult as _TB
                    _shim = _types.ModuleType("base")
                    _shim.BaseTool = BaseTool
                    _shim.ToolResult = _TB
                    _sys.modules["base"] = _shim
                except ImportError:
                    pass  # No shim possible — let the real import fail below

            with _tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, dir=output_dir) as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name
            spec = _importlib_util.spec_from_file_location(f"validate_{tool_name}", tmp_path)
            if spec and spec.loader:
                module = _importlib_util.module_from_spec(spec)
                # Set __package__ so relative imports and the import machinery
                # resolve the full dotted path (agent_engine.tools.base)
                # correctly when exec_module runs the temp file.
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
            # Clean up temp file
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        # Create the pending tools directory
        pending_dir = os.path.join(output_dir, "tools", "pending")
        os.makedirs(pending_dir, exist_ok=True)

        # Write the tool .py file
        tool_file = os.path.join(pending_dir, f"{tool_name}.py")

        with open(tool_file, 'w', encoding='utf-8') as f:
            f.write(file_content)

        return ToolResult(
            True,
            f"Tool '{tool_name}' proposed for approval.\n\n"
            f"Full code:\n{tool_code}\n\n",
            summary=f"Tool '{tool_name}' proposed for approval.",
        )

    def _build_tool_file(self, tool_name: str, description: str,
                         parameters_json: str, code: str) -> str:
        """Build the .py file content for a tool.

        If the code already contains a proper class, wrap it.
        Otherwise, create a class wrapper around the provided code.
        """
        # Check if the code already has a class definition
        if re.search(r'class\s+\w+', code):
            # Code has a class — use it as-is
            return code

        # Code is a function — wrap it in a class
        class_body = f'''\"\"\"Auto-generated tool: {tool_name}\"\"\"
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
