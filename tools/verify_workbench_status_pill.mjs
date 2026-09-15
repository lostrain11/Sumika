// Live check for the Sumika session-status pill.
//
// The pill only renders while a Session is actually running, so this script
// costs one small model turn: it starts a New Session, sends one short prompt and
// samples the header while the turn is in flight. The created Session is left in
// the workspace so the evidence can be inspected; archive or delete it freely.
//
// Usage:
//   node tools/verify_workbench_status_pill.mjs [bridge] [evidence.json] [shot.png]
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';

const require = createRequire(
  'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/',
);
const { chromium } = require('playwright');

const bridge = process.argv[2] || 'http://127.0.0.1:8765';
const evidencePath = process.argv[3] || null;
const shotPath = process.argv[4] || null;

const { url } = await (await fetch(`${bridge}/api/workbench/embed`)).json();
const browser = await chromium.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
});
const page = await browser.newPage();
const pageErrors = [];
page.on('pageerror', (error) => pageErrors.push(String(error.message || error)));
await page.goto(url, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(9000);
for (const label of ['稍后配置', 'Later']) {
  const button = page.getByRole('button', { name: label });
  if (await button.count().catch(() => 0)) { await button.first().click().catch(() => {}); break; }
}

// Start a New Session so the turn cannot disturb an existing conversation.
await page.getByRole('button', { name: /新会话/ }).first().click().catch(() => {});
await page.waitForTimeout(3000);

const composer = page.locator("[contenteditable='true']").first();
await composer.click({ timeout: 15000 }).catch(() => {});
await page.keyboard.type('你好', { delay: 40 });
await page.waitForTimeout(300);
await page.keyboard.press('Enter');

// Sample the header while the turn is in flight.
const samples = [];
let seen = null;
for (let attempt = 0; attempt < 60; attempt += 1) {
  const value = await page.locator('[data-sumika-session-status]').first()
    .getAttribute('data-sumika-session-status').catch(() => null);
  if (value !== null && samples.at(-1) !== value) samples.push(value);
  if (value === 'running') {
    seen = await page.evaluate(() => {
      const node = document.querySelector('[data-sumika-session-status]');
      return node ? node.innerText.trim() : null;
    });
    if (shotPath) await page.screenshot({ path: shotPath, fullPage: false }).catch(() => {});
    break;
  }
  await page.waitForTimeout(1000);
}

await browser.close();
const failures = [];
if (pageErrors.length) failures.push(`client errors: ${pageErrors.join(' | ')}`);
if (seen !== '执行中') failures.push(`running pill not observed; samples=${JSON.stringify(samples)}`);
const result = {
  checked_at: new Date().toISOString(),
  bridge,
  samples,
  running_pill_text: seen,
  page_errors: pageErrors,
  failures,
  status: failures.length ? 'failed' : 'passed',
};
console.log(JSON.stringify(result, null, 2));
if (evidencePath) await writeFile(evidencePath, JSON.stringify(result, null, 2) + '\n', 'utf8');
process.exit(failures.length ? 1 : 0);
