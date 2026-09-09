import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { createInterface } from 'node:readline';

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of input) {
  let browser;
  let submitted = false;
  let attemptId;
  let stage = 'validate';
  try {
    const request = JSON.parse(line);
    const endpoint = new URL(request.endpoint);
    if (endpoint.protocol !== 'http:' || endpoint.hostname !== '127.0.0.1' || !endpoint.port ||
        endpoint.username || endpoint.password || endpoint.search || endpoint.hash || endpoint.pathname !== '/') throw Error('invalid-endpoint');
    if (!/^[a-zA-Z0-9-]{1,80}$/.test(request.attempt_id) || typeof request.question !== 'string' || request.question.length > 12000) throw Error('invalid-request');
    attemptId = request.attempt_id;
    stage = 'connect';
    browser = await chromium.connectOverCDP(endpoint.origin, { timeout: 10000 });
    const pages = browser.contexts().flatMap(context => context.pages()).filter(page =>
      ['http://tauri.localhost', 'http://127.0.0.1:8771'].includes(new URL(page.url()).origin));
    if (pages.length !== 1) throw Error('trusted-main-page-required');
    const page = pages[0];
    stage = 'status';
    const invoke = operation => page.evaluate(args => window.__TAURI__.core.invoke('consultation_action', args),
      { operation, ...(['fill', 'submit', 'read'].includes(operation) ? { attemptId } : {}),
        ...(operation === 'fill' ? { text: request.question } : {}) });
    let result = await invoke('status');
    if (result.attempt_id || result.possibly_sent || ['pending', 'unknown', 'filled'].includes(result.status)) throw Error('existing-attempt');
    stage = 'observe';
    result = await invoke('observe');
    if (result.status !== 'ready') throw Error('page-not-ready');
    stage = 'fill';
    result = await invoke('fill');
    if (result.status !== 'filled') throw Error('not-filled');
    submitted = true;
    stage = 'submit';
    result = await invoke('submit');
    const deadline = Date.now() + 90000;
    while (['pending', 'ready'].includes(result.status) && Date.now() < deadline) {
      stage = 'read';
      await new Promise(resolve => setTimeout(resolve, 1500));
      result = await invoke('read');
    }
    process.stdout.write(JSON.stringify({ attempt_id: attemptId, status: result.status === 'completed' ? 'completed' : 'unknown',
      text: result.status === 'completed' ? result.text : '', possibly_sent: result.status !== 'completed', submit_calls: 1 }) + '\n');
  } catch {
    process.stdout.write(JSON.stringify({ attempt_id: attemptId, status: submitted ? 'unknown' : 'failed',
      text: '', possibly_sent: submitted, submit_calls: submitted ? 1 : 0, failure_stage: stage }) + '\n');
  } finally {
    await browser?.close().catch(() => {});
  }
  break;
}
