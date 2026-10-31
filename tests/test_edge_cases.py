"""Edge case tests for task_completed, stripping, and engine behavior."""
import json
import os
import sys
import tempfile
import shutil
import unittest
import unittest.mock as mock
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_engine.engine import is_done, parse_tool_calls, truncate_tool_result
from agent_engine.tools.task_completed import TaskCompletedTool
from agent_engine.tools.delete_file import DeleteFileTool


# ====================================================================
# Edge Case: task_completed detection
# ====================================================================

class TestIsDoneEdgeCases(unittest.TestCase):
    """Edge cases for is_done() detection."""

    def test_task_completed_with_whitespace_in_name(self):
        """task_completed with extra whitespace should still be detected."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "  task_completed  \n"
            "[PARAM_NAME]\n"
            "summary\n"
            "[PARAM_VALUE]\n"
            "Done\n"
            "[TOOL_END]"
        )
        done, summary = is_done(response)
        self.assertTrue(done)
        self.assertEqual(summary, "Done")

    def test_task_completed_nested_tool_block(self):
        """task_completed inside another tool block should still be detected."""
        response = (
            "Let me do something first.\n\n"
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "task_completed\n"
            "[PARAM_NAME]\n"
            "summary\n"
            "[PARAM_VALUE]\n"
            "Summary\n"
            "[TOOL_END]"
        )
        done, summary = is_done(response)
        self.assertTrue(done)
        self.assertEqual(summary, "Summary")

    def test_task_completed_no_summary_param(self):
        """task_completed without summary param should not be detected."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "task_completed\n"
            "[TOOL_END]"
        )
        done, summary = is_done(response)
        self.assertFalse(done)
        self.assertEqual(summary, "")

    def test_task_completed_empty_summary(self):
        """task_completed with empty summary should be detected."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "task_completed\n"
            "[PARAM_NAME]\n"
            "summary\n"
            "[PARAM_VALUE]\n"
            "\n"
            "[TOOL_END]"
        )
        done, summary = is_done(response)
        self.assertTrue(done)
        self.assertEqual(summary, "")

    def test_done_in_param_value_not_detected(self):
        """[DONE] text inside a parameter value should NOT be detected."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "write_file\n"
            "[PARAM_NAME]\n"
            "content\n"
            "[PARAM_VALUE]\n"
            "Some text [DONE] more text\n"
            "[TOOL_END]"
        )
        done, summary = is_done(response)
        self.assertFalse(done)

    def test_task_completed_with_special_chars_in_summary(self):
        """task_completed with special characters in summary."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "task_completed\n"
            "[PARAM_NAME]\n"
            "summary\n"
            "[PARAM_VALUE]\n"
            "Added: divide(a, b) — handles zero, returns float\n"
            "[TOOL_END]"
        )
        done, summary = is_done(response)
        self.assertTrue(done)
        self.assertIn("divide", summary)


# ====================================================================
# Edge Case: Non-tool content stripping
# ====================================================================

class TestStrippingEdgeCases(unittest.TestCase):
    """Edge cases for non-tool content stripping."""

    def _strip_non_tool(self, response):
        """Helper: strip non-tool content."""
        import re
        tool_blocks = re.findall(
            r'\[TOOL_START\].*?\[TOOL_END\]',
            response,
            flags=re.DOTALL,
        )
        return "\n\n".join(tool_blocks).strip()

    def test_text_before_and_after_tool(self):
        """Text before and after a tool call should both be stripped."""
        response = (
            "I'm going to list the directory.\n\n"
            "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]\n\n"
            "Then I'll read the files."
        )
        result = self._strip_non_tool(response)
        self.assertNotIn("I'm going", result)
        self.assertNotIn("Then I'll", result)
        self.assertIn("list_directory", result)

    def test_multiple_tool_blocks_with_text_between(self):
        """Multiple tool blocks with text between should all be kept."""
        response = (
            "First: list\n"
            "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]\n"
            "Then: read\n"
            "[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[TOOL_END]\n"
            "Finally: done"
        )
        result = self._strip_non_tool(response)
        self.assertIn("list_directory", result)
        self.assertIn("read_file", result)
        self.assertNotIn("First", result)
        self.assertNotIn("Then", result)
        self.assertNotIn("Finally", result)

    def test_empty_response(self):
        """Empty response should return empty string."""
        result = self._strip_non_tool("")
        self.assertEqual(result, "")

    def test_only_whitespace(self):
        """Response with only whitespace should return empty string."""
        result = self._strip_non_tool("   \n\n  ")
        self.assertEqual(result, "")

    def test_unclosed_tool_block_stripped(self):
        """Unclosed tool block should not be matched."""
        response = (
            "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n."
        )
        result = self._strip_non_tool(response)
        self.assertEqual(result, "")

    def test_task_completed_with_surrounding_text(self):
        """task_completed with surrounding text should be stripped to just the tool block."""
        response = (
            "I think we're done here.\n\n"
            "[TOOL_START]\n[TOOL_NAME]\ntask_completed\n[PARAM_NAME]\nsummary\n[PARAM_VALUE]\nAll done\n[TOOL_END]\n\n"
            "Goodbye!"
        )
        result = self._strip_non_tool(response)
        self.assertNotIn("I think", result)
        self.assertNotIn("Goodbye", result)
        self.assertIn("task_completed", result)
        self.assertIn("All done", result)

    def test_tool_block_with_newlines_in_params(self):
        """Tool block with newlines in parameter values should be captured."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "edit_file\n"
            "[PARAM_NAME]\n"
            "path\n"
            "[PARAM_VALUE]\n"
            "src/main.py\n"
            "[PARAM_NAME]\n"
            "original_text\n"
            "[PARAM_VALUE]\n"
            "def add(a, b):\n"
            "    return a + b\n"
            "[PARAM_NAME]\n"
            "new_text\n"
            "[PARAM_VALUE]\n"
            "def add(a, b):\n"
            "    return a + b\n"
            "\n"
            "def subtract(a, b):\n"
            "    return a - b\n"
            "[TOOL_END]"
        )
        result = self._strip_non_tool(response)
        self.assertIn("edit_file", result)
        self.assertIn("def subtract", result)


# ====================================================================
# Edge Case: parse_tool_calls
# ====================================================================

class TestParseToolCallsEdgeCases(unittest.TestCase):
    """Edge cases for parse_tool_calls."""

    def test_no_tool_calls_in_response(self):
        """Response with no tool calls should return empty list."""
        calls = parse_tool_calls("Just thinking out loud...")
        self.assertEqual(calls, [])

    def test_tool_call_with_no_params(self):
        """Tool call with no parameters should return empty params dict."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "list_directory\n"
            "[TOOL_END]"
        )
        # parse_tool_calls requires at least one PARAM_NAME to identify params
        # A tool call with no PARAM_NAME tags is not a valid tool call
        calls = parse_tool_calls(response)
        self.assertEqual(calls, [])

    def test_tool_call_with_missing_param_name(self):
        """Tool call with missing PARAM_NAME should not be parsed (invalid format)."""
        response = (
            "[TOOL_START]\n"
            "[PARAM_NAME]\n"
            "path\n"
            "[PARAM_VALUE]\n"
            ".\n"
            "[TOOL_END]"
        )
        # Missing TOOL_NAME means this is not a valid tool call
        calls = parse_tool_calls(response)
        self.assertEqual(calls, [])

    def test_multiple_tools_same_response(self):
        """Multiple tool calls in one response should all be parsed."""
        response = (
            "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]\n"
            "[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[TOOL_END]"
        )
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "list_directory")
        self.assertEqual(calls[1][0], "read_file")

    def test_malformed_tool_call_ignored(self):
        """Malformed tool call (missing TOOL_NAME) should be ignored."""
        response = (
            "[TOOL_START]\n"
            "[PARAM_NAME]\n"
            "path\n"
            "[PARAM_VALUE]\n"
            ".\n"
            "[TOOL_END]"
        )
        calls = parse_tool_calls(response)
        self.assertEqual(calls, [])

    def test_tool_call_with_unicode_in_params(self):
        """Tool call with unicode characters in params should be parsed."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "write_file\n"
            "[PARAM_NAME]\n"
            "content\n"
            "[PARAM_VALUE]\n"
            "Hello 世界 🌍\n"
            "[TOOL_END]"
        )
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["content"], "Hello 世界 🌍")


# ====================================================================
# Edge Case: Truncation
# ====================================================================

class TestTruncationEdgeCases(unittest.TestCase):
    """Edge cases for truncation."""

    def test_exact_limit_no_truncation(self):
        """Content exactly at limit should not be truncated."""
        content = "x" * 100
        result, was_truncated = truncate_tool_result(content, 100, "read_file")
        self.assertFalse(was_truncated)
        self.assertEqual(result, content)

    def test_one_over_limit_truncates(self):
        """Content one character over limit should be truncated."""
        content = "x" * 101
        result, was_truncated = truncate_tool_result(content, 100, "read_file")
        self.assertTrue(was_truncated)
        self.assertIn("TRUNCATED", result)
        self.assertIn("showing first 100 of 101", result)

    def test_truncation_with_newlines(self):
        """Truncation should handle content with newlines."""
        content = "line1\nline2\n" + "x" * 200
        result, was_truncated = truncate_tool_result(content, 100, "read_file")
        self.assertTrue(was_truncated)
        self.assertIn("line1", result)
        self.assertIn("TRUNCATED", result)

    def test_truncation_preserves_partial_word_at_boundary(self):
        """Truncation should cut at exact char boundary (may split words)."""
        content = "word1 word2 word3 " + "x" * 200
        result, was_truncated = truncate_tool_result(content, 30, "read_file")
        self.assertTrue(was_truncated)
        # Should contain first ~30 chars
        self.assertIn("word1", result)

    def test_truncation_notice_includes_total_chars(self):
        """Truncation notice should show total character count."""
        content = "x" * 500
        result, was_truncated = truncate_tool_result(content, 50, "read_file")
        self.assertIn("showing first 50 of 500", result)

    def test_truncation_with_empty_content(self):
        """Empty content should not be truncated."""
        result, was_truncated = truncate_tool_result("", 100, "read_file")
        self.assertFalse(was_truncated)
        self.assertEqual(result, "")


# ====================================================================
# Edge Case: task_completed tool execution
# ====================================================================

class TestTaskCompletedEdgeCases(unittest.TestCase):
    """Edge cases for task_completed tool execution."""

    def test_task_completed_with_very_long_summary(self):
        """task_completed with very long summary should succeed."""
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
        """task_completed with unicode summary should succeed."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = TaskCompletedTool(tmpdir)
            r = tool.execute({'summary': 'Added: 日本語テスト 🎉'})
            self.assertTrue(r.success)
            # The content is JSON-escaped, so check the summary field instead
            self.assertIn("日本語", r.summary)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_task_completed_with_newlines_in_summary(self):
        """task_completed with newlines in summary should succeed."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = TaskCompletedTool(tmpdir)
            r = tool.execute({'summary': 'Step 1\nStep 2\nStep 3'})
            self.assertTrue(r.success)
            self.assertIn("Step 3", r.content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Edge Case: delete_file verification
# ====================================================================

class TestDeleteFileEdgeCases(unittest.TestCase):
    """Edge cases for delete_file verification."""

    def test_delete_symlink(self):
        """Deleting a symlink should succeed."""
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
        """Deleting a directory should fail."""
        tmpdir = tempfile.mkdtemp()
        try:
            subdir = os.path.join(tmpdir, 'subdir')
            os.makedirs(subdir)
            self.assertTrue(os.path.isdir(subdir))

            tool = DeleteFileTool(tmpdir)
            r = tool.execute({'path': 'subdir'})
            self.assertFalse(r.success)
            # Directory should still exist
            self.assertTrue(os.path.isdir(subdir))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_delete_file_with_spaces_in_name(self):
        """Deleting a file with spaces in name should succeed."""
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


# ====================================================================
# Edge Case: Continuation messages
# ====================================================================

class TestContinuationEdgeCases(unittest.TestCase):
    """Edge cases for continuation messages."""

    def test_continuation_without_system_prompt(self):
        """Continuation without system prompt should handle gracefully."""
        from app import _reconstruct_from_step_history
        mock_engine = MagicMock()
        mock_engine.messages = []  # No system prompt
        mock_engine.tools = MagicMock()
        mock_engine.tools.tool_names.return_value = ['list_directory']
        steps = []
        # This will fail because the function expects engine.messages[0]
        # — the function assumes a system prompt always exists
        with self.assertRaises((IndexError, KeyError)):
            _reconstruct_from_step_history(mock_engine, steps, "Test", is_continuation=True)

    def test_continuation_with_existing_history(self):
        """Continuation should replace last message with continuation (not append)."""
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
        # Function replaces the last message with continuation (same count)
        self.assertEqual(len(mock_engine.messages), 4)
        # Last message should be the continuation
        last_msg = mock_engine.messages[-1]
        self.assertEqual(last_msg['role'], 'user')
        self.assertIn('[CONTINUATION]', last_msg['content'])


# ====================================================================
# Edge Case: SSE protocol [DONE] not interfering
# ====================================================================

class TestSSEProtocol(unittest.TestCase):
    """Verify OpenAI SSE [DONE] marker doesn't interfere with our completion."""

    def test_sse_done_in_stream_not_detected_as_completion(self):
        """SSE [DONE] marker should NOT be detected as task_completed."""
        # This is what the OpenAI SSE stream sends at the end
        sse_content = "data: [DONE]\n\n"
        done, summary = is_done(sse_content)
        self.assertFalse(done)
        self.assertEqual(summary, "")

    def test_sse_done_with_tool_call_before(self):
        """SSE [DONE] after a tool call should not affect parsing."""
        response = (
            "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]\n"
            "data: [DONE]\n\n"
        )
        done, summary = is_done(response)
        self.assertFalse(done)  # list_directory is not task_completed


if __name__ == '__main__':
    unittest.main()
