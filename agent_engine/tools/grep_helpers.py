"""Shared helpers for grep_code tools."""
from __future__ import annotations

import os
import platform
import subprocess
from typing import Dict

from agent_engine.tools.base import ToolResult

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


def build_grep_args(pattern: str, search_dir: str) -> list | None:
    """Build cross-platform grep command arguments."""
    if _OSX_OR_LINUX:
        return (
            ['grep', '-rn', '--include=*', '-I']
            + _EXCLUDE_DIRS
            + [pattern, search_dir]
        )
    elif _IS_WINDOWS:
        return None
    else:
        return None


def _windows_findstr(pattern: str, search_dir: str) -> ToolResult:
    """Use findstr on Windows for faster searching than Python os.walk."""
    matches = []
    try:
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
                if ':' in line:
                    parts = line.split(':', 2)
                    if len(parts) >= 2:
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


def python_grep_impl(pattern: str, search_dir: str, root_dir: str) -> ToolResult:
    """Python regex implementation for fallback."""
    matches = []
    try:
        for dirpath, dirs, files in os.walk(search_dir):
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
