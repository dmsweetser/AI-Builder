"""list_directory_deep tool."""
import json
import os
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class ListDirectoryDeepTool(BaseTool):
    name = "list_directory_deep"
    description = (
        "Recursively list files and directories up to a given depth. "
        "Use this to explore subdirectories of a project. "
        "Returns relative paths with type (file/directory) and size. "
        "depth parameter: how many levels deep to traverse (default 2)."
    )
    parameters = {"path": "string", "depth": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)
        depth = int(params.get("depth", params.get("max_depth", "2")))
        entries = []
        self._walk_dir(path, "", depth, entries)
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
