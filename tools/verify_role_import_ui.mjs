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
  'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/df473e5367fa2b42/bin/node_modules/',
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

// 版C 的名册默认收起：收起时 `.roster-panel` 为 `display:none`，其中的导入入口
// 尺寸为 0，点不到。展开路径是「点击常驻标题条」（见 index.html 的 rosterDock），
// 所以先像用户一样展开，再操作面板内的入口。
const rosterDock = page.locator('#rosterDock');
if (!await rosterDock.evaluate(el => el.classList.contains('open'))) {
  await page.locator('#rosterBar').click();
  await rosterDock.locator('.roster-panel').waitFor({state: 'visible'});
}
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
// 版C 把名册改为底部收起条：成员容器由 .roster 变为 .roster-list。
// 两种都写，与 bind.js 的兼容写法一致，避免结构再调整时这里静默失效。
const MEMBER_SEL = '#screen-room .roster-list .member, #screen-room .roster .member';
const UNFINISHED_SEL = '#screen-room .roster-list .sumika-unfinished, #screen-room .roster .sumika-unfinished';
const roster = await page.evaluate((sel) => ({
  names: Array.from(document.querySelectorAll(sel))
    .map(node => ({
      name: node.querySelector('.nm')?.textContent || node.innerText.split('\n')[0],
      status: node.querySelector('.st')?.textContent || '',
      active: node.classList.contains('active'),
    })),
}), MEMBER_SEL);
const complete = roster.names.find(item => item.name.includes('导入流程测试角色')
  && item.status.includes('用户导入'));
if (!complete) failures.push(`the complete role is not in the roster: ${JSON.stringify(roster.names)}`);
const unfinishedNote = await page.locator(UNFINISHED_SEL).first().innerText()
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
  // Completing it in place must move it into the roster.
  // 名册会随事件重渲染，所以「填路径」与「点补挂」之间节点可能被换掉——那样按钮
  // 读到的是空值，会走「先填路径」分支而**不发请求**，看起来就像附加失败。
  // 因此每一轮都重新定位节点、填值、点击，并把按钮自己的提示读出来作为失败原因，
  // 而不是只报一句「没完成」让人去猜。
  const attachSel = `[data-attach-path='${cardOnlyId}']`;
  if (await page.locator(attachSel).count() === 0) {
    failures.push('an unfinished user role offers no way to attach its model');
  } else {
    let attached = null, buttonNote = '';
    for (let attempt = 0; attempt < 8; attempt += 1) {
      await page.locator(attachSel).fill(modelPath);
      const fix = page.locator(attachSel).locator('xpath=..');
      await fix.getByRole('button').click();
      for (let wait = 0; wait < 12; wait += 1) {
        attached = (await (await fetch(`${bridge}/api/roles`)).json()).roles
          .find(item => item.id === cardOnlyId);
        if (attached?.complete === true) break;
        await page.waitForTimeout(400);
      }
      if (attached?.complete === true) break;
      buttonNote = await fix.getByRole('button').innerText().catch(() => '');
    }
    if (attached?.complete !== true) {
      failures.push(`attaching the model did not complete the role: ${JSON.stringify(attached)}`
        + (buttonNote ? ` (the button said: ${buttonNote})` : ''));
    } else {
      await page.waitForTimeout(1200);
      const afterAttach = await page.evaluate((sel) => Array.from(
        document.querySelectorAll(sel))
        .map(node => node.querySelector('.nm')?.textContent || ''), MEMBER_SEL);
      if (!afterAttach.some(name => name.includes('导入流程测试角色'))) {
        failures.push(`the completed role is still not in the roster: ${JSON.stringify(afterAttach)}`);
      }
    }
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
// 桥接的所有写接口都要 X-Sumika-CSRF；漏了它只会拿到 403，
// 于是「清理没做掉」会被误读成被测功能的缺陷，还会把测试角色留在用户档案里。
let removalBody = '';
let removalStatus = 0;
const session = await (await fetch(`${bridge}/api/manage/session`)).json();
for (const id of [completeId, cardOnlyId]) {
  const removal = await fetch(`${bridge}/api/roles/remove`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Sumika-CSRF': session.csrf },
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
