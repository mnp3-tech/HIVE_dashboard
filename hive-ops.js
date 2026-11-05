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


  /* ---- P1.1 system resources / model limits view helpers (pure) ---- */
  const TRUSTED = ['valid', 'fixture'];
  const num = v => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  function formatBytes(n) {
    const v = num(n); if (v === null || v < 0) return null;
    const u = [['TB', 1e12], ['GB', 1e9], ['MB', 1e6], ['KB', 1e3]];
    for (const [name, size] of u) if (v >= size) { const x = v / size; return (x >= 100 ? Math.round(x) : Math.round(x * 100) / 100) + ' ' + name; }
    return Math.round(v) + ' B';
  }
  function formatCount(n) {
    const v = num(n); if (v === null || v < 0) return null;
    if (v >= 1e6) return (Math.round(v / 1e5) / 10) + 'M'; if (v >= 1e3) return (Math.round(v / 100) / 10) + 'K'; return String(Math.round(v));
  }
  const metricKnown = m => Boolean(m && TRUSTED.includes(m.validity) && num(m.value) !== null);
  /* OS value first; else HIVE Core's own host metric (percent only, valid only); else unknown. Never a default. */
  function pickMetric(osItem, coreMetric) {
    if (metricKnown(osItem)) return { metric: osItem, from: 'os' };
    if (coreMetric && coreMetric.validity === 'valid' && num(coreMetric.value) !== null && coreMetric.unit === '%') return { metric: coreMetric, from: 'hive-core' };
    return { metric: null, from: null, reason: (osItem && osItem.reason) || (coreMetric && coreMetric.reason) || 'not provided' };
  }
  function resourceViews(system, coreMetrics) {
    const items = (system && system.items) || {}; const cm = coreMetrics || {};
    const mk = (key, label, os, core, extra) => {
      const p = pickMetric(os, core); const v = p.metric ? num(p.metric.value) : null;
      const unit = p.metric && p.metric.unit;
      const view = { key, label, known: v !== null, value: v, unit: unit || null, pct: null, text: 'UNKNOWN', sub: null, from: p.from, title: p.metric ? `${p.from} · ${p.metric.source || 'source n/a'}` : (p.reason || 'not provided') };
      if (v !== null) {
        if (unit === '%') { if (v < 0 || v > 100) { view.known = false; view.text = 'UNKNOWN'; view.title = 'out-of-range value rejected'; return view; } view.pct = v; view.text = Math.round(v) + ' %'; }
        else if (unit === 'C') { if (v < -40 || v > 150) { view.known = false; view.text = 'UNKNOWN'; view.title = 'out-of-range value rejected'; return view; } view.pct = Math.max(0, Math.min(100, v)); view.text = Math.round(v) + ' °C'; }
        else { view.known = false; view.text = 'UNKNOWN'; view.title = 'unrecognised unit'; return view; }
        if (extra) view.sub = extra(p.metric);
      }
      return view;
    };
    return [
      mk('cpu', 'CPU', items.cpu, cm.cpu),
      mk('ram', 'RAM', items.memory, cm.memory, m => (formatBytes(m.used_bytes) && formatBytes(m.total_bytes) ? `${formatBytes(m.used_bytes)} / ${formatBytes(m.total_bytes)}` : null)),
      mk('disk', 'DISK', items.disk, cm.disk, m => (formatBytes(m.free_bytes) ? `${m.drive ? m.drive + ' ' : ''}${formatBytes(m.free_bytes)} free` : null)),
      mk('gpu', 'GPU', items.gpu, null, null),
      mk('temp', 'TEMP', items.temperature, null, null),
    ];
  }
  /* One-line USB/external summary. Phones (MTP/PTP) are never counted as disks. An empty list from a probe
     that did not return that list is UNKNOWN, never "0". */
  function deviceSummary(system) {
    if (!system || !system.items || system.error) return null;
    const it = system.items; const usbKnown = it.usb_known === true, disksKnown = it.disks_known === true;
    if (!usbKnown && !disksKnown) return null;
    const disks = disksKnown && Array.isArray(it.disks) ? it.disks : []; const usb = usbKnown && Array.isArray(it.usb) ? it.usb : [];
    const ext = disks.filter(d => d.kind === 'external' || d.kind === 'removable');
    const phones = usb.filter(u => u.kind === 'phone_mtp_ptp');
    const parts = [usbKnown ? `USB ${usb.length}` : 'USB UNKNOWN'];
    ext.forEach(d => { const f = d.validity !== 'unavailable' ? formatBytes(d.free_bytes) : null; const t = d.validity !== 'unavailable' ? formatBytes(d.total_bytes) : null; parts.push(`${d.id} ${t && f ? `${t}, ${f} free` : 'size unavailable'}`); }); // access mode (Read/Write) is shown in the System console list
    if (!disksKnown) parts.push('disks UNKNOWN');
    phones.forEach(p => parts.push(`${p.name}: ${p.protocol || 'MTP/PTP'} · Storage metrics unavailable`));
    return parts.join(' · ');
  }
  function devicesNodeText(system) {
    if (!system || !system.items || system.error) return 'UNKNOWN';
    const it = system.items; const usbKnown = it.usb_known === true, disksKnown = it.disks_known === true;
    if (!usbKnown && !disksKnown) return 'UNKNOWN';
    const ext = disksKnown && Array.isArray(it.disks) ? it.disks.filter(d => d.kind === 'external' || d.kind === 'removable').length : null;
    return `${usbKnown && Array.isArray(it.usb) ? it.usb.length + ' USB' : 'USB UNKNOWN'} · ${ext === null ? 'DISKS UNKNOWN' : ext + ' EXT DISK'}`;
  }
  /* Model-limit row. Only KNOWN (provider) and ESTIMATED carry numbers; everything else is a status word. */
  function limitView(item) {
    const base = { label: (item && item.label) || '?', status: 'UNKNOWN', tone: 'unknown', text: 'Limit: UNKNOWN', fill: null, dashed: false, title: (item && item.reason) || '' };
    if (!item || !['KNOWN', 'ESTIMATED', 'NOT_PROVIDED', 'UNKNOWN'].includes(item.status)) return base;
    if (item.status === 'NOT_PROVIDED') return Object.assign(base, { status: 'NOT_PROVIDED', text: 'Limit: NOT_PROVIDED' });
    if (item.status === 'UNKNOWN') return base;
    const limit = num(item.limit), avail = item.available === null || item.available === undefined ? null : num(item.available);
    if (limit === null || limit < 0 || (avail !== null && (avail < 0 || avail > limit))) return Object.assign(base, { title: 'malformed limit rejected' });
    const est = item.status === 'ESTIMATED';
    return { label: base.label, status: item.status, tone: est ? 'warn' : 'ok', dashed: est, title: base.title,
      text: `Limit ${est ? '~' : ''}${formatCount(limit)} · Avail ${avail === null ? 'n/a' : (est ? '~' : '') + formatCount(avail)} · ${item.status}`,
      fill: avail !== null && limit > 0 ? avail / limit : null };
  }
  const EMPTY_LIMITS = [['gpt', 'GPT'], ['claude', 'CLAUDE'], ['codex', 'CODEX'], ['local', 'LOCAL']].map(([provider, label]) => ({ provider, label, status: 'UNKNOWN', reason: 'No limit data received' }));

  const api = { formatBytes, formatCount, metricKnown, pickMetric, resourceViews, deviceSummary, devicesNodeText, limitView, EMPTY_LIMITS, STATES, MAX_TEXT, MAX_FILES, sanitizeFileName, describeFiles, createOutbox, NO_CONNECTOR, pendingApprovals, decide, editAvailable, PROVIDERS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.HiveOps = api;
})(typeof window !== 'undefined' ? window : globalThis);
