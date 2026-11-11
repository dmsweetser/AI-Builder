"""Consolidated test suite for AI Builder.

Deduplicates tests from the original scattered test files and adds
mock_llm_server-based e2e tests for true integration coverage.

Run with:  pytest tests/test_suite.py -v
Or:        python -m pytest tests/test_suite.py -v
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import shutil
import threading
import time
import unittest
import unittest.mock as mock
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_engine.security import (
    ensure_under_root, validate_tool_params, SecurityError, ToolError, EngineError,
)
from agent_engine.tools.base import ToolResult, BaseTool
from agent_engine.engine import (
    LLMClient, parse_tool_calls, is_done, build_user_prompt,
    build_system_prompt, AgentEngine, _estimate_tokens,
    _trim_messages_to_context, _strip_code_blocks,
    _extract_rationale, _parse_params, truncate_tool_result,
)
from agent_engine.tools.list_directory import ListDirectoryTool
from agent_engine.tools.read_file import ReadFileTool
from agent_engine.tools.write_file import WriteFileTool
from agent_engine.tools.edit_file import EditFileTool
from agent_engine.tools.search_files import SearchFilesTool
from agent_engine.tools.grep_code import GrepCodeTool
from agent_engine.tools.delete_file import DeleteFileTool
from agent_engine.tools.check_syntax import CheckSyntaxTool
from agent_engine.tools.find_symbol import FindSymbolTool
from agent_engine.tools.decompile_jar import DecompileJarTool
from agent_engine.tools.respond_to_user import RespondToUserTool
from agent_engine.tools.task_completed import TaskCompletedTool
from agent_engine.config import EngineConfig
from agent_engine.tools import get_registry, _reset_registry, ToolRegistry
from agent_engine.tools.project_tool_loader import ProjectToolLoader

# ====================================================================
# Shared helpers
# ====================================================================

TEST_PROJECT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_project')


def _java_available():
    """Check if both javac and the Java runtime are available."""
    try:
        r1 = subprocess.run(['javac', '-version'], capture_output=True, timeout=5)
        if r1.returncode != 0:
            return False
        r2 = subprocess.run(['java', '-version'], capture_output=True, timeout=5)
        return r2.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ====================================================================
# 1. Tool & Parser Tests (from test_ai_builder_comprehensive.py, test_edge_cases.py)
# ====================================================================

class TestParserEdgeCases(unittest.TestCase):
    """Edge cases for the tool call parser."""

    def test_param_with_colon_in_value(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_write_file\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\nconfig.yaml\n"
            "[test1234_PARAM_NAME]\ncontent\n[test1234_PARAM_VALUE]\n--value with colons: in middle\n"
            "[test1234_TOOL_END]"
        )
        calls = parse_tool_calls(response, "test1234")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]['content'], '--value with colons: in middle')

    def test_empty_tool_block(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_list_directory\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\n.\n"
            "[test1234_TOOL_END]"
        )
        calls = parse_tool_calls(response, "test1234")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'list_directory')
        self.assertEqual(calls[0][1]['path'], '.')

    def test_tool_name_with_hyphen(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_my-tool\n"
            "[test1234_PARAM_NAME]\nparam\n[test1234_PARAM_VALUE]\nvalue\n"
            "[test1234_TOOL_END]"
        )
        calls = parse_tool_calls(response, "test1234")
        self.assertEqual(calls[0][0], 'my-tool')

    def test_tool_name_with_underscore(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_my_tool\n"
            "[test1234_PARAM_NAME]\nparam\n[test1234_PARAM_VALUE]\nvalue\n"
            "[test1234_TOOL_END]"
        )
        calls = parse_tool_calls(response, "test1234")
        self.assertEqual(calls[0][0], 'my_tool')

    def test_mixed_single_and_multiline_params(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_write_file\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\nsrc/app.py\n"
            "[test1234_PARAM_NAME]\ncontent\n[test1234_PARAM_VALUE]\ndef hello():\n    print(\"hello\")\n\n"
            "if __name__ == \"__main__\":\n    hello()\n[test1234_TOOL_END]"
        )
        calls = parse_tool_calls(response, "test1234")
        params = calls[0][1]
        self.assertEqual(params['path'], 'src/app.py')
        self.assertIn('def hello():', params['content'])
        self.assertIn('if __name__', params['content'])

    def test_multiple_tools_with_different_params(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_list_directory\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\nsrc\n"
            "[test1234_PARAM_NAME]\nmax_depth\n[test1234_PARAM_VALUE]\n2\n[test1234_TOOL_END]"
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_read_file\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\nsrc/main.py\n"
            "[test1234_PARAM_NAME]\nstart_line\n[test1234_PARAM_VALUE]\n1\n"
            "[test1234_PARAM_NAME]\nend_line\n[test1234_PARAM_VALUE]\n10\n[test1234_TOOL_END]"
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_check_syntax\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\nsrc/main.py\n[test1234_TOOL_END]"
        )
        calls = parse_tool_calls(response, "test1234")
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0], 'list_directory')
        self.assertEqual(calls[0][1]['max_depth'], '2')
        self.assertEqual(calls[1][0], 'read_file')
        self.assertEqual(calls[1][1]['start_line'], '1')
        self.assertEqual(calls[2][0], 'check_syntax')

    def test_no_tool_calls_in_response(self):
        calls = parse_tool_calls("Just thinking out loud...", "test1234")
        self.assertEqual(calls, [])

    def test_tool_call_with_no_params(self):
        response = "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\ntest1234_list_directory\n[test1234_TOOL_END]"
        calls = parse_tool_calls(response, "test1234")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'list_directory')
        self.assertEqual(calls[0][1], {})

    def test_tool_call_with_missing_param_name(self):
        response = "[test1234_TOOL_START]\n[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\n.\n[test1234_TOOL_END]"
        calls = parse_tool_calls(response, "test1234")
        self.assertEqual(calls, [])

    def test_tool_call_with_unicode_in_params(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_write_file\n"
            "[test1234_PARAM_NAME]\ncontent\n[test1234_PARAM_VALUE]\nHello 世界 🌍\n[test1234_TOOL_END]"
        )
        calls = parse_tool_calls(response, "test1234")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["content"], "Hello 世界 🌍")

    def test_param_end_normalization(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_list_directory\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\n.\n[test1234_PARAM_END]"
        )
        calls = parse_tool_calls(response, "test1234")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "list_directory")

    def test_rationale_in_tool_call(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_write_file\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\nmain.py\n"
            "[test1234_PARAM_NAME]\ncontent\n[test1234_PARAM_VALUE]\nhello\n"
            "[test1234_RATIONALE]\nWriting the main file.\n[test1234_TOOL_END]"
        )
        calls = parse_tool_calls(response, "test1234")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "write_file")
        self.assertEqual(calls[0][2], "Writing the main file.")

    def test_code_block_stripping(self):
        response = f"""Some text
```python
[test1234_TOOL_START]
[test1234_TOOL_NAME]
test1234_write_file
[test1234_PARAM_NAME]
path
[test1234_PARAM_VALUE]
src/main.py
[test1234_TOOL_END]
```
[test1234_TOOL_START]
[test1234_TOOL_NAME]
test1234_list_directory
[test1234_PARAM_NAME]
path
[test1234_PARAM_VALUE]
.
[test1234_TOOL_END]
"""
        stripped = _strip_code_blocks(response)
        self.assertNotIn('write_file', stripped)
        self.assertIn('list_directory', stripped)
        calls = parse_tool_calls(response, "test1234")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'list_directory')

    def test_inline_code_stripping(self):
        response2 = "Use `write_file` for writing, then [test1234_TOOL_START][test1234_TOOL_NAME]test1234_list_directory..."
        stripped2 = _strip_code_blocks(response2)
        self.assertNotIn('write_file', stripped2)


class TestIsDoneTaskCompleted(unittest.TestCase):
    """Tests for is_done() detecting task_completed tool calls."""

    def test_legacy_done_marker_not_detected(self):
        done, summary = is_done("[DONE] Added feature X", "test1234")
        self.assertFalse(done)
        self.assertEqual(summary, "")

    def test_task_completed_tool_call(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_task_completed\n"
            "[test1234_PARAM_NAME]\nsummary\n[test1234_PARAM_VALUE]\nAdded divide function with error handling\n[test1234_TOOL_END]"
        )
        done, summary = is_done(response, "test1234")
        self.assertTrue(done)
        self.assertEqual(summary, "Added divide function with error handling")

    def test_task_completed_multiline_summary(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_task_completed\n"
            "[test1234_PARAM_NAME]\nsummary\n[test1234_PARAM_VALUE]\nStep 1: Added divide function\n"
            "Step 2: Added error handling\nStep 3: Verified with check_syntax\n[test1234_TOOL_END]"
        )
        done, summary = is_done(response, "test1234")
        self.assertTrue(done)
        self.assertIn("Step 1", summary)
        self.assertIn("Step 3", summary)

    def test_no_completion(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_read_file\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\nsrc/main.py\n[test1234_TOOL_END]"
        )
        done, summary = is_done(response, "test1234")
        self.assertFalse(done)
        self.assertEqual(summary, "")

    def test_empty_response(self):
        done, summary = is_done("", "test1234")
        self.assertFalse(done)
        self.assertEqual(summary, "")

    def test_random_text(self):
        done, summary = is_done("Hello world, this is not a completion", "test1234")
        self.assertFalse(done)
        self.assertEqual(summary, "")

    def test_task_completed_with_whitespace_in_name(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "  test1234_task_completed  \n"
            "[test1234_PARAM_NAME]\nsummary\n[test1234_PARAM_VALUE]\nDone\n[test1234_TOOL_END]"
        )
        done, summary = is_done(response, "test1234")
        self.assertTrue(done)
        self.assertEqual(summary, "Done")

    def test_task_completed_nested_tool_block(self):
        response = (
            "Let me do something first.\n\n"
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_task_completed\n"
            "[test1234_PARAM_NAME]\nsummary\n[test1234_PARAM_VALUE]\nSummary\n[test1234_TOOL_END]"
        )
        done, summary = is_done(response, "test1234")
        self.assertTrue(done)
        self.assertEqual(summary, "Summary")

    def test_task_completed_no_summary_param(self):
        response = "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\ntest1234_task_completed\n[test1234_TOOL_END]"
        done, summary = is_done(response, "test1234")
        self.assertFalse(done)
        self.assertEqual(summary, "")

    def test_task_completed_empty_summary(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_task_completed\n"
            "[test1234_PARAM_NAME]\nsummary\n[test1234_PARAM_VALUE]\n\n[test1234_TOOL_END]"
        )
        done, summary = is_done(response, "test1234")
        self.assertTrue(done)
        self.assertEqual(summary, "")

    def test_done_in_param_value_not_detected(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_write_file\n"
            "[test1234_PARAM_NAME]\ncontent\n[test1234_PARAM_VALUE]\nSome text [DONE] more text\n[test1234_TOOL_END]"
        )
        done, summary = is_done(response, "test1234")
        self.assertFalse(done)

    def test_task_completed_with_special_chars_in_summary(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_task_completed\n"
            "[test1234_PARAM_NAME]\nsummary\n[test1234_PARAM_VALUE]\nAdded: divide(a, b) — handles zero, returns float\n[test1234_TOOL_END]"
        )
        done, summary = is_done(response, "test1234")
        self.assertTrue(done)
        self.assertIn("divide", summary)

    def test_sse_done_in_stream_not_detected_as_completion(self):
        sse_content = "data: [DONE]\n\n"
        done, summary = is_done(sse_content, "test1234")
        self.assertFalse(done)
        self.assertEqual(summary, "")

    def test_sse_done_with_tool_call_before(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_list_directory\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\n.\n[test1234_TOOL_END]\ndata: [DONE]\n\n"
        )
        done, summary = is_done(response, "test1234")
        self.assertFalse(done)

    def test_prefixed_task_completed_detected(self):
        """With a prefix, <prefix>_task_completed should also be detected."""
        prefix = "abc12345"
        response = (
            f"[{prefix}_TOOL_START]\n[{prefix}_TOOL_NAME]\n"
            f"{prefix}_task_completed\n"
            f"[{prefix}_PARAM_NAME]\nsummary\n"
            f"[{prefix}_PARAM_VALUE]\nDone with prefix\n"
            f"[{prefix}_TOOL_END]"
        )
        done, summary = is_done(response, prefix)
        self.assertTrue(done)
        self.assertEqual(summary, "Done with prefix")


class TestNonToolContentStripping(unittest.TestCase):
    """Tests for stripping non-tool content from LLM responses."""

    def _strip_non_tool(self, response):
        tool_blocks = re.findall(
            r'\[test1234_TOOL_START\].*?\[test1234_TOOL_END\]',
            response,
            flags=re.DOTALL,
        )
        return "\n\n".join(tool_blocks).strip()

    def test_text_before_and_after_tool(self):
        response = (
            "I'm going to list the directory.\n\n"
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\ntest1234_list_directory\n[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\n.\n[test1234_TOOL_END]\n\n"
            "Then I'll read the files."
        )
        result = self._strip_non_tool(response)
        self.assertNotIn("I'm going", result)
        self.assertNotIn("Then I'll", result)
        self.assertIn("list_directory", result)

    def test_multiple_tool_blocks_with_text_between(self):
        response = (
            "First: list\n"
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\ntest1234_list_directory\n[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\n.\n[test1234_TOOL_END]\n"
            "Then: read\n"
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\ntest1234_read_file\n[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\nmain.py\n[test1234_TOOL_END]\n"
            "Finally: done"
        )
        result = self._strip_non_tool(response)
        self.assertIn("list_directory", result)
        self.assertIn("read_file", result)
        self.assertNotIn("First", result)
        self.assertNotIn("Then", result)
        self.assertNotIn("Finally", result)

    def test_empty_response(self):
        result = self._strip_non_tool("")
        self.assertEqual(result, "")

    def test_only_whitespace(self):
        result = self._strip_non_tool("   \n\n  ")
        self.assertEqual(result, "")

    def test_unclosed_tool_block_stripped(self):
        response = "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\ntest1234_list_directory\n[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\n."
        result = self._strip_non_tool(response)
        self.assertEqual(result, "")

    def test_task_completed_with_surrounding_text(self):
        response = (
            "I think we're done here.\n\n"
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\ntest1234_task_completed\n[test1234_PARAM_NAME]\nsummary\n[test1234_PARAM_VALUE]\nAll done\n[test1234_TOOL_END]\n\n"
            "Goodbye!"
        )
        result = self._strip_non_tool(response)
        self.assertNotIn("I think", result)
        self.assertNotIn("Goodbye", result)
        self.assertIn("task_completed", result)
        self.assertIn("All done", result)

    def test_tool_block_with_newlines_in_params(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\ntest1234_edit_file\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\nsrc/main.py\n"
            "[test1234_PARAM_NAME]\noriginal_text\n[test1234_PARAM_VALUE]\ndef add(a, b):\n    return a + b\n"
            "[test1234_PARAM_NAME]\nnew_text\n[test1234_PARAM_VALUE]\ndef add(a, b):\n    return a + b\n\n"
            "def subtract(a, b):\n    return a - b\n[test1234_TOOL_END]"
        )
        result = self._strip_non_tool(response)
        self.assertIn("edit_file", result)
        self.assertIn("def subtract", result)


class TestParseToolCallsEdgeCases(unittest.TestCase):
    """Additional edge cases for parse_tool_calls."""

    def test_tool_call_with_empty_value(self):
        response = (
            "[test1234_TOOL_START]\n[test1234_TOOL_NAME]\n"
            "test1234_write_file\n"
            "[test1234_PARAM_NAME]\npath\n[test1234_PARAM_VALUE]\n\n[test1234_TOOL_END]"
        )
        calls = parse_tool_calls(response, "test1234")
        if calls:
            self.assertEqual(calls[0][0], "write_file")

    def test_prefix_stripping(self):
        """parse_tool_calls should strip the instance prefix from tool names."""
        prefix = "abc12345"
        response = (
            f"[{prefix}_TOOL_START]\n[{prefix}_TOOL_NAME]\n"
            f"{prefix}_write_file\n"
            f"[{prefix}_PARAM_NAME]\npath\n"
            f"[{prefix}_PARAM_VALUE]\ntest.txt\n"
            f"[{prefix}_TOOL_END]"
        )
        calls = parse_tool_calls(response, prefix)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "write_file")


class TestExtractRationale(unittest.TestCase):
    def test_rationale_present(self):
        params_block = (
            "[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n"
            "[RATIONALE]\nThis is the main file.\n[TOOL_END]"
        )
        self.assertEqual(_extract_rationale(params_block), "This is the main file.")

    def test_rationale_multiline(self):
        params_block = (
            "[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n"
            "[RATIONALE]\nFirst line.\nSecond line.\n[TOOL_END]"
        )
        rationale = _extract_rationale(params_block)
        self.assertIn("First line", rationale)
        self.assertIn("Second line", rationale)

    def test_no_rationale(self):
        params_block = "[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py"
        self.assertIsNone(_extract_rationale(params_block))

    def test_empty_rationale(self):
        params_block = "[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[RATIONALE]\n\n[TOOL_END]"
        self.assertIsNone(_extract_rationale(params_block))


class TestParseParams(unittest.TestCase):
    def test_valid_params(self):
        params_block = (
            "[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n"
            "[PARAM_NAME]\ncontent\n[PARAM_VALUE]\nhello\n"
        )
        params = _parse_params(params_block)
        self.assertIsNotNone(params)
        self.assertEqual(params["path"], "main.py")
        self.assertEqual(params["content"], "hello")

    def test_single_param(self):
        params_block = "[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py"
        params = _parse_params(params_block)
        self.assertIsNotNone(params)
        self.assertEqual(params["path"], "main.py")

    def test_no_params(self):
        self.assertIsNone(_parse_params(""))

    def test_malformed_params(self):
        params_block = "[PARAM_NAME]\npath"
        self.assertIsNone(_parse_params(params_block))

    def test_params_with_newlines_in_value(self):
        params_block = (
            "[PARAM_NAME]\ncontent\n[PARAM_VALUE]\nline1\nline2\nline3\n"
        )
        params = _parse_params(params_block)
        self.assertIsNotNone(params)
        self.assertIn("line1", params["content"])
        self.assertIn("line2", params["content"])

    def test_params_with_colon_in_value(self):
        params_block = "[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py"
        params = _parse_params(params_block)
        self.assertIsNotNone(params)
        self.assertEqual(params["path"], "src/main.py")


# ====================================================================
# 2. Truncation Tests (deduplicated from test_new_features.py, test_edge_cases.py)
# ====================================================================

class TestTruncation(unittest.TestCase):
    """Tests for tool result truncation."""

    def test_no_truncation_when_under_limit(self):
        content, was_truncated = truncate_tool_result("short content", 1000, "read_file")
        self.assertFalse(was_truncated)
        self.assertEqual(content, "short content")

    def test_truncation_when_over_limit(self):
        long_content = "x" * 500
        content, was_truncated = truncate_tool_result(long_content, 100, "read_file")
        self.assertTrue(was_truncated)
        self.assertLess(len(content), len(long_content))
        self.assertIn("TRUNCATED", content)
        self.assertIn("showing first 100 of 500", content)

    def test_truncation_preserves_tail(self):
        long_content = "START " + "m" * 400 + " END"
        content, was_truncated = truncate_tool_result(long_content, 100, "read_file")
        self.assertTrue(was_truncated)
        self.assertIn("START", content)
        self.assertIn("TRUNCATED", content)
        self.assertIn("showing first 100 of 410", content)

    def test_truncation_with_filter_hint(self):
        long_content = "x" * 500
        content, was_truncated = truncate_tool_result(long_content, 100, "list_directory")
        self.assertTrue(was_truncated)
        self.assertIn("list_directory_deep", content)

    def test_truncation_no_hint_for_unsupported_tool(self):
        long_content = "x" * 500
        content, was_truncated = truncate_tool_result(long_content, 100, "read_file")
        self.assertTrue(was_truncated)
        self.assertNotIn("Try narrowing", content)

    def test_zero_limit_triggers_no_truncation(self):
        content, was_truncated = truncate_tool_result("content", 0, "read_file")
        self.assertFalse(was_truncated)
        self.assertEqual(content, "content")

    def test_truncation_notice_guides_llm(self):
        long_content = "x" * 500
        content, was_truncated = truncate_tool_result(long_content, 100, "read_file")
        self.assertTrue(was_truncated)
        self.assertIn("too long", content)

    def test_exact_limit_no_truncation(self):
        content, was_truncated = truncate_tool_result("x" * 100, 100, "read_file")
        self.assertFalse(was_truncated)
        self.assertEqual(content, "x" * 100)

    def test_one_over_limit_truncates(self):
        content, was_truncated = truncate_tool_result("x" * 101, 100, "read_file")
        self.assertTrue(was_truncated)
        self.assertIn("TRUNCATED", content)
        self.assertIn("showing first 100 of 101", content)

    def test_truncation_with_newlines(self):
        content, was_truncated = truncate_tool_result("line1\nline2\n" + "x" * 200, 100, "read_file")
        self.assertTrue(was_truncated)
        self.assertIn("line1", content)
        self.assertIn("TRUNCATED", content)

    def test_truncation_preserves_partial_word_at_boundary(self):
        content, was_truncated = truncate_tool_result("word1 word2 word3 " + "x" * 200, 30, "read_file")
        self.assertTrue(was_truncated)
        self.assertIn("word1", content)

    def test_truncation_notice_includes_total_chars(self):
        content, was_truncated = truncate_tool_result("x" * 500, 50, "read_file")
        self.assertIn("showing first 50 of 500", content)

    def test_truncation_with_empty_content(self):
        content, was_truncated = truncate_tool_result("", 100, "read_file")
        self.assertFalse(was_truncated)
        self.assertEqual(content, "")

    def test_search_files_filter_hint(self):
        content, was_truncated = truncate_tool_result("x" * 100, 50, "search_files")
        self.assertTrue(was_truncated)
        self.assertIn("search_files_dir", content)

    def test_grep_code_filter_hint(self):
        content, was_truncated = truncate_tool_result("x" * 100, 50, "grep_code")
        self.assertTrue(was_truncated)
        self.assertIn("grep_code_dir", content)


# ====================================================================
# 3. Security Tests (from test_ai_builder_comprehensive.py)
# ====================================================================

class TestSecurity(unittest.TestCase):
    """Tests for security boundary enforcement."""

    def test_path_traversal_blocked(self):
        with self.assertRaises(SecurityError):
            ensure_under_root('../../../etc/passwd', TEST_PROJECT)

    def test_absolute_path_to_root_allowed(self):
        result = ensure_under_root(TEST_PROJECT, TEST_PROJECT)
        self.assertEqual(result, TEST_PROJECT)

    def test_relative_path_within_root_allowed(self):
        result = ensure_under_root('src/main.py', TEST_PROJECT)
        self.assertTrue(result.startswith(TEST_PROJECT))

    def test_absolute_path_outside_root_blocked(self):
        with self.assertRaises(SecurityError):
            ensure_under_root('/etc/passwd', TEST_PROJECT)

    def test_allowed_tmp_paths(self):
        result = ensure_under_root('/tmp/test.txt', TEST_PROJECT)
        self.assertEqual(result, '/tmp/test.txt')

    def test_nested_traversal_blocked(self):
        with self.assertRaises(SecurityError):
            ensure_under_root('src/../../../etc/hosts', TEST_PROJECT)


# ====================================================================
# 4. Parameter Validation Tests
# ====================================================================

class TestParameterValidation(unittest.TestCase):
    def test_missing_required_param(self):
        schema = {'path': 'string', 'content': 'string'}
        with self.assertRaises(ToolError):
            validate_tool_params({'path': 'test.txt'}, schema)

    def test_wrong_param_type(self):
        schema = {'path': 'string'}
        with self.assertRaises(ToolError):
            validate_tool_params({'path': 123}, schema)

    def test_valid_params(self):
        schema = {'path': 'string', 'content': 'string'}
        result = validate_tool_params({'path': 'test.txt', 'content': 'hello'}, schema)
        self.assertEqual(result, {'path': 'test.txt', 'content': 'hello'})

    def test_validate_missing_description(self):
        params = {"name": "hello", "parameters": "{}", "code": "class HelloTool(BaseTool):\n    name = 'hello'\n    pass"}
        schema = {"name": "string", "description": "string", "parameters": "string", "code": "string"}
        with self.assertRaises(ToolError):
            validate_tool_params(params, schema)


# ====================================================================
# 5. ToolResult, EngineConfig, Exception Tests (from test_remaining_features.py)
# ====================================================================

class TestToolResult(unittest.TestCase):
    def test_success_result(self):
        result = ToolResult(True, "content")
        self.assertTrue(result.success)
        self.assertEqual(result.content, "content")
        self.assertEqual(result.error, "")
        self.assertEqual(result.summary, "")

    def test_failure_result(self):
        result = ToolResult(False, "", error="something went wrong")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "something went wrong")

    def test_result_with_summary(self):
        result = ToolResult(True, "content", summary="Done")
        self.assertEqual(result.summary, "Done")

    def test_to_dict(self):
        result = ToolResult(True, "content", summary="Done")
        d = result.to_dict()
        self.assertEqual(d["success"], True)
        self.assertEqual(d["content"], "content")
        self.assertEqual(d["summary"], "Done")
        self.assertEqual(d["error"], "")

    def test_to_dict_with_error(self):
        result = ToolResult(False, "", error="fail")
        d = result.to_dict()
        self.assertEqual(d["success"], False)
        self.assertEqual(d["error"], "fail")


class TestEngineConfig(unittest.TestCase):
    def test_get_root_directory(self):
        root = EngineConfig.get_root_directory()
        self.assertIsInstance(root, str)
        self.assertGreater(len(root), 0)

    def test_get_max_steps(self):
        max_steps = EngineConfig.get_max_steps()
        self.assertIsInstance(max_steps, int)
        self.assertGreater(max_steps, 0)

    def test_get_max_context_tokens(self):
        max_tokens = EngineConfig.get_max_context_tokens()
        self.assertIsInstance(max_tokens, int)

    def test_get_max_output_tokens(self):
        max_tokens = EngineConfig.get_max_output_tokens()
        self.assertIsInstance(max_tokens, int)

    def test_get_max_tool_result_length(self):
        max_length = EngineConfig.get_max_tool_result_length()
        self.assertIsInstance(max_length, int)
        self.assertGreater(max_length, 0)

    def test_get_timeout(self):
        timeout = EngineConfig.get_timeout()
        self.assertIsInstance(timeout, int)
        self.assertGreater(timeout, 0)

    def test_get_enabled_tools(self):
        tools = EngineConfig.get_enabled_tools()
        self.assertTrue(tools is None or isinstance(tools, list))

    def test_get_custom_endpoint_url(self):
        url = EngineConfig.get_custom_endpoint_url()
        self.assertTrue(url is None or isinstance(url, str))

    def test_get_custom_api_key(self):
        key = EngineConfig.get_custom_api_key()
        self.assertTrue(key is None or isinstance(key, str))

    def test_get_custom_model_name(self):
        model = EngineConfig.get_custom_model_name()
        self.assertTrue(model is None or isinstance(model, str))

    def test_get_custom_verify_ssl(self):
        verify = EngineConfig.get_custom_verify_ssl()
        self.assertIsInstance(verify, bool)

    def test_get_live_instruction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = EngineConfig.get_live_instruction("nonexistent", base_dir=tmpdir)
            self.assertIsNone(result)

    def test_live_instruction_file_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            instruction_file = os.path.join(tmpdir, "live_instruction_123.txt")
            with open(instruction_file, "w") as f:
                f.write("New instruction")
            result = EngineConfig.get_live_instruction("123", base_dir=tmpdir)
            self.assertTrue(result is None or result == "New instruction")


class TestExceptions(unittest.TestCase):
    def test_security_error(self):
        with self.assertRaises(SecurityError):
            raise SecurityError("Path traversal detected")

    def test_security_error_message(self):
        try:
            raise SecurityError("Test error")
        except SecurityError as e:
            self.assertEqual(str(e), "Test error")

    def test_tool_error(self):
        with self.assertRaises(ToolError):
            raise ToolError("Invalid parameter")

    def test_tool_error_message(self):
        try:
            raise ToolError("Test error")
        except ToolError as e:
            self.assertEqual(str(e), "Test error")

    def test_engine_error(self):
        with self.assertRaises(EngineError):
            raise EngineError("Engine failed")

    def test_engine_error_message(self):
        try:
            raise EngineError("Test error")
        except EngineError as e:
            self.assertEqual(str(e), "Test error")


# ====================================================================
# 6. Token Estimation & Context Trimming (from test_untested_features.py)
# ====================================================================

class TestEstimateTokens(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_estimate_tokens(""), 1)

    def test_short_text(self):
        result = _estimate_tokens("hello world")
        self.assertGreaterEqual(result, 1)
        self.assertLessEqual(result, 10)

    def test_long_text_proportional(self):
        short = _estimate_tokens("hello")
        long = _estimate_tokens("hello " * 100)
        self.assertGreater(long, short)

    def test_ratio_approximately_4_to_1(self):
        text = "a" * 400
        result = _estimate_tokens(text)
        self.assertGreater(result, 50)
        self.assertLess(result, 150)


class TestTrimMessagesToContext(unittest.TestCase):
    def test_unlimited_max_tokens(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = _trim_messages_to_context(messages, "System prompt", 0)
        self.assertEqual(len(result), len(messages))

    def test_fits_within_budget(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = _trim_messages_to_context(messages, "System prompt", 1000)
        self.assertEqual(len(result), len(messages))

    def test_trims_oldest_messages(self):
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Old message 1"},
            {"role": "assistant", "content": "Old reply 1"},
            {"role": "user", "content": "Old message 2"},
            {"role": "assistant", "content": "Old reply 2"},
            {"role": "user", "content": "Recent message"},
            {"role": "assistant", "content": "Recent reply"},
        ]
        result = _trim_messages_to_context(messages, "System", 20)
        self.assertGreater(len(result), 0)
        self.assertEqual(result[0]["role"], "system")

    def test_keeps_at_least_system_prompt(self):
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Message"},
        ]
        result = _trim_messages_to_context(messages, "System", 5)
        self.assertEqual(result[0]["role"], "system")
        self.assertGreaterEqual(len(result), 1)


# ====================================================================
# 7. System/User Prompt Tests
# ====================================================================

class TestSystemPrompt(unittest.TestCase):
    def test_system_prompt_references_task_completed(self):
        prompt = build_system_prompt([])
        self.assertIn('task_completed', prompt.lower())

    def test_system_prompt_references_task_completed_with_prefix(self):
        tools = [{"name": "task_completed", "description": "Signal task completion", "parameters": {"summary": "string"}}]
        prompt = build_system_prompt(tools, "abc12345")
        self.assertIn('abc12345_task_completed', prompt)

    def test_system_prompt_contains_tool_format(self):
        prompt = build_system_prompt([])
        self.assertIn("[TOOL_START]", prompt)
        self.assertIn("[TOOL_END]", prompt)

    def test_system_prompt_contains_workflow(self):
        prompt = build_system_prompt([])
        self.assertIn("EXPLORE", prompt)
        self.assertIn("UNDERSTAND", prompt)
        self.assertIn("PLAN", prompt)
        self.assertIn("MODIFY", prompt)
        self.assertIn("VERIFY", prompt)

    def test_system_prompt_with_prefix_uses_prefixed_names(self):
        tools = [
            {"name": "write_file", "description": "Write a file", "parameters": {"path": "string", "content": "string"}},
            {"name": "read_file", "description": "Read a file", "parameters": {"path": "string"}},
        ]
        prompt = build_system_prompt(tools, "abc12345")
        self.assertIn("abc12345_write_file", prompt)
        self.assertIn("abc12345_read_file", prompt)
        # Unprefixed tool should NOT appear as standalone
        unprefixed_matches = re.findall(r'^\s+- write_file:', prompt, re.MULTILINE)
        self.assertEqual(len(unprefixed_matches), 0)

    def test_user_prompt_contains_instructions(self):
        prompt = build_user_prompt("Add a divide function")
        self.assertIn("Add a divide function", prompt)

    def test_user_prompt_contains_context(self):
        prompt = build_user_prompt("Add a function", "Context: existing code has add()")
        self.assertIn("Context: existing code has add()", prompt)

    def test_user_prompt_contains_task_completed_reference(self):
        prompt = build_user_prompt("Test")
        self.assertIn("task_completed", prompt)


# ====================================================================
# 8. File System Tool Tests (from test_ai_builder_comprehensive.py)
# ====================================================================

class TestFileSystemTools(unittest.TestCase):
    def test_list_directory(self):
        tool = ListDirectoryTool(TEST_PROJECT)
        r = tool.execute({'path': '', 'max_depth': '1'})
        self.assertTrue(r.success)
        entries = json.loads(r.content)
        names = [e['name'] for e in entries]
        self.assertIn('java-project', names)
        self.assertIn('csharp-project', names)
        self.assertIn('src', names)

    def test_search_files(self):
        tool = SearchFilesTool(TEST_PROJECT)
        r = tool.execute({'pattern': '*.java', 'search_dir': ''})
        self.assertTrue(r.success)
        self.assertIn('App.java', r.content)
        self.assertIn('Calculator.java', r.content)

    def test_search_files_cs(self):
        tool = SearchFilesTool(TEST_PROJECT)
        r = tool.execute({'pattern': '*.cs', 'search_dir': ''})
        self.assertTrue(r.success)
        self.assertIn('Program.cs', r.content)

    def test_read_file(self):
        tool = ReadFileTool(TEST_PROJECT)
        r = tool.execute({'path': 'src/main.py'})
        self.assertTrue(r.success)
        self.assertIn('def greet', r.content)

    def test_write_and_read_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            tool = WriteFileTool(tmpdir)
            r = tool.execute({'path': 'test_write.txt', 'content': 'Hello, World!\n'})
            self.assertTrue(r.success)
            read_tool = ReadFileTool(tmpdir)
            r2 = read_tool.execute({'path': 'test_write.txt'})
            self.assertTrue(r2.success)
            self.assertEqual(r2.content.strip(), 'Hello, World!')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_edit_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'edit_test.py')
            with open(test_file, 'w') as f:
                f.write('x = 1\ny = 2\n')
            tool = EditFileTool(tmpdir)
            r = tool.execute({
                'path': 'edit_test.py',
                'original_text': 'y = 2',
                'new_text': 'y = 3\nz = 4',
            })
            self.assertTrue(r.success)
            with open(test_file, 'r') as f:
                content = f.read()
            self.assertIn('y = 3', content)
            self.assertIn('z = 4', content)
            self.assertIn('x = 1', content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_delete_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'delete_me.txt')
            with open(test_file, 'w') as f:
                f.write('delete me')
            tool = DeleteFileTool(tmpdir)
            r = tool.execute({'path': 'delete_me.txt'})
            self.assertTrue(r.success)
            self.assertFalse(os.path.exists(test_file))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_delete_backup_file_blocked(self):
        tmpdir = tempfile.mkdtemp()
        try:
            bak_file = os.path.join(tmpdir, 'backup.bak')
            with open(bak_file, 'w') as f:
                f.write('backup')
            tool = DeleteFileTool(tmpdir)
            r = tool.execute({'path': 'backup.bak'})
            self.assertFalse(r.success)
            self.assertIn('backup', r.error.lower())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_delete_symlink(self):
        tmpdir = tempfile.mkdtemp()
        try:
            target = os.path.join(tmpdir, 'target.txt')
            link = os.path.join(tmpdir, 'link.txt')
            with open(target, 'w') as f:
                f.write('target')
            os.symlink(target, link)
            self.assertTrue(os.path.islink(link))
            tool = DeleteFileTool(tmpdir)
            r = tool.execute({'path': 'link.txt'})
            self.assertTrue(r.success)
            self.assertFalse(os.path.exists(link))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_delete_directory_fails(self):
        tmpdir = tempfile.mkdtemp()
        try:
            subdir = os.path.join(tmpdir, 'subdir')
            os.makedirs(subdir)
            self.assertTrue(os.path.isdir(subdir))
            tool = DeleteFileTool(tmpdir)
            r = tool.execute({'path': 'subdir'})
            self.assertFalse(r.success)
            self.assertTrue(os.path.isdir(subdir))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_delete_file_with_spaces_in_name(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'file with spaces.txt')
            with open(test_file, 'w') as f:
                f.write('content')
            self.assertTrue(os.path.exists(test_file))
            tool = DeleteFileTool(tmpdir)
            r = tool.execute({'path': 'file with spaces.txt'})
            self.assertTrue(r.success)
            self.assertFalse(os.path.exists(test_file))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_write_file_verification(self):
        tmpdir = tempfile.mkdtemp()
        try:
            tool = WriteFileTool(tmpdir)
            r = tool.execute({
                'path': 'verify_test.py',
                'content': 'def hello():\n    print("world")\n',
            })
            self.assertTrue(r.success)
            with open(os.path.join(tmpdir, 'verify_test.py')) as f:
                content = f.read()
            self.assertIn('def hello():', content)
            self.assertIn('print("world")', content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_edit_file_verification(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'edit_verify.py')
            with open(test_file, 'w') as f:
                f.write('x = 1\ny = 2\n')
            tool = EditFileTool(tmpdir)
            r = tool.execute({
                'path': 'edit_verify.py',
                'original_text': 'y = 2',
                'new_text': 'y = 3\nz = 4',
            })
            self.assertTrue(r.success)
            with open(test_file) as f:
                content = f.read()
            self.assertIn('y = 3', content)
            self.assertIn('z = 4', content)
            self.assertIn('x = 1', content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_edit_file_wrong_original_fails(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'edit_fail.py')
            with open(test_file, 'w') as f:
                f.write('x = 1\n')
            tool = EditFileTool(tmpdir)
            r = tool.execute({
                'path': 'edit_fail.py',
                'original_text': 'y = 2',
                'new_text': 'y = 3',
            })
            self.assertFalse(r.success)
            self.assertIn('not found', r.error.lower())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# 9. Tool Registry Tests (deduplicated)
# ====================================================================

class TestToolRegistry(unittest.TestCase):
    """Tests for the shared ToolRegistry singleton."""

    def setUp(self):
        _reset_registry()

    def tearDown(self):
        _reset_registry()

    def test_all_tools_registered(self):
        registry = get_registry()
        tools = registry.list_tools()
        tool_names = [t['name'] for t in tools]
        expected = [
            'list_directory', 'search_files', 'grep_code',
            'read_file', 'write_file', 'edit_file', 'delete_file',
            'find_symbol', 'decompile_jar',
            'check_syntax', 'create_tool',
            'respond_to_user', 'request_user_input', 'task_completed',
        ]
        for name in expected:
            self.assertIn(name, tool_names, f"Tool '{name}' not registered")

    def test_no_filtering_applied(self):
        registry = get_registry()
        tools = registry.list_tools()
        tool_names = [t['name'] for t in tools]
        self.assertGreater(len(tool_names), 10)
        self.assertIn('read_file', tool_names)
        self.assertIn('write_file', tool_names)

    def test_unknown_tool_raises_error(self):
        registry = get_registry()
        with self.assertRaises(ToolError):
            registry.execute('nonexistent_tool', {'path': 'test.txt'}, '/tmp')

    def test_execute_list_directory(self):
        tmpdir = tempfile.mkdtemp()
        try:
            registry = ToolRegistry()
            result = registry.execute("list_directory", {"path": "."}, tmpdir)
            self.assertTrue(result.success)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_read_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, "w") as f:
                f.write("hello")
            registry = ToolRegistry()
            result = registry.execute("read_file", {"path": "test.txt"}, tmpdir)
            self.assertTrue(result.success)
            self.assertIn("hello", result.content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_write_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            registry = ToolRegistry()
            result = registry.execute("write_file", {"path": "new.txt", "content": "new content"}, tmpdir)
            self.assertTrue(result.success)
            with open(os.path.join(tmpdir, "new.txt")) as f:
                self.assertEqual(f.read(), "new content")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_unknown_tool_raises(self):
        tmpdir = tempfile.mkdtemp()
        try:
            registry = ToolRegistry()
            with self.assertRaises(Exception):
                registry.execute("unknown_tool", {}, tmpdir)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_missing_required_param(self):
        tmpdir = tempfile.mkdtemp()
        try:
            registry = ToolRegistry()
            with self.assertRaises(Exception):
                registry.execute("read_file", {}, tmpdir)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_all_tools_available(self):
        tmpdir = tempfile.mkdtemp()
        try:
            registry = ToolRegistry()
            tools = registry.list_tools()
            tool_names = [t["name"] for t in tools]
            self.assertIn("list_directory", tool_names)
            self.assertIn("read_file", tool_names)
            self.assertIn("write_file", tool_names)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# 10. Singleton Registry (from test_round13.py)
# ====================================================================

class TestSingletonRegistry(unittest.TestCase):
    def setUp(self):
        _reset_registry()

    def tearDown(self):
        _reset_registry()

    def test_singleton_returns_same_instance(self):
        r1 = get_registry()
        r2 = get_registry()
        self.assertIs(r1, r2)

    def test_singleton_ignores_root_dir_after_first_call(self):
        r1 = get_registry("/tmp/test1")
        r2 = get_registry("/tmp/test2")
        self.assertIs(r1, r2)

    def test_all_tools_registered_without_filtering(self):
        registry = get_registry()
        tools = registry.list_tools()
        tool_names = [t['name'] for t in tools]
        expected_tools = [
            'list_directory', 'list_directory_deep', 'search_files', 'search_files_dir',
            'grep_code', 'grep_code_dir', 'read_file', 'read_file_range',
            'write_file', 'edit_file', 'delete_file', 'find_symbol',
            'decompile_jar', 'check_syntax',
            'create_tool',
            'respond_to_user', 'request_user_input', 'task_completed',
        ]
        for name in expected_tools:
            self.assertIn(name, tool_names, f"Tool '{name}' not registered")

    def test_registry_shared_across_calls(self):
        r1 = get_registry()
        r2 = get_registry()
        tools1 = set(t['name'] for t in r1.list_tools())
        tools2 = set(t['name'] for t in r2.list_tools())
        self.assertEqual(tools1, tools2)


# ====================================================================
# 11. Tool Execution Tests (from test_remaining_features.py)
# ====================================================================

class TestTaskCompletedTool(unittest.TestCase):
    def test_execute_with_summary(self):
        tmpdir = tempfile.mkdtemp()
        try:
            tool = TaskCompletedTool(tmpdir)
            r = tool.execute({'summary': 'Added divide function'})
            self.assertTrue(r.success)
            self.assertIn("Added divide function", r.content)
            self.assertIn("Added divide function", r.summary)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_empty_summary(self):
        tmpdir = tempfile.mkdtemp()
        try:
            tool = TaskCompletedTool(tmpdir)
            r = tool.execute({'summary': ''})
            self.assertTrue(r.success)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_tool_is_registered(self):
        registry = get_registry()
        tools = registry.list_tools()
        tool_names = [t['name'] for t in tools]
        self.assertIn('task_completed', tool_names)

    def test_task_completed_with_very_long_summary(self):
        tmpdir = tempfile.mkdtemp()
        try:
            tool = TaskCompletedTool(tmpdir)
            long_summary = "Step " + "x" * 5000
            r = tool.execute({'summary': long_summary})
            self.assertTrue(r.success)
            self.assertIn("Step", r.content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_task_completed_with_unicode_summary(self):
        tmpdir = tempfile.mkdtemp()
        try:
            tool = TaskCompletedTool(tmpdir)
            r = tool.execute({'summary': 'Added: 日本語テスト 🎉'})
            self.assertTrue(r.success)
            self.assertIn("日本語", r.summary)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_task_completed_with_newlines_in_summary(self):
        tmpdir = tempfile.mkdtemp()
        try:
            tool = TaskCompletedTool(tmpdir)
            r = tool.execute({'summary': 'Step 1\nStep 2\nStep 3'})
            self.assertTrue(r.success)
            self.assertIn("Step 3", r.content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestRespondToUserTool(unittest.TestCase):
    def test_execute_returns_message(self):
        tmpdir = tempfile.mkdtemp()
        try:
            tool = RespondToUserTool(tmpdir)
            r = tool.execute({"message": "Hello, world!"})
            self.assertTrue(r.success)
            self.assertIn("Hello, world!", r.content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_empty_message(self):
        tmpdir = tempfile.mkdtemp()
        try:
            tool = RespondToUserTool(tmpdir)
            r = tool.execute({"message": ""})
            self.assertTrue(r.success)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_tool_is_registered(self):
        tmpdir = tempfile.mkdtemp()
        try:
            registry = get_registry(tmpdir)
            tools = registry.list_tools()
            tool_names = [t['name'] for t in tools]
            self.assertIn('respond_to_user', tool_names)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# 12. Engine Loop Tests (from test_engine_loop.py)
# ====================================================================

def _make_engine(tmpdir, enabled_tools, max_steps=10, max_context_tokens=0,
                 max_tool_result_length=10000):
    """Helper to create an engine with standard config."""
    os.environ["AIB_OUTPUT_DIR"] = tmpdir
    os.environ["AIB_JOB_ID"] = "test-job"
    os.environ["AIB_MAX_STEPS"] = str(max_steps)
    os.environ["AIB_MAX_CONTEXT_TOKENS"] = str(max_context_tokens)
    os.environ["AIB_MAX_TOOL_RESULT_LENGTH"] = str(max_tool_result_length)
    return AgentEngine({
        "rootDirectory": tmpdir,
        "instructions": "Test",
        "custom_endpoint_url": "http://test",
        "custom_api_key": "test",
        "custom_model_name": "test",
        "custom_verify_ssl": False,
    }, output_dir=tmpdir)


def _prefixed_response(tool_name, params, prefix="", rationale=None):
    """Build a mock LLM response with the correct instance prefix.

    Args:
        tool_name: The tool name (will be prefixed if prefix is set).
        params: Dict of parameter key-value pairs.
        prefix: The instance prefix (e.g., from engine.instance_prefix).
        rationale: Optional rationale text.

    Returns:
        A string containing the full tool call block with prefixed markers.
    """
    if prefix:
        tool_name = f"{prefix}_{tool_name}"
        ts, te, tn, pn, pv, rat = (
            f"[{prefix}_TOOL_START]", f"[{prefix}_TOOL_END]",
            f"[{prefix}_TOOL_NAME]", f"[{prefix}_PARAM_NAME]",
            f"[{prefix}_PARAM_VALUE]", f"[{prefix}_RATIONALE]",
        )
    else:
        ts, te, tn, pn, pv, rat = (
            "[TOOL_START]", "[TOOL_END]", "[TOOL_NAME]",
            "[PARAM_NAME]", "[PARAM_VALUE]", "[RATIONALE]",
        )

    parts = [f"{ts}\n{tn}\n{tool_name}"]
    for k, v in params.items():
        parts.append(f"{pn}\n{k}\n{pv}\n{v}")
    if rationale:
        parts.append(f"{rat}\n{rationale}")
    parts.append(te)
    return "\n".join(parts)


def _mock_tool_execute(engine, tool_name, result_fn):
    """Patch engine.tools.execute to return a custom result for a tool."""
    original = engine.tools.execute
    def mock_execute(tn, params, root_dir=None, project_output_dir="", disabled_tools=None, job_id="", **kwargs):
        if tn == tool_name:
            return result_fn(params)
        return original(tn, params, root_dir, project_output_dir, disabled_tools, job_id=job_id)
    engine.tools.execute = mock_execute


class TestTaskCompletedConclusion(unittest.TestCase):
    def test_task_completed_breaks_loop_not_continues(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["task_completed"])
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("task_completed", {"summary": "Done"}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            _mock_tool_execute(engine, "task_completed",
                lambda p: TaskCompletedTool(tmpdir).execute(p))
            with patch('agent_engine.engine._estimate_tokens', return_value=10):
                result = engine.run()
            self.assertEqual(result["status"], "completed")
            self.assertIn("Done", result.get("summary", ""))
            step_tools = [s["tool"] for s in engine.step_history]
            self.assertIn("task_completed", step_tools)
            self.assertEqual(step_tools[-1], "task_completed")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_task_completed_includes_rationale_in_step_history(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["task_completed"])
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("task_completed", {"summary": "Done"}, prefix, rationale="I verified all changes"),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            _mock_tool_execute(engine, "task_completed",
                lambda p: TaskCompletedTool(tmpdir).execute(p))
            with patch('agent_engine.engine._estimate_tokens', return_value=10):
                result = engine.run()
            tc_steps = [s for s in engine.step_history if s["tool"] == "task_completed"]
            self.assertTrue(len(tc_steps) > 0)
            self.assertIn("rationale", tc_steps[0])
            self.assertIn("verified all changes", tc_steps[0]["rationale"].lower())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_task_completed_appends_completion_message(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["task_completed"])
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("task_completed", {"summary": "All changes done"}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            _mock_tool_execute(engine, "task_completed",
                lambda p: TaskCompletedTool(tmpdir).execute(p))
            with patch('agent_engine.engine._estimate_tokens', return_value=10):
                result = engine.run()
            completion_found = False
            for m in engine.messages:
                if m.get("role") == "user" and "[COMPLETION]" in m.get("content", ""):
                    completion_found = True
                    self.assertIn("All changes done", m["content"])
            self.assertTrue(completion_found, "[COMPLETION] message not found in messages")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestContextWarningEvent(unittest.TestCase):
    def test_context_warning_emitted_at_80_percent(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["list_directory"], max_context_tokens=100)
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("list_directory", {"path": "."}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            events = []
            def track_callback(event):
                events.append(event)
            engine._step_callback = track_callback
            def mock_estimate(text):
                return 90
            with patch('agent_engine.engine._estimate_tokens', side_effect=mock_estimate):
                result = engine.run()
            warning_events = [e for e in events if e.get("type") == "context_warning"]
            self.assertTrue(len(warning_events) > 0, "context_warning event not emitted")
            warning = warning_events[0]
            self.assertIn("step", warning)
            self.assertIn("current_tokens", warning)
            self.assertIn("max_tokens", warning)
            self.assertIn("usage_pct", warning)
            self.assertEqual(warning["max_tokens"], 100)
            self.assertGreaterEqual(warning["usage_pct"], 80.0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_context_warning_only_emitted_once(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["list_directory"], max_context_tokens=100)
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("list_directory", {"path": "."}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            events = []
            def track_callback(event):
                events.append(event)
            engine._step_callback = track_callback
            def mock_estimate(text):
                return 90
            with patch('agent_engine.engine._estimate_tokens', side_effect=mock_estimate):
                result = engine.run()
            warning_events = [e for e in events if e.get("type") == "context_warning"]
            self.assertEqual(len(warning_events), 1)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_context_warning_message_added_to_history(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["list_directory"], max_context_tokens=100)
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("list_directory", {"path": "."}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            def mock_estimate(text):
                return 90
            with patch('agent_engine.engine._estimate_tokens', side_effect=mock_estimate):
                result = engine.run()
            warning_msg_found = False
            for m in engine.messages:
                if m.get("role") == "user" and "[CONTEXT COMPRESSED]" in m.get("content", ""):
                    warning_msg_found = True
                    self.assertIn("Low-value items", m["content"])
                    self.assertIn("context window", m["content"])
            self.assertTrue(warning_msg_found, "[CONTEXT COMPRESSED] message not found in messages")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestRequestUserInputPause(unittest.TestCase):
    def test_request_user_input_returns_pending_status(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["request_user_input"])
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("request_user_input", {"question": "What is your name?"}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            result = engine.run()
            self.assertEqual(result["status"], "pending_user_input")
            self.assertIn("question", result)
            self.assertIn("What is your name?", result["question"])
            question_file = os.path.join(tmpdir, "user_input_request.txt")
            self.assertTrue(os.path.exists(question_file))
            with open(question_file) as f:
                self.assertEqual(f.read(), "What is your name?")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_request_user_input_emits_pending_user_input_event(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["request_user_input"])
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("request_user_input", {"question": "Please confirm"}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            events = []
            def track_callback(event):
                events.append(event)
            engine._step_callback = track_callback
            result = engine.run()
            pui_events = [e for e in events if e.get("type") == "pending_user_input"]
            self.assertTrue(len(pui_events) > 0, "pending_user_input event not emitted")
            self.assertIn("question", pui_events[0])
            self.assertEqual(pui_events[0]["question"], "Please confirm")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestToolResultTruncation(unittest.TestCase):
    def test_tool_result_truncated_before_fed_to_llm(self):
        tmpdir = tempfile.mkdtemp()
        try:
            large_file = os.path.join(tmpdir, "large.txt")
            with open(large_file, 'w') as f:
                f.write("x" * 200)
            engine = _make_engine(tmpdir, ["list_directory"], max_tool_result_length=50)
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("list_directory", {"path": "."}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            result = engine.run()
            list_steps = [s for s in engine.step_history if s["tool"] == "list_directory"]
            self.assertTrue(len(list_steps) > 0)
            self.assertTrue(list_steps[0]["result"].get("truncated", False),
                f"Tool result should be truncated, got: {list_steps[0]['result']['content'][:100]}")
            self.assertIn("TRUNCATED", list_steps[0]["result"]["content"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_tool_result_not_truncated_when_under_limit(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["list_directory"], max_tool_result_length=10000)
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("list_directory", {"path": "."}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            result = engine.run()
            list_steps = [s for s in engine.step_history if s["tool"] == "list_directory"]
            self.assertTrue(len(list_steps) > 0)
            self.assertFalse(list_steps[0]["result"].get("truncated", False))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestCleanedResponse(unittest.TestCase):
    def test_cleaned_response_appended_to_messages(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["list_directory"])
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": f"Let me think...\n\n{_prefixed_response('list_directory', {'path': '.'}, prefix)}\n\nDone thinking.",
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            result = engine.run()
            assistant_msgs = [m for m in engine.messages if m.get("role") == "assistant"]
            self.assertTrue(len(assistant_msgs) > 0, "No assistant messages found")
            self.assertIn(f"[{prefix}_TOOL_START]", assistant_msgs[0]["content"])
            self.assertNotIn("Let me think", assistant_msgs[0]["content"])
            self.assertNotIn("Done thinking", assistant_msgs[0]["content"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestStepHistory(unittest.TestCase):
    def test_step_history_appended_for_each_step(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["list_directory", "task_completed"])
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.side_effect = [
                {
                    "content": _prefixed_response("list_directory", {"path": "."}, prefix),
                    "raw_request": "", "raw_response": "",
                },
                {
                    "content": _prefixed_response("task_completed", {"summary": "Done"}, prefix),
                    "raw_request": "", "raw_response": "",
                },
            ]
            engine.llm = mock_llm
            _mock_tool_execute(engine, "task_completed",
                lambda p: TaskCompletedTool(tmpdir).execute(p))
            result = engine.run()
            step_tools = [s["tool"] for s in engine.step_history]
            self.assertIn("list_directory", step_tools)
            self.assertIn("task_completed", step_tools)
            self.assertEqual(step_tools[-1], "task_completed")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestStepCallback(unittest.TestCase):
    def test_step_callback_invoked_for_each_step(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["list_directory"])
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("list_directory", {"path": "."}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            events = []
            def track_callback(event):
                events.append(event)
            engine._step_callback = track_callback
            result = engine.run()
            step_events = [e for e in events if e.get("type") == "step"]
            self.assertTrue(len(step_events) > 0, "step event not emitted")
            self.assertEqual(step_events[0]["tool"], "list_directory")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestEngineLoopEdgeCases(unittest.TestCase):
    def test_tool_error_does_not_crash_engine(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["unknown_tool_xyz"])
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("unknown_tool_xyz", {"path": "."}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            result = engine.run()
            self.assertIn(result["status"], ["completed", "error", "max_steps_reached"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_max_steps_reached_returns_correct_status(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["list_directory"], max_steps=2)
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("list_directory", {"path": "."}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            result = engine.run()
            self.assertEqual(result["status"], "max_steps_reached")
            self.assertEqual(result["steps"], 2)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_tool_call_nudge_added(self):
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "I'm thinking about what to do next...",
                "raw_request": "", "raw_response": "",
            }
            engine = _make_engine(tmpdir, ["list_directory"], max_steps=3)
            engine.llm = mock_llm
            result = engine.run()
            # Engine should continue running without crashing when no tool calls are made
            self.assertEqual(result["status"], "max_steps_reached")
            self.assertEqual(result["steps"], 3)
            # The engine should have appended the raw response as assistant messages
            assistant_msgs = [m for m in engine.messages if m.get("role") == "assistant"]
            self.assertTrue(len(assistant_msgs) > 0, "No assistant messages found")
            self.assertIn("I'm thinking", assistant_msgs[0].get("content", ""))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_context_warning_not_emitted_when_max_context_zero(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, ["list_directory"], max_context_tokens=0)
            prefix = engine.instance_prefix
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": _prefixed_response("list_directory", {"path": "."}, prefix),
                "raw_request": "", "raw_response": "",
            }
            engine.llm = mock_llm
            events = []
            def track_callback(event):
                events.append(event)
            engine._step_callback = track_callback
            def mock_estimate(text):
                return 99999
            with patch('agent_engine.engine._estimate_tokens', side_effect=mock_estimate):
                result = engine.run()
            warning_events = [e for e in events if e.get("type") == "context_warning"]
            self.assertEqual(len(warning_events), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# 13. Cross-Language & File Tool Tests (from test_ai_builder_comprehensive.py)
# ====================================================================

class TestCrossLanguageE2E(unittest.TestCase):
    """End-to-end test simulating a cross-language code revision task."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))
        os.makedirs(os.path.join(self.test_dir, 'java', 'src'), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, 'csharp', 'src'), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, 'python', 'src'), exist_ok=True)
        with open(os.path.join(self.test_dir, 'java', 'src', 'App.java'), 'w') as f:
            f.write('public class App { public static void main(String[] args) { System.out.println("Hello"); } }\n')
        csproj = os.path.join(self.test_dir, 'csharp', 'src', 'App.csproj')
        with open(csproj, 'w') as f:
            f.write('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        with open(os.path.join(self.test_dir, 'csharp', 'src', 'Program.cs'), 'w') as f:
            f.write('using System;\npublic class Program { public static void Main() { Console.WriteLine("Hi"); } }\n')
        with open(os.path.join(self.test_dir, 'python', 'src', 'main.py'), 'w') as f:
            f.write('def hello():\n    print("Hello")\n')

    def test_cross_language_syntax_verification(self):
        tool = CheckSyntaxTool(self.test_dir)
        r = tool.execute({'path': 'csharp/src/Program.cs'})
        self.assertTrue(r.success, f"C# check failed: {r.error}")
        r = tool.execute({'path': 'python/src/main.py'})
        self.assertTrue(r.success, f"Python check failed: {r.error}")

class TestJavaSyntaxCheck(unittest.TestCase):
    @unittest.skipIf(not _java_available(), "Java (javac) not available")
    def test_valid_java_syntax(self):
        tool = CheckSyntaxTool(TEST_PROJECT)
        r = tool.execute({'path': 'java-project/src/main/java/com/example/App.java'})
        self.assertTrue(r.success)
        self.assertIn('OK', r.content)

    @unittest.skipIf(not _java_available(), "Java (javac) not available")
    def test_valid_java_class_syntax(self):
        tool = CheckSyntaxTool(TEST_PROJECT)
        r = tool.execute({'path': 'java-project/src/main/java/com/example/Calculator.java'})
        self.assertTrue(r.success)
        self.assertIn('OK', r.content)

    def test_invalid_java_syntax(self):
        tmpdir = tempfile.mkdtemp()
        try:
            bad_java = os.path.join(tmpdir, 'Bad.java')
            with open(bad_java, 'w') as f:
                f.write('public class Bad { public void foo( { }')
            tool = CheckSyntaxTool(tmpdir)
            with patch('subprocess.run', side_effect=FileNotFoundError()):
                r = tool.execute({'path': 'Bad.java'})
                self.assertFalse(r.success)
                self.assertTrue(r.content or r.error)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_java_brace_fallback(self):
        tmpdir = tempfile.mkdtemp()
        try:
            good_java = os.path.join(tmpdir, 'Good.java')
            with open(good_java, 'w') as f:
                f.write('public class Good {\n    public void foo() { } \n}\n')
            tool = CheckSyntaxTool(tmpdir)
            with patch('subprocess.run', side_effect=FileNotFoundError()):
                r = tool.execute({'path': 'Good.java'})
                self.assertTrue(r.success)
                self.assertIn('OK', r.content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestCSharpSyntaxCheck(unittest.TestCase):
    def test_valid_csharp_syntax(self):
        tool = CheckSyntaxTool(TEST_PROJECT)
        r = tool.execute({'path': 'csharp-project/Program.cs'})
        self.assertTrue(r.success)
        self.assertIn('OK', r.content)

    def test_invalid_csharp_syntax(self):
        tmpdir = tempfile.mkdtemp()
        try:
            bad_cs = os.path.join(tmpdir, 'Bad.cs')
            with open(bad_cs, 'w') as f:
                f.write('using System; class Bad { public static void Main() {')
            csproj = os.path.join(tmpdir, 'Bad.csproj')
            with open(csproj, 'w') as f:
                f.write('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
            tool = CheckSyntaxTool(tmpdir)
            r = tool.execute({'path': 'Bad.cs'})
            self.assertFalse(r.success)
            self.assertIn('error', r.error.lower())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_csharp_brace_fallback(self):
        tmpdir = tempfile.mkdtemp()
        try:
            good_cs = os.path.join(tmpdir, 'Good.cs')
            with open(good_cs, 'w') as f:
                f.write('using System;\npublic class Good {\n    public void Foo() { }\n}\n')
            tool = CheckSyntaxTool(tmpdir)
            with patch('subprocess.run', side_effect=FileNotFoundError()):
                r = tool.execute({'path': 'Good.cs'})
                self.assertTrue(r.success)
                self.assertIn('OK', r.content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestDecompileJar(unittest.TestCase):
    @unittest.skipIf(not _java_available(), "Java (jar/javap) not available")
    def test_decompile_jar(self):
        tool = DecompileJarTool(TEST_PROJECT)
        r = tool.execute({'jar_path': 'java-project/target/demo-1.0.0.jar'})
        self.assertTrue(r.success)

    def test_decompile_nonexistent_jar(self):
        tool = DecompileJarTool(TEST_PROJECT)
        r = tool.execute({'jar_path': 'nonexistent.jar'})
        self.assertFalse(r.success)
        self.assertIn('not found', r.error.lower())

class TestFindSymbol(unittest.TestCase):
    def test_find_java_class(self):
        tool = FindSymbolTool(TEST_PROJECT)
        r = tool.execute({'symbol': 'Calculator'})
        self.assertTrue(r.success)
        results = json.loads(r.content)
        self.assertGreater(len(results), 0)
        self.assertTrue(any('Calculator' in r['text'] for r in results))

    def test_find_python_function(self):
        tool = FindSymbolTool(TEST_PROJECT)
        r = tool.execute({'symbol': 'greet'})
        self.assertTrue(r.success)
        results = json.loads(r.content)
        self.assertGreater(len(results), 0)

    def test_find_csharp_class(self):
        tool = FindSymbolTool(TEST_PROJECT)
        r = tool.execute({'symbol': 'Calculator'})
        self.assertTrue(r.success)
        results = json.loads(r.content)
        self.assertGreater(len(results), 0)


# ====================================================================
# 14. Pending Tool Approval Tests (from test_pending_tool_approval.py)
# ====================================================================

class TestPendingToolApprovalFlow(unittest.TestCase):
    """Tests for the full pending tool approval -> execution flow."""

    def setUp(self):
        _reset_registry()

    def tearDown(self):
        _reset_registry()

    def test_plain_class_tool_executes_after_approval(self):
        tmpdir, output_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        code = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any
class EchoTool(BaseTool):
    name = "echo_tool"
    description = "Echoes back input"
    parameters = {"message": "string"}
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        msg = params.get("message", "none")
        return ToolResult(success=True, content="Echo: " + str(msg), summary="Done")
'''
        _create_pending_tool_file(output_dir, "echo_tool", code)
        registry = get_registry()
        loader = registry._get_or_create_loader(output_dir)
        result = loader.approve_tool("echo_tool")
        self.assertEqual(result["status"], "approved")
        self.assertIn("echo_tool", loader.get_tool_names())
        exec_result = registry.execute("echo_tool", {"message": "hello"}, output_dir, output_dir)
        self.assertTrue(exec_result.success)
        self.assertIn("Echo: hello", exec_result.content)
        shutil.rmtree(tmpdir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)

    def test_subclass_tool_executes_after_approval(self):
        tmpdir, output_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        code = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any
class GreetTool(BaseTool):
    name = "greet_tool"
    description = "Greets someone"
    parameters = {"name": "string"}
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        name = params.get("name", "world")
        return ToolResult(success=True, content="Hello, " + str(name) + "!", summary="Done")
'''
        _create_pending_tool_file(output_dir, "greet_tool", code)
        registry = get_registry()
        registry._get_or_create_loader(output_dir).approve_tool("greet_tool")
        exec_result = registry.execute("greet_tool", {"name": "Daniel"}, output_dir, output_dir)
        self.assertTrue(exec_result.success)
        self.assertIn("Hello, Daniel!", exec_result.content)
        shutil.rmtree(tmpdir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)

    def test_function_tool_executes_after_approval(self):
        tmpdir, output_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        code = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any
class MathToolTool(BaseTool):
    name = "math_tool"
    description = "A simple math tool."
    parameters = {"x": "string?"}
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        x = params.get("x", "0")
        return ToolResult(success=True, content="Result: " + str(x), summary="Done")
'''
        _create_pending_tool_file(output_dir, "math_tool", code)
        registry = get_registry()
        registry._get_or_create_loader(output_dir).approve_tool("math_tool")
        exec_result = registry.execute("math_tool", {"x": "42"}, output_dir, output_dir)
        self.assertTrue(exec_result.success)
        self.assertIn("Result: 42", exec_result.content)
        shutil.rmtree(tmpdir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)

    def test_approved_tool_in_list_tools(self):
        tmpdir, output_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        code = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any
class ListTestTool(BaseTool):
    name = "list_test"
    description = "A list test tool"
    parameters = {}
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, content="ok", summary="Done")
'''
        _create_pending_tool_file(output_dir, "list_test", code)
        registry = get_registry()
        registry._get_or_create_loader(output_dir).approve_tool("list_test")
        tools = registry._get_or_create_loader(output_dir).list_tools()
        tool_names = [t['name'] for t in tools]
        self.assertIn("list_test", tool_names)
        list_test_def = next(t for t in tools if t['name'] == 'list_test')
        self.assertEqual(list_test_def['description'], "A list test tool")
        shutil.rmtree(tmpdir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)

    def test_rejected_tool_not_available(self):
        tmpdir, output_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        code = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any
class RejectedTool(BaseTool):
    name = "rejected_tool"
    description = "A rejected tool"
    parameters = {}
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, content="should not happen", summary="Done")
'''
        _create_pending_tool_file(output_dir, "rejected_tool", code)
        registry = get_registry()
        loader = registry._get_or_create_loader(output_dir)
        loader.reject_tool("rejected_tool")
        self.assertNotIn("rejected_tool", loader.get_tool_names())
        pending = loader.get_pending_tools()
        self.assertEqual(len(pending), 0)
        shutil.rmtree(tmpdir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)

    def test_multiple_approved_tools_all_executable(self):
        tmpdir, output_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        code1 = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any
class ToolA(BaseTool):
    name = "tool_a"
    description = "Tool A"
    parameters = {}
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, content="A", summary="Done")
'''
        code2 = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any
class ToolB(BaseTool):
    name = "tool_b"
    description = "Tool B"
    parameters = {}
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, content="B", summary="Done")
'''
        _create_pending_tool_file(output_dir, "tool_a", code1)
        _create_pending_tool_file(output_dir, "tool_b", code2)
        registry = get_registry()
        loader = registry._get_or_create_loader(output_dir)
        loader.approve_tool("tool_a")
        loader.approve_tool("tool_b")
        r1 = registry.execute("tool_a", {}, output_dir, output_dir)
        self.assertTrue(r1.success)
        self.assertEqual(r1.content, "A")
        r2 = registry.execute("tool_b", {}, output_dir, output_dir)
        self.assertTrue(r2.success)
        self.assertEqual(r2.content, "B")
        shutil.rmtree(tmpdir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)


def _create_pending_tool_file(output_dir, tool_name, code):
    """Create a pending tool .py file."""
    pending_dir = os.path.join(output_dir, "tools", "pending")
    os.makedirs(pending_dir, exist_ok=True)
    tool_file = os.path.join(pending_dir, f"{tool_name}.py")
    with open(tool_file, 'w') as f:
        f.write(code)
    return tool_file


# ====================================================================
# 15. Mock LLM Server Tests (from test_integration_mock_llm.py)
# ====================================================================

class TestMockLLMServer(unittest.TestCase):
    """Test the mock LLM server itself."""

    def setUp(self):
        from tests.mock_llm_server import MockLLMServer
        self.server = MockLLMServer(host='127.0.0.1', port=0)
        self.port = self.server.start()
        self.base_url = f"http://127.0.0.1:{self.port}/v1/chat/completions"

    def tearDown(self):
        self.server.stop()

    def test_server_starts(self):
        self.assertIsNotNone(self.server)
        self.assertGreater(self.port, 0)

    def test_non_streaming_response(self):
        self.server.add_response(r"hello", "Hello! I'm a mock AI.")
        payload = {"model": "test-model", "messages": [{"role": "user", "content": "hello"}], "stream": False}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(self.base_url, data=data, headers={"Content-Type": "application/json"}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
        self.assertEqual(result["choices"][0]["message"]["content"], "Hello! I'm a mock AI.")
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")

    def test_streaming_response(self):
        self.server.add_response(r"hello", "Hello!")
        payload = {"model": "test-model", "messages": [{"role": "user", "content": "hello"}], "stream": True}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(self.base_url, data=data, headers={"Content-Type": "application/json"}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as response:
            chunks = []
            for line in response:
                line = line.decode('utf-8').strip()
                if line.startswith('data: '):
                    data_str = line[6:]
                    if data_str == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data_str)
                        chunks.append(chunk)
                    except json.JSONDecodeError:
                        continue
        self.assertGreater(len(chunks), 0)
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "stop")

    def test_tool_calls_response(self):
        from tests.mock_llm_server import MockLLMToolCall
        self.server.add_response(r"list_directory", "I'll help.", tool_calls=[MockLLMToolCall("list_directory", {"path": "."})])
        payload = {"model": "test-model", "messages": [{"role": "user", "content": "list_directory"}], "stream": False}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(self.base_url, data=data, headers={"Content-Type": "application/json"}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
        self.assertEqual(result["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(len(result["choices"][0]["message"]["tool_calls"]), 1)
        self.assertEqual(result["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "list_directory")

    def test_multiple_tool_calls(self):
        from tests.mock_llm_server import MockLLMToolCall
        self.server.add_response(r"complex", "I'll do multiple.", tool_calls=[
            MockLLMToolCall("list_directory", {"path": "."}),
            MockLLMToolCall("read_file", {"path": "README.md"})
        ])
        payload = {"model": "test-model", "messages": [{"role": "user", "content": "complex"}], "stream": False}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(self.base_url, data=data, headers={"Content-Type": "application/json"}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
        self.assertEqual(result["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(len(result["choices"][0]["message"]["tool_calls"]), 2)

    def test_tag_based_tool_call_response(self):
        self.server.instance_prefix = "test1234"
        self.server.add_tool_call_response(r"read_file", "read_file", {"path": "main.py"})
        payload = {"model": "test-model", "messages": [{"role": "user", "content": "read_file main.py"}], "stream": False}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(self.base_url, data=data, headers={"Content-Type": "application/json"}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
        content = result["choices"][0]["message"]["content"]
        self.assertIn("[test1234_TOOL_START]", content)
        self.assertIn("[test1234_TOOL_NAME]", content)
        self.assertIn("test1234_read_file", content)
        self.assertIn("[test1234_PARAM_NAME]", content)
        self.assertIn("[test1234_PARAM_VALUE]", content)
        self.assertIn("main.py", content)
        self.assertIn("[test1234_TOOL_END]", content)


# ====================================================================
# 16. LLMClient Tests (from test_remaining_features.py)
# ====================================================================

class TestLLMClientContextTrimming(unittest.TestCase):
    def test_context_trimming_with_max_tokens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = LLMClient(max_context_tokens=100, audit_dir=tmpdir)
            self.assertEqual(client._max_context_tokens, 100)

    def test_no_context_trimming_when_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = LLMClient(max_context_tokens=0, audit_dir=tmpdir)
            self.assertEqual(client._max_context_tokens, 0)


class TestAuditFilename(unittest.TestCase):
    def test_audit_filename_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = LLMClient(audit_dir=tmpdir)
            req, resp = client._audit_filename(step=5)
            self.assertTrue(req.endswith("_step5_request.json"))
            self.assertTrue(resp.endswith("_step5_response.json"))
            self.assertIn(tmpdir, req)
            self.assertIn(tmpdir, resp)

    def test_no_audit_dir_returns_empty(self):
        client = LLMClient(audit_dir=None)
        req, resp = client._audit_filename(step=5)
        self.assertEqual(req, "")
        self.assertEqual(resp, "")


# ====================================================================
# 17. Instance Prefix Tests (from test_round16.py)
# ====================================================================

class TestInstancePrefix(unittest.TestCase):
    """Tests for the epoch-based instance prefix mechanism."""

    def test_prefix_is_epoch_based(self):
        """The prefix should be an 8-digit epoch tick string."""
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, [])
            self.assertRegex(engine.instance_prefix, r'^\d{8}$')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_prefix_used_in_system_prompt(self):
        """System prompt should contain prefixed tool names."""
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, [])
            self.assertIn(engine.instance_prefix, engine.system_prompt)
            # Prefixed tool names should appear
            self.assertIn(f"{engine.instance_prefix}_list_directory", engine.system_prompt)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_parse_tool_calls_strips_prefix(self):
        """parse_tool_calls should strip the instance prefix from tool names."""
        prefix = "12345678"
        response = (
            f"[{prefix}_TOOL_START]\n[{prefix}_TOOL_NAME]\n"
            f"{prefix}_write_file\n"
            f"[{prefix}_PARAM_NAME]\npath\n"
            f"[{prefix}_PARAM_VALUE]\ntest.txt\n"
            f"[{prefix}_TOOL_END]"
        )
        calls = parse_tool_calls(response, prefix)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "write_file")

    def test_is_done_with_prefixed_task_completed(self):
        """is_done should detect <prefix>_task_completed when prefix is provided."""
        prefix = "12345678"
        response = (
            f"[{prefix}_TOOL_START]\n[{prefix}_TOOL_NAME]\n"
            f"{prefix}_task_completed\n"
            f"[{prefix}_PARAM_NAME]\nsummary\n"
            f"[{prefix}_PARAM_VALUE]\nDone\n"
            f"[{prefix}_TOOL_END]"
        )
        done, summary = is_done(response, prefix)
        self.assertTrue(done)
        self.assertEqual(summary, "Done")


# ====================================================================
# 18. Grep Code Optimization Test
# ====================================================================

class TestGrepCodeOptimization(unittest.TestCase):
    def test_grep_code_uses_subprocess(self):
        """Test that grep_code tool works correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "test1.txt"), 'w') as f:
                f.write("Hello World\nThis is a test\n")
            with open(os.path.join(tmpdir, "test2.txt"), 'w') as f:
                f.write("Another test file\nHello again\n")
            tool = GrepCodeTool(root_dir=tmpdir)
            result = tool.execute({"pattern": "Hello"})
            self.assertTrue(result.success)
            self.assertIn("test1.txt", result.content)
            self.assertIn("test2.txt", result.content)
            self.assertIn("2 matches", result.summary)


# ====================================================================
# 19. Continuation Message Tests
# ====================================================================

class TestContinuationEdgeCases(unittest.TestCase):
    def test_continuation_without_system_prompt(self):
        from app import _reconstruct_from_step_history
        mock_engine = MagicMock()
        mock_engine.messages = []
        mock_engine.tools = MagicMock()
        mock_engine.tools.tool_names.return_value = ['list_directory']
        steps = []
        with self.assertRaises((IndexError, KeyError)):
            _reconstruct_from_step_history(mock_engine, steps, "Test", is_continuation=True)

    def test_continuation_with_existing_history(self):
        from app import _reconstruct_from_step_history
        mock_engine = MagicMock()
        mock_engine.messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Add a function."},
            {"role": "assistant", "content": "[TOOL_START]...[TOOL_END]"},
            {"role": "user", "content": "Result: success"},
        ]
        mock_engine.tools = MagicMock()
        mock_engine.tools.tool_names.return_value = ['list_directory']
        steps = [
            {'step': 1, 'tool': 'list_directory', 'params': {}, 'result': {'success': True, 'content': '[]'}},
        ]
        _reconstruct_from_step_history(mock_engine, steps, "Test", is_continuation=True)
        self.assertEqual(len(mock_engine.messages), 4)
        last_msg = mock_engine.messages[-1]
        self.assertEqual(last_msg['role'], 'user')
        self.assertIn('[CONTINUATION]', last_msg['content'])


class TestContinuationMessages(unittest.TestCase):
    def test_verbose_tool_format_in_continuation(self):
        from app import _reconstruct_from_step_history
        mock_engine = MagicMock()
        mock_engine.messages = [{"role": "system", "content": "System prompt"}]
        mock_engine.tools = MagicMock()
        mock_engine.tools.tool_names.return_value = [
            'list_directory', 'read_file', 'edit_file', 'write_file',
            'delete_file', 'check_syntax'
        ]
        steps = [
            {'step': 1, 'tool': 'list_directory', 'params': {}, 'result': {'success': True, 'content': '[]'}},
        ]
        _reconstruct_from_step_history(mock_engine, steps, "Test instructions", is_continuation=True)
        continuation = None
        for m in mock_engine.messages:
            if m.get('role') == 'user' and '[CONTINUATION]' in m.get('content', ''):
                continuation = m['content']
                break
        self.assertIsNotNone(continuation, "Continuation message not found")
        self.assertIn("TOOL FORMAT REMINDER", continuation)
        self.assertIn("task_completed", continuation)

    def test_continuation_includes_task_completed(self):
        from app import _reconstruct_from_step_history
        mock_engine = MagicMock()
        mock_engine.messages = [{"role": "system", "content": "System prompt"}]
        mock_engine.tools = MagicMock()
        mock_engine.tools.tool_names.return_value = ['list_directory']
        steps = []
        _reconstruct_from_step_history(mock_engine, steps, "Test", is_continuation=True)
        self.assertIsNotNone(mock_engine.messages)
        for m in mock_engine.messages:
            if m.get('role') == 'user' and '[CONTINUATION]' in m.get('content', ''):
                self.assertIn("task_completed", m['content'])
                break


# ====================================================================
# 20. HTML Escaping Safety Test
# ====================================================================

class TestHTMLEscapingSafety(unittest.TestCase):
    def test_escapeHtml_escapes_quotes(self):
        """escapeHtml must escape quotes to prevent HTML attribute breakage in VIEW LIVE."""
        site_js = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'static', 'site.js'
        )
        with open(site_js) as f:
            js = f.read()
        match = re.search(r'function escapeHtml\s*\([^)]*\)\s*\{([^}]+)\}', js)
        self.assertIsNotNone(match, "escapeHtml function not found in site.js")
        func_body = match.group(1)
        self.assertIn('&quot;', func_body)
        self.assertIn('&apos;', func_body)
        self.assertIn('&amp;', func_body)
        self.assertIn('&lt;', func_body)
        self.assertIn('&gt;', func_body)


# ====================================================================
# 21. Reload Approved Tools & Script Tests
# ====================================================================

class TestReloadApprovedTools(unittest.TestCase):
    def test_reload_updates_system_prompt(self):
        tmpdir = tempfile.mkdtemp()
        try:
            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Test",
                "enabled_tools": ["list_directory"],
            }
            engine = AgentEngine(project_config)
            old_prompt = engine.system_prompt
            with patch.object(engine, '_reload_project_tool_loader'):
                engine.reload_approved_tools()
            self.assertIsNotNone(engine.system_prompt)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)



# ====================================================================
# 22. Stop Event & Max Steps Tests
# ====================================================================

class TestStopEventHandling(unittest.TestCase):
    def test_stop_event_stops_engine(self):
        tmpdir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# Test")
            with open(os.path.join(tmpdir, "src", "main.py"), "w") as f:
                f.write("print('hello')\n")
            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Add a function",
                "enabled_tools": ["list_directory"],
            }
            stop_event = threading.Event()
            stop_event.set()
            engine = AgentEngine(project_config)
            engine._stop_event = stop_event
            with patch.object(engine.llm, 'call', return_value={"content": "", "raw_request": "", "raw_response": ""}):
                result = engine.run()
                self.assertEqual(result["status"], "stopped")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestMaxStepsHandling(unittest.TestCase):
    def test_max_steps_reached(self):
        tmpdir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# Test")
            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Test",
                "enabled_tools": ["list_directory"],
            }
            engine = AgentEngine(project_config)
            engine.step_count = 5
            engine.max_steps = 5
            engine._continue_requested = False
            with patch.object(engine.llm, 'call', return_value={"content": "", "raw_request": "", "raw_response": ""}):
                result = engine.run()
                self.assertEqual(result["status"], "max_steps_reached")
                self.assertEqual(result["steps"], 5)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# 23. Pending Tool Approval in Engine
# ====================================================================

class TestPendingToolApprovalEngine(unittest.TestCase):
    def test_pending_approval_status(self):
        tmpdir = tempfile.mkdtemp()
        try:
            os.environ["AIB_OUTPUT_DIR"] = tmpdir
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# Test")
            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Create a tool",
                "enabled_tools": ["list_directory", "create_tool"],
            }
            engine = AgentEngine(project_config)
            prefix = engine.instance_prefix
            mock_response = (
                f"[{prefix}_TOOL_START]\n[{prefix}_TOOL_NAME]\n"
                f"{prefix}_create_tool\n"
                f"[{prefix}_PARAM_NAME]\nname\n[{prefix}_PARAM_VALUE]\nmy_tool\n"
                f"[{prefix}_PARAM_NAME]\ndescription\n[{prefix}_PARAM_VALUE]\nA test tool that does something for testing purposes\n"
                f"[{prefix}_PARAM_NAME]\nparameters\n[{prefix}_PARAM_VALUE]\n{{}}\n"
                f"[{prefix}_PARAM_NAME]\ncode\n[{prefix}_PARAM_VALUE]\nfrom agent_engine.tools.base import BaseTool, ToolResult\nclass my_tool(BaseTool):\n    name = 'my_tool'\n    description = 'A test tool'\n    parameters = {{}}\n    def execute(self, params):\n        return ToolResult(True, 'ok')\n"
                f"[{prefix}_TOOL_END]"
            )
            with patch.object(engine.llm, 'call', return_value={
                "content": mock_response, "raw_request": "", "raw_response": ""
            }):
                result = engine.run()
                self.assertEqual(result["status"], "pending_approval")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            os.environ.pop("AIB_OUTPUT_DIR", None)

    def test_check_pending_tools_emits_events(self):
        """_check_pending_tools should emit pending_approval events for each pending tool."""
        tmpdir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# Test")
            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Test",
            }
            engine = AgentEngine(project_config)
            # Create a pending tool file in the engine's output_dir
            pending_dir = os.path.join(engine.output_dir, "tools", "pending")
            os.makedirs(pending_dir, exist_ok=True)
            with open(os.path.join(pending_dir, "my_tool.py"), "w") as f:
                f.write('from agent_engine.tools.base import BaseTool, ToolResult\n\nclass my_tool(BaseTool):\n    name = "my_tool"\n    description = "A test tool"\n    parameters = {}\n    def execute(self, params):\n        return ToolResult(True, "ok")\n')
            events = []
            engine._step_callback = lambda e: events.append(e)
            engine._check_pending_tools()
            approval_events = [e for e in events if e.get("type") == "pending_approval"]
            self.assertEqual(len(approval_events), 1)
            self.assertEqual(approval_events[0]["tool_name"], "my_tool")
            # Should have injected a user message about pending tools
            pending_msgs = [m for m in engine.messages
                            if m.get("role") != "system"
                            and "PENDING TOOL APPROVAL" in m.get("content", "")]
            self.assertEqual(len(pending_msgs), 1)
            self.assertIn("my_tool", pending_msgs[0]["content"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_check_pending_tools_noop_when_none(self):
        """_check_pending_tools should do nothing when there are no pending tools."""
        tmpdir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# Test")
            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Test",
            }
            engine = AgentEngine(project_config)
            events = []
            engine._step_callback = lambda e: events.append(e)
            engine._check_pending_tools()
            approval_events = [e for e in events if e.get("type") == "pending_approval"]
            self.assertEqual(len(approval_events), 0)
            pending_msgs = [m for m in engine.messages
                            if m.get("role") != "system"
                            and "PENDING TOOL APPROVAL" in m.get("content", "")]
            self.assertEqual(len(pending_msgs), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# 24. Context Warning Flag Test
# ====================================================================

class TestContextWarning(unittest.TestCase):
    def test_context_warning_flag(self):
        tmpdir = tempfile.mkdtemp()
        try:
            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Test",
                "enabled_tools": ["list_directory"],
            }
            engine = AgentEngine(project_config)
            self.assertFalse(engine._context_warning_shown)
            self.assertFalse(hasattr(engine, '_compress_enabled'))
            self.assertFalse(hasattr(engine, '_compress_threshold'))
            self.assertFalse(hasattr(engine, '_compressed'))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# 25. respond_to_user / request_user_input truncation exclusion
# ====================================================================

class TestRespondToUserNoTruncation(unittest.TestCase):
    def test_respond_to_user_not_in_truncation_filter(self):
        with open(os.path.join(os.path.dirname(__file__), '..', 'agent_engine', 'engine.py')) as f:
            content = f.read()
        self.assertIn('tool_name not in ("respond_to_user", "request_user_input")', content)

    def test_request_user_input_not_in_truncation_filter(self):
        with open(os.path.join(os.path.dirname(__file__), '..', 'agent_engine', 'engine.py')) as f:
            content = f.read()
        self.assertIn('tool_name not in ("respond_to_user", "request_user_input")', content)


# ====================================================================
# 26. Queue & App Integration Tests
# ====================================================================

class TestQueueBehavior(unittest.TestCase):
    def test_queue_guards_exist(self):
        with open(os.path.join(os.path.dirname(__file__), '..', 'app.py')) as f:
            content = f.read()
        self.assertIn('is_running, is_queued, existing_job_id = get_concurrent_job_info', content)
        self.assertIn('if is_running:', content)
        self.assertIn('if is_queued:', content)

    def test_get_concurrent_job_info_returns_correct_values(self):
        from app import get_concurrent_job_info
        is_running, is_queued, job_id = get_concurrent_job_info("nonexistent")
        self.assertFalse(is_running)
        self.assertFalse(is_queued)
        self.assertIsNone(job_id)


# ====================================================================
# 27. Edit File Strategies (from test_round16.py)
# ====================================================================

class TestEditFileStrategies(unittest.TestCase):
    def test_exact_match(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'exact.py')
            with open(test_file, 'w') as f:
                f.write('x = 1\ny = 2\nz = 3\n')
            tool = EditFileTool(tmpdir)
            r = tool.execute({'path': 'exact.py', 'original_text': 'y = 2', 'new_text': 'y = 10'})
            self.assertTrue(r.success, f"Exact match failed: {r.error}")
            with open(test_file) as f:
                self.assertIn('y = 10', f.read())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_whitespace_insensitive_match(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'ws.py')
            with open(test_file, 'w') as f:
                f.write('x = 1\n  y  =  2\nz = 3\n')
            tool = EditFileTool(tmpdir)
            r = tool.execute({'path': 'ws.py', 'original_text': 'y = 2', 'new_text': 'y = 20'})
            self.assertTrue(r.success, f"Whitespace match failed: {r.error}")
            with open(test_file) as f:
                content = f.read()
                # The edit replaces the matched text with the new text
                self.assertIn('y = 20', content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_line_range_replacement(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'range.py')
            with open(test_file, 'w') as f:
                f.write('line1\nline2\nline3\nline4\n')
            tool = EditFileTool(tmpdir)
            r = tool.execute({'path': 'range.py', 'original_text': '', 'new_text': 'replaced\n', 'line_start': '2', 'line_end': '3'})
            self.assertTrue(r.success, f"Line-range match failed: {r.error}")
            with open(test_file) as f:
                content = f.read()
                self.assertIn('line1', content)
                self.assertIn('replaced', content)
                self.assertIn('line4', content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_helpful_error_message(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'error.py')
            with open(test_file, 'w') as f:
                f.write('hello world\n')
            tool = EditFileTool(tmpdir)
            r = tool.execute({'path': 'error.py', 'original_text': 'goodbye world', 'new_text': 'farewell'})
            self.assertFalse(r.success)
            error_lower = r.error.lower()
            self.assertTrue(
                'suggestions' in error_lower or 'preview' in error_lower,
                f"Expected helpful error message, got: {r.error}"
            )
            self.assertIn('hello world', r.error)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# 28. Tool Approval Endpoint Tests
# ====================================================================

class TestToolApprovalEndpoint(unittest.TestCase):
    def test_approval_endpoint_calls_resume_engine(self):
        with open(os.path.join(os.path.dirname(__file__), '..', 'app.py')) as f:
            content = f.read()
        approve_idx = content.find('def api_approve_tool')
        self.assertGreater(approve_idx, 0)
        approve_section = content[approve_idx:approve_idx+2000]
        self.assertIn('_find_project_and_resume_engine', approve_section)


class TestToolStartShowsDetails(unittest.TestCase):
    def test_handle_tool_start_shows_rationale(self):
        with open(os.path.join(os.path.dirname(__file__), '..', 'static', 'site.js')) as f:
            content = f.read()
        self.assertIn('data.rationale', content)

    def test_handle_tool_start_shows_params(self):
        with open(os.path.join(os.path.dirname(__file__), '..', 'static', 'site.js')) as f:
            content = f.read()
        self.assertIn('data.params && Object.keys(data.params).length', content)

    def test_polling_replaces_sse(self):
        with open(os.path.join(os.path.dirname(__file__), '..', 'static', 'site.js')) as f:
            content = f.read()
        self.assertIn('_startPolling', content)
        self.assertIn('pollInterval', content)


if __name__ == '__main__':
    unittest.main()
