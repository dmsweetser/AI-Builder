"""create_tool tool."""
import os
import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.config import EngineConfig


class CreateToolTool(BaseTool):
    """Tool that allows the agent to propose new tools for user approval.

    The proposed tool is NOT registered until the user explicitly approves it.
    This replaces the old ``execute_python`` arbitrary-code-execution tool.
    """
    name = "create_tool"
    description = (
        "Propose a new tool for user approval. The proposed tool will NOT be "
        "available until a user explicitly approves it via the UI. "
        "Provide a unique name, clear description, parameter schema, and "
        "the Python implementation code. The code runs inside a sandboxed "
        "context with access to ``self.root_dir`` (str), ``params`` (dict), "
        "and must return a ``ToolResult(success, content, error, summary)``. "
        "Use this instead of ``execute_python`` which has been removed."
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

        # Validate description is reasonable
        if len(tool_desc) < 10:
            return ToolResult(False, "", error="Description must be at least 10 characters")

        # Parse parameter schema
        try:
            param_schema = json.loads(tool_params_json) if tool_params_json else {}
        except json.JSONDecodeError as e:
            return ToolResult(False, "", error=f"Invalid JSON for parameters: {e}")

        # Build pending tool record
        pending_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()

        pending_tool = {
            "id": pending_id,
            "name": tool_name,
            "description": tool_desc,
            "parameters": param_schema,
            "code": tool_code,
            "status": "pending",
            "submitted_at": timestamp,
        }

        # Persist to the GLOBAL pending tools file (aib_instance/output/pending_tools.json)
        # This is where ToolRegistry looks for pending tools
        pending_file = EngineConfig.get_pending_tools_file()
        os.makedirs(os.path.dirname(pending_file), exist_ok=True)

        pending_tools = []
        if os.path.exists(pending_file):
            try:
                with open(pending_file, 'r') as f:
                    pending_tools = json.load(f)
            except Exception:
                pending_tools = []

        # Deduplicate: remove any existing entry with the same tool name
        pending_tools = [t for t in pending_tools if t.get("name") != tool_name or t.get("status") != "pending"]

        pending_tools.append(pending_tool)
        with open(pending_file, 'w') as f:
            json.dump(pending_tools, f, indent=2)

        return ToolResult(
            True,
            json.dumps(pending_tool, indent=2),
            summary=f"Tool '{tool_name}' proposed for approval (ID: {pending_id}). Awaiting user review.",
        )
