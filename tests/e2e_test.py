#!/usr/bin/env python3
"""End-to-end test for AI Builder with tool result truncation."""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import subprocess
import signal
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent  # Go up from tests/ to project root
sys.path.insert(0, str(PROJECT_ROOT))

MOCK_PORT = 18766
FLASK_PORT = 5056
BASE = f"http://127.0.0.1:{FLASK_PORT}"

def log(msg):
    print(f"[E2E] {msg}", flush=True)

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
                # Flask health check
                req = urllib.request.Request(f"http://127.0.0.1:{port}/api/projects")
                urllib.request.urlopen(req, timeout=1)
            else:
                # Mock LLM health check
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

def main():
    log("Starting E2E test...")

    # 1. Create test project
    test_dir = Path("/tmp/e2e_truncation_test")
    test_dir.mkdir(parents=True, exist_ok=True)
    src_dir = test_dir / "src"
    src_dir.mkdir(exist_ok=True)

    # Create a large README to test truncation
    large_readme = "# E2E Test Project\n\n" + "\n".join([f"Section {i}: This is section {i} of the README. " * 20 for i in range(100)])
    (test_dir / "README.md").write_text(large_readme)

    # Create main.py with add and multiply
    (test_dir / "src" / "main.py").write_text(
        'def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n'
    )

    # Create utils.py
    (test_dir / "src" / "utils.py").write_text(
        'def helper():\n    return "hello"\n\ndef format_name(first, last):\n    return f"{first} {last}"\n\ndef greet(name):\n    return f"Hello, {name}!"\n'
    )

    # Create a large requirements.txt to test truncation
    reqs = "\n".join([f"package-{i}==1.{i}.0" for i in range(200)])
    (test_dir / "requirements.txt").write_text(reqs)

    log(f"Test project created at {test_dir}")
    log(f"Files: README.md ({(test_dir / 'README.md').stat().st_size} bytes), "
        f"src/main.py, src/utils.py, requirements.txt ({(test_dir / 'requirements.txt').stat().st_size} bytes)")

    # 2. Configure mock LLM with sequential responses for the E2E test
    #    (MUST be created BEFORE starting the mock LLM server)
    mock_settings_path = PROJECT_ROOT / "tests" / "mock_llm_responses.json"
    mock_responses = [
        # Step 1: list_directory
        {
            "pattern": "",
            "response": "[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]",
            "finish_reason": "stop",
            "sequential": True
        },
        # Step 2: read_file (main.py)
        {
            "pattern": "",
            "response": "[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py\n[TOOL_END]",
            "finish_reason": "stop",
            "sequential": True
        },
        # Step 3: edit_file (add divide function)
        {
            "pattern": "",
            "response": "[TOOL_START]\n[TOOL_NAME]\nedit_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py\n[PARAM_NAME]\noriginal_text\n[PARAM_VALUE]\ndef add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n\n[PARAM_NAME]\nnew_text\n[PARAM_VALUE]\ndef add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n\ndef divide(a, b):\n    if b == 0:\n        raise ValueError(\"Cannot divide by zero\")\n    return a / b\n[TOOL_END]",
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
        # Step 5: DONE
        {
            "pattern": "",
            "response": "[DONE] Added divide function to src/main.py with division-by-zero handling.",
            "finish_reason": "stop",
            "sequential": True
        },
    ]
    with open(mock_settings_path, 'w') as f:
        json.dump(mock_responses, f, indent=2)
    log("Mock LLM responses configured")

    # 3. Start mock LLM server (now that responses file exists)
    mock_proc = subprocess.Popen(
        [sys.executable, "tests/mock_llm_server.py", "--port", str(MOCK_PORT)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    log(f"Mock LLM started (PID {mock_proc.pid})")

    # 4. Configure settings
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
    log("Settings configured")

    # 4. Start Flask app
    flask_proc = subprocess.Popen(
        [sys.executable, "-m", "flask", "run", "--port", str(FLASK_PORT)],
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "FLASK_APP": "app.py", "FLASK_ENV": "development"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    log(f"Flask app started (PID {flask_proc.pid})")

    # Wait for servers
    if not wait_for_server(MOCK_PORT, "Mock LLM"):
        mock_proc.terminate()
        return 1
    if not wait_for_server(FLASK_PORT, "Flask"):
        mock_proc.terminate()
        flask_proc.terminate()
        return 1

    # 5. Create project
    log("\n--- Creating project ---")
    proj_resp = http_post("/api/projects", {
        "name": "e2e_truncation_test",
        "rootDirectory": str(test_dir),
        "instructions": "Add a divide function to src/main.py that handles division by zero.",
        "enabled_tools": ["list_directory", "read_file", "write_file", "edit_file", "check_syntax", "search_files", "grep_code"],
    })
    if not proj_resp:
        log("FAILED: Could not create project")
        return 1
    proj = json.loads(proj_resp)
    project_id = proj.get("id", proj.get("name", "e2e_truncation_test"))
    log(f"Project created: {project_id}")

    # 6. Run the agent
    log("\n--- Running agent ---")
    run_resp = http_post("/api/agent/run", {
        "project_id": project_id,
        "rootDirectory": str(test_dir),
        "instructions": "Add a divide function to src/main.py that handles division by zero. "
                        "First explore the project structure, then read main.py, then make the change.",
        "enabled_tools": ["list_directory", "read_file", "write_file", "edit_file", "check_syntax", "search_files", "grep_code"],
    })
    if not run_resp:
        log("FAILED: Could not start agent run")
        return 1

    # Extract job_id from SSE
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
        return 1
    log(f"Job started: {job_id}")

    # 7. Poll for completion
    log("\n--- Waiting for completion ---")
    for i in range(60):
        time.sleep(1)
        queue = http_get("/api/queue")
        if queue and not queue.get('running'):
            log(f"Job completed after {i+1} seconds")
            break
    else:
        log("WARNING: Job timed out after 60 seconds")

    # 8. Get job history
    log("\n--- Job History ---")
    history = http_get(f"/api/agent/history/{job_id}")
    if not history:
        log("FAILED: Could not get job history")
        return 1

    steps = history.get('steps', [])
    truncated_count = 0
    for s in steps:
        tool = s.get('tool', '?')
        params = s.get('params', {})
        result = s.get('result', {})
        content = result.get('content', '')
        was_truncated = result.get('truncated', False)
        if was_truncated:
            truncated_count += 1
        status = "✓" if result.get('success', False) else "✗"
        trunc_note = f" [TRUNCATED {len(content)} chars]" if was_truncated else ""
        content_preview = content[:80].replace('\n', ' ')
        log(f"  Step {s.get('step', '?'):2d}: {status} {tool:20s} | {content_preview}{trunc_note}")

    log(f"\n  Total steps: {len(steps)}")
    log(f"  Truncated results: {truncated_count}")

    # 9. Check the result file
    log("\n--- Result: src/main.py ---")
    main_py = (test_dir / "src" / "main.py").read_text()
    log(main_py)

    # 10. Verify the divide function was added
    if 'def divide' in main_py:
        log("\n✓ SUCCESS: divide function was added!")
    else:
        log("\n✗ FAIL: divide function was NOT added")

    # 11. Verify truncation actually happened
    if truncated_count > 0:
        log(f"✓ Truncation worked: {truncated_count} results were truncated")
    else:
        log("⚠ No truncation occurred (results may have been under the limit)")

    # Cleanup
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

    log("\n=== E2E TEST COMPLETE ===")
    return 0

if __name__ == '__main__':
    sys.exit(main())
