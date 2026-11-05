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
