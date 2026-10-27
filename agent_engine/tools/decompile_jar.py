"""decompile_jar tool."""
import os
import json
import subprocess
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root
from agent_engine.config import EngineConfig


class DecompileJarTool(BaseTool):
    name = "decompile_jar"
    description = (
        "Decompile a JAR file to extract Java source/class files. "
        "Use this when working with Java projects that have dependency JARs. "
        "Options: output_dir (where to extract, default ./_jar_decomp/<jar_name>). "
        "Requires jd-cli or javap to be installed. "
        "Returns list of extracted file paths."
    )
    parameters = {"jar_path": "string", "output_dir": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        jar_path = ensure_under_root(params["jar_path"], self.root_dir)

        if not os.path.isfile(jar_path):
            return ToolResult(False, "", error=f"JAR file not found: {params['jar_path']}")

        output_dir = params.get("output_dir", "")
        if output_dir:
            output_dir = ensure_under_root(output_dir, self.root_dir)
        else:
            jar_name = os.path.splitext(os.path.basename(jar_path))[0]
            output_dir = os.path.join(self.root_dir, "_jar_decomp", jar_name)
            output_dir = os.path.normpath(output_dir)

        # Try jd-cli first, then javap
        jd_cli = EngineConfig.get_jd_cli_path()
        if not jd_cli:
            candidates = [
                os.path.join(EngineConfig.get_java_home() or "", "bin", "jd-cli"),
                os.path.join(self.root_dir, "jd-cli"),
                "jd-cli",
            ]
            for c in candidates:
                if c and os.path.isfile(c):
                    jd_cli = c
                    break

        extracted = []

        if jd_cli and os.path.isfile(jd_cli):
            try:
                result = subprocess.run(
                    [jd_cli, "-jar", jar_path, "-d", output_dir],
                    capture_output=True, text=True, timeout=120
                )
                if result.returncode == 0:
                    for root, dirs, files in os.walk(output_dir):
                        for f in files:
                            full = os.path.join(root, f)
                            extracted.append(os.path.relpath(full, self.root_dir))
                    return ToolResult(True, json.dumps(extracted[:20], indent=2),
                                      summary=f"Decompiled {len(extracted)} files to {output_dir}",
                                      file_paths=extracted)
                else:
                    return ToolResult(False, "", error=f"jd-cli failed: {result.stderr[:500]}")
            except subprocess.TimeoutExpired:
                return ToolResult(False, "", error="jd-cli timed out after 120s")
            except OSError as e:
                return ToolResult(False, "", error=f"jd-cli execution failed: {e}")

        # Fallback: use jar + javap
        java_home = EngineConfig.get_java_home()
        if java_home:
            javap = os.path.join(java_home, "bin", "javap")
            jar_cmd = os.path.join(java_home, "bin", "jar")
        else:
            javap = "javap"
            jar_cmd = "jar"

        try:
            os.makedirs(output_dir, exist_ok=True)
            subprocess.run(
                [jar_cmd, "xf", jar_path],
                cwd=output_dir, capture_output=True, text=True, timeout=120
            )
            for root, dirs, files in os.walk(output_dir):
                for fname in files:
                    if fname.endswith('.class'):
                        class_file = os.path.join(root, fname)
                        try:
                            result = subprocess.run(
                                [javap, "-p", "-s", "-c", class_file],
                                capture_output=True, text=True, timeout=30,
                                cwd=output_dir
                            )
                            if result.returncode == 0:
                                class_name = os.path.splitext(fname)[0]
                                decompiled_file = os.path.join(root, class_name + ".javap.txt")
                                with open(decompiled_file, 'w', encoding='utf-8') as df:
                                    df.write(result.stdout)
                                extracted.append(os.path.relpath(decompiled_file, self.root_dir))
                            else:
                                extracted.append(os.path.relpath(class_file, self.root_dir))
                        except Exception:
                            extracted.append(os.path.relpath(class_file, self.root_dir))
            return ToolResult(True, json.dumps(extracted[:20], indent=2),
                              summary=f"Extracted/decompiled {len(extracted)} class files",
                              file_paths=extracted)
        except Exception as e:
            return ToolResult(False, "", error=f"Decompilation failed: {e}")
