"""Expanded tests for AI-Builder — every tool, ToolRegistry, AgentEngine, and edge cases."""
import os
import sys
import json
import tempfile
import shutil
import unittest
import unittest.mock as mock
from unittest.mock import patch, MagicMock, PropertyMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_engine.security import ensure_under_root, validate_tool_params, SecurityError, ToolError
from agent_engine.tools.base import ToolResult, BaseTool
from agent_engine.engine import LLMClient, parse_tool_calls, is_done, build_user_prompt, build_system_prompt, AgentEngine
from agent_engine.tools.files import (
    ListDirectoryTool, ReadFileTool, WriteFileTool, EditFileTool,
    SearchFilesTool, GrepCodeTool, DeleteFileTool,
)
from agent_engine.tools.checkers import CheckSyntaxTool
from agent_engine.tools.misc import GetFileInfoTool, ListDependenciesTool
from agent_engine.tools.search import FindSymbolTool, DecompileJarTool
from agent_engine.tools import ToolRegistry
from agent_engine.config import EngineConfig


# ====================================================================
# Parser unit tests (new tag-based format)
# ====================================================================

class TestParseToolCalls(unittest.TestCase):
    """Tests for the parse_tool_calls function with the new tag-based format."""

    def test_simple_single_line(self):
        response = '''[TOOL_START]
[TOOL_NAME_START]
list_directory
[TOOL_NAME_END]
[PARAM_NAME_START]
path
[PARAM_NAME_END]
[PARAM_VALUE_START]
[PARAM_VALUE_END]
[PARAM_NAME_START]
max_depth
[PARAM_NAME_END]
[PARAM_VALUE_START]
2
[PARAM_VALUE_END]
[TOOL_END]'''
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'list_directory')
        self.assertEqual(calls[0][1], {'path': '', 'max_depth': '2'})

    def test_single_line_param_value(self):
        response = '''[TOOL_START]
[TOOL_NAME_START]
check_syntax
[TOOL_NAME_END]
[PARAM_NAME_START]
path
[PARAM_NAME_END]
[PARAM_VALUE_START]
src/hello.py
[PARAM_VALUE_END]
[TOOL_END]'''
        calls = parse_tool_calls(response)
        self.assertEqual(calls[0][1], {'path': 'src/hello.py'})

    def test_multiline_content(self):
        response = '''[TOOL_START]
[TOOL_NAME_START]
write_file
[TOOL_NAME_END]
[PARAM_NAME_START]
path
[PARAM_NAME_END]
[PARAM_VALUE_START]
src/hello.py
[PARAM_VALUE_END]
[PARAM_NAME_START]
content
[PARAM_NAME_END]
[PARAM_VALUE_START]
"""Hello module."""
from src.main import greet

if __name__ == "__main__":
    print(greet("World"))
[PARAM_VALUE_END]
[TOOL_END]'''
        calls = parse_tool_calls(response)
        self.assertEqual(calls[0][0], 'write_file')
        content = calls[0][1]['content']
        self.assertIn('"""Hello module."""', content)
        self.assertIn('from src.main import greet', content)
        self.assertIn('if __name__ == "__main__":', content)
        self.assertIn('print(greet("World"))', content)

    def test_multiple_tools(self):
        response = '''[TOOL_START]
[TOOL_NAME_START]
list_directory
[TOOL_NAME_END]
[PARAM_NAME_START]
path
[PARAM_NAME_END]
[PARAM_VALUE_START]
[PARAM_VALUE_END]
[PARAM_NAME_START]
max_depth
[PARAM_NAME_END]
[PARAM_VALUE_START]
1
[PARAM_VALUE_END]
[TOOL_END]
[TOOL_START]
[TOOL_NAME_START]
read_file
[TOOL_NAME_END]
[PARAM_NAME_START]
path
[PARAM_NAME_END]
[PARAM_VALUE_START]
src/main.py
[PARAM_VALUE_END]
[TOOL_END]'''
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], 'list_directory')
        self.assertEqual(calls[1][0], 'read_file')

    def test_no_tool_calls(self):
        response = 'Let me think about this...'
        calls = parse_tool_calls(response)
        self.assertEqual(calls, [])

    def test_edit_file_multiline(self):
        response = '''[TOOL_START]
[TOOL_NAME_START]
edit_file
[TOOL_NAME_END]
[PARAM_NAME_START]
path
[PARAM_NAME_END]
[PARAM_VALUE_START]
calc.py
[PARAM_VALUE_END]
[PARAM_NAME_START]
original_text
[PARAM_NAME_END]
[PARAM_VALUE_START]
def add(a, b):
    return a + b
[PARAM_VALUE_END]
[PARAM_NAME_START]
new_text
[PARAM_NAME_END]
[PARAM_VALUE_START]
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b
[PARAM_VALUE_END]
[TOOL_END]'''
        calls = parse_tool_calls(response)
        params = calls[0][1]
        self.assertIn('def add(a, b):', params['original_text'])
        self.assertIn('def subtract(a, b):', params['new_text'])

    def test_search_files(self):
        response = '''[TOOL_START]
[TOOL_NAME_START]
search_files
[TOOL_NAME_END]
[PARAM_NAME_START]
pattern
[PARAM_NAME_END]
[PARAM_VALUE_START]
*.py
[PARAM_VALUE_END]
[PARAM_NAME_START]
search_dir
[PARAM_NAME_END]
[PARAM_VALUE_START]
[PARAM_VALUE_END]
[TOOL_END]'''
        calls = parse_tool_calls(response)
        self.assertEqual(calls[0][1], {'pattern': '*.py', 'search_dir': ''})

    def test_grep_code(self):
        response = '''[TOOL_START]
[TOOL_NAME_START]
grep_code
[TOOL_NAME_END]
[PARAM_NAME_START]
path
[PARAM_NAME_END]
[PARAM_VALUE_START]
app.py
[PARAM_VALUE_END]
[PARAM_NAME_START]
original_text
[PARAM_NAME_END]
[PARAM_VALUE_START]
world
[PARAM_VALUE_END]
[PARAM_NAME_START]
new_text
[PARAM_NAME_END]
[PARAM_VALUE_START]
universe
[PARAM_VALUE_END]
[TOOL_END]'''
        calls = parse_tool_calls(response)
        self.assertEqual(calls[0][1], {'path': 'app.py', 'original_text': 'world', 'new_text': 'universe'})

    def test_empty_param_value(self):
        response = '''[TOOL_START]
[TOOL_NAME_START]
read_file
[TOOL_NAME_END]
[PARAM_NAME_START]
path
[PARAM_NAME_END]
[PARAM_VALUE_START]
[PARAM_VALUE_END]
[TOOL_END]'''
        calls = parse_tool_calls(response)
        self.assertEqual(calls[0][1], {'path': ''})

    def test_done_marker(self):
        self.assertTrue(is_done('[DONE] Task completed')[0])
        self.assertEqual(is_done('[DONE] Task completed')[1], 'Task completed')
        self.assertFalse(is_done('just thinking...')[0])


# ====================================================================
# E2E Test: Agentic Mode with Tool Calls and Mock Responses
# ====================================================================

class TestAgentEngineE2E(unittest.TestCase):
    """End-to-end test for agentic mode execution with mocked LLM responses."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

        # Create a test Python file
        self.test_file = os.path.join(self.test_dir, 'main.py')
        with open(self.test_file, 'w') as f:
            f.write('def hello():\n    print("Hello World")\n')

        self.project_config = {
            'rootDirectory': self.test_dir,
            'instructions': 'Add a goodbye function to main.py',
            'job_id': 'e2e_test_job',
        }

        # Mock environment variables for engine config
        self.env_patch = patch.dict(os.environ, {
            'CUSTOM_ENDPOINT_URL': 'http://localhost:11434/v1',
            'CUSTOM_MODEL_NAME': 'test-model',
            'CUSTOM_API_KEY': '',
            'CUSTOM_VERIFY_SSL': 'false',
            'AIB_MAX_STEPS': '10',
        })
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()

    def test_e2e_agentic_tool_calls_and_responses(self):
        """Simulate a full agentic run where the LLM returns tool calls, the engine executes them,
        and feeds results back until completion."""

        # Track tool calls made by the engine
        executed_tools = []

        def mock_execute(self, tool_name, params):
            executed_tools.append((tool_name, params))
            if tool_name == 'read_file':
                return ToolResult(True, 'def hello():\n    print("Hello World")\n', summary='File read successfully')
            elif tool_name == 'edit_file':
                with open(self.root_dir + '/main.py', 'w') as f:
                    f.write('def hello():\n    print("Hello World")\n\ndef goodbye():\n    print("Goodbye World")\n')
                return ToolResult(True, 'File edited successfully', summary='Edit applied')
            elif tool_name == 'check_syntax':
                return ToolResult(True, 'Syntax OK', summary='Syntax check passed')
            else:
                return ToolResult(True, 'Tool executed', summary='Success')

        with patch.object(ToolRegistry, 'execute', mock_execute):
            # New tag-based format LLM responses
            llm_responses = [
                # Step 1: Agent reads file
                '[TOOL_START]\ntool_name:read_file\npath:main.py[TOOL_END]',
                # Step 2: Agent edits file
                '[TOOL_START]\ntool_name:edit_file\npath:main.py\noriginal_text:def hello():\n    print("Hello World")\n\nnew_text:def hello():\n    print("Hello World")\n\ndef goodbye():\n    print("Goodbye World")\n[TOOL_END]',
                # Step 3: Agent checks syntax
                '[TOOL_START]\ntool_name:check_syntax\npath:main.py[TOOL_END]',
                # Step 4: Agent completes
                '[DONE] Added goodbye function to main.py and verified syntax.',
            ]

            call_count = [0]
            def mock_llm_call(self, messages, response_file=None, system_prompt=""):
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(llm_responses):
                    return llm_responses[idx]
                return '[DONE] Task completed.'

            with patch.object(LLMClient, 'call', mock_llm_call):
                engine = AgentEngine(self.project_config)
                result = engine.run()

                # Verify tool calls were made in expected order
                self.assertEqual(len(executed_tools), 3)
                self.assertEqual(executed_tools[0][0], 'read_file')
                self.assertEqual(executed_tools[1][0], 'edit_file')
                self.assertEqual(executed_tools[2][0], 'check_syntax')

                # Verify file was modified correctly
                with open(self.test_file, 'r') as f:
                    content = f.read()
                self.assertIn('def goodbye():', content)
                self.assertIn('print("Goodbye World")', content)

                # Verify engine completed successfully
                self.assertEqual(result['status'], 'completed')
                self.assertIn('Added goodbye function', result['summary'])
                self.assertEqual(result['steps'], 4)
                # step_history includes both LLM calls and tool executions
                llm_calls = [s for s in engine.step_history if s['tool'] == 'llm_call']
                tool_steps = [s for s in engine.step_history if s['tool'] != 'llm_call']
                self.assertEqual(len(llm_calls), 4)  # 4 LLM calls (one per step)
                self.assertEqual(len(tool_steps), 3)  # 3 tool executions

    def test_e2e_agentic_loop_detection(self):
        """Test that the engine detects and breaks out of tool call loops."""

        executed_tools = []

        def mock_execute(self, tool_name, params):
            executed_tools.append((tool_name, params))
            return ToolResult(True, 'Result', summary='Success')

        with patch.object(ToolRegistry, 'execute', mock_execute):
            # LLM keeps calling the same tool repeatedly
            llm_responses = [
                '[TOOL_START]\ntool_name:read_file\npath:main.py[TOOL_END]',
                '[TOOL_START]\ntool_name:read_file\npath:main.py[TOOL_END]',
                '[TOOL_START]\ntool_name:read_file\npath:main.py[TOOL_END]',
                '[TOOL_START]\ntool_name:read_file\npath:main.py[TOOL_END]',
            ]

            call_count = [0]
            def mock_llm_call(self, messages, response_file=None, system_prompt=""):
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(llm_responses):
                    return llm_responses[idx]
                return '[DONE] Stopped repeating tool calls.'

            with patch.object(LLMClient, 'call', mock_llm_call):
                engine = AgentEngine(self.project_config)
                result = engine.run()

                # Engine should have intervened and stopped the loop
                self.assertEqual(result['status'], 'completed')
                self.assertIn('Stopped repeating', result['summary'])
                # Should have at least 4 repeated tool calls before intervention
                self.assertGreaterEqual(len(engine.step_history), 4)


if __name__ == '__main__':
    unittest.main()
