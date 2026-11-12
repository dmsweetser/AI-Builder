"""respond_to_user tool."""
import os
from typing import Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.config import _read_status_file, _write_status_file


class RespondToUserTool(BaseTool):
    name = "respond_to_user"
    description = (
        "Respond to the user with a message. Use this to communicate findings, "
        "ask questions, or provide status updates.\n"
        "This tool does NOT pause the agent — the run will continue after this tool completes.\n"
        "If you need to PAUSE and wait for the user to respond, use request_user_input instead.\n"
        "After using this tool, you may continue with more tool calls or use task_completed to finish."
    )
    parameters = {"message": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        message = params["message"]
        if self.output_dir:
            try:
                status = _read_status_file(self.output_dir)
                status["last_user_message"] = message
                _write_status_file(self.output_dir, status)
            except OSError:
                pass
        return ToolResult(
            True,
            message,
            summary=f"Responded to user ({len(message)} chars)",
        )
