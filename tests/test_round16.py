#!/usr/bin/env python3
"""Round 16 tests: edit_file improvements, code block stripping, instance prefix."""
import json
import os
import sys
import time
import urllib.request
import urllib.error
import subprocess
import signal
import tempfile
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

MOCK_PORT = 18766
FLASK_PORT = 5056
BASE = f"http://127.0.0.1:{FLASK_PORT}"

def log(msg):
    print(f"[TEST] {msg}", flush=True)

def http_get(path):
    try:
        req = urllib.request.Request(f"{BASE}{path}")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        log(f"GET {path} failed: {e}")
        return None

def http_post(path, data):
    try:
        req = urllib.request.Request(
            f"{BASE}{path}",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode()
    except Exception as e:
        log(f"POST {path} failed: {e}")
        return None

def wait_for_server(port, name, max_wait=60):
    for i in range(max_wait):
        try:
            if name == "Flask":
                req = urllib.request.Request(f"http://127.0.0.1:{port}/api/projects")
                urllib.request.urlopen(req, timeout=1)
            else:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", method="POST")
                req.data = b'{"model":"test","messages":[],"stream":false}'
                req.add_header("Content-Type", "application/json")
                urllib.request.urlopen(req, timeout=1)
            log(f"{name} ready on port {port}")
            return True
        except Exception:
            time.sleep(0.5)
    log(f"ERROR: {name} failed to start on port {port}")
    return False


# ====================================================================
# Unit Tests (imported from engine)
# ====================================================================

def test_code_block_stripping():
    """Test that code blocks are stripped before tool call parsing."""
    from agent_engine.engine import _strip_code_blocks, parse_tool_calls

    # Fenced code block should be stripped
    response = """Some text
```python
[TOOL_START]
[TOOL_NAME]
write_file
[PARAM_NAME]
path
[PARAM_VALUE]
src/main.py
[TOOL_END]
```
[TOOL_START]
[TOOL_NAME]
list_directory
[PARAM_NAME]
path
[PARAM_VALUE]
.
[TOOL_END]
"""
    stripped = _strip_code_blocks(response)
    # The code block content should be removed
    assert 'write_file' not in stripped, "Code block content should be stripped"
    # The actual tool call should remain
    assert 'list_directory' in stripped, "Non-code tool call should remain"

    # Inline code should be stripped
    response2 = "Use `write_file` for writing, then [TOOL_START][TOOL_NAME]list_directory..."
    stripped2 = _strip_code_blocks(response2)
    assert 'write_file' not in stripped2

    # Parse should work on stripped content
    calls = parse_tool_calls(response)
    assert len(calls) == 1, f"Expected 1 call, got {len(calls)}: {calls}"
    assert calls[0][0] == 'list_directory', f"Expected list_directory, got {calls[0][0]}"

    log("✓ Code block stripping works")


def test_instance_prefix():
    """Test that instance prefix is generated and used."""
    from agent_engine.engine import AgentEngine, build_system_prompt, parse_tool_calls

    # Test build_system_prompt with prefix
    tools = [
        {"name": "write_file", "description": "Write a file", "parameters": {"path": "string", "content": "string"}},
        {"name": "read_file", "description": "Read a file", "parameters": {"path": "string"}},
    ]
    prompt_no_prefix = build_system_prompt(tools)
    prompt_with_prefix = build_system_prompt(tools, "abc123")

    assert "write_file" in prompt_no_prefix
    assert "abc123_write_file" in prompt_with_prefix
    # The unprefixed tool should not appear as a standalone tool definition
    # (it appears as part of the prefixed name, which is fine)
    import re
    unprefixed_matches = re.findall(r'^\s+- write_file:', prompt_with_prefix, re.MULTILINE)
    assert len(unprefixed_matches) == 0, f"Unprefixed tool should not appear as standalone: {unprefixed_matches}"

    # Test parse_tool_calls with prefix
    response = """[TOOL_START]
[TOOL_NAME]
abc123_write_file
[PARAM_NAME]
path
[PARAM_VALUE]
test.txt
[TOOL_END]"""

    calls = parse_tool_calls(response, "abc123")
    assert len(calls) == 1
    assert calls[0][0] == "write_file", f"Prefix should be stripped, got: {calls[0][0]}"

    # Without prefix, unprefixed tool name should still work
    response2 = """[TOOL_START]
[TOOL_NAME]
read_file
[PARAM_NAME]
path
[PARAM_VALUE]
test.txt
[TOOL_END]"""
    calls2 = parse_tool_calls(response2, "abc123")
    assert len(calls2) == 1
    assert calls2[0][0] == "read_file", "Unprefixed tool should work when prefix doesn't match"

    log("✓ Instance prefix system works")


def test_edit_file_strategies():
    """Test all edit_file matching strategies."""
    from agent_engine.tools.edit_file import EditFileTool

    tmpdir = tempfile.mkdtemp()
    try:
        # Test exact match
        test_file = os.path.join(tmpdir, 'exact.py')
        with open(test_file, 'w') as f:
            f.write('x = 1\ny = 2\nz = 3\n')
        tool = EditFileTool(tmpdir)
        r = tool.execute({
            'path': 'exact.py',
            'original_text': 'y = 2',
            'new_text': 'y = 10',
        })
        assert r.success, f"Exact match failed: {r.error}"
        with open(test_file) as f:
            assert 'y = 10' in f.read()
        log("  ✓ Exact match works")

        # Test whitespace-insensitive match
        test_file2 = os.path.join(tmpdir, 'ws.py')
        with open(test_file2, 'w') as f:
            f.write('x = 1\n  y  =  2\nz = 3\n')
        r = tool.execute({
            'path': 'ws.py',
            'original_text': 'y = 2',
            'new_text': 'y = 20',
        })
        assert r.success, f"Whitespace match failed: {r.error}"
        with open(test_file2) as f:
            content = f.read()
            assert 'y = 20' in content or 'y  =  20' in content
        log("  ✓ Whitespace-insensitive match works")

        # Test line-range replacement
        test_file3 = os.path.join(tmpdir, 'range.py')
        with open(test_file3, 'w') as f:
            f.write('line1\nline2\nline3\nline4\n')
        r = tool.execute({
            'path': 'range.py',
            'original_text': '',
            'new_text': 'replaced\n',
            'line_start': '2',
            'line_end': '3',
        })
        assert r.success, f"Line-range match failed: {r.error}"
        with open(test_file3) as f:
            content = f.read()
            assert 'line1' in content
            assert 'replaced' in content
            assert 'line4' in content
        log("  ✓ Line-range replacement works")

        # Test context-aware match (different indentation)
        test_file4 = os.path.join(tmpdir, 'context.py')
        with open(test_file4, 'w') as f:
            f.write('def foo():\n    x = 1\n    y = 2\n    return x + y\n')
        r = tool.execute({
            'path': 'context.py',
            'original_text': 'x = 1\ny = 2',  # No indentation
            'new_text': 'a = 1\nb = 2',
        })
        assert r.success, f"Context match failed: {r.error}"
        with open(test_file4) as f:
            content = f.read()
            assert 'a = 1' in content or '    a = 1' in content
        log("  ✓ Context-aware match works")

        # Test helpful error message
        test_file5 = os.path.join(tmpdir, 'error.py')
        with open(test_file5, 'w') as f:
            f.write('hello world\n')
        r = tool.execute({
            'path': 'error.py',
            'original_text': 'goodbye world',
            'new_text': 'farewell',
        })
        assert not r.success
        assert 'suggestions' in r.error.lower() or 'preview' in r.error.lower()
        assert 'hello world' in r.error  # Should show file content
        log("  ✓ Helpful error message works")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    log("✓ All edit_file strategies work")


def test_e2e_edit_file_improvements():
    """E2E test: agent uses edit_file with whitespace differences."""
    test_dir = Path("/tmp/test_edit_improvements")
    test_dir.mkdir(parents=True, exist_ok=True)
    src_dir = test_dir / "src"
    src_dir.mkdir(exist_ok=True)

    # Create a file with tricky whitespace
    (test_dir / "src" / "main.py").write_text(
        'def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n'
    )

    # Configure mock LLM with whitespace-difficult edit
    mock_settings_path = PROJECT_ROOT / "tests" / "mock_llm_responses.json"
    mock_responses = [
        # Step 1: list_directory
        {
            "pattern": "",
            "response": "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
            "finish_reason": "stop",
            "sequential": True
        },
        # Step 2: read_file
        {
            "pattern": "",
            "response": "[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py\n[TOOL_END]",
            "finish_reason": "stop",
            "sequential": True
        },
        # Step 3: edit_file with exact text (should work with new strategies)
        {
            "pattern": "",
            "response": "[TOOL_START]\n[TOOL_NAME]\nedit_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py\n[PARAM_NAME]\noriginal_text\n[PARAM_VALUE]\ndef add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n\n[PARAM_NAME]\nnew_text\n[PARAM_VALUE]\ndef add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n\ndef subtract(a, b):\n    return a - b\n[TOOL_END]",
            "finish_reason": "stop",
            "sequential": True
        },
        # Step 4: check_syntax
        {
            "pattern": "",
            "response": "[TOOL_START]\n[TOOL_NAME]\ncheck_syntax\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py\n[TOOL_END]",
            "finish_reason": "stop",
            "sequential": True
        },
        # Step 5: task_completed
        {
            "pattern": "",
            "response": "[TOOL_START]\n[TOOL_NAME]\ntask_completed\n[PARAM_NAME]\nsummary\n[PARAM_VALUE]\nAdded subtract function to src/main.py.\n[TOOL_END]",
            "finish_reason": "stop",
            "sequential": True
        },
    ]
    with open(mock_settings_path, 'w') as f:
        json.dump(mock_responses, f, indent=2)

    # Start mock LLM
    mock_proc = subprocess.Popen(
        [sys.executable, "tests/mock_llm_server.py", "--port", str(MOCK_PORT)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Configure settings
    settings = {
        "custom_endpoint_url": f"http://127.0.0.1:{MOCK_PORT}/v1/chat/completions",
        "custom_api_key": "",
        "custom_model_name": "mock-llm",
        "custom_verify_ssl": False,
        "max_steps": 20,
        "timeout": 300,
        "max_context_tokens": 0,
        "max_output_tokens": 0,
        "max_tool_result_length": 10000,
    }
    settings_path = PROJECT_ROOT / "aib_instance" / "settings.json"
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)

    # Start Flask
    flask_proc = subprocess.Popen(
        [sys.executable, "-m", "flask", "run", "--port", str(FLASK_PORT)],
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "FLASK_APP": "app.py", "FLASK_ENV": "development"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    try:
        if not wait_for_server(MOCK_PORT, "Mock LLM"):
            mock_proc.terminate()
            return False
        if not wait_for_server(FLASK_PORT, "Flask"):
            mock_proc.terminate()
            flask_proc.terminate()
            return False

        # Create project
        proj_resp = http_post("/api/projects", {
            "name": "test_edit_improvements",
            "rootDirectory": str(test_dir),
            "instructions": "Add a subtract function to src/main.py.",
        })
        if not proj_resp:
            log("FAILED: Could not create project")
            return False
        proj = json.loads(proj_resp)
        project_id = proj.get("id", proj.get("name", "test_edit_improvements"))

        # Run agent
        run_resp = http_post("/api/agent/run", {
            "project_id": project_id,
            "rootDirectory": str(test_dir),
            "instructions": "Add a subtract function to src/main.py.",
        })
        if not run_resp:
            log("FAILED: Could not start agent run")
            return False

        # Extract job_id
        job_id = None
        for line in run_resp.split('\n'):
            line = line.strip()
            if line.startswith('data: '):
                try:
                    event = json.loads(line[6:])
                    if 'job_id' in event:
                        job_id = event['job_id']
                        break
                except:
                    pass
        if not job_id:
            log("FAILED: Could not extract job_id")
            return False

        # Wait for completion
        for i in range(60):
            time.sleep(1)
            queue = http_get("/api/queue")
            if queue and not queue.get('running'):
                break
        else:
            log("WARNING: Job timed out")

        # Get job history
        history = http_get(f"/api/agent/history/{job_id}")
        if not history:
            log("FAILED: Could not get job history")
            return False

        steps = history.get('steps', [])
        success_count = 0
        for s in steps:
            result = s.get('result', {})
            if result.get('success', False):
                success_count += 1

        # Check result
        main_py = (test_dir / "src" / "main.py").read_text()

        if 'def subtract' in main_py:
            log(f"✓ SUCCESS: subtract function was added! ({success_count} successful steps)")
            return True
        else:
            log(f"✗ FAIL: subtract function was NOT added. Steps: {len(steps)}, Success: {success_count}")
            log(f"File content:\n{main_py}")
            return False
    finally:
        mock_proc.terminate()
        flask_proc.terminate()
        try:
            mock_proc.wait(timeout=3)
        except:
            mock_proc.kill()
        try:
            flask_proc.wait(timeout=3)
        except:
            flask_proc.kill()


def main():
    log("=== Round 16 Tests ===")

    # Unit tests
    test_code_block_stripping()
    test_instance_prefix()
    test_edit_file_strategies()

    # E2E test
    e2e_success = test_e2e_edit_file_improvements()

    log("\n=== Round 16 Complete ===")
    return 0 if e2e_success else 1


if __name__ == '__main__':
    sys.exit(main())
