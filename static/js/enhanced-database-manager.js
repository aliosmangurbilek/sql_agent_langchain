// Enhanced Database Manager for dynamic database handling
// Handles multiple databases with automatic embedding creation and testing

class EnhancedDatabaseManager {
    constructor() {
        this.currentDatabase = null;
        this.databaseCache = new Map();
        this.setupEventListeners();
    }

    setupEventListeners() {
        // Enhanced database connection testing
        const testConnectionBtn = document.getElementById('test-connection-btn');
        if (testConnectionBtn) {
            testConnectionBtn.addEventListener('click', () => this.testAndPrepareDatabase());
        }

        // Database switching with preparation
        const switchDbBtn = document.getElementById('switch-db-btn');
        if (switchDbBtn) {
            switchDbBtn.addEventListener('click', () => this.switchDatabase());
        }

        // Rebuild embeddings button
        const rebuildBtn = document.getElementById('rebuild-embeddings-btn');
        if (rebuildBtn) {
            rebuildBtn.addEventListener('click', () => this.rebuildEmbeddings());
        }
    }

    async testAndPrepareDatabase(forceRebuild = false) {
        const dbUriInput = document.getElementById('db-uri');
        const resultDiv = document.getElementById('test-connection-result');
        
        if (!dbUriInput || !resultDiv) {
            console.warn('Database test elements not found');
            return;
        }

        const dbUri = dbUriInput.value.trim();
        if (!dbUri) {
            resultDiv.innerHTML = '<span class="error">Please enter a database URI first!</span>';
            return;
        }

        resultDiv.innerHTML = '<span class="loading">🔄 Testing connection and preparing database...</span>';

        try {
            const response = await fetch('/api/database/test-and-prepare', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    db_uri: dbUri,
                    force_rebuild: forceRebuild
                }),
            });

            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                this.currentDatabase = dbUri;
                this.databaseCache.set(dbUri, result.database_info);
                
                const dbInfo = result.database_info;
                const embeddingInfo = result.embedding_info;
                
                let message = `✅ Connected to database: ${dbInfo.db_name}<br>`;
                message += `📊 Found ${dbInfo.table_count} tables<br>`;
                message += `🔧 Embeddings: ${embeddingInfo.action}<br>`;
                
                if (dbInfo.tables && dbInfo.tables.length > 0) {
                    message += `📋 Sample tables: ${dbInfo.tables.slice(0, 5).join(', ')}`;
                    if (dbInfo.tables.length > 5) {
                        message += ` and ${dbInfo.tables.length - 5} more...`;
                    }
                }

                resultDiv.innerHTML = `<span class="success">${message}</span>`;
                
                // Show schema information
                this.displaySchemaInfo(dbInfo);
                
                // Enable query interface
                this.enableQueryInterface();
                
            } else {
                resultDiv.innerHTML = `<span class="error">❌ ${result.message || 'Database preparation failed'}</span>`;
            }
        } catch (error) {
            resultDiv.innerHTML = `<span class="error">❌ Error: ${error.message}</span>`;
        }
    }

    async switchDatabase() {
        const databaseSwitcher = document.getElementById('database-switcher');
        const baseDbUriInput = document.getElementById('base-db-uri');
        
        if (!databaseSwitcher || !baseDbUriInput) return;

        const dbName = databaseSwitcher.value.trim();
        const baseUri = baseDbUriInput.value.trim();
        
        if (!dbName) {
            UIUtils.showError('Please enter a database name');
            return;
        }
        
        if (!baseUri) {
            UIUtils.showError('Please enter a base database URL first');
            return;
        }

        try {
            // Construct full database URI
            const fullDbUri = this.constructDatabaseUri(baseUri, dbName);
            
            // Test and prepare the new database
            document.getElementById('db-uri').value = fullDbUri;
            await this.testAndPrepareDatabase();
            
            UIUtils.showSuccess(`Switched to database: ${dbName}`);
            
        } catch (error) {
            UIUtils.showError(`Failed to switch database: ${error.message}`);
        }
    }

    constructDatabaseUri(baseUri, dbName) {
        try {
            const url = new URL(baseUri);
            url.pathname = `/${dbName}`;
            
            // Convert asyncpg to psycopg2 for SQLAlchemy compatibility if needed
            if (url.protocol === 'postgresql+asyncpg:') {
                url.protocol = 'postgresql:';
            }
            
            return url.toString();
        } catch (error) {
            throw new Error(`Invalid base URI: ${error.message}`);
        }
    }

    async rebuildEmbeddings() {
        if (!this.currentDatabase) {
            UIUtils.showError('No database connected. Please test a connection first.');
            return;
        }

        const resultDiv = document.getElementById('test-connection-result');
        if (resultDiv) {
            resultDiv.innerHTML = '<span class="loading">🔄 Rebuilding embeddings...</span>';
        }

        try {
            const response = await fetch('/api/database/rebuild-embeddings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    db_uri: this.currentDatabase
                }),
            });

            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                UIUtils.showSuccess('Embeddings rebuilt successfully');
                if (resultDiv) {
                    resultDiv.innerHTML = '<span class="success">✅ Embeddings rebuilt successfully</span>';
                }
            } else {
                UIUtils.showError(`Failed to rebuild embeddings: ${result.message}`);
            }
        } catch (error) {
            UIUtils.showError(`Error rebuilding embeddings: ${error.message}`);
        }
    }

    async searchTables(query, k = 5) {
        if (!this.currentDatabase) {
            throw new Error('No database connected');
        }

        try {
            const response = await fetch('/api/database/search-tables', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    db_uri: this.currentDatabase,
                    query: query,
                    k: k
                }),
            });

            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                return result.results;
            } else {
                throw new Error(result.message || 'Table search failed');
            }
        } catch (error) {
            console.error('Table search error:', error);
            throw error;
        }
    }

    displaySchemaInfo(dbInfo) {
        const schemaContainer = document.getElementById('schema-info-container');
        if (!schemaContainer) return;

        let html = '<div class="schema-info">';
        html += `<h4>📊 Database: ${dbInfo.db_name}</h4>`;
        html += `<p><strong>Tables:</strong> ${dbInfo.table_count}</p>`;
        html += `<p><strong>Embedding Status:</strong> ${dbInfo.embedding_status}</p>`;
        
        if (dbInfo.tables && dbInfo.tables.length > 0) {
            html += '<div class="table-list">';
            html += '<strong>Available Tables:</strong><ul>';
            dbInfo.tables.forEach(table => {
                html += `<li>${table}</li>`;
            });
            html += '</ul></div>';
        }
        
        html += '</div>';
        schemaContainer.innerHTML = html;
    }

    enableQueryInterface() {
        const queryForm = document.getElementById('query-form');
        const queryButton = document.getElementById('execute-query-btn');
        
        if (queryForm) {
            queryForm.style.opacity = '1';
            queryForm.style.pointerEvents = 'auto';
        }
        
        if (queryButton) {
            queryButton.disabled = false;
            queryButton.textContent = 'Ask Question';
        }
    }

    disableQueryInterface() {
        const queryForm = document.getElementById('query-form');
        const queryButton = document.getElementById('execute-query-btn');
        
        if (queryForm) {
            queryForm.style.opacity = '0.5';
            queryForm.style.pointerEvents = 'none';
        }
        
        if (queryButton) {
            queryButton.disabled = true;
            queryButton.textContent = 'Connect Database First';
        }
    }

    getCurrentDatabase() {
        return this.currentDatabase;
    }

    getDatabaseInfo(dbUri) {
        return this.databaseCache.get(dbUri);
    }
}

// Export for use in main app
window.EnhancedDatabaseManager = EnhancedDatabaseManager;
