import os
import json
import uuid
import time
import subprocess
import platform
import queue
import threading
from flask import Flask, Response, request, jsonify, render_template
from ai_builder import AIBuilder
from config import Config
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

app = Flask(__name__)

run_queue = queue.Queue()
run_status = {}

def worker():
    while True:
        job = run_queue.get()
        pid = job['pid']
        job_id = job['job_id']
        run_status[job_id] = {'status': 'running'}
        project, _ = get_project(pid)
        if project:
            try:
                ai = AIBuilder(project)
                ai.run()
                run_status[job_id] = {'status': 'completed'}
            except Exception as e:
                run_status[job_id] = {'status': 'error', 'message': str(e)}
        else:
            run_status[job_id] = {'status': 'error', 'message': 'Project not found'}
        run_queue.task_done()

threading.Thread(target=worker, daemon=True).start()

PROJECTS_FILE = "aib_instance/projects.json"
CHATS_DIR = "aib_instance/chats"

# Ensure required directories exist on startup
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
    return jsonify(project)

@app.route("/api/projects", methods=["POST"])
def api_create_project():
    projects = load_projects()
    pid = str(uuid.uuid4())

    project = {
        "id": pid,
        "name": request.form["name"],
        "rootDirectory": request.form["rootDirectory"],
        "includePatterns": request.form.get("includePatterns", ""),
        "excludePatterns": request.form.get("excludePatterns", ""),
        "iterations": int(request.form.get("iterations", "1")),
        "instructions": request.form.get("instructions", ""),
        "preScript": request.form.get("preScript", ""),
        "postScript": request.form.get("postScript", ""),
        "mode": request.form.get("mode", "include")
    }

    projects.append(project)
    save_projects(projects)
    return jsonify(project)

@app.route("/api/projects/<pid>", methods=["POST"])
def api_update_project(pid):
    project, projects = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    project.update({
        "name": request.form.get("name", project["name"]),
        "rootDirectory": request.form.get("rootDirectory", project["rootDirectory"]),
        "includePatterns": request.form.get("includePatterns", project.get("includePatterns", "")),
        "excludePatterns": request.form.get("excludePatterns", project.get("excludePatterns", "")),
        "iterations": int(request.form.get("iterations", project.get("iterations", 1))),
        "instructions": request.form.get("instructions", project.get("instructions", "")),
        "preScript": request.form.get("preScript", project.get("preScript", "")),
        "postScript": request.form.get("postScript", project.get("postScript", "")),
        "mode": request.form.get("mode", project.get("mode", "include"))
    })

    save_projects(projects)
    return jsonify({"status": "saved", "project": project})

@app.route("/api/projects/<pid>/run", methods=["POST"])
def api_run_project(pid):
    project, _ = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    job_id = str(uuid.uuid4())
    run_queue.put({'pid': pid, 'job_id': job_id})
    return jsonify({"status": "queued", "job_id": job_id})

@app.route("/api/run/<job_id>/status", methods=["GET"])
def api_run_status(job_id):
    status = run_status.get(job_id, {'status': 'unknown'})
    return jsonify(status)

@app.route("/api/projects/<pid>", methods=["DELETE"])
def api_delete_project(pid):
    projects = load_projects()
    projects = [p for p in projects if p["id"] != pid]
    save_projects(projects)
    return jsonify({"status": "deleted"})

@app.route("/api/files", methods=["GET"])
def api_files():
    path = request.args.get("path", ".")
    try:
        if not os.path.exists(path):
            return jsonify({"error": f"Path does not exist: {path}"}), 400

        paths = []
        for root, dirs, files in os.walk(path):
            rel_root = os.path.relpath(root, path)
            if rel_root == ".":
                rel_root = ""
            for d in dirs:
                rel_path = os.path.join(rel_root, d) if rel_root else d
                paths.append(f"{rel_path}/")
            for f in files:
                rel_path = os.path.join(rel_root, f) if rel_root else f
                paths.append(rel_path)
        return jsonify(paths)
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
                        chats.append({
                            "id": data.get("id", fname.replace(".json", "")),
                            "title": title
                        })
                except Exception as e:
                    print(f"Error reading chat file {fname}: {e}")
    return jsonify(chats)

@app.route("/api/chats", methods=["POST"])
def api_create_chat():
    os.makedirs(CHATS_DIR, exist_ok=True)
    chat_id = str(uuid.uuid4())
    chat_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
    with open(chat_path, "w", encoding="utf-8") as f:
        json.dump({"id": chat_id, "messages": []}, f)
    return jsonify({"id": chat_id})

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

def run_model_for_chat(prompt: str, project_config: dict = None) -> str:
    """
    Mirrors the logic in AIBuilder.run_model() to generate a response for chat.
    Uses either local model (llama.cpp) or Azure AI Inference based on Config.
    """
    response_content = ""

    if Config.use_local_model():
        # Use local model (llama.cpp)
        model_path = Config.get_model_path()
        if not model_path:
            raise ValueError("MODEL_PATH environment variable not set for local model.")

        base_dir = os.path.dirname(os.path.abspath(__file__))
        llama_binary = os.path.join(base_dir, "llama.cpp", "build", "bin", "llama-completion")

        if not os.path.isfile(llama_binary):
            raise FileNotFoundError(f"llama binary not found at: {llama_binary}")

        ticks = int(time.time() * 1000)
        filename = os.path.join(CHATS_DIR, f"chat_prompt_{ticks}.txt")

        with open(filename, "w", encoding='utf-8') as f:
            f.write(prompt)

        cmd = [
            llama_binary,
            "-m", model_path,
            "-f", filename,
            "--temp", str(Config.get_temperature()),
            "--top-p", str(Config.get_top_p()),
            "--top-k", str(Config.get_top_k()),
            "--min-p", str(Config.get_min_p()),
            "-n", str(Config.get_output_tokens()),
            "--ctx-size", str(Config.get_model_context()),
            "--jinja",
            "--no-display-prompt",
            "-st"
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        current_iteration = 0
        while True:
            token = process.stdout.read(1)
            if current_iteration % 100 == 0 or not token:
                # For chat, we don't need to write to a file, but we can log progress
                pass
            if not token:
                if os.path.exists(filename):
                    os.remove(filename)
                break
            response_content += token
            current_iteration += 1

        process.wait()
    else:
        # Use Azure AI Inference
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
            messages=[
                SystemMessage(content="You are a helpful coding assistant."),
                UserMessage(content=prompt)
            ],
            max_tokens=Config.get_output_tokens(),
            model=model_name
        )

        current_iteration = 0
        try:
            for update in response:
                if update.choices and isinstance(update.choices, list) and len(update.choices) > 0:
                    content = update.choices[0].get("delta", {}).get("content", "")
                    if content is not None:
                        response_content += content
                    if current_iteration % 100 == 0:
                        # For chat, we don't need to write to a file, but we can log progress
                        pass
                    current_iteration += 1
                else:
                    break
        finally:
            response.close()

    return response_content

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
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    llama_binary = os.path.join(base_dir, "llama.cpp", "build", "bin", "llama-completion")
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
                    response.close()
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
            json.dump({"id": chat_id, "messages": []}, f)
        return jsonify({"created": True, "id": chat_id})
    return jsonify({"created": False, "id": chats[-1]})

if __name__ == "__main__":
    app.run(port=5000, debug=True)