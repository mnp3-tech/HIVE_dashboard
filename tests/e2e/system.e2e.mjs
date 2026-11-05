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
const gauges = p => p.$$eval('#resource-gauges .gauge', gs => gs.map(g => ({ label: g.querySelector('label').textContent, text: g.dataset.status === 'UNKNOWN' ? 'UNKNOWN' : g.querySelector('text').textContent, ring: g.querySelector('text').textContent, unknown: g.classList.contains('unknown'), sub: g.classList.contains('unknown') ? null : (g.querySelector('.g-sub')?.textContent || null) })));
const limits = p => p.$$eval('#limit-rows .limit-row', rs => rs.map(r => ({ label: r.querySelector('strong').textContent, status: r.dataset.status, text: r.querySelector('.v').textContent, fill: r.querySelector('.bar span').style.width })));

test('fixture: OS gauges show real fixture values, GPU/TEMP stay UNKNOWN, disk shows free space', async () => {
  const { p, errors, ctx } = await open(FIX);
  await p.waitForFunction(() => document.querySelector('#resource-gauges .gauge text')?.textContent !== 'UNKNOWN', null, { timeout: 8000 });
  const g = await gauges(p);
  assert.deepEqual(g.map(x => x.text), ['17 %', '44 %', '63 %', 'UNKNOWN', 'UNKNOWN']);
  assert.deepEqual(g.map(x => x.unknown), [false, false, false, true, true]);
  assert.match(g[2].sub, /C:\\ 370 GB free/); assert.match(g[1].sub, /^\d+(\.\d+)? \/ \d+(\.\d+)? GB$/); assert.ok(g.filter(x => x.unknown).every(x => x.ring === '?'), 'unknown rings show ? and the caption says UNKNOWN');
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

const TIP = 'UNKNOWN \u2014 no fresh telemetry';
test('compact GPU/TEMP gauges: neutral ? glyph, UNKNOWN kept in the DOM and accessibility tree, tooltip on hover and focus, 1280x720', async () => {
  const { p, errors, ctx } = await open(FIX, { width: 1280, height: 720 });
  await p.waitForFunction(() => document.querySelector('#resource-gauges .gauge text')?.textContent !== '?', null, { timeout: 8000 });
  const info = await p.$$eval('#resource-gauges .gauge', gs => gs.map(g => { const gl = g.querySelector('.g-glyph'); return { k: g.dataset.k, status: g.dataset.status, glyph: gl ? { text: gl.textContent, label: gl.getAttribute('aria-label'), role: gl.getAttribute('role'), tab: gl.tabIndex, tip: gl.dataset.tip, visibleUnknown: /UNKNOWN/.test(g.querySelector('.g-sub').textContent) } : null, ringLabel: g.querySelector('svg').getAttribute('aria-label') }; }));
  for (const k of ['gpu', 'temp']) { const g = info.find(x => x.k === k); assert.equal(g.status, 'UNKNOWN'); assert.equal(g.glyph.text, '?'); assert.equal(g.glyph.label, TIP); assert.equal(g.glyph.tip, TIP); assert.equal(g.glyph.role, 'img'); assert.equal(g.glyph.tab, 0); assert.equal(g.glyph.visibleUnknown, false); assert.match(g.ringLabel, /UNKNOWN/); }
  for (const k of ['cpu', 'ram', 'disk']) assert.equal(info.find(x => x.k === k).glyph, null, k + ' is known in the fixture and has no glyph');
  // accessibility tree exposes the UNKNOWN text
  const snap = await p.locator('#resource-gauges').ariaSnapshot(); assert.ok(snap.includes(TIP), snap);
  // hover shows the tooltip, leaving hides it
  await p.hover('.gauge[data-k="gpu"] .g-glyph'); assert.equal(await p.$eval('#gauge-tip', e => (e.hidden ? '' : e.textContent)), TIP);
  const box = await p.$eval('#gauge-tip', e => { const r = e.getBoundingClientRect(); return { l: r.left, r: r.right, t: r.top }; }); assert.ok(box.l >= 0 && box.r <= 1280 && box.t >= 0, JSON.stringify(box));
  await p.mouse.move(5, 5); assert.equal(await p.$eval('#gauge-tip', e => e.hidden), true);
  // keyboard focus shows it, Escape hides it, focus survives a re-render cycle
  await p.focus('.gauge[data-k="temp"] .g-glyph'); assert.equal(await p.$eval('#gauge-tip', e => (e.hidden ? '' : e.textContent)), TIP);
  await p.keyboard.press('Escape'); assert.equal(await p.$eval('#gauge-tip', e => e.hidden), true);
  await p.focus('.gauge[data-k="temp"] .g-glyph'); await p.waitForTimeout(2500); assert.equal(await p.evaluate(() => document.activeElement?.className), 'g-sub g-glyph', 'polling must not drop keyboard focus');
  // the two glyphs no longer collide, and nothing overlaps or clips
  const rects = await p.$$eval('#resource-gauges .gauge', gs => gs.map(g => { const a = g.getBoundingClientRect(), b = g.querySelector('.g-sub').getBoundingClientRect(); return { l: a.left, r: a.right, sl: b.left, sr: b.right }; }));
  for (let i = 0; i < rects.length - 1; i++) assert.ok(rects[i].sr <= rects[i + 1].sl + 0.5, 'captions overlap at ' + i);
  // the full UNKNOWN text is kept in the evidence/details line
  assert.match(await p.$eval('#system-evidence', e => e.textContent), /GPU UNKNOWN, TEMP UNKNOWN \(no fresh telemetry\)/);
  assert.deepEqual(errors, []); await ctx.close();
});

test('live adapter: unknown gauges keep UNKNOWN (CPU/RAM/DISK as captions, GPU/TEMP as ? glyph); no glyph for any other state', async () => {
  const { p, errors, ctx } = await open(LIVE, { width: 1280, height: 720 });
  await p.waitForTimeout(1200);
  const r = await p.$$eval('#resource-gauges .gauge', gs => gs.map(g => ({ k: g.dataset.k, st: g.dataset.status, cap: g.querySelector('.g-sub').textContent, glyph: !!g.querySelector('.g-glyph') })));
  assert.deepEqual(r.map(x => x.glyph), [false, false, false, true, true]); assert.ok(r.every(x => x.st === 'UNKNOWN'));
  assert.deepEqual(r.slice(0, 3).map(x => x.cap), ['UNKNOWN', 'UNKNOWN', 'UNKNOWN']);
  assert.equal(await p.$$eval('.g-glyph', e => e.length), 2, '? glyph only on the two compact UNKNOWN gauges (OFFLINE / UNVERIFIED / NOT CONNECTED never use it)');
  assert.match(await p.$eval('#system-evidence', e => e.textContent), /GPU UNKNOWN, TEMP UNKNOWN/);
  assert.deepEqual(errors, []); await ctx.close();
});
