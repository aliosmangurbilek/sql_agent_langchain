// DOM Elements
const dbUriInput = document.getElementById('db-uri');
const modelSelect = document.getElementById('model-select');
const questionInput = document.getElementById('question');
const runQueryBtn = document.getElementById('run-query');
const runChartBtn = document.getElementById('run-chart');
const sqlOutput = document.getElementById('sql-output');
const dataOutput = document.getElementById('data-output');
const chartOutput = document.getElementById('chart-output');
const loadingDiv = document.getElementById('loading');
const errorDiv = document.getElementById('error');

// Keep last query results to avoid re-running agent for charts
let lastSql = null;
let lastData = null;
let lastQuestion = null;

// Tab functionality
const tabBtns = document.querySelectorAll('.tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');

// Import model module (when loaded as module)
// Note: index.html must load this script as type="module"
import { loadModelsInto } from './modules/models.js';

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    // Load saved DB URI from localStorage
    const savedDbUri = localStorage.getItem('dbUri');
    if (savedDbUri) {
        dbUriInput.value = savedDbUri;
    }
    
    // Setup event listeners
    setupEventListeners();

    // Load models via module
    loadModelsInto(modelSelect);

    // Load sample questions
    loadSampleQuestions();
});

function setupEventListeners() {
    // Tab switching
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Save DB URI to localStorage
    dbUriInput.addEventListener('change', () => {
        localStorage.setItem('dbUri', dbUriInput.value);
    });
    // Save selected model to localStorage
    modelSelect.addEventListener('change', () => {
        localStorage.setItem('selectedModel', modelSelect.value);
    });

    // Refresh models button
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

    // Query execution
    runQueryBtn.addEventListener('click', executeQuery);
    runChartBtn.addEventListener('click', generateChart);

    // Enter key handling
    questionInput.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'Enter') {
            executeQuery();
        }
    });
}

function switchTab(tabName) {
    // Update tab buttons
    tabBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    // Update tab panes
    tabPanes.forEach(pane => {
        pane.classList.toggle('active', pane.id === `${tabName}-tab`);
    });
}

function showLoading(show = true) {
    loadingDiv.classList.toggle('hidden', !show);
    runQueryBtn.disabled = show;
    runChartBtn.disabled = show;
    // Spinner feedback on runQuery button
    if (show) {
        runQueryBtn.dataset.originalText = runQueryBtn.textContent;
        runQueryBtn.innerHTML = '⏳ Running...';
        runQueryBtn.setAttribute('aria-busy', 'true');
    } else {
        if (runQueryBtn.dataset.originalText) {
            runQueryBtn.textContent = runQueryBtn.dataset.originalText;
            delete runQueryBtn.dataset.originalText;
        }
        runQueryBtn.removeAttribute('aria-busy');
    }
}

function showError(message) {
    errorDiv.textContent = message;
    errorDiv.classList.remove('hidden');
}

function hideError() {
    errorDiv.classList.add('hidden');
}

// Generic error handler used in fetch catch blocks
function handleError(error) {
    console.error('Request failed:', error);
    showError(error?.message || 'An unexpected error occurred.');
}

function executeQuery() {
    const dbUri = dbUriInput.value.trim();
    const question = questionInput.value.trim();
    const model = modelSelect.value;

    if (!dbUri || !question) {
        showError('Please provide both a database URI and a question.');
        return;
    }

    // Reset last results for new question
    lastSql = null;
    lastData = null;
    lastQuestion = question;

    showLoading(true);
    fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ db_uri: dbUri, question: question, model: model })
    })
    .then(res => res.json())
    .then(handleQueryResponse)
    .catch(handleError)
    .finally(() => showLoading(false));
}

function generateChart() {
    const dbUri = dbUriInput.value.trim();
    const question = questionInput.value.trim();
    const model = modelSelect.value;

    if (!dbUri || !question) {
        showError('Please provide both a database URI and a question.');
        return;
    }

    if (!lastSql || !Array.isArray(lastData)) {
        showError('Please run the query first to generate chart.');
        return;
    }

    showLoading(true);
    fetch('/api/chart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Pass cached sql and data to avoid re-running agent
        body: JSON.stringify({ db_uri: dbUri, question: question, model: model, sql: lastSql, data: lastData })
    })
    .then(res => res.json())
    .then(handleChartResponse)
    .catch(handleError)
    .finally(() => showLoading(false));
}

function handleQueryResponse(data) {
    if (data.error) {
        showError(data.error);
        return;
    }

    // Cache SQL and rows from agent to reuse for charts
    if (data.sql) {
        lastSql = data.sql;
    }
    if (data.data) {
        lastData = data.data;
    }

    // Display agent answer
    if (data.answer) {
        sqlOutput.textContent = data.answer;
    } else {
        sqlOutput.textContent = 'No answer returned';
    }

    // Display data results if available
    if (Array.isArray(lastData) && lastData.length > 0) {
        dataOutput.textContent = JSON.stringify(lastData, null, 2);
    }

    // Stay on SQL tab by default
    switchTab('sql');
}

function handleChartResponse(data) {
    if (data.error) {
        showError(data.error);
        return;
    }

    // Display SQL query used for chart
    if (data.sql) {
        sqlOutput.textContent = data.sql;
    }

    // Display and cache data results
    if (Array.isArray(data.data) && data.data.length > 0) {
        lastData = data.data;
        dataOutput.textContent = JSON.stringify(lastData, null, 2);
    }

    // Display chart
    if (data.vega_spec) {
        renderChart(data.vega_spec);
    } else {
        chartOutput.innerHTML = 'No chart specification generated';
    }

    // Switch to chart tab to show results
    switchTab('chart');
}

async function renderChart(vegaSpec) {
    try {
        // Clear previous chart
        chartOutput.innerHTML = '';
        chartOutput.classList.add('has-chart');

        // Deep-clone and inject data if spec expects a named dataset
        const spec = JSON.parse(JSON.stringify(vegaSpec || {}));
        if (spec && spec.data && spec.data.name === 'table') {
            const values = Array.isArray(lastData) ? lastData : [];
            // Limit to avoid rendering huge datasets on the client
            spec.data = { values: values.slice(0, 5000) };
        }

        // Render the Vega-Lite chart
        await vegaEmbed('#chart-output', spec, {
            theme: 'quartz',
            actions: {
                export: true,
                source: false,
                compiled: false,
                editor: false
            }
        });

    } catch (error) {
        console.error('Chart rendering error:', error);
        chartOutput.innerHTML = `<div class="error">Chart rendering failed: ${error.message}</div>`;
        chartOutput.classList.remove('has-chart');
    }
}

function loadSampleQuestions() {
    const samples = [
        "Show me the top 10 customers by total revenue",
        "What are the monthly sales trends for the last year?",
        "Which products have the highest profit margins?",
        "Show me the distribution of orders by region",
        "What is the average order value by customer segment?"
    ];

    // Add sample questions as placeholder rotation
    let currentSample = 0;

    function rotatePlaceholder() {
        questionInput.placeholder = `e.g., ${samples[currentSample]}`;
        currentSample = (currentSample + 1) % samples.length;
    }

    // Initial placeholder
    rotatePlaceholder();

    // Rotate every 3 seconds when input is empty
    setInterval(() => {
        if (!questionInput.value) {
            rotatePlaceholder();
        }
    }, 3000);
}

// Health check function
async function checkHealth() {
    try {
        const response = await fetch('/api/healthz');
        const data = await response.json();
        console.log('Health check:', data);
        return data.status === 'ok';
    } catch (error) {
        console.error('Health check failed:', error);
        return false;
    }
}

// Perform initial health check
checkHealth().then(healthy => {
    if (!healthy) {
        showError('Backend service is not responding. Please check the server.');
    }
});

// Extend event listeners to include Test Connection button
(function extendTestConnectionListener(){
    const testBtn = document.getElementById('test-connection-btn');
    if (!testBtn) return;
    testBtn.addEventListener('click', async () => {
        const dbUri = dbUriInput.value.trim();
        const resultDiv = document.getElementById('test-connection-result');
        if (!dbUri) {
            resultDiv.innerHTML = '<span class="error">Please enter a database URI first!</span>';
            return;
        }
        resultDiv.innerHTML = '<span class="loading">Testing connection...</span>';
        try {
            const response = await fetch('/api/test_connection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ db_uri: dbUri })
            });
            const result = await response.json();
            if (response.ok) {
                resultDiv.innerHTML = '<span class="success">✅ Connection successful!</span>';
            } else {
                resultDiv.innerHTML = `<span class="error">❌ Connection failed: ${result.error || result.message || 'Unknown error'}</span>`;
            }
        } catch (error) {
            resultDiv.innerHTML = `<span class="error">❌ Error: ${error.message}</span>`;
        }
    });
})();
