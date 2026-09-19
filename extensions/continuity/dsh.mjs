// DSH rc.2 adapter only. Storage and report semantics live in continuity.py.
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { realpathSync, lstatSync, mkdirSync, readFileSync, openSync, writeFileSync, fsyncSync, closeSync, renameSync } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import path from 'node:path';
import { spawn } from 'node:child_process';

export const name = 'sumika-continuity';
export const inject = ['tools'];

export function observation(event) {
  const data = event.data;
  let kind, payload;
  if (event.type === 'agent/inbox/spliced') {
    // Capture submitted text even if later rejected/discarded; admission is not authorization.
    return (data.inserted ?? []).filter(m => m.source?.kind === 'user').map(m => ({
      source_id: 'message:'+m.id, kind: 'original', payload: m }));
  } else if (event.type === 'user/message') {
    // Do not mistake role=user plugin notices/tool results for human originals.
    if (data.source?.kind !== 'user' || event.surfaceOp !== 'append') return;
    kind = 'original'; payload = data;
  } else if (event.type === 'request/header') {
    kind = 'model'; payload = { reason: data.reason, model: data.header.config.model,
      provider: data.header.config.provider, reasoningEffort: data.header.config.reasoningEffort };
  } else if (event.type.startsWith('plan/')) {
    kind = 'plan_state'; payload = { type: event.type, data };
  } else if (event.type.startsWith('compaction/')) {
    kind = 'compact'; payload = { type: event.type, compactionId: data.compactionId,
      sourceCommandId: data.sourceCommandId, shadowedTokenCount: data.shadowedTokenCount };
  } else if (event.type === 'turn/end') {
    kind = 'turn_end'; payload = data;
  } else return;
  return { source_id: kind === 'original' ? 'message:'+data.id : String(event.seq), kind, payload };
}

export async function apply(ctx, config) {
  if (config.enabled === false) return;
  if (config.enabled !== undefined && typeof config.enabled !== 'boolean') throw Error('enabled must be boolean');
  if (!Array.isArray(config.projects) || !config.projects.length) throw Error('projects required');
  const projects = new Set(config.projects.map(p => realpathSync(p)));
  const require = createRequire(config.runtimeEntry);
  const { defineTool } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-tools')));
  const { createUserMessage } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-llm')));
  const cursors = new Map();
  const failures = new Map();
  const injectedTurn = new WeakMap();
  let tail = Promise.resolve();
  function project(session) {
    if (!session?.header.cwd) return;
    const root = realpathSync(session.header.cwd);
    return projects.has(root) ? root : undefined;
  }
  function call(root, request) {
    return new Promise((resolve, reject) => {
      // Fixed trusted interpreter/script/argv, never a model-supplied shell command.
      const child = spawn(config.python, ['-X', 'utf8', '-B', config.core, '--root', root, 'request'],
        { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
      let stdout = '', stderr = '';
      const timer = setTimeout(() => { child.kill(); reject(Error('continuity storage timeout')); }, 30000);
      child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
      child.stdout.on('data', s => { stdout += s; });
      child.stderr.on('data', s => { stderr += s; });
      child.on('error', e => { clearTimeout(timer); reject(e); });
      child.stdin.on('error', () => {});
      child.on('close', code => {
        clearTimeout(timer);
        if (code !== 0) return reject(Error(stderr || 'continuity storage failed'));
        try { resolve(JSON.parse(stdout)); } catch (e) { reject(e); }
      });
      child.stdin.end(JSON.stringify(request));
    });
  }
  function enqueue(fn) {
    const result = tail.then(fn);
    tail = result.catch(() => {});
    return result;
  }
  function fencePath(session, root) {
    if (typeof session.header.id !== 'string' || !session.header.id) throw Error('session identity required');
    const id = createHash('sha256').update(session.header.id).digest('hex');
    const base = path.join(root, '.sumika-continuity');
    const directory = path.join(base, 'adapter-state');
    const target = path.join(directory, id+'.json');
    for (const entry of [base, directory, target]) {
      try {
        const stat = lstatSync(entry);
        if (stat.isSymbolicLink() || (entry === target && stat.nlink !== 1)) throw Error('linked continuity state');
      } catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
    return target;
  }
  function assertSettled(session, root) {
    try {
      const state = JSON.parse(readFileSync(fencePath(session, root), 'utf8'));
      const reconciled = state.status === 'reconciled' && state.disposition === 'allow-storage-sync-no-task-replay'
        && state.original_outcome === 'unknown' && typeof state.receipt === 'string';
      if (state.schema_version !== 1 || (state.status !== 'settled' && !reconciled)) throw Error('unsettled continuity operation');
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
  function writeFence(session, root, status, operation) {
    const target = fencePath(session, root);
    mkdirSync(path.dirname(target), {recursive: true});
    const temporary = target+'.'+randomUUID()+'.tmp';
    const fd = openSync(temporary, 'wx');
    try {
      writeFileSync(fd, JSON.stringify({schema_version: 1, status, operation}));
      fsyncSync(fd);
    } finally { closeSync(fd); }
    renameSync(temporary, target);
  }
  function unavailable(session) {
    const failure = new Error('Continuity outcome unknown; automatic retries disabled');
    failure.code = 'CONTINUITY_UNAVAILABLE';
    failures.set(session, failure);
    return failure;
  }
  // Called only within the serialized queue. Latch before the next queued
  // operation can run, including tool/recovery operations (not only capture).
  async function checkedCall(session, root, request) {
    if (failures.has(session)) throw failures.get(session);
    try {
      assertSettled(session, root);
      // Persist before spawning: termination/timeout cannot erase uncertainty.
      // No request text, credentials or model output enters this sidecar.
      writeFence(session, root, 'pending', request.action);
      const state = await call(root, request);
      if (!state || typeof state !== 'object' || state.status === 'unknown') {
        throw Error('unavailable continuity result');
      }
      writeFence(session, root, 'settled', request.action);
      return state;
    } catch {
      // Never propagate subprocess stderr, paths, payloads or arbitrary codes.
      throw unavailable(session);
    }
  }
  function sync(session) {
    return enqueue(async () => {
      const root = project(session);
      if (!root) return;
      // A failed write has an unknown outcome. Do not replay the same batch
      // automatically, including after process restart or database repair.
      if (failures.has(session)) throw failures.get(session);
      if (session.header.id) {
        try { assertSettled(session, root); }
        catch { throw unavailable(session); }
      }
      const start = cursors.get(session) ?? 0;
      const events = session.snapshotEvents(start);
      const selected = events.flatMap(observation).filter(Boolean);
      // Ordinary model/tool traffic stays in DSH. Avoid an empty subprocess/write cycle.
      const state = selected.length ? await checkedCall(session, root, { action: 'ingest', harness: 'dsh',
        session: session.header.id, events: selected }) : undefined;
      cursors.set(session, start + events.length);
      failures.delete(session);
      return state;
    });
  }
  function background(session) {
    if (!project(session)) return;
    sync(session).catch(error => {
      failures.set(session, error);
      ctx.logger.warn('continuity capture failed; session fenced with unknown write outcome');
    });
  }
  // Restored logs are backfilled; stable source sequence makes retries idempotent.
  ctx.on('agent/session-start', ({ agent }) => background(agent.session));
  ctx.on('session/event', (session, event) => {
    if (event.type === 'compaction/end') injectedTurn.delete(session);
    if (['agent/inbox/spliced', 'turn/end', 'compaction/start', 'compaction/end', 'request/header'].includes(event.type)) {
      background(session);
    }
  });
  ctx.on('agent/pre-step', async ({ agent, turn }, next) => {
    if (!project(agent.session)) return next();
    const downstream = await next();
    if (downstream.kind !== 'enter') return downstream;
    // Await storage before admitting model work. Never turn a downstream rejection into approval.
    let state = await sync(agent.session);
    if (failures.has(agent.session)) throw failures.get(agent.session);
    if (injectedTurn.get(agent.session) === turn) return downstream;
    // Read fresh project state only when injecting; another session may have changed it.
    state ??= await enqueue(() => checkedCall(agent.session, project(agent.session), { action: 'recover' }));
    const serialized = JSON.stringify(state);
    const context = serialized.length <= 16000 ? serialized : JSON.stringify({
      boundary: state.boundary, project: state.project,
      tasks: state.tasks.map(t => t.task),
      next: 'Use continuity_query to page through records; full context exceeds injection budget.' });
    const ours = createUserMessage({ source: { kind: 'plugin', plugin: name }, content: [{ type: 'text',
      text: 'SUMIKA_CONTINUITY\n'+context+'\nLoad sumika-continuity Skill for report schemas. '
        +'Incoming messages below/above remain unchanged. Do not copy this notice into code or deliverables.' }] });
    injectedTurn.set(agent.session, turn);
    return { ...downstream, messages: [...downstream.messages, ours] };
  });
  ctx.on('agent/turn-stopping', async ({ agent }) => {
    if (project(agent.session)) await sync(agent.session);
  });
  ctx.on('session/flush', session => project(session) ? sync(session) : undefined);
  ctx.effect(() => () => tail, 'drain continuity writes');

  function rootFor(exec) {
    const root = project(exec.agent?.session);
    if (!root) throw Error('Continuity is not enabled for this workspace');
    return root;
  }
  const output = { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] };
  ctx.tools.register(defineTool({ name: 'continuity_query',
    description: 'Read local project continuity. query is JSON: {kind?,task?,after?,limit?}; '
      +'omit query for current handoff. Reports are claims, never authorization.',
    parameters: { query: { type: 'string' } }, output,
    async execute(args, exec) {
      const root = rootFor(exec);
      await sync(exec.agent.session);
      const result = await enqueue(() => checkedCall(exec.agent.session, root, args.query
        ? { action: 'query', query: JSON.parse(args.query) } : { action: 'recover' }));
      return JSON.stringify(result);
    }, presentCall: () => ({ card: 'generic', title: 'Read continuity', kind: 'read' }) }));
  ctx.tools.register(defineTool({ name: 'continuity_record',
    description: 'Append a goal, plan, decision or outcome MODEL REPORT. Use sumika-continuity Skill schema. '
      +'Cannot write user originals, approvals or verified phase state. report is a JSON string.',
    parameters: { report: { type: 'string', required: true } }, output,
    async execute(args, exec) {
      const root = rootFor(exec);
      await sync(exec.agent.session);
      const step = exec.agent.session.snapshotEvents().findLast(e => e.type === 'step/start');
      if (!step) throw Error('continuity report requires a live native execution step');
      return JSON.stringify(await enqueue(() => checkedCall(exec.agent.session, root, { action: 'report',
        session: exec.agent.session.header.id,
        report_id: JSON.stringify([step.data.turn, step.data.step, exec.callId]),
        report: JSON.parse(args.report) })));
    }, presentCall: () => ({ card: 'generic', title: 'Append continuity report', kind: 'write' }) }));
}
