// Optional native registration; canonical data and retrieval stay in Python.
import { pathToFileURL } from 'node:url';
import { realpathSync } from 'node:fs';
import { createSettingsHost } from './mnemon-host.mjs';
import { createCanonicalSource } from './mnemon-source.mjs';

export const name = 'sumika-canonical-memory';
export const inject = ['mnemonMemory'];

export function createReadOnlyContribution(sdk, host) {
  const source = createCanonicalSource(sdk, host);
  const strategy = sdk.defineMemoryStrategy({
    manifest: { apiVersion: 'dsh-mnemon/v1', kind: 'strategy', typeId: 'sumika-read-only',
      packageName: 'sumika-memory-source', deterministic: true, supportedSourceRoles: ['canonical'],
      maxSources: 1, maxRoutes: 1, maxActions: 1 },
    compose(request, sources) {
      return { strategyTypeId: 'sumika-read-only', explanation: 'Host-bound confirmed facts; read only',
        sources: sources.filter(s => s.sourceTypeId === 'sumika-canonical' && s.availability === 'ready')
          .slice(0, 1).map(s => ({ sourceInstanceKey: s.sourceInstanceKey,
            projection: { mode: 'routed', maxCharacters: 2000 }, routeIds: ['search'], actionIds: [] })) };
    },
  });
  return { sources: [source], strategies: [strategy] };
}

export async function apply(ctx, config) {
  if (config?.enabled === false) return;
  if (config?.enabled !== true || typeof config.sdkEntry !== 'string') {
    throw new Error('Explicit enabled and reviewed Mnemon SDK path required');
  }
  const sdk = await import(pathToFileURL(realpathSync(config.sdkEntry)).href);
  const host = createSettingsHost(config);
  try {
    ctx.effect(() => () => host.dispose(), 'stop canonical memory workers');
    sdk.installMemory(ctx, createReadOnlyContribution(sdk, host));
  } catch (error) { host.dispose(); throw error; }
}
