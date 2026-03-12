// databases.js - Database selection helpers for the frontend

function fallbackLabel(name) {
  return (name || '').replaceAll('_', ' ').replace(/\b\w/g, ch => ch.toUpperCase());
}

export async function fetchDatabases() {
  const response = await fetch('/api/databases');
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.error || 'Failed to load databases');
  }
  return data;
}

export function populateDatabaseSelect(selectEl, payload) {
  const databases = Array.isArray(payload?.databases) ? payload.databases : [];
  const defaultDatabase = payload?.default_database || '';

  selectEl.innerHTML = '';

  if (!databases.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'No databases configured';
    selectEl.appendChild(option);
    selectEl.disabled = true;
    localStorage.removeItem('selectedDatabase');
    return null;
  }

  databases.forEach(database => {
    const option = document.createElement('option');
    option.value = database.name;
    option.textContent = database.label || fallbackLabel(database.name);
    selectEl.appendChild(option);
  });

  selectEl.disabled = false;

  const savedDatabase = localStorage.getItem('selectedDatabase');
  const available = new Set(databases.map(db => db.name));
  if (savedDatabase && available.has(savedDatabase)) {
    selectEl.value = savedDatabase;
  } else if (defaultDatabase && available.has(defaultDatabase)) {
    selectEl.value = defaultDatabase;
  } else {
    selectEl.value = databases[0].name;
  }

  if (selectEl.value) {
    localStorage.setItem('selectedDatabase', selectEl.value);
  }

  return selectEl.value || null;
}

export async function loadDatabasesInto(selectEl) {
  const payload = await fetchDatabases();
  const selectedDatabase = populateDatabaseSelect(selectEl, payload);
  return { ...payload, selectedDatabase };
}
