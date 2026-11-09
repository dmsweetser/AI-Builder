"""request_user_input tool."""
import os
import json
from typing import Dict
from agent_engine.tools.base import BaseTool, ToolResult


class RequestUserInputTool(BaseTool):
    name = "request_user_input"
    description = (
        "OPTIONAL: Use this tool to PAUSE the agent and request input from the user.\n"
        "This will STOP the agent's execution and wait for the user to respond.\n"
        "The user can then provide input which will be written to a file and the agent will resume.\n"
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
        output_dir = os.environ.get("AIB_OUTPUT_DIR", "")
        job_id = os.environ.get("AIB_JOB_ID", "")
        if output_dir:
            resp_file = os.path.join(output_dir, "user_input_request.txt")
            try:
                with open(resp_file, 'w', encoding='utf-8') as f:
                    json.dump({"question": question, "job_id": job_id}, indent=2)
            except OSError:
                pass
        return ToolResult(
            True,
            question,
            summary=f"Requested user input ({len(question)} chars)",
        )
