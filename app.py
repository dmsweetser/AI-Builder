import sys
import os
import json
import tempfile
from typing import Any, Dict
import uuid
import time
import subprocess
import platform
import queue
import threading
import shutil
import atexit
import signal
import re
import logging
from datetime import datetime
from flask import Flask, Response, request, jsonify, render_template, send_from_directory
import html
from agent_engine import run as agent_run

# --- Resolve app directory (works for both dev and PyInstaller one-file builds) ---
def _get_app_dir():
    """Return the directory containing the app.

    For PyInstaller one-file builds, sys._MEIPASS points to the extracted
    temp directory that contains templates/ and static/ bundled by PyInstaller.
    For one-dir builds, same thing — sys._MEIPASS has the bundled assets.
    For dev, use the directory containing this file.
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller one-file or one-dir build: assets are in the extracted temp dir
        return sys._MEIPASS
    if getattr(sys, 'frozen', False):
        # PyInstaller one-file build running from disk: assets are next to the exe
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

_app_dir = _get_app_dir()

from agent_engine import AgentEngine, EngineConfig, ToolResult, get_registry
from agent_engine.config import EngineConfig as Config

# --- Determine template/static paths ---
# In dev: templates/ and static/ are real directories on disk
# In PyInstaller one-file: they're inside the _MEIPASS temp dir
_templates_dir = os.path.join(_app_dir, 'templates')
_static_dir = os.path.join(_app_dir, 'static')

# Verify assets exist; if not, fall back to the exe directory (one-file from disk)
if not os.path.isdir(_templates_dir) or not os.path.isdir(_static_dir):
    _fallback_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    if os.path.isdir(os.path.join(_fallback_dir, 'templates')):
        _templates_dir = os.path.join(_fallback_dir, 'templates')
        _static_dir = os.path.join(_fallback_dir, 'static')
        _app_dir = _fallback_dir

app = Flask(__name__,
            template_folder=_templates_dir,
            static_folder=_static_dir)

# --- Constants (all relative to the app directory) ---
_AIB_INSTANCE = os.path.join(_app_dir, "aib_instance")
STATUS_FILE = os.path.join(_AIB_INSTANCE, "run_status.json")
HISTORY_FILE = os.path.join(_AIB_INSTANCE, "job_history.json")
PROJECTS_DIR = os.path.join(_AIB_INSTANCE)  # Project dirs live directly under aib_instance/<pid>/
os.makedirs(PROJECTS_DIR, exist_ok=True)
CHATS_DIR = os.path.join(_AIB_INSTANCE, "chats")
SETTINGS_FILE = os.path.join(_AIB_INSTANCE, "settings.json")

# --- Global State (Thread-Safe) ---
job_queue = []
running_job = None
job_history = []
job_queue_lock = threading.Lock()
stop_event = threading.Event()
worker_thread = None
_worker_wake = threading.Event()  # Signals the worker to check the queue

# Track the active SSE event queue per output_dir so the resume engine
# can emit events to the UI (e.g., pending_approval for subsequent tools).
_sse_event_queues: Dict[str, queue.Queue] = {}
_sse_event_queues_lock = threading.Lock()

# --- Settings State ---
settings_lock = threading.RLock()  # RLock allows re-entrant locking
settings_cache = {}
# Global settings cache for engine access
_settings = {}


def _load_settings_unlocked():
    """Internal: load settings from disk without acquiring lock. Must be called inside settings_lock."""
    loaded = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
        except Exception:
            loaded = {}

    # Fill defaults for anything not in settings file
    loaded.setdefault('custom_endpoint_url', "")
    loaded.setdefault('custom_api_key', "")
    loaded.setdefault('custom_model_name', "")
    loaded.setdefault('custom_verify_ssl', False)
    loaded.setdefault('max_steps', 500)
    loaded.setdefault('timeout', 7200)
    loaded.setdefault('max_context_tokens', 262144)
    loaded.setdefault('max_output_tokens', 131072)
    loaded.setdefault('max_tool_result_length', 2000)
    loaded.setdefault('root_directory', "")
    loaded.setdefault('jd_cli_path', "")
    loaded.setdefault('java_home', "")
    loaded.setdefault('dotnet_cli_path', "")

    return loaded


def load_settings():
    """Load settings from disk, falling back to defaults."""
    global settings_cache, _settings
    with settings_lock:
        if settings_cache:
            return settings_cache.copy()
        loaded = _load_settings_unlocked()
        settings_cache = loaded
        _settings = loaded
        return loaded.copy()


def save_settings(settings):
    """Save settings to disk and update cache."""
    with settings_lock:
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=2)
            settings_cache.clear()
            _settings.clear()
            load_settings()  # Reload into cache
            # Sync to engine config
            from agent_engine.config import set_global_settings
            set_global_settings(get_settings())
        except Exception as e:
            logging.error(f"Failed to save settings: {e}")


def get_settings():
    """Get the current settings dict (thread-safe)."""
    global _settings
    with settings_lock:
        if not _settings:
            load_settings()
        return dict(_settings)


# --- Initialization ---
def init_directories():
    """Create all persistent data directories."""
    # Ensure the parent aib_instance directory exists first
    os.makedirs(_AIB_INSTANCE, exist_ok=True)
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(PROJECTS_DIR), exist_ok=True)
    os.makedirs(CHATS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    # Ensure output directory exists for agent engine
    os.makedirs(os.path.join(_AIB_INSTANCE, "output"), exist_ok=True)

def load_job_history():
    global job_history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                job_history = json.load(f)
            for job in job_history:
                if job.get("status") == "running":
                    job["status"] = "stopped"
        except Exception:
            job_history = []
    else:
        job_history = []

def save_job_history():
    tmp_path = HISTORY_FILE + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(job_history, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, HISTORY_FILE)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

def load_projects():
    """Load all projects from per-project directories under aib_instance/<pid>/.

    Each project lives in aib_instance/<uuid>/ with:
      - project.json (the project config)
      - output/ (run artifacts)
      - tools/active/, tools/pending/ (project-local tools)
    """
    projects = []
    for pid in sorted(os.listdir(PROJECTS_DIR)):
        pid_path = os.path.join(PROJECTS_DIR, pid)
        if not os.path.isdir(pid_path):
            continue
        # Skip non-project directories (output, chats, settings.json, etc.)
        proj_file = os.path.join(pid_path, "project.json")
        if not os.path.exists(proj_file):
            continue
        try:
            with open(proj_file, "r", encoding="utf-8") as f:
                p = json.load(f)
            # Ensure output_dir exists
            output_dir = p.get("output_dir", "")
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            else:
                # Legacy fallback: build output_dir from old convention
                output_dir = os.path.join(_AIB_INSTANCE, pid, "output")
                p["output_dir"] = output_dir
                os.makedirs(output_dir, exist_ok=True)
            projects.append(p)
        except Exception:
            continue
    return projects


# --- Project Lock (prevents concurrent writes that corrupt project.json) ---
_project_lock = threading.RLock()


def _save_project_unlocked(project):
    """Internal: save a project to aib_instance/<pid>/project.json (thread-safe, atomic)."""
    pid = project.get("id", "")
    if not pid:
        raise ValueError("Project must have an id")
    fpath = os.path.join(PROJECTS_DIR, pid, "project.json")
    # Validate project structure before writing
    required_fields = ["id", "name", "rootDirectory"]
    for field in required_fields:
        if field not in project:
            raise ValueError(f"Project missing required field: {field}")
    # Ensure the project directory exists
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    # Atomic write: write to temp file first, then rename
    tmp_path = fpath + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(project, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, fpath)
    except Exception:
        # Clean up temp file on failure
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def save_project(project):
    """Save a single project to its own JSON file (thread-safe, atomic write)."""
    with _project_lock:
        _save_project_unlocked(project)


def delete_project_file(pid):
    """Delete a project's directory (aib_instance/<pid>/)."""
    proj_dir = os.path.join(PROJECTS_DIR, pid)
    if os.path.exists(proj_dir):
        shutil.rmtree(proj_dir)
        return True
    return False

# --- Worker Thread ---
def worker():
    global running_job
    while not stop_event.is_set():
        _worker_wake.clear()
        with job_queue_lock:
            if running_job is None and job_queue:
                running_job = job_queue.pop(0)
            else:
                # Wait for wake signal or timeout (max 0.5s)
                _worker_wake.wait(timeout=0.5)
                continue

        job_id = running_job["job_id"]
        pid = running_job["project_id"]
        project, _ = get_project(pid)

        # Use project's persistent output directory: aib_instance/<pid>/output/
        if project and "output_dir" in project:
            output_dir = project["output_dir"]
        else:
            output_dir = os.path.join(_AIB_INSTANCE, pid, "output")
        os.makedirs(output_dir, exist_ok=True)

        job_history.append({
            "job_id": job_id,
            "project_id": pid,
            "project_name": project.get("name", "Unknown") if project else "Unknown",
            "status": "running",
            "instructions": project.get("instructions", "") if project else "",
            "timestamp": datetime.now().isoformat()
        })
        save_job_history()

        try:
            if project:
                result = run_with_agent_engine(project, output_dir=output_dir)
                job_history[-1]["status"] = result.get("status", "completed")
                job_history[-1]["summary"] = result.get("summary", "")
                job_history[-1]["steps"] = result.get("steps", 0)
                if result.get("status") == "error":
                    job_history[-1]["error"] = result.get("error", "Unknown error")
                # Store step history for job detail view
                if "step_history" in result:
                    job_history[-1]["step_history"] = result["step_history"]
            else:
                job_history[-1]["status"] = "error"
                job_history[-1]["error"] = "Project not found"
        except Exception as e:
            if job_history.count() > 0:
                job_history[-1]["status"] = "error"
                job_history[-1]["error"] = str(e)
        finally:
            # Check for incomplete actions file
            actions_file = os.path.join(output_dir, "actions.txt")
            if os.path.exists(actions_file):
                job_history[-1]["incomplete"] = True
            # Update project's last_job_id
            if project:
                project["last_job_id"] = job_id
                save_project(project)
            save_job_history()
            with job_queue_lock:
                running_job = None


def run_with_agent_engine(project_config: Dict[str, Any], output_dir: str = None) -> Dict[str, Any]:
    """Run the multi-step agentic engine (delegates to agent_engine)."""

    if "job_id" not in project_config:
        project_config["job_id"] = str(int(time.time() * 1000))

    root_dir = project_config.get("rootDirectory", "")

    if output_dir is None:
        pid = project_config.get("id", project_config.get("job_id", ""))
        output_dir = os.path.join(root_dir, "aib_instance", pid, "output")

    # Write instructions to a file to avoid env var length limits
    instructions_file = os.path.join(output_dir, "instructions.txt")
    os.makedirs(output_dir, exist_ok=True)
    with open(instructions_file, 'w', encoding='utf-8') as f:
        f.write(project_config.get("instructions", ""))

    # Clean old step files from previous runs in this project's output dir
    # so a fresh run doesn't pick up stale steps
    steps_dir = os.path.join(output_dir, "steps")
    if os.path.isdir(steps_dir):
        for fname in os.listdir(steps_dir):
            if fname.endswith(".json"):
                try:
                    os.remove(os.path.join(steps_dir, fname))
                except OSError:
                    pass
    # Also clean legacy steps.jsonl
    step_log = os.path.join(output_dir, "steps.jsonl")
    if os.path.exists(step_log):
        try:
            os.remove(step_log)
        except OSError:
            pass
    # Clean conversation_history.json so the engine starts fresh
    conv_hist = os.path.join(output_dir, "conversation_history.json")
    if os.path.exists(conv_hist):
        try:
            os.remove(conv_hist)
        except OSError:
            pass
    # Clean resume/instruction state from previous runs
    try:
        status_file = os.path.join(output_dir, "status.json")
        if os.path.exists(status_file):
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
            # Clear pending state fields, keep status/step/timestamp
            status.pop("pending_user_input", None)
            status.pop("pending_live_instruction", None)
            status.pop("last_user_message", None)
            tmp_file = status_file + ".tmp"
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(status, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, status_file)
    except Exception:
        pass

    return agent_run(project_config, output_dir=output_dir)


def start_worker():
    global worker_thread
    if worker_thread and worker_thread.is_alive():
        # Worker is alive, signal it to check the queue
        _worker_wake.set()
        return
    stop_event.clear()
    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()

def stop_worker():
    global worker_thread
    stop_event.set()
    if worker_thread and worker_thread.is_alive():
        worker_thread.join(timeout=5)

def cleanup():
    stop_worker()
    save_job_history()

atexit.register(cleanup)

# --- Project Helpers ---
def get_project(pid):
    projects = load_projects()
    return next((p for p in projects if p["id"] == pid), None), projects

def is_project_running(pid):
    with job_queue_lock:
        if running_job and running_job["project_id"] == pid:
            return True
        return any(job["project_id"] == pid for job in job_queue)


def get_concurrent_job_info(pid):
    """Return (is_running, is_queued, existing_job_id) for a project."""
    with job_queue_lock:
        if running_job and running_job["project_id"] == pid:
            return True, False, running_job["job_id"]
        for job in job_queue:
            if job["project_id"] == pid:
                return False, True, job["job_id"]
        return False, False, None

def _reconstruct_from_step_history(engine, step_history, instructions, is_continuation=False):
    """Reconstruct conversation history from step_history (fallback when conversation_history.json is not available)."""
    reconstructed_messages = [engine.messages[0]]  # system prompt
    
    if is_continuation and step_history:
        # Continuation: use the original first user prompt (task instructions) without re-listing
        first_user = next((m for m in engine.messages if m.get("role") == "user"), None)
        if first_user:
            reconstructed_messages.append({
                "role": "user",
                "content": first_user["content"],
            })
    else:
        # Fresh start: tell the LLM to start with list_directory
        reconstructed_messages.append({
            "role": "user",
            "content": f"""TASK INSTRUCTIONS:
{instructions}

CRITICAL INSTRUCTIONS:
1. You MUST use a tool call to take action. Do NOT just talk about what you will do.
2. Your FIRST action MUST be: list_directory with path="."
3. Do NOT use task_completed until you have actually used tools and gathered information.
4. Your ENTIRE response must be ONLY a tool call block or task_completed tool call. No other text.
5. Format your tool call EXACTLY like this example:

[TOOL_START]
[TOOL_NAME]
a tool name
[PARAM_NAME]
a relevant param name
[PARAM_VALUE]
a relevant param value
[TOOL_END]

STEP 1: Use list_directory to explore the project structure. Do NOT use task_completed yet - you must take action first."""
        })
    # Add tool results from step_history
    all_tool_names = engine.tools.tool_names()
    for h in step_history:
        if h.get("tool") in all_tool_names:
            result = h.get("result", {})
            content = result.get("content", "")
            error = result.get("error", "")
            summary = result.get("summary", "")
            if error:
                result_display = f"Error: {error}"
            elif summary:
                result_display = summary
                if content:
                    result_display += f"\n\nOutput:\n{content}\n"
            elif content:
                result_display = content
            else:
                result_display = "(no output)"
            tool_name = h.get("tool", "unknown")
            reconstructed_messages.append({
                "role": "user",
                "content": f"[TOOL RESULT for {tool_name}]\n{result_display}\n[END TOOL RESULT]\n\nNow continue with your next action."
            })
    # Add the continuation message with a verbose tool format reminder
    reconstructed_messages.append({
        "role": "user",
        "content": (
            f"[CONTINUATION] Your previous run completed. "
            f"The user has new instructions for you. "
            f"Please continue working on the project with these new instructions:\n\n"
            f"{instructions}\n\n"
            f"Review what was already done, then take the next appropriate action.\n\n"
            f"TOOL FORMAT REMINDER\n"
            f"=====================\n\n"
            f"Your ENTIRE response must be EXACTLY ONE of the following:\n\n"
            f"  OPTION 1 — A tool call:\n"
            f"    [TOOL_START]\n"
            f"    [TOOL_NAME]\n"
            f"    <tool_name>\n"
            f"    [PARAM_NAME]\n"
            f"    <param_key_1>\n"
            f"    [PARAM_VALUE]\n"
            f"    <param_value_1>\n"
            f"    [PARAM_NAME]\n"
            f"    <param_key_2>\n"
            f"    [PARAM_VALUE]\n"
            f"    <param_value_2>\n"
            f"    [TOOL_END]\n\n"
            f"  OPTION 2 — Signal completion:\n"
            f"    Use the task_completed tool with a summary:\n"
            f"    [TOOL_START]\n"
            f"    [TOOL_NAME]\n"
            f"    task_completed\n"
            f"    [PARAM_NAME]\n"
            f"    summary\n"
            f"    [PARAM_VALUE]\n"
            f"    <your summary here>\n"
            f"    [TOOL_END]\n\n"
            f"IMPORTANT RULES:\n"
            f"  • Do NOT write any other text.\n"
            f"  • Do NOT explain what you will do — just act.\n"
            f"  • Make EXACTLY ONE tool call per response.\n"
            f"  • If you include more than one [TOOL_START]...[TOOL_END] block,\n"
            f"    only the FIRST one will be executed."
        )
    })
    engine.messages = reconstructed_messages


# --- Routes: Projects ---
@app.route("/")
def index():
    projects = load_projects()
    return render_template("index.html", projects=projects)

@app.route("/api/projects", methods=["GET"])
def api_get_projects():
    projects = load_projects()
    return jsonify(projects)

@app.route("/api/projects/<pid>", methods=["GET"])
def api_get_project(pid):
    project, _ = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    project.pop("modelConfig", None)
    return jsonify(project)

@app.route("/api/projects", methods=["POST"])
def api_create_project():
    with _project_lock:
        projects = load_projects()
        pid = str(uuid.uuid4())

        # Accept both JSON and form-encoded data
        data = request.get_json(silent=True) or request.form.to_dict()
        name = data.get("name", "")
        if not name:
            return jsonify({"error": "Project name is required"}), 400

        root_directory = data.get("rootDirectory", "")
        if not root_directory:
            return jsonify({"error": "Root directory is required"}), 400

        # Determine output directory: aib_instance/<pid>/output/
        output_dir = os.path.join(_AIB_INSTANCE, pid, "output")
        os.makedirs(output_dir, exist_ok=True)

        project = {
            "id": pid,
            "name": name,
            "rootDirectory": root_directory,
            "instructions": data.get("instructions", ""),
            "isArchived": False,
            "disabled_tools": [],
            "output_dir": output_dir,
            "run_number": 0,
            "last_job_id": None,
        }

        # Create the project directory structure
        proj_dir = os.path.join(PROJECTS_DIR, pid)
        os.makedirs(proj_dir, exist_ok=True)
        os.makedirs(os.path.join(proj_dir, "tools", "active"), exist_ok=True)
        os.makedirs(os.path.join(proj_dir, "tools", "pending"), exist_ok=True)

        projects.append(project)
        _save_project_unlocked(project)
        return jsonify(project)

@app.route("/api/projects/<pid>", methods=["POST"])
def api_update_project(pid):
    with _project_lock:
        project, projects = get_project(pid)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # Accept both JSON and form-encoded data (like api_create_project)
        data = request.get_json(silent=True) or request.form.to_dict()

        root_directory = data.get("rootDirectory", project.get("rootDirectory", ""))
        if not root_directory:
            return jsonify({"error": "Root directory is required"}), 400

        # Sanitize instructions: store as a JSON-safe string to prevent corruption
        # when pasting large blocks of text with special characters
        instructions = data.get("instructions", project.get("instructions", ""))
        # Ensure instructions is a proper string (not raw bytes or None)
        if instructions is None:
            instructions = ""
        elif not isinstance(instructions, str):
            instructions = str(instructions)

        project.update({
            "name": data.get("name", project.get("name", "")),
            "rootDirectory": root_directory,
            "instructions": instructions,
        })

        # Clean up old enabled_tools field if present
        project.pop("enabled_tools", None)
        _save_project_unlocked(project)
        return jsonify({"status": "saved", "project": project})

@app.route("/api/projects/<pid>/archive", methods=["POST"])
def api_archive_project(pid):
    with _project_lock:
        projects = load_projects()
        for project in projects:
            if project["id"] == pid:
                project["isArchived"] = True
                _save_project_unlocked(project)
                break
        return jsonify({"status": "archived"})

@app.route("/api/projects/<pid>/unarchive", methods=["POST"])
def api_unarchive_project(pid):
    with _project_lock:
        projects = load_projects()
        for project in projects:
            if project["id"] == pid:
                project["isArchived"] = False
                _save_project_unlocked(project)
                break
        return jsonify({"status": "unarchived"})


@app.route("/api/projects/<pid>/reset", methods=["POST"])
def api_reset_project(pid):
    """Reset a project: kill any running job, archive output, reset run counter."""
    try:
        project, projects = get_project(pid)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # Check if project is currently running or queued
        is_running, is_queued, existing_job_id = get_concurrent_job_info(pid)
        if is_running or is_queued:
            # Kill the running/queued job first
            _kill_job_for_project(pid)
            # Small delay to let the worker clean up
            import time as _time
            _time.sleep(0.3)

        # Archive the output directory with a datestamp so you can reset multiple times
        output_dir = project.get("output_dir", os.path.join(_AIB_INSTANCE, pid, "output"))
        archive_name = "archive_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_dir = os.path.join(os.path.dirname(output_dir), archive_name)
        if os.path.exists(output_dir):
            # Remove old archive for this reset if it exists (shouldn't, but be safe)
            if os.path.exists(archive_dir):
                shutil.rmtree(archive_dir)
            shutil.copytree(output_dir, archive_dir)
            # Wipe the output directory contents
            for fname in os.listdir(output_dir):
                fpath = os.path.join(output_dir, fname)
                if os.path.isdir(fpath):
                    shutil.rmtree(fpath)
                else:
                    os.remove(fpath)
        # Create fresh output directory
        os.makedirs(output_dir, exist_ok=True)

        # Reset project state
        project["run_number"] = 0
        project["last_job_id"] = None
        save_project(project)

        # Also remove this project's entries from job_history
        global job_history
        job_history = [h for h in job_history if h.get("project_id") != pid]
        save_job_history()

        return jsonify({"status": "reset", "project": project})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _kill_job_for_project(pid):
    """Kill a running or queued job for a project."""
    global running_job
    with job_queue_lock:
        # Remove from queue
        job_queue[:] = [j for j in job_queue if j["project_id"] != pid]
        # Stop running job if it's for this project
        if running_job and running_job["project_id"] == pid:
            running_job = None
    start_worker()


@app.route("/api/projects/<pid>/run", methods=["POST"])
def api_run_project(pid):
    """Queue a project to run, using its persistent output directory."""
    project, projects = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Guard: reject if project is already running or queued
    is_running, is_queued, existing_job_id = get_concurrent_job_info(pid)
    if is_running:
        return jsonify({"error": "Project is already running", "job_id": existing_job_id}), 409
    if is_queued:
        return jsonify({"error": "Project is already queued", "job_id": existing_job_id}), 409

    # Use project's persistent output directory: aib_instance/<pid>/output/
    output_dir = project.get("output_dir", os.path.join(_AIB_INSTANCE, pid, "output"))
    os.makedirs(output_dir, exist_ok=True)

    # Increment run number
    project["run_number"] = project.get("run_number", 0) + 1
    run_number = project["run_number"]
    project["last_job_id"] = None  # Will be set when run completes
    save_project(project)

    job_id = str(int(time.time() * 1000))

    with job_queue_lock:
        job_queue.append({"job_id": job_id, "project_id": pid})
    start_worker()
    return jsonify({"status": "queued", "job_id": job_id, "run_number": run_number, "output_dir": output_dir})

# --- Routes: Queue ---
@app.route("/api/agent/run", methods=["POST"])
def api_agent_run():
    """Start a new agent run from the frontend (non-project-lookup path).

    Accepts JSON with: project_id, rootDirectory, instructions,
    and optionally continue_from_job / new_instruction for continuation.
    """
    data = request.get_json(silent=True) or {}
    pid = data.get("project_id")

    if pid:
        project, projects = get_project(pid)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        root_dir = data.get("rootDirectory", project.get("rootDirectory", ""))
        instructions = data.get("instructions", project.get("instructions", ""))
        continue_from_job = data.get("continue_from_job")
        new_instruction = data.get("new_instruction")

        if not root_dir:
            return jsonify({"error": "Root directory is required"}), 400

        # Use project's persistent output directory: aib_instance/<pid>/output/
        output_dir = project.get("output_dir", os.path.join(_AIB_INSTANCE, pid, "output"))
        os.makedirs(output_dir, exist_ok=True)

        # If continuing from a previous job, merge instructions
        if continue_from_job and new_instruction:
            instructions = new_instruction
    else:
        root_dir = data.get("rootDirectory", "")
        instructions = data.get("instructions", "")
        if not root_dir:
            return jsonify({"error": "Root directory is required"}), 400
        output_dir = os.path.join(_AIB_INSTANCE, str(uuid.uuid4()), "output")
        os.makedirs(output_dir, exist_ok=True)
        project = None

    # Increment run number if we have a project
    if project:
        project["run_number"] = project.get("run_number", 0) + 1
        run_number = project["run_number"]
        project["last_job_id"] = None
        save_project(project)
    else:
        run_number = 0

    job_id = str(int(time.time() * 1000))

    with job_queue_lock:
        job_queue.append({"job_id": job_id, "project_id": pid or job_id})
    start_worker()
    return jsonify({
        "status": "queued",
        "job_id": job_id,
        "run_number": run_number,
        "output_dir": output_dir,
    })


@app.route("/api/queue", methods=["GET"])
def api_get_queue():
    with job_queue_lock:
        projects = load_projects()
        project_map = {p["id"]: p.get("name", "Unknown") for p in projects}

        running_name = project_map.get(running_job["project_id"], "Unknown") if running_job else None
        queue_with_names = []
        for j in job_queue:
            queue_with_names.append({**j, "project_name": project_map.get(j["project_id"], "Unknown"), "status": "queued"})

    return jsonify({
        "queue": queue_with_names,
        "running": {**running_job, "project_name": running_name} if running_job else None
    })

@app.route("/api/job/<job_id>/actions", methods=["GET"])
def api_get_job_actions(job_id):
    actions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "output", job_id, "actions.txt")
    if os.path.exists(actions_path):
        with open(actions_path, 'r', encoding='utf-8') as f:
            return jsonify({"content": f.read()})
    return jsonify({"content": "", "error": "No actions file found"})

@app.route("/api/queue", methods=["POST"])
def api_add_to_queue():
    data = request.json
    pid = data.get("project_id")
    if not pid:
        return jsonify({"error": "project_id required"}), 400
    project, projects = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Guard: reject if project is already running or queued
    is_running, is_queued, existing_job_id = get_concurrent_job_info(pid)
    if is_running:
        return jsonify({"error": "Project is already running", "job_id": existing_job_id}), 409
    if is_queued:
        return jsonify({"error": "Project is already queued", "job_id": existing_job_id}), 409

    # Use project's persistent output directory: aib_instance/<pid>/output/
    output_dir = project.get("output_dir", os.path.join(_AIB_INSTANCE, pid, "output"))
    os.makedirs(output_dir, exist_ok=True)

    # Increment run number
    project["run_number"] = project.get("run_number", 0) + 1
    run_number = project["run_number"]
    project["last_job_id"] = None
    save_project(project)

    job_id = str(int(time.time() * 1000))
    with job_queue_lock:
        job_queue.append({"job_id": job_id, "project_id": pid})
    start_worker()
    return jsonify({"status": "queued", "job_id": job_id, "run_number": run_number, "output_dir": output_dir})

@app.route("/api/queue/<job_id>", methods=["DELETE"])
def api_delete_from_queue(job_id):
    global running_job
    with job_queue_lock:
        job_queue[:] = [j for j in job_queue if j["job_id"] != job_id]
        if running_job and running_job["job_id"] == job_id:
            running_job = None
    start_worker()
    return jsonify({"status": "deleted"})

@app.route("/api/queue/running/stop", methods=["POST"])
def api_stop_running():
    global running_job
    with job_queue_lock:
        job_to_stop = running_job
        running_job = None

    start_worker()
    return jsonify({"status": "stopped"})


@app.route("/api/agent/stop/<job_id>", methods=["POST"])
def api_stop_agent(job_id):
    """Stop a running agent job."""
    # Job may have already completed (e.g., pending_user_input).
    # Mark it as stopped in history if found.
    for job in job_history:
        if job.get("job_id") == job_id and job.get("status") in ("pending_user_input", "pending_approval", "running"):
            job["status"] = "stopped"
            _log_app_event(f"Job {job_id} marked as stopped in history")
            return jsonify({"status": "stopped", "reason": "job_was_pending"})

    return jsonify({"status": "not_found", "error": "Job not found or already stopped"}), 404

@app.route("/api/projects/<pid>", methods=["DELETE"])
def api_delete_project(pid):
    global running_job
    with job_queue_lock:
        job_queue[:] = [j for j in job_queue if j["project_id"] != pid]
        if running_job and running_job["project_id"] == pid:
            running_job = None
    start_worker()

    delete_project_file(pid)
    return jsonify({"status": "deleted"})

# --- Routes: History ---
@app.route("/api/history", methods=["GET"])
def api_get_history():
    with job_queue_lock:
        projects = load_projects()
        project_map = {p["id"]: p.get("name", "Unknown") for p in projects}

        queued_jobs = []
        for j in job_queue:
            queued_jobs.append({
                "job_id": j["job_id"],
                "project_id": j["project_id"],
                "project_name": project_map.get(j["project_id"], "Unknown"),
                "status": "queued",
                "timestamp": datetime.now().isoformat()
            })

        current_job_history = sorted(job_history, key=lambda x: x["timestamp"], reverse=True)
        history_ids = {h["job_id"] for h in current_job_history}
        for qj in queued_jobs:
            if qj["job_id"] not in history_ids:
                current_job_history.insert(0, qj)

        # Enrich with project run info
        for h in current_job_history:
            pid = h.get("project_id")
            if pid and pid in project_map:
                for p in projects:
                    if p["id"] == pid:
                        h["run_number"] = p.get("run_number", 0)
                        h["output_dir"] = p.get("output_dir", "")
                        break

    return jsonify(current_job_history)

@app.route("/api/history/clear", methods=["POST"])
def api_clear_history():
    global job_history
    with job_queue_lock:
        job_history.clear()
        save_job_history()
    return jsonify({"status": "cleared"})

# --- Routes: Chat ---
@app.route("/api/chats", methods=["GET"])
def api_list_chats():
    chats = []
    if os.path.exists(CHATS_DIR):
        for fname in os.listdir(CHATS_DIR):
            if fname.endswith(".json"):
                fpath = os.path.join(CHATS_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        first_message = data.get("messages", [{}])[0] if data.get("messages") else {}
                        title = first_message.get("content", "New Chat")[:30]
                        timestamp = data.get("timestamp", data.get("id", ""))
                        chats.append({
                            "id": data.get("id", fname.replace(".json", "")),
                            "title": title,
                            "timestamp": timestamp
                        })
                except Exception:
                    continue
    chats.sort(key=lambda x: x.get("timestamp", x.get("id", "")), reverse=True)
    return jsonify(chats)

@app.route("/api/chats", methods=["POST"])
def api_create_chat():
    os.makedirs(CHATS_DIR, exist_ok=True)
    chat_id = str(uuid.uuid4())
    chat_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
    timestamp = request.json.get("timestamp", datetime.now().isoformat()) if request.json else datetime.now().isoformat()
    with open(chat_path, "w", encoding="utf-8") as f:
        json.dump({"id": chat_id, "messages": [], "timestamp": timestamp}, f)
    return jsonify({"id": chat_id, "timestamp": timestamp})

@app.route("/api/chats/<chat_id>", methods=["GET"])
def api_get_chat(chat_id):
    chat_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
    if not os.path.exists(chat_path):
        return jsonify({"error": "Chat not found"}), 404
    try:
        with open(chat_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/chats/<chat_id>/messages", methods=["POST"])
def api_send_message(chat_id):
    data = request.get_json(silent=True) or {}
    message = data.get("content", data.get("message", ""))
    if not message:
        return jsonify({"error": "Missing message content"}), 400

    chat_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
    if not os.path.exists(chat_path):
        return jsonify({"error": "Chat not found"}), 404

    try:
        with open(chat_path, "r", encoding="utf-8") as f:
            chat_data = json.load(f)

        if chat_data["messages"] and chat_data["messages"][-1].get("role") == "user" and chat_data["messages"][-1].get("content") == message:
            chat_data["messages"].pop()

        chat_data["messages"].append({"role": "user", "content": message})
        chat_data["timestamp"] = datetime.now().isoformat()
        with open(chat_path, "w", encoding="utf-8") as f:
            json.dump(chat_data, f, indent=2)

        messages = chat_data["messages"]
        prompt_parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                prompt_parts.append(f"User: {content}")
            else:
                prompt_parts.append(f"Assistant: {content}")

        prompt = "\n".join(prompt_parts) + "\nAssistant:"

        def generate():
            response_content = ""
            try:
                import urllib.request
                import ssl
                endpoint_url = Config.get_custom_endpoint_url()
                api_key = Config.get_custom_api_key()
                model_name = Config.get_custom_model_name()
                if not all([endpoint_url, model_name]):
                    raise ValueError("Missing custom endpoint credentials")
                openai_messages = []
                for msg in chat_data["messages"]:
                    openai_messages.append({"role": msg["role"], "content": msg["content"]})
                payload = {
                    "model": model_name,
                    "messages": openai_messages,
                    "stream": True,
                }
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                verify_ssl = Config.get_custom_verify_ssl()
                if verify_ssl:
                    context = ssl.create_default_context()
                else:
                    context = ssl._create_unverified_context()
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(endpoint_url, data=data, headers=headers, method='POST')
                with urllib.request.urlopen(req, context=context, timeout=300) as response:
                    for line in response:
                        line = line.decode('utf-8').strip()
                        if not line.startswith('data: '):
                            continue
                        data_str = line[6:]
                        if data_str == '[DONE]':
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get('choices', [{}])[0].get('delta', {})
                            # Only use 'content' — 'reasoning_content' is internal thinking
                            c = delta.get('content', '')
                            if c:
                                response_content += c
                                yield c
                                if len(response_content) % 20 == 0:
                                    chat_data["messages"] = [m for m in chat_data["messages"] if m["role"] != "assistant"]
                                    chat_data["messages"].append({"role": "assistant", "content": response_content})
                                    chat_data["timestamp"] = datetime.now().isoformat()
                                    with open(chat_path, "w", encoding="utf-8") as f:
                                        json.dump(chat_data, f, indent=2)
                        except json.JSONDecodeError:
                            continue

                chat_data["messages"] = [m for m in chat_data["messages"] if m["role"] != "assistant"]
                chat_data["messages"].append({"role": "assistant", "content": response_content})
                chat_data["timestamp"] = datetime.now().isoformat()
                with open(chat_path, "w", encoding="utf-8") as f:
                    json.dump(chat_data, f, indent=2)
            except Exception as e:
                yield f"Error: {str(e)}"

        return Response(generate(), mimetype='text/plain')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/chats/<chat_id>", methods=["DELETE"])
def api_delete_chat(chat_id):
    chat_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
    if os.path.exists(chat_path):
        os.remove(chat_path)
    return jsonify({"status": "deleted"})

@app.route("/api/chats/auto", methods=["GET"])
def api_auto_chat():
    if not os.path.exists(CHATS_DIR):
        os.makedirs(CHATS_DIR, exist_ok=True)
    chats = []
    if os.path.exists(CHATS_DIR):
        for fname in os.listdir(CHATS_DIR):
            if fname.endswith(".json"):
                chats.append(fname.replace(".json", ""))
    if not chats:
        chat_id = str(uuid.uuid4())
        chat_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
        with open(chat_path, "w", encoding="utf-8") as f:
            json.dump({"id": chat_id, "messages": [], "timestamp": datetime.now().isoformat()}, f)
        return jsonify({"created": True, "id": chat_id})
    return jsonify({"created": False, "id": chats[-1]})

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

# --- Job Status Route ---
@app.route("/api/job-status", methods=["GET"])
def api_job_status():
    with job_queue_lock:
        active_jobs = {
            job["job_id"]: {
                "status": "queued" if job["job_id"] != (running_job["job_id"] if running_job else None) else "running",
                "projectId": job["project_id"]
            }
            for job in job_queue
        }
        if running_job:
            active_jobs[running_job["job_id"]] = {
                "status": "running",
                "projectId": running_job["project_id"]
            }
    return jsonify({"activeJobs": active_jobs, "runStatus": {}})

# --- Settings Routes ---
@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    settings = load_settings()
    return jsonify(settings)

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.json
    if not data:
        return jsonify({"error": "No settings data provided"}), 400

    # Load current settings, then update with provided values
    current = load_settings()
    for key, value in data.items():
        current[key] = value

    save_settings(current)
    return jsonify({"status": "saved"})


@app.route("/api/settings/reload", methods=["POST"])
def api_reload_settings():
    """Force reload settings from disk, bypassing cache."""
    global settings_cache
    with settings_lock:
        settings_cache.clear()
    settings = load_settings()
    return jsonify({"status": "reloaded", "settings": settings})

# --- Agent Routes ---

def _run_engine_in_background(project_config, output_dir, step_callback=None, stop_event=None,
                               prev_step_history=None, continue_from_job=None):
    """Run the engine in a background thread.

    This is a reusable function that creates and runs the engine.
    Used by the tool approval endpoint (for re-invoke).
    Returns a dict with 'result' (engine result) and 'engine' (engine instance).
    """
    from agent_engine import AgentEngine
    engine = AgentEngine(project_config, output_dir=output_dir,
                         step_callback=step_callback, stop_event=stop_event)
    engine.reload_approved_tools()

    # If continuing from a previous job, restore conversation history
    # from step_history so the LLM knows what was already done.
    # For fresh runs (no prev_step_history), the engine starts clean.
    if prev_step_history:
        engine.step_history = prev_step_history
        engine.step_count = len(prev_step_history)
        # Reconstruct conversation from step history
        reconstructed_messages = [engine.messages[0]]  # system prompt
        # Add tool results from step_history
        all_tool_names = engine.tools.tool_names()
        for h in prev_step_history:
            if h.get("tool") in all_tool_names:
                res = h.get("result", {})
                content = res.get("content", "")
                error = res.get("error", "")
                summary = res.get("summary", "")
                if error:
                    result_display = f"Error: {error}"
                elif summary:
                    result_display = summary
                    if content:
                        result_display += f"\n\nOutput:\n{content}\n"
                elif content:
                    result_display = content
                else:
                    result_display = "(no output)"
                tool_name = h.get("tool", "unknown")
                reconstructed_messages.append({
                    "role": "user",
                    "content": f"[TOOL RESULT for {tool_name}]\n{result_display}\n[END TOOL RESULT]\n\nNow continue with your next action."
                })
        # Add the continuation message
        reconstructed_messages.append({
            "role": "user",
            "content": (
                f"[CONTINUATION] Your previous run completed. "
                f"The user has new instructions for you. "
                f"Please continue working on the project with these new instructions:\n\n"
                f"{project_config.get('instructions', '')}\n\n"
                f"Review what was already done, then take the next appropriate action.\n\n"
                f"TOOL FORMAT REMINDER\n"
                f"=====================\n\n"
                f"Your ENTIRE response must be EXACTLY ONE of the following:\n\n"
                f"  OPTION 1 — A tool call:\n"
                f"    [TOOL_START]\n"
                f"    [TOOL_NAME]\n"
                f"    <tool_name>\n"
                f"    [PARAM_NAME]\n"
                f"    <param_key_1>\n"
                f"    [PARAM_VALUE]\n"
                f"    <param_value_1>\n"
                f"    [PARAM_NAME]\n"
                f"    <param_key_2>\n"
                f"    [PARAM_VALUE]\n"
                f"    <param_value_2>\n"
                f"    [TOOL_END]\n\n"
                f"  OPTION 2 — Signal completion:\n"
                f"    Use the task_completed tool with a summary:\n"
                f"    [TOOL_START]\n"
                f"    [TOOL_NAME]\n"
                f"    task_completed\n"
                f"    [PARAM_NAME]\n"
                f"    summary\n"
                f"    [PARAM_VALUE]\n"
                f"    <your summary here>\n"
                f"    [TOOL_END]\n\n"
                f"IMPORTANT RULES:\n"
                f"  • Do NOT write any other text.\n"
                f"  • Do NOT explain what you will do — just act.\n"
                f"  • Make EXACTLY ONE tool call per response.\n"
                f"  • If you include more than one [TOOL_START]...[TOOL_END] block,\n"
                f"    only the FIRST one will be executed."
            )
        })
        engine.messages = reconstructed_messages

    # Run the engine
    result = engine.run()

    # Persist conversation history
    messages_file = os.path.join(output_dir, "conversation_history.json")
    try:
        with open(messages_file, 'w', encoding='utf-8') as f:
            json.dump(engine.messages, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.warning(f"Failed to save conversation history: {e}")

    return {"result": result, "engine": engine}




@app.route("/api/agent/history/<job_id>", methods=["GET"])
def api_agent_history(job_id):
    """Get the step history for a completed agent run."""
    # Try to find the output directory for this job
    output_dir = None
    
    # First, check if this job_id is in history to get the project_id
    for h in job_history:
        if h.get("job_id") == job_id:
            pid = h.get("project_id")
            if pid:
                projects = load_projects()
                for p in projects:
                    if p["id"] == pid:
                        output_dir = p.get("output_dir")
                        break
            break
    
    # Fallback: try aib_instance/<pid>/output/ or aib_instance/<job_id>/output/
    if not output_dir:
        output_dir = os.path.join(_AIB_INSTANCE, job_id, "output")
    
    if not output_dir or not os.path.exists(output_dir):
        return jsonify({"steps": [], "project_id": None})
    
    step_log = os.path.join(output_dir, "steps.jsonl")
    project_id = None
    if os.path.exists(step_log):
        steps = []
        with open(step_log, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        step_data = json.loads(line)
                        steps.append(step_data)
                        if project_id is None and 'project_id' in step_data:
                            project_id = step_data['project_id']
                    except json.JSONDecodeError:
                        pass
        return jsonify({"steps": steps, "project_id": project_id})
    
    # Also check for step_history in job_history entry
    for h in job_history:
        if h.get("job_id") == job_id and h.get("step_history"):
            return jsonify({"steps": h["step_history"], "project_id": h.get("project_id")})
    
    return jsonify({"steps": [], "project_id": project_id})


@app.route("/api/agent/response/<job_id>", methods=["GET"])
def api_agent_response(job_id):
    """Get the current LLM response for a running agent run."""
    response_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "aib_instance", "output", job_id, "current_response.txt")
    if os.path.exists(response_file):
        with open(response_file, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"content": content})
    return jsonify({"content": ""})


@app.route("/api/agent/output/<job_id>", methods=["GET"])
def api_agent_output(job_id):
    """Get the output file for a job."""
    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "aib_instance", "output", job_id, "output.txt")
    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"content": content})
    return jsonify({"content": ""})


@app.route("/api/agent/inject", methods=["POST"])
def api_agent_inject():
    """Inject live instructions into a running agent run, or start a continuation for completed jobs."""
    data = request.json
    job_id = data.get("job_id")
    instruction = data.get("instruction", "")

    if not job_id or not instruction:
        return jsonify({"error": "job_id and instruction required"}), 400

    # Look up the job's output directory from history or projects
    output_dir = None
    project_config = None
    project_id = None
    for h in job_history:
        if h.get("job_id") == job_id:
            pid = h.get("project_id")
            project_id = pid
            if pid:
                projects = load_projects()
                for p in projects:
                    if p["id"] == pid:
                        output_dir = p.get("output_dir")
                        # Build project config for continuation
                        project_config = {
                            "id": p["id"],
                            "name": p.get("name", ""),
                            "rootDirectory": p.get("rootDirectory", ""),
                            "instructions": p.get("instructions", ""),
                            "job_id": p.get("last_job_id", job_id),
                            "disabled_tools": p.get("disabled_tools", []),
                        }
                        break
            if not output_dir:
                # Fallback: try aib_instance/<job_id>/output/
                output_dir = os.path.join(_AIB_INSTANCE, job_id, "output")
            break

    if not output_dir:
        return jsonify({"error": "Job not found"}), 404

    # Check if the job is completed (terminal state) — if so, start a continuation run
    job_record = next((h for h in job_history if h.get("job_id") == job_id), None)
    is_completed = job_record and job_record.get("status") in ("completed", "stopped", "error", "max_steps_reached")

    if is_completed and project_config:
        # Start a new engine run in the background with the injected instruction
        # as a continuation, using the previous step history for context
        prev_step_history = job_record.get("step_history", [])

        def _continue_engine():
            try:
                os.makedirs(output_dir, exist_ok=True)

                # Build a project config that includes the continuation instruction
                cont_config = dict(project_config)
                cont_config["instructions"] = instruction
                cont_config["output_dir"] = output_dir

                # Reconstruct conversation from step history so the LLM knows
                # what was already done, then append the new instruction.
                from agent_engine import AgentEngine
                engine = AgentEngine(cont_config, output_dir=output_dir)
                engine.step_history = prev_step_history
                engine.step_count = len(prev_step_history)

                # Reconstruct conversation history from step history
                reconstructed_messages = [engine.messages[0]]  # system prompt

                # Add tool results from step_history
                all_tool_names = engine.tools.tool_names()
                for h in prev_step_history:
                    if h.get("tool") in all_tool_names:
                        res = h.get("result", {})
                        content = res.get("content", "")
                        error = res.get("error", "")
                        summary = res.get("summary", "")
                        if error:
                            result_display = f"Error: {error}"
                        elif summary:
                            result_display = summary
                            if content:
                                result_display += f"\n\nOutput:\n{content}\n"
                        elif content:
                            result_display = content
                        else:
                            result_display = "(no output)"
                        tool_name = h.get("tool", "unknown")
                        reconstructed_messages.append({
                            "role": "user",
                            "content": f"[TOOL RESULT for {tool_name}]\n{result_display}\n[END TOOL RESULT]\n\nNow continue with your next action."
                        })

                # Add the continuation message with the new instruction
                continuation_msg = (
                    f"[CONTINUATION] Your previous run completed. "
                    f"The user has new instructions for you. "
                    f"Please continue working on the project with these new instructions:\n\n"
                    f"{instruction}\n\n"
                    f"Review what was already done, then take the next appropriate action.\n\n"
                    f"TOOL FORMAT REMINDER\n"
                    f"=====================\n\n"
                    f"Your ENTIRE response must be EXACTLY ONE of the following:\n\n"
                    f"  OPTION 1 — A tool call:\n"
                    f"    [TOOL_START]\n"
                    f"    [TOOL_NAME]\n"
                    f"    <tool_name>\n"
                    f"    [PARAM_NAME]\n"
                    f"    <param_key_1>\n"
                    f"    [PARAM_VALUE]\n"
                    f"    <param_value_1>\n"
                    f"    [PARAM_NAME]\n"
                    f"    <param_key_2>\n"
                    f"    [PARAM_VALUE]\n"
                    f"    <param_value_2>\n"
                    f"    [TOOL_END]\n\n"
                    f"  OPTION 2 — Signal completion:\n"
                    f"    Use the task_completed tool with a summary:\n"
                    f"    [TOOL_START]\n"
                    f"    [TOOL_NAME]\n"
                    f"    task_completed\n"
                    f"    [PARAM_NAME]\n"
                    f"    summary\n"
                    f"    [PARAM_VALUE]\n"
                    f"    <your summary here>\n"
                    f"    [TOOL_END]\n\n"
                    f"IMPORTANT RULES:\n"
                    f"  • Do NOT write any other text.\n"
                    f"  • Do NOT explain what you will do — just act.\n"
                    f"  • Make EXACTLY ONE tool call per response.\n"
                    f"  • If you include more than one [TOOL_START]...[TOOL_END] block,\n"
                    f"    only the FIRST one will be executed."
                )
                reconstructed_messages.append({
                    "role": "user",
                    "content": continuation_msg
                })
                engine.messages = reconstructed_messages

                # Run the engine
                result = engine.run()

                # Persist conversation history
                messages_file = os.path.join(output_dir, "conversation_history.json")
                try:
                    with open(messages_file, 'w', encoding='utf-8') as f:
                        json.dump(engine.messages, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass

                # Update the job history entry with the new run's step history
                if result.get("step_history"):
                    job_record["step_history"] = result["step_history"]
                    job_record["status"] = result.get("status", "completed")
                    job_record["summary"] = result.get("summary", "")
                    job_record["steps"] = result.get("steps", 0)
                    save_job_history()

                logging.info(f"Engine continuation completed: {result.get('status', 'unknown')}")
            except Exception as e:
                logging.error(f"Engine continuation failed: {e}", exc_info=True)

        continue_thread = threading.Thread(target=_continue_engine, daemon=True)
        continue_thread.start()

        _log_app_event(f"Continuation started for completed job {job_id}")
        return jsonify({"status": "injected", "continuation": True})

    # Job is still running — inject into status.json
    os.makedirs(output_dir, exist_ok=True)
    _log_app_event(f"Live instruction injected — job_id={job_id}")
    try:
        status_file = os.path.join(output_dir, "status.json")
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
        except Exception:
            status = {}

        # Write live instruction
        status["pending_live_instruction"] = instruction
        tmp_file = status_file + ".tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, status_file)

        # If the agent was paused for user input, also write the resume answer
        # so the engine knows to continue
        resume_file = os.path.join(output_dir, "status.json")
        try:
            with open(resume_file, 'r', encoding='utf-8') as f:
                resume_status = json.load(f)
        except Exception:
            resume_status = {}
        pending = resume_status.get("pending_user_input")
        if pending and isinstance(pending, dict):
            pending["answer"] = instruction
            tmp_file = resume_file + ".tmp"
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(resume_status, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, resume_file)
        return jsonify({"status": "injected"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/agent/permission", methods=["POST"])
def api_agent_permission():
    """Deprecated: execute_python tool was removed. Use create_tool instead."""
    return jsonify({
        "error": "The execute_python tool has been removed. Use create_tool to propose new tools for approval.",
        "suggestion": "Use the create_tool tool to propose a new tool, then approve it in the TOOLS tab.",
    }), 410


@app.route("/api/agent/resume", methods=["POST"])
def api_agent_resume():
    """Resume a paused agent by providing user input (e.g. a nudge or new instructions)."""
    data = request.json
    job_id = data.get("job_id")
    user_input = data.get("input", "")

    if not job_id:
        return jsonify({"error": "job_id required"}), 400

    _log_app_event(f"Resume requested — job_id={job_id}, input_len={len(user_input)}")

    # Look up the job's output directory and project from history
    output_dir = None
    project_config = None
    project_id = None
    for h in job_history:
        if h.get("job_id") == job_id:
            pid = h.get("project_id")
            project_id = pid
            if pid:
                projects = load_projects()
                for p in projects:
                    if p["id"] == pid:
                        output_dir = p.get("output_dir")
                        project_config = {
                            "id": p["id"],
                            "name": p.get("name", ""),
                            "rootDirectory": p.get("rootDirectory", ""),
                            "instructions": p.get("instructions", ""),
                            "job_id": p.get("last_job_id", job_id),
                            "disabled_tools": p.get("disabled_tools", []),
                        }
                        break
            if not output_dir:
                output_dir = os.path.join(_AIB_INSTANCE, job_id, "output")
            break

    if not output_dir:
        output_dir = os.path.join(_AIB_INSTANCE, job_id, "output")
    status_file = os.path.join(output_dir, "status.json")
    os.makedirs(output_dir, exist_ok=True)
    try:
        # Write the resume answer into status.json
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
        except Exception:
            status = {}
        pending = status.get("pending_user_input")
        if pending and isinstance(pending, dict):
            pending["answer"] = user_input
            tmp_file = status_file + ".tmp"
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(status, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, status_file)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # If the job was in pending_user_input state, the engine thread has already
    # returned. Re-invoke the engine so it picks up the resume_input file.
    job_record = next((h for h in job_history if h.get("job_id") == job_id), None)
    if job_record and job_record.get("status") == "pending_user_input" and project_config:
        prev_step_history = job_record.get("step_history", [])

        def _resume_engine():
            try:
                from agent_engine import AgentEngine
                os.makedirs(output_dir, exist_ok=True)
                engine = AgentEngine(project_config, output_dir=output_dir)
                engine.step_history = prev_step_history
                engine.step_count = len(prev_step_history)

                # Reconstruct conversation from step history
                reconstructed_messages = [engine.messages[0]]  # system prompt
                all_tool_names = engine.tools.tool_names()
                for h in prev_step_history:
                    if h.get("tool") in all_tool_names:
                        res = h.get("result", {})
                        content = res.get("content", "")
                        error = res.get("error", "")
                        summary = res.get("summary", "")
                        if error:
                            result_display = f"Error: {error}"
                        elif summary:
                            result_display = summary
                            if content:
                                result_display += f"\n\nOutput:\n{content}\n"
                        elif content:
                            result_display = content
                        else:
                            result_display = "(no output)"
                        tool_name = h.get("tool", "unknown")
                        reconstructed_messages.append({
                            "role": "user",
                            "content": f"[TOOL RESULT for {tool_name}]\n{result_display}\n[END TOOL RESULT]\n\nNow continue with your next action."
                        })

                # Inject the user's response
                reconstructed_messages.append({
                    "role": "user",
                    "content": (
                        f"========== USER RESPONSE ==========\n"
                        f"{user_input}\n"
                        "========== END USER RESPONSE ==========\n\n"
                        "Use this response to continue your task. "
                        "Respond with EXACTLY ONE tool call."
                    )
                })
                engine.messages = reconstructed_messages

                result = engine.run()

                # Persist conversation history
                messages_file = os.path.join(output_dir, "conversation_history.json")
                try:
                    with open(messages_file, 'w', encoding='utf-8') as f:
                        json.dump(engine.messages, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass

                # Update the job history entry
                if result.get("step_history"):
                    job_record["step_history"] = result["step_history"]
                    job_record["status"] = result.get("status", "completed")
                    job_record["summary"] = result.get("summary", "")
                    job_record["steps"] = result.get("steps", 0)
                    save_job_history()

                logging.info(f"Engine resumed successfully: {result.get('status', 'unknown')}")
            except Exception as e:
                logging.error(f"Engine resume failed: {e}", exc_info=True)

        resume_thread = threading.Thread(target=_resume_engine, daemon=True)
        resume_thread.start()

    return jsonify({"status": "resume_input_saved"})


@app.route("/api/agent/resend", methods=["POST"])
def api_agent_resend():
    """Resend the last LLM request to kick the agent if it stalled."""
    data = request.json
    job_id = data.get("job_id")

    if not job_id:
        return jsonify({"error": "job_id required"}), 400

    # Find the output directory for this job
    output_dir = None
    for h in job_history:
        if h.get("job_id") == job_id:
            pid = h.get("project_id")
            if pid:
                projects = load_projects()
                for p in projects:
                    if p["id"] == pid:
                        output_dir = p.get("output_dir")
                        break
            if not output_dir:
                output_dir = os.path.join(_AIB_INSTANCE, job_id, "output")
            break

    if not output_dir or not os.path.exists(output_dir):
        return jsonify({"error": "Job output directory not found"}), 404
    
    # Find the last LLM request from the audit directory
    audit_dir = os.path.join(output_dir, "llm_audit")
    if not os.path.exists(audit_dir):
        return jsonify({"error": "No audit data found"}), 404
    
    # Get the last request file
    request_files = sorted([f for f in os.listdir(audit_dir) if f.endswith('_request.json')])
    if not request_files:
        return jsonify({"error": "No previous requests found"}), 404
    
    last_request_file = os.path.join(audit_dir, request_files[-1])
    try:
        with open(last_request_file, 'r', encoding='utf-8') as f:
            last_request = json.load(f)
        
        # Re-send the request
        import urllib.request
        import ssl
        
        endpoint_url = EngineConfig.get_custom_endpoint_url()
        api_key = EngineConfig.get_custom_api_key()
        model_name = EngineConfig.get_custom_model_name()
        timeout = EngineConfig.get_timeout()
        
        if not all([endpoint_url, model_name]):
            return jsonify({"error": "Missing endpoint configuration"}), 500
        
        payload = {
            "model": model_name,
            "messages": last_request.get("messages", []),
            "stream": True,
        }
        
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        verify_ssl = EngineConfig.get_custom_verify_ssl()
        if verify_ssl:
            context = ssl.create_default_context()
        else:
            context = ssl._create_unverified_context()
        
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            endpoint_url,
            data=data_bytes,
            headers=headers,
            method='POST',
        )
        
        # Stream the response
        response_content = ""
        with urllib.request.urlopen(req, context=context, timeout=timeout) as response:
            for line in response:
                line = line.decode('utf-8').strip()
                if not line.startswith('data: '):
                    continue
                data_str = line[6:]
                if data_str == '[DONE]':
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get('choices', [{}])[0].get('delta', {})
                    c = delta.get('content')
                    if c:
                        response_content += c
                except json.JSONDecodeError:
                    continue
        
        return jsonify({"status": "resent", "content_length": len(response_content)})
    except Exception as e:
        logging.error(f"Failed to resend request: {e}")
        return jsonify({"error": str(e)}), 500


# --- Routes: File-Based Step Polling ---

@app.route("/api/job/<job_id>/status", methods=["GET"])
def api_job_status_by_id(job_id):
    """Get the current status of a job from status.json."""
    # Resolve the output directory for this job
    output_dir = None
    # Check history first
    for h in job_history:
        if h.get("job_id") == job_id:
            pid = h.get("project_id")
            if pid:
                projects = load_projects()
                for p in projects:
                    if p["id"] == pid:
                        output_dir = p.get("output_dir")
                        break
            break

    # Fallback: try aib_instance/<job_id>/output/
    if not output_dir:
        output_dir = os.path.join(_AIB_INSTANCE, job_id, "output")

    status_file = os.path.join(output_dir, "status.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status_data = json.load(f)
            # Add job_id for convenience
            status_data["job_id"] = job_id
            return jsonify(status_data)
        except Exception as e:
            return jsonify({"error": str(e), "job_id": job_id}), 500

    # If no status.json, check job_history as fallback
    for h in job_history:
        if h.get("job_id") == job_id:
            return jsonify({
                "job_id": job_id,
                "status": h.get("status", "unknown"),
                "steps": h.get("steps", 0),
                "summary": h.get("summary", ""),
            })

    return jsonify({"error": "Job not found", "job_id": job_id}), 404


@app.route("/api/job/<job_id>/steps", methods=["GET"])
def api_job_steps(job_id):
    """Get all persisted step files for a job, ordered by step number."""
    # Resolve the output directory for this job
    output_dir = None
    # Check history first
    for h in job_history:
        if h.get("job_id") == job_id:
            pid = h.get("project_id")
            if pid:
                projects = load_projects()
                for p in projects:
                    if p["id"] == pid:
                        output_dir = p.get("output_dir")
                        break
            break

    # Fallback: try aib_instance/<job_id>/output/
    if not output_dir:
        output_dir = os.path.join(_AIB_INSTANCE, job_id, "output")

    steps_dir = os.path.join(output_dir, "steps")
    if os.path.isdir(steps_dir):
        steps = []
        for fname in sorted(os.listdir(steps_dir)):
            if fname.endswith(".json"):
                fpath = os.path.join(steps_dir, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        step_data = json.load(f)
                    steps.append(step_data)
                except Exception:
                    pass
        return jsonify({"job_id": job_id, "steps": steps, "count": len(steps)})

    # Fallback: try steps.jsonl
    step_log = os.path.join(output_dir, "steps.jsonl")
    if os.path.exists(step_log):
        steps = []
        with open(step_log, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        step_data = json.loads(line)
                        steps.append(step_data)
                    except json.JSONDecodeError:
                        pass
        return jsonify({"job_id": job_id, "steps": steps, "count": len(steps)})

    # Fallback: try step_history in job_history
    for h in job_history:
        if h.get("job_id") == job_id and h.get("step_history"):
            return jsonify({"job_id": job_id, "steps": h["step_history"], "count": len(h["step_history"])})

    return jsonify({"job_id": job_id, "steps": [], "count": 0})


@app.route("/api/job/<job_id>/steps/last", methods=["GET"])
def api_job_last_step(job_id):
    """Get the last persisted step for a job (for quick status checks)."""
    # Resolve the output directory for this job
    output_dir = None
    for h in job_history:
        if h.get("job_id") == job_id:
            pid = h.get("project_id")
            if pid:
                projects = load_projects()
                for p in projects:
                    if p["id"] == pid:
                        output_dir = p.get("output_dir")
                        break
            break

    if not output_dir:
        output_dir = os.path.join(_AIB_INSTANCE, job_id, "output")

    steps_dir = os.path.join(output_dir, "steps")
    if os.path.isdir(steps_dir):
        files = sorted(f for f in os.listdir(steps_dir) if f.endswith(".json"))
        if files:
            fpath = os.path.join(steps_dir, files[-1])
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    return jsonify({"job_id": job_id, "step": json.load(f)})
            except Exception:
                pass

    return jsonify({"job_id": job_id, "step": None})


# --- Routes: Per-Project Tool Enable/Disable ---
@app.route("/api/projects/<pid>/tools", methods=["GET"])
def api_get_project_tools(pid):
    """Get per-project disabled tools list and available tools."""
    project, projects = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    disabled_tools = project.get("disabled_tools", [])
    # Get custom (approved project-local) tools for this project
    output_dir = project.get("output_dir", "")
    custom_tools = []
    if output_dir:
        try:
            loader = get_registry()._get_or_create_loader(output_dir)
            custom_tools = sorted(loader.get_tool_names())
        except Exception:
            pass
    return jsonify({
        "disabled_tools": disabled_tools,
        "custom_tools": custom_tools,
    })

@app.route("/api/projects/<pid>/tools", methods=["POST"])
def api_set_project_tools(pid):
    """Set per-project disabled tools list."""
    with _project_lock:
        project, projects = get_project(pid)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        data = request.get_json(silent=True) or {}
        disabled_tools = data.get("disabled_tools", [])
        project["disabled_tools"] = disabled_tools
        # Clean up old enabled_tools field if present
        project.pop("enabled_tools", None)
        _save_project_unlocked(project)
        # Note: tool reload for running engines was removed with SSE migration.
        # Tool changes will apply on next engine restart.
        return jsonify({"status": "updated", "disabled_tools": disabled_tools})


# --- Routes: Pending Tools ---
@app.route("/api/tools/pending", methods=["GET", "POST"])
def api_get_pending_tools():
    """List all pending tool proposals awaiting user review (per-project)."""
    data = request.get_json(silent=True) or {}
    project_output_dir = data.get("project_output_dir", "")
    if not project_output_dir:
        project_output_dir = request.args.get("project_output_dir", "")
    if not project_output_dir:
        return jsonify({"error": "project_output_dir required"}), 400

    registry = get_registry()
    pending = registry.get_project_pending_tools(project_output_dir)
    return jsonify(pending)


@app.route("/api/tools/pending/<tool_name>/approve", methods=["POST"])
def api_approve_tool(tool_name):
    """Approve a pending tool proposal — moves it to active."""
    data = request.get_json(silent=True) or {}
    project_output_dir = data.get("project_output_dir", "")
    if not project_output_dir:
        project_output_dir = request.args.get("project_output_dir", "")
    if not project_output_dir:
        return jsonify({"error": "project_output_dir required"}), 400

    registry = get_registry()
    result = registry.approve_project_tool(project_output_dir, tool_name)
    if result["status"] == "approved":
        # Write a resume signal file so the engine loop picks it up
        # and continues to the next LLM call with the new tool available.
        resume_file = os.path.join(project_output_dir, "_tool_approved_resume.txt")
        try:
            with open(resume_file, 'w') as f:
                f.write(tool_name)
        except Exception as e:
            logging.warning(f"Failed to write resume signal for tool {tool_name}: {e}")

        # Re-invoke the engine in a background thread so it picks up the
        # resume file and continues with the newly approved tool available.
        _find_project_and_resume_engine(project_output_dir, tool_name)

        return jsonify(result)
    return jsonify(result), 404


def _find_project_and_resume_engine(project_output_dir, tool_name):
    """Find the project config for an output directory and re-invoke the engine.

    When a tool is approved, the original engine thread has already returned
    from run(). This function finds the project config and creates a new
    engine instance that will pick up the resume file and continue.

    The resumed engine receives the previous step history so it can
    reconstruct the conversation context (what was already done) and
    properly continue instead of re-doing work or completing prematurely.
    """
    projects = load_projects()
    project_config = None
    for p in projects:
        if p.get("output_dir") == project_output_dir:
            project_config = {
                "rootDirectory": p.get("rootDirectory", ""),
                "instructions": p.get("instructions", ""),
                "job_id": p.get("last_job_id", str(int(time.time() * 1000))),
                "disabled_tools": p.get("disabled_tools", []),
            }
            break

    if not project_config:
        logging.warning(f"No project found for output_dir {project_output_dir}")
        return

    # Load the previous step history from job_history so the resumed engine
    # can reconstruct the conversation and understand what was already done.
    prev_step_history = None
    for h in job_history:
        if h.get("status") in ("pending_approval", "pending_user_input", "running") and h.get("step_history"):
            # Use the most recent running/pending job's step history
            prev_step_history = h["step_history"]
            break

    # Run the engine in a background thread so that subsequent create_tool
    # calls (e.g., for a second tool) still prompt the user for approval in the UI.
    def resume_callback(event):
        """Callback that emits engine events back to the app's app_log for UI polling."""
        try:
            _log_app_event(f"Resume engine event: {event.get('type', 'unknown')} step={event.get('step', '')}")
        except Exception:
            pass

    def resume_engine():
        try:
            logging.info(f"Re-invoking engine for tool approval: {tool_name} in {project_output_dir}")
            _run_engine_in_background(
                project_config=project_config,
                output_dir=project_output_dir,
                step_callback=resume_callback,
                stop_event=None,
                prev_step_history=prev_step_history,
            )
            logging.info(f"Engine resumed successfully after tool approval: {tool_name}")
        except Exception as e:
            logging.error(f"Failed to resume engine after tool approval: {e}", exc_info=True)

    resume_thread = threading.Thread(target=resume_engine, daemon=True)
    resume_thread.start()


@app.route("/api/tools/pending/<tool_name>/reject", methods=["POST"])
def api_reject_tool(tool_name):
    """Reject a pending tool proposal — removes it."""
    data = request.get_json(silent=True) or {}
    project_output_dir = data.get("project_output_dir", "")
    if not project_output_dir:
        project_output_dir = request.args.get("project_output_dir", "")
    if not project_output_dir:
        return jsonify({"error": "project_output_dir required"}), 400

    registry = get_registry()
    result = registry.reject_project_tool(project_output_dir, tool_name)
    if result["status"] == "rejected":
        return jsonify(result)
    return jsonify(result), 404


@app.route("/api/tools/approved", methods=["GET", "POST"])
def api_get_approved_tools():
    """List all approved (registered) project-local tools (per-project)."""
    data = request.get_json(silent=True) or {}
    project_output_dir = data.get("project_output_dir", "")
    if not project_output_dir:
        # Support query param for GET requests
        project_output_dir = request.args.get("project_output_dir", "")
    if not project_output_dir:
        return jsonify({"error": "project_output_dir required"}), 400

    registry = get_registry()
    loader = registry._get_or_create_loader(project_output_dir)
    tools = loader.list_tools()
    return jsonify(tools)


@app.route("/api/tools/approved/<tool_name>", methods=["DELETE"])
def api_delete_approved_tool(tool_name):
    """Delete an approved project-local tool."""
    data = request.get_json(silent=True) or {}
    project_output_dir = data.get("project_output_dir", "")
    if not project_output_dir:
        project_output_dir = request.args.get("project_output_dir", "")
    if not project_output_dir:
        return jsonify({"error": "project_output_dir required"}), 400

    registry = get_registry()
    result = registry.delete_project_tool(project_output_dir, tool_name)
    return jsonify(result)


# --- Routes: Global Tool Enable/Disable ---
@app.route("/api/tools/enable/<tool_name>", methods=["POST"])
def api_set_tool_enabled(tool_name):
    """Enable or disable a built-in tool globally."""
    data = request.json or {}
    enabled = data.get("enabled", True)
    registry = get_registry()
    result = registry.set_tool_enabled(tool_name, enabled)
    if result["status"] == "updated":
        pass  # Tool status updated

    return jsonify(result)


@app.route("/api/tools/status", methods=["GET"])
def api_get_tool_status():
    """Return the enabled/disabled status of all known tools."""
    registry = get_registry()
    return jsonify(registry.get_tool_status())


# --- App System Log ---
_app_log = []
_app_log_lock = threading.Lock()

def _log_app_event(message):
    """Log a system-level event (not product logs)."""
    entry = {"ts": datetime.now().isoformat(), "msg": message}
    with _app_log_lock:
        _app_log.append(entry)
        # Keep last 500 entries
        while len(_app_log) > 500:
            _app_log.pop(0)


def sanitize_output_dir_name(project_name):
    """Create a file-safe directory name from a project name."""
    if not project_name:
        return "project"
    # Replace spaces and problematic chars with underscores
    name = re.sub(r'[^a-zA-Z0-9\s-]', '', project_name)
    name = re.sub(r'\s+', '_', name).strip()
    name = name.strip('_')
    if not name:
        return "project"
    # Truncate to 100 chars
    return name[:100]

def _find_available_port(start_port=5056, max_attempts=50):
    """Find next available port starting from start_port."""
    import socket
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return start_port

import webbrowser
import threading

# --- Start Worker on App Start ---
init_directories()
load_job_history()
load_settings()  # Initialize settings cache
from agent_engine.config import set_global_settings
set_global_settings(get_settings())
start_worker()
_log_app_event("App started — worker thread launched")

# Determine the port once and use it for both server and browser
_server_port = _find_available_port()

# Auto-open browser after a short delay so the server is ready
def _open_browser():
    try:
        webbrowser.open(f"http://127.0.0.1:{_server_port}/")
    except Exception:
        pass

threading.Timer(2.0, _open_browser).start()

@app.route("/api/app-log", methods=["GET"])
def api_app_log():
    """Return the system application log."""
    with _app_log_lock:
        return jsonify({"log": list(_app_log)})

if __name__ == "__main__":
    app.run(port=_server_port, debug=True, threaded=True, use_reloader=False)
