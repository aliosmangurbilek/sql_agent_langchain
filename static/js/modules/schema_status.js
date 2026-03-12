// schema_status.js
// Handles schema status banner: status fetch, check, rebuild, UI updates.

export function initSchemaStatus({ getTargetPayload, hasResolvableDbTarget, watchElements = [] }) {
  const schemaBanner = document.getElementById('schema-banner');
  const schemaBannerText = document.getElementById('schema-banner-text');
  const checkBtn = document.getElementById('btn-check-schema');
  const rebuildBtn = document.getElementById('btn-rebuild-embeddings');

  if (!schemaBanner || !schemaBannerText || !checkBtn || !rebuildBtn) return;

  function hideSchemaBanner() { schemaBanner.classList.add('hidden'); }
  function showSchemaBanner() { schemaBanner.classList.remove('hidden'); }

  async function getErrorMessage(response, fallback) {
    try {
      const payload = await response.json();
      if (payload?.error) return payload.error;
      if (payload?.message) return payload.message;
    } catch (_) {
      // ignore JSON parse failures and fall back to text.
    }
    try {
      const text = await response.text();
      if (text) return text;
    } catch (_) {
      // ignore body read failures
    }
    return fallback;
  }

  function buildStatusUrl() {
    const target = getTargetPayload();
    const params = new URLSearchParams();
    if (target.db_uri) params.set('db_uri', target.db_uri);
    else if (target.database) params.set('database', target.database);
    const query = params.toString();
    return query ? `/api/admin/embeddings/status?${query}` : '/api/admin/embeddings/status';
  }

  async function fetchSchemaStatus() {
    const res = await fetch(buildStatusUrl());
    if (!res.ok) {
      throw new Error(await getErrorMessage(res, `Status HTTP ${res.status}`));
    }
    return res.json();
  }

  async function postCheck() {
    const res = await fetch('/api/admin/embeddings/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(getTargetPayload())
    });
    if (!res.ok) {
      throw new Error(await getErrorMessage(res, `Check HTTP ${res.status}`));
    }
    return res.json();
  }

  async function postRebuild() {
    const res = await fetch('/api/admin/embeddings/rebuild', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(getTargetPayload())
    });
    if (!res.ok) {
      throw new Error(await getErrorMessage(res, `Rebuild HTTP ${res.status}`));
    }
    return res.json();
  }

  function showSchemaError(message) {
    showSchemaBanner();
    schemaBanner.classList.remove('ok', 'readonly');
    schemaBanner.classList.add('danger');
    schemaBannerText.textContent = message || 'Schema status unavailable.';
    checkBtn.disabled = !hasResolvableDbTarget();
    rebuildBtn.disabled = true;
  }

  function updateSchemaBanner(status) {
    showSchemaBanner();
    const readOnly = status.meta_writable === false || status.reason === 'permission_denied_meta_table';
    const needs = !!status.needs_rebuild;
    const reason = status.reason || (needs ? 'pending' : 'ok');
    schemaBanner.classList.remove('ok','danger','readonly');
    if (readOnly) {
      schemaBanner.classList.add('readonly');
      schemaBannerText.textContent = 'Read-only mode: embeddings disabled; agent will scan full schema (may be slower).';
      // In read-only mode, rebuilding is not possible.
      rebuildBtn.disabled = true;
    } else if (!needs) {
      schemaBanner.classList.add('ok');
      schemaBannerText.textContent = `Schema OK (signature ${status.signature_head || '—'})`;
      // Allow user-triggered rebuild even when not strictly required.
      rebuildBtn.disabled = !hasResolvableDbTarget();
    } else {
      schemaBanner.classList.add('danger');
      schemaBannerText.textContent = reason === 'pending_rebuild_schema_changed'
        ? `Schema changed – rebuild required (stored ${status.signature_head || '—'} vs live ${status.live_signature_head || '—'})`
        : `Rebuild required (reason: ${reason})`;
      rebuildBtn.disabled = !hasResolvableDbTarget();
    }
    checkBtn.disabled = !hasResolvableDbTarget();
  }

  let pollingTimer = null;

  async function refreshSchemaStatus(silent = true) {
    if (!hasResolvableDbTarget()) { hideSchemaBanner(); if (pollingTimer) { clearInterval(pollingTimer); pollingTimer = null; } return; }
    try {
      const st = await fetchSchemaStatus();
      updateSchemaBanner(st);
    } catch (e) {
      showSchemaError(e?.message || 'Schema status unavailable.');
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
    if (!hasResolvableDbTarget()) return;
    checkBtn.disabled = true;
    const original = checkBtn.textContent;
    checkBtn.textContent = 'Checking…';
    try {
      await postCheck();
    } catch (e) {
      console.error(e);
      showSchemaError(e?.message || 'Schema check failed.');
    }
    checkBtn.textContent = original;
    checkBtn.disabled = false;
    refreshSchemaStatus();
  });

  rebuildBtn.addEventListener('click', async () => {
    if (!hasResolvableDbTarget()) return;
    rebuildBtn.disabled = true;
    const original = rebuildBtn.textContent;
    rebuildBtn.textContent = 'Rebuilding…';
    try {
      await postRebuild();
    } catch (e) {
      console.error(e);
      showSchemaError(e?.message || 'Embedding rebuild failed.');
    }
    rebuildBtn.textContent = original;
    refreshSchemaStatus();
  });

  watchElements.forEach(element => {
    element?.addEventListener('change', () => { refreshSchemaStatus(false); startAutoPolling(); });
  });

  if (hasResolvableDbTarget()) { refreshSchemaStatus(false); startAutoPolling(); }

  return { refreshSchemaStatus, startAutoPolling };
}
