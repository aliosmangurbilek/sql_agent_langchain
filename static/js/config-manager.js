// Configuration Management Module
// Handles loading and managing application configuration

class ConfigManager {
    constructor() {
        this.dbUriInput = document.getElementById('db-uri');
        this.baseDbUriInput = document.getElementById('base-db-uri');
        this.testConnectionBtn = document.getElementById('test-connection-btn');
        this.connectionResultDiv = document.getElementById('test-connection-result');
        this.setupEventListeners();
    }

    setupEventListeners() {
        // Database URI validation and storage
        if (this.dbUriInput) {
            this.dbUriInput.addEventListener('input', (e) => {
                const uri = e.target.value.trim();
                localStorage.setItem('dbUri', uri);
                this.validateDatabaseUri(uri);
            });
        }

        if (this.baseDbUriInput) {
            this.baseDbUriInput.addEventListener('input', (e) => {
                localStorage.setItem('baseDbUri', e.target.value.trim());
            });
        }

        // Test connection button
        if (this.testConnectionBtn) {
            this.testConnectionBtn.addEventListener('click', () => this.testConnection());
        }
    }

    async loadConfigDefaults() {
        try {
            const response = await fetch('/api/config');
            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                const config = result.config;
                
                // Set base database URL if not already set
                if (this.baseDbUriInput && !this.baseDbUriInput.value && config.base_database_url) {
                    this.baseDbUriInput.value = config.base_database_url;
                    localStorage.setItem('baseDbUri', config.base_database_url);
                }
                
                // Set default database URI if not already set
                if (this.dbUriInput && !this.dbUriInput.value && config.default_db_uri) {
                    this.dbUriInput.value = config.default_db_uri;
                    localStorage.setItem('dbUri', config.default_db_uri);
                }
                
                console.log('✅ Configuration defaults loaded successfully');
            } else {
                console.warn('Failed to load configuration defaults:', result.message);
            }
        } catch (error) {
            console.error('Error loading configuration defaults:', error);
        }
    }

    loadSavedConfiguration() {
        // Load saved configuration from localStorage
        const savedDbUri = localStorage.getItem('dbUri');
        const savedBaseDbUri = localStorage.getItem('baseDbUri');
        
        if (savedDbUri && this.dbUriInput) {
            this.dbUriInput.value = savedDbUri;
        }
        if (savedBaseDbUri && this.baseDbUriInput) {
            this.baseDbUriInput.value = savedBaseDbUri;
        }
    }

    validateDatabaseUri(uri) {
        // Basic URI validation (can be enhanced)
        if (uri && !uri.startsWith('postgresql')) {
            console.warn('Database URI should start with postgresql://');
        }
    }

    async testConnection() {
        if (!this.dbUriInput || !this.connectionResultDiv) {
            console.warn('Connection test elements not found');
            return;
        }

        const dbUri = this.dbUriInput.value.trim();
        
        if (!dbUri) {
            this.connectionResultDiv.innerHTML = '<span class="error">Please enter a database URI first!</span>';
            return;
        }

        this.connectionResultDiv.innerHTML = '<span class="loading">Testing connection...</span>';

        try {
            const response = await fetch('/api/test_connection', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ db_uri: dbUri }),
            });

            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                this.connectionResultDiv.innerHTML = '<span class="success">✅ Connection successful!</span>';
            } else {
                this.connectionResultDiv.innerHTML = `<span class="error">❌ Connection failed: ${result.error}</span>`;
            }
        } catch (error) {
            this.connectionResultDiv.innerHTML = `<span class="error">❌ Error: ${error.message}</span>`;
        }
    }

    getCurrentDbUri() {
        return this.dbUriInput ? this.dbUriInput.value.trim() : '';
    }

    getCurrentBaseDbUri() {
        return this.baseDbUriInput ? this.baseDbUriInput.value.trim() : '';
    }
}
