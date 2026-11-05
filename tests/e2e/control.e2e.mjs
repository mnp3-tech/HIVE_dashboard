// P1.3 control plane view (DETAILS -> Control plane): read-only agent registry, role/capability matrix, ULTRON observations,
// self-evolution proposals and fixture experiments. Nothing actionable, nothing invented, no overflow. Run: node --test tests/e2e/control.e2e.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const { chromium } = createRequire(import.meta.url)('playwright');
const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FIX = 'http://127.0.0.1:4182/', LIVE = 'http://127.0.0.1:4181/';
const ENV = { ...process.env, HIVE_API_TOKEN: '', HIVE_SKILLS_ROOTS: '', ORCHESTRATOR_VAULT_ROOT: '', CREATOR_OPS_DB_PATH: '', HIVE_INTERNET_PROBES: '' };
const procs = []; let browser;
async function up(args, url) {
  const p = spawn('python', args, { cwd: root, stdio: 'ignore', env: ENV }); procs.push(p);
  for (let i = 0; i < 60; i++) { try { if ((await fetch(url)).ok) return; } catch { /* retry */ } await new Promise(r => setTimeout(r, 100)); }
  throw new Error('server did not start');
}
test.before(async () => { await up(['fixture_server.py', '--port', '4182'], FIX); await up(['server.py', '--port', '4181'], LIVE); browser = await chromium.launch(); });
test.after(async () => { await browser?.close(); procs.forEach(p => p.kill()); });

async function openControl(url, vp) {
  const ctx = await browser.newContext({ viewport: vp }); const p = await ctx.newPage(); const errors = [];
  p.on('pageerror', e => errors.push(String(e))); p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await p.goto(url, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(600);
  await p.click('#console-open'); await p.click('.nav-item[data-view="control"]');
  await p.waitForFunction(() => /7 of 7/.test(document.querySelector('#control-evidence').textContent) && !document.querySelector('#control-body [aria-busy="true"]'), null, { timeout: 15000 });
  return { p, ctx, errors };
}
const agentRows = p => p.$$eval('#control-body [data-section="agent-registry"] .reg-row', rs => rs.map(r => ({ id: r.dataset.id, display: r.dataset.display, text: r.textContent })));

for (const vp of [{ width: 1280, height: 720 }, { width: 1920, height: 1080 }, { width: 2560, height: 1440 }]) {
  test(`fixture ${vp.width}x${vp.height}: agents, matrix, observations, proposals and experiments render without overflow or actions`, async () => {
    const { p, ctx, errors } = await openControl(FIX, vp);
    assert.equal(await p.$eval('#control-mode', e => e.textContent), 'FIXTURE DATA');
    const a = await agentRows(p);
    const by = id => a.find(x => x.id === `agent-profile:${id}`);
    assert.ok(by('EVOLVE') && /CONFIGURED · CONFIGURED/.test(by('EVOLVE').text) && by('EVOLVE').display === 'NOT_VERIFIED', 'documented-only agent not active');
    assert.match(by('BLACK_WIDOW').text, /PROPOSED · PROPOSED/); assert.match(by('JARVIS').text, /DISABLED · DISABLED/);
    assert.equal(by('FALCON').display, 'CONFLICT'); assert.equal(by('THOR').display, 'STALE'); assert.match(by('WATCHER_X').text, /DISCOVERED/);
    assert.ok(a.every(x => /primary\/secondary UNKNOWN/.test(x.text)));
    assert.deepEqual(a.filter(x => ['OBSERVED', 'ACTIVE'].includes(x.display)).map(x => x.id), [], 'fixture never reads as live');
    const matrix = await p.$$eval('.reg-matrix tbody tr[data-agent]', rs => rs.map(r => ({ id: r.dataset.agent, q: r.querySelectorAll('.reg-q').length, cells: r.children.length })));
    assert.equal(matrix.length, 11); assert.ok(matrix.find(m => m.id === 'BLACK_WIDOW').q >= 8, 'Black Widow fields are NOT_PROVIDED, not invented');
    const ultron = await p.$eval('[data-section="ultron-control"]', e => e.textContent);
    for (const s of ['blocked_agent', 'permission_failure', 'repeated_failure', 'task_routing', 'worker_health', 'action: none (observation only)', 'fixture-health.example', 'rejected']) assert.ok(ultron.includes(s), s);
    const props = await p.$$eval('[data-section="evo-proposals"] .reg-row', rs => rs.map(r => r.textContent));
    assert.equal(props.length, 6); assert.ok(props.every(t => /applied=false/.test(t) && /PENDING_HUMAN_REVIEW/.test(t)));
    const exps = await p.$$eval('[data-section="experiments"] table.exp', ts => ts.length);
    assert.equal(exps, 3);
    assert.match(await p.$eval('[data-section="experiments"]', e => e.textContent), /better/);
    assert.match(await p.$eval('[data-section="domains"]', e => e.textContent), /insufficient evidence \(no-op\)/);
    assert.equal(await p.$$eval('#control-body button, #control-body input, #control-body form, #control-body select, #control-body img, #control-body script', e => e.length), 0);
    const lay = await p.evaluate(() => { const panel = document.querySelector('#control-panel'), pr = panel.getBoundingClientRect(), de = document.scrollingElement;
      return { page: de.scrollWidth > innerWidth + 1 || de.scrollHeight > innerHeight + 1, h: panel.scrollWidth > panel.clientWidth + 1,
        outside: [...document.querySelectorAll('#control-body *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && (r.right > pr.right + 1 || r.left < pr.left - 1); }).length }; });
    assert.deepEqual(lay, { page: false, h: false, outside: 0 });
    await p.screenshot({ path: join(root, 'docs/hive/screenshots', `control-fixture-${vp.width}x${vp.height}.png`) });
    assert.deepEqual(errors, []); await ctx.close();
  });
}

test('live (Core down, nothing configured): agents not active, ULTRON OFFLINE with one transport observation, no probe, experiments labelled FIXTURE', async () => {
  const { p, ctx, errors } = await openControl(LIVE, { width: 1920, height: 1080 });
  const a = await agentRows(p);
  assert.ok(a.every(x => !/HEALTHY|DEGRADED/.test(x.text)), 'no agent is healthy or degraded without observation');
  const ultron = await p.$eval('[data-section="ultron-control"]', e => e.textContent);
  assert.match(ultron, /connector_health · HIVE Core/); assert.match(ultron, /HIVE_INTERNET_PROBES is not configured/);
  assert.equal(await p.$eval('[data-section="ultron-control"] > summary .reg-chip', e => e.textContent), 'OFFLINE');
  const expChips = await p.$$eval('[data-section="experiments"] .reg-row > .reg-chip', es => es.map(e => e.textContent));
  assert.deepEqual(expChips, ['FIXTURE', 'FIXTURE', 'FIXTURE'], 'experiments never read as live evidence');
  await p.screenshot({ path: join(root, 'docs/hive/screenshots', 'control-live-1920x1080.png') });
  assert.deepEqual(errors, []); await ctx.close();
});
