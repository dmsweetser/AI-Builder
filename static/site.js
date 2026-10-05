// === Global State ===
let currentProjectId = localStorage.getItem('currentProjectId') || null;
let currentChatId = localStorage.getItem('currentChatId') || null;
let fileTreePage = 0;
let fileTreeTotal = 0;
let fileTreeSearch = '';
let fileTreePath = '';
let detailsFileTreePage = 0;
let detailsFileTreeTotal = 0;
let detailsFileTreeSearch = '';
let detailsFileTreePath = '';
let sortMode = 'name';
let detailsSortMode = 'name';
let filterTreeTimeout = null;
let detailsFilterTreeTimeout = null;
let autoSaveTimeout = null;
let pendingRootPathChange = null;
let pendingRootPathElementId = null;
let showArchived = false;

// === Live Agent State ===
let currentRunningJobId = null;
let agentSSEController = null;
let agentRunning = false;
let liveInjectActive = false;

// === Available tools for agent mode ===
const AVAILABLE_TOOLS = [
    "list_directory", "search_files", "grep_code", "read_file",
    "write_file", "edit_file", "delete_file", "find_symbol",
    "decompile_jar", "list_dependencies", "check_syntax", "get_file_info"
];

// === Tab Management ===
function showTab(tabName) {
    document.querySelectorAll('.panel').forEach(p => {
        p.classList.remove('active');
        p.classList.add('hidden');
    });
    document.querySelectorAll('.sidebar-nav .tab-btn').forEach(b => b.classList.remove('active'));
    const panel = document.getElementById(tabName + '-panel');
    if (panel) {
        panel.classList.remove('hidden');
        panel.classList.add('active');
    }
    document.querySelectorAll('.sidebar-nav .tab-btn').forEach(b => {
        if (b.textContent.trim().toUpperCase() === tabName.toUpperCase()) {
            b.classList.add('active');
        }
    });
    if (tabName === 'jobs') loadJobs();
    if (tabName === 'settings') loadSettingsUI();
}

// === Utility ===
function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// === Mode handling for add form ===
function onAddModeChange() {
    const mode = document.getElementById('add-project-mode').value;
    const fileSelector = document.getElementById('add-file-selector');
    if (fileSelector) fileSelector.style.display = mode === 'agentic' ? 'none' : 'block';
}

function onDetailsModeChange() {
    const mode = document.getElementById('details-mode').value;
    const fileSelector = document.getElementById('details-file-selector');
    const agentSettings = document.getElementById('details-agent-settings');
    const modeBadge = document.getElementById('details-mode-badge');
    if (fileSelector) fileSelector.style.display = mode === 'agentic' ? 'none' : 'block';
    if (agentSettings) agentSettings.style.display = mode === 'agentic' ? 'block' : 'none';
    if (modeBadge) {
        modeBadge.className = `mode-indicator ${mode === 'agentic' ? 'agentic' : 'oneshot'}`;
        modeBadge.textContent = mode === 'agentic' ? 'AGENTIC' : 'ONE-SHOT';
    }
    autoSaveProject();
}

// === Tool selector ===
function buildToolSelector(enabledTools) {
    const container = document.getElementById('details-tool-selector');
    if (!container) return;
    container.innerHTML = '';
    AVAILABLE_TOOLS.forEach(tool => {
        const checked = enabledTools.includes(tool) || enabledTools.length === 0;
        const label = document.createElement('label');
        label.className = 'tool-checkbox';
        label.innerHTML = `<input type="checkbox" name="tool_${tool}" ${checked ? 'checked' : ''}> ${tool}`;
        container.appendChild(label);
    });
}

function getEnabledTools() {
    const checkboxes = document.querySelectorAll('#details-tool-selector input[type="checkbox"]');
    const enabled = [];
    checkboxes.forEach(cb => {
        if (cb.checked) enabled.push(cb.name.replace('tool_', ''));
    });
    return enabled;
}

// === Live instruction injection ===
function injectLiveInstruction() {
    if (!liveInjectActive) return;
    const input = document.getElementById('live-inject-input');
    if (!input || !input.value.trim()) return;
    const instruction = input.value.trim();
    fetch('/api/agent/inject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: currentRunningJobId, instruction: instruction })
    }).then(() => {
        const statusBox = document.getElementById('live-status-box');
        if (statusBox) {
            statusBox.innerHTML += `\n[INJECTED] ${instruction}\n`;
            statusBox.scrollTop = statusBox.scrollHeight;
        }
        input.value = '';
    }).catch(err => console.error('Failed to inject instruction:', err));
}

// === Live status display ===
function showLiveStatus(projectId) {
    const liveStatus = document.getElementById('live-status-container');
    if (liveStatus) liveStatus.style.display = 'block';
    const statusBox = document.getElementById('live-status-box');
    if (statusBox) statusBox.innerHTML = '[STATUS POLLING...]\n';
    pollJobStatus();
}

function pollJobStatus() {
    const statusBox = document.getElementById('live-status-box');
    if (!statusBox || !currentProjectId) return;
    fetch('/api/queue')
        .then(r => r.json())
        .then(data => {
            let statusText = '';
            if (data.running) {
                statusText = `[RUNNING] Project: ${data.running.project_name || 'Unknown'}\n`;
                statusText += `  Job ID: ${data.running.job_id}\n`;
                statusText += `  Started: ${data.running.timestamp || 'N/A'}\n`;
            }
            if (data.queue && data.queue.length > 0) {
                statusText += `\n[QUEUED] ${data.queue.length} job(s) waiting:\n`;
                data.queue.forEach(j => {
                    statusText += `  - ${j.project_name || 'Unknown'} (${j.job_id.substring(0, 8)})\n`;
                });
            }
            if (!data.running && (!data.queue || data.queue.length === 0)) {
                statusText = '[IDLE] No active jobs.';
            }
            statusBox.innerHTML = statusText;
        })
        .catch(err => {
            statusBox.innerHTML = `[ERROR] Failed to poll status: ${err.message}`;
        });
}

// === Settings ===
function loadSettingsUI() {
    fetch('/api/settings')
        .then(r => r.json())
        .then(settings => {
            const set = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.value = val;
            };
            set('set-use-local', settings.use_local_model ?? 'false');
            set('set-model-path', settings.model_path || '');
            set('set-llama-binary', settings.llama_binary || '');
            set('set-temperature', settings.temperature ?? '0.1');
            set('set-top-p', settings.top_p ?? '0.9');
            set('set-top-k', settings.top_k ?? '40');
            set('set-min-p', settings.min_p ?? '0.0');
            set('set-output-tokens', settings.output_tokens ?? '8192');
            set('set-model-context', settings.model_context ?? '128000');
            set('set-max-steps', settings.max_steps ?? '50');
            set('set-endpoint', settings.endpoint || '');
            set('set-model-name', settings.model_name || '');
            set('set-api-key', settings.api_key || '');
            set('set-verify-ssl', settings.verify_ssl ?? 'false');
            set('set-generate-only', settings.generate_but_do_not_apply ?? 'false');
            set('set-git-diff', settings.use_git_diff ?? 'false');
            set('set-output-only', settings.generate_output_only ?? 'false');
            set('set-engine-mode', settings.engine_mode || 'agent');
            set('set-root-dir', settings.root_directory || '');
            set('set-jd-cli', settings.jd_cli_path || '');
            set('set-java-home', settings.java_home || '');
            set('set-dotnet-cli', settings.dotnet_cli_path || '');
            set('set-git-diff-cmd', settings.git_diff_command || 'git diff --name-only');
            set('set-use-custom-endpoint', settings.use_custom_endpoint ?? 'false');
            set('set-custom-endpoint-url', settings.custom_endpoint_url || '');
            set('set-custom-api-key', settings.custom_api_key || '');
            set('set-custom-model-name', settings.custom_model_name || '');
            set('set-custom-api-version', settings.custom_api_version || 'v1');
            set('set-custom-verify-ssl', settings.custom_verify_ssl ?? 'false');
            set('set-custom-max-tokens', settings.custom_max_tokens ?? '8192');
            onSettingsLocalChange();
            onSettingsCustomEndpointChange();
        })
        .catch(err => console.error('Failed to load settings:', err));
}

function onSettingsLocalChange() {
    const isLocal = document.getElementById('set-use-local').checked;
    document.getElementById('set-local-section').style.display = isLocal ? 'block' : 'none';
}

function onSettingsCustomEndpointChange() {
    const isCustom = document.getElementById('set-use-custom-endpoint').checked;
    document.getElementById('set-custom-endpoint-section').style.display = isCustom ? 'block' : 'none';
}

function saveSettings() {
    const settings = {
        use_local_model: document.getElementById('set-use-local').checked,
        model_path: document.getElementById('set-model-path').value,
        llama_binary: document.getElementById('set-llama-binary').value,
        temperature: document.getElementById('set-temperature').value,
        top_p: document.getElementById('set-top-p').value,
        top_k: document.getElementById('set-top-k').value,
        min_p: document.getElementById('set-min-p').value,
        output_tokens: document.getElementById('set-output-tokens').value,
        model_context: document.getElementById('set-model-context').value,
        max_steps: document.getElementById('set-max-steps').value,
        endpoint: document.getElementById('set-endpoint').value,
        model_name: document.getElementById('set-model-name').value,
        api_key: document.getElementById('set-api-key').value,
        verify_ssl: document.getElementById('set-verify-ssl').checked,
        generate_but_do_not_apply: document.getElementById('set-generate-only').checked,
        use_git_diff: document.getElementById('set-git-diff').checked,
        generate_output_only: document.getElementById('set-output-only').checked,
        engine_mode: document.getElementById('set-engine-mode').value,
        root_directory: document.getElementById('set-root-dir').value,
        jd_cli_path: document.getElementById('set-jd-cli').value,
        java_home: document.getElementById('set-java-home').value,
        dotnet_cli_path: document.getElementById('set-dotnet-cli').value,
        git_diff_command: document.getElementById('set-git-diff-cmd').value,
        use_custom_endpoint: document.getElementById('set-use-custom-endpoint').checked,
        custom_endpoint_url: document.getElementById('set-custom-endpoint-url').value,
        custom_api_key: document.getElementById('set-custom-api-key').value,
        custom_model_name: document.getElementById('set-custom-model-name').value,
        custom_api_version: document.getElementById('set-custom-api-version').value,
        custom_verify_ssl: document.getElementById('set-custom-verify-ssl').checked,
        custom_max_tokens: document.getElementById('set-custom-max-tokens').value,
    };
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'saved') {
                alert('Settings saved! Changes will apply on next run.');
            } else {
                alert('Failed to save settings: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => {
            console.error('Failed to save settings:', err);
            alert('Failed to save settings.');
        });
}

// === Job Management ===
function loadJobs() {
    Promise.all([
        fetch('/api/queue').then(r => r.json()),
        fetch('/api/history').then(r => r.json())
    ]).then(([queueData, history]) => {
        renderJobs(queueData, history);
        if (currentProjectId) {
            let currentStatus = null;
            if (queueData.running && queueData.running.project_id === currentProjectId) {
                currentStatus = 'running';
            } else if ((queueData.queue || []).some(j => j.project_id === currentProjectId)) {
                currentStatus = 'queued';
            }
            updateRunButtonState(currentProjectId, currentStatus);
        }
    }).catch(err => {
        console.error('Failed to load jobs:', err);
        document.getElementById('jobs-list').innerHTML = '<div class="note warning">Failed to load jobs.</div>';
    });
}

function renderJobs(queueData, history) {
    const list = document.getElementById('jobs-list');
    if (!list) return;
    list.innerHTML = '';
    let items = [...history];
    const historyIds = new Set(items.map(i => i.job_id));
    if (queueData.running && !historyIds.has(queueData.running.job_id)) {
        items.unshift(queueData.running);
    }
    queueData.queue.forEach(j => {
        if (!historyIds.has(j.job_id)) items.push(j);
    });
    if (!items.length) {
        list.innerHTML = '<div class="note">NO JOBS FOUND.</div>';
        return;
    }
    items.forEach(job => {
        const item = document.createElement('div');
        item.className = 'history-item';
        item.dataset.jobId = job.job_id;
        const statusClass = job.status === 'running' ? 'var(--grass)' :
            job.status === 'queued' ? 'var(--sky)' :
                job.status === 'error' ? '#a03030' :
                    job.status === 'stopped' ? '#808000' : '#555';
        const instructionsHtml = job.instructions ? `
                    <div style="margin-top:5px;">
                        <button class="instructions-copy-btn" id="copy-instr-btn-${job.job_id}"
                                onclick="event.stopPropagation(); copyInstructions('${job.job_id}')">
                            COPY PRIOR INSTRUCTIONS
                        </button>
                        <div id="instr-${job.job_id}" style="display:none; margin-top:5px; white-space:pre-wrap; font-size:10px; background:#222; padding:5px; border:1px solid #444;">
                            ${escapeHtml(job.instructions)}
                        </div>
                    </div>
                ` : '';
        const incompleteHtml = job.incomplete ? `
                    <div style="margin-top:5px;">
                        <button class="btn-sm" style="background:#a03030;" onclick="event.stopPropagation(); openActionsModal('${job.job_id}')">
                            VIEW INCOMPLETE ACTIONS
                        </button>
                    </div>
                ` : '';
        // Step results for agentic jobs
        const stepsHtml = job.steps && job.steps.length > 0 ? `
                    <div style="margin-top:5px;">
                        <button class="job-steps-toggle" onclick="event.stopPropagation(); toggleJobSteps('${job.job_id}')">
                            ▼ SHOW STEPS (${job.steps.length})
                        </button>
                        <div id="job-steps-${job.job_id}" class="job-steps-list" style="display:none;">
                            ${job.steps.map((s, i) => {
            const ok = s.result && s.result.success !== false;
            const resultText = s.result ? (s.result.content || '').substring(0, 200) : 'no result';
            return `<div class="job-step-item">
                                    <span class="step-num">Step ${s.step}</span>
                                    <span class="step-tool-name">[${s.tool}]</span>
                                    <span class="step-status-${ok ? 'ok' : 'err'}">${ok ? '✓' : '✗'}</span>
                                    <span style="color:#aaa;">${escapeHtml(resultText)}</span>
                                </div>`;
        }).join('')}
                        </div>
                    </div>
                ` : (job.step_count !== undefined ? `
                    <div style="margin-top:5px; font-size:9px; color:#aaa;">
                        Completed ${job.steps || 0} steps${job.summary ? ': ' + escapeHtml(job.summary.substring(0, 100)) : ''}
                    </div>
                ` : '');
        item.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;">
                        <div style="display:flex; align-items:center; gap:8px; flex:1; min-width:0;">
                            <span class="project-item-name" title="${escapeHtml(job.project_name || 'Unknown Project')}">
                                ${job.project_name || 'Unknown Project'}
                            </span>
                            <span class="project-item-status" style="background:${statusClass};">
                                ${job.status}
                            </span>
                        </div>
                        <div style="display:flex; gap:5px;">
                            ${job.status === 'running' ? `
                                <button class="btn-sm stop" onclick="event.stopPropagation(); stopJob('${job.job_id}')">STOP</button>
                            ` : ''}
                            <button class="btn-sm delete" onclick="event.stopPropagation(); deleteJob('${job.job_id}')">DELETE</button>
                        </div>
                    </div>
                    <span style="color: #ccc; font-size: 8px;">Job: ${job.job_id.substring(0, 8)}...</span>
                    ${instructionsHtml}
                    ${stepsHtml}
                    ${incompleteHtml}
                    ${job.error ? `<div style="color:#f55; margin-top:5px; font-size:10px;">Error: ${escapeHtml(job.error)}</div>` : ''}
                    ${job.summary ? `<div style="color:#aaa; margin-top:3px; font-size:9px;">Summary: ${escapeHtml(job.summary.substring(0, 150))}</div>` : ''}
                `;
        item.onclick = () => goToProject(job.project_id);
        list.appendChild(item);
    });
}

function toggleJobSteps(jobId) {
    const el = document.getElementById('job-steps-' + jobId);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function stopJob(jobId) {
    fetch('/api/queue/running/stop', { method: 'POST' })
        .then(() => loadJobs())
        .catch(err => console.error('Failed to stop job:', err));
}

function deleteJob(jobId) {
    if (!confirm('Delete this job?')) return;
    fetch(`/api/queue/${jobId}`, { method: 'DELETE' })
        .then(() => loadJobs())
        .catch(err => console.error('Failed to delete job:', err));
}

function clearJobHistory() {
    if (!confirm('Are you sure you want to clear all job history?')) return;
    fetch('/api/history/clear', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'cleared') loadJobs();
            else alert('Failed to clear history: ' + (data.error || 'Unknown error'));
        })
        .catch(err => {
            console.error('Failed to clear history:', err);
            alert('Failed to clear history.');
        });
}

// === Project Management ===
function loadProjects() {
    fetch('/api/projects')
        .then(response => response.json())
        .then(data => {
            const projectList = document.getElementById('project-list');
            if (!projectList) return;
            projectList.innerHTML = '';
            if (!data || data.length === 0) {
                projectList.innerHTML = '<div class="note">NO PROJECTS FOUND.<br>ADD ONE BELOW.</div>';
                return;
            }
            const filteredProjects = showArchived ? data : data.filter(p => !p.isArchived);
            if (filteredProjects.length === 0) {
                projectList.innerHTML = '<div class="note">NO PROJECTS FOUND.<br>ADD ONE BELOW.</div>';
                return;
            }
            filteredProjects.forEach(project => {
                const projectItem = document.createElement('div');
                projectItem.className = 'project-item';
                projectItem.id = `proj-${project.id}`;
                projectItem.onclick = () => selectProject(project.id);
                const modeBadge = project.mode === 'agentic'
                    ? '<span class="mode-indicator agentic">AGENTIC</span>'
                    : '<span class="mode-indicator oneshot">ONE-SHOT</span>';
                const archiveBtnText = project.isArchived ? 'UNARCHIVE' : 'ARCHIVE';
                const archiveBtnAction = project.isArchived ? `unarchiveProject('${project.id}')` : `archiveProject('${project.id}')`;
                projectItem.innerHTML = `
                            <div class="project-item-header">
                                <div class="project-item-name-container">
                                    <span class="project-item-name">${escapeHtml(project.name || 'Untitled')}</span>
                                    ${modeBadge}
                                </div>
                                <div class="project-item-actions">
                                    <button class="btn-sm" id="run-btn-${project.id}"
                                        onclick="event.stopPropagation(); runProject('${project.id}')">
                                        RUN
                                    </button>
                                    <button class="btn-sm stop" id="stop-btn-${project.id}"
                                        onclick="event.stopPropagation(); stopProject('${project.id}')"
                                        style="display: none;">
                                        STOP
                                    </button>
                                    <button class="btn-sm archive"
                                        onclick="event.stopPropagation(); ${archiveBtnAction}">
                                        ${archiveBtnText}
                                    </button>
                                    <button class="btn-sm delete"
                                        onclick="event.stopPropagation(); deleteProject('${project.id}')">
                                        DEL
                                    </button>
                                </div>
                            </div>
                            <span style="color: #ccc; font-size: 8px;">${escapeHtml(project.rootDirectory || '')}</span>
                        `;
                projectList.appendChild(projectItem);
            });
        })
        .catch(err => console.error('Failed to load projects:', err));
}

function runProject(projectId) {
    const project = getProjectById(projectId);
    if (!project) { alert('Project not found'); return; }
    if (project.mode === 'agentic') {
        runAgenticProject(projectId);
    } else {
        runLegacyProject(projectId);
    }
}

function runLegacyProject(projectId) {
    fetch('/api/queue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId })
    })
        .then(response => response.json())
        .then(data => {
            if (data.job_id) {
                loadJobs();
                updateRunButtonState(projectId, true);
                showLiveStatus(projectId);
            } else {
                throw new Error(data.error || 'Failed to queue job');
            }
        })
        .catch(error => {
            console.error('Error running project:', error);
            alert(error.message);
        });
}

function runAgenticProject(projectId) {
    const project = getProjectById(projectId);
    if (!project) return;
    const enabledTools = getEnabledTools();
    if (agentSSEController) agentSSEController.abort();
    agentSSEController = new AbortController();
    agentRunning = true;
    liveInjectActive = true;
    const runBtn = document.getElementById('details-run-btn');
    const stopBtn = document.getElementById('details-stop-btn');
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = '<span class="run-spinner"></span> RUNNING...'; }
    if (stopBtn) stopBtn.style.display = 'inline-block';
    const agentLive = document.getElementById('agent-live-container');
    const liveStatus = document.getElementById('live-status-container');
    const liveInject = document.getElementById('live-inject-container');
    if (agentLive) agentLive.style.display = 'block';
    if (liveStatus) liveStatus.style.display = 'block';
    if (liveInject) liveInject.style.display = 'block';
    const agentBox = document.getElementById('agent-live-box');
    const statusBox = document.getElementById('live-status-box');
    if (agentBox) agentBox.innerHTML = '';
    if (statusBox) statusBox.innerHTML = '';
    startAgentSSE(projectId, enabledTools);
}

function startAgentSSE(projectId, enabledTools) {
    if (agentSSEController) agentSSEController.abort();
    agentSSEController = new AbortController();
    const agentBox = document.getElementById('agent-live-box');
    const statusBox = document.getElementById('live-status-box');
    const liveInject = document.getElementById('live-inject-container');
    if (agentBox) agentBox.innerHTML = '';
    if (statusBox) statusBox.innerHTML = '';
    if (liveInject) liveInject.style.display = 'block';
    fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, enabled_tools: enabledTools }),
        signal: agentSSEController.signal
    })
        .then(response => {
            if (!response.ok) throw new Error('Failed to start agent run');
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            function processChunk() {
                reader.read().then(({ done, value }) => {
                    if (done || !agentRunning) {
                        agentRunning = false;
                        liveInjectActive = false;
                        resetRunButtons();
                        return;
                    }
                    buffer += decoder.decode(value, { stream: true });
                    let newlineIdx;
                    while ((newlineIdx = buffer.indexOf('\n')) !== -1) {
                        const fullLine = buffer.substring(0, newlineIdx);
                        buffer = buffer.substring(newlineIdx + 1);
                        if (fullLine.startsWith('event: ')) {
                            const eventType = fullLine.substring(7).trim();
                            const dataLine = buffer.substring(0, buffer.indexOf('\n'));
                            const dataStr = dataLine.replace('data: ', '');
                            buffer = buffer.substring(buffer.indexOf('\n') + 1);
                            try {
                                const data = JSON.parse(dataStr);
                                if (eventType === 'status') handleAgentStatus(data, statusBox);
                                else if (eventType === 'step') handleAgentStep(data, agentBox, statusBox);
                            } catch (e) { console.warn('Failed to parse SSE data:', e); }
                        }
                    }
                    processChunk();
                });
            }
            processChunk();
        })
        .catch(err => {
            if (err.name === 'AbortError') {
                console.log('Agent run stopped');
                if (statusBox) statusBox.innerHTML += '\n[STOPPED]';
            } else {
                console.error('Agent run error:', err);
                if (agentBox) agentBox.innerHTML += `<div class="step-entry error">ERROR: ${escapeHtml(err.message)}</div>`;
                if (statusBox) statusBox.innerHTML += `\n[ERROR: ${escapeHtml(err.message)}]`;
            }
            agentRunning = false;
            liveInjectActive = false;
            resetRunButtons();
        });
}

function handleAgentStatus(data, statusBox) {
    if (!statusBox) return;
    if (data.type === 'start') {
        currentRunningJobId = data.job_id;
        statusBox.innerHTML = `[STARTED] Job: ${data.job_id}\n`;
    } else if (data.type === 'complete') {
        statusBox.innerHTML += `\n[COMPLETE] Steps: ${data.steps}/${data.max_steps}\n${data.summary || ''}\n`;
        loadJobs();
    } else if (data.type === 'error') {
        statusBox.innerHTML += `\n[ERROR] ${data.error}\n`;
        loadJobs();
    }
    if (statusBox) statusBox.scrollTop = statusBox.scrollHeight;
}

function handleAgentStep(data, agentBox, statusBox) {
    if (!agentBox) return;
    const ok = data.result && data.result.success !== false;
    const resultPreview = data.result ? (data.result.content || '').substring(0, 300) : 'no result';
    const entry = document.createElement('div');
    entry.className = `step-entry ${ok ? 'success' : 'error'}`;
    entry.innerHTML = `
                <div><span class="step-tool">Step ${data.step}: ${data.tool}</span></div>
                ${data.params && Object.keys(data.params).length ? `<div style="color:#aaa;font-size:9px;">Params: ${escapeHtml(JSON.stringify(data.params))}</div>` : ''}
                <div class="step-result">${escapeHtml(resultPreview)}</div>
            `;
    agentBox.appendChild(entry);
    if (agentBox) agentBox.scrollTop = agentBox.scrollHeight;
    if (statusBox) {
        statusBox.innerHTML += `[Step ${data.step}] ${data.tool}: ${ok ? '✓' : '✗'} ${resultPreview.substring(0, 80)}\n`;
        statusBox.scrollTop = statusBox.scrollHeight;
    }
}

function stopProject(projectId) {
    agentRunning = false;
    if (agentSSEController) {
        agentSSEController.abort();
        agentSSEController = null;
    }
    liveInjectActive = false;
    fetch('/api/queue/running/stop', { method: 'POST' })
        .then(() => {
            updateRunButtonState(projectId, false);
            loadJobs();
            resetRunButtons();
        })
        .catch(err => console.error('Failed to stop project:', err));
}

function resetRunButtons() {
    const runBtn = document.getElementById('details-run-btn');
    const stopBtn = document.getElementById('details-stop-btn');
    if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = 'RUN AI BUILDER'; }
    if (stopBtn) stopBtn.style.display = 'none';
}

function updateRunButtonState(projectId, status) {
    const listBtn = document.getElementById(`run-btn-${projectId}`);
    const stopListBtn = document.getElementById(`stop-btn-${projectId}`);
    const detailBtn = document.getElementById('details-run-btn');
    const detailStopBtn = document.getElementById('details-stop-btn');
    if (listBtn) {
        listBtn.disabled = status === 'running';
        listBtn.innerHTML = status === 'running' ? '<span class="spinner"></span> RUNNING...' : status === 'queued' ? '<span class="spinner"></span> QUEUED' : 'RUN';
    }
    if (stopListBtn) stopListBtn.style.display = status === 'running' ? 'inline-block' : 'none';
    if (detailBtn && currentProjectId === projectId) {
        detailBtn.disabled = status === 'running';
        detailBtn.innerHTML = status === 'running' ? '<span class="run-spinner"></span> RUNNING...' : status === 'queued' ? '<span class="run-spinner"></span> QUEUED' : 'RUN AI BUILDER';
    }
    if (detailStopBtn && currentProjectId === projectId) {
        detailStopBtn.style.display = status === 'running' ? 'inline-block' : 'none';
    }
}

function archiveProject(projectId) {
    fetch(`/api/projects/${projectId}/archive`, { method: 'POST' })
        .then(() => loadProjects())
        .catch(err => console.error('Failed to archive project:', err));
}

function unarchiveProject(projectId) {
    fetch(`/api/projects/${projectId}/unarchive`, { method: 'POST' })
        .then(() => loadProjects())
        .catch(err => console.error('Failed to unarchive project:', err));
}

function deleteProject(projectId) {
    if (!confirm('Are you sure you want to delete this project?')) return;
    fetch(`/api/projects/${projectId}`, { method: 'DELETE' })
        .then(() => {
            if (currentProjectId === projectId) goBackToProjects();
            else loadProjects();
        })
        .catch(err => console.error('Failed to delete project:', err));
}

function getProjectById(projectId) {
    for (const p of _loadedProjects || []) {
        if (p.id === projectId) return p;
    }
    return null;
}

let _loadedProjects = [];
function loadProjectsCached() {
    return fetch('/api/projects')
        .then(r => r.json())
        .then(data => {
            _loadedProjects = data;
            loadProjects();
            return data;
        });
}

function selectProject(projectId) {
    currentProjectId = projectId;
    localStorage.setItem('currentProjectId', projectId);
    const projectsPanel = document.getElementById('projects-panel');
    const detailsPanel = document.getElementById('project-details-panel');
    if (projectsPanel) { projectsPanel.classList.add('hidden'); projectsPanel.classList.remove('active'); }
    if (detailsPanel) { detailsPanel.classList.remove('hidden'); detailsPanel.classList.add('active'); }
    fetch(`/api/projects/${projectId}`)
        .then(response => response.json())
        .then(project => {
            const safeSet = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
            safeSet('run-project-id', project.id);
            const nameEl = document.getElementById('details-project-name');
            if (nameEl) nameEl.textContent = escapeHtml(project.name || 'Untitled');
            const nameFormEl = document.getElementById('details-project-name-form');
            if (nameFormEl) nameFormEl.value = project.name || '';
            const fileListContainer = document.getElementById('details-file-tree-container');
            if (fileListContainer) fileListContainer.innerHTML = '';
            const mode = project.mode || 'oneshot';
            const modeSelect = document.getElementById('details-mode');
            const modeInput = document.getElementById('details-mode-input');
            const modeBadge = document.getElementById('details-mode-badge');
            if (modeSelect) modeSelect.value = mode;
            if (modeInput) modeInput.value = mode;
            if (modeBadge) {
                modeBadge.className = `mode-indicator ${mode === 'agentic' ? 'agentic' : 'oneshot'}`;
                modeBadge.textContent = mode === 'agentic' ? 'AGENTIC' : 'ONE-SHOT';
            }
            const fileSelector = document.getElementById('details-file-selector');
            const agentSettings = document.getElementById('details-agent-settings');
            if (fileSelector) fileSelector.style.display = mode === 'agentic' ? 'none' : 'block';
            if (agentSettings) agentSettings.style.display = mode === 'agentic' ? 'block' : 'none';
            const rootDir = project.rootDirectory || '';
            safeSet('details-root-dir', rootDir);
            const patterns = project.includePatterns ? project.includePatterns.split(',').map(p => p.trim()) : [];
            const container = document.getElementById('details-selected-paths-container');
            if (container) {
                container.innerHTML = '';
                patterns.forEach(path => { if (path) addPathToDetailsList(path); });
            }
            updateDetailsPatternsInput();
            safeSet('details-instructions', project.instructions || '');
            safeSet('details-pre-script', project.preScript || '');
            safeSet('details-post-script', project.postScript || '');
            safeSet('details-exclude-patterns', project.excludePatterns || '');
            if (mode === 'agentic') buildToolSelector(project.enabled_tools || []);
            loadDetailsFileTree();
            loadJobs();
        })
        .catch(err => console.error('Failed to load project details:', err));
}

function goToProject(projectId) { selectProject(projectId); }

function goBackToProjects() {
    document.getElementById('project-details-panel').classList.add('hidden');
    document.getElementById('project-details-panel').classList.remove('active');
    document.getElementById('projects-panel').classList.remove('hidden');
    document.getElementById('projects-panel').classList.add('active');
    localStorage.removeItem('currentProjectId');
    currentProjectId = null;
    loadProjects();
}

// === File Tree Management ===
function loadFileTree(isSearch = false) {
    if (isSearch) fileTreePage = 0;
    const rootPath = document.getElementById('add-root-path')?.value;
    if (!rootPath) { alert('Please enter a root directory first'); return; }
    fileTreePath = rootPath;
    fileTreeSearch = document.getElementById('tree-search').value.toLowerCase();
    const loadTreeBtn = document.getElementById('load-tree-btn');
    const loadTreeText = document.getElementById('load-tree-text');
    const loadTreeSpinner = document.getElementById('load-tree-spinner');
    const container = document.getElementById('file-tree-container');
    const paginationDiv = document.getElementById('file-tree-pagination');
    if (loadTreeBtn) loadTreeBtn.disabled = true;
    if (loadTreeText) loadTreeText.style.display = 'none';
    if (loadTreeSpinner) loadTreeSpinner.style.display = 'inline-block';
    if (container) container.innerHTML = '<span class="spinner" style="display:inline-block; margin:10px;"></span><span style="margin-left: 10px;">Loading files...</span>';
    if (paginationDiv) paginationDiv.innerHTML = '';
    const pathToUse = fileTreePath.startsWith('/') || fileTreePath.match(/^[a-zA-Z]:\\\\/) ? fileTreePath : `./${fileTreePath}`;
    fetch(`/api/files?path=${encodeURIComponent(pathToUse)}&limit=50&offset=${fileTreePage * 50}&search=${encodeURIComponent(fileTreeSearch)}`)
        .then(response => response.json())
        .then(data => {
            if (!container) return;
            container.innerHTML = '';
            let paths = data.files || [];
            fileTreeTotal = data.total || 0;
            const showSelectedOnly = document.getElementById('show-selected-only-new')?.checked;
            if (showSelectedOnly) {
                const selectedPaths = Array.from(document.querySelectorAll('#selected-paths-container .path-item')).map(el => el.dataset.path);
                paths = paths.filter(p => selectedPaths.includes(p.path));
                fileTreeTotal = paths.length;
            }
            const currentPaths = Array.from(document.querySelectorAll('#selected-paths-container .path-item')).map(el => el.dataset.path);
            paths.forEach(item => {
                const isDir = item.path.endsWith('/');
                const itemElement = document.createElement('div');
                itemElement.className = `tree-item ${isDir ? 'dir' : 'file'}`;
                itemElement.style.cursor = 'pointer';
                itemElement.style.padding = '5px 0';
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.checked = currentPaths.includes(item.path);
                checkbox.onchange = () => updateSelectedPatterns();
                checkbox.dataset.path = item.path;
                checkbox.style.width = '10%';
                const label = document.createElement('label');
                label.textContent = item.path;
                label.style.marginLeft = '5px';
                label.style.display = 'inline-block';
                const sizeLabel = document.createElement('span');
                sizeLabel.textContent = ` (${formatSize(item.size)})`;
                sizeLabel.style.color = '#888';
                sizeLabel.style.fontSize = '11px';
                label.appendChild(sizeLabel);
                itemElement.appendChild(checkbox);
                itemElement.appendChild(label);
                itemElement.onclick = (e) => { if (e.target !== checkbox) { checkbox.checked = !checkbox.checked; checkbox.onchange(); } };
                container.appendChild(itemElement);
            });
            updateSelectedPatterns();
            if (loadTreeBtn) loadTreeBtn.disabled = false;
            if (loadTreeText) loadTreeText.style.display = 'inline';
            if (loadTreeSpinner) loadTreeSpinner.style.display = 'none';
            if (paginationDiv) renderPagination(paginationDiv, fileTreePage, fileTreeTotal, 50, loadFileTree, false);
        })
        .catch(err => {
            console.error('Failed to load file tree:', err);
            if (loadTreeBtn) loadTreeBtn.disabled = false;
            if (loadTreeText) loadTreeText.style.display = 'inline';
            if (loadTreeSpinner) loadTreeSpinner.style.display = 'none';
            if (container) container.innerHTML = '<div class="note warning">Failed to load files. Check path and try again.</div>';
        });
}

function loadDetailsFileTree(isSearch = false) {
    if (isSearch) detailsFileTreePage = 0;
    const rootPath = document.getElementById('details-root-dir')?.value;
    if (!rootPath) { alert('Please enter a root directory first'); return; }
    detailsFileTreePath = rootPath;
    detailsFileTreeSearch = document.getElementById('details-tree-search').value.toLowerCase();
    const loadTreeBtn = document.getElementById('details-load-tree-btn');
    const loadTreeText = document.getElementById('details-load-tree-text');
    const loadTreeSpinner = document.getElementById('details-load-tree-spinner');
    const container = document.getElementById('details-file-tree-container');
    const paginationDiv = document.getElementById('details-file-tree-pagination');
    if (loadTreeBtn) loadTreeBtn.disabled = true;
    if (loadTreeText) loadTreeText.style.display = 'none';
    if (loadTreeSpinner) loadTreeSpinner.style.display = 'inline-block';
    if (container) container.innerHTML = '<span class="spinner" style="display:inline-block; margin:10px;"></span><span style="margin-left: 10px;">Loading files...</span>';
    if (paginationDiv) paginationDiv.innerHTML = '';
    const pathToUse = detailsFileTreePath.startsWith('/') || detailsFileTreePath.match(/^[a-zA-Z]:\\\\/) ? detailsFileTreePath : `./${detailsFileTreePath}`;
    fetch(`/api/files?path=${encodeURIComponent(pathToUse)}&limit=50&offset=${detailsFileTreePage * 50}&search=${encodeURIComponent(detailsFileTreeSearch)}`)
        .then(response => response.json())
        .then(data => {
            if (!container) return;
            container.innerHTML = '';
            let paths = data.files || [];
            detailsFileTreeTotal = data.total || 0;
            const showSelectedOnly = document.getElementById('details-show-selected-only')?.checked;
            if (showSelectedOnly) {
                const selectedPaths = Array.from(document.querySelectorAll('#details-selected-paths-container .path-item')).map(el => el.dataset.path);
                paths = paths.filter(p => selectedPaths.includes(p.path));
                detailsFileTreeTotal = paths.length;
            }
            const currentPaths = Array.from(document.querySelectorAll('#details-selected-paths-container .path-item')).map(el => el.dataset.path);
            paths.forEach(item => {
                const isDir = item.path.endsWith('/');
                const itemElement = document.createElement('div');
                itemElement.className = `tree-item ${isDir ? 'dir' : 'file'}`;
                itemElement.style.cursor = 'pointer';
                itemElement.style.padding = '5px 0';
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.checked = currentPaths.includes(item.path);
                checkbox.onchange = () => detailsUpdateSelectedPatterns();
                checkbox.dataset.path = item.path;
                checkbox.style.width = '10%';
                const label = document.createElement('label');
                label.textContent = item.path;
                label.style.marginLeft = '5px';
                label.style.display = 'inline-block';
                const sizeLabel = document.createElement('span');
                sizeLabel.textContent = ` (${formatSize(item.size)})`;
                sizeLabel.style.color = '#888';
                sizeLabel.style.fontSize = '11px';
                label.appendChild(sizeLabel);
                itemElement.appendChild(checkbox);
                itemElement.appendChild(label);
                itemElement.onclick = (e) => { if (e.target !== checkbox) { checkbox.checked = !checkbox.checked; checkbox.onchange(); } };
                container.appendChild(itemElement);
            });
            detailsUpdateSelectedPatterns();
            if (loadTreeBtn) loadTreeBtn.disabled = false;
            if (loadTreeText) loadTreeText.style.display = 'inline';
            if (loadTreeSpinner) loadTreeSpinner.style.display = 'none';
            if (paginationDiv) renderPagination(paginationDiv, detailsFileTreePage, detailsFileTreeTotal, 50, loadDetailsFileTree, true);
        })
        .catch(err => {
            console.error('Failed to load details file tree:', err);
            if (loadTreeBtn) loadTreeBtn.disabled = false;
            if (loadTreeText) loadTreeText.style.display = 'inline';
            if (loadTreeSpinner) loadTreeSpinner.style.display = 'none';
            if (container) container.innerHTML = '<div class="note warning">Failed to load files. Check path and try again.</div>';
        });
}

function renderPagination(container, currentPage, total, limit, callback, isDetails = false) {
    const totalPages = Math.ceil(total / limit);
    if (totalPages <= 1) return;
    const pageVar = isDetails ? 'detailsFileTreePage' : 'fileTreePage';
    container.innerHTML = `
                <div style="display:flex; justify-content:center; gap:10px; margin-top:10px;">
                    <button class="btn-sm" onclick="event.stopPropagation(); ${pageVar} = Math.max(0, ${pageVar} - 1); ${callback.name}(false)"
                            ${currentPage === 0 ? 'disabled' : ''}>PREV</button>
                    <span style="align-self:center;">Page ${currentPage + 1} of ${totalPages} (${total} files)</span>
                    <button class="btn-sm" onclick="event.stopPropagation(); ${pageVar} = Math.min(${totalPages - 1}, ${pageVar} + 1); ${callback.name}(false)"
                            ${currentPage >= totalPages - 1 ? 'disabled' : ''}>NEXT</button>
                </div>
            `;
}

function selectAll() {
    showTreeOverlay('file-tree');
    document.querySelectorAll('#file-tree-container input[type="checkbox"]').forEach(cb => { cb.checked = true; });
    updateSelectedPatterns();
    hideTreeOverlay('file-tree');
}

function deselectAll() {
    showTreeOverlay('file-tree');
    document.querySelectorAll('#file-tree-container input[type="checkbox"]').forEach(cb => { cb.checked = false; });
    updateSelectedPatterns();
    hideTreeOverlay('file-tree');
}

function detailsSelectAll() {
    showTreeOverlay('details-file-tree');
    document.querySelectorAll('#details-file-tree-container input[type="checkbox"]').forEach(cb => { cb.checked = true; });
    detailsUpdateSelectedPatterns();
    hideTreeOverlay('details-file-tree');
}

function detailsDeselectAll() {
    showTreeOverlay('details-file-tree');
    document.querySelectorAll('#details-file-tree-container input[type="checkbox"]').forEach(cb => { cb.checked = false; });
    detailsUpdateSelectedPatterns();
    hideTreeOverlay('details-file-tree');
}

function filterTree() {
    clearTimeout(filterTreeTimeout);
    showTreeOverlay('file-tree');
    filterTreeTimeout = setTimeout(() => { loadFileTree(true); }, 300);
}

function detailsFilterTree() {
    clearTimeout(detailsFilterTreeTimeout);
    showTreeOverlay('details-file-tree');
    detailsFilterTreeTimeout = setTimeout(() => { loadDetailsFileTree(true); }, 300);
}

function showTreeOverlay(id) { const overlay = document.getElementById(id + '-loading-overlay'); if (overlay) overlay.style.display = 'flex'; }
function hideTreeOverlay(id) { const overlay = document.getElementById(id + '-loading-overlay'); if (overlay) overlay.style.display = 'none'; }

// === Path Management ===
function addPathToDetailsList(path) {
    const container = document.getElementById('details-selected-paths-container');
    if (!container) return;
    const pathItem = document.createElement('div');
    pathItem.className = 'path-item';
    pathItem.dataset.path = path;
    const pathText = document.createElement('span');
    pathText.textContent = escapeHtml(path);
    const removeBtn = document.createElement('button');
    removeBtn.className = 'remove-btn';
    removeBtn.textContent = 'X';
    removeBtn.onclick = () => { pathItem.remove(); updateDetailsPatternsInput(); autoSaveProject(); };
    pathItem.appendChild(pathText);
    pathItem.appendChild(removeBtn);
    container.appendChild(pathItem);
}

function updateDetailsPatternsInput() {
    const container = document.getElementById('details-selected-paths-container');
    const input = document.getElementById('details-patterns-input');
    if (!container || !input) return;
    const paths = Array.from(container.children).map(el => el.dataset.path);
    input.value = paths.join(',');
}

function detailsUpdateSelectedPatterns() { updateDetailsPatternsInput(); autoSaveProject(); }

function addNewPath() {
    const input = document.getElementById('new-path-input');
    const path = input.value.trim();
    if (!path) return;
    const container = document.getElementById('selected-paths-container');
    if (!container) return;
    const pathItem = document.createElement('div');
    pathItem.className = 'path-item';
    pathItem.dataset.path = path;
    const pathText = document.createElement('span');
    pathText.textContent = escapeHtml(path);
    const removeBtn = document.createElement('button');
    removeBtn.className = 'remove-btn';
    removeBtn.textContent = 'X';
    removeBtn.onclick = () => { pathItem.remove(); updateSelectedPatterns(); };
    pathItem.appendChild(pathText);
    pathItem.appendChild(removeBtn);
    container.appendChild(pathItem);
    input.value = '';
    updateSelectedPatterns();
}

function updateSelectedPatterns() {
    const container = document.getElementById('selected-paths-container');
    const input = document.getElementById('patterns-input');
    if (!container || !input) return;
    const paths = Array.from(container.children).map(el => el.dataset.path);
    input.value = paths.join(',');
}

function formatSize(bytes) {
    if (bytes === null || bytes === undefined) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// === Project Form Submit ===
document.getElementById('add-project-form').addEventListener('submit', function (e) {
    e.preventDefault();
    const formData = new FormData(this);
    formData.set('includePatterns', document.getElementById('patterns-input').value);
    fetch('/api/projects', { method: 'POST', body: formData })
        .then(res => res.json())
        .then(data => {
            if (data.error) { alert('Error: ' + data.error); }
            else { loadProjects(); this.reset(); selectedPaths = []; renderSelectedPaths(); onAddModeChange(); }
        })
        .catch(err => console.error('Failed to create project:', err));
});

function toggleArchived() {
    showArchived = !showArchived;
    const btn = document.getElementById('show-archived-btn');
    if (btn) btn.textContent = showArchived ? 'HIDE ARCHIVED' : 'SHOW ARCHIVED';
    loadProjects();
}

function openActionsModal(jobId) {
    fetch(`/api/job/${jobId}/actions`)
        .then(r => r.json())
        .then(data => {
            document.getElementById('actions-modal-content').textContent = data.content || 'No actions file found.';
            document.getElementById('actions-modal').style.display = 'flex';
        })
        .catch(err => { console.error('Failed to load actions:', err); alert('Failed to load actions.'); });
}

function closeActionsModal() { document.getElementById('actions-modal').style.display = 'none'; }

function copyInstructions(jobId) {
    const el = document.getElementById('instr-' + jobId);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

// === Auto Save ===
function autoSaveProject() {
    clearTimeout(autoSaveTimeout);
    autoSaveTimeout = setTimeout(() => { saveProjectChanges(); }, 2000);
}

function saveProjectChanges() {
    const projectId = document.getElementById('run-project-id')?.value;
    if (!projectId) return;
    const formData = new FormData(document.getElementById('project-details-form'));
    formData.set('includePatterns', document.getElementById('details-patterns-input')?.value || '');
    formData.set('mode', document.getElementById('details-mode').value);
    fetch(`/api/projects/${projectId}`, { method: 'POST', body: formData })
        .then(res => res.json())
        .then(data => { if (data.status === 'saved') console.log('Project saved'); })
        .catch(err => console.error('Failed to save project:', err));
}

function confirmDetailsRootPathChange() {
    pendingRootPathChange = true;
    pendingRootPathElementId = 'details-root-dir';
    document.getElementById('root-path-confirmation-modal').style.display = 'flex';
}

function confirmRootPathChangeProceed() {
    document.getElementById('root-path-confirmation-modal').style.display = 'none';
    const container = document.getElementById('details-selected-paths-container');
    if (container) container.innerHTML = '';
    updateDetailsPatternsInput();
    autoSaveProject();
}

function cancelRootPathChange() {
    document.getElementById('root-path-confirmation-modal').style.display = 'none';
    const el = document.getElementById(pendingRootPathElementId);
    if (el) el.blur();
}

// === Chat ===
function loadChats() {
    fetch('/api/chats')
        .then(r => r.json())
        .then(chats => {
            const list = document.getElementById('chat-list');
            if (!list) return;
            list.innerHTML = '';
            if (!chats.length) { list.innerHTML = '<div class="note">NO CHATS FOUND.</div>'; return; }
            chats.forEach(chat => {
                const item = document.createElement('div');
                item.className = 'chat-item' + (chat.id === currentChatId ? ' active' : '');
                item.innerHTML = `<span>${escapeHtml(chat.title || 'New Chat')}</span>`;
                item.onclick = () => openChat(chat.id);
                list.appendChild(item);
            });
        })
        .catch(err => console.error('Failed to load chats:', err));
}

function newChat() {
    fetch('/api/chats', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timestamp: new Date().toISOString() })
    })
        .then(r => r.json())
        .then(data => { loadChats(); openChat(data.id); })
        .catch(err => console.error('Failed to create chat:', err));
}

function openChat(chatId) {
    currentChatId = chatId;
    localStorage.setItem('currentChatId', chatId);
    fetch(`/api/chats/${chatId}`)
        .then(r => r.json())
        .then(chat => {
            const log = document.getElementById('chat-log');
            const controls = document.getElementById('chat-controls-container');
            const input = document.getElementById('chat-input');
            const sendBtn = document.getElementById('send-chat-btn');
            if (log) {
                log.style.display = 'block';
                log.innerHTML = '';
                chat.messages.forEach(msg => {
                    const div = document.createElement('div');
                    div.className = 'chat-msg';
                    div.innerHTML = `<strong>${msg.role === 'user' ? 'YOU' : 'AI'}:</strong> ${escapeHtml(msg.content)}`;
                    log.appendChild(div);
                });
                log.scrollTop = log.scrollHeight;
            }
            if (controls) controls.style.display = 'block';
            if (input) input.disabled = false;
            if (sendBtn) sendBtn.disabled = false;
            loadChats();
        })
        .catch(err => console.error('Failed to load chat:', err));
}

function sendChat() {
    const input = document.getElementById('chat-input');
    const content = input.value.trim();
    if (!content) return;
    const log = document.getElementById('chat-log');
    const sendBtn = document.getElementById('send-chat-btn');
    const userDiv = document.createElement('div');
    userDiv.className = 'chat-msg';
    userDiv.innerHTML = `<strong>YOU:</strong> ${escapeHtml(content)}`;
    log.appendChild(userDiv);
    input.value = '';
    sendBtn.disabled = true;
    log.scrollTop = log.scrollHeight;
    fetch(`/api/chats/${currentChatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
    })
        .then(response => {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let aiDiv = document.createElement('div');
            aiDiv.className = 'chat-msg';
            aiDiv.innerHTML = `<strong>AI:</strong> <span id="chat-stream-text"></span>`;
            log.appendChild(aiDiv);
            function read() {
                reader.read().then(({ done, value }) => {
                    if (done) { sendBtn.disabled = false; log.scrollTop = log.scrollHeight; loadChats(); return; }
                    buffer += decoder.decode(value, { stream: true });
                    const textEl = document.getElementById('chat-stream-text');
                    if (textEl) textEl.textContent = buffer;
                    log.scrollTop = log.scrollHeight;
                    read();
                });
            }
            read();
        })
        .catch(err => { console.error('Chat error:', err); sendBtn.disabled = false; });
}

// === Init ===
document.addEventListener('DOMContentLoaded', () => {
    loadProjectsCached();
    loadJobs();
    setInterval(() => { if (currentProjectId) pollJobStatus(); }, 3000);
});