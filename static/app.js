// Global state
let currentProjectId = null;
let currentChatId = null;
let fileTreeData = [];

// Tab switching
function showTab(tabName) {
    document.querySelectorAll('.panel').forEach(panel => {
        panel.classList.add('hidden');
        panel.classList.remove('active');
    });
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });

    document.getElementById(tabName + '-panel').classList.remove('hidden');
    document.getElementById(tabName + '-panel').classList.add('active');
    event.target.classList.add('active');

    if (tabName === 'projects') {
        loadProjects();
    } else if (tabName === 'chat') {
        loadChats();
    }
}

// Load projects
function loadProjects() {
    fetch('/api/projects')
        .then(response => response.json())
        .then(data => {
            const projectList = document.getElementById('project-list');
            projectList.innerHTML = '';

            if (data.length === 0) {
                projectList.innerHTML = '<div class="note">NO PROJECTS FOUND.<br>ADD ONE BELOW.</div>';
                return;
            }

            data.forEach(project => {
                const projectItem = document.createElement('div');
                projectItem.className = 'project-item';
                projectItem.id = `proj-${project.id}`;
                projectItem.onclick = () => selectProject(project.id);

                projectItem.innerHTML = `
                            <div class="project-item-header">
                                <span class="project-item-name">${project.name}</span>
                                <div class="project-item-actions">
                                    <button class="btn-sm" onclick="event.stopPropagation(); runProject('${project.id}')">Run</button>
                                    <button class="btn-sm delete" onclick="event.stopPropagation(); deleteProject('${project.id}')">Del</button>
                                </div>
                            </div>
                            <span style="color: #ccc; font-size: 8px;">${project.rootDirectory || ''}</span>
                        `;

                projectList.appendChild(projectItem);
            });
        });
}

// Select a project
function selectProject(projectId) {
    currentProjectId = projectId;

    // Hide projects panel with animation
    document.getElementById('projects-panel').classList.add('hidden');
    document.getElementById('projects-panel').classList.remove('active');

    // Show project details panel
    document.getElementById('project-details-panel').classList.remove('hidden');
    document.getElementById('project-details-panel').classList.add('active');

    // Load project details
    fetch(`/api/projects/${projectId}`)
        .then(response => response.json())
        .then(project => {
            document.getElementById('details-project-id').value = project.id;
            document.getElementById('details-project-name').textContent = project.name;
            document.getElementById('details-root-dir').value = project.rootDirectory || '';
            document.getElementById('details-patterns').value = project.includePatterns || '';
            document.getElementById('details-iterations').value = project.iterations || 1;
            document.getElementById('details-instructions').value = project.instructions || '';
            document.getElementById('details-pre-script').value = project.preScript || '';
            document.getElementById('details-post-script').value = project.postScript || '';
            document.getElementById('run-project-id').value = project.id;
        });
}

// Go back to projects
function goBackToProjects() {
    document.getElementById('project-details-panel').classList.add('hidden');
    document.getElementById('project-details-panel').classList.remove('active');
    document.getElementById('projects-panel').classList.remove('hidden');
    document.getElementById('projects-panel').classList.add('active');
    loadProjects();
}

// Load file tree
function loadFileTree() {
    const rootPath = document.getElementById('root-path').value;
    if (!rootPath) {
        alert('Please enter a root directory first');
        return;
    }

    const loadTreeBtn = document.getElementById('load-tree-btn');
    const loadTreeText = document.getElementById('load-tree-text');
    const loadTreeSpinner = document.getElementById('load-tree-spinner');

    loadTreeBtn.disabled = true;
    loadTreeText.style.display = 'none';
    loadTreeSpinner.style.display = 'inline-block';

    fetch(`/api/files?path=${encodeURIComponent(rootPath)}`)
        .then(response => response.json())
        .then(paths => {
            // Build tree structure from flat paths
            const tree = {};
            paths.forEach(p => {
                const isDir = p.endsWith('/');
                const cleanPath = isDir ? p.slice(0, -1) : p;
                const parts = cleanPath.split('/');
                let current = tree;
                parts.forEach((part, idx) => {
                    if (!current[part]) {
                        current[part] = { children: {}, isDir: idx === parts.length - 1 ? false : true };
                    }
                    current = current[part].children;
                });
            });

            // Convert to array format expected by renderFileTree
            function buildArray(obj) {
                return Object.keys(obj).map(key => {
                    const node = obj[key];
                    const isDir = node.isDir;
                    const item = {
                        name: key,
                        type: isDir ? 'dir' : 'file',
                        path: `${rootPath}/${key}`,
                        children: isDir ? buildArray(node.children) : []
                    };
                    return item;
                });
            }

            fileTreeData = buildArray(tree);
            renderFileTree(fileTreeData);

            loadTreeBtn.disabled = false;
            loadTreeText.style.display = 'inline';
            loadTreeSpinner.style.display = 'none';

            document.getElementById('root-path-hidden').value = rootPath;
        })
        .catch(err => {
            console.error('Failed to load file tree:', err);
            loadTreeBtn.disabled = false;
            loadTreeText.style.display = 'inline';
            loadTreeSpinner.style.display = 'none';
            alert('Failed to load file tree. Check console.');
        });
}

// Render file tree
function renderFileTree(data, parentElement = null, level = 0) {
    const container = parentElement || document.getElementById('file-tree-container');
    container.innerHTML = '';

    function renderItems(items, container, level) {
        items.forEach(item => {
            const itemElement = document.createElement('div');
            itemElement.className = `tree-item ${item.type}`;
            itemElement.style.paddingLeft = `${level * 15}px`;

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = true; // Default to checked
            checkbox.onchange = () => updateSelectedPatterns();
            checkbox.dataset.path = item.path;

            const label = document.createElement('label');
            label.textContent = item.name;
            label.style.marginLeft = '5px';

            itemElement.appendChild(checkbox);
            itemElement.appendChild(label);
            container.appendChild(itemElement);

            if (item.type === 'dir' && item.children) {
                renderItems(item.children, container, level + 1);
            }
        });
    }

    renderItems(data, container, level);
    updateSelectedPatterns();
}

// Update selected patterns display
function updateSelectedPatterns() {
    const checkboxes = document.querySelectorAll('#file-tree-container input[type="checkbox"]:checked');
    const patterns = Array.from(checkboxes).map(cb => cb.dataset.path);
    document.getElementById('patterns-display').value = patterns.join(', ');
    document.getElementById('patterns-input').value = patterns.join(',');
}

// Select all files
function selectAll() {
    document.querySelectorAll('#file-tree-container input[type="checkbox"]').forEach(cb => {
        cb.checked = true;
    });
    updateSelectedPatterns();
}

// Deselect all files
function deselectAll() {
    document.querySelectorAll('#file-tree-container input[type="checkbox"]').forEach(cb => {
        cb.checked = false;
    });
    updateSelectedPatterns();
}

// Filter file tree
function filterTree() {
    const searchTerm = document.getElementById('tree-search').value.toLowerCase();
    const items = document.querySelectorAll('.tree-item');

    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        if (text.includes(searchTerm)) {
            item.style.display = '';
        } else {
            item.style.display = 'none';
        }
    });
}

// Auto-save project
function autoSaveProject() {
    if (!currentProjectId) return;

    const form = document.getElementById('project-details-form');
    const formData = new FormData(form);

    fetch(`/api/projects/${currentProjectId}`, {
        method: 'POST',
        body: formData
    }).catch(error => {
        console.error('Auto-save failed:', error);
    });
}

// Create new project
document.getElementById('add-project-form').addEventListener('submit', function (e) {
    e.preventDefault();

    const formData = new FormData(this);
    const projectName = document.getElementById('add-project-name').value;
    const rootPath = document.getElementById('root-path').value;

    fetch('/api/projects', {
        method: 'POST',
        body: formData
    })
        .then(response => response.json())
        .then(data => {
            // Clear form
            this.reset();
            document.getElementById('file-tree-container').innerHTML = '';
            document.getElementById('patterns-display').value = '';

            // Select the new project
            selectProject(data.id);
        });
});

// Run project
function runProject(projectId) {
    fetch(`/api/projects/${projectId}/run`, {
        method: 'POST'
    });
}

// Delete project
function deleteProject(projectId) {
    if (!confirm('Are you sure you want to delete this project?')) return;

    fetch(`/api/projects/${projectId}`, {
        method: 'DELETE'
    })
        .then(() => {
            if (currentProjectId === projectId) {
                goBackToProjects();
            } else {
                loadProjects();
            }
        });
}

// Chat functions
function loadChats() {
    fetch('/api/chats')
        .then(response => response.json())
        .then(chats => {
            const chatList = document.getElementById('chat-list');
            chatList.innerHTML = '';

            chats.forEach(chat => {
                const chatItem = document.createElement('div');
                chatItem.className = 'chat-item';
                chatItem.dataset.chatId = chat.id;
                chatItem.onclick = () => selectChat(chat.id);
                chatItem.innerHTML = `
                            <span>${chat.title || 'Unnamed Chat'}</span>
                            <button class="btn-xs" onclick="event.stopPropagation(); deleteChat('${chat.id}')">X</button>
                        `;
                chatList.appendChild(chatItem);
            });
        });
}

function newChat() {
    fetch('/api/chats', { method: 'POST' })
        .then(response => response.json())
        .then(chat => {
            selectChat(chat.id);
        });
}

function selectChat(chatId) {
    currentChatId = chatId;

    // Remove active class from all chat items
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });

    // Add active class to selected chat
    const selectedItem = document.querySelector(`.chat-item[data-chat-id="${chatId}"]`);
    if (selectedItem) selectedItem.classList.add('active');

    // Load chat messages
    fetch(`/api/chats/${chatId}`)
        .then(response => response.json())
        .then(chat => {
            const chatLog = document.getElementById('chat-log');
            chatLog.innerHTML = '';

            chat.messages.forEach(msg => {
                const msgElement = document.createElement('div');
                msgElement.className = `chat-msg ${msg.role}`;

                // Render markdown content
                if (msg.content.includes('```') || msg.content.includes('**') || msg.content.includes('*')) {
                    msgElement.innerHTML = `<strong>${msg.role.toUpperCase()}</strong><div class="markdown-content">${renderMarkdown(msg.content)}</div>`;
                } else {
                    msgElement.innerHTML = `<strong>${msg.role.toUpperCase()}</strong>${msg.content}`;
                }

                chatLog.appendChild(msgElement);
                chatLog.scrollTop = chatLog.scrollHeight;
            });
        });
}

function sendChat() {
    const input = document.getElementById('chat-input');
    const content = input.value.trim();
    if (!content || !currentChatId) return;

    fetch(`/api/chats/${currentChatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
    })
        .then(response => response.json())
        .then(message => {
            input.value = '';
            selectChat(currentChatId); // Refresh chat
        })
        .catch(err => console.error('Send failed:', err));
}

function deleteChat(chatId) {
    if (!confirm('Delete this chat?')) return;
    fetch(`/api/chats/${chatId}`, { method: 'DELETE' })
        .then(() => loadChats());
}

// Simple markdown renderer
function renderMarkdown(text) {
    // Escape HTML first
    let html = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Italic
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // Line breaks
    html = html.replace(/\n/g, '<br>');

    return html;
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadProjects();
});