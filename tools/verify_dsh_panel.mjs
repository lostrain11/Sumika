// DSH's own sidebar is the project tree — the design's 项目 ▸ 任务 —
// so Sumika must not add panel rows of its own on top of it (it did twice:
// 能力 duplicated the shell's top bar, 项目 duplicated the workspace tree).
// This guards both against coming back, and checks the sidebar really is there.
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
const sidebar = await page.evaluate(() => ({
  workspaceRows: Array.from(document.querySelectorAll("[class*='_groupSection']"))
    .map(node => (node.innerText || '').split('\n')[0]),
  sessionRows: document.querySelectorAll("[class*='_root_1b2ny_3']").length,
}));
if (labels.length > 0) {
  failures.push(`Sumika must not add sidebar panel rows: ${JSON.stringify(labels)}`);
}
if (sidebar.workspaceRows.length === 0) {
  failures.push('the sidebar has no workspace row, so the project tree is missing');
}

if (pageErrors.length) failures.push(`client errors: ${pageErrors.join(' | ')}`);
if (consoleErrors.length) failures.push(`client console errors: ${consoleErrors.join(' | ')}`);
if (shotPath) await page.screenshot({ path: shotPath, fullPage: false });
await browser.close();

const result = {
  checked_at: new Date().toISOString(),
  bridge,
  panel_rows: labels,
  sidebar,
  page_errors: pageErrors,
  console_errors: consoleErrors,
  failures,
  status: failures.length ? 'failed' : 'passed',
};
console.log(JSON.stringify(result, null, 2));
if (evidencePath) await writeFile(evidencePath, JSON.stringify(result, null, 2) + '\n', 'utf8');
process.exit(failures.length ? 1 : 0);
