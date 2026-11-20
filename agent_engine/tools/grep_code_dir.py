"""grep_code_dir tool - search within a specific subdirectory."""
from __future__ import annotations

import os
import subprocess
from typing import Dict

from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root
from agent_engine.tools.grep_helpers import (
    build_grep_args,
    python_grep_impl,
    _IS_WINDOWS,
    _windows_findstr,
)


class GrepCodeDirTool(BaseTool):
    name = "grep_code_dir"
    description = (
        "Search file contents for a text pattern within a specific subdirectory. "
        "Returns matching file paths and line numbers."
    )
    parameters = {"pattern": "string", "directory": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        pattern = params["pattern"]
        search_dir_param = params.get("directory", "")
        search_full = ensure_under_root(search_dir_param, self.root_dir)

        # Try subprocess grep on POSIX; findstr on Windows; fall through to Python
        args = build_grep_args(pattern, search_full)
        if args is not None:
            try:
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    errors='replace',
                )
                output = result.stdout.strip()
                if output:
                    lines = output.split('\n')[:50]
                    return ToolResult(
                        True,
                        '\n'.join(lines),
                        summary=f"{min(len(lines), 50)} matches",
                    )
                return ToolResult(True, "", summary="0 matches")
            except subprocess.TimeoutExpired:
                return ToolResult(False, "", error="grep timed out after 30s")
            except Exception as e:
                pass

        # Windows: try findstr as a faster fallback than Python os.walk
        if _IS_WINDOWS:
            result = _windows_findstr(pattern, search_full)
            if result.error is None:
                return result

        # Fallback: Python implementation
        return python_grep_impl(pattern, search_full, self.root_dir)
