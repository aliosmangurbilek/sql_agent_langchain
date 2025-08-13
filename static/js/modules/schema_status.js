// schema_status.js
// Handles schema status banner: status fetch, check, rebuild, UI updates.

export function initSchemaStatus(dbUriInput) {
  const schemaBanner = document.getElementById('schema-banner');
  const schemaBannerText = document.getElementById('schema-banner-text');
  const checkBtn = document.getElementById('btn-check-schema');
  const rebuildBtn = document.getElementById('btn-rebuild-embeddings');

  if (!schemaBanner || !schemaBannerText || !checkBtn || !rebuildBtn) return;

  function hideSchemaBanner() { schemaBanner.classList.add('hidden'); }
  function showSchemaBanner() { schemaBanner.classList.remove('hidden'); }

  async function fetchSchemaStatus(dbUri) {
    const url = `/api/admin/embeddings/status?db_uri=${encodeURIComponent(dbUri)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Status HTTP ${res.status}`);
    return res.json();
  }

  async function postCheck(dbUri) {
    const res = await fetch('/api/admin/embeddings/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ db_uri: dbUri })
    });
    if (!res.ok) throw new Error(`Check HTTP ${res.status}`);
    return res.json();
  }

  async function postRebuild(dbUri) {
    const res = await fetch('/api/admin/embeddings/rebuild', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ db_uri: dbUri })
    });
    if (!res.ok) throw new Error(`Rebuild HTTP ${res.status}`);
    return res.json();
  }

  function updateSchemaBanner(status) {
    showSchemaBanner();
    const needs = !!status.needs_rebuild;
    const reason = status.reason || (needs ? 'pending' : 'ok');
    schemaBanner.classList.remove('ok','danger');
    if (!needs) {
      schemaBanner.classList.add('ok');
      schemaBannerText.textContent = `Schema OK (signature ${status.signature_head || '—'})`;
      rebuildBtn.disabled = true;
    } else {
      schemaBanner.classList.add('danger');
      schemaBannerText.textContent = reason === 'pending_rebuild_schema_changed'
        ? `Schema changed – rebuild required (stored ${status.signature_head || '—'} vs live ${status.live_signature_head || '—'})`
        : `Rebuild required (reason: ${reason})`;
      rebuildBtn.disabled = false;
    }
    checkBtn.disabled = !dbUriInput.value.trim();
  }

  let pollingTimer = null;

  async function refreshSchemaStatus(silent = true) {
    const dbUri = dbUriInput.value.trim();
    if (!dbUri) { hideSchemaBanner(); if (pollingTimer) { clearInterval(pollingTimer); pollingTimer=null; } return; }
    try {
      const st = await fetchSchemaStatus(dbUri);
      updateSchemaBanner(st);
    } catch (e) {
      if (!silent) console.warn('Schema status error:', e);
    }
  }

  function startAutoPolling() {
    if (pollingTimer) clearInterval(pollingTimer);
    pollingTimer = setInterval(() => {
      // Lightweight status poll (live signature already computed inside)
      refreshSchemaStatus(true);
    }, 10000); // 10s
  }

  checkBtn.addEventListener('click', async () => {
    const dbUri = dbUriInput.value.trim();
    if (!dbUri) return;
    checkBtn.disabled = true;
    const original = checkBtn.textContent;
    checkBtn.textContent = 'Checking…';
    try { await postCheck(dbUri); } catch (e) { console.error(e); }
    checkBtn.textContent = original;
    checkBtn.disabled = false;
    refreshSchemaStatus();
  });

  rebuildBtn.addEventListener('click', async () => {
    const dbUri = dbUriInput.value.trim();
    if (!dbUri) return;
    rebuildBtn.disabled = true;
    const original = rebuildBtn.textContent;
    rebuildBtn.textContent = 'Rebuilding…';
    try { await postRebuild(dbUri); } catch (e) { console.error(e); }
    rebuildBtn.textContent = original;
    refreshSchemaStatus();
  });

  dbUriInput.addEventListener('change', () => { refreshSchemaStatus(false); startAutoPolling(); });

  if (dbUriInput.value.trim()) { refreshSchemaStatus(false); startAutoPolling(); }

  return { refreshSchemaStatus, startAutoPolling };
}
