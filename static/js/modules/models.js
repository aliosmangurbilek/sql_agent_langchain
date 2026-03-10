// models.js - Model-related UI logic isolated from base app.js

export async function fetchModels() {
  const response = await fetch('/api/models');
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.error || 'Failed to load models');
  }
  return data.models || [];
}

export function populateModelSelect(selectEl, models) {
  // Clear
  selectEl.innerHTML = '';

  // Default option
  const defaultOption = document.createElement('option');
  defaultOption.value = '';
  defaultOption.textContent = 'Select a model...';
  selectEl.appendChild(defaultOption);

  const freeModels = models.filter(m => m.is_free);
  const paidModels = models.filter(m => !m.is_free);

  if (freeModels.length > 0) {
    const freeGroup = document.createElement('optgroup');
    freeGroup.label = '🆓 Free Models';
    freeModels.forEach(model => {
      const option = document.createElement('option');
      option.value = model.id;
      const provider = model.provider ? ` (${model.provider})` : '';
      option.textContent = `${model.name}${provider}`;
      freeGroup.appendChild(option);
    });
    selectEl.appendChild(freeGroup);
  }

  if (paidModels.length > 0) {
    const paidGroup = document.createElement('optgroup');
    paidGroup.label = '💰 Paid Models';
    paidModels.forEach(model => {
      const option = document.createElement('option');
      option.value = model.id;
      const provider = model.provider ? ` (${model.provider})` : '';
      option.textContent = `${model.name}${provider}`;
      paidGroup.appendChild(option);
    });
    selectEl.appendChild(paidGroup);
  }

  // Enable and restore selection
  selectEl.disabled = false;
  const savedModel = localStorage.getItem('selectedModel');
  if (savedModel && Array.from(selectEl.options).some(o => o.value === savedModel)) {
    selectEl.value = savedModel;
  } else if (freeModels.length > 0) {
    selectEl.value = freeModels[0].id;
  }
}

export async function loadModelsInto(selectEl) {
  try {
    const models = await fetchModels();
    populateModelSelect(selectEl, models);
  } catch (error) {
    console.error('Error loading models:', error);
    populateModelSelect(selectEl, [
      { id: 'deepseek/deepseek-chat', name: 'DeepSeek Chat (Free)', is_free: true, provider: 'deepseek' },
      { id: 'meta-llama/llama-3.1-8b-instruct:free', name: 'Llama 3.1 8B (Free)', is_free: true, provider: 'meta-llama' },
      { id: 'qwen/qwen-2.5-7b-instruct:free', name: 'Qwen 2.5 7B (Free)', is_free: true, provider: 'qwen' }
    ]);
  }
}
