// P1.1 E2E: system resources, USB/external disks, MTP/PTP phone, model limits.
// Fixture = synthetic data (validity "fixture"); live adapter on this host = honest UNKNOWN (non-Windows).
// Real Windows OS probing is NOT exercised here. Run: node --test tests/e2e/system.e2e.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const { chromium } = createRequire(import.meta.url)('playwright');
const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FIX = 'http://127.0.0.1:4188/', LIVE = 'http://127.0.0.1:4187/';
const procs = []; let browser;
async function up(args, url) {
  const p = spawn('python', args, { cwd: root, stdio: 'ignore', env: { ...process.env, HIVE_API_TOKEN: '' } }); procs.push(p);
  for (let i = 0; i < 60; i++) { try { if ((await fetch(url)).ok) return; } catch { /* retry */ } await new Promise(r => setTimeout(r, 100)); }
  throw new Error('server did not start');
}
test.before(async () => { await up(['fixture_server.py', '--port', '4188'], FIX); await up(['server.py', '--port', '4187'], LIVE); browser = await chromium.launch(); });
test.after(async () => { await browser?.close(); procs.forEach(p => p.kill()); });

async function open(url, vp = { width: 1920, height: 1080 }) {
  const ctx = await browser.newContext({ viewport: vp }); const p = await ctx.newPage(); const errors = []; p.on('pageerror', e => errors.push(String(e)));
  await p.goto(url, { waitUntil: 'domcontentloaded' });
  await p.waitForFunction(() => document.querySelectorAll('#resource-gauges .gauge').length === 5 && document.querySelectorAll('#limit-rows .limit-row').length === 4);
  return { p, errors, ctx };
}
const gauges = p => p.$$eval('#resource-gauges .gauge', gs => gs.map(g => ({ label: g.querySelector('label').textContent, text: g.querySelector('text').textContent, unknown: g.classList.contains('unknown'), sub: g.querySelector('.g-sub')?.textContent || null })));
const limits = p => p.$$eval('#limit-rows .limit-row', rs => rs.map(r => ({ label: r.querySelector('strong').textContent, status: r.dataset.status, text: r.querySelector('.v').textContent, fill: r.querySelector('.bar span').style.width })));

test('fixture: OS gauges show real fixture values, GPU/TEMP stay UNKNOWN, disk shows free space', async () => {
  const { p, errors, ctx } = await open(FIX);
  await p.waitForFunction(() => document.querySelector('#resource-gauges .gauge text')?.textContent !== 'UNKNOWN', null, { timeout: 8000 });
  const g = await gauges(p);
  assert.deepEqual(g.map(x => x.text), ['17 %', '44 %', '63 %', 'UNKNOWN', 'UNKNOWN']);
  assert.deepEqual(g.map(x => x.unknown), [false, false, false, true, true]);
  assert.match(g[2].sub, /C:\\ 370 GB free/); assert.match(g[1].sub, /GB \/ .* GB/);
  assert.match(await p.$eval('#env-tag', e => e.textContent), /FIXTURE/i, 'synthetic values are labelled');
  assert.deepEqual(errors, []); await ctx.close();
});

test('fixture: external disk with free space; phone (MTP/PTP) says Storage metrics unavailable and is not a disk', async () => {
  const { p, ctx } = await open(FIX);
  await p.waitForFunction(() => /E:\\/.test(document.querySelector('#sys-summary')?.textContent || ''), null, { timeout: 8000 });
  const sum = await p.$eval('#sys-summary', e => e.textContent);
  assert.match(sum, /USB 2/); assert.match(sum, /E:\\ 1 TB, 620 GB free/); assert.match(sum, /Fixture Phone: MTP\/PTP · Storage metrics unavailable/);
  assert.doesNotMatch(sum, /Fixture Phone.*(GB|TB)/);
  assert.equal(await p.$eval('#devices-state', e => e.textContent), '2 USB · 1 EXT DISK');
  await p.click('#console-open'); await p.click('.nav-item[data-view="system"]');
  const rows = await p.$$eval('#system-devices .rail-row', r => r.map(x => x.innerText.replace(/\s+/g, ' ')));
  assert.ok(rows.some(r => /E:\\ Fixture External SSD.*external.*Read\/Write.*1 TB.*620 GB free/.test(r)), rows.join(' | '));
  const phone = rows.find(r => /Fixture Phone/.test(r)); assert.match(phone, /not a disk/); assert.match(phone, /Storage metrics unavailable/); assert.doesNotMatch(phone, /\d (GB|TB)/);
  assert.equal(rows.filter(r => /external|fixed|removable/.test(r)).length, 2, 'only the two real volumes are listed as disks');
  await ctx.close();
});

test('fixture: model limits show all four statuses with honest text; no provider is privileged', async () => {
  const { p, ctx } = await open(FIX);
  await p.waitForFunction(() => document.querySelector('#limit-rows .limit-row[data-status="KNOWN"]'), null, { timeout: 8000 });
  const l = await limits(p);
  assert.deepEqual(l.map(x => x.label), ['GPT', 'CLAUDE', 'CODEX', 'LOCAL']);
  assert.deepEqual(l.map(x => x.status), ['KNOWN', 'ESTIMATED', 'NOT_PROVIDED', 'UNKNOWN']);
  assert.equal(l[0].text, 'Limit 100K · Avail 61K · KNOWN'); assert.equal(l[0].fill, '61%');
  assert.equal(l[1].text, 'Limit ~100K · Avail ~40K · ESTIMATED'); assert.equal(l[1].fill, '40%');
  assert.equal(l[2].text, 'Limit: NOT_PROVIDED'); assert.equal(l[2].fill, '0%'); assert.equal(l[3].text, 'Limit: UNKNOWN'); assert.equal(l[3].fill, '0%');
  assert.equal(await p.$eval('#limit-rows .limit-row[data-status="ESTIMATED"] .bar', e => e.classList.contains('est')), true, 'estimates are drawn differently from known values');
  await ctx.close();
});

test('live adapter on a non-Windows host: every resource is UNKNOWN, devices UNKNOWN, limits UNKNOWN (nothing invented)', async () => {
  const { p, errors, ctx } = await open(LIVE);
  await p.waitForTimeout(1500);
  assert.deepEqual((await gauges(p)).map(x => x.text), ['UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN']);
  assert.ok((await gauges(p)).every(x => x.unknown && x.sub === null));
  const sum = await p.$eval('#sys-summary', e => e.textContent); assert.match(sum, /UNKNOWN/); assert.match(sum, /Windows/); assert.doesNotMatch(sum, /USB 0|\b0 USB/, 'a failed probe must never read as zero devices');
  assert.equal(await p.$eval('#devices-state', e => e.textContent), 'UNKNOWN');
  const l = await limits(p); assert.ok(l.every(x => x.status === 'UNKNOWN' && x.text === 'Limit: UNKNOWN' && x.fill === '0%'), JSON.stringify(l));
  assert.doesNotMatch(await p.$eval('#panel-resources', e => e.innerText), /\d\s?%|°C/, 'no number appears without a source');
  assert.deepEqual(errors, []); await ctx.close();
});

test('layout: resources and limits panels do not clip or overlap at 1280x720 and 2560x1440', async () => {
  for (const vp of [{ width: 1280, height: 720 }, { width: 2560, height: 1440 }]) {
    const { p, ctx } = await open(FIX, vp);
    await p.waitForFunction(() => /E:\\/.test(document.querySelector('#sys-summary')?.textContent || ''), null, { timeout: 8000 });
    const bad = await p.evaluate(() => { const out = [];
      for (const id of ['#panel-resources', '#panel-limits']) { const pr = document.querySelector(id).getBoundingClientRect();
        document.querySelectorAll(id + ' .gauge, ' + id + ' .limit-row, ' + id + ' .sys-summary, ' + id + ' svg').forEach(e => { const r = e.getBoundingClientRect(); if (r.width && (r.right > pr.right + 1 || r.left < pr.left - 1 || r.bottom > pr.bottom + 1 || r.top < pr.top - 1)) out.push(id + ' clipped: ' + (e.className.baseVal ?? e.className)); }); }
      const gs = [...document.querySelectorAll('#resource-gauges .gauge')].map(g => g.getBoundingClientRect());
      for (let i = 0; i < gs.length - 1; i++) if (gs[i].right > gs[i + 1].left + 1) out.push('gauges overlap');
      document.querySelectorAll('#limit-rows .limit-row').forEach(r => { const kids = [...r.children].map(k => k.getBoundingClientRect()); for (let i = 0; i < kids.length - 1; i++) if (kids[i].right > kids[i + 1].left + 1) out.push('limit row collision'); if (r.scrollWidth > r.clientWidth + 1) out.push('limit row overflow'); });
      return out; });
    assert.deepEqual(bad, [], `${vp.width}x${vp.height}`);
    const full = await p.$eval('#sys-summary', e => ({ cut: e.scrollHeight > e.clientHeight + 1, shown: e.innerText }));
    assert.equal(full.cut, false, `summary truncated at ${vp.width}x${vp.height}: ${full.shown}`); assert.match(full.shown, /Storage metrics unavailable/);
    assert.ok((await p.$eval('#hive-core-art', e => e.getBoundingClientRect().height)) >= vp.height * 0.35, 'CORE still dominant');
    await p.screenshot({ path: join(root, 'docs/hive/screenshots', `system-fixture-${vp.width}x${vp.height}.png`) });
    await ctx.close();
  }
});
