// ------------------------------------------------------------
// Modular App Script (schema banner logic moved to schema_status.js)
// ------------------------------------------------------------

import { loadModelsInto } from './modules/models.js';
import { initSchemaStatus } from './modules/schema_status.js';

// Core DOM elements
const dbUriInput = document.getElementById('db-uri');
const modelSelect = document.getElementById('model-select');
const questionInput = document.getElementById('question');
const runQueryBtn = document.getElementById('run-query');
const runChartBtn = document.getElementById('run-chart');
const answerOutput = document.getElementById('answer-output');
const sqlOutput = document.getElementById('sql-output');
const dataOutput = document.getElementById('data-output');
const chartOutput = document.getElementById('chart-output');
const loadingDiv = document.getElementById('loading');
const errorDiv = document.getElementById('error');
const copyAnswerBtn = document.getElementById('btn-copy-answer');
const copySqlBtn = document.getElementById('btn-copy-sql');
const downloadCsvBtn = document.getElementById('btn-download-csv');
const resultMeta = document.getElementById('result-meta');
const chartInfo = document.getElementById('chart-info');

// Tabs
const tabBtns = document.querySelectorAll('.tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');

// Cache last successful query for chart reuse
let lastSql = null;
let lastData = null;
let lastQuestion = null;

function initApp() {
    const savedDbUri = localStorage.getItem('dbUri');
    if (savedDbUri) dbUriInput.value = savedDbUri;
    setupEventListeners();
    loadModelsInto(modelSelect);
    loadSampleQuestions();
    try {
        window.__schemaStatus = initSchemaStatus(dbUriInput);
    } catch (e) { console.warn('Schema status init failed:', e); }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    // DOM already parsed
    initApp();
}

function setupEventListeners() {
    // Tabs
    tabBtns.forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));

    // Persist DB URI
    dbUriInput.addEventListener('change', () => {
        localStorage.setItem('dbUri', dbUriInput.value);
    });

    // Persist model
    modelSelect.addEventListener('change', () => {
        localStorage.setItem('selectedModel', modelSelect.value);
    });

    // Refresh models
    const refreshModelsBtn = document.getElementById('refresh-models-btn');
    if (refreshModelsBtn) {
        refreshModelsBtn.addEventListener('click', async () => {
            refreshModelsBtn.disabled = true;
            refreshModelsBtn.textContent = '⏳';
            try { await loadModelsInto(modelSelect); } finally {
                refreshModelsBtn.disabled = false;
                refreshModelsBtn.textContent = '🔄';
            }
        });
    }

    runQueryBtn.addEventListener('click', executeQuery);
    runChartBtn.addEventListener('click', generateChart);
    questionInput.addEventListener('keydown', e => { if (e.ctrlKey && e.key === 'Enter') executeQuery(); });

        if (copyAnswerBtn) copyAnswerBtn.addEventListener('click', () => copyToClipboard(answerOutput?.textContent || '', copyAnswerBtn));
        if (copySqlBtn) copySqlBtn.addEventListener('click', () => copyToClipboard(sqlOutput?.textContent || '', copySqlBtn));
        if (downloadCsvBtn) downloadCsvBtn.addEventListener('click', downloadCsv);
}

// ---------------- UI Helpers ----------------
function showLoading(show) { if (loadingDiv) loadingDiv.classList.toggle('hidden', !show); }
function showError(msg) { if (errorDiv) { errorDiv.textContent = msg; errorDiv.classList.remove('hidden'); } }
function clearError() { if (errorDiv) { errorDiv.textContent=''; errorDiv.classList.add('hidden'); } }
function switchTab(tab) { tabBtns.forEach(b=>b.classList.toggle('active', b.dataset.tab===tab)); tabPanes.forEach(p=>p.classList.toggle('active', p.id===`${tab}-tab`)); }

// ---------------- Query Flow ----------------
async function executeQuery() {
    clearError();
    const db_uri = dbUriInput.value.trim();
    const question = questionInput.value.trim();
    const model = modelSelect.value;
    if (!db_uri || !question) { showError('Please provide both a database URI and a question.'); return; }
    runQueryBtn.disabled = true;
    showLoading(true);
    try {
        // Pre-query schema hash check (will mark needs_rebuild if changed)
        try {
            await fetch('/api/admin/embeddings/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ db_uri }) });
        } catch (e) { console.warn('Pre-query schema check failed (continuing):', e); }
        const res = await fetch('/api/query', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ db_uri, question, model }) });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        handleQueryResponse(data);
        // After successful query, refresh schema banner (it might have changed state)
        try { if (window.__schemaStatus && typeof window.__schemaStatus.refreshSchemaStatus === 'function') window.__schemaStatus.refreshSchemaStatus(false); } catch {}
    } catch (e) { showError(e.message); } finally { runQueryBtn.disabled = false; showLoading(false); }
}

async function generateChart() {
    clearError();
    const db_uri = dbUriInput.value.trim();
    const question = questionInput.value.trim();
    const model = modelSelect.value;
    if (!db_uri || !question) { showError('Please provide both a database URI and a question.'); return; }
    if (!lastSql || !Array.isArray(lastData)) { showError('Please run the query first to generate chart.'); return; }
    showLoading(true);
    try {
        const res = await fetch('/api/chart', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ db_uri, question, model, sql: lastSql, data: lastData }) });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        handleChartResponse(data);
    } catch (e) { showError(e.message); } finally { showLoading(false); }
}

function handleQueryResponse(data) {
    if (data.error) { showError(data.error); return; }
    lastSql = data.sql || null;
    lastData = Array.isArray(data.data) ? data.data : null;
    lastQuestion = questionInput.value.trim();
    if (answerOutput) {
        answerOutput.textContent = data.answer || 'No answer returned';
    }
    sqlOutput.textContent = data.sql || 'No SQL generated';
    if (Array.isArray(lastData) && lastData.length) dataOutput.textContent = JSON.stringify(lastData, null, 2);
        updateMeta();
        enableCsvIfPossible();
    switchTab('sql');
}

function handleChartResponse(data) {
    if (data.error) { showError(data.error); return; }
    // Only update SQL box; keep previous natural language answer stable
    if (data.sql) sqlOutput.textContent = data.sql;
    if (Array.isArray(data.data)) { lastData = data.data; dataOutput.textContent = JSON.stringify(lastData, null, 2); }
    if (data.vega_spec) renderChart(data.vega_spec); else chartOutput.textContent = 'No chart specification generated';
    switchTab('chart');
        updateMeta();
        enableCsvIfPossible();
}

// ---------------- Chart Rendering ----------------
async function renderChart(vegaSpec) {
    try {
        chartOutput.innerHTML = '';
        chartOutput.classList.add('has-chart');
        const spec = JSON.parse(JSON.stringify(vegaSpec || {}));
        if (spec && spec.data && spec.data.name === 'table') {
            const values = Array.isArray(lastData) ? lastData : [];
            spec.data = { values: values.slice(0, 5000) };
        }
        await vegaEmbed('#chart-output', spec, { theme: 'quartz', actions: { export: true, source: false, compiled: false, editor: false } });
    } catch (error) {
        console.error('Chart rendering error:', error);
        chartOutput.innerHTML = `<div class="error">Chart rendering failed: ${error.message}</div>`;
        chartOutput.classList.remove('has-chart');
    }
}
    // ---------------- Meta / Copy / CSV ----------------
    function updateMeta() {
        if (!resultMeta) return;
        const rows = Array.isArray(lastData) ? lastData.length : 0;
        const cols = rows ? Object.keys(lastData[0] || {}).length : 0;
        resultMeta.textContent = `Rows: ${rows}${cols? ' | Cols: '+cols:''}`;
    }
    function enableCsvIfPossible() {
        if (!downloadCsvBtn) return;
        const ok = Array.isArray(lastData) && lastData.length > 0;
        downloadCsvBtn.disabled = !ok;
    }
    function copyToClipboard(text, btn) {
        if (!navigator.clipboard) return;
        navigator.clipboard.writeText(text || '').then(() => {
            const old = btn.textContent; btn.textContent='Copied'; btn.disabled=true;
            setTimeout(()=>{ btn.textContent=old; btn.disabled=false; }, 900);
        }).catch(()=>{});
    }
    function downloadCsv() {
        if (!Array.isArray(lastData) || !lastData.length) return;
        const headers = Object.keys(lastData[0]);
        const lines = [headers.join(',')];
        for (const row of lastData) {
            lines.push(headers.map(h => formatCsvCell(row[h])).join(','));
        }
        const blob = new Blob([lines.join('\n')], {type:'text/csv'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'data.csv'; a.click();
        setTimeout(()=>URL.revokeObjectURL(url), 2000);
    }
    function formatCsvCell(v) {
        if (v === null || v === undefined) return '';
        const s = String(v);
        if (/[",\n]/.test(s)) return '"'+s.replace(/"/g,'""')+'"';
        return s;
    }

// ---------------- Samples + Health ----------------
function loadSampleQuestions() {
    const samples = [
        'Show me the top 10 customers by total revenue',
        'What are the monthly sales trends for the last year?',
        'Which products have the highest profit margins?',
        'Show me the distribution of orders by region',
        'What is the average order value by customer segment?'
    ];
    let i = 0;
    const rotate = () => { questionInput.placeholder = `e.g., ${samples[i]}`; i = (i + 1) % samples.length; };
    rotate();
    setInterval(() => { if (!questionInput.value) rotate(); }, 3000);
}

async function checkHealth() {
    try { const r = await fetch('/api/healthz'); const d = await r.json(); if (!d.status || d.status !== 'ok') throw new Error('unhealthy'); }
    catch { showError('Backend service is not responding. Please check the server.'); }
}
checkHealth();

// Test connection button extension
(function addTestConnectionListener() {
    const testBtn = document.getElementById('test-connection-btn');
    if (!testBtn) return;
    testBtn.addEventListener('click', async () => {
        const db_uri = dbUriInput.value.trim();
        const resultDiv = document.getElementById('test-connection-result');
        if (!db_uri) { resultDiv.innerHTML = '<span class="error">Please enter a database URI first!</span>'; return; }
        resultDiv.innerHTML = '<span class="loading">Testing connection...</span>';
        try {
            const res = await fetch('/api/test_connection', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ db_uri }) });
            const data = await res.json();
            if (res.ok) resultDiv.innerHTML = '<span class="success">✅ Connection successful!</span>'; else resultDiv.innerHTML = `<span class="error">❌ Connection failed: ${data.error || data.message || 'Unknown error'}</span>`;
        } catch (e) { resultDiv.innerHTML = `<span class=\"error\">❌ Error: ${e.message}</span>`; }
    });
})();
