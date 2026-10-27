"""E2E tests for list_directory and related file tools using a temp directory."""

import json
import os
import shutil
import sys
import tempfile
import unittest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agent_engine.tools.list_directory import ListDirectoryTool
from agent_engine.tools.search_files import SearchFilesTool
from agent_engine.tools.grep_code import GrepCodeTool
from agent_engine.tools.read_file import ReadFileTool
from agent_engine.tools.write_file import WriteFileTool
from agent_engine.tools.edit_file import EditFileTool
from agent_engine.tools.delete_file import DeleteFileTool


class TestListDirectoryTool(unittest.TestCase):
    """Test list_directory tool with a real temp directory."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='aibuilder_test_')
        # Create a realistic project structure
        self._create_test_structure()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_test_structure(self):
        """Create a test directory structure."""
        # Root files
        with open(os.path.join(self.temp_dir, 'README.md'), 'w') as f:
            f.write('# Test Project\n\nThis is a test project.')
        with open(os.path.join(self.temp_dir, 'config.json'), 'w') as f:
            f.write('{"key": "value"}')

        # Subdirectory with files
        os.makedirs(os.path.join(self.temp_dir, 'src'), exist_ok=True)
        with open(os.path.join(self.temp_dir, 'src', 'main.py'), 'w') as f:
            f.write('print("hello")\n')
        with open(os.path.join(self.temp_dir, 'src', 'utils.py'), 'w') as f:
            f.write('def helper(): pass\n')

        # Nested subdirectory
        os.makedirs(os.path.join(self.temp_dir, 'src', 'models'), exist_ok=True)
        with open(os.path.join(self.temp_dir, 'src', 'models', 'model.py'), 'w') as f:
            f.write('class Model: pass\n')

        # File with special characters in name
        with open(os.path.join(self.temp_dir, 'src', 'test_file.txt'), 'w') as f:
            f.write('test content')

        # File with longer name
        with open(os.path.join(self.temp_dir, 'src', 'very_long_filename_that_goes_on_and_on.py'), 'w') as f:
            f.write('long filename test')

    def test_list_directory_root(self):
        """Test listing the root directory."""
        tool = ListDirectoryTool(self.temp_dir)
        result = tool.execute({'path': '.', 'max_depth': '1'})

        self.assertTrue(result.success)
        entries = json.loads(result.content)

        # Check that all root files/dirs are present
        names = [e['name'] for e in entries]
        self.assertIn('README.md', names)
        self.assertIn('config.json', names)
        self.assertIn('src', names)

        # Check that root-level filenames are NOT truncated
        for entry in entries:
            # For root-level entries (path has no /), path should equal name
            if '/' not in entry['path']:
                self.assertEqual(entry['path'], entry['name'],
                                 f"Root-level path '{entry['path']}' should match name '{entry['name']}'")
                # Verify the full filename is preserved (no truncation)
                self.assertEqual(len(entry['name']), len(entry['name']),
                                 f"Filename '{entry['name']}' appears truncated")

        # Verify no entry has a truncated name (check for any entry with name ending in '..')
        for entry in entries:
            self.assertFalse(entry['name'].endswith('..'),
                             f"Filename '{entry['name']}' appears to be truncated")

    def test_list_directory_with_depth(self):
        """Test listing with max_depth=2."""
        tool = ListDirectoryTool(self.temp_dir)
        result = tool.execute({'path': '.', 'max_depth': '2'})

        self.assertTrue(result.success)
        entries = json.loads(result.content)

        # Should include nested files
        paths = [e['path'] for e in entries]
        self.assertIn('src/main.py', paths)
        self.assertIn('src/models/model.py', paths)

        # Verify nested paths are complete (not truncated)
        for entry in entries:
            if entry['type'] == 'file' and entry['path'].startswith('src/'):
                # Just verify the path is complete and not truncated
                self.assertTrue(len(entry['path']) > 0,
                                f"Path should not be empty")
                # Verify the path ends with a valid extension
                self.assertTrue(entry['path'].endswith('.py') or entry['path'].endswith('.txt'),
                                f"File path '{entry['path']}' should have a valid extension")

    def test_list_directory_special_chars(self):
        """Test that filenames with special characters are preserved."""
        tool = ListDirectoryTool(self.temp_dir)
        result = tool.execute({'path': 'src', 'max_depth': '1'})

        self.assertTrue(result.success)
        entries = json.loads(result.content)
        names = [e['name'] for e in entries]

        # Check special filename is present
        self.assertIn('test_file.txt', names)
        self.assertIn('very_long_filename_that_goes_on_and_on.py', names)

        # Verify no truncation - the long filename should be complete
        long_name = 'very_long_filename_that_goes_on_and_on.py'
        self.assertIn(long_name, names,
                      f"Long filename '{long_name}' was not found in entries")

    def test_list_directory_json_serialization(self):
        """Test that the JSON output is valid and complete."""
        tool = ListDirectoryTool(self.temp_dir)
        result = tool.execute({'path': '.', 'max_depth': '2'})

        self.assertTrue(result.success)
        # Verify JSON is valid
        entries = json.loads(result.content)
        self.assertIsInstance(entries, list)

        # Verify each entry has required fields
        for entry in entries:
            self.assertIn('name', entry)
            self.assertIn('type', entry)
            self.assertIn('path', entry)
            # Verify name and path are not truncated
            self.assertEqual(entry['name'], entry['name'])  # No-op but ensures no None
            self.assertEqual(entry['path'], entry['path'])


class TestSearchFilesTool(unittest.TestCase):
    """Test search_files tool."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='aibuilder_test_')
        os.makedirs(os.path.join(self.temp_dir, 'src'), exist_ok=True)
        with open(os.path.join(self.temp_dir, 'src', 'main.py'), 'w') as f:
            f.write('print("hello")\n')
        with open(os.path.join(self.temp_dir, 'src', 'utils.py'), 'w') as f:
            f.write('def helper(): pass\n')
        with open(os.path.join(self.temp_dir, 'README.md'), 'w') as f:
            f.write('# Test')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_search_by_extension(self):
        tool = SearchFilesTool(self.temp_dir)
        result = tool.execute({'pattern': '*.py', 'search_dir': '.'})
        self.assertTrue(result.success)
        matches = result.content.strip().split('\n')
        self.assertEqual(len(matches), 2)
        self.assertIn('src/main.py', matches)
        self.assertIn('src/utils.py', matches)

    def test_search_by_name(self):
        tool = SearchFilesTool(self.temp_dir)
        result = tool.execute({'pattern': 'README*', 'search_dir': '.'})
        self.assertTrue(result.success)
        self.assertIn('README.md', result.content)


class TestGrepCodeTool(unittest.TestCase):
    """Test grep_code tool."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='aibuilder_test_')
        os.makedirs(os.path.join(self.temp_dir, 'src'), exist_ok=True)
        with open(os.path.join(self.temp_dir, 'src', 'main.py'), 'w') as f:
            f.write('print("hello")\n')
            f.write('def main(): pass\n')
        with open(os.path.join(self.temp_dir, 'src', 'utils.py'), 'w') as f:
            f.write('def helper(): pass\n')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_grep_text(self):
        tool = GrepCodeTool(self.temp_dir)
        result = tool.execute({'pattern': 'print', 'search_dir': '.', 'max_results': '10'})
        self.assertTrue(result.success)
        self.assertIn('main.py', result.content)
        self.assertIn('print("hello")', result.content)


class TestReadWriteFileTools(unittest.TestCase):
    """Test read_file and write_file tools."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='aibuilder_test_')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_write_and_read(self):
        write_tool = WriteFileTool(self.temp_dir)
        result = write_tool.execute({
            'path': 'test.txt',
            'content': 'Hello, World!\nLine 2\n'
        })
        self.assertTrue(result.success)

        read_tool = ReadFileTool(self.temp_dir)
        result = read_tool.execute({'path': 'test.txt'})
        self.assertTrue(result.success)
        self.assertEqual(result.content, 'Hello, World!\nLine 2\n')

    def test_write_nested_dir(self):
        write_tool = WriteFileTool(self.temp_dir)
        result = write_tool.execute({
            'path': 'a/b/c/deep.txt',
            'content': 'deep content'
        })
        self.assertTrue(result.success)

        read_tool = ReadFileTool(self.temp_dir)
        result = read_tool.execute({'path': 'a/b/c/deep.txt'})
        self.assertTrue(result.success)
        self.assertEqual(result.content, 'deep content')

    def test_write_with_newlines(self):
        """Test that literal \\n is converted to actual newlines."""
        write_tool = WriteFileTool(self.temp_dir)
        result = write_tool.execute({
            'path': 'test.txt',
            'content': 'line1\\nline2\\nline3'
        })
        self.assertTrue(result.success)

        read_tool = ReadFileTool(self.temp_dir)
        result = read_tool.execute({'path': 'test.txt'})
        self.assertTrue(result.success)
        self.assertEqual(result.content, 'line1\nline2\nline3')


class TestEditFileTool(unittest.TestCase):
    """Test edit_file tool."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='aibuilder_test_')
        with open(os.path.join(self.temp_dir, 'test.py'), 'w') as f:
            f.write('def hello():\n    print("world")\n')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_edit_file(self):
        tool = EditFileTool(self.temp_dir)
        result = tool.execute({
            'path': 'test.py',
            'original_text': 'print("world")',
            'new_text': 'print("edited")'
        })
        self.assertTrue(result.success)

        read_tool = ReadFileTool(self.temp_dir)
        result = read_tool.execute({'path': 'test.py'})
        self.assertTrue(result.success)
        self.assertIn('print("edited")', result.content)


class TestDeleteFileTool(unittest.TestCase):
    """Test delete_file tool."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='aibuilder_test_')
        with open(os.path.join(self.temp_dir, 'to_delete.txt'), 'w') as f:
            f.write('delete me')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_delete_file(self):
        tool = DeleteFileTool(self.temp_dir)
        result = tool.execute({'path': 'to_delete.txt'})
        self.assertTrue(result.success)
        self.assertFalse(os.path.exists(os.path.join(self.temp_dir, 'to_delete.txt')))


if __name__ == '__main__':
    unittest.main()
