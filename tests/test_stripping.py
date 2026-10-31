#!/usr/bin/env python3
"""Test non-tool content stripping and continuation flow."""
import json
import os
import sys
import time
import urllib.request
import urllib.error
import subprocess
import signal
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

def main():
    log("Starting non-tool stripping + continuation test...")

    # Create test project
    test_dir = Path("/tmp/test_stripping")
    test_dir.mkdir(parents=True, exist_ok=True)
    src_dir = test_dir / "src"
    src_dir.mkdir(exist_ok=True)
    (test_dir / "src" / "main.py").write_text('def add(a, b):\n    return a + b\n')
    (test_dir / "README.md").write_text("# Test Project\n")

    # Configure mock LLM with responses that include extra text
    mock_settings_path = PROJECT_ROOT / "tests" / "mock_llm_responses.json"
    mock_responses = [
        # Step 1: LLM responds with extra text before tool call
        {
            "pattern": "",
            "response": "I'll start by listing the directory.\n\n[TOOL_START]\n[TOOL_NAME]\nlist_directory\n[PARAM_NAME]\npath\n[PARAM_VALUE]\n.\n[TOOL_END]\n\nNow I'll explore the structure.",
            "finish_reason": "stop",
            "sequential": True
        },
        # Step 2: LLM responds with extra text before read_file
        {
            "pattern": "",
            "response": "Let me read main.py to understand the code.\n\n[TOOL_START]\n[TOOL_NAME]\nread_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py\n[TOOL_END]",
            "finish_reason": "stop",
            "sequential": True
        },
        # Step 3: LLM responds with extra text before edit_file
        {
            "pattern": "",
            "response": "I see the add function. I'll add a multiply function.\n\n[TOOL_START]\n[TOOL_NAME]\nedit_file\n[PARAM_NAME]\npath\n[PARAM_VALUE]\nsrc/main.py\n[PARAM_NAME]\noriginal_text\n[PARAM_VALUE]\ndef add(a, b):\n    return a + b\n[PARAM_NAME]\nnew_text\n[PARAM_VALUE]\ndef add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n[TOOL_END]\n\nDone editing!",
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
        # Step 5: task_completed with extra text
        {
            "pattern": "",
            "response": "All done! Here's the task_completed call:\n\n[TOOL_START]\n[TOOL_NAME]\ntask_completed\n[PARAM_NAME]\nsummary\n[PARAM_VALUE]\nAdded multiply function to src/main.py.\n[TOOL_END]\n\nGoodbye!",
            "finish_reason": "stop",
            "sequential": True
        },
    ]
    with open(mock_settings_path, 'w') as f:
        json.dump(mock_responses, f, indent=2)
    log("Mock LLM responses configured (with extra text)")

    # Start mock LLM
    mock_proc = subprocess.Popen(
        [sys.executable, "tests/mock_llm_server.py", "--port", str(MOCK_PORT)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    log(f"Mock LLM started (PID {mock_proc.pid})")

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
    log("Settings configured")

    # Start Flask
    flask_proc = subprocess.Popen(
        [sys.executable, "-m", "flask", "run", "--port", str(FLASK_PORT)],
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "FLASK_APP": "app.py", "FLASK_ENV": "development"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    log(f"Flask app started (PID {flask_proc.pid})")

    if not wait_for_server(MOCK_PORT, "Mock LLM"):
        mock_proc.terminate()
        return 1
    if not wait_for_server(FLASK_PORT, "Flask"):
        mock_proc.terminate()
        flask_proc.terminate()
        return 1

    # Create project
    log("\n--- Creating project ---")
    proj_resp = http_post("/api/projects", {
        "name": "test_stripping",
        "rootDirectory": str(test_dir),
        "instructions": "Add a multiply function to src/main.py.",
        "enabled_tools": ["list_directory", "read_file", "write_file", "edit_file", "check_syntax"],
    })
    if not proj_resp:
        log("FAILED: Could not create project")
        return 1
    proj = json.loads(proj_resp)
    project_id = proj.get("id", proj.get("name", "test_stripping"))
    log(f"Project created: {project_id}")

    # Run agent
    log("\n--- Running agent ---")
    run_resp = http_post("/api/agent/run", {
        "project_id": project_id,
        "rootDirectory": str(test_dir),
        "instructions": "Add a multiply function to src/main.py.",
        "enabled_tools": ["list_directory", "read_file", "write_file", "edit_file", "check_syntax"],
    })
    if not run_resp:
        log("FAILED: Could not start agent run")
        return 1

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
        return 1
    log(f"Job started: {job_id}")

    # Wait for completion
    log("\n--- Waiting for completion ---")
    for i in range(60):
        time.sleep(1)
        queue = http_get("/api/queue")
        if queue and not queue.get('running'):
            log(f"Job completed after {i+1} seconds")
            break
    else:
        log("WARNING: Job timed out after 60 seconds")

    # Get job history
    log("\n--- Job History ---")
    history = http_get(f"/api/agent/history/{job_id}")
    if not history:
        log("FAILED: Could not get job history")
        return 1

    steps = history.get('steps', [])
    for s in steps:
        tool = s.get('tool', '?')
        result = s.get('result', {})
        content = result.get('content', '')
        status = "✓" if result.get('success', False) else "✗"
        content_preview = content[:80].replace('\n', ' ')
        log(f"  Step {s.get('step', '?'):2d}: {status} {tool:20s} | {content_preview}")

    log(f"\n  Total steps: {len(steps)}")

    # Check result
    log("\n--- Result: src/main.py ---")
    main_py = (test_dir / "src" / "main.py").read_text()
    log(main_py)

    if 'def multiply' in main_py:
        log("\n✓ SUCCESS: multiply function was added!")
    else:
        log("\n✗ FAIL: multiply function was NOT added")

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

    log("\n=== TEST COMPLETE ===")
    return 0

if __name__ == '__main__':
    sys.exit(main())
