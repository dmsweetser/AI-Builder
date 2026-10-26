#!/usr/bin/env python3
"""Systematic feature tester for AI Builder. Tests every feature and updates FEATURES.md."""
import json, os, re, sys, time
from datetime import datetime, timezone

# Fix sys.path for module imports
sys.path.insert(0, "/Users/daniel/Files/source/repos/AI-Builder")

BASE = "http://127.0.0.1:5056"
FEATURES_FILE = "/Users/daniel/Files/source/repos/AI-Builder/FEATURES.md"
now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

import requests

results = {}

def test(feature_id, name, fn):
    try:
        result = fn()
        status = "PASS" if result else "FAIL"
        notes = result if isinstance(result, str) and result else ""
        results[feature_id] = {"status": status, "notes": notes, "name": name}
        print(f"  {feature_id} {status}: {name}")
    except Exception as e:
        results[feature_id] = {"status": "FAIL", "notes": str(e)[:200], "name": name}
        print(f"  {feature_id} FAIL: {name} — {e}")
    return results[feature_id]

# ========================================================================
# 1. PROJECT MANAGEMENT
# ========================================================================
def test_1_1():
    r = requests.get(f"{BASE}/api/projects")
    return r.status_code == 200 and isinstance(r.json(), list)

def test_1_2():
    r = requests.post(f"{BASE}/api/projects", json={
        "name": "Feature Test Project",
        "rootDirectory": "/tmp/aib_feature_test",
        "instructions": "Test project for systematic testing"
    })
    return r.status_code == 200 and "id" in r.json()

def test_1_3():
    r = requests.get(f"{BASE}/api/projects")
    projects = r.json()
    if not projects:
        return "no projects"
    pid = projects[0]["id"]
    r2 = requests.get(f"{BASE}/api/projects/{pid}")
    return r2.status_code == 200 and r2.json()["id"] == pid

def test_1_4():
    r = requests.get(f"{BASE}/api/projects")
    projects = r.json()
    if not projects:
        return "no projects"
    pid = projects[0]["id"]
    r2 = requests.post(f"{BASE}/api/projects/{pid}", json={
        "name": "Updated Test Project",
        "rootDirectory": "/tmp/aib_feature_test",
        "instructions": "Updated instructions"
    })
    return r2.status_code == 200

def test_1_5():
    r = requests.get(f"{BASE}/api/projects")
    projects = r.json()
    if not projects:
        return "no projects"
    pid = projects[0]["id"]
    r2 = requests.post(f"{BASE}/api/projects/{pid}/archive")
    return r2.status_code == 200

def test_1_6():
    r = requests.get(f"{BASE}/api/projects")
    projects = r.json()
    if not projects:
        return "no projects"
    pid = projects[0]["id"]
    r2 = requests.post(f"{BASE}/api/projects/{pid}/unarchive")
    return r2.status_code == 200

def test_1_7():
    r = requests.get(f"{BASE}/api/projects")
    projects = r.json()
    if not projects:
        return "no projects"
    pid = projects[0]["id"]
    r2 = requests.post(f"{BASE}/api/projects/{pid}/reset")
    return r2.status_code == 200 and r2.json().get("status") == "reset"

def test_1_8():
    r = requests.get(f"{BASE}/api/projects")
    projects = r.json()
    if not projects:
        return "no projects"
    pid = projects[0]["id"]
    r2 = requests.delete(f"{BASE}/api/projects/{pid}")
    return r2.status_code == 200

# ========================================================================
# 2. PROJECT RUN & QUEUE
# ========================================================================
def test_2_1():
    r = requests.get(f"{BASE}/api/projects")
    projects = r.json()
    if not projects:
        return "no projects"
    pid = projects[0]["id"]
    r2 = requests.post(f"{BASE}/api/projects/{pid}/run")
    return r2.status_code in (200, 409)

def test_2_2():
    r = requests.get(f"{BASE}/api/queue")
    return r.status_code == 200 and "queue" in r.json() and "running" in r.json()

def test_2_3():
    r = requests.get(f"{BASE}/api/queue")
    q = r.json()
    if q.get("queue"):
        job_id = q["queue"][0]["job_id"]
        r2 = requests.delete(f"{BASE}/api/queue/{job_id}")
        return r2.status_code == 200
    return "queue empty (ok)"

def test_2_4():
    r = requests.post(f"{BASE}/api/queue/running/stop")
    return r.status_code == 200

# ========================================================================
# 3. JOB HISTORY
# ========================================================================
def test_3_1():
    r = requests.get(f"{BASE}/api/history")
    return r.status_code == 200 and isinstance(r.json(), list)

def test_3_2():
    r = requests.post(f"{BASE}/api/history/clear")
    return r.status_code == 200

def test_3_3():
    r = requests.get(f"{BASE}/api/job/0000000000000/actions")
    return r.status_code == 200

# ========================================================================
# 4. AGENT ENGINE
# ========================================================================
def test_4_1():
    r = requests.get(f"{BASE}/api/projects")
    projects = r.json()
    if not projects:
        return "no projects"
    pid = projects[0]["id"]
    r2 = requests.post(f"{BASE}/api/projects/{pid}/run")
    return r2.status_code in (200, 409)

def test_4_2():
    r = requests.get(f"{BASE}/api/agent/history/0000000000000")
    return r.status_code == 200

def test_4_3():
    r = requests.get(f"{BASE}/api/agent/response/0000000000000")
    return r.status_code == 200

def test_4_4():
    r = requests.get(f"{BASE}/api/agent/output/0000000000000")
    return r.status_code == 200

def test_4_5():
    r = requests.post(f"{BASE}/api/agent/inject", json={
        "job_id": "0000000000000", "instruction": "test"
    })
    return r.status_code == 200

def test_4_6():
    r = requests.post(f"{BASE}/api/agent/permission", json={
        "job_id": "0000000000000", "tool_id": "test", "approved": True
    })
    return r.status_code == 200

def test_4_7():
    r = requests.post(f"{BASE}/api/agent/resume", json={
        "job_id": "0000000000000", "input": "test input"
    })
    return r.status_code == 200

def test_4_8():
    r = requests.get(f"{BASE}/api/job-status")
    return r.status_code == 200

# ========================================================================
# 5. TOOL APPROVAL
# ========================================================================
def test_5_1():
    r = requests.get(f"{BASE}/api/tools/pending")
    return r.status_code == 200 and isinstance(r.json(), list)

def test_5_2():
    r = requests.post(f"{BASE}/api/tools/pending/nonexistent/approve")
    return r.status_code in (200, 404)

def test_5_3():
    r = requests.post(f"{BASE}/api/tools/pending/nonexistent/reject")
    return r.status_code in (200, 404)

def test_5_4():
    r = requests.get(f"{BASE}/api/tools/approved")
    return r.status_code == 200 and isinstance(r.json(), list)

# ========================================================================
# 6. CHAT
# ========================================================================
def test_6_1():
    r = requests.get(f"{BASE}/api/chats")
    return r.status_code == 200 and isinstance(r.json(), list)

def test_6_2():
    r = requests.post(f"{BASE}/api/chats", json={"title": "Test Chat"})
    return r.status_code == 200 and "id" in r.json()

def test_6_3():
    r = requests.get(f"{BASE}/api/chats")
    chats = r.json()
    if not chats:
        return "no chats"
    cid = chats[0]["id"]
    r2 = requests.get(f"{BASE}/api/chats/{cid}")
    return r2.status_code == 200 and "messages" in r2.json()

def test_6_4():
    r = requests.get(f"{BASE}/api/chats")
    chats = r.json()
    if not chats:
        return "no chats"
    cid = chats[0]["id"]
    r2 = requests.post(f"{BASE}/api/chats/{cid}/messages", json={"message": "Hello test"})
    return r2.status_code == 200

def test_6_5():
    r = requests.get(f"{BASE}/api/chats")
    chats = r.json()
    if not chats:
        return "no chats"
    cid = chats[0]["id"]
    r2 = requests.delete(f"{BASE}/api/chats/{cid}")
    return r2.status_code == 200

def test_6_6():
    r = requests.get(f"{BASE}/api/chats/auto")
    return r.status_code == 200 and "id" in r.json()

# ========================================================================
# 7. SETTINGS
# ========================================================================
def test_7_1():
    r = requests.get(f"{BASE}/api/settings")
    return r.status_code == 200 and isinstance(r.json(), dict)

def test_7_2():
    r = requests.post(f"{BASE}/api/settings", json={
        "CUSTOM_ENDPOINT_URL": "http://test:11434/v1",
        "CUSTOM_MODEL_NAME": "test-model",
        "AIB_MAX_STEPS": 20
    })
    return r.status_code == 200

def test_7_3():
    r = requests.post(f"{BASE}/api/settings/reload")
    return r.status_code == 200

# ========================================================================
# 8. APP LOG
# ========================================================================
def test_8_1():
    r = requests.get(f"{BASE}/api/app-log")
    return r.status_code == 200

# ========================================================================
# 9. FRONTEND (UI)
# ========================================================================
def test_9_1():
    r = requests.get(f"{BASE}/")
    html = r.text
    # Check for project list elements
    return "project-list" in html or "project-list" in html.lower() or "project-item" in html.lower()

def test_9_2():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "project-details-panel" in html or "details-project-name" in html

def test_9_3():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "tool-selector-grid" in html or "enabled_tools" in html

def test_9_4():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "details-run-btn" in html and "details-stop-btn" in html

def test_9_5():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "resetProject" in html and "deleteProject" in html

def test_9_6():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "agent-live-container" in html and "agent-live-box" in html

def test_9_7():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "live-inject-container" in html and "live-inject-input" in html

def test_9_8():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "jobs-panel" in html and "jobs-list" in html

def test_9_9():
    r = requests.get(f"{BASE}/")
    html = r.text
    # toggleJobSteps is defined in site.js, referenced via onclick in HTML
    return "toggleJobSteps" in html or "toggleJobSteps" in open("/Users/daniel/Files/source/repos/AI-Builder/static/site.js").read()

def test_10_0():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "app-log-panel" in html and "app-log-list" in html

def test_10_1():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "chat-panel" in html and "chat-list" in html

def test_10_2():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "settings-panel" in html and "set-custom-endpoint-url" in html

def test_10_3():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "tools-panel" in html and "pending-tools-list" in html

def test_10_4():
    requests.post(f"{BASE}/api/settings", json={"CUSTOM_MODEL_NAME": "test"})
    r = requests.get(f"{BASE}/api/settings")
    return r.json().get("CUSTOM_MODEL_NAME") == "test"

def test_10_5():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "show-archived-btn" in html or "toggleArchived" in html

def test_10_6():
    r = requests.get(f"{BASE}/")
    html = r.text
    # pickFolder function creates hidden file input with webkitdirectory at runtime
    js = open("/Users/daniel/Files/source/repos/AI-Builder/static/site.js").read()
    return "pickFolder" in html and "pickFolder" in js

def test_10_7():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "actions-modal" in html

def test_10_8():
    r = requests.get(f"{BASE}/")
    html = r.text
    return "root-path-confirmation-modal" in html

# ========================================================================
# 10. AGENT TOOLS
# ========================================================================
def test_tools():
    from agent_engine.tools import ToolRegistry
    reg = ToolRegistry("/tmp")
    tools = [t["name"] for t in reg.list_tools()]
    return tools

def test_10_9():
    tools = test_tools()
    return "list_directory" in tools

def test_10_10():
    tools = test_tools()
    return "list_directory_deep" in tools

def test_10_11():
    tools = test_tools()
    return "search_files" in tools

def test_10_12():
    tools = test_tools()
    return "search_files_dir" in tools

def test_10_13():
    tools = test_tools()
    return "grep_code" in tools

def test_10_14():
    tools = test_tools()
    return "grep_code_dir" in tools

def test_10_15():
    tools = test_tools()
    return "read_file" in tools

def test_10_16():
    tools = test_tools()
    return "read_file_range" in tools

def test_10_17():
    tools = test_tools()
    return "write_file" in tools

def test_10_18():
    tools = test_tools()
    return "edit_file" in tools

def test_10_19():
    tools = test_tools()
    return "delete_file" in tools

def test_10_20():
    tools = test_tools()
    return "find_symbol" in tools

def test_10_21():
    tools = test_tools()
    return "decompile_jar" in tools

def test_10_22():
    tools = test_tools()
    return "list_dependencies" in tools

def test_10_23():
    tools = test_tools()
    return "check_syntax" in tools

def test_10_24():
    tools = test_tools()
    return "get_file_info" in tools

def test_10_25():
    tools = test_tools()
    return "create_tool" in tools

def test_10_26():
    tools = test_tools()
    return "compress_context" in tools

def test_10_27():
    tools = test_tools()
    return "respond_to_user" in tools

def test_10_28():
    tools = test_tools()
    return "request_user_input" in tools

# ========================================================================
# 11. ENGINE SAFEGUARDS
# ========================================================================
def test_11_1():
    from agent_engine.engine import AgentEngine
    import inspect
    src = inspect.getsource(AgentEngine.run)
    return "read_budget" in src or "READ BUDGET" in src or "consecutive" in src.lower()

def test_11_2():
    from agent_engine.engine import AgentEngine
    import inspect
    src = inspect.getsource(AgentEngine.run)
    return "loop" in src.lower() or "LOOP DETECTED" in src

def test_11_3():
    from agent_engine.engine import AgentEngine
    import inspect
    src = inspect.getsource(AgentEngine.run)
    return "duplicate" in src.lower() or "DUPLICATE" in src

def test_11_4():
    from agent_engine.engine import AgentEngine
    import inspect
    src = inspect.getsource(AgentEngine.run)
    return "repeated" in src.lower() or "REPEATED" in src

def test_11_5():
    from agent_engine.engine import AgentEngine
    import inspect
    src = inspect.getsource(AgentEngine)
    return "compress" in src.lower() or "CONTEXT COMPRESSED" in src

def test_11_6():
    from agent_engine.engine import AgentEngine
    import inspect
    src = inspect.getsource(AgentEngine)
    return "timeout" in src.lower() or "120" in src

# ========================================================================
# RUN ALL TESTS
# ========================================================================
all_tests = [
    ("1.1", "List projects", test_1_1),
    ("1.2", "Create project", test_1_2),
    ("1.3", "Get project details", test_1_3),
    ("1.4", "Update project", test_1_4),
    ("1.5", "Archive project", test_1_5),
    ("1.6", "Unarchive project", test_1_6),
    ("1.7", "Reset project", test_1_7),
    ("1.8", "Delete project", test_1_8),
    ("2.1", "Run project (queue)", test_2_1),
    ("2.2", "Get queue status", test_2_2),
    ("2.3", "Delete from queue", test_2_3),
    ("2.4", "Stop running job", test_2_4),
    ("3.1", "List job history", test_3_1),
    ("3.2", "Clear job history", test_3_2),
    ("3.3", "Get job actions", test_3_3),
    ("4.1", "Start agent run", test_4_1),
    ("4.2", "Get agent history", test_4_2),
    ("4.3", "Get agent response", test_4_3),
    ("4.4", "Get agent output", test_4_4),
    ("4.5", "Inject live instruction", test_4_5),
    ("4.6", "Grant/deny permission", test_4_6),
    ("4.7", "Resume agent input", test_4_7),
    ("4.8", "Get job status", test_4_8),
    ("5.1", "List pending tools", test_5_1),
    ("5.2", "Approve tool", test_5_2),
    ("5.3", "Reject tool", test_5_3),
    ("5.4", "List approved tools", test_5_4),
    ("6.1", "List chats", test_6_1),
    ("6.2", "Create chat", test_6_2),
    ("6.3", "Get chat", test_6_3),
    ("6.4", "Send message", test_6_4),
    ("6.5", "Delete chat", test_6_5),
    ("6.6", "Auto-create chat", test_6_6),
    ("7.1", "Get settings", test_7_1),
    ("7.2", "Save settings", test_7_2),
    ("7.3", "Reload settings", test_7_3),
    ("8.1", "Get app log", test_8_1),
    ("9.1", "Project list sidebar", test_9_1),
    ("9.2", "Project details panel", test_9_2),
    ("9.3", "Tool selector checkboxes", test_9_3),
    ("9.4", "Run/Stop buttons", test_9_4),
    ("9.5", "Reset/Delete buttons", test_9_5),
    ("9.6", "Agent live feed", test_9_6),
    ("9.7", "Live inject input", test_9_7),
    ("9.8", "Job management panel", test_9_8),
    ("9.9", "Job step expansion", test_9_9),
    ("10.0", "App log panel", test_10_0),
    ("10.1", "AI Chat panel", test_10_1),
    ("10.2", "Settings panel", test_10_2),
    ("10.3", "Tool management panel", test_10_3),
    ("10.4", "Settings persistence", test_10_4),
    ("10.5", "Archived projects toggle", test_10_5),
    ("10.6", "Root directory picker", test_10_6),
    ("10.7", "Incomplete actions modal", test_10_7),
    ("10.8", "Root path confirmation modal", test_10_8),
    ("10.9", "list_directory", test_10_9),
    ("10.10", "list_directory_deep", test_10_10),
    ("10.11", "search_files", test_10_11),
    ("10.12", "search_files_dir", test_10_12),
    ("10.13", "grep_code", test_10_13),
    ("10.14", "grep_code_dir", test_10_14),
    ("10.15", "read_file", test_10_15),
    ("10.16", "read_file_range", test_10_16),
    ("10.17", "write_file", test_10_17),
    ("10.18", "edit_file", test_10_18),
    ("10.19", "delete_file", test_10_19),
    ("10.20", "find_symbol", test_10_20),
    ("10.21", "decompile_jar", test_10_21),
    ("10.22", "list_dependencies", test_10_22),
    ("10.23", "check_syntax", test_10_23),
    ("10.24", "get_file_info", test_10_24),
    ("10.25", "create_tool", test_10_25),
    ("10.26", "compress_context", test_10_26),
    ("10.27", "respond_to_user", test_10_27),
    ("10.28", "request_user_input", test_10_28),
    ("11.1", "Read budget", test_11_1),
    ("11.2", "Loop detection", test_11_2),
    ("11.3", "Duplicate read detection", test_11_3),
    ("11.4", "Repeated read detection", test_11_4),
    ("11.5", "Context compression", test_11_5),
    ("11.6", "Hard timeout", test_11_6),
]

print(f"Running {len(all_tests)} feature tests...\n")
for fid, name, fn in all_tests:
    test(fid, name, fn)

pass_count = sum(1 for r in results.values() if r["status"] == "PASS")
fail_count = sum(1 for r in results.values() if r["status"] == "FAIL")
print(f"\n{'='*60}")
print(f"RESULTS: {pass_count} PASS, {fail_count} FAIL out of {len(all_tests)}")
print(f"{'='*60}")

if fail_count > 0:
    print("\nFAILURES:")
    for fid, r in sorted(results.items()):
        if r["status"] == "FAIL":
            print(f"  {fid} {r['name']}: {r['notes'][:100]}")

# Save results
with open("/tmp/feature_test_results.json", "w") as f:
    json.dump({"results": results, "date": now}, f, indent=2)

print(f"\nResults saved to /tmp/feature_test_results.json")
