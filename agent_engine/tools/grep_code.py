"""grep_code tool - optimized with subprocess grep."""
import os
import subprocess
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
        
        # Use subprocess grep for better performance
        try:
            # Build exclude patterns for common directories to skip
            exclude_dirs = [
                '--exclude-dir=.{1,}',  # hidden dirs
                '--exclude-dir=node_modules',
                '--exclude-dir=__pycache__',
                '--exclude-dir=venv',
                '--exclude-dir=.git',
                '--exclude-dir=bin',
                '--exclude-dir=obj',
                '--exclude-dir=Target',
            ]
            
            # Run grep with reasonable limits
            result = subprocess.run(
                ['grep', '-rn', '--include=*', '-I'] + exclude_dirs + [pattern, search_full],
                capture_output=True,
                text=True,
                timeout=30,
                errors='replace'
            )
            
            output = result.stdout.strip()
            if not output:
                return ToolResult(True, "", summary="0 matches")
            
            # Limit results to 50 matches
            lines = output.split('\n')[:50]
            final_output = '\n'.join(lines)
            
            return ToolResult(
                True,
                final_output,
                summary=f"{min(len(lines), 50)} matches"
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, "", error="grep timed out after 30s")
        except FileNotFoundError:
            # Fallback to Python implementation if grep is not available
            return self._python_grep(pattern, search_full)
        except Exception as e:
            return ToolResult(False, "", error=str(e))

    def _python_grep(self, pattern: str, search_dir: str) -> ToolResult:
        """Fallback Python implementation if grep command is not available."""
        matches = []
        try:
            for root, dirs, files in os.walk(search_dir):
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
        pattern = params["pattern"]
        search_dir_param = params.get("directory", "")
        search_full = ensure_under_root(search_dir_param, self.root_dir)
        
        # Use subprocess grep for better performance
        try:
            # Build exclude patterns for common directories to skip
            exclude_dirs = [
                '--exclude-dir=.{1,}',  # hidden dirs
                '--exclude-dir=node_modules',
                '--exclude-dir=__pycache__',
                '--exclude-dir=venv',
                '--exclude-dir=.git',
                '--exclude-dir=bin',
                '--exclude-dir=obj',
                '--exclude-dir=Target',
            ]
            
            # Run grep with reasonable limits
            result = subprocess.run(
                ['grep', '-rn', '--include=*', '-I'] + exclude_dirs + [pattern, search_full],
                capture_output=True,
                text=True,
                timeout=30,
                errors='replace'
            )
            
            output = result.stdout.strip()
            if not output:
                return ToolResult(True, "", summary="0 matches")
            
            # Limit results to 50 matches
            lines = output.split('\n')[:50]
            final_output = '\n'.join(lines)
            
            return ToolResult(
                True,
                final_output,
                summary=f"{min(len(lines), 50)} matches"
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, "", error="grep timed out after 30s")
        except FileNotFoundError:
            # Fallback to Python implementation if grep is not available
            return self._python_grep(pattern, search_full)
        except Exception as e:
            return ToolResult(False, "", error=str(e))

    def _python_grep(self, pattern: str, search_dir: str) -> ToolResult:
        """Fallback Python implementation if grep command is not available."""
        matches = []
        try:
            for root, dirs, files in os.walk(search_dir):
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
