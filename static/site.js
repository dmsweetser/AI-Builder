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
    renderJobs();
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
            else if (panelId === 'jobs-panel') renderJobs();
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
    if (tabName === 'jobs') renderJobs();
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
        var liveBtn = document.createElement('button');
        liveBtn.className = 'btn btn-sm btn-info';
        liveBtn.textContent = '📺 LIVE';
        liveBtn.onclick = function(e) { e.stopPropagation(); showLiveViewForJob(project.job_id || ''); };
        var runBtn = document.createElement('button');
        runBtn.className = 'btn btn-sm btn-primary';
        runBtn.textContent = 'RUN';
        runBtn.onclick = function(e) { e.stopPropagation(); runProject(project.id); };
        var stopBtn = document.createElement('button');
        stopBtn.className = 'btn btn-sm btn-danger';
        stopBtn.textContent = 'STOP';
        stopBtn.onclick = function(e) { e.stopPropagation(); stopProject(project.id); };
        if (status === 'running') {
            actions.appendChild(liveBtn);
            actions.appendChild(stopBtn);
        } else {
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

function _doRunProject(projectId, overrideInstruction) {
    var rootDir = document.getElementById('details-root-dir') ? document.getElementById('details-root-dir').value : '';
    if (!rootDir) {
        var project = (_uiState.projects || []).find(function(p) { return p.id === projectId; });
        if (project) rootDir = project.rootDirectory || '';
    }
    if (!rootDir) { showNotification('Please set a root directory first.', 'info'); return; }
    
    var instructions = overrideInstruction || (document.getElementById('details-instructions') ? document.getElementById('details-instructions').value : '');
    
    // Show live view
    var configSection = document.getElementById('project-config-section');
    var agentLive = document.getElementById('agent-live-container');
    if (configSection) configSection.style.display = 'none';
    if (agentLive) agentLive.style.display = 'block';
    var statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'RUNNING'; statusText.style.color = 'var(--success)'; }
    var agentBox = document.getElementById('agent-live-box');
    if (agentBox) agentBox.innerHTML = '';
    var runBtn = document.getElementById('details-run-btn');
    var stopBtn = document.getElementById('details-stop-btn');
    var liveStopBtn = document.getElementById('live-stop-btn');
    var refreshBtn = document.getElementById('live-refresh-btn');
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = '<span class="run-spinner"></span> RUNNING...'; }
    if (stopBtn) stopBtn.style.display = 'inline-block';
    if (liveStopBtn) liveStopBtn.style.display = 'inline-block';
    if (refreshBtn) refreshBtn.style.display = 'inline-block';
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions or questions...'; }
    if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
    
    if (agentLive) {
        setTimeout(function() { agentLive.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 100);
    }
    
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
        if (agentLive) {
            agentLive.dataset.jobId = data.job_id;
            agentLive.dataset.projectId = projectId;
            agentLive.dataset.outputDir = data.output_dir;
        }
        _startPolling(data.job_id, data.output_dir, agentBox, projectId);
        // Refresh state to pick up new running job
        fetchState();
    })
    .catch(function(err) {
        console.error('Agent run error:', err);
        var errEntry = document.createElement('div');
        errEntry.className = 'step-entry error';
        errEntry.textContent = 'ERROR: ' + err.message;
        if (agentBox.firstChild) agentBox.insertBefore(errEntry, agentBox.firstChild);
        else agentBox.appendChild(errEntry);
        agentBox.scrollTop = 0;
        resetRunButtons();
        if (stopBtn) stopBtn.style.display = 'none';
        var injectInputErr = document.getElementById('live-inject-input');
        var injectBtnErr = document.getElementById('live-inject-btn');
        if (injectInputErr) { injectInputErr.disabled = false; injectInputErr.placeholder = 'Retry or inject instructions...'; }
        if (injectBtnErr) { injectBtnErr.disabled = false; injectBtnErr.textContent = 'INJECT'; }
    });
}

// === File-Based Polling ===
function _startPolling(jobId, outputDir, agentBox, projectId, fastPoll) {
    if (_pollInterval) clearInterval(_pollInterval);
    var interval = fastPoll ? 5000 : 30000;
    var pollJobId = jobId;
    var pollProjectId = projectId;
    
    _pollOnce(jobId, outputDir, agentBox, projectId);
    
    _pollInterval = setInterval(function() {
        var activeContainer = document.getElementById('agent-live-container');
        if (activeContainer && activeContainer.dataset.jobId !== pollJobId) {
            clearInterval(_pollInterval);
            _pollInterval = null;
            return;
        }
        _pollOnce(pollJobId, outputDir, agentBox, pollProjectId);
    }, interval);
}

function _pollOnce(jobId, outputDir, agentBox, projectId) {
    var stepsPromise = fetch('/api/job/' + jobId + '/steps')
        .then(function(r) { return r.json(); })
        .catch(function() { return { steps: [], count: 0 }; });
    var statusPromise = fetch('/api/job/' + jobId + '/status')
        .then(function(r) { return r.json(); })
        .catch(function() { return {}; });
    var pendingPromise = outputDir
        ? fetch('/api/tools/pending', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({project_output_dir: outputDir})
        }).then(function(r) { return r.json(); }).catch(function() { return []; })
        : Promise.resolve([]);
    
    Promise.all([stepsPromise, statusPromise, pendingPromise])
        .then(function(results) {
            var stepsData = results[0];
            var statusData = results[1];
            var pendingTools = results[2] || [];
            var steps = stepsData.steps || [];
            var count = stepsData.count || 0;
            var hasPendingTools = pendingTools && pendingTools.length > 0;
            var hasPendingUserInput = count > 0 && steps[count-1] && steps[count-1].tool === 'request_user_input';
            _renderAllSteps(jobId, outputDir, agentBox, statusData, hasPendingTools, hasPendingUserInput, projectId);
        })
        .catch(function(err) { console.error('Polling error:', err); });
}

function _renderAllSteps(jobId, outputDir, agentBox, statusData, hasPendingTools, hasPendingUserInput, projectId) {
    if (!agentBox) {
        agentBox = document.getElementById('agent-live-box');
    }
    if (!agentBox) { console.warn('agent-live-box not found'); return; }
    
    fetch('/api/job/' + jobId + '/steps')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var steps = data.steps || [];
            var count = data.count || 0;
            agentBox.innerHTML = '';
            for (var i = 0; i < count; i++) {
                var step = steps[i];
                if (step) _renderStep(step, agentBox);
            }
            if (hasPendingTools && outputDir) _showPendingApproval(jobId, outputDir, agentBox);
            if (hasPendingUserInput) _showPendingUserInput(statusData, agentBox);
            
            var st = document.getElementById('agent-status-text');
            if (st) {
                if (hasPendingTools) {
                    st.textContent = 'PENDING TOOL APPROVAL';
                    st.style.color = 'var(--warning)';
                    st.style.fontWeight = 'bold';
                } else if (hasPendingUserInput) {
                    st.textContent = 'AWAITING INPUT';
                    st.style.color = 'var(--warning)';
                    st.style.fontWeight = 'bold';
                }
            }
            
            var status = statusData.status || 'running';
            if (status !== 'running' && !hasPendingTools && !hasPendingUserInput) {
                if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
                resetRunButtons();
                var stopBtn = document.getElementById('details-stop-btn');
                if (stopBtn) stopBtn.style.display = 'none';
                var liveStopBtn = document.getElementById('live-stop-btn');
                if (liveStopBtn) liveStopBtn.style.display = 'none';
                if (st) {
                    if (status === 'completed') { st.textContent = 'COMPLETED'; st.style.color = 'var(--success)'; }
                    else if (status === 'error') { st.textContent = 'ERROR'; st.style.color = 'var(--danger)'; }
                    else if (status === 'stopped') { st.textContent = 'STOPPED'; st.style.color = 'var(--text-muted)'; }
                    else if (status === 'max_steps_reached') { st.textContent = 'MAX STEPS'; st.style.color = 'var(--warning)'; }
                    else { st.textContent = status.toUpperCase(); }
                }
                var ii = document.getElementById('live-inject-input');
                var ib = document.getElementById('live-inject-btn');
                if (ii) { ii.disabled = false; ii.placeholder = 'Continue with new instructions...'; }
                if (ib) { ib.disabled = false; ib.textContent = 'INJECT'; }
            } else {
                var ii = document.getElementById('live-inject-input');
                var ib = document.getElementById('live-inject-btn');
                if (ii) { ii.disabled = false; ii.placeholder = 'Continue with new instructions...'; }
                if (ib) { ib.disabled = false; ib.textContent = 'INJECT'; }
            }
        })
        .catch(function(err) {
            console.error('Failed to load steps:', err);
            var ii = document.getElementById('live-inject-input');
            var ib = document.getElementById('live-inject-btn');
            if (ii) { ii.disabled = false; ii.placeholder = 'Continue with new instructions...'; }
            if (ib) { ib.disabled = false; ib.textContent = 'INJECT'; }
        });
}

function _renderStep(step, agentBox) {
    if (!agentBox) return;
    var runningEntry = document.getElementById('tool-running-' + step.step);
    if (runningEntry) runningEntry.remove();
    var stepCount = document.getElementById('agent-step-count');
    if (stepCount) stepCount.textContent = 'Step ' + step.step;
    
    var entry = document.createElement('div');
    entry.className = 'step-entry';
    
    if (step.tool === 'respond_to_user') {
        entry.classList.add('llm-step');
        entry.style.borderLeftColor = 'var(--info)';
        var toolDiv = document.createElement('div');
        toolDiv.className = 'step-tool';
        toolDiv.style.color = 'var(--info)';
        toolDiv.textContent = '💬 AI Response';
        entry.appendChild(toolDiv);
        var respContent = step.result ? (step.result.content || '') : '';
        var resultDiv = document.createElement('div');
        resultDiv.className = 'step-result';
        resultDiv.textContent = respContent;
        entry.appendChild(resultDiv);
    } else if (step.tool === 'request_user_input') {
        entry.classList.add('pending-approval');
        var toolDiv2 = document.createElement('div');
        toolDiv2.className = 'step-tool';
        toolDiv2.style.color = 'var(--warning)';
        toolDiv2.textContent = '⏸ REQUEST USER INPUT';
        entry.appendChild(toolDiv2);
        var reqQuestion = step.result ? (step.result.content || 'The agent is waiting for your input.') : 'The agent is waiting for your input.';
        var resultDiv2 = document.createElement('div');
        resultDiv2.className = 'step-result';
        resultDiv2.style.cssText = 'color:var(--warning);white-space:pre-wrap;';
        resultDiv2.textContent = reqQuestion;
        entry.appendChild(resultDiv2);
        var hintDiv = document.createElement('div');
        hintDiv.className = 'step-result';
        hintDiv.style.cssText = 'color:var(--text-muted);font-size:11px;margin-top:6px;';
        hintDiv.textContent = '👉 The agent is waiting for your response. Type instructions below and click INJECT or RUN to continue';
        entry.appendChild(hintDiv);
    } else if (step.tool === 'llm_call') {
        var msgCount = step.params ? step.params.messages : 0;
        entry.classList.add('llm-step');
        var rawReq = step.raw_request || '';
        var rawResp = step.raw_response || '';
        var hasRaw = rawReq.length > 0 || rawResp.length > 0;
        var toolDiv3 = document.createElement('div');
        toolDiv3.className = 'step-tool';
        toolDiv3.textContent = '🤔 Thinking...';
        entry.appendChild(toolDiv3);
        var resultDiv3 = document.createElement('div');
        resultDiv3.className = 'step-result';
        resultDiv3.textContent = '...';
        entry.appendChild(resultDiv3);
        // Fetch the live response from current_response.txt
        (function fetchLiveResponse(container, jobId, resultEl) {
            fetch('/api/agent/response/' + jobId)
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var content = data.content || '';
                    if (content.trim()) {
                        // Check if it contains a complete tool call block
                        var toolStart = content.indexOf('[TOOL_START]');
                        var toolEnd = content.indexOf('[TOOL_END]');
                        if (toolStart !== -1 && toolEnd !== -1 && toolEnd > toolStart) {
                            // Valid tool call — parse and display it
                            var toolBlock = content.substring(toolStart, toolEnd + '[TOOL_END]'.length);
                            var beforeTool = content.substring(0, toolStart).trim();
                            var parsed = _parseToolCall(toolBlock);
                            resultEl.innerHTML = '';
                            if (beforeTool) {
                                var prefix = document.createElement('div');
                                prefix.style.cssText = 'color:var(--text-muted);font-size:8px;margin-bottom:4px;font-style:italic;';
                                prefix.textContent = beforeTool.substring(0, 300) + (beforeTool.length > 300 ? '...' : '');
                                resultEl.appendChild(prefix);
                            }
                            if (parsed) {
                                var toolLabel = document.createElement('div');
                                toolLabel.style.cssText = 'color:var(--mc-gold);font-weight:bold;margin-bottom:2px;';
                                toolLabel.textContent = '⚙️ ' + (parsed.name || 'unknown') + '(' + (JSON.stringify(parsed.params || {}).substring(0, 120)) + (parsed.params ? (JSON.stringify(parsed.params).length > 120 ? '...' : '') : '') + ')';
                                resultEl.appendChild(toolLabel);
                                if (parsed.code) {
                                    var codePre = document.createElement('pre');
                                    codePre.style.cssText = 'background:var(--mc-bg);padding:6px;border:1px solid var(--mc-border);font-size:8px;max-height:100px;overflow:auto;margin-top:2px;white-space:pre-wrap;';
                                    codePre.textContent = parsed.code.substring(0, 500) + (parsed.code.length > 500 ? '...' : '');
                                    resultEl.appendChild(codePre);
                                }
                            }
                        } else {
                            // Not a valid tool call yet — show raw streaming text
                            var preview = content.length > 400 ? content.substring(0, 400) + '...' : content;
                            resultEl.textContent = preview;
                        }
                    } else {
                        resultEl.textContent = 'Waiting for response...';
                    }
                })
                .catch(function() { resultEl.textContent = 'Response unavailable'; });
        })(entry, _activeJobId || '', resultDiv3);
        if (hasRaw) {
            var rawDiv = document.createElement('div');
            rawDiv.style.cssText = 'margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;';
            if (rawReq.length > 0) {
                var details1 = document.createElement('details');
                details1.className = 'raw-data-block';
                var summary1 = document.createElement('summary');
                summary1.className = 'raw-summary';
                summary1.textContent = '📤 Raw Request (' + rawReq.length + ' chars)';
                details1.appendChild(summary1);
                var contentDiv1 = document.createElement('div');
                contentDiv1.className = 'raw-content';
                var pre1 = document.createElement('pre');
                var code1 = document.createElement('code');
                code1.textContent = rawReq;
                pre1.appendChild(code1);
                contentDiv1.appendChild(pre1);
                details1.appendChild(contentDiv1);
                rawDiv.appendChild(details1);
            }
            if (rawResp.length > 0) {
                var details2 = document.createElement('details');
                details2.className = 'raw-data-block';
                var summary2 = document.createElement('summary');
                summary2.className = 'raw-summary';
                summary2.textContent = '📥 Raw Response (' + rawResp.length + ' chars)';
                details2.appendChild(summary2);
                var contentDiv2 = document.createElement('div');
                contentDiv2.className = 'raw-content';
                var pre2 = document.createElement('pre');
                var code2 = document.createElement('code');
                code2.textContent = rawResp;
                pre2.appendChild(code2);
                contentDiv2.appendChild(pre2);
                details2.appendChild(contentDiv2);
                rawDiv.appendChild(details2);
            }
            entry.appendChild(rawDiv);
        }
    } else if (step.tool === 'format_retry') {
        entry.classList.add('llm-step');
        var toolDiv4 = document.createElement('div');
        toolDiv4.className = 'step-tool';
        toolDiv4.style.color = 'var(--warning)';
        toolDiv4.textContent = '⚠ Format reminder sent';
        entry.appendChild(toolDiv4);
        var resultDiv4 = document.createElement('div');
        resultDiv4.className = 'step-result';
        resultDiv4.style.color = 'var(--warning)';
        resultDiv4.textContent = step.result ? step.result.content : '';
        entry.appendChild(resultDiv4);
    } else if (step.tool === 'task_completed') {
        var summary = step.result ? (step.result.content || '') : '';
        var toolDiv5 = document.createElement('div');
        toolDiv5.className = 'step-tool';
        toolDiv5.style.cssText = 'color:var(--success);font-weight:bold;font-size:16px;';
        toolDiv5.textContent = '🎉 TASK COMPLETED';
        entry.appendChild(toolDiv5);
        if (step.rationale) {
            var rationaleDiv = document.createElement('div');
            rationaleDiv.className = 'step-rationale';
            rationaleDiv.innerText = '💡 ' + step.rationale;
            entry.appendChild(rationaleDiv);
        }
        var resultDiv5 = document.createElement('div');
        resultDiv5.className = 'step-result';
        resultDiv5.style.cssText = 'margin-top:6px;padding:8px;background:rgba(46,204,113,0.1);border:1px solid var(--success);border-radius:4px;';
        resultDiv5.textContent = summary;
        entry.appendChild(resultDiv5);
        if (step.params && step.params.summary) {
            var paramsDiv = document.createElement('div');
            paramsDiv.className = 'step-result';
            paramsDiv.style.cssText = 'margin-top:6px;font-style:italic;color:var(--text-muted);';
            paramsDiv.textContent = 'Summary: ' + step.params.summary;
            entry.appendChild(paramsDiv);
        }
    } else {
        var ok = step.result && step.result.success !== false;
        var resultPreview = step.result ? (step.result.content || '') : 'no result';
        var errorMsg = step.result ? (step.result.error || '') : '';
        entry.classList.add(ok ? 'success' : 'error');
        var toolDiv6 = document.createElement('div');
        toolDiv6.className = 'step-tool';
        toolDiv6.textContent = (ok ? '✓' : '✗') + ' ' + step.tool;
        entry.appendChild(toolDiv6);
        if (step.rationale) {
            var rationaleDiv2 = document.createElement('div');
            rationaleDiv2.className = 'step-rationale';
            rationaleDiv2.innerText = '💡 ' + step.rationale;
            entry.appendChild(rationaleDiv2);
        }
        if (step.params && Object.keys(step.params).length) {
            var paramsDiv2 = document.createElement('div');
            paramsDiv2.className = 'step-params';
            paramsDiv2.textContent = JSON.stringify(step.params);
            entry.appendChild(paramsDiv2);
        }
        if (errorMsg && !ok) {
            var errDiv = document.createElement('div');
            errDiv.className = 'step-result step-result-error';
            errDiv.style.cssText = 'color:var(--mc-nether);font-weight:bold;margin-top:4px;';
            errDiv.textContent = 'ERROR: ' + errorMsg;
            entry.appendChild(errDiv);
        }
        if (resultPreview) {
            var resultDiv6 = document.createElement('div');
            resultDiv6.className = 'step-result';
            resultDiv6.textContent = resultPreview;
            entry.appendChild(resultDiv6);
        }
    }
    agentBox.appendChild(entry);
    agentBox.scrollTop = agentBox.scrollHeight;
}

function _showPendingApproval(jobId, outputDir, agentBox) {
    var existingEntry = document.getElementById('pending-approval-entry');
    if (existingEntry) {
        var actionsDiv = document.getElementById('pending-approval-actions');
        if (actionsDiv) {
            actionsDiv.innerHTML = '';
            _loadPendingTools(actionsDiv, outputDir, jobId);
        }
        return;
    }
    var entry = document.createElement('div');
    entry.className = 'step-entry pending-approval';
    entry.id = 'pending-approval-entry';
    var toolDiv = document.createElement('div');
    toolDiv.className = 'step-tool';
    toolDiv.textContent = '⏸ AGENT WAITING — PENDING TOOL APPROVAL';
    entry.appendChild(toolDiv);
    var resultDiv = document.createElement('div');
    resultDiv.className = 'step-result';
    resultDiv.textContent = 'The agent cannot proceed until you approve or reject new tools.';
    entry.appendChild(resultDiv);
    var actionsDiv = document.createElement('div');
    actionsDiv.id = 'pending-approval-actions';
    actionsDiv.style.cssText = 'margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;';
    entry.appendChild(actionsDiv);
    agentBox.appendChild(entry);
    agentBox.scrollTop = agentBox.scrollHeight;
    var statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'PENDING TOOL APPROVAL'; statusText.style.color = 'var(--warning)'; statusText.style.fontWeight = 'bold'; }
    _loadPendingTools(actionsDiv, outputDir, jobId);
}

function _loadPendingTools(actionsDiv, outputDir, jobId) {
    fetch('/api/tools/pending', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project_output_dir: outputDir})
    })
    .then(function(r) { return r.json(); })
    .then(function(pendingTools) {
        if (!pendingTools || pendingTools.length === 0) {
            actionsDiv.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">No pending tools.</div>';
            return;
        }
        pendingTools.forEach(function(tool) {
            var toolEntry = document.createElement('div');
            toolEntry.style.cssText = 'background:var(--muted);padding:12px;border-radius:6px;margin-top:8px;width:100%;';
            var nameDiv = document.createElement('div');
            nameDiv.style.cssText = 'font-weight:bold;margin-bottom:4px;';
            nameDiv.textContent = '📦 ' + tool.name;
            toolEntry.appendChild(nameDiv);
            var descDiv = document.createElement('div');
            descDiv.style.cssText = 'font-size:12px;color:var(--text-muted);margin-bottom:4px;';
            descDiv.textContent = tool.description || '';
            toolEntry.appendChild(descDiv);
            if (tool.code) {
                var codePre = document.createElement('pre');
                codePre.style.cssText = 'background:var(--bg-primary);padding:8px;border-radius:4px;max-height:200px;overflow:auto;font-size:11px;margin:8px 0;white-space:pre-wrap;';
                codePre.textContent = tool.code;
                toolEntry.appendChild(codePre);
            }
            var btnRow = document.createElement('div');
            btnRow.style.cssText = 'display:flex;gap:8px;margin-top:8px;';
            var approveBtn = document.createElement('button');
            approveBtn.className = 'btn btn-success btn-sm';
            approveBtn.textContent = '✅ APPROVE';
            approveBtn.dataset.url = '/api/tools/pending/' + encodeURIComponent(tool.name) + '/approve';
            approveBtn.dataset.outputDir = outputDir;
            approveBtn.dataset.jobId = jobId;
            btnRow.appendChild(approveBtn);
            var rejectBtn = document.createElement('button');
            rejectBtn.className = 'btn btn-danger btn-sm';
            rejectBtn.textContent = '❌ REJECT';
            rejectBtn.dataset.url = '/api/tools/pending/' + encodeURIComponent(tool.name) + '/reject';
            rejectBtn.dataset.outputDir = outputDir;
            btnRow.appendChild(rejectBtn);
            toolEntry.appendChild(btnRow);
            actionsDiv.appendChild(toolEntry);
        });
    })
    .catch(function(err) { console.error('Failed to load pending tools:', err); });
}

function _showPendingUserInput(statusData, agentBox) {
    if (!agentBox) return;
    if (document.getElementById('pending-user-input-entry')) return;
    var entry = document.createElement('div');
    entry.className = 'step-entry pending-approval';
    entry.id = 'pending-user-input-entry';
    var questionText = statusData.question || statusData.summary || 'The agent is waiting for your input.';
    var toolDiv = document.createElement('div');
    toolDiv.className = 'step-tool';
    toolDiv.style.color = 'var(--warning)';
    toolDiv.textContent = '⏸ AGENT NEEDS HELP';
    entry.appendChild(toolDiv);
    var resultDiv = document.createElement('div');
    resultDiv.className = 'step-result';
    resultDiv.style.cssText = 'color:var(--warning);white-space:pre-wrap;';
    resultDiv.textContent = questionText;
    entry.appendChild(resultDiv);
    var hintDiv = document.createElement('div');
    hintDiv.className = 'step-result';
    hintDiv.style.cssText = 'color:var(--text-muted);font-size:11px;margin-top:6px;';
    hintDiv.textContent = '👉 Type instructions below and click INJECT or RUN to continue';
    entry.appendChild(hintDiv);
    agentBox.appendChild(entry);
    agentBox.scrollTop = agentBox.scrollHeight;
    var statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'AWAITING INPUT'; statusText.style.color = 'var(--warning)'; }
}

// Resend the last request
function resendLastRequest() {
    var jobId = _activeJobId;
    if (!jobId) { showNotification('No active job to resend', 'warning'); return; }
    var resendBtn = document.getElementById('live-resend-btn');
    if (!resendBtn) return;
    resendBtn.disabled = true;
    resendBtn.textContent = 'RESENDING...';
    var agentBox = document.getElementById('agent-live-box');
    if (agentBox) {
        var resendEntry = document.createElement('div');
        resendEntry.className = 'step-entry';
        resendEntry.style.borderLeftColor = 'var(--warning)';
        resendEntry.style.background = 'rgba(252, 219, 5, 0.1)';
        resendEntry.innerHTML = '<div class="step-tool" style="color:var(--warning);">🔄 RESENDING LAST REQUEST...</div>';
        agentBox.appendChild(resendEntry);
        agentBox.scrollTop = agentBox.scrollHeight;
    }
    fetch('/api/agent/resend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId })
    })
    .then(function(response) {
        if (!response.ok) throw new Error('Failed to resend');
        return response.json();
    })
    .then(function(data) {
        if (agentBox) {
            resendEntry.innerHTML = '<div class="step-tool" style="color:var(--success);">✅ Request resent successfully</div>';
            agentBox.scrollTop = agentBox.scrollHeight;
        }
        var statusText = document.getElementById('agent-status-text');
        if (statusText) { statusText.textContent = 'RESENT'; statusText.style.color = 'var(--success)'; }
        fetchState();
        setTimeout(function() {
            resendBtn.disabled = false;
            resendBtn.textContent = 'RESEND';
        }, 2000);
    })
    .catch(function(err) {
        console.error('Failed to resend:', err);
        if (agentBox) {
            resendEntry.innerHTML = '<div class="step-tool" style="color:var(--danger);">❌ Failed to resend: ' + err.message + '</div>';
            agentBox.scrollTop = agentBox.scrollHeight;
        }
        resendBtn.disabled = false;
        resendBtn.textContent = 'RESEND';
    });
}

// Agent inject enter key handler
document.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        var injectInput = document.getElementById('live-inject-input');
        var injectBtn = document.getElementById('live-inject-btn');
        if (injectInput && document.activeElement === injectInput && injectBtn && !injectBtn.disabled) {
            e.preventDefault();
            injectLiveInstruction();
        }
    }
});

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
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
    var promises = [fetch('/api/queue/running/stop', { method: 'POST' }).catch(function() {})];
    Promise.all(promises).then(function() {
        var container = document.getElementById('agent-live-container');
        if (container) { container.style.display = 'block'; }
        var configSection = document.getElementById('project-config-section');
        if (configSection) configSection.style.display = 'block';
        var stopBtn = document.getElementById('details-stop-btn');
        if (stopBtn) stopBtn.style.display = 'none';
        var viewLiveBtn = document.getElementById('details-live-btn');
        if (viewLiveBtn) viewLiveBtn.style.display = 'inline-block';
        var liveStopBtn = document.getElementById('live-stop-btn');
        if (liveStopBtn) liveStopBtn.style.display = 'none';
        fetchState();
        loadJobs();
        resetRunButtons();
    })
    .catch(function(err) { console.error('Failed to stop project:', err); });
}

function stopCurrentJob() {
    var container = document.getElementById('agent-live-container');
    var jobId = container ? container.dataset.jobId : null;
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
    var promises = [fetch('/api/queue/running/stop', { method: 'POST' }).catch(function() {})];
    if (jobId) promises.push(fetch('/api/agent/stop/' + jobId, { method: 'POST' }).catch(function() {}));
    Promise.all(promises).then(function() {
        if (container) {
            container.innerHTML = '';
            delete container.dataset.jobId;
            delete container.dataset.projectId;
            delete container.dataset.outputDir;
        }
        var liveStopBtn = document.getElementById('live-stop-btn');
        if (liveStopBtn) liveStopBtn.style.display = 'none';
        var statusText = document.getElementById('agent-status-text');
        if (statusText) { statusText.textContent = 'STOPPED'; statusText.style.color = 'var(--text-muted)'; }
        fetchState();
        loadJobs();
        resetRunButtons();
    })
    .catch(function(err) { console.error('Failed to stop job:', err); });
}

function continueAgentRunWithInstruction(projectId, prevJobId, newInstruction) {
    if (!projectId) return;
    if (!prevJobId) { _doRunProject(projectId, newInstruction); return; }
    var enabledTools = (AVAILABLE_TOOLS && AVAILABLE_TOOLS.length > 0) ? AVAILABLE_TOOLS.slice() : [];
    var runBtn = document.getElementById('details-run-btn');
    var stopBtn = document.getElementById('details-stop-btn');
    var liveStopBtn = document.getElementById('live-stop-btn');
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = '<span class="run-spinner"></span> RUNNING...'; }
    if (stopBtn) stopBtn.style.display = 'inline-block';
    if (liveStopBtn) liveStopBtn.style.display = 'inline-block';
    var configSection = document.getElementById('project-config-section');
    var agentLive = document.getElementById('agent-live-container');
    if (configSection) configSection.style.display = 'none';
    if (agentLive) agentLive.style.display = 'block';
    var agentBox = document.getElementById('agent-live-box');
    if (agentBox) agentBox.innerHTML = '';
    var statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'CONTINUING...'; statusText.style.color = 'var(--info)'; }
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions or questions...'; }
    if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
    fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, instructions: newInstruction, continue_from_job: prevJobId })
    })
    .then(function(response) {
        if (!response.ok) throw new Error('Failed to start continued agent run');
        return response.json();
    })
    .then(function(data) {
        if (data.error) throw new Error(data.error);
        _activeJobId = data.job_id;
        _startPolling(data.job_id, data.output_dir, agentBox, projectId);
        fetchState();
    })
    .catch(function(err) {
        console.error('Agent run error:', err);
        if (agentBox) { var errEntry = document.createElement('div'); errEntry.className = 'step-entry error'; errEntry.textContent = 'ERROR: ' + err.message; agentBox.appendChild(errEntry); agentBox.scrollTop = agentBox.scrollHeight; }
        var iInput2 = document.getElementById('live-inject-input');
        var iBtn2 = document.getElementById('live-inject-btn');
        if (iInput2) { iInput2.disabled = false; iInput2.placeholder = 'Continue with new instructions...'; }
        if (iBtn2) { iBtn2.disabled = false; iBtn2.textContent = 'INJECT'; }
    });
}

function resetRunButtons() {
    var runBtn = document.getElementById('details-run-btn');
    var stopBtn = document.getElementById('details-stop-btn');
    if (runBtn) {
        runBtn.disabled = false;
        runBtn.innerHTML = 'RUN AI BUILDER';
    } else {
        // Run button not found — likely because the live view is showing
        // and the config section is hidden. Restore the UI to the config view.
        var configSection = document.getElementById('project-config-section');
        var agentLive = document.getElementById('agent-live-container');
        if (configSection) configSection.style.display = 'block';
        if (agentLive) {
            agentLive.style.display = 'none';
            var statusText = document.getElementById('agent-status-text');
            if (statusText) { statusText.textContent = 'AGENT READY'; statusText.style.color = ''; }
        }
    }
    if (stopBtn) stopBtn.style.display = 'none';
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Continue with new instructions...'; }
    if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
}

function selectProject(projectId) {
    resetRunButtons();
    currentProjectId = projectId;
    document.getElementById('projects-panel').classList.remove('active');
    document.getElementById('project-details-panel').classList.add('active');
    window.scrollTo(0, 0);
    var configSection = document.getElementById('project-config-section');
    var agentLive = document.getElementById('agent-live-container');
    if (configSection) configSection.style.display = 'block';
    if (agentLive) agentLive.style.display = 'none';
    
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
    if (activeJob) {
        var liveBtn = document.getElementById('details-live-btn');
        var stopBtn = document.getElementById('details-stop-btn');
        if (liveBtn) liveBtn.style.display = 'inline-block';
        if (stopBtn) stopBtn.style.display = 'inline-block';
    }
}

function goBackToProjects() {
    saveProjectChanges().finally(function() {
        _goBackToProjects();
    });
}

function _goBackToProjects() {
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
    _activeJobId = null;
    var container = document.getElementById('agent-live-container');
    if (container) {
        container.style.display = 'none';
        container.innerHTML = '';
        delete container.dataset.jobId;
        delete container.dataset.projectId;
        delete container.dataset.outputDir;
    }
    var configSection = document.getElementById('project-config-section');
    var agentLive = document.getElementById('agent-live-container');
    if (configSection) configSection.style.display = 'block';
    if (agentLive) agentLive.style.display = 'none';
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

// === Jobs ===
function loadJobs() {
    // Reload state from the consolidated endpoint, then re-render
    fetchState().then(function() { renderJobs(); });
}

function renderJobs() {
    var queueData = _uiState.queue || {};
    var history = _uiState.history || [];
    renderJobsFromData(queueData, history);
}

function renderJobsFromData(queueData, history) {
    var list = document.getElementById('jobs-list');
    if (!list) return;
    list.innerHTML = '';
    var items = history.slice();
    var historyIds = {};
    items.forEach(function(i) { historyIds[i.job_id] = true; });
    if (queueData.running && !historyIds[queueData.running.job_id]) items.unshift(queueData.running);
    if (queueData.queued) queueData.queued.forEach(function(j) { if (!historyIds[j.job_id]) items.push(j); });
    if (!items.length) { list.innerHTML = '<div class="note">NO JOBS FOUND.</div>'; return; }
    items.forEach(function(job) {
        var item = document.createElement('div');
        item.className = 'history-item';
        item.dataset.jobId = job.job_id;
        item.onclick = function() { toggleJobSteps(job.job_id); };
        var statusClass = 'completed';
        var statusText = job.status || 'unknown';
        if (statusText === 'running') statusClass = 'running';
        else if (statusText === 'pending_approval') statusClass = 'queued';
        else if (statusText === 'pending_user_input') statusClass = 'queued';
        else if (statusText === 'error') statusClass = 'error';
        else if (statusText === 'stopped') statusClass = 'stopped';
        else if (statusText === 'max_steps_reached') statusClass = 'queued';
        
        var header = document.createElement('div');
        header.className = 'history-item-header';
        var nameSpan = document.createElement('span');
        nameSpan.className = 'history-item-name';
        nameSpan.textContent = job.project_name || 'Unknown Project';
        header.appendChild(nameSpan);
        var statusSpan = document.createElement('span');
        statusSpan.className = 'project-item-status ' + statusClass;
        statusSpan.textContent = statusText.toUpperCase().replace('_', ' ');
        header.appendChild(statusSpan);
        item.appendChild(header);
        
        var idDiv = document.createElement('div');
        idDiv.className = 'history-item-id';
        idDiv.textContent = job.job_id.substring(0, 8) + '...';
        item.appendChild(idDiv);
        
        if (job.error) {
            var errDiv = document.createElement('div');
            errDiv.className = 'history-item-error';
            errDiv.textContent = 'Error: ' + job.error;
            item.appendChild(errDiv);
        }
        if (job.summary) {
            var sumDiv = document.createElement('div');
            sumDiv.className = 'history-item-summary';
            sumDiv.textContent = 'Summary: ' + job.summary.substring(0, 150);
            item.appendChild(sumDiv);
        }
        // Use step_history length from state if available, otherwise fall back
        // to job.steps or job.step_count from the queue/history payload
        var stepCount = 0;
        if (job.step_history && job.step_history.length > 0) {
            stepCount = job.step_history.length;
        } else {
            stepCount = job.steps || 0;
        }
        if (stepCount > 0) {
            var stepsBtn = document.createElement('button');
            stepsBtn.className = 'btn btn-xs btn-secondary';
            stepsBtn.textContent = '▼ SHOW STEPS (' + stepCount + ')';
            stepsBtn.onclick = function(e) { e.stopPropagation(); toggleJobSteps(job.job_id); };
            item.appendChild(stepsBtn);
            var stepsList = document.createElement('div');
            stepsList.id = 'job-steps-' + job.job_id;
            stepsList.className = 'job-steps-list';
            stepsList.style.display = 'none';
            stepsList.innerHTML = '<div style="padding:8px;color:var(--text-muted);">Loading steps...</div>';
            item.appendChild(stepsList);
        } else if (job.step_count !== undefined) {
            var stepCountDiv = document.createElement('div');
            stepCountDiv.style.cssText = 'font-size:11px;color:var(--text-muted);margin-top:4px;';
            var displayCount = (job.step_history && job.step_history.length > 0) ? job.step_history.length : (job.steps || 0);
            stepCountDiv.textContent = 'Completed ' + displayCount + ' steps';
            item.appendChild(stepCountDiv);
        }
        var delBtn = document.createElement('button');
        delBtn.className = 'btn btn-xs btn-secondary';
        delBtn.style.cssText = 'margin-top:6px;';
        delBtn.textContent = 'DELETE';
        delBtn.onclick = function(e) { e.stopPropagation(); deleteJob(job.job_id); };
        item.appendChild(delBtn);
        list.appendChild(item);
    });
}

function _loadJobSteps(jobId) {
    var stepsList = document.getElementById('job-steps-' + jobId);
    if (!stepsList) return;
    // Try to find step_history from the current state first (avoids extra API call)
    var historyEntry = (_uiState.history || []).find(function(h) { return h.job_id === jobId; });
    var steps = historyEntry && historyEntry.step_history && historyEntry.step_history.length > 0
        ? historyEntry.step_history
        : null;
    if (!steps) {
        // Fallback: fetch from the dedicated steps endpoint
        fetch('/api/job/' + jobId + '/steps')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                steps = data.steps || [];
                _renderJobSteps(steps, stepsList);
            })
            .catch(function(err) {
                console.error('Failed to load job steps:', err);
                stepsList.innerHTML = '<div style="padding:8px;color:var(--mc-nether);">Failed to load steps.</div>';
            });
        return;
    }
    _renderJobSteps(steps, stepsList);
}

function _renderJobSteps(steps, stepsList) {
    if (!steps.length) {
        stepsList.innerHTML = '<div style="padding:8px;color:var(--text-muted);">No steps recorded.</div>';
        return;
    }
    stepsList.innerHTML = '';
    steps.forEach(function(s) {
        var stepItem = document.createElement('div');
        stepItem.className = 'job-step-item';
        var stepNum = document.createElement('span');
        stepNum.className = 'step-num';
        stepNum.textContent = 'Step ' + s.step;
        stepItem.appendChild(stepNum);
        var toolName = document.createElement('span');
        toolName.className = 'step-tool-name';
        if (s.tool === 'llm_call') toolName.textContent = '[Thinking]';
        else if (s.tool === 'request_user_input') toolName.textContent = '[⏸ User Input]';
        else toolName.textContent = '[' + s.tool + ']';
        stepItem.appendChild(toolName);
        var statusSpan = document.createElement('span');
        var ok = s.result && s.result.success !== false;
        if (s.tool === 'request_user_input') {
            statusSpan.className = 'step-status-err';
            statusSpan.textContent = '⏸';
        } else {
            statusSpan.className = 'step-status-' + (ok ? 'ok' : 'err');
            statusSpan.textContent = ok ? '✓' : '✗';
        }
        stepItem.appendChild(statusSpan);
        if (s.tool === 'llm_call') {
            var mc = s.params ? s.params.messages : 0;
            var llmSpan = document.createElement('span');
            llmSpan.style.color = 'var(--text-muted)';
            llmSpan.textContent = 'LLM (' + mc + ' msgs)';
            stepItem.appendChild(llmSpan);
        } else if (s.params && Object.keys(s.params).length) {
            var paramsSpan = document.createElement('span');
            paramsSpan.style.color = 'var(--text-muted)';
            paramsSpan.textContent = JSON.stringify(s.params);
            stepItem.appendChild(paramsSpan);
        } else if (s.tool === 'request_user_input') {
            var rq = s.result ? (s.result.content || 'User input requested') : 'User input requested';
            var rqSpan = document.createElement('span');
            rqSpan.style.color = 'var(--warning)';
            rqSpan.textContent = rq.substring(0, 150) + (rq.length > 150 ? '...' : '');
            stepItem.appendChild(rqSpan);
        } else {
            var rt = s.result ? (s.result.content || '').substring(0, 200) : 'no result';
            var rtSpan = document.createElement('span');
            rtSpan.style.color = 'var(--text-muted)';
            rtSpan.textContent = rt;
            stepItem.appendChild(rtSpan);
        }
        if (s.rationale) {
            var ratDiv = document.createElement('div');
            ratDiv.style.cssText = 'color:var(--mc-gold);font-size:9px;margin-left:16px;font-style:italic;';
            ratDiv.textContent = '💡 ' + s.rationale;
            stepItem.appendChild(ratDiv);
        }
        stepsList.appendChild(stepItem);
    });
}

function toggleJobSteps(jobId) {
    var el = document.getElementById('job-steps-' + jobId);
    if (el) {
        if (el.style.display === 'none') {
            el.style.display = 'block';
            _loadJobSteps(jobId);
        } else {
            el.style.display = 'none';
        }
    }
}

function deleteJob(jobId) {
    if (!confirm('Delete this job?')) return;
    fetch('/api/queue/' + jobId, { method: 'DELETE' })
        .then(function() { fetchState(); })
        .catch(function(err) { console.error('Failed to delete job:', err); });
}

function clearJobHistory() {
    if (!confirm('Are you sure you want to clear all job history?')) return;
    fetch('/api/history/clear', { method: 'POST' })
        .then(function(res) { return res.json(); })
        .then(function(data) { if (data.status === 'cleared') fetchState(); else showNotification('Failed to clear history: ' + (data.error || 'Unknown error'), 'info'); })
        .catch(function(err) { console.error('Failed to clear history:', err); showNotification('Failed to clear history.', 'info'); });
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
function showLiveView(project_id) {
    var activeJob = (_uiState.active_jobs || {})[project_id];
    if (activeJob) {
        showLiveViewForJob(activeJob.job_id);
        return;
    }
    var history = _uiState.history || [];
    var lastJob = history.find(function(h) { return h.project_id === project_id; });
    if (lastJob) {
        showLiveViewForJob(lastJob.job_id);
    } else {
        showNotification('No active job to view', 'warning');
    }
}

function showLiveViewForJob(jobId, projectId) {
    var container = document.getElementById('agent-live-container');
    if (!container) return;
    var agentBox = document.getElementById('agent-live-box');
    if (agentBox) agentBox.innerHTML = '';
    var detailsPanel = document.getElementById('project-details-panel');
    if (detailsPanel) detailsPanel.classList.add('active');
    var configSection = document.getElementById('project-config-section');
    if (configSection) configSection.style.display = 'none';
    container.style.display = 'block';
    container.scrollIntoView({ behavior: 'smooth' });
    container.dataset.jobId = jobId;
    container.dataset.projectId = projectId || '';
    _activeJobId = jobId;
    var refreshBtn = document.getElementById('live-refresh-btn');
    if (refreshBtn) refreshBtn.style.display = 'inline-block';

    // Reload full state from /api/state as the single source of truth
    fetchState().then(function() {
        var queueData = _uiState.queue || {};
        var history = _uiState.history || [];
        var jobRecord = history.find(function(h) { return h.job_id === jobId; });
        var isRunning = queueData.running && queueData.running.job_id === jobId;

        // Check for pending states via the status endpoint (authoritative)
        fetch('/api/job/' + jobId + '/status')
            .then(function(r) { return r.json(); })
            .catch(function() { return {}; })
            .then(function(statusData) {
                var isPendingApproval = statusData.status === 'pending_approval' ||
                    (jobRecord && jobRecord.status === 'pending_approval');
                var isPendingInput = statusData.status === 'pending_user_input' ||
                    (jobRecord && jobRecord.status === 'pending_user_input');
                var outputDir = jobRecord ? jobRecord.output_dir : (queueData.running ? queueData.running.output_dir : null);
                var resolvedProjectId = jobRecord ? jobRecord.project_id : projectId;

                _doShowLiveView(jobId, queueData, history, jobRecord, isRunning,
                    isPendingApproval, isPendingInput, outputDir, resolvedProjectId);
            });
    });
}

function _doShowLiveView(jobId, queueData, history, jobRecord, isRunning, isPendingApproval, isPendingInput, outputDir, projectId) {
    var agentBox = document.getElementById('agent-live-box');
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    var container = document.getElementById('agent-live-container');
    
    if (isRunning && !isPendingApproval && !isPendingInput) {
        var stopBtn = document.getElementById('details-stop-btn');
        if (stopBtn) stopBtn.style.display = 'inline-block';
        var liveStopBtn = document.getElementById('live-stop-btn');
        if (liveStopBtn) liveStopBtn.style.display = 'inline-block';
        if (agentBox) agentBox.innerHTML = '<div class="step-entry llm-step">📺 Viewing live feed for running job (LIVE)...</div>';
        var statusText = document.getElementById('agent-status-text');
        if (statusText) { statusText.textContent = 'LIVE'; statusText.style.color = 'var(--success)'; }
        if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions or questions...'; }
        if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
        _startPolling(jobId, outputDir, agentBox, projectId, true);
    } else {
        var stopBtn = document.getElementById('details-stop-btn');
        if (stopBtn) stopBtn.style.display = 'inline-block';
        if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Continue with new instructions...'; }
        if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }

        // For non-running jobs, use step_history from state if available
        var steps = jobRecord && jobRecord.step_history && jobRecord.step_history.length > 0
            ? jobRecord.step_history : null;

        var stepsPromise = steps
            ? Promise.resolve({ steps: steps, count: steps.length })
            : fetch('/api/job/' + jobId + '/steps').then(function(r) { return r.json(); });

        Promise.all([
            stepsPromise,
            fetch('/api/job/' + jobId + '/status').then(function(r) { return r.json(); }),
            fetch('/api/agent/response/' + jobId).then(function(r) { return r.json(); })
        ]).then(function(results) {
            var stepsData = results[0] || { steps: [], count: 0 };
            var statusData = results[1] || {};
            var responseData = results[2] || {};
            agentBox.innerHTML = '';
            var allSteps = stepsData.steps || [];
            var count = stepsData.count || 0;
            for (var i = 0; i < count; i++) {
                var step = allSteps[i];
                if (step) _renderStep(step, agentBox);
            }
            if (responseData.content && responseData.content.trim()) {
                var liveResp = document.getElementById('live-response-container');
                if (liveResp) { liveResp.textContent = responseData.content; liveResp.style.display = 'block'; }
            }
            var statusText = document.getElementById('agent-status-text');
            if (statusText) {
                var finalStatus = statusData.status || (jobRecord ? jobRecord.status : 'unknown');
                if (isPendingApproval) { statusText.textContent = 'PENDING APPROVAL'; statusText.style.color = 'var(--warning)'; statusText.style.fontWeight = 'bold'; }
                else if (isPendingInput) { statusText.textContent = 'AWAITING INPUT'; statusText.style.color = 'var(--warning)'; statusText.style.fontWeight = 'bold'; }
                else if (finalStatus === 'completed') { statusText.textContent = 'COMPLETED'; statusText.style.color = 'var(--success)'; }
                else if (finalStatus === 'error') { statusText.textContent = 'ERROR'; statusText.style.color = 'var(--danger)'; }
                else if (finalStatus === 'stopped') { statusText.textContent = 'STOPPED'; statusText.style.color = 'var(--text-muted)'; }
                else { statusText.textContent = finalStatus.toUpperCase(); }
            }
            if (container) {
                if (outputDir) container.dataset.outputDir = outputDir;
                if (projectId) container.dataset.projectId = projectId;
            }
            _startPolling(jobId, outputDir, agentBox, projectId, false);
            setTimeout(function() { refreshLiveView(); }, 1000);
            if (isPendingApproval && outputDir) _showPendingApproval(jobId, outputDir, agentBox);
            if (isPendingInput) _showPendingUserInput(jobRecord, agentBox);
        }).catch(function(err) {
            console.error('Failed to aggressively fetch live state:', err);
        });
    }
}

function refreshLiveView() {
    var container = document.getElementById('agent-live-container');
    if (!container) return;
    var jobId = container.dataset.jobId;
    if (!jobId) {
        var qd = _uiState.queue || {};
        if (qd.running) {
            container.dataset.jobId = qd.running.job_id;
            refreshLiveView();
        } else {
            showNotification('No active job to refresh.', 'info');
        }
        return;
    }

    // Reload full state from /api/state so we have the latest data
    fetchState().then(function() {
        var agentBox = document.getElementById('agent-live-box');
        if (agentBox) agentBox.innerHTML = '<div class="step-entry llm-step">🔄 Refreshing...</div>';

        // Try to find the job's steps from state first
        var jobRecord = (_uiState.history || []).find(function(h) { return h.job_id === jobId; });
        var steps = jobRecord && jobRecord.step_history && jobRecord.step_history.length > 0
            ? jobRecord.step_history : null;

        // If not in state, fetch from the dedicated endpoint
        if (!steps) {
            fetch('/api/job/' + jobId + '/steps')
                .then(function(r) { return r.json(); })
                .then(function(data) { steps = data.steps || []; })
                .catch(function() { steps = []; });
        }

        // Also fetch the latest response content
        fetch('/api/agent/response/' + jobId)
            .then(function(r) { return r.json(); })
            .then(function(respData) {
                if (!steps || steps.length === 0) {
                    // No steps — just show refresh confirmation
                    var ab = document.getElementById('agent-live-box');
                    if (ab) {
                        var refreshMsg = document.createElement('div');
                        refreshMsg.className = 'step-entry';
                        refreshMsg.style.borderLeftColor = 'var(--mc-diamond)';
                        refreshMsg.style.background = 'rgba(74, 237, 223, 0.1)';
                        refreshMsg.innerHTML = '<div class="step-tool" style="color:var(--mc-diamond);">✅ Feed refreshed</div>';
                        ab.appendChild(refreshMsg);
                        ab.scrollTop = ab.scrollHeight;
                    }
                    return;
                }

                // Render all steps
                var ab = document.getElementById('agent-live-box');
                if (ab) {
                    ab.innerHTML = '';
                    steps.forEach(function(step) { _renderStep(step, ab); });
                    // Refresh confirmation at the bottom
                    var refreshMsg = document.createElement('div');
                    refreshMsg.className = 'step-entry';
                    refreshMsg.style.borderLeftColor = 'var(--mc-diamond)';
                    refreshMsg.style.background = 'rgba(74, 237, 223, 0.1)';
                    refreshMsg.innerHTML = '<div class="step-tool" style="color:var(--mc-diamond);">✅ Feed refreshed</div>';
                    ab.appendChild(refreshMsg);
                    ab.scrollTop = ab.scrollHeight;
                }

                // Show current response if available
                if (respData && respData.content && respData.content.trim()) {
                    var liveResp = document.getElementById('live-response-container');
                    if (liveResp) {
                        liveResp.textContent = respData.content;
                        liveResp.style.display = 'block';
                    }
                }
            })
            .catch(function(err) { console.error('Failed to refresh:', err); });
    });
}

// === Inject Live Instruction ===
function injectLiveInstruction() {
    var input = document.getElementById('live-inject-input');
    var btn = document.getElementById('live-inject-btn');
    if (!input || !btn) return;
    var instruction = input.value.trim();
    if (!instruction) return;
    var jobId = _activeJobId;
    if (!jobId) { showNotification('No active job to inject into', 'warning'); return; }
    btn.disabled = true;
    btn.textContent = 'INJECTING...';
    input.disabled = true;
    var agentBox = document.getElementById('agent-live-box');
    if (agentBox) {
        var injectEntry = document.createElement('div');
        injectEntry.className = 'step-entry';
        injectEntry.style.borderLeftColor = 'var(--info)';
        injectEntry.style.background = 'rgba(74, 237, 223, 0.1)';
        injectEntry.innerHTML = '<div class="step-tool" style="color:var(--info);">📥 USER INJECTION: ' + escapeHtml(instruction) + '</div>';
        agentBox.appendChild(injectEntry);
        agentBox.scrollTop = agentBox.scrollHeight;
    }
    fetch('/api/agent/inject', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({job_id: jobId, instruction: instruction})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) throw new Error(data.error);
        input.value = '';
        if (data.continuation) {
            var agentBox = document.getElementById('agent-live-box');
            if (agentBox) {
                var contEntry = document.createElement('div');
                contEntry.className = 'step-entry';
                contEntry.style.borderLeftColor = 'var(--info)';
                contEntry.style.background = 'rgba(74, 237, 223, 0.1)';
                contEntry.innerHTML = '<div class="step-tool" style="color:var(--info);">🔄 CONTINUING WITH NEW INSTRUCTIONS...</div>';
                agentBox.appendChild(contEntry);
                agentBox.scrollTop = agentBox.scrollHeight;
            }
            var statusText = document.getElementById('agent-status-text');
            if (statusText) { statusText.textContent = 'CONTINUING...'; statusText.style.color = 'var(--info)'; }
            showNotification('Continuation started — engine running', 'success');
        } else if (data.resumed) {
            var agentBox = document.getElementById('agent-live-box');
            if (agentBox) {
                var contEntry = document.createElement('div');
                contEntry.className = 'step-entry';
                contEntry.style.borderLeftColor = 'var(--info)';
                contEntry.style.background = 'rgba(74, 237, 223, 0.1)';
                contEntry.innerHTML = '<div class="step-tool" style="color:var(--info);">🔄 INSTRUCTION INJECTED — ENGINE RESUMED...</div>';
                agentBox.appendChild(contEntry);
                agentBox.scrollTop = agentBox.scrollHeight;
            }
            var statusText = document.getElementById('agent-status-text');
            if (statusText) { statusText.textContent = 'RESUMING...'; statusText.style.color = 'var(--info)'; }
            showNotification('Instruction injected — agent resumed', 'success');
        } else {
            showNotification('Instruction injected successfully', 'success');
        }
        fetchState();
        setTimeout(function() {
            btn.disabled = false;
            btn.textContent = 'INJECT';
            input.disabled = false;
        }, 1000);
    })
    .catch(function(err) {
        console.error('Inject failed:', err);
        showNotification('Failed to inject: ' + err.message, 'error');
        btn.disabled = false;
        btn.textContent = 'INJECT';
        input.disabled = false;
    });
}

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
