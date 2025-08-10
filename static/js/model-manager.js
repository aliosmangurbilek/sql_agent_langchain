// Model Management Module
// Handles OpenRouter model loading and selection

class ModelManager {
    constructor() {
        this.modelSelect = document.getElementById('model-select');
        this.refreshBtn = document.getElementById('refresh-models-btn');
        
        console.log('🔧 ModelManager initialized:', {
            modelSelect: !!this.modelSelect,
            refreshBtn: !!this.refreshBtn
        });
        
        this.setupEventListeners();
    }

    setupEventListeners() {
        if (this.refreshBtn) {
            this.refreshBtn.addEventListener('click', () => this.loadModels());
        }
    }

    async loadModels() {
        if (!this.modelSelect || !this.refreshBtn) {
            console.warn('Model elements not found');
            return;
        }

        console.log('🔄 Loading models from API...');

        // Disable during loading
        this.modelSelect.disabled = true;
        this.refreshBtn.disabled = true;
        this.modelSelect.innerHTML = '<option value="">Loading models...</option>';
        
        try {
            const response = await fetch('/api/models');
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const result = await response.json();
            console.log('📡 API Response:', result);
            
            // Check if we have models array (direct or nested in result)
            let models = null;
            if (result.models && Array.isArray(result.models)) {
                models = result.models;
            } else if (result.status === 'success' && result.models) {
                models = result.models;
            } else if (Array.isArray(result)) {
                models = result;
            }
            
            if (models && models.length > 0) {
                this.populateModelSelect(models);
                console.log(`✅ Models loaded successfully (${models.length} models)`);
            } else {
                throw new Error('No models found in response');
            }
        } catch (error) {
            this.modelSelect.innerHTML = '<option value="">Error loading models</option>';
            console.error('❌ Error loading models:', error);
            
            // Show fallback models
            this.populateFallbackModels();
        } finally {
            this.modelSelect.disabled = false;
            this.refreshBtn.disabled = false;
        }
    }

    populateFallbackModels() {
        console.log('🔄 Loading fallback models...');
        const fallbackModels = [
            {
                id: 'deepseek/deepseek-chat',
                name: 'DeepSeek Chat',
                is_free: true,
                pricing: { prompt: '0.000000', completion: '0.000000', total: '0.000000' }
            },
            {
                id: 'meta-llama/llama-3.1-8b-instruct:free',
                name: 'Llama 3.1 8B',
                is_free: true,
                pricing: { prompt: '0.000000', completion: '0.000000', total: '0.000000' }
            }
        ];
        this.populateModelSelect(fallbackModels);
    }

    populateModelSelect(models) {
        console.log('🔄 Populating model select with:', models.length, 'models');
        this.modelSelect.innerHTML = '';
        
        // Add default option
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = 'Select a model...';
        this.modelSelect.appendChild(defaultOption);
        
        // Group models by type
        const freeModels = models.filter(m => m.is_free);
        const collator = new Intl.Collator(undefined, { sensitivity: 'base' });
        freeModels.sort((a,b)=>collator.compare((a.name||a.id||'').toLowerCase(), (b.name||b.id||'').toLowerCase()));
        const paidModels = models.filter(m => !m.is_free);
        paidModels.sort((a,b)=>collator.compare((a.name||a.id||'').toLowerCase(), (b.name||b.id||'').toLowerCase()));

        console.log(`📊 Found ${freeModels.length} free models, ${paidModels.length} paid models`);

        // Add free models first
        if (freeModels.length > 0) {
            const freeGroup = document.createElement('optgroup');
            freeGroup.label = '🆓 Free Models';
            freeModels.forEach(model => {
                const option = document.createElement('option');
                option.value = model.id;
                // Use provider info if available
                const providerText = model.provider ? ` (${model.provider})` : '';
                option.textContent = `${(model.name || model.id)}${providerText} - Free`;
                if (model.description) {
                    option.title = model.description;
                }
                freeGroup.appendChild(option);
            });
            this.modelSelect.appendChild(freeGroup);
        }

        // Add paid models
        if (paidModels.length > 0) {
            const paidGroup = document.createElement('optgroup');
            paidGroup.label = '💰 Paid Models';
            paidModels.forEach(model => {
                const option = document.createElement('option');
                option.value = model.id;

                // Handle pricing display
                let pricingText = '';
                if (model.pricing && model.pricing.prompt) {
                    pricingText = ` ($${model.pricing.prompt}/1M tokens)`;
                } else if (model.total_price !== undefined) {
                    pricingText = ` ($${model.total_price.toFixed(6)}/1M tokens)`;
                }

                const providerText = model.provider ? ` (${model.provider})` : '';
                option.textContent = `${(model.name || model.id)}${providerText}${pricingText}`;
                if (model.description) {
                    option.title = model.description;
                }
                paidGroup.appendChild(option);
            });
            this.modelSelect.appendChild(paidGroup);
        }
        
        // Select default model (first free model or deepseek/deepseek-chat)
        const defaultModel = freeModels.find(m => m.id.includes('deepseek')) || 
                           freeModels.find(m => m.id.includes('horizon')) ||
                           freeModels[0];
        if (defaultModel) {
            this.modelSelect.value = defaultModel.id;
            console.log('🎯 Selected default model:', defaultModel.name);
        }
    }

    getSelectedModel() {
        return this.modelSelect ? this.modelSelect.value : null;
    }
}