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
        @import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap');
        
        :root {
            --dirt: #8B4513;
            --grass: #5C8A3B;
            --stone: #4A4A4A;
            --wood: #A0522D;
            --sky: #87CEEB;
            --dark-bg: #1e1e1e;
            --light-text: #fff;
            --border-width: 4px;
        }

        body {
            background-color: var(--dark-bg);
            background-image: 
                linear-gradient(45deg, #252525 25%, transparent 25%), 
                linear-gradient(-45deg, #252525 25%, transparent 25%), 
                linear-gradient(45deg, transparent 75%, #252525 75%), 
                linear-gradient(-45deg, transparent 75%, #252525 75%);
            background-size: 20px 20px;
            font-family: 'Press Start 2P', monospace;
            color: var(--light-text);
            margin: 0;
            padding: 20px;
            display: flex;
            justify-content: center;
            min-height: 100vh;
        }

        .container {
            width: 1100px;
            background: var(--stone);
            border: var(--border-width) solid #000;
            box-shadow: 8px 8px 0px #000;
            padding: 20px;
            display: flex;
            gap: 20px;
        }

        h1 {
            text-align: center;
            color: var(--grass);
            text-shadow: 2px 2px 0px #000;
            margin-bottom: 20px;
            font-size: 24px;
        }

        h2 {
            background: var(--dirt);
            padding: 10px;
            margin: 0 0 15px 0;
            border: 3px solid #000;
            box-shadow: inset 2px 2px 0px rgba(255,255,255,0.2), inset -2px -2px 0px rgba(0,0,0,0.5);
            font-size: 14px;
        }

        .panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        .panel-right {
            flex: 2;
        }

        .block {
            background: var(--wood);
            border: var(--border-width) solid #000;
            padding: 15px;
            box-shadow: 4px 4px 0px #000;
        }

        .project-list {
            background: var(--dark-bg);
            border: 3px solid #000;
            max-height: 300px;
            overflow-y: auto;
            padding: 10px;
        }

        .project-item {
            background: var(--grass);
            padding: 12px;
            margin: 8px 0;
            border: 3px solid #000;
            cursor: pointer;
            transition: transform 0.1s;
            font-size: 10px;
            line-height: 1.5;
        }

        .project-item:hover {
            transform: scale(1.02);
            background: #6aa94a;
        }

        .project-item.active {
            background: var(--sky);
            color: #000;
            font-weight: bold;
        }

        label {
            display: block;
            margin-top: 15px;
            font-size: 10px;
            color: #ddd;
        }

        input, textarea, select {
            width: 100%;
            background: var(--dark-bg);
            color: var(--light-text);
            border: 3px solid #555;
            padding: 10px;
            margin-top: 5px;
            font-family: 'Press Start 2P', monospace;
            font-size: 10px;
            box-sizing: border-box;
        }

        input:focus, textarea:focus {
            outline: none;
            border-color: var(--grass);
        }

        button {
            background: var(--grass);
            color: #fff;
            padding: 15px 20px;
            border: 4px solid #000;
            cursor: pointer;
            font-family: 'Press Start 2P', monospace;
            font-size: 12px;
            margin-top: 20px;
            width: 100%;
            box-shadow: 4px 4px 0px #000;
            transition: all 0.1s;
        }

        button:hover {
            background: #6aa94a;
            transform: translate(-2px, -2px);
            box-shadow: 6px 6px 0px #000;
        }

        button:active {
            transform: translate(2px, 2px);
            box-shadow: 2px 2px 0px #000;
        }

        .run-btn {
            background: var(--sky);
            color: #000;
        }

        .run-btn:hover {
            background: #aaddff;
        }

        .note {
            font-size: 9px;
            color: #aaa;
            margin-top: 10px;
            line-height: 1.4;
        }

        .flex-row {
            display: flex;
            gap: 20px;
        }

        ::-webkit-scrollbar {
            width: 12px;
        }
        ::-webkit-scrollbar-track {
            background: var(--dark-bg); 
        }
        ::-webkit-scrollbar-thumb {
            background: var(--wood); 
            border: 2px solid #000;
        }
    </style>
</head>
<body>

<div class="container">
    <h1>AI BUILDER – STUDIO</h1>

    <div class="panel">
        <div class="block">
            <h2>PROJECTS</h2>
            <div class="project-list">
                {% for p in projects %}
                    <div class="project-item {% if selected and selected['id'] == p['id'] %}active{% endif %}" onclick="selectProject('{{p['id']}}')">
                        {{ p['name'] }}<br>
                        <span style="color: #ccc; font-size: 8px;">{{ p['rootDirectory'] }}</span>
                    </div>
                {% endfor %}
                {% if not projects %}
                    <div class="note">NO PROJECTS FOUND.<br>ADD ONE BELOW.</div>
                {% endif %}
            </div>
        </div>

        <div class="block">
            <h2>ADD PROJECT</h2>
            <form method="POST" action="/add">
                <label>PROJECT NAME</label>
                <input name="name" required placeholder="My Cool Project">

                <label>ROOT DIRECTORY</label>
                <input name="rootDirectory" required placeholder="C:\dev\myapp">

                <label>INCLUDE PATTERNS (comma sep)</label>
                <input name="includePatterns" placeholder="*.py, src, app">

                <label>EXCLUDE PATTERNS (comma sep)</label>
                <input name="excludePatterns" placeholder="node_modules, .git">

                <label>USE GIT DIFF (true/false)</label>
                <input name="useGitDiff" value="true">

                <label>ITERATIONS</label>
                <input name="iterations" value="1" type="number">

                <label>MODE (include/exclude)</label>
                <input name="mode" value="include">

                <label>MODEL ENDPOINT</label>
                <input name="endpoint" placeholder="https://...">

                <label>MODEL NAME</label>
                <input name="modelName" placeholder="gpt-4o">

                <label>API KEY</label>
                <input name="apiKey" placeholder="">

                <button type="submit">CREATE PROJECT</button>
            </form>
        </div>
    </div>

    <div class="panel panel-right">
        {% if selected %}
        <div class="block">
            <h2>INTERVIEW – {{selected['name']}}</h2>
            <p class="note">
                ANSWER THESE BLOCKS LIKE AN INTERVIEW. AI BUILDER WILL USE THEM WITHOUT DIRTYING THE TARGET DIRECTORY.
            </p>

            <form method="POST" action="/save">
                <input type="hidden" name="id" value="{{selected['id']}}">

                <label>1. WHERE IS YOUR PROJECT LOCATED?</label>
                <input name="rootDirectory" value="{{selected['rootDirectory']}}">

                <label>2. WHICH FILES/FOLDERS SHOULD BE INCLUDED?</label>
                <input name="includePatterns" value="{{selected['includePatterns']|join(',')}}">

                <label>3. WHICH FILES/FOLDERS SHOULD BE EXCLUDED?</label>
                <input name="excludePatterns" value="{{selected['excludePatterns']|join(',')}}">

                <label>4. SHOULD WE USE GIT DIFF? (true/false)</label>
                <input name="useGitDiff" value="{{selected['useGitDiff']}}">

                <label>5. HOW MANY ITERATIONS?</label>
                <input name="iterations" value="{{selected['iterations']}}">

                <label>6. MODE (include/exclude)</label>
                <input name="mode" value="{{selected['mode']}}">

                <label>7. INSTRUCTIONS FOR AI BUILDER</label>
                <textarea name="instructions" rows="8">{{selected['instructions']}}</textarea>

                <label>8. PRE-SCRIPT (BEFORE EACH ITERATION)</label>
                <textarea name="preScript" rows="4">{{selected['preScript']}}</textarea>

                <label>9. POST-SCRIPT (AFTER EACH ITERATION)</label>
                <textarea name="postScript" rows="4">{{selected['postScript']}}</textarea>

                <label>10. MODEL ENDPOINT</label>
                <input name="endpoint" value="{{selected['modelConfig']['endpoint']}}">

                <label>11. MODEL NAME</label>
                <input name="modelName" value="{{selected['modelConfig']['modelName']}}">

                <label>12. API KEY</label>
                <input name="apiKey" value="{{selected['modelConfig']['apiKey']}}">

                <button type="submit">SAVE INTERVIEW ANSWERS</button>
            </form>

            <form method="POST" action="/run">
                <input type="hidden" name="id" value="{{selected['id']}}">
                <button type="submit" class="run-btn">RUN AI BUILDER (CLEAN MODE)</button>
            </form>

            <p class="note">
                REVISE INSTRUCTIONS & SCRIPTS, THEN RE-RUN AS MANY TIMES AS YOU LIKE.
            </p>
        </div>
        {% else %}
        <div class="block">
            <h2>NO PROJECT SELECTED</h2>
            <p class="note">SELECT A PROJECT ON THE LEFT OR CREATE A NEW ONE.</p>
        </div>
        {% endif %}
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
