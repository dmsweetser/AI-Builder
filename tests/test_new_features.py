"""Tests for new features: task_completed, non-tool stripping, verification, truncation, continuations."""
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
from agent_engine.tools.write_file import WriteFileTool
from agent_engine.tools.edit_file import EditFileTool
from agent_engine.tools.check_syntax import CheckSyntaxTool


# ====================================================================
# is_done() Tests — task_completed detection
# ====================================================================

class TestIsDoneTaskCompleted(unittest.TestCase):
    """Tests for is_done() detecting task_completed tool calls."""

    def test_legacy_done_marker(self):
        """[DONE] marker is no longer supported — only task_completed works."""
        done, summary = is_done("[DONE] Added feature X")
        self.assertFalse(done)
        self.assertEqual(summary, "")

    def test_task_completed_tool_call(self):
        """task_completed tool call should be detected."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "task_completed\n"
            "[PARAM_NAME]\n"
            "summary\n"
            "[PARAM_VALUE]\n"
            "Added divide function with error handling\n"
            "[TOOL_END]"
        )
        done, summary = is_done(response)
        self.assertTrue(done)
        self.assertEqual(summary, "Added divide function with error handling")

    def test_task_completed_multiline_summary(self):
        """task_completed with multi-line summary should extract correctly."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "task_completed\n"
            "[PARAM_NAME]\n"
            "summary\n"
            "[PARAM_VALUE]\n"
            "Step 1: Added divide function\n"
            "Step 2: Added error handling\n"
            "Step 3: Verified with check_syntax\n"
            "[TOOL_END]"
        )
        done, summary = is_done(response)
        self.assertTrue(done)
        self.assertIn("Step 1", summary)
        self.assertIn("Step 3", summary)

    def test_no_completion(self):
        """Regular tool call should NOT be detected as done."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "read_file\n"
            "[PARAM_NAME]\n"
            "path\n"
            "[PARAM_VALUE]\n"
            "src/main.py\n"
            "[TOOL_END]"
        )
        done, summary = is_done(response)
        self.assertFalse(done)
        self.assertEqual(summary, "")

    def test_empty_response(self):
        """Empty response should not be detected as done."""
        done, summary = is_done("")
        self.assertFalse(done)
        self.assertEqual(summary, "")

    def test_random_text(self):
        """Random text should not be detected as done."""
        done, summary = is_done("Hello world, this is not a completion")
        self.assertFalse(done)
        self.assertEqual(summary, "")


# ====================================================================
# Non-Tool Content Stripping Tests
# ====================================================================

class TestNonToolContentStripping(unittest.TestCase):
    """Tests for stripping non-tool content from LLM responses."""

    def _strip_non_tool(self, response):
        """Helper: strip non-tool content (mirrors engine.py logic)."""
        import re
        tool_blocks = re.findall(
            r'\[TOOL_START\].*?\[TOOL_END\]',
            response,
            flags=re.DOTALL,
        )
        return "\n\n".join(tool_blocks).strip()

    def test_clean_tool_call_unchanged(self):
        """A clean tool call should pass through unchanged."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "list_directory\n"
            "[PARAM_NAME]\n"
            "path\n"
            "[PARAM_VALUE]\n"
            ".\n"
            "[TOOL_END]"
        )
        result = self._strip_non_tool(response)
        self.assertEqual(result, response)

    def test_text_before_tool_stripped(self):
        """Text before a tool call should be stripped."""
        response = "Let me think about this...\n\n[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]"
        result = self._strip_non_tool(response)
        self.assertNotIn("Let me think", result)
        self.assertIn("[TOOL_START]", result)

    def test_text_after_tool_stripped(self):
        """Text after a tool call should be stripped."""
        response = (
            "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]\n\n"
            "I'll explore the directory structure now."
        )
        result = self._strip_non_tool(response)
        self.assertNotIn("I'll explore", result)
        self.assertIn("[TOOL_END]", result)

    def test_done_marker_stripped(self):
        """[DONE] marker is no longer preserved — only tool blocks remain."""
        response = "I think we're done here.\n\n[DONE] Added the divide function."
        result = self._strip_non_tool(response)
        # [DONE] should NOT be in result since it's not a tool block
        self.assertNotIn("[DONE]", result)
        self.assertNotIn("I think we're done", result)
        # Result should be empty since there are no tool blocks
        self.assertEqual(result, "")

    def test_task_completed_preserved(self):
        """task_completed tool call should be preserved as a tool block."""
        response = (
            "[TOOL_START]\n"
            "[TOOL_NAME]\n"
            "task_completed\n"
            "[PARAM_NAME]\n"
            "summary\n"
            "[PARAM_VALUE]\n"
            "All changes complete\n"
            "[TOOL_END]"
        )
        result = self._strip_non_tool(response)
        # The tool block is kept (for tool execution)
        self.assertIn("[TOOL_START]", result)
        self.assertIn("task_completed", result)
        self.assertIn("All changes complete", result)

    def test_multiple_tool_blocks_kept(self):
        """Multiple tool blocks should all be kept (though engine takes only first)."""
        response = (
            "Thinking...\n"
            "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]\n"
            "Some text\n"
            "[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[TOOL_END]\n"
            "More text"
        )
        result = self._strip_non_tool(response)
        self.assertIn("list_directory", result)
        self.assertIn("read_file", result)
        self.assertNotIn("Thinking", result)
        self.assertNotIn("Some text", result)
        self.assertNotIn("More text", result)


# ====================================================================
# Truncation Tests
# ====================================================================

class TestTruncation(unittest.TestCase):
    """Tests for tool result truncation."""

    def test_no_truncation_when_under_limit(self):
        """Content under limit should not be truncated."""
        content, was_truncated = truncate_tool_result("short content", 1000, "read_file")
        self.assertFalse(was_truncated)
        self.assertEqual(content, "short content")

    def test_truncation_when_over_limit(self):
        """Content over limit should be truncated."""
        long_content = "x" * 500
        content, was_truncated = truncate_tool_result(long_content, 100, "read_file")
        self.assertTrue(was_truncated)
        self.assertLess(len(content), len(long_content))
        self.assertIn("TRUNCATED", content)
        self.assertIn("showing first 100 of 500", content)

    def test_truncation_preserves_tail(self):
        """Truncated content preserves head + truncation notice (tail computed but not appended)."""
        long_content = "START " + "m" * 400 + " END"
        content, was_truncated = truncate_tool_result(long_content, 100, "read_file")
        self.assertTrue(was_truncated)
        # Should contain the head ("START")
        self.assertIn("START", content)
        # Should contain truncation notice
        self.assertIn("TRUNCATED", content)
        self.assertIn("showing first 100 of 410", content)

    def test_truncation_with_filter_hint(self):
        """Truncation should include filter hints for supported tools."""
        long_content = "x" * 500
        content, was_truncated = truncate_tool_result(long_content, 100, "list_directory")
        self.assertTrue(was_truncated)
        self.assertIn("TRUNCATED", content)
        self.assertIn("list_directory_deep", content)

    def test_truncation_no_hint_for_unsupported_tool(self):
        """Unsupported tools should not get filter hints."""
        long_content = "x" * 500
        content, was_truncated = truncate_tool_result(long_content, 100, "read_file")
        self.assertTrue(was_truncated)
        self.assertIn("TRUNCATED", content)
        self.assertNotIn("Try narrowing", content)

    def test_zero_limit_triggers_truncation(self):
        """Zero or negative limit should not truncate (bypass)."""
        content, was_truncated = truncate_tool_result("content", 0, "read_file")
        self.assertFalse(was_truncated)
        self.assertEqual(content, "content")

    def test_truncation_notice_guides_llm(self):
        """Truncation notice should tell LLM it can use more specific parameters."""
        long_content = "x" * 500
        content, was_truncated = truncate_tool_result(long_content, 100, "read_file")
        self.assertTrue(was_truncated)
        # The notice says "output was too long"
        self.assertIn("too long", content)


# ====================================================================
# task_completed Tool Execution Tests
# ====================================================================

class TestTaskCompletedTool(unittest.TestCase):
    """Tests for the task_completed tool."""

    def test_execute_with_summary(self):
        """task_completed should return a ToolResult with summary."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = TaskCompletedTool(tmpdir)
            r = tool.execute({'summary': 'Added divide function'})
            self.assertTrue(r.success)
            self.assertIn("Added divide function", r.content)
            # The summary field is prefixed with "Task completed: "
            self.assertIn("Added divide function", r.summary)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_empty_summary(self):
        """task_completed with empty summary should still succeed."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = TaskCompletedTool(tmpdir)
            r = tool.execute({'summary': ''})
            self.assertTrue(r.success)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_tool_is_registered(self):
        """task_completed should be in the tool registry."""
        from agent_engine.tools import ToolRegistry
        tmpdir = tempfile.mkdtemp()
        try:
            registry = ToolRegistry(tmpdir, enabled_tools=['task_completed'])
            tools = registry.list_tools()
            tool_names = [t['name'] for t in tools]
            self.assertIn('task_completed', tool_names)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# delete_file Verification Tests
# ====================================================================

class TestDeleteFileVerification(unittest.TestCase):
    """Tests for delete_file verification."""

    def test_delete_succeeds_and_verifies(self):
        """Successfully deleted file should pass verification."""
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'to_delete.txt')
            with open(test_file, 'w') as f:
                f.write('delete me')
            self.assertTrue(os.path.exists(test_file))

            tool = DeleteFileTool(tmpdir)
            r = tool.execute({'path': 'to_delete.txt'})
            self.assertTrue(r.success)
            self.assertFalse(os.path.exists(test_file))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_delete_nonexistent_file_fails(self):
        """Deleting a non-existent file should fail."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = DeleteFileTool(tmpdir)
            r = tool.execute({'path': 'does_not_exist.txt'})
            self.assertFalse(r.success)
            self.assertIn('not found', r.error.lower())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_delete_backup_file_blocked(self):
        """Backup files should not be deletable."""
        tmpdir = tempfile.mkdtemp()
        try:
            bak = os.path.join(tmpdir, 'backup.bak')
            with open(bak, 'w') as f:
                f.write('backup')
            tool = DeleteFileTool(tmpdir)
            r = tool.execute({'path': 'backup.bak'})
            self.assertFalse(r.success)
            self.assertIn('backup', r.error.lower())
            # File should still exist
            self.assertTrue(os.path.exists(bak))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Continuation Message Tests
# ====================================================================

class TestContinuationMessages(unittest.TestCase):
    """Tests for continuation message content."""

    def test_verbose_tool_format_in_continuation(self):
        """Continuation message should include verbose tool format reminder."""
        from app import _reconstruct_from_step_history
        # Mock engine with minimal attributes
        mock_engine = MagicMock()
        mock_engine.messages = [{"role": "system", "content": "System prompt"}]
        mock_engine.tools = MagicMock()
        mock_engine.tools.tool_names.return_value = ['list_directory', 'read_file', 'edit_file', 'write_file', 'delete_file', 'check_syntax']
        steps = [
            {'step': 1, 'tool': 'list_directory', 'params': {}, 'result': {'success': True, 'content': '[]'}},
        ]
        _reconstruct_from_step_history(mock_engine, steps, "Test instructions", is_continuation=True)
        # Find the user message with continuation
        self.assertIsNotNone(mock_engine.messages, "Messages should not be None")
        continuation = None
        for m in mock_engine.messages:
            if m.get('role') == 'user' and '[CONTINUATION]' in m.get('content', ''):
                continuation = m['content']
                break
        self.assertIsNotNone(continuation, "Continuation message not found")
        self.assertIn("TOOL FORMAT REMINDER", continuation)
        self.assertIn("=====================", continuation)
        self.assertIn("OPTION 1", continuation)
        self.assertIn("OPTION 2", continuation)
        self.assertIn("task_completed", continuation)
        self.assertIn("EXACTLY ONE", continuation)

    def test_continuation_includes_task_completed(self):
        """Continuation message should reference task_completed (not legacy [DONE])."""
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
# Conversation History Sanitization Tests
# ====================================================================

class TestConversationHistorySanitization(unittest.TestCase):
    """Tests for conversation history sanitization in the engine."""

    def test_parse_tool_calls_from_mixed_response(self):
        """parse_tool_calls should extract tools from mixed text."""
        response = (
            "I'll list the directory first.\n\n"
            "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]\n\n"
            "Then I'll read the files."
        )
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'list_directory')
        self.assertEqual(calls[0][1]['path'], '.')

    def test_parse_tool_calls_from_clean_response(self):
        """parse_tool_calls should work with clean tool call."""
        response = (
            "[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[TOOL_END]"
        )
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'read_file')

    def test_parse_tool_calls_no_tools(self):
        """parse_tool_calls should return empty list for text-only response."""
        response = "I'm thinking about what to do next..."
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 0)


# ====================================================================
# edit_file/write_file Verification Tests
# ====================================================================

class TestFileWriteVerification(unittest.TestCase):
    """Tests for write_file and edit_file verification."""

    def test_write_file_verification(self):
        """write_file should verify the file was written correctly."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = WriteFileTool(tmpdir)
            r = tool.execute({
                'path': 'verify_test.py',
                'content': 'def hello():\n    print("world")\n',
            })
            self.assertTrue(r.success)
            # Verify the content matches
            with open(os.path.join(tmpdir, 'verify_test.py')) as f:
                content = f.read()
            self.assertIn('def hello():', content)
            self.assertIn('print("world")', content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_edit_file_verification(self):
        """edit_file should verify the edit was applied correctly."""
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
        """edit_file should fail if original_text not found."""
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
# System Prompt Updates Tests
# ====================================================================

class TestSystemPromptUpdates(unittest.TestCase):
    """Tests for system prompt updates referencing task_completed."""

    def test_system_prompt_references_task_completed(self):
        """System prompt should reference task_completed (not legacy [DONE])."""
        from agent_engine.engine import build_system_prompt
        prompt = build_system_prompt(tools=[])
        self.assertIn('task_completed', prompt.lower())

    def test_user_prompt_references_task_completed(self):
        """User prompt should reference task_completed."""
        from agent_engine.engine import build_user_prompt
        prompt = build_user_prompt("Test task")
        self.assertIn('task_completed', prompt.lower())


if __name__ == '__main__':
    unittest.main()
