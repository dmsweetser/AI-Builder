"""Communication tools: respond_to_user, request_user_input."""

import os
import json
import time
from typing import Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.config import EngineConfig


class RespondToUserTool(BaseTool):
    name = "respond_to_user"
    description = (
        "Respond to the user with a message. Use this to communicate findings, "
        "ask questions, or provide status updates. After using this tool, you "
        "may continue with more tool calls or use [DONE] to finish."
    )
    parameters = {"message": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        message = params["message"]
        # Save the response so the UI can display it
        output_dir = os.environ.get("AIB_OUTPUT_DIR", "")
        if output_dir:
            resp_file = os.path.join(output_dir, "user_response.txt")
            try:
                with open(resp_file, 'w', encoding='utf-8') as f:
                    f.write(message)
            except OSError:
                pass
        return ToolResult(
            True,
            f"Response sent to user: {message[:200]}",
            summary=f"Responded to user ({len(message)} chars)",
        )


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
            # Save the question so the UI can prompt the user
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
