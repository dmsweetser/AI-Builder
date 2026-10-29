"""grep_code tool - optimized with subprocess grep (cross-platform)."""
import os
import platform
import subprocess
import re
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root

_EXCLUDE_DIRS = [
    '--exclude-dir=.{1,}',
    '--exclude-dir=node_modules',
    '--exclude-dir=__pycache__',
    '--exclude-dir=venv',
    '--exclude-dir=.git',
    '--exclude-dir=bin',
    '--exclude-dir=obj',
    '--exclude-dir=Target',
]

# Detect if we have a working POSIX grep (not Windows native)
_OSX_OR_LINUX = platform.system() in ('Darwin', 'Linux')
_IS_WINDOWS = platform.system() == 'Windows'


def _build_grep_args(pattern: str, search_dir: str) -> list | None:
    """Build cross-platform grep command arguments."""
    if _OSX_OR_LINUX:
        return (
            ['grep', '-rn', '--include=*', '-I']
            + _EXCLUDE_DIRS
            + [pattern, search_dir]
        )
    elif _IS_WINDOWS:
        # Windows: return None to trigger _windows_findstr call
        return None
    else:
        return None


def _windows_findstr(pattern: str, search_dir: str) -> ToolResult:
    """Use findstr on Windows for faster searching than Python os.walk."""
    matches = []
    try:
        # findstr doesn't support --exclude-dir, so we need to filter manually
        result = subprocess.run(
            ['findstr', '/R', '/N', '/I', pattern, f'{search_dir}\\*'],
            capture_output=True,
            text=True,
            timeout=30,
            errors='replace',
        )
        output = result.stdout.strip()
        if output:
            for line in output.split('\n')[:50]:
                # findstr output format: filename:linenum:content
                # But with /N it's: linenum:filename:content or filename(linenum):content
                # We'll try to parse it
                if ':' in line:
                    # Try to extract file path and line number
                    parts = line.split(':', 2)
                    if len(parts) >= 2:
                        # Filter out excluded directories
                        if any(d in parts[0] for d in ['.git', '__pycache__', 'node_modules', 'venv']):
                            continue
                        matches.append(line)
    except subprocess.TimeoutExpired:
        return ToolResult(False, "", error="findstr timed out after 30s")
    except Exception as e:
        return ToolResult(False, "", error=f"findstr failed: {e}")

    if matches:
        return ToolResult(True, '\n'.join(matches), summary=f"{min(len(matches), 50)} matches")
    return ToolResult(True, "", summary="0 matches")


def _python_grep_impl(pattern: str, search_dir: str, root_dir: str) -> ToolResult:
    """Python regex implementation for fallback."""
    matches = []
    try:
        for dirpath, dirs, files in os.walk(search_dir):
            # Filter excluded directories in-place
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.git', 'bin', 'obj', 'Target')]
            for fname in sorted(files):
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                        for line_no, line in enumerate(f, 1):
                            if pattern in line:
                                rel = os.path.relpath(fpath, root_dir)
                                matches.append(f"{rel}:{line_no}: {line.rstrip()}")
                                if len(matches) >= 50:
                                    return ToolResult(True, "\n".join(matches), summary=f"{len(matches)} matches")
                except (OSError, PermissionError):
                    continue
    except OSError as e:
        return ToolResult(False, "", error=str(e))

    return ToolResult(True, "\n".join(matches), summary=f"{len(matches)} matches")


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

        # Try subprocess grep on POSIX; findstr on Windows; fall through to Python
        args = _build_grep_args(pattern, search_full)
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
                # grep/findstr command failed — fall through to Python
                pass

        # Windows: try findstr as a faster fallback than Python os.walk
        if _IS_WINDOWS:
            result = _windows_findstr(pattern, search_full)
            if result.error is None:
                return result

        # Fallback: Python implementation
        return _python_grep_impl(pattern, search_full, self.root_dir)

    def _python_grep(self, pattern: str, search_dir: str) -> ToolResult:
        """Alias for _python_grep_impl for backward compatibility."""
        return _python_grep_impl(pattern, search_dir, self.root_dir)


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
        args = _build_grep_args(pattern, search_full)
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
                # grep/findstr command failed — fall through to Python
                pass

        # Windows: try findstr as a faster fallback than Python os.walk
        if _IS_WINDOWS:
            result = _windows_findstr(pattern, search_full)
            if result.error is None:
                return result

        # Fallback: Python implementation
        return _python_grep_impl(pattern, search_full, self.root_dir)
