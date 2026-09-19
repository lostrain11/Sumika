import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {apply} from './development_probe_guard.mjs';

function fixture() {
  const parent = path.resolve('.sumika-next/probe-guard-tests');
  fs.mkdirSync(parent, {recursive: true});
  const base = fs.mkdtempSync(path.join(parent, 'case-'));
  const root = path.join(base, 'work');
  fs.mkdirSync(root);
  const source = path.join(root, 'module.py');
  const tests = path.join(root, 'test.py');
  fs.writeFileSync(source, 'value = 1\n');
  fs.writeFileSync(tests, 'import module\n');
  const policyFile = path.join(base, 'review.json');
  fs.writeFileSync(policyFile, JSON.stringify({schema_version: 1, workspace: root,
    files: ['module.py', 'test.py'], testCommand: 'approved-test', reviewedHashes:
    Object.fromEntries([source, tests].map(p => [path.basename(p), crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')]))}));
  const hooks = {};
  apply({on: (event, handler) => { hooks[event] = handler; }}, {workspace: root, policyFile});
  const call = (name, args, signal = new AbortController().signal) => ({name, arguments: args, signal});
  return {hooks, source, tests, root, policyFile, call};
}

test('multiple explicitly editable files do not grant edits to tests or other files', async () => {
  const {hooks, source, tests, root, policyFile, call} = fixture();
  const doc = path.join(root, 'README.md');
  fs.writeFileSync(doc, 'Task documentation');
  const policy = JSON.parse(fs.readFileSync(policyFile));
  policy.files.push('README.md');
  policy.editableFiles = ['module.py', 'README.md'];
  fs.writeFileSync(policyFile, JSON.stringify(policy));
  for (const file of [source, doc]) {
    await hooks['tools/execute'](call('edit', {file_path:file}), async () => {});
  }
  await assert.rejects(hooks['tools/execute'](call('edit', {file_path:tests}), async () => {}), {code:'SUMIKA_PROBE_SCOPE'});
  await assert.rejects(hooks['tools/execute'](call('pwsh', {command:'approved-test'}), async () => {}), {code:'SUMIKA_PROBE_SCOPE'});
  policy.allowEdits = false;
  fs.writeFileSync(policyFile, JSON.stringify(policy));
  await assert.rejects(hooks['tools/execute'](call('edit', {file_path:doc}), async () => {}), {code:'SUMIKA_PROBE_SCOPE'});
});

test('queued execution rechecks hash after an earlier edit', async () => {
  const {hooks, source, call} = fixture();
  const run = call('pwsh', {command: 'approved-test'});
  assert.deepEqual(await hooks['tools/pre-execute'](run, async () => ({kind:'allow'})), {kind:'allow'});
  let release;
  const wait = new Promise(resolve => {release = resolve;});
  const edit = hooks['tools/execute'](call('edit', {file_path: source}), async () => {
    await wait;
    fs.writeFileSync(source, 'value = 2\n');
  });
  let executed = false;
  const queued = hooks['tools/execute'](run, async () => {executed = true;});
  const rejection = assert.rejects(queued, {code: 'SUMIKA_PROBE_SCOPE'});
  release();
  await edit;
  await rejection;
  assert.equal(executed, false);
});

test('running test excludes edits and aborted queued calls never run', async () => {
  const {hooks, source, call} = fixture();
  let release;
  const wait = new Promise(resolve => {release = resolve;});
  const running = hooks['tools/execute'](call('pwsh', {command:'approved-test'}), async () => {await wait;});
  const cancellation = new AbortController();
  let edited = false;
  const cancelled = hooks['tools/execute'](call('edit', {file_path:source}, cancellation.signal), async () => {edited = true;});
  const rejection = assert.rejects(cancelled, {name:'AbortError'});
  cancellation.abort();
  await Promise.resolve();
  assert.equal(edited, false);
  release();
  await running;
  await rejection;
  assert.equal(edited, false);
  await hooks['tools/execute'](call('edit', {file_path:source}), async () => {edited = true;});
  assert.equal(edited, true);
});

test('failed tool releases queue without replay', async () => {
  const {hooks, source, call} = fixture();
  let attempts = 0;
  await assert.rejects(hooks['tools/execute'](call('edit', {file_path:source}), async () => {
    attempts++;
    throw new Error('fixture failure');
  }), /fixture failure/);
  const value = await hooks['tools/execute'](call('read', {file_path:source}), async () => 'next');
  assert.equal(value, 'next');
  assert.equal(attempts, 1);
});
