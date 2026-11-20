"""Bash script tool loader and base class.

Bash tools are shell scripts stored in a project's aib_instance/tools/bash/ directory.
Each script has a YAML-like metadata header that defines:
  - TOOL_NAME: the tool name (used as the tool identifier)
  - TOOL_DESCRIPTION: description shown to the LLM
  - TOOL_PARAMS: list of parameters with name, type, required, default

The LLM sees bash tools identically to Python tools — same definition format.
Execution runs the script in the project's root directory with params passed
as environment variables.
"""

import json
import os
import re
import shlex
import subprocess
from typing import Any, Dict, List, Optional, Set

from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root, validate_tool_params, SecurityError, ToolError


# -------------------------------------------------------------------
# BashTool — base class for bash-script tools
# -------------------------------------------------------------------

class BashTool(BaseTool):
    """Base class for tools backed by a bash script."""
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    def __init__(self, root_dir: str, output_dir: str = "", job_id: str = "",
                 script_path: str = "", env_prefix: str = "TOOL"):
        super().__init__(root_dir, output_dir, job_id)
        self.script_path = script_path
        self.env_prefix = env_prefix

    def get_definition(self) -> Dict[str, Any]:
        """Return tool definition with NO parameters — bash scripts take none."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {},
        }

    def execute(self, params: Dict[str, str]) -> ToolResult:
        """Run the bash script with params passed as environment variables."""
        if not self.script_path or not os.path.isfile(self.script_path):
            return ToolResult(False, "", error="Script not found")

        # Run the script without dynamic parameters, passing only fixed environment variables.
        env = os.environ.copy()

        try:
            result = subprocess.run(
                ["bash", self.script_path],
                cwd=self.root_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,  # 5-minute timeout
            )
            stdout = (result.stdout or "").rstrip("\n")
            stderr = (result.stderr or "").rstrip("\n")
            combined = stdout
            if stderr:
                combined += f"\n--- STDERR ---\n{stderr}"
            success = result.returncode == 0
            return ToolResult(
                success=success,
                content=combined if success else f"Exit code {result.returncode}: {combined}",
                error="" if success else f"Exit code {result.returncode}",
                summary=stdout[:200] if stdout else f"Exit code {result.returncode}",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, "", error="Script timed out after 5 minutes")
        except Exception as e:
            return ToolResult(False, "", error=str(e))


# -------------------------------------------------------------------
# BashToolLoader — loads .sh files from the project bash tools dir
# -------------------------------------------------------------------

# Metadata header pattern:
#   # TOOL_NAME: my_tool
#   # TOOL_DESCRIPTION: does something
#   # TOOL_PARAMS:
#   #   - name: file_path
#   #     type: string
#   #     required: true
#   #   - name: count
#   #     type: integer
#   #     required: false
#   #     default: 10

_HEADER_RE = re.compile(
    r'^#\s*TOOL_NAME:\s*(.+)$', re.MULTILINE
)
_HEADER_DESC_RE = re.compile(
    r'^#\s*TOOL_DESCRIPTION:\s*(.+)$', re.MULTILINE
)
# Params are extracted via string parsing, not regex


def _parse_params_text(text: str) -> List[Dict[str, Any]]:
    """Parse the TOOL_PARAMS block into a list of param dicts."""
    params = []
    # Split into blocks by "- " prefix lines (each param starts with "- name: ...")
    # Each param block starts with a line like "#   - name: xxx"
    # and continues with lines like "#     type: xxx" until the next "- name:" or end
    param_blocks = re.split(r'\n\s*#\s*- ', text)
    for block in param_blocks:
        lines = block.strip().split('\n')
        if not lines:
            continue
        # First line after "- " is "name: xxx" (possibly with other props)
        # But the FIRST block may still have "#   - " prefix
        first = lines[0].strip()
        # Strip "#   - " prefix if present (from first block only)
        first = re.sub(r'^#\s*-\s*', '', first)
        name_match = re.match(r'name:\s*(.+)', first)
        if not name_match:
            continue
        param = {"name": name_match.group(1).strip(), "type": "string", "required": False}
        for line in lines[1:]:
            lm = re.match(r'(\w+):\s*(.+)', line.strip())
            if lm:
                k, v = lm.group(1).strip(), lm.group(2).strip()
                if k == "required":
                    v = v.lower() in ("true", "yes", "1")
                elif k == "default":
                    if param.get("type") == "integer":
                        try:
                            v = int(v)
                        except ValueError:
                            pass
                param[k] = v
        params.append(param)
    return params


def _extract_params_text(source: str) -> str:
    """Extract the TOOL_PARAMS block from a bash script source.

    Returns the raw text of all comment lines between '# TOOL_PARAMS:' and the
    next blank line or non-comment content.
    """
    lines = source.split('\n')
    in_params = False
    params_lines = []
    for line in lines:
        if '# TOOL_PARAMS:' in line:
            in_params = True
            continue
        if in_params:
            if line.startswith('#'):
                params_lines.append(line)
            elif line.strip() == '':
                break
            else:
                break
    return '\n'.join(params_lines)


def _build_schema(params: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convert param list into JSON Schema-like parameters dict."""
    schema = {}
    for p in params:
        pname = p.get("name", "")
        ptype = p.get("type", "string")
        required = p.get("required", False)
        default = p.get("default", None)

        prop = {"type": ptype}
        if ptype == "string":
            prop["type"] = "string"
        elif ptype in ("integer", "int"):
            prop["type"] = "integer"
        elif ptype in ("number", "float"):
            prop["type"] = "number"
        elif ptype == "boolean":
            prop["type"] = "boolean"

        if default is not None:
            prop["default"] = default
        schema[pname] = prop
    return schema


class BashToolLoader:
    """Loads bash script tools from a project's aib_instance/tools/bash/ directory."""

    def __init__(self, project_output_dir: str, disabled_tools: Optional[Set[str]] = None):
        self.project_output_dir = project_output_dir
        self.disabled_tools = disabled_tools or set()
        self._tools: Dict[str, BashTool] = {}
        self._sources: Dict[str, str] = {}
        self._load_bash_tools()

    def _bash_dir(self) -> str:
        """Return the project-level bash tools directory."""
        # Walk up from output_dir to find the project root (same logic as ProjectToolLoader)
        candidate = self.project_output_dir
        for _ in range(10):
            parent = os.path.dirname(candidate)
            if parent == candidate:
                break
            candidate = parent
            if os.path.isdir(os.path.join(candidate, "tools")) and os.path.isdir(os.path.join(candidate, "output")):
                return candidate
        return os.path.dirname(self.project_output_dir)

    def _tools_dir(self) -> str:
        return os.path.join(self._bash_dir(), "tools")

    def _bash_scripts_dir(self) -> str:
        return os.path.join(self._tools_dir(), "bash")

    def _load_bash_tools(self):
        """Load all .sh files from the bash scripts directory."""
        scripts_dir = self._bash_scripts_dir()
        if not os.path.isdir(scripts_dir):
            return
        for fname in os.listdir(scripts_dir):
            if not fname.endswith(".sh"):
                continue
            tool_name = fname[:-3]  # strip .sh
            if tool_name in self.disabled_tools:
                continue
            script_path = os.path.join(scripts_dir, fname)
            try:
                with open(script_path, 'r', encoding='utf-8') as f:
                    source = f.read()
                tool = self._parse_bash_tool(source, tool_name, script_path)
                if tool:
                    self._tools[tool_name] = tool
                    self._sources[tool_name] = source
            except Exception:
                pass

    def _parse_bash_tool(self, source: str, tool_name: str, script_path: str) -> Optional[BashTool]:
        """Parse a bash script source into a BashTool instance."""
        name_match = _HEADER_RE.search(source)
        desc_match = _HEADER_DESC_RE.search(source)
        params_text = _extract_params_text(source)
        name = name_match.group(1).strip() if name_match else tool_name
        description = desc_match.group(1).strip() if desc_match else ""
        param_defs = _parse_params_text(params_text) if params_text else []
        schema = _build_schema(param_defs) if param_defs else {}

        tool = BashTool(
            root_dir="/tmp",  # overridden at execution time
            output_dir=self.project_output_dir,
            script_path=script_path,
        )
        tool.name = name
        tool.description = description
        tool.parameters = schema
        return tool

    def get_pending_tools(self) -> List[Dict[str, Any]]:
        """Bash tools are immediately available — no pending state."""
        return []

    def get_tool_names(self) -> Set[str]:
        return set(self._tools.keys())

    def create_tool_instance(self, tool_name: str, root_dir: str,
                             output_dir: str = "", job_id: str = "", **_extra_kwargs) -> Optional[BashTool]:
        if tool_name in self.disabled_tools:
            return None
        if tool_name in self._tools:
            t = self._tools[tool_name]
            t.root_dir = root_dir
            t.output_dir = output_dir or self.project_output_dir
            t.job_id = job_id
            return t
        return None

    def get_tool_source(self, tool_name: str) -> Optional[str]:
        return self._sources.get(tool_name)

    def list_tools(self) -> List[Dict[str, Any]]:
        defs = []
        for name, tool in self._tools.items():
            if name not in self.disabled_tools:
                try:
                    defs.append(tool.get_definition())
                except Exception:
                    pass
        return defs

    # --- CRUD operations for bash tools ---

    def create_bash_tool(self, name: str, description: str, params: List[Dict[str, Any]],
                         script_content: str) -> Dict[str, Any]:
        """Create a new bash tool script."""
        scripts_dir = self._bash_scripts_dir()
        os.makedirs(scripts_dir, exist_ok=True)
        # Sanitize name for filename
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)[:64]
        script_path = os.path.join(scripts_dir, f"{safe_name}.sh")
        if os.path.exists(script_path):
            return {"status": "error", "error": f"Tool '{name}' already exists"}

        # Build the script with metadata header
        lines = [
            "#!/bin/bash",
            f"# TOOL_NAME: {safe_name}",
            f"# TOOL_DESCRIPTION: {description}",
        ]
        if params:
            lines.append("# TOOL_PARAMS:")
            for p in params:
                pname = p.get("name", "")
                ptype = p.get("type", "string")
                preq = p.get("required", False)
                pdflt = p.get("default")
                line = f"#   - name: {pname}"
                if ptype != "string":
                    line += f"\n#     type: {ptype}"
                if preq:
                    line += f"\n#     required: true"
                if pdflt is not None:
                    line += f"\n#     default: {pdflt}"
                lines.append(line)
        lines.append("")
        lines.append("# --- Script body starts here ---")
        lines.append(script_content)

        with open(script_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        os.chmod(script_path, 0o755)

        # Reload to pick up the new tool
        self._load_bash_tools()
        return {"status": "created", "tool_name": safe_name}

    def delete_bash_tool(self, name: str) -> Dict[str, Any]:
        scripts_dir = self._bash_scripts_dir()
        script_path = os.path.join(scripts_dir, f"{name}.sh")
        if not os.path.exists(script_path):
            return {"status": "not_found", "tool_name": name}
        os.remove(script_path)
        self._tools.pop(name, None)
        self._sources.pop(name, None)
        return {"status": "deleted", "tool_name": name}

    def list_bash_tools(self) -> List[Dict[str, Any]]:
        """List all bash tools with their source code."""
        tools = []
        scripts_dir = self._bash_scripts_dir()
        if not os.path.isdir(scripts_dir):
            return tools
        for fname in sorted(os.listdir(scripts_dir)):
            if not fname.endswith(".sh"):
                continue
            tool_name = fname[:-3]
            script_path = os.path.join(scripts_dir, fname)
            try:
                with open(script_path, 'r', encoding='utf-8') as f:
                    source = f.read()
                # Parse metadata
                name_match = _HEADER_RE.search(source)
                desc_match = _HEADER_DESC_RE.search(source)
                params_text = _extract_params_text(source)
                tools.append({
                    "name": name_match.group(1).strip() if name_match else tool_name,
                    "description": desc_match.group(1).strip() if desc_match else "",
                    "params": _parse_params_text(params_text) if params_text else [],
                    "source": source,
                })
            except Exception:
                pass
        return tools
