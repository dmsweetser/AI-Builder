// === State ===
let currentProjectId = localStorage.getItem('currentProjectId') || null;
let currentChatId = localStorage.getItem('currentChatId') || null;
let showArchived = false;
let autoSaveTimeout = null;
let pendingRootPathChange = null;
let pendingRootPathElementId = null;

// === Live Agent State ===
let currentRunningJobId = null;
let agentRunning = false;
let liveInjectActive = false;
let currentRunningProjectId = null;
let _loadedProjects = [];

// === Available Tools ===
const AVAILABLE_TOOLS = [
    "list_directory", "list_directory_deep", "search_files", "search_files_dir",
    "grep_code", "grep_code_dir", "read_file", "read_file_range",
    "write_file", "edit_file", "delete_file", "find_symbol",
    "decompile_jar", "check_syntax",
    "create_tool", "respond_to_user", "request_user_input", "task_completed"
];


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
    html = html.replace(/(?<!\w)\*(.+?)\*(?!\w)/g, '<em>$1</em>');
    html = html.replace(/^- (.+)$/gm, '<div style="margin-left:12px;">• $1</div>');
    html = html.replace(/\n\n/g, '<br><br>');
    html = html.replace(/\n/g, '<br>');
    codeBlocks.forEach(function(block) {
        var escaped = block.content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        html = html.replace('%%CODEBLOCK_' + block.id + '%%',
            '<div style="position:relative;margin:4px 0;"><button class="pre-copy-btn" onclick="copyCodeBlock(\'' + block.id + '\', this)" style="position:absolute;bottom:4px;right:4px;background:var(--wood);border:1px solid #000;padding:3px 8px;cursor:pointer;font-size:8px;color:#fff;z-index:10;border-radius:3px;font-family:\'Press Start 2P\',monospace;">COPY</button><pre style="background:#111;padding:8px;border-radius:4px;overflow-x:auto;margin:0;"><code id="' + block.id + '" style="white-space:pre-wrap;">' + escaped + '</code></pre></div>');
    });
    return html;
}

function copyCodeBlock(id, btn) {
    var el = document.getElementById(id);
    if (!el) return;
    var text = el.textContent || el.innerText || '';
    // Decode HTML entities
    var decoded = text.replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
    // Strip language label if present (e.g., "python\nprint(...)" -> "print(...)")
    var firstLineEnd = decoded.indexOf('\n');
    if (firstLineEnd !== -1) {
        var firstLine = decoded.substring(0, firstLineEnd).trim().toLowerCase().replace('```','');
        var langNames = ['python','javascript','js','ts','typescript','java','c','cpp','c++','c#','cs','go','rust','rs','ruby','rb','php','html','css','bash','sh','shell','sql','json','yaml','yml','xml','markdown','md','txt','plaintext'];
        if (langNames.indexOf(firstLine) !== -1) {
            decoded = decoded.substring(firstLineEnd + 1);
        }
    }
    copyToClipboard(decoded, btn);
}

// === Tab Management ===
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
    if (tabName === 'jobs') loadJobs();
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

// === Project Management ===
function loadProjects() {
    fetch('/api/projects')
        .then(function(response) { return response.json(); })
        .then(function(data) {
            var projectList = document.getElementById('project-list');
            if (!projectList) return;
            projectList.innerHTML = '';
            if (!data || data.length === 0) {
                projectList.innerHTML = '<div class="note">NO PROJECTS FOUND. ADD ONE BELOW.</div>';
                return;
            }
            var filteredProjects = showArchived ? data : data.filter(function(p) { return !p.isArchived; });
            if (filteredProjects.length === 0) {
                projectList.innerHTML = '<div class="note">NO PROJECTS FOUND. ADD ONE BELOW.</div>';
                return;
            }
            filteredProjects.forEach(function(project) {
                var projectItem = document.createElement('div');
                projectItem.className = 'project-item';
                projectItem.id = 'proj-' + project.id;
                projectItem.onclick = function() {
                    selectProject(project.id);
                };

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
                var isRunning = project.status === 'running';
                var liveBtn = document.createElement('button');
                liveBtn.className = 'btn btn-sm btn-info';
                liveBtn.textContent = '📺 LIVE';
                liveBtn.onclick = function(e) { e.stopPropagation(); showLiveViewForJob(project.id); };
                var runBtn = document.createElement('button');
                runBtn.className = 'btn btn-sm btn-primary';
                runBtn.textContent = 'RUN';
                runBtn.onclick = function(e) { e.stopPropagation(); runProject(project.id); };
                var stopBtn = document.createElement('button');
                stopBtn.className = 'btn btn-sm btn-danger';
                stopBtn.textContent = 'STOP';
                stopBtn.onclick = function(e) { e.stopPropagation(); stopProject(project.id); };
                if (isRunning) {
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
                archiveBtn.title = 'Archive';
                archiveBtn.onclick = function(e) { e.stopPropagation(); archiveProject(project.id, e.target); };
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
        })
        .catch(function(err) { console.error('Failed to load projects:', err); });
}

function runProject(projectId) {
    // Save project first (name, rootDirectory, instructions, tools)
    saveProjectChanges()
        .then(function() {
            var project = getProjectById(projectId);
            if (!project) {
                fetch('/api/projects/' + projectId)
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data.error) { showNotification('Project not found', 'error'); return; }
                        _loadedProjects = _loadedProjects || [];
                        if (!_loadedProjects.find(function(p) { return p.id === projectId; })) _loadedProjects.push(data);
                        _doRunProject(projectId);
                    })
                    .catch(function(err) { console.error('Failed to fetch project:', err); showNotification('Failed to load project details', 'info'); });
                return;
            }
            _doRunProject(projectId);
        })
        .catch(function(err) {
            console.error('Failed to save project:', err);
            showNotification('Failed to save project changes. Please try again.', 'info');
        });
}

function _doRunProject(projectId, overrideInstruction) {
    // Try to get rootDir from the details form (if open), fall back to project data
    var rootDir = document.getElementById('details-root-dir') ? document.getElementById('details-root-dir').value : '';
    if (!rootDir) {
        // Details panel not open — look up the project's stored rootDirectory
        var project = getProjectById(projectId);
        if (!project) {
            // Not in cache — fetch it
            fetch('/api/projects/' + projectId)
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.error) { showNotification('Project not found', 'info'); return; }
                    _loadedProjects = _loadedProjects || [];
                    if (!_loadedProjects.find(function(p) { return p.id === projectId; })) _loadedProjects.push(data);
                    _doRunProject(projectId, overrideInstruction);
                })
                .catch(function(err) { console.error('Failed to fetch project:', err); showNotification('Failed to load project details', 'info'); });
            return;
        }
        rootDir = project.rootDirectory || '';
    }
    if (!rootDir) { showNotification('Please set a root directory first.', 'info'); return; }
    var instructions = overrideInstruction || (document.getElementById('details-instructions') ? document.getElementById('details-instructions').value : '');
    // All tools are always available — getEnabledTools() returns the full list.
    var enabledTools = getEnabledTools();
    // Use file-based polling instead of SSE
    agentRunning = true;
    liveInjectActive = false;
    currentRunningProjectId = projectId;
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
    // Keep inject button enabled so user can inject at will
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions or questions...'; }
    if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
    // Scroll to agent live box
    if (agentLive) {
        setTimeout(function() { agentLive.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 100);
    }
    // Start the agent run via POST (non-streaming)
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
        currentRunningJobId = data.job_id;
        // Start polling for status and steps
        _startPolling(data.job_id, data.output_dir, agentBox);
    })
    .catch(function(err) {
        console.error('Agent run error:', err);
        var errEntry = document.createElement('div');
        errEntry.className = 'step-entry error';
        errEntry.textContent = 'ERROR: ' + err.message;
        if (agentBox.firstChild) agentBox.insertBefore(errEntry, agentBox.firstChild);
        else agentBox.appendChild(errEntry);
        agentBox.scrollTop = 0;
        agentRunning = false;
        liveInjectActive = false;
        resetRunButtons();
        if (stopBtn) stopBtn.style.display = 'none';
        if (injectInput) { injectInput.disabled = true; injectInput.placeholder = 'Agent error'; }
        if (injectBtn) { injectBtn.disabled = true; injectBtn.textContent = 'WAITING'; }
    });
}

// === File-Based Polling (replaces SSE) ===
var _pollInterval = null;
var _lastPollTimestamp = 0;

function _startPolling(jobId, outputDir, agentBox) {
    // Clear any existing poll interval
    if (_pollInterval) clearInterval(_pollInterval);
    _lastPollTimestamp = Date.now();

    // Initial fetch
    _pollOnce(jobId, outputDir, agentBox);

    // Poll every 30 seconds
    _pollInterval = setInterval(function() {
        _pollOnce(jobId, outputDir, agentBox);
    }, 30000);
}

function _pollOnce(jobId, outputDir, agentBox) {
    // Fetch steps to detect pending states from the data (not status.json)
    var stepsPromise = fetch('/api/job/' + jobId + '/steps')
        .then(function(r) { return r.json(); })
        .catch(function() { return { steps: [], count: 0 }; });

    // Fetch status for terminal states (completed, error, etc.)
    var statusPromise = fetch('/api/job/' + jobId + '/status')
        .then(function(r) { return r.json(); })
        .catch(function() { return {}; });

    Promise.all([stepsPromise, statusPromise])
        .then(function(results) {
            var stepsData = results[0];
            var statusData = results[1];
            var steps = stepsData.steps || [];
            var count = stepsData.count || 0;

            // Detect pending states from the steps data
            var hasPendingTools = false;
            var hasPendingUserInput = false;

            if (count > 0) {
                var lastStep = steps[count - 1];
                // Detect pending user input: last step was request_user_input
                if (lastStep && lastStep.tool === 'request_user_input') {
                    hasPendingUserInput = true;
                }
            }

            // Check for pending tools via API (filesystem-based)
            if (outputDir) {
                fetch('/api/tools/pending', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({project_output_dir: outputDir})
                })
                .then(function(r) { return r.json(); })
                .then(function(pendingTools) {
                    if (pendingTools && pendingTools.length > 0) {
                        hasPendingTools = true;
                    }
                    _renderAllSteps(jobId, outputDir, agentBox, statusData, hasPendingTools, hasPendingUserInput);
                })
                .catch(function() {
                    _renderAllSteps(jobId, outputDir, agentBox, statusData, hasPendingTools, hasPendingUserInput);
                });
            } else {
                _renderAllSteps(jobId, outputDir, agentBox, statusData, hasPendingTools, hasPendingUserInput);
            }
        })
        .catch(function(err) {
            console.error('Polling error:', err);
        });
}

function _renderAllSteps(jobId, outputDir, agentBox, statusData, hasPendingTools, hasPendingUserInput) {
    fetch('/api/job/' + jobId + '/steps')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var steps = data.steps || [];
            var count = data.count || 0;

            // Always re-render all steps from scratch
            agentBox.innerHTML = '';

            for (var i = 0; i < count; i++) {
                var step = steps[i];
                if (step) {
                    _renderStep(step, agentBox);
                }
            }

            // Show pending approval banner if detected from filesystem
            if (hasPendingTools && outputDir) {
                _showPendingApproval(jobId, outputDir, agentBox);
            }

            // Show pending user input banner if detected from steps
            if (hasPendingUserInput) {
                _showPendingUserInput(statusData, agentBox);
            }

            // Update status text for pending states
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

            // If terminal state (not pending), stop polling
            var status = statusData.status || 'running';
            if (status !== 'running' && !hasPendingTools && !hasPendingUserInput) {
                if (_pollInterval) {
                    clearInterval(_pollInterval);
                    _pollInterval = null;
                }
                agentRunning = false;
                liveInjectActive = true;
                resetRunButtons();
                var stopBtn = document.getElementById('details-stop-btn');
                if (stopBtn) stopBtn.style.display = 'none';
                var liveStopBtn = document.getElementById('live-stop-btn');
                if (liveStopBtn) liveStopBtn.style.display = 'none';

                // Update status text
                if (st) {
                    if (status === 'completed') {
                        st.textContent = 'COMPLETED';
                        st.style.color = 'var(--success)';
                    } else if (status === 'error') {
                        st.textContent = 'ERROR';
                        st.style.color = 'var(--danger)';
                    } else if (status === 'stopped') {
                        st.textContent = 'STOPPED';
                        st.style.color = 'var(--text-muted)';
                    } else if (status === 'max_steps_reached') {
                        st.textContent = 'MAX STEPS';
                        st.style.color = 'var(--warning)';
                    } else {
                        st.textContent = status.toUpperCase();
                    }
                }

                // Enable inject
                var ii = document.getElementById('live-inject-input');
                var ib = document.getElementById('live-inject-btn');
                if (ii) { ii.disabled = false; ii.placeholder = 'Continue with new instructions...'; }
                if (ib) { ib.disabled = false; ib.textContent = 'INJECT'; }
            }
        })
        .catch(function(err) {
            console.error('Failed to load steps:', err);
        });
}

function _renderStep(step, agentBox) {
    if (!agentBox) return;

    // Remove the "tool running" indicator for this step
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
        var respContent = step.result ? step.result.content : '';
        var preview = respContent ? (respContent.length > 200 ? respContent.substring(0, 200) + '...' : respContent) : 'Processing request...';
        var toolDiv3 = document.createElement('div');
        toolDiv3.className = 'step-tool';
        toolDiv3.textContent = '🤔 Thinking (' + msgCount + ' messages)';
        entry.appendChild(toolDiv3);
        var resultDiv3 = document.createElement('div');
        resultDiv3.className = 'step-result';
        resultDiv3.textContent = preview;
        entry.appendChild(resultDiv3);
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
        // Show error details prominently when a tool fails
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
    // Idempotent: if already showing, just refresh the tool list (in case new tools were added)
    var existingEntry = document.getElementById('pending-approval-entry');
    if (existingEntry) {
        // Refresh the tool list inside the existing entry
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
    .catch(function(err) {
        console.error('Failed to load pending tools:', err);
    });
}

function _showPendingUserInput(statusData, agentBox) {
    if (!agentBox) return;
    // Idempotent: if already showing, nothing to do
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



function handleAgentStep(data, agentBox) {
    if (!agentBox) return;
    // Remove the "tool running" indicator for this step
    var runningEntry = document.getElementById('tool-running-' + data.step);
    if (runningEntry) runningEntry.remove();
    var stepCount = document.getElementById('agent-step-count');
    if (stepCount) stepCount.textContent = 'Step ' + data.step;
    var entry = document.createElement('div');
    entry.className = 'step-entry';
    if (data.tool === 'respond_to_user') {
        entry.classList.add('llm-step');
        entry.style.borderLeftColor = 'var(--info)';
        var toolDiv = document.createElement('div');
        toolDiv.className = 'step-tool';
        toolDiv.style.color = 'var(--info)';
        toolDiv.textContent = '💬 AI Response';
        entry.appendChild(toolDiv);
        var respContent = data.result ? (data.result.content || '') : '';
        var resultDiv = document.createElement('div');
        resultDiv.className = 'step-result';
        resultDiv.textContent = respContent;
        entry.appendChild(resultDiv);
    } else if (data.tool === 'request_user_input') {
        entry.classList.add('pending-approval');
        var toolDiv2 = document.createElement('div');
        toolDiv2.className = 'step-tool';
        toolDiv2.style.color = 'var(--warning)';
        toolDiv2.textContent = '⏸ REQUEST USER INPUT';
        entry.appendChild(toolDiv2);
        var reqQuestion = data.result ? (data.result.content || 'The agent is waiting for your input.') : 'The agent is waiting for your input.';
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
    } else if (data.tool === 'llm_call') {
        var msgCount = data.params ? data.params.messages : 0;
        entry.classList.add('llm-step');
        var rawReq = data.raw_request || '';
        var rawResp = data.raw_response || '';
        var hasRaw = rawReq.length > 0 || rawResp.length > 0;
        var respContent = data.result ? data.result.content : '';
        var preview = respContent ? (respContent.length > 200 ? respContent.substring(0, 200) + '...' : respContent) : 'Processing request...';
        var toolDiv3 = document.createElement('div');
        toolDiv3.className = 'step-tool';
        toolDiv3.textContent = '🤔 Thinking (' + msgCount + ' messages)';
        entry.appendChild(toolDiv3);
        var resultDiv3 = document.createElement('div');
        resultDiv3.className = 'step-result';
        resultDiv3.textContent = preview;
        entry.appendChild(resultDiv3);
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
    } else if (data.tool === 'format_retry') {
        entry.classList.add('llm-step');
        var toolDiv4 = document.createElement('div');
        toolDiv4.className = 'step-tool';
        toolDiv4.style.color = 'var(--warning)';
        toolDiv4.textContent = '⚠ Format reminder sent';
        entry.appendChild(toolDiv4);
        var resultDiv4 = document.createElement('div');
        resultDiv4.className = 'step-result';
        resultDiv4.style.color = 'var(--warning)';
        resultDiv4.textContent = data.result ? data.result.content : '';
        entry.appendChild(resultDiv4);
    } else if (data.tool === 'task_completed') {
        // Celebration entry for task completion
        var summary = data.result ? (data.result.content || '') : '';
        var toolDiv5 = document.createElement('div');
        toolDiv5.className = 'step-tool';
        toolDiv5.style.cssText = 'color:var(--success);font-weight:bold;font-size:16px;';
        toolDiv5.textContent = '🎉 TASK COMPLETED';
        entry.appendChild(toolDiv5);
        if (data.rationale) {
            var rationaleDiv = document.createElement('div');
            rationaleDiv.className = 'step-rationale';
            rationaleDiv.innerText = '💡 ' + data.rationale;
            entry.appendChild(rationaleDiv);
        }
        var resultDiv5 = document.createElement('div');
        resultDiv5.className = 'step-result';
        resultDiv5.style.cssText = 'margin-top:6px;padding:8px;background:rgba(46,204,113,0.1);border:1px solid var(--success);border-radius:4px;';
        resultDiv5.textContent = summary;
        entry.appendChild(resultDiv5);
        if (data.params && data.params.summary) {
            var paramsDiv = document.createElement('div');
            paramsDiv.className = 'step-result';
            paramsDiv.style.cssText = 'margin-top:6px;font-style:italic;color:var(--text-muted);';
            paramsDiv.textContent = 'Summary: ' + data.params.summary;
            entry.appendChild(paramsDiv);
        }
    } else {
        var ok = data.result && data.result.success !== false;
        var resultPreview = data.result ? (data.result.content || '') : 'no result';
        var errorMsg = data.result ? (data.result.error || '') : '';
        entry.classList.add(ok ? 'success' : 'error');
        var toolDiv6 = document.createElement('div');
        toolDiv6.className = 'step-tool';
        toolDiv6.textContent = (ok ? '✓' : '✗') + ' ' + data.tool;
        entry.appendChild(toolDiv6);
        if (data.rationale) {
            var rationaleDiv2 = document.createElement('div');
            rationaleDiv2.className = 'step-rationale';
            rationaleDiv2.innerText = '💡 ' + data.rationale;
            entry.appendChild(rationaleDiv2);
        }
        if (data.params && Object.keys(data.params).length) {
            var paramsDiv2 = document.createElement('div');
            paramsDiv2.className = 'step-params';
            paramsDiv2.textContent = JSON.stringify(data.params);
            entry.appendChild(paramsDiv2);
        }
        // Show error details prominently when a tool fails
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
// Resend the last request to kick the agent if it stalled
function resendLastRequest() {
    if (!currentRunningJobId) {
        showNotification('No active job to resend', 'warning');
        return;
    }
    var resendBtn = document.getElementById('live-resend-btn');
    if (!resendBtn) return;
    
    // Disable button while resending
    resendBtn.disabled = true;
    resendBtn.textContent = 'RESENDING...';
    
    // Add a visual indicator in the live feed
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
    
    // Call the resend endpoint
    fetch('/api/agent/resend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: currentRunningJobId })
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
        // Re-enable the button after a delay
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

// === Event delegation for approve/reject buttons in pending approval section ===
document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-url]');
    if (!btn) return;
    var url = btn.dataset.url;
    var outputDir = btn.dataset.outputDir || '';
    var jobId = btn.dataset.jobId || '';
    var isApprove = url.indexOf('/approve') !== -1;

    // Disable button to prevent double-clicks
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
    })
    .catch(function(err) { console.error('Failed:', err); showNotification('Failed to process tool action.', 'info'); })
    .finally(function() {
        // Re-enable button on failure so user can retry
        btn.disabled = false;
        btn.textContent = isApprove ? '✅ APPROVE' : '❌ REJECT';
    });
});

function clearPendingApprovalState() {
    var actions = document.getElementById('pending-approval-actions');
    if (actions) actions.innerHTML = '<div style="color:var(--success);font-size:12px;">✅ Tool action processed. The agent will resume automatically.</div>';
    var statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'AGENT RUNNING'; statusText.style.color = ''; statusText.style.fontWeight = ''; }
}

function stopProject(projectId) {
    agentRunning = false;
    liveInjectActive = false;
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
        // Stop the SSE engine job if there is one
    var jobId = currentRunningJobId;
    var promises = [fetch('/api/queue/running/stop', { method: 'POST' }).catch(function() {})];
    if (jobId) {
        promises.push(fetch('/api/agent/stop/' + jobId, { method: 'POST' }).catch(function() {}));
    }
    Promise.all(promises).then(function() {
        // Hide the agent live container and show config section again
        var container = document.getElementById('agent-live-container');
        if (container) container.style.display = 'none';
        var configSection = document.getElementById('project-config-section');
        if (configSection) configSection.style.display = 'block';
        var stopBtn = document.getElementById('details-stop-btn');
        if (stopBtn) stopBtn.style.display = 'none';
        var viewLiveBtn = document.getElementById('details-live-btn');
        if (viewLiveBtn) viewLiveBtn.style.display = 'none';
        var liveStopBtn = document.getElementById('live-stop-btn');
        if (liveStopBtn) liveStopBtn.style.display = 'none';
        updateRunButtonState(projectId, false);
        loadJobs();
        resetRunButtons();
    })
    .catch(function(err) { console.error('Failed to stop project:', err); });
}

function stopCurrentJob() {
    // Stop the currently running job from the VIEW LIVE screen
    agentRunning = false;
    liveInjectActive = false;
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
        var jobId = currentRunningJobId;
    var promises = [fetch('/api/queue/running/stop', { method: 'POST' }).catch(function() {})];
    if (jobId) {
        promises.push(fetch('/api/agent/stop/' + jobId, { method: 'POST' }).catch(function() {}));
    }
    Promise.all(promises).then(function() {
        var liveStopBtn = document.getElementById('live-stop-btn');
        if (liveStopBtn) liveStopBtn.style.display = 'none';
        var statusText = document.getElementById('agent-status-text');
        if (statusText) { statusText.textContent = 'STOPPED'; statusText.style.color = 'var(--danger)'; }
        loadJobs();
        resetRunButtons();
    })
    .catch(function(err) { console.error('Failed to stop job:', err); });
}

function continueAgentRunWithInstruction(projectId, prevJobId, newInstruction) {
    if (!projectId) return;
    // If no prevJobId, we'll start a new run for the project
    if (!prevJobId) {
        // Start a fresh run with the new instruction
        _doRunProject(projectId, newInstruction);
        return;
    }
    agentRunning = true;
    liveInjectActive = false;
    currentRunningProjectId = projectId;
    currentRunningJobId = null;
    var enabledTools = getEnabledTools();
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
        currentRunningJobId = data.job_id;
        _startPolling(data.job_id, data.output_dir, agentBox);
    })
    .catch(function(err) {
        console.error('Agent run error:', err);
        if (agentBox) { var errEntry = document.createElement('div'); errEntry.className = 'step-entry error'; errEntry.textContent = 'ERROR: ' + err.message; agentBox.appendChild(errEntry); agentBox.scrollTop = agentBox.scrollHeight; }
        agentRunning = false;
        liveInjectActive = true;
        var iInput2 = document.getElementById('live-inject-input');
        var iBtn2 = document.getElementById('live-inject-btn');
        if (iInput2) { iInput2.disabled = false; iInput2.placeholder = 'Continue with new instructions...'; }
        if (iBtn2) { iBtn2.disabled = false; iBtn2.textContent = 'INJECT'; }
    });
}

function resetRunButtons() {
    var runBtn = document.getElementById('details-run-btn');
    var stopBtn = document.getElementById('details-stop-btn');
    if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = 'RUN AI BUILDER'; }
    if (stopBtn) stopBtn.style.display = 'none';
    // Restore inject button state based on liveInjectActive flag
    // (processChunk sets it to WAITING, but handleAgentStatus may have
    // already set it to INJECT — we need to respect that)
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    if (liveInjectActive) {
        // Agent completed or was interrupted — allow injection
        if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Continue with new instructions...'; }
        if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
    }
}

function updateRunButtonState(projectId, status) {
    var listBtn = document.getElementById('run-btn-' + projectId);
    var stopListBtn = document.getElementById('stop-btn-' + projectId);
    var detailBtn = document.getElementById('details-run-btn');
    var detailStopBtn = document.getElementById('details-stop-btn');
    if (listBtn) {
        listBtn.disabled = status === 'running';
        if (status === 'running') listBtn.innerHTML = '<span class="run-spinner"></span> RUNNING';
        else if (status === 'queued') listBtn.innerHTML = '<span class="run-spinner"></span> QUEUED';
        else listBtn.innerHTML = 'RUN';
    }
    if (stopListBtn) stopListBtn.style.display = (status === 'running' || status === 'pending_approval' || status === 'pending_user_input') ? 'inline-block' : 'none';
    if (detailBtn && currentProjectId === projectId) {
        detailBtn.disabled = (status === 'running' || status === 'pending_approval' || status === 'pending_user_input');
        if (status === 'running') detailBtn.innerHTML = '<span class="run-spinner"></span> RUNNING...';
        else if (status === 'queued') detailBtn.innerHTML = '<span class="run-spinner"></span> QUEUED';
        else detailBtn.innerHTML = 'RUN AI BUILDER';
    }
    if (detailStopBtn && currentProjectId === projectId) {
        detailStopBtn.style.display = (status === 'running' || status === 'pending_approval' || status === 'pending_user_input') ? 'inline-block' : 'none';
    }
    // Show/hide VIEW LIVE button for running, pending_approval, pending_user_input
    var liveBtn = document.getElementById('details-live-btn');
    if (liveBtn && currentProjectId === projectId) {
        liveBtn.style.display = 'inline-block';
    }
}

function getProjectById(projectId) {
    for (var i = 0; i < _loadedProjects.length; i++) {
        if (_loadedProjects[i].id === projectId) return _loadedProjects[i];
    }
    return null;
}

function loadProjectsCached() {
    return fetch('/api/projects')
        .then(function(r) { return r.json(); })
        .then(function(data) { _loadedProjects = data; loadProjects(); return data; });
}

function selectProject(projectId) {
    currentProjectId = projectId;
    currentRunningProjectId = projectId;  // Set for inject continuation
    localStorage.setItem('currentProjectId', projectId);
    document.getElementById('projects-panel').classList.remove('active');
    document.getElementById('project-details-panel').classList.add('active');
    // Scroll to top so user can see the run button
    window.scrollTo(0, 0);
    var configSection = document.getElementById('project-config-section');
    var agentLive = document.getElementById('agent-live-container');
    if (configSection) configSection.style.display = 'block';
    if (agentLive) agentLive.style.display = 'none';
    fetch('/api/projects/' + projectId)
        .then(function(response) { return response.json(); })
        .then(function(project) {
            if (!_loadedProjects) _loadedProjects = [];
            var idx = -1;
            for (var i = 0; i < _loadedProjects.length; i++) { if (_loadedProjects[i].id === projectId) { idx = i; break; } }
            if (idx === -1) _loadedProjects.push(project); else _loadedProjects[idx] = project;
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
            // Fetch custom tools for this project
            fetch('/api/projects/' + projectId + '/tools')
                .then(function(r) { return r.json(); })
                .then(function(toolData) {
                    buildToolSelector(toolData.disabled_tools || [], toolData.custom_tools || []);
                })
                .catch(function(err) {
                    console.error('Failed to load project tools:', err);
                    buildToolSelector(project.disabled_tools || [], []);
                });
            // Check if this project has a running job and show VIEW LIVE button
            fetch('/api/queue')
                .then(function(r) { return r.json(); })
                .then(function(queueData) {
                    var isRunning = queueData.running && queueData.running.project_id === projectId;
                    var isQueued = queueData.queue && queueData.queue.some(function(j) { return j.project_id === projectId; });
                    updateRunButtonState(projectId, isRunning ? 'running' : (isQueued ? 'queued' : null));
                    // Show VIEW LIVE button if project is running, pending, or has completed jobs
                    if (isRunning) {
                        var liveBtn = document.getElementById('details-live-btn');
                        if (liveBtn) liveBtn.style.display = 'inline-block';
                        var stopBtn = document.getElementById('details-stop-btn');
                        if (stopBtn) stopBtn.style.display = 'inline-block';
                        currentRunningJobId = queueData.running.job_id;
                    } else {
                        // Check job history for any job (running, pending, or completed)
                        fetch('/api/history')
                            .then(function(r) { return r.json(); })
                            .then(function(history) {
                                var recentJob = history.find(function(h) { return h.project_id === projectId; });
                                if (recentJob) {
                                    var liveBtn = document.getElementById('details-live-btn');
                                    if (liveBtn) liveBtn.style.display = 'inline-block';
                                    var stopBtn = document.getElementById('details-stop-btn');
                                    if (stopBtn) stopBtn.style.display = 'inline-block';
                                    currentRunningJobId = recentJob.job_id;
                                }
                            });
                    }
                });
        })
        .catch(function(err) { console.error('Failed to load project details:', err); });
}

function goBackToProjects() {
    // Save project first (name, rootDirectory, instructions, tools)
    saveProjectChanges()
        .then(function() {
        _goBackToProjects();
    })
    .catch(function(err) {
        console.error('Failed to save project:', err);
        // Still allow going back even if save fails
        _goBackToProjects();
    });
}

function _goBackToProjects() {
    if (agentRunning) stopProject(currentProjectId);
    agentRunning = false;
    liveInjectActive = false;
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
    currentRunningJobId = null;
    currentRunningProjectId = null;
    var configSection = document.getElementById('project-config-section');
    var agentLive = document.getElementById('agent-live-container');
    if (configSection) configSection.style.display = 'block';
    if (agentLive) agentLive.style.display = 'none';
    document.getElementById('project-details-panel').classList.remove('active');
    document.getElementById('projects-panel').classList.add('active');
    localStorage.removeItem('currentProjectId');
    currentProjectId = null;
    loadProjects();
}

function resetProject(projectId) {
    if (!confirm('Reset project "' + projectId + '"? This will clear all run history and output.')) return;
    fetch('/api/projects/' + projectId + '/reset', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'reset') { loadProjects(); showNotification('Project reset successfully!', 'info'); }
            else showNotification('Failed to reset project: ' + (data.error || 'Unknown error', 'info'));
        })
        .catch(function(err) { console.error('Failed to reset project:', err); showNotification('Failed to reset project.', 'info'); });
}

function deleteProject(projectId) {
    if (!confirm('Are you sure you want to delete this project?')) return;
    fetch('/api/projects/' + projectId, { method: 'DELETE' })
        .then(function() { if (currentProjectId === projectId) goBackToProjects(); else loadProjects(); })
        .catch(function(err) { console.error('Failed to delete project:', err); });
}

function archiveProject(projectId, btnEl) {
    fetch('/api/projects/' + projectId + '/archive', { method: 'POST' })
        .then(function() { loadProjects(); if (currentProjectId === projectId) selectProject(projectId); })
        .catch(function(err) { console.error('Failed to archive project:', err); });
}

function toggleArchived() {
    showArchived = !showArchived;
    var btn = document.getElementById('show-archived-btn');
    if (btn) btn.textContent = showArchived ? 'HIDE ARCHIVED' : 'SHOW ARCHIVED';
    loadProjects();
}

function autoSaveProject() {
    clearTimeout(autoSaveTimeout);
    autoSaveTimeout = setTimeout(function() { saveProjectChanges(); }, 2000);
}

function saveProjectChanges() {
    var projectId = document.getElementById('run-project-id') ? document.getElementById('run-project-id').value : null;
    if (!projectId) return;
    var formData = new FormData(document.getElementById('project-details-form'));
    // Collect disabled_tools: unchecked boxes = disabled
    var unchecked = document.querySelectorAll('#details-tool-selector input[type="checkbox"]:not(:checked)');
    var disabledTools = [];
    unchecked.forEach(function(cb) { disabledTools.push(cb.value); });
    // Save disabled_tools via dedicated endpoint
    fetch('/api/projects/' + projectId + '/tools', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({disabled_tools: disabledTools})
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (data.status === 'updated') console.log('Project tools updated');
    })
    .catch(function(err) { console.error('Failed to save project tools:', err); });
    // Also save other project fields
    return fetch('/api/projects/' + projectId, { method: 'POST', body: formData })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.status === 'saved') console.log('Project saved');
            return data;
        })
        .catch(function(err) { console.error('Failed to save project:', err); throw err; });
}

// === Tool Selector ===
function buildToolSelector(enabledTools) {
    buildToolSelectorForElement('details-tool-selector', enabledTools);
}
// Generic tool selector builder for any element ID
function buildToolSelectorForElement(elementId, disabledTools, customTools) {
    var container = document.getElementById(elementId);
    if (!container) return;
    var html = '';

    // Built-in tools section
    html += '<div style="margin-bottom:12px;">';
    html += '<div style="font-size:11px;font-weight:bold;color:var(--text-muted);margin-bottom:4px;">BUILT-IN TOOLS</div>';
    html += '<div class="tool-selector-grid">';
    var tools = AVAILABLE_TOOLS.slice().sort();
    tools.forEach(function(toolName) {
        // All tools checked by default; unchecked = disabled
        var isChecked = disabledTools && disabledTools.indexOf(toolName) === -1;
        html += '<label class="tool-checkbox" style="display:flex;align-items:center;gap:6px;font-size:12px;padding:4px 8px;background:var(--muted);border-radius:4px;cursor:pointer;min-width:0;">' +
            '<input type="checkbox" class="tool-cb" data-toolname="' + escapeHtml(toolName) + '" value="' + toolName + '" ' + (isChecked ? 'checked' : '') + '>' +
            '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;">' + escapeHtml(toolName) + '</span></label>';
    });
    html += '</div></div>';

    // Custom tools section
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

function buildToolSelector(disabledTools, customTools) {
    buildToolSelectorForElement('details-tool-selector', disabledTools, customTools);
}


function getEnabledTools() {
    // Per-project disabled_tools is now handled via the project form UI.
    // This function is kept for backward compatibility but no longer used.
    return AVAILABLE_TOOLS.slice();
}

// === Jobs ===
function loadJobs() {
    Promise.all([
        fetch('/api/queue').then(function(r) { return r.json(); }),
        fetch('/api/history').then(function(r) { return r.json(); })
    ])
    .then(function(data) {
        var queueData = data[0];
        var history = data[1];
        renderJobs(queueData, history);
        if (currentProjectId) {
            var currentStatus = null;
            if (queueData.running && queueData.running.project_id === currentProjectId) currentStatus = 'running';
            else if (queueData.queue && queueData.queue.some(function(j) { return j.project_id === currentProjectId; })) currentStatus = 'queued';
            // Also check for pending_approval or pending_user_input in history
            if (!currentStatus) {
                var pendingJob = history.find(function(h) {
                    return h.project_id === currentProjectId &&
                           (h.status === 'pending_approval' || h.status === 'pending_user_input');
                });
                if (pendingJob) currentStatus = pendingJob.status;
            }
            updateRunButtonState(currentProjectId, currentStatus);
        }
    })
    .catch(function(err) { console.error('Failed to load jobs:', err); var list = document.getElementById('jobs-list'); if (list) list.innerHTML = '<div class="note warning">Failed to load jobs.</div>'; });
}

function renderJobs(queueData, history) {
    var list = document.getElementById('jobs-list');
    if (!list) return;
    list.innerHTML = '';
    var items = history.slice();
    var historyIds = {};
    items.forEach(function(i) { historyIds[i.job_id] = true; });
    if (queueData.running && !historyIds[queueData.running.job_id]) items.unshift(queueData.running);
    if (queueData.queue) queueData.queue.forEach(function(j) { if (!historyIds[j.job_id]) items.push(j); });
    if (!items.length) { list.innerHTML = '<div class="note">NO JOBS FOUND.</div>'; return; }
    items.forEach(function(job) {
        var item = document.createElement('div');
        item.className = 'history-item';
        item.dataset.jobId = job.job_id;
        item.onclick = function() { toggleJobSteps(job.job_id); };
        var statusClass = 'completed';
        if (job.status === 'running') statusClass = 'running';
        else if (job.status === 'error') statusClass = 'error';
        else if (job.status === 'stopped') statusClass = 'stopped';

        // Build header
        var header = document.createElement('div');
        header.className = 'history-item-header';
        var nameSpan = document.createElement('span');
        nameSpan.className = 'history-item-name';
        nameSpan.textContent = job.project_name || 'Unknown Project';
        header.appendChild(nameSpan);
        var statusSpan = document.createElement('span');
        statusSpan.className = 'project-item-status ' + statusClass;
        statusSpan.textContent = job.status || 'unknown';
        header.appendChild(statusSpan);
        item.appendChild(header);

        // Job ID
        var idDiv = document.createElement('div');
        idDiv.className = 'history-item-id';
        idDiv.textContent = job.job_id.substring(0, 8) + '...';
        item.appendChild(idDiv);

        // Error
        if (job.error) {
            var errDiv = document.createElement('div');
            errDiv.className = 'history-item-error';
            errDiv.textContent = 'Error: ' + job.error;
            item.appendChild(errDiv);
        }

        // Summary
        if (job.summary) {
            var sumDiv = document.createElement('div');
            sumDiv.className = 'history-item-summary';
            sumDiv.textContent = 'Summary: ' + job.summary.substring(0, 150);
            item.appendChild(sumDiv);
        }

        // Steps
        var stepsData = (job.step_history && job.step_history.length > 0) ? job.step_history : (job.steps && Array.isArray(job.steps)) ? job.steps : null;
        if (stepsData) {
            var stepsBtn = document.createElement('button');
            stepsBtn.className = 'btn btn-xs btn-secondary';
            stepsBtn.textContent = '▼ SHOW STEPS (' + stepsData.length + ')';
            stepsBtn.onclick = function(e) { e.stopPropagation(); toggleJobSteps(job.job_id); };
            item.appendChild(stepsBtn);

            var stepsList = document.createElement('div');
            stepsList.id = 'job-steps-' + job.job_id;
            stepsList.className = 'job-steps-list';
            stepsList.style.display = 'none';
            stepsData.forEach(function(s) {
                var stepItem = document.createElement('div');
                stepItem.className = 'job-step-item';

                var stepNum = document.createElement('span');
                stepNum.className = 'step-num';
                stepNum.textContent = 'Step ' + s.step;
                stepItem.appendChild(stepNum);

                var toolName = document.createElement('span');
                toolName.className = 'step-tool-name';
                if (s.tool === 'llm_call') {
                    toolName.textContent = '[Thinking]';
                } else if (s.tool === 'request_user_input') {
                    toolName.textContent = '[⏸ User Input]';
                } else {
                    toolName.textContent = '[' + s.tool + ']';
                }
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

                // Rationale
                if (s.rationale) {
                    var ratDiv = document.createElement('div');
                    ratDiv.style.cssText = 'color:var(--mc-gold);font-size:9px;margin-left:16px;font-style:italic;';
                    ratDiv.textContent = '💡 ' + s.rationale;
                    stepItem.appendChild(ratDiv);
                }

                stepsList.appendChild(stepItem);
            });
            item.appendChild(stepsList);
        } else if (job.step_count !== undefined) {
            var stepCountDiv = document.createElement('div');
            stepCountDiv.style.cssText = 'font-size:11px;color:var(--text-muted);margin-top:4px;';
            stepCountDiv.textContent = 'Completed ' + (job.steps || 0) + ' steps';
            item.appendChild(stepCountDiv);
        }

        // Delete button
        var delBtn = document.createElement('button');
        delBtn.className = 'btn btn-xs btn-secondary';
        delBtn.style.cssText = 'margin-top:6px;';
        delBtn.textContent = 'DELETE';
        delBtn.onclick = function(e) { e.stopPropagation(); deleteJob(job.job_id); };
        item.appendChild(delBtn);

        list.appendChild(item);
    });
}

function toggleJobSteps(jobId) {
    var el = document.getElementById('job-steps-' + jobId);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}



function deleteJob(jobId) {
    if (!confirm('Delete this job?')) return;
    fetch('/api/queue/' + jobId, { method: 'DELETE' })
        .then(function() { loadJobs(); })
        .catch(function(err) { console.error('Failed to delete job:', err); });
}

function clearJobHistory() {
    if (!confirm('Are you sure you want to clear all job history?')) return;
    fetch('/api/history/clear', { method: 'POST' })
        .then(function(res) { return res.json(); })
        .then(function(data) { if (data.status === 'cleared') loadJobs(); else showNotification('Failed to clear history: ' + (data.error || 'Unknown error', 'info')); })
        .catch(function(err) { console.error('Failed to clear history:', err); showNotification('Failed to clear history.', 'info'); });
}


// === Chat ===
function loadChats() {
    fetch('/api/chats')
        .then(function(r) { return r.json(); })
        .then(function(chats) {
            var list = document.getElementById('chat-list');
            if (!list) return;
            list.innerHTML = '';
            if (!chats.length) { list.innerHTML = '<div class="note">NO CHATS FOUND.</div>'; return; }
            chats.forEach(function(chat) {
                var item = document.createElement('div');
                item.className = 'chat-item' + (chat.id === currentChatId ? ' active' : '');
                var nameSpan = document.createElement('span');
                nameSpan.className = 'chat-item-name';
                nameSpan.textContent = chat.title || 'New Chat';
                item.appendChild(nameSpan);
                item.onclick = function() { openChat(chat.id); };
                list.appendChild(item);
            });
        })
        .catch(function(err) { console.error('Failed to load chats:', err); });
}

function newChat() {
    // Switch to chat tab first
    showTab('chat');
    fetch('/api/chats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ timestamp: new Date().toISOString() }) })
        .then(function(r) { return r.json(); })
        .then(function(data) { loadChats(); openChat(data.id); })
        .catch(function(err) { console.error('Failed to create chat:', err); });
}

function openChat(chatId) {
    currentChatId = chatId;
    localStorage.setItem('currentChatId', chatId);
    fetch('/api/chats/' + chatId)
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

                    // Copy button at bottom-right of the message body
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
            // Show the chat view container
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

    // Copy button at bottom-right of the message body
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

    // Copy button at bottom-right of the message body
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

    fetch('/api/chats/' + currentChatId + '/messages', {
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
    fetch('/api/settings')
        .then(function(r) { return r.json(); })
        .then(function(settings) {
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
        })
        .catch(function(err) { console.error('Failed to load settings:', err); });
}

function reloadSettingsFromDisk() {
    fetch('/api/settings/reload', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'reloaded') { loadSettingsUI(); showNotification('Settings reloaded from disk!', 'info'); }
            else showNotification('Failed to reload settings: ' + (data.error || 'Unknown error', 'info'));
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
    };
    fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings) })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'saved') showNotification('Settings saved! Changes will apply on next run.', 'info');
            else showNotification('Failed to save settings: ' + (data.error || 'Unknown error', 'info'));
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

// Returns a promise that resolves when the user clicks OK
function showNotificationModalPromise(message, type) {
    return new Promise(function(resolve) {
        showNotificationModal(message, type);
        _notificationResolve = resolve;
    });
}

// Wait for user to click OK before continuing
async function showNotificationAndWait(message, type) {
    return await showNotificationModalPromise(message, type);
}

// Close notification modal on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        var notifModal = document.getElementById('notification-modal');
        if (notifModal && notifModal.style.display === 'flex') {
            closeNotificationModal();
        }
    }
});

// === Live View Functions ===
function showLiveView(project_id) {
    // Check if there's a running job for this project (queue or SSE)
    fetch('/api/queue')
        .then(function(r) { return r.json(); })
        .then(function(queueData) {
            // Check queue-based running job
            if (queueData.running && queueData.running.project_id === project_id) {
                showLiveViewForJob(queueData.running.job_id);
                return;
            }
            // Check SSE jobs
            if (queueData.sse_jobs && queueData.sse_jobs.length > 0) {
                // Check history to find which SSE job belongs to this project
                return fetch('/api/history')
                    .then(function(r) { return r.json(); })
                    .then(function(history) {
                        var sseJob = queueData.sse_jobs.find(function(s) {
                            return history.some(function(h) {
                                return h.job_id === s.job_id && h.project_id === project_id;
                            });
                        });
                        if (sseJob) {
                            showLiveViewForJob(sseJob.job_id);
                            return;
                        }
                        // Fall through to check pending jobs
                        checkPendingJobs(project_id);
                    });
            }
            // No running job found - check for pending jobs
            checkPendingJobs(project_id);
        })
        .catch(function(err) { console.error('Failed to check job status:', err); showNotification('No active job to view', 'warning'); });
}

function checkPendingJobs(project_id) {
    fetch('/api/history')
        .then(function(r) { return r.json(); })
        .then(function(history) {
            // First look for pending jobs (approval or user input)
            var pendingJob = history.find(function(h) {
                return h.project_id === project_id &&
                       (h.status === 'pending_approval' || h.status === 'pending_user_input');
            });
            if (pendingJob) {
                showLiveViewForJob(pendingJob.job_id);
                return;
            }
            // Also allow VIEW LIVE for completed/stopped/error jobs so user can review steps
            var lastJob = history.find(function(h) { return h.project_id === project_id; });
            if (lastJob) {
                showLiveViewForJob(lastJob.job_id);
            } else {
                showNotification('No active job to view', 'warning');
            }
        })
        .catch(function(err) { console.error('Failed to check job history:', err); showNotification('No active job to view', 'warning'); });
}

function showLiveViewForJob(jobId) {
    var container = document.getElementById('agent-live-container');
    if (!container) return;

    // Ensure the project-details panel is active so the container is visible
    var detailsPanel = document.getElementById('project-details-panel');
    if (detailsPanel) detailsPanel.classList.add('active');

    // Hide project config section, show agent live view (same as RUN)
    var configSection = document.getElementById('project-config-section');
    if (configSection) configSection.style.display = 'none';
    container.style.display = 'block';
    container.scrollIntoView({ behavior: 'smooth' });
    container.dataset.jobId = jobId;
    currentRunningJobId = jobId;

    // Always clear any stale poll interval and inject state before starting fresh
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = true; injectInput.placeholder = 'Loading...'; }
    if (injectBtn) { injectBtn.disabled = true; injectBtn.textContent = 'LOADING...'; }

    // Show refresh button
    var refreshBtn = document.getElementById('live-refresh-btn');
    if (refreshBtn) refreshBtn.style.display = 'inline-block';
    // Preserve currentRunningProjectId — don't set to null

    // Check if the job is still running/paused in queue OR in history with pending status
    Promise.all([
        fetch('/api/queue').then(function(r) { return r.json(); }),
        fetch('/api/history').then(function(r) { return r.json(); })
    ])
    .then(function(results) {
        var queueData = results[0];
        var history = results[1];
        var jobRecord = history.find(function(h) { return h.job_id === jobId; });

        var isRunning = queueData.running && queueData.running.job_id === jobId;
        var isPendingApproval = queueData.running && queueData.running.status === 'pending_approval';
        var isPendingInput = queueData.running && queueData.running.status === 'pending_user_input';

        // Also check history for pending status (for paused SSE jobs)
        if (!isRunning && !isPendingApproval && !isPendingInput && jobRecord) {
            isPendingApproval = jobRecord.status === 'pending_approval';
            isPendingInput = jobRecord.status === 'pending_user_input';
        }

        // Resolve the output directory for this job (needed for pending tool checks)
        var outputDir = null;
        if (jobRecord && jobRecord.output_dir) {
            outputDir = jobRecord.output_dir;
        } else if (currentRunningProjectId) {
            // Fallback: get output_dir from the project
            fetch('/api/projects/' + currentRunningProjectId)
                .then(function(r) { return r.json(); })
                .then(function(proj) {
                    outputDir = proj.output_dir;
                    _resolveOutputDirAndContinue(jobId, queueData, history, jobRecord, isRunning, isPendingApproval, isPendingInput, outputDir);
                })
                .catch(function() {
                    _resolveOutputDirAndContinue(jobId, queueData, history, jobRecord, isRunning, isPendingApproval, isPendingInput, null);
                });
        } else {
            _resolveOutputDirAndContinue(jobId, queueData, history, jobRecord, isRunning, isPendingApproval, isPendingInput, null);
        }
    })
    .catch(function(err) { console.error('Failed to check job status:', err); });
}

function _resolveOutputDirAndContinue(jobId, queueData, history, jobRecord, isRunning, isPendingApproval, isPendingInput, outputDir) {
    var agentBox = document.getElementById('agent-live-box');
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');

    if (isRunning && !isPendingApproval && !isPendingInput) {
        // Job is actively running (not pending) - show the view and start polling
        agentRunning = true;
        liveInjectActive = true;
        // Show stop button
        var stopBtn = document.getElementById('details-stop-btn');
        if (stopBtn) stopBtn.style.display = 'inline-block';
        var liveStopBtn = document.getElementById('live-stop-btn');
        if (liveStopBtn) liveStopBtn.style.display = 'inline-block';
        if (agentBox) {
            agentBox.innerHTML = '<div class="step-entry llm-step">📺 Viewing live feed for running job (LIVE)...</div>';
        }
        var statusText = document.getElementById('agent-status-text');
        if (statusText) { statusText.textContent = 'LIVE'; statusText.style.color = 'var(--success)'; }
        if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions or questions...'; }
        if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
        // Start polling for live updates
        _startPolling(jobId, outputDir, agentBox);
    } else {
        // Job is pending, completed, or stopped - load history and show it
        loadJobHistory(jobId, function() {
            // Always start polling (every 30s) so the feed auto-refreshes
            // even for completed jobs — user can see if a continuation started
            _startPolling(jobId, outputDir, agentBox);

            // After loading history, check for pending approval tools
            // This handles the case where we re-enter VIEW LIVE for a job that has pending tools
            if (isPendingApproval && outputDir) {
                _showPendingApproval(jobId, outputDir, agentBox);
            }

            // Enable inject if job is pending (user can inject to resume)
            if (isPendingApproval || isPendingInput) {
                agentRunning = false;
                liveInjectActive = true;
                var stopBtn = document.getElementById('details-stop-btn');
                if (stopBtn) stopBtn.style.display = 'inline-block';
                if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions to resume...'; }
                if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
                var statusText = document.getElementById('agent-status-text');
                if (statusText) {
                    statusText.textContent = isPendingApproval ? 'PENDING APPROVAL' : 'AWAITING INPUT';
                    statusText.style.color = 'var(--warning)';
                }
            } else if (jobRecord) {
                // Completed or stopped job - show status
                var statusText = document.getElementById('agent-status-text');
                if (statusText) {
                    statusText.textContent = jobRecord.status === 'completed' ? 'COMPLETED' : (jobRecord.status === 'error' ? 'ERROR' : (jobRecord.status === 'stopped' ? 'STOPPED' : jobRecord.status.toUpperCase()));
                    statusText.style.color = jobRecord.status === 'completed' ? 'var(--success)' : (jobRecord.status === 'error' ? 'var(--danger)' : 'var(--text-muted)');
                }
                // Enable inject for completed jobs so user can INJECT to resume
                if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Continue with new instructions...'; }
                if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
            }
        });
    }
}

function loadJobHistory(jobId, callback) {
    var agentBox = document.getElementById('agent-live-box');
    var statusText = document.getElementById('agent-status-text');
    var container = document.getElementById('agent-live-container');

    // Try to get step history from the job
    fetch('/api/agent/history/' + jobId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.steps && data.steps.length > 0) {
                agentBox.innerHTML = '';
                data.steps.forEach(function(step) {
                    // Reuse handleAgentStep so all tools render with proper formatting
                    // (respond_to_user full content, task_completed celebration, etc.)
                    handleAgentStep(step, agentBox);
                });
                if (statusText) { statusText.textContent = 'HISTORY'; statusText.style.color = 'var(--text-muted)'; }
                // Set currentRunningProjectId if available in data
                if (data.project_id) {
                    currentRunningProjectId = data.project_id;
                }
                // Store outputDir on the container for polling
                if (data.output_dir && container) {
                    container.dataset.outputDir = data.output_dir;
                }
                if (callback) callback();
            } else {
                // Try to get history from the job history API
                fetch('/api/history')
                    .then(function(r) { return r.json(); })
                    .then(function(history) {
                        var job = history.find(function(h) { return h.job_id === jobId; });
                        if (job && job.step_history && job.step_history.length > 0) {
                            agentBox.innerHTML = '';
                            job.step_history.forEach(function(step) {
                                // Reuse handleAgentStep for consistent formatting
                                handleAgentStep(step, agentBox);
                            });
                            if (statusText) { statusText.textContent = 'HISTORY'; statusText.style.color = 'var(--text-muted)'; }
                            // Set currentRunningProjectId for inject continuation
                            if (job && job.project_id) {
                                currentRunningProjectId = job.project_id;
                            }
                            // Store outputDir on the container for polling
                            if (job.output_dir && container) {
                                container.dataset.outputDir = job.output_dir;
                            }
                            if (callback) callback();
                        } else {
                            agentBox.innerHTML = '<div class="step-entry llm-step">No history available for this job.</div>';
                            if (statusText) { statusText.textContent = 'NO HISTORY'; statusText.style.color = 'var(--text-muted)'; }
                            if (callback) callback();
                        }
                    });
            }
        })
        .catch(function(err) { console.error('Failed to load job history:', err); });
}

function refreshLiveView() {
    var container = document.getElementById('agent-live-container');
    if (!container) return;
    var jobId = container.dataset.jobId || currentRunningJobId;
    if (!jobId) {
        // No job ID — try to find it from the queue
        fetch('/api/queue')
            .then(function(r) { return r.json(); })
            .then(function(qd) {
                if (qd.running) {
                    currentRunningJobId = qd.running.job_id;
                    refreshLiveView();
                } else {
                    showNotification('No active job to refresh.', 'info');
                }
            });
        return;
    }
    var agentBox = document.getElementById('agent-live-box');
    if (agentBox) {
        agentBox.innerHTML = '<div class="step-entry llm-step">🔄 Refreshing...</div>';
    }
    loadJobHistory(jobId, function() {
        var agentBox2 = document.getElementById('agent-live-box');
        if (agentBox2) {
            var refreshMsg = document.createElement('div');
            refreshMsg.className = 'step-entry';
            refreshMsg.style.borderLeftColor = 'var(--mc-diamond)';
            refreshMsg.style.background = 'rgba(74, 237, 223, 0.1)';
            refreshMsg.innerHTML = '<div class="step-tool" style="color:var(--mc-diamond);">✅ Feed refreshed</div>';
            agentBox2.appendChild(refreshMsg);
            agentBox2.scrollTop = agentBox2.scrollHeight;
        }
    });
}

// === Inject Live Instruction ===
function injectLiveInstruction() {
    var input = document.getElementById('live-inject-input');
    var btn = document.getElementById('live-inject-btn');
    if (!input || !btn) return;
    var instruction = input.value.trim();
    if (!instruction) return;

    var jobId = currentRunningJobId;
    if (!jobId) {
        // Try to find the job from the container
        var container = document.getElementById('agent-live-container');
        if (container) jobId = container.dataset.jobId;
    }
    if (!jobId) {
        showNotification('No active job to inject into', 'warning');
        return;
    }

    // Disable the button while injecting
    btn.disabled = true;
    btn.textContent = 'INJECTING...';
    input.disabled = true;

    // Check if the job is in pending_user_input state — if so, use the resume endpoint
    fetch('/api/job/' + jobId + '/status')
        .then(function(r) { return r.json(); })
        .then(function(statusData) {
            if (statusData.status === 'pending_user_input') {
                // Use the resume endpoint which re-invokes the engine
                return fetch('/api/agent/resume', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({job_id: jobId, input: instruction})
                }).then(function(r) { return r.json(); });
            } else {
                // Use the inject endpoint for running jobs
                return fetch('/api/agent/inject', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({job_id: jobId, instruction: instruction})
                }).then(function(r) { return r.json(); });
            }
        })
        .then(function(data) {
            if (data.error) throw new Error(data.error);
            input.value = '';

            if (data.continuation) {
                // A new engine run was started for this completed job.
                // Show a continuation message in the live feed.
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

                // Update status text
                var statusText = document.getElementById('agent-status-text');
                if (statusText) { statusText.textContent = 'CONTINUING...'; statusText.style.color = 'var(--info)'; }

                // Start polling for the continuation results
                // Get outputDir from the container or project
                var container = document.getElementById('agent-live-container');
                var outputDir = container ? container.dataset.outputDir : null;
                if (!outputDir && currentRunningProjectId) {
                    fetch('/api/projects/' + currentRunningProjectId)
                        .then(function(r) { return r.json(); })
                        .then(function(proj) {
                            outputDir = proj.output_dir;
                            _startPolling(jobId, outputDir, null);
                        });
                } else {
                    _startPolling(jobId, outputDir, null);
                }

                showNotification('Continuation started — engine running', 'success');
            } else if (data.status === 'resume_input_saved') {
                // Resume was triggered — engine is restarting
                var agentBox = document.getElementById('agent-live-box');
                if (agentBox) {
                    var contEntry = document.createElement('div');
                    contEntry.className = 'step-entry';
                    contEntry.style.borderLeftColor = 'var(--info)';
                    contEntry.style.background = 'rgba(74, 237, 223, 0.1)';
                    contEntry.innerHTML = '<div class="step-tool" style="color:var(--info);">🔄 RESUMING AGENT...</div>';
                    agentBox.appendChild(contEntry);
                    agentBox.scrollTop = agentBox.scrollHeight;
                }
                var statusText = document.getElementById('agent-status-text');
                if (statusText) { statusText.textContent = 'RESUMING...'; statusText.style.color = 'var(--info)'; }
                showNotification('Agent resumed — waiting for response', 'success');
            } else {
                showNotification('Instruction injected successfully', 'success');
            }

            // Re-enable after a short delay
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

// === Init ===

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
            // Collect disabled_tools from the tool selector checkboxes
            var checkboxes = document.querySelectorAll('#add-tool-selector input[type="checkbox"]');
            var disabledTools = [];
            checkboxes.forEach(function(cb) {
                if (cb.checked) {
                    disabledTools.push(cb.value);
                }
            });
            var formRef = this;
            fetch('/api/projects', { method: 'POST', body: formData })
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    if (data.error) { showNotification('Error: ' + data.error, 'error'); }
                    else {
                        // Save disabled_tools via dedicated endpoint
                        var pid = data.id;
                        if (pid && disabledTools.length > 0) {
                            fetch('/api/projects/' + pid + '/tools', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({disabled_tools: disabledTools})
                            }).catch(function(err) { console.error('Failed to save disabled tools:', err); });
                        }
                        loadProjects(); formRef.reset(); toggleCreateForm();
                    }
                })
                .catch(function(err) { console.error('Failed to create project:', err); });
        });
    }

    // Load initial data
    loadProjectsCached();
    loadJobs();
    loadChats();

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
});
