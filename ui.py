import os
import json
from uuid import uuid4
from flask import Flask, request, jsonify, render_template_string
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


# ---------- UI Template ----------
HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>AI Builder – Blocky Studio</title>
    <style>
        body {
            background: #1e1e1e;
            font-family: monospace;
            color: #fff;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
        }
        .container {
            width: 1000px;
            margin: 40px auto;
            background: #2e2e2e;
            padding: 20px;
            border: 5px solid #444;
        }
        h1 {
            text-align: center;
        }
        .flex-row {
            display: flex;
            gap: 20px;
        }
        .block {
            background: #3b3b3b;
            padding: 15px;
            margin-bottom: 20px;
            border: 4px solid #000;
        }
        .block h2 {
            margin-top: 0;
        }
        .project-list {
            background: #4a4a4a;
            padding: 10px;
            border: 3px solid #000;
            max-height: 400px;
            overflow-y: auto;
        }
        .project-item {
            padding: 10px;
            margin: 5px 0;
            background: #5c8a3b;
            cursor: pointer;
            border: 3px solid #000;
        }
        .project-item:hover {
            background: #6aa94a;
        }
        label {
            display: block;
            margin-top: 10px;
        }
        input, textarea {
            width: 100%;
            background: #1e1e1e;
            color: #fff;
            border: 2px solid #555;
            padding: 8px;
            margin-top: 5px;
            font-family: monospace;
        }
        button {
            background: #5c8a3b;
            color: #fff;
            padding: 10px 16px;
            border: 3px solid #000;
            cursor: pointer;
            font-size: 14px;
            margin-top: 10px;
        }
        button:hover {
            background: #6aa94a;
        }
        .button-row {
            display: flex;
            gap: 10px;
            margin-top: 10px;
        }
        .small-note {
            font-size: 12px;
            color: #ccc;
        }
    </style>
</head>
<body>

<div class="container">
    <h1>AI Builder – Blocky Studio</h1>

    <div class="flex-row">
        <!-- Left: Projects & Add Project -->
        <div style="flex: 1;">
            <div class="block">
                <h2>Projects</h2>
                <div class="project-list">
                    {% for p in projects %}
                        <div class="project-item" onclick="selectProject('{{p['id']}}')">
                            {{ p['name'] }}<br>
                            <span class="small-note">{{ p['rootDirectory'] }}</span>
                        </div>
                    {% endfor %}
                    {% if not projects %}
                        <div class="small-note">No projects yet. Add one below.</div>
                    {% endif %}
                </div>
            </div>

            <div class="block">
                <h2>Add Project</h2>
                <form method="POST" action="/add">
                    <label>Project Name</label>
                    <input name="name" required>

                    <label>Root Directory (target project path)</label>
                    <input name="rootDirectory" required>

                    <label>Include Patterns (files/folders, comma separated)</label>
                    <input name="includePatterns" placeholder="e.g. *.py, src, app">

                    <label>Exclude Patterns (files/folders, comma separated)</label>
                    <input name="excludePatterns" placeholder="e.g. node_modules, .git">

                    <label>Use Git Diff (true/false)</label>
                    <input name="useGitDiff" value="true">

                    <label>Iterations</label>
                    <input name="iterations" value="1">

                    <label>Mode (include/exclude)</label>
                    <input name="mode" value="include">

                    <label>Model Endpoint</label>
                    <input name="endpoint" placeholder="https://...">

                    <label>Model Name</label>
                    <input name="modelName" placeholder="gpt-4o">

                    <label>API Key</label>
                    <input name="apiKey" placeholder="">

                    <button type="submit">Create Project</button>
                </form>
            </div>
        </div>

        <!-- Right: Interview-style Project Details -->
        <div style="flex: 2;">
            {% if selected %}
            <div class="block">
                <h2>Project Interview – {{selected['name']}}</h2>
                <p class="small-note">
                    Answer these blocks like an interview. AI Builder will use them without dirtying the target directory.
                </p>

                <form method="POST" action="/save">
                    <input type="hidden" name="id" value="{{selected['id']}}">

                    <label>1. Where is your project located?</label>
                    <input name="rootDirectory" value="{{selected['rootDirectory']}}">

                    <label>2. Which files/folders should be included?</label>
                    <input name="includePatterns" value="{{selected['includePatterns']|join(',')}}">

                    <label>3. Which files/folders should be excluded?</label>
                    <input name="excludePatterns" value="{{selected['excludePatterns']|join(',')}}">

                    <label>4. Should we use git diff instead of scanning everything? (true/false)</label>
                    <input name="useGitDiff" value="{{selected['useGitDiff']}}">

                    <label>5. How many iterations should we run?</label>
                    <input name="iterations" value="{{selected['iterations']}}">

                    <label>6. Mode (include/exclude)</label>
                    <input name="mode" value="{{selected['mode']}}">

                    <label>7. What instructions should AI Builder follow?</label>
                    <textarea name="instructions" rows="6">{{selected['instructions']}}</textarea>

                    <label>8. What should run before each iteration? (Pre PS1 script)</label>
                    <textarea name="preScript" rows="4">{{selected['preScript']}}</textarea>

                    <label>9. What should run after each iteration? (Post PS1 script)</label>
                    <textarea name="postScript" rows="4">{{selected['postScript']}}</textarea>

                    <label>10. Which model should we talk to? (Endpoint)</label>
                    <input name="endpoint" value="{{selected['modelConfig']['endpoint']}}">

                    <label>11. Model name</label>
                    <input name="modelName" value="{{selected['modelConfig']['modelName']}}">

                    <label>12. API key</label>
                    <input name="apiKey" value="{{selected['modelConfig']['apiKey']}}">

                    <div class="button-row">
                        <button type="submit">Save Interview Answers</button>
                    </div>
                </form>

                <form method="POST" action="/run">
                    <input type="hidden" name="id" value="{{selected['id']}}">
                    <div class="button-row">
                        <button type="submit">Run AI Builder (Clean Mode)</button>
                    </div>
                </form>

                <p class="small-note">
                    You can revise instructions and scripts, then re-run as many times as you like.
                </p>
            </div>
            {% else %}
            <div class="block">
                <h2>No project selected</h2>
                <p class="small-note">Select a project on the left or create a new one.</p>
            </div>
            {% endif %}
        </div>
    </div>
</div>

<script>
function selectProject(id) {
    window.location = "/?id=" + id;
}
</script>

</body>
</html>
"""

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
    return render_template_string(HTML, projects=projects, selected=selected)


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


if __name__ == "__main__":
    app.run(port=5000, debug=True)
