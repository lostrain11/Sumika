// Isolated acceptance policy, never registered in daily profiles.
// Exact commands are not a sandbox: reviewed source hashes gate code execution.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export function createGuard(config) {
  const root = fs.realpathSync(config.workspace);
  const policyFile = fs.realpathSync(config.policyFile);
  if (path.relative(root, policyFile) === '' || !path.relative(root, policyFile).startsWith('..')) {
    throw new Error('review policy must be outside workspace');
  }
  const deny = () => ({kind: 'deny', reason: 'SUMIKA_PROBE_SCOPE: operation requires reviewed probe authorization'});
  const canonical = value => {
    if (typeof value !== 'string') throw new Error('missing path');
    const requested = path.resolve(root, value);
    const actual = fs.realpathSync(requested);
    const stat = fs.lstatSync(requested);
    if (stat.isSymbolicLink() || !stat.isFile() || stat.nlink !== 1 || actual !== requested) throw new Error('aliased path');
    return actual;
  };
  return exec => {
    try {
      const policy = JSON.parse(fs.readFileSync(policyFile, 'utf8'));
      if (policy.workspace !== root || policy.schema_version !== 1) return deny();
      const args = exec.arguments;
      if (!args || typeof args !== 'object' || args.sandbox_permissions !== undefined) return deny();
      const files = policy.files.map(name => canonical(name));
      if (files.some(file => path.dirname(file) !== root)) return deny();
      const editable = policy.editableFiles === undefined ? [files[0]] : policy.editableFiles.map(name => canonical(name));
      if (editable.some(file => !files.includes(file))) return deny();
      if (exec.name === 'read' || exec.name === 'edit') {
        if (exec.name === 'edit' && policy.allowEdits === false) return deny();
        const target = canonical(args.file_path);
        return (exec.name === 'read' ? files.includes(target) : editable.includes(target)) ? null : deny();
      }
      if (exec.name === 'glob') {
        return args.path === undefined && policy.files.some(name => args.pattern === name || args.pattern === '**/'+name) ? null : deny();
      }
      if (exec.name === 'pwsh') {
        const allowedKeys = new Set(['command', 'description', 'workdir', 'timeoutMs']);
        if (Object.keys(args).some(k => !allowedKeys.has(k)) || args.command !== policy.testCommand) return deny();
        if (args.workdir !== undefined && fs.realpathSync(args.workdir) !== root) return deny();
        // Tests import modified Python code; command allowlisting alone does not
        // make that safe. A reviewer outside this session pins every input.
        for (const file of files) {
          const hash = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
          if (policy.reviewedHashes[path.basename(file)] !== hash) return deny();
        }
        return null;
      }
      return deny();
    } catch { return deny(); }
  };
}

export function apply(ctx, config) {
  const decide = createGuard(config);
  let tail = Promise.resolve();
  ctx.on('tools/pre-execute', async (exec, next) => decide(exec) ?? await next());
  ctx.on('tools/execute', (exec, next) => {
    const result = tail.then(async () => {
      exec.signal.throwIfAborted();
      const denied = decide(exec);
      if (denied) throw Object.assign(new Error(denied.reason), {code: 'SUMIKA_PROBE_SCOPE'});
      // Hold through settlement, including exceptions and cancellation; a later
      // edit must not overlap the reviewed program while it is still running.
      return await next();
    });
    tail = result.then(() => undefined, () => undefined);
    return result;
  });
}
