document.getElementById('evaluation-form').addEventListener('submit', async function(e) {
    e.preventDefault();

    // 1. Gather data
    const apiKey = document.getElementById('gemini-api-key').value;
    const studentId = document.getElementById('student-id').value;
    const examTopic = document.getElementById('exam-topic').value;
    
    const rawPaths = document.getElementById('video-paths').value;
    const videoPaths = rawPaths.split(/[\n,]/).map(p => p.trim()).filter(p => p !== '');

    if(videoPaths.length === 0) {
        alert("Please enter at least one valid absolute video path.");
        return;
    }

    // ❌ processing_mode 제거됨
    const payload = {
        student_id: studentId,
        exam_topic: examTopic,
        video_paths: videoPaths,
        gemini_api_key: apiKey
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
        appendLog("Submitting API Job to Backend...");
        
        const response = await fetch('http://localhost:8000/api/v1/evaluations/', {
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
        else if (evtType === "PROGRESS_UPDATE") {
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

function renderResult(result) {
    document.getElementById('progress-container').classList.add('hidden');
    document.getElementById('result-container').classList.remove('hidden');

    document.getElementById('final-score').innerText = result.score;
    
    const badge = document.getElementById('pass-fail-badge');
    if (result.passed) {
        badge.innerText = "PASSED";
        badge.className = "pass";
    } else {
        badge.innerText = "FAILED";
        badge.className = "fail";
    }

    document.getElementById('feedback-text').innerText = result.details || "No additional feedback provided.";

    const tbody = document.getElementById('checklist-body');
    tbody.innerHTML = "";

    if (result.checklist && result.checklist.length > 0) {
        result.checklist.forEach(item => {
            const tr = document.createElement('tr');
            
            const tdDesc = document.createElement('td');
            tdDesc.innerText = item.item;
            
            const tdStatus = document.createElement('td');
            tdStatus.innerText = item.passed ? "✔ PASS" : "✖ FAIL";
            tdStatus.className = item.passed ? "pass" : "fail";

            tr.appendChild(tdDesc);
            tr.appendChild(tdStatus);
            tbody.appendChild(tr);
        });
    }
}
