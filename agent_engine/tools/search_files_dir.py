"""search_files_dir tool - find files by name pattern in a subdirectory."""
import fnmatch
import os
from typing import Dict

from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class SearchFilesDirTool(BaseTool):
    name = "search_files_dir"
    description = (
        "Find files by name pattern within a specific subdirectory. "
        "Matches against the filename only (directory parts of the pattern are ignored). "
        "Examples: '*.py' finds all Python files; 'test*' finds files starting with 'test'; "
        "'**/*.java' or 'src/*.java' both become '*.java' and match any .java file. "
        "Searches the specified subdirectory tree. Returns matching file paths relative to the project root."
    )
    parameters = {"pattern": "string", "directory": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        pattern = params["pattern"]
        search_dir_param = params.get("directory", "")
        search_full = self.root_dir if not search_dir_param else ensure_under_root(search_dir_param, self.root_dir)

        # Strip directory components from the pattern so '**/foo.py' and 'foo.py'
        # both match files named 'foo.py' regardless of their directory.
        match_pattern = os.path.basename(pattern)

        matches = []
        try:
            for root, dirs, files in os.walk(search_full):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.git', 'bin', 'obj', 'Target')]
                for fname in files:
                    if fnmatch.fnmatch(fname, match_pattern):
                        full = os.path.join(root, fname)
                        rel = os.path.relpath(full, self.root_dir)
                        matches.append(rel)
        except OSError as e:
            return ToolResult(False, "", error=str(e))

        matches.sort()
        return ToolResult(True, "\n".join(matches), summary=f"{len(matches)} files")
