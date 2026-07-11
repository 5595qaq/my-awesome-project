const API_BASE = 'http://localhost:8000';

// GCS URIs collected from files uploaded through the browser this session.
let uploadedGcsUris = [];

const uploadBtn = document.getElementById('upload-btn');
const fileInput = document.getElementById('video-files');
const uploadStatusList = document.getElementById('upload-status-list');

uploadBtn.addEventListener('click', async () => {
    const files = Array.from(fileInput.files);
    if (files.length === 0) {
        alert("Please choose at least one video file first.");
        return;
    }

    uploadBtn.disabled = true;
    uploadBtn.innerText = "Uploading...";
    uploadStatusList.innerHTML = "";

    const statusItems = files.map(f => {
        const li = document.createElement('li');
        li.innerText = `> ${f.name}: uploading...`;
        uploadStatusList.appendChild(li);
        return li;
    });

    try {
        const formData = new FormData();
        files.forEach(f => formData.append('files', f));

        const response = await fetch(`${API_BASE}/api/v1/uploads/`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error(`Upload failed: ${response.statusText}`);
        }

        const results = await response.json();
        results.forEach((r, i) => {
            const label = r.status === 'skipped_existing'
                ? 'already exists in GCS, reused existing file'
                : 'uploaded';
            if (statusItems[i]) {
                statusItems[i].innerText = `> ${r.filename}: ${label} (${r.gcs_uri})`;
            }
            if (!uploadedGcsUris.includes(r.gcs_uri)) {
                uploadedGcsUris.push(r.gcs_uri);
            }
        });
    } catch (error) {
        const li = document.createElement('li');
        li.innerText = `> ERROR: ${error.message}`;
        uploadStatusList.appendChild(li);
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.innerText = "Upload to GCS";
    }
});

document.getElementById('evaluation-form').addEventListener('submit', async function(e) {
    e.preventDefault();

    // 1. Gather data
    const examTopic = document.getElementById('exam-topic').value;

    const rawPaths = document.getElementById('video-paths').value;
    const pastedPaths = rawPaths.split(/[\n,]/).map(p => p.trim()).filter(p => p !== '');

    const videoPaths = Array.from(new Set([...uploadedGcsUris, ...pastedPaths]));

    if (videoPaths.length === 0) {
        alert("Please upload at least one video, or paste an existing gs:// path.");
        return;
    }

    const payload = {
        exam_topic: examTopic,
        video_paths: videoPaths
    };

    // 2. Prepare UI
    const submitBtn = document.getElementById('submit-btn');
    submitBtn.disabled = true;
    submitBtn.innerText = "Evaluating...";

    document.getElementById('progress-container').classList.remove('hidden');
    document.getElementById('result-container').classList.add('hidden');

    const logList = document.getElementById('log-list');
    logList.innerHTML = "";
    document.getElementById('progress-fill').style.width = "0%";

    const appendLog = (msg) => {
        const li = document.createElement('li');
        li.innerText = `> ${msg}`;
        logList.appendChild(li);
        logList.scrollTop = logList.scrollHeight;
    };

    // 3. POST request to backend
    try {
        appendLog("Submitting evaluation job to backend...");

        const response = await fetch(`${API_BASE}/api/v1/evaluations/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            throw new Error(`Failed to create job: ${response.statusText}`);
        }

        const data = await response.json();
        const jobId = data.id;
        appendLog(`Job Created [ID: ${jobId}]. Connecting to WebSocket...`);

        connectWebSocket(jobId, appendLog, submitBtn);

    } catch (error) {
        appendLog(`ERROR: ${error.message}`);
        submitBtn.disabled = false;
        submitBtn.innerText = "Start Evaluation";
    }
});


function connectWebSocket(jobId, appendLog, submitBtn) {
    const ws = new WebSocket(`ws://localhost:8000/api/v1/evaluations/${jobId}/ws`);

    const statusText = document.getElementById('job-status');
    const progressBar = document.getElementById('progress-fill');

    ws.onopen = () => {
        appendLog("WebSocket connection established. Waiting for progress...");
    };

    ws.onmessage = (event) => {
        const wsData = JSON.parse(event.data);
        const { event: evtType, payload } = wsData;

        if (evtType === "STAGE_UPDATE") {
            appendLog(`[MODE: ${payload.stage}] ${payload.message}`);
            statusText.innerText = payload.stage;

            if (payload.stage === "FINISHED") {
                progressBar.style.width = "100%";
                progressBar.style.backgroundColor = "#2ecc71"; // Green
                renderResult(payload.result);
                cleanup(ws, submitBtn);
            }
            else if (payload.stage === "FAILED") {
                progressBar.style.backgroundColor = "#e74c3c"; // Red
                statusText.innerText = "FAILED";
                cleanup(ws, submitBtn);
            }
            else if (payload.stage === "LLM_SCORING") {
                progressBar.style.width = "90%";
            }
        }
        else if (evtType === "BRANCH_STATUS_UPDATE" && payload.progress) {
            appendLog(`[${payload.stage}] ${payload.message} (${payload.progress})`);

            // basic logic to advance progress bar based on parsed fraction
            const parts = payload.progress.split("/");
            if(parts.length === 2 && payload.stage === "GEMINI_UPLOAD") {
                const perc = (parseInt(parts[0]) / parseInt(parts[1])) * 40; // upload takes 40%
                progressBar.style.width = `${Math.round(perc)}%`;
            } else if (parts.length === 2 && payload.stage === "GEMINI_PROCESSING") {
                const perc = 40 + ((parseInt(parts[0]) / parseInt(parts[1])) * 40); // process takes next 40%
                progressBar.style.width = `${Math.round(perc)}%`;
            }
        }
    };

    ws.onerror = (err) => {
        appendLog(`WebSocket Error occurred.`);
    };

    ws.onclose = () => {
        appendLog(`WebSocket Closed.`);
        submitBtn.disabled = false;
        submitBtn.innerText = "Start Evaluation";
    };
}

function cleanup(ws, submitBtn) {
    ws.close();
    submitBtn.disabled = false;
    submitBtn.innerText = "Start Evaluation";
}

// The multi-agent output schema isn't unified yet (different agents return
// different fields), so results render generically instead of a fixed table.
function renderResult(result) {
    document.getElementById('progress-container').classList.add('hidden');
    document.getElementById('result-container').classList.remove('hidden');

    document.getElementById('raw-json').innerText = JSON.stringify(result, null, 2);

    const feed = document.getElementById('result-feed');
    feed.innerHTML = "";

    const items = (result && result.items) || [];
    if (items.length === 0) {
        feed.innerHTML = "<p>No results returned.</p>";
        return;
    }

    const groups = new Map();
    items.forEach(item => {
        const agent = item.Agent_Name || "Unknown Agent";
        if (!groups.has(agent)) {
            groups.set(agent, []);
        }
        groups.get(agent).push(item);
    });

    groups.forEach((groupItems, agentName) => {
        const groupEl = document.createElement('div');
        groupEl.className = 'agent-group';

        const heading = document.createElement('h3');
        heading.innerText = `${agentName} (${groupItems.length} item${groupItems.length > 1 ? 's' : ''})`;
        groupEl.appendChild(heading);

        groupItems.forEach(item => groupEl.appendChild(renderResultCard(item)));

        feed.appendChild(groupEl);
    });
}

function renderResultCard(item) {
    const card = document.createElement('div');
    const verdict = getVerdict(item);
    card.className = verdict ? `result-card ${verdict}` : 'result-card';

    const table = document.createElement('table');
    const tbody = document.createElement('tbody');

    Object.entries(item).forEach(([key, value]) => {
        const tr = document.createElement('tr');

        const tdKey = document.createElement('td');
        tdKey.className = 'field-name';
        tdKey.innerText = key;

        const tdValue = document.createElement('td');
        tdValue.innerText = (value !== null && typeof value === 'object')
            ? JSON.stringify(value)
            : value;

        tr.appendChild(tdKey);
        tr.appendChild(tdValue);
        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    card.appendChild(table);
    return card;
}

// Different agent schemas encode pass/fail differently - check the fields
// that show up in the example outputs (status, passed, score) generically.
function getVerdict(item) {
    if (typeof item.status === 'string') {
        const status = item.status.toLowerCase();
        if (status === 'pass') return 'pass';
        if (status === 'fail') return 'fail';
    }
    if (typeof item.passed === 'boolean') {
        return item.passed ? 'pass' : 'fail';
    }
    if (typeof item.score === 'number') {
        return item.score > 0 ? 'pass' : 'fail';
    }
    return '';
}
