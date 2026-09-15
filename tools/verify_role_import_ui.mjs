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
const completeId = 'ui-import-full';
const cardOnlyId = 'ui-import-card-only';

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
// A stand-in model file: the rule under test is "card + model", and copying a
// 16 MB VRM would only prove the filesystem works.
const modelPath = join(directory, 'placeholder.vrm');
writeFileSync(modelPath, 'vrm-placeholder', 'utf8');

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

async function importRole({ id, withModel }) {
  await form.locator('[data-import="id"]').fill(id);
  await form.locator('[data-import="card"]').setInputFiles(cardPath);
  await form.locator('[data-import="model"]').fill(withModel ? modelPath : '');
  await form.locator('[data-import="submit"]').click();
  let text = '';
  for (let attempt = 0; attempt < 40; attempt += 1) {
    text = await form.locator('[data-import="status"]').innerText().catch(() => '');
    if (/已导入|失败/.test(text)) break;
    await page.waitForTimeout(500);
  }
  return text;
}

const completeStatus = await importRole({ id: completeId, withModel: true });
if (!/已导入/.test(completeStatus)) failures.push(`complete import failed: ${completeStatus}`);
const cardOnlyStatus = await importRole({ id: cardOnlyId, withModel: false });
if (!/已导入/.test(cardOnlyStatus)) failures.push(`card-only import failed: ${cardOnlyStatus}`);

await page.waitForTimeout(1500);
const roster = await page.evaluate(() => ({
  names: Array.from(document.querySelectorAll('#screen-room .roster .member'))
    .map(node => ({
      name: node.querySelector('.nm')?.textContent || node.innerText.split('\n')[0],
      status: node.querySelector('.st')?.textContent || '',
      active: node.classList.contains('active'),
    })),
}));
const complete = roster.names.find(item => item.name.includes('导入流程测试角色')
  && item.status.includes('用户导入'));
if (!complete) failures.push(`the complete role is not in the roster: ${JSON.stringify(roster.names)}`);
const unfinishedNote = await page.locator('#screen-room .roster .sumika-unfinished').innerText()
  .catch(() => '');
const listed = await (await fetch(`${bridge}/api/roles`)).json();
const cardOnly = (listed.roles || []).find(item => item.id === cardOnlyId);
if (!cardOnly) failures.push('the card-only role is not listed at all');
else {
  if (cardOnly.complete !== false) failures.push('a card-only role is reported as complete');
  if (!(cardOnly.missing || []).includes('model_3d')) {
    failures.push(`card-only role does not report the missing model: ${cardOnly.missing}`);
  }
  if (roster.names.some(item => item.name.includes('导入流程测试角色') && item.status === '')) {
    failures.push('an unfinished role was placed in the roster');
  }
  if (!unfinishedNote.includes('缺 3D 模型')) {
    failures.push(`the roster does not say what the unfinished role lacks: ${unfinishedNote}`);
  }
}

const entry = (listed.roles || []).find(item => item.id === completeId);
if (!entry) failures.push('the bridge does not list the imported role');
else {
  if (entry.kind !== 'user') failures.push(`imported role kind is ${entry.kind}`);
  if (entry.complete !== true || !entry.model_3d_url) {
    failures.push(`card + model import is not complete: ${JSON.stringify(entry)}`);
  }
}

if (shotPath) await page.screenshot({ path: shotPath, fullPage: false });

// Undo: the test role exists only for this run.
let removalBody = '';
let removalStatus = 0;
for (const id of [completeId, cardOnlyId]) {
  const removal = await fetch(`${bridge}/api/roles/remove`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  removalStatus = removal.status;
  removalBody += await removal.text();
}
const after = await (await fetch(`${bridge}/api/roles`)).json();
for (const id of [completeId, cardOnlyId]) {
  if ((after.roles || []).some(item => item.id === id)) {
    failures.push(`the test role ${id} was not removed: ${removalStatus} ${removalBody}`);
  }
}

if (pageErrors.length) failures.push(`client errors: ${pageErrors.join(' | ')}`);
if (consoleErrors.length) failures.push(`client console errors: ${consoleErrors.join(' | ')}`);
await browser.close();

const result = {
  checked_at: new Date().toISOString(),
  bridge,
  imported: {
    complete: { id: completeId, listed: entry || null, roster_entry: complete || null,
                status: completeStatus },
    card_only: { id: cardOnlyId, listed: cardOnly || null, status: cardOnlyStatus,
                 unfinished_note: unfinishedNote },
  },
  cleanup: { status: removalStatus, body: removalBody.slice(0, 200) },
  page_errors: pageErrors,
  console_errors: consoleErrors,
  failures,
  status: failures.length ? 'failed' : 'passed',
};
console.log(JSON.stringify(result, null, 2));
if (evidencePath) await writeFile(evidencePath, JSON.stringify(result, null, 2) + '\n', 'utf8');
process.exit(failures.length ? 1 : 0);
