// UI Utilities Module
// Common UI helper functions and utilities

class UIUtils {
    static showMessage(message, type = 'info', duration = 3000) {
        const errorDiv = document.getElementById('error');
        if (errorDiv) {
            errorDiv.className = `error ${type}`;
            errorDiv.textContent = message;
            errorDiv.classList.remove('hidden');
            
            setTimeout(() => {
                errorDiv.classList.add('hidden');
            }, duration);
        }
    }

    static showError(message, duration = 5000) {
        this.showMessage(message, 'error', duration);
    }

    static showSuccess(message, duration = 3000) {
        this.showMessage(message, 'success', duration);
    }

    static showLoading(show = true) {
        const loadingDiv = document.getElementById('loading');
        if (loadingDiv) {
            if (show) {
                loadingDiv.classList.remove('hidden');
            } else {
                loadingDiv.classList.add('hidden');
            }
        }
    }

    static switchTab(tabName) {
        // Hide all tab panes
        document.querySelectorAll('.tab-pane').forEach(pane => {
            pane.classList.remove('active');
        });
        
        // Remove active class from all tab buttons
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        
        // Show selected tab pane
        const selectedPane = document.getElementById(`${tabName}-tab`);
        if (selectedPane) {
            selectedPane.classList.add('active');
        }
        
        // Add active class to selected tab button
        const selectedBtn = document.querySelector(`[data-tab="${tabName}"]`);
        if (selectedBtn) {
            selectedBtn.classList.add('active');
        }
    }

    static setTheme(mode) {
        const themeToggle = document.getElementById('theme-toggle');
        
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
        
        localStorage.setItem('theme', mode);
    }

    static toggleTheme() {
        const isDark = document.body.classList.contains('dark-mode');
        this.setTheme(isDark ? 'light' : 'dark');
    }

    static validateDatabaseUri(uri) {
        if (!uri) return false;
        
        // Basic validation for database URI formats
        const patterns = [
            /^postgresql:\/\//,
            /^mysql:\/\//,
            /^sqlite:\/\//,
            /^oracle:\/\//,
            /^mssql:\/\//
        ];
        
        return patterns.some(pattern => pattern.test(uri));
    }

    static formatTimestamp(date = new Date()) {
        return date.toLocaleString('tr-TR', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }

    static debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    static truncateText(text, maxLength = 50) {
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }
}

// Export for use in main app
window.UIUtils = UIUtils;
