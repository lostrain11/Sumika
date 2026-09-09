import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { createInterface } from 'node:readline';

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
const lines = input[Symbol.asyncIterator]();
let browser;
let page;
let handler;
const report = { transport: 'production-frontend-native', claimed: 0, completed: 0, possibly_sent: false };
try {
  const config = JSON.parse((await lines.next()).value);
  for (const value of [config.endpoint, config.bridge]) {
    const url = new URL(value);
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port ||
        url.username || url.password || url.search || url.hash || url.pathname !== '/') throw Error('invalid-endpoint');
  }
  browser = await chromium.connectOverCDP(config.endpoint, { timeout: 10000 });
  const pages = browser.contexts().flatMap(context => context.pages()).filter(item =>
    ['http://tauri.localhost', 'http://127.0.0.1:8771'].includes(new URL(item.url()).origin));
  if (pages.length !== 1) throw Error('main-page-required');
  [page] = pages;
  const status = await page.evaluate(() => window.__TAURI__.core.invoke('consultation_action', { operation: 'status' }));
  if (status.possibly_sent || ['pending', 'unknown', 'filled'].includes(status.status)) throw Error('existing-attempt');
  let attached = false;
  handler = async route => {
    const request = route.request().postDataJSON();
    if (!['quality.browser.attach', 'quality.browser.poll', 'quality.browser.complete'].includes(request?.method)) {
      await route.continue();
      return;
    }
    try {
      const response = await fetch(config.bridge, { method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Smoke-Token': config.token },
        body: JSON.stringify(request), signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw Error('bridge-failed');
      const body = await response.text();
      const result = JSON.parse(body).result;
      if (request.method === 'quality.browser.attach' && result?.token) attached = true;
      if (request.method === 'quality.browser.poll' && result?.request) report.claimed += 1;
      if (request.method === 'quality.browser.complete' && result?.accepted) {
        report.completed += Number(request.params.result.status === 'completed');
        report.possibly_sent ||= request.params.result.possibly_sent === true;
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body });
    } catch {
      await route.abort('failed');
    }
  };
  await page.route('**/rpc', handler);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('[data-portal-panel]').click({ timeout: 30000 });
  await page.locator('[data-embedded-tab="native-consultation"]').click();
  const deadline = Date.now() + 30000;
  while (!attached && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 250));
  if (!attached) throw Error('frontend-not-attached');
  process.stdout.write(JSON.stringify({ ready: true }) + '\n');
  await lines.next();
} catch {
  report.failed = true;
  process.stdout.write(JSON.stringify({ ready: false }) + '\n');
} finally {
  if (page && handler) await page.unroute('**/rpc', handler).catch(() => {});
  if (page) {
    try {
      const status = await page.evaluate(() => window.__TAURI__.core.invoke('consultation_action', { operation: 'status' }));
      if (!status.possibly_sent && !['pending', 'unknown', 'filled'].includes(status.status)) {
        await page.reload({ waitUntil: 'domcontentloaded' });
        report.daily_bridge_restored = true;
      }
    } catch { report.daily_bridge_restored = false; }
  }
  await browser?.close().catch(() => {});
  input.close();
  process.stdout.write(JSON.stringify(report) + '\n');
}
