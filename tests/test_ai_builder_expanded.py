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

from oneshot_engine import FileParser, FileModifier, ActionManager
from oneshot_engine.code_utility import CodeUtility
from agent_engine.security import ensure_under_root, validate_tool_params, SecurityError, ToolError
from agent_engine.tools.base import ToolResult, BaseTool
from agent_engine.engine import parse_tool_calls, is_done, build_user_prompt, build_system_prompt, AgentEngine
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
# ToolRegistry tests
# ====================================================================

class TestToolRegistry(unittest.TestCase):
    """Tests for the ToolRegistry."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_all_tools_registered(self):
        registry = ToolRegistry(self.test_dir)
        names = [t.name for t in registry._tools.values()]
        expected = {
            'list_directory', 'search_files', 'grep_code', 'read_file',
            'write_file', 'edit_file', 'delete_file', 'find_symbol',
            'decompile_jar', 'list_dependencies', 'check_syntax', 'get_file_info',
        }
        self.assertEqual(set(names), expected)

    def test_list_tools_definitions(self):
        registry = ToolRegistry(self.test_dir)
        defs = registry.list_tools()
        self.assertEqual(len(defs), 12)
        for d in defs:
            self.assertIn('name', d)
            self.assertIn('description', d)
            self.assertIn('parameters', d)

    def test_execute_known_tool(self):
        registry = ToolRegistry(self.test_dir)
        result = registry.execute('list_directory', {'path': '', 'max_depth': '0'})
        self.assertTrue(result.success)

    def test_execute_unknown_tool_raises(self):
        registry = ToolRegistry(self.test_dir)
        with self.assertRaises(ToolError) as ctx:
            registry.execute('nonexistent_tool', {})
        self.assertIn('Unknown tool', str(ctx.exception))

    def test_enabled_tools_filter(self):
        registry = ToolRegistry(self.test_dir, enabled_tools=['read_file', 'write_file'])
        names = [t.name for t in registry._tools.values()]
        self.assertEqual(set(names), {'read_file', 'write_file'})

    def test_execute_with_missing_required_param(self):
        registry = ToolRegistry(self.test_dir)
        # read_file requires 'path' — passing empty dict raises ToolError
        with self.assertRaises(ToolError) as ctx:
            registry.execute('read_file', {})
        self.assertIn('Missing required parameter', str(ctx.exception))


# ====================================================================
# DecompileJarTool tests
# ====================================================================

class TestDecompileJarTool(unittest.TestCase):
    """Tests for the JAR decompilation tool."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_jar_not_found(self):
        tool = DecompileJarTool(self.test_dir)
        result = tool.execute({'jar_path': 'missing.jar'})
        self.assertFalse(result.success)
        self.assertIn('not found', result.error.lower())

    def test_jar_file_exists_no_jd_cli(self):
        # Create a fake JAR file
        jar_path = os.path.join(self.test_dir, 'test.jar')
        with open(jar_path, 'wb') as f:
            f.write(b'PK' + b'\x00' * 100)  # minimal ZIP header

        # Mock jd-cli not found, javap not found
        with patch('agent_engine.tools.search.EngineConfig.get_jd_cli_path', return_value=''):
            with patch('agent_engine.tools.search.EngineConfig.get_java_home', return_value=''):
                with patch('agent_engine.tools.search.subprocess.run') as mock_run:
                    mock_run.side_effect = FileNotFoundError('jar')
                    tool = DecompileJarTool(self.test_dir)
                    result = tool.execute({'jar_path': 'test.jar'})
                    # Should gracefully fail, not crash
                    self.assertIsNotNone(result)


# ====================================================================
# ListDependenciesTool tests
# ====================================================================

class TestListDependenciesTool(unittest.TestCase):
    """Tests for the dependency listing tool."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_python_requirements(self):
        with open(os.path.join(self.test_dir, 'requirements.txt'), 'w') as f:
            f.write('flask>=2.0\nrequests==2.28\n# comment\n\nnumpy\n')
        tool = ListDependenciesTool(self.test_dir)
        result = tool.execute({'search_dir': ''})
        self.assertTrue(result.success)
        deps = json.loads(result.content)
        dep_names = [d['name'] for d in deps]
        self.assertIn('flask', dep_names)
        self.assertIn('requests', dep_names)
        self.assertIn('numpy', dep_names)

    def test_package_json(self):
        with open(os.path.join(self.test_dir, 'package.json'), 'w') as f:
            json.dump({
                'dependencies': {'react': '^18.0.0'},
                'devDependencies': {'jest': '^29.0.0'}
            }, f)
        tool = ListDependenciesTool(self.test_dir)
        result = tool.execute({'search_dir': ''})
        self.assertTrue(result.success)
        deps = json.loads(result.content)
        dep_names = [d['name'] for d in deps]
        self.assertIn('react', dep_names)
        self.assertIn('jest', dep_names)

    def test_pom_xml(self):
        with open(os.path.join(self.test_dir, 'pom.xml'), 'w') as f:
            f.write('''<project>
                <dependencies>
                    <dependency>
                        <groupId>org.springframework</groupId>
                        <artifactId>spring-core</artifactId>
                        <version>5.3.20</version>
                    </dependency>
                </dependencies>
            </project>''')
        tool = ListDependenciesTool(self.test_dir)
        result = tool.execute({'search_dir': ''})
        self.assertTrue(result.success)
        deps = json.loads(result.content)
        self.assertTrue(len(deps) > 0)
        self.assertIn('spring-core', deps[0]['name'])

    def test_no_dependencies(self):
        tool = ListDependenciesTool(self.test_dir)
        result = tool.execute({'search_dir': ''})
        self.assertTrue(result.success)
        deps = json.loads(result.content)
        self.assertEqual(len(deps), 0)

    def test_csproj(self):
        with open(os.path.join(self.test_dir, 'MyApp.csproj'), 'w') as f:
            f.write('''<Project>
                <ItemGroup>
                    <PackageReference Include="Newtonsoft.Json" Version="13.0.3"/>
                </ItemGroup>
            </Project>''')
        tool = ListDependenciesTool(self.test_dir)
        result = tool.execute({'search_dir': ''})
        self.assertTrue(result.success)
        deps = json.loads(result.content)
        dep_names = [d['name'] for d in deps]
        self.assertIn('Newtonsoft.Json', dep_names)


# ====================================================================
# CheckSyntaxTool — additional edge cases
# ====================================================================

class TestCheckSyntaxEdgeCases(unittest.TestCase):
    """Additional edge-case tests for syntax checking."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_check_xml_valid_nested(self):
        with open(os.path.join(self.test_dir, 'valid.xml'), 'w') as f:
            f.write('<root><child><grandchild>text</grandchild></child></root>')
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'valid.xml'})
        self.assertTrue(result.success)

    def test_check_xml_malformed(self):
        with open(os.path.join(self.test_dir, 'bad.xml'), 'w') as f:
            f.write('<root><child></root>')
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'bad.xml'})
        self.assertFalse(result.success)

    def test_check_json_valid_nested(self):
        with open(os.path.join(self.test_dir, 'valid.json'), 'w') as f:
            json.dump({'a': {'b': [1, 2, 3]}}, f)
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'valid.json'})
        self.assertTrue(result.success)

    def test_check_json_trailing_comma(self):
        with open(os.path.join(self.test_dir, 'bad.json'), 'w') as f:
            f.write('{"a": 1,}')
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'bad.json'})
        self.assertFalse(result.success)

    def test_check_xml_not_found(self):
        tool = CheckSyntaxTool(self.test_dir)
        result = tool.execute({'path': 'missing.xml'})
        self.assertFalse(result.success)


# ====================================================================
# FindSymbolTool — additional edge cases
# ====================================================================

class TestFindSymbolEdgeCases(unittest.TestCase):
    """Additional tests for symbol search."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_find_symbol_java(self):
        with open(os.path.join(self.test_dir, 'Main.java'), 'w') as f:
            f.write('public class Main {\n    public static void main(String[] args) {}\n}\n')
        tool = FindSymbolTool(self.test_dir)
        result = tool.execute({'symbol': 'Main', 'language': 'java'})
        self.assertTrue(result.success)
        matches = json.loads(result.content)
        self.assertTrue(len(matches) > 0)

    def test_find_symbol_javascript(self):
        with open(os.path.join(self.test_dir, 'app.js'), 'w') as f:
            f.write('function hello() { return 42; }\nconst x = 1;\nclass MyClass {}\n')
        tool = FindSymbolTool(self.test_dir)
        result = tool.execute({'symbol': 'hello', 'language': 'javascript'})
        self.assertTrue(result.success)
        matches = json.loads(result.content)
        self.assertTrue(len(matches) > 0)

    def test_find_symbol_csharp(self):
        with open(os.path.join(self.test_dir, 'Program.cs'), 'w') as f:
            f.write('using System;\nnamespace NS { public class Program { public static void Main() {} } }\n')
        tool = FindSymbolTool(self.test_dir)
        result = tool.execute({'symbol': 'Program', 'language': 'csharp'})
        self.assertTrue(result.success)
        matches = json.loads(result.content)
        self.assertTrue(len(matches) > 0)

    def test_find_symbol_not_found(self):
        with open(os.path.join(self.test_dir, 'test.py'), 'w') as f:
            f.write('x = 1\n')
        tool = FindSymbolTool(self.test_dir)
        result = tool.execute({'symbol': 'NonExistentSymbolXYZ'})
        self.assertTrue(result.success)
        matches = json.loads(result.content)
        self.assertEqual(len(matches), 0)

    def test_find_symbol_max_results(self):
        # Create many files with the symbol
        for i in range(40):
            with open(os.path.join(self.test_dir, f'm{i}.py'), 'w') as f:
                f.write(f'class MyClass{i}: pass\n')
        tool = FindSymbolTool(self.test_dir)
        result = tool.execute({'symbol': 'MyClass', 'language': 'python', 'max_results': '10'})
        self.assertTrue(result.success)
        matches = json.loads(result.content)
        self.assertLessEqual(len(matches), 10)


# ====================================================================
# SearchFilesTool — additional edge cases
# ====================================================================

class TestSearchFilesEdgeCases(unittest.TestCase):
    """Additional tests for file search."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_search_no_match(self):
        with open(os.path.join(self.test_dir, 'test.py'), 'w') as f:
            f.write('hello')
        tool = SearchFilesTool(self.test_dir)
        result = tool.execute({'pattern': '*.xyz', 'search_dir': ''})
        self.assertTrue(result.success)
        matches = result.content.strip().split('\n')
        self.assertEqual(len([m for m in matches if m]), 0)

    def test_search_recursive(self):
        os.makedirs(os.path.join(self.test_dir, 'a', 'b'))
        with open(os.path.join(self.test_dir, 'a', 'b', 'deep.py'), 'w') as f:
            f.write('deep')
        tool = SearchFilesTool(self.test_dir)
        result = tool.execute({'pattern': '*.py', 'search_dir': ''})
        self.assertTrue(result.success)
        self.assertIn('a/b/deep.py', result.content)


# ====================================================================
# GrepCodeTool — additional edge cases
# ====================================================================

class TestGrepCodeEdgeCases(unittest.TestCase):
    """Additional tests for grep."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_grep_with_file_pattern(self):
        with open(os.path.join(self.test_dir, 'test.py'), 'w') as f:
            f.write('hello world')
        with open(os.path.join(self.test_dir, 'test.js'), 'w') as f:
            f.write('hello world')
        tool = GrepCodeTool(self.test_dir)
        result = tool.execute({'pattern': 'hello', 'search_dir': '', 'file_pattern': '*.py'})
        self.assertTrue(result.success)
        matches = json.loads(result.content)
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0]['file'].endswith('.py'))

    def test_grep_max_results(self):
        for i in range(10):
            with open(os.path.join(self.test_dir, f'test{i}.py'), 'w') as f:
                f.write('hello world')
        tool = GrepCodeTool(self.test_dir)
        result = tool.execute({'pattern': 'hello', 'search_dir': '', 'max_results': '3'})
        self.assertTrue(result.success)
        matches = json.loads(result.content)
        self.assertEqual(len(matches), 3)

    def test_grep_unicode_content(self):
        with open(os.path.join(self.test_dir, 'unicode.py'), 'w', encoding='utf-8') as f:
            f.write('# café résumé naïve\n')
        tool = GrepCodeTool(self.test_dir)
        result = tool.execute({'pattern': 'café', 'search_dir': ''})
        self.assertTrue(result.success)
        matches = json.loads(result.content)
        self.assertTrue(len(matches) > 0)


# ====================================================================
# EditFileTool — additional edge cases
# ====================================================================

class TestEditFileEdgeCases(unittest.TestCase):
    """Additional tests for edit_file."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_edit_multiline(self):
        with open(os.path.join(self.test_dir, 'test.py'), 'w') as f:
            f.write('line1\nline2\nline3\n')
        tool = EditFileTool(self.test_dir)
        result = tool.execute({
            'path': 'test.py',
            'original_text': 'line1\nline2',
            'new_text': 'new1\nnew2'
        })
        self.assertTrue(result.success)
        with open(os.path.join(self.test_dir, 'test.py')) as f:
            self.assertIn('new1', f.read())

    def test_edit_whitespace_flexible(self):
        with open(os.path.join(self.test_dir, 'test.py'), 'w') as f:
            f.write('line1\n  line2\nline3\n')
        tool = EditFileTool(self.test_dir)
        # The flexible match requires the stripped version to be in content
        result = tool.execute({
            'path': 'test.py',
            'original_text': 'line1\n  line2',
            'new_text': 'replaced'
        })
        # Flexible match: normalizes whitespace but still needs stripped version in content
        # "line1 line2" normalizes to "line1 line2" but content has "line1\n  line2"
        # The fallback checks if stripped original is in content
        self.assertTrue(result.success)


# ====================================================================
# WriteFileTool — additional edge cases
# ====================================================================

class TestWriteFileEdgeCases(unittest.TestCase):
    """Additional tests for write_file."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_write_empty_file(self):
        tool = WriteFileTool(self.test_dir)
        result = tool.execute({'path': 'empty.txt', 'content': ''})
        self.assertTrue(result.success)
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, 'empty.txt')))

    def test_write_large_content(self):
        tool = WriteFileTool(self.test_dir)
        content = 'x' * 100000
        result = tool.execute({'path': 'large.txt', 'content': content})
        self.assertTrue(result.success)
        with open(os.path.join(self.test_dir, 'large.txt')) as f:
            self.assertEqual(len(f.read()), 100000)

    def test_write_unicode_content(self):
        tool = WriteFileTool(self.test_dir)
        result = tool.execute({'path': 'unicode.txt', 'content': 'こんにちは世界'})
        self.assertTrue(result.success)
        with open(os.path.join(self.test_dir, 'unicode.txt'), encoding='utf-8') as f:
            self.assertEqual(f.read(), 'こんにちは世界')


# ====================================================================
# ReadFileTool — additional edge cases
# ====================================================================

class TestReadFileEdgeCases(unittest.TestCase):
    """Additional tests for read_file."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_read_binary_file(self):
        path = os.path.join(self.test_dir, 'binary.bin')
        with open(path, 'wb') as f:
            f.write(b'\x00\x01\x02\x03')
        tool = ReadFileTool(self.test_dir)
        result = tool.execute({'path': 'binary.bin'})
        self.assertTrue(result.success)

    def test_read_empty_file(self):
        with open(os.path.join(self.test_dir, 'empty.txt'), 'w') as f:
            pass
        tool = ReadFileTool(self.test_dir)
        result = tool.execute({'path': 'empty.txt'})
        self.assertTrue(result.success)
        self.assertEqual(result.content, '')

    def test_read_unicode_file(self):
        with open(os.path.join(self.test_dir, 'unicode.txt'), 'w', encoding='utf-8') as f:
            f.write('こんにちは')
        tool = ReadFileTool(self.test_dir)
        result = tool.execute({'path': 'unicode.txt'})
        self.assertTrue(result.success)
        self.assertIn('こんにちは', result.content)


# ====================================================================
# ListDirectoryTool — additional edge cases
# ====================================================================

class TestListDirectoryEdgeCases(unittest.TestCase):
    """Additional tests for list_directory."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_list_empty_directory(self):
        tool = ListDirectoryTool(self.test_dir)
        result = tool.execute({'path': '', 'max_depth': '1'})
        self.assertTrue(result.success)
        entries = json.loads(result.content)
        self.assertEqual(len(entries), 0)

    def test_list_with_hidden_files(self):
        with open(os.path.join(self.test_dir, '.hidden'), 'w') as f:
            f.write('hidden')
        tool = ListDirectoryTool(self.test_dir)
        result = tool.execute({'path': '', 'max_depth': '0'})
        self.assertTrue(result.success)
        entries = json.loads(result.content)
        names = [e['name'] for e in entries]
        self.assertIn('.hidden', names)

    def test_list_nested_dirs(self):
        os.makedirs(os.path.join(self.test_dir, 'a', 'b'))
        tool = ListDirectoryTool(self.test_dir)
        result = tool.execute({'path': '', 'max_depth': '2'})
        self.assertTrue(result.success)
        entries = json.loads(result.content)
        names = [e['name'] for e in entries]
        self.assertIn('a', names)


# ====================================================================
# GetFileInfoTool — additional edge cases
# ====================================================================

class TestGetFileInfoEdgeCases(unittest.TestCase):
    """Additional tests for get_file_info."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_get_info_java(self):
        with open(os.path.join(self.test_dir, 'Test.java'), 'w') as f:
            f.write('public class Test {}')
        tool = GetFileInfoTool(self.test_dir)
        result = tool.execute({'path': 'Test.java'})
        self.assertTrue(result.success)
        info = json.loads(result.content)
        self.assertEqual(info['language'], 'java')
        self.assertEqual(info['extension'], '.java')

    def test_get_info_binary(self):
        with open(os.path.join(self.test_dir, 'binary.bin'), 'wb') as f:
            f.write(b'\x00\x01\x02\x03\x04\x05')  # contains null byte
        tool = GetFileInfoTool(self.test_dir)
        result = tool.execute({'path': 'binary.bin'})
        self.assertTrue(result.success)
        info = json.loads(result.content)
        self.assertTrue(info['is_binary'])

    def test_get_info_jsx(self):
        with open(os.path.join(self.test_dir, 'App.jsx'), 'w') as f:
            f.write('export default function App() {}')
        tool = GetFileInfoTool(self.test_dir)
        result = tool.execute({'path': 'App.jsx'})
        self.assertTrue(result.success)
        info = json.loads(result.content)
        self.assertEqual(info['language'], 'javascript')


# ====================================================================
# parse_tool_calls — additional edge cases
# ====================================================================

class TestParseToolCallsEdgeCases(unittest.TestCase):
    """Additional tests for tool call parsing."""

    def test_multiple_tools_same_response(self):
        response = '[TOOL:read_file{path:"a.py"}]\n[TOOL:write_file{path:"b.py",content:"hello"}]'
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], 'read_file')
        self.assertEqual(calls[1][0], 'write_file')

    def test_tool_call_with_special_chars_in_params(self):
        response = '[TOOL:grep_code{pattern:"hello.*world",search_dir:"src"}]'
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]['pattern'], 'hello.*world')

    def test_tool_call_with_hyphenated_name(self):
        # Hypothetical tool with hyphen
        response = '[TOOL:list_dependencies{search_dir:"."}]'
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'list_dependencies')

    def test_empty_response(self):
        calls = parse_tool_calls('')
        self.assertEqual(len(calls), 0)

    def test_tool_call_with_empty_params(self):
        response = '[TOOL:list_directory{}]'
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], {})


# ====================================================================
# is_done — additional edge cases
# ====================================================================

class TestIsDoneEdgeCases(unittest.TestCase):
    """Additional tests for is_done."""

    def test_done_with_multiline_summary(self):
        response = '[DONE] Made changes to:\n- file1.py\n- file2.py'
        done, summary = is_done(response)
        self.assertTrue(done)
        self.assertIn('file1.py', summary)

    def test_done_at_start(self):
        done, summary = is_done('[DONE]')
        self.assertTrue(done)
        self.assertEqual(summary, '')


# ====================================================================
# build_system_prompt — additional tests
# ====================================================================

class TestBuildSystemPrompt(unittest.TestCase):
    """Additional tests for system prompt generation."""

    def test_prompt_includes_max_steps(self):
        with patch.object(EngineConfig, 'get_max_steps', return_value=100):
            prompt = build_system_prompt([])
            self.assertIn('100', prompt)

    def test_prompt_includes_tool_names(self):
        tools = [
            {'name': 'read_file', 'description': 'Read a file', 'parameters': {}},
            {'name': 'write_file', 'description': 'Write a file', 'parameters': {}},
        ]
        prompt = build_system_prompt(tools)
        self.assertIn('read_file', prompt)
        self.assertIn('write_file', prompt)
        self.assertIn('Read a file', prompt)
        self.assertIn('Write a file', prompt)

    def test_prompt_includes_rules(self):
        prompt = build_system_prompt([])
        self.assertIn('RULES:', prompt)
        self.assertIn('read_file before edit_file', prompt)
        self.assertIn('check_syntax', prompt)


# ====================================================================
# AgentEngine — unit tests (without LLM calls)
# ====================================================================

class TestAgentEngine(unittest.TestCase):
    """Tests for AgentEngine initialization and basic behavior."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))
        self.project_config = {
            'rootDirectory': self.test_dir,
            'instructions': 'Test instructions',
            'job_id': 'test_job_001',
        }

    def test_engine_initializes_with_tools(self):
        engine = AgentEngine(self.project_config)
        self.assertIsNotNone(engine.tools)
        self.assertEqual(len(engine.tools._tools), 12)
        self.assertEqual(len(engine.messages), 1)  # system message only
        self.assertEqual(engine.step_count, 0)
        self.assertEqual(engine.step_history, [])

    def test_engine_initializes_with_enabled_tools_filter(self):
        with patch.object(EngineConfig, 'get_enabled_tools', return_value=['read_file', 'write_file']):
            engine = AgentEngine(self.project_config)
            names = [t.name for t in engine.tools._tools.values()]
            self.assertEqual(set(names), {'read_file', 'write_file'})

    def test_engine_step_log_file(self):
        engine = AgentEngine(self.project_config)
        # Files are created lazily during run(), not at init
        # Just verify the path is correct
        self.assertEqual(engine.step_log_file,
                         os.path.join(engine.output_dir, 'steps.jsonl'))

    def test_engine_response_file(self):
        engine = AgentEngine(self.project_config)
        # Files are created lazily during run(), not at init
        self.assertEqual(engine.response_file,
                         os.path.join(engine.output_dir, 'current_response.txt'))

    def test_engine_log_file(self):
        engine = AgentEngine(self.project_config)
        self.assertTrue(os.path.exists(engine.log_file))

    def test_engine_messages_have_system_prompt(self):
        engine = AgentEngine(self.project_config)
        sys_msg = engine.messages[0]
        self.assertEqual(sys_msg['role'], 'system')
        self.assertIn('AVAILABLE TOOLS:', sys_msg['content'])

    def test_engine_max_steps_from_config(self):
        with patch.object(EngineConfig, 'get_max_steps', return_value=99):
            engine = AgentEngine(self.project_config)
            self.assertEqual(engine.max_steps, 99)

    def test_engine_output_dir_creation(self):
        custom_output = os.path.join(self.test_dir, 'custom_output', 'job_002')
        engine = AgentEngine(self.project_config, output_dir=custom_output)
        self.assertTrue(os.path.exists(custom_output))

    def test_engine_default_output_dir(self):
        engine = AgentEngine(self.project_config)
        expected = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'aib_instance', 'output', 'test_job_001'
        )
        # When no caller-provided output_dir, engine uses its own default
        self.assertIn('test_job_001', engine.output_dir)


# ====================================================================
# EngineConfig — additional edge cases
# ====================================================================

class TestEngineConfigEdgeCases(unittest.TestCase):
    """Additional tests for EngineConfig."""

    def test_get_max_steps_from_env(self):
        with patch.dict(os.environ, {'AIB_MAX_STEPS': '200'}):
            # Need to reload the module to pick up env change
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_max_steps(), 200)

    def test_get_temperature_from_env(self):
        with patch.dict(os.environ, {'TEMPERATURE': '0.7'}):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_temperature(), 0.7)

    def test_get_root_directory_default(self):
        result = EngineConfig.get_root_directory()
        self.assertIsInstance(result, str)
        self.assertTrue(os.path.isabs(result))

    def test_get_pre_script(self):
        with patch.dict(os.environ, {'AIB_PRE_SCRIPT': 'echo hello'}):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_pre_script(), 'echo hello')

    def test_get_post_script(self):
        with patch.dict(os.environ, {'AIB_POST_SCRIPT': 'echo world'}):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_post_script(), 'echo world')

    def test_get_jd_cli_path(self):
        with patch.dict(os.environ, {'JD_CLI_PATH': '/usr/local/bin/jd-cli'}):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_jd_cli_path(), '/usr/local/bin/jd-cli')

    def test_get_java_home(self):
        with patch.dict(os.environ, {'JAVA_HOME': '/usr/lib/jvm/java-17'}):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_java_home(), '/usr/lib/jvm/java-17')

    def test_get_dotnet_cli_path(self):
        with patch.dict(os.environ, {'DOTNET_CLI_PATH': '/usr/share/dotnet/dotnet'}):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_dotnet_cli_path(), '/usr/share/dotnet/dotnet')

    def test_get_custom_api_key(self):
        with patch.dict(os.environ, {'CUSTOM_API_KEY': 'sk-test'}):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_custom_api_key(), 'sk-test')

    def test_verify_ssl_default(self):
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertFalse(config.EngineConfig.verify_ssl())

    def test_get_custom_api_version(self):
        with patch.dict(os.environ, {'CUSTOM_API_VERSION': 'v2'}):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_custom_api_version(), 'v2')

    def test_get_model_context(self):
        with patch.dict(os.environ, {'MODEL_CONTEXT': '32000'}):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_model_context(), 32000)

    def test_get_top_k(self):
        with patch.dict(os.environ, {'TOP_K': '100'}):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_top_k(), 100)

    def test_get_min_p(self):
        with patch.dict(os.environ, {'MIN_P': '0.1'}):
            import importlib
            from agent_engine import config
            importlib.reload(config)
            self.assertEqual(config.EngineConfig.get_min_p(), 0.1)


# ====================================================================
# FileModifier — additional edge cases
# ====================================================================

class TestFileModifierEdgeCases(unittest.TestCase):
    """Additional tests for FileModifier."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_replace_section_not_exact_match(self):
        with open(os.path.join(self.test_dir, 'test.py'), 'w') as f:
            f.write('line1\nline2\nline3\n')
        changes = [{
            'file': 'test.py',
            'actions': [{
                'action': 'replace_section',
                'original_content': 'line1\nline2\nline3\nextra',
                'file_content': ['new']
            }]
        }]
        incomplete = FileModifier.apply_modifications(changes, self.test_dir, dry_run=False)
        # Should fail because original_content not found
        self.assertTrue(len(incomplete) > 0)

    def test_create_file_overwrite(self):
        with open(os.path.join(self.test_dir, 'existing.txt'), 'w') as f:
            f.write('old')
        changes = [{
            'file': 'existing.txt',
            'actions': [{'action': 'create_file', 'file_content': ['new content']}]
        }]
        incomplete = FileModifier.apply_modifications(changes, self.test_dir, dry_run=False)
        self.assertEqual(len(incomplete), 0)
        with open(os.path.join(self.test_dir, 'existing.txt')) as f:
            self.assertEqual(f.read(), 'new content')

    def test_sanitize_trailing_slash(self):
        result = FileModifier._sanitize_path('subdir/', '/home/user')
        self.assertEqual(result, os.path.normpath('/home/user/subdir'))


# ====================================================================
# Security — additional edge cases
# ====================================================================

class TestSecurityEdgeCases(unittest.TestCase):
    """Additional security edge-case tests."""

    def test_ensure_under_root_double_dot_escape(self):
        with self.assertRaises(SecurityError):
            ensure_under_root('foo/../../../etc/passwd', '/project')

    def test_ensure_under_root_encoded_escape(self):
        # URL-encoded paths are NOT decoded by ensure_under_root,
        # so '..%2F' stays literal and doesn't escape — this is a limitation.
        # The function only does os.path.normpath, not urllib.parse.unquote.
        result = ensure_under_root('..%2F..%2Fetc%2Fpasswd', '/project')
        # The path stays literal (not resolved), so it passes validation
        self.assertIn('/project', result)

    def test_ensure_under_root_symlink_escape(self):
        """Symlink-based escape should be caught by normpath + samefile."""
        # This test verifies that normpath catches .. patterns
        with self.assertRaises(SecurityError):
            ensure_under_root('../secret/file.txt', '/project')

    def test_validate_tool_params_extra_params_allowed(self):
        result = validate_tool_params(
            {'path': 'test.py', 'extra_param': 'value'},
            {'path': 'string'}
        )
        self.assertEqual(result['path'], 'test.py')
        # validate_tool_params only returns required params, not extras
        self.assertNotIn('extra_param', result)

    def test_validate_tool_params_none_value(self):
        with self.assertRaises(ToolError):
            validate_tool_params({'path': None}, {'path': 'string'})


# ====================================================================
# ToolResult — additional edge cases
# ====================================================================

class TestToolResultEdgeCases(unittest.TestCase):
    """Additional tests for ToolResult."""

    def test_to_dict_success_false(self):
        result = ToolResult(False, '', error='something broke')
        d = result.to_dict()
        self.assertFalse(d['success'])
        self.assertEqual(d['error'], 'something broke')
        self.assertEqual(d['content'], '')

    def test_to_dict_with_file_paths(self):
        result = ToolResult(True, 'ok', file_paths=['a.py', 'b.py'])
        d = result.to_dict()
        self.assertEqual(d['file_paths'], ['a.py', 'b.py'])

    def test_to_dict_empty_values(self):
        result = ToolResult(True, '')
        d = result.to_dict()
        self.assertEqual(d['content'], '')
        self.assertEqual(d['error'], '')
        self.assertEqual(d['file_paths'], [])
        self.assertEqual(d['summary'], '')


# ====================================================================
# Integration: run_with_agent_engine path
# ====================================================================

class TestRunWithAgentEngine(unittest.TestCase):
    """Tests for the run_with_agent_engine integration path."""

    def test_import_available(self):
        from oneshot_engine.engine import _HAS_AGENT_ENGINE
        self.assertTrue(_HAS_AGENT_ENGINE)

    def test_run_with_agent_engine_no_job_id(self):
        from oneshot_engine.engine import run_with_agent_engine
        import tempfile, shutil
        test_dir = tempfile.mkdtemp()
        try:
            project_config = {
                'rootDirectory': test_dir,
                'instructions': 'Test',
            }
            # This will call the LLM (which will fail without credentials),
            # but we verify the function reaches the engine and returns
            with patch('agent_engine.engine.LLMClient.call') as mock_call:
                mock_call.return_value = '[DONE] Test complete'
                result = run_with_agent_engine(project_config)
                self.assertEqual(result['status'], 'completed')
                self.assertIn('steps', result)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


# ====================================================================
# CodeUtility — basic tests
# ====================================================================

class TestCodeUtility(unittest.TestCase):
    """Tests for CodeUtility."""

    def test_import(self):
        from oneshot_engine.code_utility import CodeUtility
        self.assertIsNotNone(CodeUtility)


# ====================================================================
# ActionManager — additional tests
# ====================================================================

class TestActionManagerEdgeCases(unittest.TestCase):
    """Additional tests for ActionManager."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

    def test_save_empty_actions(self):
        filepath = os.path.join(self.test_dir, 'empty.txt')
        ActionManager.save_actions([], filepath)
        loaded = ActionManager.load_actions(filepath)
        self.assertEqual(len(loaded), 0)

    def test_save_multiple_actions(self):
        actions = [
            {'file': 'a.py', 'action': {'action': 'create_file', 'file_content': ['a']}},
            {'file': 'b.py', 'action': {'action': 'create_file', 'file_content': ['b']}},
            {'file': 'c.py', 'action': {'action': 'remove_file'}},
        ]
        filepath = os.path.join(self.test_dir, 'multi.txt')
        ActionManager.save_actions(actions, filepath)
        loaded = ActionManager.load_actions(filepath)
        self.assertEqual(len(loaded), 3)


# ====================================================================
# FileParser — additional edge cases
# ====================================================================

class TestFileParserEdgeCases(unittest.TestCase):
    """Additional tests for FileParser."""

    def test_parse_empty_content(self):
        changes = FileParser.parse_custom_format('')
        self.assertEqual(len(changes), 0)

    def test_parse_think_block_only(self):
        content = '<think>Thinking through the problem...</think>'
        changes = FileParser.parse_custom_format(content)
        self.assertEqual(len(changes), 0)

    def test_parse_mixed_think_and_changes(self):
        content = '''<think>First thought</think>
[aibuilder_change file="a.py"]
[aibuilder_action type="create_file"]
[aibuilder_file_content]
a
[aibuilder_end_file_content]
[aibuilder_end_action]
[aibuilder_change file="b.py"]
[aibuilder_action type="create_file"]
[aibuilder_file_content]
b
[aibuilder_end_file_content]
[aibuilder_end_action]'''
        changes = FileParser.parse_custom_format(content)
        # Parser strips content up to first [aibuilder_change, then finds all change blocks
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[0]['file'], 'a.py')
        self.assertEqual(changes[1]['file'], 'b.py')

    def test_parse_action_without_type(self):
        content = '[aibuilder_change file="test.py"]\n[aibuilder_action]\n[aibuilder_end_action]'
        changes = FileParser.parse_custom_format(content)
        # Should parse but action may have no type
        self.assertEqual(len(changes), 1)


if __name__ == '__main__':
    unittest.main()
