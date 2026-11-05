// P0.2 unit tests: event contract, dedupe, freshness, CORE state, visual mapping, movement, transport.
// Run: node --test tests/core.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const H = createRequire(import.meta.url)('../hive-core.js');

const NOW = Date.parse('2026-11-05T12:00:00Z');
const iso = secAgo => new Date(NOW - secAgo * 1000).toISOString();
const ev = (o = {}) => H.normalizeEvent({ event_id: 'e' + Math.random(), timestamp: iso(5), role_id: 'FURY', event_type: 'TASK_ROUTED', state: 'working', task_id: 't1', ...o });
const ctx = (o = {}) => ({ now: NOW, transportStatus: 'live', lastMessageAt: NOW - 1000, sourceValidity: 'valid', ...o });

test('normalizeEvent emits the section 9 contract and maps legacy fields', () => {
  const e = H.normalizeEvent({ timestamp: iso(3), kind: 'TASK_ROUTED', component_id: 'FURY', title: 'hello', severity: 'warn', status: 'running', source: 'bus' });
  for (const k of ['schema_version', 'event_id', 'timestamp', 'source', 'role_id', 'provider', 'model', 'task_id', 'run_id', 'correlation_id', 'event_type', 'state', 'severity', 'provenance', 'redacted_summary']) assert.ok(k in e, k);
  assert.equal(e.state, 'WORKING'); assert.equal(e.severity, 'warning'); assert.equal(e.role_id, 'FURY'); assert.match(e.event_id, /^derived-/);
  assert.equal(e.provider, null); assert.equal(e.model, null); // never invented
});
test('unrecognised or missing state is UNKNOWN, not WORKING', () => {
  assert.equal(H.normalizeEvent({ event_id: 'a', status: 'frobnicating' }).state, 'UNKNOWN');
  assert.equal(H.normalizeEvent({ event_id: 'b' }).state, 'UNKNOWN');
  assert.equal(H.normalizeEvent('nope'), null); assert.equal(H.normalizeEvent(null), null); assert.equal(H.normalizeEvent([]), null);
});
test('summaries are redacted and bounded', () => {
  const e = H.normalizeEvent({ event_id: 'x', title: 'call with Bearer abcdef1234567890 and api_key=SECRET123 ' + 'z'.repeat(400) });
  assert.doesNotMatch(e.redacted_summary, /abcdef1234567890|SECRET123/); assert.match(e.redacted_summary, /REDACTED/); assert.ok(e.redacted_summary.length <= 160);
});
test('derived ids are deterministic so replays dedupe', () => {
  const raw = { timestamp: iso(1), kind: 'X', component_id: 'FURY', title: 't' };
  assert.equal(H.normalizeEvent(raw).event_id, H.normalizeEvent({ ...raw }).event_id);
});
test('buffer drops duplicates and stays bounded', () => {
  const b = H.createEventBuffer(3);
  assert.equal(b.add(ev({ event_id: 'a' })), true); assert.equal(b.add(ev({ event_id: 'a' })), false);
  ['b', 'c', 'd', 'e'].forEach(id => b.add(ev({ event_id: id })));
  assert.equal(b.size(), 3); assert.deepEqual(b.list().map(x => x.event_id), ['c', 'd', 'e']);
  assert.equal(b.add(ev({ event_id: 'a' })), true, 'evicted ids may be re-accepted (bounded memory)');
});
test('freshness classification: live / stale / offline / unknown', () => {
  assert.equal(H.classifyFreshness(null, NOW), 'unknown');
  assert.equal(H.classifyFreshness(NOW - 1000, NOW), 'live');
  assert.equal(H.classifyFreshness(NOW - 40000, NOW), 'stale');
  assert.equal(H.classifyFreshness(NOW - 120000, NOW), 'offline');
  assert.equal(H.classifyFreshness(NOW - 10, NOW, { staleMs: 5, offlineMs: 20 }), 'stale');
});
test('CORE state: no telemetry => UNKNOWN, never WORKING; silence never infers WORKING', () => {
  assert.equal(H.deriveCoreState([], ctx({ lastMessageAt: null })).state, 'UNKNOWN');
  assert.equal(H.deriveCoreState([ev()], ctx({ lastMessageAt: null })).state, 'UNKNOWN', 'events without fresh transport telemetry');
  assert.equal(H.deriveCoreState([ev()], ctx({ lastMessageAt: NOW - 40000 })).state, 'UNKNOWN', 'stale');
  assert.equal(H.deriveCoreState([ev()], ctx({ sourceValidity: 'auth_required' })).state, 'UNKNOWN');
  assert.equal(H.deriveCoreState([ev()], ctx({ sourceValidity: null })).state, 'UNKNOWN');
  assert.equal(H.deriveCoreState([], ctx()).state, 'IDLE');
  assert.equal(H.deriveCoreState([ev({ timestamp: iso(600) })], ctx()).state, 'IDLE', 'old events do not count as work');
  assert.equal(H.deriveCoreState([ev({ state: 'bogus' })], ctx()).state, 'IDLE', 'UNKNOWN-state events never become WORKING');
});
test('CORE state: OFFLINE when transport is offline or telemetry long gone', () => {
  assert.equal(H.deriveCoreState([], ctx({ transportStatus: 'offline' })).state, 'OFFLINE');
  assert.equal(H.deriveCoreState([], ctx({ lastMessageAt: NOW - 200000 })).state, 'OFFLINE');
});
test('CORE state: priority SECURITY_BLOCKED > FAILED > WAITING_APPROVAL > REVIEW > WORKING', () => {
  const mk = (...states) => states.map((s, i) => ev({ state: s, task_id: 't' + i }));
  assert.equal(H.deriveCoreState(mk('working'), ctx()).state, 'WORKING');
  assert.equal(H.deriveCoreState(mk('working', 'review'), ctx()).state, 'REVIEW');
  assert.equal(H.deriveCoreState(mk('review', 'waiting_approval'), ctx()).state, 'WAITING_APPROVAL');
  assert.equal(H.deriveCoreState(mk('waiting_approval', 'failed'), ctx()).state, 'FAILED');
  assert.equal(H.deriveCoreState(mk('failed', 'security_blocked', 'working'), ctx()).state, 'SECURITY_BLOCKED');
});
test('CORE state: a run that later completes no longer counts as active', () => {
  const events = [ev({ state: 'working', timestamp: iso(20), task_id: 'r' }), ev({ state: 'completed', timestamp: iso(5), task_id: 'r' })];
  assert.equal(H.deriveCoreState(events, ctx()).state, 'IDLE');
});
test('state -> visual class mapping covers all 8 states with distinct classes', () => {
  const seen = new Set();
  for (const s of H.STATES) { const v = H.visualClass(s); assert.ok(v.cls.startsWith('core-state-')); seen.add(v.cls); }
  assert.equal(seen.size, 8);
  assert.equal(H.visualClass('WAITING_APPROVAL').tone, 'warn'); assert.equal(H.visualClass('REVIEW').tone, 'review');
  assert.equal(H.visualClass('FAILED').tone, 'fail'); assert.equal(H.visualClass('SECURITY_BLOCKED').lock, true);
  assert.equal(H.visualClass('OFFLINE').tone, 'unknown'); assert.equal(H.visualClass('nonsense').cls, 'core-state-unknown');
  assert.equal(H.visualClass('UNKNOWN').motion, 'none'); assert.equal(H.visualClass('OFFLINE').motion, 'none');
});
test('ULTRON ring: green only when ULTRON observed; amber/red/gray otherwise', () => {
  assert.equal(H.ultronRingClass('WORKING', false), 'gray'); assert.equal(H.ultronRingClass('WORKING', true), 'green');
  assert.equal(H.ultronRingClass('WAITING_APPROVAL', true), 'amber'); assert.equal(H.ultronRingClass('SECURITY_BLOCKED', false), 'red');
  assert.equal(H.ultronRingClass('UNKNOWN', true), 'gray'); assert.equal(H.ultronRingClass('OFFLINE', true), 'gray');
});

/* ---------- movement ---------- */
const mv = o => H.createMovementModel({ travelMs: 1000, returnMs: 1000, timeoutMs: 5000, ...o });
test('movement: no events => no movement, agents sit at home', () => {
  const m = mv(); m.tick(NOW); m.tick(NOW + 60000);
  assert.equal(m.size(), 0); assert.deepEqual(m.snapshot(NOW + 60000), []);
  const p = m.positionFor('FURY', NOW); assert.equal(p.angle, H.HOME_ANGLES.FURY);
});
test('movement: events without an interaction target or from unknown roles do not move anything', () => {
  const m = mv();
  assert.equal(m.applyEvent(ev({ event_type: 'HEARTBEAT' }), NOW), false);
  assert.equal(m.applyEvent(ev({ role_id: 'NOBODY', event_type: 'INTERNET_ACCESS' }), NOW), false);
  assert.equal(m.applyEvent(ev({ role_id: null, event_type: 'INTERNET_ACCESS' }), NOW), false);
  assert.equal(m.applyEvent(ev({ event_type: 'INTERNET_DONE', state: 'completed' }), NOW), false, 'terminal event never starts a trip');
  assert.equal(m.size(), 0);
});
test('movement: internet event -> travel to internet angle -> at target', () => {
  const m = mv(); assert.equal(m.applyEvent(ev({ role_id: 'THOR', event_type: 'INTERNET_ACCESS', correlation_id: 'c1' }), NOW), true);
  assert.equal(m.snapshot(NOW)[0].movement_state, 'traveling');
  const mid = m.snapshot(NOW + 500)[0]; assert.ok(mid.angle < H.HOME_ANGLES.THOR && mid.angle > -33.7, 'between home and internet angle');
  m.tick(NOW + 1000); const s = m.snapshot(NOW + 1000)[0];
  assert.equal(s.movement_state, 'at_target'); assert.equal(s.target_node, 'internet'); assert.equal(s.interaction_id, 'c1');
  assert.ok(Math.abs(s.angle - Math.atan2(130 - 450, 1280 - 800) * 180 / Math.PI) < 8, 'rests near the internet bearing');
  assert.ok(Object.entries(H.HOME_ANGLES).filter(([r]) => r !== 'THOR').every(([, h]) => Math.abs(((s.angle - h + 540) % 360) - 180) >= 25.9), 'clear of other agents');
});
test('movement: obsidian read event targets obsidian', () => {
  const m = mv(); m.applyEvent(ev({ role_id: 'UATU', event_type: 'WONG_READ', correlation_id: 'c2' }), NOW);
  assert.equal(m.snapshot(NOW)[0].target_node, 'obsidian');
});
test('movement: resting angles never sit on another agent (all roles x all nodes)', () => {
  for (const role of Object.keys(H.HOME_ANGLES)) for (const node of ['internet', 'obsidian']) {
    const m = mv(); m.applyEvent(ev({ role_id: role, event_type: 'X', target_node: node, correlation_id: role + node }), NOW); m.tick(NOW + 1000);
    const a = m.snapshot(NOW + 1000)[0].angle;
    for (const [r, h] of Object.entries(H.HOME_ANGLES)) if (r !== role) assert.ok(Math.abs(((a - h + 540) % 360) - 180) >= 25.9, `${role}->${node} rests ${a} near ${r}`);
  }
});
test('movement: handoff moves source toward destination agent, beside it', () => {
  const m = mv(); m.applyEvent(ev({ role_id: 'FURY', event_type: 'HANDOFF', target_role_id: 'THOR', correlation_id: 'c3' }), NOW);
  m.tick(NOW + 1000); const s = m.snapshot(NOW + 1000)[0];
  assert.equal(s.target_kind, 'agent'); assert.notEqual(s.angle, H.HOME_ANGLES.THOR, 'does not sit on top of the partner');
  assert.ok(Math.abs(s.angle - H.HOME_ANGLES.THOR) >= 30 && Math.abs(s.angle - H.HOME_ANGLES.THOR) <= 42, 'beside, not on, the partner');
  assert.equal(m.applyEvent(ev({ role_id: 'FURY', event_type: 'HANDOFF', target_role_id: 'FURY', correlation_id: 'c3b' }), NOW), false, 'cannot hand off to self');
});
test('movement: completion event returns the agent home', () => {
  const m = mv(); m.applyEvent(ev({ role_id: 'THOR', event_type: 'INTERNET_ACCESS', correlation_id: 'c4' }), NOW); m.tick(NOW + 1000);
  m.applyEvent(ev({ role_id: 'THOR', event_type: 'INTERNET_ACCESS', correlation_id: 'c4', state: 'completed' }), NOW + 2000);
  m.tick(NOW + 2000); assert.equal(m.snapshot(NOW + 2000)[0].movement_state, 'returning');
  assert.ok(m.snapshot(NOW + 2000)[0].completed_at);
  m.tick(NOW + 3000); assert.equal(m.size(), 0); assert.equal(m.positionFor('THOR', NOW + 3000).angle, H.HOME_ANGLES.THOR);
});
test('movement: timeout with no further events returns home; fresh events keep it out', () => {
  const m = mv(); m.applyEvent(ev({ role_id: 'FALCON', event_type: 'NETWORK_FETCH', correlation_id: 'c5' }), NOW); m.tick(NOW + 1000);
  m.applyEvent(ev({ role_id: 'FALCON', event_type: 'NETWORK_FETCH', correlation_id: 'c5' }), NOW + 4000);
  m.tick(NOW + 8000); assert.equal(m.snapshot(NOW + 8000)[0].movement_state, 'at_target', 'refresh extends the interaction');
  m.tick(NOW + 9500); assert.equal(m.snapshot(NOW + 9500)[0].movement_state, 'returning');
  m.tick(NOW + 10600); assert.equal(m.size(), 0);
});
test('movement: concurrency is capped and one trip per agent', () => {
  const m = mv({ maxMovers: 2, queueMax: 1 });
  assert.equal(m.applyEvent(ev({ role_id: 'FURY', event_type: 'INTERNET_ACCESS', correlation_id: 'a' }), NOW), true);
  assert.equal(m.applyEvent(ev({ role_id: 'FURY', event_type: 'WONG_READ', correlation_id: 'a2' }), NOW), false, 'same agent already travelling');
  assert.equal(m.applyEvent(ev({ role_id: 'SHURI', event_type: 'WONG_READ', correlation_id: 'b' }), NOW), true);
  assert.equal(m.applyEvent(ev({ role_id: 'THOR', event_type: 'INTERNET_ACCESS', correlation_id: 'c' }), NOW), true, 'queued');
  assert.equal(m.applyEvent(ev({ role_id: 'VISION', event_type: 'INTERNET_ACCESS', correlation_id: 'd' }), NOW), false, 'queue full -> dropped');
  assert.equal(m.size(), 2); assert.equal(m.queued(), 1);
  m.applyEvent(ev({ role_id: 'FURY', event_type: 'INTERNET_ACCESS', correlation_id: 'a', state: 'failed' }), NOW + 100);
  m.tick(NOW + 1000); m.tick(NOW + 1100); m.tick(NOW + 2200);
  assert.equal(m.queued(), 0, 'queued trip promoted when a slot frees'); assert.ok(m.size() <= 2);
});

/* ---------- transport ---------- */
function harness(over = {}) {
  let now = 1000; const timers = []; let id = 0; const sources = []; const events = []; const statuses = [];
  class FakeES { constructor(url) { this.url = url; this.l = {}; sources.push(this); this.closed = false; } addEventListener(n, f) { this.l[n] = f; } close() { this.closed = true; } }
  const setT = (fn, ms) => { timers.push({ id: ++id, at: now + ms, fn }); return id; };
  const clrT = tid => { const i = timers.findIndex(t => t.id === tid); if (i >= 0) timers.splice(i, 1); };
  const advance = async ms => { const end = now + ms; for (;;) { timers.sort((a, b) => a.at - b.at); const t = timers[0]; if (!t || t.at > end) break; timers.shift(); now = t.at; t.fn(); for (let i = 0; i < 12; i++) await Promise.resolve(); } now = end; };
  const tr = H.createTransport({ EventSource: FakeES, now: () => now, setTimeout: setT, clearTimeout: clrT, onEvent: e => events.push(e), onStatus: s => statuses.push(s), pollFn: async () => ({ events: [], validity: 'valid' }), ...over });
  return { tr, sources, events, statuses, advance, timers, now: () => now };
}
test('transport: SSE is primary; frames normalise and mark telemetry', async () => {
  const h = harness(); h.tr.start(); const es = h.sources[0];
  assert.equal(es.url, '/api/events/stream'); es.onopen();
  es.l.status({ data: JSON.stringify({ validity: 'valid' }) });
  es.l.hive({ data: JSON.stringify({ event_id: 'z1', role_id: 'FURY', state: 'working', timestamp: new Date().toISOString() }) });
  es.l.hive({ data: 'not json' }); // malformed frames are ignored
  const s = h.tr.state(); assert.equal(s.mode, 'sse'); assert.equal(s.status, 'live'); assert.equal(s.sourceValidity, 'valid');
  assert.equal(h.events.length, 1); assert.equal(h.events[0].state, 'WORKING'); assert.ok(s.lastMessageAt);
});
test('transport: SSE error -> polling fallback + exponential reconnect backoff', async () => {
  let polls = 0; const h = harness({ pollFn: async () => { polls++; return { events: [{ event_id: 'p' + polls, state: 'working' }], validity: 'valid' }; } });
  h.tr.start(); h.sources[0].onopen(); h.sources[0].onerror();
  assert.equal(h.sources[0].closed, true); assert.equal(h.tr.state().mode, 'polling');
  await h.advance(100); assert.equal(polls, 1); assert.equal(h.events.length, 1);
  await h.advance(1000); assert.equal(h.sources.length, 2, 'reconnect attempt after 1s');
  h.sources[1].onerror(); assert.equal(h.tr.state().nextReconnectMs, 2000);
  await h.advance(2100); assert.equal(h.sources.length, 3); h.sources[2].onerror(); assert.equal(h.tr.state().nextReconnectMs, 4000);
  h.sources[2].onopen(); assert.equal(h.tr.state().mode, 'sse'); assert.equal(h.tr.state().status, 'live');
});
test('transport: polling has an in-flight guard (no overlapping requests)', async () => {
  let active = 0, max = 0, release; const gate = new Promise(r => { release = r; });
  const h = harness({ EventSource: undefined, pollFn: async () => { active++; max = Math.max(max, active); await gate; active--; return { events: [], validity: 'valid' }; } });
  h.tr.start(); await h.advance(10); h.tr._poll(); h.tr._poll(); await Promise.resolve();
  assert.equal(max, 1); release(); await h.advance(10);
});
test('transport: poll timeout counts as failure; repeated failures => offline with backoff', async () => {
  const h = harness({ EventSource: undefined, pollTimeoutMs: 100, pollIntervalMs: 1000, pollFn: () => new Promise(() => {}) });
  h.tr.start(); await h.advance(200); assert.equal(h.tr.state().failures, 1); assert.notEqual(h.tr.state().status, 'offline');
  await h.advance(1500); assert.equal(h.tr.state().failures, 2); assert.equal(h.tr.state().status, 'offline');
  assert.equal(h.tr.state().lastMessageAt, null, 'failed polls never refresh telemetry');
});
test('transport: failed polls never produce events, and recovery clears offline', async () => {
  let fail = true; const h = harness({ EventSource: undefined, pollIntervalMs: 1000, pollFn: async () => { if (fail) throw new Error('x'); return { events: [{ event_id: 'r1' }], validity: 'valid' }; } });
  h.tr.start(); await h.advance(5000); assert.equal(h.events.length, 0); assert.equal(h.tr.state().status, 'offline');
  fail = false; await h.advance(10000); assert.ok(h.events.length >= 1 && h.events.every(e => e.event_id === 'r1')); assert.notEqual(h.tr.state().status, 'offline'); assert.equal(h.tr.state().failures, 0);
});
test('stopped transport schedules nothing further', async () => {
  const h = harness(); h.tr.start(); h.sources[0].onerror(); h.tr.stop(); await h.advance(60000);
  assert.equal(h.sources.length, 1);
});
