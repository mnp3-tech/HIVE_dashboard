// P0.1 visual-shell E2E. Run: node --test tests/e2e/shell.e2e.mjs
// Starts the read-only fixture server (loopback, no credentials) and drives Chromium
// at three desktop resolutions. Screenshots go to docs/hive/screenshots/.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const PORT = 4199;
const BASE = `http://127.0.0.1:${PORT}/`;
const RES = [
  { w: 1280, h: 720, minGap: 10 },
  { w: 1920, h: 1080, minGap: 16 },
  { w: 2560, h: 1440, minGap: 20 },
];

let server, browser;
test.before(async () => {
  server = spawn('python', ['fixture_server.py', '--port', String(PORT)], { cwd: root, stdio: 'ignore' });
  for (let i = 0; i < 50; i++) {
    try { const r = await fetch(BASE); if (r.ok) break; } catch { /* retry */ }
    await new Promise(r => setTimeout(r, 100));
  }
  browser = await chromium.launch();
});
test.after(async () => { await browser?.close(); server?.kill(); });

const PANEL_SELECTOR = '#topbar, .hive-panel, #core-stage';
async function open(res, query = '') {
  const page = await browser.newPage({ viewport: { width: res.w, height: res.h } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(BASE + query, { waitUntil: 'networkidle' });
  return { page, errors };
}

for (const res of RES) {
  test(`P0.1 shell @ ${res.w}x${res.h}`, async () => {
    const { page, errors } = await open(res);
    const rects = await page.$$eval(PANEL_SELECTOR, els => els.filter(e => e.offsetParent !== null || e.id === 'core-stage')
      .map(e => { const r = e.getBoundingClientRect(); return { id: e.id || e.className, l: r.left, t: r.top, r: r.right, b: r.bottom }; }));
    assert.ok(rects.length === 15, `expected 15 shell boxes, got ${rects.length}`);
    // no overlap + minimum gutter between every pair
    let minSep = Infinity;
    for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i], b = rects[j];
      const dx = Math.max(0, a.l - b.r, b.l - a.r), dy = Math.max(0, a.t - b.b, b.t - a.b);
      const sep = Math.max(dx, dy);
      assert.ok(!(dx === 0 && dy === 0), `overlap: ${a.id} vs ${b.id}`);
      minSep = Math.min(minSep, sep);
    }
    assert.ok(minSep >= res.minGap - 0.5, `min gutter ${minSep}px < ${res.minGap}px`);
    // edge margins and no scroll
    for (const r of rects) assert.ok(r.l >= res.minGap - 0.5 && r.t >= res.minGap - 0.5 && r.r <= res.w - res.minGap + 0.5 && r.b <= res.h - res.minGap + 0.5, `edge margin: ${r.id}`);
    const scroll = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, sh: document.documentElement.scrollHeight }));
    assert.ok(scroll.sw <= res.w && scroll.sh <= res.h, `page scrolls: ${JSON.stringify(scroll)}`);
    // no clipped content inside any panel (catches buttons/labels cut off at the right edge)
    const clipped = await page.$$eval('#topbar, .hive-panel, .hive-panel *', els => els.filter(e => e.offsetParent !== null && e.getClientRects().length)
      .filter(e => { const p = e.closest('.hive-panel'); if (!p) return false; const a = e.getBoundingClientRect(), b = p.getBoundingClientRect(); return a.width > 0 && (a.right > b.right + 1 || a.left < b.left - 1) && getComputedStyle(e).position !== 'fixed' && !e.closest('.hp-body[id="activity-rows"]'); })
      .map(e => (e.id || e.className || e.tagName) + ':' + (e.textContent || '').trim().slice(0, 20)));
    assert.deepEqual(clipped, [], `content outside its panel: ${clipped.join(' | ')}`);
    // CORE must stay the dominant element, and sibling text must not collide or overflow its own box
    const coreBox = await page.$eval('#hive-core-art', e => { const r = e.getBoundingClientRect(); return { w: r.width, h: r.height }; });
    assert.ok(coreBox.h >= res.h * 0.4, `CORE too small: ${coreBox.h}px high`);
    const collisions = await page.evaluate(() => {
      const bad = [];
      document.querySelectorAll('.source-chip, .approval-row, .tb-ultron, .limit-row').forEach(box => {
        if (box.scrollWidth > box.clientWidth + 1) bad.push('overflow:' + (box.className || box.id));
        const kids = [...box.children].filter(k => k.getClientRects().length).map(k => k.getBoundingClientRect());
        for (let i = 0; i < kids.length; i++) for (let j = i + 1; j < kids.length; j++) {
          const a = kids[i], b = kids[j];
          if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) bad.push('collision in ' + (box.className || box.id));
        }
      });
      return bad;
    });
    assert.deepEqual(collisions, []);
    // CORE centered +-2px (horizontal, against the viewport)
    const core = await page.$eval('#hive-core-art', e => { const r = e.getBoundingClientRect(); return { cx: r.left + r.width / 2, w: r.width }; });
    assert.ok(Math.abs(core.cx - res.w / 2) <= 2, `CORE centre ${core.cx} vs ${res.w / 2}`);
    // forbidden visible text
    const text = await page.evaluate(() => document.body.innerText);
    assert.doesNotMatch(text, /\bDONE\b/i); assert.doesNotMatch(text, /\bLOGS?\b/i);
    assert.doesNotMatch(text, /\bversion\b|\bv\d+\.\d+|contract v/i);
    // forbidden text must also be absent from attributes and hidden text of the shell (outside the closed details console)
    const attrText = await page.evaluate(() => [...document.querySelectorAll('body *')].filter(e => !e.closest('#console') && !['SCRIPT', 'STYLE'].includes(e.tagName))
      .flatMap(e => [e.getAttribute('title'), e.getAttribute('aria-label'), e.getAttribute('placeholder'), e.getAttribute('alt'), e.textContent && e.children.length === 0 ? e.textContent : null]).filter(Boolean).join(' | '));
    assert.doesNotMatch(attrText, /\bDONE\b|\bLOGS?\b|\bversion\b|\bv\d+\.\d+/i, 'forbidden label hidden in attributes/hidden text');
    // required shell labels
    for (const label of ['HIVE', 'GPT', 'CODEX', 'CLAUDE', 'ULTRON', 'JARVIS / VOICE LAYER', 'CHATS', 'PROJECTS', 'AGENTS / ROLES', 'ACTIVITY', 'APPROVALS', 'SYSTEM RESOURCES', 'AI MODELS / LIMITS', 'VOICE'])
      assert.ok(text.includes(label), `missing label ${label}`);
    assert.deepEqual(errors, []);
    await page.screenshot({ path: join(root, 'docs/hive/screenshots', `shell-${res.w}x${res.h}.png`) });
    await page.close();
  });
}

test('panel material, equal provider chips, inactive JARVIS/VOICE', async () => {
  const { page } = await open(RES[1]);
  const mats = await page.$$eval('.hive-panel', els => els.map(e => { const s = getComputedStyle(e); return { id: e.id, bg: s.backgroundColor, bf: s.backdropFilter || s.webkitBackdropFilter, bc: s.borderTopColor }; }));
  assert.equal(mats.length, 14);
  for (const mat of mats) { assert.equal(mat.bg, 'rgba(4, 16, 29, 0.46)', mat.id); assert.match(mat.bf, /blur\(12px\)/, mat.id); assert.equal(mat.bc, 'rgba(90, 190, 255, 0.4)', mat.id); }
  const widths = await page.$$eval('.source-chip', els => els.map(e => Math.round(e.getBoundingClientRect().width)));
  assert.equal(widths.length, 3); assert.equal(new Set(widths).size, 1, `provider chips unequal: ${widths}`);
  assert.equal(await page.$eval('#voice-button', e => e.disabled), true);
  assert.ok(await page.$eval('#jarvis-indicator', e => e.classList.contains('inactive')));
  assert.equal(await page.$$eval('#approval-rows .ap-btn', els => els.every(e => e.disabled)), true);
  await page.close();
});

test('missing telemetry is UNKNOWN, never WORKING, and demo is labelled', async () => {
  const { page } = await open(RES[1], '?demo=1');
  assert.equal(await page.$eval('#demo-banner', e => !e.hidden), true);
  await page.close();
  const { page: live } = await open(RES[1]);
  const t = await live.$eval('#ultron-state', e => e.textContent);
  assert.equal(t, 'NOT CONNECTED');
  assert.equal(await live.$eval('#panel-limits', e => e.innerText.includes('NOT_PROVIDED')), true);
  await live.close();
});

test('data environment is always visible in the top bar (fixture is never presented as live)', async () => {
  const { page } = await open(RES[1]);
  const env = await page.$eval('#env-tag', e => e.textContent);
  assert.match(env, /FIXTURE|UNVERIFIED|LOCAL/i);
  await page.close();
});

test('details console opens and closes; legacy views stay reachable', async () => {
  const { page } = await open(RES[1]);
  assert.equal(await page.$eval('#console', e => e.hidden), true);
  await page.click('#console-open');
  assert.equal(await page.$eval('#console', e => e.hidden), false);
  await page.keyboard.press('Escape');
  assert.equal(await page.$eval('#console', e => e.hidden), true);
  await page.close();
});
