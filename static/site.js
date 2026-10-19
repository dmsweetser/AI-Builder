// === Fling Game State ===
let flingCount = 0;
let logoX = 40, logoY = 40;
let velX = 0, velY = 0;
let isDragging = false;
let dragStartX = 0, dragStartY = 0;
let dragLogoStartX = 0, dragLogoStartY = 0;
let flingAnimFrame = null;
const GOAL_ZONE = { x: 40, y: 40, w: 120, h: 120 };
const FRICTION = 0.98;
const MIN_VEL = 0.5;

function startFlingLoop() {
    if (flingAnimFrame) return;
    function animate() {
        if (isDragging) { flingAnimFrame = requestAnimationFrame(animate); return; }
        logoX += velX;
        logoY += velY;
        velX *= FRICTION;
        velY *= FRICTION;
        const logo = document.getElementById('draggable-logo');
        if (logo) {
            const rect = logo.getBoundingClientRect();
            // Clamp to viewport
            if (logoX < 0) { logoX = 0; velX = -velX * 0.7; }
            if (logoY < 0) { logoY = 0; velY = -velY * 0.7; }
            if (logoX + rect.width > window.innerWidth) { logoX = window.innerWidth - rect.width; velX = -velX * 0.7; }
            if (logoY + rect.height > window.innerHeight) { logoY = window.innerHeight - rect.height; velY = -velY * 0.7; }
            logo.style.left = logoX + 'px';
            logo.style.top = logoY + 'px';
        }
        // Check goal zone
        const goalZone = document.getElementById('goal-zone');
        const flingCounter = document.getElementById('fling-counter');
        const logoEl = document.getElementById('draggable-logo');
        const logoW = logoEl ? logoEl.offsetWidth : 120;
        const logoH = logoEl ? logoEl.offsetHeight : 120;
        if (logoX >= GOAL_ZONE.x && logoX + logoW >= GOAL_ZONE.x + GOAL_ZONE.w &&
            logoY >= GOAL_ZONE.y && logoY + logoH >= GOAL_ZONE.y + GOAL_ZONE.h) {
            if (goalZone) goalZone.style.display = 'block';
            if (flingCounter) flingCounter.style.display = 'block';
            flingCounter.textContent = 'FLINGS: ' + flingCount;
        } else {
            if (goalZone) goalZone.style.display = 'none';
            if (flingCounter) flingCounter.style.display = 'none';
        }
        // Stop animation when velocity is tiny
        if (Math.abs(velX) < MIN_VEL && Math.abs(velY) < MIN_VEL) {
            flingAnimFrame = null;
            return;
        }
        flingAnimFrame = requestAnimationFrame(animate);
    }
    flingAnimFrame = requestAnimationFrame(animate);
}

function checkWinCondition() {
    const goalZone = document.getElementById('goal-zone');
    const logoEl = document.getElementById('draggable-logo');
    if (!logoEl) return;
    const logoW = logoEl.offsetWidth;
    const logoH = logoEl.offsetHeight;
    // Check logo is fully contained within the goal zone
    if (logoX >= GOAL_ZONE.x && logoX + logoW <= GOAL_ZONE.x + GOAL_ZONE.w &&
        logoY >= GOAL_ZONE.y && logoY + logoH <= GOAL_ZONE.y + GOAL_ZONE.h) {
        flingCount++;
        const flingCounter = document.getElementById('fling-counter');
        if (flingCounter) flingCounter.textContent = 'FLINGS: ' + flingCount;
        // Show win message after 3 flings
        if (flingCount >= 3) {
            const winMsg = document.getElementById('win-message');
            if (winMsg) {
                document.getElementById('win-fling-count').textContent = flingCount + ' FLINGS';
                winMsg.style.display = 'block';
                setTimeout(() => { if (winMsg) winMsg.style.display = 'none'; }, 5000);
            }
        }
        // Reset position to bottom-right and clear velocity
        logoX = window.innerWidth - logoW - 20;
        logoY = window.innerHeight - logoH - 20;
        velX = 0;
        velY = 0;
        if (goalZone) goalZone.style.display = 'none';
        // Update logo position immediately
        logoEl.style.left = logoX + 'px';
        logoEl.style.top = logoY + 'px';
    }
}

// Fling game event handlers
document.addEventListener('DOMContentLoaded', () => {
    const logo = document.getElementById('draggable-logo');
    if (logo) {
        logo.addEventListener('mousedown', (e) => {
            isDragging = true;
            dragStartX = e.clientX;
            dragStartY = e.clientY;
            dragLogoStartX = logoX;
            dragLogoStartY = logoY;
            logo.style.cursor = 'grabbing';
            e.preventDefault();
        });
        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const dx = e.clientX - dragStartX;
            const dy = e.clientY - dragStartY;
            logoX = dragLogoStartX + dx;
            logoY = dragLogoStartY + dy;
            velX = dx * 0.3;
            velY = dy * 0.3;
            const el = document.getElementById('draggable-logo');
            if (el) {
                el.style.left = logoX + 'px';
                el.style.top = logoY + 'px';
            }
        });
        document.addEventListener('mouseup', () => {
            if (!isDragging) return;
            isDragging = false;
            logo.style.cursor = 'grab';
            checkWinCondition();
            startFlingLoop();
        });
        // Touch support
        logo.addEventListener('touchstart', (e) => {
            const touch = e.touches[0];
            isDragging = true;
            dragStartX = touch.clientX;
            dragStartY = touch.clientY;
            dragLogoStartX = logoX;
            dragLogoStartY = logoY;
            e.preventDefault();
        });
        document.addEventListener('touchmove', (e) => {
            if (!isDragging) return;
            const touch = e.touches[0];
            const dx = touch.clientX - dragStartX;
            const dy = touch.clientY - dragStartY;
            logoX = dragLogoStartX + dx;
            logoY = dragLogoStartY + dy;
            velX = dx * 0.3;
            velY = dy * 0.3;
            const el = document.getElementById('draggable-logo');
            if (el) {
                el.style.left = logoX + 'px';
                el.style.top = logoY + 'px';
            }
        });
        document.addEventListener('touchend', () => {
            if (!isDragging) return;
            isDragging = false;
            checkWinCondition();
            startFlingLoop();
        });
    }
});
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
    const buttons = document.querySelectorAll('.sidebar-nav .tab-btn');
    buttons.forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
        b.setAttribute('tabindex', '-1');
    });
    const panel = document.getElementById(tabName + '-panel');
    if (panel) {
        panel.classList.remove('hidden');
        panel.classList.add('active');
    }
    // Activate the correct button
    buttons.forEach(b => {
        if (b.textContent.trim().toUpperCase() === tabName.toUpperCase()) {
            b.classList.add('active');
            b.setAttribute('aria-selected', 'true');
            b.setAttribute('tabindex', '0');
            b.focus();
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
        modeBadge.className = `mode-indicator ${mode === 'agentic' ? 'agentic' : ''}`;
        modeBadge.textContent = mode === 'agentic' ? 'AGENTIC' : '';
    }
    if (mode === 'agentic') {
        buildToolSelector([]);
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

// === Live step updates during agent run ===
function pollAgentSteps() {
    if (!currentRunningJobId || !agentRunning) return;
    fetch(`/api/agent/history/${currentRunningJobId}`)
        .then(r => r.json())
        .then(data => {
            if (data.steps && data.steps.length > 0) {
                // Update the job history item if it exists
                const historyItem = document.querySelector(`.history-item[data-job-id="${currentRunningJobId}"]`);
                if (historyItem) {
                    const stepsList = historyItem.querySelector('.job-steps-list');
                    if (stepsList) {
                        stepsList.innerHTML = data.steps.map((s, i) => {
                            const ok = s.result && s.result.success !== false;
                            const resultText = s.result ? (s.result.content || '').substring(0, 200) : 'no result';
                            return `<div class="job-step-item">
                                <span class="step-num">Step ${s.step}</span>
                                <span class="step-tool-name">[${s.tool}]</span>
                                <span class="step-status-${ok ? 'ok' : 'err'}">${ok ? '✓' : '✗'}</span>
                                <span style="color:#aaa;">${escapeHtml(resultText)}</span>
                            </div>`;
                        }).join('');
                        // Auto-scroll the steps list
                        stepsList.scrollTop = stepsList.scrollHeight;
                    }
                }
            }
        })
        .catch(err => console.warn('Failed to poll agent steps:', err));
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
            set('set-custom-endpoint-url', settings.custom_endpoint_url || '');
            set('set-custom-api-key', settings.custom_api_key || '');
            set('set-custom-model-name', settings.custom_model_name || '');
            set('set-custom-verify-ssl', settings.custom_verify_ssl ?? 'false');
            set('set-max-steps', settings.max_steps ?? '50');
            set('set-timeout', settings.timeout ?? '3600');
            set('set-root-dir', settings.root_directory || '');
            set('set-jd-cli', settings.jd_cli_path || '');
            set('set-java-home', settings.java_home || '');
            set('set-dotnet-cli', settings.dotnet_cli_path || '');
        })
        .catch(err => console.error('Failed to load settings:', err));
}

function saveSettings() {
    const settings = {
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
        item.setAttribute('role', 'listitem');
        item.setAttribute('tabindex', '0');
        item.onclick = () => goToProject(job.project_id);
        item.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); goToProject(job.project_id); } };
        const statusClass = job.status === 'running' ? 'var(--grass)' :
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
        // Step results for agentic jobs (check step_history array first, then legacy steps)
        const stepsData = (job.step_history && job.step_history.length > 0) ? job.step_history :
                          (job.steps && Array.isArray(job.steps)) ? job.steps : null;
        const stepsHtml = stepsData ? `
                    <div style="margin-top:5px;">
                        <button class="job-steps-toggle" onclick="event.stopPropagation(); toggleJobSteps('${job.job_id}')">
                            ▼ SHOW STEPS (${stepsData.length})
                        </button>
                        <div id="job-steps-${job.job_id}" class="job-steps-list" style="display:none;">
                            ${stepsData.map((s, i) => {
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
                projectItem.setAttribute('role', 'listitem');
                projectItem.setAttribute('tabindex', '0');
                projectItem.onclick = () => selectProject(project.id);
                projectItem.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectProject(project.id); } };
                const modeBadge = project.mode === 'agentic'
                    ? '<span class="mode-indicator agentic">AGENTIC</span>'
                    : '';
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
                                        onclick="event.stopPropagation(); runProject('${project.id}')"
                                        aria-label="Run ${escapeHtml(project.name || 'project')}">
                                        RUN
                                    </button>
                                    <button class="btn-sm stop" id="stop-btn-${project.id}"
                                        onclick="event.stopPropagation(); stopProject('${project.id}')"
                                        style="display: none;"
                                        aria-label="Stop ${escapeHtml(project.name || 'project')}">
                                        STOP
                                    </button>
                                    <button class="btn-sm archive"
                                        onclick="event.stopPropagation(); ${archiveBtnAction}"
                                        aria-label="${archiveBtnText} ${escapeHtml(project.name || 'project')}">
                                        ${archiveBtnText}
                                    </button>
                                    <button class="btn-sm delete"
                                        onclick="event.stopPropagation(); deleteProject('${project.id}')"
                                        aria-label="Delete ${escapeHtml(project.name || 'project')}">
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
    let project = getProjectById(projectId);
    if (!project) {
        fetch(`/api/projects/${projectId}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) { alert('Project not found'); return; }
                _loadedProjects = _loadedProjects || [];
                if (!_loadedProjects.find(p => p.id === projectId)) {
                    _loadedProjects.push(data);
                }
                runAgenticProject(projectId);
            })
            .catch(err => { console.error('Failed to fetch project:', err); alert('Failed to load project details'); });
        return;
    }
    runAgenticProject(projectId);
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
    // Process complete SSE messages (delimited by \n\n or \n)
                    // This handles multi-chunk messages correctly
                    let doubleNewlineIdx;
                    while ((doubleNewlineIdx = buffer.indexOf('\n\n')) !== -1) {
                        const message = buffer.substring(0, doubleNewlineIdx);
                        buffer = buffer.substring(doubleNewlineIdx + 2); // skip \n\n

                        const lines = message.split('\n');
                        let eventType = 'message'; // default SSE event type
                        let dataStr = '';

                        for (const line of lines) {
                            if (line.startsWith('event: ')) {
                                eventType = line.substring(7).trim();
                            } else if (line.startsWith('data: ')) {
                                dataStr = line.substring(6);
                            }
                        }

                        if (dataStr) {
                            try {
                                const data = JSON.parse(dataStr);
                                if (eventType === 'status') handleAgentStatus(data, statusBox);
                                else if (eventType === 'step') handleAgentStep(data, agentBox, statusBox);
                            } catch (e) { console.warn('Failed to parse SSE data:', e); }
                        }
                    }
                    // Fallback: process single-line SSE messages (delimited by \n)
                    // The backend sends step events as single-line SSE: event: step\ndata: {...}\n
                    let singleNewlineIdx;
                    while ((singleNewlineIdx = buffer.indexOf('\n')) !== -1) {
                        const line = buffer.substring(0, singleNewlineIdx).trim();
                        buffer = buffer.substring(singleNewlineIdx + 1);
                        if (!line) continue;
                        // Parse single-line SSE: event: ...\ndata: ...
                        if (line.startsWith('event: ')) {
                            const eventType = line.substring(7).trim();
                            // Next line should be data: ...
                            const dataIdx = buffer.indexOf('\n');
                            if (dataIdx !== -1) {
                                const dataLine = buffer.substring(0, dataIdx).trim();
                                buffer = buffer.substring(dataIdx + 1);
                                if (dataLine.startsWith('data: ')) {
                                    const dataStr = dataLine.substring(6);
                                    try {
                                        const data = JSON.parse(dataStr);
                                        if (eventType === 'status') handleAgentStatus(data, statusBox);
                                        else if (eventType === 'step') handleAgentStep(data, agentBox, statusBox);
                                    } catch (e) { /* ignore parse errors */ }
                                }
                            }
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
        // Stop polling agent steps when complete
        agentRunning = false;
    } else if (data.type === 'error') {
        statusBox.innerHTML += `\n[ERROR] ${data.error}\n`;
        loadJobs();
        agentRunning = false;
    } else if (data.type === 'max_steps_reached') {
        statusBox.innerHTML += `
[MAX STEPS REACHED] Steps: ${data.steps}/${data.max_steps}
`;
        // Show continue button
        const continueBtn = document.createElement('button');
        continueBtn.className = 'btn-sm';
        continueBtn.textContent = 'CONTINUE AGENT';
        continueBtn.onclick = () => continueAgentRun(currentRunningJobId);
        statusBox.appendChild(continueBtn);
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
    agentBox.scrollTop = agentBox.scrollHeight;
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

function continueAgentRun(jobId) {
    if (!jobId) return;
    agentRunning = true;
    liveInjectActive = true;
    fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, continue: true })
    })
    .then(response => {
        if (!response.ok) throw new Error('Failed to continue agent run');
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
                // Process SSE messages: try \n\n first, then \n
                let delimIdx;
                while ((delimIdx = buffer.indexOf('\n\n')) !== -1) {
                    const message = buffer.substring(0, delimIdx);
                    buffer = buffer.substring(delimIdx + 2);
                    const lines = message.split('\n');
                    let eventType = 'message';
                    let dataStr = '';
                    for (const line of lines) {
                        if (line.startsWith('event: ')) eventType = line.substring(7).trim();
                        else if (line.startsWith('data: ')) dataStr = line.substring(6);
                    }
                    if (dataStr) {
                        try {
                            const data = JSON.parse(dataStr);
                            if (eventType === 'status') handleAgentStatus(data, document.getElementById('live-status-box'));
                            else if (eventType === 'step') handleAgentStep(data, document.getElementById('agent-live-box'), document.getElementById('live-status-box'));
                        } catch (e) { console.warn('Failed to parse SSE data:', e); }
                    }
                }
                // Fallback: single-line SSE messages
                while ((delimIdx = buffer.indexOf('\n')) !== -1) {
                    const line = buffer.substring(0, delimIdx).trim();
                    buffer = buffer.substring(delimIdx + 1);
                    if (!line) continue;
                    if (line.startsWith('event: ')) {
                        const eventType = line.substring(7).trim();
                        const dataIdx = buffer.indexOf('\n');
                        if (dataIdx !== -1) {
                            const dataLine = buffer.substring(0, dataIdx).trim();
                            buffer = buffer.substring(dataIdx + 1);
                            if (dataLine.startsWith('data: ')) {
                                const dataStr = dataLine.substring(6);
                                try {
                                    const data = JSON.parse(dataStr);
                                    if (eventType === 'status') handleAgentStatus(data, document.getElementById('live-status-box'));
                                    else if (eventType === 'step') handleAgentStep(data, document.getElementById('agent-live-box'), document.getElementById('live-status-box'));
                                } catch (e) { /* ignore */ }
                            }
                        }
                    }
                }
                processChunk();
            });
        }
        processChunk();
    })
    .catch(err => {
        console.error('Agent run error:', err);
        agentRunning = false;
        liveInjectActive = false;
        resetRunButtons();
    });
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
    document.querySelectorAll('.panel').forEach(p => {
        if (p.id !== 'projects-panel' && p.id !== 'project-details-panel') {
            p.classList.add('hidden');
            p.classList.remove('active');
        }
    });
    fetch(`/api/projects/${projectId}`)
        .then(response => response.json())
        .then(project => {
            if (!_loadedProjects) _loadedProjects = [];
            const idx = _loadedProjects.findIndex(p => p.id === projectId);
            if (idx === -1) _loadedProjects.push(project);
            else _loadedProjects[idx] = project;
            const safeSet = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
            safeSet('run-project-id', project.id);
            const nameEl = document.getElementById('details-project-name');
            if (nameEl) nameEl.textContent = escapeHtml(project.name || 'Untitled');
            const nameFormEl = document.getElementById('details-project-name-form');
            if (nameFormEl) nameFormEl.value = project.name || '';
            const agentSettings = document.getElementById('details-agent-settings');
            if (agentSettings) agentSettings.style.display = 'block';
            const rootDir = project.rootDirectory || '';
            safeSet('details-root-dir', rootDir);
            safeSet('details-instructions', project.instructions || '');
            safeSet('details-pre-script', project.preScript || '');
            safeSet('details-post-script', project.postScript || '');
            buildToolSelector(project.enabled_tools || []);
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
    // Hide all other panels
    document.querySelectorAll('.panel').forEach(p => {
        if (p.id !== 'projects-panel') {
            p.classList.add('hidden');
            p.classList.remove('active');
        }
    });
    localStorage.removeItem('currentProjectId');
    currentProjectId = null;
    loadProjects();
}

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

function detailsAddNewPath() {
    const input = document.getElementById('details-new-path-input');
    const path = input.value.trim();
    if (!path) return;
    addPathToDetailsList(path);
    input.value = '';
    updateDetailsPatternsInput();
    autoSaveProject();
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
            else { loadProjects(); this.reset(); onAddModeChange(); }
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
                item.setAttribute('role', 'listitem');
                item.setAttribute('tabindex', '0');
                item.innerHTML = `<span>${escapeHtml(chat.title || 'New Chat')}</span>`;
                item.onclick = () => openChat(chat.id);
                item.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openChat(chat.id); } };
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
    // Poll agent steps during active runs (every 2s)
    setInterval(() => { if (agentRunning) pollAgentSteps(); }, 2000);

    // Keyboard navigation for sidebar tabs
    const sidebarNav = document.querySelector('.sidebar-nav');
    if (sidebarNav) {
        sidebarNav.addEventListener('keydown', (e) => {
            const buttons = Array.from(sidebarNav.querySelectorAll('.tab-btn'));
            const current = document.activeElement;
            const idx = buttons.indexOf(current);
            if (idx === -1) return;

            let nextIdx;
            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                e.preventDefault();
                nextIdx = (idx + 1) % buttons.length;
            } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                e.preventDefault();
                nextIdx = (idx - 1 + buttons.length) % buttons.length;
            } else if (e.key === 'Home') {
                e.preventDefault();
                nextIdx = 0;
            } else if (e.key === 'End') {
                e.preventDefault();
                nextIdx = buttons.length - 1;
            } else {
                return;
            }
            buttons[nextIdx].focus();
            buttons[nextIdx].click();
        });
    }

    // Close modals on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const actionsModal = document.getElementById('actions-modal');
            const rootModal = document.getElementById('root-path-confirmation-modal');
            if (actionsModal && actionsModal.style.display === 'flex') {
                closeActionsModal();
            }
            if (rootModal && rootModal.style.display === 'flex') {
                cancelRootPathChange();
            }
        }
    });

    // Trap focus in modals
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('keydown', (e) => {
            if (e.key !== 'Tab') return;
            const focusable = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey) {
                if (document.activeElement === first) {
                    e.preventDefault();
                    last.focus();
                }
            } else {
                if (document.activeElement === last) {
                    e.preventDefault();
                    first.focus();
                }
            }
        });
    });
});