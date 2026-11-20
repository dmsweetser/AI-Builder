"""read_full_file tool - read file contents with no truncation."""
import os
from typing import Dict

from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class ReadFullFileTool(BaseTool):
    name = "read_full_file"
    description = (
        "Read the full contents of a file with NO truncation. "
        "This bypasses the normal tool result limit and returns "
        "the ENTIRE file — even very large files. "
        "WARNING: Using this for large files can cause context overflow and slow the agent. "
        "Only use this when you have already inspected the file's size via read_file's summary "
        "and have determined that the full content is genuinely needed. "
        "For most cases, use read_file (which includes size info in its summary) or "
        "read_file_range to read specific sections instead."
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
