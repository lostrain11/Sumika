// A Sumika screen living inside DSH as a main panel.
//
// Opens the sidebar panel row, checks the panel renders real registry rows, and
// flips one switch through the panel to confirm it writes to the bridge.
//
// Usage:
//   node tools/verify_dsh_panel.mjs [bridge] [evidence.json] [shot.png]
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';

const require = createRequire(
  'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/',
);
const { chromium } = require('playwright');

const bridge = process.argv[2] || 'http://127.0.0.1:8765';
const evidencePath = process.argv[3] || null;
const shotPath = process.argv[4] || null;

const registry = async () => (await (await fetch(`${bridge}/api/modules`)).json()).modules;
const failures = [];
const { url } = await (await fetch(`${bridge}/api/workbench/embed`)).json();

const browser = await chromium.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const pageErrors = [];
const consoleErrors = [];
page.on('pageerror', (error) => pageErrors.push(String(error.message || error)));
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 300));
});
await page.goto(url, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(9000);
for (const label of ['稍后配置', 'Later']) {
  const button = page.getByRole('button', { name: label });
  if (await button.count().catch(() => 0)) { await button.first().click().catch(() => {}); break; }
}

const panelRows = page.locator("[class*='_panelRow']");
const labels = await panelRows.allInnerTexts().catch(() => []);
let clicked = false;
for (let index = 0; index < labels.length; index += 1) {
  if (/能力/.test(labels[index])) {
    await panelRows.nth(index).click().catch(() => {});
    clicked = true;
    break;
  }
}
await page.waitForTimeout(4000);

if (!clicked) failures.push(`no 能力 panel row in the sidebar: ${JSON.stringify(labels)}`);
const panel = await page.evaluate(() => ({
  present: !!document.querySelector('[data-sumika-panel]'),
  rows: document.querySelectorAll('[data-sumika-panel-row]').length,
  switches: document.querySelectorAll('[data-sumika-panel-switch]').length,
  ids: Array.from(document.querySelectorAll('[data-sumika-panel-row]'))
    .map(node => node.dataset.sumikaPanelRow),
}));
if (!panel.present) failures.push('the capabilities panel did not render');

const before = await registry();
const missing = before.map(item => item.id).filter(id => !panel.ids.includes(id));
if (missing.length) failures.push(`panel is missing registered capabilities: ${missing}`);

let toggle = null;
const target = before.find(item => item.id === 'camera') || before[0];
if (target) {
  const wanted = target.enabled !== true;
  await page.locator(`[data-sumika-panel-row='${target.id}'] [data-sumika-panel-switch]`)
    .first().click().catch(() => {});
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const current = (await registry()).find(item => item.id === target.id);
    if (current && current.enabled === wanted) break;
    await page.waitForTimeout(250);
  }
  const after = (await registry()).find(item => item.id === target.id);
  toggle = { id: target.id, requested: wanted, registry_after: after?.enabled };
  if (after?.enabled !== wanted) failures.push(`panel toggle did not reach the bridge for ${target.id}`);
  await page.locator(`[data-sumika-panel-row='${target.id}'] [data-sumika-panel-switch]`)
    .first().click().catch(() => {});
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const current = (await registry()).find(item => item.id === target.id);
    if (current && current.enabled === (target.enabled === true)) break;
    await page.waitForTimeout(250);
  }
  const restored = (await registry()).find(item => item.id === target.id);
  toggle.restored = restored?.enabled;
  if (restored?.enabled !== (target.enabled === true)) {
    failures.push(`panel switch for ${target.id} was not restored`);
  }
}

if (pageErrors.length) failures.push(`client errors: ${pageErrors.join(' | ')}`);
if (consoleErrors.length) failures.push(`client console errors: ${consoleErrors.join(' | ')}`);
if (shotPath) await page.screenshot({ path: shotPath, fullPage: false });
await browser.close();

const result = {
  checked_at: new Date().toISOString(),
  bridge,
  panel_rows: labels,
  panel,
  toggle,
  page_errors: pageErrors,
  console_errors: consoleErrors,
  failures,
  status: failures.length ? 'failed' : 'passed',
};
console.log(JSON.stringify(result, null, 2));
if (evidencePath) await writeFile(evidencePath, JSON.stringify(result, null, 2) + '\n', 'utf8');
process.exit(failures.length ? 1 : 0);
