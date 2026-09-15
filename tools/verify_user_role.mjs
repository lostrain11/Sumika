// The user-imported role must work end to end: its own card drives the chat and
// its own VRM drives the stage, with nothing borrowed from the built-in sample.
//
// Costs one small role-model call. Usage:
//   node tools/verify_user_role.mjs [bridge] [roleId] [evidence.json] [shot.png]
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';

const require = createRequire(
  'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/',
);
const { chromium } = require('playwright');

const bridge = process.argv[2] || 'http://127.0.0.1:8765';
const roleId = process.argv[3] || 'ando-subaru';
const evidencePath = process.argv[4] || null;
const shotPath = process.argv[5] || null;

const failures = [];
const payload = await (await fetch(`${bridge}/api/roles`)).json();
const role = (payload.roles || []).find(item => item.id === roleId);
if (!role) failures.push(`role ${roleId} is not listed by the bridge`);
else {
  if (role.kind !== 'user') failures.push(`role ${roleId} is not marked as user-imported`);
  if (!role.model_3d_url) failures.push(`role ${roleId} has no 3D asset url`);
}

const assetResponse = role?.model_3d_url
  ? await fetch(`${bridge}${role.model_3d_url}`) : null;
if (assetResponse && assetResponse.status !== 200) {
  failures.push(`the role's 3D asset is not served: HTTP ${assetResponse.status}`);
}
const assetBytes = assetResponse ? Number(assetResponse.headers.get('content-length') || 0) : 0;

const browser = await chromium.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const pageErrors = [];
const consoleErrors = [];
const assetRequests = [];
page.on('pageerror', (error) => pageErrors.push(String(error.message || error)));
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 300));
});
page.on('request', (request) => {
  if (role?.model_3d_url && request.url().includes(role.model_3d_url)) assetRequests.push(request.url());
});

await page.goto(`${bridge}/#room`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(5000);

const stage = await page.evaluate(() => ({
  active: document.querySelector('.member.active .nm')?.textContent || null,
  activeSub: document.querySelector('.member.active .st')?.textContent || null,
  stageName: document.getElementById('stageChara')?.textContent || null,
  stageSub: document.getElementById('stageCharaSub')?.textContent || null,
  layerTag: document.getElementById('layerVrmTag')?.textContent || null,
  vrmVisible: document.getElementById('vport')?.classList.contains('show-vrm') || false,
  canvas: !!document.querySelector('#vrmLive canvas'),
  header: document.getElementById('chatChara')?.textContent || null,
}));
if (stage.active !== role?.name) failures.push(`roster active is ${stage.active}, expected ${role?.name}`);
if (!/用户导入/.test(stage.stageSub || '')) failures.push(`stage sub does not say 用户导入: ${stage.stageSub}`);
if (!/已绑定/.test(stage.layerTag || '')) {
  failures.push(`layer legend does not list the bound roles: ${stage.layerTag}`);
}
if (role?.name && !(stage.layerTag || '').includes(role.name)) {
  failures.push(`layer legend omits the imported role: ${stage.layerTag}`);
}
if (stage.header !== role?.name) failures.push(`chat header is ${stage.header}, expected ${role?.name}`);
if (!stage.canvas) failures.push('no VRM canvas was mounted on the stage');
if (assetRequests.length === 0 && role?.model_3d_url) {
  failures.push('the page never requested the role own 3D asset');
}

await page.locator('[data-room-input]').fill('你好，简单打个招呼就好。');
await page.locator('[data-room-input]').press('Enter');
let reply = null;
for (let attempt = 0; attempt < 60; attempt += 1) {
  reply = await page.evaluate(() => {
    const nodes = Array.from(document.querySelectorAll('#screen-room .chat-msgs .cm'));
    const last = nodes.at(-1);
    return {
      count: nodes.length,
      role: last?.className.includes('user') ? 'me' : 'role',
      text: last?.querySelector('.bub')?.textContent || '',
      error: last?.dataset.roomError === '1',
    };
  });
  if (reply.count >= 2 && reply.role === 'role' && reply.text) break;
  await page.waitForTimeout(1000);
}
if (!reply || reply.role !== 'role' || !reply.text) failures.push('the imported role never answered');
else if (reply.error) failures.push(`the imported role refused: ${reply.text}`);

if (shotPath) await page.screenshot({ path: shotPath, fullPage: false });
if (pageErrors.length) failures.push(`client errors: ${pageErrors.join(' | ')}`);
if (consoleErrors.length) failures.push(`client console errors: ${consoleErrors.join(' | ')}`);
await browser.close();

const result = {
  checked_at: new Date().toISOString(),
  bridge,
  role: role ? { id: role.id, name: role.name, kind: role.kind, model_3d_url: role.model_3d_url } : null,
  asset: { status: assetResponse?.status ?? null, bytes: assetBytes,
           requested_by_page: assetRequests.length },
  stage,
  reply,
  page_errors: pageErrors,
  console_errors: consoleErrors,
  failures,
  status: failures.length ? 'failed' : 'passed',
};
console.log(JSON.stringify(result, null, 2));
if (evidencePath) await writeFile(evidencePath, JSON.stringify(result, null, 2) + '\n', 'utf8');
process.exit(failures.length ? 1 : 0);
