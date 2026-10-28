"""Tests for the tool creation and approval workflow."""
import json
import os
import sys
import tempfile
import shutil
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.tools import ToolRegistry
from agent_engine.tools.create_tool import CreateToolTool
from agent_engine.security import ToolError
from agent_engine import config as engine_config


def _get_pending_file_for_dir(test_dir):
    """Return the pending tools file path for a given test directory."""
    return os.path.join(test_dir, "output", "pending_tools.json")


class TestCreateToolTool(unittest.TestCase):
    """Tests for the create_tool tool that proposes new tools for approval."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_proposes_tool_and_creates_pending_file(self):
        """Proposing a tool should create a pending_tools.json entry."""
        pending_file = _get_pending_file_for_dir(self.test_dir)
        with mock.patch.object(engine_config.EngineConfig, 'get_pending_tools_file', return_value=pending_file):
            tool = CreateToolTool(self.test_dir)
            r = tool.execute({
                'name': 'test_greet',
                'description': 'A simple greeting tool that says hello.',
                'parameters': json.dumps({'name': 'string'}),
                'code': '# placeholder code',
            })
            self.assertTrue(r.success)
            self.assertIn('test_greet', r.summary)
            self.assertIn('approval', r.summary)
            self.assertTrue(os.path.exists(pending_file))
            with open(pending_file, 'r') as f:
                pending = json.load(f)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]['name'], 'test_greet')
            self.assertEqual(pending[0]['status'], 'pending')

    def test_invalid_tool_name_rejected(self):
        """Tool names must match the pattern ^[a-zA-Z_][a-zA-Z0-9_-]*$."""
        tool = CreateToolTool(self.test_dir)
        r = tool.execute({
            'name': 'bad-name!',
            'description': 'A tool with an invalid name.',
            'parameters': '{}',
            'code': '# code',
        })
        self.assertFalse(r.success)
        self.assertIn('name must match', r.error)

    def test_short_description_rejected(self):
        """Descriptions shorter than 10 characters should be rejected."""
        tool = CreateToolTool(self.test_dir)
        r = tool.execute({
            'name': 'short_desc',
            'description': 'Too short',
            'parameters': '{}',
            'code': '# code',
        })
        self.assertFalse(r.success)
        self.assertIn('at least 10 characters', r.error)

    def test_invalid_json_parameters_rejected(self):
        """Malformed parameter JSON should be rejected."""
        tool = CreateToolTool(self.test_dir)
        r = tool.execute({
            'name': 'bad_json',
            'description': 'A tool with bad JSON parameters.',
            'parameters': '{invalid json',
            'code': '# code',
        })
        self.assertFalse(r.success)
        self.assertIn('Invalid JSON', r.error)

    def test_empty_parameters_allowed(self):
        """Tools with no parameters should be allowed."""
        tool = CreateToolTool(self.test_dir)
        r = tool.execute({
            'name': 'no_params_tool',
            'description': 'A tool that takes no parameters.',
            'parameters': '',
            'code': '# code',
        })
        self.assertTrue(r.success)
        self.assertIn('no_params_tool', r.summary)


class TestToolRegistryDynamicLoading(unittest.TestCase):
    """Tests for dynamic tool registration from approved pending tools."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))
        self.pending_file = _get_pending_file_for_dir(self.test_dir)

    def _make_create_tool(self):
        return CreateToolTool(self.test_dir)

    def _get_registry(self):
        return ToolRegistry(self.test_dir)

    def test_pending_tools_not_in_registry(self):
        """A newly proposed tool should NOT be in the registry until approved."""
        with mock.patch.object(engine_config.EngineConfig, 'get_pending_tools_file', return_value=self.pending_file):
            self._make_create_tool().execute({
                'name': 'my_dynamic_tool',
                'description': 'A dynamically created tool for testing.',
                'parameters': json.dumps({'x': 'string'}),
                'code': 'class Tool(BaseTool):\n    name = "my_dynamic_tool"\n    description = "A test tool"\n    parameters = {"x": "string"}\n    def execute(self, params):\n        return ToolResult(True, f"Got {params.get(chr(120), chr(45))}")',
            })
            registry = self._get_registry()
            tools = registry.list_tools()
            tool_names = [t['name'] for t in tools]
            self.assertNotIn('my_dynamic_tool', tool_names)

    def test_approve_tool_registers_it(self):
        """Approving a tool should register it in the registry."""
        with mock.patch.object(engine_config.EngineConfig, 'get_pending_tools_file', return_value=self.pending_file):
            self._make_create_tool().execute({
                'name': 'approved_tool',
                'description': 'A tool that was approved.',
                'parameters': json.dumps({'value': 'string'}),
                'code': 'class Tool(BaseTool):\n    name = "approved_tool"\n    description = "An approved test tool"\n    parameters = {"value": "string"}\n    def execute(self, params):\n        return ToolResult(True, f"Value: {params.get(chr(118), chr(45))}")',
            })
            registry = self._get_registry()
            result = registry.approve_tool(
                [t for t in registry.get_pending_tools() if t['name'] == 'approved_tool'][0]['id']
            )
            self.assertEqual(result['status'], 'approved')
            registry2 = self._get_registry()
            tools = registry2.list_tools()
            tool_names = [t['name'] for t in tools]
            self.assertIn('approved_tool', tool_names)

    def test_reject_tool_removes_from_pending(self):
        """Rejecting a tool should mark it rejected and remove from pending."""
        with mock.patch.object(engine_config.EngineConfig, 'get_pending_tools_file', return_value=self.pending_file):
            self._make_create_tool().execute({
                'name': 'rejected_tool',
                'description': 'A tool that will be rejected.',
                'parameters': '{}',
                'code': '# rejected',
            })
            registry = self._get_registry()
            pending = registry.get_pending_tools()
            self.assertEqual(len(pending), 1)
            result = registry.reject_tool(pending[0]['id'])
            self.assertEqual(result['status'], 'rejected')
            pending_after = registry.get_pending_tools()
            self.assertEqual(len(pending_after), 0)

    def test_nonexistent_tool_id_returns_not_found(self):
        """Approving/rejecting a nonexistent tool ID should return not_found."""
        registry = self._get_registry()
        result = registry.approve_tool('nonexistent-id')
        self.assertEqual(result['status'], 'not_found')
        result = registry.reject_tool('nonexistent-id')
        self.assertEqual(result['status'], 'not_found')

    def test_get_pending_tools_returns_only_pending(self):
        """get_pending_tools should only return tools with status 'pending'."""
        with mock.patch.object(engine_config.EngineConfig, 'get_pending_tools_file', return_value=self.pending_file):
            self._make_create_tool().execute({
                'name': 'tool_a',
                'description': 'First tool.',
                'parameters': '{}',
                'code': '# a',
            })
            self._make_create_tool().execute({
                'name': 'tool_b',
                'description': 'Second tool.',
                'parameters': '{}',
                'code': '# b',
            })
            registry = self._get_registry()
            pending = registry.get_pending_tools()
            self.assertEqual(len(pending), 2)
            names = {t['name'] for t in pending}
            self.assertEqual(names, {'tool_a', 'tool_b'})

    def test_create_tool_in_built_in_tools(self):
        """create_tool should be in the list of built-in tools."""
        registry = self._get_registry()
        tools = registry.list_tools()
        tool_names = [t['name'] for t in tools]
        self.assertIn('create_tool', tool_names)


class TestToolRegistryNoExecutePython(unittest.TestCase):
    """Verify that execute_python is NOT in the registry."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_execute_python_not_registered(self):
        """execute_python should NOT be registered (replaced by create_tool)."""
        registry = ToolRegistry(self.test_dir)
        tools = registry.list_tools()
        tool_names = [t['name'] for t in tools]
        self.assertNotIn('execute_python', tool_names)


class TestCreateToolToolE2E(unittest.TestCase):
    """End-to-end test: propose -> approve -> execute dynamic tool."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))
        self.pending_file = _get_pending_file_for_dir(self.test_dir)

    def test_full_proposal_approval_lifecycle(self):
        """Propose a tool, approve it, verify it appears in the registry."""
        with mock.patch.object(engine_config.EngineConfig, 'get_pending_tools_file', return_value=self.pending_file):
            create_tool = CreateToolTool(self.test_dir)
            r = create_tool.execute({
                'name': 'e2e_greet_tool',
                'description': 'A greeting tool for end-to-end testing.',
                'parameters': json.dumps({'greeting': 'string', 'name': 'string'}),
                'code': (
                    'class Tool(BaseTool):\n'
                    '    name = "e2e_greet_tool"\n'
                    '    description = "Greets someone"\n'
                    '    parameters = {"greeting": "string", "name": "string"}\n'
                    '    def execute(self, params):\n'
                    '        return ToolResult(True, f"{params.get(chr(103),chr(45))}, {params.get(chr(110),chr(45))}")\n'
                ),
            })
            self.assertTrue(r.success)

            registry = self._get_registry()
            pending = registry.get_pending_tools()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]['name'], 'e2e_greet_tool')

            result = registry.approve_tool(pending[0]['id'])
            self.assertEqual(result['status'], 'approved')

            pending_after = registry.get_pending_tools()
            self.assertEqual(len(pending_after), 0)

            registry2 = self._get_registry()
            tools = registry2.list_tools()
            tool_names = [t['name'] for t in tools]
            self.assertIn('e2e_greet_tool', tool_names)

            tool_def = next(t for t in tools if t['name'] == 'e2e_greet_tool')
            self.assertEqual(tool_def['description'], 'Greets someone')
            self.assertEqual(tool_def['parameters'], {'greeting': 'string', 'name': 'string'})

    def _get_registry(self):
        return ToolRegistry(self.test_dir)


if __name__ == '__main__':
    unittest.main()
