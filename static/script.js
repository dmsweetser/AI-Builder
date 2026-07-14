
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('projectForm');
    const projectList = document.getElementById('projectList');
    const logOutput = document.getElementById('logOutput');
    const saveBtn = document.getElementById('saveBtn');
    const runBtn = document.getElementById('runBtn');

    async function loadProjects() {
        const res = await fetch('/api/projects');
        const projects = await res.json();
        projectList.innerHTML = '';
        projects.forEach(p => {
            const li = document.createElement('li');
            li.className = 'list-group-item d-flex justify-content-between align-items-center';
            li.innerHTML = `
                <span>${p.id}</span>
                <div>
                    <button class="btn btn-sm btn-outline-light edit-btn" data-id="${p.id}">Edit</button>
                    <button class="btn btn-sm btn-outline-danger delete-btn" data-id="${p.id}">Del</button>
                </div>
            `;
            projectList.appendChild(li);
        });
        document.querySelectorAll('.edit-btn').forEach(btn => {
            btn.addEventListener('click', (e) => loadProject(e.target.dataset.id));
        });
        document.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', (e) => deleteProject(e.target.dataset.id));
        });
    }

    async function loadProject(id) {
        const res = await fetch(`/api/projects/${id}`);
        const p = await res.json();
        document.getElementById('id').value = p.id;
        document.getElementById('instructions').value = p.instructions || '';
        document.getElementById('pre_script').value = p.pre_script || '';
        document.getElementById('post_script').value = p.post_script || '';
        document.getElementById('mode').value = p.mode || 'exclude';
        const allPatterns = (p.exclude_patterns || []).concat(p.include_patterns || []);
        document.getElementById('patterns').value = allPatterns.join('\n');
        saveBtn.textContent = 'Update Project';
    }

    async function deleteProject(id) {
        if(!confirm('Delete project?')) return;
        await fetch(`/api/projects/${id}`, { method: 'DELETE' });
        loadProjects();
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const patternsText = document.getElementById('patterns').value.trim();
        const patterns = patternsText ? patternsText.split('\n').map(p => p.trim()).filter(Boolean) : [];
        const mode = document.getElementById('mode').value;
        
        const project = {
            id: document.getElementById('id').value,
            instructions: document.getElementById('instructions').value,
            pre_script: document.getElementById('pre_script').value,
            post_script: document.getElementById('post_script').value,
            mode: mode,
            exclude_patterns: mode === 'exclude' ? patterns : [],
            include_patterns: mode === 'include' ? patterns : []
        };
        
        const method = document.getElementById('id').dataset.oldId ? 'PUT' : 'POST';
        const url = method === 'PUT' ? `/api/projects/${project.id}` : '/api/projects';
        
        await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(project)
        });
        
        document.getElementById('id').dataset.oldId = project.id;
        saveBtn.textContent = 'Save Project';
        loadProjects();
    });

    runBtn.addEventListener('click', async () => {
        const id = document.getElementById('id').value;
        if (!id) { alert('Select or create a project first.'); return; }
        runBtn.disabled = true;
        logOutput.textContent = 'Starting project execution...\n';
        
        const res = await fetch('/api/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: id })
        });
        const data = await res.json();
        logOutput.textContent += data.output || 'Execution complete.';
        runBtn.disabled = false;
    });

    loadProjects();
});
