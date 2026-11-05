// Live-dashboard check against the REAL adapter (Windows) - read-only; starts server.py WITHOUT a token on a loopback port.
//   node tools/live_check_windows.mjs                 # Windows: expects CPU/RAM/DISK known, GPU/TEMP UNKNOWN
//   node tools/live_check_windows.mjs --expect-unknown  # non-Windows host: expects everything UNKNOWN (checks the checker only)
// Needs Playwright (npm i -g playwright / already installed); if it is missing the browser part is reported NOT_RUN.
//   --ready-timeout-ms N            how long to wait for the server (default 15000)
//   --base http://127.0.0.1:PORT   use an already running server instead of starting one (used to test failure handling)
// Prints values only; no tokens, no environment. Exit 0 = PASS, 1 = FAIL (incl. request failure/crash), 3 = browser part NOT_RUN, 4 = NOT_RUN (server did not start).
// HTTP uses node:http with Connection: close (not the global fetch/undici, whose parser can assert on Node 24); every failure is reported, never an uncaught crash.
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const expectUnknown = process.argv.includes('--expect-unknown');
const baseArg = process.argv.indexOf('--base') > 0 ? process.argv[process.argv.indexOf('--base') + 1] : null;
const PORT = 4195, BASE = baseArg || `http://127.0.0.1:${PORT}`;
let stderrTail = ''; let finished = false;
const finish = (code, line) => { if (finished) return; finished = true; if (code !== 0 && stderrTail.trim()) console.log('--- server stderr (last 2 kB; request log lines are normal) ---\n' + stderrTail.slice(-2048).trim() + '\n--- end ---'); console.log(line); try { server?.kill(); } catch { /* ignore */ } process.exit(code); };
process.on('uncaughtException', e => finish(1, `FAIL: uncaught ${e && e.name}: ${String(e && e.message).split('\n')[0]} (checker error, no hardware result is claimed)`));
process.on('unhandledRejection', e => finish(1, `FAIL: unhandled rejection: ${String(e && e.message || e).split('\n')[0]} (no hardware result is claimed)`));
/** GET a loopback URL with node:http, Connection: close, 10 s timeout, 2 MB cap. Rejects with a plain Error on any failure. */
const get = (url) => new Promise((resolve, reject) => {
  const req = http.get(url, { agent: false, headers: { Connection: 'close', Accept: 'application/json' }, timeout: 10000 }, res => {
    let size = 0; const chunks = [];
    res.on('data', c => { size += c.length; if (size > 2e6) { req.destroy(new Error('response too large')); return; } chunks.push(c); });
    res.on('end', () => resolve({ status: res.statusCode, text: Buffer.concat(chunks).toString('utf8') }));
    res.on('error', reject);
  });
  req.on('timeout', () => req.destroy(new Error('request timed out')));
  req.on('error', e => reject(new Error(`${url}: ${e.code || ''} ${e.message}`.trim())));
});
const getJson = async url => { const r = await get(url); if (r.status !== 200) throw new Error(`${url}: HTTP ${r.status}`); try { return JSON.parse(r.text); } catch { throw new Error(`${url}: response was not JSON`); } };
const fails = []; const note = (ok, msg) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${msg}`); if (!ok) fails.push(msg); };
const env = { ...process.env, HIVE_API_TOKEN: '' }; // no token: this check never uses or prints one
const server = baseArg ? null : spawn(process.platform === 'win32' ? 'python' : 'python3', ['server.py', '--port', String(PORT)], { cwd: root, stdio: ['ignore', 'ignore', 'pipe'], env });
if (server) { server.stderr.on('data', d => { stderrTail = (stderrTail + d.toString('utf8')).slice(-8192); }); server.on('error', e => finish(4, `NOT_RUN: could not start server.py (${e.code || e.message})`)); server.on('exit', c => { if (!finished && !ready) finish(4, `NOT_RUN: server.py exited early (code ${c})`); }); }
const stop = () => { try { server?.kill(); } catch { /* ignore */ } };
process.on('exit', stop);
let ready = false;
const waitMs = process.argv.includes('--ready-timeout-ms') ? Number(process.argv[process.argv.indexOf('--ready-timeout-ms') + 1]) || 15000 : 15000;
for (let i = 0; i < Math.max(1, Math.round(waitMs / 150)) && !ready; i++) { try { ready = (await get(BASE + '/')).status === 200; } catch { /* retry */ } if (!ready) await new Promise(r => setTimeout(r, 150)); }
if (!ready) finish(4, `NOT_RUN: the dashboard server did not answer at ${BASE} within ${Math.round(waitMs / 1000)} s`);

let exit = 0;
try {
  // --- API: the data the dashboard receives
  const sys = await getJson(BASE + '/api/system/resources');
  const items = sys.items, ev = sys.evidence;
  console.log(`evidence: ${ev.validity} source=${ev.source} observed_at=${ev.observed_at}`);
  for (const k of ['cpu', 'memory', 'disk', 'gpu', 'temperature']) console.log(`api ${k}: validity=${items[k].validity} value=${items[k].value} source=${items[k].source} observed_at=${items[k].observed_at} reason=${items[k].reason}`);
  note(!/fixture/i.test(JSON.stringify(sys)), 'API response contains no fixture marker (live mode)');
  for (const k of ['cpu', 'memory', 'disk']) {
    const m = items[k];
    if (expectUnknown) note(m.validity === 'unavailable' && m.value === null && !!m.reason, `${k} UNKNOWN with a reason`);
    else note(m.validity === 'valid' && typeof m.value === 'number' && m.value >= 0 && m.value <= 100 && !!m.source && !!m.observed_at, `${k} valid with source and observed_at`);
  }
  for (const k of ['gpu', 'temperature']) note(items[k].validity === 'unavailable' ? items[k].value === null && !!items[k].reason : items[k].source === 'nvidia-smi', `${k} UNKNOWN (or valid only from nvidia-smi)`);
  const snap = await getJson(BASE + '/api/dashboard/snapshot');

  // --- Browser
  let chromium;
  try { ({ chromium } = createRequire(import.meta.url)('playwright')); } catch { chromium = null; }
  if (!chromium) { console.log('NOT_RUN: Playwright is not installed; browser checks skipped'); exit = fails.length ? 1 : 3; }
  else {
    const browser = await chromium.launch();
    try {
      for (const vp of [{ width: 1280, height: 720 }, { width: 1920, height: 1080 }]) {
        const tag = `${vp.width}x${vp.height}`; const ctx = await browser.newContext({ viewport: vp }); const p = await ctx.newPage();
        const errors = []; p.on('pageerror', e => errors.push('pageerror: ' + e)); p.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); }); p.on('requestfailed', r => { if (r.url().startsWith(BASE) && !r.url().endsWith('/api/events/stream')) errors.push('requestfailed: ' + r.url()); });
        await p.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
        await p.waitForFunction(() => document.querySelectorAll('#resource-gauges .gauge').length === 5 && document.querySelectorAll('#limit-rows .limit-row').length === 4, null, { timeout: 15000 });
        await p.waitForTimeout(2500);
        const g = await p.$$eval('#resource-gauges .gauge', gs => gs.map(x => ({ k: x.dataset.k, st: x.dataset.status, ring: x.querySelector('text').textContent, glyph: !!x.querySelector('.g-glyph'), cap: x.querySelector('.g-sub').textContent })));
        console.log(`[${tag}] gauges: ` + g.map(x => `${x.k}=${x.st}(${x.ring}${x.glyph ? ',?glyph' : ''})`).join(' '));
        for (const x of g) {
          const known = ['cpu', 'ram', 'disk'].includes(x.k) && !expectUnknown;
          note(x.st === (known ? 'KNOWN' : 'UNKNOWN'), `[${tag}] ${x.k} gauge is ${known ? 'KNOWN' : 'UNKNOWN'}`);
          if (known) note(/^\d+(\.\d+)? ?%$/.test(x.ring), `[${tag}] ${x.k} ring shows a percentage (${x.ring})`);
        }
        note(g.filter(x => ['gpu', 'temp'].includes(x.k)).every(x => x.st === 'UNKNOWN' && x.glyph), `[${tag}] GPU and TEMP show the UNKNOWN ? glyph`);
        const apiPct = { cpu: items.cpu.value, ram: items.memory.value, disk: items.disk.value };
        if (!expectUnknown) for (const k of ['cpu', 'ram', 'disk']) { const shown = parseFloat(g.find(x => x.k === k).ring); note(Math.abs(shown - apiPct[k]) <= 15, `[${tag}] ${k} gauge ${shown}% is consistent with the API value ${apiPct[k]}% (live values move between polls)`); }
        const layout = await p.evaluate(() => { const out = []; const box = id => document.querySelector(id).getBoundingClientRect();
          for (const id of ['#panel-resources', '#panel-limits']) { const pr = box(id); document.querySelectorAll(id + ' .gauge, ' + id + ' .limit-row, ' + id + ' .sys-summary').forEach(e => { const r = e.getBoundingClientRect(); if (r.width && (r.right > pr.right + 1 || r.left < pr.left - 1 || r.bottom > pr.bottom + 1 || r.top < pr.top - 1)) out.push(id + ' clipped: ' + e.className); }); }
          const gs = [...document.querySelectorAll('#resource-gauges .gauge')].map(x => x.getBoundingClientRect()); for (let i = 0; i < gs.length - 1; i++) if (gs[i].right > gs[i + 1].left + 1) out.push('gauges overlap');
          const sum = document.querySelector('#sys-summary'); if (sum.scrollHeight > sum.clientHeight + 1) out.push('sys-summary truncated: ' + sum.innerText.replace(/\s+/g, ' ').slice(0, 120));
          const dev = document.querySelector('#devices-state'); const dr = dev.getBoundingClientRect(); if (!dev.textContent.trim()) out.push('Local Devices text empty'); if (dr.left < 0 || dr.right > innerWidth || dr.top < 0 || dr.bottom > innerHeight) out.push('Local Devices label outside the viewport');
          return { out, devices: document.querySelector('#devices-state').textContent.trim(), summary: sum.innerText.replace(/\s+/g, ' ').trim() }; });
        console.log(`[${tag}] Local Devices: "${layout.devices}" | summary: "${layout.summary.slice(0, 140)}"`);
        note(layout.out.length === 0, `[${tag}] System Resources / Local Devices not clipped or overlapping` + (layout.out.length ? ': ' + layout.out.join('; ') : ''));
        // model limits: every DOM row must equal what the API reports (nothing invented)
        const rows = await p.$$eval('#limit-rows .limit-row', rs => rs.map(r => ({ p: r.dataset.p, st: r.dataset.status, text: r.textContent.replace(/\s+/g, ' ').trim() })));
        const api = (snap.model_limits && snap.model_limits.items) || [];
        const same = rows.every(r => { const a = api.find(x => x.provider === r.p); return a ? a.status === r.st : r.st === 'UNKNOWN'; });
        console.log(`[${tag}] limits: ` + rows.map(r => `${r.p || '?'}=${r.st}`).join(' '));
        note(same, `[${tag}] model-limit rows match the API statuses (no invented provider/model values)`);
        note(rows.every(r => r.st !== 'KNOWN' || api.some(a => a.provider === r.p && a.status === 'KNOWN')), `[${tag}] no KNOWN limit without an API record`);
        note(errors.length === 0, `[${tag}] no console/page errors` + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
        await ctx.close();
      }
    } finally { await browser.close(); }
    exit = fails.length ? 1 : 0;
  }
} catch (e) {
  fails.push('request/runtime failure: ' + String(e && e.message).split('\n')[0]); exit = 1;
} finally { stop(); }
finish(exit, exit === 0 ? 'PASS' : exit === 3 ? 'API PASS; browser NOT_RUN' : 'FAIL: ' + fails.join('; ') + (exit === 1 ? ' (a FAIL is never a hardware PASS)' : ''));
