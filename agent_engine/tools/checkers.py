"""Syntax and compiler checking tools for Python, Java, C#, JavaScript, HTML, CSS, XML, JSON."""

import os
import re
import json
import subprocess
import tempfile
import shutil
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root, ToolError


class CheckSyntaxTool(BaseTool):
    name = "check_syntax"
    description = (
        "Check syntax of a file without executing it. "
        "Language detected from file extension: .py (Python), .java (Java), "
        ".cs (C#), .js/.ts (JavaScript/TypeScript), .html (HTML), .css (CSS). "
        "Returns success/failure and any error messages."
    )
    parameters = {"path": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        ext = os.path.splitext(path)[1].lower()

        if ext == '.py':
            return self._check_python(path)
        elif ext == '.java':
            return self._check_java(path)
        elif ext == '.cs':
            return self._check_csharp(path)
        elif ext in ('.js', '.ts', '.jsx', '.tsx'):
            return self._check_javascript(path)
        elif ext in ('.html', '.htm'):
            return self._check_html(path)
        elif ext in ('.css', '.scss', '.less'):
            return self._check_css(path)
        elif ext in ('.xml',):
            return self._check_xml(path)
        elif ext in ('.json',):
            return self._check_json(path)
        else:
            return ToolResult(False, "",
                              error=f"Unknown file type '{ext}'. Supported: .py, .java, .cs, .js, .ts, .html, .css, .xml, .json")

    def _check_python(self, path: str) -> ToolResult:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                source = f.read()
            compile(source, path, 'exec', dont_inherit=True)
            return ToolResult(True, f"Python syntax OK ({path})",
                              summary="Syntax check passed")
        except SyntaxError as e:
            line_text = getattr(e, 'text', '') or ''
            return ToolResult(False, f"SyntaxError at line {e.lineno}: {e.msg}\n  {line_text or ''}",
                              error=f"SyntaxError line {e.lineno}: {e.msg}")
        except Exception as e:
            return ToolResult(False, "", error=str(e))

    def _check_java(self, path: str) -> ToolResult:
        """Check Java syntax via javac if available, otherwise brace matching."""
        java_home = os.getenv("JAVA_HOME")
        javac = None
        if java_home:
            javac = os.path.join(java_home, "bin", "javac")
        else:
            javac = "javac"

        try:
            result = subprocess.run(
                [javac, "-d", "/tmp", "-Xlint:-all", path],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                return ToolResult(True, f"Java syntax OK ({path})", summary="Syntax check passed")
            # Parse javac output for errors
            errors = []
            for line in result.stderr.split('\n'):
                if 'error:' in line or 'Note:' not in line:
                    errors.append(line.strip())
            if errors:
                return ToolResult(False, "\n".join(errors[:10]), error=errors[0] if errors else "Java compilation failed")
            return ToolResult(True, f"Java syntax OK ({path})", summary="Syntax check passed")
        except FileNotFoundError:
            return self._check_java_braces(path)
        except subprocess.TimeoutExpired:
            return self._check_java_braces(path)
        except Exception as e:
            return self._check_java_braces(path)

    def _check_java_braces(self, path: str) -> ToolResult:
        """Fallback Java syntax check: brace matching."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            errors = []
            brace_depth = 0
            paren_depth = 0
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('/*'):
                    continue
                brace_depth += stripped.count('{') - stripped.count('}')
                paren_depth += stripped.count('(') - stripped.count(')')
                if brace_depth < 0:
                    errors.append(f"Line {i}: Unmatched closing brace")
                    break
                if paren_depth < 0:
                    errors.append(f"Line {i}: Unmatched closing parenthesis")
                    break
            if brace_depth != 0:
                errors.append(f"Unmatched braces: {brace_depth} unclosed")
            if paren_depth != 0:
                errors.append(f"Unmatched parentheses: {paren_depth} unclosed")
            if errors:
                return ToolResult(False, "\n".join(errors), error=errors[0])
            return ToolResult(True, f"Java syntax OK ({path}) [braces]", summary="Basic syntax check passed")
        except Exception as e:
            return ToolResult(False, "", error=str(e))

    def _check_csharp(self, path: str) -> ToolResult:
        """Check C# syntax via dotnet if available, otherwise brace matching."""
        dotnet = None
        dotnet_cli = os.getenv("DOTNET_CLI_PATH")
        if dotnet_cli and os.path.isfile(dotnet_cli):
            dotnet = dotnet_cli
        else:
            candidates = [
                "/usr/share/dotnet/dotnet",
                "/usr/bin/dotnet",
                "/usr/local/bin/dotnet",
                "dotnet",
            ]
            for c in candidates:
                if os.path.isfile(c) or (c == "dotnet" and subprocess.run(["which", "dotnet"], capture_output=True).returncode == 0):
                    dotnet = c
                    break

        if not dotnet:
            return self._check_csharp_braces(path)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                proj_file = os.path.join(tmpdir, "check.csproj")
                with open(proj_file, 'w') as f:
                    f.write('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>')

                src_dir = os.path.join(tmpdir, "src")
                os.makedirs(src_dir)
                shutil.copy2(path, os.path.join(src_dir, os.path.basename(path)))

                result = subprocess.run(
                    [dotnet, "build", tmpdir, "--no-restore", "-v", "q"],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0:
                    return ToolResult(True, f"C# syntax OK ({path})", summary="Syntax check passed")
                errors = []
                for line in result.stderr.split('\n'):
                    if 'error CS' in line:
                        errors.append(line.strip())
                if errors:
                    return ToolResult(False, "\n".join(errors[:10]), error=errors[0])
                return ToolResult(False, result.stderr[:500], error="C# compilation failed")
        except FileNotFoundError:
            return self._check_csharp_braces(path)
        except subprocess.TimeoutExpired:
            return self._check_csharp_braces(path)
        except Exception as e:
            return self._check_csharp_braces(path)

    def _check_csharp_braces(self, path: str) -> ToolResult:
        """Fallback C# syntax check: brace matching."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            errors = []
            brace_depth = 0
            paren_depth = 0
            for line in content.split('\n'):
                stripped = line.strip()
                if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*'):
                    continue
                cleaned = re.sub(r'["\'].*?["\']', '', stripped)
                brace_depth += cleaned.count('{') - cleaned.count('}')
                paren_depth += cleaned.count('(') - cleaned.count(')')
                if brace_depth < 0:
                    errors.append(f"Unmatched closing brace")
                    break
                if paren_depth < 0:
                    errors.append(f"Unmatched closing parenthesis")
                    break
            if brace_depth != 0:
                errors.append(f"Unmatched braces: {brace_depth} unclosed")
            if paren_depth != 0:
                errors.append(f"Unmatched parentheses: {paren_depth} unclosed")
            if errors:
                return ToolResult(False, "\n".join(errors), error=errors[0])
            return ToolResult(True, f"C# syntax OK ({path}) [braces]", summary="Basic syntax check passed")
        except Exception as e:
            return ToolResult(False, "", error=str(e))

    def _check_javascript(self, path: str) -> ToolResult:
        """Check JavaScript/TypeScript syntax via node if available."""
        try:
            result = subprocess.run(
                ["node", "--check", path],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return ToolResult(True, "JavaScript syntax OK", summary="Syntax check passed")
            return ToolResult(False, result.stderr[:500], error=result.stderr[:200])
        except FileNotFoundError:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                errors = []
                braces = parens = 0
                for line in content.split('\n'):
                    stripped = line.strip()
                    if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*'):
                        continue
                    cleaned = re.sub(r'["\'].*?["\']', '', stripped)
                    braces += cleaned.count('{') - cleaned.count('}')
                    parens += cleaned.count('(') - cleaned.count(')')
                if braces != 0:
                    errors.append(f"Unmatched braces: {braces}")
                if parens != 0:
                    errors.append(f"Unmatched parentheses: {parens}")
                if errors:
                    return ToolResult(False, "\n".join(errors), error=errors[0])
                return ToolResult(True, "JavaScript syntax OK (basic check)", summary="Basic syntax check passed")
            except Exception as e:
                return ToolResult(False, "", error=str(e))

    def _check_html(self, path: str) -> ToolResult:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            errors = []
            open_tags = []
            for m in re.finditer(r'<(\w+)(?:\s[^>]*)?>(?:(?!</?\1\s*>).)*', content):
                tag = m.group(1).lower()
                if tag in ('br', 'hr', 'img', 'input', 'meta', 'link', 'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'):
                    continue
                if not content[m.start():m.start()+2].startswith('</'):
                    open_tags.append((tag, m.start()))
            if open_tags:
                errors.append(f"Unclosed tags: {', '.join(t[0] for t in open_tags[:5])}")
            if errors:
                return ToolResult(False, "\n".join(errors), error=errors[0])
            return ToolResult(True, "HTML syntax OK", summary="Basic HTML check passed")
        except Exception as e:
            return ToolResult(False, "", error=str(e))

    def _check_css(self, path: str) -> ToolResult:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            brace_depth = 0
            for line in content.split('\n'):
                stripped = line.strip()
                if stripped.startswith('/*') or stripped.startswith('*'):
                    continue
                brace_depth += stripped.count('{') - stripped.count('}')
            if brace_depth != 0:
                return ToolResult(False, f"Unmatched CSS braces: {brace_depth}", error="Unmatched braces")
            return ToolResult(True, "CSS syntax OK", summary="Basic CSS check passed")
        except Exception as e:
            return ToolResult(False, "", error=str(e))

    def _check_xml(self, path: str) -> ToolResult:
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(path)
            return ToolResult(True, "XML syntax OK", summary="XML check passed")
        except ET.ParseError as e:
            return ToolResult(False, f"XML ParseError: {e}", error=str(e))
        except Exception as e:
            return ToolResult(False, "", error=str(e))

    def _check_json(self, path: str) -> ToolResult:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                json.load(f)
            return ToolResult(True, "JSON syntax OK", summary="JSON check passed")
        except json.JSONDecodeError as e:
            return ToolResult(False, f"JSON ParseError at line {e.lineno}: {e.msg}", error=str(e))
