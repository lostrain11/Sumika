// Real public SDK + settings bridge. Invoked by Python synthetic acceptance.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { dirname } from 'node:path';
import { createSettingsHost } from '../extensions/memory/mnemon-host.mjs';
import { createReadOnlyContribution } from '../extensions/memory/dsh.mjs';

const [python, settingsPath, sdkPath] = process.argv.slice(2);
const sdk = await import(pathToFileURL(sdkPath));
const { MemoryCompositionRunner } = await import(new URL('./testing.js', pathToFileURL(sdkPath)));
const workspaceId = dirname(settingsPath);
const scope = { storage: 'workspace', workspaceId };
const host = createSettingsHost({ python, projects: { [workspaceId]: settingsPath } });
const runner = new MemoryCompositionRunner({ strategyTypeId: 'sumika-read-only' });
const checks = {};
try {
  assert.equal(host.resolveBinding({ ...scope, storage: 'global' }), null);
  assert.equal(host.resolveBinding({ ...scope, workspaceId: dirname(workspaceId) }), null);
  checks.unmapped_rejected = true;
  const binding = host.resolveBinding(scope);
  assert(binding.enabled); // Legacy memory section deliberately omitted.
  assert.equal((await host.search(binding, '茉莉花茶'))[0].text, '用户喜欢茉莉花茶');
  checks.real_python_hydration_and_legacy_switch = true;
  await runner.mount({ name: 'settings-host-acceptance', apply(ctx) {
    sdk.installMemory(ctx, createReadOnlyContribution(sdk, host));
  } }, { instanceId: 'settings-host-acceptance' });
  const turn = await runner.beginTurn({ scope });
  assert.equal(turn.view.routes.length, 1);
  const route = turn.view.routes[0].id;
  assert.equal((await turn.executeRoute(route, { query: '茉莉花茶' })).items.length, 1);
  checks.sdk_route_real_settings_bridge = true;
  const old = readFileSync(settingsPath);
  const settings = JSON.parse(old);
  settings.memory = { enabled: false, auto_extract: false, extract_threshold: .8, max_extracts_per_turn: 3 };
  writeFileSync(settingsPath, JSON.stringify(settings));
  await assert.rejects(host.search(binding, '茉莉花茶'));
  let result;
  try { result = await turn.executeRoute(route, { query: '茉莉花茶' }); } catch {}
  if (result) { assert.equal(result.items.length, 0); assert(result.unavailable); }
  checks.old_grant_disabled_no_text = true;
  writeFileSync(settingsPath, old);
  host.invalidate();
  assert.notEqual(host.resolveBinding(scope).epoch, binding.epoch);
  await assert.rejects(host.search(binding, '茉莉花茶'));
  checks.restore_invalidate_old_binding_rejected = true;
  const controller = new AbortController();
  const pending = host.search(host.resolveBinding(scope), '茉莉花茶', { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, /cancelled|unavailable/);
  checks.inflight_cancel = true;
  const pendingDispose = host.search(host.resolveBinding(scope), '茉莉花茶');
  host.dispose();
  await assert.rejects(pendingDispose, /unavailable/);
  assert.equal(host.resolveBinding(scope), null);
  checks.dispose_owned_worker = true;
  turn.release();
  console.log(JSON.stringify({ passed: true, checks, external_model_calls: 0 }));
} finally { host.dispose(); runner.dispose(); }
