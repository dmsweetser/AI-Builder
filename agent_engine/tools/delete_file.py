"""delete_file tool."""
import os
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class DeleteFileTool(BaseTool):
    name = "delete_file"
    description = (
        "Delete a file from the project. "
        "Use this to remove obsolete or unwanted files."
    )
    parameters = {"path": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        # Safety: don't delete backup files
        if path.endswith('.bak') or path.endswith('.backup'):
            return ToolResult(False, "", error="Refusing to delete backup file")

        try:
            os.remove(path)
            return ToolResult(True, f"Deleted: {params['path']}",
                              summary=f"Removed: {params['path']}")
        except OSError as e:
            return ToolResult(False, "", error=f"Cannot delete file: {e}")
