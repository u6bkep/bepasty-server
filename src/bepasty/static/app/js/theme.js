/**
 * Theme Management for bepasty
 * Handles dark/light mode detection, switching, and persistence
 */

class ThemeManager {
    constructor() {
        this.storageKey = 'bepasty-theme';
        this.themes = {
            LIGHT: 'light',
            DARK: 'dark'
        };
        
        this.init();
    }

    init() {
        // Set initial theme based on stored preference or system preference
        const savedTheme = this.getSavedTheme();
        const systemTheme = this.getSystemTheme();
        const initialTheme = savedTheme || systemTheme;
        
        this.setTheme(initialTheme);
        this.setupToggleButton();
        this.watchSystemThemeChanges();
        
        // Initialize Pygments theme on existing pages
        this.switchPygmentsTheme(initialTheme);
    }

    getSavedTheme() {
        return localStorage.getItem(this.storageKey);
    }

    getSystemTheme() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return this.themes.DARK;
        }
        return this.themes.LIGHT;
    }

    setTheme(theme) {
        const validTheme = Object.values(this.themes).includes(theme) ? theme : this.themes.LIGHT;
        
        document.documentElement.setAttribute('data-theme', validTheme);
        localStorage.setItem(this.storageKey, validTheme);
        
        this.updateToggleButton(validTheme);
        this.switchPygmentsTheme(validTheme);
        
        // Dispatch custom event for other components that might need to react
        window.dispatchEvent(new CustomEvent('themeChanged', { 
            detail: { theme: validTheme } 
        }));
    }

    switchPygmentsTheme(theme) {
        const lightStylesheet = document.getElementById('pygments-light');
        const darkStylesheet = document.getElementById('pygments-dark');
        
        if (lightStylesheet && darkStylesheet) {
            if (theme === this.themes.DARK) {
                lightStylesheet.disabled = true;
                darkStylesheet.disabled = false;
            } else {
                lightStylesheet.disabled = false;
                darkStylesheet.disabled = true;
            }
        }
    }

    getCurrentTheme() {
        return document.documentElement.getAttribute('data-theme') || this.themes.LIGHT;
    }

    toggleTheme() {
        const currentTheme = this.getCurrentTheme();
        const newTheme = currentTheme === this.themes.DARK ? this.themes.LIGHT : this.themes.DARK;
        this.setTheme(newTheme);
    }

    setupToggleButton() {
        const toggleButton = document.getElementById('theme-toggle');
        if (toggleButton) {
            toggleButton.addEventListener('click', () => this.toggleTheme());
            this.updateToggleButton(this.getCurrentTheme());
        }
    }

    updateToggleButton(theme) {
        const toggleButton = document.getElementById('theme-toggle');
        if (toggleButton) {
            const icon = toggleButton.querySelector('i');
            if (icon) {
                if (theme === this.themes.DARK) {
                    icon.className = 'fa fa-sun-o';
                    toggleButton.title = 'Switch to light mode';
                } else {
                    icon.className = 'fa fa-moon-o';
                    toggleButton.title = 'Switch to dark mode';
                }
            }
        }
    }

    watchSystemThemeChanges() {
        if (window.matchMedia) {
            const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
            
            // Only follow system changes if no manual preference is stored
            mediaQuery.addEventListener('change', (e) => {
                if (!this.getSavedTheme()) {
                    this.setTheme(e.matches ? this.themes.DARK : this.themes.LIGHT);
                }
            });
        }
    }

    // Method to reset to system preference
    resetToSystemTheme() {
        localStorage.removeItem(this.storageKey);
        const systemTheme = this.getSystemTheme();
        this.setTheme(systemTheme);
    }
}

// Initialize theme manager when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.themeManager = new ThemeManager();
});

// Also provide a global function for manual initialization if needed
window.initThemeManager = function() {
    if (!window.themeManager) {
        window.themeManager = new ThemeManager();
    }
};
