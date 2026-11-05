// Read-only registry view (DETAILS console -> Registry): provenance, distinct states, fixture labelling, hostile metadata
// rendered as text, nothing executable, no console errors, no page scroll. Run: node --test tests/e2e/registry.e2e.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const { chromium } = createRequire(import.meta.url)('playwright');
const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FIX = 'http://127.0.0.1:4186/', LIVE = 'http://127.0.0.1:4185/';
const procs = []; let browser;
async function up(args, url) {
  const p = spawn('python', args, { cwd: root, stdio: 'ignore', env: { ...process.env, HIVE_API_TOKEN: '', HIVE_SKILL_ROOTS: '', ORCHESTRATOR_VAULT_ROOT: '' } }); procs.push(p);
  for (let i = 0; i < 60; i++) { try { if ((await fetch(url)).ok) return; } catch { /* retry */ } await new Promise(r => setTimeout(r, 100)); }
  throw new Error('server did not start');
}
test.before(async () => { await up(['fixture_server.py', '--port', '4186'], FIX); await up(['server.py', '--port', '4185'], LIVE); browser = await chromium.launch(); });
test.after(async () => { await browser?.close(); procs.forEach(p => p.kill()); });

async function openRegistry(url, vp) {
  const ctx = await browser.newContext({ viewport: vp }); const p = await ctx.newPage(); const errors = [];
  p.on('pageerror', e => errors.push(String(e))); p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await p.goto(url, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(800);
  await p.click('#console-open'); await p.click('.nav-item[data-view="registry"]');
  await p.waitForFunction(() => document.querySelectorAll('#registry-body .reg-section').length >= 17, null, { timeout: 15000 });
  return { p, ctx, errors };
}
const rows = p => p.$$eval('#registry-body .reg-row', rs => rs.map(r => ({ kind: r.dataset.kind, id: r.dataset.id, display: r.dataset.display, text: r.textContent })));

for (const vp of [{ width: 1280, height: 720 }, { width: 1920, height: 1080 }]) {
  test(`fixture ${vp.width}x${vp.height}: every row is FIXTURE-labelled or a non-live state; hostile metadata is text; nothing is enabled`, async () => {
    const { p, ctx, errors } = await openRegistry(FIX, vp);
    assert.equal(await p.$eval('#registry-mode', e => e.textContent), 'FIXTURE DATA');
    const r = await rows(p);
    assert.ok(r.length > 20, `rows: ${r.length}`);
    assert.deepEqual(r.filter(x => ['OBSERVED', 'ACTIVE'].includes(x.display)).map(x => x.id), [], 'fixture data must never read as observed/live');
    assert.ok(r.some(x => x.display === 'STALE') && r.some(x => x.display === 'UNVERIFIED') && r.some(x => x.display === 'FIXTURE'), 'distinct states are rendered');
    assert.equal(await p.$$eval('#registry-body img, #registry-body script, #registry-body iframe', e => e.length), 0, 'metadata must not become markup');
    const hostile = r.find(x => x.id === 'skill:fixture/hostile-metadata');
    assert.ok(hostile && hostile.text.includes('<img src=x onerror=alert(1)>') && hostile.text.includes('enabled=false') && !hostile.text.includes('FIXTUREFAKEKEY'));
    assert.equal(await p.$$eval('#registry-body button, #registry-body input, #registry-body form', e => e.length), 0, 'the registry view has no action controls');
    const blob = await p.$eval('#registry-body', e => e.textContent);
    assert.doesNotMatch(blob, /Body text that the registry|Private daily content/, 'note content never reaches the browser');
    assert.match(blob, /classification UNKNOWN/); assert.doesNotMatch(blob, /PRIMARY|SECONDARY/);
    assert.equal(await p.$eval('.nav-item[data-view="registry"]', e => e.classList.contains('active')), true);
    const scroll = await p.evaluate(() => ({ page: document.scrollingElement.scrollHeight > innerHeight + 1 || document.scrollingElement.scrollWidth > innerWidth + 1,
      panel: (() => { const e = document.querySelector('#registry-panel'); return e.scrollWidth > e.clientWidth + 1; })() }));
    assert.deepEqual(scroll, { page: false, panel: false });
    await p.screenshot({ path: join(root, 'docs/hive/screenshots', `registry-fixture-${vp.width}x${vp.height}.png`) });
    assert.deepEqual(errors, []); await ctx.close();
  });
}

test('live (no Core on this host): ULTRON OFFLINE, connectors not observed, no agents/workers invented, proposals stay pending review', async () => {
  const { p, ctx, errors } = await openRegistry(LIVE, { width: 1920, height: 1080 });
  assert.equal(await p.$eval('#registry-mode', e => e.textContent), 'LIVE · READ-ONLY');
  const r = await rows(p);
  assert.equal(r.find(x => x.kind === 'ultron_status').display, 'OFFLINE');
  const conns = r.filter(x => x.kind === 'connector');
  assert.equal(conns.find(x => x.id === 'connector:hive-core').display, 'OFFLINE');
  assert.equal(conns.find(x => x.id === 'connector:obsidian').display, 'NOT_CONNECTED');
  assert.ok(['agent', 'worker', 'task_instance', 'capability'].every(k => !r.some(x => x.kind === k)), 'nothing invented while Core is down');
  const sec = k => p.$eval(`[data-section="${k}"]`, e => e.textContent);
  for (const k of ['agents', 'workers', 'tasks']) assert.match(await sec(k), /Nothing from this source/);
  const props = r.filter(x => x.kind === 'proposal');
  assert.equal(props.length, 3); assert.ok(props.every(x => /review PENDING_HUMAN_REVIEW/.test(x.text)));
  assert.ok(r.filter(x => x.kind === 'provider').every(x => x.display === 'UNKNOWN'));
  await p.screenshot({ path: join(root, 'docs/hive/screenshots', 'registry-live-1920x1080.png') });
  assert.deepEqual(errors, []); await ctx.close();
});

test('the main dashboard is unchanged by the registry: no registry request until the view is opened', async () => {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } }); const p = await ctx.newPage(); const hits = [];
  p.on('request', q => { if (q.url().includes('/api/registry')) hits.push(q.url()); });
  await p.goto(LIVE, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(2500);
  assert.deepEqual(hits, []); await ctx.close();
});
