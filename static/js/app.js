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
    
    // Setup event listeners
    setupEventListeners();

    // Load models from OpenRouter
    loadModels();

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
        refreshModelsBtn.addEventListener('click', () => {
            refreshModelsBtn.disabled = true;
            refreshModelsBtn.textContent = '⏳';
            loadModels().finally(() => {
                refreshModelsBtn.disabled = false;
                refreshModelsBtn.textContent = '🔄';
            });
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

    // Display agent answer
    if (data.answer) {
        sqlOutput.textContent = data.answer;
    } else {
        sqlOutput.textContent = 'No answer returned';
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
    if (data.sql) {
        sqlOutput.textContent = data.sql;
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
        const response = await fetch('/healthz');
        const data = await response.json();
        console.log('Health check:', data);
        return data.status === 'healthy';
    } catch (error) {
        console.error('Health check failed:', error);
        return false;
    }
}

// Load models from OpenRouter API
async function loadModels() {
    try {
        const response = await fetch('/api/models');
        const data = await response.json();
        
        if (response.ok) {
            populateModelSelect(data.models);
        } else {
            console.error('Failed to load models:', data.error);
            // Fallback to default models
            populateModelSelect([
                { id: 'deepseek/deepseek-chat', name: 'DeepSeek Chat (Free)', is_free: true },
                { id: 'meta-llama/llama-3.1-8b-instruct:free', name: 'Llama 3.1 8B (Free)', is_free: true },
                { id: 'qwen/qwen-2.5-7b-instruct:free', name: 'Qwen 2.5 7B (Free)', is_free: true }
            ]);
        }
    } catch (error) {
        console.error('Error loading models:', error);
        // Fallback to default models
        populateModelSelect([
            { id: 'deepseek/deepseek-chat', name: 'DeepSeek Chat (Free)', is_free: true },
            { id: 'meta-llama/llama-3.1-8b-instruct:free', name: 'Llama 3.1 8B (Free)', is_free: true },
            { id: 'qwen/qwen-2.5-7b-instruct:free', name: 'Qwen 2.5 7B (Free)', is_free: true }
        ]);
    }
}

function populateModelSelect(models) {
    // Clear existing options
    modelSelect.innerHTML = '';
    
    // Add default option
    const defaultOption = document.createElement('option');
    defaultOption.value = '';
    defaultOption.textContent = 'Select a model...';
    modelSelect.appendChild(defaultOption);
    
    // Group models by free/paid
    const freeModels = models.filter(m => m.is_free);
    const paidModels = models.filter(m => !m.is_free);
    
    // Add free models first
    if (freeModels.length > 0) {
        const freeGroup = document.createElement('optgroup');
        freeGroup.label = '🆓 Free Models';
        freeModels.forEach(model => {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = `${model.name} (${model.provider})`;
            freeGroup.appendChild(option);
        });
        modelSelect.appendChild(freeGroup);
    }
    
    // Add paid models
    if (paidModels.length > 0) {
        const paidGroup = document.createElement('optgroup');
        paidGroup.label = '💰 Paid Models';
        paidModels.forEach(model => {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = `${model.name} (${model.provider})`;
            paidGroup.appendChild(option);
        });
        modelSelect.appendChild(paidGroup);
    }
    
    // Enable the select and restore saved selection
    modelSelect.disabled = false;
    const savedModel = localStorage.getItem('selectedModel');
    if (savedModel && Array.from(modelSelect.options).some(option => option.value === savedModel)) {
        modelSelect.value = savedModel;
    } else if (freeModels.length > 0) {
        // Default to first free model
        modelSelect.value = freeModels[0].id;
    }
}

// Perform initial health check
checkHealth().then(healthy => {
    if (!healthy) {
        showError('Backend service is not responding. Please check the server.');
    }
});
