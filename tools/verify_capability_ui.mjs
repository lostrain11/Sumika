// Real-browser acceptance for the capability switches (R-107/R-108).
//
// Drives the Sumika shell the way a user does: open 能力, check every switch
// against the registry, flip one through the DOM and confirm the backend really
// changed, then check 设置 shows the same facts. The flipped switch is restored.
//
// Usage:
//   node tools/verify_capability_ui.mjs [bridge] [evidence.json] [shelf.png] [settings.png]
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';

const require = createRequire(
  'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/',
);
const { chromium } = require('playwright');

const bridge = process.argv[2] || 'http://127.0.0.1:8765';
const evidencePath = process.argv[3] || null;
const shelfShot = process.argv[4] || null;
const settingsShot = process.argv[5] || null;

const registry = async () => (await (await fetch(`${bridge}/api/modules`)).json()).modules;

const browser = await chromium.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
});
const page = await browser.newPage();
const pageErrors = [];
page.on('pageerror', (error) => pageErrors.push(String(error.message || error)));
await page.goto(bridge, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(3500);

const failures = [];
await page.locator("#gnav button[data-go='shelf']").click();
await page.waitForTimeout(1200);

const shelfState = await page.evaluate(() => {
  const shelf = document.querySelector('#screen-shelf');
  const cards = Array.from(shelf.querySelectorAll('.cap-card'));
  const kv = (panel) => Object.fromEntries(Array.from(panel?.querySelectorAll('.kv') || [])
    .map(row => [row.querySelector('span')?.textContent.trim(), row.querySelector('b')?.textContent]));
  const panels = document.querySelectorAll('.cap-side .panel');
  return {
    visible: shelf.classList.contains('show'),
    cards: cards.length,
    switchable: cards.filter(card => card.querySelector('[data-capability-switch]'))
      .map(card => ({
        id: card.dataset.capabilityId || null,
        checked: card.querySelector('[data-capability-switch]').getAttribute('aria-checked'),
    })),
    groups: Array.from(shelf.querySelectorAll('.cap-group h2')).map(node => node.textContent.trim()),
    detail: kv(panels[0]),
    counts: Array.from(panels[1]?.querySelectorAll('.st-grid > div') || [])
      .map(cell => cell.querySelector('b')?.textContent),
  };
});
if (!shelfState.visible) failures.push('能力 screen did not open');
if (shelfState.cards === 0) failures.push('能力 screen rendered no cards');
if (!/注册表/.test(shelfState.detail?.['来源'] || '')) {
  failures.push(`detail panel does not describe a registry entry: ${JSON.stringify(shelfState.detail)}`);
}
const enabledCount = (await registry()).filter(item => item.enabled).length;
if (String(enabledCount) !== shelfState.counts?.[0]) {
  failures.push(`启用状态 panel shows ${shelfState.counts?.[0]}, registry has ${enabledCount} enabled`);
}

const before = await registry();
const expected = Object.fromEntries(before.map(item => [item.id, String(item.enabled === true)]));
for (const entry of shelfState.switchable) {
  if (entry.id === null) {
    failures.push('a capability switch has no capability id');
    continue;
  }
  if (expected[entry.id] === undefined) {
    failures.push(`switch for unregistered capability ${entry.id}`);
  } else if (expected[entry.id] !== entry.checked) {
    failures.push(`switch ${entry.id} shows aria-checked=${entry.checked}, registry says ${expected[entry.id]}`);
  }
}

// Flip one switch through the DOM and confirm the registry really changed.
let toggled = null;
const target = shelfState.switchable.find(entry => entry.id === 'camera')
  || shelfState.switchable[0];
if (target) {
  const wanted = target.checked !== 'true';
  await page.locator(`[data-capability-id='${target.id}'] [data-capability-switch]`).first().click();
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const current = (await registry()).find(item => item.id === target.id);
    if (current && current.enabled === wanted) break;
    await page.waitForTimeout(250);
  }
  const after = (await registry()).find(item => item.id === target.id);
  const ariaAfter = await page.locator(`[data-capability-id='${target.id}'] [data-capability-switch]`)
    .first().getAttribute('aria-checked').catch(() => null);
  toggled = { id: target.id, from: target.checked, requested: wanted,
              registry_after: after?.enabled, aria_after: ariaAfter };
  if (after?.enabled !== wanted) failures.push(`UI toggle did not reach the registry for ${target.id}`);
  if (ariaAfter !== String(wanted)) failures.push(`switch ${target.id} did not re-render after toggling`);
  // Put it back the way the user had it.
  await page.locator(`[data-capability-id='${target.id}'] [data-capability-switch]`).first().click();
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const current = (await registry()).find(item => item.id === target.id);
    if (current && current.enabled === (target.checked === 'true')) break;
    await page.waitForTimeout(250);
  }
  const restored = (await registry()).find(item => item.id === target.id);
  toggled.restored = restored?.enabled;
  if (restored?.enabled !== (target.checked === 'true')) {
    failures.push(`switch ${target.id} was not restored to ${target.checked}`);
  }
} else {
  failures.push('no switchable capability was rendered');
}

if (shelfShot) await page.screenshot({ path: shelfShot, fullPage: false });

await page.locator("#gnav button[data-go='settings']").click();
await page.waitForTimeout(1000);
const settingsState = await page.evaluate(() => {
  const group = Array.from(document.querySelectorAll('#screen-settings .set-group'))
    .find(node => /能力模块/.test(node.querySelector('h2')?.textContent || ''));
  if (!group) return null;
  return {
    visible: document.querySelector('#screen-settings').classList.contains('show'),
    summary: group.querySelector('.set-row b')?.textContent || null,
    switches: group.querySelectorAll('[data-capability-switch]').length,
    ids: Array.from(group.querySelectorAll('[data-capability-id]'))
      .map(node => node.dataset.capabilityId),
    side: Object.fromEntries(Array.from(document.querySelectorAll('.set-side .panel .kv'))
      .map(row => [row.querySelector('span')?.textContent.trim(), row.querySelector('b')?.textContent])),
    models: Object.fromEntries(Array.from(document.querySelectorAll('#screen-settings .set-group'))
      .filter(node => /模型与连接/.test(node.querySelector('h2')?.textContent || ''))
      .flatMap(node => Array.from(node.querySelectorAll('.set-row')))
      .map(row => [(row.querySelector('div')?.textContent || '').split('角色')[0].trim(),
                   row.querySelector('.val')?.textContent.trim()])),
    placeholders: {
      checkpoint: /[0-9a-f]{7}/.test(document.querySelector('#screen-settings').innerText.match(/最近\s*[0-9a-f]{7}/)?.[0] || ''),
      mcpCount: /项已授权/.test(document.querySelector('#screen-settings').innerText),
      enabledButtons: Array.from(document.querySelectorAll('#screen-settings .set-group'))
        .filter(group => group.querySelector('h2 .rsv-tag'))
        .flatMap(group => Array.from(group.querySelectorAll('button:not([disabled])')))
        .map(node => node.textContent.trim()),
    },
  };
});
if (!settingsState) failures.push('设置 screen has no 能力模块 section');
else {
  if (!settingsState.visible) failures.push('设置 screen did not open');
  const enabled = before.filter(item => item.enabled).length;
  if (!settingsState.summary || !settingsState.summary.includes(`${enabled} 已启用`)) {
    failures.push(`设置 summary does not match the registry: ${settingsState.summary}`);
  }
  const missing = before.map(item => item.id).filter(id => !settingsState.ids.includes(id));
  if (missing.length) failures.push(`设置 section is missing switches: ${missing}`);
  const status = await (await fetch(`${bridge}/api/workbench`)).json();
  if (!settingsState.side?.DSH?.includes(status.version)) {
    failures.push(`设置 side panel does not show the harness release: ${settingsState.side?.DSH}`);
  }
  const tree = await (await fetch(`${bridge}/api/tree`)).json();
  if (tree.project?.path && settingsState.side?.项目 !== tree.project.path) {
    failures.push(`设置 side panel project is ${settingsState.side?.项目}, expected ${tree.project.path}`);
  }
  const roleModel = (await (await fetch(`${bridge}/api/state`)).json()).role?.model;
  if (!Object.values(settingsState.models || {}).some(value => (value || '').includes(roleModel))) {
    failures.push(`角色模型 row does not show the role service model: ${JSON.stringify(settingsState.models)}`);
  }
  if (settingsState.placeholders?.checkpoint || settingsState.placeholders?.mcpCount) {
    failures.push(`settings still show sample values: ${JSON.stringify(settingsState.placeholders)}`);
  }
  if (settingsState.placeholders?.enabledButtons?.length) {
    failures.push(`unwired settings groups still have live buttons: ${settingsState.placeholders.enabledButtons}`);
  }
}
if (settingsShot) await page.screenshot({ path: settingsShot, fullPage: false });

if (pageErrors.length) failures.push(`client errors: ${pageErrors.join(' | ')}`);
await browser.close();

const result = {
  checked_at: new Date().toISOString(),
  bridge,
  shelf: shelfState,
  toggle: toggled,
  settings: settingsState,
  page_errors: pageErrors,
  failures,
  status: failures.length ? 'failed' : 'passed',
};
console.log(JSON.stringify(result, null, 2));
if (evidencePath) await writeFile(evidencePath, JSON.stringify(result, null, 2) + '\n', 'utf8');
process.exit(failures.length ? 1 : 0);
