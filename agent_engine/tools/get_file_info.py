"""get_file_info tool."""
import os
import json
from datetime import datetime
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class GetFileInfoTool(BaseTool):
    name = "get_file_info"
    description = (
        "Get metadata about a file: size, modification time, line count, "
        "file type (text/binary), and detected language. "
        "Use this to understand file characteristics before reading."
    )
    parameters = {"path": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        try:
            stat = os.stat(path)
            size = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()

            ext = os.path.splitext(path)[1].lower()
            lang_map = {
                '.py': 'python', '.java': 'java', '.cs': 'csharp',
                '.js': 'javascript', '.ts': 'typescript', '.jsx': 'javascript',
                '.tsx': 'typescript', '.html': 'html', '.css': 'css',
                '.xml': 'xml', '.json': 'json', '.yml': 'yaml', '.yaml': 'yaml',
                '.md': 'markdown', '.txt': 'text', '.sh': 'shell', '.bat': 'batch',
                '.ps1': 'powershell', '.sql': 'sql', '.rb': 'ruby', '.go': 'go',
            }
            language = lang_map.get(ext, 'unknown')

            is_binary = False
            try:
                with open(path, 'rb') as f:
                    chunk = f.read(8192)
                    if b'\x00' in chunk:
                        is_binary = True
            except OSError:
                pass

            line_count = 0
            if not is_binary:
                try:
                    with open(path, 'r', encoding='utf-8', errors='replace') as f:
                        line_count = sum(1 for _ in f)
                except OSError:
                    pass

            return ToolResult(True, json.dumps({
                "path": params["path"],
                "full_path": path,
                "size": size,
                "modified": mtime,
                "language": language,
                "is_binary": is_binary,
                "line_count": line_count,
                "extension": ext,
            }, indent=2), summary=f"{language} file, {size} bytes, {line_count} lines")
        except Exception as e:
            return ToolResult(False, "", error=str(e))
