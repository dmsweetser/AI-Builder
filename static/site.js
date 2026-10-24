// === Fling Game State ===
let flingCount = 0;
let logoX = 40, logoY = 40;
let velX = 0, velY = 0;
let isDragging = false;
let dragStartX = 0, dragStartY = 0;
let dragLogoStartX = 0, dragLogoStartY = 0;
let flingAnimFrame = null;
let wasInGoalZone = false;  // Track if logo was previously inside the goal zone
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
        // Check goal zone — delegate to checkWinCondition for accurate containment logic
        checkWinCondition();
        const flingCounter = document.getElementById('fling-counter');
        if (flingCounter) flingCounter.textContent = 'FLINGS: ' + flingCount;
        // Stop animation when velocity is tiny
        if (Math.abs(velX) < MIN_VEL && Math.abs(velY) < MIN_VEL) {
            flingAnimFrame = null;
            return;
        }
        flingAnimFrame = requestAnimationFrame(animate);
    }
    flingAnimFrame = requestAnimationFrame(animate);
}

function isInGoalZone() {
    const logoEl = document.getElementById('draggable-logo');
    if (!logoEl) return false;
    const logoW = logoEl.offsetWidth;
    const logoH = logoEl.offsetHeight;
    return (logoX >= GOAL_ZONE.x && logoX + logoW <= GOAL_ZONE.x + GOAL_ZONE.w &&
        logoY >= GOAL_ZONE.y && logoY + logoH <= GOAL_ZONE.y + GOAL_ZONE.h);
}

function checkWinCondition() {
    const goalZone = document.getElementById('goal-zone');
    const logoEl = document.getElementById('draggable-logo');
    if (!logoEl) return;

    const inZone = isInGoalZone();

    // A valid fling = the logo was previously in the goal zone and is now leaving it
    if (wasInGoalZone && !inZone) {
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
        logoX = window.innerWidth - logoEl.offsetWidth - 20;
        logoY = window.innerHeight - logoEl.offsetHeight - 20;
        velX = 0;
        velY = 0;
        if (goalZone) goalZone.style.display = 'none';
        wasInGoalZone = false;
        // Update logo position immediately
        logoEl.style.left = logoX + 'px';
        logoEl.style.top = logoY + 'px';
    } else if (inZone && !wasInGoalZone) {
        // Logo just entered the goal zone — count it immediately as a successful fling
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
        logoX = window.innerWidth - logoEl.offsetWidth - 20;
        logoY = window.innerHeight - logoEl.offsetHeight - 20;
        velX = 0;
        velY = 0;
        if (goalZone) goalZone.style.display = 'none';
        wasInGoalZone = false;
        logoEl.style.left = logoX + 'px';
        logoEl.style.top = logoY + 'px';
    }

    wasInGoalZone = inZone;
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
            // Show fling counter when game is engaged
            const flingCounter = document.getElementById('fling-counter');
            if (flingCounter) flingCounter.style.display = 'block';
            // Show goal zone on first interaction
            const goalZone = document.getElementById('goal-zone');
            if (goalZone) goalZone.style.display = 'block';
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
let autoSaveTimeout = null;
let pendingRootPathChange = null;
let pendingRootPathElementId = null;
let showArchived = false;

// === Live Agent State (scoped per project) ===
let currentRunningJobId = null;
let agentSSEController = null;
let agentRunning = false;
let liveInjectActive = false;
let currentRunningProjectId = null; // Track which project the agent belongs to

const AVAILABLE_TOOLS = [
    "list_directory", "search_files", "grep_code", "read_file",
    "write_file", "edit_file", "delete_file", "find_symbol",
    "decompile_jar", "list_dependencies", "check_syntax", "get_file_info", "create_tool", "compress_context"
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
    if (tabName === 'tools') loadPendingTools();
    if (tabName === 'app-log') loadAppLog();
}

// === Utility ===
function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Copy text to clipboard (as plain text, not HTML)
function copyToClipboard(text, buttonEl) {
    if (!text) return;
    // Use the Clipboard API if available
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            if (buttonEl) {
                const original = buttonEl.textContent;
                buttonEl.textContent = 'COPIED!';
                setTimeout(() => { buttonEl.textContent = original; }, 1500);
            }
        }).catch(err => console.error('Copy failed:', err));
    } else {
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            if (buttonEl) {
                const original = buttonEl.textContent;
                buttonEl.textContent = 'COPIED!';
                setTimeout(() => { buttonEl.textContent = original; }, 1500);
            }
        } catch (e) {
            console.error('Copy failed:', e);
        }
        document.body.removeChild(textarea);
    }
}

// Get plain text from a chat message element
function getChatMessageText(msgElement) {
    const body = msgElement.querySelector('.chat-msg-body');
    if (!body) return '';
    // Return textContent for plain text (not HTML)
    return body.textContent || '';
}

// Get plain text from agent live box
function getAgentLiveText() {
    const box = document.getElementById('agent-live-box');
    if (!box) return '';
    // Collect all step results in order (they're prepended, so reverse)
    const entries = Array.from(box.querySelectorAll('.step-entry'));
    return entries.reverse().map(e => {
        const tool = e.querySelector('.step-tool');
        const result = e.querySelector('.step-result');
        let text = '';
        if (tool) text += tool.textContent + '\n';
        if (result) text += result.textContent;
        return text;
    }).join('\n\n');
}

// Simple markdown-to-HTML converter (handles code blocks, inline code, bold, italic, lists)
function markdownToHtml(md) {
    if (!md) return '';
    let html = escapeHtml(md);

    // Code blocks (``` ... ```) — extract them first so newlines inside are protected
    const codeBlocks = [];
    html = html.replace(/```([\s\S]*?)```/g, function(match, code) {
        const uniqueId = 'code-block-' + Math.random().toString(36).substr(2, 9);
        // Store the raw (already-escaped) code with newlines intact
        codeBlocks.push({ id: uniqueId, content: code.trim() });
        return `%%CODEBLOCK_${uniqueId}%%`;
    });

    // Inline code (` ... `) - handle single backticks but not triple
    html = html.replace(/`([^`]+)`/g, '<code style="background:#111;padding:1px 4px;border-radius:3px;font-size:9px;">$1</code>');

    // Bold (**text**)
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Italic (*text*) - but not inside words
    html = html.replace(/(?<!\w)\*(.+?)\*(?!\w)/g, '<em>$1</em>');

    // Unordered lists (- item)
    html = html.replace(/^- (.+)$/gm, '<div style="margin-left:12px;">• $1</div>');

    // Line breaks (double newline = paragraph break)
    html = html.replace(/\n\n/g, '<br><br>');
    html = html.replace(/\n/g, '<br>');

    // Restore code blocks with preserved newlines (rendered inside <pre>)
    codeBlocks.forEach(function(block) {
        // Use literal newlines — <pre> preserves them; copy via textContent gets real newlines
        const escaped = block.content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        html = html.replace(`%%CODEBLOCK_${block.id}%%`,
            `<div style="position:relative;margin:4px 0;"><button class="pre-copy-btn" onclick="copyCodeBlock('${block.id}', this)" style="position:absolute;top:4px;right:4px;background:var(--wood);border:1px solid #000;padding:3px 8px;cursor:pointer;font-size:8px;color:#fff;z-index:10;border-radius:3px;font-family:'Press Start 2P',monospace;">COPY</button><pre style="background:#111;padding:8px;border-radius:4px;overflow-x:auto;margin:0;"><code id="${block.id}" style="white-space:pre-wrap;">${escaped}</code></pre></div>`);
    });

    return html;
}

// Copy a code block by its ID
function copyCodeBlock(id, btn) {
    const el = document.getElementById(id);
    if (!el) return;
    // Use textContent — <pre> + <code> preserves newlines; <br> → newline in textContent
    const text = el.textContent || el.innerText || '';
    copyToClipboard(text, btn);
}

// === Tool selector ===
function buildToolSelector(enabledTools) {
    const container = document.getElementById('details-tool-selector');
    if (!container) return;
    container.innerHTML = '';

    // Fetch approved custom tools and add them to the selector
    fetch('/api/tools/approved')
        .then(r => r.json())
        .then(approvedTools => {
            const allTools = [...AVAILABLE_TOOLS, ...approvedTools.map(t => t.name)];
            allTools.forEach(tool => {
                const checked = enabledTools.includes(tool) || enabledTools.length === 0;
                const label = document.createElement('label');
                label.className = 'tool-checkbox';
                const isCustom = approvedTools.some(t => t.name === tool);
                const badge = isCustom ? ' <span style="color:#ffaa00;font-size:8px;">[CUSTOM]</span>' : '';
                // Use enabled_tools as name so FormData collects checked values
                label.innerHTML = `<input type="checkbox" name="enabled_tools" value="${tool}" ${checked ? 'checked' : ''}> ${tool}${badge}`;
                container.appendChild(label);
            });
        })
        .catch(() => {
            // If approved tools fetch fails, just show built-in tools
            AVAILABLE_TOOLS.forEach(tool => {
                const checked = enabledTools.includes(tool) || enabledTools.length === 0;
                const label = document.createElement('label');
                label.className = 'tool-checkbox';
                label.innerHTML = `<input type="checkbox" name="enabled_tools" value="${tool}" ${checked ? 'checked' : ''}> ${tool}`;
                container.appendChild(label);
            });
        });
}

function getEnabledTools() {
    const checkboxes = document.querySelectorAll('#details-tool-selector input[type="checkbox"]');
    const enabled = [];
    checkboxes.forEach(cb => {
        if (cb.checked) enabled.push(cb.value);
    });
    return enabled;
}

// === Directory Picker ===
function pickFolder(inputId) {
    // Create a hidden file input that only accepts directories
    let input = document.getElementById('_hidden_dir_picker_' + inputId);
    if (!input) {
        input = document.createElement('input');
        input.type = 'file';
        input.id = '_hidden_dir_picker_' + inputId;
        input.style.display = 'none';
        // @ts-ignore - webkitdirectory is non-standard but widely supported
        input.webkitdirectory = true;
        // @ts-ignore - mozdirectory is Firefox-specific
        input.mozdirectory = true;
        document.body.appendChild(input);
    }
    input.value = ''; // Reset so change fires even on same selection
    input.click();

    input.onchange = function () {
        let path = this.value;

        // Handle the case where value includes a fake path (Chrome sends "C:\fakepath\dir")
        // Extract just the directory name from the fakepath
        if (path.includes('\\')) {
            // Chrome on Windows: "C:\fakepath\selected_dir" or just "selected_dir"
            const parts = path.split('\\');
            path = parts[parts.length - 1];
        } else if (path.includes('/')) {
            // macOS/Linux: value may be full path or just name
            // If it starts with / it's a full path — keep it
            // If not, it's just the directory name — keep as-is
        }

        // Write the selected path back to the associated text input
        const targetInput = document.getElementById(inputId);
        if (targetInput) {
            targetInput.value = path;
            // Trigger save so the project definition stays in sync
            autoSaveProject();
        }

        // Remove the hidden input after use to prevent accumulation
        if (input && input.parentNode) {
            input.parentNode.removeChild(input);
        }
    };
}

// === Live instruction injection ===
function injectLiveInstruction() {
    if (!liveInjectActive) return;
    const input = document.getElementById('live-inject-input');
    if (!input || !input.value.trim()) return;
    const instruction = input.value.trim();

    if (agentRunning && currentRunningJobId) {
        // During an active run: inject into the running engine
        fetch('/api/agent/inject', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: currentRunningJobId, instruction: instruction })
        }).then(() => {
            input.value = '';
            // Show a brief "sent" indicator
            const statusText = document.getElementById('agent-status-text');
            if (statusText) {
                const orig = statusText.textContent;
                statusText.textContent = '📨 Instruction sent';
                setTimeout(() => { statusText.textContent = orig; }, 1500);
            }
        }).catch(err => console.error('Failed to inject instruction:', err));
    } else if (currentRunningProjectId) {
        // After completion: start a new run with the instruction to continue
        continueAgentRunWithInstruction(currentRunningProjectId, currentRunningJobId, instruction);
    }
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
                            if (s.tool === 'llm_call') {
                                const msgCount = s.params?.messages || 0;
                                return `<div class="job-step-item">
                                    <span class="step-num">Step ${s.step}</span>
                                    <span class="step-tool-name">[🧠 Thinking]</span>
                                    <span class="step-status-ok">✓</span>
                                    <span style="color:#888;">LLM processing (${msgCount} msgs)</span>
                                </div>`;
                            }
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
            set('set-max-context-tokens', settings.max_context_tokens ?? '0');
            set('set-max-output-tokens', settings.max_output_tokens ?? '0');
            set('set-max-tool-result-length', settings.max_tool_result_length ?? '2000');
            set('set-root-dir', settings.root_directory || '');
            set('set-jd-cli', settings.jd_cli_path || '');
            set('set-java-home', settings.java_home || '');
            set('set-dotnet-cli', settings.dotnet_cli_path || '');
        })
        .catch(err => console.error('Failed to load settings:', err));
}

function reloadSettingsFromDisk() {
    fetch('/api/settings/reload', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'reloaded') {
                loadSettingsUI();
                alert('Settings reloaded from disk!');
            } else {
                alert('Failed to reload settings: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => {
            console.error('Failed to reload settings:', err);
            alert('Failed to reload settings.');
        });
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
        max_context_tokens: document.getElementById('set-max-context-tokens').value,
        max_output_tokens: document.getElementById('set-max-output-tokens').value,
        max_tool_result_length: document.getElementById('set-max-tool-result-length').value,
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
            if (s.tool === 'llm_call') {
                const msgCount = s.params?.messages || 0;
                return `<div class="job-step-item">
                                    <span class="step-num">Step ${s.step}</span>
                                    <span class="step-tool-name">[🧠 Thinking]</span>
                                    <span class="step-status-ok">✓</span>
                                    <span style="color:#888;">LLM processing (${msgCount} msgs)</span>
                                </div>`;
            }
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

// === App Log ===
function loadAppLog() {
    fetch('/api/app-log')
        .then(r => r.json())
        .then(data => {
            const list = document.getElementById('app-log-list');
            if (!list) return;
            const entries = data.log || [];
            if (!entries.length) {
                list.innerHTML = '<div class="note">NO LOG ENTRIES YET.</div>';
                return;
            }
            list.innerHTML = entries.map(e => {
                const ts = e.ts ? new Date(e.ts).toLocaleString() : 'unknown';
                return `<div style="padding:3px 0;border-bottom:1px solid #333;font-size:9px;font-family:'Courier New',monospace;"><span style="color:var(--sky);">${ts}</span> <span style="color:#aaa;">${escapeHtml(e.msg)}</span></div>`;
            }).join('');
            list.scrollTop = list.scrollHeight;
        })
        .catch(err => {
            console.error('Failed to load app log:', err);
            const list = document.getElementById('app-log-list');
            if (list) list.innerHTML = '<div class="note warning">Failed to load app log.</div>';
        });
}

function clearAppLog() {
    // No clear endpoint — just refresh
    loadAppLog();
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
                const archiveBtnText = project.isArchived ? 'UNARCHIVE' : 'ARCHIVE';
                const archiveBtnAction = project.isArchived ? `unarchiveProject('${project.id}')` : `archiveProject('${project.id}')`;
                projectItem.innerHTML = `
                            <div class="project-item-header">
                                <div class="project-item-name-container">
                                    <span class="project-item-name">${escapeHtml(project.name || 'Untitled')}</span>
                                    ${project.run_number > 0 ? `<span style="color:#aaa;font-size:8px;margin-left:6px;">Run #${project.run_number}</span>` : ''}
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
                                        onclick="event.stopPropagation(); resetProject('${project.id}')"
                                        aria-label="Reset ${escapeHtml(project.name || 'project')}">
                                        RESET
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
                _doRunProject(projectId);
            })
            .catch(err => { console.error('Failed to fetch project:', err); alert('Failed to load project details'); });
        return;
    }
    _doRunProject(projectId);
}

function _doRunProject(projectId) {
    const project = getProjectById(projectId);
    if (!project) return;

    // Validate
    const rootDir = document.getElementById('details-root-dir')?.value;
    if (!rootDir) {
        alert('Please set a root directory first.');
        return;
    }

    // Use the new project run endpoint which uses persistent output dir
    fetch(`/api/projects/${projectId}/run`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                alert('Failed to queue project: ' + data.error);
                return;
            }
            // Show running state
            updateRunButtonState(projectId, 'running');
            loadJobs();
            // Switch to agent view
            const configSection = document.getElementById('project-config-section');
            const agentLive = document.getElementById('agent-live-container');
            if (configSection) configSection.style.display = 'none';
            if (agentLive) agentLive.style.display = 'block';
            const statusText = document.getElementById('agent-status-text');
            if (statusText) { statusText.textContent = '⏳ QUEUED'; statusText.style.color = 'var(--sky)'; }
            const agentBox = document.getElementById('agent-live-box');
            if (agentBox) agentBox.innerHTML = '';
            // Now start the SSE stream for this job
            startAgentSSE(projectId, getEnabledTools());
        })
        .catch(err => { console.error('Failed to queue project:', err); alert('Failed to queue project.'); });
}

// === Agent Runner ===
function runAgenticProject(projectId) {
    const project = getProjectById(projectId);
    if (!project) return;

    // Validate
    const rootDir = document.getElementById('details-root-dir')?.value;
    if (!rootDir) {
        alert('Please set a root directory first.');
        return;
    }

    // Abort any existing SSE connection
    if (agentSSEController) agentSSEController.abort();
    agentSSEController = new AbortController();
    agentRunning = true;
    liveInjectActive = true;
    currentRunningProjectId = projectId;
    currentRunningJobId = null; // Will be set on 'start' event

    const runBtn = document.getElementById('details-run-btn');
    const stopBtn = document.getElementById('details-stop-btn');
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = '⏳ RUNNING…'; }
    if (stopBtn) stopBtn.style.display = 'inline-block';

    // Show agent live container, hide config
    const configSection = document.getElementById('project-config-section');
    const agentLive = document.getElementById('agent-live-container');
    if (configSection) configSection.style.display = 'none';
    if (agentLive) agentLive.style.display = 'block';

    // Clear and prepare agent box
    const agentBox = document.getElementById('agent-live-box');
    if (agentBox) agentBox.innerHTML = '';
    const statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = '⏳ RUNNING'; statusText.style.color = 'var(--sky)'; }
    const stepCount = document.getElementById('agent-step-count');
    if (stepCount) stepCount.textContent = '';
    const postRun = document.getElementById('post-run-actions');
    if (postRun) postRun.style.display = 'none';

    // Enable interjection
    const injectInput = document.getElementById('live-inject-input');
    const injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions or questions…'; }
    if (injectBtn) injectBtn.disabled = false;

    const enabledTools = getEnabledTools();
    startAgentSSE(projectId, enabledTools);
}

// === Shared SSE Parser ===
function parseSSEMessage(buffer, onEvent) {
    // Process complete SSE messages (delimited by \n\n)
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
                onEvent(eventType, data);
            } catch (e) { console.warn('Failed to parse SSE data:', e); }
        }
    }
    // Fallback: single-line SSE messages (delimited by \n)
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
                        onEvent(eventType, data);
                    } catch (e) { /* ignore */ }
                }
            }
        }
    }
    return buffer;
}

// === Agent SSE Streaming ===
function startAgentSSE(projectId, enabledTools) {
    if (agentSSEController) agentSSEController.abort();
    agentSSEController = new AbortController();
    const agentBox = document.getElementById('agent-live-box');
    if (agentBox) agentBox.innerHTML = '';
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
                    buffer = parseSSEMessage(buffer, (eventType, data) => {
                        if (eventType === 'status') handleAgentStatus(data);
                        else if (eventType === 'step') handleAgentStep(data, agentBox);
                        else if (eventType === 'pending_approval') handlePendingApproval(data, agentBox);
                        else if (eventType === 'pending_user_input') handlePendingUserInput(data, agentBox);
                    });
                    // Use setTimeout to avoid stack overflow from deep recursion
                    setTimeout(processChunk, 0);
                });
            }
            processChunk();
        })
        .catch(err => {
            if (err.name === 'AbortError') {
                console.log('Agent run stopped');
            } else {
                console.error('Agent run error:', err);
                const errEntry = document.createElement('div');
                errEntry.className = 'step-entry error';
                errEntry.textContent = `ERROR: ${err.message}`;
                if (agentBox.firstChild) {
                    agentBox.insertBefore(errEntry, agentBox.firstChild);
                } else {
                    agentBox.appendChild(errEntry);
                }
                agentBox.scrollTop = 0;
            }
            agentRunning = false;
            liveInjectActive = false;
            resetRunButtons();
        });
}


function handleAgentStatus(data) {
    if (data.type === 'start') {
        currentRunningJobId = data.job_id;
        const stepCount = document.getElementById('agent-step-count');
        if (stepCount) stepCount.textContent = '';
    } else if (data.type === 'complete') {
        loadJobs();
        agentRunning = false;
        liveInjectActive = true;
        const statusText = document.getElementById('agent-status-text');
        if (statusText) { statusText.textContent = '✅ COMPLETED'; statusText.style.color = 'var(--grass)'; }
        const postRun = document.getElementById('post-run-actions');
        if (postRun) postRun.style.display = 'block';
        const injectInput = document.getElementById('live-inject-input');
        const injectBtn = document.getElementById('live-inject-btn');
        if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Continue with new instructions…'; }
        if (injectBtn) injectBtn.disabled = false;
        const runBtn = document.getElementById('details-run-btn');
        if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = 'RUN'; }
    } else if (data.type === 'error') {
        loadJobs();
        agentRunning = false;
        liveInjectActive = true;
        const statusText = document.getElementById('agent-status-text');
        if (statusText) { statusText.textContent = '❌ ERROR'; statusText.style.color = '#f55'; }
        const postRun = document.getElementById('post-run-actions');
        if (postRun) postRun.style.display = 'block';
        const injectInput = document.getElementById('live-inject-input');
        const injectBtn = document.getElementById('live-inject-btn');
        if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Fix the error and try again…'; }
        if (injectBtn) injectBtn.disabled = false;
        const runBtn = document.getElementById('details-run-btn');
        if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = 'RESUBMIT'; }
    } else if (data.type === 'max_steps_reached') {
        agentRunning = false;
        liveInjectActive = true;
        const statusText = document.getElementById('agent-status-text');
        if (statusText) { statusText.textContent = '⏹ MAX STEPS'; statusText.style.color = '#ffaa00'; }
        const postRun = document.getElementById('post-run-actions');
        if (postRun) postRun.style.display = 'block';
        const injectInput = document.getElementById('live-inject-input');
        const injectBtn = document.getElementById('live-inject-btn');
        if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Continue with new instructions…'; }
        if (injectBtn) injectBtn.disabled = false;
        const runBtn = document.getElementById('details-run-btn');
        if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = 'RUN'; }
    }
}


function handleAgentStep(data, agentBox) {
    if (!agentBox) return;

    // Update step count
    const stepCount = document.getElementById('agent-step-count');
    if (stepCount) stepCount.textContent = `Step ${data.step}`;

    const entry = document.createElement('div');
    entry.className = 'step-entry';

    if (data.tool === 'llm_call') {
        // LLM call - show as thinking/reasoning step
        const msgCount = data.params?.messages || 0;
        entry.classList.add('llm-step');
        entry.innerHTML = `
            <div class="step-tool">🧠 Step ${data.step}: Thinking (${msgCount} messages)</div>
            <div class="step-result" style="color:#888;font-size:9px;">Processing request…</div>
        `;
    } else if (data.tool === 'format_retry') {
        // Format reminder
        entry.classList.add('llm-step');
        entry.innerHTML = `
            <div class="step-tool" style="color:#ffaa00;">⚠ Step ${data.step}: Format reminder sent</div>
            <div class="step-result" style="color:#ffaa00;font-size:9px;">${escapeHtml(data.result?.content || '')}</div>
        `;
    } else {
        // Tool call
        const ok = data.result && data.result.success !== false;
        const resultPreview = data.result ? (data.result.content || '').substring(0, 500) : 'no result';
        entry.classList.add(ok ? 'success' : 'error');
        entry.innerHTML = `
            <div class="step-tool">${ok ? '✓' : '✗'} Step ${data.step}: ${data.tool}</div>
            ${data.params && Object.keys(data.params).length ? `<div style="color:#aaa;font-size:9px;">${escapeHtml(JSON.stringify(data.params))}</div>` : ''}
            <div class="step-result">${escapeHtml(resultPreview)}</div>
        `;
    }
    // Append so newest appears at the bottom (natural reading order)
    agentBox.appendChild(entry);
    // Auto-scroll to bottom
    agentBox.scrollTop = agentBox.scrollHeight;
}

// === Pending Tool Approval ===
function handlePendingApproval(data, agentBox) {
    if (!agentBox) return;
    const entry = document.createElement('div');
    entry.classList.add('step-entry', 'pending-approval');
    entry.innerHTML = `
        <div class="step-tool" style="color:#ffaa00;">⚠ PENDING TOOL APPROVAL</div>
        <div class="step-result" style="color:#ffaa00;font-size:9px;">Tool "${escapeHtml(data.tool_name)}" proposed — review in TOOLS tab.</div>
    `;
    agentBox.appendChild(entry);
    agentBox.scrollTop = agentBox.scrollHeight;
}

// === Pending User Input (only after 3 consecutive format failures) ===
function handlePendingUserInput(data, agentBox) {
    if (!agentBox) return;
    agentRunning = false;
    liveInjectActive = true;

    const entry = document.createElement('div');
    entry.classList.add('step-entry', 'pending-approval');
    entry.innerHTML = `
        <div class="step-tool" style="color:#ffaa00;">⏸ AGENT NEEDS HELP</div>
        <div class="step-result" style="color:#ffaa00;font-size:10px;white-space:pre-wrap;">${escapeHtml(data.response || 'The agent is waiting for your input.')}</div>
    `;
    agentBox.appendChild(entry);
    agentBox.scrollTop = agentBox.scrollHeight;

    // Enable the interjection area
    const injectInput = document.getElementById('live-inject-input');
    const injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type a nudge or new instructions…'; }
    if (injectBtn) injectBtn.disabled = false;

    const statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = '⏸ AWAITING INPUT'; statusText.style.color = '#ffaa00'; }
    const runBtn = document.getElementById('details-run-btn');
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = '⏸ AWAITING INPUT…'; }
}

function submitPendingInput() {
    const input = document.getElementById('pending-input-' + currentRunningJobId);
    if (!input || !input.value.trim()) return;
    const userResponse = input.value.trim();

    // Disable the submit button
    input.disabled = true;
    const resumeBtn = input.nextElementSibling;
    if (resumeBtn) resumeBtn.disabled = true;

    fetch('/api/agent/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: currentRunningJobId, input: userResponse })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'resume_input_saved') {
            // The engine will pick up the input and continue
            // Show a "resumed" indicator
            const statusDiv = document.createElement('div');
            statusDiv.style.cssText = 'color:#5C8A3B;font-size:9px;margin-top:4px;';
            statusDiv.textContent = '▶ Resumed — waiting for agent...';
            input.parentElement.appendChild(statusDiv);
        }
    })
    .catch(err => {
        console.error('Failed to submit pending input:', err);
        input.disabled = false;
        if (resumeBtn) resumeBtn.disabled = false;
    });
}

function stopProject(projectId) {
    agentRunning = false;
    liveInjectActive = false;
    if (agentSSEController) {
        agentSSEController.abort();
        agentSSEController = null;
    }
    fetch('/api/queue/running/stop', { method: 'POST' })
        .then(() => {
            updateRunButtonState(projectId, false);
            loadJobs();
            resetRunButtons();
        })
        .catch(err => console.error('Failed to stop project:', err));
}

function continueAgentRun(jobId) {
    // User clicked "CONTINUE AGENT" button without typing a new instruction.
    // Use the current instructions from the project or a generic prompt.
    const projectId = currentProjectId;
    if (!projectId) return;
    const instructions = document.getElementById('details-instructions')?.value || '';
    continueAgentRunWithInstruction(projectId, jobId, instructions || 'Please continue working on the project.');
}

function continueAgentRunWithInstruction(projectId, prevJobId, newInstruction) {
    if (!projectId || !prevJobId) return;

    // Abort any existing SSE connection
    if (agentSSEController) agentSSEController.abort();
    agentSSEController = new AbortController();
    agentRunning = true;
    liveInjectActive = true;
    currentRunningProjectId = projectId;
    currentRunningJobId = null;

    // Get enabled tools from the project
    const enabledTools = getEnabledTools();

    // Update UI to show running state
    const runBtn = document.getElementById('details-run-btn');
    const stopBtn = document.getElementById('details-stop-btn');
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = '⏳ RUNNING…'; }
    if (stopBtn) stopBtn.style.display = 'inline-block';

    // Show agent live container, hide config
    const configSection = document.getElementById('project-config-section');
    const agentLive = document.getElementById('agent-live-container');
    if (configSection) configSection.style.display = 'none';
    if (agentLive) agentLive.style.display = 'block';

    // Clear and prepare agent box
    const agentBox = document.getElementById('agent-live-box');
    if (agentBox) agentBox.innerHTML = '';
    const statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = '⏳ CONTINUING…'; statusText.style.color = 'var(--sky)'; }
    const stepCount = document.getElementById('agent-step-count');
    if (stepCount) stepCount.textContent = '';
    const postRun = document.getElementById('post-run-actions');
    if (postRun) postRun.style.display = 'none';

    // Enable interjection
    const injectInput = document.getElementById('live-inject-input');
    const injectBtn = document.getElementById('live-inject-btn');
    if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Type instructions or questions…'; }
    if (injectBtn) injectBtn.disabled = false;

    // POST to /api/agent/run with continue_from_job
    fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            project_id: projectId,
            instructions: newInstruction,
            continue_from_job: prevJobId,
            enabled_tools: enabledTools,
        }),
        signal: agentSSEController.signal
    })
    .then(response => {
        if (!response.ok) throw new Error('Failed to start continued agent run');
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        function processChunk() {
            reader.read().then(({ done, value }) => {
                if (done || !agentRunning) {
                    agentRunning = false;
                    liveInjectActive = true;
                    const injectInput = document.getElementById('live-inject-input');
                    const injectBtn = document.getElementById('live-inject-btn');
                    if (injectInput) {
                        injectInput.disabled = false;
                        injectInput.placeholder = 'Continue with new instructions…';
                    }
                    if (injectBtn) injectBtn.disabled = false;
                    return;
                }
                buffer += decoder.decode(value, { stream: true });
                buffer = parseSSEMessage(buffer, (eventType, data) => {
                    if (eventType === 'status') handleAgentStatus(data);
                    else if (eventType === 'step') handleAgentStep(data, agentBox);
                    else if (eventType === 'pending_approval') handlePendingApproval(data, agentBox);
                    else if (eventType === 'pending_user_input') handlePendingUserInput(data, agentBox);
                });
                setTimeout(processChunk, 0);
            });
        }
        processChunk();
    })
    .catch(err => {
        if (err.name === 'AbortError') {
            console.log('Agent run stopped');
        } else {
            console.error('Agent run error:', err);
            if (agentBox) {
                const errEntry = document.createElement('div');
                errEntry.className = 'step-entry error';
                errEntry.textContent = `ERROR: ${err.message}`;
                agentBox.appendChild(errEntry);
                agentBox.scrollTop = agentBox.scrollHeight;
            }
        }
        agentRunning = false;
        liveInjectActive = true;
        const injectInput = document.getElementById('live-inject-input');
        const injectBtn = document.getElementById('live-inject-btn');
        if (injectInput) { injectInput.disabled = false; injectInput.placeholder = 'Continue with new instructions…'; }
        if (injectBtn) injectBtn.disabled = false;
    });
}

function resetRunButtons() {
    const runBtn = document.getElementById('details-run-btn');
    const stopBtn = document.getElementById('details-stop-btn');
    if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = 'RUN'; }
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

function resetProject(projectId) {
    if (!confirm(`Reset project "${projectId}"? This will clear all run history and output for this project.`)) return;
    fetch(`/api/projects/${projectId}/reset`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'reset') {
                loadProjects();
                alert('Project reset successfully!');
            } else {
                alert('Failed to reset project: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => {
            console.error('Failed to reset project:', err);
            alert('Failed to reset project.');
        });
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

    // Reset agent UI state when switching projects
    const configSection = document.getElementById('project-config-section');
    const agentLive = document.getElementById('agent-live-container');
    if (configSection) configSection.style.display = 'block';
    if (agentLive) agentLive.style.display = 'none';
    const statusText = document.getElementById('agent-status-text');
    if (statusText) { statusText.textContent = 'AGENT RUNNING'; statusText.style.color = 'var(--sky)'; }
    const stepCount = document.getElementById('agent-step-count');
    if (stepCount) stepCount.textContent = '';
    const postRun = document.getElementById('post-run-actions');
    if (postRun) postRun.style.display = 'none';

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
            if (nameEl) {
                let displayName = escapeHtml(project.name || 'Untitled');
                if (project.run_number > 0) {
                    displayName += ` <span style="font-size:10px;color:#aaa;">(Run #${project.run_number})</span>`;
                }
                nameEl.innerHTML = displayName;
            }
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
    // Stop any running agent
    if (agentRunning) stopProject(currentProjectId);
    agentRunning = false;
    liveInjectActive = false;
    currentRunningJobId = null;
    currentRunningProjectId = null;

    // Restore config view
    const configSection = document.getElementById('project-config-section');
    const agentLive = document.getElementById('agent-live-container');
    if (configSection) configSection.style.display = 'block';
    if (agentLive) agentLive.style.display = 'none';

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

// === Project Form Submit ===
document.getElementById('add-project-form').addEventListener('submit', function (e) {
    e.preventDefault();
    const formData = new FormData(this);
    fetch('/api/projects', { method: 'POST', body: formData })
        .then(res => res.json())
        .then(data => {
            if (data.error) { alert('Error: ' + data.error); }
            else { loadProjects(); this.reset(); }
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
                    div.style.display = 'flex';
                    div.style.flexDirection = 'column';
                    const roleLabel = msg.role === 'user' ? 'YOU' : 'AI';
                    const roleClass = msg.role === 'user' ? '' : ' ai-response';
                    const bodyDiv = document.createElement('div');
                    bodyDiv.className = 'chat-msg-body';
                    bodyDiv.style.width = '100%';
                    bodyDiv.innerHTML = markdownToHtml(msg.content);
                    div.innerHTML = `<strong class="${roleClass}">${roleLabel}:</strong>`;
                    div.appendChild(bodyDiv);
                    // Add copy button to each message (left-aligned)
                    const copyBtn = document.createElement('button');
                    copyBtn.className = 'copy-btn';
                    copyBtn.textContent = 'COPY';
                    copyBtn.style.marginTop = '4px';
                    copyBtn.style.marginBottom = '4px';
                    copyBtn.onclick = (e) => {
                        e.stopPropagation();
                        const text = getChatMessageText(bodyDiv);
                        copyToClipboard(text, copyBtn);
                    };
                    div.appendChild(copyBtn);
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
    sendBtn.disabled = true;
    input.disabled = true;

    // Create user message element
    const userDiv = document.createElement('div');
    userDiv.className = 'chat-msg';
    userDiv.style.display = 'flex';
    userDiv.style.flexDirection = 'column';
    const userBody = document.createElement('div');
    userBody.className = 'chat-msg-body';
    userBody.style.width = '100%';
    userBody.innerHTML = markdownToHtml(content);
    userDiv.innerHTML = '<strong>YOU:</strong>';
    userDiv.appendChild(userBody);
    log.appendChild(userDiv);
    input.value = '';
    log.scrollTop = log.scrollHeight;

    // Create AI response placeholder
    const aiDiv = document.createElement('div');
    aiDiv.className = 'chat-msg';
    aiDiv.style.display = 'flex';
    aiDiv.style.flexDirection = 'column';
    aiDiv.innerHTML = `<strong class="ai-response">AI:</strong>`;
    const aiBodyDiv = document.createElement('div');
    aiBodyDiv.className = 'chat-msg-body';
    aiBodyDiv.style.width = '100%';
    aiBodyDiv.id = 'chat-stream-text-' + Date.now();
    aiDiv.appendChild(aiBodyDiv);
    // Add copy button to AI response
    const aiCopyBtn = document.createElement('button');
    aiCopyBtn.className = 'copy-btn';
    aiCopyBtn.textContent = 'COPY';
    aiCopyBtn.style.marginTop = '4px';
    aiCopyBtn.style.marginBottom = '4px';
    aiCopyBtn.onclick = (e) => {
        e.stopPropagation();
        const text = getChatMessageText(aiBodyDiv);
        copyToClipboard(text, aiCopyBtn);
    };
    aiDiv.appendChild(aiCopyBtn);
    log.appendChild(aiDiv);
    log.scrollTop = log.scrollHeight;

    // Now send to server and stream response
    fetch(`/api/chats/${currentChatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
    })
        .then(response => {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            function read() {
                reader.read().then(({ done, value }) => {
                    if (done) {
                        sendBtn.disabled = false;
                        input.disabled = false;
                        log.scrollTop = log.scrollHeight;
                        loadChats();
                        return;
                    }
                    buffer += decoder.decode(value, { stream: true });
                    // Find the AI response body div by class (last .chat-msg-body in the log)
                    const textEl = log.querySelector('.chat-msg:last-child .chat-msg-body');
                    if (textEl) textEl.innerHTML = markdownToHtml(buffer);
                    log.scrollTop = log.scrollHeight;
                    // Use setTimeout to avoid stack overflow
                    setTimeout(read, 0);
                });
            }
            read();
        })
        .catch(err => {
            console.error('Chat error:', err);
            sendBtn.disabled = false;
            input.disabled = false;
        });
}

// === Pending Tools Management ===
function loadPendingTools() {
    fetch('/api/tools/pending')
        .then(r => r.json())
        .then(tools => {
            renderPendingTools(tools);
            renderApprovedTools();
        })
        .catch(err => {
            console.error('Failed to load pending tools:', err);
            const list = document.getElementById('pending-tools-list');
            if (list) list.innerHTML = '<div class="note warning">Failed to load pending tools.</div>';
        });
}

function renderApprovedTools() {
    const list = document.getElementById('approved-tools-list');
    if (!list) return;

    fetch('/api/tools/approved')
        .then(r => r.json())
        .then(tools => {
            if (!tools || tools.length === 0) {
                list.innerHTML = '<div class="note">NO APPROVED TOOLS YET.</div>';
                return;
            }
            list.innerHTML = tools.map(t => `
                <div style="padding:8px; border:1px solid #444; border-radius:4px; margin-bottom:6px;">
                    <strong style="color:var(--grass);">${escapeHtml(t.name)}</strong>
                    <span style="color:#aaa; font-size:11px; margin-left:8px;">${escapeHtml(t.description)}</span>
                </div>
            `).join('');
        })
        .catch(err => {
            console.error('Failed to load approved tools:', err);
            list.innerHTML = '<div class="note warning">Failed to load approved tools.</div>';
        });
}

function renderPendingTools(pendingTools) {
    const list = document.getElementById('pending-tools-list');
    if (!list) return;
    list.innerHTML = '';

    if (!pendingTools || pendingTools.length === 0) {
        list.innerHTML = '<div class="note">NO PENDING TOOLS. The agent has not proposed any new tools yet.</div>';
    } else {
        pendingTools.forEach(tool => {
            const item = document.createElement('div');
            item.className = 'pending-tool-item';
            item.style.cssText = 'border:1px solid #444; padding:12px; margin-bottom:10px; border-radius:4px;';

            const paramsStr = tool.parameters ? JSON.stringify(tool.parameters, null, 2) : '(none)';

            item.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <strong style="color:var(--grass); font-size:14px;">${escapeHtml(tool.name)}</strong>
                    <span style="color:#aaa; font-size:10px;">Submitted: ${escapeHtml(tool.submitted_at || 'unknown')}</span>
                </div>
                <p style="margin:4px 0; color:#ccc; font-size:12px;">${escapeHtml(tool.description)}</p>
                <details style="margin:8px 0;" open>
                    <summary style="cursor:pointer; color:var(--accent); font-size:11px;">View Parameters & Code</summary>
                    <div style="margin-top:8px;">
                        <div style="margin-bottom:8px;">
                            <strong style="color:#aaa; font-size:11px;">Parameters:</strong>
                            <pre style="background:#111; padding:8px; border-radius:4px; font-size:10px; overflow-x:auto; margin-top:4px;">${escapeHtml(paramsStr)}</pre>
                        </div>
                        <div>
                            <strong style="color:#aaa; font-size:11px;">Implementation Code:</strong>
                            <pre style="background:#111; padding:8px; border-radius:4px; font-size:10px; overflow-x:auto; margin-top:4px; white-space:pre-wrap;">${escapeHtml(tool.code || '(no code)')}</pre>
                        </div>
                    </div>
                </details>
                <div style="display:flex; gap:8px; margin-top:10px;">
                    <button class="btn-sm" onclick="approvePendingTool('${tool.id}', '${escapeHtml(tool.name)}')" style="background:var(--grass);">✓ APPROVE</button>
                    <button class="btn-sm" onclick="rejectPendingTool('${tool.id}', '${escapeHtml(tool.name)}')" style="background:#a03030;">✗ REJECT</button>
                </div>
            `;
            list.appendChild(item);
        });
    }
}

function approvePendingTool(toolId, toolName) {
    if (!confirm(`Approve tool "${toolName}"? It will be immediately available to the agent.`)) return;
    fetch(`/api/tools/pending/${toolId}/approve`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'approved') {
                alert(`Tool "${toolName}" approved and registered!`);
                loadPendingTools();
            } else {
                alert('Failed to approve tool: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => {
            console.error('Failed to approve tool:', err);
            alert('Failed to approve tool.');
        });
}

function rejectPendingTool(toolId, toolName) {
    if (!confirm(`Reject tool "${toolName}"?`)) return;
    fetch(`/api/tools/pending/${toolId}/reject`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'rejected') {
                alert(`Tool "${toolName}" rejected and removed.`);
                loadPendingTools();
            } else {
                alert('Failed to reject tool: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => {
            console.error('Failed to reject tool:', err);
            alert('Failed to reject tool.');
        });
}

// === Init ===
document.addEventListener('DOMContentLoaded', () => {
    loadProjectsCached();
    loadJobs();
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