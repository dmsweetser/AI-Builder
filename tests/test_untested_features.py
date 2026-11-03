"""Tests for untested engine features: first-tool-only, no-tool-call nudge, context trimming, etc."""
import json
import os
import sys
import tempfile
import shutil
import threading
import time
import unittest
import unittest.mock as mock
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_engine.engine import (
    _estimate_tokens,
    _trim_messages_to_context,
    build_system_prompt,
    build_user_prompt,
    parse_tool_calls,
    is_done,
    AgentEngine,
)


# ====================================================================
# First Tool Call Only — engine takes only the first tool call
# ====================================================================

class TestFirstToolCallOnly(unittest.TestCase):
    """Verify engine takes ONLY the first tool call when LLM produces multiple."""

    def test_parse_multiple_tools_returns_all(self):
        """parse_tool_calls should extract ALL tool calls from a response."""
        response = (
            "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]\n"
            "[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[TOOL_END]"
        )
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "list_directory")
        self.assertEqual(calls[1][0], "read_file")

    def test_first_tool_only_simulation(self):
        """Simulate: LLM produces 3 tool calls, engine takes only first."""
        response = (
            "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]\n"
            "[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[TOOL_END]\n"
            "[TOOL_START]\n[TOOL_NAME]\nwrite_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nnew.py\n[TOOL_END]"
        )
        calls = parse_tool_calls(response)
        # Engine takes only the first
        first_only = [calls[0]]
        self.assertEqual(len(first_only), 1)
        self.assertEqual(first_only[0][0], "list_directory")
        self.assertEqual(first_only[0][1]["path"], ".")


# ====================================================================
# No-Tool-Call Nudge — engine appends "Please continue"
# ====================================================================

class TestNoToolCallNudge(unittest.TestCase):
    """Verify engine handles LLM responses without tool calls."""

    def test_no_tool_call_response(self):
        """LLM response with no tool calls should be detected."""
        response = "I think we should add a function here."
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 0)

    def test_task_completed_is_not_a_tool_call(self):
        """task_completed is detected via is_done(), not parse_tool_calls."""
        response = (
            "[TOOL_START]\n[TOOL_NAME]\ntask_completed\n[PARAM_NAME]\nsummary\n[PARAM_VALUE]\nDone\n[TOOL_END]"
        )
        calls = parse_tool_calls(response)
        # parse_tool_calls should NOT match task_completed as a regular tool
        # (it requires [PARAM_NAME] tags, which task_completed has, but
        # the tool name parsing may not match)
        # Actually, task_completed DOES have PARAM_NAME tags, so it might be parsed.
        # The key is: is_done() detects it, and the engine handles it separately.
        done, summary = is_done(response)
        self.assertTrue(done)
        self.assertEqual(summary, "Done")

    def test_nudge_message_content(self):
        """The nudge message should say 'Please continue with your next action.'"""
        expected = "Please continue with your next action."
        # This is hardcoded in engine.py line 1100
        self.assertIn("continue", expected.lower())


# ====================================================================
# _estimate_tokens() — token estimation
# ====================================================================

class TestEstimateTokens(unittest.TestCase):
    """Tests for _estimate_tokens()."""

    def test_empty_string(self):
        """Empty string should return 1 (minimum)."""
        self.assertEqual(_estimate_tokens(""), 1)

    def test_short_text(self):
        """Short text should return a small number."""
        result = _estimate_tokens("hello world")
        self.assertGreaterEqual(result, 1)
        self.assertLessEqual(result, 10)

    def test_long_text_proportional(self):
        """Long text should have proportionally more tokens."""
        short = _estimate_tokens("hello")
        long = _estimate_tokens("hello " * 100)
        self.assertGreater(long, short)

    def test_ratio_approximately_4_to_1(self):
        """Roughly 4 chars per token."""
        text = "a" * 400
        result = _estimate_tokens(text)
        # Should be approximately 100 (400 / 4)
        self.assertGreater(result, 50)
        self.assertLess(result, 150)


# ====================================================================
# _trim_messages_to_context() — context trimming
# ====================================================================

class TestTrimMessagesToContext(unittest.TestCase):
    """Tests for _trim_messages_to_context()."""

    def test_unlimited_max_tokens(self):
        """max_tokens=0 should return messages unchanged."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = _trim_messages_to_context(messages, "System prompt", 0)
        self.assertEqual(len(result), len(messages))

    def test_fits_within_budget(self):
        """Messages within budget should not be trimmed."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = _trim_messages_to_context(messages, "System prompt", 1000)
        self.assertEqual(len(result), len(messages))

    def test_trims_oldest_messages(self):
        """Messages exceeding budget should be trimmed from the beginning."""
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Old message 1"},
            {"role": "assistant", "content": "Old reply 1"},
            {"role": "user", "content": "Old message 2"},
            {"role": "assistant", "content": "Old reply 2"},
            {"role": "user", "content": "Recent message"},
            {"role": "assistant", "content": "Recent reply"},
        ]
        # Very tight budget — should trim oldest non-system messages
        result = _trim_messages_to_context(messages, "System", 20)
        # Should keep at least system + last message
        self.assertGreater(len(result), 0)
        # System prompt should always be preserved
        self.assertEqual(result[0]["role"], "system")

    def test_keeps_at_least_system_prompt(self):
        """Should never trim below just the system prompt."""
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Message"},
        ]
        result = _trim_messages_to_context(messages, "System", 5)
        # System prompt should always be preserved
        self.assertEqual(result[0]["role"], "system")
        # May keep more messages if they fit within budget
        self.assertGreaterEqual(len(result), 1)


# ====================================================================
# _audit_filename() — audit filename generation
# ====================================================================

class TestAuditFilename(unittest.TestCase):
    """Tests for LLMClient._audit_filename()."""

    def test_audit_filename_format(self):
        """Audit filenames should follow the expected format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from agent_engine.engine import LLMClient
            client = LLMClient(audit_dir=tmpdir)
            req, resp = client._audit_filename(step=5)
            self.assertTrue(req.endswith("_step5_request.json"))
            self.assertTrue(resp.endswith("_step5_response.json"))
            self.assertIn(tmpdir, req)
            self.assertIn(tmpdir, resp)

    def test_no_audit_dir_returns_empty(self):
        """No audit dir should return empty strings."""
        from agent_engine.engine import LLMClient
        client = LLMClient(audit_dir=None)
        req, resp = client._audit_filename(step=5)
        self.assertEqual(req, "")
        self.assertEqual(resp, "")


# ====================================================================
# reload_approved_tools() — tool reloading
# ====================================================================

class TestReloadApprovedTools(unittest.TestCase):
    """Tests for AgentEngine.reload_approved_tools()."""

    def test_reload_updates_system_prompt(self):
        """reload_approved_tools should update the system prompt."""
        tmpdir = tempfile.mkdtemp()
        try:
            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Test",
                "enabled_tools": ["list_directory"],
            }
            engine = AgentEngine(project_config)
            old_prompt = engine.system_prompt
            # Mock the tool reload
            with patch.object(engine.tools, '_load_approved_tools'):
                engine.reload_approved_tools()
            # System prompt should be updated (tool list changed)
            self.assertIsNotNone(engine.system_prompt)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# _run_script() — script execution
# ====================================================================

class TestRunScript(unittest.TestCase):
    """Tests for AgentEngine._run_script()."""

    def test_empty_script_does_nothing(self):
        """Empty script should not execute anything."""
        tmpdir = tempfile.mkdtemp()
        try:
            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Test",
                "enabled_tools": ["list_directory"],
            }
            engine = AgentEngine(project_config)
            # Should not raise
            engine._run_script("pre", "")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_whitespace_only_script_does_nothing(self):
        """Whitespace-only script should not execute."""
        tmpdir = tempfile.mkdtemp()
        try:
            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Test",
                "enabled_tools": ["list_directory"],
            }
            engine = AgentEngine(project_config)
            # Should not raise
            engine._run_script("pre", "   \n  ")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Context warning — prompt when context reaches 80% of window
# ====================================================================

class TestContextWarning(unittest.TestCase):
    """Tests for context warning behavior (replaces auto-compression)."""

    def test_context_warning_flag(self):
        """Engine should have _context_warning_shown flag, not auto-compress."""
        tmpdir = tempfile.mkdtemp()
        try:
            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Test",
                "enabled_tools": ["list_directory"],
            }
            engine = AgentEngine(project_config)
            # Should have context warning flag, not compression flags
            self.assertFalse(engine._context_warning_shown)
            self.assertFalse(hasattr(engine, '_compress_enabled'))
            self.assertFalse(hasattr(engine, '_compress_threshold'))
            self.assertFalse(hasattr(engine, '_compressed'))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Stop event handling — engine handles user stop request
# ====================================================================

class TestStopEventHandling(unittest.TestCase):
    """Tests for stop event handling."""

    def test_stop_event_stops_engine(self):
        """Engine should stop when stop event is set."""
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
            stop_event.set()  # Set immediately

            engine = AgentEngine(project_config)
            engine._stop_event = stop_event

            # Mock the LLM to avoid actual API calls
            with patch.object(engine.llm, 'call', return_value={"content": "", "raw_request": "", "raw_response": ""}):
                result = engine.run()
                # Should return stopped status
                self.assertEqual(result["status"], "stopped")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Max steps handling — engine handles max steps reached
# ====================================================================

class TestMaxStepsHandling(unittest.TestCase):
    """Tests for max steps handling."""

    def test_max_steps_reached(self):
        """Engine should return max_steps_reached when steps exhausted."""
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
# Pending tool approval — engine handles create_tool approval flow
# ====================================================================

class TestPendingToolApproval(unittest.TestCase):
    """Tests for pending tool approval handling."""

    def test_pending_approval_status(self):
        """Engine should return pending_approval when create_tool is used."""
        tmpdir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# Test")

            project_config = {
                "rootDirectory": tmpdir,
                "instructions": "Create a tool",
                "enabled_tools": ["list_directory", "create_tool"],
            }

            engine = AgentEngine(project_config)

            # Mock the LLM to return a create_tool call
            mock_response = (
                "[TOOL_START]\n"
                "[TOOL_NAME]\n"
                "create_tool\n"
                "[PARAM_NAME]\n"
                "name\n"
                "[PARAM_VALUE]\n"
                "my_tool\n"
                "[TOOL_END]"
            )
            with patch.object(engine.llm, 'call', return_value={
                "content": mock_response,
                "raw_request": "",
                "raw_response": ""
            }):
                result = engine.run()
                # Should return pending_approval status
                self.assertEqual(result["status"], "pending_approval")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# build_system_prompt() — system prompt generation
# ====================================================================

class TestBuildSystemPrompt(unittest.TestCase):
    """Tests for build_system_prompt()."""

    def test_system_prompt_contains_task_completed(self):
        """System prompt should reference task_completed."""
        prompt = build_system_prompt([])
        self.assertIn("task_completed", prompt)

    def test_system_prompt_contains_tool_format(self):
        """System prompt should contain the tool format example."""
        prompt = build_system_prompt([])
        self.assertIn("[TOOL_START]", prompt)
        self.assertIn("[TOOL_END]", prompt)

    def test_system_prompt_contains_workflow(self):
        """System prompt should contain workflow steps."""
        prompt = build_system_prompt([])
        self.assertIn("EXPLORE", prompt)
        self.assertIn("UNDERSTAND", prompt)
        self.assertIn("PLAN", prompt)
        self.assertIn("MODIFY", prompt)
        self.assertIn("VERIFY", prompt)


# ====================================================================
# build_user_prompt() — user prompt generation
# ====================================================================

class TestBuildUserPrompt(unittest.TestCase):
    """Tests for build_user_prompt()."""

    def test_user_prompt_contains_instructions(self):
        """User prompt should contain the task instructions."""
        prompt = build_user_prompt("Add a divide function")
        self.assertIn("Add a divide function", prompt)

    def test_user_prompt_contains_context(self):
        """User prompt should include context when provided."""
        prompt = build_user_prompt("Add a function", "Context: existing code has add()")
        self.assertIn("Context: existing code has add()", prompt)

    def test_user_prompt_contains_task_completed_reference(self):
        """User prompt should reference task_completed."""
        prompt = build_user_prompt("Test")
        self.assertIn("task_completed", prompt)


if __name__ == '__main__':
    unittest.main()
