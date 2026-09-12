import { test } from 'node:test';
import assert from 'node:assert/strict';
import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { observation, apply } from './dsh.mjs';

test('human text survives while plugin messages and surface rewrites are excluded', () => {
  const event = { seq: 4, type: 'user/message', surfaceOp: 'append',
    data: { id: 'm1', source: { kind: 'user' }, content: [{ type: 'text', text: ' 原文\r\n```diff``` ' }] } };
  assert.deepEqual(observation(event).payload, event.data);
  const inserted = observation({ seq: 1, type: 'agent/inbox/spliced', data: { inserted: [event.data] } });
  assert.deepEqual(inserted, [observation(event)]);
  assert.equal(observation({ ...event, data: { ...event.data, source: { kind: 'plugin' } } }), undefined);
  assert.equal(observation({ ...event, surfaceOp: { op: 'replace' } }), undefined);
});

test('assistant reasoning and provider secrets never enter normalized observations', () => {
  const e = observation({ seq: 5, type: 'assistant/message', data: { turn: 1, step: 1,
    message: { source: { kind: 'model', model: 'a' }, content: [
      { type: 'reasoning', text: 'private' }, { type: 'text', text: 'result' }] } } });
  assert.deepEqual(e.payload.content, [{ type: 'text', text: 'result' }]);
  const m = observation({ seq: 6, type: 'request/header', data: { reason: 'change',
    header: { config: { model: 'b', provider: 'local', apiKey: 'private' } } } });
  assert.equal(m.payload.model, 'b');
  assert.equal(JSON.stringify(m).includes('private'), false);
});

test('disabled extension registers nothing and does not access runtime or storage', async () => {
  await apply(new Proxy({}, { get() { throw Error('unexpected registration'); } }), { enabled: false });
  await assert.rejects(apply({}, { enabled: 'false' }), /enabled must be boolean/);
});

test('downstream rejection remains rejection without storage or message mutation', async () => {
  const root = realpathSync(fileURLToPath(new URL('../..', import.meta.url)));
  const runtimeEntry = realpathSync(root+'/runtime/dsh/node_modules/@deepseek-ai/dsh/package.json');
  const handlers = new Map();
  const ctx = { tools: { register() {} }, effect() {}, on(name, fn) { handlers.set(name, fn); } };
  await apply(ctx, { projects: [root], runtimeEntry, python: 'MUST_NOT_RUN', core: 'MUST_NOT_READ' });
  const rejected = { kind: 'reject' };
  const result = await handlers.get('agent/pre-step')({ agent: { session: { header: { cwd: root } } }, turn: 1 },
    async () => rejected);
  assert.equal(result, rejected);
});
