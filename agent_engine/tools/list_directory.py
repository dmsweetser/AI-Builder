"""list_directory tool."""
import json
import os
from typing import Any, Dict, List
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = (
        "List files and directories in a directory. "
        "Use this to explore the project structure before making changes. "
        "Returns relative paths with type (file/directory) and size. "
        "You can also use 'max_depth' parameter for recursive listing."
    )
    parameters = {"path": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        import logging
        logger = logging.getLogger(f"tool.{self.name}")
        
        path = ensure_under_root(params["path"], self.root_dir)
        max_depth = params.get("max_depth", "")
        if max_depth:
            depth = int(max_depth)
            entries = []
            self._walk_dir(path, "", depth, entries)
        else:
            entries = []
            self._walk_dir(path, "", 1, entries)
        result_json = json.dumps(entries, indent=2)
        # Log directory listing details for debugging
        logger.info(
            f"path='{params.get('path', '.')}' "
            f"resolved='{path}' entries={len(entries)} "
            f"output_chars={len(result_json)}"
        )
        return ToolResult(True, result_json, summary=f"{len(entries)} entries")

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
