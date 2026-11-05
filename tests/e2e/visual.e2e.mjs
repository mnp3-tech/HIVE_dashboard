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

test('artwork is local and decorative: wallpaper file, vortex canvas drawn, ring nodes, connectors, role icons (no procedural stars, no text in art)', async () => {
  const { p, errors, ctx } = await open(LIVE);
  const bg = await p.$eval('.space-bg', e => getComputedStyle(e).backgroundImage); assert.match(bg, /assets\/hive-wallpaper\.jpg/); assert.match(bg, /^url\("http:\/\/127\.0\.0\.1:\d+\/assets\/hive-wallpaper\.jpg"\)$/, 'same-origin (loopback) local file only');
  const wp = await p.evaluate(async () => { const r = await fetch('assets/hive-wallpaper.jpg'); const b = await r.blob(); return { ok: r.ok, type: r.headers.get('content-type'), size: b.size }; });
  assert.equal(wp.ok, true); assert.match(wp.type, /image\/jpeg/); assert.ok(wp.size > 50000 && wp.size <= 650 * 1024, `wallpaper size ${wp.size}`);
  assert.equal(await p.$$eval('.space-bg *', c => c.length), 0, 'no procedural art inside the wallpaper layer');
  const px = await p.$eval('#core-canvas', cv => { const g = cv.getContext('2d'), S = cv.width; const d = g.getImageData(0, 0, S, S).data; let lit = 0, colours = new Set(); for (let i = 0; i < d.length; i += 4 * 97) { if (d[i + 3] > 40) { lit++; colours.add((d[i] >> 5) + ',' + (d[i + 1] >> 5) + ',' + (d[i + 2] >> 5)); } } const c = g.getImageData(S / 2, S / 2, 1, 1).data; return { lit, colours: colours.size, centreAlpha: c[3], centreLum: c[0] + c[1] + c[2] }; });
  assert.ok(px.lit > 500 && px.colours > 12, `vortex canvas looks empty: ${JSON.stringify(px)}`); assert.equal(px.centreLum, 0, 'the horizon is black');
  assert.ok((await p.$$eval('#ring-nodes circle', c => c.length)) >= 12); assert.ok((await p.$$eval('#core-ambient path', c => c.length)) >= 4, 'connector curves');
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
  assert.match(await txt(p, '#card-layout .lay-note'), /not available/i); assert.match(await p.$eval('#card-layout .lay-note', e => e.title), /editor not available/i);
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
  assert.deepEqual(await live.p.$$eval('#agent-roster .rail-row .state', e => e.map(x => x.textContent)), Array(6).fill('provider unknown'));
  await live.ctx.close();
  const fx = await open(FIX); await fx.p.waitForFunction(() => [...document.querySelectorAll('#agent-roster .rail-row .dot')].some(d => !d.classList.contains('hollow')), null, { timeout: 8000 });
  const obs = await fx.p.$$eval('#agent-roster .rail-row', rows => rows.filter(r => !r.querySelector('.dot').classList.contains('hollow')).map(r => [r.querySelector('strong').textContent, r.querySelector('.state').textContent, r.querySelector('.state').title]));
  assert.ok(obs.length >= 1); for (const [, state, title] of obs) { assert.match(state, /^(WORKING|IDLE|WAITING APPROVAL|REVIEW|FAILED|SECURITY BLOCKED)$/); assert.match(title, /observed from an event; provider unknown/); }
  assert.ok(!(await fx.p.$eval('#agent-roster', e => /claude|gpt|codex/i.test(e.textContent))), 'no provider is ever named next to a role');
  await fx.ctx.close();
});

test('a travelling agent hides its caption (no label collisions) while its name stays visible', async () => {
  const { p, ctx } = await open(FIX);
  await p.waitForSelector('.core-agent.moving', { timeout: 8000 });
  const r = await p.$eval('.core-agent.moving', g => ({ state: getComputedStyle(g.querySelector('.ca-state')).opacity, name: getComputedStyle(g.querySelector('.ca-name')).opacity }));
  assert.equal(r.state, '0'); assert.equal(r.name, '1'); await ctx.close();
});

test('the stage layout is the measured one: panel rectangles equal stage-layout-final.json x k, and stay within 1.5 pp of the target after the centring transform', async () => {
  const { readFileSync } = await import('node:fs');
  const fin = JSON.parse(readFileSync(join(root, 'docs/hive/measurements/stage-layout-final.json'), 'utf8')).panels_px;
  const tgt = JSON.parse(readFileSync(join(root, 'docs/hive/measurements/target.json'), 'utf8')); const S = 0.985, ring = tgt.core.neon_ring;
  const IDS = { chats: '#panel-chats', projects: '#panel-projects', agents: '#panel-agents', card_current: '#card-current', card_next: '#card-next', card_context: '#card-context', card_external: '#card-external', card_layout: '#card-layout', activity: '#panel-activity', approvals: '#panel-approvals', resources: '#panel-resources', limits: '#panel-limits', composer: '#chat-draft-form', topbar: '#topbar' };
  for (const vp of [{ width: 1280, height: 720 }, { width: 1920, height: 1080 }, { width: 2560, height: 1440 }]) {
    const { p, ctx } = await open(LIVE, vp); const k = await p.evaluate(() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--k')));
    assert.ok(Math.abs(k - Math.min(vp.width / 1671, vp.height / 941)) < 1e-6, 'stage scale');
    const ox = (vp.width - 1671 * k) / 2, oy = (vp.height - 941 * k) / 2;
    for (const [key, sel] of Object.entries(IDS)) {
      const r = await p.$eval(sel, e => { const b = e.getBoundingClientRect(); return { x: b.left, y: b.top, w: b.width, h: b.height }; }), f = fin[key];
      assert.ok(Math.abs(r.x - (ox + f.x0 * k)) <= 1 && Math.abs(r.y - (oy + f.y0 * k)) <= 1 && Math.abs(r.w - f.w * k) <= 1 && Math.abs(r.h - f.h * k) <= 1, `${key} @${vp.width}: ${JSON.stringify(r)} vs final`);
      if (key !== 'topbar' && tgt.panels[key]) { // deviation from the measured target after the centring transform (pp of the 1671x941 stage)
        const t = tgt.panels[key], tx = x => 835.5 + (x - ring.cx) * S, ty = y => 470.5 + (y - 470.5) * S;
        const dpp = [Math.abs(f.x0 - tx(t.x0)) / 1671, Math.abs(f.y0 - ty(t.y0)) / 941, Math.abs(f.w - (t.w * S)) / 1671, Math.abs(f.h - (t.h * S)) / 941].map(v => v * 100);
        assert.ok(Math.max(...dpp) <= 1.5, `${key} deviates ${dpp.map(v => v.toFixed(2))} pp from the target`);
      }
    }
    await ctx.close();
  }
});

test('agent homes are the measured polar positions (live: nothing observed => nobody moves); ring centre and radius match the spec', async () => {
  const { readFileSync } = await import('node:fs');
  const polar = JSON.parse(readFileSync(join(root, 'docs/hive/measurements/target.json'), 'utf8')).core.polar; const R = 233.1, C = { x: 835.5, y: 398.6 };
  for (const vp of [{ width: 1280, height: 720 }, { width: 1920, height: 1080 }]) {
    const { p, ctx } = await open(LIVE, vp); await p.waitForTimeout(1500);
    const k = Math.min(vp.width / 1671, vp.height / 941), ox = (vp.width - 1671 * k) / 2, oy = (vp.height - 941 * k) / 2;
    const ring = await p.$eval('#ultron-ring', e => { const b = e.getBoundingClientRect(); return { cx: b.left + b.width / 2, cy: b.top + b.height / 2, r: b.width / 2 }; });
    assert.ok(Math.abs(ring.cx - vp.width / 2) <= 2 && Math.abs(ring.r - R * k) <= 2 && Math.abs(ring.cy - (oy + C.y * k)) <= 2, JSON.stringify(ring));
    for (const [role, pol] of Object.entries(polar)) {
      if (!['FURY', 'SHURI', 'THOR', 'VISION', 'FALCON', 'UATU'].includes(role)) continue;
      const c = await p.$eval(`.core-agent[data-agent="${role}"] circle:not(.halo)`, e => { const b = e.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; });
      const ex = ox + (C.x + R * pol.r_over_ring * Math.cos(pol.angle_deg * Math.PI / 180)) * k, ey = oy + (C.y + R * pol.r_over_ring * Math.sin(pol.angle_deg * Math.PI / 180)) * k;
      assert.ok(Math.hypot(c.x - ex, c.y - ey) <= 1.5, `${role} home is ${Math.hypot(c.x - ex, c.y - ey).toFixed(1)}px from the measured position at ${vp.width}`);
    }
    await ctx.close();
  }
});

test('text floor: no rendered text is smaller than 9.9 px on screen at 1280x720 (HTML and SVG text)', async () => {
  const { p, ctx } = await open(FIX + '?scenario=approval', { width: 1280, height: 720 }); await p.waitForTimeout(2200);
  const small = await p.evaluate(() => { const out = []; const k = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--k'));
    for (const e of document.querySelectorAll('.stage *')) { const own = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()); if (!own) continue; const r = e.getBoundingClientRect(); if (!r.width || !r.height) continue; const cs = getComputedStyle(e); if (cs.visibility === 'hidden' || cs.display === 'none' || e.classList.contains('visually-hidden')) continue; // screen-reader-only text is not visually rendered
      let px = parseFloat(cs.fontSize); px *= e.ownerSVGElement ? e.ownerSVGElement.getScreenCTM().a : k; if (px < 9.9) out.push(`${e.tagName.toLowerCase()}.${(e.className.baseVal ?? e.className) || ''}: "${e.textContent.trim().slice(0, 24)}" ${px.toFixed(1)}px`); }
    return out; });
  assert.deepEqual(small, []); await ctx.close();
});

test('local-only: every request is same-origin or loopback; nothing fails; the wallpaper is fetched once as a local image', async () => {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } }); const p = await ctx.newPage(); const urls = [], failed = [];
  p.on('request', r => urls.push(r.url())); p.on('requestfailed', r => failed.push(r.url()));
  await p.goto(FIX, { waitUntil: 'networkidle' }); await p.waitForTimeout(800);
  const foreign = urls.filter(u => !/^http:\/\/127\.0\.0\.1:\d+\//.test(u) && !u.startsWith('data:') && !u.startsWith('blob:'));
  assert.deepEqual(foreign, []); assert.deepEqual(failed.filter(u => !u.includes('/api/events/stream')), []);
  assert.equal(urls.filter(u => u.endsWith('/assets/hive-wallpaper.jpg')).length, 1); await ctx.close();
});

test('reduced motion: vortex, ambient connectors and links do not animate; UNKNOWN vortex is dimmed, WORKING is bright', async () => {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, reducedMotion: 'reduce' }); const p = await ctx.newPage();
  await p.goto(FIX); await p.waitForFunction(() => document.querySelector('#core-stage')?.dataset.coreState === 'WORKING', null, { timeout: 8000 });
  assert.equal(await p.$eval('#core-canvas', e => getComputedStyle(e).animationName), 'none'); assert.equal(await p.$eval('#core-ambient path', e => getComputedStyle(e).animationName), 'none'); await ctx.close();
  const live = await open(LIVE); await live.p.waitForTimeout(1500);
  const o = await live.p.$eval('#core-canvas', e => ({ op: parseFloat(getComputedStyle(e).opacity), f: getComputedStyle(e).filter, a: getComputedStyle(e).animationName })); assert.ok(o.op <= 0.5 && /grayscale/.test(o.f) && o.a === 'none', JSON.stringify(o)); await live.ctx.close();
  const w = await open(FIX); await w.p.waitForFunction(() => document.querySelector('#core-stage')?.dataset.coreState === 'WORKING', null, { timeout: 8000 });
  const ow = await w.p.$eval('#core-canvas', e => parseFloat(getComputedStyle(e).opacity)); assert.ok(ow >= 0.95); await w.ctx.close();
});
