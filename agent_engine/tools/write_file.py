"""write_file tool."""
import os
import fcntl
import time
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class FileLock:
    """Simple file-based lock for preventing concurrent writes."""

    def __init__(self, lock_path: str, timeout: float = 30.0):
        self.lock_path = lock_path + ".lock"
        self.timeout = timeout
        self._lock_file = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

    def acquire(self):
        """Acquire the lock (blocking with timeout)."""
        self._lock_file = open(self.lock_path, 'w')
        deadline = time.time() + self.timeout
        while True:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except (IOError, OSError):
                if time.time() >= deadline:
                    self._lock_file.close()
                    self._lock_file = None
                    raise TimeoutError(f"Could not acquire lock on {self.lock_path} within {self.timeout}s")
                time.sleep(0.05)

    def release(self):
        """Release the lock."""
        if self._lock_file:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except OSError:
                pass
            self._lock_file = None


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
