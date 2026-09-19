// The workbench screen must *be* the DSH front end: framing it in the shell's own
// screen, under the shell top bar, with no mock board markup left on top.
//
// Usage:
//   node tools/verify_workbench_screen.mjs [bridge] [evidence.json] [shot.png]
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';

const require = createRequire(
  'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/',
);
const { chromium } = require('playwright');

const bridge = process.argv[2] || 'http://127.0.0.1:8765';
const evidencePath = process.argv[3] || null;
const shotPath = process.argv[4] || null;

const failures = [];
const browser = await chromium.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const pageErrors = [];
const consoleErrors = [];
const frameRequests = [];
const badResponses = [];
page.on('pageerror', (error) => pageErrors.push(String(error.message || error)));
page.on('console', (message) => {
  if (message.type() === 'error') {
    const where = message.location();
    consoleErrors.push(`${message.text().slice(0, 200)} @ ${where.url?.split('?')[0] || 'unknown'}`);
  }
});
page.on('request', (request) => {
  if (request.url().includes(':5175')) frameRequests.push(request.url().split('?')[0]);
});
page.on('response', (response) => {
  if (response.status() >= 400) badResponses.push({ status: response.status(), url: response.url().split('?')[0] });
});

await page.goto(`${bridge}/#board`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(9000);

const state = await page.evaluate(() => {
  const frame = document.querySelector('#sumika-workbench-frame');
  const screen = document.querySelector('#screen-board');
  const box = frame?.getBoundingClientRect();
  return {
    screenVisible: screen?.classList.contains('show') || false,
    framePresent: !!frame,
    frameSrc: frame?.getAttribute('src')?.split('?')[0] || null,
    frameHeight: box ? Math.round(box.height) : 0,
    mockWrapPresent: !!document.querySelector('#screen-board .wb-wrap'),
    navVisible: !!document.querySelector('#gnav button[data-go="board"]'),
    deskpetVisible: (() => {
      const node = document.querySelector('#deskpet');
      if (!node) return null;
      return getComputedStyle(node).display !== 'none';
    })(),
  };
});

if (!state.screenVisible) failures.push('workbench screen is not the active screen');
if (!state.framePresent) failures.push('the workbench screen does not frame the DSH front end');
if (state.frameSrc && !/:5175\/?$/.test(state.frameSrc)) {
  failures.push(`frame source is not the managed instance: ${state.frameSrc.split('?')[0]}`);
}
if (state.frameHeight < 400) failures.push(`frame is only ${state.frameHeight}px tall`);
if (state.mockWrapPresent) failures.push('the design mock board markup is still in the workbench screen');
if (state.deskpetVisible === true) failures.push('the sample deskpet overlay is visible over the real workbench');
if (frameRequests.length === 0) failures.push('the page never requested the managed instance');
if (pageErrors.length) failures.push(`client errors: ${pageErrors.join(' | ')}`);
// A missing favicon is the browser asking for something the page never
// referenced; anything else 4xx/5xx is a real load failure.
const realBadResponses = badResponses.filter(entry => !/favicon\.ico$/.test(entry.url));
if (realBadResponses.length) {
  failures.push(`failed resources: ${realBadResponses.map(e => `${e.status} ${e.url}`).join(' | ')}`);
}
const realConsoleErrors = consoleErrors.filter(text => !/Failed to load resource/.test(text));
if (realConsoleErrors.length) failures.push(`client console errors: ${realConsoleErrors.join(' | ')}`);
if (shotPath) await page.screenshot({ path: shotPath, fullPage: false });
await browser.close();

const result = {
  checked_at: new Date().toISOString(),
  bridge,
  screen: state,
  frame_requests: [...new Set(frameRequests)].slice(0, 5),
  bad_responses: badResponses.slice(0, 6),
  page_errors: pageErrors,
  console_errors: consoleErrors,
  failures,
  status: failures.length ? 'failed' : 'passed',
};
console.log(JSON.stringify(result, null, 2));
if (evidencePath) await writeFile(evidencePath, JSON.stringify(result, null, 2) + '\n', 'utf8');
process.exit(failures.length ? 1 : 0);
