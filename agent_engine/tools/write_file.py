"""write_file tool."""
import os
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class WriteFileTool(BaseTool):
    name = "write_file"
    description = (
        "Write or overwrite a file with new content. "
        "Creates parent directories if needed. "
        "Use this to create new files or replace entire files. "
        "For targeted edits, use edit_file instead."
    )
    parameters = {"path": "string", "content": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)
        content = params["content"]

        # Create parent directories
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        # Write atomically using a temp file + rename
        tmp_path = path + '.tmp_write'
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except OSError as e:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return ToolResult(False, "", error=f"Cannot write file: {e}")

        # Verify the file was actually written
        with open(path, 'r', encoding='utf-8') as f:
            written = f.read()
        if written != content:
            return ToolResult(False, "",
                              error="File verification failed: written content does not match requested content")
        return ToolResult(True, f"Written {len(content)} chars to {params['path']}",
                          summary=f"Created/overwrote: {params['path']}")
