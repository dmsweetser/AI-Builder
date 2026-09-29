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
        "Recurses up to max_depth levels. Returns relative paths."
    )
    parameters = {"path": "string", "max_depth": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)
        max_depth = int(params.get("max_depth", "1"))
        entries = []
        self._walk_dir(path, "", max_depth, entries)
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


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = (
        "Find files by name pattern using glob-style matching (e.g., '*.py', '**/*.java', 'test*'). "
        "Use this to locate files by name. Supports wildcards: * (any chars), ** (any dirs). "
        "Returns matching file paths relative to project root."
    )
    parameters = {"pattern": "string", "search_dir": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        pattern = params["pattern"]
        search_dir = params.get("search_dir", "")
        search_full = ensure_under_root(search_dir, self.root_dir) if search_dir else self.root_dir

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
        "Search file contents for a text pattern (plain text or regex). "
        "Use this to find code references, function usages, or specific strings. "
        "Options: max_results (default 50), file_pattern (optional glob filter). "
        "Returns matching file paths and line numbers."
    )
    parameters = {"pattern": "string", "search_dir": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        pattern = params["pattern"]
        search_dir = params.get("search_dir", "")
        search_full = ensure_under_root(search_dir, self.root_dir) if search_dir else self.root_dir
        # Handle optional params - may be int or string from LLM
        max_results_raw = params.get("max_results", "50")
        max_results = int(max_results_raw) if isinstance(max_results_raw, str) else max_results_raw
        file_pattern = params.get("file_pattern", "")

        try:
            compiled = re.compile(pattern)
        except re.error as e:
            return ToolResult(False, "", error=f"Invalid regex: {e}")

        results = []
        try:
            for root, dirs, files in os.walk(search_full):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.git', 'bin', 'obj', 'Target')]
                for fname in files:
                    if file_pattern and not fnmatch.fnmatch(fname, file_pattern):
                        continue
                    full = os.path.join(root, fname)
                    try:
                        with open(full, 'r', encoding='utf-8', errors='replace') as f:
                            for i, line in enumerate(f, 1):
                                if compiled.search(line):
                                    rel = os.path.relpath(full, self.root_dir)
                                    results.append({
                                        "file": rel,
                                        "line": i,
                                        "text": line.rstrip('\n'),
                                    })
                                    if len(results) >= max_results:
                                        return ToolResult(True, json.dumps(results, indent=2),
                                                          summary=f"{len(results)} matches (truncated)",
                                                          file_paths=list({r["file"] for r in results}))
                    except (OSError, PermissionError):
                        continue
        except OSError as e:
            return ToolResult(False, "", error=str(e))

        return ToolResult(True, json.dumps(results, indent=2),
                          summary=f"{len(results)} matches",
                          file_paths=list({r["file"] for r in results}))


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read the contents of a file. Use this to inspect code before modifying it. "
        "Options: start_line (1-indexed, default 1), end_line (default all). "
        "For large files, specify line ranges to avoid truncation."
    )
    parameters = {"path": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
        except (OSError, PermissionError) as e:
            return ToolResult(False, "", error=f"Cannot read file: {e}")

        start = int(params.get("start_line", "1")) - 1
        end = int(params.get("end_line", str(len(all_lines))))
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

        try:
            dir_path = os.path.dirname(path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
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
                    content = content.replace(original, new_text, 1)
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
            content = content.replace(original, new_text, 1)

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
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
