import { test } from 'node:test';
import assert from 'node:assert/strict';
import { realpathSync, mkdirSync, mkdtempSync, writeFileSync, readFileSync, symlinkSync, readdirSync } from 'node:fs';
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

// Exercise the real subprocess boundary without touching personal continuity data.
// Retain fixture artifacts under the ignored D: runtime directory for inspection.
async function failureHarness(mode) {
  const root = realpathSync(fileURLToPath(new URL('../..', import.meta.url)));
  mkdirSync(root+'/.sumika-next/continuity-tests', { recursive: true });
  const dir = mkdtempSync(root+'/.sumika-next/continuity-tests/failure-');
  const core = dir+'/fixture.py';
  writeFileSync(core, `import json, pathlib, sys
request = json.load(sys.stdin)
with pathlib.Path(__file__).with_suffix('.calls').open('a') as f:
    f.write(request['action'] + '\\n')
if ${JSON.stringify(mode)} == 'exit':
    sys.stderr.write('SECRET subprocess path and payload')
    sys.exit(1)
print(json.dumps({'status': 'ok' if ${JSON.stringify(mode)} == 'healthy' else 'unknown', 'private': 'SECRET'}))
`);
  const handlers = new Map(), registered = new Map();
  const config = {
    projects: [dir], runtimeEntry: realpathSync(root+'/runtime/dsh/node_modules/@deepseek-ai/dsh/package.json'),
    python: process.env.SUMIKA_TEST_PYTHON || 'D:/Tools/python/Python314/python.exe', core,
  };
  const ctx = { tools: { register(t) { registered.set(t.name, t); } }, effect() {},
    logger: { warn() {} }, on(name, fn) { handlers.set(name, fn); } };
  await apply(ctx, config);
  const session = { header: { id: 'fixture', cwd: dir }, snapshotEvents: () => [] };
  return { handlers, registered, session, core, restart: () => apply(ctx, config),
    calls: () => readFileSync(dir+'/fixture.calls', 'utf8').trim().split(/\r?\n/) };
}

test('unknown result stays fenced after adapter restart and storage repair', async () => {
  const h = await failureHarness('unknown');
  await assert.rejects(h.registered.get('continuity_query').execute({}, {agent:{session:h.session}}), unavailable);
  // Repair the worker; reloading the adapter must not retry the unknown call.
  writeFileSync(h.core, "raise RuntimeError('REPAIRED WORKER MUST NOT RUN')\n");
  await h.restart();
  const restored = {header:{...h.session.header}, snapshotEvents: () => []};
  await assert.rejects(h.handlers.get('session/flush')(restored), unavailable);
  await assert.rejects(h.registered.get('continuity_query').execute({}, {agent:{session:restored}}), unavailable);
  assert.deepEqual(h.calls(), ['recover']);
});

test('settled operation permits normal reads after adapter restart', async () => {
  const h = await failureHarness('healthy');
  await h.registered.get('continuity_query').execute({}, {agent:{session:h.session}});
  await h.restart();
  const restored = {header:{...h.session.header}, snapshotEvents: () => []};
  await h.registered.get('continuity_query').execute({}, {agent:{session:restored}});
  assert.deepEqual(h.calls(), ['recover', 'recover']);
});

test('linked state directory is rejected before writing or launching storage', async () => {
  const h = await failureHarness('healthy');
  const outside = mkdtempSync(h.session.header.cwd+'-outside-');
  symlinkSync(outside, h.session.header.cwd+'/.sumika-continuity', 'junction');
  await assert.rejects(h.registered.get('continuity_query').execute({}, {agent:{session:h.session}}), unavailable);
  assert.deepEqual(readdirSync(outside), []);
});

function unavailable(error) {
  assert.equal(error.code, 'CONTINUITY_UNAVAILABLE');
  assert.equal(error.message, 'Continuity outcome unknown; automatic retries disabled');
  assert.equal(String(error).includes('SECRET'), false);
  return true;
}

for (const mode of ['unknown', 'exit']) {
  test(`capture ${mode} fences queued flush, tools and model admission without retry`, async () => {
    const h = await failureHarness(mode);
    h.session.snapshotEvents = () => [{ seq: 0, type: 'user/message', surfaceOp: 'append',
      data: { id: 'm1', source: { kind: 'user' }, content: [] } }];
    const exec = { agent: { session: h.session }, callId: 'c1' };
    const operations = [
      h.handlers.get('session/flush')(h.session),
      h.handlers.get('session/flush')(h.session),
      h.registered.get('continuity_query').execute({}, exec),
      h.registered.get('continuity_record').execute({ report: '{}' }, exec),
      h.handlers.get('agent/pre-step')({ ...exec, turn: 1 }, async () => ({ kind: 'enter', messages: [] })),
      h.handlers.get('agent/turn-stopping')(exec),
    ];
    await Promise.all(operations.map(p => assert.rejects(p, unavailable)));
    assert.deepEqual(h.calls(), ['ingest']);
  });
}

for (const action of ['recover', 'query', 'report']) {
  test(`${action} failure fences later capture and tool calls`, async () => {
    const h = await failureHarness('unknown');
    h.session.snapshotEvents = () => [{ seq: 0, type: 'step/start', data: { turn: 1, step: 1 } }];
    const exec = { agent: { session: h.session }, callId: 'c1' };
    const first = action === 'recover'
      ? h.handlers.get('agent/pre-step')({ ...exec, turn: 1 }, async () => ({ kind: 'enter', messages: [] }))
      : h.registered.get(action === 'query' ? 'continuity_query' : 'continuity_record')
        .execute(action === 'query' ? { query: '{}' } : { report: '{}' }, exec);
    await assert.rejects(first, unavailable);
    await assert.rejects(h.handlers.get('session/flush')(h.session), unavailable);
    await assert.rejects(h.registered.get('continuity_query').execute({}, exec), unavailable);
    assert.deepEqual(h.calls(), [action]);
  });
}

test('native model/tool history is not duplicated and provider secrets are excluded', () => {
  const e = observation({ seq: 5, type: 'assistant/message', data: { turn: 1, step: 1,
    message: { source: { kind: 'model', model: 'a' }, content: [
      { type: 'reasoning', text: 'private' }, { type: 'text', text: 'result' }] } } });
  assert.equal(e, undefined);
  assert.equal(observation({ seq: 6, type: 'tool/result', data: {} }), undefined);
  const m = observation({ seq: 6, type: 'request/header', data: { reason: 'change',
    header: { config: { model: 'b', provider: 'local', apiKey: 'private' } } } });
  assert.equal(m.payload.model, 'b');
  assert.equal(JSON.stringify(m).includes('private'), false);
});

test('disabled extension registers nothing and does not access runtime or storage', async () => {
  await apply(new Proxy({}, { get() { throw Error('unexpected registration'); } }), { enabled: false });
  await assert.rejects(apply({}, { enabled: 'false' }), /enabled must be boolean/);
});

test('rejected steps and empty/native-only sync do not launch storage', async () => {
  const root = realpathSync(fileURLToPath(new URL('../..', import.meta.url)));
  const runtimeEntry = realpathSync(root+'/runtime/dsh/node_modules/@deepseek-ai/dsh/package.json');
  const handlers = new Map();
  const ctx = { tools: { register() {} }, effect() {}, on(name, fn) { handlers.set(name, fn); } };
  await apply(ctx, { projects: [root], runtimeEntry, python: 'MUST_NOT_RUN', core: 'MUST_NOT_READ' });
  const rejected = { kind: 'reject' };
  const result = await handlers.get('agent/pre-step')({ agent: { session: { header: { cwd: root } } }, turn: 1 },
    async () => rejected);
  assert.equal(result, rejected);
  const session = { header: { cwd: root }, snapshotEvents: () => [] };
  await handlers.get('session/flush')(session);
  session.snapshotEvents = () => [{ seq: 0, type: 'tool/result', data: {} }];
  await handlers.get('session/flush')(session);
});
