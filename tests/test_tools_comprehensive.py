#!/usr/bin/env python3
"""Comprehensive tool testing against a sample project directory."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agent_engine.tools.files import (
    ListDirectoryTool, SearchFilesTool, GrepCodeTool,
    ReadFileTool, WriteFileTool, EditFileTool, DeleteFileTool,
)


class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results = []

    def add(self, name, passed, details=""):
        status = "✓ PASS" if passed else "✗ FAIL"
        self.results.append((status, name, details))
        if passed:
            self.passed += 1
        else:
            self.failed += 1

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"RESULTS: {self.passed}/{total} tests passed")
        if self.failed > 0:
            print(f"{'='*60}")
            print("FAILURES:")
            for status, name, details in self.results:
                if status == "✗ FAIL":
                    print(f"  {status} {name}")
                    if details:
                        print(f"         {details}")
        else:
            print(f"{'='*60}")
            print("ALL TESTS PASSED ✓")
        print(f"{'='*60}\n")


def test_list_directory(tool, result):
    """Test list_directory tool."""
    print("\n--- Testing list_directory ---")
    
    # Test 1: List root directory
    r = tool.execute({'path': '.', 'max_depth': '1'})
    result.add("list_directory root", r.success, r.content if not r.success else "")
    if r.success:
        entries = json.loads(r.content)
        names = [e['name'] for e in entries]
        result.add("  contains README.md", 'README.md' in names)
        result.add("  contains src/", 'src' in names)
        result.add("  contains config.json", 'config.json' in names)
        
        # Verify no truncation
        for e in entries:
            if e['name'].endswith('..') or len(e['name']) < 2:
                result.add(f"  no truncation: {e['name']}", False, f"Name appears truncated")
                break
        else:
            result.add("  no truncation", True)
    
    # Test 2: List with depth
    r = tool.execute({'path': '.', 'max_depth': '2'})
    result.add("list_directory depth=2", r.success, r.content if not r.success else "")
    if r.success:
        entries = json.loads(r.content)
        paths = [e['path'] for e in entries]
        result.add("  contains src/main.py", 'src/main.py' in paths)
        result.add("  contains tests/test_main.py", 'tests/test_main.py' in paths)


def test_search_files(tool, result):
    """Test search_files tool."""
    print("\n--- Testing search_files ---")
    
    # Test 1: Search by extension
    r = tool.execute({'pattern': '*.py', 'search_dir': '.'})
    result.add("search_files *.py", r.success, r.content if not r.success else "")
    if r.success:
        matches = [m.strip() for m in r.content.strip().split('\n') if m.strip()]
        result.add("  finds main.py", any('main.py' in m for m in matches))
        result.add("  finds utils.py", any('utils.py' in m for m in matches))
        result.add("  finds test_main.py", any('test_main.py' in m for m in matches))
    
    # Test 2: Search by name pattern
    r = tool.execute({'pattern': 'README*', 'search_dir': '.'})
    result.add("search_files README*", r.success, r.content if not r.success else "")
    if r.success:
        result.add("  finds README.md", 'README.md' in r.content)


def test_grep_code(tool, result):
    """Test grep_code tool."""
    print("\n--- Testing grep_code ---")
    
    # Test 1: Search for text
    r = tool.execute({'pattern': 'def greet', 'search_dir': '.', 'max_results': '10'})
    result.add("grep_code 'def greet'", r.success, r.content if not r.success else "")
    if r.success:
        result.add("  finds main.py", 'main.py' in r.content)
        result.add("  finds 'def greet'", 'def greet' in r.content)
    
    # Test 2: Search for function
    r = tool.execute({'pattern': 'print(greet', 'search_dir': '.', 'max_results': '10'})
    result.add("grep_code 'print(greet'", r.success, r.content if not r.success else "")
    if r.success:
        result.add("  finds usage", 'print(greet("World"))' in r.content)


def test_read_file(tool, result):
    """Test read_file tool."""
    print("\n--- Testing read_file ---")
    
    # Test 1: Read a file
    r = tool.execute({'path': 'src/main.py'})
    result.add("read_file src/main.py", r.success, r.content if not r.success else "")
    if r.success:
        result.add("  contains 'def greet'", 'def greet' in r.content)
        result.add("  contains 'Hello'", 'Hello' in r.content)
    
    # Test 2: Read with line range
    r = tool.execute({'path': 'src/utils.py', 'start_line': '1', 'end_line': '5'})
    result.add("read_file with lines", r.success, r.content if not r.success else "")
    if r.success:
        result.add("  contains 'def add'", 'def add' in r.content)
        result.add("  contains 'def multiply'", 'def multiply' in r.content)


def test_write_file(tool, result):
    """Test write_file tool."""
    print("\n--- Testing write_file ---")
    
    # Test 1: Write a new file
    r = tool.execute({
        'path': 'test_output.txt',
        'content': 'This is a test file created by the agent.\nLine 2\nLine 3\n'
    })
    result.add("write_file test_output.txt", r.success, r.content if not r.success else "")
    if r.success:
        # Verify the file was written
        r2 = ReadFileTool('/tmp/aibuilder_sample_project')
        r2_result = r2.execute({'path': 'test_output.txt'})
        result.add("  file exists", r2_result.success)
        result.add("  content matches", 'This is a test file' in r2_result.content if r2_result.success else False)
    
    # Test 2: Write with literal newlines
    r = tool.execute({
        'path': 'test_newlines.txt',
        'content': 'line1\\nline2\\nline3'
    })
    result.add("write_file with \\n", r.success, r.content if not r.success else "")
    if r.success:
        r2 = ReadFileTool('/tmp/aibuilder_sample_project')
        r2_result = r2.execute({'path': 'test_newlines.txt'})
        result.add("  newlines converted", r2_result.content == 'line1\nline2\nline3' if r2_result.success else False)
    
    # Test 3: Write nested directory
    r = tool.execute({
        'path': 'output/deep/nested/file.txt',
        'content': 'deep content'
    })
    result.add("write_file nested dir", r.success, r.content if not r.success else "")
    if r.success:
        r2 = ReadFileTool('/tmp/aibuilder_sample_project')
        r2_result = r2.execute({'path': 'output/deep/nested/file.txt'})
        result.add("  nested file exists", r2_result.success and 'deep content' in r2_result.content)


def test_edit_file(tool, result):
    """Test edit_file tool."""
    print("\n--- Testing edit_file ---")
    
    # First, write a test file
    write_tool = WriteFileTool('/tmp/aibuilder_sample_project')
    write_tool.execute({'path': 'edit_test.py', 'content': 'def original():\n    print("original")\n'})
    
    # Test: Edit the file
    r = tool.execute({
        'path': 'edit_test.py',
        'original_text': 'print("original")',
        'new_text': 'print("edited")'
    })
    result.add("edit_file", r.success, r.content if not r.success else "")
    if r.success:
        read_tool = ReadFileTool('/tmp/aibuilder_sample_project')
        r2 = read_tool.execute({'path': 'edit_test.py'})
        result.add("  content updated", 'print("edited")' in r2.content if r2.success else False)
        result.add("  original removed", 'print("original")' not in r2.content if r2.success else False)


def test_delete_file(tool, result):
    """Test delete_file tool."""
    print("\n--- Testing delete_file ---")
    
    # First, create a file to delete
    write_tool = WriteFileTool('/tmp/aibuilder_sample_project')
    write_tool.execute({'path': 'to_delete.txt', 'content': 'delete me'})
    
    # Test: Delete the file
    r = tool.execute({'path': 'to_delete.txt'})
    result.add("delete_file", r.success, r.content if not r.success else "")
    if r.success:
        result.add("  file removed", not os.path.exists('/tmp/aibuilder_sample_project/to_delete.txt'))


def main():
    result_obj = TestResult()
    
    root_dir = '/tmp/aibuilder_sample_project'
    if not os.path.exists(root_dir):
        print(f"ERROR: Sample project not found at {root_dir}")
        sys.exit(1)
    
    print(f"Testing tools against: {root_dir}")
    result = subprocess.run(['find', root_dir, '-type', 'f'], capture_output=True, text=True)
    print(f"Files:\n{result.stdout}")
    
    # Initialize tools
    list_tool = ListDirectoryTool(root_dir)
    search_tool = SearchFilesTool(root_dir)
    grep_tool = GrepCodeTool(root_dir)
    read_tool = ReadFileTool(root_dir)
    write_tool = WriteFileTool(root_dir)
    edit_tool = EditFileTool(root_dir)
    delete_tool = DeleteFileTool(root_dir)
    
    try:
        test_list_directory(list_tool, result_obj)
        test_search_files(search_tool, result_obj)
        test_grep_code(grep_tool, result_obj)
        test_read_file(read_tool, result_obj)
        test_write_file(write_tool, result_obj)
        test_edit_file(edit_tool, result_obj)
        test_delete_file(delete_tool, result_obj)
    
    finally:
        # Cleanup test files
        for f in ['test_output.txt', 'test_newlines.txt', 'edit_test.py', 'to_delete.txt']:
            path = os.path.join(root_dir, f)
            if os.path.exists(path):
                os.remove(path)
        # Remove nested output dir
        output_dir = os.path.join(root_dir, 'output')
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
    
    result_obj.summary()
    return result_obj.failed == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
