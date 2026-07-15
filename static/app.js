
let fileTreeData = [];
let allPaths = [];

function loadFileTree() {
    const pathInput = document.getElementById('root-path');
    const path = pathInput.value.trim();
    if (!path) {
        alert("Please enter a root path first.");
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
        info.dirs.forEach(d => {
            paths.push(fullPath + '/' + d);
        });
        info.files.forEach(f => {
            paths.push(fullPath + '/' + f);
        });
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
