"""Base tool class and ToolResult."""

import json
from typing import Any, Dict, List, Optional


class ToolResult:
    """Wrapper for tool execution results."""
    def __init__(self, success: bool, content: str, error: str = "",
                 file_paths: List[str] = None, summary: str = ""):
        self.success = success
        self.content = content
        self.error = error
        self.file_paths = file_paths if file_paths is not None else []
        self.summary = summary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "content": self.content,
            "error": self.error,
            "file_paths": self.file_paths,
            "summary": self.summary,
        }


class BaseTool:
    """Base class for all tools."""
    name: str = ""
    description: str = ""
    parameters: Dict[str, str] = {}

    def __init__(self, root_dir: str):
        self.root_dir = root_dir

    def execute(self, params: Dict[str, str]) -> ToolResult:
        raise NotImplementedError

    def get_definition(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
