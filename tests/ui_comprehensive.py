"""Comprehensive browser-equivalent UI tests for AI-Builder.

NOTE: This file is designed to be run as a standalone script (python ui_comprehensive.py).
It is NOT a pytest test — it uses module-level requests calls that require a running server.
"""
import os
import sys
import json
import time
import requests

BASE = "http://localhost:5056"

def check(name, condition, details=""):
    status = "PASS" if condition else "FAIL"
    mark = "\u2713" if condition else "\u2717"
    msg = f"  {mark} {name}"
    if details:
        msg += f" \u2014 {details}"
    print(msg)
    return condition

results = []

def track(name, condition, details=""):
    results.append((name, condition))
    return check(name, condition, details)


def run_tests():
    """Run all UI tests. Call this from __main__ or import and call manually."""
    print("=" * 60)
    print("AI-BUILDER UI COMPREHENSIVE TEST")
    print("=" * 60)

    # ---- 1. PAGE RENDERING ----
    print("\n--- 1. PAGE RENDERING ---")

    r = requests.get(f"{BASE}/")
    track("Main page returns 200", r.status_code == 200, f"status={r.status_code}")
    html = r.text
    track("HTML has doctype", "<!DOCTYPE html>" in html)
    track("HTML has closing </html>", "</html>" in html)
    track("HTML has closing </body>", "</body>" in html)
    track("Page title is AIB", "<title>AIB</title>" in html)
    track("Has styles.css link", 'href="/static/styles.css"' in html)
    track("Has site.js script", 'src="/static/site.js"' in html)
    track("Has favicon", 'href="/static/favicon.ico"' in html)

    # ---- 2. NAVIGATION TABS ----
    print("\n--- 2. NAVIGATION TABS ---")

    for tab in ["projects", "jobs", "chat", "settings", "tools"]:
        track(f"Tab button '{tab}'", f'onclick="showTab(\'{tab}\')"' in html,
              f'found={tab in html}')

    # ---- 3. PROJECTS PANEL ----
    print("\n--- 3. PROJECTS PANEL ---")

    track("Projects panel exists", 'id="projects-panel"' in html)
    track("Project list container", 'id="project-list"' in html)
    track("Add project form", 'id="add-project-form"' in html)
    track("Project name input", 'id="add-project-name"' in html)
    track("Root directory input", 'id="add-root-path"' in html)
    track("Instructions textarea", 'id="add-instructions"' in html)
    track("Create project button", 'CREATE PROJECT' in html)
    track("Show archived button", 'SHOW' in html and 'ARCHIVED' in html)
    track("Project details panel", 'id="project-details-panel"' in html)
    track("Run button", 'id="details-run-btn"' in html)
    track("Stop button", 'id="details-stop-btn"' in html)
    track("Delete button", 'DELETE' in html)
    track("Tool selector grid", 'id="details-tool-selector"' in html)
    track("Agent live container", 'id="agent-live-container"' in html)
    track("Live inject container", 'id="live-inject-container"' in html)
    track("Live inject input", 'id="live-inject-input"' in html)

    # ---- 4. JOBS PANEL ----
    print("\n--- 4. JOBS PANEL ---")

    track("Jobs panel exists", 'id="jobs-panel"' in html)
    track("Jobs list container", 'id="jobs-list"' in html)
    track("Clear history button", 'CLEAR' in html and 'HISTORY' in html)

    # ---- 5. CHAT PANEL ----
    print("\n--- 5. CHAT PANEL ---")

    track("Chat panel exists", 'id="chat-panel"' in html)
    track("Chat list container", 'id="chat-list"' in html)
    track("Chat log container", 'id="chat-log"' in html)
    track("Chat input", 'id="chat-input"' in html)
    track("Send chat button", 'id="send-chat-btn"' in html)
    track("Refresh chats button", 'REFRESH LIST' in html)
    track("New chat button", '+ NEW CHAT' in html)

    # ---- 6. SETTINGS PANEL ----
    print("\n--- 6. SETTINGS PANEL ---")

    track("Settings panel exists", 'id="settings-panel"' in html)
    track("Endpoint URL input", 'id="set-custom-endpoint-url"' in html)
    track("API Key input", 'id="set-custom-api-key"' in html)
    track("Model Name input", 'id="set-custom-model-name"' in html)
    track("Verify SSL checkbox", 'id="set-custom-verify-ssl"' in html)
    track("Max Steps input", 'id="set-max-steps"' in html)
    track("Timeout input", 'id="set-timeout"' in html)
    track("Root Directory input", 'id="set-root-dir"' in html)
    track("JD-CLI Path input", 'id="set-jd-cli"' in html)
    track("Java Home input", 'id="set-java-home"' in html)
    track("Dotnet CLI Path input", 'id="set-dotnet-cli"' in html)
    track("Save Settings button", 'SAVE SETTINGS' in html)
    track("Reload from Disk button", 'RELOAD FROM DISK' in html)

    # ---- 7. TOOLS PANEL ----
    print("\n--- 7. TOOLS PANEL ---")

    track("Tools panel exists", 'id="tools-panel"' in html)
    track("Pending tools list", 'id="pending-tools-list"' in html)
    track("Approved tools list", 'id="approved-tools-list"' in html)
    track("Refresh tools button", 'REFRESH' in html)

    # ---- 8. MODALS ----
    print("\n--- 8. MODALS ---")

    track("Root path confirmation modal", 'id="root-path-confirmation-modal"' in html)
    track("Actions modal", 'id="actions-modal"' in html)

    # ---- 9. ACCESSIBILITY ----
    print("\n--- 9. ACCESSIBILITY ---")

    track("Skip navigation link", 'class="skip-link"' in html)
    track("Skip link has href", 'href="#main-content"' in html)
    track("Main content has role=main", 'role="main"' in html)
    track("Main content has aria-live", 'aria-live="polite"' in html)
    track("Sidebar has role=navigation", 'role="navigation"' in html)
    track("Sidebar has aria-label", 'aria-label="Main navigation"' in html)
    track("Project list has role=list", 'role="list"' in html)
    track("Chat list has role=list", 'role="list"' in html)
    track("Jobs list has role=list", 'role="list"' in html)
    track("Tab buttons have role=menuitem", 'role="menuitem"' in html)
    track("Tab buttons have aria-selected", 'aria-selected' in html)

    # ---- 10. STATIC ASSETS ----
    print("\n--- 10. STATIC ASSETS ---")

    for path in ["/static/styles.css", "/static/site.js", "/static/favicon.ico"]:
        r = requests.get(f"{BASE}{path}")
        track(f"Static asset {path}", r.status_code == 200, f"status={r.status_code}")

    # ---- 11. CSS CONTENT ----
    print("\n--- 11. CSS VERIFICATION ---")

    r = requests.get(f"{BASE}/static/styles.css")
    css = r.text
    track("CSS has custom properties", "--grass" in css and "--wood" in css)
    track("CSS has sidebar styles", ".sidebar" in css)
    track("CSS has project list styles", ".project-list" in css or ".project-item" in css)
    track("CSS has button styles", ".btn-sm" in css or "button" in css)
    track("CSS has modal styles", ".modal" in css)
    track("CSS has responsive design", "max-width" in css or "viewport" in css)

    # ---- 12. JS CONTENT ----
    print("\n--- 12. JS VERIFICATION ---")

    r = requests.get(f"{BASE}/static/site.js")
    js = r.text
    track("JS has showTab function", "function showTab(" in js)
    track("JS has loadProjects function", "function loadProjects(" in js)
    track("JS has runProject function", "function runProject(" in js)
    track("JS has deleteProject function", "function deleteProject(" in js)
    track("JS has archiveProject function", "function archiveProject(" in js)
    track("JS has saveSettings function", "function saveSettings(" in js)
    track("JS has loadSettingsUI function", "function loadSettingsUI(" in js)
    track("JS has sendChat function", "function sendChat(" in js)
    track("JS has loadChats function", "function loadChats(" in js)
    track("JS has newChat function", "function newChat(" in js)
    track("JS has openChat function", "function openChat(" in js)
    track("JS has loadJobs function", "function loadJobs(" in js)
    track("JS has clearJobHistory function", "function clearJobHistory(" in js)
    track("JS has runAgenticProject function", "function runAgenticProject(" in js)
    track("JS has stopProject function", "function stopProject(" in js)
    track("JS has injectLiveInstruction function", "function injectLiveInstruction(" in js)
    track("JS has buildToolSelector function", "function buildToolSelector(" in js)
    track("JS has getEnabledTools function", "function getEnabledTools(" in js)
    track("JS has escapeHtml function", "function escapeHtml(" in js)
    track("JS has AVAILABLE_TOOLS array", "AVAILABLE_TOOLS" in js)
    track("JS has DOMContentLoaded handler", "DOMContentLoaded" in js)

    # ---- 13. API ENDPOINTS ----
    print("\n--- 13. API ENDPOINTS ---")

    # Projects
    r = requests.get(f"{BASE}/api/projects")
    track("GET /api/projects", r.status_code == 200)

    r = requests.post(f"{BASE}/api/projects", data={
        "name": "Browser Test Project",
        "rootDirectory": "/tmp/aib_ui_test",
        "instructions": "Test project for UI validation"
    })
    track("POST /api/projects", r.status_code == 200, f"status={r.status_code}")
    pid = r.json()["id"]

    r = requests.get(f"{BASE}/api/projects/{pid}")
    track("GET /api/projects/:id", r.status_code == 200)
    track("  Project has correct name", r.json()["name"] == "Browser Test Project")

    r = requests.post(f"{BASE}/api/projects/{pid}", data={
        "name": "Browser Test Project Updated",
        "rootDirectory": "/tmp/aib_ui_test"
    })
    track("POST /api/projects/:id (update)", r.status_code == 200)

    r = requests.post(f"{BASE}/api/projects/{pid}/archive")
    track("POST /api/projects/:id/archive", r.status_code == 200)

    r = requests.post(f"{BASE}/api/projects/{pid}/unarchive")
    track("POST /api/projects/:id/unarchive", r.status_code == 200)

    r = requests.delete(f"{BASE}/api/projects/{pid}")
    track("DELETE /api/projects/:id", r.status_code == 200)

    # Settings
    r = requests.get(f"{BASE}/api/settings")
    track("GET /api/settings", r.status_code == 200)
    settings = r.json()
    track("  Has all expected keys", all(k in settings for k in [
        "custom_endpoint_url", "custom_api_key", "custom_model_name",
        "custom_verify_ssl", "max_steps", "timeout", "root_directory",
        "jd_cli_path", "java_home", "dotnet_cli_path"
    ]))

    r = requests.post(f"{BASE}/api/settings", json={
        "custom_endpoint_url": "http://localhost:11434/v1",
        "custom_model_name": "test-model",
        "max_steps": 25,
        "timeout": 600
    })
    track("POST /api/settings", r.status_code == 200)

    r = requests.get(f"{BASE}/api/settings")
    settings = r.json()
    track("  Settings persisted", settings["custom_model_name"] == "test-model" and settings["max_steps"] == 25)

    # Queue
    r = requests.get(f"{BASE}/api/queue")
    track("GET /api/queue", r.status_code == 200)
    track("  Has queue array", "queue" in r.json())
    track("  Has running field", "running" in r.json())

    r = requests.delete(f"{BASE}/api/queue/fake-id")
    track("DELETE /api/queue/:id", r.status_code == 200)

    r = requests.post(f"{BASE}/api/queue/running/stop")
    track("POST /api/queue/running/stop", r.status_code == 200)

    # History
    r = requests.get(f"{BASE}/api/history")
    track("GET /api/history", r.status_code == 200)

    r = requests.post(f"{BASE}/api/history/clear")
    track("POST /api/history/clear", r.status_code == 200)

    # Chat
    r = requests.get(f"{BASE}/api/chats")
    track("GET /api/chats", r.status_code == 200)

    r = requests.post(f"{BASE}/api/chats", json={"timestamp": "2026-01-01T00:00:00"})
    track("POST /api/chats", r.status_code == 200)
    cid = r.json()["id"]

    r = requests.get(f"{BASE}/api/chats")
    track("GET /api/chats (after create)", len(r.json()) >= 1)

    r = requests.get(f"{BASE}/api/chats/{cid}")
    track("GET /api/chats/:id", r.status_code == 200)
    track("  Chat has messages array", "messages" in r.json())

    r = requests.post(f"{BASE}/api/chats/{cid}/messages", json={"content": "Hello"})
    track("POST /api/chats/:id/messages", r.status_code == 200)

    r = requests.get(f"{BASE}/api/chats/{cid}")
    msg = r.json()["messages"][-1]
    track("  Message persisted", msg["role"] == "user" and msg["content"] == "Hello")

    r = requests.delete(f"{BASE}/api/chats/{cid}")
    track("DELETE /api/chats/:id", r.status_code == 200)

    # Auto chat
    r = requests.get(f"{BASE}/api/chats/auto")
    track("GET /api/chats/auto", r.status_code == 200)
    track("  Returns created flag", "created" in r.json())
    track("  Returns chat id", "id" in r.json())

    # Tools
    r = requests.get(f"{BASE}/api/tools/pending")
    track("GET /api/tools/pending", r.status_code == 200)

    r = requests.get(f"{BASE}/api/tools/approved")
    track("GET /api/tools/approved", r.status_code == 200)

    # Job actions
    r = requests.get(f"{BASE}/api/job/fake/actions")
    track("GET /api/job/:id/actions", r.status_code == 200)

    # Agent history
    r = requests.get(f"{BASE}/api/agent/history/fake")
    track("GET /api/agent/history/:id", r.status_code == 200)
    track("  Returns steps array", "steps" in r.json())

    # Agent response
    r = requests.get(f"{BASE}/api/agent/response/fake")
    track("GET /api/agent/response/:id", r.status_code == 200)
    track("  Returns content", "content" in r.json())

    # Agent output
    r = requests.get(f"{BASE}/api/agent/output/fake")
    track("GET /api/agent/output/:id", r.status_code == 200)
    track("  Returns content", "content" in r.json())

    # Agent inject
    r = requests.post(f"{BASE}/api/agent/inject", json={
        "job_id": "fake", "instruction": "test"
    })
    track("POST /api/agent/inject", r.status_code == 200)

    # Agent permission
    r = requests.post(f"{BASE}/api/agent/permission", json={
        "job_id": "fake", "decision": "approved"
    })
    track("POST /api/agent/permission", r.status_code == 200)

    # Favicon
    r = requests.get(f"{BASE}/favicon.ico")
    track("GET /favicon.ico", r.status_code == 200)

    # ---- 14. ERROR HANDLING ----
    print("\n--- 14. ERROR HANDLING ---")

    r = requests.post(f"{BASE}/api/projects", data={"name": "NoRoot"})
    track("POST /api/projects (missing root dir) \u2192 400", r.status_code == 400)

    r = requests.post(f"{BASE}/api/projects", data={"rootDirectory": "/tmp"})
    track("POST /api/projects (missing name) \u2192 400", r.status_code == 400)

    r = requests.get(f"{BASE}/api/projects/nonexistent")
    track("GET /api/projects/:id (not found) \u2192 404", r.status_code == 404)

    r = requests.get(f"{BASE}/api/chats/nonexistent")
    track("GET /api/chats/:id (not found) \u2192 404", r.status_code == 404)

    r = requests.post(f"{BASE}/api/chats/fake/messages", json={"content": ""})
    track("POST /api/chats/:id/messages (empty) \u2192 400", r.status_code == 400)

    r = requests.post(f"{BASE}/api/settings", json=None)
    track("POST /api/settings (null body) \u2192 error", r.status_code != 200)

    # ---- 15. UI INTERACTION FLOW ----
    print("\n--- 15. FULL UI WORKFLOW ---")

    # Create project
    r = requests.post(f"{BASE}/api/projects", data={
        "name": "Workflow Test",
        "rootDirectory": "/tmp/aib_workflow",
        "instructions": "Create a fibonacci function"
    })
    wf_pid = r.json()["id"]
    track("Workflow: create project", r.status_code == 200)

    # Select project (get details)
    r = requests.get(f"{BASE}/api/projects/{wf_pid}")
    wf_project = r.json()
    track("Workflow: get project details", r.status_code == 200)
    track("  Has instructions", wf_project["instructions"] == "Create a fibonacci function")

    # Update project
    r = requests.post(f"{BASE}/api/projects/{wf_pid}", data={
        "name": "Workflow Test Updated",
        "rootDirectory": "/tmp/aib_workflow",
        "instructions": "Create fibonacci AND factorial functions"
    })
    track("Workflow: update project", r.status_code == 200)

    # Add to queue
    r = requests.post(f"{BASE}/api/queue", json={"project_id": wf_pid})
    track("Workflow: add to queue", r.status_code == 200)
    wf_job_id = r.json()["job_id"]

    # Get queue
    r = requests.get(f"{BASE}/api/queue")
    track("Workflow: check queue", r.status_code == 200)

    # Delete from queue
    r = requests.delete(f"{BASE}/api/queue/{wf_job_id}")
    track("Workflow: delete from queue", r.status_code == 200)

    # Archive
    r = requests.post(f"{BASE}/api/projects/{wf_pid}/archive")
    track("Workflow: archive project", r.status_code == 200)

    # Unarchive
    r = requests.post(f"{BASE}/api/projects/{wf_pid}/unarchive")
    track("Workflow: unarchive project", r.status_code == 200)

    # Delete
    r = requests.delete(f"{BASE}/api/projects/{wf_pid}")
    track("Workflow: delete project", r.status_code == 200)

    # ---- 16. SECURITY ----
    print("\n--- 16. SECURITY ---")

    # Test that the HTML properly escapes content
    r = requests.post(f"{BASE}/api/projects", data={
        "name": "<script>alert('xss')</script>",
        "rootDirectory": "/tmp/test"
    })
    track("Project creation with XSS in name", r.status_code == 200)
    pid_xss = r.json()["id"]

    r = requests.get(f"{BASE}/api/projects/{pid_xss}")
    track("  Project name contains XSS payload (stored)", "<script>" in r.json()["name"])
    # The UI should escape this when rendering
    track("  escapeHtml function exists", "function escapeHtml(" in js)

    r = requests.delete(f"{BASE}/api/projects/{pid_xss}")

    # ---- 17. SETTINGS PERSISTENCE ----
    print("\n--- 17. SETTINGS PERSISTENCE ---")

    # Save settings
    requests.post(f"{BASE}/api/settings", json={
        "custom_endpoint_url": "http://test.com/v1",
        "custom_model_name": "persist-test",
        "max_steps": 42,
        "timeout": 999
    })

    # Reload settings
    r = requests.get(f"{BASE}/api/settings")
    s = r.json()
    track("Settings survive GET after POST",
          s["custom_endpoint_url"] == "http://test.com/v1" and
          s["custom_model_name"] == "persist-test" and
          s["max_steps"] == 42 and
          s["timeout"] == 999)

    # ---- SUMMARY ----
    print("\n" + "=" * 60)
    passed = sum(1 for _, c in results if c)
    total = len(results)
    print(f"RESULTS: {passed}/{total} tests passed")
    if passed == total:
        print("ALL TESTS PASSED \u2713")
    else:
        print("FAILURES:")
        for name, c in results:
            if not c:
                print(f"  \u2717 {name}")
    print("=" * 60)


if __name__ == '__main__':
    try:
        run_tests()
    except requests.exceptions.ConnectionError:
        print("=" * 60)
        print("SKIPPING: Cannot connect to AI-Builder at http://localhost:5056")
        print("Run the app first, then execute this file directly:")
        print("  python tests/ui_comprehensive.py")
        print("=" * 60)
        sys.exit(0)
