"""Tests for AI-Builder - FileParser, FileModifier, security helpers."""
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

from ai_builder import FileParser, FileModifier, ActionManager
from agent_engine.security import ensure_under_root, validate_tool_params, SecurityError, ToolError
from agent_engine.tools.base import ToolResult, BaseTool
from agent_engine.engine import parse_tool_calls, is_done, build_user_prompt
from agent_engine.tools.files import (
    ListDirectoryTool, ReadFileTool, WriteFileTool, EditFileTool,
    SearchFilesTool, GrepCodeTool, DeleteFileTool,
)
from agent_engine.tools.checkers import CheckSyntaxTool
from agent_engine.tools.misc import GetFileInfoTool
from agent_engine.tools.search import FindSymbolTool


class TestFileParser(unittest.TestCase):
    """Tests for the custom Walbert-style code modification syntax parser."""

    def test_parse_create_file(self):
        content = '[aibuilder_change file="test.py"]\n[aibuilder_action type="create_file"]\n[aibuilder_file_content]\nprint("hello")\n[aibuilder_end_file_content]\n[aibuilder_end_action]'
        changes = FileParser.parse_custom_format(content)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['file'], 'test.py')
        self.assertEqual(changes[0]['actions'][0]['action'], 'create_file')
        self.assertEqual(changes[0]['actions'][0]['file_content'], ['print("hello")'])

    def test_parse_remove_file(self):
        content = '[aibuilder_change file="old.py"]\n[aibuilder_action type="remove_file"]\n[aibuilder_end_action]'
        changes = FileParser.parse_custom_format(content)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['file'], 'old.py')
        self.assertEqual(changes[0]['actions'][0]['action'], 'remove_file')

    def test_parse_replace_file(self):
        content = '[aibuilder_change file="test.py"]\n[aibuilder_action type="replace_file"]\n[aibuilder_file_content]\nnew content\n[aibuilder_end_file_content]\n[aibuilder_end_action]'
        changes = FileParser.parse_custom_format(content)
        self.assertEqual(changes[0]['actions'][0]['action'], 'replace_file')

    def test_parse_replace_section(self):
        content = '[aibuilder_change file="test.py"]\n[aibuilder_action type="replace_section"]\n[aibuilder_original_content]\nold line\n[aibuilder_end_original_content]\n[aibuilder_file_content]\nnew line\n[aibuilder_end_file_content]\n[aibuilder_end_action]'
        changes = FileParser.parse_custom_format(content)
        action = changes[0]['actions'][0]
        self.assertEqual(action['action'], 'replace_section')
        self.assertEqual(action['original_content'], 'old line\n')
        self.assertEqual(action['file_content'], ['new line'])

    def test_parse_multiple_changes(self):
        content = '[aibuilder_change file="a.py"]\n[aibuilder_action type="create_file"]\n[aibuilder_file_content]\na\n[aibuilder_end_file_content]\n[aibuilder_end_action]\n[aibuilder_change file="b.py"]\n[aibuilder_action type="remove_file"]\n[aibuilder_end_action]'
        changes = FileParser.parse_custom_format(content)
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[0]['file'], 'a.py')
        self.assertEqual(changes[1]['file'], 'b.py')

    def test_parse_with_think_block(self):
        content = '<think>thinking...\</think>\n[aibuilder_change file="test.py"]\n[aibuilder_action type="create_file"]\n[aibuilder_file_content]\nhello\n[aibuilder_end_file_content]\n[aibuilder_end_action]'
        changes = FileParser.parse_custom_format(content)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['file'], 'test.py')

    def test_parse_optional_brackets(self):
        """Test that square brackets before tags are optional."""
        content = 'aibuilder_change file="test.py"]\naibuilder_action type="create_file"]\naibuilder_file_content]\nhello\naibuilder_end_file_content]\naibuilder_end_action]'
        changes = FileParser.parse_custom_format(content)
        self.assertEqual(len(changes), 1)

    def test_escape_unescape_newlines(self):
        original = "line1\nline2\r\nline3"
        escaped = FileParser.escape_newline_sequences(original)
        self.assertIn('<<LITERAL_NEWLINE>>', escaped)
        self.assertIn('<<LITERAL_CRLF>>', escaped)
        restored = FileParser.unescape_newline_sequences(escaped)
        self.assertEqual(restored, original)

    def test_escape_literal_newline_sequences(self):
        original = r"line1\\nline2"
        escaped = FileParser.escape_newline_sequences(original)
        self.assertIn('<<LITERAL_ESCAPED_NEWLINE>>', escaped)
        restored = FileParser.unescape_newline_sequences(escaped)
        self.assertEqual(restored, original)


class TestFileModifier(unittest.TestCase):
    """Tests for file modification operations."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.test_dir, ignore_errors=True))

    def test_apply_create_file(self):
        changes = [{
            'file': 'test.txt',
            'actions': [{'action': 'create_file', 'file_content': ['hello', 'world']}]
        }]
        incomplete = FileModifier.apply_modifications(changes, self.test_dir, dry_run=False)
        self.assertEqual(len(incomplete), 0)
        with open(os.path.join(self.test_dir, 'test.txt'), 'r') as f:
            self.assertEqual(f.read(), 'hello\nworld')

    def test_apply_remove_file(self):
        test_file = os.path.join(self.test_dir, 'remove_me.txt')
        with open(test_file, 'w') as f:
            f.write('delete me')
        changes = [{
            'file': 'remove_me.txt',
            'actions': [{'action': 'remove_file'}]
        }]
        FileModifier.apply_modifications(changes, self.test_dir, dry_run=False)
        self.assertFalse(os.path.exists(test_file))

    def test_apply_remove_protected_file(self):
        """Should refuse to remove protected files."""
        test_file = os.path.join(self.test_dir, 'pre.ps1')
        with open(test_file, 'w') as f:
            f.write('# protected')
        changes = [{
            'file': 'pre.ps1',
            'actions': [{'action': 'remove_file'}]
        }]
        incomplete = FileModifier.apply_modifications(changes, self.test_dir, dry_run=False)
        self.assertTrue(os.path.exists(test_file))

    def test_apply_replace_file(self):
        test_file = os.path.join(self.test_dir, 'replace.txt')
        with open(test_file, 'w') as f:
            f.write('old content')
        changes = [{
            'file': 'replace.txt',
            'actions': [{'action': 'replace_file', 'file_content': ['new content']}]
        }]
        FileModifier.apply_modifications(changes, self.test_dir, dry_run=False)
        with open(test_file, 'r') as f:
            self.assertEqual(f.read(), 'new content')

    def test_apply_replace_section(self):
        test_file = os.path.join(self.test_dir, 'section.txt')
        with open(test_file, 'w') as f:
            f.write('line1\nold section\nline3')
        changes = [{
            'file': 'section.txt',
            'actions': [{
                'action': 'replace_section',
                'original_content': 'old section',
                'file_content': ['new section']
            }]
        }]
        FileModifier.apply_modifications(changes, self.test_dir, dry_run=False)
        with open(test_file, 'r') as f:
            self.assertIn('new section', f.read())

    def test_apply_dry_run(self):
        changes = [{
            'file': 'dry.txt',
            'actions': [{'action': 'create_file', 'file_content': ['test']}]
        }]
        FileModifier.apply_modifications(changes, self.test_dir, dry_run=True)
        self.assertFalse(os.path.exists(os.path.join(self.test_dir, 'dry.txt')))

    def test_apply_creates_backup(self):
        test_file = os.path.join(self.test_dir, 'backup.txt')
        with open(test_file, 'w') as f:
            f.write('original')
        changes = [{
            'file': 'backup.txt',
            'actions': [{'action': 'replace_file', 'file_content': ['modified']}]
        }]
        FileModifier.apply_modifications(changes, self.test_dir, dry_run=False)
        self.assertTrue(os.path.exists(test_file + '.bak'))

    def test_sanitize_path_traversal(self):
        """Should prevent directory traversal."""
        with self.assertRaises(ValueError):
            FileModifier._sanitize_path('../../../etc/passwd', '/home/user')

    def test_sanitize_absolute_path(self):
        """Absolute paths should be allowed."""
        result = FileModifier._sanitize_path('/etc/passwd', '/home/user')
        self.assertEqual(result, '/etc/passwd')


class TestActionManager(unittest.TestCase):
    """Tests for action serialization."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.test_dir, ignore_errors=True))

    def test_save_and_load_actions(self):
        actions = [
            {'file': 'test.txt', 'action': {'action': 'create_file', 'file_content': ['hello']}}
        ]
        filepath = os.path.join(self.test_dir, 'actions.txt')
        ActionManager.save_actions(actions, filepath)
        loaded = ActionManager.load_actions(filepath)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]['file'], 'test.txt')


class TestSecurity(unittest.TestCase):
    """Tests for security helpers."""

    def test_ensure_under_root_valid(self):
        result = ensure_under_root('subdir/file.txt', '/project')
        self.assertEqual(result, os.path.normpath('/project/subdir/file.txt'))

    def test_ensure_under_root_escape(self):
        with self.assertRaises(SecurityError):
            ensure_under_root('../etc/passwd', '/project')

    def test_ensure_under_root_exact_match(self):
        result = ensure_under_root('', '/project')
        self.assertEqual(result, os.path.normpath('/project'))

    def test_validate_tool_params_missing(self):
        with self.assertRaises(ToolError):
            validate_tool_params({}, {'path': 'string'})

    def test_validate_tool_params_valid(self):
        result = validate_tool_params({'path': 'test.py'}, {'path': 'string'})
        self.assertEqual(result['path'], 'test.py')

    def test_validate_tool_params_wrong_type(self):
        with self.assertRaises(ToolError):
            validate_tool_params({'path': 123}, {'path': 'string'})


class TestToolResult(unittest.TestCase):
    """Tests for ToolResult."""

    def test_to_dict(self):
        result = ToolResult(True, 'content', 'error', ['file.txt'], 'summary')
        d = result.to_dict()
        self.assertEqual(d['success'], True)
        self.assertEqual(d['content'], 'content')
        self.assertEqual(d['error'], 'error')
        self.assertEqual(d['file_paths'], ['file.txt'])
        self.assertEqual(d['summary'], 'summary')

    def test_defaults(self):
        result = ToolResult(True, 'ok')
        self.assertEqual(result.file_paths, [])
        self.assertEqual(result.summary, '')


class TestToolCalls(unittest.TestCase):
    """Tests for tool call parsing."""

    def test_parse_single_tool_call(self):
        response = '[TOOL:list_directory{path:"src",max_depth:"1"}]'
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'list_directory')
        self.assertEqual(calls[0][1]['path'], 'src')

    def test_parse_multiple_tool_calls(self):
        response = '[TOOL:read_file{path:"a.py"}]\n[TOOL:read_file{path:"b.py"}]'
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 2)

    def test_parse_no_tool_calls(self):
        response = 'Just some text'
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 0)

    def test_parse_with_whitespace(self):
        response = '[TOOL: list_directory { path : "src" } ]'
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 1)

    def test_is_done_with_summary(self):
        response = 'Here are my changes\n[DONE] Added new feature'
        done, summary = is_done(response)
        self.assertTrue(done)
        self.assertEqual(summary, 'Added new feature')

    def test_is_done_no_summary(self):
        response = '[DONE]'
        done, summary = is_done(response)
        self.assertTrue(done)
        self.assertEqual(summary, '')

    def test_is_done_false(self):
        response = 'Working on it...'
        done, summary = is_done(response)
        self.assertFalse(done)


class TestBuildUserPrompt(unittest.TestCase):
    """Tests for prompt building."""

    def test_build_user_prompt(self):
        prompt = build_user_prompt('Add a feature')
        self.assertIn('TASK INSTRUCTIONS:', prompt)
        self.assertIn('Add a feature', prompt)
        self.assertIn('Begin by exploring', prompt)

    def test_build_user_prompt_with_context(self):
        prompt = build_user_prompt('Add a feature', 'Context: old code')
        self.assertIn('RELEVANT CONTEXT:', prompt)
        self.assertIn('old code', prompt)


class TestFileTools(unittest.TestCase):
    """Tests for file system tools."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.test_dir, ignore_errors=True))
        # Create test files
        os.makedirs(os.path.join(self.test_dir, 'subdir'))
        with open(os.path.join(self.test_dir, 'test.py'), 'w') as f:
            f.write('print("hello")')
        with open(os.path.join(self.test_dir, 'subdir', 'nested.py'), 'w') as f:
            f.write('print("nested")')

    def test_list_directory(self):
        tool = ListDirectoryTool(self.test_dir)
        result = tool.execute({'path': '', 'max_depth': '1'})
        self.assertTrue(result.success)
        entries = json.loads(result.content)
        names = [e['name'] for e in entries]
        self.assertIn('test.py', names)
        self.assertIn('subdir', names)

    def test_list_directory_max_depth(self):
        tool = ListDirectoryTool(self.test_dir)
        result = tool.execute({'path': '', 'max_depth': '0'})
        entries = json.loads(result.content)
        names = [e['name'] for e in entries]
        self.assertIn('test.py', names)
        # Should not recurse into subdir
        for e in entries:
            if e['name'] == 'subdir':
                self.assertEqual(e['type'], 'directory')

    def test_read_file(self):
        tool = ReadFileTool(self.test_dir)
        result = tool.execute({'path': 'test.py'})
        self.assertTrue(result.success)
        self.assertIn('print("hello")', result.content)

    def test_read_file_not_found(self):
        tool = ReadFileTool(self.test_dir)
        result = tool.execute({'path': 'missing.py'})
        self.assertFalse(result.success)

    def test_read_file_line_range(self):
        tool = ReadFileTool(self.test_dir)
        result = tool.execute({'path': 'test.py', 'start_line': '1', 'end_line': '1'})
        self.assertTrue(result.success)

    def test_write_file(self):
        tool = WriteFileTool(self.test_dir)
        result = tool.execute({'path': 'new.txt', 'content': 'hello world'})
        self.assertTrue(result.success)
        with open(os.path.join(self.test_dir, 'new.txt'), 'r') as f:
            self.assertEqual(f.read(), 'hello world')

    def test_write_file_creates_dirs(self):
        tool = WriteFileTool(self.test_dir)
        result = tool.execute({'path': 'subdir/deep/nested.txt', 'content': 'deep'})
        self.assertTrue(result.success)
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, 'subdir', 'deep', 'nested.txt')))

    def test_edit_file(self):
        tool = EditFileTool(self.test_dir)
        result = tool.execute({
            'path': 'test.py',
            'original_text': 'print("hello")',
            'new_text': 'print("world")'
        })
        self.assertTrue(result.success)
        with open(os.path.join(self.test_dir, 'test.py'), 'r') as f:
            self.assertIn('print("world")', f.read())

    def test_edit_file_not_found(self):
        tool = EditFileTool(self.test_dir)
        result = tool.execute({
            'path': 'missing.py',
            'original_text': 'old',
            'new_text': 'new'
        })
        self.assertFalse(result.success)

    def test_edit_file_original_not_found(self):
        tool = EditFileTool(self.test_dir)
        result = tool.execute({
            'path': 'test.py',
            'original_text': 'nonexistent text',
            'new_text': 'new'
        })
        self.assertFalse(result.success)

    def test_delete_file(self):
        tool = DeleteFileTool(self.test_dir)
        result = tool.execute({'path': 'test.py'})
        self.assertTrue(result.success)
        self.assertFalse(os.path.exists(os.path.join(self.test_dir, 'test.py')))

    def test_delete_file_not_found(self):
        tool = DeleteFileTool(self.test_dir)
        result = tool.execute({'path': 'missing.py'})
        self.assertFalse(result.success)

    def test_delete_protected_file(self):
        """Should refuse to delete backup files."""
        backup = os.path.join(self.test_dir, 'test.py.bak')
        with open(backup, 'w') as f:
            f.write('backup')
        tool = DeleteFileTool(self.test_dir)
        result = tool.execute({'path': 'test.py.bak'})
        self.assertFalse(result.success)
        self.assertTrue(os.path.exists(backup))

    def test_search_files(self):
        tool = SearchFilesTool(self.test_dir)
        result = tool.execute({'pattern': '*.py', 'search_dir': ''})
        self.assertTrue(result.success)
        matches = result.content.strip().split('\n')
        self.assertIn('test.py', matches)
        self.assertIn('subdir/nested.py', matches)

    def test_grep_code(self):
        tool = GrepCodeTool(self.test_dir)
        result = tool.execute({'pattern': 'hello', 'search_dir': ''})
        self.assertTrue(result.success)
        matches = json.loads(result.content)
        self.assertTrue(len(matches) > 0)
        self.assertEqual(matches[0]['file'], 'test.py')
        self.assertIn('hello', matches[0]['text'])

    def test_grep_code_regex(self):
        tool = GrepCodeTool(self.test_dir)
        result = tool.execute({'pattern': 'print\\(', 'search_dir': ''})
        self.assertTrue(result.success)
        matches = json.loads(result.content)
        self.assertTrue(len(matches) > 0)

    def test_grep_code_invalid_regex(self):
        tool = GrepCodeTool(self.test_dir)
        result = tool.execute({'pattern': '[invalid', 'search_dir': ''})
        self.assertFalse(result.success)

    def test_get_file_info(self):
        tool = GetFileInfoTool(self.test_dir)
        result = tool.execute({'path': 'test.py'})
        self.assertTrue(result.success)
        info = json.loads(result.content)
        self.assertEqual(info['language'], 'python')
        self.assertEqual(info['extension'], '.py')
        self.assertTrue(info['size'] > 0)

    def test_get_file_info_not_found(self):
        tool = GetFileInfoTool(self.test_dir)
        result = tool.execute({'path': 'missing.py'})
        self.assertFalse(result.success)

    def test_search_files_with_file_pattern(self):
        tool = SearchFilesTool(self.test_dir)
        result = tool.execute({'pattern': '*.py', 'search_dir': 'subdir'})
        self.assertTrue(result.success)
        matches = result.content.strip().split('\n')
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0], 'subdir/nested.py')


class TestCheckSyntax(unittest.TestCase):
    """Tests for syntax checking tools."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.test_dir, ignore_errors=True))

    def test_check_python_valid(self):
        test_file = os.path.join(self.test_dir, 'valid.py')
        with open(test_file, 'w') as f:
            f.write('def hello():\n    pass')
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'valid.py'})
        self.assertTrue(result.success)

    def test_check_python_invalid(self):
        test_file = os.path.join(self.test_dir, 'invalid.py')
        with open(test_file, 'w') as f:
            f.write('def hello(:')
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'invalid.py'})
        self.assertFalse(result.success)

    def test_check_python_not_found(self):
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'missing.py'})
        self.assertFalse(result.success)

    def test_check_json_valid(self):
        test_file = os.path.join(self.test_dir, 'valid.json')
        with open(test_file, 'w') as f:
            f.write('{"key": "value"}')
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'valid.json'})
        self.assertTrue(result.success)

    def test_check_json_invalid(self):
        test_file = os.path.join(self.test_dir, 'invalid.json')
        with open(test_file, 'w') as f:
            f.write('{"key": invalid}')
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'invalid.json'})
        self.assertFalse(result.success)

    def test_check_xml_valid(self):
        test_file = os.path.join(self.test_dir, 'valid.xml')
        with open(test_file, 'w') as f:
            f.write('<root><child/></root>')
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'valid.xml'})
        self.assertTrue(result.success)

    def test_check_xml_invalid(self):
        test_file = os.path.join(self.test_dir, 'invalid.xml')
        with open(test_file, 'w') as f:
            f.write('<root><child></root>')
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'invalid.xml'})
        self.assertFalse(result.success)

    def test_check_unknown_extension(self):
        test_file = os.path.join(self.test_dir, 'unknown.xyz')
        with open(test_file, 'w') as f:
            f.write('content')
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'unknown.xyz'})
        self.assertFalse(result.success)


class TestFindSymbol(unittest.TestCase):
    """Tests for symbol search tool."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.test_dir, ignore_errors=True))
        with open(os.path.join(self.test_dir, 'test.py'), 'w') as f:
            f.write('class MyClass:\n    def my_method(self):\n        pass\n')

    def test_find_symbol_python(self):
        tool = FindSymbolTool(self.test_dir)
        result = tool.execute({'symbol': 'MyClass', 'language': 'python'})
        self.assertTrue(result.success)
        matches = json.loads(result.content)
        self.assertTrue(len(matches) > 0)

    def test_find_symbol_any_language(self):
        tool = FindSymbolTool(self.test_dir)
        result = tool.execute({'symbol': 'my_method'})
        self.assertTrue(result.success)


class TestEngineConfig(unittest.TestCase):
    """Tests for EngineConfig."""

    def test_use_local_model_default(self):
        with patch.dict(os.environ, {}, clear=True):
            from agent_engine.config import EngineConfig
            self.assertFalse(EngineConfig.use_local_model())

    def test_use_local_model_true(self):
        with patch.dict(os.environ, {'USE_LOCAL_MODEL': 'true'}):
            from agent_engine.config import EngineConfig
            self.assertTrue(EngineConfig.use_local_model())

    def test_use_custom_endpoint_default(self):
        with patch.dict(os.environ, {}, clear=True):
            from agent_engine.config import EngineConfig
            self.assertFalse(EngineConfig.use_custom_endpoint())

    def test_use_custom_endpoint_true(self):
        with patch.dict(os.environ, {'USE_CUSTOM_ENDPOINT': 'true'}):
            from agent_engine.config import EngineConfig
            self.assertTrue(EngineConfig.use_custom_endpoint())

    def test_get_custom_endpoint_url(self):
        with patch.dict(os.environ, {'CUSTOM_ENDPOINT_URL': 'https://test.com'}):
            from agent_engine.config import EngineConfig
            self.assertEqual(EngineConfig.get_custom_endpoint_url(), 'https://test.com')

    def test_get_custom_model_name(self):
        with patch.dict(os.environ, {'CUSTOM_MODEL_NAME': 'llama3'}):
            from agent_engine.config import EngineConfig
            self.assertEqual(EngineConfig.get_custom_model_name(), 'llama3')

    def test_get_custom_max_tokens(self):
        with patch.dict(os.environ, {'CUSTOM_MAX_TOKENS': '4096'}):
            from agent_engine.config import EngineConfig
            self.assertEqual(EngineConfig.get_custom_max_tokens(), 4096)

    def test_get_custom_verify_ssl(self):
        with patch.dict(os.environ, {'CUSTOM_VERIFY_SSL': 'true'}):
            from agent_engine.config import EngineConfig
            self.assertTrue(EngineConfig.get_custom_verify_ssl())

    def test_get_enabled_tools(self):
        with patch.dict(os.environ, {'AIB_ENABLED_TOOLS': '["read_file", "write_file"]'}):
            from agent_engine.config import EngineConfig
            tools = EngineConfig.get_enabled_tools()
            self.assertEqual(tools, ['read_file', 'write_file'])

    def test_get_enabled_tools_invalid_json(self):
        with patch.dict(os.environ, {'AIB_ENABLED_TOOLS': 'invalid'}):
            from agent_engine.config import EngineConfig
            tools = EngineConfig.get_enabled_tools()
            self.assertIsNone(tools)

    def test_get_root_directory(self):
        with patch.dict(os.environ, {}, clear=True):
            from agent_engine.config import EngineConfig
            result = EngineConfig.get_root_directory()
            self.assertIsInstance(result, str)

    def test_get_max_steps_default(self):
        with patch.dict(os.environ, {}, clear=True):
            from agent_engine.config import EngineConfig
            self.assertEqual(EngineConfig.get_max_steps(), 50)

    def test_get_temperature_default(self):
        with patch.dict(os.environ, {}, clear=True):
            from agent_engine.config import EngineConfig
            self.assertEqual(EngineConfig.get_temperature(), 0.1)

    def test_get_live_instruction_not_found(self):
        from agent_engine.config import EngineConfig
        result = EngineConfig.get_live_instruction('nonexistent_job_id')
        self.assertIsNone(result)


class TestEngineIntegration(unittest.TestCase):
    """Integration tests for the engine without actual model calls."""

    def test_parse_and_apply_full_workflow(self):
        """Test parsing LLM output and applying modifications."""
        test_dir = tempfile.mkdtemp()
        try:
            # Simulate LLM response
            llm_response = '''<think>Let me create a new file.</think>
[aibuilder_change file="new_feature.py"]
[aibuilder_action type="create_file"]
[aibuilder_file_content]
def new_feature():
    return "hello"
[aibuilder_end_file_content]
[aibuilder_end_action]'''

            changes = FileParser.parse_custom_format(llm_response)
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0]['file'], 'new_feature.py')

            incomplete = FileModifier.apply_modifications(changes, test_dir, dry_run=False)
            self.assertEqual(len(incomplete), 0)

            with open(os.path.join(test_dir, 'new_feature.py'), 'r') as f:
                content = f.read()
            self.assertIn('def new_feature():', content)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_parse_multiple_changes_with_different_actions(self):
        """Test parsing and applying a mix of action types."""
        test_dir = tempfile.mkdtemp()
        try:
            # Create a file to modify
            existing_file = os.path.join(test_dir, 'existing.py')
            with open(existing_file, 'w') as f:
                f.write('old code here')

            llm_response = '''[aibuilder_change file="existing.py"]
[aibuilder_action type="replace_section"]
[aibuilder_original_content]old code here
[aibuilder_end_original_content]
[aibuilder_file_content]new code here
[aibuilder_end_file_content]
[aibuilder_end_action]
[aibuilder_change file="new.py"]
[aibuilder_action type="create_file"]
[aibuilder_file_content]
new content
[aibuilder_end_file_content]
[aibuilder_end_action]
[aibuilder_change file="remove_me.py"]
[aibuilder_action type="remove_file"]
[aibuilder_end_action]'''

            changes = FileParser.parse_custom_format(llm_response)
            self.assertEqual(len(changes), 3)

            incomplete = FileModifier.apply_modifications(changes, test_dir, dry_run=False)
            self.assertEqual(len(incomplete), 0)

            # Verify changes
            with open(os.path.join(test_dir, 'existing.py'), 'r') as f:
                self.assertIn('new code here', f.read())
            with open(os.path.join(test_dir, 'new.py'), 'r') as f:
                self.assertIn('new content', f.read())
            self.assertFalse(os.path.exists(os.path.join(test_dir, 'remove_me.py')))
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_security_prevents_traversal_in_modifications(self):
        """Test that directory traversal is prevented in modifications."""
        test_dir = tempfile.mkdtemp()
        try:
            changes = [{
                'file': '../../../etc/passwd',
                'actions': [{'action': 'create_file', 'file_content': ['hacked']}]
            }]
            with self.assertRaises(ValueError):
                FileModifier.apply_modifications(changes, test_dir, dry_run=False)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_dry_run_does_not_write_files(self):
        """Test that dry run doesn't actually write files."""
        test_dir = tempfile.mkdtemp()
        try:
            changes = [{
                'file': 'should_not_exist.txt',
                'actions': [{'action': 'create_file', 'file_content': ['content']}]
            }]
            FileModifier.apply_modifications(changes, test_dir, dry_run=True)
            self.assertFalse(os.path.exists(os.path.join(test_dir, 'should_not_exist.txt')))
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


class TestAgentEngineConfig(unittest.TestCase):
    """Tests for AgentEngine configuration."""

    def test_build_system_prompt_includes_tools(self):
        from agent_engine.engine import build_system_prompt
        tools = [
            {'name': 'read_file', 'description': 'Read a file', 'parameters': {'path': 'string'}},
            {'name': 'write_file', 'description': 'Write a file', 'parameters': {'path': 'string', 'content': 'string'}},
        ]
        prompt = build_system_prompt(tools)
        self.assertIn('read_file', prompt)
        self.assertIn('write_file', prompt)
        self.assertIn('WORKFLOW:', prompt)
        self.assertIn('RULES:', prompt)
        self.assertIn('AVAILABLE TOOLS:', prompt)


if __name__ == '__main__':
    unittest.main()
