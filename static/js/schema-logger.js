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
        
        // Start monitoring via SSE
        this.schemaMonitoring = true;
        this.connectEventSource();
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

    connectEventSource() {
        if (!this.schemaMonitoring) return;

        this.schemaEventSource = new EventSource('/api/worker/schema_events');

        this.schemaEventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const extra = data.command ? data.command.toLowerCase().replace(' ', '-') : data.type || '';
                const message = data.message || `${data.command}: ${data.schema}.${data.table}`;
                this.addSchemaLogEntry('info', message, extra);
            } catch (err) {
                this.addSchemaLogEntry('error', `Invalid event data: ${event.data}`);
            }
        };

        this.schemaEventSource.onerror = () => {
            this.addSchemaLogEntry('error', 'Connection lost. Reconnecting...');
            this.schemaEventSource.close();
            if (this.schemaMonitoring) {
                setTimeout(() => this.connectEventSource(), 3000);
            }
        };
    }

    // Method to be called from external modules
    logDatabaseSwitch(dbName) {
        this.addSchemaLogEntry('info', `Database switched to: ${dbName}`);
    }
}

// Export for use in main app
window.SchemaLogger = SchemaLogger;
