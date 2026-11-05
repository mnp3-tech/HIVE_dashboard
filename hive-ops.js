/* HIVE chat outbox + approvals logic (P0.3). Pure, injectable, Node-testable.
   Rules: SENT only after a real provider response; no connector => NOT_CONNECTED (never SENT);
   no provider reply is ever fabricated; approvals act at the source only if a connector supports it,
   otherwise the decision is local and says so. */
(function (root) {
  'use strict';
  const MAX_TEXT = 4000, MAX_FILES = 10, MAX_FILE_BYTES = 50 * 1024 * 1024;
  const STATES = ['QUEUED', 'SENT', 'FAILED', 'NOT_CONNECTED'];

  function sanitizeFileName(name) {
    const base = String(name == null ? '' : name).split(/[\\/]/).pop().replace(/[\u0000-\u001f\u007f<>:"|?*]/g, '').trim();
    return (base || 'file').slice(0, 80);
  }
  /* Attachment metadata only: contents are never read or uploaded here. */
  function describeFiles(files, existing) {
    const out = (existing || []).slice(); const rejected = [];
    for (const f of Array.from(files || [])) {
      const name = sanitizeFileName(f && f.name); const size = Number(f && f.size) || 0;
      if (out.length >= MAX_FILES) { rejected.push({ name, reason: `limit of ${MAX_FILES} files` }); continue; }
      if (size > MAX_FILE_BYTES) { rejected.push({ name, reason: 'larger than 50 MB' }); continue; }
      if (out.some(x => x.name === name && x.size === size)) { rejected.push({ name, reason: 'already attached' }); continue; }
      out.push({ id: 'f' + out.length + '-' + name.length + '-' + size, name, size, type: String((f && f.type) || '').slice(0, 60) || null });
    }
    return { attachments: out, rejected };
  }
  const withTimeout = (p, ms) => Promise.race([p, new Promise((_r, rej) => setTimeout(() => rej(new Error('provider response timeout')), ms))]);

  /* connector: { connected(): {ok:boolean, reason?:string}, send({text, attachments}) -> Promise<{delivered:boolean, provider_response_id?:string, reason?:string}> } */
  const NO_CONNECTOR = { connected: () => ({ ok: false, reason: 'No provider connector is connected' }), send: async () => { throw new Error('not connected'); } };

  function createOutbox(cfg) {
    const c = Object.assign({ connector: NO_CONNECTOR, now: Date.now, timeoutMs: 15000, max: 50, onChange: null }, cfg);
    const messages = []; let seq = 0;
    const notify = () => c.onChange && c.onChange(messages.slice());
    async function attempt(m) {
      m.state = 'QUEUED'; m.reason = null; notify();
      let conn; try { conn = c.connector.connected(); } catch (e) { conn = { ok: false, reason: 'Connector check failed: ' + String(e && e.message || e).slice(0, 120) }; }
      if (!conn || conn.ok !== true) { m.state = 'NOT_CONNECTED'; m.reason = (conn && conn.reason) || 'No provider connector is connected'; m.updatedAt = c.now(); notify(); return m; }
      try {
        const res = await withTimeout(c.connector.send({ text: m.text, attachments: m.attachments.map(a => ({ name: a.name, size: a.size, type: a.type })) }), c.timeoutMs);
        if (res && res.delivered === true && Boolean(res.provider_response_id) && (typeof res.provider_response_id === 'string' || typeof res.provider_response_id === 'number')) { m.state = 'SENT'; m.providerResponseId = String(res.provider_response_id).slice(0, 80); m.reason = null; }
        else { m.state = 'FAILED'; m.reason = (res && res.reason) || 'Provider did not confirm delivery'; }
      } catch (e) { m.state = 'FAILED'; m.reason = String(e && e.message || e).slice(0, 160); }
      m.updatedAt = c.now(); notify(); return m;
    }
    return {
      async send(text, attachments) {
        const t = String(text == null ? '' : text).replace(/\r\n/g, '\n').trim();
        if (!t && !(attachments && attachments.length)) return { error: 'Nothing to send' };
        if (t.length > MAX_TEXT) return { error: `Message longer than ${MAX_TEXT} characters` };
        const m = { id: 'm' + (++seq), text: t, attachments: (attachments || []).slice(0, MAX_FILES), state: 'QUEUED', reason: null, createdAt: c.now(), updatedAt: c.now(), providerResponseId: null };
        messages.push(m); while (messages.length > c.max) messages.shift();
        await attempt(m); return { message: m };
      },
      async retry(id) { const m = messages.find(x => x.id === id); if (!m || (m.state !== 'FAILED' && m.state !== 'NOT_CONNECTED')) return null; return attempt(m); },
      list() { return messages.slice(); },
    };
  }

  /* ---- approvals ---- */
  const PROVIDERS = ['gpt', 'codex', 'claude'];
  function providerKey(ev) { const p = String(ev.provider || '').toLowerCase(); return PROVIDERS.find(k => p.includes(k)) || null; }
  /* Pending items come only from observed WAITING_APPROVAL events (latest state per task). */
  function pendingApprovals(events, now, windowMs) {
    const w = windowMs || 15 * 60 * 1000; const latest = new Map();
    (events || []).forEach(ev => {
      const p = providerKey(ev); const t = Date.parse(ev.timestamp || ''); if (!p || !Number.isFinite(t) || now - t > w) return;
      const key = p + ':' + (ev.task_id || ev.run_id || ev.correlation_id || ev.event_id);
      const prev = latest.get(key); if (!prev || t >= prev.t) latest.set(key, { t, ev, key, provider: p });
    });
    const out = { gpt: [], codex: [], claude: [] };
    latest.forEach(v => { if (v.ev.state === 'WAITING_APPROVAL') out[v.provider].push({ key: v.key + ':' + v.ev.event_id /* per request: a new request for the same task is a new decision */, provider: v.provider, summary: v.ev.redacted_summary || v.ev.event_type, at: v.ev.timestamp }); });
    return out;
  }
  const DECISIONS = { approve: 'APPROVED', reject: 'REJECTED' };
  /* connector: { supports(provider, action) -> bool, apply(provider, action, item) -> Promise<{ok:boolean, reason?}> } */
  const NO_APPROVAL_CONNECTOR = { supports: () => false, apply: async () => ({ ok: false }) };
  async function decide(item, action, connector) {
    const conn = connector || NO_APPROVAL_CONNECTOR;
    if (!DECISIONS[action]) throw new Error('unsupported action');
    let supported = false; try { supported = conn.supports(item.provider, action) === true; } catch (_e) { supported = false; }
    if (supported) {
      try { const r = await conn.apply(item.provider, action, item); if (r && r.ok === true) return { scope: 'source', decision: DECISIONS[action], label: (action === 'approve' ? 'Approved' : 'Rejected') + ' at source' }; return { scope: 'none', decision: null, label: 'Source did not confirm; nothing changed', reason: r && r.reason }; }
      catch (e) { return { scope: 'none', decision: null, label: 'Source call failed; nothing changed', reason: String(e && e.message || e) }; }
    }
    return { scope: 'local', decision: DECISIONS[action], label: (action === 'approve' ? 'Approved' : 'Rejected') + ' locally, source not updated' };
  }
  /* Edit is available only with a valid adapter/deep link; none exists yet. */
  function editAvailable(item, connector) { return Boolean(connector && connector.supports && connector.supports(item.provider, 'edit') && item.editUrl); }

  const api = { STATES, MAX_TEXT, MAX_FILES, sanitizeFileName, describeFiles, createOutbox, NO_CONNECTOR, pendingApprovals, decide, editAvailable, PROVIDERS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.HiveOps = api;
})(typeof window !== 'undefined' ? window : globalThis);
