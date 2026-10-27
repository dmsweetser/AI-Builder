"""grep_code tool."""
import os
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class GrepCodeTool(BaseTool):
    name = "grep_code"
    description = (
        "Search file contents for a text pattern (plain text). "
        "Searches the entire project. Returns matching file paths and line numbers."
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
                for fname in sorted(files):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                            for line_no, line in enumerate(f, 1):
                                if pattern in line:
                                    rel = os.path.relpath(fpath, self.root_dir)
                                    matches.append(f"{rel}:{line_no}: {line.rstrip()}")
                                    if len(matches) >= 50:
                                        return ToolResult(True, "\n".join(matches), summary=f"{len(matches)} matches")
                    except (OSError, PermissionError):
                        continue
        except OSError as e:
            return ToolResult(False, "", error=str(e))

        return ToolResult(True, "\n".join(matches), summary=f"{len(matches)} matches")


class GrepCodeDirTool(BaseTool):
    name = "grep_code_dir"
    description = (
        "Search file contents for a text pattern within a specific subdirectory. "
        "Returns matching file paths and line numbers."
    )
    parameters = {"pattern": "string", "directory": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        search_dir_param = params.get("directory", "")
        search_full = self.root_dir if not search_dir_param else ensure_under_root(search_dir_param, self.root_dir)
        pattern = params["pattern"]
        matches = []
        try:
            for root, dirs, files in os.walk(search_full):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.git', 'bin', 'obj', 'Target')]
                for fname in sorted(files):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                            for line_no, line in enumerate(f, 1):
                                if pattern in line:
                                    rel = os.path.relpath(fpath, self.root_dir)
                                    matches.append(f"{rel}:{line_no}: {line.rstrip()}")
                                    if len(matches) >= 50:
                                        return ToolResult(True, "\n".join(matches), summary=f"{len(matches)} matches")
                    except (OSError, PermissionError):
                        continue
        except OSError as e:
            return ToolResult(False, "", error=str(e))

        return ToolResult(True, "\n".join(matches), summary=f"{len(matches)} matches")
