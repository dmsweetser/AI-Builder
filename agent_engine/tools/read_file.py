"""read_file tool - read file contents."""
import os
from typing import Dict

from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read a file's contents. Results are truncated as needed by default — "
        "the response summary includes the total character count, line count, and byte size "
        "so you know the file's full size. "
        "For large files, use read_file_range to read specific line ranges. "
        "For files that must be read entirely (no truncation), use read_full_file. "
        "Always prefer read_file or read_file_range over read_full_file."
    )
    parameters = {"path": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)
        line_range = params.get("line_range", "")

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        # If line_range is provided, delegate to range logic
        if line_range:
            return self._read_range(path, line_range)

        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except (OSError, PermissionError) as e:
            return ToolResult(False, "", error=f"Cannot read file: {e}")

        return ToolResult(True, content,
                          summary=f"{len(content)} chars, {len(content.splitlines())} lines ({os.path.getsize(path)} bytes)")

    def _read_range(self, path: str, line_range_str: str) -> ToolResult:
        """Helper to read a specific line range."""
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
        except (OSError, PermissionError) as e:
            return ToolResult(False, "", error=f"Cannot read file: {e}")

        try:
            start_str, end_str = line_range_str.split("-", 1)
            start = int(start_str.strip()) - 1
            end = int(end_str.strip())
        except (ValueError, IndexError):
            return ToolResult(False, "", error=f"Invalid line_range format: '{line_range_str}'. Use 'start-end' (1-indexed, inclusive).")

        start = max(0, start)
        end = min(len(all_lines), end)

        content = ''.join(all_lines[start:end])
        return ToolResult(True, content,
                          summary=f"Lines {start + 1}-{end} of {len(all_lines)} lines ({os.path.getsize(path)} bytes)")
