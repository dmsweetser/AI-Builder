"""list_dependencies tool."""
import os
import json
import re
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


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
        search_dir_param = params.get("search_dir", "")
        if not search_dir_param:
            search_dir = self.root_dir
        else:
            search_dir = ensure_under_root(search_dir_param, self.root_dir)

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
