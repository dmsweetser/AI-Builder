"""search_files tool."""
import fnmatch
import os
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = (
        "Find files by name pattern using glob-style matching (e.g., '*.py', '**/*.java', 'test*'). "
        "Searches the entire project. Returns matching file paths relative to project root. "
        "You can also use 'directory' parameter to search in a specific subdirectory."
    )
    parameters = {"pattern": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        pattern = params["pattern"]
        search_dir_param = params.get("directory", "")
        search_full = self.root_dir if not search_dir_param else ensure_under_root(search_dir_param, self.root_dir)

        matches = []
        try:
            for root, dirs, files in os.walk(search_full):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.git', 'bin', 'obj', 'Target')]
                for fname in files:
                    if fnmatch.fnmatch(fname, pattern):
                        full = os.path.join(root, fname)
                        rel = os.path.relpath(full, self.root_dir)
                        matches.append(rel)
        except OSError as e:
            return ToolResult(False, "", error=str(e))

        matches.sort()
        return ToolResult(True, "\n".join(matches), summary=f"{len(matches)} files", file_paths=matches)


class SearchFilesDirTool(BaseTool):
    name = "search_files_dir"
    description = (
        "Find files by name pattern within a specific subdirectory. "
        "Use glob-style matching (e.g., '*.py', 'test*'). "
        "Returns matching file paths relative to project root."
    )
    parameters = {"pattern": "string", "directory": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        pattern = params["pattern"]
        search_dir_param = params.get("directory", "")
        search_full = self.root_dir if not search_dir_param else ensure_under_root(search_dir_param, self.root_dir)

        matches = []
        try:
            for root, dirs, files in os.walk(search_full):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.git', 'bin', 'obj', 'Target')]
                for fname in files:
                    if fnmatch.fnmatch(fname, pattern):
                        full = os.path.join(root, fname)
                        rel = os.path.relpath(full, self.root_dir)
                        matches.append(rel)
        except OSError as e:
            return ToolResult(False, "", error=str(e))

        matches.sort()
        return ToolResult(True, "\n".join(matches), summary=f"{len(matches)} files", file_paths=matches)
