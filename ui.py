import os
import json
from uuid import uuid4
import uuid
from flask import Flask, redirect, request, jsonify, render_template
from ai_builder import AIBuilder
from config import Config

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

app = Flask(__name__)

PROJECTS_FILE = "instance/projects.json"
CHATS_DIR = "instance/chats"

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
    return jsonify(project)


@app.route("/api/projects", methods=["POST"])
def api_create_project():
    projects = load_projects()
    pid = str(uuid4())

    project = {
        "id": pid,
        "name": request.form["name"],
        "rootDirectory": request.form["rootDirectory"],
        "includePatterns": [x.strip() for x in request.form.get("includePatterns", "").split(",") if x.strip()],
        "excludePatterns": [],
        "useGitDiff": False,
        "iterations": int(request.form.get("iterations", "1")),
        "instructions": "",
        "preScript": "",
        "postScript": "",
        "modelConfig": {
            "endpoint": "",
            "modelName": "",
            "apiKey": ""
        }
    }

    projects.append(project)
    save_projects(projects)
    return jsonify(project)


@app.route("/api/projects/<pid>", methods=["POST"])
def api_update_project(pid):
    project, projects = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    updated = {
        "id": pid,
        "name": project["name"],
        "rootDirectory": request.form.get("rootDirectory", project.get("rootDirectory", "")),
        "includePatterns": [x.strip() for x in request.form.get("includePatterns", "").split(",") if x.strip()],
        "excludePatterns": project.get("excludePatterns", []),
        "useGitDiff": project.get("useGitDiff", False),
        "iterations": int(request.form.get("iterations", project.get("iterations", 1))),
        "instructions": request.form.get("instructions", project.get("instructions", "")),
        "preScript": request.form.get("preScript", project.get("preScript", "")),
        "postScript": request.form.get("postScript", project.get("postScript", "")),
        "modelConfig": project.get("modelConfig", {"endpoint": "", "modelName": "", "apiKey": ""})
    }

    for i, p in enumerate(projects):
        if p["id"] == pid:
            projects[i] = updated
            break

    save_projects(projects)
    return jsonify({"status": "saved", "project": updated})


@app.route("/api/projects/<pid>/run", methods=["POST"])
def api_run_project(pid):
    project, _ = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Clean-mode AI Builder: no files emitted into target rootDirectory
    builder = AIBuilder(project_config=project)
    builder.run()

    return jsonify({"status": "completed"})


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
        tree = {}
        for root, dirs, files in os.walk(path):
            rel_root = os.path.relpath(root, path)
            if rel_root == ".":
                rel_root = ""
            if rel_root not in tree:
                tree[rel_root] = {"dirs": [], "files": []}
            tree[rel_root]["dirs"].extend(sorted(dirs))
            tree[rel_root]["files"].extend(sorted(files))
        return jsonify(tree)
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
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    chats.append({
                        "id": data.get("id", fname.replace(".json", "")),
                        "title": data.get("messages", [{}])[0].get("content", "New Chat")[:30]
                    })
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
    os.makedirs(CHATS_DIR, exist_ok=True)
    chat_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
    if not os.path.exists(chat_path):
        return jsonify({"error": "Chat not found"}), 404
    with open(chat_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/api/chats/<chat_id>/messages", methods=["POST"])
def api_send_message(chat_id):
    message = request.json.get("content", "")
    if not message:
        return jsonify({"error": "Missing message content"}), 400
    
    os.makedirs(CHATS_DIR, exist_ok=True)
    chat_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
    if not os.path.exists(chat_path):
        return jsonify({"error": "Chat not found"}), 404
        
    with open(chat_path, "r", encoding="utf-8") as f:
        chat_data = json.load(f)
        
    chat_data["messages"].append({"role": "user", "content": message})
    
    try:
        endpoint = Config.get_endpoint()
        model_name = Config.get_model_name()
        api_key = Config.get_api_key()
        if not all([endpoint, model_name, api_key]):
            raise ValueError("Missing Azure AI credentials")
            
        client = ChatCompletionsClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(api_key),
            api_version="2024-05-01-preview",
            connection_verify=Config.verify_ssl()
        )
        
        messages = [SystemMessage(content="You are a helpful coding assistant.")] + [
            UserMessage(content=msg["content"]) if msg["role"] == "user" else SystemMessage(content=msg["content"])
            for msg in chat_data["messages"]
        ]
        
        response = client.complete(messages=messages, max_tokens=Config.get_output_tokens() or 2048, model=model_name)
        ai_reply = response.choices[0].message.content if response.choices else "No response generated."
        
        chat_data["messages"].append({"role": "assistant", "content": ai_reply})
    except Exception as e:
        ai_reply = f"Error calling LLM: {str(e)}"
        
    with open(chat_path, "w", encoding="utf-8") as f:
        json.dump(chat_data, f, indent=2)
        
    return jsonify({"response": ai_reply, "messages": chat_data["messages"]})


@app.route("/api/chats/<chat_id>", methods=["DELETE"])
def api_delete_chat(chat_id):
    chat_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
    if os.path.exists(chat_path):
        os.remove(chat_path)
    return jsonify({"status": "deleted"})


if __name__ == "__main__":
    app.run(port=5000, debug=True)