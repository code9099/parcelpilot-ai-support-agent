const chatHistory = document.getElementById('chatHistory');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const profileSelect = document.getElementById('profileSelect');
const traceContent = document.getElementById('traceContent');

const actionModal = document.getElementById('actionModal');
const actionDetails = document.getElementById('actionDetails');
const confirmActionBtn = document.getElementById('confirmActionBtn');
const cancelActionBtn = document.getElementById('cancelActionBtn');

let currentPendingAction = null;

function appendMessage(text, role) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    msgDiv.textContent = text;
    chatHistory.appendChild(msgDiv);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function renderTrace(trace, responseData) {
    if (!trace) return;
    
    let html = '';
    
    // Status Badge
    const status = trace.decision_context?.evidence_status || 'UNKNOWN';
    html += `<div class="trace-block">
        <h4>Evidence Status</h4>
        <span class="badge ${status}">${status}</span>
    </div>`;

    // Tool Calls
    const toolCalls = trace.llm1_output?.tool_calls || [];
    if (toolCalls.length > 0) {
        html += `<div class="trace-block">
            <h4>Executed Tools</h4>
            <ul>`;
        toolCalls.forEach(tc => {
            html += `<li><strong>${tc.name}</strong>: <code>${JSON.stringify(tc.arguments)}</code></li>`;
        });
        html += `</ul></div>`;
    }

    // Evidence Gaps
    const gaps = trace.decision_context?.evidence_gaps || [];
    if (gaps.length > 0) {
        html += `<div class="trace-block">
            <h4>Evidence Gaps</h4>
            <ul class="gaps-list">`;
        gaps.forEach(g => {
            html += `<li>${g.missing_fact} (Impact: ${g.impact})</li>`;
        });
        html += `</ul></div>`;
    }

    // Computed Results
    const computed = trace.decision_context?.computed_results || {};
    if (Object.keys(computed).length > 0) {
        html += `<div class="trace-block">
            <h4>Computed Results</h4>
            <pre style="white-space: pre-wrap; font-size: 0.8rem; background: #f1f3f4; padding: 0.5rem; border-radius: 4px;">${JSON.stringify(computed, null, 2)}</pre>
        </div>`;
    }
    
    traceContent.innerHTML = html;
}

async function handleActionConfirmation(action) {
    actionDetails.textContent = `Type: ${action.action_type} | Request ID: ${action.request_id}`;
    currentPendingAction = action;
    actionModal.classList.remove('hidden');
}

confirmActionBtn.addEventListener('click', async () => {
    if (!currentPendingAction) return;
    actionModal.classList.add('hidden');
    
    const profileId = profileSelect.value;
    try {
        const res = await fetch('/api/action/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile_id: profileId,
                request_id: currentPendingAction.request_id
            })
        });
        const data = await res.json();
        
        if (res.ok && data.status === 'executed') {
            appendMessage(`System: Action executed successfully.`, 'system');
        } else {
            appendMessage(`System: Action failed - ${data.error || data.status}`, 'system');
        }
    } catch (e) {
        appendMessage(`System Error: ${e.message}`, 'system');
    }
    currentPendingAction = null;
});

cancelActionBtn.addEventListener('click', () => {
    actionModal.classList.add('hidden');
    currentPendingAction = null;
    appendMessage(`System: Action confirmation cancelled by user.`, 'system');
});

sendBtn.addEventListener('click', async () => {
    const text = userInput.value.trim();
    if (!text) return;
    
    const profileId = profileSelect.value;
    
    appendMessage(text, 'user');
    userInput.value = '';
    
    traceContent.innerHTML = '<p class="placeholder">Processing...</p>';
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile_id: profileId,
                user_text: text,
                context_links: [] // Demo starts empty
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            appendMessage(`Error: ${data.detail || 'API request failed'}`, 'system');
            traceContent.innerHTML = '<p class="placeholder">Error occurred.</p>';
            return;
        }
        
        // Handle Answer
        if (data.text) {
            appendMessage(data.text, 'ai');
        } else if (data.system_error) {
            appendMessage(`System Error: ${data.system_error.code}`, 'system');
        }
        
        // Handle Action
        if (data.computed_results?.prepared_action) {
            const action = data.computed_results.prepared_action;
            appendMessage(`System: Action [${action.action_type}] is ready for confirmation.`, 'system');
            // Show modal
            handleActionConfirmation(action);
        }
        
        // Render Trace
        renderTrace(data._trace, data);
        
    } catch (err) {
        appendMessage(`Network Error: ${err.message}`, 'system');
        traceContent.innerHTML = '<p class="placeholder">Failed to reach server.</p>';
    }
});

userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendBtn.click();
});
