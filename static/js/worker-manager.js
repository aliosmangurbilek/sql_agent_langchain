// Worker Status Management Module
// Handles schema worker status monitoring and database management

class WorkerManager {
    constructor() {
        this.workerStatus = document.getElementById('worker-status');
        this.workerStatusText = document.getElementById('worker-status-text');
        this.activeDbName = document.getElementById('active-db-name');
        this.cachedDbCount = document.getElementById('cached-db-count');
        this.cachedDbList = document.getElementById('cached-db-list');
        
        // Initialize periodic status checks
        this.startStatusChecking();
    }

    startStatusChecking() {
        this.checkWorkerStatus();
        setInterval(() => this.checkWorkerStatus(), 30000); // Check every 30 seconds
    }

    async checkWorkerStatus() {
        try {
            const response = await fetch('/api/worker/status');
            const data = await response.json();
            
            if (response.ok && data.worker_online) {
                this.updateWorkerStatus(true, data.data);
            } else {
                this.updateWorkerStatus(false);
            }
        } catch (error) {
            this.updateWorkerStatus(false);
        }
    }

    updateWorkerStatus(isOnline, data = null) {
        if (isOnline && data) {
            this.workerStatus.className = 'status-indicator online';
            this.workerStatusText.textContent = 'Online';
            this.activeDbName.textContent = data.active_db || 'None';
            this.cachedDbCount.textContent = data.cached_connections.length;
            
            // Update cached database list
            if (data.cached_connections.length > 0) {
                this.cachedDbList.innerHTML = data.cached_connections
                    .map(db => `<span class="cached-db-item">${db}</span>`)
                    .join('');
            } else {
                this.cachedDbList.textContent = 'No cached connections';
            }
        } else {
            this.workerStatus.className = 'status-indicator offline';
            this.workerStatusText.textContent = 'Offline';
            this.activeDbName.textContent = 'N/A';
            this.cachedDbCount.textContent = '0';
            this.cachedDbList.textContent = 'Worker offline';
        }
    }

    async switchActiveDatabase(dbName) {
        if (!dbName.trim()) {
            throw new Error('Please enter a database name');
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
                // Refresh status after successful switch
                await this.checkWorkerStatus();
                return { success: true, activeDb: data.data.active_db };
            } else {
                throw new Error(data.message || 'Unknown error');
            }
        } catch (error) {
            throw new Error(`Network error: ${error.message}`);
        }
    }

    saveBaseUri(baseUri) {
        if (!baseUri.trim()) {
            throw new Error('Please enter a base database URL');
        }
        
        localStorage.setItem('baseDbUri', baseUri);
        return 'Base database URL saved successfully';
    }
}

// Export for use in main app
window.WorkerManager = WorkerManager;
