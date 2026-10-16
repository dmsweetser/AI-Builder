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
        original_execute = ToolRegistry.execute
        
        def mock_execute(self, tool_name, params):
            executed_tools.append((tool_name, params))
            # Simulate tool results based on tool name
            if tool_name == 'read_file':
                return ToolResult(True, 'def hello():\n    print("Hello World")\n', summary='File read successfully')
            elif tool_name == 'edit_file':
                # Simulate successful edit
                with open(self.root_dir + '/main.py', 'w') as f:
                    f.write('def hello():\n    print("Hello World")\n\ndef goodbye():\n    print("Goodbye World")\n')
                return ToolResult(True, 'File edited successfully', summary='Edit applied')
            elif tool_name == 'check_syntax':
                return ToolResult(True, 'Syntax OK', summary='Syntax check passed')
            else:
                return ToolResult(True, 'Tool executed', summary='Success')
        
        # Patch ToolRegistry.execute
        with patch.object(ToolRegistry, 'execute', mock_execute):
            # Mock LLM responses to simulate agent behavior
            llm_responses = [
                # Step 1: Agent reads file
                '[TOOL:read_file{path:"main.py"}]',
                # Step 2: Agent edits file
                '[TOOL:edit_file{path:"main.py",original_text:"def hello():\\n    print(\\"Hello World\\")\\n",new_text:"def hello():\\n    print(\\"Hello World\\")\\n\\ndef goodbye():\\n    print(\\"Goodbye World\\")\\n"}]',
                # Step 3: Agent checks syntax
                '[TOOL:check_syntax{path:"main.py"}]',
                # Step 4: Agent completes
                '[DONE] Added goodbye function to main.py and verified syntax.',
            ]
            
            call_count = [0]
            def mock_llm_call(messages, response_file=None):
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(llm_responses):
                    return llm_responses[idx]
                return '[DONE] Task completed.'
            
            # Patch LLMClient.call
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
                self.assertEqual(len(engine.step_history), 4)

    def test_e2e_agentic_loop_detection(self):
        """Test that the engine detects and breaks out of tool call loops."""
        
        executed_tools = []
        original_execute = ToolRegistry.execute
        
        def mock_execute(self, tool_name, params):
            executed_tools.append((tool_name, params))
            return ToolResult(True, 'Result', summary='Success')
        
        with patch.object(ToolRegistry, 'execute', mock_execute):
            # LLM keeps calling the same tool repeatedly
            llm_responses = [
                '[TOOL:read_file{path:"main.py"}]',
                '[TOOL:read_file{path:"main.py"}]',
                '[TOOL:read_file{path:"main.py"}]',
                '[TOOL:read_file{path:"main.py"}]',
            ]
            
            call_count = [0]
            def mock_llm_call(messages, response_file=None):
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(llm_responses):
                    return llm_responses[idx]
                # After loop detection intervention, LLM should stop
                return '[DONE] Stopped repeating tool calls.'
            
            with patch.object(LLMClient, 'call', mock_llm_call):
                engine = AgentEngine(self.project_config)
                result = engine.run()
                
                # Engine should have intervened and stopped the loop
                self.assertEqual(result['status'], 'completed')
                self.assertIn('Stopped repeating', result['summary'])
                # Should have more steps than just the repeated tool calls due to intervention messages
                self.assertGreater(len(engine.step_history), 4)


if __name__ == '__main__':
    unittest.main()
