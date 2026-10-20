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
from agent_engine import run as agent_run

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

from agent_engine import AgentEngine, EngineConfig, ToolResult
from agent_engine.tools import ToolRegistry
from config import Config

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
    loaded.setdefault('custom_endpoint_url', os.getenv("CUSTOM_ENDPOINT_URL", ""))
    loaded.setdefault('custom_api_key', os.getenv("CUSTOM_API_KEY", ""))
    loaded.setdefault('custom_model_name', os.getenv("CUSTOM_MODEL_NAME", ""))
    loaded.setdefault('custom_verify_ssl', os.getenv("CUSTOM_VERIFY_SSL", "false").lower() == "true")
    loaded.setdefault('max_steps', int(os.getenv("AIB_MAX_STEPS", "50")))
    loaded.setdefault('timeout', int(os.getenv("CUSTOM_TIMEOUT", "3600")))
    loaded.setdefault('max_context_tokens', int(os.getenv("AIB_MAX_CONTEXT_TOKENS", "0")))
    loaded.setdefault('max_output_tokens', int(os.getenv("AIB_MAX_OUTPUT_TOKENS", "0")))
    loaded.setdefault('max_tool_result_length', int(os.getenv("AIB_MAX_TOOL_RESULT_LENGTH", "2000")))
    loaded.setdefault('root_directory', os.getenv("ROOT_DIRECTORY", ""))
    loaded.setdefault('jd_cli_path', os.getenv("JD_CLI_PATH", ""))
    loaded.setdefault('java_home', os.getenv("JAVA_HOME", ""))
    loaded.setdefault('dotnet_cli_path', os.getenv("DOTNET_CLI_PATH", ""))

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
    os.environ["AIB_MAX_STEPS"] = str(s.get('max_steps', 50))
    os.environ["CUSTOM_TIMEOUT"] = str(s.get('timeout', 3600))
    os.environ["AIB_MAX_CONTEXT_TOKENS"] = str(s.get('max_context_tokens', 0))
    os.environ["AIB_MAX_OUTPUT_TOKENS"] = str(s.get('max_output_tokens', 0))
    os.environ["AIB_MAX_TOOL_RESULT_LENGTH"] = str(s.get('max_tool_result_length', 2000))
    if s.get('root_directory'):
        os.environ["ROOT_DIRECTORY"] = s['root_directory']
    if s.get('jd_cli_path'):
        os.environ["JD_CLI_PATH"] = s['jd_cli_path']
    if s.get('java_home'):
        os.environ["JAVA_HOME"] = s['java_home']
    if s.get('dotnet_cli_path'):
        os.environ["DOTNET_CLI_PATH"] = s['dotnet_cli_path']
    # OpenAI-compatible endpoint settings (always used now)
    if s.get('custom_endpoint_url'):
        os.environ["CUSTOM_ENDPOINT_URL"] = s['custom_endpoint_url']
    if s.get('custom_api_key'):
        os.environ["CUSTOM_API_KEY"] = s['custom_api_key']
    if s.get('custom_model_name'):
        os.environ["CUSTOM_MODEL_NAME"] = s['custom_model_name']
    os.environ["CUSTOM_VERIFY_SSL"] = str(s.get('custom_verify_ssl', False)).lower()


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
                result = run_with_agent_engine(project)
                job_history[-1]["status"] = result.get("status", "completed")
                job_history[-1]["summary"] = result.get("summary", "")
                job_history[-1]["steps"] = result.get("steps", 0)
                if result.get("status") == "error":
                    job_history[-1]["error"] = result.get("error", "Unknown error")
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


def run_with_agent_engine(project_config: Dict[str, Any]) -> Dict[str, Any]:
    """Run the multi-step agentic engine (delegates to agent_engine)."""
    
    if "job_id" not in project_config:
        project_config["job_id"] = str(int(time.time() * 1000))

    root_dir = project_config.get("rootDirectory", "")
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "output", project_config["job_id"])
    
    os.environ["AIB_ROOT"] = root_dir
    os.environ["AIB_INSTRUCTIONS"] = project_config.get("instructions", "")
    os.environ["AIB_PRE_SCRIPT"] = project_config.get("preScript", "")
    os.environ["AIB_POST_SCRIPT"] = project_config.get("postScript", "")

    enabled_tools = project_config.get("enabled_tools")
    if enabled_tools:
        os.environ["AIB_ENABLED_TOOLS"] = json.dumps(enabled_tools)

    return agent_run(project_config, output_dir=output_dir)


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


def get_concurrent_job_info(pid):
    """Return (is_running, is_queued, existing_job_id) for a project."""
    with job_queue_lock:
        if running_job and running_job["project_id"] == pid:
            return True, False, running_job["job_id"]
        for job in job_queue:
            if job["project_id"] == pid:
                return False, True, job["job_id"]
        return False, False, None

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
    projects = load_projects()
    pid = str(uuid.uuid4())

    name = request.form.get("name", "")
    if not name:
        return jsonify({"error": "Project name is required"}), 400

    root_directory = request.form.get("rootDirectory", "")
    if not root_directory:
        return jsonify({"error": "Root directory is required"}), 400

    project = {
        "id": pid,
        "name": name,
        "rootDirectory": root_directory,
        "instructions": request.form.get("instructions", ""),
        "preScript": request.form.get("preScript", ""),
        "postScript": request.form.get("postScript", ""),
        "isArchived": False,
        "enabled_tools": []
    }

    projects.append(project)
    save_projects(projects)
    return jsonify(project)

@app.route("/api/projects/<pid>", methods=["POST"])
def api_update_project(pid):
    project, projects = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    root_directory = request.form.get("rootDirectory", project.get("rootDirectory", ""))
    if not root_directory:
        return jsonify({"error": "Root directory is required"}), 400

    project.update({
        "name": request.form.get("name", project["name"]),
        "rootDirectory": root_directory,
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

    # Guard: reject if project is already running or queued
    is_running, is_queued, existing_job_id = get_concurrent_job_info(pid)
    if is_running:
        return jsonify({"error": "Project is already running", "job_id": existing_job_id}), 409
    if is_queued:
        return jsonify({"error": "Project is already queued", "job_id": existing_job_id}), 409

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
        running_job = None
    start_worker()
    return jsonify({"status": "stopped"})

@app.route("/api/projects/<pid>", methods=["DELETE"])
def api_delete_project(pid):
    global running_job
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
    continue_from_job = data.get("continue_from_job")  # job_id to continue from

    if not project_id and not instructions:
        return jsonify({"error": "project_id or instructions required"}), 400

    # Get project if project_id provided
    project = None
    if project_id:
        project, _ = get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        # Use project's root dir, but prefer user-provided instructions for continuation
        root_dir = project.get("rootDirectory", "")
        if not instructions:
            instructions = project.get("instructions", "")

    if not root_dir:
        return jsonify({"error": "rootDirectory required"}), 400

    # Guard: reject if project is already running or queued
    if project_id:
        is_running, is_queued, existing_job_id = get_concurrent_job_info(project_id)
        if is_running:
            return jsonify({"error": "Project is already running", "job_id": existing_job_id}), 409
        if is_queued:
            return jsonify({"error": "Project is already queued", "job_id": existing_job_id}), 409

    # --- Handle continuation from a previous completed job ---
    prev_step_history = None
    if continue_from_job:
        # Load previous step history from job history
        for h in job_history:
            if h.get("job_id") == continue_from_job and h.get("step_history"):
                prev_step_history = h["step_history"]
                break

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
    os.environ["AIB_JOB_ID"] = job_id
    os.environ["CUSTOM_ENDPOINT_URL"] = os.getenv("CUSTOM_ENDPOINT_URL", "")
    os.environ["CUSTOM_API_KEY"] = os.getenv("CUSTOM_API_KEY", "")
    os.environ["CUSTOM_MODEL_NAME"] = os.getenv("CUSTOM_MODEL_NAME", "")
    os.environ["CUSTOM_VERIFY_SSL"] = os.getenv("CUSTOM_VERIFY_SSL", "false")
    os.environ["CUSTOM_TIMEOUT"] = os.getenv("CUSTOM_TIMEOUT", "3600")

    def generate():
        # Queue for events from background thread
        event_queue: queue.Queue = queue.Queue()
        engine_result: list = [None]
        engine_error: list = [None]
        engine_step_history: list = [None]

        def on_event(event):
            event_queue.put(event)

        def run_engine():
            """Run the engine in a background thread."""
            try:
                config = {
                    "rootDirectory": root_dir,
                    "instructions": instructions,
                    "job_id": job_id,
                    "enabled_tools": enabled_tools if enabled_tools else None,
                }
                engine = AgentEngine(config, output_dir=output_dir, step_callback=on_event)

                # If continuing, load previous step history into the engine
                if prev_step_history:
                    engine.step_history = prev_step_history
                    engine.step_count = len(prev_step_history)
                    # Inject a user message so the agent knows to continue
                    engine.messages.append({
                        "role": "user",
                        "content": (
                            f"[CONTINUATION] Your previous run completed. "
                            f"The user has new instructions for you. "
                            f"Please continue working on the project with these new instructions:\n\n"
                            f"{instructions}\n\n"
                            f"Explore the project again and take action."
                        )
                    })

                result = engine.run()
                engine_result[0] = result
                engine_step_history[0] = engine.step_history
                # Push a sentinel to signal completion
                event_queue.put({"type": "__done__"})
            except Exception as e:
                engine_error[0] = e
                event_queue.put({"type": "__error__", "error": str(e)})

        # Start engine in background thread
        bg_thread = threading.Thread(target=run_engine, daemon=True)
        bg_thread.start()

        yield "event: status\ndata: " + json.dumps({"type": "start", "job_id": job_id}) + "\n\n"

        # Process events as they arrive
        for ev in iter(event_queue.get, None):
            if ev.get("type") == "__done__":
                result = engine_result[0] or {}
                # Yield any remaining events from the queue
                while not event_queue.empty():
                    try:
                        ev = event_queue.get_nowait()
                        if ev["type"] == "step":
                            yield "event: step\ndata: " + json.dumps({
                                "type": "step",
                                "step": ev["step"],
                                "tool": ev["tool"],
                                "params": ev.get("params", {}),
                                "result": ev.get("result", {}),
                            }) + "\n"
                        elif ev["type"] == "llm_call":
                            yield "event: step\ndata: " + json.dumps({
                                "type": "llm_call",
                                "step": ev["step"],
                                "tool": "llm_call",
                                "params": ev.get("params", {}),
                                "result": {"content": "", "success": True},
                            }) + "\n"
                    except queue.Empty:
                        break
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
                job_history[-1]["step_history"] = engine_step_history[0] or []
                if result.get("status") == "error":
                    job_history[-1]["error"] = result.get("error", "Unknown error")
                save_job_history()
                break

            elif ev.get("type") == "__error__":
                yield "event: status\ndata: " + json.dumps({
                    "type": "error",
                    "error": ev.get("error", str(engine_error[0] or "Unknown error")),
                }) + "\n\n"
                job_history[-1]["status"] = "error"
                job_history[-1]["error"] = ev.get("error", str(engine_error[0] or "Unknown error"))
                save_job_history()
                break

            elif ev["type"] == "step":
                yield "event: step\ndata: " + json.dumps({
                    "type": "step",
                    "step": ev["step"],
                    "tool": ev["tool"],
                    "params": ev.get("params", {}),
                    "result": ev.get("result", {}),
                }) + "\n"
            elif ev["type"] == "llm_call":
                yield "event: step\ndata: " + json.dumps({
                    "type": "llm_call",
                    "step": ev["step"],
                    "tool": "llm_call",
                    "params": ev.get("params", {}),
                    "result": {"content": "", "success": True},
                }) + "\n"

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
    os.makedirs(os.path.dirname(instruction_file), exist_ok=True)
    try:
        with open(instruction_file, 'w') as f:
            f.write(instruction)
        return jsonify({"status": "injected"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/agent/permission", methods=["POST"])
def api_agent_permission():
    """Handle permission requests (e.g., execute_python)."""
    data = request.json
    job_id = data.get("job_id")
    decision = data.get("decision", "")  # "approved" or "rejected"

    if not job_id or not decision:
        return jsonify({"error": "job_id and decision required"}), 400

    perm_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "aib_instance", "output", job_id, "execute_python_permission.txt")
    os.makedirs(os.path.dirname(perm_file), exist_ok=True)
    try:
        with open(perm_file, 'w') as f:
            f.write(decision)
        return jsonify({"status": "decision_recorded"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Routes: Pending Tools ---
@app.route("/api/tools/pending", methods=["GET"])
def api_get_pending_tools():
    """List all pending tool proposals awaiting user review."""
    # We need a registry instance to query pending tools
    root_dir = os.getenv("AIB_ROOT", os.getenv("ROOT_DIRECTORY", os.getcwd()))
    registry = ToolRegistry(root_dir)
    pending = registry.get_pending_tools()
    return jsonify(pending)


@app.route("/api/tools/pending/<tool_id>/approve", methods=["POST"])
def api_approve_tool(tool_id):
    """Approve a pending tool proposal — registers it immediately."""
    root_dir = os.getenv("AIB_ROOT", os.getenv("ROOT_DIRECTORY", os.getcwd()))
    registry = ToolRegistry(root_dir)
    result = registry.approve_tool(tool_id)
    if result["status"] == "approved":
        return jsonify(result)
    return jsonify(result), 404


@app.route("/api/tools/pending/<tool_id>/reject", methods=["POST"])
def api_reject_tool(tool_id):
    """Reject a pending tool proposal — removes it from pending."""
    root_dir = os.getenv("AIB_ROOT", os.getenv("ROOT_DIRECTORY", os.getcwd()))
    registry = ToolRegistry(root_dir)
    result = registry.reject_tool(tool_id)
    if result["status"] == "rejected":
        return jsonify(result)
    return jsonify(result), 404


@app.route("/api/tools/approved", methods=["GET"])
def api_get_approved_tools():
    """List all approved (registered) dynamic tools."""
    from agent_engine.config import EngineConfig
    pending_file = EngineConfig.get_pending_tools_file()
    approved_tools = []
    if os.path.exists(pending_file):
        try:
            with open(pending_file, 'r') as f:
                pending_tools = json.load(f)
            for entry in pending_tools:
                if entry.get("status") == "approved":
                    approved_tools.append({
                        "name": entry["name"],
                        "description": entry.get("description", ""),
                        "parameters": entry.get("parameters", {}),
                        "approved_at": entry.get("approved_at", ""),
                    })
        except Exception:
            pass
    return jsonify(approved_tools)


# --- Start Worker on App Start ---
init_directories()
load_job_history()
apply_settings_to_env()
start_worker()


if __name__ == "__main__":
    app.run(port=5056, debug=True, threaded=True)
