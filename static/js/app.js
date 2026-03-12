// ------------------------------------------------------------
// Main application script
// ------------------------------------------------------------

import { loadModelsInto } from './modules/models.js';
import { loadDatabasesInto } from './modules/databases.js';
import { initSchemaStatus } from './modules/schema_status.js';

const databaseSelect = document.getElementById('database-select');
const dbUriInput = document.getElementById('db-uri');
const advancedDbPanel = document.getElementById('advanced-db-panel');
const modelSelect = document.getElementById('model-select');
const questionInput = document.getElementById('question');
const sampleQuestionsLabel = document.getElementById('sample-questions-label');
const sampleQuestionsContainer = document.getElementById('sample-questions');
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
const hasServerDefaultDb = document.body.dataset.hasDefaultDb === 'true';

const tabBtns = document.querySelectorAll('.tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');

let lastSql = null;
let lastData = null;

const SAMPLE_QUESTIONS_BY_DATABASE = {
  pagila: [
    'Find the top 10 most popular film categories based on rental frequency.',
    'Show the top 10 customers by total revenue.',
  ],
  chinook: [
    'Find the top 10 customers by total spending.',
    'Show the genres with the highest number of tracks.',
  ],
  titanic: [
    'Query passengers with the most expensive fares.',
    'Show survival rates grouped by passenger class.',
  ],
  netflix: [
    'Find the directors with the most movies in the database.',
    'Show the release years with the most titles added.',
  ],
  periodic_table: [
    'Look up the element with the Atomic Number 10.',
    'Find the heaviest elements that are gases at room temperature.',
  ],
  happiness_index: [
    'Find the countries where the happiness score is above average but the GDP per capita is below average.',
    'Show the top 10 countries by happiness score.',
  ],
};

const DEFAULT_SAMPLE_QUESTIONS = [
  'Show the top 10 rows that best represent this database.',
  'List the most important categories or groups in this dataset.',
];

function getDbTargetPayload() {
  const manualOverrideEnabled = Boolean(advancedDbPanel?.open);
  const db_uri = manualOverrideEnabled ? (dbUriInput.value.trim() || null) : null;
  const database = db_uri ? null : (databaseSelect.value || '').trim() || null;
  return { db_uri, database };
}

function hasResolvableDbTarget() {
  const target = getDbTargetPayload();
  return Boolean(target.db_uri || target.database || hasServerDefaultDb);
}

function showLoading(show) {
  if (loadingDiv) loadingDiv.classList.toggle('hidden', !show);
}

function showError(msg) {
  if (!errorDiv) return;
  errorDiv.textContent = msg;
  errorDiv.classList.remove('hidden');
}

function clearError() {
  if (!errorDiv) return;
  errorDiv.textContent = '';
  errorDiv.classList.add('hidden');
}

function clearConnectionStatus() {
  const resultDiv = document.getElementById('test-connection-result');
  if (resultDiv) resultDiv.innerHTML = '';
}

function getSelectedDatabaseForSamples() {
  const manualOverrideEnabled = Boolean(advancedDbPanel?.open && dbUriInput.value.trim());
  if (manualOverrideEnabled) return null;
  return (databaseSelect.value || '').trim() || null;
}

function getSampleQuestionsForCurrentDatabase() {
  const selectedDatabase = getSelectedDatabaseForSamples();
  if (selectedDatabase && SAMPLE_QUESTIONS_BY_DATABASE[selectedDatabase]) {
    return {
      database: selectedDatabase,
      questions: SAMPLE_QUESTIONS_BY_DATABASE[selectedDatabase],
    };
  }
  return {
    database: null,
    questions: DEFAULT_SAMPLE_QUESTIONS,
  };
}

function applySampleQuestion(question) {
  questionInput.value = question;
  questionInput.focus();
  clearError();
}

function renderSampleQuestions() {
  if (!sampleQuestionsContainer || !sampleQuestionsLabel) return;

  const { database, questions } = getSampleQuestionsForCurrentDatabase();
  sampleQuestionsLabel.textContent = database
    ? `Suggested questions for ${database.replaceAll('_', ' ')}`
    : 'Suggested questions';

  sampleQuestionsContainer.innerHTML = '';
  questions.forEach(question => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'sample-question-chip';
    button.textContent = question;
    button.dataset.question = question;
    sampleQuestionsContainer.appendChild(button);
  });

  if (!questionInput.value && questions[0]) {
    questionInput.placeholder = `e.g., ${questions[0]}`;
  }
}

function switchTab(tab) {
  tabBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tab));
  tabPanes.forEach(pane => pane.classList.toggle('active', pane.id === `${tab}-tab`));
}

async function initApp() {
  localStorage.removeItem('dbUri');
  setupEventListeners();

  try {
    await loadDatabasesInto(databaseSelect);
  } catch (error) {
    console.error('Error loading databases:', error);
    databaseSelect.innerHTML = '<option value="">Database list unavailable</option>';
    databaseSelect.disabled = !hasServerDefaultDb;
  }

  loadModelsInto(modelSelect);
  renderSampleQuestions();

  try {
    window.__schemaStatus = initSchemaStatus({
      getTargetPayload: getDbTargetPayload,
      hasResolvableDbTarget,
      watchElements: [databaseSelect, dbUriInput],
    });
  } catch (error) {
    console.warn('Schema status init failed:', error);
  }
}

function setupEventListeners() {
  tabBtns.forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));

  databaseSelect.addEventListener('change', () => {
    if (databaseSelect.value) {
      localStorage.setItem('selectedDatabase', databaseSelect.value);
      if (dbUriInput.value.trim()) dbUriInput.value = '';
    } else {
      localStorage.removeItem('selectedDatabase');
    }
    clearConnectionStatus();
    renderSampleQuestions();
  });

  dbUriInput.addEventListener('input', () => {
    clearConnectionStatus();
    renderSampleQuestions();
  });

  advancedDbPanel?.addEventListener('toggle', () => {
    clearConnectionStatus();
    if (!advancedDbPanel.open) {
      dbUriInput.value = '';
    }
    renderSampleQuestions();
    window.__schemaStatus?.refreshSchemaStatus?.(false);
  });

  modelSelect.addEventListener('change', () => {
    localStorage.setItem('selectedModel', modelSelect.value);
  });

  const refreshModelsBtn = document.getElementById('refresh-models-btn');
  if (refreshModelsBtn) {
    refreshModelsBtn.addEventListener('click', async () => {
      refreshModelsBtn.disabled = true;
      refreshModelsBtn.textContent = '⏳';
      try {
        await loadModelsInto(modelSelect);
      } finally {
        refreshModelsBtn.disabled = false;
        refreshModelsBtn.textContent = '🔄';
      }
    });
  }

  runQueryBtn.addEventListener('click', executeQuery);
  runChartBtn.addEventListener('click', generateChart);
  questionInput.addEventListener('keydown', event => {
    if (event.ctrlKey && event.key === 'Enter') executeQuery();
  });
  sampleQuestionsContainer?.addEventListener('click', event => {
    const button = event.target.closest('.sample-question-chip');
    if (!button?.dataset.question) return;
    applySampleQuestion(button.dataset.question);
  });

  if (copyAnswerBtn) {
    copyAnswerBtn.addEventListener('click', () => copyToClipboard(answerOutput?.textContent || '', copyAnswerBtn));
  }
  if (copySqlBtn) {
    copySqlBtn.addEventListener('click', () => copyToClipboard(sqlOutput?.textContent || '', copySqlBtn));
  }
  if (downloadCsvBtn) {
    downloadCsvBtn.addEventListener('click', downloadCsv);
  }

  const testBtn = document.getElementById('test-connection-btn');
  if (testBtn) {
    testBtn.addEventListener('click', testConnection);
  }
}

async function executeQuery() {
  clearError();
  const question = questionInput.value.trim();
  const model = modelSelect.value;
  const payload = getDbTargetPayload();

  if (!question) {
    showError('Please provide a question.');
    return;
  }
  if (!hasResolvableDbTarget()) {
    showError('Please select a database or configure DEFAULT_DB_URI on the server.');
    return;
  }

  runQueryBtn.disabled = true;
  showLoading(true);

  try {
    try {
      await fetch('/api/admin/embeddings/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (error) {
      console.warn('Pre-query schema check failed (continuing):', error);
    }

    const response = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...payload, question, model }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

    handleQueryResponse(data);
    if (window.__schemaStatus?.refreshSchemaStatus) {
      window.__schemaStatus.refreshSchemaStatus(false);
    }
  } catch (error) {
    showError(error.message);
  } finally {
    runQueryBtn.disabled = false;
    showLoading(false);
  }
}

async function generateChart() {
  clearError();
  const question = questionInput.value.trim();
  const model = modelSelect.value;
  const payload = getDbTargetPayload();

  if (!question) {
    showError('Please provide a question.');
    return;
  }
  if (!hasResolvableDbTarget()) {
    showError('Please select a database or configure DEFAULT_DB_URI on the server.');
    return;
  }
  if (!lastSql || !Array.isArray(lastData)) {
    showError('Please run the query first to generate chart.');
    return;
  }

  showLoading(true);
  try {
    const response = await fetch('/api/chart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...payload, question, model, sql: lastSql, data: lastData }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    handleChartResponse(data);
  } catch (error) {
    showError(error.message);
  } finally {
    showLoading(false);
  }
}

function handleQueryResponse(data) {
  if (data.error) {
    showError(data.error);
    return;
  }

  lastSql = data.sql || null;
  lastData = Array.isArray(data.data) ? data.data : null;

  if (answerOutput) answerOutput.textContent = data.answer || 'No answer returned';
  sqlOutput.textContent = data.sql || 'No SQL generated';
  dataOutput.textContent = Array.isArray(lastData) && lastData.length
    ? JSON.stringify(lastData, null, 2)
    : 'No data available.';

  updateMeta();
  enableCsvIfPossible();
  switchTab('sql');
}

function handleChartResponse(data) {
  if (data.error) {
    showError(data.error);
    return;
  }

  if (data.sql) sqlOutput.textContent = data.sql;
  if (Array.isArray(data.data)) {
    lastData = data.data;
    dataOutput.textContent = JSON.stringify(lastData, null, 2);
  }
  if (data.vega_spec) renderChart(data.vega_spec);
  else chartOutput.textContent = 'No chart specification generated';

  updateMeta();
  enableCsvIfPossible();
  switchTab('chart');
}

async function renderChart(vegaSpec) {
  try {
    chartOutput.innerHTML = '';
    chartOutput.classList.add('has-chart');
    const spec = JSON.parse(JSON.stringify(vegaSpec || {}));
    if (spec?.data?.name === 'table') {
      spec.data = { values: Array.isArray(lastData) ? lastData.slice(0, 5000) : [] };
    }
    await vegaEmbed('#chart-output', spec, {
      theme: 'quartz',
      actions: { export: true, source: false, compiled: false, editor: false },
    });
  } catch (error) {
    console.error('Chart rendering error:', error);
    chartOutput.innerHTML = `<div class="error">Chart rendering failed: ${error.message}</div>`;
    chartOutput.classList.remove('has-chart');
  }
}

function updateMeta() {
  if (!resultMeta) return;
  const rows = Array.isArray(lastData) ? lastData.length : 0;
  const cols = rows ? Object.keys(lastData[0] || {}).length : 0;
  resultMeta.textContent = `Rows: ${rows}${cols ? ` | Cols: ${cols}` : ''}`;
}

function enableCsvIfPossible() {
  if (!downloadCsvBtn) return;
  downloadCsvBtn.disabled = !(Array.isArray(lastData) && lastData.length > 0);
}

function copyToClipboard(text, button) {
  if (!navigator.clipboard) return;
  navigator.clipboard.writeText(text || '').then(() => {
    const oldText = button.textContent;
    button.textContent = 'Copied';
    button.disabled = true;
    setTimeout(() => {
      button.textContent = oldText;
      button.disabled = false;
    }, 900);
  }).catch(() => {});
}

function downloadCsv() {
  if (!Array.isArray(lastData) || !lastData.length) return;
  const headers = Object.keys(lastData[0]);
  const lines = [headers.join(',')];
  for (const row of lastData) {
    lines.push(headers.map(header => formatCsvCell(row[header])).join(','));
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'data.csv';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function formatCsvCell(value) {
  if (value === null || value === undefined) return '';
  const text = String(value);
  if (/[",\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

async function checkHealth() {
  try {
    const response = await fetch('/api/healthz');
    const data = await response.json();
    if (data.status !== 'ok') throw new Error('unhealthy');
  } catch {
    showError('Backend service is not responding. Please check the server.');
  }
}

async function testConnection() {
  const resultDiv = document.getElementById('test-connection-result');
  if (!resultDiv) return;
  if (!hasResolvableDbTarget()) {
    resultDiv.innerHTML = '<span class="error">Please choose a database first.</span>';
    return;
  }

  resultDiv.innerHTML = '<span class="loading">Testing connection...</span>';
  try {
    const response = await fetch('/api/test_connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(getDbTargetPayload()),
    });
    const data = await response.json();
    if (response.ok) {
      resultDiv.innerHTML = '<span class="success">✅ Connection successful!</span>';
    } else {
      resultDiv.innerHTML = `<span class="error">❌ Connection failed: ${data.error || data.message || 'Unknown error'}</span>`;
    }
  } catch (error) {
    resultDiv.innerHTML = `<span class="error">❌ Error: ${error.message}</span>`;
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}

checkHealth();
