"""read_file tool."""
import os
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read the full contents of a file. "
        "Use this to inspect code before modifying it. "
        "For large files, use read_file_range instead to read specific lines. "
        "You can also use line_range parameter (e.g., '1-50') to read specific lines."
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


class ReadFileRangeTool(BaseTool):
    name = "read_file_range"
    description = (
        "Read a specific range of lines from a file. "
        "Use this for large files to avoid reading everything. "
        "line_range format: 'start-end' (1-indexed, inclusive). "
        "Example: '1-50' reads lines 1 through 50."
    )
    parameters = {"path": "string", "line_range": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        # Accept 'lines' as an alias for 'line_range'
        line_range = params.get("line_range", params.get("lines", ""))
        if not line_range:
            return ToolResult(False, "", error="line_range parameter is required. Use format 'start-end' (1-indexed, inclusive).")

        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
        except (OSError, PermissionError) as e:
            return ToolResult(False, "", error=f"Cannot read file: {e}")

        try:
            start_str, end_str = line_range.split("-", 1)
            start = int(start_str.strip()) - 1
            end = int(end_str.strip())
        except (ValueError, IndexError):
            return ToolResult(False, "", error=f"Invalid line_range format: '{line_range}'. Use 'start-end' (1-indexed, inclusive).")

        start = max(0, start)
        end = min(len(all_lines), end)

        content = ''.join(all_lines[start:end])
        return ToolResult(True, content,
                          summary=f"Lines {start + 1}-{end} of {len(all_lines)} lines ({os.path.getsize(path)} bytes)")
