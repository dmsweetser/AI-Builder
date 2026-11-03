"""Tests for Round 15: respond_to_user truncation fix, request_user_input display,
VIEW LIVE re-entry, tool approval resume, and queue behavior."""

import os
import sys
import json
import tempfile
import shutil
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agent_engine.tools import get_registry, _reset_registry


class TestRespondToUserNoTruncation(unittest.TestCase):
    """Verify respond_to_user and request_user_input are NOT truncated."""

    def setUp(self):
        _reset_registry()

    def tearDown(self):
        _reset_registry()

    def test_respond_to_user_not_in_truncation_filter(self):
        """respond_to_user should be excluded from truncation."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'agent_engine', 'engine.py')) as f:
            content = f.read()
        self.assertIn('tool_name not in ("respond_to_user", "request_user_input")', content)

    def test_request_user_input_not_in_truncation_filter(self):
        """request_user_input should be excluded from truncation."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'agent_engine', 'engine.py')) as f:
            content = f.read()
        self.assertIn('tool_name not in ("respond_to_user", "request_user_input")', content)


class TestPendingUserInputDisplay(unittest.TestCase):
    """Verify request_user_input shows full question in live view."""

    def test_sse_includes_question_field(self):
        """SSE pending_user_input event should include question field."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'app.py')) as f:
            content = f.read()
        self.assertIn('"question": ev.get("question"', content)

    def test_frontend_uses_question_text(self):
        """Frontend handlePendingUserInput should use questionText variable."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'static', 'site.js')) as f:
            content = f.read()
        self.assertIn('questionText', content)
        self.assertIn('data.question', content)


class TestViewLiveReEntry(unittest.TestCase):
    """Verify VIEW LIVE re-entry preserves formatting."""

    def test_load_job_history_uses_handle_agent_step(self):
        """loadJobHistory should reuse handleAgentStep for consistent formatting."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'static', 'site.js')) as f:
            content = f.read()
        # Both branches of loadJobHistory should use handleAgentStep
        self.assertIn('handleAgentStep(step, agentBox)', content)
        # Count occurrences — should be 2 (one per branch)
        count = content.count('handleAgentStep(step, agentBox)')
        self.assertGreaterEqual(count, 2, f"Expected >= 2 handleAgentStep calls in loadJobHistory, found {count}")


class TestToolApprovalResume(unittest.TestCase):
    """Verify tool approval triggers engine resume."""

    def test_engine_checks_tool_approved_file(self):
        """Engine should check for _tool_approved_resume.txt on each step."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'agent_engine', 'engine.py')) as f:
            content = f.read()
        self.assertIn('_tool_approved_resume', content)

    def test_engine_reloads_approved_tools_on_resume(self):
        """Engine should call reload_approved_tools() when tool approval detected."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'agent_engine', 'engine.py')) as f:
            content = f.read()
        # After the tool_approved_file check, should call reload_approved_tools
        self.assertIn('self.reload_approved_tools()', content)

    def test_approval_endpoint_writes_resume_file(self):
        """Approval endpoint should write _tool_approved_resume.txt."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'app.py')) as f:
            content = f.read()
        self.assertIn('_tool_approved_resume', content)


class TestQueueBehavior(unittest.TestCase):
    """Verify second project queues when another is running."""

    def test_queue_guards_exist(self):
        """app.py should have queue guards for running/queued projects."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'app.py')) as f:
            content = f.read()
        self.assertIn('is_running, is_queued, existing_job_id = get_concurrent_job_info', content)
        self.assertIn('if is_running:', content)
        self.assertIn('if is_queued:', content)

    def test_get_concurrent_job_info_returns_correct_values(self):
        """get_concurrent_job_info should return correct (running, queued, job_id)."""
        from app import get_concurrent_job_info
        # When nothing is running or queued
        is_running, is_queued, job_id = get_concurrent_job_info("nonexistent")
        self.assertFalse(is_running)
        self.assertFalse(is_queued)
        self.assertIsNone(job_id)


class TestInjectTextboxClears(unittest.TestCase):
    """Verify inject textbox clears after sending."""

    def test_inject_clears_on_error(self):
        """injectLiveInstruction should clear input on error."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'static', 'site.js')) as f:
            content = f.read()
        # Find the catch handler for inject
        catch_idx = content.find('Failed to inject instruction')
        self.assertGreater(catch_idx, 0, "Could not find inject error handler")
        snippet = content[catch_idx:catch_idx+200]
        self.assertIn("input.value = ''", snippet, "Input should be cleared on error")


class TestToolStartShowsDetails(unittest.TestCase):
    """Verify tool steps show actual content instead of 'THINKING'."""

    def test_handle_tool_start_shows_rationale(self):
        """handleToolStart should display rationale."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'static', 'site.js')) as f:
            content = f.read()
        self.assertIn('data.rationale', content)

    def test_handle_tool_start_shows_params(self):
        """handleToolStart should display tool parameters."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'static', 'site.js')) as f:
            content = f.read()
        self.assertIn('data.params && Object.keys(data.params).length', content)

    def test_handle_tool_start_no_longer_thinking(self):
        """handleToolStart should not show 'THINKING' text."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'static', 'site.js')) as f:
            content = f.read()
        # The old "⏳ Running:" text should be replaced with "🔧 tool_name"
        self.assertIn('🔧 ', content)
        self.assertNotIn('⏳ Running:', content)


class TestSSEQuestionForwarding(unittest.TestCase):
    """Verify the __pending_user_input__ SSE event also includes question."""

    def test_pending_user_input_status_event_includes_question(self):
        """The __pending_user_input__ event should include question field."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'app.py')) as f:
            content = f.read()
        # Find the __pending_user_input__ handler (engine returning pending_user_input status)
        idx = content.find('elif ev["type"] == "__pending_user_input__":')
        self.assertGreater(idx, 0)
        # The next 500 chars should contain the yield with question
        yield_section = content[idx:idx+500]
        self.assertIn('"question"', yield_section)


class TestToolApprovalEndpoint(unittest.TestCase):
    """Verify the approval endpoint properly handles the resume signal."""

    def test_approval_endpoint_writes_resume_file(self):
        """The approval endpoint should write a resume signal file."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'app.py')) as f:
            content = f.read()
        # Should have the resume file write in api_approve_tool
        approve_idx = content.find('def api_approve_tool')
        self.assertGreater(approve_idx, 0)
        approve_section = content[approve_idx:approve_idx+2000]
        self.assertIn('_tool_approved_resume', approve_section)


if __name__ == '__main__':
    unittest.main()
