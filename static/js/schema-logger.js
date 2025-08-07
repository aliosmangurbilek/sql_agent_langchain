// Schema Log Management Module
// Handles real-time schema change logging and monitoring

class SchemaLogger {
    constructor() {
        this.schemaLogContainer = document.getElementById('schema-log-container');
        this.clearSchemaLogBtn = document.getElementById('clear-schema-log');
        this.toggleSchemaMonitoringBtn = document.getElementById('toggle-schema-monitoring');
        this.refreshEmbeddingsBtn = document.getElementById('refresh-embeddings');
        this.addCurrentDbListenerBtn = document.getElementById('add-current-db-listener');
        
        this.schemaMonitoring = false;
        this.schemaEventSource = null;
        
        this.setupEventListeners();
    }

    setupEventListeners() {
        this.clearSchemaLogBtn.addEventListener('click', () => this.clearSchemaLog());
        this.toggleSchemaMonitoringBtn.addEventListener('click', () => this.toggleSchemaMonitoring());
        this.refreshEmbeddingsBtn.addEventListener('click', () => this.refreshEmbeddings());
        this.addCurrentDbListenerBtn.addEventListener('click', () => this.addCurrentDatabaseListener());
    }

    addSchemaLogEntry(type, message, extraClass = '') {
        const timestamp = new Date().toLocaleTimeString();
        const logEntry = document.createElement('div');
        logEntry.className = `log-entry ${type} ${extraClass}`;
        
        logEntry.innerHTML = `
            <span class="timestamp">${timestamp}</span>
            <span class="message">${message}</span>
        `;
        
        this.schemaLogContainer.appendChild(logEntry);
        
        // Auto-scroll to bottom
        this.schemaLogContainer.scrollTop = this.schemaLogContainer.scrollHeight;
        
        // Limit log entries to prevent memory issues
        const entries = this.schemaLogContainer.querySelectorAll('.log-entry');
        if (entries.length > 100) {
            entries[0].remove();
        }
    }

    clearSchemaLog() {
        this.schemaLogContainer.innerHTML = `
            <div class="log-entry info">
                <span class="timestamp">Cleared</span>
                <span class="message">Schema log cleared</span>
            </div>
        `;
    }

    toggleSchemaMonitoring() {
        const isMonitoring = this.toggleSchemaMonitoringBtn.dataset.monitoring === 'true';
        
        if (isMonitoring) {
            this.stopSchemaMonitoring();
        } else {
            this.startSchemaMonitoring();
        }
    }

    startSchemaMonitoring() {
        this.toggleSchemaMonitoringBtn.textContent = 'Stop Monitoring';
        this.toggleSchemaMonitoringBtn.dataset.monitoring = 'true';
        this.toggleSchemaMonitoringBtn.className = 'btn btn-warning btn-sm';
        
        this.addSchemaLogEntry('info', 'Schema monitoring started - listening for real schema changes');
        
        // Start real monitoring (connect to actual schema change events)
        this.schemaMonitoring = true;
        this.connectToSchemaEvents();
    }

    stopSchemaMonitoring() {
        this.toggleSchemaMonitoringBtn.textContent = 'Start Monitoring';
        this.toggleSchemaMonitoringBtn.dataset.monitoring = 'false';
        this.toggleSchemaMonitoringBtn.className = 'btn btn-primary btn-sm';
        
        this.schemaMonitoring = false;
        if (this.schemaEventSource) {
            this.schemaEventSource.close();
            this.schemaEventSource = null;
        }
        
        this.addSchemaLogEntry('info', 'Schema monitoring stopped');
    }

    async refreshEmbeddings() {
        try {
            this.refreshEmbeddingsBtn.disabled = true;
            this.refreshEmbeddingsBtn.textContent = '🔄 Refreshing...';
            
            this.addSchemaLogEntry('info', 'Starting manual embedding refresh...');
            
            const response = await fetch('/api/worker/refresh_embeddings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({}) // Empty body to refresh all embeddings
            });

            const data = await response.json();
            
            if (response.ok && data.status === 'success') {
                const result = data.data;
                this.addSchemaLogEntry('success', 
                    `✅ Embeddings refreshed successfully: ${result.tables_processed} tables, ${result.total_vectors} vectors (${result.target})`, 
                    'embedding-refresh'
                );
            } else {
                throw new Error(data.message || 'Unknown error');
            }
            
        } catch (error) {
            this.addSchemaLogEntry('error', `❌ Failed to refresh embeddings: ${error.message}`);
            console.error('Embedding refresh error:', error);
        } finally {
            this.refreshEmbeddingsBtn.disabled = false;
            this.refreshEmbeddingsBtn.textContent = '🔄 Refresh Embeddings';
        }
    }

    async addCurrentDatabaseListener() {
        try {
            this.addCurrentDbListenerBtn.disabled = true;
            this.addCurrentDbListenerBtn.textContent = '📡 Adding...';
            
            // Get current active database from worker status
            const statusResponse = await fetch('/api/worker/status');
            const statusData = await statusResponse.json();
            
            if (!statusResponse.ok || !statusData.worker_online) {
                throw new Error('Worker is offline');
            }
            
            const activeDb = statusData.data.active_db;
            if (!activeDb || activeDb === 'default') {
                throw new Error('No active database set. Please switch to a database first.');
            }
            
            this.addSchemaLogEntry('info', `Adding database listener for: ${activeDb}`);
            
            const response = await fetch('/api/worker/add_database_listener', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ database: activeDb })
            });

            const data = await response.json();
            
            if (response.ok && data.status === 'success') {
                const result = data.data;
                this.addSchemaLogEntry('success', 
                    `✅ Database listener added: ${result.database}. Active listeners: ${result.active_listeners.join(', ')}`, 
                    'embedding-refresh'
                );
            } else {
                throw new Error(data.message || 'Unknown error');
            }
            
        } catch (error) {
            this.addSchemaLogEntry('error', `❌ Failed to add database listener: ${error.message}`);
            console.error('Database listener error:', error);
        } finally {
            this.addCurrentDbListenerBtn.disabled = false;
            this.addCurrentDbListenerBtn.textContent = '📡 Monitor Current DB';
        }
    }

    connectToSchemaEvents() {
        if (!this.schemaMonitoring) return;
        
        try {
            // Connect to real-time schema change events via Server-Sent Events
            this.addSchemaLogEntry('info', 'Connecting to schema events...');
            this.schemaEventSource = new EventSource('/api/worker/schema_events');
            
            this.schemaEventSource.onopen = (event) => {
                this.addSchemaLogEntry('success', 'Schema monitoring connected successfully!');
                console.log('SSE connection opened:', event);
            };
            
            this.schemaEventSource.onmessage = (event) => {
                try {
                    console.log('SSE message received:', event.data);
                    const data = JSON.parse(event.data);
                    
                    if (data.type === 'connected') {
                        this.addSchemaLogEntry('success', data.message, 'connection');
                    } else if (data.type === 'schema_change') {
                        this.addSchemaLogEntry('warning', `🔄 ${data.message}`, 'schema-change');
                    } else if (data.type === 'embedding_refresh') {
                        this.addSchemaLogEntry('success', data.message, 'embedding-refresh');
                    } else if (data.type === 'table_drop') {
                        this.addSchemaLogEntry('error', `🗑️ ${data.message}`, 'table-drop');
                    } else if (data.type === 'heartbeat') {
                        // Don't show heartbeats in UI, just console
                        console.log('Heartbeat received');
                    } else {
                        this.addSchemaLogEntry('info', `📡 ${data.message || JSON.stringify(data)}`, 'debug');
                    }
                } catch (e) {
                    console.warn('Failed to parse schema event:', e);
                    this.addSchemaLogEntry('error', `Failed to parse event: ${e.message}`);
                }
            };
            
            this.schemaEventSource.onerror = (error) => {
                console.error('Schema monitoring connection error:', error);
                this.addSchemaLogEntry('error', 'Schema monitoring connection lost - retrying...');
                
                // Auto-reconnect after 5 seconds
                setTimeout(() => {
                    if (this.schemaMonitoring && (!this.schemaEventSource || this.schemaEventSource.readyState === EventSource.CLOSED)) {
                        this.addSchemaLogEntry('info', 'Attempting to reconnect...');
                        this.connectToSchemaEvents();
                    }
                }, 5000);
            };
            
        } catch (error) {
            console.error('Failed to connect to schema events:', error);
            this.addSchemaLogEntry('error', `Failed to connect to schema monitoring: ${error.message}`);
        }
    }

    // Method to be called from external modules
    logDatabaseSwitch(dbName) {
        this.addSchemaLogEntry('info', `Database switched to: ${dbName}`);
    }
}

// Export for use in main app
window.SchemaLogger = SchemaLogger;
