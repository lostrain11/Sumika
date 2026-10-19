// Read-only Mnemon bridge. Host callbacks own scope, permissions and lifecycle.
// No default scope, model-supplied role mapping, writes or process spawning.
import { createHash, randomUUID } from 'node:crypto';

export function createCanonicalSource(sdk, host) {
  for (const name of ['resolveBinding', 'revision', 'search']) {
    if (typeof host[name] !== 'function') throw new TypeError(`Missing host ${name}`);
  }
  const capabilities = ['status', 'project', 'search'];
  function binding(scope) {
    const value = host.resolveBinding(scope);
    if (!value || value.enabled !== true) throw new Error('Memory binding unavailable');
    for (const key of ['bindingId', 'epoch', 'user_id', 'role_id', 'project_id']) {
      if (typeof value[key] !== 'string' || !value[key].trim()) throw new Error('Invalid host memory binding');
    }
    return { ...value };
  }
  const identity = value => createHash('sha256').update(JSON.stringify(
    ['bindingId', 'epoch', 'user_id', 'role_id', 'project_id'].map(k => value[k]))).digest('hex');
  async function snapshot(scope, signal) {
    signal?.throwIfAborted();
    const value = binding(scope);
    const revision = await host.revision(value, { signal });
    signal?.throwIfAborted();
    if (identity(value) !== identity(binding(scope))) throw new Error('Stale memory binding');
    if (typeof revision !== 'string' || !revision) throw new Error('Invalid canonical revision');
    // Repository counters may coincide across scopes. Bind the public fence to
    // both host epoch and identity, without exposing raw user/project IDs.
    const stamp = createHash('sha256').update(identity(value)).update('\0').update(revision).digest('hex');
    return { value, revision: stamp };
  }
  const source = sdk.defineMemorySource({
    manifest: { apiVersion: 'dsh-mnemon/v1', kind: 'source', typeId: 'sumika-canonical',
      packageName: 'sumika-memory-source', role: 'canonical', capabilities,
      consistency: 'namespace-pinned-live-read', routes: [{ id: 'search',
        description: 'Search confirmed canonical facts in the host-bound role', capability: 'search',
        inputSchema: { type: 'object', properties: { query: { type: 'string', maxLength: 200 } },
          required: ['query'], additionalProperties: false }, maxCalls: 10, maxResults: 5, maxCharacters: 2000 }] },
    create({ sourceInstanceKey }) {
      return {
        async facts(request) {
          let state;
          try { state = await snapshot(request.scope, request.signal); }
          catch (error) {
            request.signal?.throwIfAborted();
            return { sourceInstanceKey, sourceTypeId: 'sumika-canonical', role: 'canonical',
              availability: 'unavailable', revision: 'unavailable', capabilities, routeIds: [], actionIds: [] };
          }
          return { sourceInstanceKey, sourceTypeId: 'sumika-canonical', role: 'canonical',
            availability: 'ready', revision: state.revision, capabilities, routeIds: ['search'], actionIds: [] };
        },
        async project(request) {
          const state = await snapshot(request.scope, request.signal);
          if (state.revision !== request.expectedRevision) throw new Error('Stale source revision');
          return { fragments: [], readGrant: { id: randomUUID(), sourceInstanceKey,
            schema: 'sumika-canonical/v1', value: { binding: identity(state.value) },
            revision: state.revision, consistency: 'namespace-pinned-live-read' } };
        },
        async query({ view, route, grant, input, signal }) {
          signal?.throwIfAborted();
          if (!input || Object.keys(input).length !== 1 || typeof input.query !== 'string'
              || input.query.length > 200) throw new Error('Invalid search input');
          const before = await snapshot(view.scope, signal);
          if (grant.value?.binding !== identity(before.value) || grant.revision !== before.revision) {
            throw new Error('Stale source revision or binding');
          }
          const hits = await host.search(before.value, input.query, { signal, limit: 5 });
          const after = await snapshot(view.scope, signal);
          if (identity(before.value) !== identity(after.value) || before.revision !== after.revision) {
            throw new Error('Stale source revision or binding');
          }
          if (!Array.isArray(hits) || hits.length > 5) throw new Error('Invalid canonical hits');
          // host.search must use MemoryRetrieval: never accept third-party text directly.
          let characters = 0;
          let truncated = false;
          const items = [];
          for (const hit of hits) {
            if (typeof hit.record_id !== 'string' || typeof hit.text !== 'string'
                || !Number.isSafeInteger(hit.revision) || hit.revision < 1
                || typeof hit.source !== 'string') throw new Error('Invalid canonical hit');
            if (characters + hit.text.length > 2000) { truncated = true; continue; }
            characters += hit.text.length;
            items.push({ id: hit.record_id, text: hit.text, revision: String(hit.revision),
              provenance: { source: hit.source, record_id: hit.record_id } });
          }
          return { id: randomUUID(), viewId: view.id, routeId: route.id, sourceInstanceKey,
            observedAt: new Date().toISOString(), truncated, items };
        },
      };
    },
  });
  return source;
}
