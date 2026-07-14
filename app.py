
import os
import json
import subprocess
from flask import Flask, render_template, request, jsonify
from pathlib import Path

app = Flask(__name__)
PROJECTS_DIR = Path("projects")
PROJECTS_DIR.mkdir(exist_ok=True)

def save_project(project):
    project_id = project.get("id", "default")
    filepath = PROJECTS_DIR / f"{project_id}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=4)
    return str(filepath)

def load_project(project_id):
    filepath = PROJECTS_DIR / f"{project_id}.json"
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def list_projects():
    projects = []
    for p in PROJECTS_DIR.glob("*.json"):
        with open(p, "r", encoding="utf-8") as f:
            projects.append(json.load(f))
    return projects

def apply_project_to_env(project):
    with open("instructions.txt", "w", encoding="utf-8") as f:
        f.write(project.get("instructions", ""))
    with open("pre.ps1", "w", encoding="utf-8") as f:
        f.write(project.get("pre_script", "Write-Output 'Pre-script'"))
    with open("post.ps1", "w", encoding="utf-8") as f:
        f.write(project.get("post_script", "Write-Output 'Post-script'"))
    
    mode = project.get("mode", "exclude")
    patterns = project.get("exclude_patterns", []) + project.get("include_patterns", [])
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
    <iterations>1</iterations>
    <mode>{mode}</mode>
    <git_diff_command>git diff --name-only</git_diff_command>
    <patterns>
"""
    for p in patterns:
        xml_content += f"        <pattern>{p}</pattern>\n"
    xml_content += """    </patterns>
</config>
"""
    with open("user_config.xml", "w", encoding="utf-8") as f:
        f.write(xml_content)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/projects", methods=["GET"])
def get_projects():
    return jsonify(list_projects())

@app.route("/api/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    project = load_project(project_id)
    if project:
        return jsonify(project)
    return jsonify({"error": "Not found"}), 404

@app.route("/api/projects", methods=["POST"])
def create_project():
    project = request.json
    if "id" not in project:
        project["id"] = f"project_{len(list_projects()) + 1}"
    save_project(project)
    return jsonify(project), 201

@app.route("/api/projects/<project_id>", methods=["PUT"])
def update_project(project_id):
    project = request.json
    project["id"] = project_id
    save_project(project)
    return jsonify(project)

@app.route("/api/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id):
    filepath = PROJECTS_DIR / f"{project_id}.json"
    if filepath.exists():
        filepath.unlink()
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Not found"}), 404

@app.route("/api/run", methods=["POST"])
def run_project():
    project_id = request.json.get("project_id")
    project = load_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    apply_project_to_env(project)
    try:
        result = subprocess.run(["python", "ai_builder.py"], capture_output=True, text=True)
        if result.returncode == 0:
            return jsonify({"status": "success", "output": result.stdout})
        else:
            return jsonify({"status": "error", "output": result.stderr}), 500
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
