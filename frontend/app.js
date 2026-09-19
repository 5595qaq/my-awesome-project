const API_BASE = 'http://localhost:8000';
const EXAM_TOPIC = '無菌抽藥技術（Vial 粉劑）';

const STAGE_LABELS = {
    GEMINI_UPLOAD: '確認影片',
    GEMINI_PROCESSING: '影片分析',
    GAZE_PROCESSING: '注視點辨識',
    LLM_SCORING: '彙整評分',
    FINISHED: '評分完成'
};

const FIELD_LABELS = {
    Agent_Name: '評分代理',
    Video_Path: '影片路徑',
    score: '得分',
    passed: '是否通過',
    status: '判定狀態',
    start_time: '開始時間',
    end_time: '結束時間',
    temporal_status: '時間狀態',
    success_reason: '通過理由',
    failure_reason: '未通過理由',
    evidence: '判定證據'
};

// 5 FPS GCS URIs collected from files uploaded through the browser this session.
let uploadedGcsUris = [];
let currentEvaluationJob = null;
let activeWebSocket = null;
let reconnectTimer = null;
let reconnectAttempt = 0;
const ACTIVE_JOB_KEY = 'vlm-active-evaluation-job';

const uploadBtn = document.getElementById('upload-btn');
const fileInput = document.getElementById('video-files');
const uploadStatusList = document.getElementById('upload-status-list');
const retryBtn = document.getElementById('retry-btn');

function appendProgressLog(msg) {
    const logList = document.getElementById('log-list');
    const li = document.createElement('li');
    li.innerText = `> ${msg}`;
    logList.appendChild(li);
    logList.scrollTop = logList.scrollHeight;
}

uploadBtn.addEventListener('click', async () => {
    const files = Array.from(fileInput.files);
    if (files.length === 0) {
        alert("請先選擇至少一部影片。");
        return;
    }

    uploadBtn.disabled = true;
    uploadBtn.innerText = "上傳中…";
    uploadStatusList.innerHTML = "";

    const statusItems = files.map(f => {
        const li = document.createElement('li');
        li.innerText = `> ${f.name}：上傳中…`;
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
            throw new Error(`上傳失敗（${response.status} ${response.statusText}）`);
        }

        const results = await response.json();
        results.forEach((r, i) => {
            const label = r.status === 'skipped_existing'
                ? '雲端已有此檔案，已直接使用'
                : '上傳完成';
            if (statusItems[i]) {
                statusItems[i].innerText = `> ${r.filename}：${label}（${r.gcs_uri}）`;
            }
            if (!uploadedGcsUris.includes(r.gcs_uri)) {
                uploadedGcsUris.push(r.gcs_uri);
            }
        });
    } catch (error) {
        const li = document.createElement('li');
        li.innerText = `> 錯誤：${error.message}`;
        uploadStatusList.appendChild(li);
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.innerText = "上傳影片";
    }
});

document.getElementById('evaluation-form').addEventListener('submit', async function(e) {
    e.preventDefault();

    const rawPaths = document.getElementById('video-paths').value;
    const pastedPaths = rawPaths.split(/[\n,]/).map(p => p.trim()).filter(Boolean);

    const videoPaths = Array.from(new Set([...uploadedGcsUris, ...pastedPaths]));

    if (videoPaths.length === 0) {
        alert("請至少上傳一部影片，或輸入既有的 gs:// 雲端路徑。");
        return;
    }

    const payload = {
        exam_topic: EXAM_TOPIC,
        video_paths: videoPaths
    };

    // 2. Prepare UI
    const submitBtn = document.getElementById('submit-btn');
    submitBtn.disabled = true;
    submitBtn.innerText = "評分中…";

    document.getElementById('progress-container').classList.remove('hidden');
    document.getElementById('result-container').classList.add('hidden');
    setDownloadButtonsEnabled(false);
    currentEvaluationJob = null;

    const logList = document.getElementById('log-list');
    logList.innerHTML = "";
    document.getElementById('progress-fill').style.width = "0%";

    // 3. POST request to backend
    try {
        appendProgressLog("正在建立評分工作…");

        const response = await fetch(`${API_BASE}/api/v1/evaluations/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorBody = await response.json().catch(() => null);
            const detail = errorBody?.detail ? `：${errorBody.detail}` : '';
            throw new Error(`無法建立評分工作（${response.status} ${response.statusText}）${detail}`);
        }

        const data = await response.json();
        const jobId = data.id;
        localStorage.setItem(ACTIVE_JOB_KEY, jobId);
        appendProgressLog(`評分工作已建立（編號：${jobId}），正在連線以取得即時進度…`);

        connectWebSocket(jobId, submitBtn);

    } catch (error) {
        appendProgressLog(`錯誤：${error.message}`);
        submitBtn.disabled = false;
        submitBtn.innerText = "開始評分";
    }
});


function connectWebSocket(jobId, submitBtn) {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    if (activeWebSocket && activeWebSocket.readyState < WebSocket.CLOSING) {
        activeWebSocket._intentionalClose = true;
        activeWebSocket.close();
    }
    const ws = new WebSocket(`ws://localhost:8000/api/v1/evaluations/${jobId}/ws`);
    activeWebSocket = ws;
    const statusText = document.getElementById('job-status');
    const progressBar = document.getElementById('progress-fill');

    ws.onopen = () => {
        reconnectAttempt = 0;
        appendProgressLog("已連線，等待評分進度…");
    };

    ws.onmessage = (event) => {
        const { event: evtType, payload } = JSON.parse(event.data);
        if (evtType !== "BRANCH_STATUS_UPDATE") return;
        const { stage, status, progress, message } = payload;
        const stageLabel = STAGE_LABELS[stage] || stage;
        appendProgressLog(`[${stageLabel}] ${[localizeMessage(message), progress && '（' + progress + '）'].filter(Boolean).join(' ')}`.trim());
        if (stage !== 'GEMINI_UPLOAD' || parseFloat(progressBar.style.width) < 40) {
            statusText.innerText = stageLabel;
        }
        const terminalAction = Recovery.branchNotificationAction(status);
        if (terminalAction === 'retired') {
            showRetiredEvaluation(message, submitBtn, ws);
            return;
        }
        if (terminalAction === 'retry') {
            progressBar.style.backgroundColor = "#e74c3c";
            statusText.innerText = "評分失敗";
            retryBtn.classList.remove('hidden');
            cleanup(ws, submitBtn);
            return;
        }
        if (stage === "FINISHED" && status === "completed") {
            progressBar.style.width = "100%";
            progressBar.style.backgroundColor = "#2ecc71";
            localStorage.removeItem(ACTIVE_JOB_KEY);
            fetchAndRenderResult(jobId, appendProgressLog);
            cleanup(ws, submitBtn);
            return;
        }
        if (progress) {
            const parts = progress.split("/");
            if (parts.length === 2 && parseInt(parts[1]) > 0 && stage === "GEMINI_UPLOAD") {
                const perc = (parseInt(parts[0]) / parseInt(parts[1])) * 40;
                progressBar.style.width = `${Math.max(parseFloat(progressBar.style.width) || 0, Math.round(perc))}%`;
            } else if (parts.length === 2 && parseInt(parts[1]) > 0 && stage === "GEMINI_PROCESSING") {
                const perc = 40 + ((parseInt(parts[0]) / parseInt(parts[1])) * 40);
                progressBar.style.width = `${Math.max(parseFloat(progressBar.style.width) || 0, Math.round(perc))}%`;
            }
        } else if (stage === "LLM_SCORING") {
            progressBar.style.width = "90%";
        }
    };

    ws.onerror = () => appendProgressLog("即時進度連線發生錯誤。");
    ws.onclose = async () => {
        if (activeWebSocket === ws) activeWebSocket = null;
        if (ws._intentionalClose) return;
        appendProgressLog("即時進度連線已關閉，正在確認工作狀態…");
        await recoverConnection(jobId, submitBtn);
    };
}

function cleanup(ws, submitBtn) {
    ws._intentionalClose = true;
    ws.close();
    submitBtn.disabled = false;
    submitBtn.innerText = "開始評分";
}

function showRetiredEvaluation(message, submitBtn, ws = null) {
    localStorage.removeItem(ACTIVE_JOB_KEY);
    document.getElementById('job-status').innerText = '舊格式工作已停用';
    document.getElementById('progress-fill').style.backgroundColor = '#e67e22';
    retryBtn.classList.add('hidden');
    appendProgressLog(message || '此工作使用舊版影片格式，請重新提交。');
    if (ws) {
        cleanup(ws, submitBtn);
    } else {
        submitBtn.disabled = false;
        submitBtn.innerText = '開始評分';
    }
}

async function recoverConnection(jobId, submitBtn) {
    try {
        const response = await fetch(`${API_BASE}/api/v1/evaluations/${jobId}`);
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        const job = await response.json();
        const action = Recovery.recoveryAction(job.status);
        if (action === 'render') {
            localStorage.removeItem(ACTIVE_JOB_KEY);
            await fetchAndRenderResult(jobId, appendProgressLog);
            submitBtn.disabled = false;
            submitBtn.innerText = "開始評分";
            return;
        }
        if (action === 'retry') {
            document.getElementById('job-status').innerText = '評分失敗';
            document.getElementById('progress-fill').style.backgroundColor = '#e74c3c';
            retryBtn.classList.remove('hidden');
            if (job.result?.error) appendProgressLog(`執行失敗：${job.result.error}`);
            submitBtn.disabled = false;
            submitBtn.innerText = "開始評分";
            return;
        }
        if (action === 'retired') {
            showRetiredEvaluation(job.result?.error, submitBtn);
            return;
        }
    } catch (error) {
        appendProgressLog(`暫時無法取得工作狀態：${error.message}`);
    }
    const delay = Recovery.reconnectDelay(reconnectAttempt++);
    appendProgressLog(`${Math.round(delay / 1000)} 秒後重新連線…`);
    reconnectTimer = setTimeout(() => connectWebSocket(jobId, submitBtn), delay);
}

retryBtn.addEventListener('click', async () => {
    const jobId = localStorage.getItem(ACTIVE_JOB_KEY);
    if (!jobId) return;
    retryBtn.disabled = true;
    try {
        const response = await fetch(`${API_BASE}/api/v1/evaluations/${jobId}/retry`, { method: 'POST' });
        if (!response.ok) {
            const detail = await response.json().catch(() => ({}));
            throw new Error(detail.detail || `${response.status} ${response.statusText}`);
        }
        retryBtn.classList.add('hidden');
        document.getElementById('progress-fill').style.backgroundColor = '#2ecc71';
        document.getElementById('job-status').innerText = '影片分析';
        appendProgressLog('已保留完成進度，正在續跑未完成項目…');
        const submitBtn = document.getElementById('submit-btn');
        submitBtn.disabled = true;
        submitBtn.innerText = '評分中…';
        connectWebSocket(jobId, submitBtn);
    } catch (error) {
        appendProgressLog(`無法續跑：${error.message}`);
    } finally {
        retryBtn.disabled = false;
    }
});

async function restoreActiveEvaluation() {
    const jobId = localStorage.getItem(ACTIVE_JOB_KEY);
    if (!jobId) return;
    const submitBtn = document.getElementById('submit-btn');
    document.getElementById('progress-container').classList.remove('hidden');
    submitBtn.disabled = true;
    submitBtn.innerText = '評分中…';
    appendProgressLog(`正在恢復工作（編號：${jobId}）…`);
    await recoverConnection(jobId, submitBtn);
}

restoreActiveEvaluation();

async function fetchAndRenderResult(jobId, appendLog) {
    try {
        const response = await fetch(`${API_BASE}/api/v1/evaluations/${jobId}`);
        if (!response.ok) {
            throw new Error(`無法取得評分結果（${response.status} ${response.statusText}）`);
        }
        const job = await response.json();
        currentEvaluationJob = job;
        renderResult(job.result);
        setDownloadButtonsEnabled(Array.isArray(job.result?.items) && job.result.items.length > 0);
    } catch (error) {
        appendLog(`錯誤：${error.message}`);
    }
}

const summaryDownloadBtn = document.getElementById('download-summary-btn');
const detailDownloadBtn = document.getElementById('download-detail-btn');

summaryDownloadBtn.addEventListener('click', () => {
    if (!currentEvaluationJob) return;
    downloadCsv(CsvExport.buildSummaryCsv(currentEvaluationJob), makeCsvFilename('評分總表'));
});

detailDownloadBtn.addEventListener('click', () => {
    if (!currentEvaluationJob) return;
    downloadCsv(CsvExport.buildDetailCsv(currentEvaluationJob), makeCsvFilename('完整分析資料'));
});

function setDownloadButtonsEnabled(enabled) {
    summaryDownloadBtn.disabled = !enabled;
    detailDownloadBtn.disabled = !enabled;
}

function makeCsvFilename(prefix) {
    const now = new Date();
    const pad = value => String(value).padStart(2, '0');
    const timestamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    const shortJobId = (currentEvaluationJob?.id || 'unknown').slice(0, 8);
    return `${prefix}_${shortJobId}_${timestamp}.csv`;
}

function downloadCsv(csv, filename) {
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
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
        feed.innerHTML = "<p>系統未傳回評分結果。</p>";
        return;
    }

    const groups = new Map();
    items.forEach(item => {
        const agent = item.Agent_Name || "未命名評分代理";
        if (!groups.has(agent)) {
            groups.set(agent, []);
        }
        groups.get(agent).push(item);
    });

    groups.forEach((groupItems, agentName) => {
        const groupEl = document.createElement('div');
        groupEl.className = 'agent-group';

        const heading = document.createElement('h3');
        heading.innerText = `${localizeAgentName(agentName)}（${groupItems.length} 項）`;
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
        tdKey.innerText = FIELD_LABELS[key] || key;

        const tdValue = document.createElement('td');
        tdValue.innerText = (value !== null && typeof value === 'object')
            ? JSON.stringify(value)
            : localizeValue(value);

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

function localizeAgentName(name) {
    const match = /^Agent_([A-D])$/.exec(name);
    return match ? `評分代理 ${match[1]}` : name;
}

function localizeValue(value) {
    if (value === true) return '是';
    if (value === false) return '否';
    if (value === null || value === undefined) return '無';

    const translations = {
        pass: '通過',
        passed: '通過',
        fail: '未通過',
        failed: '失敗',
        none: '無',
        completed: '已完成',
        pending: '等待中',
        'in-progress': '進行中'
    };
    return typeof value === 'string' ? (translations[value.toLowerCase()] || value) : value;
}

function localizeMessage(message = '') {
    if (!message) return '';
    if (message === 'Verifying uploaded videos in GCS...') return '正在確認雲端影片…';
    if (message === 'Aggregating agent outputs...') return '正在彙整各項評分結果…';
    if (message === 'Evaluation completed successfully.') return '評分已順利完成。';
    if (message === 'Resuming unfinished video analysis...') return '正在續跑未完成的影片分析…';
    if (message === 'done') return '完成';

    const confirmed = message.match(/^Confirmed (.+)$/);
    if (confirmed) return `已確認影片 ${confirmed[1]}`;

    const started = message.match(/^Starting (.+) mode video analysis\.\.\.$/);
    if (started) return `準備定位影片操作階段（${started[1]} 模式）；分段完成後才會更新完成工作數…`;

    const segmentProgress = message.match(/^Time_cuting (queued|analyzing|retrying) \| (\d+)s \| (.+)$/);
    if (segmentProgress) {
        const phases = {
            queued: '等待模型處理名額',
            analyzing: '已送出整支影片的分段分析請求，等待模型回覆',
            retrying: '分段結果格式或時間範圍驗證未通過，正在重試一次',
        };
        return `${phases[segmentProgress[1]]}（本支影片分段已等待 ${segmentProgress[2]} 秒；完成後才會增加工作數）：${segmentProgress[3]}`;
    }

    const segmented = message.match(/^Time_cuting finished segmenting (.+)$/);
    if (segmented) return `已完成影片分段：${segmented[1]}`;

    const analyzed = message.match(/^(Agent_[A-D]) finished analyzing (.+)$/);
    if (analyzed) return `${localizeAgentName(analyzed[1])} 已完成影片分析：${analyzed[2]}`;

    const failed = message.match(/^Execution failed: (.+)$/);
    if (failed) return `執行失敗：${failed[1]}`;

    return message;
}
