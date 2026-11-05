// Measure the real UI (fixture data, so every panel is populated) at the three desktop sizes and write
// docs/hive/measurements/ours-<w>x<h>.json plus overlay-<w>x<h>.png (the TARGET's panel outlines drawn over our UI).
// Usage: node tools/measure_ours.mjs [label]      (label defaults to "current"; used in output file names)
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const { chromium } = createRequire(import.meta.url)('playwright');
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const label = process.argv[2] || 'current';
const target = JSON.parse(readFileSync(join(root, 'docs/hive/measurements/target.json'), 'utf8'));
const PORT = 4179;
const SELECTORS = {
  chats: '#panel-chats', projects: '#panel-projects', agents: '#panel-agents',
  card_current: '#card-current', card_next: '#card-next', card_context: '#card-context', card_external: '#card-external', card_layout: '#card-layout',
  activity: '#panel-activity', approvals: '#panel-approvals', resources: '#panel-resources', limits: '#panel-limits', composer: '#chat-draft-form',
};
const TEXT = { // selector -> what it is; font-size is read from computed style (SVG text through the CTM)
  panel_title: '.hp-head h2', card_title: '.tc-head h2', card_main: '.tc-main', body_row: '.rail-row strong', approval_label: '.approval-row strong',
  button: '.ap-btn', gauge_label: '.gauge label', limit_label: '.limit-row strong', node_name: '#core-agents .ca-name', node_caption: '#core-agents .ca-state',
  ctx_label: '.ctx-item text', internet_label: '#node-internet .ca-name', composer_input: '#chat-draft-input', top_brand: '.tb-brand strong', chip: '.source-chip',
};
const COLOURS = ['.hive-panel', '.ap-btn.approve', '.ap-actions .ap-btn:nth-child(2)', '.ap-btn.reject', '.source-chip', '.hp-chip', '.gauge[data-k="cpu"] .g-val', '.gauge[data-k="ram"] .g-val', '.gauge[data-k="gpu"] .g-val', '.limit-row .bar span', '.ring-orbit', '#ultron-ring', '.photon'];

const srv = spawn('python', ['fixture_server.py', '--port', String(PORT)], { cwd: root, stdio: 'ignore' });
for (let i = 0; i < 60; i++) { try { if ((await fetch(`http://127.0.0.1:${PORT}/`)).ok) break; } catch { /* retry */ } await new Promise(r => setTimeout(r, 100)); }
const browser = await chromium.launch();
mkdirSync(join(root, 'docs/hive/measurements'), { recursive: true });
try {
  for (const [w, h] of [[1280, 720], [1920, 1080], [2560, 1440]]) {
    const p = await browser.newPage({ viewport: { width: w, height: h } });
    await p.goto(`http://127.0.0.1:${PORT}/`);
    await p.waitForFunction(() => document.querySelector('#core-stage')?.dataset.coreState === 'WORKING', null, { timeout: 9000 });
    await p.waitForTimeout(2600);
    const data = await p.evaluate(({ SELECTORS, TEXT, COLOURS }) => {
      const R = e => { const r = e.getBoundingClientRect(); return { x0: r.left, y0: r.top, x1: r.right, y1: r.bottom, w: r.width, h: r.height }; };
      const out = { viewport: { w: innerWidth, h: innerHeight }, panels: {}, text: {}, colours: {}, core: {}, gutters: {} };
      for (const [k, s] of Object.entries(SELECTORS)) { const e = document.querySelector(s); if (e) out.panels[k] = R(e); }
      const fs = e => { const cs = getComputedStyle(e); let px = parseFloat(cs.fontSize); const svg = e.ownerSVGElement; if (svg) px *= svg.getScreenCTM().a; return { font_px: +px.toFixed(2), weight: cs.fontWeight, letter_spacing: cs.letterSpacing, family: cs.fontFamily.split(',')[0].replace(/"/g, ''), colour: cs.fill && svg ? cs.fill : cs.color }; };
      for (const [k, s] of Object.entries(TEXT)) { const e = document.querySelector(s); if (e) out.text[k] = fs(e); }
      for (const s of COLOURS) { const e = document.querySelector(s); if (!e) continue; const cs = getComputedStyle(e); out.colours[s] = { color: cs.color, background: cs.backgroundColor, border: cs.borderTopColor, stroke: cs.stroke, border_width: cs.borderTopWidth }; }
      const circ = e => { const r = e.getBoundingClientRect(); return { cx: +(r.left + r.width / 2).toFixed(1), cy: +(r.top + r.height / 2).toFixed(1), r: +(r.width / 2).toFixed(1) }; };
      const ring = circ(document.querySelector('#ultron-ring')); out.core.ultron_ring = ring;
      out.core.orbit_ring = circ(document.querySelector('.ring-orbit')); out.core.horizon = circ(document.querySelector('.horizon'));
      out.core.planet = circ(document.querySelector('#node-internet .planet'));
      out.core.nodes = {}; out.core.polar = {};
      for (const g of document.querySelectorAll('#core-agents .core-agent, #ultron-icon')) {
        const c = circ(g.querySelector('circle:not(.halo)')); const k = g.dataset.agent; out.core.nodes[k] = c;
        const dx = c.cx - ring.cx, dy = c.cy - ring.cy; out.core.polar[k] = { angle_deg: +(Math.atan2(dy, dx) * 180 / Math.PI).toFixed(1), r_over_ring: +(Math.hypot(dx, dy) / ring.r).toFixed(3) };
      }
      const pl = out.core.planet; const dxp = pl.cx - ring.cx, dyp = pl.cy - ring.cy; out.core.polar.INTERNET_planet = { angle_deg: +(Math.atan2(dyp, dxp) * 180 / Math.PI).toFixed(1), r_over_ring: +(Math.hypot(dxp, dyp) / ring.r).toFixed(3) };
      const P = out.panels; const gx = (a, b) => +(P[b].x0 - P[a].x1).toFixed(1), gy = (a, b) => +(P[b].y0 - P[a].y1).toFixed(1);
      Object.assign(out.gutters, { chats_to_projects_y: gy('chats', 'projects'), projects_to_agents_y: gy('projects', 'agents'), activity_to_approvals_y: gy('activity', 'approvals'),
        resources_to_limits_x: gx('resources', 'limits'), card_current_to_next_x: gx('card_current', 'card_next'), card_next_to_context_x: gx('card_next', 'card_context'),
        card_context_to_external_x: gx('card_context', 'card_external'), card_external_to_layout_x: gx('card_external', 'card_layout'),
        left_rail_to_center_x: +(P.card_current.x0 - P.chats.x1).toFixed(1), center_to_right_rail_x: +(P.activity.x0 - P.card_layout.x1).toFixed(1), resources_to_composer_y: gy('resources', 'composer') });
      return out;
    }, { SELECTORS, TEXT, COLOURS });
    writeFileSync(join(root, `docs/hive/measurements/ours-${label}-${w}x${h}.json`), JSON.stringify(data, null, 1));
    // overlay: the target's panel outlines (yellow) and neon ring (cyan) scaled onto our UI
    await p.evaluate(({ t, w, h }) => {
      const sx = w / t.image_px.w, sy = h / t.image_px.h; const box = document.createElement('div'); box.id = 'target-overlay'; box.style.cssText = 'position:fixed;inset:0;z-index:999;pointer-events:none';
      for (const q of Object.values(t.panels)) { const d = document.createElement('div'); d.style.cssText = `position:absolute;left:${q.x0 * sx}px;top:${q.y0 * sy}px;width:${(q.x1 - q.x0) * sx}px;height:${(q.y1 - q.y0) * sy}px;border:2px solid #ffe14a`; box.appendChild(d); }
      const r = t.core.neon_ring; const c = document.createElement('div'); c.style.cssText = `position:absolute;left:${(r.cx - r.r) * sx}px;top:${(r.cy - r.r) * sy}px;width:${2 * r.r * sx}px;height:${2 * r.r * sy}px;border:2px solid #29e5ff;border-radius:50%`; box.appendChild(c);
      for (const n of Object.values(t.core.nodes)) if (n) { const d = document.createElement('div'); d.style.cssText = `position:absolute;left:${n.cx * sx - 6}px;top:${n.cy * sy - 6}px;width:12px;height:12px;background:#ff3df2;border-radius:50%`; box.appendChild(d); }
      document.body.appendChild(box);
    }, { t: target, w, h });
    await p.screenshot({ path: join(root, `docs/hive/screenshots/overlay-${label}-${w}x${h}.png`) });
    await p.close();
  }
} finally { await browser.close(); srv.kill(); }
console.log('measured', label);
