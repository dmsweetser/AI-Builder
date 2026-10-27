"""edit_file tool."""
import os
import re
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Make a targeted edit to an existing file. "
        "Specify the exact original text (original_text) and the replacement text (new_text). "
        "The original_text must match exactly (whitespace-sensitive). "
        "For multi-line edits, include the full lines. "
        "Use read_file first to get the exact original text."
    )
    parameters = {"path": "string", "original_text": "string", "new_text": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)
        original = params["original_text"]
        new_text = params["new_text"]

        # Interpret literal \n and \t sequences as actual newlines/tabs
        original = original.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")
        new_text = new_text.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (OSError, PermissionError) as e:
            return ToolResult(False, "", error=f"Cannot read file: {e}")

        if original not in content:
            # Try flexible match: normalize whitespace
            norm_orig = re.sub(r'\s+', ' ', original.strip())
            norm_content = re.sub(r'\s+', ' ', content)
            if norm_orig in norm_content:
                if original.strip() in content:
                    new_content = content.replace(original, new_text, 1)
                else:
                    return ToolResult(False, "",
                                      error="Original text not found (flexible match found but exact text differs). "
                                            "Use read_file to get the exact original text.")
            else:
                return ToolResult(False, "",
                                  error="Original text not found in file. "
                                        "Use read_file to get the exact text to replace.")
        else:
            # Original text found - do the replacement
            new_content = content.replace(original, new_text, 1)

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            # Verify the file content actually changed
            with open(path, 'r', encoding='utf-8') as f:
                actual = f.read()
            if actual != new_content:
                return ToolResult(False, "",
                                  error="File verification failed: content does not match after write")
            if actual == content:
                return ToolResult(False, "",
                                  error="Edit verification failed: file content did not change")
            return ToolResult(True, f"Edited {params['path']}",
                              summary=f"Replaced section in: {params['path']}")
        except OSError as e:
            return ToolResult(False, "", error=f"Cannot write file: {e}")
