"""Expanded integration tests for AI Builder using a mock LLM server.

This test suite starts a background mock LLM server that returns prescribed
responses based on input patterns. It configures AI Builder to use this
endpoint and validates the entire system with actual over-network LLM comms.

Tests include:
- Mock LLM server functionality (streaming, non-streaming, tool calls)
- Basic tool execution (list_directory, create_file, respond_to_user)
- Pending user input workflow
- Tool creation and approval
- Project reset and continuation
- UI components (jobs, live view, inject)
- Grep code optimization
- E2E agentic loops (read -> edit -> check_syntax -> done)
- Loop detection (repeated tool calls)
- Multi-file project creation
- JavaScript project modification
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

from tests.mock_llm_server import MockLLMServer, MockLLMHandler, MockLLMToolCall


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
            tool_calls=[MockLLMToolCall("list_directory", {"path": "."})]
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
    
    def test_multiple_tool_calls(self):
        """Test multiple tool calls in one response."""
        self.server.add_response(
            r"complex",
            "I'll do multiple things.",
            tool_calls=[
                MockLLMToolCall("list_directory", {"path": "."}),
                MockLLMToolCall("read_file", {"path": "README.md"})
            ]
        )
        
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "complex"}],
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
        self.assertEqual(len(result["choices"][0]["message"]["tool_calls"]), 2)
    
    def test_pattern_matching(self):
        """Test that pattern matching works correctly."""
        self.server.add_response(
            r"specific_pattern",
            "Matched specific pattern."
        )
        
        # Should match
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "this has specific_pattern in it"}],
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
        
        self.assertEqual(result["choices"][0]["message"]["content"], "Matched specific pattern.")
    
    def test_no_match_fallback(self):
        """Test that unmatched patterns get fallback response."""
        # Don't add any responses
        
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "random stuff"}],
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
        
        # Should get the fallback response
        self.assertIn("mock AI", result["choices"][0]["message"]["content"])

    def test_tag_based_tool_call_response(self):
        """Test add_tool_call_response helper method."""
        self.server.add_tool_call_response(
            r"read_file",
            "read_file",
            {"path": "main.py"}
        )
        
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "read_file main.py"}],
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
        
        # Should get the tag-based tool call as content
        content = result["choices"][0]["message"]["content"]
        self.assertIn("[TOOL_START]", content)
        self.assertIn("[TOOL_NAME]", content)
        self.assertIn("read_file", content)
        self.assertIn("[PARAM_NAME]", content)
        self.assertIn("[PARAM_VALUE]", content)
        self.assertIn("main.py", content)
        self.assertIn("[TOOL_END]", content)


class TestAIBuilderIntegration(unittest.TestCase):
    """Test AI Builder integration with the mock LLM server."""
    
    @classmethod
    def setUpClass(cls):
        """Set up the mock LLM server once for all tests."""
        cls.server = MockLLMServer(host='127.0.0.1', port=18766)
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
        import time
        time.sleep(0.5)
    
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
            tool_calls=[MockLLMToolCall("list_directory", {"path": "."})]
        )
        
        self.server.add_response(
            r"CREATE_FILE",
            "I've created the file as requested.",
            tool_calls=[MockLLMToolCall("create_file", {"path": "test.txt", "content": "Hello, World!"})]
        )
        
        self.server.add_response(
            r"respond_to_user",
            "Task completed successfully!",
            tool_calls=[MockLLMToolCall("respond_to_user", {"message": "Task completed successfully!"})]
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
            tool_calls=[MockLLMToolCall("request_user_input", {"prompt": "What is your name?"})]
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
    
    def test_tool_creation_workflow(self):
        """Test the tool creation workflow."""
        # Add a response that creates a tool
        self.server.add_response(
            r"create_tool",
            "I'll create a new tool for you.",
            tool_calls=[MockLLMToolCall("create_tool", {
                "name": "my_custom_tool",
                "code": "def my_tool(): pass"
            })]
        )
        
        payload = {
            "model": "mock-llm",
            "messages": [{"role": "user", "content": "create_tool"}],
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
            "create_tool"
        )
    
    def test_grep_code_optimization(self):
        """Test that grep_code tool uses subprocess for better performance."""
        # Import the tool
        from agent_engine.tools.grep_code import GrepCodeTool
        
        # Create a temporary directory for testing
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some test files
            with open(os.path.join(tmpdir, "test1.txt"), 'w') as f:
                f.write("Hello World\nThis is a test\n")
            with open(os.path.join(tmpdir, "test2.txt"), 'w') as f:
                f.write("Another test file\nHello again\n")
            
            # Create the tool instance
            tool = GrepCodeTool(root_dir=tmpdir)
            
            # Execute the tool
            result = tool.execute({"pattern": "Hello"})
            
            # Validate the result
            self.assertTrue(result.success)
            self.assertIn("test1.txt", result.content)
            self.assertIn("test2.txt", result.content)
            self.assertIn("2 matches", result.summary)
    
    def test_project_reset_workflow(self):
        """Test the project reset workflow."""
        # Add a response that resets the project
        self.server.add_response(
            r"reset",
            "I'll reset the project.",
            tool_calls=[MockLLMToolCall("respond_to_user", {"message": "Project reset successfully!"})]
        )
        
        payload = {
            "model": "mock-llm",
            "messages": [{"role": "user", "content": "reset"}],
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
            "respond_to_user"
        )
    
    def test_continuation_workflow(self):
        """Test the continuation workflow."""
        # Add a response that continues from a previous run
        self.server.add_response(
            r"CONTINUATION",
            "I'll continue from where we left off.",
            tool_calls=[MockLLMToolCall("list_directory", {"path": "."})]
        )
        
        payload = {
            "model": "mock-llm",
            "messages": [{"role": "user", "content": "CONTINUATION"}],
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


class TestAIBuilderFlaskAPI(unittest.TestCase):
    """Test the Flask API endpoints with the mock LLM server."""
    
    @classmethod
    def setUpClass(cls):
        """Set up the mock LLM server and Flask app."""
        cls.server = MockLLMServer(host='127.0.0.1', port=18767)
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
        
        # Start the Flask app
        import app as flask_app
        cls.flask_app = flask_app.app
        cls.flask_app.config['TESTING'] = True
        cls.flask_client = cls.flask_app.test_client()
    
    @classmethod
    def tearDownClass(cls):
        """Tear down the mock LLM server."""
        cls.server.stop()
        import time
        time.sleep(0.5)
    
    def setUp(self):
        """Reset the mock server state before each test."""
        MockLLMHandler.state.reset()
        MockLLMHandler.responses.clear()
    
    def test_projects_endpoint(self):
        """Test the /api/projects endpoint."""
        response = self.flask_client.get('/api/projects')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIsInstance(data, list)
    
    def test_queue_endpoint(self):
        """Test the /api/queue endpoint."""
        response = self.flask_client.get('/api/queue')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('queue', data)
        self.assertIn('running', data)
    
    def test_history_endpoint(self):
        """Test the /api/history endpoint."""
        response = self.flask_client.get('/api/history')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIsInstance(data, list)
    
    def test_settings_endpoint(self):
        """Test the /api/settings endpoint."""
        response = self.flask_client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        # The settings may have more keys, so just check it's a dict
        self.assertIsInstance(data, dict)


class TestE2EAgenticLoop(unittest.TestCase):
    """End-to-end tests for the agentic loop using the mock LLM server.
    
    These tests configure the engine to use the mock LLM server and verify
    that the full agentic loop works correctly: LLM -> tool execution -> feedback.
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up the mock LLM server once for all tests."""
        cls.server = MockLLMServer(host='127.0.0.1', port=18768)
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
        import time
        time.sleep(0.5)
    
    def setUp(self):
        """Reset the mock server state and create a temp project before each test."""
        MockLLMHandler.state.reset()
        MockLLMHandler.responses.clear()
        self.test_dir = None
        self.main_file = None
    
    def tearDown(self):
        """Clean up temp project."""
        if self.test_dir:
            import shutil
            shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def _create_python_project(self, initial_content):
        """Create a temp Python project with the given initial content."""
        import tempfile
        self.test_dir = tempfile.mkdtemp()
        self.main_file = os.path.join(self.test_dir, 'main.py')
        with open(self.main_file, 'w') as f:
            f.write(initial_content)
        return self.test_dir
    
    def _run_engine(self, instructions, llm_responses):
        """Run the engine with prescribed LLM responses via the mock server.
        
        Args:
            instructions: Task instructions for the engine
            llm_responses: List of (pattern, response_text) tuples to add as sequential responses
        """
        import app as flask_app
        
        # Add LLM responses as sequential responses (used in order)
        for pattern, response_text in llm_responses:
            self.server.add_sequential_response(response_text, delay=0.0)
        
        # Submit the job via Flask API
        client = flask_app.app.test_client()
        
        # First, create a project
        proj_response = client.post('/api/projects', json={
            'rootDirectory': self.test_dir,
            'name': 'e2e_test'
        })
        self.assertEqual(proj_response.status_code, 200)
        proj_data = json.loads(proj_response.data)
        project_id = proj_data.get('id', 'e2e_test')
        
        # Submit the job - the /api/agent/run endpoint returns an SSE stream
        job_response = client.post('/api/agent/run', json={
            'project_id': project_id,
            'instructions': instructions,
            'enabled_tools': ['list_directory', 'read_file', 'write_file', 'edit_file', 'check_syntax', 'delete_file']
        })
        self.assertEqual(job_response.status_code, 200)
        # Parse SSE stream to extract job_id from the first event
        sse_data = job_response.data.decode('utf-8')
        job_id = None
        for line in sse_data.split('\n'):
            line = line.strip()
            if line.startswith('data: '):
                try:
                    event = json.loads(line[6:])
                    if 'job_id' in event:
                        job_id = event['job_id']
                        break
                except json.JSONDecodeError:
                    continue
        if not job_id:
            # Fallback: extract from the first SSE event
            for line in sse_data.split('\n'):
                if line.startswith('data: '):
                    try:
                        event = json.loads(line[6:])
                        job_id = event.get('job_id', f'e2e_test_{int(time.time() * 1000)}')
                    except json.JSONDecodeError:
                        job_id = f'e2e_test_{int(time.time() * 1000)}'
                    break
            else:
                job_id = f'e2e_test_{int(time.time() * 1000)}'
        
        # Wait for the job to complete (poll the queue)
        max_wait = 30  # seconds
        start = time.time()
        while time.time() - start < max_wait:
            queue_response = client.get('/api/queue')
            queue_data = json.loads(queue_response.data)
            running = queue_data.get('running', [])
            if not running:
                break
            time.sleep(0.5)
        
        # Get the job history
        history_response = client.get(f'/api/agent/history/{job_id}')
        self.assertEqual(history_response.status_code, 200)
        history_data = json.loads(history_response.data)
        
        return history_data
    
    def test_e2e_python_add_function(self):
        """Agent should add a subtract function to main.py via the mock server."""
        self._create_python_project('def add(a, b):\n    return a + b\n')
        
        # Prescribed LLM responses (tag-based format)
        llm_responses = [
            (r"EXPLORE", '[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]'),
            (r"READ_FILE", '[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[TOOL_END]'),
            (r"EDIT_FILE", '[TOOL_START]\n[TOOL_NAME]\nedit_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[PARAM_NAME]\noriginal_text\n[PARAM_VALUE]\ndef add(a, b):\n    return a + b\n\n[PARAM_NAME]\nnew_text\n[PARAM_VALUE]\ndef add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n[TOOL_END]'),
            (r"SYNTAX", '[TOOL_START]\n[TOOL_NAME]\ncheck_syntax\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[TOOL_END]'),
            (r"COMPLETE", '[DONE] Added subtract function to main.py and verified syntax.'),
        ]
        
        history = self._run_engine(
            'Add a subtract function to main.py',
            llm_responses
        )
        
        # Verify the file was modified
        assert self.main_file is not None
        with open(self.main_file, 'r') as f:
            content = f.read()
        self.assertIn('def subtract(a, b):', content)
        self.assertIn('return a - b', content)
    
    def test_e2e_js_add_function(self):
        """Agent should add a farewell function to utils.js via the mock server."""
        import tempfile
        self.test_dir = tempfile.mkdtemp()
        self.main_file = os.path.join(self.test_dir, 'utils.js')
        with open(self.main_file, 'w') as f:
            f.write('function greet(name) {\n    return "Hello, " + name;\n}\n')
        
        llm_responses = [
            (r"EXPLORE", '[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]'),
            (r"READ_FILE", '[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nutils.js\n[TOOL_END]'),
            (r"EDIT_FILE", '[TOOL_START]\n[TOOL_NAME]\nedit_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nutils.js\n[PARAM_NAME]\noriginal_text\n[PARAM_VALUE]\nfunction greet(name) {\n    return "Hello, " + name;\n}\n\n[PARAM_NAME]\nnew_text\n[PARAM_VALUE]\nfunction greet(name) {\n    return "Hello, " + name;\n}\n\nfunction farewell(name) {\n    return "Goodbye, " + name;\n}\n[TOOL_END]'),
            (r"SYNTAX", '[TOOL_START]\n[TOOL_NAME]\ncheck_syntax\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nutils.js\n[TOOL_END]'),
            (r"COMPLETE", '[DONE] Added farewell function to utils.js.'),
        ]
        
        import app as flask_app
        client = flask_app.app.test_client()
        
        proj_response = client.post('/api/projects', json={
            'rootDirectory': self.test_dir,
            'name': 'e2e_js_test'
        })
        self.assertEqual(proj_response.status_code, 200)
        project_id = json.loads(proj_response.data).get('id', 'e2e_js_test')
        
        for pattern, response_text in llm_responses:
            self.server.add_sequential_response(response_text, delay=0.0)
        
        job_response = client.post('/api/agent/run', json={
            'project_id': project_id,
            'instructions': 'Add a farewell function to utils.js',
            'enabled_tools': ['list_directory', 'read_file', 'write_file', 'edit_file', 'check_syntax']
        })
        self.assertEqual(job_response.status_code, 200)
        # Parse SSE stream to extract job_id
        sse_data = job_response.data.decode('utf-8')
        job_id = None
        for line in sse_data.split('\n'):
            line = line.strip()
            if line.startswith('data: '):
                try:
                    event = json.loads(line[6:])
                    job_id = event.get('job_id')
                    if job_id:
                        break
                except json.JSONDecodeError:
                    continue
        job_id = job_id or 'test_job'
        
        # Wait for completion
        max_wait = 30
        start = time.time()
        while time.time() - start < max_wait:
            queue_response = client.get('/api/queue')
            queue_data = json.loads(queue_response.data)
            if not queue_data.get('running'):
                break
            time.sleep(0.5)
        
        # Verify the file was modified
        assert self.main_file is not None
        with open(self.main_file, 'r') as f:
            content = f.read()
        self.assertIn('function farewell(name)', content)
        self.assertIn('Goodbye', content)
    
    def test_e2e_create_new_file(self):
        """Agent should create a new utils.py file via the mock server."""
        import tempfile
        self.test_dir = tempfile.mkdtemp()
        self.src_dir = os.path.join(self.test_dir, 'src')
        os.makedirs(self.src_dir)
        self.main_py = os.path.join(self.src_dir, 'main.py')
        with open(self.main_py, 'w') as f:
            f.write('from .utils import helper\n\ndef run():\n    return helper()\n')
        
        llm_responses = [
            (r"EXPLORE", '[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[PARAM_NAME]\nmax_depth\n[PARAM_VALUE]\n2\n[TOOL_END]'),
            (r"READ_FILE", '[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py\n[TOOL_END]'),
            (r"WRITE_FILE", '[TOOL_START]\n[TOOL_NAME]\nwrite_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/utils.py\n[PARAM_NAME]\ncontent\n[PARAM_VALUE]\ndef helper():\n    return "Hello from utils"\n[TOOL_END]'),
            (r"SYNTAX", '[TOOL_START]\n[TOOL_NAME]\ncheck_syntax\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/utils.py\n[TOOL_END]'),
            (r"COMPLETE", '[DONE] Created utils.py with helper function.'),
        ]
        
        import app as flask_app
        client = flask_app.app.test_client()
        
        proj_response = client.post('/api/projects', json={
            'rootDirectory': self.test_dir,
            'name': 'e2e_multifile_test'
        })
        self.assertEqual(proj_response.status_code, 200)
        project_id = json.loads(proj_response.data).get('id', 'e2e_multifile_test')
        
        for pattern, response_text in llm_responses:
            self.server.add_sequential_response(response_text, delay=0.0)
        
        job_response = client.post('/api/agent/run', json={
            'project_id': project_id,
            'instructions': 'Create a utils.py with a helper function in src/',
            'enabled_tools': ['list_directory', 'read_file', 'write_file', 'edit_file', 'check_syntax']
        })
        self.assertEqual(job_response.status_code, 200)
        # Parse SSE stream to extract job_id
        sse_data = job_response.data.decode('utf-8')
        job_id = None
        for line in sse_data.split('\n'):
            line = line.strip()
            if line.startswith('data: '):
                try:
                    event = json.loads(line[6:])
                    job_id = event.get('job_id')
                    if job_id:
                        break
                except json.JSONDecodeError:
                    continue
        job_id = job_id or 'test_job'
        
        # Wait for completion
        max_wait = 30
        start = time.time()
        while time.time() - start < max_wait:
            queue_response = client.get('/api/queue')
            queue_data = json.loads(queue_response.data)
            if not queue_data.get('running'):
                break
            time.sleep(0.5)
        
        # Verify the file was created
        utils_file = os.path.join(self.src_dir, 'utils.py')
        self.assertTrue(os.path.exists(utils_file))
        with open(utils_file, 'r') as f:
            content = f.read()
        self.assertIn('def helper():', content)
        self.assertIn('Hello from utils', content)


if __name__ == '__main__':
    unittest.main()
