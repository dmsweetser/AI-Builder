"""read_full_file tool - read file contents with no truncation."""
import os
from typing import Dict

from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class ReadFullFileTool(BaseTool):
    name = "read_full_file"
    description = (
        "Read the full contents of a file with NO truncation. "
        "Use this ONLY when you have determined the file should be read in full "
        "and you need to see every character. This bypasses the normal tool result "
        "length limit. Prefer read_file or read_file_range for large files."
    )
    parameters = {"path": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except (OSError, PermissionError) as e:
            return ToolResult(False, "", error=f"Cannot read file: {e}")

        return ToolResult(True, content,
                          summary=f"{len(content)} chars, {len(content.splitlines())} lines ({os.path.getsize(path)} bytes)")
