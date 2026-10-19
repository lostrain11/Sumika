// Explicit trusted workspace -> existing role settings bridge; opt-in only.
import { readFileSync, statSync, realpathSync } from 'node:fs';
import { join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export function createSettingsHost({ python, projects, timeoutMs = 15000, storage = 'workspace' }) {
  if (typeof python !== 'string' || !python || !Number.isInteger(timeoutMs) || timeoutMs < 1) throw new Error('Invalid memory host configuration');
  if (!['workspace', 'custom'].includes(storage)) throw new Error('Explicit scoped storage required');
  const paths = new Map(Object.entries(projects ?? {}).map(([id, path]) => [realpathSync(id), realpathSync(path)]));
  if (!paths.size) throw new Error('Explicit workspace settings bindings required');
  const leases = new Map();
  const children = new Set();
  let disposed = false;
  function resolveBinding(scope) {
    if (disposed || scope?.storage !== storage || typeof scope.workspaceId !== 'string') return null;
    let workspace;
    try { workspace = realpathSync(scope.workspaceId); } catch { return null; }
    const path = paths.get(workspace);
    if (!path) return null;
    try {
      const raw = readFileSync(path);
      const settings = JSON.parse(raw.toString('utf8'));
      const rolePath = join(settings.role.role_dir, 'role.json');
      const roleRaw = readFileSync(rolePath);
      const role = JSON.parse(roleRaw.toString('utf8'));
      const configuration_revision = createHash('sha256').update(raw).update('\0').update(roleRaw).digest('hex');
      const stamp = [path, configuration_revision, statSync(path, { bigint: true }).mtimeNs.toString(),
        statSync(rolePath, { bigint: true }).mtimeNs.toString()].join(':');
      let lease = leases.get(workspace);
      if (!lease || lease.stamp !== stamp) {
        lease = { stamp, epoch: randomUUID() };
        leases.set(workspace, lease);
      }
      return { bindingId: workspace, epoch: lease.epoch,
        enabled: (settings.memory?.enabled ?? true) === true, user_id: settings.role.user_id,
        role_id: role.id, project_id: settings.role.project_id, configuration_revision };
    } catch { leases.delete(workspace); return null; }
  }
  function call(binding, op, args, signal) {
    signal?.throwIfAborted();
    const current = resolveBinding({ storage, workspaceId: binding.bindingId });
    if (!current?.enabled || current.epoch !== binding.epoch) return Promise.reject(new Error('Memory binding unavailable'));
    return new Promise((resolve, reject) => {
      const child = spawn(python, ['-X', 'utf8', '-B', fileURLToPath(new URL('./mnemon_bridge.py', import.meta.url)),
        '--settings', paths.get(binding.bindingId)], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
      children.add(child);
      let output = '', settled = false;
      const finish = (error, value) => {
        if (settled) return;
        settled = true; clearTimeout(timer); signal?.removeEventListener('abort', abort); children.delete(child);
        if (error) { child.kill(); reject(error); } else resolve(value);
      };
      const abort = () => finish(new Error('Memory read cancelled'));
      const timer = setTimeout(() => finish(new Error('Memory read timed out')), timeoutMs);
      signal?.addEventListener('abort', abort, { once: true });
      child.stdout.setEncoding('utf8');
      child.stdout.on('data', chunk => { output += chunk; if (output.length > 262144) finish(new Error('Memory response too large')); });
      child.stderr.resume();
      child.stdin.on('error', () => {});
      child.on('error', () => finish(new Error('Memory worker unavailable')));
      child.on('close', code => {
        if (code !== 0 || disposed || signal?.aborted) return finish(new Error('Memory read unavailable'));
        const latest = resolveBinding({ storage, workspaceId: binding.bindingId });
        if (!latest?.enabled || latest.epoch !== binding.epoch) return finish(new Error('Memory binding changed'));
        try { finish(null, JSON.parse(output)); } catch { finish(new Error('Invalid memory response')); }
      });
      child.stdin.end(JSON.stringify({ op, configuration_revision: binding.configuration_revision, ...args }));
      if (signal?.aborted) abort();
    });
  }
  return { resolveBinding,
    revision: (binding, { signal } = {}) => call(binding, 'revision', {}, signal),
    search: (binding, query, { signal, limit = 5 } = {}) => call(binding, 'search', { query, limit }, signal),
    invalidate() { leases.clear(); },
    dispose() { disposed = true; leases.clear(); for (const child of children) child.kill(); },
  };
}
