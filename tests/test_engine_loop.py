"""Tests for engine loop behaviors not covered by existing test suites.

Covers:
- task_completed conclusion flow (engine breaks loop)
- context_warning SSE event emission
- request_user_input pause/resume flow
- tool result truncation in engine loop
- cleaned response in messages
- step_history append
- _step_callback invocation
- SSE event emission
- respond_to_user tool
- compress_context tool
- Engine loop edge cases
"""
import json
import os
import sys
import tempfile
import shutil
import unittest
import unittest.mock as mock
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_engine.engine import AgentEngine, build_system_prompt, build_user_prompt
from agent_engine.tools.respond_to_user import RespondToUserTool
from agent_engine.tools.compress_context import CompressContextTool
from agent_engine.tools.task_completed import TaskCompletedTool


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


def _mock_tool_execute(engine, tool_name, result_fn):
    """Patch engine.tools.execute to return a custom result for a tool."""
    original = engine.tools.execute
    def mock_execute(tn, params, root_dir=None):
        if tn == tool_name:
            return result_fn(params)
        return original(tn, params, root_dir)
    engine.tools.execute = mock_execute


# ====================================================================
# Engine Loop: task_completed Conclusion Flow
# ====================================================================

class TestTaskCompletedConclusion(unittest.TestCase):
    """Tests for task_completed conclusion flow in the engine loop."""

    def test_task_completed_breaks_loop_not_continues(self):
        """task_completed should break the loop, not continue to next step."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\ntask_completed\n[PARAM_NAME]\nsummary\n[PARAM_VALUE]\nDone\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["task_completed"])
            engine.llm = mock_llm
            _mock_tool_execute(engine, "task_completed",
                lambda p: TaskCompletedTool(tmpdir).execute(p))

            with patch('agent_engine.engine._estimate_tokens', return_value=10):
                result = engine.run()

            # Verify: result contains the summary
            self.assertEqual(result["status"], "completed")
            self.assertIn("Done", result.get("summary", ""))

            # Verify: step_history has task_completed entry (llm_call is also recorded)
            step_tools = [s["tool"] for s in engine.step_history]
            self.assertIn("task_completed", step_tools)
            # The last step should be task_completed (loop broke)
            self.assertEqual(step_tools[-1], "task_completed")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_task_completed_includes_rationale_in_step_history(self):
        """task_completed step should include rationale if present."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\ntask_completed\n[PARAM_NAME]\nsummary\n[PARAM_VALUE]\nDone\n[RATIONALE]\nI verified all changes\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["task_completed"])
            engine.llm = mock_llm
            _mock_tool_execute(engine, "task_completed",
                lambda p: TaskCompletedTool(tmpdir).execute(p))

            with patch('agent_engine.engine._estimate_tokens', return_value=10):
                result = engine.run()

            # Verify rationale is in step_history
            tc_steps = [s for s in engine.step_history if s["tool"] == "task_completed"]
            self.assertTrue(len(tc_steps) > 0)
            self.assertIn("rationale", tc_steps[0])
            self.assertIn("verified all changes", tc_steps[0]["rationale"].lower())

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_task_completed_appends_completion_message(self):
        """task_completed should append [COMPLETION] message to history."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\ntask_completed\n[PARAM_NAME]\nsummary\n[PARAM_VALUE]\nAll changes done\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["task_completed"])
            engine.llm = mock_llm
            _mock_tool_execute(engine, "task_completed",
                lambda p: TaskCompletedTool(tmpdir).execute(p))

            with patch('agent_engine.engine._estimate_tokens', return_value=10):
                result = engine.run()

            # Verify [COMPLETION] message was appended
            completion_found = False
            for m in engine.messages:
                if m.get("role") == "user" and "[COMPLETION]" in m.get("content", ""):
                    completion_found = True
                    self.assertIn("All changes done", m["content"])
            self.assertTrue(completion_found, "[COMPLETION] message not found in messages")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Engine Loop: context_warning SSE Event
# ====================================================================

class TestContextWarningEvent(unittest.TestCase):
    """Tests for context_warning SSE event emission."""

    def test_context_warning_emitted_at_80_percent(self):
        """context_warning should be emitted when context reaches 80%."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["list_directory"],
                max_context_tokens=100)
            engine.llm = mock_llm

            events = []
            def track_callback(event):
                events.append(event)
            engine._step_callback = track_callback

            def mock_estimate(text):
                return 90

            with patch('agent_engine.engine._estimate_tokens', side_effect=mock_estimate):
                result = engine.run()

            # Verify context_warning event was emitted
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
        """context_warning should only be emitted once per run."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["list_directory"],
                max_context_tokens=100)
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
        """context_warning should add a user message prompting compress_context."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["list_directory"],
                max_context_tokens=100)
            engine.llm = mock_llm

            def mock_estimate(text):
                return 90

            with patch('agent_engine.engine._estimate_tokens', side_effect=mock_estimate):
                result = engine.run()

            warning_msg_found = False
            for m in engine.messages:
                if m.get("role") == "user" and "[CONTEXT WARNING]" in m.get("content", ""):
                    warning_msg_found = True
                    self.assertIn("compress_context", m["content"])
                    self.assertIn("tokens", m["content"])
            self.assertTrue(warning_msg_found, "[CONTEXT WARNING] message not found in messages")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Engine Loop: request_user_input Pause/Resume
# ====================================================================

class TestRequestUserInputPause(unittest.TestCase):
    """Tests for request_user_input pause/resume flow."""

    def test_request_user_input_returns_pending_status(self):
        """request_user_input should return pending_user_input status."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\nrequest_user_input\n[PARAM_NAME]\nquestion\n[PARAM_VALUE]\nWhat is your name?\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["request_user_input"])
            engine.llm = mock_llm

            result = engine.run()

            self.assertEqual(result["status"], "pending_user_input")
            self.assertIn("question", result)
            self.assertIn("What is your name?", result["question"])

            # Verify: user_input_request.txt was written (engine writes plain text)
            question_file = os.path.join(tmpdir, "user_input_request.txt")
            self.assertTrue(os.path.exists(question_file))
            with open(question_file) as f:
                self.assertEqual(f.read(), "What is your name?")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_request_user_input_emits_pending_user_input_event(self):
        """request_user_input should emit pending_user_input SSE event."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\nrequest_user_input\n[PARAM_NAME]\nquestion\n[PARAM_VALUE]\nPlease confirm\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["request_user_input"])
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


# ====================================================================
# Engine Loop: Tool Result Truncation in Messages
# ====================================================================

class TestToolResultTruncation(unittest.TestCase):
    """Tests for tool result truncation in the engine loop."""

    def test_tool_result_truncated_before_fed_to_llm(self):
        """Tool results should be truncated before being added to messages."""
        tmpdir = tempfile.mkdtemp()
        try:
            # Create a large file to ensure list_directory returns a large result
            large_file = os.path.join(tmpdir, "large.txt")
            with open(large_file, 'w') as f:
                f.write("x" * 200)

            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["list_directory"], max_tool_result_length=50)
            engine.llm = mock_llm

            result = engine.run()

            # Verify: tool result was truncated in step_history
            list_steps = [s for s in engine.step_history if s["tool"] == "list_directory"]
            self.assertTrue(len(list_steps) > 0)
            # The result should be marked as truncated
            self.assertTrue(list_steps[0]["result"].get("truncated", False),
                f"Tool result should be truncated, got: {list_steps[0]['result']['content'][:100]}")
            # The truncated content should contain a TRUNCATED notice
            self.assertIn("TRUNCATED", list_steps[0]["result"]["content"])

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_tool_result_not_truncated_when_under_limit(self):
        """Tool results under the limit should not be truncated."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["list_directory"],
                max_tool_result_length=10000)
            engine.llm = mock_llm

            result = engine.run()

            list_steps = [s for s in engine.step_history if s["tool"] == "list_directory"]
            self.assertTrue(len(list_steps) > 0)
            self.assertFalse(list_steps[0]["result"].get("truncated", False))

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Engine Loop: Cleaned Response in Messages
# ====================================================================

class TestCleanedResponse(unittest.TestCase):
    """Tests for cleaned response handling in the engine loop."""

    def test_cleaned_response_appended_to_messages(self):
        """Cleaned tool response should be appended to messages."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "Let me think...\n\n[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]\n\nDone thinking.",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["list_directory"])
            engine.llm = mock_llm

            result = engine.run()

            assistant_msgs = [m for m in engine.messages if m.get("role") == "assistant"]
            self.assertTrue(len(assistant_msgs) > 0, "No assistant messages found")
            # Should contain the tool block, not the stray text
            self.assertIn("[TOOL_START]", assistant_msgs[0]["content"])
            self.assertNotIn("Let me think", assistant_msgs[0]["content"])
            self.assertNotIn("Done thinking", assistant_msgs[0]["content"])

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Engine Loop: step_history Append
# ====================================================================

class TestStepHistory(unittest.TestCase):
    """Tests for step_history tracking in the engine loop."""

    def test_step_history_appended_for_each_step(self):
        """step_history should be appended for each step."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.side_effect = [
                {
                    "content": "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
                    "raw_request": "", "raw_response": "",
                },
                {
                    "content": "[TOOL_START]\n[TOOL_NAME]\ntask_completed\n[PARAM_NAME]\nsummary\n[PARAM_VALUE]\nDone\n[TOOL_END]",
                    "raw_request": "", "raw_response": "",
                },
            ]

            engine = _make_engine(tmpdir, ["list_directory", "task_completed"])
            engine.llm = mock_llm
            _mock_tool_execute(engine, "task_completed",
                lambda p: TaskCompletedTool(tmpdir).execute(p))

            result = engine.run()

            # Verify: step_history has task_completed entry
            step_tools = [s["tool"] for s in engine.step_history]
            self.assertIn("list_directory", step_tools)
            self.assertIn("task_completed", step_tools)
            # task_completed should be the last step
            self.assertEqual(step_tools[-1], "task_completed")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Engine Loop: _step_callback Invocation
# ====================================================================

class TestStepCallback(unittest.TestCase):
    """Tests for _step_callback invocation in the engine loop."""

    def test_step_callback_invoked_for_each_step(self):
        """_step_callback should be invoked for each step."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["list_directory"])
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


# ====================================================================
# respond_to_user Tool Tests
# ====================================================================

class TestRespondToUserTool(unittest.TestCase):
    """Tests for the respond_to_user tool."""

    def test_execute_returns_message(self):
        """respond_to_user should return the message as content."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = RespondToUserTool(tmpdir)
            r = tool.execute({"message": "Hello, world!"})
            self.assertTrue(r.success)
            self.assertIn("Hello, world!", r.content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_empty_message(self):
        """respond_to_user with empty message should still succeed."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = RespondToUserTool(tmpdir)
            r = tool.execute({"message": ""})
            self.assertTrue(r.success)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_tool_is_registered(self):
        """respond_to_user should be in the tool registry."""
        from agent_engine.tools import get_registry
        tmpdir = tempfile.mkdtemp()
        try:
            registry = get_registry(tmpdir)
            tools = registry.list_tools()
            tool_names = [t['name'] for t in tools]
            self.assertIn('respond_to_user', tool_names)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# compress_context Tool Tests
# ====================================================================

class TestCompressContextTool(unittest.TestCase):
    """Tests for the compress_context tool."""

    def test_execute_returns_compression_message(self):
        """compress_context should return a compression message."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = CompressContextTool(tmpdir)
            r = tool.execute({"summary": "Prior steps summarized"})
            self.assertTrue(r.success)
            self.assertIn("compressed", r.content.lower())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_tool_is_registered(self):
        """compress_context should be in the tool registry."""
        from agent_engine.tools import get_registry
        tmpdir = tempfile.mkdtemp()
        try:
            registry = get_registry(tmpdir)
            tools = registry.list_tools()
            tool_names = [t['name'] for t in tools]
            self.assertIn('compress_context', tool_names)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Engine Loop: Edge Cases
# ====================================================================

class TestEngineLoopEdgeCases(unittest.TestCase):
    """Edge case tests for the engine loop."""

    def test_tool_error_does_not_crash_engine(self):
        """Tool execution error should not crash the engine."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\nunknown_tool_xyz\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["unknown_tool_xyz"])
            engine.llm = mock_llm

            # Should not raise an exception
            result = engine.run()

            # Should complete (tool error is handled)
            self.assertIn(result["status"], ["completed", "error", "max_steps_reached"])

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_max_steps_reached_returns_correct_status(self):
        """Engine should return max_steps_reached when max_steps is exhausted."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["list_directory"], max_steps=2)
            engine.llm = mock_llm

            result = engine.run()

            self.assertEqual(result["status"], "max_steps_reached")
            self.assertEqual(result["steps"], 2)

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_tool_call_nudge_added(self):
        """When LLM returns no tool call, a nudge should be added to messages."""
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

            # Verify nudge message was added
            nudge_found = False
            for m in engine.messages:
                if m.get("role") == "user" and "Please continue" in m.get("content", ""):
                    nudge_found = True
            self.assertTrue(nudge_found, "Nudge message not found in messages")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_context_warning_not_emitted_when_max_context_zero(self):
        """context_warning should not be emitted when max_context_tokens is 0."""
        tmpdir = tempfile.mkdtemp()
        try:
            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "content": "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
                "raw_request": "", "raw_response": "",
            }

            engine = _make_engine(tmpdir, ["list_directory"], max_context_tokens=0)
            engine.llm = mock_llm

            events = []
            def track_callback(event):
                events.append(event)
            engine._step_callback = track_callback

            def mock_estimate(text):
                return 99999  # Would trigger warning if max_context > 0

            with patch('agent_engine.engine._estimate_tokens', side_effect=mock_estimate):
                result = engine.run()

            warning_events = [e for e in events if e.get("type") == "context_warning"]
            self.assertEqual(len(warning_events), 0)

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
