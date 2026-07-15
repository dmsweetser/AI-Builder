
let currentMode = '';
let fileTreeData = {};

function selectProject(id) {
    window.location = "/?id=" + id;
}

function loadFileTree(mode) {
    const pathInput = document.getElementById(mode + '-path');
    const path = pathInput.value.trim();
    if (!path) {
        alert("Please enter a path first.");
        return;
    }
    currentMode = mode;
    document.getElementById('file-tree-container').innerHTML = '<div class="note">Loading...</div>';
    document.getElementById('tree-search').style.display = 'none';
    document.querySelector('.selector-controls').style.display = 'none';

    fetch('/api/files?path=' + encodeURIComponent(path))
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                document.getElementById('file-tree-container').innerHTML = `<div class="note" style="color:red">Error: ${data.error}</div>`;
                return;
            }
            fileTreeData = data;
            renderTree();
            document.getElementById('tree-search').style.display = 'block';
            document.querySelector('.selector-controls').style.display = 'flex';
        })
        .catch(err => {
            document.getElementById('file-tree-container').innerHTML = `<div class="note" style="color:red">Fetch failed: ${err}</div>`;
        });
}

function renderTree() {
    const container = document.getElementById('file-tree-container');
    container.innerHTML = '';
    Object.keys(fileTreeData).forEach(dir => {
        const item = fileTreeData[dir];
        item.dirs.forEach(d => {
            const el = createTreeItem(dir + '/' + d, true);
            container.appendChild(el);
        });
        item.files.forEach(f => {
            const el = createTreeItem(dir + '/' + f, false);
            container.appendChild(el);
        });
    });
    updateHiddenInputs();
}

function createTreeItem(path, isDir) {
    const div = document.createElement('div');
    div.className = `tree-item ${isDir ? 'dir' : 'file'}`;
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
    document.getElementById(currentMode + '-patterns-input').value = paths.join(',');
    document.getElementById(currentMode + '-patterns-display').value = paths.join('\n');
}

function selectAll() {
    document.querySelectorAll('#file-tree-container input[type="checkbox"]').forEach(cb => cb.checked = true);
    updateHiddenInputs();
}

function deselectAll() {
    document.querySelectorAll('#file-tree-container input[type="checkbox"]').forEach(cb => cb.checked = false);
    updateHiddenInputs();
}

function toggleFilter() {
    const search = document.getElementById('tree-search');
    search.style.display = search.style.display === 'none' ? 'block' : 'none';
    if (search.style.display === 'block') search.focus();
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

function selectFiltered() {
    document.querySelectorAll('#file-tree-container .visible input').forEach(cb => cb.checked = true);
    updateHiddenInputs();
}

function deselectFiltered() {
    document.querySelectorAll('#file-tree-container .visible input').forEach(cb => cb.checked = false);
    updateHiddenInputs();
}
