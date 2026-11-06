"""write_file tool."""
import os
import time
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.tools.file_lock import FileLock
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

        # Use file locking to prevent concurrent writes from corrupting files
        # (especially JSON files like projects.json)
        lock = FileLock(path)
        try:
            lock.acquire()
        except TimeoutError:
            return ToolResult(False, "", error=f"Could not acquire write lock for {params['path']}")

        try:
            dir_path = os.path.dirname(path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            # Verify the file was actually written by reading it back
            with open(path, 'r', encoding='utf-8') as f:
                written = f.read()
            if written != content:
                return ToolResult(False, "",
                                  error=f"File verification failed: written content does not match requested content")
            return ToolResult(True, f"Written {len(content)} chars to {params['path']}",
                              summary=f"Created/overwrote: {params['path']}")
        except OSError as e:
            return ToolResult(False, "", error=f"Cannot write file: {e}")
        finally:
            lock.release()
