/* HIVE CORE logic (P0.2): event contract, freshness, CORE state, agent movement, transport.
   Classic script that also works under Node (module.exports) so it is unit-testable.
   Nothing here invents telemetry: no event -> no movement; no fresh telemetry -> UNKNOWN. */
(function (root) {
  'use strict';
  const STATES = ['IDLE', 'WORKING', 'WAITING_APPROVAL', 'REVIEW', 'FAILED', 'SECURITY_BLOCKED', 'OFFLINE', 'UNKNOWN'];
  const STATE_WORDS = {
    IDLE: ['idle', 'ready', 'completed', 'complete', 'done', 'succeeded', 'success', 'finished'],
    WORKING: ['working', 'running', 'active', 'in_progress', 'in-progress', 'started', 'executing', 'routed'],
    WAITING_APPROVAL: ['waiting_approval', 'waiting-approval', 'awaiting_approval', 'approval_required', 'waiting', 'pending_approval'],
    REVIEW: ['review', 'in_review', 'reviewing', 'review_blocked'],
    FAILED: ['failed', 'failure', 'error', 'errored', 'crashed'],
    SECURITY_BLOCKED: ['security_blocked', 'blocked_by_security', 'policy_violation', 'sandbox_violation', 'denied'],
    OFFLINE: ['offline', 'unreachable', 'disconnected'],
  };
  const STATE_MAP = {};
  Object.keys(STATE_WORDS).forEach(s => STATE_WORDS[s].forEach(w => { STATE_MAP[w] = s; }));
  const SECRET = /(bearer\s+[a-z0-9._\-]{8,}|sk-[a-z0-9_\-]{10,}|ghp_[a-z0-9]{10,}|AKIA[0-9A-Z]{12,}|eyJ[a-z0-9_\-]{8,}\.[a-z0-9_\-]{8,}\.[a-z0-9_\-]{8,}|(?:api[_-]?key|token|secret|password|authorization)\s*[=:]\s*\S+)/gi;

  function normalizeState(raw) {
    if (typeof raw !== 'string') return 'UNKNOWN';
    const word = raw.trim().toLowerCase().replace(/ /g, '_');
    return STATE_MAP[word] || (STATES.includes(word.toUpperCase()) ? word.toUpperCase() : 'UNKNOWN');
  }
  function redactSummary(text, limit) {
    if (typeof text !== 'string' || !text.trim()) return null;
    return text.split(/\s+/).join(' ').replace(SECRET, '[REDACTED]').slice(0, limit || 160);
  }
  function hash(str) { let h = 5381; for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0; return (h >>> 0).toString(36); }
  const text = (v, n) => (v === null || v === undefined || v === '' ? null : String(v).slice(0, n || 80));

  /* Normalise one upstream event (server contract event or legacy snapshot event) to spec section 9. */
  function normalizeEvent(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
    const timestamp = raw.timestamp || raw.created_at;
    const eventType = raw.event_type || raw.kind || 'OBSERVED_EVENT';
    const role = raw.role_id || raw.component_id;
    let id = raw.event_id || raw.id;
    if (!id) id = 'derived-' + hash([raw.source, timestamp, eventType, role, raw.task_id, raw.title].join('|'));
    let severity = String(raw.severity || 'info').toLowerCase();
    severity = severity === 'warn' ? 'warning' : severity === 'err' ? 'error' : severity;
    const stateRaw = raw.state || raw.status;
    const ev = {
      schema_version: 1, event_id: String(id).slice(0, 80),
      timestamp: typeof timestamp === 'string' ? timestamp : null,
      source: text(raw.source), role_id: text(role), provider: text(raw.provider), model: text(raw.model),
      task_id: text(raw.task_id), run_id: text(raw.run_id), correlation_id: text(raw.correlation_id || raw.interaction_id),
      event_type: String(eventType).slice(0, 60), state: stateRaw ? normalizeState(stateRaw) : 'UNKNOWN',
      severity: ['info', 'warning', 'error', 'critical'].includes(severity) ? severity : 'info',
      provenance: raw.provenance && typeof raw.provenance === 'object' ? raw.provenance : {},
      redacted_summary: redactSummary(raw.redacted_summary || raw.title || raw.summary),
    };
    if (raw.target_node) ev.target_node = text(raw.target_node, 40);
    if (raw.target_role_id) ev.target_role_id = text(raw.target_role_id, 40);
    return ev;
  }

  /* Bounded buffer with duplicate protection. */
  function createEventBuffer(max) {
    const limit = max || 200; const items = []; const ids = new Set();
    return {
      add(ev) {
        if (!ev || ids.has(ev.event_id)) return false;
        items.push(ev); ids.add(ev.event_id);
        while (items.length > limit) ids.delete(items.shift().event_id);
        return true;
      },
      list() { return items.slice(); }, size() { return items.length; },
    };
  }

  /* live | stale | offline | unknown, from the time of the last message received. */
  function classifyFreshness(lastMs, nowMs, opts) {
    const o = Object.assign({ staleMs: 30000, offlineMs: 90000 }, opts);
    if (lastMs === null || lastMs === undefined || !Number.isFinite(lastMs)) return 'unknown';
    const age = nowMs - lastMs;
    return age <= o.staleMs ? 'live' : age <= o.offlineMs ? 'stale' : 'offline';
  }

  const TRUSTED_VALIDITY = ['valid', 'fixture'];
  const PRIORITY = ['SECURITY_BLOCKED', 'FAILED', 'WAITING_APPROVAL', 'REVIEW', 'WORKING'];
  /* ctx: {transportStatus, lastMessageAt, sourceValidity, now}. Missing telemetry -> UNKNOWN, never WORKING. */
  function deriveCoreState(events, ctx, opts) {
    const o = Object.assign({ activeWindowMs: 120000, staleMs: 30000, offlineMs: 90000 }, opts);
    const now = ctx.now;
    if (ctx.transportStatus === 'offline') return { state: 'OFFLINE', reason: 'Event transport offline' };
    const fresh = classifyFreshness(ctx.lastMessageAt, now, o);
    if (fresh === 'offline') return { state: 'OFFLINE', reason: 'No telemetry received within the offline window' };
    if (fresh !== 'live') return { state: 'UNKNOWN', reason: fresh === 'stale' ? 'Telemetry is stale' : 'No telemetry observed yet' };
    if (!TRUSTED_VALIDITY.includes(ctx.sourceValidity)) return { state: 'UNKNOWN', reason: 'Event source validity is ' + (ctx.sourceValidity || 'unknown') };
    const latest = new Map();
    (events || []).forEach(ev => {
      const t = Date.parse(ev.timestamp || '');
      if (!Number.isFinite(t) || now - t > o.activeWindowMs || t > now + 60000) return;
      const key = ev.run_id || ev.task_id || ev.correlation_id || ev.event_id;
      const prev = latest.get(key);
      if (!prev || t >= prev.t) latest.set(key, { t, state: ev.state });
    });
    const active = new Set([...latest.values()].map(v => v.state));
    for (const s of PRIORITY) if (active.has(s)) return { state: s, reason: 'Observed event' };
    return { state: 'IDLE', reason: 'Fresh valid telemetry, no active run observed' };
  }

  const STATE_VISUAL = {
    IDLE: { cls: 'core-state-idle', tone: 'ok', motion: 'slow' },
    WORKING: { cls: 'core-state-working', tone: 'ok', motion: 'active' },
    WAITING_APPROVAL: { cls: 'core-state-waiting', tone: 'warn', motion: 'pulse' },
    REVIEW: { cls: 'core-state-review', tone: 'review', motion: 'pulse' },
    FAILED: { cls: 'core-state-failed', tone: 'fail', motion: 'none' },
    SECURITY_BLOCKED: { cls: 'core-state-blocked', tone: 'fail', motion: 'none', lock: true },
    OFFLINE: { cls: 'core-state-offline', tone: 'unknown', motion: 'none' },
    UNKNOWN: { cls: 'core-state-unknown', tone: 'unknown', motion: 'none' },
  };
  function visualClass(state) { return STATE_VISUAL[state] || STATE_VISUAL.UNKNOWN; }
  /* ULTRON ring colour: green only when ULTRON itself was observed; never assumed. */
  function ultronRingClass(coreState, ultronObserved) {
    if (coreState === 'SECURITY_BLOCKED') return 'red';
    if (coreState === 'WAITING_APPROVAL') return 'amber';
    if (ultronObserved && ['IDLE', 'WORKING', 'REVIEW'].includes(coreState)) return 'green';
    return 'gray';
  }

  /* ---- agent orbital movement ---- */
  const CENTER = { x: 800, y: 450 }; const ORBIT_R = 285;
  const HOME_ANGLES = { FURY: -90, SHURI: -150, THOR: -30, VISION: 150, FALCON: 30, UATU: 90 };
  const NODES = { internet: { x: 1280, y: 130 }, obsidian: { x: 330, y: 300 } };
  const angleToNode = n => Math.atan2(n.y - CENTER.y, n.x - CENTER.x) * 180 / Math.PI;
  const norm180 = a => ((a + 540) % 360) - 180;
  const pointAt = a => ({ x: CENTER.x + ORBIT_R * Math.cos(a * Math.PI / 180), y: CENTER.y + ORBIT_R * Math.sin(a * Math.PI / 180) });
  const ease = p => p < 0 ? 0 : p > 1 ? 1 : p * p * (3 - 2 * p);
  const TERMINAL_TYPE = /COMPLETED|FINISHED|DONE|FAILED|CANCELLED|TIMEOUT/i;

  function resolveTarget(ev) {
    if (ev.target_node && NODES[String(ev.target_node).toLowerCase()]) return { kind: 'node', id: String(ev.target_node).toLowerCase() };
    const role = ev.target_role_id && String(ev.target_role_id).toUpperCase();
    if (role && HOME_ANGLES[role] !== undefined && role !== String(ev.role_id).toUpperCase()) return { kind: 'agent', id: role };
    if (/INTERNET|NETWORK|WEB_|EXTERNAL/i.test(ev.event_type)) return { kind: 'node', id: 'internet' };
    if (/OBSIDIAN|WONG|CONTEXT|MEMORY/i.test(ev.event_type)) return { kind: 'node', id: 'obsidian' };
    return null;
  }

  function createMovementModel(opts) {
    const o = Object.assign({ maxMovers: 2, queueMax: 4, timeoutMs: 20000, travelMs: 1500, returnMs: 1500 }, opts);
    const movers = new Map(); let queue = [];
    const MIN_SEP = 26; // degrees of orbit kept clear between a resting agent and any other agent's home
    function restAngle(preferred, role, mustBeNear) {
      const others = Object.keys(HOME_ANGLES).filter(r => r !== role).map(r => HOME_ANGLES[r]);
      const clear = a => others.every(h => Math.abs(norm180(a - h)) >= MIN_SEP - 0.001);
      for (let d = 0; d <= 90; d += 2) for (const sign of d === 0 ? [1] : [1, -1]) { const a = norm180(preferred + sign * d); if (clear(a)) return a; }
      return preferred;
    }
    function destinationAngle(m) {
      if (m.target.kind === 'node') return restAngle(angleToNode(NODES[m.target.id]), m.role);
      const t = HOME_ANGLES[m.target.id]; const home = HOME_ANGLES[m.role];
      // beside the partner on the side we approach from, but never on top of a third agent
      const others = Object.keys(HOME_ANGLES).filter(r => r !== m.role && r !== m.target.id).map(r => HOME_ANGLES[r]);
      const side = norm180(home - t) >= 0 ? 1 : -1;
      for (const off of [30, 36, 42]) { const a = norm180(t + side * off); if (others.every(h => Math.abs(norm180(a - h)) >= 18)) return a; }
      return norm180(t + side * 30);
    }
    function start(item, now) {
      movers.set(item.id, { id: item.id, role: item.role, target: item.target, phase: 'traveling', phaseAt: now, startedAt: now, lastEventAt: now, completedAt: null, completing: false, fromAngle: HOME_ANGLES[item.role] });
    }
    function terminal(ev) { return ev.state === 'IDLE' || ev.state === 'FAILED' || TERMINAL_TYPE.test(ev.event_type); }
    return {
      applyEvent(ev, now) {
        const role = ev && ev.role_id && String(ev.role_id).toUpperCase();
        if (!role || HOME_ANGLES[role] === undefined) return false;
        const id = ev.correlation_id || ev.run_id || ev.task_id || ev.event_id;
        const existing = movers.get(id);
        if (existing) { existing.lastEventAt = now; if (terminal(ev)) existing.completing = true; return true; }
        if (terminal(ev)) return false;
        const target = resolveTarget(Object.assign({}, ev, { role_id: role }));
        if (!target) return false;
        const item = { id, role, target };
        const busy = [...movers.values()].some(m => m.role === role) || queue.some(q => q.role === role);
        if (busy) return false; // one interaction per agent at a time
        if (movers.size >= o.maxMovers) { if (queue.length < o.queueMax) queue.push(item); return queue.includes(item); }
        start(item, now); return true;
      },
      tick(now) {
        movers.forEach((m, id) => {
          if (m.phase === 'traveling' && now - m.phaseAt >= o.travelMs) { m.phase = 'at_target'; m.phaseAt = now; }
          if (m.phase === 'at_target' && (m.completing || now - m.lastEventAt > o.timeoutMs)) { m.phase = 'returning'; m.phaseAt = now; m.completedAt = now; m.fromAngle = destinationAngle(m); m.timedOut = !m.completing; }
          if (m.phase === 'returning' && now - m.phaseAt >= o.returnMs) movers.delete(id);
          if (m.phase === 'traveling' && m.completing) { m.phase = 'returning'; m.phaseAt = now; m.completedAt = now; m.fromAngle = HOME_ANGLES[m.role]; }
        });
        while (queue.length && movers.size < o.maxMovers) start(queue.shift(), now);
      },
      snapshot(now) {
        return [...movers.values()].map(m => {
          const home = HOME_ANGLES[m.role]; const dest = destinationAngle(m); let angle;
          if (m.phase === 'traveling') angle = home + norm180(dest - home) * ease((now - m.phaseAt) / o.travelMs);
          else if (m.phase === 'at_target') angle = dest;
          else angle = m.fromAngle + norm180(home - m.fromAngle) * ease((now - m.phaseAt) / o.returnMs);
          const p = pointAt(angle);
          return { role: m.role, interaction_id: m.id, movement_state: m.phase, target_node: m.target.id, target_kind: m.target.kind, home_angle: home, target_angle: dest, angle, x: p.x, y: p.y, started_at: m.startedAt, completed_at: m.completedAt };
        });
      },
      positionFor(role, now) { const s = this.snapshot(now).find(m => m.role === role); const a = s ? s.angle : HOME_ANGLES[role]; return Object.assign({ angle: a }, pointAt(a)); },
      size() { return movers.size; }, queued() { return queue.length; },
    };
  }

  /* ---- transport: SSE primary, guarded polling fallback ---- */
  function createTransport(cfg) {
    const c = Object.assign({ streamUrl: '/api/events/stream', pollIntervalMs: 5000, pollTimeoutMs: 4000, backoffBaseMs: 1000, backoffMaxMs: 30000, offlineAfterFailures: 2, now: Date.now, setTimeout: root.setTimeout && root.setTimeout.bind(root), clearTimeout: root.clearTimeout && root.clearTimeout.bind(root) }, cfg);
    const st = { mode: 'connecting', status: 'connecting', lastMessageAt: null, sourceValidity: null, failures: 0, backoffN: 0, inflight: false };
    let es = null, pollTimer = null, reconnectTimer = null, stopped = false;
    const emit = () => c.onStatus && c.onStatus(Object.assign({}, st));
    const got = () => { st.lastMessageAt = c.now(); st.failures = 0; };
    function openSse() {
      if (stopped || !c.EventSource) return startPolling();
      try { es = new c.EventSource(c.streamUrl); } catch (_e) { return startPolling(); }
      es.onopen = () => { st.mode = 'sse'; st.status = 'live'; st.backoffN = 0; stopPolling(); emit(); };
      es.addEventListener('hive', m => { try { const ev = normalizeEvent(JSON.parse(m.data)); got(); if (ev) c.onEvent(ev); emit(); } catch (_e) { /* malformed frame ignored */ } });
      es.addEventListener('status', m => { try { const s = JSON.parse(m.data); got(); st.sourceValidity = s.validity || null; st.sourceReason = s.reason || null; emit(); } catch (_e) { /* ignore */ } });
      es.onerror = () => { try { es.close(); } catch (_e) { /* closed */ } es = null; st.mode = 'polling'; st.status = 'degraded'; startPolling(); scheduleReconnect(); emit(); };
    }
    function scheduleReconnect() {
      if (stopped || reconnectTimer) return;
      const delay = Math.min(c.backoffMaxMs, c.backoffBaseMs * Math.pow(2, st.backoffN++));
      reconnectTimer = c.setTimeout(() => { reconnectTimer = null; openSse(); }, delay);
      st.nextReconnectMs = delay;
    }
    function startPolling() { if (stopped || pollTimer !== null) return; st.mode = st.mode === 'sse' ? 'sse' : 'polling'; pollTimer = c.setTimeout(poll, 0); }
    function stopPolling() { if (pollTimer !== null && pollTimer !== 'running') c.clearTimeout(pollTimer); pollTimer = null; }
    async function poll() {
      if (stopped) return; pollTimer = 'running';
      if (st.inflight) return; // in-flight guard
      st.inflight = true;
      const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
      const killer = c.setTimeout(() => { if (ctl) ctl.abort(); }, c.pollTimeoutMs);
      let timedOut = false;
      try {
        const res = await Promise.race([c.pollFn(ctl && ctl.signal), new Promise((_r, rej) => c.setTimeout(() => { timedOut = true; rej(new Error('poll timeout')); }, c.pollTimeoutMs + 50))]);
        got(); st.sourceValidity = (res && res.validity) || null; st.status = 'degraded';
        (res && res.events || []).forEach(raw => { const ev = normalizeEvent(raw); if (ev) c.onEvent(ev); });
      } catch (_e) {
        st.failures += 1; if (st.failures >= c.offlineAfterFailures) st.status = 'offline';
      } finally { c.clearTimeout(killer); st.inflight = false; }
      emit();
      if (stopped || pollTimer === null) return;
      const wait = st.failures ? Math.min(c.backoffMaxMs, c.pollIntervalMs * Math.pow(2, st.failures - 1)) : c.pollIntervalMs;
      pollTimer = c.setTimeout(poll, wait);
    }
    return {
      start() { openSse(); emit(); },
      stop() { stopped = true; if (es) try { es.close(); } catch (_e) { /* closed */ } stopPolling(); if (reconnectTimer) c.clearTimeout(reconnectTimer); },
      state() { return Object.assign({}, st); }, _poll: poll,
    };
  }

  const api = { STATES, STATE_MAP, normalizeState, normalizeEvent, redactSummary, createEventBuffer, classifyFreshness, deriveCoreState, visualClass, ultronRingClass, createMovementModel, createTransport, HOME_ANGLES, NODES, CENTER, ORBIT_R };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.HiveCore = api;
})(typeof window !== 'undefined' ? window : globalThis);
