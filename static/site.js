// === Stateless UI — All state comes from /api/state ===
// The UI is purely presentational. It fetches everything from the backend
// and renders accordingly. No localStorage, no client-side caching,
// no per-project tracking objects.

let _uiState = {};        // Current state payload from /api/state
let _pollInterval = null;  // Polling timer handle
let _activeJobId = null;   // Currently viewed job (for live view)
let _showArchived = false; // Filter toggle (kept in memory only)
let currentProjectId = null; // Currently selected project (for inline HTML onclick handlers)
let chatId = null;         // Currently open chat (for sendChat)
let AVAILABLE_TOOLS = [];  // All tool names (loaded from backend)

// === Live View Scroll Tracking ===
let _liveViewPrevStepCount = 0;  // Last rendered step count for incremental updates
let _liveViewScrolledToBottom = true; // Whether user was at bottom before last render

// === Core State Fetch ===
async function fetchState() {
    try {
        const resp = await fetch('/api/state' + (_showArchived ? '?archived=true' : ''));
        if (resp.ok) {
            _uiState = await resp.json();
            return _uiState;
        }
    } catch (e) {
        console.error('State fetch failed:', e);
    }
    return _uiState;
}

// === Init — Load everything from backend ===
async function initUI() {
    // Load initial state
    await fetchState();
    
    // Load available tools from backend
    fetch('/api/tools/status')
        .then(function(r) { return r.json(); })
        .then(function(toolStatus) {
            AVAILABLE_TOOLS = Object.keys(toolStatus).sort();
            // Re-render tool selectors now that we have tool data
            var detailsSelector = document.getElementById('details-tool-selector');
            if (detailsSelector) {
                // Rebuild if form is already open
                var projectId = document.getElementById('run-project-id')?.value;
                if (projectId) {
                    fetch('/api/projects/' + projectId + '/tools')
                        .then(function(r) { return r.json(); })
                        .then(function(toolData) {
                            buildToolSelector(toolData.disabled_tools || [], toolData.custom_tools || []);
                        }).catch(function() {});
                }
            }
            var addSelector = document.getElementById('add-tool-selector');
            if (addSelector) {
                buildToolSelectorForElement('add-tool-selector', []);
            }
        })
        .catch(function(err) { console.warn('Failed to load tools status:', err); });
    
    // Render everything based on backend state
    renderProjects();
    loadChats();
    
    // Start polling for updates
    if (_pollInterval) clearInterval(_pollInterval);
    _pollInterval = setInterval(async () => {
        await fetchState();
        // Re-render the currently active panel
        const activePanel = document.querySelector('.panel.active');
        if (activePanel) {
            const panelId = activePanel.id;
            if (panelId === 'projects-panel' || panelId === 'project-details-panel') renderProjects();
            else if (panelId === 'chat-panel') loadChats();
        }
    }, 5000); // Poll every 5 seconds
}

// === Tab Management (stateless) ===
function showTab(tabName) {
    document.querySelectorAll('.panel').forEach(function(p) {
        p.classList.remove('active');
    });
    document.querySelectorAll('.tab-btn').forEach(function(b) {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
        b.setAttribute('tabindex', '-1');
    });
    var panel = document.getElementById(tabName + '-panel');
    if (panel) panel.classList.add('active');
    document.querySelectorAll('.tab-btn').forEach(function(b) {
        if (b.getAttribute('data-tab') === tabName) {
            b.classList.add('active');
            b.setAttribute('aria-selected', 'true');
            b.setAttribute('tabindex', '0');
        }
    });
    if (tabName === 'settings') loadSettingsUI();
    if (tabName === 'chat') loadChats();
}

// === Project Form Toggle ===
function toggleCreateForm() {
    var form = document.getElementById('create-project-form');
    if (form) {
        var isVisible = form.style.display === 'block';
        form.style.display = isVisible ? 'none' : 'block';
    }
}

// === Project Management (stateless) ===
function loadProjects() {
    renderProjects();
}

function renderProjects() {
    var projectList = document.getElementById('project-list');
    if (!projectList) return;
    projectList.innerHTML = '';
    var projects = _uiState.projects || [];
    
    if (projects.length === 0) {
        projectList.innerHTML = '<div class="note">NO PROJECTS FOUND. ADD ONE BELOW.</div>';
        return;
    }
    
    projects.forEach(function(project) {
        var projectItem = document.createElement('div');
        projectItem.className = 'project-item';
        projectItem.id = 'proj-' + project.id;
        projectItem.onclick = function() { selectProject(project.id); };

        // Build header
        var header = document.createElement('div');
        header.className = 'project-item-header';
        var nameSpan = document.createElement('span');
        nameSpan.className = 'project-item-name';
        nameSpan.textContent = project.name || 'Untitled';
        header.appendChild(nameSpan);
        // Status badge
        var statusBadge = document.createElement('span');
        var status = project.status || 'idle';
        statusBadge.className = 'project-item-status';
        if (status === 'running') {
            statusBadge.classList.add('running');
            statusBadge.textContent = 'RUNNING';
        } else if (status === 'queued') {
            statusBadge.classList.add('queued');
            statusBadge.textContent = 'QUEUED';
        } else if (project.run_number > 0) {
            statusBadge.classList.add('completed');
            statusBadge.textContent = 'COMPLETED';
        } else {
            statusBadge.classList.add('stopped');
            statusBadge.textContent = 'IDLE';
        }
        header.appendChild(statusBadge);
        if (project.run_number > 0) {
            var runSpan = document.createElement('span');
            runSpan.style.cssText = 'color:var(--text-muted);font-size:11px;';
            runSpan.textContent = 'Run #' + project.run_number;
            header.appendChild(runSpan);
        }
        projectItem.appendChild(header);

        // Build meta
        var meta = document.createElement('div');
        meta.className = 'project-item-meta';
        var pathSpan = document.createElement('span');
        pathSpan.className = 'project-item-path';
        pathSpan.textContent = project.rootDirectory || '';
        meta.appendChild(pathSpan);

        // Actions
        var actions = document.createElement('div');
        actions.className = 'project-item-actions';
        var status = project.status || 'idle';
        // VIEW button always visible
        var viewBtn = document.createElement('button');
        viewBtn.className = 'btn btn-sm btn-info';
        viewBtn.textContent = '👁 VIEW';
        viewBtn.onclick = function(e) {
            e.stopPropagation();
            var activeJobs = _uiState.active_jobs || {};
            var activeJob = activeJobs[project.id];
            var activeJobId = activeJob ? activeJob.job_id : null;
            openViewInNewTab(project.id, activeJobId || project.last_job_id);
        };
        var runBtn = document.createElement('button');
        runBtn.className = 'btn btn-sm btn-primary';
        runBtn.textContent = 'RUN';
        // Disable run button when project is running or queued
        if (status === 'running' || status === 'queued') {
            runBtn.disabled = true;
            runBtn.style.opacity = '0.4';
            runBtn.style.cursor = 'not-allowed';
            runBtn.textContent = 'RUNNING';
        }
        runBtn.onclick = function(e) { e.stopPropagation(); runProjectFromList(project); };
        var stopBtn = document.createElement('button');
        stopBtn.className = 'btn btn-sm btn-danger';
        stopBtn.textContent = 'STOP';
        stopBtn.onclick = function(e) { e.stopPropagation(); stopProject(project.id); };
        if (status === 'running') {
            actions.appendChild(viewBtn);
            actions.appendChild(runBtn);
            actions.appendChild(stopBtn);
        } else {
            actions.appendChild(viewBtn);
            actions.appendChild(runBtn);
            stopBtn.style.display = 'none';
            actions.appendChild(stopBtn);
        }
        var resetBtn = document.createElement('button');
        resetBtn.className = 'btn btn-sm btn-secondary';
        resetBtn.textContent = 'RESET';
        resetBtn.onclick = function(e) { e.stopPropagation(); resetProject(project.id); };
        actions.appendChild(resetBtn);
        var archiveBtn = document.createElement('button');
        archiveBtn.className = 'btn btn-sm btn-secondary';
        archiveBtn.textContent = project.isArchived ? '📤' : '📦';
        archiveBtn.title = project.isArchived ? 'Unarchive' : 'Archive';
        archiveBtn.onclick = function(e) { e.stopPropagation(); archiveProject(project.id, project.isArchived, e.target); };
        actions.appendChild(archiveBtn);
        var delBtn = document.createElement('button');
        delBtn.className = 'btn btn-sm btn-danger';
        delBtn.textContent = 'DEL';
        delBtn.onclick = function(e) { e.stopPropagation(); deleteProject(project.id); };
        actions.appendChild(delBtn);
        meta.appendChild(actions);
        projectItem.appendChild(meta);
        projectList.appendChild(projectItem);
    });
}

function runAgenticProject() {
    runProject.apply(null, arguments);
}

function runProject(projectId) {
    // Save project first, then run
    saveProjectChanges()
        .then(function() { _doRunProject(projectId); })
        .catch(function(err) {
            console.error('Failed to save project:', err);
            showNotification('Failed to save project changes. Please try again.', 'info');
        });
}

// Run a project directly from the project list (bypasses form-based save)
function runProjectFromList(project) {
    // Reset scroll tracking for new run
    _liveViewPrevStepCount = 0;

    var rootDir = project.rootDirectory || '';
    var instructions = project.instructions || '';

    if (!rootDir) { showNotification('Please set a root directory first.', 'info'); return; }

    // Show spinner on the Run button
    var runBtn = document.getElementById('details-run-btn');
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = '<span class="run-spinner"></span> RUNNING...'; }

    fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: project.id, rootDirectory: rootDir, instructions: instructions })
    })
    .then(function(response) {
        if (!response.ok) throw new Error('Failed to start agent run');
        return response.json();
    })
    .then(function(data) {
        if (data.error) throw new Error(data.error);
        // Open VIEW in new tab
        openViewInNewTab(project.id, data.job_id);
        showNotification('Run started — VIEW opened.', 'success');
        fetchState();
    })
    .catch(function(err) {
        console.error('Agent run error:', err);
        showNotification('Failed to start run: ' + err.message, 'error');
    })
    .finally(function() {
        if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = 'RUN AI BUILDER'; }
    });
}

function _doRunProject(projectId, overrideInstruction) {
    var rootDir = '';
    var instructions = '';

    // If called from project details form, read from form fields
    if (document.getElementById('details-root-dir')) {
        rootDir = document.getElementById('details-root-dir').value;
        instructions = overrideInstruction || document.getElementById('details-instructions').value;
    }
    // If rootDir is empty, try to get from state
    if (!rootDir) {
        var project = (_uiState.projects || []).find(function(p) { return p.id === projectId; });
        if (project) {
            rootDir = project.rootDirectory || '';
            instructions = overrideInstruction || project.instructions || '';
        }
    }
    if (!rootDir) { showNotification('Please set a root directory first.', 'info'); return; }

    // Reset scroll tracking for new run
    _liveViewPrevStepCount = 0;

    // Show spinner on the Run button
    var runBtn = document.getElementById('details-run-btn');
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = '<span class="run-spinner"></span> RUNNING...'; }

    fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, rootDirectory: rootDir, instructions: instructions })
    })
    .then(function(response) {
        if (!response.ok) throw new Error('Failed to start agent run');
        return response.json();
    })
    .then(function(data) {
        if (data.error) throw new Error(data.error);
        _activeJobId = data.job_id;
        // Open VIEW in new tab
        openViewInNewTab(projectId, data.job_id);
        showNotification('Run started — VIEW opened.', 'success');
        fetchState();
    })
    .catch(function(err) {
        console.error('Agent run error:', err);
        showNotification('Failed to start run: ' + err.message, 'error');
    })
    .finally(function() {
        if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = 'RUN AI BUILDER'; }
    });
}

// Event delegation for approve/reject buttons
document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-url]');
    if (!btn) return;
    var url = btn.dataset.url;
    var outputDir = btn.dataset.outputDir || '';
    var jobId = btn.dataset.jobId || '';
    var isApprove = url.indexOf('/approve') !== -1;
    btn.disabled = true;
    btn.textContent = isApprove ? '⏳ APPROVING...' : '⏳ REJECTING...';
    fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project_output_dir: outputDir})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (isApprove && data.status === 'approved') {
            showNotification('Tool approved! The agent will continue shortly.', 'info');
            clearPendingApprovalState();
        } else if (!isApprove && data.status === 'rejected') {
            showNotification('Tool rejected. The agent will choose a different approach.', 'info');
            clearPendingApprovalState();
        } else {
            showNotification('Failed: ' + (data.error || 'Unknown error', 'info'));
        }
        fetchState();
    })
    .catch(function(err) { console.error('Failed:', err); showNotification('Failed to process tool action.', 'info'); })
    .finally(function() {
        btn.disabled = false;
        btn.textContent = isApprove ? '✅ APPROVE' : '❌ REJECT';
    });
});

// Event delegation for bash tool delete buttons
document.addEventListener('click', function(e) {
    var delBtn = e.target.closest('[data-delete-bash-tool]');
    if (!delBtn) return;
    var pid = delBtn.dataset.projectId;
    var toolName = delBtn.dataset.toolName;
    if (pid && toolName) deleteBashTool(pid, toolName);
});

function clearPendingApprovalState() {
    var actions = document.getElementById('pending-approval-actions');
    if (actions) actions.innerHTML = '<div style="color:var(--success);font-size:12px;">✅ Tool action processed. The agent will resume automatically.</div>';
    var statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'AGENT RUNNING'; statusText.style.color = ''; statusText.style.fontWeight = ''; }
}

function stopProject(projectId) {
    fetch('/api/queue/running/stop', { method: 'POST' }).catch(function() {});
    fetch('/api/projects/' + projectId + '/stop', { method: 'POST' }).catch(function() {});
    fetchState();
}

function resetRunButtons() {
    var runBtn = document.getElementById('details-run-btn');
    var stopBtn = document.getElementById('details-stop-btn');
    if (runBtn) {
        runBtn.disabled = false;
        runBtn.innerHTML = 'RUN AI BUILDER';
    }
    if (stopBtn) stopBtn.style.display = 'none';
}

function selectProject(projectId) {
    resetRunButtons();
    currentProjectId = projectId;
    document.getElementById('projects-panel').classList.remove('active');
    document.getElementById('project-details-panel').classList.add('active');
    window.scrollTo(0, 0);
    
    // Get project from state or fetch
    var project = (_uiState.projects || []).find(function(p) { return p.id === projectId; });
    if (!project) {
        fetch('/api/projects/' + projectId)
            .then(function(r) { return r.json(); })
            .then(function(proj) {
                _populateProjectForm(proj);
            })
            .catch(function(err) { console.error('Failed to load project details:', err); });
    } else {
        _populateProjectForm(project);
    }
}

function _populateProjectForm(project) {
    var safeSet = function(id, val) { var el = document.getElementById(id); if (el) el.value = val; };
    safeSet('run-project-id', project.id);
    var nameEl = document.getElementById('details-project-name');
    if (nameEl) {
        nameEl.textContent = project.name || 'Untitled';
        if (project.run_number > 0) {
            var runSpan = document.createElement('span');
            runSpan.style.cssText = 'font-size:12px;color:var(--text-muted);';
            runSpan.textContent = '(Run #' + project.run_number + ')';
            nameEl.appendChild(document.createTextNode(' '));
            nameEl.appendChild(runSpan);
        }
    }
    safeSet('details-project-name-form', project.name || '');
    safeSet('details-root-dir', project.rootDirectory || '');
    safeSet('details-instructions', project.instructions || '');
    fetch('/api/projects/' + project.id + '/tools')
        .then(function(r) { return r.json(); })
        .then(function(toolData) {
            buildToolSelector(toolData.disabled_tools || [], toolData.custom_tools || []);
        })
        .catch(function(err) {
            console.error('Failed to load project tools:', err);
            buildToolSelector(project.disabled_tools || [], []);
        });
    loadBashTools(project.id);
    // Check for running job
    var activeJob = (_uiState.active_jobs || {})[project.id];
    var liveBtn = document.getElementById('details-live-btn');
    var stopBtn = document.getElementById('details-stop-btn');
    if (activeJob) {
        if (liveBtn) liveBtn.style.display = 'inline-block';
        if (stopBtn) stopBtn.style.display = 'inline-block';
    } else {
        // Always show VIEW button even when idle (shows last completed run)
        if (liveBtn) liveBtn.style.display = 'inline-block';
        if (stopBtn) stopBtn.style.display = 'none';
    }
}

function goBackToProjects() {
    saveProjectChanges().finally(function() {
        _goBackToProjects();
    });
}

function _goBackToProjects() {
    _activeJobId = null;
    _liveViewPrevStepCount = 0;
    document.getElementById('project-details-panel').classList.remove('active');
    document.getElementById('projects-panel').classList.add('active');
    fetchState();
}

function resetProject(projectId) {
    if (!confirm('Reset project "' + projectId + '"? This will clear all run history and output.')) return;
    fetch('/api/projects/' + projectId + '/reset', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'reset') { fetchState(); showNotification('Project reset successfully!', 'info'); }
            else showNotification('Failed to reset project: ' + (data.error || 'Unknown error'), 'info');
        })
        .catch(function(err) { console.error('Failed to reset project:', err); showNotification('Failed to reset project.', 'info'); });
}

function deleteProject(projectId) {
    if (!confirm('Are you sure you want to delete this project?')) return;
    fetch('/api/projects/' + projectId, { method: 'DELETE' })
        .then(function() { fetchState(); })
        .catch(function(err) { console.error('Failed to delete project:', err); });
}

function archiveProject(projectId, isArchived, btnEl) {
    var endpoint = isArchived ? 'unarchive' : 'archive';
    fetch('/api/projects/' + projectId + '/' + endpoint, { method: 'POST' })
        .then(function() { fetchState(); })
        .catch(function(err) { console.error('Failed to ' + endpoint + ' project:', err); });
}

function toggleArchived() {
    _showArchived = !_showArchived;
    var btn = document.getElementById('show-archived-btn');
    if (btn) btn.textContent = _showArchived ? 'HIDE ARCHIVED' : 'SHOW ARCHIVED';
    fetchState();
}

function autoSaveProject() {
    saveProjectChanges();
}

function saveProjectChanges() {
    var projectId = document.getElementById('run-project-id') ? document.getElementById('run-project-id').value : null;
    if (!projectId) return Promise.resolve();
    var formData = new FormData(document.getElementById('project-details-form'));
    var unchecked = document.querySelectorAll('#details-tool-selector input[type="checkbox"]:not(:checked)');
    var disabledTools = [];
    unchecked.forEach(function(cb) { disabledTools.push(cb.value); });
    // Save disabled_tools
    fetch('/api/projects/' + projectId + '/tools', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({disabled_tools: disabledTools})
    }).catch(function(err) { console.error('Failed to save project tools:', err); });
    // Save other fields
    return fetch('/api/projects/' + projectId, { method: 'POST', body: formData })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.status === 'saved') fetchState();
            return data;
        })
        .catch(function(err) { console.error('Failed to save project:', err); throw err; });
}

// === Tool Selector ===
function buildToolSelector(disabledTools, customTools) {
    buildToolSelectorForElement('details-tool-selector', disabledTools, customTools);
}
function buildToolSelectorForElement(elementId, disabledTools, customTools) {
    customTools = customTools || [];
    var container = document.getElementById(elementId);
    if (!container) return;
    var html = '';
    html += '<div style="margin-bottom:12px;">';
    html += '<div style="font-size:11px;font-weight:bold;color:var(--text-muted);margin-bottom:4px;">BUILT-IN TOOLS</div>';
    html += '<div class="tool-selector-grid">';
    var tools = (AVAILABLE_TOOLS && AVAILABLE_TOOLS.length > 0) ? AVAILABLE_TOOLS.slice().sort() : [];
    if (tools.length === 0) {
        html += '<div style="color:var(--text-muted);font-size:11px;padding:4px 0;">Loading tools...</div>';
    }
    tools.forEach(function(toolName) {
        var isChecked = disabledTools && disabledTools.indexOf(toolName) === -1;
        html += '<label class="tool-checkbox" style="display:flex;align-items:center;gap:6px;font-size:12px;padding:4px 8px;background:var(--muted);border-radius:4px;cursor:pointer;min-width:0;">' +
            '<input type="checkbox" class="tool-cb" data-toolname="' + escapeHtml(toolName) + '" value="' + toolName + '" ' + (isChecked ? 'checked' : '') + '>' +
            '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;">' + escapeHtml(toolName) + '</span></label>';
    });
    html += '</div></div>';
    if (customTools && customTools.length > 0) {
        html += '<div style="margin-bottom:12px;">';
        html += '<div style="font-size:11px;font-weight:bold;color:var(--text-muted);margin-bottom:4px;">CUSTOM TOOLS (project-local)</div>';
        html += '<div class="tool-selector-grid">';
        customTools.forEach(function(toolName) {
            var isChecked = disabledTools && disabledTools.indexOf(toolName) === -1;
            html += '<label class="tool-checkbox" style="display:flex;align-items:center;gap:6px;font-size:12px;padding:4px 8px;background:var(--muted);border-radius:4px;cursor:pointer;min-width:0;">' +
                '<input type="checkbox" class="tool-cb" data-toolname="' + escapeHtml(toolName) + '" value="' + toolName + '" ' + (isChecked ? 'checked' : '') + '>' +
                '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;">' + escapeHtml(toolName) + '</span> <span style="font-size:10px;color:var(--text-muted);white-space:nowrap;">(custom)</span></label>';
        });
        html += '</div></div>';
    }
    html += '<div style="color:var(--text-muted);font-size:11px;padding:4px 0;">Checked = enabled. Uncheck to disable.</div>';
    container.innerHTML = html;
}

function getEnabledTools() {
    return (AVAILABLE_TOOLS && AVAILABLE_TOOLS.length > 0) ? AVAILABLE_TOOLS.slice() : [];
}

// === Chat ===
function loadChats() {
    // Reload state from the consolidated endpoint first
    fetchState().then(function() {
        fetch('/api/chats')
            .then(function(r) { return r.json(); })
            .then(function(chats) {
                var list = document.getElementById('chat-list');
                if (!list) return;
                list.innerHTML = '';
                if (!chats.length) { list.innerHTML = '<div class="note">NO CHATS FOUND.</div>'; return; }
                chats.forEach(function(chat) {
                    var item = document.createElement('div');
                    item.className = 'chat-item';
                    var nameSpan = document.createElement('span');
                    nameSpan.className = 'chat-item-name';
                    nameSpan.textContent = chat.title || 'New Chat';
                    item.appendChild(nameSpan);
                    item.onclick = function() { openChat(chat.id); };
                    list.appendChild(item);
                });
            })
            .catch(function(err) { console.error('Failed to load chats:', err); });
    });
}

function newChat() {
    showTab('chat');
    fetch('/api/chats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ timestamp: new Date().toISOString() }) })
        .then(function(r) { return r.json(); })
        .then(function(data) { loadChats(); openChat(data.id); })
        .catch(function(err) { console.error('Failed to create chat:', err); });
}

function openChat(id) {
    chatId = id;
    fetch('/api/chats/' + id)
        .then(function(r) { return r.json(); })
        .then(function(chat) {
            var log = document.getElementById('chat-log');
            var controls = document.getElementById('chat-controls-container');
            var input = document.getElementById('chat-input');
            var sendBtn = document.getElementById('send-chat-btn');
            if (log) {
                log.style.display = 'block';
                log.innerHTML = '';
                chat.messages.forEach(function(msg) {
                    var div = document.createElement('div');
                    div.className = 'chat-msg ' + (msg.role === 'user' ? 'user' : 'ai');
                    var roleLabel = msg.role === 'user' ? 'YOU' : 'AI';
                    var bodyDiv = document.createElement('div');
                    bodyDiv.className = 'chat-msg-body';
                    bodyDiv.innerHTML = markdownToHtml(msg.content);
                    var headerDiv = document.createElement('div');
                    headerDiv.className = 'chat-msg-header';
                    var roleSpan = document.createElement('span');
                    roleSpan.className = 'chat-msg-role';
                    roleSpan.textContent = roleLabel;
                    headerDiv.appendChild(roleSpan);
                    div.appendChild(headerDiv);
                    div.appendChild(bodyDiv);
                    var copyBtn = document.createElement('button');
                    copyBtn.className = 'copy-btn';
                    copyBtn.textContent = 'COPY';
                    copyBtn.onclick = function(e) { e.stopPropagation(); copyToClipboard(getChatMessageText(div), copyBtn); };
                    var bodyWrapper = document.createElement('div');
                    bodyWrapper.style.position = 'relative';
                    bodyWrapper.appendChild(bodyDiv);
                    bodyWrapper.appendChild(copyBtn);
                    div.appendChild(bodyWrapper);
                    log.appendChild(div);
                });
                log.scrollTop = log.scrollHeight;
            }
            var chatView = document.getElementById('chat-view');
            if (chatView) chatView.style.display = 'flex';
            if (controls) controls.style.display = 'flex';
            if (input) input.disabled = false;
            if (sendBtn) sendBtn.disabled = false;
            loadChats();
        })
        .catch(function(err) { console.error('Failed to load chat:', err); });
}

function sendChat() {
    var input = document.getElementById('chat-input');
    var content = input.value.trim();
    if (!content) return;
    var log = document.getElementById('chat-log');
    var sendBtn = document.getElementById('send-chat-btn');
    sendBtn.disabled = true;
    input.disabled = true;
    var userDiv = document.createElement('div');
    userDiv.className = 'chat-msg user';
    var userBody = document.createElement('div');
    userBody.className = 'chat-msg-body';
    userBody.innerHTML = markdownToHtml(content);
    var userHeader = document.createElement('div');
    userHeader.className = 'chat-msg-header';
    var userRole = document.createElement('span');
    userRole.className = 'chat-msg-role';
    userRole.textContent = 'YOU';
    userHeader.appendChild(userRole);
    userDiv.appendChild(userHeader);
    var userCopyBtn = document.createElement('button');
    userCopyBtn.className = 'copy-btn';
    userCopyBtn.textContent = 'COPY';
    userCopyBtn.onclick = function(e) { e.stopPropagation(); copyToClipboard(getChatMessageText(userDiv), userCopyBtn); };
    var userBodyWrapper = document.createElement('div');
    userBodyWrapper.style.position = 'relative';
    userBodyWrapper.appendChild(userBody);
    userBodyWrapper.appendChild(userCopyBtn);
    userDiv.appendChild(userBodyWrapper);
    log.appendChild(userDiv);
    input.value = '';
    log.scrollTop = log.scrollHeight;
    var aiDiv = document.createElement('div');
    aiDiv.className = 'chat-msg ai';
    var aiHeader = document.createElement('div');
    aiHeader.className = 'chat-msg-header';
    var aiRole = document.createElement('span');
    aiRole.className = 'chat-msg-role';
    aiRole.textContent = 'AI';
    aiHeader.appendChild(aiRole);
    aiDiv.appendChild(aiHeader);
    var aiBodyDiv = document.createElement('div');
    aiBodyDiv.className = 'chat-msg-body';
    aiBodyDiv.id = 'chat-stream-text-' + Date.now();
    aiDiv.appendChild(aiBodyDiv);
    var aiCopyBtn = document.createElement('button');
    aiCopyBtn.className = 'copy-btn';
    aiCopyBtn.textContent = 'COPY';
    aiCopyBtn.onclick = function(e) { e.stopPropagation(); copyToClipboard(getChatMessageText(aiDiv), aiCopyBtn); };
    var aiBodyWrapper = document.createElement('div');
    aiBodyWrapper.style.position = 'relative';
    aiBodyWrapper.appendChild(aiBodyDiv);
    aiBodyWrapper.appendChild(aiCopyBtn);
    aiDiv.appendChild(aiBodyWrapper);
    log.appendChild(aiDiv);
    log.scrollTop = log.scrollHeight;
    fetch('/api/chats/' + chatId + '/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: content })
    })
    .then(function(response) {
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';
        function read() {
            reader.read().then(function(result) {
                var done = result.done;
                var value = result.value;
                if (done) { sendBtn.disabled = false; input.disabled = false; log.scrollTop = log.scrollHeight; loadChats(); return; }
                buffer += decoder.decode(value, { stream: true });
                if (aiBodyDiv) aiBodyDiv.innerHTML = markdownToHtml(buffer);
                log.scrollTop = log.scrollHeight;
                setTimeout(read, 0);
            });
        }
        read();
    })
    .catch(function(err) { console.error('Chat error:', err); sendBtn.disabled = false; input.disabled = false; });
}

// Chat enter key handler
document.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        var chatInput = document.getElementById('chat-input');
        if (chatInput && document.activeElement === chatInput) {
            e.preventDefault();
            sendChat();
        }
    }
});

// === Settings ===
function loadSettingsUI() {
    var settings = _uiState.settings || {};
    var set = function(id, val) { var el = document.getElementById(id); if (el) el.value = val; };
    set('set-custom-endpoint-url', settings.custom_endpoint_url || '');
    set('set-custom-api-key', settings.custom_api_key || '');
    set('set-custom-model-name', settings.custom_model_name || '');
    var sslEl = document.getElementById('set-custom-verify-ssl');
    if (sslEl) sslEl.checked = settings.custom_verify_ssl;
    set('set-max-steps', settings.max_steps || '50');
    set('set-timeout', settings.timeout || '3600');
    set('set-max-context-tokens', settings.max_context_tokens || '0');
    set('set-max-output-tokens', settings.max_output_tokens || '0');
    set('set-max-tool-result-length', settings.max_tool_result_length || '10000');
    set('set-root-dir', settings.root_directory || '');
    set('set-jd-cli', settings.jd_cli_path || '');
    set('set-java-home', settings.java_home || '');
    set('set-dotnet-cli', settings.dotnet_cli_path || '');
    set('set-shared-tools-dir', settings.shared_tools_dir || '');
}

function reloadSettingsFromDisk() {
    fetch('/api/settings/reload', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'reloaded') { fetchState(); showNotification('Settings reloaded from disk!', 'info'); }
            else showNotification('Failed to reload settings: ' + (data.error || 'Unknown error'), 'info');
        })
        .catch(function(err) { console.error('Failed to reload settings:', err); showNotification('Failed to reload settings.', 'info'); });
}

function saveSettings() {
    var settings = {
        root_directory: document.getElementById('set-root-dir').value,
        jd_cli_path: document.getElementById('set-jd-cli').value,
        java_home: document.getElementById('set-java-home').value,
        dotnet_cli_path: document.getElementById('set-dotnet-cli').value,
        custom_endpoint_url: document.getElementById('set-custom-endpoint-url').value,
        custom_api_key: document.getElementById('set-custom-api-key').value,
        custom_model_name: document.getElementById('set-custom-model-name').value,
        custom_verify_ssl: document.getElementById('set-custom-verify-ssl').checked,
        max_steps: document.getElementById('set-max-steps').value,
        timeout: document.getElementById('set-timeout').value,
        max_context_tokens: document.getElementById('set-max-context-tokens').value,
        max_output_tokens: document.getElementById('set-max-output-tokens').value,
        max_tool_result_length: document.getElementById('set-max-tool-result-length').value,
        shared_tools_dir: document.getElementById('set-shared-tools-dir').value,
    };
    fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings) })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'saved') { fetchState(); showNotification('Settings saved! Changes will apply on next run.', 'info'); }
            else showNotification('Failed to save settings: ' + (data.error || 'Unknown error'), 'info');
        })
        .catch(function(err) { console.error('Failed to save settings:', err); showNotification('Failed to save settings.', 'info'); });
}

function closeActionsModal() { document.getElementById('actions-modal').style.display = 'none'; }

function confirmRootPathChangeProceed() {
    document.getElementById('root-path-confirmation-modal').style.display = 'none';
    autoSaveProject();
}

function cancelRootPathChange() {
    document.getElementById('root-path-confirmation-modal').style.display = 'none';
    var el = document.getElementById(pendingRootPathElementId);
    if (el) el.blur();
}

function showNotification(message, type) {
    showNotificationModal(message, type);
}

// === Notification Modal System ===
let _notificationResolve = null;

function showNotificationModal(message, type) {
    type = type || 'info';
    var icons = { info: '💬', success: '✅', warning: '⚠️', error: '❌' };
    var iconEl = document.getElementById('notification-icon');
    var titleEl = document.getElementById('notification-title');
    var bodyEl = document.getElementById('notification-body');
    var modal = document.getElementById('notification-modal');
    if (!modal) return;
    iconEl.textContent = icons[type] || icons.info;
    iconEl.className = 'notification-icon ' + type;
    var titles = { info: 'NOTICE', success: 'SUCCESS', warning: 'WARNING', error: 'ERROR' };
    titleEl.textContent = titles[type] || titles.info;
    bodyEl.textContent = message;
    modal.style.display = 'flex';
}

function showNotificationModalDetailed(title, bodyHtml, type) {
    var icons = { info: '💬', success: '✅', warning: '⚠️', error: '❌' };
    var iconEl = document.getElementById('notification-icon');
    var titleEl = document.getElementById('notification-title');
    var bodyEl = document.getElementById('notification-body');
    var modal = document.getElementById('notification-modal');
    if (!modal) return;
    iconEl.textContent = icons[type] || icons.info;
    iconEl.className = 'notification-icon ' + type;
    titleEl.textContent = title || 'NOTICE';
    bodyEl.innerHTML = bodyHtml;
    modal.style.display = 'flex';
}

function closeNotificationModal() {
    var modal = document.getElementById('notification-modal');
    if (modal) modal.style.display = 'none';
    if (_notificationResolve) {
        _notificationResolve();
        _notificationResolve = null;
    }
}

function showNotificationModalPromise(message, type) {
    return new Promise(function(resolve) {
        showNotificationModal(message, type);
        _notificationResolve = resolve;
    });
}

async function showNotificationAndWait(message, type) {
    return await showNotificationModalPromise(message, type);
}

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        var notifModal = document.getElementById('notification-modal');
        if (notifModal && notifModal.style.display === 'flex') closeNotificationModal();
    }
});

// === Live View Functions ===
// Note: showLiveView / showLiveViewForJob / _doShowLiveView / refreshLiveView removed — VIEW now opens in a new tab

// === Bash Tool Management ===
function toggleBashToolForm() {
    var container = document.getElementById('bash-tool-form-container');
    if (!container) return;
    var isVisible = container.style.display === 'block';
    container.style.display = isVisible ? 'none' : 'block';
    if (!isVisible) {
        var nameEl = document.getElementById('bash-tool-name');
        var descEl = document.getElementById('bash-tool-desc');
        var scriptEl = document.getElementById('bash-tool-script');
        if (nameEl) nameEl.value = '';
        if (descEl) descEl.value = '';
        if (scriptEl) scriptEl.value = '';
        container.removeAttribute('data-editing');
        container.removeAttribute('data-edit-name');
        var createBtn = container.querySelector('.btn-success');
        if (createBtn) {
            createBtn.textContent = 'CREATE';
            createBtn.onclick = function() { createBashTool(); };
        }
    }
}

function loadBashTools(pid) {
    if (!pid) return;
    fetch('/api/projects/' + pid + '/bash-tools')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var list = document.getElementById('bash-tools-list');
            if (!list) return;
            var tools = data.bash_tools || [];
            if (tools.length === 0) {
                list.innerHTML = '<div style="color:var(--text-muted); font-size:12px; padding:8px;">No bash tools yet. Click "+ NEW BASH TOOL" to create one.</div>';
                return;
            }
            list.innerHTML = '';
            tools.forEach(function(tool) {
                var toolEl = document.createElement('div');
                toolEl.style.cssText = 'background:var(--bg-primary); padding:10px; border-radius:6px; margin-bottom:8px; border:1px solid var(--border);';
                var headerEl = document.createElement('div');
                headerEl.style.cssText = 'display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;';
                var nameEl = document.createElement('span');
                nameEl.style.cssText = 'font-weight:bold; font-size:13px;';
                nameEl.textContent = '⚡ ' + tool.name;
                var actionsEl = document.createElement('div');
                actionsEl.style.cssText = 'display:flex; gap:4px;';
                var editBtn = document.createElement('button');
                editBtn.className = 'btn btn-xs btn-secondary';
                editBtn.textContent = 'EDIT';
                editBtn.style.cssText = 'font-size:10px;';
                editBtn.onclick = function(e) { e.stopPropagation(); editBashTool(pid, tool); };
                var delBtn = document.createElement('button');
                delBtn.className = 'btn btn-xs btn-danger';
                delBtn.textContent = 'DELETE';
                delBtn.style.cssText = 'font-size:10px;';
                delBtn.dataset.deleteBashTool = 'true';
                delBtn.dataset.projectId = pid;
                delBtn.dataset.toolName = tool.name;
                actionsEl.appendChild(editBtn);
                actionsEl.appendChild(delBtn);
                headerEl.appendChild(nameEl);
                headerEl.appendChild(actionsEl);
                toolEl.appendChild(headerEl);
                if (tool.description) {
                    var descEl = document.createElement('div');
                    descEl.style.cssText = 'color:var(--text-muted); font-size:11px; margin-bottom:4px;';
                    descEl.textContent = tool.description;
                    toolEl.appendChild(descEl);
                }
                list.appendChild(toolEl);
            });
        })
        .catch(function(err) {
            console.error('Failed to load bash tools:', err);
            var list = document.getElementById('bash-tools-list');
            if (list) list.innerHTML = '<div style="color:var(--danger); font-size:12px;">Failed to load bash tools.</div>';
        });
}

function createBashTool() {
    var name = document.getElementById('bash-tool-name').value.trim();
    var desc = document.getElementById('bash-tool-desc').value.trim();
    var script = document.getElementById('bash-tool-script').value.trim();
    if (!name) { showNotification('Tool name is required', 'warning'); return; }
    if (!desc) { showNotification('Description is required', 'warning'); return; }
    if (!script) { showNotification('Script body is required', 'warning'); return; }
    var pid = document.getElementById('run-project-id') ? document.getElementById('run-project-id').value : null;
    if (!pid) { showNotification('No project selected', 'warning'); return; }
    fetch('/api/projects/' + pid + '/bash-tools', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name, description: desc, script_content: script})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'created') {
            showNotification('Bash tool "' + name + '" created!', 'success');
            toggleBashToolForm();
            loadBashTools(pid);
            fetchState();
        } else {
            showNotification('Failed: ' + (data.error || 'Unknown error'), 'error');
        }
    })
    .catch(function(err) {
        console.error('Failed to create bash tool:', err);
        showNotification('Failed to create bash tool.', 'error');
    });
}

function editBashTool(pid, tool) {
    var container = document.getElementById('bash-tool-form-container');
    if (!container) return;
    container.setAttribute('data-editing', 'true');
    container.setAttribute('data-edit-name', tool.name);
    var nameEl = document.getElementById('bash-tool-name');
    var descEl = document.getElementById('bash-tool-desc');
    var scriptEl = document.getElementById('bash-tool-script');
    if (nameEl) nameEl.value = tool.name;
    if (descEl) descEl.value = tool.description;
    if (scriptEl) scriptEl.value = tool.source || '';
    var createBtn = container.querySelector('.btn-success');
    if (createBtn) {
        createBtn.textContent = 'UPDATE';
        createBtn.onclick = function() { updateBashTool(pid, tool.name); };
    }
    container.style.display = 'block';
}

function updateBashTool(pid, oldName) {
    var desc = document.getElementById('bash-tool-desc').value.trim();
    var script = document.getElementById('bash-tool-script').value.trim();
    if (!desc) { showNotification('Description is required', 'warning'); return; }
    if (!script) { showNotification('Script body is required', 'warning'); return; }
    fetch('/api/projects/' + pid + '/bash-tools/' + encodeURIComponent(oldName), {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({description: desc, script_content: script})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'updated') {
            showNotification('Bash tool "' + oldName + '" updated!', 'success');
            toggleBashToolForm();
            loadBashTools(pid);
            fetchState();
        } else {
            showNotification('Failed: ' + (data.error || 'Unknown error'), 'error');
        }
    })
    .catch(function(err) {
        console.error('Failed to update bash tool:', err);
        showNotification('Failed to update bash tool.', 'error');
    });
}

function deleteBashTool(pid, toolName) {
    if (!confirm('Delete bash tool "' + toolName + '"?')) return;
    fetch('/api/projects/' + pid + '/bash-tools/' + encodeURIComponent(toolName), {
        method: 'DELETE'
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'deleted') {
            showNotification('Bash tool "' + toolName + '" deleted.', 'success');
            loadBashTools(pid);
            fetchState();
        } else {
            showNotification('Failed: ' + (data.error || 'Unknown error'), 'error');
        }
    })
    .catch(function(err) {
        console.error('Failed to delete bash tool:', err);
        showNotification('Failed to delete bash tool.', 'error');
    });
}

// === Open View in New Tab ===
function openViewInNewTab(projectId, jobId) {
    var url = '/view/' + projectId + (jobId ? '?job=' + jobId : '');
    window.open(url, '_blank');
}

// === Open View for current project (checks active job first) ===
function openViewInNewTabForCurrentProject() {
    var activeJobs = _uiState.active_jobs || {};
    var activeJob = activeJobs[currentProjectId];
    var activeJobId = activeJob ? activeJob.job_id : null;
    openViewInNewTab(currentProjectId, activeJobId);
}

// === Utility Functions ===
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function copyToClipboard(text, buttonEl) {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() {
            if (buttonEl) {
                var original = buttonEl.textContent;
                buttonEl.textContent = 'COPIED!';
                setTimeout(function() { buttonEl.textContent = original; }, 1500);
            }
        }).catch(function(err) { console.error('Copy failed:', err); });
    } else {
        var textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            if (buttonEl) {
                var original = buttonEl.textContent;
                buttonEl.textContent = 'COPIED!';
                setTimeout(function() { buttonEl.textContent = original; }, 1500);
            }
        } catch (e) { console.error('Copy failed:', e); }
        document.body.removeChild(textarea);
    }
}

function getChatMessageText(msgElement) {
    var body = msgElement.querySelector('.chat-msg-body');
    if (!body) return '';
    return body.textContent || '';
}

function markdownToHtml(md) {
    if (!md) return '';
    var html = md;
    var codeBlocks = [];
    html = html.replace(/```([\s\S]*?)```/g, function(match, code) {
        var uniqueId = 'code-block-' + Math.random().toString(36).substr(2, 9);
        codeBlocks.push({ id: uniqueId, content: code.trim() });
        return '%%CODEBLOCK_' + uniqueId + '%%';
    });
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\b\*(.+?)\*\b/g, '<em>$1</em>');
    html = html.replace(/^- (.+)$/gm, '<div style="margin-left:12px;">• $1</div>');
    html = html.replace(/\n\n/g, '<br><br>');
    html = html.replace(/\n/g, '<br>');
    codeBlocks.forEach(function(block) {
        var escaped = block.content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        var btnStyle = 'position:absolute;bottom:4px;right:4px;background:var(--wood);border:1px solid #000;padding:3px 8px;cursor:pointer;font-size:8px;color:#fff;z-index:10;border-radius:3px;font-family:\'Press Start 2P\',monospace;';
        html = html.replace('%%CODEBLOCK_' + block.id + '%%',
            '<div class="code-block-wrapper" data-code-id="' + block.id + '" style="position:relative;margin:4px 0;"><button class="pre-copy-btn" style="' + btnStyle + '">COPY</button><pre style="background:#111;padding:8px;border-radius:4px;overflow-x:auto;margin:0;"><code id="' + block.id + '" style="white-space:pre-wrap;">' + escaped + '</code></pre></div>');
    });
    return html;
}

// Event delegation for code block copy buttons
document.addEventListener('click', function(e) {
    var btn = e.target.closest('.pre-copy-btn');
    if (!btn) return;
    var wrapper = btn.closest('.code-block-wrapper');
    if (!wrapper) return;
    var codeId = wrapper.getAttribute('data-code-id');
    var el = document.getElementById(codeId);
    if (!el) return;
    var text = el.textContent || el.innerText || '';
    var decoded = text.replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
    var firstLineEnd = decoded.indexOf('\n');
    if (firstLineEnd !== -1) {
        decoded = decoded.substring(firstLineEnd + 1);
    }
    copyToClipboard(decoded, btn);
});

// === DOM Ready — Initialize UI ===
document.addEventListener('DOMContentLoaded', function() {
    // Fade out loading screen after 2.5s
    var loadingScreen = document.getElementById('loading-screen');
    if (loadingScreen) {
        setTimeout(function() {
            loadingScreen.classList.add('fade-out');
            setTimeout(function() { loadingScreen.style.display = 'none'; }, 600);
        }, 2500);
    }

    // Tab navigation
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var tabName = this.getAttribute('data-tab');
            showTab(tabName);
        });
    });

    // Project form submit
    var form = document.getElementById('add-project-form');
    if (form) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var formData = new FormData(this);
            var checkboxes = document.querySelectorAll('#add-tool-selector input[type="checkbox"]');
            var disabledTools = [];
            checkboxes.forEach(function(cb) {
                if (!cb.checked) {
                    disabledTools.push(cb.value);
                }
            });
            var formRef = this;
            fetch('/api/projects', { method: 'POST', body: formData })
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    if (data.error) { showNotification('Error: ' + data.error, 'error'); }
                    else {
                        var pid = data.id;
                        if (pid && disabledTools.length > 0) {
                            fetch('/api/projects/' + pid + '/tools', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({disabled_tools: disabledTools})
                            }).catch(function(err) { console.error('Failed to save disabled tools:', err); });
                        }
                        fetchState();
                        formRef.reset();
                        toggleCreateForm();
                    }
                })
                .catch(function(err) { console.error('Failed to create project:', err); });
        });
    }

    // Keyboard navigation for sidebar
    var sidebarNav = document.querySelector('.sidebar-nav');
    if (sidebarNav) {
        sidebarNav.addEventListener('keydown', function(e) {
            var buttons = Array.from(sidebarNav.querySelectorAll('.tab-btn'));
            var current = document.activeElement;
            var idx = buttons.indexOf(current);
            if (idx === -1) return;
            var nextIdx;
            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); nextIdx = (idx + 1) % buttons.length; }
            else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); nextIdx = (idx - 1 + buttons.length) % buttons.length; }
            else if (e.key === 'Home') { e.preventDefault(); nextIdx = 0; }
            else if (e.key === 'End') { e.preventDefault(); nextIdx = buttons.length - 1; }
            else return;
            buttons[nextIdx].focus();
            buttons[nextIdx].click();
        });
    }

    // Close modals on Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            var actionsModal = document.getElementById('actions-modal');
            var rootModal = document.getElementById('root-path-confirmation-modal');
            if (actionsModal && actionsModal.style.display === 'flex') closeActionsModal();
            if (rootModal && rootModal.style.display === 'flex') cancelRootPathChange();
        }
    });

    // Trap focus in modals
    document.querySelectorAll('.modal').forEach(function(modal) {
        modal.addEventListener('keydown', function(e) {
            if (e.key !== 'Tab') return;
            var focusable = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
            if (!focusable.length) return;
            var first = focusable[0];
            var last = focusable[focusable.length - 1];
            if (e.shiftKey) { if (document.activeElement === first) { e.preventDefault(); last.focus(); } }
            else { if (document.activeElement === last) { e.preventDefault(); first.focus(); } }
        });
    });

    // === INIT: Load everything from backend ===
    initUI();
});
