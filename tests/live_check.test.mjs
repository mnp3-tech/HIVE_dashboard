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
