// P0.2 CORE E2E. Run: node --test tests/e2e/core.e2e.mjs
// Fixture server = deterministic synthetic SSE; live server.py with an unreachable HIVE Core = honest UNKNOWN.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const { chromium } = createRequire(import.meta.url)('playwright');
const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FIX = 'http://127.0.0.1:4196/', LIVE = 'http://127.0.0.1:4195/';
const procs = []; let browser;

async function up(args, url) {
  const p = spawn('python', args, { cwd: root, stdio: 'ignore', env: { ...process.env, HIVE_API_TOKEN: '' } }); procs.push(p);
  for (let i = 0; i < 60; i++) { try { if ((await fetch(url)).ok) return; } catch { /* retry */ } await new Promise(r => setTimeout(r, 100)); }
  throw new Error('server did not start: ' + args.join(' '));
}
test.before(async () => {
  await up(['fixture_server.py', '--port', '4196'], FIX);
  await up(['server.py', '--port', '4195'], LIVE);
  browser = await chromium.launch();
});
test.after(async () => { await browser?.close(); procs.forEach(p => p.kill()); });

async function page(url, { reduced = false, prep } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, reducedMotion: reduced ? 'reduce' : 'no-preference' });
  const p = await ctx.newPage(); const errors = []; p.on('pageerror', e => errors.push(String(e)));
  if (prep) await prep(p);
  await p.goto(url, { waitUntil: 'domcontentloaded' });
  return { p, errors, ctx };
}
const coreState = p => p.$eval('#core-stage', e => e.dataset.coreState);
const agentPos = (p, role) => p.$eval(`.core-agent[data-agent="${role}"]`, e => e.getAttribute('transform').match(/-?[\d.]+/g).map(Number));
const sameSpot = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) < 1.5;

test('fixture SSE: events drive CORE to WORKING, UATU moves toward Obsidian with a real event link', async () => {
  const { p, errors, ctx } = await page(FIX);
  const home = await agentPos(p, 'UATU'); const thorHome = await agentPos(p, 'THOR');
  await p.waitForFunction(() => document.querySelector('#core-stage')?.dataset.coreState === 'WORKING', null, { timeout: 8000 });
  await p.waitForSelector('.event-link.obsidian', { timeout: 8000 });
  assert.ok(!sameSpot(await agentPos(p, 'UATU'), home), 'UATU left its home sector');
  assert.equal(await p.$eval('#node-obsidian', e => e.classList.contains('active')), true);
  assert.equal(await p.$eval('#obsidian-state', e => e.textContent), 'READ OBSERVED');
  assert.equal(await p.$eval('#node-internet', e => e.classList.contains('active')), false, 'Internet stays inactive without observed traffic');
  assert.ok(sameSpot(await agentPos(p, 'THOR'), thorHome), 'agents without an observed interaction stay home');
  assert.match(await p.$eval('#core-state', e => e.textContent), /WORKING/);
  assert.deepEqual(errors, []); await ctx.close();
});

test('live adapter with HIVE Core unreachable: CORE is UNKNOWN (never WORKING), nothing moves, nothing active', async () => {
  const { p, errors, ctx } = await page(LIVE);
  const homes = {}; for (const r of ['FURY', 'SHURI', 'THOR', 'VISION', 'FALCON', 'UATU']) homes[r] = await agentPos(p, r);
  await p.waitForTimeout(2500);
  assert.equal(await coreState(p), 'UNKNOWN');
  assert.match(await p.$eval('#core-state', e => e.textContent), /UNKNOWN/);
  for (const r of Object.keys(homes)) assert.ok(sameSpot(await agentPos(p, r), homes[r]), `${r} must not move without events`);
  assert.equal(await p.$$eval('.event-link', e => e.length), 0);
  assert.equal(await p.$eval('#internet-state', e => e.textContent), 'NO ACTIVITY OBSERVED');
  assert.equal(await p.$eval('#ultron-ring', e => e.getAttribute('class').includes('gray')), true);
  assert.deepEqual(errors, []); await ctx.close();
});

test('SSE unavailable: polling fallback keeps the page truthful (no WORKING from silence)', async () => {
  const { p, errors, ctx } = await page(FIX, { prep: pg => pg.route('**/api/events/stream*', r => r.abort()) });
  await p.waitForFunction(() => ['IDLE', 'UNKNOWN'].includes(document.querySelector('#core-stage')?.dataset.coreState), null, { timeout: 10000 });
  assert.notEqual(await coreState(p), 'WORKING'); assert.equal(await p.$$eval('.event-link', e => e.length), 0);
  assert.deepEqual(errors, []); await ctx.close();
});

test('everything unreachable: CORE goes OFFLINE after repeated failed polls (not WORKING, not stuck)', async () => {
  const { p, ctx } = await page(FIX, { prep: async pg => { await pg.route('**/api/events/stream*', r => r.abort()); await pg.route('**/api/dashboard/snapshot*', r => r.abort()); } });
  await p.waitForFunction(() => document.querySelector('#core-stage')?.dataset.coreState === 'OFFLINE', null, { timeout: 25000 });
  assert.equal(await p.$eval('#core-lock', e => e.hidden), true);
  await ctx.close();
});

test('ambient layer is visibly distinct from event links; reduced-motion disables animation', async () => {
  const { p, ctx } = await page(FIX, { reduced: true });
  await p.waitForSelector('.event-link', { timeout: 8000 });
  const css = await p.evaluate(() => { const a = getComputedStyle(document.querySelector('.core-ambient path')), e = getComputedStyle(document.querySelector('.event-link')); const arms = getComputedStyle(document.querySelector('.core-arms'));
    return { aStroke: a.stroke, eStroke: e.stroke, aWidth: parseFloat(a.strokeWidth), eWidth: parseFloat(e.strokeWidth), aAnim: a.animationName, eAnim: e.animationName, armAnim: arms.animationName }; });
  assert.notEqual(css.aStroke, css.eStroke); assert.ok(css.eWidth > css.aWidth);
  assert.equal(css.aAnim, 'none'); assert.equal(css.eAnim, 'none'); assert.equal(css.armAnim, 'none');
  await ctx.close();
});

test('CORE motion respects state: animated when WORKING (motion allowed), static when UNKNOWN', async () => {
  const w = await page(FIX); await w.p.waitForFunction(() => document.querySelector('#core-stage')?.dataset.coreState === 'WORKING', null, { timeout: 8000 });
  assert.notEqual(await w.p.$eval('.core-arms', e => getComputedStyle(e).animationName), 'none'); await w.ctx.close();
  const u = await page(LIVE); await u.p.waitForTimeout(1500);
  assert.equal(await u.p.$eval('.core-arms', e => getComputedStyle(e).animationName), 'none'); await u.ctx.close();
});

test('CORE stays centred and screenshots are saved for each state', async () => {
  const { p, ctx } = await page(FIX); await p.waitForFunction(() => document.querySelector('#core-stage')?.dataset.coreState === 'WORKING', null, { timeout: 8000 });
  const cx = await p.$eval('#hive-core-art', e => { const r = e.getBoundingClientRect(); return r.left + r.width / 2; });
  assert.ok(Math.abs(cx - 960) <= 2);
  await p.waitForTimeout(1800); await p.screenshot({ path: join(root, 'docs/hive/screenshots/core-working-1920x1080.png') });
  await ctx.close();
  const u = await page(LIVE); await u.p.waitForTimeout(1500); await u.p.screenshot({ path: join(root, 'docs/hive/screenshots/core-unknown-1920x1080.png') }); await u.ctx.close();
});
