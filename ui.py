import os
import json
from uuid import uuid4
from flask import Flask, request, jsonify, render_template
from ai_builder import AIBuilder

app = Flask(__name__)

PROJECTS_FILE = "projects.json"


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
    selected_id = request.args.get("id")
    selected = None
    if selected_id:
        selected = next((p for p in projects if p["id"] == selected_id), None)
    elif projects:
        selected = projects[0]
    return render_template("index.html", projects=projects, selected=selected)


@app.route("/api/files", methods=["GET", "POST"])
def api_files():
    path = request.form.get("path", request.args.get("path", "."))
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


@app.route("/add", methods=["POST"])
def add():
    projects = load_projects()
    pid = str(uuid4())

    project = {
        "id": pid,
        "name": request.form["name"],
        "rootDirectory": request.form["rootDirectory"],
        "includePatterns": [x.strip() for x in request.form.get("includePatterns", "").split(",") if x.strip()],
        "excludePatterns": [x.strip() for x in request.form.get("excludePatterns", "").split(",") if x.strip()],
        "useGitDiff": request.form.get("useGitDiff", "true").lower() == "true",
        "iterations": int(request.form.get("iterations", "1")),
        "mode": request.form.get("mode", "include"),
        "instructions": "",
        "preScript": "",
        "postScript": "",
        "modelConfig": {
            "endpoint": request.form.get("endpoint", ""),
            "modelName": request.form.get("modelName", ""),
            "apiKey": request.form.get("apiKey", "")
        }
    }

    projects.append(project)
    save_projects(projects)
    return jsonify({"status": "created", "id": pid})


@app.route("/save", methods=["POST"])
def save():
    pid = request.form["id"]
    project, projects = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    updated = {
        "id": pid,
        "name": project["name"],  # name stays from creation; could be editable if desired
        "rootDirectory": request.form["rootDirectory"],
        "includePatterns": [x.strip() for x in request.form.get("includePatterns", "").split(",") if x.strip()],
        "excludePatterns": [x.strip() for x in request.form.get("excludePatterns", "").split(",") if x.strip()],
        "useGitDiff": request.form.get("useGitDiff", "true").lower() == "true",
        "iterations": int(request.form.get("iterations", project.get("iterations", 1))),
        "mode": request.form.get("mode", project.get("mode", "include")),
        "instructions": request.form.get("instructions", project.get("instructions", "")),
        "preScript": request.form.get("preScript", project.get("preScript", "")),
        "postScript": request.form.get("postScript", project.get("postScript", "")),
        "modelConfig": {
            "endpoint": request.form.get("endpoint", project["modelConfig"].get("endpoint", "")),
            "modelName": request.form.get("modelName", project["modelConfig"].get("modelName", "")),
            "apiKey": request.form.get("apiKey", project["modelConfig"].get("apiKey", ""))
        }
    }

    for i, p in enumerate(projects):
        if p["id"] == pid:
            projects[i] = updated
            break

    save_projects(projects)
    return jsonify({"status": "saved"})


@app.route("/run", methods=["POST"])
def run():
    pid = request.form["id"]
    project, _ = get_project(pid)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Clean-mode AI Builder: no files emitted into target rootDirectory
    builder = AIBuilder(project_config=project)
    builder.run()

    return jsonify({"status": "completed"})

@app.route("/delete", methods=["POST"])
def delete():
    pid = request.form["id"]
    projects = load_projects()
    projects = [p for p in projects if p["id"] != pid]
    save_projects(projects)
    return jsonify({"status": "deleted"})

@app.route("/chat", methods=["POST"])
def chat():
    message = request.form.get("message", "")
    # In a real implementation, this would call the LLM and return the response.
    # For now, it echoes back to demonstrate the UI flow.
    response = f"Logged: '{message}'. AI response simulation."
    return jsonify({"response": response})


if __name__ == "__main__":
    app.run(port=5000, debug=True)
