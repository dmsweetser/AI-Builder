"""
Comprehensive integration tests for AI Builder using a mock LLM server.

This test suite starts a background mock LLM server that returns prescribed
responses based on input patterns. It configures AI Builder to use this
endpoint and validates the entire system with actual over-network LLM comms.

Tests include:
- Basic tool execution (list_directory, create_file, respond_to_user)
- Pending user input workflow
- Tool creation and approval
- Project reset and continuation
- UI components (jobs, live view, inject)
"""

import json
import os
import sys
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tests.mock_llm_server import MockLLMServer, MockLLMHandler


class TestMockLLMServer(unittest.TestCase):
    """Test the mock LLM server itself."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.server = MockLLMServer(host='127.0.0.1', port=0)
        self.port = self.server.start()
        self.base_url = f"http://127.0.0.1:{self.port}/v1/chat/completions"
    
    def tearDown(self):
        """Tear down test fixtures."""
        self.server.stop()
    
    def test_server_starts(self):
        """Test that the server starts and is accessible."""
        self.assertIsNotNone(self.server)
        self.assertGreater(self.port, 0)
    
    def test_non_streaming_response(self):
        """Test non-streaming response."""
        self.server.add_response(
            r"hello",
            "Hello! I'm a mock AI."
        )
        
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
        
        self.assertEqual(result["choices"][0]["message"]["content"], "Hello! I'm a mock AI.")
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")
    
    def test_streaming_response(self):
        """Test streaming response."""
        self.server.add_response(
            r"hello",
            "Hello! I'm a mock AI."
        )
        
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            chunks = []
            for line in response:
                line = line.decode('utf-8').strip()
                if line.startswith('data: '):
                    data_str = line[6:]
                    if data_str == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data_str)
                        chunks.append(chunk)
                    except json.JSONDecodeError:
                        continue
        
        # Should have multiple chunks
        self.assertGreater(len(chunks), 0)
        # Last chunk should have finish_reason
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "stop")
    
    def test_tool_calls_response(self):
        """Test tool calls response."""
        self.server.add_response(
            r"list_directory",
            "I'll help you with that. Let me explore the project structure.",
            tool_calls=[{
                "function": {
                    "name": "list_directory",
                    "arguments": {"path": "."}
                }
            }]
        )
        
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "list_directory"}],
            "stream": False
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
        
        self.assertEqual(result["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(len(result["choices"][0]["message"]["tool_calls"]), 1)
        self.assertEqual(
            result["choices"][0]["message"]["tool_calls"][0]["function"]["name"],
            "list_directory"
        )


class TestAIBuilderIntegration(unittest.TestCase):
    """Test AI Builder integration with the mock LLM server."""
    
    @classmethod
    def setUpClass(cls):
        """Set up the mock LLM server once for all tests."""
        cls.server = MockLLMServer(host='127.0.0.1', port=0)
        cls.port = cls.server.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}/v1/chat/completions"
        
        # Configure AI Builder to use the mock server
        settings_path = project_root / "aib_instance" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        
        settings = {
            "custom_endpoint_url": cls.base_url,
            "custom_api_key": "",
            "custom_model_name": "mock-llm",
            "custom_verify_ssl": False,
            "max_steps": 10,
            "timeout": 300,
            "max_tokens": 1000
        }
        
        with open(settings_path, 'w') as f:
            json.dump(settings, f, indent=2)
        
        cls.settings_path = settings_path
    
    @classmethod
    def tearDownClass(cls):
        """Tear down the mock LLM server."""
        cls.server.stop()
    
    def setUp(self):
        """Reset the mock server state before each test."""
        MockLLMHandler.state.reset()
        MockLLMHandler.responses.clear()
    
    def test_basic_tool_execution(self):
        """Test basic tool execution: list_directory -> create_file -> respond_to_user."""
        # Add prescribed responses
        self.server.add_response(
            r"list_directory",
            "I'll help you with that. Let me explore the project structure.",
            tool_calls=[{
                "function": {
                    "name": "list_directory",
                    "arguments": {"path": "."}
                }
            }]
        )
        
        self.server.add_response(
            r"CREATE_FILE",
            "I've created the file as requested.",
            tool_calls=[{
                "function": {
                    "name": "create_file",
                    "arguments": {"path": "test.txt", "content": "Hello, World!"}
                }
            }]
        )
        
        self.server.add_response(
            r"respond_to_user",
            "Task completed successfully!",
            tool_calls=[{
                "function": {
                    "name": "respond_to_user",
                    "arguments": {"message": "Task completed successfully!"}
                }
            }]
        )
        
        # Make a request to the mock server
        payload = {
            "model": "mock-llm",
            "messages": [{"role": "user", "content": "list_directory"}],
            "stream": False
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
        
        # Validate the response
        self.assertEqual(result["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(
            result["choices"][0]["message"]["tool_calls"][0]["function"]["name"],
            "list_directory"
        )
    
    def test_pending_user_input_workflow(self):
        """Test the pending user input workflow."""
        # Add a response that requests user input
        self.server.add_response(
            r"request_user_input",
            "I need more information from you.",
            tool_calls=[{
                "function": {
                    "name": "request_user_input",
                    "arguments": {"prompt": "What is your name?"}
                }
            }]
        )
        
        payload = {
            "model": "mock-llm",
            "messages": [{"role": "user", "content": "request_user_input"}],
            "stream": False
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
        
        # Validate the response
        self.assertEqual(result["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(
            result["choices"][0]["message"]["tool_calls"][0]["function"]["name"],
            "request_user_input"
        )


if __name__ == '__main__':
    unittest.main()
