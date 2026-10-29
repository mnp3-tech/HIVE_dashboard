// Zero-dependency structural contract check for the P-018 HIVE cockpit UI.
// Run with: node tests/ui_contract.test.mjs
// Static text checks only -- no DOM, no network, no browser. Verifies required
// ids/classes exist and are wired between index.html/app.js, and that no secret-
// shaped string (server-only env var names, bearer tokens, raw credentials) has
// leaked into any shipped UI file.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(join(root, 'index.html'), 'utf8');
const css = readFileSync(join(root, 'styles.css'), 'utf8');
const js = readFileSync(join(root, 'app.js'), 'utf8');

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`ok - ${name}`); }
  catch (error) { console.error(`FAIL - ${name}\n  ${error.message}`); process.exitCode = 1; }
}

test('required ids exist in index.html', () => {
  for (const id of [
    'mode-group', 'density-toggle', 'rail-mode', 'rail-density',
    'workers-panel', 'worker-policy-cards', 'worker-policy-evidence', 'worker-policy-validity',
    'hive-orbit-panel', 'hive-orbit', 'orbit-validity', 'orbit-evidence', 'orbit-empty',
    'chat-panel', 'chat-transcript', 'chat-session-label', 'chat-draft-form', 'chat-draft-input',
    'evolution-panel', 'evolution-validity', 'evolution-evidence', 'evolution-summary', 'local-worker-cards', 'cli-worker-status-panel', 'cli-worker-validity', 'cli-worker-evidence', 'cli-worker-cards', 'local-inference-status', 'handoff-panel', 'handoff-validity', 'handoff-evidence', 'handoff-summary',
    'evidence-drawer', 'evidence-drawer-title', 'evidence-drawer-source', 'evidence-drawer-validity',
    'evidence-drawer-observed', 'evidence-drawer-reason', 'evidence-drawer-close',
  ]) assert.match(html, new RegExp(`id="${id}"`), `missing #${id} in index.html`);
});

test('COMMAND/OBSERVE/FOCUS mode buttons are present with distinct data-mode values', () => {
  for (const mode of ['command', 'observe', 'focus']) assert.match(html, new RegExp(`data-mode="${mode}"`));
});

test('app.js is wired to every new index.html id/class it needs', () => {
  for (const id of ['density-toggle', 'worker-policy-cards', 'worker-policy-evidence', 'hive-orbit', 'chat-transcript', 'chat-draft-form', 'evidence-drawer', 'evidence-drawer-close', 'rail-mode', 'rail-density', 'handoff-evidence']) {
    assert.match(js, new RegExp(id), `app.js never references #${id}`);
  }
  assert.match(js, /mode-button/, 'app.js never references .mode-button');
});

test('HIVE orbit uses only snapshot workers, tasks and timestamped events', () => {
  assert.match(js, /function renderHiveOrbit/);
  assert.match(js, /snapshot\.workers/);
  assert.match(js, /snapshot\.events/);
  assert.match(js, /orbit-edge/);
  assert.match(html, /No verified topology yet/);
});

test('chat panel is read-only and drafts into the proposal flow', () => {
  assert.match(js, /api\/ao\/sessions/);
  assert.match(js, /safeChatText/);
  assert.match(js, /no provider message sent/);
  assert.doesNotMatch(js, /fetch\(['"]\/api\/ao\/sessions\/.*send/);
});

test('project registry and self-evolution checkpoint stay evidence-backed', () => {
  assert.match(js, /projectRegistry/);
  assert.match(js, /selfEvolution/);
  assert.match(js, /obsidian:Registry\/projects\.json/);
  assert.match(js, /proposal-only/);
});

test('local worker panel uses bounded probes and never auto-starts providers', () => {
  assert.match(html, /id="local-worker-cards"/);
  assert.match(js, /local_worker_status|localWorkers/);
  assert.match(js, /workers are never auto-started/);
  assert.match(css, /local-worker-grid/);
});

test('CLI worker evidence stays separate from execution readiness', () => {
  assert.match(js, /api\/local-workers\/cli-status/);
  assert.match(js, /VERSION PROBE ONLY/);
  assert.match(html, /inference is not invoked during dashboard load/);
  assert.match(html, /Installation evidence, not execution readiness/);
  assert.match(html, /Model-list availability does not imply inference readiness/);
});

test('handoff panel exposes proposal-only capability without delivery', () => {
  assert.match(html, /HANDOFF \/ RESUME/);
  assert.match(js, /api\/control\/capabilities/);
  assert.match(js, /handoff-proposal/);
  assert.match(js, /no delivery or retry/);
});

test('degraded local inference cannot be rendered as available', () => {
  assert.doesNotMatch(js, /local-workers\/lmstudio\/infer/);
  assert.match(html, /completed or degraded evidence/);
  assert.match(html, /does not imply inference readiness/);
});

test('self-evolution panel exposes HIVE auth uncertainty instead of claiming valid lifecycle state', () => {
  assert.match(js, /selfEvolution/);
  assert.match(js, /HIVE \/evolution/);
  assert.match(js, /AUTH_REQUIRED|auth_required/);
});

test('narrow layout explicitly prevents horizontal overflow', () => {
  assert.match(css, /overflow-x:hidden/);
  assert.match(css, /main-shell\{width:calc\(100% - 70px\)/);
});

test('app.js declares all three density states and all three operator modes as literals', () => {
  for (const density of ['full', 'reduced', 'minimal']) assert.match(js, new RegExp(`'${density}'`));
  assert.match(js, /DENSITY_CYCLE/);
});

test('evidence-line triggers never hide evidence text behind a density class', () => {
  // ui-direction.md: "reduced modes lowering motion/detail rather than hiding
  // evidence labels" -- density-minimal CSS must not set display:none on evidence
  // lines.
  const minimalBlock = css.match(/body\.density-minimal[^}]*\{[^}]*\}/g) || [];
  for (const rule of minimalBlock) assert.doesNotMatch(rule, /evidence-line[^{]*\{[^}]*display:\s*none/);
});

test('worker intelligence panel renders a trust-boundary badge (local vs remote/subscription)', () => {
  assert.match(js, /trust-badge/);
  assert.match(js, /LOCAL/);
  assert.match(js, /EXTERNAL \/ SUBSCRIPTION/);
});

test('worker intelligence panel never fabricates a non-loopback or invented remote endpoint label', () => {
  assert.match(js, /No local endpoint declared/);
  assert.match(js, /Remote .{1,3} no endpoint declared/);
});

test('UNKNOWN/STALE/BLOCKED vocabulary is used instead of fabricated healthy defaults', () => {
  assert.match(js, /UNKNOWN/);
  assert.match(js, /STALE \/ UNOBSERVED/);
  assert.match(js, /BLOCKED/);
});

test('evidence drawer dialog explicitly disclaims prompts/tokens/raw sessions', () => {
  assert.match(html, /never shows prompts, tokens, credentials, or raw provider session content/);
});

const FORBIDDEN_PATTERNS = [
  /HIVE_API_TOKEN/i, /AO_SEND_CALLER_TOKEN/i, /AO_CLI_PATH/i, /CREATOR_OPS_DB_PATH/i,
  /LMSTUDIO_ENDPOINT/i, /CODEX_SUBSCRIPTION_CONFIRMED/i,
  /Bearer\s+[A-Za-z0-9\-_.=]{8,}/, // an actual bearer token value, not the word "Bearer"
  /sk-[A-Za-z0-9]{20,}/, /AKIA[0-9A-Z]{16}/,
];
test('no server-only secret/env-var names or token-shaped values appear in any shipped UI file', () => {
  for (const [file, text] of [['index.html', html], ['styles.css', css], ['app.js', js]]) {
    for (const pattern of FORBIDDEN_PATTERNS) assert.doesNotMatch(text, pattern, `${file} matched forbidden pattern ${pattern}`);
  }
});

test('dispatch request body never includes a credential/token field', () => {
  const dispatchCall = js.match(/fetch\('\/api\/control\/dispatch'[\s\S]{0,400}?\)/);
  assert.ok(dispatchCall, 'dispatch fetch call not found');
  assert.doesNotMatch(dispatchCall[0], /token|password|secret|credential/i);
});

console.log(`\n${passed} passed`);
if (process.exitCode) { console.error('UI contract check FAILED'); } else { console.log('UI contract check OK'); }
