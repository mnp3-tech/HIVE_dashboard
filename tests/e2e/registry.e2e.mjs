// Read-only registry v2 (DETAILS console -> Registry): lazy per-source loading, isolation of a failing source, distinct states,
// fixture labelling, catalog text rendered as text, compact unknown values with labels, no aggregate chips, no page scroll.
// Run: node --test tests/e2e/registry.e2e.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const { chromium } = createRequire(import.meta.url)('playwright');
const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FIX = 'http://127.0.0.1:4186/', LIVE = 'http://127.0.0.1:4185/';
const ENV = { ...process.env, HIVE_API_TOKEN: '', HIVE_SKILLS_ROOTS: '', ORCHESTRATOR_VAULT_ROOT: '', CREATOR_OPS_DB_PATH: '', HIVE_INTERNET_PROBES: '' };
const procs = []; let browser;
async function up(args, url) {
  const p = spawn('python', args, { cwd: root, stdio: 'ignore', env: ENV }); procs.push(p);
  for (let i = 0; i < 60; i++) { try { if ((await fetch(url)).ok) return; } catch { /* retry */ } await new Promise(r => setTimeout(r, 100)); }
  throw new Error('server did not start');
}
test.before(async () => { await up(['fixture_server.py', '--port', '4186'], FIX); await up(['server.py', '--port', '4185'], LIVE); browser = await chromium.launch(); });
test.after(async () => { await browser?.close(); procs.forEach(p => p.kill()); });

async function openRegistry(url, vp, prep) {
  const ctx = await browser.newContext({ viewport: vp }); const p = await ctx.newPage(); const errors = [];
  p.on('pageerror', e => errors.push(String(e))); p.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  if (prep) await prep(p);
  await p.goto(url, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(600);
  await p.click('#console-open'); await p.click('.nav-item[data-view="registry"]');
  await p.waitForFunction(() => document.querySelectorAll('#registry-body .reg-section').length >= 16 && !document.querySelector('#registry-body [aria-busy="true"]'), null, { timeout: 15000 });
  return { p, ctx, errors };
}
const rows = p => p.$$eval('#registry-body .reg-row', rs => rs.map(r => ({ kind: r.dataset.kind, id: r.dataset.id, display: r.dataset.display, text: r.textContent })));
const layout = p => p.evaluate(() => { const panel = document.querySelector('#registry-panel'), pr = panel.getBoundingClientRect(), de = document.scrollingElement;
  return { page: de.scrollWidth > innerWidth + 1 || de.scrollHeight > innerHeight + 1, panel: panel.scrollWidth > panel.clientWidth + 1,
    outside: [...document.querySelectorAll('#registry-body *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && (r.right > pr.right + 1 || r.left < pr.left - 1); }).length }; });

for (const vp of [{ width: 1280, height: 720 }, { width: 1920, height: 1080 }, { width: 2560, height: 1440 }]) {
  test(`fixture ${vp.width}x${vp.height}: fixture-labelled, distinct states, text-only catalog content, compact unknowns, no aggregate chips, no overflow`, async () => {
    const { p, ctx, errors } = await openRegistry(FIX, vp);
    assert.equal(await p.$eval('#registry-mode', e => e.textContent), 'FIXTURE DATA');
    assert.match(await p.$eval('#registry-evidence', e => e.textContent), /7 of 7 sources loaded/);
    const r = await rows(p);
    assert.deepEqual(r.filter(x => ['OBSERVED', 'ACTIVE'].includes(x.display)).map(x => x.id), [], 'fixture data never reads as observed/live');
    for (const d of ['FIXTURE', 'STALE', 'UNVERIFIED', 'CONFLICT', 'NOT_VERIFIED']) assert.ok(r.some(x => x.display === d), `state ${d} rendered`);
    assert.equal(await p.$$eval('#registry-body img, #registry-body script, #registry-body iframe, #registry-body [src], #registry-body [href]', e => e.length), 0, 'catalog text never becomes markup');
    const blob = await p.$eval('#registry-body', e => e.textContent);
    assert.ok(blob.includes('<img src=x onerror=alert(1)>') && blob.includes('<script>alert(1)</script>') && blob.includes('![x](http://example.com/pixel.png)'));
    assert.doesNotMatch(blob, /FIXTUREFAKEKEY|FIXTURE-SECRET|fixture_handle|Body text that the registry|Private daily content|Prompt body/);
    assert.equal(await p.$$eval('#registry-body button, #registry-body input, #registry-body form, #registry-body select', e => e.length), 0, 'no action controls');
    assert.match(blob, /classification UNKNOWN/); assert.doesNotMatch(blob, /\bPRIMARY\b|\bSECONDARY\b/);
    const q = await p.$$eval('#registry-body .reg-q', es => es.map(e => ({ t: e.textContent, label: e.getAttribute('aria-label'), title: e.getAttribute('title') })));
    assert.ok(q.length > 5 && q.every(x => x.t === '?' && /not provided/.test(x.label) && /NOT_PROVIDED by/.test(x.title)), 'compact unknowns carry their meaning');
    const chips = await p.$$eval('#registry-body .reg-chip', es => es.map(e => e.getAttribute('aria-label') || ''));
    assert.ok(chips.every(c => c.length > 0) && chips.some(c => /source .* observed /.test(c)), 'chips expose state, reason, source and observed_at');
    for (const agg of ['connectors', 'capabilities', 'skills', 'prompts', 'bots', 'providers', 'roles']) {
      assert.equal(await p.$eval(`[data-section="${agg}"] > summary`, e => e.querySelectorAll('.reg-chip').length), 0, `${agg} aggregate has no state chip`);
    }
    const ultron = await p.$eval('[data-section="ultron"]', e => e.textContent);
    assert.match(ultron, /Recent ULTRON observations/); assert.match(ultron, /evt-ultron-1/); assert.match(ultron, /Blocked or unavailable connectors/);
    assert.deepEqual(await layout(p), { page: false, panel: false, outside: 0 });
    await p.screenshot({ path: join(root, 'docs/hive/screenshots', `registry-fixture-${vp.width}x${vp.height}.png`) });
    assert.deepEqual(errors, []); await ctx.close();
  });
}

test('live (no Core, no configured paths on this host): honest unavailable states, nothing invented, proposals pending review', async () => {
  const { p, ctx, errors } = await openRegistry(LIVE, { width: 1920, height: 1080 });
  assert.equal(await p.$eval('#registry-mode', e => e.textContent), 'LIVE · READ-ONLY');
  const r = await rows(p);
  const c = id => r.find(x => x.id === id);
  assert.equal(r.find(x => x.kind === 'ultron_status').display, 'OFFLINE');
  assert.equal(c('connector:hive-core').display, 'OFFLINE'); assert.equal(c('connector:obsidian').display, 'NOT_CONNECTED');
  assert.equal(c('connector:creator-ops').display, 'NOT_CONNECTED'); assert.equal(c('connector:tool-manifests').display, 'OBSERVED');
  assert.ok(['agent', 'worker', 'task_instance', 'capability'].every(k => !r.some(x => x.kind === k)), 'nothing invented while Core is down');
  assert.match(await p.$eval('[data-section="agents"]', e => e.textContent), /HIVE Core has no agents route/);
  const props = r.filter(x => x.kind === 'proposal'); assert.equal(props.length, 6); assert.ok(props.every(x => /PENDING_HUMAN_REVIEW/.test(x.text)));
  assert.ok(r.filter(x => x.kind === 'catalog_item' && x.id.startsWith('tool:')).every(x => /enabled=false/.test(x.text)));
  await p.screenshot({ path: join(root, 'docs/hive/screenshots', 'registry-live-1920x1080.png') });
  assert.deepEqual(errors, []); await ctx.close();
});

test('one failing source is isolated: the others render, the failed one says so', async () => {
  const { p, ctx } = await openRegistry(FIX, { width: 1920, height: 1080 }, async page => {
    await page.route('**/api/registry?part=obsidian', route => route.fulfill({ status: 503, body: '{}' }));
  });
  const obs = await p.$eval('[data-section="obsidian"]', e => e.textContent);
  assert.match(obs, /UNAVAILABLE/); assert.match(obs, /source part failed/);
  assert.ok((await rows(p)).some(x => x.kind === 'worker'), 'HIVE Core part still rendered');
  assert.match(await p.$eval('#registry-evidence', e => e.textContent), /6 of 7 sources loaded/);
  await ctx.close();
});

test('the main dashboard makes no registry request until the view is opened', async () => {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } }); const p = await ctx.newPage(); const hits = [];
  p.on('request', q => { if (q.url().includes('/api/registry')) hits.push(q.url()); });
  await p.goto(LIVE, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(2500);
  assert.deepEqual(hits, []); await ctx.close();
});
