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
run_queue = queue.Queue()
run_status = {}
job_history = []
active_jobs = {}
job_queue_lock = threading.Lock()
state_lock = threading.Lock()
queue_order_counter = 0

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
    while True:
        job = run_queue.get()
        if job is None:
            break
        pid = job['pid']
        job_id = job['job_id']

        with state_lock:
            if run_status.get(job_id, {}).get('status') == 'stopped':
                run_queue.task_done()
                continue

            run_status[job_id] = {'status': 'running', 'project_id': pid, 'queue_order': run_status[job_id].get('queue_order', 0)}
            if job_id in active_jobs:
                active_jobs[job_id]['status'] = 'running'

        project, _ = get_project(pid)
        job_history.append({
            "job_id": job_id,
            "project_id": pid,
            "project_name": project.get("name", "Unknown") if project else "Unknown",
            "status": "running",
            "instructions": project.get("instructions", ""),
            "timestamp": datetime.now().isoformat()
        })
        save_job_history()

        try:
            if project:
                try:
                    ai = AIBuilder(project)
                    ai.run()
                    with state_lock:
                        run_status[job_id] = {'status': 'completed', 'project_id': pid, 'queue_order': run_status[job_id].get('queue_order', 0)}
                        if job_id in active_jobs:
                            active_jobs[job_id]['status'] = 'completed'
                        for item in job_history:
                            if item["job_id"] == job_id:
                                item["status"] = "completed"
                                item["end_timestamp"] = datetime.now().isoformat()
                                break
                except Exception as e:
                    with state_lock:
                        run_status[job_id] = {'status': 'error', 'message': str(e), 'project_id': pid, 'queue_order': run_status[job_id].get('queue_order', 0)}
                        if job_id in active_jobs:
                            active_jobs[job_id]['status'] = 'error'
                        for item in job_history:
                            if item["job_id"] == job_id:
                                item["status"] = "error"
                                item["error"] = str(e)
                                item["end_timestamp"] = datetime.now().isoformat()
                                break
            else:
                with state_lock:
                    run_status[job_id] = {'status': 'error', 'message': 'Project not found', 'project_id': pid, 'queue_order': run_status[job_id].get('queue_order', 0)}
                    if job_id in active_jobs:
                        active_jobs[job_id]['status'] = 'error'
                    for item in job_history:
                        if item["job_id"] == job_id:
                            item["status"] = "error"
                            item["error"] = "Project not found"
                            item["end_timestamp"] = datetime.now().isoformat()
                            break
        finally:
            save_job_history()
            with state_lock:
                if job_id in active_jobs:
                    del active_jobs[job_id]
                if job_id in run_status:
                    del run_status[job_id]
            run_queue.task_done()
            time.sleep(3)

threading.Thread(target=worker, daemon=True).start()

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
    with state_lock:
        stale_job_ids = [jid for jid, job in active_jobs.items() if job.get('pid') == pid and job.get('status') not in ['running', 'queued']]
        for jid in stale_job_ids:
            del active_jobs[jid]

        for jid, status in run_status.items():
            if status.get('project_id') == pid and status.get('status') not in ['running', 'queued']:
                del run_status[jid]

        for job_id, job in active_jobs.items():
            if job.get('pid') == pid and job.get('status') in ['running', 'queued']:
                return True, job_id

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
    if not root_directory:  # <-- REQUIRE ROOT DIRECTORY
        return jsonify({"error": "Root directory is required"}), 400

    include_patterns = request.form.get("includePatterns", "")
    if not include_patterns:
        return jsonify({"error": "At least one include pattern is required"}), 400

    # Allow absolute paths even if rootDirectory is set
    # Only require rootDirectory if there are relative paths and no absolute paths
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
    if not root_directory:  # <-- REQUIRE ROOT DIRECTORY
        return jsonify({"error": "Root directory is required"}), 400

    include_patterns = request.form.get("includePatterns", project.get("includePatterns", ""))
    if not include_patterns:
        return jsonify({"error": "At least one include pattern is required"}), 400

    # Same logic as create - allow absolute paths even if rootDirectory is set
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

@app.route("/api/projects/<pid>/run", methods=["POST"])
def api_run_project(pid):
    project, _ = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    with state_lock:
        is_running, existing_job_id = is_project_running(pid)
        if is_running:
            return jsonify({"status": "already_running", "job_id": existing_job_id})

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

        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "output", pid)
        try:
            if os.path.exists(output_dir):
                shutil.rmtree(output_dir)
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            return jsonify({"error": f"Failed to create output directory: {str(e)}"}), 500

        actions_file = os.path.join(output_dir, "actions.txt")
        warning_content = None
        if os.path.exists(actions_file):
            with open(actions_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    warning_content = content

        if warning_content:
            return jsonify({
                "warning": True,
                "actions_content": warning_content,
                "message": "Existing unapplied changes found. Review or clear them before running."
            })

        global queue_order_counter
        queue_order_counter += 1
        job_id = str(uuid.uuid4())
        run_status[job_id] = {'status': 'queued', 'project_id': pid, 'queue_order': queue_order_counter}
        active_jobs[job_id] = {
            'pid': pid,
            'status': 'queued',
            'queue_order': queue_order_counter,
            'project_name': project.get('name', 'Unknown')
        }

    with job_queue_lock:
        run_queue.put({'pid': pid, 'job_id': job_id})

    return jsonify({"status": "queued", "job_id": job_id})

@app.route("/api/projects/<pid>/stop", methods=["POST"])
def api_stop_project(pid):
    with state_lock:
        jobs_to_stop = [job_id for job_id, job in active_jobs.items() if job.get('pid') == pid]
        for job_id in jobs_to_stop:
            if job_id in active_jobs:
                active_jobs[job_id]['status'] = 'stopped'
            if job_id in run_status:
                run_status[job_id]['status'] = 'stopped'
                
        queued_jobs = [job_id for job_id, status in run_status.items() if status.get('project_id') == pid and status.get('status') == 'queued']
        for job_id in queued_jobs:
            run_status[job_id]['status'] = 'stopped'
            if job_id in active_jobs:
                del active_jobs[job_id]
                
        for item in job_history:
            if item["project_id"] == pid and item["status"] in ["running", "queued"]:
                item["status"] = "stopped"
                item["end_timestamp"] = datetime.now().isoformat()
        save_job_history()

    return jsonify({"status": "stopped", "stopped_jobs": list(set(jobs_to_stop + queued_jobs))})

@app.route("/api/projects/<pid>/clear", methods=["POST"])
def api_clear_project_artifacts(pid):
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "output", pid)
    for fname in ["output.txt", "modifications.txt", "current_response.txt", "log.txt", "actions.txt"]:
        fpath = os.path.join(output_dir, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass
    return jsonify({"status": "cleared"})

@app.route("/api/run/<job_id>/status", methods=["GET"])
def api_run_status(job_id):
    status = run_status.get(job_id, {'status': 'unknown'})
    return jsonify(status)

@app.route("/api/projects/<pid>", methods=["DELETE"])
def api_delete_project(pid):
    with state_lock:
        jobs_to_stop = [job_id for job_id, job in active_jobs.items() if job.get('pid') == pid]
        for job_id in jobs_to_stop:
            if job_id in active_jobs:
                active_jobs[job_id]['status'] = 'stopped'
            if job_id in run_status:
                run_status[job_id]['status'] = 'stopped'
        save_job_history()

    projects = load_projects()
    projects = [p for p in projects if p["id"] != pid]
    save_projects(projects)

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "output", pid)
    if os.path.exists(output_dir):
        try:
            shutil.rmtree(output_dir)
        except Exception:
            pass

    return jsonify({"status": "deleted"})

@app.route("/api/files", methods=["GET"])
def api_files():
    path = request.args.get("path", ".")
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
           path.startswith('C:\\Windows') or path.startswith('C:\\Program Files'):
            return jsonify({"error": "Access to system directories is not allowed"}), 403

        paths = []
        for root, dirs, files in os.walk(path):
            rel_root = os.path.relpath(root, path)
            if rel_root == ".":
                rel_root = ""
            for f in files:
                rel_path = os.path.join(rel_root, f) if rel_root else f
                file_size = os.path.getsize(os.path.join(root, f))
                paths.append({"path": rel_path, "size": file_size})
        return jsonify(paths)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/history", methods=["GET"])
def api_get_history():
    current_job_history = sorted(job_history, key=lambda x: x["timestamp"], reverse=True)
    return jsonify(current_job_history)

# ---------- NEW ENDPOINTS ----------
@app.route("/api/job-status", methods=["GET"])
def api_job_status():
    """Return current job statuses from the server."""
    with state_lock:
        sorted_jobs = sorted(active_jobs.values(), key=lambda x: x.get('queue_order', 0))
        return jsonify({
            "activeJobs": {k: {"projectId": v.get("pid"), "projectName": v.get("projectName", "Unknown"), "status": v.get("status", "unknown"), "queueOrder": v.get("queue_order", 0)} for k, v in active_jobs.items()},
            "runStatus": run_status,
            "sortedJobs": sorted_jobs
        })

@app.route("/api/projects/<pid>/output-files", methods=["GET"])
def api_get_output_files(pid):
    """Get list of files created in the output directory for a project."""
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "output", pid)
    if not os.path.exists(output_dir):
        return jsonify({"files": []})

    try:
        files = []
        for root, dirs, filenames in os.walk(output_dir):
            for filename in filenames:
                if filename.endswith(('.txt', '.log', '.json')):
                    continue
                full_path = os.path.join(root, filename)
                full_path = full_path.replace('\\', '/')
                files.append(full_path)
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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