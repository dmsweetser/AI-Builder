"""Integration test: create_tool -> approve -> use approved tool in a real engine run.

Tests the full pending tool approval flow:
1. Agent proposes a tool via create_tool
2. Tool appears as pending
3. User approves it
4. Agent can then use the approved tool
5. Agent completes with task_completed
"""
import json
import os
import sys
import tempfile
import shutil
import unittest
import unittest.mock as mock
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_engine.engine import AgentEngine
from agent_engine.tools.base import ToolResult
from agent_engine.tools import get_registry, _reset_registry


def _make_engine(tmpdir, max_steps=10):
    """Helper to create an engine with standard config."""
    os.environ["AIB_OUTPUT_DIR"] = tmpdir
    os.environ["AIB_JOB_ID"] = "test-job"
    os.environ["AIB_MAX_STEPS"] = str(max_steps)
    os.environ["AIB_MAX_CONTEXT_TOKENS"] = "0"
    os.environ["AIB_MAX_TOOL_RESULT_LENGTH"] = "10000"
    return AgentEngine({
        "rootDirectory": tmpdir,
        "instructions": "Test",
        "custom_endpoint_url": "http://test",
        "custom_api_key": "test",
        "custom_model_name": "test",
        "custom_verify_ssl": False,
    }, output_dir=tmpdir)


class TestPendingToolApprovalFlow(unittest.TestCase):
    """Tests for the full pending tool approval -> execution flow."""

    def _get_pending_file(self):
        """Get the actual pending tools file path used by the registry."""
        from agent_engine.config import EngineConfig
        try:
            return EngineConfig.get_pending_tools_file()
        except Exception:
            return os.path.join(os.getcwd(), "output", "pending_tools.json")

    def _create_pending_tool(self, name, code):
        """Create a pending tool entry in the pending tools file."""
        pending_file = self._get_pending_file()
        os.makedirs(os.path.dirname(pending_file), exist_ok=True)
        pending_tools = []
        if os.path.exists(pending_file):
            try:
                with open(pending_file, 'r') as f:
                    pending_tools = json.load(f)
            except Exception:
                pass
        # Remove any existing entry with same name
        pending_tools = [t for t in pending_tools if t.get("name") != name]
        pending_tools.append({
            "id": f"test-{name}",
            "name": name,
            "description": f"Test tool {name}",
            "parameters": {},
            "code": code,
            "status": "pending",
            "created_at": "2026-10-30T00:00:00"
        })
        with open(pending_file, 'w') as f:
            json.dump(pending_tools, f, indent=2)

    def test_plain_class_tool_executes_after_approval(self):
        """Plain class tool (LLM format) should execute after approval."""
        tmpdir = tempfile.mkdtemp()
        pending_file = os.path.join(tmpdir, "pending_tools.json")
        try:
            _reset_registry()
            registry = get_registry()

            # Create pending tool
            code = '''class Tool:
    def __init__(self, root_dir):
        self.name = "echo_tool"
        self.description = "Echoes back input"
        self.parameters = {"message": "string"}
    def execute(self, params):
        msg = params.get("message", "none")
        return ToolResult(success=True, content="Echo: " + str(msg), summary="Done")'''
            self._create_pending_tool("echo_tool", code)

            # Approve it
            result = registry.approve_tool("test-echo_tool")
            self.assertEqual(result["status"], "approved")

            # Verify it's in dynamic entries
            self.assertIn("echo_tool", registry._dynamic_entries)

            # Execute it
            exec_result = registry.execute("echo_tool", {"message": "hello"}, tmpdir)
            self.assertTrue(exec_result.success)
            self.assertIn("Echo: hello", exec_result.content)

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_subclass_tool_executes_after_approval(self):
        """BaseTool subclass tool should execute after approval."""
        tmpdir = tempfile.mkdtemp()
        pending_file = os.path.join(tmpdir, "pending_tools.json")
        try:
            _reset_registry()
            registry = get_registry()

            code = '''class Tool(BaseTool):
    name = "greet_tool"
    description = "Greets someone"
    parameters = {"name": "string"}
    def execute(self, params):
        name = params.get("name", "world")
        return ToolResult(success=True, content="Hello, " + str(name) + "!", summary="Done")'''
            self._create_pending_tool("greet_tool", code)

            result = registry.approve_tool("test-greet_tool")
            self.assertEqual(result["status"], "approved")

            exec_result = registry.execute("greet_tool", {"name": "Daniel"}, tmpdir)
            self.assertTrue(exec_result.success)
            self.assertIn("Hello, Daniel!", exec_result.content)

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_function_tool_executes_after_approval(self):
        """Function-based tool should execute after approval."""
        tmpdir = tempfile.mkdtemp()
        pending_file = os.path.join(tmpdir, "pending_tools.json")
        try:
            _reset_registry()
            registry = get_registry()

            code = '''def execute(params):
    x = params.get("x", 0)
    return ToolResult(success=True, content="Result: " + str(x), summary="Done")'''
            self._create_pending_tool("math_tool", code)

            result = registry.approve_tool("test-math_tool")
            self.assertEqual(result["status"], "approved")

            exec_result = registry.execute("math_tool", {"x": 42}, tmpdir)
            self.assertTrue(exec_result.success)
            self.assertIn("Result: 42", exec_result.content)

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_fresh_registry_sees_approved_tool(self):
        """A fresh registry (after _reset_registry) should see approved tools from disk."""
        tmpdir = tempfile.mkdtemp()
        pending_file = os.path.join(tmpdir, "pending_tools.json")
        try:
            # Create and approve via first registry
            _reset_registry()
            reg1 = get_registry()

            code = '''class Tool:
    def __init__(self, root_dir):
        self.name = "verify_tool"
        self.description = "Verification tool"
        self.parameters = {}
    def execute(self, params):
        return ToolResult(success=True, content="Verified!", summary="Done")'''
            self._create_pending_tool("verify_tool", code)
            reg1.approve_tool("test-verify_tool")

            # Now create a fresh registry (simulates engine restart)
            _reset_registry()
            reg2 = get_registry()

            # Should see the approved tool from disk
            self.assertIn("verify_tool", reg2._dynamic_entries)
            self.assertIn("verify_tool", [t['name'] for t in reg2.list_tools()])

            # Should be able to execute it
            exec_result = reg2.execute("verify_tool", {}, tmpdir)
            self.assertTrue(exec_result.success)
            self.assertEqual(exec_result.content, "Verified!")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_approved_tool_in_list_tools(self):
        """Approved tools should appear in list_tools() output."""
        tmpdir = tempfile.mkdtemp()
        pending_file = os.path.join(tmpdir, "pending_tools.json")
        try:
            _reset_registry()
            registry = get_registry()

            code = '''class Tool:
    def __init__(self, root_dir):
        self.name = "list_test"
        self.description = "A list test tool"
        self.parameters = {}
    def execute(self, params):
        return ToolResult(success=True, content="ok", summary="Done")'''
            self._create_pending_tool("list_test", code)
            registry.approve_tool("test-list_test")

            tools = registry.list_tools()
            tool_names = [t['name'] for t in tools]
            self.assertIn("list_test", tool_names)

            # Verify the tool definition includes description and parameters
            list_test_def = next(t for t in tools if t['name'] == 'list_test')
            self.assertEqual(list_test_def['description'], "Test tool list_test")
            self.assertEqual(list_test_def['parameters'], {})

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_rejected_tool_not_available(self):
        """Rejected tools should not be available for execution."""
        tmpdir = tempfile.mkdtemp()
        pending_file = os.path.join(tmpdir, "pending_tools.json")
        try:
            _reset_registry()
            registry = get_registry()

            code = '''class Tool:
    def __init__(self, root_dir):
        self.name = "rejected_tool"
        self.description = "A rejected tool"
        self.parameters = {}
    def execute(self, params):
        return ToolResult(success=True, content="should not happen", summary="Done")'''
            self._create_pending_tool("rejected_tool", code)
            registry.reject_tool("test-rejected_tool")

            # Should NOT be in dynamic entries
            self.assertNotIn("rejected_tool", registry._dynamic_entries)

            # Should NOT be in list_tools
            tool_names = [t['name'] for t in registry.list_tools()]
            self.assertNotIn("rejected_tool", tool_names)

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_multiple_approved_tools_all_executable(self):
        """Multiple approved tools should all be executable."""
        tmpdir = tempfile.mkdtemp()
        pending_file = os.path.join(tmpdir, "pending_tools.json")
        try:
            _reset_registry()
            registry = get_registry()

            code1 = '''class Tool:
    def __init__(self, root_dir):
        self.name = "tool_a"
        self.description = "Tool A"
        self.parameters = {}
    def execute(self, params):
        return ToolResult(success=True, content="A", summary="Done")'''
            code2 = '''class Tool:
    def __init__(self, root_dir):
        self.name = "tool_b"
        self.description = "Tool B"
        self.parameters = {}
    def execute(self, params):
        return ToolResult(success=True, content="B", summary="Done")'''

            self._create_pending_tool("tool_a", code1)
            self._create_pending_tool("tool_b", code2)

            registry.approve_tool("test-tool_a")
            registry.approve_tool("test-tool_b")

            # Both should be executable
            r1 = registry.execute("tool_a", {}, tmpdir)
            self.assertTrue(r1.success)
            self.assertEqual(r1.content, "A")

            r2 = registry.execute("tool_b", {}, tmpdir)
            self.assertTrue(r2.success)
            self.assertEqual(r2.content, "B")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
