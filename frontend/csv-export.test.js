const assert = require('node:assert/strict');
const {
    EXPECTED_CRITERIA,
    normalizeItems,
    createSummaryRows,
    buildSummaryCsv,
    buildDetailCsv
} = require('./csv-export.js');

const job = {
    id: 'a1b2c3d4-full-id',
    exam_topic: '無菌抽藥技術',
    video_paths: ['gs://bucket/影片一.mp4', 'gs://bucket/video-two.mp4'],
    result: {
        items: [
            { Video_Path: 'gs://bucket/影片一.mp4', Agent_Name: 'Agent_A', score: true, start_time: '00:01', end_time: '00:02', evidence: '=SUM(A1:A2)' },
            { Video_Path: 'gs://bucket/影片一.mp4', Agent_Name: 'Agent_A', score: false, failure_reason: '沒有完成' },
            { Video_Path: 'gs://bucket/影片一.mp4', Agent_Name: 'Agent_B', '步驟編號': 1, '步驟': '洗手', '判定': '未通過', '得分': 0, '看到什麼': '文字,含逗號與"引號"\n換行' },
            { Video_Path: 'gs://bucket/video-two.mp4', Agent_Name: 'Agent_C', '步驟編號': 13, '判定': '通過', '得分': 1, '信心': 0.9 },
            { Video_Path: 'gs://bucket/video-two.mp4', Agent_Name: 'Agent_D', '步驟編號': 21, '得分': 'unknown' }
        ]
    }
};

const normalized = normalizeItems(job.result.items);
assert.equal(normalized[0].stepNumber, 1);
assert.equal(normalized[1].stepNumber, 2);
assert.equal(normalized[0].score, 1);
assert.equal(normalized[1].score, 0);
assert.equal(normalized[2].score, 0);
assert.equal(normalized[4].score, null);
assert.match(normalized[4].dataStatus, /有效分數/);

const summaryRows = createSummaryRows(job);
assert.equal(summaryRows.length, 2);
assert.equal(summaryRows[0][4], 3);
assert.equal(summaryRows[0][5], 1);
assert.equal(summaryRows[0][6], '33.33%');
assert.equal(summaryRows[0][7], 1); // Step 1, Agent A
assert.equal(summaryRows[0][11], 0); // Step 1, Agent B
assert.equal(EXPECTED_CRITERIA.some(([, step]) => step === 11), false);

const summaryCsv = buildSummaryCsv(job);
const detailCsv = buildDetailCsv(job);
assert.equal(summaryCsv.charCodeAt(0), 0xFEFF);
assert.equal(detailCsv.charCodeAt(0), 0xFEFF);
assert.match(detailCsv, /'\=SUM\(A1:A2\)/);
assert.match(detailCsv, /"文字,含逗號與""引號""\n換行"/);
assert.match(detailCsv, /原始項目 JSON/);

console.log('csv-export tests passed');
