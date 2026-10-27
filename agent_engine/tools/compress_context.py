"""compress_context tool."""
import os
from typing import Any, Dict
from agent_engine.tools.base import BaseTool, ToolResult


class CompressContextTool(BaseTool):
    """Tool that compresses conversation history by summarizing prior steps.

    When the context window is filling up, the agent can use this tool to
    summarize earlier tool results and conversation turns into a compact
    summary, freeing up tokens for new work.
    """
    name = "compress_context"
    description = (
        "Compress conversation history by summarizing prior tool results. "
        "This is useful when the context window is filling up. The tool "
        "accepts a 'summary' parameter containing a compact summary of prior "
        "steps. The agent should review earlier tool results and create a "
        "summary that captures what was learned, what files were modified, "
        "and what the current state of the project is. Use this when you "
        "have accumulated many tool results and need to free up context space."
    )
    parameters = {"summary": "string"}

    def execute(self, params: Dict[str, str]) -> ToolResult:
        summary = params.get("summary", "").strip()
        if not summary:
            return ToolResult(False, "", error="Summary is required")

        # Write the compressed context to a file so the engine can use it
        output_dir = os.environ.get("AIB_OUTPUT_DIR", "")
        if output_dir:
            context_file = os.path.join(output_dir, "compressed_context.txt")
            try:
                with open(context_file, 'w', encoding='utf-8') as f:
                    f.write(summary)
            except OSError:
                pass

        return ToolResult(
            True,
            f"Context compressed. Summary saved ({len(summary)} chars).",
            summary=f"Context compressed: {len(summary)} characters of prior history summarized.",
        )
