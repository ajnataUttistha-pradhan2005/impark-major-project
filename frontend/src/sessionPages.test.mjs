import assert from 'node:assert/strict';
import test from 'node:test';
import { loadAllSessions } from './sessionPages.mjs';

test('loads old chats past the first page before showing an empty sidebar', async () => {
  const calls = [];
  const rows = Array.from({ length: 35 }, (_, index) => ({ session_id: `chat-${index}` }));
  const getPage = async (archived, offset) => {
    calls.push({ archived, offset });
    return { items: rows.slice(offset, offset + 30), next_offset: offset + 30 < rows.length ? offset + 30 : null };
  };
  const all = await loadAllSessions(getPage, false, () => true);
  assert.equal(all.length, 35);
  assert.deepEqual(calls, [{ archived: false, offset: 0 }, { archived: false, offset: 30 }]);
  rows.length = 0;
  assert.deepEqual(await loadAllSessions(getPage, false, () => true), []);
});

test('an obsolete refresh cannot restore chats after a mutation', async () => {
  let current = true;
  let resolvePage;
  const page = new Promise(resolve => { resolvePage = resolve; });
  const loading = loadAllSessions(() => page, false, () => current);
  current = false;
  resolvePage({ items: [{ session_id: 'deleted' }], next_offset: null });
  assert.equal(await loading, null);
});

test('rejects a non-advancing pagination cursor', async () => {
  await assert.rejects(
    loadAllSessions(async () => ({ items: [], next_offset: 0 }), false, () => true),
    /Invalid session page cursor/,
  );
});
