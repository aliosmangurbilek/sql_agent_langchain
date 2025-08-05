// Main Application JavaScript - Refactored and Modularized
// Core functionality and module coordination

// Global module instances
let workerManager;
let schemaLogger;
let modelManager;
let configManager;

// Core DOM elements
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

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Initializing SQL Agent Application...');
    
    // Initialize modules
    workerManager = new WorkerManager();
    schemaLogger = new SchemaLogger();
    modelManager = new ModelManager();
    configManager = new ConfigManager();
    
    // Load saved configuration and defaults
    configManager.loadSavedConfiguration();
    configManager.loadConfigDefaults();

    // Apply saved theme
    const savedTheme = localStorage.getItem('theme') || 'light';
    UIUtils.setTheme(savedTheme);
    
    // Setup core event listeners
    setupEventListeners();

    // Load models and sample questions
    modelManager.loadModels();
    loadSampleQuestions();

    console.log('✅ Application initialized successfully');
});

function setupEventListeners() {
    // Tab switching
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => UIUtils.switchTab(btn.dataset.tab));
    });

    // Theme toggle
    if (themeToggle) {
        themeToggle.addEventListener('click', UIUtils.toggleTheme);
    }

    // Query execution
    if (runQueryBtn) {
        runQueryBtn.addEventListener('click', () => executeQuery(false));
    }
    if (runChartBtn) {
        runChartBtn.addEventListener('click', () => executeQuery(true));
    }

    // Sample questions
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('sample-question')) {
            if (questionInput) {
                questionInput.value = e.target.textContent;
                questionInput.focus();
            }
        }
    });

    // Database management event listeners
    const saveBaseUriBtn = document.getElementById('save-base-uri-btn');
    const switchDbBtn = document.getElementById('switch-db-btn');
    const refreshStatusBtn = document.getElementById('refresh-status-btn');
    const databaseSwitcher = document.getElementById('database-switcher');

    if (saveBaseUriBtn) {
        saveBaseUriBtn.addEventListener('click', handleSaveBaseUri);
    }
    if (switchDbBtn) {
        switchDbBtn.addEventListener('click', handleSwitchDatabase);
    }
    if (refreshStatusBtn) {
        refreshStatusBtn.addEventListener('click', () => workerManager.checkWorkerStatus());
    }

    // Enter key handling
    if (questionInput) {
        questionInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && e.ctrlKey) {
                executeQuery(false);
            }
        });
    }

    if (databaseSwitcher) {
        databaseSwitcher.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                handleSwitchDatabase();
            }
        });
    }
}

function handleSaveBaseUri() {
    try {
        const baseUri = configManager.getCurrentBaseDbUri();
        if (!baseUri) {
            UIUtils.showError('Please enter a base database URL first');
            return;
        }
        
        const message = workerManager.saveBaseUri(baseUri);
        UIUtils.showSuccess(message);
    } catch (error) {
        UIUtils.showError(error.message);
    }
}

async function handleSwitchDatabase() {
    const databaseSwitcher = document.getElementById('database-switcher');
    if (!databaseSwitcher) return;

    const dbName = databaseSwitcher.value.trim();
    if (!dbName) {
        UIUtils.showError('Please enter a database name');
        return;
    }

    try {
        const result = await workerManager.switchActiveDatabase(dbName);
        UIUtils.showSuccess(`Database switched to: ${result.activeDb}`);
        schemaLogger.logDatabaseSwitch(result.activeDb);
    } catch (error) {
        UIUtils.showError(error.message);
    }
}

async function executeQuery(generateChart = false) {
    if (!questionInput || !questionInput.value.trim()) {
        UIUtils.showError('Please enter a question first');
        return;
    }

    const question = questionInput.value.trim();
    const dbUri = configManager.getCurrentDbUri();
    const selectedModel = modelManager.getSelectedModel();

    if (!dbUri) {
        UIUtils.showError('Please configure a database URI first');
        return;
    }

    if (!selectedModel) {
        UIUtils.showError('Please select a model first');
        return;
    }

    showProgress(true);
    updateProgress(0, 'Initializing query execution...');

    try {
        const endpoint = generateChart ? '/api/chart' : '/api/query';
        
        updateProgress(25, 'Sending request to server...');
        
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                question: question,
                db_uri: dbUri,
                model: selectedModel
            }),
        });

        updateProgress(50, 'Processing response...');

        const result = await response.json();
        
        updateProgress(75, 'Rendering results...');

        if (response.ok) {
            handleQuerySuccess(result, generateChart);
        } else {
            handleQueryError(result);
        }

        updateProgress(100, 'Complete!');
        
    } catch (error) {
        console.error('Query execution error:', error);
        UIUtils.showError(`Network error: ${error.message}`);
    } finally {
        setTimeout(() => showProgress(false), 1000);
    }
}

function handleQuerySuccess(result, isChart) {
    console.log('handleQuerySuccess called with:', { result, isChart });
    if (isChart) {
        console.log('Chart mode - vega_spec:', result.vega_spec);
        // Switch to chart tab and render
        UIUtils.switchTab('chart');
        renderChart(result.vega_spec);
        if (sqlOutput) sqlOutput.textContent = result.answer || 'Query executed successfully';
    } else {
        // Switch to data tab and display results
        UIUtils.switchTab('data');
        if (sqlOutput) sqlOutput.textContent = result.answer || 'Query executed successfully';
        if (dataOutput) {
            if (result.data && Array.isArray(result.data)) {
                dataOutput.textContent = JSON.stringify(result.data, null, 2);
            } else {
                dataOutput.textContent = JSON.stringify(result, null, 2);
            }
        }
    }

    // Show embedding suggestions if available
    if (result.embedding_suggestions) {
        displayEmbeddingSuggestions(result.embedding_suggestions);
    }
}

function handleQueryError(result) {
    UIUtils.showError(`Query failed: ${result.error || result.message || 'Unknown error'}`);
    if (sqlOutput) {
        sqlOutput.textContent = `Error: ${result.error || result.message || 'Query execution failed'}`;
    }
}

function renderChart(chartSpec) {
    console.log('renderChart called with:', chartSpec);
    if (!chartOutput) {
        console.error('chartOutput element not found!');
        return;
    }
    
    chartOutput.innerHTML = '';
    
    if (chartSpec) {
        console.log('Attempting to render chart with vegaEmbed...');
        
        // Safe theme detection
        let theme = 'default';
        try {
            theme = UIUtils.getCurrentTheme() === 'dark' ? 'dark' : 'default';
        } catch (e) {
            console.warn('UIUtils.getCurrentTheme not available, using default theme');
        }
        
        vegaEmbed(chartOutput, chartSpec, {
            theme: theme,
            actions: false
        }).then(() => {
            console.log('Chart rendered successfully');
        }).catch(error => {
            console.error('Chart rendering error:', error);
            chartOutput.innerHTML = '<p class="error">Failed to render chart: ' + error.message + '</p>';
        });
    } else {
        console.log('No chart spec provided');
        chartOutput.innerHTML = '<p>No chart data available</p>';
    }
}

function displayEmbeddingSuggestions(suggestions) {
    const suggestionsDiv = document.getElementById('embedding-suggestions');
    if (!suggestionsDiv || !suggestions || suggestions.length === 0) return;

    suggestionsDiv.innerHTML = '<h4>📊 Schema Context Used:</h4>' +
        suggestions.map(s => {
            // Handle both strings and objects
            if (typeof s === 'string') return `<div class="suggestion">${s}</div>`;
            if (typeof s === 'object') return `<div class="suggestion">${JSON.stringify(s, null, 2)}</div>`;
            return `<div class="suggestion">${String(s)}</div>`;
        }).join('');
}

function showProgress(show = true) {
    if (progressContainer) {
        progressContainer.classList.toggle('hidden', !show);
        if (!show) {
            resetProgress();
        }
    }
}

function updateProgress(percentage, message, steps = []) {
    if (progressPercentage) progressPercentage.textContent = `${percentage}%`;
    if (progressFill) progressFill.style.width = `${percentage}%`;
    if (progressMessage) progressMessage.textContent = message;
    
    if (progressSteps && steps.length > 0) {
        progressSteps.innerHTML = steps.map(step => 
            `<div class="progress-step ${step.completed ? 'completed' : ''}">${step.name}</div>`
        ).join('');
    }
}

function resetProgress() {
    updateProgress(0, 'Initializing...', []);
}

async function loadSampleQuestions() {
    // This can be enhanced to load from an API endpoint
    const sampleQuestions = [
        "Show me the top 10 customers by revenue",
        "What's the average order value by month?",
        "List all products with low inventory",
        "Show sales trends over the last 6 months"
    ];
    
    // Add sample questions to UI if there's a dedicated section
    const questionsContainer = document.getElementById('sample-questions');
    if (questionsContainer) {
        questionsContainer.innerHTML = sampleQuestions
            .map(q => `<button class="sample-question btn btn-outline">${q}</button>`)
            .join('');
    }
}

// Export functions for debugging and testing
window.AppDebug = {
    workerManager: () => workerManager,
    schemaLogger: () => schemaLogger,
    modelManager: () => modelManager,
    configManager: () => configManager,
    executeQuery,
    loadSampleQuestions
};
