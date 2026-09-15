// The roster's import entry must really import a user role, and the test role it
// creates is removed again afterwards so the user's list stays as it was.
//
// Usage:
//   node tools/verify_role_import_ui.mjs [bridge] [evidence.json] [shot.png]
import { createRequire } from 'node:module';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { writeFile } from 'node:fs/promises';

const require = createRequire(
  'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/',
);
const { chromium } = require('playwright');

const bridge = process.argv[2] || 'http://127.0.0.1:8765';
const evidencePath = process.argv[3] || null;
const shotPath = process.argv[4] || null;
const roleId = 'ui-import-test';

const card = {
  spec: 'chara_card_v2',
  data: {
    name: '导入流程测试角色',
    description: '由 verify_role_import_ui.mjs 临时导入，验证结束后删除。',
    personality: '简洁',
    scenario: '导入流程测试',
    character_book: { entries: [{ keys: ['测试'], content: '临时条目' }] },
  },
};
const directory = mkdtempSync(join(tmpdir(), 'sumika-import-'));
const cardPath = join(directory, 'card.json');
writeFileSync(cardPath, JSON.stringify(card, null, 2), 'utf8');

const failures = [];
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

await page.goto(`${bridge}/#room`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(4000);

const trigger = page.locator('#screen-room .roster-foot .import-btn');
if (await trigger.count() === 0) failures.push('the roster has no import entry');
await trigger.click();
await page.waitForTimeout(300);
const form = page.locator('#screen-room .sumika-import');
if (await form.count() === 0) failures.push('the import form did not appear');

await form.locator('[data-import="id"]').fill(roleId);
await form.locator('[data-import="card"]').setInputFiles(cardPath);
await form.locator('[data-import="submit"]').click();

let status = null;
for (let attempt = 0; attempt < 40; attempt += 1) {
  status = await form.locator('[data-import="status"]').innerText().catch(() => '');
  if (/已导入|失败/.test(status)) break;
  await page.waitForTimeout(500);
}
if (!/已导入/.test(status || '')) failures.push(`import did not report success: ${status}`);

await page.waitForTimeout(1500);
const roster = await page.evaluate(() => ({
  names: Array.from(document.querySelectorAll('#screen-room .roster .member'))
    .map(node => ({
      name: node.querySelector('.nm')?.textContent || node.innerText.split('\n')[0],
      status: node.querySelector('.st')?.textContent || '',
      active: node.classList.contains('active'),
    })),
}));
const imported = roster.names.find(item => item.status.includes('用户导入')
  && item.name.includes('导入流程测试角色'));
if (!imported) failures.push(`the imported role is not in the roster: ${JSON.stringify(roster.names)}`);

const listed = await (await fetch(`${bridge}/api/roles`)).json();
const entry = (listed.roles || []).find(item => item.id === roleId);
if (!entry) failures.push('the bridge does not list the imported role');
else if (entry.kind !== 'user') failures.push(`imported role kind is ${entry.kind}`);

if (shotPath) await page.screenshot({ path: shotPath, fullPage: false });

// Undo: the test role exists only for this run.
const removal = await fetch(`${bridge}/api/roles/remove`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ id: roleId }),
});
const removalBody = await removal.text();
const after = await (await fetch(`${bridge}/api/roles`)).json();
if ((after.roles || []).some(item => item.id === roleId)) {
  failures.push(`the test role was not removed: ${removal.status} ${removalBody}`);
}

if (pageErrors.length) failures.push(`client errors: ${pageErrors.join(' | ')}`);
if (consoleErrors.length) failures.push(`client console errors: ${consoleErrors.join(' | ')}`);
await browser.close();

const result = {
  checked_at: new Date().toISOString(),
  bridge,
  imported: { id: roleId, listed: entry || null, roster_entry: imported || null, status },
  cleanup: { status: removal.status, body: removalBody.slice(0, 200) },
  page_errors: pageErrors,
  console_errors: consoleErrors,
  failures,
  status: failures.length ? 'failed' : 'passed',
};
console.log(JSON.stringify(result, null, 2));
if (evidencePath) await writeFile(evidencePath, JSON.stringify(result, null, 2) + '\n', 'utf8');
process.exit(failures.length ? 1 : 0);
