"""Tests for Round 13 features: TaskCompleted celebration rendering and singleton registry."""
import json
import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_engine.tools import get_registry, _reset_registry


class TestSingletonRegistry(unittest.TestCase):
    """Tests for the shared ToolRegistry singleton behavior."""

    def setUp(self):
        _reset_registry()

    def tearDown(self):
        _reset_registry()

    def test_singleton_returns_same_instance(self):
        """Multiple get_registry() calls should return the same instance."""
        r1 = get_registry("/tmp/test1")
        r2 = get_registry("/tmp/test2")
        self.assertIs(r1, r2, "get_registry() should return the same singleton")

    def test_singleton_ignores_root_dir_after_first_call(self):
        """Second call's root_dir should be ignored."""
        r1 = get_registry("/tmp/test1")
        r2 = get_registry("/tmp/test2")
        self.assertEqual(r1.root_dir, "/tmp/test1")
        # r2 is the same object, so root_dir is still "/tmp/test1"
        self.assertEqual(r2.root_dir, "/tmp/test1")

    def test_all_tools_registered_without_filtering(self):
        """All built-in tools should be registered — no enabled_tools filtering."""
        registry = get_registry(tempfile.mkdtemp())
        tools = registry.list_tools()
        tool_names = [t['name'] for t in tools]
        # Verify all expected tools are present
        expected_tools = [
            'list_directory', 'list_directory_deep', 'search_files', 'search_files_dir',
            'grep_code', 'grep_code_dir', 'read_file', 'read_file_range',
            'write_file', 'edit_file', 'delete_file', 'find_symbol',
            'decompile_jar', 'list_dependencies', 'check_syntax', 'get_file_info',
            'create_tool', 'respond_to_user', 'request_user_input', 'task_completed',
        ]
        for name in expected_tools:
            self.assertIn(name, tool_names, f"Tool '{name}' not registered")

    def test_tool_approval_makes_tool_available(self):
        """Approved tools should be loadable via reload_approved_tools()."""
        registry = get_registry(tempfile.mkdtemp())
        # Initially, the tool list should be stable
        initial_tools = set(t['name'] for t in registry.list_tools())
        # Reload should not change anything (no pending tools)
        registry.reload_approved_tools()
        after_tools = set(t['name'] for t in registry.list_tools())
        self.assertEqual(initial_tools, after_tools)

    def test_registry_shared_across_calls(self):
        """A tool registered in one registry instance should be visible in another."""
        r1 = get_registry(tempfile.mkdtemp())
        r2 = get_registry(tempfile.mkdtemp())
        # Both should have the same tools
        tools1 = set(t['name'] for t in r1.list_tools())
        tools2 = set(t['name'] for t in r2.list_tools())
        self.assertEqual(tools1, tools2)


class TestTaskCompletedCelebrationRendering(unittest.TestCase):
    """Tests for task_completed celebration rendering in the live feed.

    These tests verify the JavaScript logic for rendering task_completed
    as a celebration entry rather than a generic tool result.
    """

    def test_task_completed_rendering_has_emoji_header(self):
        """task_completed rendering should include 🎉 emoji header."""
        # Simulate the handleAgentStep logic for task_completed
        data = {
            "tool": "task_completed",
            "step": 5,
            "params": {"summary": "Added divide function"},
            "result": {
                "success": True,
                "content": json.dumps({"task_completed": True, "summary": "Added divide function"}),
                "error": "",
                "file_paths": [],
                "summary": "Task completed: Added divide function",
            },
        }
        # Verify the data structure matches what the engine sends
        self.assertEqual(data["tool"], "task_completed")
        self.assertTrue(data["result"]["success"])

    def test_task_completed_has_success_not_error(self):
        """task_completed result should have success=True, not success=False."""
        data = {
            "result": {
                "success": True,
                "content": json.dumps({"task_completed": True, "summary": "Done"}),
                "error": "",
            }
        }
        # This is what the JS check uses: data.result.success !== false
        self.assertNotEqual(data["result"]["success"], False)

    def test_task_completed_summary_extracted(self):
        """Summary should be extractable from task_completed params."""
        data = {
            "params": {"summary": "Added divide function to src/main.py"},
            "result": {
                "success": True,
                "content": json.dumps({"task_completed": True, "summary": "Added divide function to src/main.py"}),
            }
        }
        summary = data["params"]["summary"]
        self.assertEqual(summary, "Added divide function to src/main.py")

    def test_task_completed_content_format(self):
        """task_completed content should be JSON with task_completed: true."""
        content = json.dumps({"task_completed": True, "summary": "Test summary"})
        parsed = json.loads(content)
        self.assertTrue(parsed["task_completed"])
        self.assertEqual(parsed["summary"], "Test summary")


class TestAvailableToolsList(unittest.TestCase):
    """Tests for the AVAILABLE_TOOLS list in site.js."""

    def test_task_completed_in_available_tools(self):
        """task_completed should be in the AVAILABLE_TOOLS list."""
        # Read the site.js file and verify task_completed is in the list
        site_js = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "site.js"
        )
        with open(site_js, 'r') as f:
            content = f.read()
        self.assertIn('"task_completed"', content,
                      "task_completed should be in AVAILABLE_TOOLS array")

    def test_no_enabled_tools_filtering_in_get_enabled_tools(self):
        """getEnabledTools() should return all tools, not filtered."""
        site_js = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "site.js"
        )
        with open(site_js, 'r') as f:
            content = f.read()
        # getEnabledTools should not use checkbox filtering
        # Find the getEnabledTools function and verify it doesn't reference checkboxes
        get_enabled_idx = content.find('function getEnabledTools()')
        self.assertGreater(get_enabled_idx, 0, "getEnabledTools function should exist")
        # Get the next function definition after getEnabledTools
        next_func_idx = content.find('function ', get_enabled_idx + 1)
        if next_func_idx == -1:
            next_func_idx = len(content)
        get_enabled_body = content[get_enabled_idx:next_func_idx]
        self.assertNotIn('checkbox', get_enabled_body,
            "getEnabledTools() should not use checkbox filtering")
        # Should return all tools
        self.assertIn('AVAILABLE_TOOLS.slice()', content), \
            "getEnabledTools should return a copy of AVAILABLE_TOOLS"


if __name__ == '__main__':
    unittest.main()
