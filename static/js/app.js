// Main Application JavaScript - Refactored and Modularized
// Core functionality and module coordination

// Global module instances
let workerManager;
let schemaLogger;
let modelManager;
let configManager;

// Global state for caching query results (optimization)
let lastQueryResult = null;
let lastQueryQuestion = null;

// Core DOM elements
const questionInput = document.getElementById('question');
const runQueryBtn = document.getElementById('run-query');
const runChartBtn = document.getElementById('run-chart');
const sqlOutput = document.getElementById('sql-output');
const dataOutput = document.getElementById('data-output');
const chartOutput = document.getElementById('chart-output');
const themeToggle = document.getElementById('theme-toggle');
const useLlmToggle = document.getElementById('use-llm');

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
document.addEventListener('DOMContentLoaded', async function() {
    console.log('🚀 Initializing SQL Agent Application...');
    
    // Initialize modules
    workerManager = new WorkerManager();
    schemaLogger = new SchemaLogger();
    modelManager = new ModelManager();
    configManager = new ConfigManager();
    
    // Load saved configuration and defaults
    configManager.loadSavedConfiguration();
    await configManager.loadConfigDefaults();

    // Apply saved theme
    const savedTheme = localStorage.getItem('theme') || 'light';
    UIUtils.setTheme(savedTheme);
    
    // Setup core event listeners
    setupEventListeners();

    // Load models and sample questions (async operations)
    await modelManager.loadModels();
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

    // Clear cache when question changes
    if (questionInput) {
        questionInput.addEventListener('input', () => {
            const currentQuestion = questionInput.value.trim();
            if (lastQueryQuestion && lastQueryQuestion !== currentQuestion) {
                clearCache();
            }
        });
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
    const useLlm = useLlmToggle ? useLlmToggle.checked : false;

    if (!dbUri) {
        UIUtils.showError('Please configure a database URI first');
        return;
    }

    if (!selectedModel) {
        UIUtils.showError('Please select a model first');
        return;
    }

    // Check if we can use cached data for chart generation
    if (generateChart && lastQueryResult && lastQueryQuestion === question && lastQueryResult.data) {
        console.log('🔄 Using cached data for chart generation');
        showCacheNotification();
        await handleChartFromCache();
        return;
    }

    console.log(`🚀 ${generateChart ? 'Generating chart' : 'Executing query'}: "${question}"`);

    // Set button loading state
    setButtonLoadingState(generateChart, true);
    
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
                model: selectedModel,
                use_llm: useLlm
            }),
        });

        updateProgress(50, 'Processing response...');

        const result = await response.json();
        
        updateProgress(75, 'Rendering results...');

        if (response.ok) {
            // Cache the results for potential chart generation
            lastQueryResult = result;
            lastQueryQuestion = question;
            
            handleQuerySuccess(result, generateChart);
        } else {
            handleQueryError(result);
        }

        updateProgress(100, 'Complete!');
        
    } catch (error) {
        console.error('Query execution error:', error);
        UIUtils.showError(`Network error: ${error.message}`);
    } finally {
        // Reset button state
        setButtonLoadingState(generateChart, false);
        setTimeout(() => showProgress(false), 1000);
    }
}

async function handleChartFromCache() {
    try {
        console.log('📊 Generating chart from cached data...');
        
        // Set button loading state for chart generation
        setButtonLoadingState(true, true);
        
        showProgress(true);
        updateProgress(30, 'Generating chart specification...', [
            {name: 'Query Execution', completed: true},
            {name: 'Chart Generation', completed: false},
            {name: 'Rendering', completed: false}
        ]);
        
        // Generate chart spec from cached data
        const useLlm = useLlmToggle ? useLlmToggle.checked : false;
        const chartResponse = await fetch('/api/chart_spec', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                question: lastQueryQuestion,
                data: lastQueryResult.data,
                sql: lastQueryResult.sql,
                use_llm: useLlm
            })
        });
        
        if (chartResponse.ok) {
            const chartResult = await chartResponse.json();
            
            updateProgress(70, 'Rendering chart...', [
                {name: 'Query Execution', completed: true},
                {name: 'Chart Generation', completed: true},
                {name: 'Rendering', completed: false}
            ]);
            
            // Combine cached data with new chart spec
            const combinedResult = {
                ...lastQueryResult,
                vega_spec: chartResult.vega_spec
            };
            
            handleQuerySuccess(combinedResult, true);
            
            updateProgress(100, 'Chart generated successfully!', [
                {name: 'Query Execution', completed: true},
                {name: 'Chart Generation', completed: true},
                {name: 'Rendering', completed: true}
            ]);
        } else {
            throw new Error(`Chart generation failed: ${chartResponse.status}`);
        }
        
    } catch (error) {
        console.error('Error generating chart from cache:', error);
        UIUtils.showError(`Chart generation failed: ${error.message}`);
        // Fallback to full query execution
        console.log('🔄 Falling back to full query execution...');
        clearCache();
        executeQuery(true);
    } finally {
        setButtonLoadingState(true, false); // Reset chart button
        setTimeout(() => showProgress(false), 1000);
    }
}

function showCacheNotification() {
    console.log('💡 Using cached query results for faster chart generation');
    
    // Show a small notification in the UI
    const notification = document.createElement('div');
    notification.className = 'cache-notification';
    notification.innerHTML = '💡 Using cached data for faster chart generation';
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #4CAF50;
        color: white;
        padding: 10px 15px;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        z-index: 1000;
        font-size: 14px;
        animation: slideInRight 0.3s ease-out;
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOutRight 0.3s ease-in';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

function clearCache() {
    lastQueryResult = null;
    lastQueryQuestion = null;
    console.log('🗑️ Query cache cleared');
}

function setButtonLoadingState(isChart, loading) {
    const targetBtn = isChart ? runChartBtn : runQueryBtn;
    const otherBtn = isChart ? runQueryBtn : runChartBtn;
    
    if (!targetBtn) return;
    
    if (loading) {
        // Set loading state for active button
        targetBtn.disabled = true;
        targetBtn.dataset.originalText = targetBtn.textContent;
        targetBtn.innerHTML = isChart ? 
            '<span class="btn-spinner">⏳</span> Generating Chart...' : 
            '<span class="btn-spinner">⏳</span> Fetching Data...';
        
        // Disable other button too
        if (otherBtn) {
            otherBtn.disabled = true;
        }
    } else {
        // Reset both buttons
        if (targetBtn.dataset.originalText) {
            targetBtn.textContent = targetBtn.dataset.originalText;
            delete targetBtn.dataset.originalText;
        }
        targetBtn.disabled = false;
        
        if (otherBtn) {
            otherBtn.disabled = false;
        }
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
