"""Dependency listing and file info tools."""

import os
import json
import re
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root
from datetime import datetime


class ListDependenciesTool(BaseTool):
    name = "list_dependencies"
    description = (
        "List project dependencies by reading dependency manifest files. "
        "Auto-detects: requirements.txt (Python), pom.xml (Java/Maven), "
        "package.json (JS/Node), .csproj (C#), Gemfile (Ruby), go.mod (Go). "
        "Options: search_dir (default project root). "
        "Returns dependency names and versions."
    )
    parameters = {"search_dir": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        search_dir = ensure_under_root(params.get("search_dir", ""), self.root_dir)

        deps = []

        # Python: requirements.txt
        for name in ['requirements.txt', 'requirements-dev.txt', 'pyproject.toml', 'setup.py', 'Pipfile']:
            path = os.path.join(search_dir, name)
            if os.path.isfile(path):
                try:
                    with open(path, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#') and not line.startswith('-'):
                                dep = re.split(r'[>=<!~]', line)[0].strip()
                                if dep:
                                    deps.append({"name": dep, "source": name})
                except OSError:
                    pass

        # Java: pom.xml
        pom_path = os.path.join(search_dir, "pom.xml")
        if os.path.isfile(pom_path):
            try:
                with open(pom_path, 'r') as f:
                    content = f.read()
                for m in re.finditer(r'<groupId>([^<]+)</groupId>.*?<artifactId>([^<]+)</artifactId>.*?<version>([^<]*)</version>', content, re.DOTALL):
                    deps.append({"name": f"{m.group(1)}:{m.group(2)}", "version": m.group(3).strip(), "source": "pom.xml"})
            except OSError:
                pass

        # Node: package.json
        pkg_path = os.path.join(search_dir, "package.json")
        if os.path.isfile(pkg_path):
            try:
                with open(pkg_path, 'r') as f:
                    data = json.load(f)
                for section in ['dependencies', 'devDependencies']:
                    for name, ver in data.get(section, {}).items():
                        deps.append({"name": name, "version": str(ver), "source": "package.json", "section": section})
            except (OSError, json.JSONDecodeError):
                pass

        # C#: .csproj
        for root, dirs, files in os.walk(search_dir):
            for fname in files:
                if fname.endswith('.csproj'):
                    cs_path = os.path.join(root, fname)
                    try:
                        with open(cs_path, 'r') as f:
                            content = f.read()
                        for m in re.finditer(r'<PackageReference\s+Include="([^"]+)"\s*Version="([^"]+)"', content):
                            deps.append({"name": m.group(1), "version": m.group(2), "source": fname})
                    except OSError:
                        pass

        return ToolResult(True, json.dumps(deps[:100], indent=2),
                          summary=f"{len(deps)} dependencies found",
                          file_paths=deps[:10] if deps else [])


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
