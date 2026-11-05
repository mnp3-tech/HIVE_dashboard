// Guards against duplicate element ids in index.html (a duplicate silently disables the second element).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const html = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'index.html'), 'utf8');
test('index.html has no duplicate ids', () => {
  const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]);
  const dup = [...new Set(ids.filter((id, i) => ids.indexOf(id) !== i))];
  assert.deepEqual(dup, []);
});
test('only one composer form/textarea exists', () => {
  assert.equal((html.match(/id="chat-draft-form"/g) || []).length, 1);
  assert.match(html, /<textarea id="chat-draft-input"/);
});

test('every id that app.js looks up statically exists in index.html (a missing id silently hides a feature)', () => {
  const js = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'app.js'), 'utf8');
  const htmlIds = new Set([...html.matchAll(/\sid=["']([^"']+)["']/g)].map(m => m[1]));
  const used = new Set();
  for (const m of js.matchAll(/\$\(\s*['"`]#([A-Za-z0-9_-]+)['"`]/g)) used.add(m[1]);
  for (const m of js.matchAll(/getElementById\(\s*['"]([A-Za-z0-9_-]+)['"]/g)) used.add(m[1]);
  for (const m of js.matchAll(/(?:setText|setSvgText)\(\s*['"]([A-Za-z0-9_-]+)['"]/g)) used.add(m[1]);
  const DYNAMIC = new Set([]); // ids created at runtime would be listed here with a reason
  const missing = [...used].filter(id => !htmlIds.has(id) && !DYNAMIC.has(id));
  assert.deepEqual(missing, []);
  assert.ok(used.size > 40, 'sanity: the scan found the ids');
});
