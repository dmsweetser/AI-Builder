"""Run real test projects through the agent engine to validate end-to-end behavior."""
import os
import sys
import json
import tempfile
import shutil
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_engine.engine import AgentEngine, LLMClient
from agent_engine.tools.base import ToolResult
from agent_engine.tools import ToolRegistry


def make_mock_execute(test_dir):
    """Create a mock execute function that uses the given test directory."""
    def mock_execute(self, tool_name, params):
        root = self.root_dir
        if tool_name == 'list_directory':
            path = params.get('path', root) or root
            try:
                entries = os.listdir(path)
                return ToolResult(True, '\n'.join(entries), summary=f'Directory listing of {path}')
            except FileNotFoundError:
                return ToolResult(False, '', error='Directory not found')
        elif tool_name == 'read_file':
            path = os.path.join(root, params.get('path', ''))
            with open(path, 'r') as f:
                content = f.read()
            return ToolResult(True, content, summary='File read successfully')
        elif tool_name == 'write_file':
            path = os.path.join(root, params.get('path', ''))
            content = params.get('content', '')
            with open(path, 'w') as f:
                f.write(content)
            return ToolResult(True, 'File created successfully', summary='New file written')
        elif tool_name == 'edit_file':
            path = os.path.join(root, params.get('path', ''))
            original = params.get('original_text', '')
            new_text = params.get('new_text', '')
            with open(path, 'r') as f:
                content = f.read()
            if original in content:
                content = content.replace(original, new_text)
                with open(path, 'w') as f:
                    f.write(content)
                return ToolResult(True, 'File edited successfully', summary='Edit applied')
            return ToolResult(False, '', error='original_text not found')
        elif tool_name == 'check_syntax':
            return ToolResult(True, 'Syntax OK', summary='Syntax check passed')
        return ToolResult(True, 'Tool executed', summary='Success')
    return mock_execute


class TestRealProjectPython(unittest.TestCase):
    """Test the agent engine with a real Python project."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.main_file = os.path.join(self.test_dir, 'main.py')
        with open(self.main_file, 'w') as f:
            f.write('def add(a, b):\n    return a + b\n')

        self.config = {
            'rootDirectory': self.test_dir,
            'instructions': 'Add a subtract function to main.py',
            'job_id': 'test_python_project',
        }

        self.env_patch = mock.patch.dict(os.environ, {
            'CUSTOM_ENDPOINT_URL': 'http://localhost:11434/v1',
            'CUSTOM_MODEL_NAME': 'test-model',
            'CUSTOM_API_KEY': '',
            'CUSTOM_VERIFY_SSL': 'false',
            'AIB_MAX_STEPS': '10',
        })
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_agent_adds_function(self):
        """Agent should add a subtract function to main.py."""
        executed_tools = []

        def track_execute(registry, tool_name, params):
            executed_tools.append((tool_name, params))
            return make_mock_execute(registry.root_dir)(registry, tool_name, params)

        llm_responses = [
            '[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[TOOL_END]',
            '[TOOL_START]\n[TOOL_NAME]\nedit_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[PARAM_NAME]\noriginal_text\n[PARAM_VALUE]\ndef add(a, b):\n    return a + b\n\n[PARAM_NAME]\nnew_text\n[PARAM_VALUE]\ndef add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n[TOOL_END]',
            '[TOOL_START]\n[TOOL_NAME]\ncheck_syntax\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nmain.py\n[TOOL_END]',
            '[DONE] Added subtract function to main.py and verified syntax.',
        ]

        call_count = [0]
        def mock_llm(self, messages, response_file=None, system_prompt="", step=0):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(llm_responses):
                return {"content": llm_responses[idx]}
            return {"content": '[DONE] Done.'}

        with mock.patch.object(ToolRegistry, 'execute', track_execute):
            with mock.patch.object(LLMClient, 'call', mock_llm):
                engine = AgentEngine(self.config)
                result = engine.run()

                self.assertEqual(len(executed_tools), 3)
                self.assertEqual(executed_tools[0][0], 'read_file')
                self.assertEqual(executed_tools[1][0], 'edit_file')
                self.assertEqual(executed_tools[2][0], 'check_syntax')

                with open(self.main_file, 'r') as f:
                    content = f.read()
                self.assertIn('def subtract(a, b):', content)
                self.assertIn('return a - b', content)

                self.assertEqual(result['status'], 'completed')
                self.assertIn('Added subtract function', result['summary'])
                self.assertEqual(result['steps'], 4)


class TestRealProjectJavaScript(unittest.TestCase):
    """Test the agent engine with a JavaScript project."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.main_file = os.path.join(self.test_dir, 'utils.js')
        with open(self.main_file, 'w') as f:
            f.write('function greet(name) {\n    return "Hello, " + name;\n}\n')

        self.config = {
            'rootDirectory': self.test_dir,
            'instructions': 'Add a farewell function to utils.js',
            'job_id': 'test_js_project',
        }

        self.env_patch = mock.patch.dict(os.environ, {
            'CUSTOM_ENDPOINT_URL': 'http://localhost:11434/v1',
            'CUSTOM_MODEL_NAME': 'test-model',
            'CUSTOM_API_KEY': '',
            'CUSTOM_VERIFY_SSL': 'false',
            'AIB_MAX_STEPS': '10',
        })
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_agent_adds_js_function(self):
        """Agent should add a farewell function to utils.js."""
        executed_tools = []

        def track_execute(registry, tool_name, params):
            executed_tools.append((tool_name, params))
            return make_mock_execute(registry.root_dir)(registry, tool_name, params)

        llm_responses = [
            '[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nutils.js\n[TOOL_END]',
            '[TOOL_START]\n[TOOL_NAME]\nedit_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nutils.js\n[PARAM_NAME]\noriginal_text\n[PARAM_VALUE]\nfunction greet(name) {\n    return "Hello, " + name;\n}\n\n[PARAM_NAME]\nnew_text\n[PARAM_VALUE]\nfunction greet(name) {\n    return "Hello, " + name;\n}\n\nfunction farewell(name) {\n    return "Goodbye, " + name;\n}\n[TOOL_END]',
            '[TOOL_START]\n[TOOL_NAME]\ncheck_syntax\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nutils.js\n[TOOL_END]',
            '[DONE] Added farewell function to utils.js.',
        ]

        call_count = [0]
        def mock_llm(self, messages, response_file=None, system_prompt="", step=0):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(llm_responses):
                return {"content": llm_responses[idx]}
            return {"content": '[DONE] Done.'}

        with mock.patch.object(ToolRegistry, 'execute', track_execute):
            with mock.patch.object(LLMClient, 'call', mock_llm):
                engine = AgentEngine(self.config)
                result = engine.run()

                self.assertEqual(len(executed_tools), 3)

                with open(self.main_file, 'r') as f:
                    content = f.read()
                self.assertIn('function farewell(name)', content)
                self.assertIn('Goodbye', content)

                self.assertEqual(result['status'], 'completed')
                self.assertIn('Added farewell function', result['summary'])


class TestRealProjectMultiFile(unittest.TestCase):
    """Test the agent engine with a multi-file project."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.src_dir = os.path.join(self.test_dir, 'src')
        os.makedirs(self.src_dir)
        self.init_py = os.path.join(self.src_dir, '__init__.py')
        self.main_py = os.path.join(self.src_dir, 'main.py')

        with open(self.init_py, 'w') as f:
            f.write('# Package init\n')
        with open(self.main_py, 'w') as f:
            f.write('from .utils import helper\n\ndef run():\n    return helper()\n')

        self.config = {
            'rootDirectory': self.test_dir,
            'instructions': 'Create a utils.py with a helper function in src/',
            'job_id': 'test_multifile_project',
        }

        self.env_patch = mock.patch.dict(os.environ, {
            'CUSTOM_ENDPOINT_URL': 'http://localhost:11434/v1',
            'CUSTOM_MODEL_NAME': 'test-model',
            'CUSTOM_API_KEY': '',
            'CUSTOM_VERIFY_SSL': 'false',
            'AIB_MAX_STEPS': '10',
        })
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_agent_creates_new_file(self):
        """Agent should create a new utils.py file."""
        executed_tools = []

        def track_execute(registry, tool_name, params):
            executed_tools.append((tool_name, params))
            return make_mock_execute(registry.root_dir)(registry, tool_name, params)

        llm_responses = [
            '[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n[PARAM_NAME]\nmax_depth\n[PARAM_VALUE]\n2\n[TOOL_END]',
            '[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py\n[TOOL_END]',
            '[TOOL_START]\n[TOOL_NAME]\nwrite_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/utils.py\n[PARAM_NAME]\ncontent\n[PARAM_VALUE]\ndef helper():\n    return "Hello from utils"\n[TOOL_END]',
            '[TOOL_START]\n[TOOL_NAME]\nedit_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py\n[PARAM_NAME]\noriginal_text\n[PARAM_VALUE]\ndef helper():\n    return "Hello from utils"\n\ndef run():\n    return helper()\n\n[PARAM_NAME]\nnew_text\n[PARAM_VALUE]\ndef helper():\n    return "Hello from utils"\n\ndef run():\n    return helper()\n[TOOL_END]',
            '[TOOL_START]\n[TOOL_NAME]\ncheck_syntax\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py\n[TOOL_END]',
            '[DONE] Created utils.py with helper function and updated imports.',
        ]

        call_count = [0]
        def mock_llm(self, messages, response_file=None, system_prompt="", step=0):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(llm_responses):
                return {"content": llm_responses[idx]}
            return {"content": '[DONE] Done.'}

        with mock.patch.object(ToolRegistry, 'execute', track_execute):
            with mock.patch.object(LLMClient, 'call', mock_llm):
                engine = AgentEngine(self.config)
                result = engine.run()

                self.assertGreaterEqual(len(executed_tools), 4)
                tool_names = [t[0] for t in executed_tools]
                self.assertIn('list_directory', tool_names)
                self.assertIn('read_file', tool_names)
                self.assertIn('write_file', tool_names)

                utils_file = os.path.join(self.src_dir, 'utils.py')
                self.assertTrue(os.path.exists(utils_file))
                with open(utils_file, 'r') as f:
                    content = f.read()
                self.assertIn('def helper():', content)
                self.assertIn('Hello from utils', content)

                self.assertEqual(result['status'], 'completed')
                self.assertIn('Created utils.py', result['summary'])


if __name__ == '__main__':
    unittest.main()
