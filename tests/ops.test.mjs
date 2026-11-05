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

/* ======== P1.1 view helpers: resources, devices, model limits ======== */
test('formatBytes / formatCount: decimal units, invalid input => null', () => {
  assert.equal(O.formatBytes(1.31e12), '1.31 TB'); assert.equal(O.formatBytes(370e9), '370 GB'); assert.equal(O.formatBytes(0), '0 B'); assert.equal(O.formatBytes(1500), '1.5 KB');
  for (const bad of [-1, NaN, Infinity, '5', null, undefined, true]) assert.equal(O.formatBytes(bad), null, String(bad));
  assert.equal(O.formatCount(100000), '100K'); assert.equal(O.formatCount(999), '999'); assert.equal(O.formatCount(-1), null); assert.equal(O.formatCount('x'), null);
});
test('resourceViews: nothing known => five UNKNOWN gauges, never zero', () => {
  for (const v of O.resourceViews(null, null)) { assert.equal(v.known, false); assert.equal(v.text, 'UNKNOWN'); assert.equal(v.pct, null); }
  assert.deepEqual(O.resourceViews(null, null).map(v => v.label), ['CPU', 'RAM', 'DISK', 'GPU', 'TEMP']);
});
test('resourceViews: OS value preferred; Core metric only if valid percent; stale/other rejected', () => {
  const os = { items: { cpu: { value: 17, unit: '%', validity: 'valid', source: 'windows:powershell' } } };
  assert.equal(O.resourceViews(os, { cpu: { value: 90, unit: '%', validity: 'valid' } })[0].from, 'os');
  assert.equal(O.resourceViews(os, null)[0].text, '17 %');
  const core = O.resourceViews(null, { cpu: { value: 55, unit: '%', validity: 'valid', source: 'hive' } })[0]; assert.equal(core.from, 'hive-core'); assert.equal(core.text, '55 %');
  for (const m of [{ value: 55, unit: '%', validity: 'stale' }, { value: 55, unit: '%', validity: 'unavailable' }, { value: 55, unit: '%', validity: 'unknown' }, { value: 55, unit: 'GB', validity: 'valid' }, { value: null, unit: '%', validity: 'valid' }, { value: '55', unit: '%', validity: 'valid' }])
    assert.equal(O.resourceViews(null, { cpu: m })[0].known, false, JSON.stringify(m));
});
test('resourceViews: OS values with invalid validity/range/units are rejected; fixture is accepted', () => {
  const mk = (cpu, extra) => O.resourceViews({ items: { cpu: Object.assign({ unit: '%', validity: 'valid' }, cpu) } }, null)[0];
  assert.equal(mk({ value: 101 }).known, false); assert.equal(mk({ value: -1 }).known, false); assert.equal(mk({ value: 0 }).known, true, 'zero is a real value');
  assert.equal(mk({ value: 5, validity: 'unavailable' }).known, false); assert.equal(mk({ value: 5, validity: 'fixture' }).known, true); assert.equal(mk({ value: 5, unit: 'furlongs' }).known, false);
  const temp = O.resourceViews({ items: { temperature: { value: 46.2, unit: 'C', validity: 'valid' } } }, null)[4]; assert.equal(temp.text, '46 °C');
  assert.equal(O.resourceViews({ items: { temperature: { value: 400, unit: 'C', validity: 'valid' } } }, null)[4].known, false);
});
test('resourceViews: sublabels (disk free space, RAM used/total) only from real numbers', () => {
  const v = O.resourceViews({ items: { disk: { value: 60, unit: '%', validity: 'valid', drive: 'C:\\', free_bytes: 400e9 }, memory: { value: 75, unit: '%', validity: 'valid', used_bytes: 12e9, total_bytes: 16e9 } } }, null);
  assert.equal(v[2].sub, 'C:\\ 400 GB free'); assert.equal(v[1].sub, '12 GB / 16 GB');
  assert.equal(O.resourceViews({ items: { disk: { value: 60, unit: '%', validity: 'valid', free_bytes: 'lots' } } }, null)[2].sub, null);
});
test('deviceSummary: external disks with free space; MTP/PTP phone says Storage metrics unavailable and is not a disk', () => {
  const sys = { items: { usb_known: true, disks_known: true, disks: [{ id: 'C:\\', kind: 'fixed', validity: 'valid', total_bytes: 1e12, free_bytes: 4e11 }, { id: 'E:\\', kind: 'external', validity: 'valid', total_bytes: 2e12, free_bytes: 1.31e12, access: 'Read/Write' }],
    usb: [{ name: 'USB Storage', kind: 'usb_device' }, { name: 'Pixel 8', kind: 'phone_mtp_ptp', protocol: 'MTP/PTP', storage_metrics: 'unavailable' }] } };
  const s = O.deviceSummary(sys);
  assert.match(s, /USB 2/); assert.match(s, /E:\\ 2 TB, 1\.31 TB free/); assert.doesNotMatch(s, /Read\/Write/, 'access mode lives in the console list'); assert.match(s, /Pixel 8: MTP\/PTP · Storage metrics unavailable/); assert.doesNotMatch(s, /C:\\/, 'fixed system disk is not an external disk');
  assert.doesNotMatch(s, /Pixel 8.*\d+ (GB|TB)/, 'phone has no size');
  assert.equal(O.deviceSummary(null), null); assert.equal(O.deviceSummary({ error: 'x', items: {} }), null);
  // empty-but-unknown is not zero
  assert.equal(O.deviceSummary({ items: { usb: [], disks: [], usb_known: false, disks_known: false } }), null);
  assert.equal(O.devicesNodeText({ items: { usb: [], disks: [] } }), 'UNKNOWN');
  assert.match(O.deviceSummary({ items: { usb: [], disks: [], usb_known: false, disks_known: true } }), /USB UNKNOWN/);
  assert.equal(O.devicesNodeText({ items: { usb: [], disks: [], usb_known: true, disks_known: false } }), '0 USB · DISKS UNKNOWN');
  assert.equal(O.devicesNodeText({ items: { usb: [], disks: [], usb_known: true, disks_known: true } }), '0 USB · 0 EXT DISK', 'a successful empty probe really is zero');
  assert.equal(O.devicesNodeText(sys), '2 USB · 1 EXT DISK'); assert.equal(O.devicesNodeText(null), 'UNKNOWN');
  const bad = O.deviceSummary({ items: { usb_known: true, disks_known: true, disks: [{ id: 'F:\\', kind: 'removable', validity: 'unavailable', total_bytes: null, free_bytes: null }], usb: [] } }); assert.match(bad, /size unavailable/);
});
test('limitView: only KNOWN/ESTIMATED show numbers; others are status words; malformed numbers are rejected', () => {
  assert.equal(O.limitView({ label: 'GPT', status: 'KNOWN', limit: 200000, available: 187000 }).text, 'Limit 200K · Avail 187K · KNOWN');
  const est = O.limitView({ label: 'X', status: 'ESTIMATED', limit: 100000, available: 40000 }); assert.equal(est.text, 'Limit ~100K · Avail ~40K · ESTIMATED'); assert.equal(est.dashed, true); assert.equal(est.fill, 0.4); assert.equal(est.tone, 'warn');
  assert.equal(O.limitView({ label: 'C', status: 'NOT_PROVIDED', limit: 5 }).text, 'Limit: NOT_PROVIDED'); assert.equal(O.limitView({ label: 'L', status: 'UNKNOWN', limit: 5 }).text, 'Limit: UNKNOWN');
  assert.equal(O.limitView({ label: 'G', status: 'KNOWN', limit: 100, available: null }).text, 'Limit 100 · Avail n/a · KNOWN'); assert.equal(O.limitView({ label: 'G', status: 'KNOWN', limit: 100, available: null }).fill, null);
  for (const bad of [{ status: 'KNOWN', limit: 'x' }, { status: 'KNOWN', limit: -1 }, { status: 'KNOWN', limit: 10, available: 20 }, { status: 'KNOWN', limit: NaN }, { status: 'WEIRD', limit: 5 }, null, undefined, {}])
    assert.equal(O.limitView(bad).status === 'UNKNOWN' || O.limitView(bad).status === 'NOT_PROVIDED', true, JSON.stringify(bad)), assert.doesNotMatch(O.limitView(bad).text, /\d/, 'no number shown for ' + JSON.stringify(bad));
});
test('EMPTY_LIMITS: four equal UNKNOWN rows (no provider privileged)', () => {
  assert.deepEqual(O.EMPTY_LIMITS.map(r => r.label), ['GPT', 'CLAUDE', 'CODEX', 'LOCAL']); assert.ok(O.EMPTY_LIMITS.every(r => r.status === 'UNKNOWN'));
});


/* ======== visual parity C: task-card row view models (truthful: no invented task, progress, context or version) ======== */
const snapT = (tasks, ev) => ({ tasks, tasksEvidence: ev === undefined ? { validity: 'valid', source: 'hive:/tasks' } : ev });
test('cards: without trusted task evidence both task cards are UNKNOWN (never "no tasks")', () => {
  for (const ev of [null, undefined, { validity: 'unavailable', reason: 'connection refused' }, { validity: 'auth_required' }, { validity: 'stale' }, { validity: 'unknown' }]) {
    const v = O.taskCardViews({ tasks: [{ status: 'active', title: 'x' }], tasksEvidence: ev }, null);
    assert.equal(v.current.text, 'UNKNOWN', JSON.stringify(ev)); assert.equal(v.next.text, 'UNKNOWN'); assert.equal(v.current.progress, null);
  }
  assert.equal(O.taskCardViews(null, null).current.text, 'UNKNOWN');
});
test('cards: valid evidence with no active/queued task says so explicitly', () => {
  const v = O.taskCardViews(snapT([{ status: 'completed', title: 'old' }]), null);
  assert.equal(v.current.text, 'NO ACTIVE TASK OBSERVED'); assert.equal(v.next.text, 'NONE OBSERVED');
  assert.equal(O.taskCardViews(snapT([]), null).current.text, 'NO ACTIVE TASK OBSERVED');
});
test('cards: active and queued tasks are shown from the records (redacted, clipped), first item wins', () => {
  const red = s => s.replace(/sk-[a-z0-9]+/g, '[REDACTED]');
  const v = O.taskCardViews(snapT([{ status: 'queued', title: 'Second' }, { status: 'active', title: 'Use sk-abc123def now', worker: 'w1', project_id: 'p1' }, { status: 'queued', title: 'Third' }, { status: 'active', title: 'Other active' }]), null, red);
  assert.equal(v.current.text, 'Use [REDACTED] now'); assert.equal(v.current.sub, 'w1 · p1'); assert.match(v.current.title, /\+1 more active/);
  assert.equal(v.next.text, 'Second'); assert.equal(v.next.sub, '2 queued');
  assert.ok(O.taskCardViews(snapT([{ status: 'active', title: 'x'.repeat(500) }]), null).current.text.length <= 60);
});
test('cards: a progress bar exists only for an explicit numeric progress_percent in 0..100', () => {
  const p = v => O.taskCardViews(snapT([{ status: 'active', title: 't', ...v }]), null).current.progress;
  assert.equal(p({}), null); assert.equal(p({ progress: 80 }), null, 'other field names are ignored'); assert.equal(p({ percent: 80 }), null);
  assert.equal(p({ progress_percent: 68 }), 68); assert.equal(p({ progress_percent: 0 }), 0); assert.equal(p({ progress_percent: 100 }), 100);
  for (const bad of ['68', '', null, true, false, NaN, Infinity, -1, 101, {}, [5]]) assert.equal(p({ progress_percent: bad }), null, JSON.stringify(bad));
});
test('cards: shared context shows only real memory evidence (no vault, version or invented counts)', () => {
  assert.equal(O.contextCardView(null).text, 'UNKNOWN'); assert.equal(O.contextCardView({ error: 'HTTP 500' }).text, 'UNKNOWN');
  assert.equal(O.contextCardView({ items: [] }).text, 'UNKNOWN', 'no evidence object');
  assert.equal(O.contextCardView({ evidence: { validity: 'unknown' } }).text, 'UNKNOWN');
  assert.equal(O.contextCardView({ evidence: { validity: 'unavailable', reason: 'registry file not found' } }).text, 'UNAVAILABLE');
  assert.equal(O.contextCardView({ evidence: { validity: 'auth_required' } }).text, 'AUTH REQUIRED');
  const ok = O.contextCardView({ items: [{ record_count: 2 }, { record_count: 1 }], evidence: { validity: 'valid', source: 'obsidian:registry' } });
  assert.equal(ok.text, 'CONTEXT READABLE'); assert.equal(ok.sub, '2 project(s) · 3 record(s) · read-only'); assert.equal(ok.tone, 'ok');
  const fx = O.contextCardView({ status: 'ready', project_count: 1, record_count: 3, evidence: { validity: 'fixture' } }); assert.equal(fx.sub, '1 project(s) · 3 record(s) · read-only');
  assert.equal(O.contextCardView({ evidence: { validity: 'valid' } }).sub, 'read-only', 'no counts => none shown');
  assert.equal(O.contextCardView({ project_count: 'many', record_count: -1, evidence: { validity: 'valid' } }).sub, 'read-only');
  assert.doesNotMatch(JSON.stringify(ok), /\bv\d|version|vault/i);
  assert.equal(O.obsidianNodeText(null), 'UNKNOWN'); assert.equal(O.obsidianNodeText({ evidence: { validity: 'unavailable' } }), 'UNAVAILABLE'); assert.equal(O.obsidianNodeText({ evidence: { validity: 'valid' } }), 'CONTEXT READABLE');
});
