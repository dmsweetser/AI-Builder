"""Tests for the tool approval + resume flow.

These tests verify that when the agent calls create_tool and the user approves
the tool, the resumed engine properly continues the task using the approved
tool — instead of completing prematurely or re-doing work.

Run with:  pytest tests/test_tool_approval_flow.py -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock as mock
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_engine.engine import (
    AgentEngine, parse_tool_calls, is_done, _prefixed_markers,
    _strip_code_blocks,
)
from agent_engine.tools import get_registry, _reset_registry, ToolRegistry
from agent_engine.tools.base import ToolResult, BaseTool
from agent_engine.tools.task_completed import TaskCompletedTool
from agent_engine.tools.project_tool_loader import ProjectToolLoader


# ====================================================================
# Helpers
# ====================================================================

def _make_engine(tmpdir, max_steps=10, max_context_tokens=0,
                 max_tool_result_length=10000, instructions="Test"):
    """Helper to create an engine with standard config."""
    os.environ["AIB_OUTPUT_DIR"] = tmpdir
    os.environ["AIB_JOB_ID"] = "test-job"
    os.environ["AIB_MAX_STEPS"] = str(max_steps)
    os.environ["AIB_MAX_CONTEXT_TOKENS"] = str(max_context_tokens)
    os.environ["AIB_MAX_TOOL_RESULT_LENGTH"] = str(max_tool_result_length)
    return AgentEngine({
        "rootDirectory": tmpdir,
        "instructions": instructions,
        "custom_endpoint_url": "http://test",
        "custom_api_key": "test",
        "custom_model_name": "test",
        "custom_verify_ssl": False,
    }, output_dir=tmpdir)


def _make_tool_call_response(tool_name, params, prefix="", rationale=None):
    """Build a mock LLM response that the engine's parser WILL recognize.

    The engine's parse_tool_calls expects the format:
        [PREFIX_TOOL_START]
        [PREFIX_TOOL_NAME]
        tool_name
        [PREFIX_PARAM_NAME]
        key
        [PREFIX_PARAM_VALUE]
        value
        ...
        [PREFIX_TOOL_END]

    With rationale appended before TOOL_END if provided.
    """
    if prefix:
        ts, te, tn, pn, pv, rat = (
            f"[{prefix}_TOOL_START]", f"[{prefix}_TOOL_END]",
            f"[{prefix}_TOOL_NAME]", f"[{prefix}_PARAM_NAME]",
            f"[{prefix}_PARAM_VALUE]", f"[{prefix}_RATIONALE]",
        )
        actual_tool_name = f"{prefix}_{tool_name}"
    else:
        ts, te, tn, pn, pv, rat = (
            "[TOOL_START]", "[TOOL_END]", "[TOOL_NAME]",
            "[PARAM_NAME]", "[PARAM_VALUE]", "[RATIONALE]",
        )
        actual_tool_name = tool_name

    parts = [ts, tn, actual_tool_name]
    for k, v in params.items():
        parts.append(pn)
        parts.append(k)
        parts.append(pv)
        parts.append(v)
    if rationale:
        parts.append(rat)
        parts.append(rationale)
    parts.append(te)
    return "\n".join(parts)


# ====================================================================
# 1. create_tool returns pending_approval
# ====================================================================

class TestCreateToolPendingApproval(unittest.TestCase):
    """Verify that create_tool causes the engine to return pending_approval."""

    def test_create_tool_returns_pending_approval(self):
        tmpdir = tempfile.mkdtemp()
        try:
            engine = _make_engine(tmpdir, max_steps=10)
            prefix = engine.instance_prefix

            called_tools = []

            def mock_execute(tn, params, root_dir=None, project_output_dir="", disabled_tools=None):
                called_tools.append(tn)
                if tn == "create_tool":
                    pending_dir = os.path.join(project_output_dir, "tools", "pending")
                    os.makedirs(pending_dir, exist_ok=True)
                    tool_file = os.path.join(pending_dir, "my_tool.py")
                    with open(tool_file, 'w') as f:
                        f.write("# placeholder tool\n")
                    return ToolResult(
                        True,
                        "Tool 'my_tool' proposed for approval.",
                        summary="Tool 'my_tool' proposed for approval."
                    )
                return ToolResult(True, "", error=f"Unexpected tool: {tn}")

            engine.tools.execute = mock_execute

            engine.llm = MagicMock()
            engine.llm.call.return_value = {
                "content": _make_tool_call_response("create_tool", {
                    "name": "my_tool",
                    "description": "A test tool that does something useful for testing.",
                    "parameters": "{}",
                    "code": "# tool code",
                }, prefix),
                "raw_request": "", "raw_response": "",
            }

            with patch('agent_engine.engine._estimate_tokens', return_value=10):
                result = engine.run()

            self.assertEqual(result["status"], "pending_approval",
                f"Expected pending_approval, got {result['status']}. Called tools: {called_tools}")
            self.assertIn("create_tool", called_tools)

            pending_dir = os.path.join(tmpdir, "tools", "pending")
            self.assertTrue(os.path.exists(os.path.join(pending_dir, "my_tool.py")),
                "Tool file should be in pending/")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# 2. Resume WITHOUT step history (the bug)
# ====================================================================

class TestResumeWithoutStepHistory(unittest.TestCase):
    """Verify that resuming without step history causes the LLM to complete
    without using the approved tool (the bug behavior)."""

    def test_resumed_engine_without_history_completes_without_using_tool(self):
        """When the resumed engine has no step history, the LLM sees the
        approved tool in the system prompt but has no context about what
        was already done. It may call task_completed immediately.

        This demonstrates the BUG: the task is 'create a tool AND use it',
        but the resumed engine completes without using the tool.
        """
        tmpdir = tempfile.mkdtemp()
        try:
            # Step 1: Create the first engine and run it to create the tool
            engine1 = _make_engine(tmpdir, max_steps=10)
            prefix1 = engine1.instance_prefix

            all_called_tools = []

            def mock_execute1(tn, params, root_dir=None, project_output_dir="", disabled_tools=None):
                all_called_tools.append(tn)
                if tn == "create_tool":
                    pending_dir = os.path.join(project_output_dir, "tools", "pending")
                    os.makedirs(pending_dir, exist_ok=True)
                    tool_file = os.path.join(pending_dir, "my_tool.py")
                    with open(tool_file, 'w') as f:
                        f.write("# placeholder tool\n")
                    return ToolResult(
                        True, "Tool 'my_tool' proposed for approval.",
                        summary="Tool 'my_tool' proposed for approval."
                    )
                return ToolResult(True, "", error=f"Unexpected tool: {tn}")

            engine1.tools.execute = mock_execute1

            engine1.llm = MagicMock()
            engine1.llm.call.return_value = {
                "content": _make_tool_call_response("create_tool", {
                    "name": "my_tool",
                    "description": "A test tool that does something useful for testing.",
                    "parameters": "{}",
                    "code": "# tool code",
                }, prefix1),
                "raw_request": "", "raw_response": "",
            }

            with patch('agent_engine.engine._estimate_tokens', return_value=10):
                result1 = engine1.run()

            self.assertEqual(result1["status"], "pending_approval",
                "First engine should return pending_approval")
            self.assertIn("create_tool", all_called_tools)

            # Step 2: Simulate tool approval (move from pending to active)
            pending_dir = os.path.join(tmpdir, "tools", "pending")
            active_dir = os.path.join(tmpdir, "tools", "active")
            os.makedirs(active_dir, exist_ok=True)
            shutil.move(os.path.join(pending_dir, "my_tool.py"),
                        os.path.join(active_dir, "my_tool.py"))

            # Step 3: Create a NEW engine (simulating resume WITHOUT step history)
            engine2 = _make_engine(tmpdir, max_steps=10)
            prefix2 = engine2.instance_prefix

            # The LLM for the resumed engine: it sees the approved tool in the
            # system prompt but has NO context about what was already done.
            # It may just call task_completed because "create a tool" was done.
            engine2.llm = MagicMock()
            engine2.llm.call.return_value = {
                "content": _make_tool_call_response("task_completed", {
                    "summary": "Tool was created and is now approved.",
                }, prefix2),
                "raw_request": "", "raw_response": "",
            }

            def mock_execute2(tn, params, root_dir=None, project_output_dir="", disabled_tools=None):
                all_called_tools.append(tn)
                if tn == "task_completed":
                    return TaskCompletedTool(root_dir or tmpdir).execute(params)
                if tn == "my_tool":
                    return ToolResult(True, "my_tool executed successfully")
                return ToolResult(True, "", error=f"Unexpected tool: {tn}")

            engine2.tools.execute = mock_execute2

            with patch('agent_engine.engine._estimate_tokens', return_value=10):
                result2 = engine2.run()

            # THE BUG: The engine completed but NEVER used the approved tool
            self.assertEqual(result2["status"], "completed")
            self.assertNotIn("my_tool", all_called_tools,
                "BUG: The approved tool was NOT used — the engine completed "
                "without actually using the tool that was created.")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# 3. Resume WITH step history (the fix)
# ====================================================================

class TestResumeWithStepHistory(unittest.TestCase):
    """Verify that resuming WITH step history allows the LLM to properly
    continue the task using the approved tool."""

    def test_resumed_engine_with_history_uses_approved_tool(self):
        """When the resumed engine has step history, it can reconstruct
        the conversation and understand that the tool was created.
        The LLM should then use the tool instead of just completing.

        This verifies the FIX: with step history, the engine properly
        continues the task.
        """
        tmpdir = tempfile.mkdtemp()
        try:
            # Step 1: Create the first engine and run it to create the tool
            engine1 = _make_engine(tmpdir, max_steps=10)
            prefix1 = engine1.instance_prefix

            all_called_tools = []

            def mock_execute1(tn, params, root_dir=None, project_output_dir="", disabled_tools=None):
                all_called_tools.append(tn)
                if tn == "create_tool":
                    pending_dir = os.path.join(project_output_dir, "tools", "pending")
                    os.makedirs(pending_dir, exist_ok=True)
                    tool_file = os.path.join(pending_dir, "my_tool.py")
                    with open(tool_file, 'w') as f:
                        f.write("# placeholder tool\n")
                    return ToolResult(
                        True, "Tool 'my_tool' proposed for approval.",
                        summary="Tool 'my_tool' proposed for approval."
                    )
                return ToolResult(True, "", error=f"Unexpected tool: {tn}")

            engine1.tools.execute = mock_execute1

            engine1.llm = MagicMock()
            engine1.llm.call.return_value = {
                "content": _make_tool_call_response("create_tool", {
                    "name": "my_tool",
                    "description": "A test tool that does something useful for testing.",
                    "parameters": "{}",
                    "code": "# tool code",
                }, prefix1),
                "raw_request": "", "raw_response": "",
            }

            with patch('agent_engine.engine._estimate_tokens', return_value=10):
                result1 = engine1.run()

            self.assertEqual(result1["status"], "pending_approval")
            self.assertIn("create_tool", all_called_tools)

            # Simulate tool approval
            pending_dir = os.path.join(tmpdir, "tools", "pending")
            active_dir = os.path.join(tmpdir, "tools", "active")
            os.makedirs(active_dir, exist_ok=True)
            shutil.move(os.path.join(pending_dir, "my_tool.py"),
                        os.path.join(active_dir, "my_tool.py"))

            # Step 2: Get the step history from engine1
            step_history = engine1.step_history

            # Step 3: Create a NEW engine (simulating resume WITH step history)
            engine2 = _make_engine(tmpdir, max_steps=10)
            prefix2 = engine2.instance_prefix

            # The LLM for the resumed engine: it now has context from step history.
            # It should use the approved tool instead of just completing.
            engine2.llm = MagicMock()
            engine2.llm.call.return_value = {
                "content": _make_tool_call_response("my_tool", {}, prefix2,
                    rationale="The tool was already created and approved. Now I'll use it."),
                "raw_request": "", "raw_response": "",
            }

            def mock_execute2(tn, params, root_dir=None, project_output_dir="", disabled_tools=None):
                all_called_tools.append(tn)
                if tn == "task_completed":
                    return TaskCompletedTool(root_dir or tmpdir).execute(params)
                if tn == "my_tool":
                    return ToolResult(True, "my_tool executed successfully")
                return ToolResult(True, "", error=f"Unexpected tool: {tn}")

            engine2.tools.execute = mock_execute2

            # THE FIX: Pass prev_step_history to the resumed engine
            engine2.step_history = step_history
            engine2.step_count = len(step_history)

            with patch('agent_engine.engine._estimate_tokens', return_value=10):
                result2 = engine2.run()

            # The engine should have used the approved tool
            self.assertIn("my_tool", all_called_tools,
                "The approved tool should have been used after resume with step history")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# 4. Integration test: full approval flow via app.py
# ====================================================================

class TestAppApprovalFlow(unittest.TestCase):
    """Integration test that simulates the full approval flow through
    app.py's _find_project_and_resume_engine function."""

    def setUp(self):
        _reset_registry()

    def tearDown(self):
        _reset_registry()

    def test_find_project_and_resume_engine_loads_step_history(self):
        """_find_project_and_resume_engine should load step history from
        job_history and pass it to _run_engine_in_background."""
        from app import _find_project_and_resume_engine, job_history

        tmpdir = tempfile.mkdtemp()
        # Save original state and restore on exit
        original_job_history = list(job_history)
        original_projects_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             '..', 'aib_instance', 'projects')
        try:
            # Create a fake project
            project = {
                "id": "test-project-flow",
                "name": "Test Project Flow",
                "rootDirectory": tmpdir,
                "instructions": "Create and use a tool.",
                "output_dir": tmpdir,
                "run_number": 1,
                "last_job_id": "test-job-flow",
                "disabled_tools": [],
            }

            # Create the project file
            os.makedirs(original_projects_dir, exist_ok=True)
            project_file = os.path.join(original_projects_dir, "test-project-flow.json")
            with open(project_file, 'w') as f:
                json.dump(project, f)

            # Add a fake job history entry with step_history
            fake_step_history = [
                {
                    "step": 1,
                    "tool": "create_tool",
                    "params": {"name": "my_tool"},
                    "result": {"success": True, "content": "Tool proposed."},
                },
            ]

            # Patch _run_engine_in_background to capture its arguments
            captured_args = {}

            def capture_run_engine(*args, **kwargs):
                captured_args.update(kwargs)
                # Return a mock result to avoid actually running the engine
                return {"result": {"status": "completed", "steps": 0},
                        "engine": MagicMock()}

            # Replace job_history with only our test entry to avoid stale data
            job_history[:] = [{
                "job_id": "test-job-flow",
                "project_id": "test-project-flow",
                "project_name": "Test Project Flow",
                "status": "pending_approval",
                "instructions": "Create and use a tool.",
                "timestamp": "2026-01-01T00:00:00",
                "step_history": fake_step_history,
            }]

            with patch('app._run_engine_in_background', side_effect=capture_run_engine):
                _find_project_and_resume_engine(tmpdir, "my_tool")

            # Verify that prev_step_history was passed
            self.assertIn("prev_step_history", captured_args,
                "prev_step_history should be passed to _run_engine_in_background")
            self.assertIsNotNone(captured_args["prev_step_history"],
                "prev_step_history should not be None when job_history has entries")
            # Check that it contains the create_tool step
            tool_names = [s.get("tool") for s in captured_args["prev_step_history"]]
            self.assertIn("create_tool", tool_names,
                f"prev_step_history should contain the create_tool step. Got tools: {tool_names}")

            # Cleanup
            os.remove(project_file)

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            # Restore original job_history
            job_history[:] = original_job_history


if __name__ == '__main__':
    unittest.main()
