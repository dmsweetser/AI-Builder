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
from datetime import datetime
from flask import Flask, Response, request, jsonify, render_template, send_from_directory

from ai_builder import AIBuilder
from config import Config
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

app = Flask(__name__)

STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "run_status.json")
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "job_history.json")

# Clear job history on app start
if os.path.exists(HISTORY_FILE):
    try:
        os.remove(HISTORY_FILE)
    except Exception:
        pass

job_queue = []
running_job = None
job_history = []
job_queue_lock = threading.Lock()
worker_thread = None
stop_event = threading.Event()

def load_job_history():
    global job_history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                job_history = json.load(f)
        except Exception:
            job_history = []
    else:
        job_history = []

def save_job_history():
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, 'w') as f:
            json.dump(job_history, f, indent=2)
    except Exception:
        pass

load_job_history()

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
            save_job_history()
            with job_queue_lock:
                running_job = None

def start_worker():
    global worker_thread
    if worker_thread and worker_thread.is_alive():
        return
    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()

def stop_worker():
    global worker_thread
    if worker_thread and worker_thread.is_alive():
        stop_event.set()
        worker_thread.join(timeout=5)
    start_worker()

start_worker()

PROJECTS_FILE = "aib_instance/projects.json"
CHATS_DIR = "aib_instance/chats"

os.makedirs(CHATS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(PROJECTS_FILE), exist_ok=True)

# ---------- Helpers ----------
def load_projects():
    if not os.path.exists(PROJECTS_FILE):
        with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_projects(projects):
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2)

def get_project(pid):
    projects = load_projects()
    return next((p for p in projects if p["id"] == pid), None), projects

def is_project_running(pid):
    # Clean up stale entries for this project
    stale_job_ids = []
    for jid, job in active_jobs.items():
        if job.get('pid') == pid and job.get('status') not in ['running', 'queued']:
            stale_job_ids.append(jid)
    for jid in stale_job_ids:
        del active_jobs[jid]

    for jid, status in run_status.items():
        if status.get('project_id') == pid and status.get('status') not in ['running', 'queued']:
            del run_status[jid]

    # Check active jobs
    for job_id, job in active_jobs.items():
        if job.get('pid') == pid and job.get('status') in ['running', 'queued']:
            return True, job_id

    # Check run_status
    for job_id, status in run_status.items():
        if status.get('project_id') == pid and status.get('status') in ['running', 'queued']:
            return True, job_id

    return False, None

# ---------- Routes ----------
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

    root_directory = request.form.get("rootDirectory", "")
    if not root_directory:
        return jsonify({"error": "Root directory is required"}), 400

    include_patterns = request.form.get("includePatterns", "")
    if not include_patterns:
        return jsonify({"error": "At least one include pattern is required"}), 400

    patterns = [p.strip() for p in include_patterns.split(",") if p.strip()]
    has_absolute = any(os.path.isabs(p) for p in patterns)
    has_relative = any(not os.path.isabs(p) for p in patterns)

    if has_relative and not root_directory and not has_absolute:
        return jsonify({"error": "rootDirectory is required if includePatterns contain relative paths and no absolute paths"}), 400

    project = {
        "id": pid,
        "name": name,
        "rootDirectory": root_directory,
        "includePatterns": include_patterns,
        "excludePatterns": request.form.get("excludePatterns", ""),
        "iterations": 1,
        "instructions": request.form.get("instructions", ""),
        "preScript": request.form.get("preScript", ""),
        "postScript": request.form.get("postScript", ""),
        "mode": request.form.get("mode", "include"),
        "isArchived": False
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

    include_patterns = request.form.get("includePatterns", project.get("includePatterns", ""))
    if not include_patterns:
        return jsonify({"error": "At least one include pattern is required"}), 400

    patterns = [p.strip() for p in include_patterns.split(",") if p.strip()]
    has_absolute = any(os.path.isabs(p) for p in patterns)
    has_relative = any(not os.path.isabs(p) for p in patterns)

    if has_relative and not root_directory and not has_absolute:
        return jsonify({"error": "rootDirectory is required if includePatterns contain relative paths and no absolute paths"}), 400

    project.update({
        "name": request.form.get("name", project["name"]),
        "rootDirectory": root_directory,
        "includePatterns": include_patterns,
        "excludePatterns": request.form.get("excludePatterns", project.get("excludePatterns", "")),
        "iterations": 1,
        "instructions": request.form.get("instructions", project.get("instructions", "")),
        "preScript": request.form.get("preScript", project.get("preScript", "")),
        "postScript": request.form.get("postScript", project.get("postScript", "")),
        "mode": request.form.get("mode", project.get("mode", "include"))
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

@app.route("/api/queue", methods=["GET"])
def api_get_queue():
    return jsonify({"queue": job_queue, "running": running_job})

@app.route("/api/queue", methods=["POST"])
def api_add_to_queue():
    data = request.json
    pid = data.get("project_id")
    if not pid:
        return jsonify({"error": "project_id required"}), 400
    project, _ = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if not project.get("includePatterns"):
        return jsonify({"error": "No includePatterns specified"}), 400

    include_patterns = [p.strip() for p in project["includePatterns"].split(",") if p.strip()]
    has_absolute = any(os.path.isabs(p) for p in include_patterns)
    has_relative = any(not os.path.isabs(p) for p in include_patterns)

    if has_relative and not project.get("rootDirectory") and not has_absolute:
        return jsonify({"error": "rootDirectory required if includePatterns contain relative paths and no absolute paths"}), 400

    root_dir = project.get("rootDirectory", "")
    if root_dir and os.path.isdir(root_dir):
        all_files_pattern = any(p.strip() == "." or p.strip() == "./" or p.strip() == "" for p in include_patterns)
        if all_files_pattern and not project.get("excludePatterns"):
            return jsonify({
                "error": "Pattern includes entire directory without exclusion filters. This is not allowed for safety reasons.",
                "suggestion": "Add specific file patterns or exclusion patterns to limit the scope."
            }), 400

    job_id = str(uuid.uuid4())
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "output", job_id)
    try:
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        return jsonify({"error": f"Failed to create output directory: {str(e)}"}), 500

    with job_queue_lock:
        job_queue.append({"job_id": job_id, "project_id": pid})
    stop_event.clear()
    if not worker_thread or not worker_thread.is_alive():
        start_worker()
    return jsonify({"status": "queued", "job_id": job_id})

@app.route("/api/queue/<job_id>", methods=["DELETE"])
def api_delete_from_queue(job_id):
    with job_queue_lock:
        for i, j in enumerate(job_queue):
            if j["job_id"] == job_id:
                job_queue.pop(i)
                break
        if running_job and running_job["job_id"] == job_id:
            running_job = None
    stop_event.clear()
    if not worker_thread or not worker_thread.is_alive():
        start_worker()
    return jsonify({"status": "deleted"})

@app.route("/api/queue/running/stop", methods=["POST"])
def api_stop_running():
    with job_queue_lock:
        if running_job:
            running_job = None
    stop_event.clear()
    if not worker_thread or not worker_thread.is_alive():
        start_worker()
    return jsonify({"status": "stopped"})

@app.route("/api/projects/<pid>", methods=["DELETE"])
def api_delete_project(pid):
    with job_queue_lock:
        job_queue[:] = [j for j in job_queue if j["project_id"] != pid]
        if running_job and running_job["project_id"] == pid:
            running_job = None
    stop_event.clear()
    if not worker_thread or not worker_thread.is_alive():
        start_worker()

    projects = load_projects()
    projects = [p for p in projects if p["id"] != pid]
    save_projects(projects)
    return jsonify({"status": "deleted"})

@app.route("/api/history", methods=["GET"])
def api_get_history():
    current_job_history = sorted(job_history, key=lambda x: x["timestamp"], reverse=True)
    return jsonify(current_job_history)

@app.route("/api/history/clear", methods=["POST"])
def api_clear_history():
    global job_history
    with job_queue_lock:
        job_history.clear()
        save_job_history()
    return jsonify({"status": "cleared"})

@app.route("/api/files", methods=["GET"])
def api_files():
    path = request.args.get("path", ".")
    search = request.args.get("search", "").lower()
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if not os.path.isabs(path):
            if path.startswith('./') or path.startswith('.\\'):
                path = os.path.abspath(path)
            else:
                path = os.path.abspath(os.path.join(os.getcwd(), path))

        path = os.path.normpath(path)
        if not os.path.exists(path):
            return jsonify({"error": f"Path does not exist: {path}"}), 400

        if path.startswith('/etc') or path.startswith('/usr') or path.startswith('/var') or \
           path.startswith('C:\Windows') or path.startswith('C:\Program Files'):
            return jsonify({"error": "Access to system directories is not allowed"}), 403

        all_paths = []
        for root, dirs, files in os.walk(path):
            rel_root = os.path.relpath(root, path)
            if rel_root == ".":
                rel_root = ""
            for f in files:
                rel_path = os.path.join(rel_root, f) if rel_root else f
                if search and search not in rel_path.lower():
                    continue
                file_size = os.path.getsize(os.path.join(root, f))
                all_paths.append({"path": rel_path, "size": file_size})

        all_paths.sort(key=lambda x: x["path"])
        total = len(all_paths)
        paginated = all_paths[offset:offset+limit]
        return jsonify({"files": paginated, "total": total, "offset": offset, "limit": limit})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ---------- Chat Routes ----------
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
                except Exception as e:
                    print(f"Error reading chat file {fname}: {e}")
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

        prompt = f"{chr(10)}".join(prompt_parts) + f"{chr(10)}Assistant:"

        def generate():
            response_content = ""
            try:
                if Config.use_local_model():
                    model_path = Config.get_model_path()
                    if not model_path:
                        raise ValueError("MODEL_PATH environment variable not set for local model.")
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    llama_binary = Config.get_llama_binary_path()
                    if not os.path.isfile(llama_binary):
                        raise FileNotFoundError(f"llama binary not found at: {llama_binary}")
                    ticks = int(time.time() * 1000)
                    filename = os.path.join(CHATS_DIR, f"chat_prompt_{ticks}.txt")
                    with open(filename, "w", encoding='utf-8') as f:
                        f.write(prompt)
                    cmd = [
                        llama_binary, "-m", model_path, "-f", filename,
                        "--temp", str(Config.get_temperature()), "--top-p", str(Config.get_top_p()),
                        "--top-k", str(Config.get_top_k()), "--min-p", str(Config.get_min_p()),
                        "-n", str(Config.get_output_tokens()), "--ctx-size", str(Config.get_model_context()),
                        "--jinja", "--no-display-prompt", "-st"
                    ]
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
                    for token in iter(lambda: process.stdout.read(1), ''):
                        response_content += token
                        yield token
                        if len(response_content) % 20 == 0:
                            chat_data["messages"] = [m for m in chat_data["messages"] if m["role"] != "assistant"]
                            chat_data["messages"].append({"role": "assistant", "content": response_content})
                            with open(chat_path, "w", encoding="utf-8") as f:
                                json.dump(chat_data, f, indent=2)
                    process.wait()
                    if os.path.exists(filename):
                        os.remove(filename)
                else:
                    endpoint = Config.get_endpoint()
                    model_name = Config.get_model_name()
                    api_key = Config.get_api_key()
                    verify_ssl = Config.verify_ssl()
                    if not all([endpoint, model_name, api_key]):
                        raise ValueError("Missing one or more required environment variables: ENDPOINT, MODEL_NAME, API_KEY")
                    client = ChatCompletionsClient(
                        endpoint=endpoint, credential=AzureKeyCredential(api_key),
                        api_version="2024-05-01-preview", connection_verify=verify_ssl
                    )
                    response = client.complete(
                        stream=True,
                        messages=[SystemMessage(content="You are a helpful coding assistant."), UserMessage(content=prompt)],
                        max_tokens=Config.get_output_tokens(), model=model_name
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
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == "__main__":
    app.run(port=5000, debug=True, threaded=True)