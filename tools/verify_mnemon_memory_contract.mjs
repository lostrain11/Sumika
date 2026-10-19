// Public Mnemon testing SDK against the real Python canonical repository.
// Not a product plugin or a new retrieval engine. No starter/provider mounted.
import { registerHooks } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import assert from 'node:assert/strict';

const config = JSON.parse(readFileSync(process.argv[2], 'utf8'));
// Resolve the reviewed artifacts without installing or modifying upstream files.
registerHooks({ resolve(specifier, context, next) {
  if (specifier === '@deepseek-ai/cordis') return { url: config.cordis, shortCircuit: true };
  const key = { 'dsh-mnemon/testing': './testing', 'dsh-mnemon/extension-sdk': './extension-sdk' }[specifier];
  return key ? { url: config.entries[key], shortCircuit: true } : next(specifier, context);
}});
const { MemoryCompositionRunner } = await import('dsh-mnemon/testing');
const { installMemory, defineMemorySource, defineMemoryStrategy } = await import('dsh-mnemon/extension-sdk');
const { createCanonicalFixture } = await import('./lib/mnemon-canonical-fixture.mjs');
const { source, strategy, scope, bridge, original } = createCanonicalFixture(config,
  { defineMemorySource, defineMemoryStrategy }, { seed: true });
const checks = {};
const runner = new MemoryCompositionRunner({ strategyTypeId: 'sumika-read-only' });
try {
  const unmount = await runner.mount({ name: 'sumika-memory-contract-fixture',
    apply(ctx) { installMemory(ctx, { sources: [source], strategies: [strategy] }); } },
    { instanceId: 'sumika-contract-fixture' });
  const begin = () => runner.beginTurn({ scope });
  const search = (turn, query) => turn.executeRoute(turn.view.routes[0].id, { query });
  const turn = await begin();
  assert.equal(turn.view.routes.length, 1);
  assert.equal(turn.view.actionOffers.length, 0);
  checks.read_only_no_model_write = true;
  const recalled = await search(turn, '茉莉花茶');
  assert.equal(recalled.items.length, 1);
  assert.equal(recalled.items[0].id, original.record_id);
  assert.equal(recalled.items[0].text, '用户喜欢茉莉花茶');
  checks.chinese_recall_three_axis_isolation = true;
  assert.equal((await search(turn, '红茶')).items.length, 0);
  checks.unconfirmed_proposal_excluded = true;
  const foreign = await runner.beginTurn({ scope: { storage: 'global' } });
  assert.equal(foreign.view.routes.length, 0);
  assert.equal(foreign.view.projection.length, 0);
  foreign.release();
  checks.unmapped_scope_no_content = true;
  await assert.rejects(turn.executeRoute('not-offered', { query: '茉莉花茶' }));
  checks.unoffered_route_rejected = true;
  const corrected = bridge('correct', { record_id: original.record_id });
  // Upstream may return unavailable evidence instead of throwing a Source error.
  async function noStaleRead(t, query) {
    let evidence;
    try { evidence = await search(t, query); }
    catch (error) {
      assert.match(error.message, /stale source revision/);
      return;
    }
    assert.equal(evidence.items.length, 0);
    assert(evidence.unavailable, 'must identify a failed read');
  }
  await noStaleRead(turn, '茉莉花茶');
  checks.old_turn_after_correction_no_old_text = true;
  turn.release();
  const after = await begin();
  assert.equal((await search(after, '茉莉花茶')).items.length, 0);
  assert.equal((await search(after, '黑咖啡')).items[0].id, corrected.record_id);
  checks.correction_current_canonical_only = true;
  bridge('forget', { record_id: corrected.record_id });
  await noStaleRead(after, '黑咖啡');
  after.release();
  bridge('rebuild');
  const rebuilt = await begin();
  assert.equal((await search(rebuilt, '黑咖啡')).items.length, 0);
  rebuilt.release();
  checks.forget_rebuild_no_resurrection = true;
  await assert.rejects(search(rebuilt, '黑咖啡'));
  checks.released_turn_rejected = true;
  await unmount();
  assert.equal(runner.inspect().evaluation.sourceInstanceKeys.length, 0);
  checks.unmount_removes_source = true;
  // Exercise the reusable adapter with trusted host bindings, not fixture logic.
  const { createCanonicalSource } = await import('../extensions/memory/mnemon-source.mjs');
  let active = { bindingId: 'role-session', epoch: '1', enabled: true,
    user_id: 'fixture-user', role_id: 'fixture-role', project_id: 'fixture-project' };
  let duringSearch;
  let searchCalls = 0;
  const scoped = new MemoryCompositionRunner({ strategyTypeId: 'sumika-read-only' });
  try {
    const adapter = createCanonicalSource({ defineMemorySource }, {
      resolveBinding(value) { return value.storage === 'custom' && value.workspaceId === 'fixture-binding' ? active : null; },
      revision() { return bridge('revision'); },
      search(value, query) {
        searchCalls++;
        assert.equal(value.role_id, 'fixture-role');
        const hits = bridge('search', { query });
        duringSearch?.();
        return hits;
      },
    });
    await scoped.mount({ name: 'sumika-source-binding-test',
      apply(ctx) { installMemory(ctx, { sources: [adapter], strategies: [strategy] }); } },
      { instanceId: 'sumika-source-binding-test' });
    const first = await scoped.beginTurn({ scope });
    assert.equal(first.view.routes.length, 1);
    assert.equal(first.view.actionOffers.length, 0);
    await search(first, '茶');
    checks.reusable_host_adapter_route = true;
    active = { ...active, epoch: '2', role_id: 'other-role' };
    await assert.rejects(search(first, '茶'));
    checks.role_switch_rejects_old_grant = true;
    active = { ...active, epoch: '3', role_id: 'fixture-role', enabled: false };
    const disabledTurn = await scoped.beginTurn({ scope });
    assert.equal(disabledTurn.view.routes.length, 0);
    const calls = searchCalls;
    await assert.rejects(search(first, '茶'));
    assert.equal(searchCalls, calls);
    checks.disabled_memory_no_search = true;
    active = { ...active, epoch: '4', enabled: true };
    const live = await scoped.beginTurn({ scope });
    duringSearch = () => { active = { ...active, enabled: false, epoch: '5' }; };
    await assert.rejects(search(live, '茶'));
    checks.inflight_disable_discards_hits = true;
    duringSearch = undefined;
    active = { ...active, enabled: true, epoch: '6' };
    const cancellable = await scoped.beginTurn({ scope });
    const controller = new AbortController();
    duringSearch = () => controller.abort();
    await assert.rejects(cancellable.executeRoute(cancellable.view.routes[0].id, { query: '茶' }, controller.signal));
    checks.inflight_cancel_discards_hits = true;
    first.release(); disabledTurn.release(); live.release(); cancellable.release();
  } finally { await scoped.dispose(); }
  const report = { passed: true, mnemon: '0.5.29', cordis: '4.0.4', checks,
    external_model_calls: 0, provider_installed: false, daily_profile_changed: false,
    limits: ['Public SDK composition probe, not full DSH UI/plugin lifecycle acceptance',
      'Uses existing EmbeddedMemory FTS; no new retrieval/extraction quality conclusion',
      'Persistent scope fence exercised across Python processes; full host binding and file-restore lease reset still require acceptance'] };
  writeFileSync(join(config.base, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally { await runner.dispose(); }
