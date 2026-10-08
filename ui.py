import os
import json
import tempfile
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

# --- Resolve app directory (works for both dev and PyInstaller one-file builds) ---
def _get_app_dir():
    """Return the directory containing the app.

    For PyInstaller one-file builds ``sys._MEIPASS`` points to the
    extracted temp directory.  For normal dev it returns the directory
    containing this file.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

import sys
_app_dir = _get_app_dir()

from oneshot_engine import AIBuilder
from oneshot_engine.engine import run_with_agent_engine
from agent_engine import AgentEngine, EngineConfig, ToolResult
from config import Config
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

# Engine mode: 'agent' (multi-step tool-based) or 'legacy' (single-pass)
ENGINE_MODE = os.getenv("AIB_ENGINE_MODE", "agent").lower()

app = Flask(__name__,
            template_folder=os.path.join(_app_dir, 'templates'),
            static_folder=os.path.join(_app_dir, 'static'))

# --- Constants (all relative to the app directory) ---
_AIB_INSTANCE = os.path.join(_app_dir, "aib_instance")
STATUS_FILE = os.path.join(_AIB_INSTANCE, "run_status.json")
HISTORY_FILE = os.path.join(_AIB_INSTANCE, "job_history.json")
PROJECTS_FILE = os.path.join(_AIB_INSTANCE, "projects.json")
CHATS_DIR = os.path.join(_AIB_INSTANCE, "chats")
SETTINGS_FILE = os.path.join(_AIB_INSTANCE, "settings.json")

# --- Global State (Thread-Safe) ---
job_queue = []
running_job = None
job_history = []
job_queue_lock = threading.Lock()
stop_event = threading.Event()
worker_thread = None

# --- Settings State ---
settings_lock = threading.RLock()  # RLock allows re-entrant locking
settings_cache = {}


def _load_settings_unlocked():
    """Internal: load settings from disk without acquiring lock. Must be called inside settings_lock."""
    loaded = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
        except Exception:
            loaded = {}

    # Fill defaults from env vars for anything not in settings file
    loaded.setdefault('use_local_model', os.getenv("USE_LOCAL_MODEL", "false").lower() == "true")
    loaded.setdefault('model_path', os.getenv("MODEL_PATH", ""))
    loaded.setdefault('llama_binary', os.getenv("LLAMA_BINARY_PATH", ""))
    loaded.setdefault('use_custom_endpoint', os.getenv("USE_CUSTOM_ENDPOINT", "false").lower() == "true")
    loaded.setdefault('custom_endpoint_url', os.getenv("CUSTOM_ENDPOINT_URL", ""))
    loaded.setdefault('custom_api_key', os.getenv("CUSTOM_API_KEY", ""))
    loaded.setdefault('custom_model_name', os.getenv("CUSTOM_MODEL_NAME", ""))
    loaded.setdefault('custom_api_version', os.getenv("CUSTOM_API_VERSION", "v1"))
    loaded.setdefault('custom_verify_ssl', os.getenv("CUSTOM_VERIFY_SSL", "false").lower() == "true")
    loaded.setdefault('custom_max_tokens', int(os.getenv("CUSTOM_MAX_TOKENS", "8192")))
    loaded.setdefault('temperature', float(os.getenv("TEMPERATURE", "0.1")))
    loaded.setdefault('top_p', float(os.getenv("TOP_P", "0.9")))
    loaded.setdefault('top_k', int(os.getenv("TOP_K", "40")))
    loaded.setdefault('min_p', float(os.getenv("MIN_P", "0.0")))
    loaded.setdefault('output_tokens', int(os.getenv("OUTPUT_TOKENS", "8192")))
    loaded.setdefault('model_context', int(os.getenv("MODEL_CONTEXT", "128000")))
    loaded.setdefault('max_steps', int(os.getenv("AIB_MAX_STEPS", "50")))
    loaded.setdefault('endpoint', os.getenv("ENDPOINT", ""))
    loaded.setdefault('model_name', os.getenv("MODEL_NAME", ""))
    loaded.setdefault('api_key', os.getenv("API_KEY", ""))
    loaded.setdefault('verify_ssl', os.getenv("VERIFY_SSL", "false").lower() == "true")
    loaded.setdefault('generate_but_do_not_apply', os.getenv("GENERATE_BUT_DO_NOT_APPLY", "false").lower() == "true")
    loaded.setdefault('use_git_diff', os.getenv("USE_GIT_DIFF", "false").lower() == "true")
    loaded.setdefault('generate_output_only', os.getenv("GENERATE_OUTPUT_ONLY", "false").lower() == "true")
    loaded.setdefault('engine_mode', os.getenv("AIB_ENGINE_MODE", "agent"))
    loaded.setdefault('root_directory', os.getenv("ROOT_DIRECTORY", ""))
    loaded.setdefault('jd_cli_path', os.getenv("JD_CLI_PATH", ""))
    loaded.setdefault('java_home', os.getenv("JAVA_HOME", ""))
    loaded.setdefault('dotnet_cli_path', os.getenv("DOTNET_CLI_PATH", ""))
    loaded.setdefault('git_diff_command', os.getenv("GIT_DIFF_COMMAND", "git diff --name-only"))

    return loaded


def load_settings():
    """Load settings from disk, falling back to env vars."""
    global settings_cache
    with settings_lock:
        if settings_cache:
            return settings_cache.copy()

        loaded = _load_settings_unlocked()
        settings_cache = loaded
        return loaded.copy()


def save_settings(settings):
    """Save settings to disk and update cache."""
    with settings_lock:
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=2)
            settings_cache.clear()
            load_settings()  # Reload into cache
        except Exception as e:
            logging.error(f"Failed to save settings: {e}")


def apply_settings_to_env():
    """Apply settings to environment variables for engine config."""
    s = load_settings()
    os.environ["USE_LOCAL_MODEL"] = str(s.get('use_local_model', False)).lower()
    if s.get('model_path'):
        os.environ["MODEL_PATH"] = s['model_path']
    if s.get('llama_binary'):
        os.environ["LLAMA_BINARY_PATH"] = s['llama_binary']
    os.environ["TEMPERATURE"] = str(s.get('temperature', 0.1))
    os.environ["TOP_P"] = str(s.get('top_p', 0.9))
    os.environ["TOP_K"] = str(s.get('top_k', 40))
    os.environ["MIN_P"] = str(s.get('min_p', 0.0))
    os.environ["OUTPUT_TOKENS"] = str(s.get('output_tokens', 8192))
    os.environ["MODEL_CONTEXT"] = str(s.get('model_context', 128000))
    os.environ["AIB_MAX_STEPS"] = str(s.get('max_steps', 50))
    if s.get('endpoint'):
        os.environ["ENDPOINT"] = s['endpoint']
    if s.get('model_name'):
        os.environ["MODEL_NAME"] = s['model_name']
    if s.get('api_key'):
        os.environ["API_KEY"] = s['api_key']
    os.environ["VERIFY_SSL"] = str(s.get('verify_ssl', False)).lower()
    os.environ["GENERATE_BUT_DO_NOT_APPLY"] = str(s.get('generate_but_do_not_apply', False)).lower()
    os.environ["USE_GIT_DIFF"] = str(s.get('use_git_diff', False)).lower()
    os.environ["GENERATE_OUTPUT_ONLY"] = str(s.get('generate_output_only', False)).lower()
    os.environ["AIB_ENGINE_MODE"] = s.get('engine_mode', 'agent')
    if s.get('root_directory'):
        os.environ["ROOT_DIRECTORY"] = s['root_directory']
    if s.get('jd_cli_path'):
        os.environ["JD_CLI_PATH"] = s['jd_cli_path']
    if s.get('java_home'):
        os.environ["JAVA_HOME"] = s['java_home']
    if s.get('dotnet_cli_path'):
        os.environ["DOTNET_CLI_PATH"] = s['dotnet_cli_path']
    if s.get('git_diff_command'):
        os.environ["GIT_DIFF_COMMAND"] = s['git_diff_command']
    # Custom endpoint settings
    os.environ["USE_CUSTOM_ENDPOINT"] = str(s.get('use_custom_endpoint', False)).lower()
    if s.get('custom_endpoint_url'):
        os.environ["CUSTOM_ENDPOINT_URL"] = s['custom_endpoint_url']
    if s.get('custom_api_key'):
        os.environ["CUSTOM_API_KEY"] = s['custom_api_key']
    if s.get('custom_model_name'):
        os.environ["CUSTOM_MODEL_NAME"] = s['custom_model_name']
    os.environ["CUSTOM_API_VERSION"] = s.get('custom_api_version', 'v1')
    os.environ["CUSTOM_VERIFY_SSL"] = str(s.get('custom_verify_ssl', False)).lower()
    os.environ["CUSTOM_MAX_TOKENS"] = str(s.get('custom_max_tokens', 8192))


# --- Initialization ---
def init_directories():
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(PROJECTS_FILE), exist_ok=True)
    os.makedirs(CHATS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)

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
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(job_history, f, indent=2)
    except Exception:
        pass

def load_projects():
    if not os.path.exists(PROJECTS_FILE):
        with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_projects(projects):
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2)

# --- Worker Thread ---
def worker():
    global running_job
    while not stop_event.is_set():
        with job_queue_lock:
            if running_job is None and job_queue:
                running_job = job_queue.pop(0)
            else:
                time.sleep(0.5)
                continue

        job_id = running_job["job_id"]
        pid = running_job["project_id"]
        project, _ = get_project(pid)

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
                if ENGINE_MODE == "agent" or project.get("mode") == "agentic":
                    # Use the new multi-step agentic engine
                    result = run_with_agent_engine(project)
                    job_history[-1]["status"] = result.get("status", "completed")
                    job_history[-1]["summary"] = result.get("summary", "")
                    job_history[-1]["steps"] = result.get("steps", 0)
                    if result.get("status") == "error":
                        job_history[-1]["error"] = result.get("error", "Unknown error")
                else:
                    # Legacy single-pass mode
                    ai = AIBuilder(job_id, project)
                    ai.run()
                    job_history[-1]["status"] = "completed"
            else:
                job_history[-1]["status"] = "error"
                job_history[-1]["error"] = "Project not found"
        except Exception as e:
            job_history[-1]["status"] = "error"
            job_history[-1]["error"] = str(e)
        finally:
            # Check for incomplete actions file
            actions_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "output", job_id, "actions.txt")
            if os.path.exists(actions_file):
                job_history[-1]["incomplete"] = True
            save_job_history()
            with job_queue_lock:
                running_job = None

def start_worker():
    global worker_thread
    if worker_thread and worker_thread.is_alive():
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
    if not isinstance(project.get("includePatterns"), str):
        project["includePatterns"] = ""
    return jsonify(project)

@app.route("/api/projects", methods=["POST"])
def api_create_project():
    projects = load_projects()
    pid = str(uuid.uuid4())

    name = request.form.get("name", "")
    if not name:
        return jsonify({"error": "Project name is required"}), 400

    mode = request.form.get("mode", "oneshot")
    root_directory = request.form.get("rootDirectory", "")
    if not root_directory:
        return jsonify({"error": "Root directory is required"}), 400

    # For oneshot mode, require include patterns
    if mode == "oneshot":
        include_patterns = request.form.get("includePatterns", "")
        if not include_patterns:
            return jsonify({"error": "At least one include pattern is required for One-Shot mode"}), 400
        patterns = [p.strip() for p in include_patterns.split(",") if p.strip()]
        has_absolute = any(os.path.isabs(p) for p in patterns)
        has_relative = any(not os.path.isabs(p) for p in patterns)
        if has_relative and not root_directory and not has_absolute:
            return jsonify({"error": "rootDirectory is required if includePatterns contain relative paths and no absolute paths"}), 400
    else:
        # Agentic mode: root directory is sufficient
        include_patterns = ""
        patterns = []

    project = {
        "id": pid,
        "name": name,
        "mode": mode,
        "rootDirectory": root_directory,
        "includePatterns": include_patterns,
        "excludePatterns": request.form.get("excludePatterns", ""),
        "iterations": 1,
        "instructions": request.form.get("instructions", ""),
        "preScript": request.form.get("preScript", ""),
        "postScript": request.form.get("postScript", ""),
        "isArchived": False,
        "enabled_tools": []  # Will be set when running in agentic mode
    }

    projects.append(project)
    save_projects(projects)
    return jsonify(project)

@app.route("/api/projects/<pid>", methods=["POST"])
def api_update_project(pid):
    project, projects = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    mode = request.form.get("mode", project.get("mode", "oneshot"))
    root_directory = request.form.get("rootDirectory", project.get("rootDirectory", ""))
    if not root_directory:
        return jsonify({"error": "Root directory is required"}), 400

    # For oneshot mode, require include patterns
    if mode == "oneshot":
        include_patterns = request.form.get("includePatterns", project.get("includePatterns", ""))
        if not include_patterns:
            return jsonify({"error": "At least one include pattern is required for One-Shot mode"}), 400
        patterns = [p.strip() for p in include_patterns.split(",") if p.strip()]
        has_absolute = any(os.path.isabs(p) for p in patterns)
        has_relative = any(not os.path.isabs(p) for p in patterns)
        if has_relative and not root_directory and not has_absolute:
            return jsonify({"error": "rootDirectory is required if includePatterns contain relative paths and no absolute paths"}), 400
    else:
        include_patterns = project.get("includePatterns", "")

    project.update({
        "name": request.form.get("name", project["name"]),
        "mode": mode,
        "rootDirectory": root_directory,
        "includePatterns": include_patterns,
        "excludePatterns": request.form.get("excludePatterns", project.get("excludePatterns", "")),
        "iterations": 1,
        "instructions": request.form.get("instructions", project.get("instructions", "")),
        "preScript": request.form.get("preScript", project.get("preScript", "")),
        "postScript": request.form.get("postScript", project.get("postScript", "")),
    })

    save_projects(projects)
    return jsonify({"status": "saved", "project": project})

@app.route("/api/projects/<pid>/archive", methods=["POST"])
def api_archive_project(pid):
    projects = load_projects()
    for project in projects:
        if project["id"] == pid:
            project["isArchived"] = True
            break
    save_projects(projects)
    return jsonify({"status": "archived"})

@app.route("/api/projects/<pid>/unarchive", methods=["POST"])
def api_unarchive_project(pid):
    projects = load_projects()
    for project in projects:
        if project["id"] == pid:
            project["isArchived"] = False
            break
    save_projects(projects)
    return jsonify({"status": "unarchived"})

# --- Routes: Queue ---
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
    project, _ = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Agentic mode doesn't need include patterns
    if project.get("mode") != "agentic":
        if not project.get("includePatterns"):
            return jsonify({"error": "No includePatterns specified"}), 400

        include_patterns = [p.strip() for p in project["includePatterns"].split(",") if p.strip()]
        has_absolute = any(os.path.isabs(p) for p in include_patterns)
        has_relative = any(not os.path.isabs(p) for p in include_patterns)

        if has_relative and not project.get("rootDirectory") and not has_absolute:
            return jsonify({"error": "rootDirectory required if includePatterns contain relative paths and no absolute paths"}), 400

        root_dir = project.get("rootDirectory", "")
        if root_dir and os.path.isdir(root_dir):
            all_files_pattern = any(p.strip() in (".", "./", "") for p in include_patterns)
            if all_files_pattern and not project.get("excludePatterns"):
                return jsonify({
                    "error": "Pattern includes entire directory without exclusion filters. This is not allowed for safety reasons.",
                    "suggestion": "Add specific file patterns or exclusion patterns to limit the scope."
                }), 400

    job_id = str(int(time.time() * 1000))
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "output", job_id)
    try:
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        return jsonify({"error": f"Failed to create output directory: {str(e)}"}), 500

    with job_queue_lock:
        job_queue.append({"job_id": job_id, "project_id": pid})
    start_worker()
    return jsonify({"status": "queued", "job_id": job_id})

@app.route("/api/queue/<job_id>", methods=["DELETE"])
def api_delete_from_queue(job_id):
    with job_queue_lock:
        job_queue[:] = [j for j in job_queue if j["job_id"] != job_id]
        if running_job and running_job["job_id"] == job_id:
            running_job = None
    start_worker()
    return jsonify({"status": "deleted"})

@app.route("/api/queue/running/stop", methods=["POST"])
def api_stop_running():
    with job_queue_lock:
        running_job = None
    start_worker()
    return jsonify({"status": "stopped"})

@app.route("/api/projects/<pid>", methods=["DELETE"])
def api_delete_project(pid):
    with job_queue_lock:
        job_queue[:] = [j for j in job_queue if j["project_id"] != pid]
        if running_job and running_job["project_id"] == pid:
            running_job = None
    start_worker()

    projects = load_projects()
    projects = [p for p in projects if p["id"] != pid]
    save_projects(projects)
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

    return jsonify(current_job_history)

@app.route("/api/history/clear", methods=["POST"])
def api_clear_history():
    global job_history
    with job_queue_lock:
        job_history.clear()
        save_job_history()
    return jsonify({"status": "cleared"})

# --- Routes: Files ---
@app.route("/api/files", methods=["GET"])
def api_files():
    path = request.args.get("path", ".")
    search = request.args.get("search", "").lower()
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if not os.path.isabs(path):
            path = os.path.abspath(os.path.join(base_dir, path))
        path = os.path.normpath(path)

        # Security: Block access to sensitive directories
        blocked_prefixes = [
            '/etc', '/usr', '/var', '/bin', '/sbin', '/lib', '/dev',
            'C:\\\\Windows', 'C:\\\\Program Files', 'C:\\\\ProgramData'
        ]
        if any(path.startswith(prefix) for prefix in blocked_prefixes):
            return jsonify({"error": "Access to system directories is not allowed"}), 403

        if not os.path.exists(path):
            return jsonify({"error": f"Path does not exist: {path}"}), 400

        all_paths = []
        for root, dirs, files in os.walk(path):
            rel_root = os.path.relpath(root, path)
            if rel_root == ".":
                rel_root = ""
            for f in files:
                rel_path = os.path.join(rel_root, f) if rel_root else f
                if search:
                    criteria = [c.strip() for c in search.split(',') if c.strip()]
                    pos_pats = [c for c in criteria if not c.startswith('!')]
                    neg_pats = [c[1:].strip() for c in criteria if c.startswith('!')]

                    has_positive_match = any(re.search(re.escape(p).replace(r'\*', '.*'), rel_path, re.IGNORECASE) for p in pos_pats)
                    has_negative_match = any(re.search(re.escape(p).replace(r'\*', '.*'), rel_path, re.IGNORECASE) for p in neg_pats)

                    if pos_pats and not has_positive_match:
                        continue
                    if has_negative_match:
                        continue
                try:
                    file_size = os.path.getsize(os.path.join(root, f))
                    all_paths.append({"path": rel_path, "size": file_size})
                except (OSError, PermissionError):
                    continue

        all_paths.sort(key=lambda x: x["path"])
        total = len(all_paths)
        paginated = all_paths[offset:offset + limit]
        return jsonify({"files": paginated, "total": total, "offset": offset, "limit": limit})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

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
    message = data.get("content", "")
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
                if Config.use_local_model():
                    model_path = Config.get_model_path()
                    if not model_path:
                        raise ValueError("MODEL_PATH environment variable not set for local model.")
                    llama_binary = Config.get_llama_binary_path()
                    if not os.path.isfile(llama_binary):
                        raise FileNotFoundError(f"llama binary not found at: {llama_binary}")
                    ticks = int(time.time() * 1000)
                    filename = os.path.join(CHATS_DIR, f"chat_prompt_{ticks}.txt")
                    with open(filename, "w", encoding='utf-8') as f:
                        f.write(prompt)
                    cmd = [
                        llama_binary, "-m", model_path, "-f", filename,
                        "--temp", str(Config.get_temperature()),
                        "--top-p", str(Config.get_top_p()),
                        "--top-k", str(Config.get_top_k()),
                        "--min-p", str(Config.get_min_p()),
                        "-n", str(Config.get_output_tokens()),
                        "--ctx-size", str(Config.get_model_context()),
                        "--jinja", "--no-display-prompt", "-st"
                    ]
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        universal_newlines=True
                    )
                    for line in process.stdout:
                        response_content += line
                        yield line
                        if len(response_content) % 20 == 0:
                            chat_data["messages"] = [m for m in chat_data["messages"] if m["role"] != "assistant"]
                            chat_data["messages"].append({"role": "assistant", "content": response_content})
                            with open(chat_path, "w", encoding="utf-8") as f:
                                json.dump(chat_data, f, indent=2)
                    process.wait()
                    if os.path.exists(filename):
                        os.remove(filename)
                elif Config.use_custom_endpoint():
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
                        "temperature": Config.get_temperature(),
                        "top_p": Config.get_top_p(),
                        "max_tokens": Config.get_output_tokens(),
                        "stream": True,
                    }
                    headers = {"Content-Type": "application/json"}
                    if api_key:
                        headers["Authorization"] = f"Bearer {api_key}"
                    verify_ssl = Config.verify_ssl()
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
                                c = delta.get('content', '')
                                if c:
                                    response_content += c
                                    yield c
                                    if len(response_content) % 20 == 0:
                                        chat_data["messages"] = [m for m in chat_data["messages"] if m["role"] != "assistant"]
                                        chat_data["messages"].append({"role": "assistant", "content": response_content})
                                        with open(chat_path, "w", encoding="utf-8") as f:
                                            json.dump(chat_data, f, indent=2)
                            except json.JSONDecodeError:
                                continue
                else:
                    endpoint = Config.get_endpoint()
                    model_name = Config.get_model_name()
                    api_key = Config.get_api_key()
                    verify_ssl = Config.verify_ssl()
                    if not all([endpoint, model_name, api_key]):
                        raise ValueError("Missing one or more required environment variables: ENDPOINT, MODEL_NAME, API_KEY")
                    client = ChatCompletionsClient(
                        endpoint=endpoint,
                        credential=AzureKeyCredential(api_key),
                        api_version="2024-05-01-preview",
                        connection_verify=verify_ssl
                    )
                    response = client.complete(
                        stream=True,
                        messages=[SystemMessage(content="You are a helpful coding assistant."), UserMessage(content=prompt)],
                        max_tokens=Config.get_output_tokens(),
                        model=model_name
                    )
                    for update in response:
                        if update.choices and isinstance(update.choices, list) and len(update.choices) > 0:
                            content = update.choices[0].get("delta", {}).get("content", "")
                            if content is not None:
                                response_content += content
                                yield content
                                if len(response_content) % 20 == 0:
                                    chat_data["messages"] = [m for m in chat_data["messages"] if m["role"] != "assistant"]
                                    chat_data["messages"].append({"role": "assistant", "content": response_content})
                                    with open(chat_path, "w", encoding="utf-8") as f:
                                        json.dump(chat_data, f, indent=2)
                    response.close()

                chat_data["messages"] = [m for m in chat_data["messages"] if m["role"] != "assistant"]
                chat_data["messages"].append({"role": "assistant", "content": response_content})
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
    apply_settings_to_env()
    return jsonify({"status": "saved"})

# --- Agent Routes ---
@app.route("/api/agent/run", methods=["POST"])
def api_agent_run():
    """Start the agentic engine and stream step results via SSE."""
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    instructions = data.get("instructions", "")
    root_dir = data.get("rootDirectory", "")
    enabled_tools = data.get("enabled_tools", [])

    if not project_id and not instructions:
        return jsonify({"error": "project_id or instructions required"}), 400

    # Get project if project_id provided
    project = None
    if project_id:
        project, _ = get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        instructions = project.get("instructions", "")
        root_dir = project.get("rootDirectory", "")

    if not root_dir:
        return jsonify({"error": "rootDirectory required"}), 400

    job_id = str(int(time.time() * 1000))
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "aib_instance", "output", job_id)
    try:
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        return jsonify({"error": f"Failed to create output directory: {str(e)}"}), 500

    # Add to history
    job_history.append({
        "job_id": job_id,
        "project_id": project_id,
        "project_name": project.get("name", "Ad-hoc") if project else "Ad-hoc",
        "status": "running",
        "instructions": instructions,
        "timestamp": datetime.now().isoformat()
    })
    save_job_history()

    # Set environment variables for the engine
    os.environ["AIB_ROOT"] = root_dir
    os.environ["AIB_INSTRUCTIONS"] = instructions
    os.environ["AIB_PRE_SCRIPT"] = project.get("preScript", "") if project else ""
    os.environ["AIB_POST_SCRIPT"] = project.get("postScript", "") if project else ""

    def generate():
        yield "event: status\ndata: " + json.dumps({"type": "start", "job_id": job_id}) + "\n\n"

        try:
            config = {
                "rootDirectory": root_dir,
                "instructions": instructions,
                "job_id": job_id,
                "preScript": project.get("preScript", "") if project else "",
                "postScript": project.get("postScript", "") if project else "",
                "enabled_tools": enabled_tools if enabled_tools else None,
            }

            engine = AgentEngine(config, output_dir=output_dir)
            result = engine.run()

            # Stream step history
            for step in engine.step_history:
                yield "event: step\ndata: " + json.dumps({
                    "type": "step",
                    "step": step["step"],
                    "tool": step["tool"],
                    "params": step.get("params", {}),
                    "result": step.get("result", {}),
                }) + "\n\n"
                time.sleep(0.01)

            # Final result
            yield "event: status\ndata: " + json.dumps({
                "type": "complete",
                "status": result.get("status", "completed"),
                "summary": result.get("summary", ""),
                "steps": result.get("steps", 0),
                "max_steps": result.get("max_steps", 50),
            }) + "\n\n"

            # Update history with step results
            job_history[-1]["status"] = result.get("status", "completed")
            job_history[-1]["summary"] = result.get("summary", "")
            job_history[-1]["steps"] = result.get("steps", 0)
            job_history[-1]["step_count"] = result.get("steps", 0)
            # Save step results to history for display
            job_history[-1]["steps"] = engine.step_history  # Override step count with step list
            if result.get("status") == "error":
                job_history[-1]["error"] = result.get("error", "Unknown error")
            save_job_history()

        except Exception as e:
            yield "event: status\ndata: " + json.dumps({
                "type": "error",
                "error": str(e),
            }) + "\n\n"
            job_history[-1]["status"] = "error"
            job_history[-1]["error"] = str(e)
            save_job_history()

    return Response(generate(), mimetype='text/event-stream')


@app.route("/api/agent/history/<job_id>", methods=["GET"])
def api_agent_history(job_id):
    """Get the step history for a completed agent run."""
    step_log = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "aib_instance", "output", job_id, "steps.jsonl")
    if os.path.exists(step_log):
        steps = []
        with open(step_log, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        steps.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return jsonify({"steps": steps})
    return jsonify({"steps": []})


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
    """Inject live instructions into a running agent run."""
    data = request.json
    job_id = data.get("job_id")
    instruction = data.get("instruction", "")

    if not job_id or not instruction:
        return jsonify({"error": "job_id and instruction required"}), 400

    # Write instruction to a temp file that the agent engine can pick up
    # For now, we'll store it in the job's output directory
    instruction_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "aib_instance", "output", job_id, "live_instruction.txt")
    try:
        with open(instruction_file, 'w') as f:
            f.write(instruction)
        return jsonify({"status": "injected"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Start Worker on App Start ---
init_directories()
load_job_history()
apply_settings_to_env()
start_worker()


if __name__ == "__main__":
    app.run(port=5056, debug=True, threaded=True)
