
let fileTreeData = [];
let allPaths = [];

function showTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector(`.tab-btn[onclick="showTab('${tabName}')"]`).classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');
}

function handleFolderPick(input) {
    if (input.files && input.files.length > 0) {
        const path = input.files[0].webkitRelativePath.split('/')[0];
        document.getElementById('root-path').value = path;
        loadFileTree();
    }
}

function loadFileTree() {
    const pathInput = document.getElementById('root-path');
    const path = pathInput.value.trim();
    if (!path) {
        document.getElementById('file-tree-container').innerHTML = '<div class="note">Enter a path first.</div>';
        return;
    }
    document.getElementById('file-tree-container').innerHTML = '<div class="note">Loading...</div>';
    document.getElementById('tree-search').value = '';
    document.getElementById('tree-search').style.display = 'block';
    document.querySelector('.selector-controls').style.display = 'flex';

    fetch('/api/files?path=' + encodeURIComponent(path))
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                document.getElementById('file-tree-container').innerHTML = `<div class="note" style="color:red">Error: ${data.error}</div>`;
                return;
            }
            allPaths = flattenTree(data, '');
            renderTree();
        })
        .catch(err => {
            document.getElementById('file-tree-container').innerHTML = `<div class="note" style="color:red">Fetch failed: ${err}</div>`;
        });
}

function flattenTree(tree, currentPath) {
    let paths = [];
    for (const [dir, info] of Object.entries(tree)) {
        const fullPath = currentPath ? currentPath + '/' + dir : dir;
        info.dirs.forEach(d => paths.push(fullPath + '/' + d));
        info.files.forEach(f => paths.push(fullPath + '/' + f));
    }
    return paths;
}

function renderTree() {
    const container = document.getElementById('file-tree-container');
    container.innerHTML = '';
    allPaths.forEach(path => {
        const el = createTreeItem(path);
        container.appendChild(el);
    });
    updateHiddenInputs();
}

function createTreeItem(path) {
    const div = document.createElement('div');
    div.className = 'tree-item file';
    div.dataset.path = path;
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = false;
    cb.onchange = updateHiddenInputs;
    const label = document.createElement('span');
    label.textContent = path;
    div.appendChild(cb);
    div.appendChild(label);
    return div;
}

function updateHiddenInputs() {
    const container = document.getElementById('file-tree-container');
    const checked = Array.from(container.querySelectorAll('input[type="checkbox"]:checked'));
    const paths = checked.map(cb => cb.parentElement.dataset.path);
    document.getElementById('patterns-input').value = paths.join(',');
    document.getElementById('patterns-display').value = paths.join('\n');
}

function selectAll() {
    document.querySelectorAll('#file-tree-container .visible input[type="checkbox"]').forEach(cb => cb.checked = true);
    updateHiddenInputs();
}

function deselectAll() {
    document.querySelectorAll('#file-tree-container .visible input[type="checkbox"]').forEach(cb => cb.checked = false);
    updateHiddenInputs();
}

function filterTree() {
    const query = document.getElementById('tree-search').value.toLowerCase();
    document.querySelectorAll('.tree-item').forEach(item => {
        const path = item.dataset.path.toLowerCase();
        if (path.includes(query)) {
            item.classList.add('visible');
            item.style.display = 'flex';
        } else {
            item.classList.remove('visible');
            item.style.display = 'none';
        }
    });
    updateHiddenInputs();
}

function selectProject(id) {
    window.location.href = `/?id=${id}`;
}

function runProject(id) {
    if(!confirm("Run AI Builder for this project?")) return;
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/run';
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'id';
    input.value = id;
    form.appendChild(input);
    document.body.appendChild(form);
    form.submit();
}

function deleteProject(id) {
    if(!confirm("Are you sure you want to delete this project? This cannot be undone.")) return;
    fetch('/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: `id=${encodeURIComponent(id)}`
    })
    .then(res => res.json())
    .then(data => {
        if(data.status === 'deleted') {
            window.location.reload();
        } else {
            alert('Failed to delete project.');
        }
    })
    .catch(err => alert('Error: ' + err));
}

let chatHistory = [];

function sendChat() {
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;

    const log = document.getElementById('chat-log');
    const userDiv = document.createElement('div');
    userDiv.className = 'chat-msg user';
    userDiv.innerHTML = `<strong>YOU</strong>${msg}`;
    log.appendChild(userDiv);
    log.scrollTop = log.scrollHeight;
    input.value = '';

    chatHistory.push({ role: 'user', content: msg });

    fetch('/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: `message=${encodeURIComponent(msg)}`
    })
    .then(res => res.json())
    .then(data => {
        const modelDiv = document.createElement('div');
        modelDiv.className = 'chat-msg model';
        modelDiv.innerHTML = `<strong>AI BUILDER</strong>${data.response}`;
        log.appendChild(modelDiv);
        log.scrollTop = log.scrollHeight;
        chatHistory.push({ role: 'model', content: data.response });
        updateInstructions();
    })
    .catch(err => {
        const errDiv = document.createElement('div');
        errDiv.className = 'chat-msg model';
        errDiv.innerHTML = `<strong>AI BUILDER</strong>Error: ${err}`;
        log.appendChild(errDiv);
    });
}

function updateInstructions() {
    const textarea = document.querySelector('textarea[name="instructions"]');
    if (textarea) {
        textarea.value = chatHistory.map(m => `${m.role === 'user' ? 'USER' : 'MODEL'}: ${m.content}`).join('\n\n');
    }
}
