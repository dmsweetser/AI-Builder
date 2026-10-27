"""respond_to_user tool."""
import os
from typing import Dict
from agent_engine.tools.base import BaseTool, ToolResult


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
