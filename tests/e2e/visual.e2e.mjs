// Visual-parity phase E2E: artwork present, task-card row truthful, Layout controls disabled,
// context labels inactive without events, role icons, and no target numbers / invented statuses.
// Run: node --test tests/e2e/visual.e2e.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const { chromium } = createRequire(import.meta.url)('playwright');
const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FIX = 'http://127.0.0.1:4184/', LIVE = 'http://127.0.0.1:4183/';
const procs = []; let browser;
async function up(args, url) {
  const p = spawn('python', args, { cwd: root, stdio: 'ignore', env: { ...process.env, HIVE_API_TOKEN: '' } }); procs.push(p);
  for (let i = 0; i < 60; i++) { try { if ((await fetch(url)).ok) return; } catch { /* retry */ } await new Promise(r => setTimeout(r, 100)); }
  throw new Error('server did not start');
}
test.before(async () => { await up(['fixture_server.py', '--port', '4184'], FIX); await up(['server.py', '--port', '4183'], LIVE); browser = await chromium.launch(); });
test.after(async () => { await browser?.close(); procs.forEach(p => p.kill()); });

async function open(url, vp = { width: 1920, height: 1080 }, prep) {
  const ctx = await browser.newContext({ viewport: vp }); const p = await ctx.newPage(); const errors = []; p.on('pageerror', e => errors.push(String(e)));
  if (prep) await prep(p);
  await p.goto(url, { waitUntil: 'domcontentloaded' });
  await p.waitForFunction(() => document.querySelectorAll('#resource-gauges .gauge').length === 5);
  return { p, errors, ctx };
}
const txt = (p, sel) => p.$eval(sel, e => e.textContent.trim());
const TARGET_ONLY = ['72 %', '64 %', '58 %', '84 %', '46 °C', '1.31 TB', '187K', '165K', 'Admin', 'AKTU', 'HIVE Context v4', 'Quantum', 'SECURITY: ACTIVE', 'Logs', 'Anomalies', 'Patterns'];

test('artwork is present and decorative: stars, nebula, spiral arms, ring nodes, ambient connectors, role icons', async () => {
  const { p, errors, ctx } = await open(LIVE);
  assert.ok((await p.$$eval('.space-bg .stars circle', c => c.length)) >= 300, 'starfield');
  assert.ok((await p.$$eval('.space-bg .neb ellipse', c => c.length)) >= 6, 'nebula');
  assert.equal(await p.$$eval('#core-arms path', c => c.length), 12, 'six spiral arms (glow + line)');
  assert.ok((await p.$$eval('#ring-nodes circle', c => c.length)) >= 12);
  assert.ok((await p.$$eval('#core-ambient path', c => c.length)) >= 4, 'connector curves');
  assert.deepEqual(await p.$$eval('#core-agents .core-agent', g => g.map(x => [x.dataset.agent, x.querySelector('use').getAttribute('href')])),
    [['FURY', '#ico-fury'], ['SHURI', '#ico-shuri'], ['THOR', '#ico-thor'], ['VISION', '#ico-vision'], ['FALCON', '#ico-falcon'], ['UATU', '#ico-uatu']]);
  assert.equal(await p.$$eval('#core-agents .ca-glyph', c => c.length), 0, 'letter placeholders are gone');
  assert.deepEqual(errors, []); await ctx.close();
});

test('live (nothing reachable): agent captions are role descriptor + UNKNOWN; nothing is active', async () => {
  const { p, ctx } = await open(LIVE); await p.waitForTimeout(1500);
  assert.deepEqual(await p.$$eval('#core-agents .ca-state', e => e.map(x => x.textContent)),
    ['Planning · UNKNOWN', 'Coding · UNKNOWN', 'Research · UNKNOWN', 'Analysis · UNKNOWN', 'Monitoring · UNKNOWN', 'Watching · UNKNOWN']);
  assert.equal(await p.$$eval('.ctx-item.on', e => e.length), 0, 'no context label is lit');
  assert.equal(await txt(p, '#internet-state'), 'NO ACTIVITY OBSERVED');
  assert.equal(await p.$eval('#ultron-ring', e => e.getAttribute('class').includes('gray')), true);
  assert.match(await txt(p, '#ultron-indicator'), /NOT CONNECTED/); await ctx.close();
});

test('live: task cards say UNKNOWN / UNAVAILABLE, no progress bar, Layout controls disabled and labelled', async () => {
  const { p, ctx } = await open(LIVE); await p.waitForTimeout(1500);
  assert.equal(await txt(p, '#card-current-main'), 'UNKNOWN'); assert.equal(await txt(p, '#card-next-main'), 'UNKNOWN');
  assert.match(await txt(p, '#card-context-main'), /^(UNKNOWN|UNAVAILABLE)$/);
  assert.equal(await txt(p, '#card-external-main'), 'INTERNET'); assert.equal(await txt(p, '#card-external-sub'), 'NO ACTIVITY OBSERVED');
  assert.equal(await p.$eval('#card-current-progress', e => e.hidden), true);
  assert.equal(await p.$$eval('#card-layout .lay-btn', b => b.every(x => x.disabled && /not available/i.test(x.title))), true);
  assert.match(await txt(p, '#card-layout .lay-note'), /editor not available/i);
  await ctx.close();
});

test('fixture: task cards show the fixture records; progress bar stays hidden without progress_percent; Layout stays disabled', async () => {
  const { p, ctx } = await open(FIX);
  await p.waitForFunction(() => document.querySelector('#card-current-main')?.textContent !== 'UNKNOWN', null, { timeout: 8000 });
  assert.equal(await txt(p, '#card-current-main'), 'Render live CORE state'); assert.match(await txt(p, '#card-current-sub'), /claude-subscription/);
  assert.equal(await txt(p, '#card-next-main'), 'Read WONG projection'); assert.equal(await txt(p, '#card-next-sub'), '1 queued');
  assert.equal(await txt(p, '#card-context-main'), 'CONTEXT READABLE'); assert.match(await txt(p, '#card-context-sub'), /read-only/);
  assert.equal(await p.$eval('#card-current-progress', e => e.hidden), true, 'no invented progress');
  assert.equal(await p.$$eval('#card-layout .lay-btn', b => b.every(x => x.disabled)), true);
  assert.match(await p.$eval('#env-tag', e => e.textContent), /FIXTURE/i); await ctx.close();
});

test('a context label lights up only when a fresh trusted event names it; untrusted source lights nothing', async () => {
  const frame = (ev, d) => `event: ${ev}\ndata: ${JSON.stringify(d)}\n\n`;
  const ev = { event_id: 'ctx-1', timestamp: new Date().toISOString(), role_id: 'SHURI', event_type: 'READ', state: 'WORKING', task_id: 'ctx-t', target_node: 'github', provenance: { validity: 'valid' } };
  const route = status => pg => pg.route('**/api/events/stream*', r => r.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: frame('status', { validity: status }) + frame('hive', ev) }));
  const good = await open(FIX, undefined, route('valid'));
  await good.p.waitForFunction(() => document.querySelector('.ctx-item[data-node="github"]')?.classList.contains('on'), null, { timeout: 8000 });
  assert.deepEqual(await good.p.$$eval('.ctx-item.on', e => e.map(x => x.dataset.node)), ['github'], 'only the named label');
  await good.ctx.close();
  const bad = await open(FIX, undefined, route('auth_required')); await bad.p.waitForTimeout(2500);
  assert.equal(await bad.p.$$eval('.ctx-item.on', e => e.length), 0); await bad.ctx.close();
});

test('no target-image numbers, names or statuses appear as data (live and fixture)', async () => {
  for (const url of [LIVE, FIX]) {
    const { p, ctx } = await open(url); await p.waitForTimeout(1800);
    const text = await p.evaluate(() => document.body.innerText);
    for (const bad of TARGET_ONLY) assert.ok(!text.includes(bad), `target-only text "${bad}" found at ${url}`);
    assert.doesNotMatch(text, /Online(?! Tools)/, 'a bare "Online" status would claim connectivity');
    assert.doesNotMatch(text, /INTERNET:\s*(Online|ACTIVE)/i, 'Internet is never shown active without an observed event');
    await ctx.close();
  }
});

test('GPT / CODEX / CLAUDE keep equal visual weight (chips, approval rows, limit rows)', async () => {
  const { p, ctx } = await open(FIX);
  const w = await p.$$eval('.source-chip', e => e.map(x => Math.round(x.getBoundingClientRect().width))); assert.equal(new Set(w).size, 1, String(w));
  const a = await p.$$eval('.approval-row', e => e.map(x => Math.round(x.getBoundingClientRect().height))); assert.equal(new Set(a).size, 1, 'approval rows differ in height: ' + a);
  const l = await p.$$eval('.limit-row', e => e.map(x => Math.round(x.getBoundingClientRect().height))); assert.equal(new Set(l).size, 1, 'limit rows differ in height: ' + l);
  await ctx.close();
});

test('layout with the card row: nothing clips or overlaps at 1280x720, 1920x1080, 2560x1440; CORE and labels stay legible', async () => {
  for (const vp of [{ width: 1280, height: 720 }, { width: 1920, height: 1080 }, { width: 2560, height: 1440 }]) {
    const { p, ctx } = await open(FIX + '?scenario=approval', vp);
    await p.waitForFunction(() => document.querySelector('#core-stage')?.dataset.coreState === 'WAITING_APPROVAL', null, { timeout: 8000 }); await p.waitForTimeout(1200);
    const r = await p.evaluate(() => { const out = [];
      document.querySelectorAll('.task-card').forEach(c => { const cb = c.getBoundingClientRect(); c.querySelectorAll('*').forEach(e => { const b = e.getBoundingClientRect(); if (b.width && (b.right > cb.right + 1 || b.bottom > cb.bottom + 1 || b.left < cb.left - 1)) out.push('card content outside: ' + (e.id || e.className.baseVal || e.className)); }); });
      const rail = document.querySelector('.rail-left').getBoundingClientRect(), cards = document.querySelector('#cards-row').getBoundingClientRect(), core = document.querySelector('#core-stage').getBoundingClientRect();
      if (cards.left < rail.right) out.push('cards overlap left rail'); if (core.top < cards.bottom - 0.5) out.push('core overlaps cards');
      const names = [...document.querySelectorAll('#core-agents .ca-name')]; const px = names.map(n => parseFloat(getComputedStyle(n).fontSize) * n.ownerSVGElement.getScreenCTM().a);
      return { out, minNamePx: Math.min(...px), coreH: core.height, vh: innerHeight }; });
    assert.deepEqual(r.out, [], `${vp.width}x${vp.height}`);
    assert.ok(r.minNamePx >= 9.5, `agent names too small: ${r.minNamePx.toFixed(1)}px at ${vp.width}x${vp.height}`);
    assert.ok(r.coreH >= vp.height * 0.3, `CORE stage too short: ${r.coreH}px`);
    await p.screenshot({ path: join(root, 'docs/hive/screenshots', `parity-${vp.width}x${vp.height}.png`) });
    await ctx.close();
  }
});

test('identity colours never reuse status hues; unobserved roles show a hollow neutral dot, observed ones say so in words', async () => {
  const live = await open(LIVE); await live.p.waitForTimeout(1500);
  const acc = await live.p.$$eval('.source-chip', e => e.map(x => getComputedStyle(x).getPropertyValue('--acc').trim().toLowerCase()));
  const STATUS = ['#4ff0c0', '#f2b84b', '#ff5c6c', '#7f93a3'];
  assert.equal(new Set(acc).size, 3, 'three distinct provider accents'); for (const a of acc) assert.ok(!STATUS.includes(a), `accent ${a} equals a status colour`);
  const ring = await live.p.$$eval('.approval-row', e => e.map(x => getComputedStyle(x).getPropertyValue('--acc').trim().toLowerCase()));
  for (const a of ring) assert.ok(!STATUS.includes(a), `approval accent ${a} equals a status colour`);
  const dots = await live.p.$$eval('#agent-roster .rail-row .dot', e => e.map(d => ({ hollow: d.classList.contains('hollow'), bg: getComputedStyle(d).backgroundColor })));
  assert.equal(dots.length, 6); assert.ok(dots.every(d => d.hollow && /rgba\(0, 0, 0, 0\)|transparent/.test(d.bg)), 'nothing observed => every dot is a hollow ring');
  assert.equal(await live.p.$$eval('#agent-roster small.obs', e => e.length), 0, 'no observed-state text without an observation');
  await live.ctx.close();
  const fx = await open(FIX); await fx.p.waitForFunction(() => document.querySelector('#agent-roster small.obs'), null, { timeout: 8000 });
  const obs = await fx.p.$$eval('#agent-roster .rail-row', rows => rows.filter(r => r.querySelector('small.obs')).map(r => [r.querySelector('strong').textContent, r.querySelector('small.obs').textContent, r.querySelector('.state').textContent]));
  assert.ok(obs.length >= 1); for (const [, state, prov] of obs) { assert.match(state, /· observed$/); assert.equal(prov, 'PROVIDER UNKNOWN', 'provider stays unknown even when the role state is observed'); }
  await fx.ctx.close();
});

test('a travelling agent hides its caption (no label collisions) while its name stays visible', async () => {
  const { p, ctx } = await open(FIX);
  await p.waitForSelector('.core-agent.moving', { timeout: 8000 });
  const r = await p.$eval('.core-agent.moving', g => ({ state: getComputedStyle(g.querySelector('.ca-state')).opacity, name: getComputedStyle(g.querySelector('.ca-name')).opacity }));
  assert.equal(r.state, '0'); assert.equal(r.name, '1'); await ctx.close();
});

test('rails: bottom panels stay anchored to the composer line and nothing stretches into empty glass', async () => {
  for (const vp of [{ width: 1920, height: 1080 }, { width: 1280, height: 720 }]) {
    const { p, ctx } = await open(LIVE, vp); await p.waitForTimeout(1200);
    const g = await p.evaluate(() => { const b = s => document.querySelector(s).getBoundingClientRect(); return { agents: b('#panel-agents').bottom, comp: b('#chat-draft-form').bottom, appr: b('#panel-approvals').bottom, chatsH: b('#panel-chats').height, vh: innerHeight }; });
    assert.ok(Math.abs(g.agents - g.comp) <= 2 && Math.abs(g.appr - g.comp) <= 2, `bottom panels not aligned: ${JSON.stringify(g)}`);
    assert.ok(g.chatsH <= vp.height * 0.5, 'CHATS must not stretch'); await ctx.close();
  }
});
