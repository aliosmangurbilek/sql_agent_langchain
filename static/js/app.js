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
    initSchemaStatus(dbUriInput);
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
        const res = await fetch('/api/query', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ db_uri, question, model }) });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        handleQueryResponse(data);
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
    switchTab('sql');
}

function handleChartResponse(data) {
    if (data.error) { showError(data.error); return; }
    // Only update SQL box; keep previous natural language answer stable
    if (data.sql) sqlOutput.textContent = data.sql;
    if (Array.isArray(data.data)) { lastData = data.data; dataOutput.textContent = JSON.stringify(lastData, null, 2); }
    if (data.vega_spec) renderChart(data.vega_spec); else chartOutput.textContent = 'No chart specification generated';
    switchTab('chart');
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
