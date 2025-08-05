// Main Application JavaScript
// Core functionality and initialization

// Global references to DOM elements
const dbUriInput = document.getElementById('db-uri');
const baseDbUriInput = document.getElementById('base-db-uri');
const databaseSwitcher = document.getElementById('database-switcher');
const switchDbBtn = document.getElementById('switch-db-btn');
const saveBaseUriBtn = document.getElementById('save-base-uri-btn');
const refreshStatusBtn = document.getElementById('refresh-status-btn');
const modelSelect = document.getElementById('model-select');
const questionInput = document.getElementById('question');
const runQueryBtn = document.getElementById('run-query');
const runChartBtn = document.getElementById('run-chart');
const sqlOutput = document.getElementById('sql-output');
const dataOutput = document.getElementById('data-output');
const chartOutput = document.getElementById('chart-output');
const themeToggle = document.getElementById('theme-toggle');

// Progress elements
const progressContainer = document.getElementById('progress-container');
const progressTitle = document.getElementById('progress-title');
const progressPercentage = document.getElementById('progress-percentage');
const progressFill = document.getElementById('progress-fill');
const progressMessage = document.getElementById('progress-message');
const progressSteps = document.getElementById('progress-steps');

// Tab functionality
const tabBtns = document.querySelectorAll('.tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');

// Global module instances
let workerManager;
let schemaLogger;

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    // Initialize modules
    workerManager = new WorkerManager();
    schemaLogger = new SchemaLogger();
    
    // Load saved configuration from localStorage
    const savedDbUri = localStorage.getItem('dbUri');
    const savedBaseDbUri = localStorage.getItem('baseDbUri');
    
    if (savedDbUri) {
        dbUriInput.value = savedDbUri;
    }
    if (savedBaseDbUri) {
        baseDbUriInput.value = savedBaseDbUri;
    }

    // Apply saved theme
    const savedTheme = localStorage.getItem('theme') || 'light';
    UIUtils.setTheme(savedTheme);
    
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
        btn.addEventListener('click', () => UIUtils.switchTab(btn.dataset.tab));
    });

    // Theme toggle
    themeToggle.addEventListener('click', UIUtils.toggleTheme);

    // Query execution
    runQueryBtn.addEventListener('click', () => executeQuery(false));
    runChartBtn.addEventListener('click', () => executeQuery(true));

    // Database URI validation and connection testing
    dbUriInput.addEventListener('input', function() {
        const uri = this.value.trim();
        localStorage.setItem('dbUri', uri);
        validateDatabaseUri(uri);
    });

    document.getElementById('test-connection-btn').addEventListener('click', testConnection);

    // Model management
    const refreshModelsBtn = document.getElementById('refresh-models-btn');
    if (refreshModelsBtn) {
        refreshModelsBtn.addEventListener('click', loadModels);
    }

    // Sample questions
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('sample-question')) {
            questionInput.value = e.target.textContent;
            questionInput.focus();
        }
    });

    // Database management event listeners
    saveBaseUriBtn.addEventListener('click', handleSaveBaseUri);
    switchDbBtn.addEventListener('click', handleSwitchDatabase);
    refreshStatusBtn.addEventListener('click', () => workerManager.checkWorkerStatus());

    // Base DB URI input
    baseDbUriInput.addEventListener('input', function() {
        localStorage.setItem('baseDbUri', this.value.trim());
    });

    // Enter key handling
    questionInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && e.ctrlKey) {
            executeQuery(false);
        }
    });

    databaseSwitcher.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            handleSwitchDatabase();
        }
    });
}

// Database management handlers
function handleSaveBaseUri() {
    try {
        const message = workerManager.saveBaseUri(baseDbUriInput.value);
        UIUtils.showSuccess(message);
    } catch (error) {
        UIUtils.showError(error.message);
    }
}

async function handleSwitchDatabase() {
    const dbName = databaseSwitcher.value.trim();
    try {
        const result = await workerManager.switchActiveDatabase(dbName);
        UIUtils.showSuccess(`Database switched to: ${result.activeDb}`);
        schemaLogger.logDatabaseSwitch(result.activeDb);
    } catch (error) {
        UIUtils.showError(error.message);
    }
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

function showLoading(show = true, message = "Processing...") {
    const loadingSpan = loadingDiv.querySelector('span');
    if (loadingSpan) {
        loadingSpan.textContent = message;
    }
    loadingDiv.classList.toggle('hidden', !show);
    runQueryBtn.disabled = show;
    runChartBtn.disabled = show;
}

function hideLoading() {
    showLoading(false);
}

function showProgress(show = true) {
    progressContainer.classList.toggle('hidden', !show);
    if (!show) {
        resetProgress();
    }
}

function updateProgress(step, message, progress, isError = false) {
    if (isError) {
        progressTitle.textContent = "Error occurred";
        progressMessage.textContent = message;
        progressFill.style.width = "100%";
        progressFill.style.background = "#dc3545";
        progressPercentage.textContent = "Error";
        return;
    }

    progressTitle.textContent = getStepTitle(step);
    progressMessage.textContent = message;
    progressFill.style.width = progress + "%";
    progressPercentage.textContent = progress + "%";
    
    addProgressStep(step, message, progress);
}

function resetProgress() {
    progressFill.style.width = "0%";
    progressFill.style.background = "linear-gradient(90deg, #667eea 0%, #764ba2 100%)";
    progressPercentage.textContent = "0%";
    progressSteps.innerHTML = "";
}

function getStepTitle(step) {
    const titles = {
        'start': 'Starting Process...',
        'init': 'Initializing...',
        'llm_start': 'AI Processing...',
        'embedding': 'Database Analysis...',
        'query_gen': 'Creating SQL...',
        'query_exec': 'Running Query...',
        'chart_gen': 'Creating Visualization...',
        'complete': 'Complete!',
        'error': 'Error'
    };
    return titles[step] || 'Processing...';
}

function addProgressStep(step, message, progress) {
    const stepElement = document.createElement('div');
    stepElement.className = 'progress-step';
    
    let icon = '';
    let className = 'pending';
    
    if (progress === 100) {
        className = 'completed';
        icon = '✓';
    } else if (progress > 0) {
        className = 'current';
        icon = '⏳';
    } else {
        icon = '⏸';
    }
    
    stepElement.className += ' ' + className;
    stepElement.innerHTML = `
        <span class="progress-step-icon">${icon}</span>
        <span>${message}</span>
    `;
    
    // Remove any existing step with the same step name
    const existingSteps = progressSteps.querySelectorAll(`[data-step="${step}"]`);
    existingSteps.forEach(el => el.remove());
    
    stepElement.setAttribute('data-step', step);
    progressSteps.appendChild(stepElement);
}

function showError(message) {
    errorDiv.textContent = message;
    errorDiv.classList.remove('hidden');
}

function hideError() {
    errorDiv.classList.add('hidden');
}

function handleError(error) {
    console.error('Request failed:', error);
    const msg = error && error.message ? error.message : 'An unexpected error occurred';
    showError(msg);
}

// Helper to fetch JSON with graceful error handling
async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const text = await response.text();
    if (!response.ok) {
        try {
            const data = JSON.parse(text);
            throw new Error(data.error || response.statusText);
        } catch (_) {
            throw new Error(text || response.statusText);
        }
    }
    try {
        return JSON.parse(text);
    } catch (_) {
        throw new Error('Invalid JSON response');
    }

}

function executeQuery() {
    const dbUri = dbUriInput.value.trim();
    const question = questionInput.value.trim();
    const model = modelSelect.value;

    if (!dbUri || !question) {
        showError('Please provide both a database URI and a question.');
        return;
    }

    hideError();
    showProgress(true);
    runQueryBtn.disabled = true;
    runChartBtn.disabled = true;

    const eventSource = new EventSource('/api/query-stream', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ db_uri: dbUri, question: question, model: model })
    });

    // For EventSource, we need to use fetch for POST data and then connect to SSE
    fetch('/api/query-stream', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ db_uri: dbUri, question: question, model: model })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        function readStream() {
            return reader.read().then(({ done, value }) => {
                if (done) {
                    showProgress(false);
                    runQueryBtn.disabled = false;
                    runChartBtn.disabled = false;
                    return;
                }

                const chunk = decoder.decode(value);
                const lines = chunk.split('\n');
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6));
                            handleProgressUpdate(data, 'query');
                        } catch (e) {
                            console.error('Failed to parse SSE data:', e);
                        }
                    }
                }

                return readStream();
            });
        }

        return readStream();
    })
    .catch(error => {
        console.error('Stream error:', error);
        showError(error.message);
        showProgress(false);
        runQueryBtn.disabled = false;
        runChartBtn.disabled = false;
    });
}

function generateChart() {
    const dbUri = dbUriInput.value.trim();
    const question = questionInput.value.trim();
    const model = modelSelect.value;

    if (!dbUri || !question) {
        showError('Please provide both a database URI and a question.');
        return;
    }

    hideError();
    showProgress(true);
    runQueryBtn.disabled = true;
    runChartBtn.disabled = true;

    fetch('/api/chart-stream', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ db_uri: dbUri, question: question, model: model })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        function readStream() {
            return reader.read().then(({ done, value }) => {
                if (done) {
                    showProgress(false);
                    runQueryBtn.disabled = false;
                    runChartBtn.disabled = false;
                    return;
                }

                const chunk = decoder.decode(value);
                const lines = chunk.split('\n');
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6));
                            handleProgressUpdate(data, 'chart');
                        } catch (e) {
                            console.error('Failed to parse SSE data:', e);
                        }
                    }
                }

                return readStream();
            });
        }

        return readStream();
    })
    .catch(error => {
        console.error('Stream error:', error);
        showError(error.message);
        showProgress(false);
        runQueryBtn.disabled = false;
        runChartBtn.disabled = false;
    });
}

function handleProgressUpdate(data, type) {
    const { step, message, progress } = data;
    
    if (step === 'error') {
        updateProgress(step, message, progress, true);
        showError(message);
        return;
    }
    
    updateProgress(step, message, progress);
    
    if (step === 'complete' && data.data) {
        if (type === 'query') {
            handleQueryResponse(data.data);
        } else if (type === 'chart') {
            handleChartResponse(data.data);
        }
    }
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

    // Show SQL query if returned
    if (data.sql) {
        sqlOutput.textContent += `\nSQL: ${data.sql}`;
    }

    // Display data rows if available
    if (data.data && data.data.length > 0) {
        dataOutput.textContent = JSON.stringify(data.data, null, 2);
    } else {
        dataOutput.textContent = 'No data returned';
    }

    // Display embedding suggestions if available
    const suggestionsDiv = document.getElementById('embedding-suggestions');
    if (suggestionsDiv) {
        if (data.embedding_suggestions && data.embedding_suggestions.length > 0) {
            let html = '<b>Embedding Suggestions:</b><ul>';
            data.embedding_suggestions.forEach(s => {
                html += `<li><b>Table:</b> ${s.table} <b>Score:</b> ${s.score.toFixed(3)}<br><span>${s.text}</span></li>`;
            });
            html += '</ul>';
            suggestionsDiv.innerHTML = html;
        } else {
            suggestionsDiv.innerHTML = '';
        }
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
        const data = await fetchJson('/api/healthz');
        console.log('Health check:', data);
        return data.status === 'ok';
    } catch (error) {
        console.error('Health check failed:', error);
        return false;
    }
}

// Load models from OpenRouter API
async function loadModels() {
    try {
        const data = await fetchJson('/api/models');
        if (data.models) {
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

function setTheme(mode) {
    if (mode === 'dark') {
        document.body.classList.add('dark-mode');
        if (themeToggle) {
            themeToggle.textContent = '☀️ Light Mode';
        }
    } else {
        document.body.classList.remove('dark-mode');
        if (themeToggle) {
            themeToggle.textContent = '🌙 Dark Mode';
        }
    }
}

// Utility functions
function validateDatabaseUri(uri) {
    return UIUtils.validateDatabaseUri(uri);
}

function showError(message) {
    UIUtils.showError(message);
}

function showLoading(show = true) {
    UIUtils.showLoading(show);
}

function switchTab(tabName) {
    UIUtils.switchTab(tabName);
}

// Sample questions functionality
function loadSampleQuestions() {
    const questions = [
        "Show me the top 10 customers by revenue",
        "List all products with low stock levels", 
        "What are the sales trends for the last 6 months?",
        "Find customers who haven't purchased in the last year",
        "Show revenue by category for this quarter"
    ];

    const questionsContainer = document.createElement('div');
    questionsContainer.className = 'sample-questions';
    questionsContainer.innerHTML = `
        <h4>💡 Sample Questions:</h4>
        <div class="questions-grid">
            ${questions.map((q, i) => `
                <button class="sample-question" title="Click to use this question">
                    ${q}
                </button>
            `).join('')}
        </div>
    `;

    // Insert after the textarea
    const questionTextarea = document.getElementById('question');
    questionTextarea.parentNode.insertBefore(questionsContainer, questionTextarea.nextSibling);
}

// Model loading functionality
async function loadModels() {
    const refreshBtn = document.getElementById('refresh-models-btn');
    
    if (refreshBtn) refreshBtn.disabled = true;
    modelSelect.innerHTML = '<option value="">Loading models...</option>';

    try {
        const response = await fetch('/api/models');
        const models = await response.json();

        modelSelect.innerHTML = '<option value="">Select a model...</option>';
        
        models.forEach(model => {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = `${model.name} ${model.is_free ? '(Free)' : '(Paid)'}`;
            modelSelect.appendChild(option); 
        });

        // Try to select a default model
        const defaultModel = models.find(m => m.is_free) || models[0];
        if (defaultModel) {
            modelSelect.value = defaultModel.id;
        }
    } catch (error) {
        modelSelect.innerHTML = '<option value="">Failed to load models</option>';
        console.error('Failed to load models:', error);
    } finally {
        if (refreshBtn) refreshBtn.disabled = false;
    }
}

// Test connection functionality
async function testConnection() {
    const dbUri = dbUriInput.value;
    const resultDiv = document.getElementById('test-connection-result');
    
    if (!dbUri) {
        resultDiv.innerHTML = '<span class="error">Please enter a database URI first!</span>';
        return;
    }

    resultDiv.innerHTML = '<span class="loading">Testing connection...</span>';

    try {
        const response = await fetch('/api/test_connection', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ db_uri: dbUri })
        });

        const result = await response.json();
        
        if (result.connected) {
            resultDiv.innerHTML = '<span class="success">✅ Connection successful!</span>';
        } else {
            resultDiv.innerHTML = `<span class="error">❌ Connection failed: ${result.message}</span>`;
        }
    } catch (error) {
        resultDiv.innerHTML = `<span class="error">❌ Error: ${error.message}</span>`;
    }
}

// Placeholder for executeQuery function (implement based on your existing logic)
async function executeQuery(generateChart = false) {
    // TODO: Implement query execution logic
    console.log('Executing query...', generateChart);
}

// Database Management
function saveBaseUri() {
    const baseUri = baseDbUriInput.value.trim();
    if (!baseUri) {
        showError('Please enter a base database URL');
        return;
    }
    
    localStorage.setItem('baseDbUri', baseUri);
    showMessage('Base database URL saved successfully', 'success');
}

async function switchActiveDatabase() {
    const dbName = databaseSwitcher.value.trim();
    if (!dbName) {
        showError('Please enter a database name');
        return;
    }

    try {
        const response = await fetch('/api/worker/set_db', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ database: dbName })
        });

        const data = await response.json();
        
        if (response.ok) {
            showMessage(`Database switched to: ${data.data.active_db}`, 'success');
            checkWorkerStatus(); // Refresh status
            
            // Add to schema log
            addSchemaLogEntry('info', `Database switched to: ${data.data.active_db}`);
        } else {
            showError(`Failed to switch database: ${data.message || 'Unknown error'}`);
        }
    } catch (error) {
        showError(`Network error: ${error.message}`);
    }
}

// Schema Log Management
function addSchemaLogEntry(type, message, extraClass = '') {
    const timestamp = new Date().toLocaleTimeString();
    const logEntry = document.createElement('div');
    logEntry.className = `log-entry ${type} ${extraClass}`;
    
    logEntry.innerHTML = `
        <span class="timestamp">${timestamp}</span>
        <span class="message">${message}</span>
    `;
    
    schemaLogContainer.appendChild(logEntry);
    
    // Auto-scroll to bottom
    schemaLogContainer.scrollTop = schemaLogContainer.scrollHeight;
    
    // Limit log entries to prevent memory issues
    const entries = schemaLogContainer.querySelectorAll('.log-entry');
    if (entries.length > 100) {
        entries[0].remove();
    }
}

function clearSchemaLog() {
    schemaLogContainer.innerHTML = `
        <div class="log-entry info">
            <span class="timestamp">Cleared</span>
            <span class="message">Schema log cleared</span>
        </div>
    `;
}

function toggleSchemaMonitoring() {
    const isMonitoring = toggleSchemaMonitoringBtn.dataset.monitoring === 'true';
    
    if (isMonitoring) {
        stopSchemaMonitoring();
    } else {
        startSchemaMonitoring();
    }
}

function startSchemaMonitoring() {
    // Note: This would typically connect to a Server-Sent Events endpoint
    // For now, we'll simulate with periodic checks
    toggleSchemaMonitoringBtn.textContent = 'Stop Monitoring';
    toggleSchemaMonitoringBtn.dataset.monitoring = 'true';
    toggleSchemaMonitoringBtn.className = 'btn btn-warning btn-sm';
    
    addSchemaLogEntry('info', 'Schema monitoring started');
    
    // Simulate periodic schema change detection
    // In a real implementation, this would be SSE or WebSocket connection
    schemaMonitoring = true;
    simulateSchemaMonitoring();
}

function stopSchemaMonitoring() {
    toggleSchemaMonitoringBtn.textContent = 'Start Monitoring';
    toggleSchemaMonitoringBtn.dataset.monitoring = 'false';
    toggleSchemaMonitoringBtn.className = 'btn btn-primary btn-sm';
    
    schemaMonitoring = false;
    if (schemaEventSource) {
        schemaEventSource.close();
        schemaEventSource = null;
    }
    
    addSchemaLogEntry('info', 'Schema monitoring stopped');
}

function simulateSchemaMonitoring() {
    // This is a simulation - in real implementation, you'd connect to actual schema change events
    // For demonstration purposes only
    if (!schemaMonitoring) return;
    
    // Simulate random schema events for demo
    setTimeout(() => {
        if (schemaMonitoring && Math.random() > 0.7) {
            const actions = [
                { type: 'schema-change', message: '🔄 Table "users" created in schema "public"' },
                { type: 'embedding-refresh', message: '✅ Embeddings refreshed for "public.users" (5 vectors)' },
                { type: 'table-drop', message: '🗑️ Table "temp_data" dropped from schema "public"' }
            ];
            
            const action = actions[Math.floor(Math.random() * actions.length)];
            addSchemaLogEntry('info', action.message, action.type);
        }
        
        simulateSchemaMonitoring();
    }, 5000 + Math.random() * 10000); // Random interval between 5-15 seconds
}

// Helper function for showing messages
function showMessage(message, type = 'info') {
    // Reuse existing error display mechanism
    const errorDiv = document.getElementById('error');
    if (errorDiv) {
        errorDiv.className = `error ${type}`;
        errorDiv.textContent = message;
        errorDiv.classList.remove('hidden');
        
        setTimeout(() => {
            errorDiv.classList.add('hidden');
        }, 3000);
    }
}
