// Side-by-side images: target (left) vs the real UI on fixture data (right) at 1280x720, 1920x1080, 2560x1440,
// plus a zoomed CORE comparison at 1920x1080 and a live-adapter (everything UNKNOWN) capture.
// Output: docs/hive/screenshots/hybrid-compare-<w>x<h>.png, hybrid-core-zoom-1920x1080.png, hybrid-live-<w>x<h>.png
// Usage: node tools/make_compare.mjs
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const { chromium } = createRequire(import.meta.url)('playwright');
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(root, 'docs/hive/screenshots'); const tmp = '/tmp/hive-compare'; mkdirSync(tmp, { recursive: true });
const procs = [spawn('python', ['fixture_server.py', '--port', '4176'], { cwd: root, stdio: 'ignore' }), spawn('python', ['server.py', '--port', '4175'], { cwd: root, stdio: 'ignore', env: { ...process.env, HIVE_API_TOKEN: '' } })];
for (const port of [4176, 4175]) for (let i = 0; i < 60; i++) { try { if ((await fetch(`http://127.0.0.1:${port}/`)).ok) break; } catch { /* retry */ } await new Promise(r => setTimeout(r, 100)); }
const browser = await chromium.launch();
const SIZES = [[1280, 720], [1920, 1080], [2560, 1440]];
try {
  for (const [w, h] of SIZES) {
    let p = await browser.newPage({ viewport: { width: w, height: h } });
    await p.goto('http://127.0.0.1:4176/'); await p.waitForFunction(() => document.querySelector('#core-stage')?.dataset.coreState === 'WORKING', null, { timeout: 9000 }); await p.waitForTimeout(2600);
    await p.screenshot({ path: `${tmp}/ours-${w}.png` }); await p.close();
    p = await browser.newPage({ viewport: { width: w, height: h } }); await p.goto('http://127.0.0.1:4175/'); await p.waitForTimeout(2300);
    await p.screenshot({ path: join(out, `hybrid-live-${w}x${h}.png`) }); await p.close();
    writeFileSync(`${tmp}/c${w}.html`, `<body style="margin:0;background:#111;color:#ddd;font:14px sans-serif"><div style="display:flex;gap:8px"><div style="width:996px"><div>TARGET (visual direction only; its numbers are illustrative)</div><img style="width:996px;display:block" src="${root}/docs/assets/hive-dashboard-target.png"></div><div style="width:996px"><div>OURS (hybrid 2.5D) @ ${w}x${h} (fixture data)</div><img style="width:996px;display:block" src="${tmp}/ours-${w}.png"></div></div></body>`);
    const c = await browser.newPage({ viewport: { width: 2000, height: 700 } }); await c.goto(`file://${tmp}/c${w}.html`); await c.waitForLoadState('load'); await c.waitForTimeout(500);
    const hh = await c.evaluate(() => document.body.scrollHeight); await c.setViewportSize({ width: 2000, height: hh }); await c.screenshot({ path: join(out, `hybrid-compare-${w}x${h}.png`) }); await c.close();
  }
  // CORE zoom at 1920x1080: same scale on both sides (target scaled by 1920/1671)
  const s = 1920 / 1671; const cx0 = 380, cy0 = 120, cw = 1020, ch = 560;
  writeFileSync(`${tmp}/zoom.html`, `<body style="margin:0;background:#111;color:#ddd;font:14px sans-serif"><div style="display:flex;gap:8px"><div><div>TARGET (scaled x${s.toFixed(3)})</div><div style="width:${cw}px;height:${ch}px;overflow:hidden;position:relative"><img style="position:absolute;left:${-cx0}px;top:${-cy0}px;width:${1671 * s}px" src="${root}/docs/assets/hive-dashboard-target.png"></div></div><div><div>OURS @ 1920x1080</div><div style="width:${cw}px;height:${ch}px;overflow:hidden;position:relative"><img style="position:absolute;left:${-cx0}px;top:${-cy0}px;width:1920px" src="${tmp}/ours-1920.png"></div></div></div></body>`);
  const z = await browser.newPage({ viewport: { width: 2060, height: ch + 30 } }); await z.goto(`file://${tmp}/zoom.html`); await z.waitForLoadState('load'); await z.waitForTimeout(500);
  await z.screenshot({ path: join(out, 'hybrid-core-zoom-1920x1080.png') }); await z.close();
} finally { await browser.close(); procs.forEach(p => p.kill()); }
console.log('compare images written to', out);
