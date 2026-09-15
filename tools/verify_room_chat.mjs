// The 活动室 chat column must be the real role conversation, not the design's
// sample messages. Sends one short message and checks both surfaces agree.
//
// Costs one small role-model call. Usage:
//   node tools/verify_room_chat.mjs [bridge] [evidence.json] [shot.png]
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';

const require = createRequire(
  'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/',
);
const { chromium } = require('playwright');

const bridge = process.argv[2] || 'http://127.0.0.1:8765';
const evidencePath = process.argv[3] || null;
const shotPath = process.argv[4] || null;
const prompt = '你好，用一句话打个招呼就好。';

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

const before = await page.evaluate(() => {
  const list = document.querySelector('#screen-room .chat-msgs');
  return {
    text: list?.innerText || '',
    empty: !!document.querySelector('[data-room-empty]'),
    input: !!document.querySelector('[data-room-input]'),
    header: document.getElementById('chatChara')?.textContent || null,
    stage: document.getElementById('stageChara')?.textContent || null,
  };
});
// The design shipped two fabricated messages; they must be gone.
for (const sample of ['先陪我过一下多角色的排布方案', '名册里的每位伙伴有自己的强调色和独立记忆']) {
  if (before.text.includes(sample)) failures.push(`design sample message still rendered: ${sample}`);
}
if (!before.input) failures.push('the chat composer is not a real input');
for (const [where, value] of [['chat header', before.header], ['stage name', before.stage]]) {
  if (!value || value === '澄花') {
    failures.push(`${where} still shows the design placeholder name: ${value}`);
  }
}

await page.locator('[data-room-input]').fill(prompt);
await page.locator('[data-room-input]').press('Enter');

let after = null;
for (let attempt = 0; attempt < 60; attempt += 1) {
  after = await page.evaluate(() => {
    const list = document.querySelector('#screen-room .chat-msgs');
    const nodes = Array.from(list?.querySelectorAll('.cm') || []);
    const last = nodes.at(-1);
    return {
      count: nodes.length,
      lastRole: last?.className.includes('user') ? 'me' : 'role',
      lastText: last?.querySelector('.bub')?.textContent || '',
      error: last?.dataset.roomError === '1',
    };
  });
  if (after.count >= 2 && after.lastText && after.lastRole === 'role') break;
  await page.waitForTimeout(1000);
}
const emptyLeft = await page.locator('[data-room-empty]').count().catch(() => 0);
if (emptyLeft > 0) failures.push('the empty-state bubble stayed after the first message');
if (!after || after.lastRole !== 'role' || !after.lastText) {
  failures.push('the chat never rendered a reply bubble');
} else if (after.error) {
  failures.push(`the role service refused: ${after.lastText}`);
}

if (shotPath) await page.screenshot({ path: shotPath, fullPage: false });
await browser.close();

const session = 'room-unknown';
if (pageErrors.length) failures.push(`client errors: ${pageErrors.join(' | ')}`);
if (consoleErrors.length) failures.push(`client console errors: ${consoleErrors.join(' | ')}`);
const result = {
  checked_at: new Date().toISOString(),
  bridge,
  prompt,
  before,
  after,
  session_hint: session,
  page_errors: pageErrors,
  console_errors: consoleErrors,
  failures,
  status: failures.length ? 'failed' : 'passed',
};
console.log(JSON.stringify(result, null, 2));
if (evidencePath) await writeFile(evidencePath, JSON.stringify(result, null, 2) + '\n', 'utf8');
process.exit(failures.length ? 1 : 0);
