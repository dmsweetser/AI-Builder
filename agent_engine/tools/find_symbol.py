"""find_symbol tool."""
import os
import re
import json
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class FindSymbolTool(BaseTool):
    name = "find_symbol"
    description = (
        "Find references to a code symbol (class, function, variable, method). "
        "Searches for symbol name across the codebase. "
        "Options: symbol_type (class/function/variable/method/import, default any), "
        "language (python/java/csharp/js, default any), max_results (default 30). "
        "Returns file paths and line numbers where the symbol appears."
    )
    parameters = {"symbol": "string"}

    _SYMBOL_PATTERNS = {
        "python": [
            (r'\bclass\s+(\w+)', 'class'),
            (r'\bdef\s+(\w+)', 'function'),
            (r'^(?:from|import)\s+(\w+)', 'import'),
            (r'^\s*(?:const|let|var)\s+(\w+)', 'variable'),
            (r'^\s*(\w+)\s*=\s*(?:lambda|Function)', 'variable'),
        ],
        "java": [
            (r'\b(?:public|private|protected|\s)\s*class\s+(\w+)', 'class'),
            (r'\b(?:public|private|protected|\s)\s*(?:static\s+)?(?:final\s+)?\w+\s+(\w+)\s*\(', 'function'),
            (r'\bimport\s+([\w.]+)\.', 'import'),
        ],
        "csharp": [
            (r'\b(?:public|private|protected|internal)\s+class\s+(\w+)', 'class'),
            (r'\b(?:public|private|protected|internal)\s+(?:static\s+)?\w+\s+(\w+)\s*\(', 'function'),
            (r'\busing\s+([\w.]+)\s*;', 'import'),
        ],
        "javascript": [
            (r'\b(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)', 'function'),
            (r'\b(?:const|let|var)\s+(\w+)\s*=', 'variable'),
            (r'\bclass\s+(\w+)', 'class'),
            (r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]', 'import'),
        ],
    }

    def execute(self, params: Dict[str, str]) -> ToolResult:
        symbol = params["symbol"]
        language = params.get("language", "").lower()
        symbol_type = params.get("symbol_type", "").lower()
        max_results = int(params.get("max_results", "30"))

        # Build regex patterns to search for
        patterns = [re.escape(symbol)]

        # Add language-specific patterns
        if language and language in self._SYMBOL_PATTERNS:
            lang_pats = self._SYMBOL_PATTERNS[language]
            for pat, stype in lang_pats:
                if not symbol_type or symbol_type == stype:
                    modified = pat.replace(r'(\w+)', re.escape(symbol))
                    patterns.append(modified)
        elif not language:
            # Search for all language-specific patterns
            for lang_pats in self._SYMBOL_PATTERNS.values():
                for pat, stype in lang_pats:
                    if not symbol_type or symbol_type == stype:
                        modified = pat.replace(r'(\w+)', re.escape(symbol))
                        patterns.append(modified)

        # Also search for the symbol as a whole word
        patterns.append(r'\b' + re.escape(symbol) + r'\b')

        combined = '|'.join(set(patterns))
        try:
            regex = re.compile(combined)
        except re.error as e:
            return ToolResult(False, "", error=f"Invalid pattern: {e}")

        results = []
        seen = set()

        # Determine which file extensions to search
        extensions = set()
        if not language or language == 'python':
            extensions.update(['.py'])
        if not language or language == 'java':
            extensions.update(['.java'])
        if not language or language == 'csharp':
            extensions.update(['.cs'])
        if not language or language in ('js', 'javascript', 'typescript'):
            extensions.update(['.js', '.ts', '.jsx', '.tsx'])
        if not language or language in ('html',):
            extensions.update(['.html', '.htm'])
        if not language or language == 'css':
            extensions.update(['.css', '.scss', '.less'])

        if not extensions:
            extensions = {'.py', '.java', '.cs', '.js', '.ts', '.html', '.css', '.xml', '.json', '.yml', '.yaml'}

        try:
            for root, dirs, files in os.walk(self.root_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.git', 'bin', 'obj', 'Target')]
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in extensions:
                        continue
                    full = os.path.join(root, fname)
                    try:
                        with open(full, 'r', encoding='utf-8', errors='replace') as f:
                            for i, line in enumerate(f, 1):
                                if regex.search(line):
                                    key = (os.path.relpath(full, self.root_dir), i)
                                    if key not in seen:
                                        seen.add(key)
                                        results.append({
                                            "file": os.path.relpath(full, self.root_dir),
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
