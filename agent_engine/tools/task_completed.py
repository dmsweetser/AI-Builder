"""Task completed tool - signals task completion with a summary."""

import json
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult


class TaskCompletedTool(BaseTool):
    """Signals that the task is complete and provides a summary."""
    
    name = "task_completed"
    description = ("Signals that the task is complete. Provide a summary of all changes made.")
    parameters = {
        "summary": {
            "type": "string",
            "description": "A summary of all changes made during this task."
        }
    }
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        summary = params.get("summary", "Task completed.")
        return ToolResult(
            success=True,
            content=json.dumps({"task_completed": True, "summary": summary}),
            summary=f"Task completed: {summary[:100]}",
        )
