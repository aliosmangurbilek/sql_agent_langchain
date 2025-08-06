// Schema Log Management Module
// Handles real-time schema change logging and monitoring

class SchemaLogger {
    constructor() {
        this.schemaLogContainer = document.getElementById('schema-log-container');
        this.clearSchemaLogBtn = document.getElementById('clear-schema-log');
        this.toggleSchemaMonitoringBtn = document.getElementById('toggle-schema-monitoring');
        
        this.schemaMonitoring = false;
        this.schemaEventSource = null;
        
        this.setupEventListeners();
    }

    setupEventListeners() {
        this.clearSchemaLogBtn.addEventListener('click', () => this.clearSchemaLog());
        this.toggleSchemaMonitoringBtn.addEventListener('click', () => this.toggleSchemaMonitoring());
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
        
        this.addSchemaLogEntry('info', 'Schema monitoring started');
        
        // Start monitoring
        this.schemaMonitoring = true;
        this.simulateSchemaMonitoring();
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

    simulateSchemaMonitoring() {
        // This is a simulation - in real implementation, you'd connect to actual schema change events
        // For demonstration purposes only
        if (!this.schemaMonitoring) return;
        
        // Simulate random schema events for demo
        setTimeout(() => {
            if (this.schemaMonitoring && Math.random() > 0.7) {
                const actions = [
                    { type: 'schema-change', message: '🔄 Table "users" created in schema "public"' },
                    { type: 'embedding-refresh', message: '✅ Embeddings refreshed for "public.users" (5 vectors)' },
                    { type: 'table-drop', message: '🗑️ Table "temp_data" dropped from schema "public"' }
                ];
                
                const action = actions[Math.floor(Math.random() * actions.length)];
                this.addSchemaLogEntry('info', action.message, action.type);
            }
            
            this.simulateSchemaMonitoring();
        }, 5000 + Math.random() * 10000); // Random interval between 5-15 seconds
    }

    // Method to be called from external modules
    logDatabaseSwitch(dbName) {
        this.addSchemaLogEntry('info', `Database switched to: ${dbName}`);
    }
}

// Export for use in main app
window.SchemaLogger = SchemaLogger;
