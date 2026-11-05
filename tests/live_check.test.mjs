// Failure-handling tests for tools/live_check_windows.mjs (Node 24 / undici crash regression).
// The checker must always end with a meaningful FAIL or NOT_RUN line and a non-zero exit, never an uncaught assertion.
// Run: node --test tests/live_check.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const TOOL = join(root, 'tools/live_check_windows.mjs');
const run = (args, pre = []) => new Promise(res => { const p = spawn(process.execPath, [...pre, ...args], { cwd: root, env: { ...process.env, HIVE_API_TOKEN: '' } }); let out = ''; p.stdout.on('data', d => { out += d; }); p.stderr.on('data', d => { out += d; }); p.on('close', code => res({ code, out })); });
const rogue = (handler) => new Promise(res => { const s = net.createServer(sock => { sock.on('error', () => {}); sock.once('data', () => handler(sock)); }); s.listen(0, '127.0.0.1', () => res(s)); });
const last = out => out.trim().split('\n').pop();

test('server never answers: NOT_RUN (exit 4), no crash', async () => {
  const r = await run([TOOL, '--base', 'http://127.0.0.1:1', '--ready-timeout-ms', '600']);
  assert.equal(r.code, 4); assert.match(last(r.out), /^NOT_RUN: the dashboard server did not answer/);
});
test('HTTP 500 and malformed/half responses: FAIL (exit 1) or NOT_RUN, never an uncaught error', async () => {
  let n = 0;
  const s500 = await rogue(sock => { sock.end(n++ === 0 ? 'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok' : 'HTTP/1.1 500 X\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'); });
  const r = await run([TOOL, '--base', `http://127.0.0.1:${s500.address().port}`]); s500.close();
  assert.equal(r.code, 1); assert.match(last(r.out), /^FAIL: request\/runtime failure: .*HTTP 500/); assert.doesNotMatch(r.out, /AssertionError|undici/);
  for (const reply of ['NOT HTTP AT ALL\r\n\r\n', 'HTTP/1.1 200 OK\r\nContent-Length: 500\r\n\r\n{"items":']) {
    const s = await rogue(sock => { sock.write(reply); setTimeout(() => sock.destroy(), 50); });
    const x = await run([TOOL, '--base', `http://127.0.0.1:${s.address().port}`, '--ready-timeout-ms', '600']); s.close();
    assert.ok([1, 4].includes(x.code), `exit ${x.code}`); assert.match(last(x.out), /^(FAIL|NOT_RUN):/); assert.doesNotMatch(x.out, /AssertionError|undici/);
  }
});
test('an uncaught assertion inside the checker (undici-style) becomes FAIL, exit 1, and the server it started is stopped', async () => {
  const wrapper = "process.argv=[process.argv[0],'tools/live_check_windows.mjs','--expect-unknown'];setTimeout(()=>{const e=new Error('The expression evaluated to a falsy value: assert(!this.paused)');e.name='AssertionError [ERR_ASSERTION]';process.nextTick(()=>{throw e;});},1200);await import(" + JSON.stringify(TOOL.replace(/\\/g, '/')) + ');';
  const r = await run(['--input-type=module', '-e', wrapper]);
  assert.equal(r.code, 1); assert.match(last(r.out), /^FAIL: uncaught AssertionError.*no hardware result is claimed/);
  await new Promise(r2 => setTimeout(r2, 500));
  await assert.rejects(() => new Promise((ok, no) => { const c = net.connect(4195, '127.0.0.1'); c.on('connect', () => { c.destroy(); ok(); }); c.on('error', no); }), 'server on 4195 must be stopped');
});
test('the failing paths never read as PASS', async () => {
  const r = await run([TOOL, '--base', 'http://127.0.0.1:1', '--ready-timeout-ms', '300']);
  assert.doesNotMatch(r.out, /^PASS$/m);
});

test('a probe timeout reported by the API is a FAIL naming the timeout (not a valid UNKNOWN); browser phase is skipped', async () => {
  const http = await import('node:http');
  const unk = { value: null, unit: '%', validity: 'unavailable', source: 'local:os-probe', observed_at: null, reason: 'OS probe timed out after 8 s (finished: cpu; stalled in: memory)' };
  const body = JSON.stringify({ items: { cpu: unk, memory: unk, disk: unk, gpu: unk, temperature: unk }, evidence: { source: 'windows:powershell', validity: 'unavailable', observed_at: '2026-11-05T00:00:00Z', reason: unk.reason, probe_ms: 8012, probe_completed: ['cpu'], probe_stalled_in: 'memory' } });
  const srv = http.createServer((req, res) => { res.writeHead(200, { 'Content-Type': 'application/json', Connection: 'close' }); res.end(req.url.startsWith('/api/system/resources') ? body : '{}'); });
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  const r = await run([TOOL, '--base', `http://127.0.0.1:${srv.address().port}`]); srv.close();
  assert.equal(r.code, 1); assert.match(r.out, /FAIL .*OS probe did not time out \(a timeout is a FAILURE of the probe, never a valid UNKNOWN\)/);
  assert.match(r.out, /stalled_in=memory/); assert.match(r.out, /browser checks skipped/); assert.match(last(r.out), /^FAIL:/); assert.doesNotMatch(r.out, /^PASS$/m);
});

test('a slow /api/dashboard/snapshot with valid system metrics is reported as SNAPSHOT SLOW (exit 6), not as a System Resources FAIL and not as PASS', async () => {
  const http = await import('node:http');
  const ok = { value: 41, unit: '%', validity: 'valid', source: 'windows:powershell/x', observed_at: '2026-11-05T00:00:00Z', reason: null };
  const unk = { value: null, unit: '%', validity: 'unavailable', source: 'none', observed_at: null, reason: 'no reliable local source' };
  const body = JSON.stringify({ items: { cpu: ok, memory: ok, disk: ok, gpu: unk, temperature: unk }, evidence: { source: 'windows:powershell', validity: 'valid', observed_at: '2026-11-05T00:00:00Z', reason: null, probe_ms: 4500, probe_timings_ms: { cpu: 500 } } });
  const srv = http.createServer((req, res) => { const send = () => { res.writeHead(200, { 'Content-Type': 'application/json', Connection: 'close' }); res.end(req.url.startsWith('/api/system/resources') ? body : '{}'); }; if (req.url.startsWith('/api/dashboard/snapshot')) setTimeout(send, 700); else send(); });
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  const r = await run([TOOL, '--base', `http://127.0.0.1:${srv.address().port}`, '--skip-browser', '--snapshot-warn-ms', '300']); srv.close();
  assert.equal(r.code, 6, r.out); assert.match(last(r.out), /^SYSTEM PASS but SNAPSHOT SLOW \(\d+ ms > 300 ms\).*separate finding/); assert.match(r.out, /SLOW .*diagnose_snapshot/);
  assert.doesNotMatch(r.out, /^PASS$/m); assert.doesNotMatch(r.out, /^FAIL/m);
});

// GPU/TEMP slow-tier contract: a pending first slow probe (validity=unknown) is an honest ?, not a failure; anything that
// would claim hardware data without nvidia-smi + observed_at, or a pending state with a value/timestamp, is a FAIL.
const slowCase = async (gpu, temperature, slow = 'pending') => {
  const http = await import('node:http');
  const ok = { value: 41, unit: '%', validity: 'valid', source: 'windows:powershell/x', observed_at: '2026-11-05T00:00:00Z', reason: null };
  const body = JSON.stringify({ items: { cpu: ok, memory: ok, disk: ok, gpu, temperature }, evidence: { source: 'windows:powershell', validity: 'valid', observed_at: '2026-11-05T00:00:00Z', reason: null },
    tiers: { fast: { state: 'fresh', attempts: [] }, slow: { state: slow, attempts: [] } }, diagnostics: {} });
  const srv = http.createServer((req, res) => { res.writeHead(200, { 'Content-Type': 'application/json', Connection: 'close' }); res.end(req.url.startsWith('/api/system/resources') ? body : '{}'); });
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  const r = await run([TOOL, '--base', `http://127.0.0.1:${srv.address().port}`, '--skip-browser']); srv.close();
  return r;
};
const pending = u => ({ value: null, unit: u, validity: 'unknown', source: 'windows:powershell (slow tier)', observed_at: null, reason: 'first slow probe in progress (started 4.9 s ago)', freshness: 'pending', age_s: null });
const unavail = u => ({ value: null, unit: u, validity: 'unavailable', source: 'none', observed_at: null, reason: 'no reliable local source' });
const nv = (v, u) => ({ value: v, unit: u, validity: 'valid', source: 'nvidia-smi', observed_at: '2026-11-05T00:00:00Z', reason: null });

test('GPU/TEMP pending first slow probe (unknown, null value, no observed_at, reason) is accepted: API PASS', async () => {
  for (const slow of ['pending', 'not_started']) {
    const r = await slowCase(pending('%'), pending('C'), slow);
    assert.equal(r.code, 3, r.out); assert.match(last(r.out), /^API PASS; browser NOT_RUN$/); assert.doesNotMatch(r.out, /^FAIL/m);
  }
});
test('GPU/TEMP unavailable with a reason, and valid nvidia-smi with observed_at, are accepted', async () => {
  for (const [g, t] of [[unavail('%'), unavail('C')], [nv(12, '%'), nv(48, 'C')], [nv(12, '%'), pending('C')]]) {
    const r = await slowCase(g, t);
    assert.equal(r.code, 3, r.out); assert.doesNotMatch(r.out, /^FAIL/m);
  }
});
test('GPU/TEMP fake or inconsistent states are a FAIL, never a PASS', async () => {
  const bad = [
    [{ ...pending('%'), value: 0 }, 'unknown with a value'],
    [{ ...pending('%'), observed_at: '2026-11-05T00:00:00Z' }, 'unknown with observed_at'],
    [{ ...pending('%'), reason: null }, 'unknown without a reason'],
    [{ ...unavail('%'), reason: '' }, 'unavailable without a reason'],
    [{ ...unavail('%'), value: 5 }, 'unavailable with a value'],
    [{ ...nv(12, '%'), source: 'windows:powershell/acpi' }, 'valid not from nvidia-smi'],
    [{ ...nv(12, '%'), observed_at: null }, 'valid nvidia-smi without observed_at'],
    [{ ...nv(12, '%'), value: null }, 'valid nvidia-smi without a value'],
    [{ ...pending('%'), validity: 'stale' }, 'unrecognised validity'],
  ];
  for (const [gpu, label] of bad) {
    const r = await slowCase(gpu, unavail('C'));
    assert.equal(r.code, 1, `${label}: ${r.out}`); assert.match(r.out, /FAIL gpu UNKNOWN/, label); assert.match(last(r.out), /^FAIL:/, label); assert.doesNotMatch(r.out, /^(API )?PASS/m, label);
  }
  // unknown is only legitimate while the slow tier has not produced its first result
  const r = await slowCase(pending('%'), pending('C'), 'fresh');
  assert.equal(r.code, 1, r.out); assert.match(r.out, /FAIL temperature UNKNOWN.*slow tier=fresh/);
});

test('Playwright missing or Chromium not launchable is NOT_RUN (exit 3) with the install hint, never a FAIL and never a PASS', async () => {
  const http = await import('node:http');
  const ok = { value: 41, unit: '%', validity: 'valid', source: 'windows:powershell/x', observed_at: '2026-11-05T00:00:00Z', reason: null };
  const unk = { value: null, unit: '%', validity: 'unavailable', source: 'none', observed_at: null, reason: 'no reliable local source' };
  const body = JSON.stringify({ items: { cpu: ok, memory: ok, disk: ok, gpu: unk, temperature: unk }, evidence: { source: 'windows:powershell', validity: 'valid', observed_at: '2026-11-05T00:00:00Z', reason: null } });
  const srv = http.createServer((req, res) => { res.writeHead(200, { 'Content-Type': 'application/json', Connection: 'close' }); res.end(req.url.startsWith('/api/system/resources') ? body : '{}'); });
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  // a browser-path that does not exist makes chromium.launch() fail when Playwright is installed; when it is not installed the require fails: both are NOT_RUN
  const child = spawn(process.execPath, [TOOL, '--base', `http://127.0.0.1:${srv.address().port}`], { cwd: root, env: { ...process.env, HIVE_API_TOKEN: '', PLAYWRIGHT_BROWSERS_PATH: join(root, 'no-such-browser-dir') } });
  let out = ''; child.stdout.on('data', d => { out += d; }); child.stderr.on('data', d => { out += d; });
  const code = await new Promise(res => child.on('close', res)); srv.close();
  assert.equal(code, 3, out); assert.match(out, /NOT_RUN: (Playwright is not installed|Chromium could not be launched)/);
  assert.match(out, /npm install --no-save --no-package-lock playwright@1\.63\.0/); assert.match(out, /npx playwright install chromium/);
  assert.match(last(out), /^API PASS; browser NOT_RUN$/); assert.doesNotMatch(out, /^PASS$/m); assert.doesNotMatch(out, /^FAIL/m);
});
