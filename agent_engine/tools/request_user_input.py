"""request_user_input tool."""
import os
import json
from typing import Dict
from agent_engine.tools.base import BaseTool, ToolResult


class RequestUserInputTool(BaseTool):
    name = "request_user_input"
    description = (
        "Request input from the user. Use this when you need clarification, "
        "a decision, or confirmation before proceeding. The run will pause "
        "until the user provides input. After receiving input, continue with "
        "your task using the new information."
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
            f"User input requested: {question[:200]}",
            summary=f"Requested user input ({len(question)} chars)",
        )
