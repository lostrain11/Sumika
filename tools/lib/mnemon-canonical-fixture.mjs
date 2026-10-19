// Synthetic read-only canonical Source shared by SDK and actual DSH host probes.
// Test asset only: host scope mapping is deliberately fixed, never user data.
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import assert from 'node:assert/strict';

export function createCanonicalFixture(config, { defineMemorySource, defineMemoryStrategy }, { seed = false } = {}) {
  function bridge(op, args = {}) {
    const result = spawnSync(config.python, ['-B', config.bridge, '--bridge', config.base], {
      input: JSON.stringify({ op, ...args }), encoding: 'utf8', timeout: 15000,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
    assert.equal(result.status, 0, result.stderr || String(result.error));
    return JSON.parse(result.stdout);
  }
  const scope = { storage: 'custom', workspaceId: 'fixture-binding' };
  const authorized = value => JSON.stringify(value) === JSON.stringify(scope);
  const revision = () => bridge('revision');
  const original = seed ? bridge('seed') : null;
  const capabilities = ['status', 'project', 'search'];
  const source = defineMemorySource({
    manifest: { apiVersion: 'dsh-mnemon/v1', kind: 'source', typeId: 'sumika-canonical',
      packageName: 'sumika-memory-contract-fixture', role: 'canonical', capabilities,
      consistency: 'namespace-pinned-live-read', routes: [{ id: 'search', description: 'Search confirmed canonical facts',
        capability: 'search', inputSchema: { type: 'object', properties: { query: { type: 'string', maxLength: 200 } },
          required: ['query'], additionalProperties: false }, maxCalls: 10, maxResults: 5, maxCharacters: 2000 }] },
    create({ sourceInstanceKey }) {
      return {
        facts(request) {
          return { sourceInstanceKey, sourceTypeId: 'sumika-canonical', role: 'canonical',
            availability: authorized(request.scope) ? 'ready' : 'unavailable', revision: revision(),
            capabilities, routeIds: ['search'], actionIds: [] };
        },
        project(request) {
          assert(authorized(request.scope), 'unmapped host scope');
          assert.equal(request.expectedRevision, revision());
          return { fragments: [], readGrant: { id: randomUUID(), sourceInstanceKey,
            schema: 'sumika-fixture/v1', value: { binding: 'fixture-binding' }, revision: revision(),
            consistency: 'namespace-pinned-live-read' } };
        },
        query({ view, route, grant, input, signal }) {
          signal?.throwIfAborted();
          assert(authorized(view.scope), 'unmapped route scope');
          // Current governance revision fences previously granted reads after mutation.
          assert.equal(grant.revision, revision(), 'stale source revision');
          assert.deepEqual(Object.keys(input), ['query']);
          assert.equal(typeof input.query, 'string');
          assert(input.query.length <= 200);
          const hits = bridge('search', { query: input.query });
          assert.equal(grant.revision, revision(), 'stale source revision');
          return { id: randomUUID(), viewId: view.id, routeId: route.id, sourceInstanceKey,
            observedAt: new Date().toISOString(), truncated: false,
            items: hits.map(hit => ({ id: hit.record_id, text: hit.text, revision: String(hit.revision),
              provenance: { source: hit.source, record_id: hit.record_id } })) };
        },
      };
    },
  });
  const strategy = defineMemoryStrategy({
    manifest: { apiVersion: 'dsh-mnemon/v1', kind: 'strategy', typeId: 'sumika-read-only',
      packageName: 'sumika-memory-contract-fixture', deterministic: true,
      supportedSourceRoles: ['canonical'], maxSources: 1, maxRoutes: 1, maxActions: 1 },
    compose(request, sources) {
      return { strategyTypeId: 'sumika-read-only', explanation: 'Explicit host scope, confirmed facts only',
        sources: sources.filter(s => s.availability === 'ready').map(s => ({ sourceInstanceKey: s.sourceInstanceKey,
          projection: { mode: 'routed', maxCharacters: 2000 }, routeIds: ['search'], actionIds: [] })) };
    },
  });
  return { source, strategy, scope, bridge, original };
}
