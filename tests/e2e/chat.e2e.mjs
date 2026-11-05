// P0.3 E2E: composer (attach, chips, Enter vs Shift+Enter, NOT_CONNECTED), Activity sanitisation, Approvals fallback.
// Run: node --test tests/e2e/chat.e2e.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';

const { chromium } = createRequire(import.meta.url)('playwright');
const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FIX = 'http://127.0.0.1:4194/', LIVE = 'http://127.0.0.1:4193/';
const procs = []; let browser; let dir;
async function up(args, url) {
  const p = spawn('python', args, { cwd: root, stdio: 'ignore', env: { ...process.env, HIVE_API_TOKEN: '', AO_CLI_PATH: '', AO_SEND_CALLER_TOKEN: '' } }); procs.push(p);
  for (let i = 0; i < 60; i++) { try { if ((await fetch(url)).ok) return; } catch { /* retry */ } await new Promise(r => setTimeout(r, 100)); }
  throw new Error('server did not start');
}
test.before(async () => {
  dir = mkdtempSync(join(tmpdir(), 'hive-e2e-'));
  for (const [n, c] of [['notes.txt', 'hello'], ['data.csv', 'a,b\n1,2'], ['plan.md', '# plan']]) writeFileSync(join(dir, n), c);
  await up(['fixture_server.py', '--port', '4194'], FIX); await up(['server.py', '--port', '4193'], LIVE);
  browser = await chromium.launch();
});
test.after(async () => { await browser?.close(); procs.forEach(p => p.kill()); });

async function open(url, vp = { width: 1920, height: 1080 }) {
  const ctx = await browser.newContext({ viewport: vp }); const p = await ctx.newPage();
  const errors = [], posts = []; p.on('pageerror', e => errors.push(String(e)));
  p.on('request', r => { if (r.method() !== 'GET') posts.push(r.method() + ' ' + r.url()); });
  await p.goto(url, { waitUntil: 'domcontentloaded' }); await p.waitForSelector('#chat-draft-input');
  return { p, errors, posts, ctx };
}
const outbox = p => p.$$eval('#chat-outbox .outbox-row', rows => rows.map(r => ({ state: r.dataset.state, text: r.querySelector('.ob-text').textContent })));

test('attach multiple files -> chips, removable, contents never uploaded', async () => {
  const { p, errors, posts, ctx } = await open(LIVE);
  await p.setInputFiles('#attach-input', [join(dir, 'notes.txt'), join(dir, 'data.csv'), join(dir, 'plan.md')]);
  assert.deepEqual(await p.$$eval('#attachment-chips .chip-name', e => e.map(x => x.textContent)), ['notes.txt', 'data.csv', 'plan.md']);
  assert.match(await p.$eval('#attachment-chips', e => e.textContent), /not uploaded/);
  await p.click('#attachment-chips .chip:nth-of-type(2) .chip-x');
  assert.deepEqual(await p.$$eval('#attachment-chips .chip-name', e => e.map(x => x.textContent)), ['notes.txt', 'plan.md']);
  assert.deepEqual(posts, []); assert.deepEqual(errors, []); await ctx.close();
});

test('Enter sends, Shift+Enter inserts a newline; no provider => NOT_CONNECTED (never SENT)', async () => {
  const { p, errors, posts, ctx } = await open(LIVE);
  await p.setInputFiles('#attach-input', [join(dir, 'notes.txt')]);
  await p.click('#chat-draft-input'); await p.keyboard.type('line one'); await p.keyboard.press('Shift+Enter'); await p.keyboard.type('line two');
  assert.equal(await p.$eval('#chat-draft-input', e => e.value), 'line one\nline two');
  assert.deepEqual(await outbox(p), [], 'Shift+Enter must not send');
  await p.keyboard.press('Enter'); await p.waitForSelector('#chat-outbox .outbox-row');
  const rows = await outbox(p); assert.equal(rows.length, 1); assert.equal(rows[0].state, 'NOT_CONNECTED');
  assert.match(rows[0].text, /line one/);
  assert.equal(await p.$eval('#chat-draft-input', e => e.value), '', 'composer cleared'); assert.equal(await p.$eval('#attachment-chips', e => e.hidden), true);
  const status = await p.$eval('#chat-draft-status', e => e.textContent); assert.match(status, /NOT_CONNECTED/); assert.match(status, /no provider message sent/);
  assert.equal(await p.$$eval('.ob-state', e => e.some(x => x.textContent === 'SENT')), false);
  assert.equal(await p.$eval('#chat-outbox', e => /SENT/.test(e.innerText.replace(/NOT_CONNECTED/g, ''))), false);
  assert.deepEqual(posts, [], 'nothing is POSTed to any provider/AO route');
  assert.deepEqual(errors, []); await ctx.close();
});

test('empty Enter sends nothing; attachments-only message is allowed; Retry stays NOT_CONNECTED; VOICE disabled', async () => {
  const { p, ctx } = await open(LIVE);
  await p.click('#chat-draft-input'); await p.keyboard.press('Enter'); assert.deepEqual(await outbox(p), []);
  assert.match(await p.$eval('#chat-draft-status', e => e.textContent), /Nothing to send/);
  await p.setInputFiles('#attach-input', [join(dir, 'plan.md')]); await p.click('#send-button');
  await p.waitForSelector('#chat-outbox .outbox-row'); assert.equal((await outbox(p))[0].state, 'NOT_CONNECTED');
  await p.click('[data-retry]'); assert.equal((await outbox(p))[0].state, 'NOT_CONNECTED');
  assert.equal(await p.$eval('#voice-button', e => e.disabled), true); assert.match(await p.$eval('#voice-button', e => e.textContent), /FUTURE/i);
  await ctx.close();
});

test('"Draft as proposal" is an explicit user action that opens the proposal form (no silent hijack)', async () => {
  const { p, ctx } = await open(LIVE);
  await p.click('#chat-draft-input'); await p.keyboard.type('please plan the migration'); await p.keyboard.press('Enter');
  assert.equal(await p.$eval('#console', e => e.hidden), true, 'sending does not open the console');
  await p.click('[data-draft]'); assert.equal(await p.$eval('#console', e => e.hidden), false);
  assert.equal(await p.$eval('#delegate-prompt', e => e.value), 'please plan the migration'); await ctx.close();
});

test('Activity rows show time/role/provider/action/state and never raw prompts, thoughts or secrets', async () => {
  const { p, ctx } = await open(FIX + '?scenario=secrets');
  await p.waitForFunction(() => document.querySelector('#activity-rows')?.innerText.includes('SHURI'), null, { timeout: 8000 });
  const text = await p.$eval('#activity-rows', e => e.innerText);
  for (const bad of ['abcdef1234567890', 'hunter2', 'RAW PROMPT TEXT', 'SECRET THOUGHT', 'private tax return']) assert.ok(!text.includes(bad), `leaked: ${bad}`);
  assert.match(text, /REDACTED/); assert.match(text, /content withheld/);
  const row = await p.$eval('#activity-rows .act-row', e => ({ time: !!e.querySelector('time'), role: !!e.querySelector('.act-meta b'), meta: e.querySelectorAll('.act-meta > *').length, action: !!e.querySelector('.act-action') }));
  assert.deepEqual(row, { time: true, role: true, meta: 3, action: true }); await ctx.close();
});

test('Approvals: GPT/CODEX/CLAUDE rows; no pending => buttons disabled; Edit disabled without adapter', async () => {
  const { p, ctx } = await open(LIVE);
  assert.deepEqual(await p.$$eval('#approval-rows .approval-row strong', e => e.map(x => x.textContent)), ['GPT', 'CODEX', 'CLAUDE']);
  assert.equal(await p.$$eval('#approval-rows .ap-btn', e => e.every(b => b.disabled)), true);
  assert.match(await p.$eval('#approval-rows', e => e.innerText), /UNKNOWN/); await ctx.close();
});

test('Approvals fallback: Approve changes local state only and says so; persists; no network write', async () => {
  const { p, errors, posts, ctx } = await open(FIX + '?scenario=approval');
  await p.waitForFunction(() => document.querySelector('.approval-row[data-provider="gpt"] .ap-state')?.textContent.includes('PENDING'), null, { timeout: 8000 });
  assert.equal(await p.$eval('#core-stage', e => e.dataset.coreState), 'WAITING_APPROVAL');
  assert.equal(await p.$eval('.approval-row[data-provider="claude"] .ap-btn.approve', b => b.disabled), true, 'no pending claude approval');
  assert.equal(await p.$eval('.approval-row[data-provider="gpt"] [data-act="edit"]', b => b.disabled), true, 'Edit needs adapter/deep link');
  await p.click('.approval-row[data-provider="gpt"] .ap-btn.approve');
  await p.waitForFunction(() => document.querySelector('.approval-row[data-provider="gpt"] .ap-state')?.textContent.includes('Approved locally, source not updated'));
  assert.equal(await p.$$eval('.approval-row[data-provider="gpt"] .ap-btn', e => e.every(b => b.disabled)), true);
  assert.doesNotMatch(await p.$eval('.approval-row[data-provider="gpt"] .ap-state', e => e.textContent), /at source/i);
  assert.deepEqual(posts, [], 'a local decision must not write to any source'); assert.deepEqual(errors, []);
  await p.reload({ waitUntil: 'domcontentloaded' });
  await p.waitForFunction(() => document.querySelector('.approval-row[data-provider="gpt"] .ap-state')?.textContent.includes('Approved locally'), null, { timeout: 8000 });
  await ctx.close();
});

test('Approvals fallback: Reject is also local and labelled', async () => {
  const { p, ctx } = await open(FIX + '?scenario=approval');
  await p.waitForSelector('.approval-row[data-provider="gpt"] .ap-btn.reject:not([disabled])', { timeout: 8000 });
  await p.click('.approval-row[data-provider="gpt"] .ap-btn.reject');
  await p.waitForFunction(() => document.querySelector('.approval-row[data-provider="gpt"] .ap-state')?.textContent.includes('Rejected locally, source not updated')); await ctx.close();
});

test('composer with chips fits at 1280x720 without clipping or overlap; screenshot saved', async () => {
  const { p, ctx } = await open(LIVE, { width: 1280, height: 720 });
  await p.setInputFiles('#attach-input', [join(dir, 'notes.txt'), join(dir, 'data.csv'), join(dir, 'plan.md')]);
  await p.click('#chat-draft-input'); await p.keyboard.type('hello'); await p.keyboard.press('Enter'); await p.waitForSelector('.outbox-row');
  await p.setInputFiles('#attach-input', [join(dir, 'notes.txt'), join(dir, 'data.csv')]);
  const bad = await p.evaluate(() => { const out = []; const bx = e => e.getBoundingClientRect();
    const comp = bx(document.querySelector('#chat-draft-form')), res = bx(document.querySelector('#res-row')), core = bx(document.querySelector('#core-stage'));
    if (comp.top < res.bottom - 0.5) out.push('composer overlaps resources'); if (core.bottom > res.top + 0.5) out.push('core overlaps resources');
    if (comp.bottom > innerHeight || comp.right > innerWidth) out.push('composer off-screen');
    document.querySelectorAll('#chat-draft-form *').forEach(e => { const r = bx(e), c = bx(document.querySelector('#chat-draft-form')); if (r.width && (r.right > c.right + 1 || r.left < c.left - 1)) out.push('outside composer: ' + (e.id || e.className)); });
    const o = bx(document.querySelector('#panel-chats')); document.querySelectorAll('#panel-chats *').forEach(e => { const r = bx(e); if (r.width && r.right > o.right + 1) out.push('outside chats: ' + (e.className || e.tagName)); });
    return out; });
  assert.deepEqual(bad, []);
  // the outbox row must be visible inside the CHATS panel (regression: empty states once crushed CHATS to ~60px)
  const vis = await p.evaluate(() => { const pr = document.querySelector('#panel-chats').getBoundingClientRect(), r = document.querySelector('#chat-outbox .outbox-row').getBoundingClientRect(), o = document.querySelector('#chat-outbox').getBoundingClientRect();
    return { panelH: pr.height, rowInside: r.top >= o.top - 1 && r.bottom <= o.bottom + 1 && r.height > 10 && r.bottom <= pr.bottom + 1 }; });
  const shape = await p.evaluate(() => { const r = document.querySelector('#chat-outbox .outbox-row'), t = r.querySelector('.ob-text'), st = r.querySelector('.ob-state');
    return { rowH: r.getBoundingClientRect().height, textW: t.getBoundingClientRect().width, stateScroll: st.scrollWidth <= st.clientWidth + 1, btns: [...r.querySelectorAll('.ap-btn')].every(b => b.getBoundingClientRect().width >= 40) }; });
  assert.ok(shape.textW >= 60, `outbox text squeezed to ${shape.textW}px`); assert.ok(shape.rowH <= 120, `outbox row too tall: ${shape.rowH}px`); assert.equal(shape.stateScroll, true); assert.equal(shape.btns, true);
  assert.ok(vis.panelH >= 140, `CHATS panel too small: ${vis.panelH}px`); assert.equal(vis.rowInside, true, 'outbox row clipped');
  assert.ok((await p.$eval('#hive-core-art', e => e.getBoundingClientRect().height)) >= 720 * 0.35, 'CORE still dominant with chips visible');
  await p.screenshot({ path: join(root, 'docs/hive/screenshots/composer-1280x720.png') }); await ctx.close();
});
