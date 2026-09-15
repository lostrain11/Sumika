// Real-browser acceptance for the Sumika workbench shell.
//
// The workbench is the managed DSH web client with Sumika's profile patch layer
// applied, so this script checks what a user actually sees: the sidebar brand,
// the footer status line, the palette the skin publishes, and that no client
// error fired while the page rendered. Run it with the bridge already up.
//
// Usage:
//   node tools/verify_workbench_ui.mjs [bridge] [evidence.json] [sidebar.png] [page.png] [rail.png]
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';

const require = createRequire(
  'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/',
);
const { chromium } = require('playwright');

const bridge = process.argv[2] || 'http://127.0.0.1:8765';
const evidencePath = process.argv[3] || null;
const sidebarPath = process.argv[4] || null;
const pagePath = process.argv[5] || null;
const railPath = process.argv[6] || null;

const embed = await fetch(`${bridge}/api/workbench/embed`);
if (!embed.ok) throw new Error(`bridge did not return an embed URL: HTTP ${embed.status}`);
const { url } = await embed.json();
if (typeof url !== 'string' || !url) throw new Error('embed URL missing');

const browser = await chromium.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
});
const page = await browser.newPage();
const pageErrors = [];
// A crashing slot entry is reported as a console error ("slot entry crashed in
// '<slot>'"), not as a page error, so both channels have to be watched.
const consoleErrors = [];
page.on('pageerror', (error) => pageErrors.push(String(error.message || error)));
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 300));
});
await page.goto(url, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(9000);

// DSH's own first-run credential dialog covers the workbench in a fresh browser
// profile; dismiss it through its own "configure later" action when present.
for (const label of ['稍后配置', 'Later', 'Skip']) {
  const button = page.getByRole('button', { name: label });
  if (await button.count().catch(() => 0)) {
    await button.first().click().catch(() => {});
    await page.waitForTimeout(800);
    break;
  }
}

const probe = await page.evaluate(() => {
  const style = (selector) => {
    const node = document.querySelector(selector);
    if (!node) return null;
    const computed = getComputedStyle(node);
    return { className: node.className, background: computed.backgroundColor,
             color: computed.color, radius: computed.borderTopLeftRadius };
  };
  const root = getComputedStyle(document.documentElement);
  const text = document.body.innerText;
  return {
    skinMarker: document.documentElement.dataset.sumikaSkin || null,
    shellGlobal: window.__sumikaShell || null,
    brand: text.includes('晴日部室'),
    footerStatus: text.includes('本地优先 · 数据不出本机'),
    footerRelease: /已连接\s*DSH\s*[0-9]/.test(text),
    heroMark: (() => {
      // The slot hands its occupant the surrounding mark geometry class, so find
      // whichever element inside the headline actually paints a gradient.
      const headline = document.querySelector("[class*='_headline']") || document.body;
      for (const node of headline.querySelectorAll('*')) {
        const image = getComputedStyle(node).backgroundImage;
        if (image && image !== 'none' && image.includes('gradient')) return image;
      }
      return null;
    })(),
    surfaces: {
      frame: style("[class$='_frame']"),
      sidebar: style("[class$='_sidebarCol']"),
      newSession: style("[class$='_newSession']"),
    },
    tokens: {
      paper: root.getPropertyValue('--sumika-paper').trim(),
      rose: root.getPropertyValue('--sumika-rose').trim(),
      green: root.getPropertyValue('--sumika-green').trim(),
      webRadius: root.getPropertyValue('--dsl-web-radius').trim(),
    },
  };
});

if (sidebarPath) {
  await page.locator("[class$='_sidebarCol']").first()
    .screenshot({ path: sidebarPath }).catch(() => {});
}

// Rail check: DSH swaps the brand mark for its own panel glyph while the pointer
// is on the collapsed toggle, which reads as "the icon reverts on hover". Collapse
// the column, hover the toggle, and record what the skin actually leaves visible.
let rail = null;
const toggle = page.locator("[class*='_toggle']").first();
if (await toggle.count().catch(() => 0)) {
  await toggle.click().catch(() => {});
  await page.waitForTimeout(700);
  await toggle.hover().catch(() => {});
  await page.waitForTimeout(300);
  rail = await page.evaluate(() => {
    const mark = document.querySelector("[class*='_railMark']");
    const panelIcon = document.querySelector("[class*='_toggle'] [class*='_panelIcon']");
    const painted = (root) => {
      if (!root) return null;
      for (const node of [root, ...root.querySelectorAll('*')]) {
        const image = getComputedStyle(node).backgroundImage;
        if (image && image !== 'none' && image.includes('gradient')) return image;
      }
      return null;
    };
    return {
      markDisplay: mark ? getComputedStyle(mark).display : null,
      panelIconDisplay: panelIcon ? getComputedStyle(panelIcon).display : null,
      markGradient: painted(mark),
    };
  });
  if (railPath) await page.screenshot({ path: railPath, fullPage: false }).catch(() => {});
  await toggle.click().catch(() => {});
  await page.waitForTimeout(700);
}

// Conversation header: the Session header only mounts for a non-blank Session, so
// open one from the tree when the profile has any. The status marker reports
// "wired but idle" against "not mounted".
let sessionStatus = { state: 'no_non_blank_session' };
let sessionStatusFailure = null;
const treeRows = page.locator("[class*='_root_1b2ny_3']");
const treeRowCount = await treeRows.count().catch(() => 0);
for (let index = treeRowCount - 1; index >= 0; index -= 1) {
  const text = (await treeRows.nth(index).innerText().catch(() => '')).trim();
  if (!text || /^新会话/.test(text)) continue;
  await treeRows.nth(index).click().catch(() => {});
  await page.waitForTimeout(6000);
  break;
}
if (await page.locator("[class*='_headerUtilities']").count().catch(() => 0)) {
  const marked = page.locator('[data-sumika-session-status]');
  sessionStatus = (await marked.count().catch(() => 0)) > 0
    ? { state: await marked.first().getAttribute('data-sumika-session-status').catch(() => null) }
    : { state: 'slot_rendered_without_our_entry' };
  const lineage = page.locator('[data-sumika-lineage]');
  sessionStatus.lineage = await lineage.count().catch(() => 0) > 0
    ? { kind: await lineage.first().getAttribute('data-sumika-lineage'),
        text: (await lineage.first().innerText().catch(() => '')).trim() }
    : null;
  if (sessionStatus.lineage && sessionStatus.lineage.kind === 'workspace'
      && !sessionStatus.lineage.text.startsWith('工作区 · ')) {
    sessionStatusFailure = `session breadcrumb is not a workspace label: ${sessionStatus.lineage.text}`;
  }
  if (sessionStatus.lineage && sessionStatus.lineage.text.includes('\n')) {
    sessionStatusFailure = `session breadcrumb repeats the title: ${JSON.stringify(sessionStatus.lineage.text)}`;
  }
}
probe.sessionStatus = sessionStatus;
if (sessionStatus.state === 'slot_rendered_without_our_entry') {
  sessionStatusFailure = 'session header rendered but the Sumika status entry is missing';
}
if (pagePath) await page.screenshot({ path: pagePath, fullPage: false });

await browser.close();

const failures = [];
if (pageErrors.length) failures.push(`client errors: ${pageErrors.join(' | ')}`);
if (consoleErrors.length) failures.push(`client console errors: ${consoleErrors.join(' | ')}`);
if (probe.skinMarker !== '1') failures.push('skin marker missing');
if (!probe.brand) failures.push('sidebar brand is not 晴日部室');
if (!probe.footerStatus) failures.push('footer status line missing');
if (!probe.footerRelease) failures.push('footer harness release missing');
if (!probe.heroMark || !probe.heroMark.includes('linear-gradient')) {
  failures.push(`hero brand mark is ${probe.heroMark}`);
}
if (probe.surfaces.sidebar?.background !== 'rgb(250, 248, 240)') {
  failures.push(`sidebar surface is ${probe.surfaces.sidebar?.background}`);
}
if (probe.tokens.rose !== '#b4496a') failures.push(`rose token is ${probe.tokens.rose}`);
if (rail) {
  if (rail.markDisplay === 'none') failures.push('rail toggle hides the Sumika mark on hover');
  if (rail.panelIconDisplay !== 'none') failures.push('rail toggle swaps in the upstream panel glyph on hover');
  if (!rail.markGradient) failures.push('rail mark does not paint the Sumika gradient');
}
if (sessionStatusFailure) failures.push(sessionStatusFailure);

const result = { checked_at: new Date().toISOString(), url: bridge, probe, rail, session_status: sessionStatus,
                 page_errors: pageErrors, console_errors: consoleErrors, failures,
                 status: failures.length ? 'failed' : 'passed' };
console.log(JSON.stringify(result, null, 2));
if (evidencePath) await writeFile(evidencePath, JSON.stringify(result, null, 2) + '\n', 'utf8');
process.exit(failures.length ? 1 : 0);
