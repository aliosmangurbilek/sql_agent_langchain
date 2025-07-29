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

// Tab functionality
const tabBtns = document.querySelectorAll('.tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    // Load saved DB URI from localStorage
    const savedDbUri = localStorage.getItem('dbUri');
    if (savedDbUri) {
        dbUriInput.value = savedDbUri;
    }
    // Load saved model from localStorage
    const savedModel = localStorage.getItem('selectedModel');
    if (savedModel) {
        modelSelect.value = savedModel;
    }
    // Setup event listeners
    setupEventListeners();

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
}

function showError(message) {
    errorDiv.textContent = message;
    errorDiv.classList.remove('hidden');
}

function hideError() {
    errorDiv.classList.add('hidden');
}

function executeQuery() {
    const dbUri = dbUriInput.value.trim();
    const question = questionInput.value.trim();
    const model = modelSelect.value;

    if (!dbUri || !question) {
        showError('Please provide both a database URI and a question.');
        return;
    }

    showLoading();
    fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ db_uri: dbUri, question: question, model: model })
    })
    .then(res => res.json())
    .then(handleQueryResponse)
    .catch(handleError)
    .finally(hideLoading);
}

function generateChart() {
    const dbUri = dbUriInput.value.trim();
    const question = questionInput.value.trim();
    const model = modelSelect.value;

    if (!dbUri || !question) {
        showError('Please provide both a database URI and a question.');
        return;
    }

    showLoading();
    fetch('/api/chart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ db_uri: dbUri, question: question, model: model })
    })
    .then(res => res.json())
    .then(handleChartResponse)
    .catch(handleError)
    .finally(hideLoading);
}

function handleQueryResponse(data) {
    if (data.error) {
        showError(data.error);
        return;
    }

    // Display SQL query
    sqlOutput.textContent = data.sql_query || 'No SQL generated';

    // Display data results
    if (data.result && data.result.length > 0) {
        dataOutput.textContent = JSON.stringify(data.result, null, 2);
    } else {
        dataOutput.textContent = 'No data returned';
    }

    // Switch to SQL tab to show results
    switchTab('sql');
}

function handleChartResponse(data) {
    if (data.error) {
        showError(data.error);
        return;
    }

    // Display SQL query
    if (data.sql_query) {
        sqlOutput.textContent = data.sql_query;
    }

    // Display data results
    if (data.data && data.data.length > 0) {
        dataOutput.textContent = JSON.stringify(data.data, null, 2);
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

        // Render the Vega-Lite chart
        await vegaEmbed('#chart-output', vegaSpec, {
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
        const response = await fetch('/api/health');
        const data = await response.json();
        console.log('Health check:', data);
        return data.status === 'healthy';
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
