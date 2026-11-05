// P0.3 unit tests: outbox states, attachments, activity sanitization, approvals fallback.
// Run: node --test tests/ops.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const O = require('../hive-ops.js'); const H = require('../hive-core.js');

const connected = (sendImpl) => ({ connected: () => ({ ok: true }), send: sendImpl });

test('no connector => NOT_CONNECTED, never SENT, no reply fabricated', async () => {
  const ob = O.createOutbox({}); const { message } = await ob.send('hello', []);
  assert.equal(message.state, 'NOT_CONNECTED'); assert.match(message.reason, /connector/i);
  assert.equal(message.providerResponseId, null); assert.ok(!('reply' in message));
});
test('SENT only after a real provider response (delivered + response id)', async () => {
  const mk = res => O.createOutbox({ connector: connected(async () => res) });
  assert.equal((await mk({ delivered: true, provider_response_id: 'r-1' }).send('x')).message.state, 'SENT');
  assert.equal((await mk({ delivered: true }).send('x')).message.state, 'FAILED', 'no response id => not SENT');
  assert.equal((await mk({ delivered: false, reason: 'rejected' }).send('x')).message.state, 'FAILED');
  assert.equal((await mk(undefined).send('x')).message.state, 'FAILED');
  assert.equal((await mk('ok').send('x')).message.state, 'FAILED', 'truthy but not a provider response');
});
test('provider error and timeout => FAILED with reason', async () => {
  const boom = O.createOutbox({ connector: connected(async () => { throw new Error('502 bad gateway'); }) });
  const m = (await boom.send('x')).message; assert.equal(m.state, 'FAILED'); assert.match(m.reason, /502/);
  const slow = O.createOutbox({ timeoutMs: 20, connector: connected(() => new Promise(() => {})) });
  const s = (await slow.send('x')).message; assert.equal(s.state, 'FAILED'); assert.match(s.reason, /timeout/);
});
test('state passes through QUEUED before resolution and onChange sees it', async () => {
  const seen = []; let release; const gate = new Promise(r => { release = r; });
  const ob = O.createOutbox({ connector: connected(async () => { await gate; return { delivered: true, provider_response_id: 'p' }; }), onChange: l => seen.push(l[l.length - 1].state) });
  const p = ob.send('x'); await Promise.resolve(); assert.equal(ob.list()[0].state, 'QUEUED'); release(); await p;
  assert.deepEqual(seen.slice(0, 1), ['QUEUED']); assert.equal(seen.at(-1), 'SENT');
});
test('retry re-attempts only FAILED / NOT_CONNECTED messages', async () => {
  let ok = false; const ob = O.createOutbox({ connector: { connected: () => (ok ? { ok: true } : { ok: false, reason: 'down' }), send: async () => ({ delivered: true, provider_response_id: 'r' }) } });
  const { message } = await ob.send('x'); assert.equal(message.state, 'NOT_CONNECTED');
  ok = true; assert.equal((await ob.retry(message.id)).state, 'SENT'); assert.equal(await ob.retry(message.id), null, 'SENT is final');
  assert.equal(await ob.retry('nope'), null);
});
test('validation: empty, oversize; attachments-only allowed; list bounded', async () => {
  const ob = O.createOutbox({ max: 3 });
  assert.ok((await ob.send('   ', [])).error); assert.ok((await ob.send('a'.repeat(O.MAX_TEXT + 1))).error);
  assert.equal((await ob.send('', [{ name: 'a.txt', size: 1 }])).message.state, 'NOT_CONNECTED');
  for (let i = 0; i < 5; i++) await ob.send('m' + i); assert.equal(ob.list().length, 3);
});
test('attachments: multiple files, sanitised names, limits, duplicates; contents never read', () => {
  const f = (name, size) => ({ name, size, type: 'text/plain', text() { throw new Error('contents must not be read'); }, arrayBuffer() { throw new Error('contents must not be read'); } });
  const r = O.describeFiles([f('a.txt', 3), f('..\\..\\evil\u0000<x>.sh', 5), f('a.txt', 3), f('big.bin', 60 * 1024 * 1024)], []);
  assert.equal(r.attachments.length, 2); assert.equal(r.attachments[1].name, 'evilx.sh');
  assert.deepEqual(r.rejected.map(x => x.reason), ['already attached', 'larger than 50 MB']);
  let cur = []; for (let i = 0; i < 12; i++) cur = O.describeFiles([f('f' + i, i)], cur).attachments;
  assert.equal(cur.length, O.MAX_FILES);
  assert.equal(O.sanitizeFileName('C:/Users/x/secret.pem'), 'secret.pem'); assert.equal(O.sanitizeFileName(''), 'file');
});
test('attachments are passed to the connector as metadata only', async () => {
  let got; const ob = O.createOutbox({ connector: connected(async p => { got = p; return { delivered: true, provider_response_id: 'r' }; }) });
  await ob.send('hi', [{ id: '1', name: 'a.txt', size: 3, type: 't', blob: 'SECRET' }]);
  assert.deepEqual(Object.keys(got.attachments[0]).sort(), ['name', 'size', 'type']);
});

/* ---- activity sanitization ---- */
test('activity rows contain only time|role|provider|action|state and redact secrets', () => {
  const ev = H.normalizeEvent({ event_id: 'a', timestamp: '2026-11-05T12:00:00Z', role_id: 'FURY', provider: 'gpt', event_type: 'TASK_STARTED', state: 'running',
    title: 'ran with Bearer abcdef1234567890 and password=hunter2 key sk-abcdefghijklmnopqrst', prompt: 'RAW PROMPT', chain_of_thought: 'SECRET THOUGHT', messages: [{ content: 'private' }] });
  const row = H.sanitizeActivityRow(ev);
  assert.deepEqual(Object.keys(row).sort(), ['action', 'id', 'provider', 'role', 'state', 'time']);
  const dump = JSON.stringify(row);
  for (const bad of ['abcdef1234567890', 'hunter2', 'sk-abcdefghijklmnopqrst', 'RAW PROMPT', 'SECRET THOUGHT', 'private']) assert.ok(!dump.includes(bad), bad);
  assert.match(row.action, /REDACTED/);
});
test('prompt/reasoning-type events never expose their content', () => {
  for (const type of ['PROMPT_SENT', 'LLM_COMPLETION', 'CHAIN_OF_THOUGHT', 'REASONING_TRACE', 'TRANSCRIPT_UPDATE']) {
    const ev = H.normalizeEvent({ event_id: type, timestamp: 't', event_type: type, title: 'Please summarise my private tax return', state: 'working' });
    assert.equal(ev.redacted_summary, null, type); assert.match(H.sanitizeActivityRow(ev).action, /content withheld/);
  }
});
test('redaction covers private keys, long opaque tokens, cookies, github/slack tokens', () => {
  const t = '-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\n-----END RSA PRIVATE KEY----- cookie: sid=abc123 ghp_abcdefghijklmnop xoxb-1234567890-abcdef ' + 'A'.repeat(48);
  const out = H.redactSummary(t, 400); for (const bad of ['MIIEabc', 'abc123', 'ghp_abcdefghijklmnop', 'xoxb-1234567890', 'A'.repeat(40)]) assert.ok(!out.includes(bad), bad);
});

/* ---- approvals ---- */
const now = Date.parse('2026-11-05T12:00:00Z');
const evt = (o) => H.normalizeEvent({ event_id: 'e' + Math.random(), timestamp: new Date(now - 5000).toISOString(), provider: 'gpt', state: 'waiting_approval', task_id: 't1', event_type: 'APPROVAL_REQUESTED', ...o });
test('pending approvals come only from observed WAITING_APPROVAL events, per provider, latest state wins', () => {
  assert.deepEqual(O.pendingApprovals([], now), { gpt: [], codex: [], claude: [] });
  const p = O.pendingApprovals([evt({}), evt({ provider: 'claude', task_id: 't2' }), evt({ provider: 'codex', state: 'working', task_id: 't3' })], now);
  assert.equal(p.gpt.length, 1); assert.equal(p.claude.length, 1); assert.equal(p.codex.length, 0);
  const resolved = O.pendingApprovals([evt({ timestamp: new Date(now - 9000).toISOString() }), evt({ state: 'completed', timestamp: new Date(now - 2000).toISOString() })], now);
  assert.equal(resolved.gpt.length, 0, 'later completion clears the approval');
  assert.equal(O.pendingApprovals([evt({ timestamp: new Date(now - 3600e3).toISOString() })], now).gpt.length, 0, 'old requests expire');
  assert.equal(O.pendingApprovals([evt({ provider: null })], now).gpt.length, 0, 'unknown provider is not guessed');
});
test('approve/reject without a connector are LOCAL and labelled as such', async () => {
  const item = { provider: 'gpt', key: 'gpt:t1' };
  const a = await O.decide(item, 'approve'); assert.equal(a.scope, 'local'); assert.equal(a.label, 'Approved locally, source not updated');
  const r = await O.decide(item, 'reject', { supports: () => false }); assert.equal(r.label, 'Rejected locally, source not updated');
  await assert.rejects(() => O.decide(item, 'delete'));
});
test('remote approval only when the connector supports it AND confirms; failures change nothing', async () => {
  const item = { provider: 'claude', key: 'claude:t' };
  const ok = await O.decide(item, 'approve', { supports: (p, a) => p === 'claude' && a === 'approve', apply: async () => ({ ok: true }) });
  assert.equal(ok.scope, 'source'); assert.equal(ok.label, 'Approved at source');
  const no = await O.decide(item, 'approve', { supports: () => true, apply: async () => ({ ok: false, reason: 'denied' }) });
  assert.equal(no.scope, 'none'); assert.equal(no.decision, null);
  const bad = await O.decide(item, 'reject', { supports: () => true, apply: async () => { throw new Error('net'); } });
  assert.equal(bad.scope, 'none');
  assert.equal((await O.decide({ provider: 'gpt' }, 'approve', { supports: (p) => p === 'claude', apply: async () => ({ ok: true }) })).scope, 'local', 'unsupported provider falls back to local');
});
test('Edit needs both adapter support and a deep link', () => {
  assert.equal(O.editAvailable({ provider: 'gpt' }, null), false);
  assert.equal(O.editAvailable({ provider: 'gpt', editUrl: 'https://x' }, { supports: () => false }), false);
  assert.equal(O.editAvailable({ provider: 'gpt' }, { supports: () => true }), false);
  assert.equal(O.editAvailable({ provider: 'gpt', editUrl: 'https://x' }, { supports: () => true }), true);
});

/* ======== review-driven additions ======== */
test('SENT gate is strict: string/empty/zero/missing id or non-true delivered => FAILED', async () => {
  const mk = res => O.createOutbox({ connector: connected(async () => res) });
  for (const res of [{ delivered: 'true', provider_response_id: 'x' }, { delivered: 1, provider_response_id: 'x' }, { delivered: true, provider_response_id: '' }, { delivered: true, provider_response_id: 0 }, { delivered: true, provider_response_id: {} }, { delivered: true, provider_response_id: null }, { ok: true }, {}, null, 'delivered'])
    assert.equal((await mk(res).send('x')).message.state, 'FAILED', JSON.stringify(res));
  assert.equal((await mk({ delivered: true, provider_response_id: 42 }).send('x')).message.state, 'SENT');
});
test('a response that arrives after the timeout cannot flip FAILED to SENT', async () => {
  const ob = O.createOutbox({ timeoutMs: 20, connector: connected(() => new Promise(r => setTimeout(() => r({ delivered: true, provider_response_id: 'late' }), 80))) });
  const m = (await ob.send('x')).message; assert.equal(m.state, 'FAILED'); await new Promise(r => setTimeout(r, 120)); assert.equal(m.state, 'FAILED'); assert.equal(m.providerResponseId, null);
});
test('retry on SENT never calls send again; QUEUED is the visible state when the connector is called', async () => {
  let calls = 0, stateAtCall = null; let ob;
  ob = O.createOutbox({ connector: connected(async () => { calls++; stateAtCall = ob.list()[0].state; return { delivered: true, provider_response_id: 'r' }; }) });
  const { message } = await ob.send('x'); assert.equal(stateAtCall, 'QUEUED'); assert.equal(message.state, 'SENT');
  assert.equal(await ob.retry(message.id), null); assert.equal(calls, 1);
});
test('a connector whose connected() throws yields NOT_CONNECTED (no unhandled rejection)', async () => {
  const ob = O.createOutbox({ connector: { connected() { throw new Error('boom'); }, send: async () => ({ delivered: true, provider_response_id: 'r' }) } });
  const r = await ob.send('x'); assert.equal(r.message.state, 'NOT_CONNECTED'); assert.match(r.message.reason, /boom/);
  const ob2 = O.createOutbox({ connector: { connected: () => ({ ok: 'yes' }), send: async () => ({ delivered: true, provider_response_id: 'r' }) } });
  assert.equal((await ob2.send('x')).message.state, 'NOT_CONNECTED', 'connected() must be exactly ok:true');
});
test('approvals: connector must return ok === true; truthy values and thrown supports() never claim "source"', async () => {
  const item = { provider: 'gpt', key: 'gpt:t:e' };
  for (const ok of ['yes', 1, {}, 'true']) { const r = await O.decide(item, 'approve', { supports: () => true, apply: async () => ({ ok }) }); assert.equal(r.scope, 'none', JSON.stringify(ok)); assert.equal(r.decision, null); }
  const t = await O.decide(item, 'approve', { supports: () => { throw new Error('x'); } }); assert.equal(t.scope, 'local'); assert.doesNotMatch(t.label, /at source/);
  const s = await O.decide(item, 'approve', { supports: () => 'yes', apply: async () => ({ ok: true }) }); assert.equal(s.scope, 'local', 'supports() must be exactly true');
});
test('approval decisions are per request: same task, new event => new key; reconnect replay => same key', () => {
  const a = O.pendingApprovals([evt({ event_id: 'req-1' })], now).gpt[0], b = O.pendingApprovals([evt({ event_id: 'req-2' })], now).gpt[0], a2 = O.pendingApprovals([evt({ event_id: 'req-1' })], now).gpt[0];
  assert.notEqual(a.key, b.key); assert.equal(a.key, a2.key);
});
test('approvals: events for an unrecognised provider are never attributed to GPT/CODEX/CLAUDE', () => {
  assert.deepEqual(O.pendingApprovals([evt({ provider: 'mistral' }), evt({ provider: 'local' })], now), { gpt: [], codex: [], claude: [] });
});
