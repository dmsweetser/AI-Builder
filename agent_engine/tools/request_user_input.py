"""request_user_input tool."""
import os
from typing import Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.config import _read_status_file, _write_status_file


class RequestUserInputTool(BaseTool):
    name = "request_user_input"
    description = (
        "OPTIONAL: Use this tool to PAUSE the agent and request input from the user.\n"
        "This will STOP the agent's execution and wait for the user to respond.\n"
        "The user can then provide input which will be written to status.json and the agent will resume.\n"
        "Use this when you need the user to provide information, make a decision, or confirm an action.\n"
        "This tool WILL PAUSE processing — the agent will wait until the user provides input.\n"
        "If you just need to display information to the user without pausing, use respond_to_user instead.\n"
        "\n"
        "Parameters:\n"
        "  question: The question or prompt to show the user. Be specific and clear.\n"
    )
    parameters = {"question": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        question = params["question"]
        if self.output_dir:
            try:
                status = _read_status_file(self.output_dir)
                status["pending_user_input"] = {
                    "question": question,
                    "job_id": self.job_id,
                }
                _write_status_file(self.output_dir, status)
            except OSError:
                pass
        return ToolResult(
            True,
            question,
            summary=f"Requested user input ({len(question)} chars)",
        )
