"""edit_file tool — line-range replacement.

Replaces lines line_start..line_end (1-indexed, inclusive) with new content.
The caller must provide a complete replacement for the specified line range.
"""
import os
from typing import Any, Dict, Optional
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Replace lines line_start through line_end (1-indexed, inclusive) in a file "
        "with new content. Read the file first with read_file to see what to replace. "
        "Provide a complete replacement — the content in line_start..line_end will be "
        "entirely replaced by new_text. After editing, you MUST read back the affected "
        "area (lines line_start-5 through line_end+5, clamped to file bounds) to verify "
        "the change was applied correctly."
    )
    parameters = {
        "path": "string",
        "line_start": "integer (1-indexed)",
        "line_end": "integer (1-indexed, inclusive)",
        "new_text": "string (complete replacement for lines line_start..line_end)",
    }

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)
        new_text = params.get("new_text", "")
        line_start_str = params.get("line_start", "").strip()
        line_end_str = params.get("line_end", "").strip()

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        try:
            ls = int(line_start_str)
            le = int(line_end_str)
        except (ValueError, TypeError):
            return ToolResult(False, "", error="line_start and line_end must be integers")

        if ls < 1 or le < ls:
            return ToolResult(False, "", error=f"Invalid line range: line_start={ls}, line_end={le} (must be 1 <= line_start <= line_end)")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw_lines = f.readlines()
        except (OSError, PermissionError) as e:
            return ToolResult(False, "", error=f"Cannot read file: {e}")

        # Convert to 0-indexed
        ls0 = ls - 1
        le0 = le  # exclusive end for slicing

        if ls0 < 0 or ls0 >= len(raw_lines):
            return ToolResult(False, "", error=f"line_start={ls} is out of range (file has {len(raw_lines)} lines)")
        if le0 > len(raw_lines):
            return ToolResult(False, "", error=f"line_end={le} exceeds file length ({len(raw_lines)} lines)")

        # Preserve original line endings for the prefix
        # Reconstruct: lines before range + new_text + lines after range
        prefix = ''.join(raw_lines[:ls0])
        suffix = ''.join(raw_lines[le0:])

        # Ensure new_text ends with newline if the original last line did
        if raw_lines and raw_lines[-1].endswith('\n') and new_text and not new_text.endswith('\n'):
            new_text += '\n'

        new_content = prefix + new_text + suffix

        # Write atomically
        tmp_path = path + '.tmp_edit'
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except OSError as e:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return ToolResult(False, "", error=f"Cannot write file: {e}")

        # Verify the file actually changed
        with open(path, 'r', encoding='utf-8') as f:
            actual = f.read()
        if actual != new_content:
            return ToolResult(False, "", error="File verification failed: content does not match after write")

        return ToolResult(True, f"Replaced lines {ls}-{le} in {params['path']}",
                          summary=f"Replaced lines {ls}-{le} in: {params['path']}")
