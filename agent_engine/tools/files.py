"""File system tools: list_directory, search_files, grep_code, read_file, write_file, edit_file, delete_file."""

import os
import re
import json
import fnmatch
from typing import Any, Dict, List
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root, ToolError


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = (
        "List files and directories in a directory. "
        "Use this to explore the project structure before making changes. "
        "Returns relative paths with type (file/directory) and size. "
        "You can also use 'max_depth' parameter for recursive listing."
    )
    parameters = {"path": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)
        # Accept 'max_depth' as alias for recursive listing
        max_depth = params.get("max_depth", "")
        if max_depth:
            depth = int(max_depth)
            entries = []
            self._walk_dir(path, "", depth, entries)
        else:
            entries = []
            self._walk_dir(path, "", 1, entries)
        return ToolResult(True, json.dumps(entries, indent=2), summary=f"{len(entries)} entries")

    def _walk_dir(self, full_path: str, rel_prefix: str, depth: int, entries: list):
        if depth < 0:
            return
        try:
            for item in sorted(os.listdir(full_path)):
                full_item = os.path.join(full_path, item)
                rel_item = os.path.join(rel_prefix, item) if rel_prefix else item
                is_dir = os.path.isdir(full_item)
                try:
                    size = os.path.getsize(full_item) if not is_dir else None
                except OSError:
                    size = None
                entries.append({
                    "name": item,
                    "type": "directory" if is_dir else "file",
                    "path": rel_item,
                    "size": size,
                })
                if is_dir and depth > 0:
                    self._walk_dir(full_item, rel_item, depth - 1, entries)
        except PermissionError:
            entries.append({"name": rel_prefix, "type": "permission_denied", "path": rel_prefix})
        except OSError as e:
            entries.append({"name": rel_prefix, "type": "error", "path": rel_prefix, "error": str(e)})


class ListDirectoryDeepTool(BaseTool):
    name = "list_directory_deep"
    description = (
        "Recursively list files and directories up to a given depth. "
        "Use this to explore subdirectories of a project. "
        "Returns relative paths with type (file/directory) and size. "
        "depth parameter: how many levels deep to traverse (default 2)."
    )
    parameters = {"path": "string", "depth": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)
        # Accept 'max_depth' as alias for 'depth'
        depth = int(params.get("depth", params.get("max_depth", "2")))
        entries = []
        self._walk_dir(path, "", depth, entries)
        return ToolResult(True, json.dumps(entries, indent=2), summary=f"{len(entries)} entries")


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

        # Interpret literal \n and \t sequences as actual newlines/tabs
        content = content.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")

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


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Make a targeted edit to an existing file. "
        "Specify the exact original text (original_text) and the replacement text (new_text). "
        "The original_text must match exactly (whitespace-sensitive). "
        "For multi-line edits, include the full lines. "
        "Use read_file first to get the exact original text."
    )
    parameters = {"path": "string", "original_text": "string", "new_text": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)
        original = params["original_text"]
        new_text = params["new_text"]

        # Interpret literal \n and \t sequences as actual newlines/tabs
        original = original.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")
        new_text = new_text.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (OSError, PermissionError) as e:
            return ToolResult(False, "", error=f"Cannot read file: {e}")

        if original not in content:
            # Try flexible match: normalize whitespace
            norm_orig = re.sub(r'\s+', ' ', original.strip())
            norm_content = re.sub(r'\s+', ' ', content)
            if norm_orig in norm_content:
                if original.strip() in content:
                    new_content = content.replace(original, new_text, 1)
                else:
                    return ToolResult(False, "",
                                      error="Original text not found (flexible match found but exact text differs). "
                                            "Use read_file to get the exact original text.")
            else:
                return ToolResult(False, "",
                                  error="Original text not found in file. "
                                        "Use read_file to get the exact text to replace.")
        else:
            # Original text found - do the replacement
            new_content = content.replace(original, new_text, 1)

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            # Verify the file content actually changed
            with open(path, 'r', encoding='utf-8') as f:
                actual = f.read()
            if actual != new_content:
                return ToolResult(False, "",
                                  error="File verification failed: content does not match after write")
            if actual == content:
                return ToolResult(False, "",
                                  error="Edit verification failed: file content did not change")
            return ToolResult(True, f"Edited {params['path']}",
                              summary=f"Replaced section in: {params['path']}")
        except OSError as e:
            return ToolResult(False, "", error=f"Cannot write file: {e}")


class DeleteFileTool(BaseTool):
    name = "delete_file"
    description = (
        "Delete a file from the project. "
        "Use this to remove obsolete or unwanted files."
    )
    parameters = {"path": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        # Safety: don't delete backup files
        if path.endswith('.bak') or path.endswith('.backup'):
            return ToolResult(False, "", error="Refusing to delete backup file")

        try:
            os.remove(path)
            return ToolResult(True, f"Deleted: {params['path']}",
                              summary=f"Removed: {params['path']}")
        except OSError as e:
            return ToolResult(False, "", error=f"Cannot delete file: {e}")
