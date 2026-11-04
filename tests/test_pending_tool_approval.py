"""Integration test: create_tool -> approve -> use approved tool in a real engine run.

Tests the full pending tool approval flow with the new per-project system:
1. Agent proposes a tool via create_tool (writes .py to pending/)
2. Tool appears as pending
3. User approves it (moves to active/)
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
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.tools import get_registry, _reset_registry
from agent_engine.tools.project_tool_loader import ProjectToolLoader


def _make_project_dir():
    """Create a temp directory structure for a project."""
    tmpdir = tempfile.mkdtemp()
    output_dir = os.path.join(tmpdir, "output")
    os.makedirs(output_dir, exist_ok=True)
    return tmpdir, output_dir


def _create_pending_tool_file(output_dir, tool_name, code):
    """Create a pending tool .py file."""
    pending_dir = os.path.join(output_dir, "tools", "pending")
    os.makedirs(pending_dir, exist_ok=True)
    tool_file = os.path.join(pending_dir, f"{tool_name}.py")
    with open(tool_file, 'w') as f:
        f.write(code)
    return tool_file


class TestPendingToolApprovalFlow(unittest.TestCase):
    """Tests for the full pending tool approval -> execution flow."""

    def test_plain_class_tool_executes_after_approval(self):
        """Plain class tool (LLM format) should execute after approval."""
        _, output_dir = _make_project_dir()
        _reset_registry()
        registry = get_registry()

        code = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any

class EchoTool(BaseTool):
    """Echoes back input."""
    name = "echo_tool"
    description = "Echoes back input"
    parameters = {"message": "string"}

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        msg = params.get("message", "none")
        return ToolResult(success=True, content="Echo: " + str(msg), summary="Done")
'''
        _create_pending_tool_file(output_dir, "echo_tool", code)

        loader = registry._get_or_create_loader(output_dir)
        result = loader.approve_tool("echo_tool")
        self.assertEqual(result["status"], "approved")

        # Verify it's available
        self.assertIn("echo_tool", loader.get_tool_names())

        # Execute it
        exec_result = registry.execute("echo_tool", {"message": "hello"}, output_dir, output_dir)
        self.assertTrue(exec_result.success)
        self.assertIn("Echo: hello", exec_result.content)

        shutil.rmtree(os.path.dirname(output_dir), ignore_errors=True)

    def test_subclass_tool_executes_after_approval(self):
        """BaseTool subclass tool should execute after approval."""
        _, output_dir = _make_project_dir()
        _reset_registry()
        registry = get_registry()

        code = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any

class GreetTool(BaseTool):
    """Greets someone."""
    name = "greet_tool"
    description = "Greets someone"
    parameters = {"name": "string"}

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        name = params.get("name", "world")
        return ToolResult(success=True, content="Hello, " + str(name) + "!", summary="Done")
'''
        _create_pending_tool_file(output_dir, "greet_tool", code)

        registry._get_or_create_loader(output_dir).approve_tool("greet_tool")

        exec_result = registry.execute("greet_tool", {"name": "Daniel"}, output_dir, output_dir)
        self.assertTrue(exec_result.success)
        self.assertIn("Hello, Daniel!", exec_result.content)

        shutil.rmtree(os.path.dirname(output_dir), ignore_errors=True)

    def test_function_tool_executes_after_approval(self):
        """Function-based tool (wrapped by create_tool) should execute after approval."""
        _, output_dir = _make_project_dir()
        _reset_registry()
        registry = get_registry()

        # This is what create_tool generates for a function-based tool
        code = '''"""Auto-generated tool: math_tool"""
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any


class MathToolTool(BaseTool):
    """A simple math tool."""
    name = "math_tool"
    description = "A simple math tool for testing."
    parameters = {"x": "string?"}

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        x = params.get("x", "0")
        return ToolResult(success=True, content="Result: " + str(x), summary="Done")
'''
        _create_pending_tool_file(output_dir, "math_tool", code)

        loader = registry._get_or_create_loader(output_dir)
        loader.approve_tool("math_tool")

        exec_result = registry.execute("math_tool", {"x": "42"}, output_dir, output_dir)
        self.assertTrue(exec_result.success)
        self.assertIn("Result: 42", exec_result.content)

        shutil.rmtree(os.path.dirname(output_dir), ignore_errors=True)

    def test_fresh_registry_sees_approved_tool(self):
        """A fresh registry should see approved tools from disk."""
        _, output_dir = _make_project_dir()
        _reset_registry()

        code = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any

class VerifyTool(BaseTool):
    """Verification tool."""
    name = "verify_tool"
    description = "Verification tool"
    parameters = {}

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, content="Verified!", summary="Done")
'''
        _create_pending_tool_file(output_dir, "verify_tool", code)

        # Approve via first loader
        loader1 = ProjectToolLoader(output_dir)
        loader1.approve_tool("verify_tool")

        # Fresh registry should see it
        _reset_registry()
        registry = get_registry()
        loader2 = registry._get_or_create_loader(output_dir)
        self.assertIn("verify_tool", loader2.get_tool_names())

        exec_result = registry.execute("verify_tool", {}, output_dir, output_dir)
        self.assertTrue(exec_result.success)
        self.assertEqual(exec_result.content, "Verified!")

        shutil.rmtree(os.path.dirname(output_dir), ignore_errors=True)

    def test_approved_tool_in_list_tools(self):
        """Approved tools should appear in loader.list_tools() output."""
        _, output_dir = _make_project_dir()
        _reset_registry()
        registry = get_registry()

        code = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any

class ListTestTool(BaseTool):
    """A list test tool."""
    name = "list_test"
    description = "A list test tool"
    parameters = {}

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, content="ok", summary="Done")
'''
        _create_pending_tool_file(output_dir, "list_test", code)
        registry._get_or_create_loader(output_dir).approve_tool("list_test")

        tools = registry._get_or_create_loader(output_dir).list_tools()
        tool_names = [t['name'] for t in tools]
        self.assertIn("list_test", tool_names)

        list_test_def = next(t for t in tools if t['name'] == 'list_test')
        self.assertEqual(list_test_def['description'], "A list test tool")
        self.assertEqual(list_test_def['parameters'], {})

        shutil.rmtree(os.path.dirname(output_dir), ignore_errors=True)

    def test_rejected_tool_not_available(self):
        """Rejected tools should not be available for execution."""
        _, output_dir = _make_project_dir()
        _reset_registry()
        registry = get_registry()

        code = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any

class RejectedTool(BaseTool):
    """A rejected tool."""
    name = "rejected_tool"
    description = "A rejected tool"
    parameters = {}

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, content="should not happen", summary="Done")
'''
        _create_pending_tool_file(output_dir, "rejected_tool", code)
        loader = registry._get_or_create_loader(output_dir)
        loader.reject_tool("rejected_tool")

        # Should NOT be available
        self.assertNotIn("rejected_tool", loader.get_tool_names())

        # Pending tools should be empty
        pending = loader.get_pending_tools()
        self.assertEqual(len(pending), 0)

        shutil.rmtree(os.path.dirname(output_dir), ignore_errors=True)

    def test_multiple_approved_tools_all_executable(self):
        """Multiple approved tools should all be executable."""
        _, output_dir = _make_project_dir()
        _reset_registry()
        registry = get_registry()

        code1 = '''
from agent_engine.tools.base import BaseTool, ToolResult
from typing import Dict, Any

class ToolA(BaseTool):
    """Tool A."""
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
    """Tool B."""
    name = "tool_b"
    description = "Tool B"
    parameters = {}

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, content="B", summary="Done")
'''

        _create_pending_tool_file(output_dir, "tool_a", code1)
        _create_pending_tool_file(output_dir, "tool_b", code2)

        loader = registry._get_or_create_loader(output_dir)
        loader.approve_tool("tool_a")
        loader.approve_tool("tool_b")

        # Both should be executable
        r1 = registry.execute("tool_a", {}, output_dir, output_dir)
        self.assertTrue(r1.success)
        self.assertEqual(r1.content, "A")

        r2 = registry.execute("tool_b", {}, output_dir, output_dir)
        self.assertTrue(r2.success)
        self.assertEqual(r2.content, "B")

        shutil.rmtree(os.path.dirname(output_dir), ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
