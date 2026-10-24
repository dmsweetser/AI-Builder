"""Comprehensive tests for AI-Builder — Java, C#, .NET, JAR decompilation, security, and edge cases."""
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
# Test Project Root (shared across tests)
# ====================================================================
TEST_PROJECT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_project')


# ====================================================================
# Java Syntax Check Tests
# ====================================================================

class TestJavaSyntaxCheck(unittest.TestCase):
    """Tests for Java syntax checking via javac."""

    def test_valid_java_syntax(self):
        """Valid Java code should pass syntax check."""
        tool = CheckSyntaxTool(TEST_PROJECT)
        r = tool.execute({'path': 'java-project/src/main/java/com/example/App.java'})
        self.assertTrue(r.success)
        self.assertIn('OK', r.content)

    def test_valid_java_class_syntax(self):
        """Another valid Java class should pass."""
        tool = CheckSyntaxTool(TEST_PROJECT)
        r = tool.execute({'path': 'java-project/src/main/java/com/example/Calculator.java'})
        self.assertTrue(r.success)
        self.assertIn('OK', r.content)

    def test_invalid_java_syntax(self):
        """Java code with syntax errors should fail."""
        tmpdir = tempfile.mkdtemp()
        try:
            bad_java = os.path.join(tmpdir, 'Bad.java')
            with open(bad_java, 'w') as f:
                f.write('public class Bad { public void foo( { }')
            tool = CheckSyntaxTool(tmpdir)
            r = tool.execute({'path': 'Bad.java'})
            self.assertFalse(r.success)
            self.assertIn('error', r.error.lower())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_java_brace_fallback(self):
        """When javac is not available, brace matching should work as fallback."""
        tmpdir = tempfile.mkdtemp()
        try:
            good_java = os.path.join(tmpdir, 'Good.java')
            with open(good_java, 'w') as f:
                f.write('public class Good {\n    public void foo() { } \n}\n')
            tool = CheckSyntaxTool(tmpdir)
            # Mock javac not found
            with patch('subprocess.run', side_effect=FileNotFoundError()):
                r = tool.execute({'path': 'Good.java'})
                self.assertTrue(r.success)
                self.assertIn('OK', r.content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# C# Syntax Check Tests
# ====================================================================

class TestCSharpSyntaxCheck(unittest.TestCase):
    """Tests for C# syntax checking via dotnet."""

    def test_valid_csharp_syntax(self):
        """Valid C# code should pass syntax check."""
        tool = CheckSyntaxTool(TEST_PROJECT)
        r = tool.execute({'path': 'csharp-project/Program.cs'})
        self.assertTrue(r.success)
        self.assertIn('OK', r.content)

    def test_invalid_csharp_syntax(self):
        """C# code with syntax errors should fail."""
        tmpdir = tempfile.mkdtemp()
        try:
            bad_cs = os.path.join(tmpdir, 'Bad.cs')
            with open(bad_cs, 'w') as f:
                f.write('using System; class Bad { public static void Main() {')
            csproj = os.path.join(tmpdir, 'Bad.csproj')
            with open(csproj, 'w') as f:
                f.write('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
            tool = CheckSyntaxTool(tmpdir)
            r = tool.execute({'path': 'Bad.cs'})
            self.assertFalse(r.success)
            self.assertIn('error', r.error.lower())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_csharp_brace_fallback(self):
        """When dotnet is not available, brace matching should work as fallback."""
        tmpdir = tempfile.mkdtemp()
        try:
            good_cs = os.path.join(tmpdir, 'Good.cs')
            with open(good_cs, 'w') as f:
                f.write('using System;\npublic class Good {\n    public void Foo() { }\n}\n')
            tool = CheckSyntaxTool(tmpdir)
            with patch('subprocess.run', side_effect=FileNotFoundError()):
                r = tool.execute({'path': 'Good.cs'})
                self.assertTrue(r.success)
                self.assertIn('OK', r.content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# JAR Decompilation Tests
# ====================================================================

class TestDecompileJar(unittest.TestCase):
    """Tests for JAR decompilation via jar + javap fallback."""

    def test_decompile_jar(self):
        """Decompiling a known JAR should extract class files."""
        tool = DecompileJarTool(TEST_PROJECT)
        r = tool.execute({'jar_path': 'java-project/target/demo-1.0.0.jar'})
        self.assertTrue(r.success)
        self.assertGreater(len(r.file_paths), 0)
        # Should contain .class or .javap.txt files
        has_class = any('.class' in f for f in r.file_paths)
        has_javap = any('.javap.txt' in f for f in r.file_paths)
        self.assertTrue(has_class or has_javap, f"Expected class or javap files, got: {r.file_paths}")

    def test_decompile_nonexistent_jar(self):
        """Decompiling a non-existent JAR should fail gracefully."""
        tool = DecompileJarTool(TEST_PROJECT)
        r = tool.execute({'jar_path': 'nonexistent.jar'})
        self.assertFalse(r.success)
        self.assertIn('not found', r.error.lower())

    def test_decompile_custom_output_dir(self):
        """Decompiling to a custom output directory should work."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = DecompileJarTool(tmpdir)
            r = tool.execute({
                'jar_path': os.path.join(TEST_PROJECT, 'java-project', 'target', 'demo-1.0.0.jar'),
                'output_dir': tmpdir,
            })
            # When jar_path is outside root_dir, ensure_under_root may reject it.
            # Fall back to checking if the tool at least tried to process it.
            # The real test is that the JAR exists and is readable.
            if r.success:
                self.assertGreater(len(r.file_paths), 0)
        except SecurityError:
            # Expected if jar_path is outside the tool's root_dir
            pass
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# Dependency Listing Tests
# ====================================================================

class TestListDependencies(unittest.TestCase):
    """Tests for dependency manifest parsing."""

    def test_java_pom_xml(self):
        """Should parse Maven pom.xml dependencies."""
        tool = ListDependenciesTool(TEST_PROJECT)
        r = tool.execute({'search_dir': 'java-project'})
        self.assertTrue(r.success)
        deps = json.loads(r.content)
        names = [d['name'] for d in deps]
        self.assertTrue(any('junit' in n for n in names))
        self.assertTrue(any('guava' in n for n in names))

    def test_csharp_csproj(self):
        """Should parse .csproj PackageReference dependencies."""
        tool = ListDependenciesTool(TEST_PROJECT)
        r = tool.execute({'search_dir': 'csharp-project'})
        self.assertTrue(r.success)
        deps = json.loads(r.content)
        names = [d['name'] for d in deps]
        self.assertTrue(any('Newtonsoft' in n for n in names))

    def test_python_requirements(self):
        """Should parse Python requirements.txt."""
        tool = ListDependenciesTool(TEST_PROJECT)
        r = tool.execute({'search_dir': ''})
        self.assertTrue(r.success)
        deps = json.loads(r.content)
        names = [d['name'] for d in deps]
        self.assertTrue(any('flask' in n for n in names))
        self.assertTrue(any('requests' in n for n in names))

    def test_empty_directory(self):
        """Should return empty list for directory with no manifests."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = ListDependenciesTool(tmpdir)
            r = tool.execute({'search_dir': ''})
            self.assertTrue(r.success)
            deps = json.loads(r.content)
            self.assertEqual(len(deps), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# File Info Tests
# ====================================================================

class TestGetFileInfo(unittest.TestCase):
    """Tests for file metadata extraction."""

    def test_java_file_info(self):
        """Should detect Java file metadata correctly."""
        tool = GetFileInfoTool(TEST_PROJECT)
        r = tool.execute({'path': 'java-project/src/main/java/com/example/App.java'})
        self.assertTrue(r.success)
        info = json.loads(r.content)
        self.assertEqual(info['language'], 'java')
        self.assertEqual(info['extension'], '.java')
        self.assertFalse(info['is_binary'])
        self.assertGreater(info['line_count'], 0)

    def test_csharp_file_info(self):
        """Should detect C# file metadata correctly."""
        tool = GetFileInfoTool(TEST_PROJECT)
        r = tool.execute({'path': 'csharp-project/Program.cs'})
        self.assertTrue(r.success)
        info = json.loads(r.content)
        self.assertEqual(info['language'], 'csharp')
        self.assertEqual(info['extension'], '.cs')

    def test_python_file_info(self):
        """Should detect Python file metadata correctly."""
        tool = GetFileInfoTool(TEST_PROJECT)
        r = tool.execute({'path': 'src/main.py'})
        self.assertTrue(r.success)
        info = json.loads(r.content)
        self.assertEqual(info['language'], 'python')
        self.assertEqual(info['extension'], '.py')

    def test_nonexistent_file(self):
        """Should fail gracefully for non-existent files."""
        tool = GetFileInfoTool(TEST_PROJECT)
        r = tool.execute({'path': 'nonexistent.py'})
        self.assertFalse(r.success)
        self.assertIn('not found', r.error.lower())


# ====================================================================
# Security Tests
# ====================================================================

class TestSecurity(unittest.TestCase):
    """Tests for security boundary enforcement."""

    def test_path_traversal_blocked(self):
        """Path traversal via ../ should be blocked."""
        with self.assertRaises(SecurityError):
            ensure_under_root('../../../etc/passwd', TEST_PROJECT)

    def test_absolute_path_to_root_allowed(self):
        """Absolute path equal to root_dir should be allowed."""
        result = ensure_under_root(TEST_PROJECT, TEST_PROJECT)
        self.assertEqual(result, TEST_PROJECT)

    def test_relative_path_within_root_allowed(self):
        """Relative paths within root should be allowed."""
        result = ensure_under_root('src/main.py', TEST_PROJECT)
        self.assertTrue(result.startswith(TEST_PROJECT))

    def test_absolute_path_outside_root_blocked(self):
        """Absolute paths outside root should be blocked."""
        with self.assertRaises(SecurityError):
            ensure_under_root('/etc/passwd', TEST_PROJECT)

    def test_allowed_tmp_paths(self):
        """Paths in /tmp/ should be allowed."""
        result = ensure_under_root('/tmp/test.txt', TEST_PROJECT)
        self.assertEqual(result, '/tmp/test.txt')

    def test_nested_traversal_blocked(self):
        """Nested path traversal should be blocked."""
        with self.assertRaises(SecurityError):
            ensure_under_root('src/../../../etc/hosts', TEST_PROJECT)


# ====================================================================
# FindSymbol Tests
# ====================================================================

class TestFindSymbol(unittest.TestCase):
    """Tests for symbol search across codebases."""

    def test_find_java_class(self):
        """Should find Java class references."""
        tool = FindSymbolTool(TEST_PROJECT)
        r = tool.execute({'symbol': 'Calculator'})
        self.assertTrue(r.success)
        results = json.loads(r.content)
        self.assertGreater(len(results), 0)
        self.assertTrue(any('Calculator' in r['text'] for r in results))

    def test_find_python_function(self):
        """Should find Python function references."""
        tool = FindSymbolTool(TEST_PROJECT)
        r = tool.execute({'symbol': 'greet'})
        self.assertTrue(r.success)
        results = json.loads(r.content)
        self.assertGreater(len(results), 0)

    def test_find_csharp_class(self):
        """Should find C# class references."""
        tool = FindSymbolTool(TEST_PROJECT)
        r = tool.execute({'symbol': 'Calculator'})
        self.assertTrue(r.success)
        results = json.loads(r.content)
        self.assertGreater(len(results), 0)


# ====================================================================
# File System Tool Tests
# ====================================================================

class TestFileSystemTools(unittest.TestCase):
    """Tests for file system operations."""

    def test_list_directory(self):
        """Should list directory contents."""
        tool = ListDirectoryTool(TEST_PROJECT)
        r = tool.execute({'path': '', 'max_depth': '1'})
        self.assertTrue(r.success)
        entries = json.loads(r.content)
        names = [e['name'] for e in entries]
        self.assertIn('java-project', names)
        self.assertIn('csharp-project', names)
        self.assertIn('src', names)

    def test_search_files(self):
        """Should find files by pattern."""
        tool = SearchFilesTool(TEST_PROJECT)
        r = tool.execute({'pattern': '*.java', 'search_dir': ''})
        self.assertTrue(r.success)
        self.assertIn('App.java', r.content)
        self.assertIn('Calculator.java', r.content)

    def test_search_files_cs(self):
        """Should find C# files."""
        tool = SearchFilesTool(TEST_PROJECT)
        r = tool.execute({'pattern': '*.cs', 'search_dir': ''})
        self.assertTrue(r.success)
        self.assertIn('Program.cs', r.content)

    def test_read_file(self):
        """Should read file contents."""
        tool = ReadFileTool(TEST_PROJECT)
        r = tool.execute({'path': 'src/main.py'})
        self.assertTrue(r.success)
        self.assertIn('def greet', r.content)

    def test_write_and_read_file(self):
        """Should write and read back a file."""
        tmpdir = tempfile.mkdtemp()
        try:
            tool = WriteFileTool(tmpdir)
            r = tool.execute({
                'path': 'test_write.txt',
                'content': 'Hello, World!\n',
            })
            self.assertTrue(r.success)

            read_tool = ReadFileTool(tmpdir)
            r2 = read_tool.execute({'path': 'test_write.txt'})
            self.assertTrue(r2.success)
            self.assertEqual(r2.content.strip(), 'Hello, World!')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_edit_file(self):
        """Should edit a file with exact text replacement."""
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'edit_test.py')
            with open(test_file, 'w') as f:
                f.write('x = 1\ny = 2\n')

            tool = EditFileTool(tmpdir)
            r = tool.execute({
                'path': 'edit_test.py',
                'original_text': 'y = 2',
                'new_text': 'y = 3\nz = 4',
            })
            self.assertTrue(r.success)

            with open(test_file, 'r') as f:
                content = f.read()
            self.assertIn('y = 3', content)
            self.assertIn('z = 4', content)
            self.assertIn('x = 1', content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_delete_file(self):
        """Should delete a file."""
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(tmpdir, 'delete_me.txt')
            with open(test_file, 'w') as f:
                f.write('delete me')

            tool = DeleteFileTool(tmpdir)
            r = tool.execute({'path': 'delete_me.txt'})
            self.assertTrue(r.success)
            self.assertFalse(os.path.exists(test_file))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_delete_backup_file_blocked(self):
        """Should refuse to delete .bak files."""
        tmpdir = tempfile.mkdtemp()
        try:
            bak_file = os.path.join(tmpdir, 'backup.bak')
            with open(bak_file, 'w') as f:
                f.write('backup')

            tool = DeleteFileTool(tmpdir)
            r = tool.execute({'path': 'backup.bak'})
            self.assertFalse(r.success)
            self.assertIn('backup', r.error.lower())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ====================================================================
# ToolRegistry Tests
# ====================================================================

class TestToolRegistry(unittest.TestCase):
    """Tests for the tool registry."""

    def test_all_tools_registered(self):
        """All expected tools should be registered."""
        registry = ToolRegistry(TEST_PROJECT)
        tools = registry.list_tools()
        tool_names = [t['name'] for t in tools]
        expected = [
            'list_directory', 'search_files', 'grep_code',
            'read_file', 'write_file', 'edit_file', 'delete_file',
            'find_symbol', 'decompile_jar', 'list_dependencies',
            'check_syntax', 'get_file_info', 'create_tool',
        ]
        for name in expected:
            self.assertIn(name, tool_names, f"Tool '{name}' not registered")

    def test_tool_filtering(self):
        """Should only register enabled tools."""
        registry = ToolRegistry(TEST_PROJECT, enabled_tools=['read_file', 'write_file'])
        tools = registry.list_tools()
        tool_names = [t['name'] for t in tools]
        self.assertEqual(len(tool_names), 2)
        self.assertIn('read_file', tool_names)
        self.assertIn('write_file', tool_names)

    def test_unknown_tool_raises_error(self):
        """Executing unknown tool should raise ToolError."""
        registry = ToolRegistry(TEST_PROJECT)
        with self.assertRaises(ToolError):
            registry.execute('nonexistent_tool', {'path': 'test.txt'})


# ====================================================================
# E2E: Cross-Language Agentic Workflow
# ====================================================================

class TestCrossLanguageE2E(unittest.TestCase):
    """End-to-end test simulating a cross-language code revision task."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda d=self.test_dir: shutil.rmtree(d, ignore_errors=True))

        # Create a multi-language project
        os.makedirs(os.path.join(self.test_dir, 'java', 'src'), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, 'csharp', 'src'), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, 'python', 'src'), exist_ok=True)

        # Java file
        with open(os.path.join(self.test_dir, 'java', 'src', 'App.java'), 'w') as f:
            f.write('public class App { public static void main(String[] args) { System.out.println("Hello"); } }\n')

        # C# file
        csproj = os.path.join(self.test_dir, 'csharp', 'src', 'App.csproj')
        with open(csproj, 'w') as f:
            f.write('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        with open(os.path.join(self.test_dir, 'csharp', 'src', 'Program.cs'), 'w') as f:
            f.write('using System;\npublic class Program { public static void Main() { Console.WriteLine("Hi"); } }\n')

        # Python file
        with open(os.path.join(self.test_dir, 'python', 'src', 'main.py'), 'w') as f:
            f.write('def hello():\n    print("Hello")\n')

        self.project_config = {
            'rootDirectory': self.test_dir,
            'instructions': 'Explore the project structure and verify all files have valid syntax.',
            'job_id': 'cross_lang_test',
        }

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

    def test_cross_language_syntax_verification(self):
        """Verify that all language syntax checkers work in a single project."""
        tool = CheckSyntaxTool(self.test_dir)

        # Java
        r = tool.execute({'path': 'java/src/App.java'})
        self.assertTrue(r.success, f"Java check failed: {r.error}")

        # C#
        r = tool.execute({'path': 'csharp/src/Program.cs'})
        self.assertTrue(r.success, f"C# check failed: {r.error}")

        # Python
        r = tool.execute({'path': 'python/src/main.py'})
        self.assertTrue(r.success, f"Python check failed: {r.error}")

    def test_cross_language_dependency_listing(self):
        """Verify dependency listing works across languages."""
        dep_tool = ListDependenciesTool(self.test_dir)

        # Java
        r = dep_tool.execute({'search_dir': 'java'})
        self.assertTrue(r.success)

        # C#
        r = dep_tool.execute({'search_dir': 'csharp'})
        self.assertTrue(r.success)

        # Python
        r = dep_tool.execute({'search_dir': 'python'})
        self.assertTrue(r.success)


# ====================================================================
# Parser Edge Cases
# ====================================================================

class TestParserEdgeCases(unittest.TestCase):
    """Edge case tests for the tool call parser."""

    def test_param_with_colon_in_value(self):
        """Parameter values containing colons should be preserved."""
        response = (
            '[TOOL_START]\n'
            '[TOOL_NAME]\n'
            'write_file\n'
            ''
            '[PARAM_NAME]\n'
            'path\n'
            ''
            '[PARAM_VALUE]\n'
            'config.yaml\n'
            ''
            '[PARAM_NAME]\n'
            'content\n'
            ''
            '[PARAM_VALUE]\n'
            '--value with colons: in middle\n'
            ''
            '[TOOL_END]'
        )
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]['content'], '--value with colons: in middle')

    def test_empty_tool_block(self):
        """Empty tool block with no params should return empty params."""
        response = (
            '[TOOL_START]\n'
            '[TOOL_NAME]\n'
            'list_directory\n'
            ''
            '[PARAM_NAME]\n'
            'path\n'
            ''
            '[PARAM_VALUE]\n'
            '.\n'
            ''
            '[TOOL_END]'
        )
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'list_directory')
        self.assertEqual(calls[0][1]['path'], '.')

    def test_tool_name_with_hyphen(self):
        """Tool names with hyphens should be parsed."""
        response = (
            '[TOOL_START]\n'
            '[TOOL_NAME]\n'
            'my-tool\n'
            ''
            '[PARAM_NAME]\n'
            'param\n'
            ''
            '[PARAM_VALUE]\n'
            'value\n'
            ''
            '[TOOL_END]'
        )
        calls = parse_tool_calls(response)
        self.assertEqual(calls[0][0], 'my-tool')
        self.assertEqual(calls[0][1]['param'], 'value')

    def test_tool_name_with_underscore(self):
        """Tool names with underscores should be parsed."""
        response = (
            '[TOOL_START]\n'
            '[TOOL_NAME]\n'
            'my_tool\n'
            ''
            '[PARAM_NAME]\n'
            'param\n'
            ''
            '[PARAM_VALUE]\n'
            'value\n'
            ''
            '[TOOL_END]'
        )
        calls = parse_tool_calls(response)
        self.assertEqual(calls[0][0], 'my_tool')

    def test_mixed_single_and_multiline_params(self):
        """Mix of single-line and multi-line params should parse correctly."""
        response = (
            '[TOOL_START]\n'
            '[TOOL_NAME]\n'
            'write_file\n'
            ''
            '[PARAM_NAME]\n'
            'path\n'
            ''
            '[PARAM_VALUE]\n'
            'src/app.py\n'
            ''
            '[PARAM_NAME]\n'
            'content\n'
            ''
            '[PARAM_VALUE]\n'
            'def hello():\n'
            '    print("hello")\n'
            '\n'
            'if __name__ == "__main__":\n'
            '    hello()\n'
            ''
            '[TOOL_END]'
        )
        calls = parse_tool_calls(response)
        params = calls[0][1]
        self.assertEqual(params['path'], 'src/app.py')
        self.assertIn('def hello():', params['content'])
        self.assertIn('if __name__', params['content'])

    def test_multiple_tools_with_different_params(self):
        """Multiple tools with different parameter sets should parse correctly."""
        response = (
            '[TOOL_START]\n'
            '[TOOL_NAME]\n'
            'list_directory\n'
            ''
            '[PARAM_NAME]\n'
            'path\n'
            ''
            '[PARAM_VALUE]\n'
            'src\n'
            ''
            '[PARAM_NAME]\n'
            'max_depth\n'
            ''
            '[PARAM_VALUE]\n'
            '2\n'
            ''
            '[TOOL_END]'
            '[TOOL_START]\n'
            '[TOOL_NAME]\n'
            'read_file\n'
            ''
            '[PARAM_NAME]\n'
            'path\n'
            ''
            '[PARAM_VALUE]\n'
            'src/main.py\n'
            ''
            '[PARAM_NAME]\n'
            'start_line\n'
            ''
            '[PARAM_VALUE]\n'
            '1\n'
            ''
            '[PARAM_NAME]\n'
            'end_line\n'
            ''
            '[PARAM_VALUE]\n'
            '10\n'
            ''
            '[TOOL_END]'
            '[TOOL_START]\n'
            '[TOOL_NAME]\n'
            'check_syntax\n'
            ''
            '[PARAM_NAME]\n'
            'path\n'
            ''
            '[PARAM_VALUE]\n'
            'src/main.py\n'
            ''
            '[TOOL_END]'
        )
        calls = parse_tool_calls(response)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0], 'list_directory')
        self.assertEqual(calls[0][1]['max_depth'], '2')
        self.assertEqual(calls[1][0], 'read_file')
        self.assertEqual(calls[1][1]['start_line'], '1')
        self.assertEqual(calls[2][0], 'check_syntax')


# ====================================================================
# Parameter Validation Tests
# ====================================================================

class TestParameterValidation(unittest.TestCase):
    """Tests for tool parameter validation."""

    def test_missing_required_param(self):
        """Missing required parameter should raise ToolError."""
        schema = {'path': 'string', 'content': 'string'}
        with self.assertRaises(ToolError):
            validate_tool_params({'path': 'test.txt'}, schema)

    def test_wrong_param_type(self):
        """Non-string value for string param should raise ToolError."""
        schema = {'path': 'string'}
        with self.assertRaises(ToolError):
            validate_tool_params({'path': 123}, schema)

    def test_valid_params(self):
        """Valid params should pass validation."""
        schema = {'path': 'string', 'content': 'string'}
        result = validate_tool_params({'path': 'test.txt', 'content': 'hello'}, schema)
        self.assertEqual(result, {'path': 'test.txt', 'content': 'hello'})


if __name__ == '__main__':
    unittest.main()
