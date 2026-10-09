// Real-browser acceptance for the capability switches (R-107/R-108).
//
// Drives the Sumika shell the way a user does: open 能力, check every switch
// against the registry, flip one through the DOM and confirm the backend really
// changed, then confirm 设置 no longer duplicates the capability controls (the
// capability page is the single entry, per the user's authorised consolidation).
// The flipped switch is restored.
//
// Two counting rules this file encodes, both learned from real defects:
//   1. The 启用状态 panel counts the switches the user can see and click, not the
//      raw /api/modules rows — voice+asr merge into one 语音交互 card and
//      microphone folds into it, so the registry total is legitimately higher.
//   2. 设置 must render zero capability switches; a reappearing copy is a regression.
//
// Usage:
//   node tools/verify_capability_ui.mjs [bridge] [evidence.json] [shelf.png] [settings.png]
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';

const require = createRequire(
  'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/df473e5367fa2b42/bin/node_modules/',
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
// Icon loading is part of this screen's contract: cards are rebuilt at runtime, so
// the data-icon placeholders must be hydrated here and the request count must stay
// bounded. Unbounded parallel icon fetches once caused random ERR_CONNECTION_REFUSED
// and silently blank icons; both are asserted rather than assumed.
const iconRequests = [];
const failedRequests = [];
page.on('request', (request) => {
  if (request.url().includes('/vendor/icons/')) iconRequests.push(request.url().split('/').pop());
});
page.on('requestfailed', (request) => {
  failedRequests.push(`${request.url().split('/').pop()} :: ${request.failure()?.errorText}`);
});
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
  // bind.js 会把「扩展模块/就绪视图/DSH 原生」三组重排成「开发/办公/陪伴」业务分组，
  // 组名不再能用来区分口径。注册表口径的卡片带 data-capability-id（含只有详情、
  // 无内联开关的语音交互与长期记忆），其余为就绪视图与 DSH 原生卡片。
  const registryCards = cards.filter(card => card.dataset.capabilityId);
  const glyphs = cards.map(card => card.querySelector('.cap-ic'));
  return {
    visible: shelf.classList.contains('show'),
    cards: cards.length,
    registryCards: registryCards.length,
    registryIds: registryCards.map(card => card.dataset.capabilityId),
    // 卡片图标必须是 SVG，且不能残留说明文字（历史缺陷：运行时用 ◈ ⌨ ✎ 等字符）
    iconSvg: glyphs.filter(node => node?.querySelector('svg')).length,
    iconText: glyphs.map(node => (node?.textContent || '').trim()).filter(Boolean),
    leftoverPlaceholders: shelf.querySelectorAll('[data-icon]').length,
    groupNames: Array.from(shelf.querySelectorAll('.cap-group'))
      .map(group => group.querySelector('h2 b')?.textContent.trim()).filter(Boolean),
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
// 图标：每张卡片都必须渲染成 Lucide SVG，不能退回 Unicode 字符。
// 这些卡片是 bind.js 运行期重建的，静态 HTML 里的占位会被丢弃，
// 所以必须在这里断言，而不是只看静态标记。
if (shelfState.iconSvg !== shelfState.cards) {
  failures.push(`only ${shelfState.iconSvg}/${shelfState.cards} capability cards render an icon SVG; `
    + `text leftovers: ${JSON.stringify(shelfState.iconText)}`);
}
if (shelfState.iconText.length) {
  failures.push(`capability cards still render glyph text instead of icons: `
    + JSON.stringify(shelfState.iconText));
}
if (shelfState.leftoverPlaceholders !== 0) {
  failures.push(`${shelfState.leftoverPlaceholders} [data-icon] placeholders were never hydrated`);
}
// 图标请求必须「按需且成功」：既不预拉整表，也不允许静默失败。
const uniqueIcons = new Set(iconRequests).size;
if (iconRequests.length > 45) {
  failures.push(`icon loading is not on demand: ${iconRequests.length} SVG requests `
    + `(${uniqueIcons} unique) for ${shelfState.cards} cards`);
}
if (failedRequests.length) {
  failures.push(`icon requests failed: ${failedRequests.join(' | ')}`);
}
const enabledCount = (await registry()).filter(item => item.enabled).length;
// The panel counts the 6 capabilities the page actually lists, not the 7 raw registry
// rows: voice + asr + microphone merge into one 语音交互 card and 长期记忆 is a
// settings-backed card that has no registry row. Two of the six (语音交互, 长期记忆)
// are detail-only and carry no inline switch, so the panel total exceeds the
// rendered switch count by exactly those. Assert the split adds up to the cards.
const shown = (shelfState.counts || []).map(Number);
const [shownEnabled, shownDisabled, shownUnavailable] = shown;
if (Number.isFinite(shownEnabled) && Number.isFinite(shownDisabled)
    && Number.isFinite(shownUnavailable)) {
  // 已启用 + 已停用 覆盖注册表口径的全部卡片（带 data-capability-id 的 6 张，含只有
  // 详情、无内联开关的语音交互与长期记忆），与就绪视图 / DSH 原生卡片无关。
  if (shownEnabled + shownDisabled !== shelfState.registryCards) {
    failures.push(`启用状态 panel splits ${shownEnabled}+${shownDisabled}, but `
      + `${shelfState.registryCards} registry-backed cards are rendered `
      + `(${JSON.stringify(shelfState.registryIds)})`);
  }
  const switchableOn = shelfState.switchable.filter(entry => entry.checked === 'true').length;
  if (switchableOn > shownEnabled) {
    failures.push(`启用状态 panel shows ${shownEnabled} enabled, but ${switchableOn} rendered `
      + 'switches are on');
  }
}
if (String(enabledCount) === shelfState.counts?.[0] && enabledCount !== shelfState.registryCards) {
  failures.push(`启用状态 panel still mirrors the raw registry (${enabledCount}); it must `
    + `count the ${shelfState.registryCards} registry-backed capabilities instead`);
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
// 设置页不再有「能力模块」分区。用户明确要求把语音与设备、长期记忆的详细设置移到
// 能力页对应卡片内，并保留能力页作为唯一管理入口（requirements.json R-107/R-108 跟进项，
// progress.json / handoff.json 的 settings_capabilities 记录为「用户授权移除」）。
// 因此这里改为断言「唯一入口」：设置页不得再出现能力开关，能力页必须仍是可操作的。
const settingsState = await page.evaluate(() => {
  const screen = document.querySelector('#screen-settings');
  const groups = Array.from(screen.querySelectorAll('.set-group'));
  return {
    visible: screen.classList.contains('show'),
    groups: groups.map(node => node.querySelector('h2')?.textContent.trim() || ''),
    capabilityGroups: groups
      .filter(node => /能力模块/.test(node.querySelector('h2')?.textContent || '')).length,
    capabilitySwitches: screen.querySelectorAll('[data-capability-switch]').length,
    side: Object.fromEntries(Array.from(document.querySelectorAll('.set-side .panel .kv'))
      .map(row => [row.querySelector('span')?.textContent.trim(), row.querySelector('b')?.textContent])),
    // 「模型与连接」用 .model-usage-panel + .set-row(span+input)，不是 .val 只读行。
    // 只取「角色模型」面板，避免与辅助模型/工作模型的同名行混淆。
    models: (() => {
      const group = groups.find(node => /模型与连接/.test(node.querySelector('h2')?.textContent || ''));
      const panel = group?.querySelector('.model-usage-panel[data-usage="role"]');
      if (!panel) return {};
      return Object.fromEntries(Array.from(panel.querySelectorAll('.set-row')).map(row => {
        const label = row.querySelector('span')?.textContent.trim() || '';
        const control = row.querySelector('input, select');
        const value = control?.tagName === 'SELECT'
          ? control.selectedOptions?.[0]?.textContent?.trim()
          : control?.type === 'checkbox' ? String(control.checked) : control?.value;
        return [label, value];
      }));
    })(),
    placeholders: {
      checkpoint: /[0-9a-f]{7}/.test(screen.innerText.match(/最近\s*[0-9a-f]{7}/)?.[0] || ''),
      mcpCount: /项已授权/.test(screen.innerText),
      enabledButtons: groups
        .filter(group => group.querySelector('h2 .rsv-tag'))
        .flatMap(group => Array.from(group.querySelectorAll('button:not([disabled])')))
        .map(node => node.textContent.trim()),
    },
  };
});
if (!settingsState) {
  failures.push('设置 screen could not be inspected');
} else {
  if (!settingsState.visible) failures.push('设置 screen did not open');
  // 单一入口：设置页有且只有一份能力开关（0 份）。
  if (settingsState.capabilityGroups !== 0) {
    failures.push(`设置 still renders ${settingsState.capabilityGroups} 能力模块 section(s); `
      + 'the capability page is meant to be the only entry');
  }
  if (settingsState.capabilitySwitches !== 0) {
    failures.push(`设置 still renders ${settingsState.capabilitySwitches} capability switches; `
      + 'they belong to the capability page only');
  }
  // 能力页的开关仍在且可操作（由上面的 toggle 断言覆盖），设置页改为只读事实面板。
  if (settingsState.groups.length === 0) failures.push('设置 screen rendered no sections at all');
  const status = await (await fetch(`${bridge}/api/workbench`)).json();
  if (!settingsState.side?.DSH?.includes(status.version)) {
    failures.push(`设置 side panel does not show the harness release: ${settingsState.side?.DSH}`);
  }
  const tree = await (await fetch(`${bridge}/api/tree`)).json();
  if (tree.project?.path && settingsState.side?.项目 !== tree.project.path) {
    failures.push(`设置 side panel project is ${settingsState.side?.项目}, expected ${tree.project.path}`);
  }
  const roleModel = (await (await fetch(`${bridge}/api/state`)).json()).role?.model;
  // 角色模型分区是可编辑表单，不是只读事实行：断言「模型名称」字段真的预填了
  // 角色服务当前使用的模型，而不是断言某个只读 .val 文本。
  const shownModel = settingsState.models?.['模型名称'];
  if (!shownModel) {
    failures.push(`角色模型 panel has no 模型名称 field: ${JSON.stringify(settingsState.models)}`);
  } else if (roleModel && !String(shownModel).includes(roleModel)) {
    failures.push(`角色模型 field shows ${shownModel}, expected the role service model ${roleModel}`);
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
