// === State ===
let currentProjectId = localStorage.getItem('currentProjectId') || null;
let currentChatId = localStorage.getItem('currentChatId') || null;
let showArchived = false;
let autoSaveTimeout = null;
let pendingRootPathChange = null;
let pendingRootPathElementId = null;

// === Live Agent State ===
let currentRunningJobId = null;
let agentSSEController = null;
let agentRunning = false;
let liveInjectActive = false;
let currentRunningProjectId = null;
let _loadedProjects = [];

// === Available Tools ===
const AVAILABLE_TOOLS = [
    "list_directory", "list_directory_deep", "search_files", "search_files_dir",
    "grep_code", "grep_code_dir", "read_file", "read_file_range",
    "write_file", "edit_file", "delete_file", "find_symbol",
    "decompile_jar", "list_dependencies", "check_syntax", "get_file_info",
    "create_tool", "compress_context", "respond_to_user", "request_user_input"
];

// === Utility Functions ===
function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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
    var html = escapeHtml(md);
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
            '<div style="position:relative;margin:4px 0;"><button class="pre-copy-btn" onclick="copyCodeBlock(\'' + block.id + '\', this)" style="position:absolute;top:4px;right:4px;background:var(--wood);border:1px solid #000;padding:3px 8px;cursor:pointer;font-size:8px;color:#fff;z-index:10;border-radius:3px;font-family:\'Press Start 2P\',monospace;">COPY</button><pre style="background:#111;padding:8px;border-radius:4px;overflow-x:auto;margin:0;"><code id="' + block.id + '" style="white-space:pre-wrap;">' + escaped + '</code></pre></div>');
    });
    return html;
}

function copyCodeBlock(id, btn) {
    var el = document.getElementById(id);
    if (!el) return;
    var text = el.textContent || el.innerText || '';
    // Decode HTML entities
    var decoded = text.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
    // Strip language label if present (e.g., "python\nprint(...)" -> "print(...)")
    var firstLineEnd = decoded.indexOf('\n');
    if (firstLineEnd !== -1) {
        var firstLine = decoded.substring(0, firstLineEnd).trim().toLowerCase();
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
    if (tabName === 'tools') loadPendingTools();
}

// === Project Form Toggle ===
function toggleCreateForm() {
    var form = document.getElementById('create-project-form');
    if (form) form.style.display = form.style.display === 'none' ? 'block' : 'none';
    // Build tool selector when form is shown
    if (form && form.style.display === 'block') {
        buildToolSelectorForElement('add-tool-selector', []);
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
                projectItem.innerHTML =
                    '<div class="project-item-header">' +
                        '<span class="project-item-name">' + escapeHtml(project.name || 'Untitled') + '</span>' +
                        (project.run_number > 0 ? '<span style="color:var(--text-muted);font-size:11px;">Run #' + project.run_number + '</span>' : '') +
                    '</div>' +
                    '<div class="project-item-meta">' +
                        '<span class="project-item-path">' + escapeHtml(project.rootDirectory || '') + '</span>' +
                        '<div class="project-item-actions">' +
                            (project.status === 'running' ? '<button class="btn btn-sm btn-info" onclick="event.stopPropagation(); showLiveViewForJob(\'' + project.id + '\')">📺 LIVE</button>' : '<button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); runProject(\'' + project.id + '\')">RUN</button>') +
                            (project.status === 'running' ? '<button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); stopProject(\'' + project.id + '\')">STOP</button>' : '<button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); stopProject(\'' + project.id + '\')" style="display:none;">STOP</button>') +
                            '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); resetProject(\'' + project.id + '\')">RESET</button>' +
                            '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); archiveProject(\'' + project.id + '\', this)" title="Archive">' +
                                (project.isArchived ? '📤' : '📦') +
                            '</button>' +
                            '<button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteProject(\'' + project.id + '\')">DEL</button>' +
                        '</div>' +
                    '</div>';
                projectList.appendChild(projectItem);
            });
        })
        .catch(function(err) { console.error('Failed to load projects:', err); });
}

function runProject(projectId) {
    var project = getProjectById(projectId);
    if (!project) {
        fetch('/api/projects/' + projectId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) { alert('Project not found'); return; }
                _loadedProjects = _loadedProjects || [];
                if (!_loadedProjects.find(function(p) { return p.id === projectId; })) _loadedProjects.push(data);
                _doRunProject(projectId);
            })
            .catch(function(err) { console.error('Failed to fetch project:', err); alert('Failed to load project details'); });
        return;
    }
    _doRunProject(projectId);
}

function _doRunProject(projectId, overrideInstruction) {
    var rootDir = document.getElementById('details-root-dir') ? document.getElementById('details-root-dir').value : '';
    if (!rootDir) { alert('Please set a root directory first.'); return; }
    var instructions = overrideInstruction || (document.getElementById('details-instructions') ? document.getElementById('details-instructions').value : '');
    var enabledTools = getEnabledTools();
    // Use /api/agent/run which streams SSE — no conflict with worker
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
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = '<span class="run-spinner"></span> RUNNING...'; }
    if (stopBtn) stopBtn.style.display = 'inline-block';
    // Keep inject button enabled so user can inject at will
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions or questions...'; }
    if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
    // Scroll to agent live box
    if (agentLive) {
        setTimeout(function() { agentLive.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 100);
    }
    fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, rootDirectory: rootDir, instructions: instructions, enabled_tools: enabledTools })
    })
    .then(function(response) {
        if (!response.ok) throw new Error('Failed to start agent run');
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';
        function processChunk() {
            reader.read().then(function(result) {
                var done = result.done;
                var value = result.value;
                if (done || !agentRunning) {
                    // Process any remaining events in the buffer before returning
                    // (e.g., the 'complete' status event might be in the buffer)
                    if (buffer && buffer.length > 0) {
                        buffer = parseSSEMessage(buffer, function(eventType, data) {
                            if (eventType === 'status') handleAgentStatus(data);
                            else if (eventType === 'step') handleAgentStep(data, agentBox);
                            else if (eventType === 'tool_start') handleToolStart(data, agentBox);
                            else if (eventType === 'pending_approval') handlePendingApproval(data, agentBox);
                            else if (eventType === 'pending_user_input') handlePendingUserInput(data, agentBox);
                        });
                    }
                    agentRunning = false;
                    resetRunButtons();
                    if (stopBtn) stopBtn.style.display = 'none';
                    // Only disable inject button if handleAgentStatus didn't already enable it
                    if (!liveInjectActive) {
                        if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Agent stopped'; }
                        if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
                    }
                    return;
                }
                buffer += decoder.decode(value, { stream: true });
                buffer = parseSSEMessage(buffer, function(eventType, data) {
                    if (eventType === 'status') handleAgentStatus(data);
                    else if (eventType === 'step') handleAgentStep(data, agentBox);
                    else if (eventType === 'tool_start') handleToolStart(data, agentBox);
                    else if (eventType === 'pending_approval') handlePendingApproval(data, agentBox);
                    else if (eventType === 'pending_user_input') handlePendingUserInput(data, agentBox);
                });
                setTimeout(processChunk, 0);
            });
        }
        processChunk();
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

// === Agent SSE ===
function startAgentSSE(projectId, enabledTools) {
    if (agentSSEController) agentSSEController.abort();
    agentSSEController = new AbortController();
    var agentBox = document.getElementById('agent-live-box');
    if (agentBox) agentBox.innerHTML = '';
    fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, enabled_tools: enabledTools }),
        signal: agentSSEController.signal
    })
    .then(function(response) {
        if (!response.ok) throw new Error('Failed to start agent run');
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';
        function processChunk() {
            reader.read().then(function(result) {
                var done = result.done;
                var value = result.value;
                if (done || !agentRunning) {
                    agentRunning = false;
                    liveInjectActive = false;
                    resetRunButtons();
                    return;
                }
                buffer += decoder.decode(value, { stream: true });
                buffer = parseSSEMessage(buffer, function(eventType, data) {
                    if (eventType === 'status') handleAgentStatus(data);
                    else if (eventType === 'step') handleAgentStep(data, agentBox);
                    else if (eventType === 'tool_start') handleToolStart(data, agentBox);
                    else if (eventType === 'pending_approval') handlePendingApproval(data, agentBox);
                    else if (eventType === 'pending_user_input') handlePendingUserInput(data, agentBox);
                });
                setTimeout(processChunk, 0);
            });
        }
        processChunk();
    })
    .catch(function(err) {
        if (err.name === 'AbortError') { console.log('Agent run stopped'); }
        else {
            console.error('Agent run error:', err);
            var errEntry = document.createElement('div');
            errEntry.className = 'step-entry error';
            errEntry.textContent = 'ERROR: ' + err.message;
            if (agentBox.firstChild) agentBox.insertBefore(errEntry, agentBox.firstChild);
            else agentBox.appendChild(errEntry);
            agentBox.scrollTop = 0;
        }
        agentRunning = false;
        liveInjectActive = false;
        resetRunButtons();
    });
}

function parseSSEMessage(buffer, onEvent) {
    var delimIdx;
    while ((delimIdx = buffer.indexOf('\n\n')) !== -1) {
        var message = buffer.substring(0, delimIdx);
        buffer = buffer.substring(delimIdx + 2);
        var lines = message.split('\n');
        var eventType = 'message';
        var dataStr = '';
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (line.startsWith('event: ')) eventType = line.substring(7).trim();
            else if (line.startsWith('data: ')) dataStr = line.substring(6);
        }
        if (dataStr) {
            try { var data = JSON.parse(dataStr); onEvent(eventType, data); }
            catch (e) { console.warn('Failed to parse SSE data:', e); }
        }
    }
    while ((delimIdx = buffer.indexOf('\n')) !== -1) {
        var line = buffer.substring(0, delimIdx).trim();
        buffer = buffer.substring(delimIdx + 1);
        if (!line) continue;
        if (line.startsWith('event: ')) {
            var eventType2 = line.substring(7).trim();
            var dataIdx = buffer.indexOf('\n');
            if (dataIdx !== -1) {
                var dataLine = buffer.substring(0, dataIdx).trim();
                buffer = buffer.substring(dataIdx + 1);
                if (dataLine.startsWith('data: ')) {
                    var dataStr2 = dataLine.substring(6);
                    try { var data2 = JSON.parse(dataStr2); onEvent(eventType2, data2); }
                    catch (e) { /* ignore */ }
                }
            }
        }
    }
    return buffer;
}

function handleAgentStatus(data) {
    if (data.type === 'start') {
        currentRunningJobId = data.job_id;
        // Update button states for the current project
        if (currentRunningProjectId) {
            updateRunButtonState(currentRunningProjectId, 'running');
        }
    } else if (data.type === 'complete') {
        loadJobs();
        agentRunning = false;
        liveInjectActive = true;
        // Preserve the last completed job ID so inject can continue from it
        // (don't clear currentRunningJobId)
        var st = document.getElementById('agent-status-text');
        if (st) { st.textContent = 'COMPLETED'; st.style.color = 'var(--success)'; }
        var ii = document.getElementById('live-inject-input');
        var ib = document.getElementById('live-inject-btn');
        if (ii) { ii.disabled = false; ii.placeholder = 'Continue with new instructions...'; }
        if (ib) { ib.disabled = false; ib.textContent = 'INJECT'; }
        var rb = document.getElementById('details-run-btn');
        if (rb) { rb.disabled = false; rb.innerHTML = 'RUN AI BUILDER'; }
    } else if (data.type === 'error') {
        loadJobs();
        agentRunning = false;
        liveInjectActive = true;
        // Preserve job ID on error too
        var st2 = document.getElementById('agent-status-text');
        if (st2) { st2.textContent = 'ERROR'; st2.style.color = 'var(--danger)'; }
        var ii2 = document.getElementById('live-inject-input');
        var ib2 = document.getElementById('live-inject-btn');
        if (ii2) { ii2.disabled = false; ii2.placeholder = 'Fix the error and try again...'; }
        if (ib2) { ib2.disabled = false; ib2.textContent = 'INJECT'; }
        var rb2 = document.getElementById('details-run-btn');
        if (rb2) { rb2.disabled = false; rb2.innerHTML = 'RESUBMIT'; }
    } else if (data.type === 'pending_approval') {
        agentRunning = false;
        liveInjectActive = true;
        var st4 = document.getElementById('agent-status-text');
        if (st4) { st4.textContent = 'PENDING TOOL APPROVAL'; st4.style.color = 'var(--warning)'; st4.style.fontWeight = 'bold'; }
        var ii4 = document.getElementById('live-inject-input');
        var ib4 = document.getElementById('live-inject-btn');
        if (ii4) { ii4.disabled = false; ii4.placeholder = 'Go to TOOLS tab to approve/reject the pending tool...'; }
        if (ib4) { ib4.disabled = false; ib4.textContent = 'INJECT'; }
        var rb4 = document.getElementById('details-run-btn');
        if (rb4) { rb4.disabled = false; rb4.innerHTML = 'RUN AI BUILDER'; }
    } else if (data.type === 'pending_user_input') {
        agentRunning = false;
        liveInjectActive = true;
        var st5 = document.getElementById('agent-status-text');
        if (st5) { st5.textContent = 'AWAITING INPUT'; st5.style.color = 'var(--warning)'; st5.style.fontWeight = 'bold'; }
        var ii5 = document.getElementById('live-inject-input');
        var ib5 = document.getElementById('live-inject-btn');
        if (ii5) { ii5.disabled = false; ii5.placeholder = 'Inject instructions or click RUN to continue...'; }
        if (ib5) { ib5.disabled = false; ib5.textContent = 'INJECT'; }
        var rb5 = document.getElementById('details-run-btn');
        if (rb5) { rb5.disabled = false; rb5.innerHTML = 'RUN AI BUILDER'; }
    } else if (data.type === 'max_steps_reached') {
        agentRunning = false;
        liveInjectActive = true;
        var st3 = document.getElementById('agent-status-text');
        if (st3) { st3.textContent = 'MAX STEPS'; st3.style.color = 'var(--warning)'; }
        var ii3 = document.getElementById('live-inject-input');
        var ib3 = document.getElementById('live-inject-btn');
        if (ii3) { ii3.disabled = false; ii3.placeholder = 'Continue with new instructions...'; }
        if (ib3) { ib3.disabled = false; ib3.textContent = 'INJECT'; }
        var rb3 = document.getElementById('details-run-btn');
        if (rb3) { rb3.disabled = false; rb3.innerHTML = 'RUN AI BUILDER'; }
    }
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
        var respContent = data.result ? (data.result.content || '') : '';
        entry.innerHTML = '<div class="step-tool" style="color:var(--info);">💬 AI Response</div><div class="step-result">' + escapeHtml(respContent) + '</div>';
    } else if (data.tool === 'llm_call') {
        var msgCount = data.params ? data.params.messages : 0;
        entry.classList.add('llm-step');
        var rawReq = data.raw_request || '';
        var rawResp = data.raw_response || '';
        var hasRaw = rawReq.length > 0 || rawResp.length > 0;
        var html = '<div class="step-tool">Thinking (' + msgCount + ' messages)</div>';
        html += '<div class="step-result">' + escapeHtml(data.result ? data.result.content : 'Processing request...') + '</div>';
        if (hasRaw) {
            html += '<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">';
            if (rawReq.length > 0) {
                var reqId = 'raw-req-' + data.step + '-' + Math.random().toString(36).substr(2,5);
                var reqPreview = rawReq;
                html += '<details class="raw-data-block"><summary class="raw-summary">📤 Raw Request (' + rawReq.length + ' chars)</summary><div class="raw-content"><pre>' + escapeHtml(reqPreview) + '</pre></div></details>';
            }
            if (rawResp.length > 0) {
                var respId = 'raw-resp-' + data.step + '-' + Math.random().toString(36).substr(2,5);
                var respPreview = rawResp;
                html += '<details class="raw-data-block"><summary class="raw-summary">📥 Raw Response (' + rawResp.length + ' chars)</summary><div class="raw-content"><pre>' + escapeHtml(respPreview) + '</pre></div></details>';
            }
            html += '</div>';
        }
        entry.innerHTML = html;
    } else if (data.tool === 'format_retry') {
        entry.classList.add('llm-step');
        entry.innerHTML = '<div class="step-tool" style="color:var(--warning);">⚠ Format reminder sent</div><div class="step-result" style="color:var(--warning);">' + escapeHtml(data.result ? data.result.content : '') + '</div>';
    } else {
        var ok = data.result && data.result.success !== false;
        var resultPreview = data.result ? (data.result.content || '') : 'no result';
        entry.classList.add(ok ? 'success' : 'error');
        var html = '<div class="step-tool">' + (ok ? '✓' : '✗') + ' ' + escapeHtml(data.tool) + '</div>';
        if (data.rationale) {
            html += '<div class="step-rationale">💡 ' + escapeHtml(data.rationale) + '</div>';
        }
        if (data.params && Object.keys(data.params).length) {
            html += '<div class="step-params">' + escapeHtml(JSON.stringify(data.params)) + '</div>';
            }
        html += '<div class="step-result">' + escapeHtml(resultPreview) + '</div>';
        entry.innerHTML = html;
    }
    agentBox.appendChild(entry);
    agentBox.scrollTop = agentBox.scrollHeight;
}

function handlePendingApproval(data, agentBox) {
    if (!agentBox) return;
    var entry = document.createElement('div');
    entry.className = 'step-entry pending-approval';
    entry.innerHTML =
        '<div class="step-tool">⏸ AGENT WAITING — PENDING TOOL APPROVAL</div>' +
        '<div class="step-result">Tool <strong>"' + escapeHtml(data.tool_name) + '"</strong> proposed. The agent cannot proceed until you approve or reject it.</div>' +
        '<div class="step-result" style="color:var(--warning);margin-top:8px;">👉 Go to TOOLS tab → Review and click APPROVE or REJECT</div>';
    agentBox.insertBefore(entry, agentBox.firstChild);
    agentBox.scrollTop = 0;
    var statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'WAITING FOR TOOL APPROVAL'; statusText.style.color = 'var(--warning)'; statusText.style.fontWeight = 'bold'; }
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = true; injectInput.placeholder = 'Agent is waiting for tool approval...'; }
    if (injectBtn) { injectBtn.disabled = true; injectBtn.textContent = 'WAITING'; }
}

function handlePendingUserInput(data, agentBox) {
    if (!agentBox) return;
    agentRunning = false;
    liveInjectActive = true;
    var entry = document.createElement('div');
    entry.className = 'step-entry pending-approval';
    entry.innerHTML = '<div class="step-tool" style="color:var(--warning);">⏸ AGENT NEEDS HELP</div><div class="step-result" style="color:var(--warning);white-space:pre-wrap;">' + escapeHtml(data.response || 'The agent is waiting for your input.') + '</div>';
    agentBox.appendChild(entry);
    agentBox.scrollTop = agentBox.scrollHeight;
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type a nudge or new instructions...'; }
    if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
    var statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'AWAITING INPUT'; statusText.style.color = 'var(--warning)'; }
    var runBtn = document.getElementById('details-run-btn');
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = 'AWAITING INPUT...'; }
}

function handleToolStart(data, agentBox) {
    if (!agentBox) return;
    var entry = document.createElement('div');
    entry.className = 'step-entry tool-running';
    entry.id = 'tool-running-' + data.step;
    entry.innerHTML = '<div class=\"step-tool\" style=\"color:var(--mc-gold);\">⏳ Running: ' + escapeHtml(data.tool) + ' <span class=\"run-spinner-inline\"></span></div>' +
        (data.rationale ? '<div class=\"step-rationale\">💡 ' + escapeHtml(data.rationale) + '</div>' : '');
    // Insert at top of box so user sees current tool immediately
    if (agentBox.firstChild) agentBox.insertBefore(entry, agentBox.firstChild);
    else agentBox.appendChild(entry);
    agentBox.scrollTop = 0;
    // Update status text
    var statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'RUNNING: ' + (data.tool || 'tool'); statusText.style.color = 'var(--mc-gold)'; }
}

function injectLiveInstruction() {
    var input = document.getElementById('live-inject-input');
    if (!input || !input.value.trim()) return;
    var instruction = input.value.trim();
    var originalValue = input.value;
    input.value = '';
    input.disabled = true;
    var injectBtn = document.getElementById('live-inject-btn');
    if (injectBtn) { injectBtn.disabled = true; injectBtn.textContent = 'SENDING...'; }
    var agentBox = document.getElementById('agent-live-box');
    if (agentBox) {
        var injectEntry = document.createElement('div');
        injectEntry.className = 'step-entry';
        injectEntry.style.borderLeftColor = 'var(--mc-gold)';
        injectEntry.style.background = 'rgba(252, 219, 5, 0.1)';
        injectEntry.innerHTML = '<div class="step-tool" style="color:var(--mc-gold);">📝 USER INJECTION</div><div class="step-result">' + escapeHtml(instruction) + '</div>';
        agentBox.appendChild(injectEntry);
        agentBox.scrollTop = agentBox.scrollHeight;
    }
    if (agentRunning && currentRunningJobId) {
        // Agent is actively running — inject into the live stream
        fetch('/api/agent/inject', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: currentRunningJobId, instruction: instruction })
        })
        .then(function() {
            input.disabled = false;
            if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
            var statusText = document.getElementById('agent-status-text');
            if (statusText) { var orig = statusText.textContent; statusText.textContent = 'Instruction sent'; setTimeout(function() { statusText.textContent = orig; }, 1500); }
        })
        .catch(function(err) { console.error('Failed to inject instruction:', err); input.disabled = false; if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; } });
    } else if (currentRunningProjectId || currentRunningJobId) {
        // Agent is paused (pending_approval or pending_user_input) or completed —
        // restart the run with the injected instruction as a continuation
        // from the previous job, so it picks up where it left off
        continueAgentRunWithInstruction(currentRunningProjectId, currentRunningJobId, instruction);
    } else {
        // No project running — start fresh
        alert('No active project. Select a project and click RUN to start, or inject while an agent is running.');
        input.disabled = false;
        if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
    }
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

function stopProject(projectId) {
    agentRunning = false;
    liveInjectActive = false;
    if (agentSSEController) { agentSSEController.abort(); agentSSEController = null; }
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
        updateRunButtonState(projectId, false);
        loadJobs();
        resetRunButtons();
    })
    .catch(function(err) { console.error('Failed to stop project:', err); });
}

function continueAgentRunWithInstruction(projectId, prevJobId, newInstruction) {
    if (!projectId) return;
    // If no prevJobId, we'll start a new run for the project
    if (!prevJobId) {
        // Start a fresh run with the new instruction
        _doRunProject(projectId, newInstruction);
        return;
    }
    if (agentSSEController) agentSSEController.abort();
    agentSSEController = new AbortController();
    agentRunning = true;
    liveInjectActive = true;
    currentRunningProjectId = projectId;
    currentRunningJobId = null;
    var enabledTools = getEnabledTools();
    var runBtn = document.getElementById('details-run-btn');
    var stopBtn = document.getElementById('details-stop-btn');
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = '<span class="run-spinner"></span> RUNNING...'; }
    if (stopBtn) stopBtn.style.display = 'inline-block';
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
        body: JSON.stringify({ project_id: projectId, instructions: newInstruction, continue_from_job: prevJobId, enabled_tools: enabledTools }),
        signal: agentSSEController.signal
    })
    .then(function(response) {
        if (!response.ok) throw new Error('Failed to start continued agent run');
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';
        function processChunk() {
            reader.read().then(function(result) {
                var done = result.done;
                var value = result.value;
                if (done || !agentRunning) {
                    agentRunning = false;
                    liveInjectActive = true;
                    var iInput = document.getElementById('live-inject-input');
                    var iBtn = document.getElementById('live-inject-btn');
                    if (iInput) { iInput.disabled = false; iInput.placeholder = 'Continue with new instructions...'; }
                    if (iBtn) { iBtn.disabled = false; iBtn.textContent = 'INJECT'; }
                    return;
                }
                buffer += decoder.decode(value, { stream: true });
                buffer = parseSSEMessage(buffer, function(eventType, data) {
                    if (eventType === 'status') handleAgentStatus(data);
                    else if (eventType === 'step') handleAgentStep(data, agentBox);
                    else if (eventType === 'tool_start') handleToolStart(data, agentBox);
                    else if (eventType === 'pending_approval') handlePendingApproval(data, agentBox);
                    else if (eventType === 'pending_user_input') handlePendingUserInput(data, agentBox);
                });
                setTimeout(processChunk, 0);
            });
        }
        processChunk();
    })
    .catch(function(err) {
        if (err.name === 'AbortError') { console.log('Agent run stopped'); }
        else {
            console.error('Agent run error:', err);
            if (agentBox) { var errEntry = document.createElement('div'); errEntry.className = 'step-entry error'; errEntry.textContent = 'ERROR: ' + err.message; agentBox.appendChild(errEntry); agentBox.scrollTop = agentBox.scrollHeight; }
        }
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
                var displayName = escapeHtml(project.name || 'Untitled');
                if (project.run_number > 0) displayName += ' <span style="font-size:12px;color:var(--text-muted);">(Run #' + project.run_number + ')</span>';
                nameEl.innerHTML = displayName;
            }
            safeSet('details-project-name-form', project.name || '');
            safeSet('details-root-dir', project.rootDirectory || '');
            safeSet('details-instructions', project.instructions || '');
            buildToolSelector(project.enabled_tools || []);
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

function goToProject(projectId) {
    selectProject(projectId);
}

function goBackToProjects() {
    if (agentRunning) stopProject(currentProjectId);
    agentRunning = false;
    liveInjectActive = false;
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
            if (data.status === 'reset') { loadProjects(); alert('Project reset successfully!'); }
            else alert('Failed to reset project: ' + (data.error || 'Unknown error'));
        })
        .catch(function(err) { console.error('Failed to reset project:', err); alert('Failed to reset project.'); });
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
    // Add enabled_tools from the tool selector
    var checkboxes = document.querySelectorAll('#details-tool-selector input[type="checkbox"]');
    checkboxes.forEach(function(cb) {
        if (cb.checked) {
            formData.append('enabled_tools', cb.value);
        }
    });
    fetch('/api/projects/' + projectId, { method: 'POST', body: formData })
        .then(function(res) { return res.json(); })
        .then(function(data) { if (data.status === 'saved') console.log('Project saved'); })
        .catch(function(err) { console.error('Failed to save project:', err); });
}

// === Tool Selector ===
function buildToolSelector(enabledTools) {
    buildToolSelectorForElement('details-tool-selector', enabledTools);
}
// Generic tool selector builder for any element ID
function buildToolSelectorForElement(elementId, enabledTools) {
    var container = document.getElementById(elementId);
    if (!container) return;
    container.innerHTML = '';
    fetch('/api/tools/approved')
        .then(function(r) { return r.json(); })
        .then(function(approvedTools) {
            var allTools = AVAILABLE_TOOLS.concat(approvedTools.map(function(t) { return t.name; }));
            allTools.forEach(function(tool) {
                var checked = enabledTools.length === 0 || enabledTools.indexOf(tool) !== -1;
                var label = document.createElement('label');
                label.className = 'tool-checkbox';
                var isCustom = approvedTools.some(function(t) { return t.name === tool; });
                var badge = isCustom ? ' <span style="color:var(--warning);font-size:9px;">[CUSTOM]</span>' : '';
                label.innerHTML = '<input type="checkbox" name="enabled_tools" value="' + tool + '"' + (checked ? ' checked' : '') + '> ' + tool + badge;
                container.appendChild(label);
            });
        })
        .catch(function() {
            AVAILABLE_TOOLS.forEach(function(tool) {
                var checked = enabledTools.length === 0 || enabledTools.indexOf(tool) !== -1;
                var label = document.createElement('label');
                label.className = 'tool-checkbox';
                label.innerHTML = '<input type="checkbox" name="enabled_tools" value="' + tool + '"' + (checked ? ' checked' : '') + '> ' + tool;
                container.appendChild(label);
            });
        });
}


function getEnabledTools() {
    var checkboxes = document.querySelectorAll('#details-tool-selector input[type="checkbox"]');
    var enabled = [];
    checkboxes.forEach(function(cb) { if (cb.checked) enabled.push(cb.value); });
    return enabled;
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
        var stepsData = (job.step_history && job.step_history.length > 0) ? job.step_history : (job.steps && Array.isArray(job.steps)) ? job.steps : null;
        var stepsHtml = '';
        if (stepsData) {
            var stepsHtmlInner = stepsData.map(function(s) {
                if (s.tool === 'llm_call') {
                    var mc = s.params ? s.params.messages : 0;
                    return '<div class="job-step-item"><span class="step-num">Step ' + s.step + '</span><span class="step-tool-name">[Thinking]</span><span class="step-status-ok">✓</span><span style="color:var(--text-muted);">LLM (' + mc + ' msgs)</span></div>';
                }
                var ok = s.result && s.result.success !== false;
                var rt = s.result ? (s.result.content || '').substring(0, 200) : 'no result';
                var rationaleHtml = s.rationale ? '<div style="color:var(--mc-gold);font-size:9px;margin-left:16px;font-style:italic;">💡 ' + escapeHtml(s.rationale) + '</div>' : '';
                return '<div class="job-step-item"><span class="step-num">Step ' + s.step + '</span><span class="step-tool-name">[' + s.tool + ']</span><span class="step-status-' + (ok ? 'ok' : 'err') + '">' + (ok ? '✓' : '✗') + '</span><span style="color:var(--text-muted);">' + escapeHtml(rt) + '</span></div>' + rationaleHtml;
            }).join('');
            stepsHtml = '<button class="btn btn-xs btn-secondary" onclick="event.stopPropagation(); toggleJobSteps(\'' + job.job_id + '\')">▼ SHOW STEPS (' + stepsData.length + ')</button><div id="job-steps-' + job.job_id + '" class="job-steps-list" style="display:none;">' + stepsHtmlInner + '</div>';
        } else if (job.step_count !== undefined) {
            stepsHtml = '<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Completed ' + (job.steps || 0) + ' steps</div>';
        }
        item.innerHTML =
            '<div class="history-item-header">' +
                '<span class="history-item-name">' + escapeHtml(job.project_name || 'Unknown Project') + '</span>' +
                '<span class="project-item-status ' + statusClass + '">' + (job.status || 'unknown') + '</span>' +
            '</div>' +
            '<div class="history-item-id">' + job.job_id.substring(0, 8) + '...</div>' +
            (job.error ? '<div class="history-item-error">Error: ' + escapeHtml(job.error) + '</div>' : '') +
            (job.summary ? '<div class="history-item-summary">Summary: ' + escapeHtml(job.summary.substring(0, 150)) + '</div>' : '') +
            stepsHtml +
            '<div style="margin-top:6px;"><button class="btn btn-xs btn-secondary" onclick="event.stopPropagation(); deleteJob(\'' + job.job_id + '\')">DELETE</button></div>';
        list.appendChild(item);
    });
}

function toggleJobSteps(jobId) {
    var el = document.getElementById('job-steps-' + jobId);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function stopJob(jobId) {
    fetch('/api/queue/running/stop', { method: 'POST' })
        .then(function() { loadJobs(); })
        .catch(function(err) { console.error('Failed to stop job:', err); });
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
        .then(function(data) { if (data.status === 'cleared') loadJobs(); else alert('Failed to clear history: ' + (data.error || 'Unknown error')); })
        .catch(function(err) { console.error('Failed to clear history:', err); alert('Failed to clear history.'); });
}

// === Tools ===
function loadPendingTools() {
    fetch('/api/tools/pending')
        .then(function(r) { return r.json(); })
        .then(function(tools) { renderPendingTools(tools); renderApprovedTools(); })
        .catch(function(err) { console.error('Failed to load pending tools:', err); var list = document.getElementById('pending-tools-list'); if (list) list.innerHTML = '<div class="note warning">Failed to load pending tools.</div>'; });
}

function renderApprovedTools() {
    var list = document.getElementById('approved-tools-list');
    if (!list) return;
    fetch('/api/tools/approved')
        .then(function(r) { return r.json(); })
        .then(function(tools) {
            if (!tools || tools.length === 0) { list.innerHTML = '<div class="note">NO APPROVED TOOLS YET.</div>'; return; }
            list.innerHTML = tools.map(function(t) {
                return '<div style="padding:10px 14px;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:6px;"><strong style="color:var(--success);">' + escapeHtml(t.name) + '</strong><span style="color:var(--text-muted);font-size:11px;margin-left:8px;">' + escapeHtml(t.description || '') + '</span></div>';
            }).join('');
        })
        .catch(function(err) { console.error('Failed to load approved tools:', err); list.innerHTML = '<div class="note warning">Failed to load approved tools.</div>'; });
}

function renderPendingTools(pendingTools) {
    var list = document.getElementById('pending-tools-list');
    if (!list) return;
    list.innerHTML = '';
    if (!pendingTools || pendingTools.length === 0) {
        list.innerHTML = '<div class="note">NO PENDING TOOLS. The agent has not proposed any new tools yet.</div>';
    } else {
        pendingTools.forEach(function(tool) {
            var item = document.createElement('div');
            item.className = 'pending-tool-item';
            var paramsStr = tool.parameters ? JSON.stringify(tool.parameters, null, 2) : '(none)';
            var codePreview = tool.code ? escapeHtml(tool.code).substring(0, 1000) : '(no code)';
            var showMoreId = 'code-show-' + tool.id;
            var codeBlockId = 'code-block-' + tool.id;
            item.innerHTML =
                '<div class="tool-name">' + escapeHtml(tool.name) + '</div>' +
                '<div class="tool-desc">' + escapeHtml(tool.description || '') + '</div>' +
                '<div class="tool-params">' + escapeHtml(paramsStr) + '</div>' +
                '<details style="margin:8px 0;"><summary style="cursor:pointer;color:var(--info);">📄 View Tool Source Code (' + (tool.code ? tool.code.length : 0) + ' chars)</summary>' +
                    '<div id="' + codeBlockId + '" style="margin-top:8px;padding:10px;background:#111;border-radius:4px;overflow:auto;max-height:400px;font-family:monospace;font-size:12px;line-height:1.4;white-space:pre-wrap;">' +
                        codePreview + (tool.code && tool.code.length > 1000 ? '\n\n... [truncated, click "Expand" to see full code]' : '') +
                    '</div>' +
                    (tool.code && tool.code.length > 1000 ? '<button class="btn btn-xs btn-secondary" onclick="event.stopPropagation(); this.parentElement.querySelector(\'div\').style.maxHeight=\'none\'; this.style.display=\'none\';" style="margin-top:4px;">Expand Full Code</button>' : '') +
                '</details>' +
                '<div class="tool-actions">' +
                    '<button class="btn btn-sm btn-primary" onclick="approvePendingTool(\'' + tool.id + '\', \'' + escapeHtml(tool.name) + '\')">✓ APPROVE</button>' +
                    '<button class="btn btn-sm btn-danger" onclick="rejectPendingTool(\'' + tool.id + '\', \'' + escapeHtml(tool.name) + '\')">✗ REJECT</button>' +
                '</div>';
            list.appendChild(item);
        });
    }
}

function approvePendingTool(toolId, toolName) {
    if (!confirm('Approve tool "' + toolName + '"?')) return;
    fetch('/api/tools/pending/' + toolId + '/approve', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'approved') { alert('Tool "' + toolName + '" approved!'); loadPendingTools(); clearPendingApprovalState(); }
            else alert('Failed to approve tool: ' + (data.error || 'Unknown error'));
        })
        .catch(function(err) { console.error('Failed to approve tool:', err); alert('Failed to approve tool.'); });
}

function rejectPendingTool(toolId, toolName) {
    if (!confirm('Reject tool "' + toolName + '"?')) return;
    fetch('/api/tools/pending/' + toolId + '/reject', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'rejected') { alert('Tool "' + toolName + '" rejected.'); loadPendingTools(); clearPendingApprovalState(); }
            else alert('Failed to reject tool: ' + (data.error || 'Unknown error'));
        })
        .catch(function(err) { console.error('Failed to reject tool:', err); alert('Failed to reject tool.'); });
}

function clearPendingApprovalState() {
    var agentBox = document.getElementById('agent-live-box');
    if (agentBox) { var pendingEntries = agentBox.querySelectorAll('.step-entry.pending-approval'); pendingEntries.forEach(function(entry) { entry.remove(); }); }
    var statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'AGENT RUNNING'; statusText.style.color = 'var(--info)'; statusText.style.fontWeight = ''; }
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions or questions...'; }
    if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
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
                item.innerHTML = '<span class="chat-item-name">' + escapeHtml(chat.title || 'New Chat') + '</span>';
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
                    var copyBtn = document.createElement('button');
                    copyBtn.className = 'copy-btn';
                    copyBtn.textContent = 'COPY';
                    copyBtn.onclick = function(e) { e.stopPropagation(); copyToClipboard(getChatMessageText(div), copyBtn); };
                    headerDiv.appendChild(roleSpan);
                    headerDiv.appendChild(copyBtn);
                    div.appendChild(headerDiv);
                    div.appendChild(bodyDiv);
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
    userDiv.appendChild(userBody);
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
    var aiCopyBtn = document.createElement('button');
    aiCopyBtn.className = 'copy-btn';
    aiCopyBtn.textContent = 'COPY';
    aiCopyBtn.onclick = function(e) { e.stopPropagation(); copyToClipboard(getChatMessageText(aiDiv), aiCopyBtn); };
    aiHeader.appendChild(aiCopyBtn);
    aiDiv.appendChild(aiHeader);
    var aiBodyDiv = document.createElement('div');
    aiBodyDiv.className = 'chat-msg-body';
    aiBodyDiv.id = 'chat-stream-text-' + Date.now();
    aiDiv.appendChild(aiBodyDiv);
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
            set('set-max-tool-result-length', settings.max_tool_result_length || '2000');
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
            if (data.status === 'reloaded') { loadSettingsUI(); alert('Settings reloaded from disk!'); }
            else alert('Failed to reload settings: ' + (data.error || 'Unknown error'));
        })
        .catch(function(err) { console.error('Failed to reload settings:', err); alert('Failed to reload settings.'); });
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
            if (data.status === 'saved') alert('Settings saved! Changes will apply on next run.');
            else alert('Failed to save settings: ' + (data.error || 'Unknown error'));
        })
        .catch(function(err) { console.error('Failed to save settings:', err); alert('Failed to save settings.'); });
}

// === Modals ===
function openActionsModal(jobId) {
    fetch('/api/job/' + jobId + '/actions')
        .then(function(r) { return r.json(); })
        .then(function(data) { document.getElementById('actions-modal-content').textContent = data.content || 'No actions file found.'; document.getElementById('actions-modal').style.display = 'flex'; })
        .catch(function(err) { console.error('Failed to load actions:', err); alert('Failed to load actions.'); });
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
    // Simple alert-based notification (no toast system in current UI)
    alert(message);
}

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
            var pendingJob = history.find(function(h) {
                return h.project_id === project_id &&
                       (h.status === 'pending_approval' || h.status === 'pending_user_input');
            });
            if (pendingJob) {
                showLiveViewForJob(pendingJob.job_id);
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

        if (isRunning && !isPendingApproval && !isPendingInput) {
            // Job is actively running (not pending) - show the view and connect to SSE
            agentRunning = true;
            liveInjectActive = true;
            // Show stop button
            var stopBtn = document.getElementById('details-stop-btn');
            if (stopBtn) stopBtn.style.display = 'inline-block';
            var agentBox = document.getElementById('agent-live-box');
            if (agentBox) {
                agentBox.innerHTML = '<div class="step-entry llm-step">📺 Viewing live feed for running job (LIVE)...</div>';
            }
            var statusText = document.getElementById('agent-status-text');
            if (statusText) { statusText.textContent = 'LIVE'; statusText.style.color = 'var(--success)'; }
            var injectInput = document.getElementById('live-inject-input');
            var injectBtn = document.getElementById('live-inject-btn');
            if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions or questions...'; }
            if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
            // Connect to SSE for live feed (job is actively running, not pending)
            connectToJobSSE(jobId);
        } else {
            // Job is pending, completed, or stopped - load history and show it (NO continuation)
            loadJobHistory(jobId, function() {
                // Enable inject if job is pending (user can inject to resume)
                if (isPendingApproval || isPendingInput) {
                    agentRunning = false;
                    liveInjectActive = true;
                    var stopBtn = document.getElementById('details-stop-btn');
                    if (stopBtn) stopBtn.style.display = 'inline-block';
                    var injectInput = document.getElementById('live-inject-input');
                    var injectBtn = document.getElementById('live-inject-btn');
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
                }
            });
        }
    })
    .catch(function(err) { console.error('Failed to check job status:', err); });
}

function loadJobHistory(jobId, callback) {
    var agentBox = document.getElementById('agent-live-box');
    var statusText = document.getElementById('agent-status-text');

    // Try to get step history from the job
    fetch('/api/agent/history/' + jobId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.steps && data.steps.length > 0) {
                agentBox.innerHTML = '';
                data.steps.forEach(function(step) {
                    var entry = document.createElement('div');
                    entry.className = 'step-entry';
                    entry.style.borderLeftColor = 'var(--mc-blue)';
                    var toolName = step.tool || 'unknown';
                    var result = step.result || {};
                    var content = result.content || result.summary || '';
                    var error = result.error || '';
                    var html = '<div class="step-tool">' + escapeHtml(toolName) + '</div>';
                    if (error) {
                        html += '<div class="step-result" style="color:var(--danger);">Error: ' + escapeHtml(error) + '</div>';
                    } else if (content) {
                        html += '<div class="step-result">' + escapeHtml(content) + '</div>';
                    }
                    entry.innerHTML = html;
                    agentBox.appendChild(entry);
                });
                if (statusText) { statusText.textContent = 'HISTORY'; statusText.style.color = 'var(--text-muted)'; }
                // Set currentRunningProjectId if available in data
                if (data.project_id) {
                    currentRunningProjectId = data.project_id;
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
                                var entry = document.createElement('div');
                                entry.className = 'step-entry';
                                entry.style.borderLeftColor = 'var(--mc-blue)';
                                var toolName = step.tool || 'unknown';
                                var result = step.result || {};
                                var content = result.content || result.summary || '';
                                var error = result.error || '';
                                var html = '<div class="step-tool">' + escapeHtml(toolName) + '</div>';
                                if (error) {
                                    html += '<div class="step-result" style="color:var(--danger);">Error: ' + escapeHtml(error) + '</div>';
                                } else if (content) {
                                    html += '<div class="step-result">' + escapeHtml(content) + '</div>';
                                }
                                entry.innerHTML = html;
                                agentBox.appendChild(entry);
                            });
                            if (statusText) { statusText.textContent = 'HISTORY'; statusText.style.color = 'var(--text-muted)'; }
                            // Set currentRunningProjectId for inject continuation
                            if (job && job.project_id) {
                                currentRunningProjectId = job.project_id;
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

function connectToJobSSE(jobId) {
    currentRunningJobId = jobId;
    agentRunning = true;
    liveInjectActive = true;
    var agentBox = document.getElementById('agent-live-box');
    if (agentBox) agentBox.innerHTML = '';
    var statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'CONNECTED'; statusText.style.color = 'var(--info)'; }
    var injectInput = document.getElementById('live-inject-input');
    var injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions or questions...'; }
    if (injectBtn) { injectBtn.disabled = false; injectBtn.textContent = 'INJECT'; }
    fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProjectId, instructions: '', continue_from_job: jobId })
    })
    .then(function(response) {
        if (!response.ok) throw new Error('Failed to connect to agent');
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';
        function processChunk() {
            reader.read().then(function(result) {
                var done = result.done;
                var value = result.value;
                if (done || !agentRunning) {
                    agentRunning = false;
                    liveInjectActive = true;
                    return;
                }
                buffer += decoder.decode(value, { stream: true });
                buffer = parseSSEMessage(buffer, function(eventType, data) {
                    if (eventType === 'status') handleAgentStatus(data);
                    else if (eventType === 'step') handleAgentStep(data, agentBox);
                    else if (eventType === 'tool_start') handleToolStart(data, agentBox);
                    else if (eventType === 'pending_approval') handlePendingApproval(data, agentBox);
                    else if (eventType === 'pending_user_input') handlePendingUserInput(data, agentBox);
                });
                setTimeout(processChunk, 0);
            });
        }
        processChunk();
    })
    .catch(function(err) {
        console.error('SSE connection error:', err);
        agentRunning = false;
        liveInjectActive = true;
    });
}

function getActiveJob() {
    var container = document.getElementById('agent-live-container');
    if (!container) return null;
    var jobId = container.dataset.jobId;
    if (jobId) {
        // Look up from the queue to get full job info
        fetch('/api/queue')
            .then(function(r) { return r.json(); })
            .then(function(queueData) {
                if (queueData.running && queueData.running.job_id === jobId) {
                    return queueData.running;
                }
                // Check history
                fetch('/api/history')
                    .then(function(r) { return r.json(); })
                    .then(function(history) {
                        for (var i = 0; i < history.length; i++) {
                            if (history[i].job_id === jobId) return history[i];
                        }
                    });
            });
        return null; // Async — caller should use showLiveViewForJob directly
    }
    return null;
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
            // Add enabled_tools from the tool selector
            var checkboxes = document.querySelectorAll('#add-tool-selector input[type="checkbox"]');
            checkboxes.forEach(function(cb) {
                if (cb.checked) {
                    formData.append('enabled_tools', cb.value);
                }
            });
            var formRef = this;
            fetch('/api/projects', { method: 'POST', body: formData })
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    if (data.error) { alert('Error: ' + data.error); }
                    else { loadProjects(); formRef.reset(); toggleCreateForm(); }
                })
                .catch(function(err) { console.error('Failed to create project:', err); });
        });
    }

    // Load initial data
    loadProjectsCached();
    loadJobs();

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
