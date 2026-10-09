/* 版C 名册条与图标：断言「默认收起 / 悬停停留后上浮 / 图标确实渲染」。 */
import {createRequire} from 'node:module';
import {mkdir, writeFile} from 'node:fs/promises';
const require = createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/df473e5367fa2b42/bin/node_modules/');
const {chromium} = require('playwright');
const base = process.argv[2] || 'http://127.0.0.1:8765';
const dir = '.sumika-next/evidence/ui-roster';
await mkdir(dir, {recursive: true});

const browser = await chromium.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
});
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
const errors = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', e => { if (e.type() === 'error') errors.push(e.text().slice(0, 300)); });

const checks = [];
const record = (name, pass, detail) => checks.push({name, pass, detail});

try {
  await page.goto(base + '/#room', {waitUntil: 'domcontentloaded'});
  await page.waitForTimeout(3000);
  /* 图标是异步拉取的（icons.js 需先 fetch 全部 SVG 再水合），必须等到水合完成再断言，
     否则会在占位 <i data-icon> 还没替换时误判失败。 */
  await page.waitForFunction(
    () => window.sumikaIconsReady && document.querySelectorAll('[data-icon]').length === 0,
    null, {timeout: 20000},
  ).catch(() => {});

  /* ---- 1. 图标真的渲染成 <svg>，而不是残留 <i data-icon> 占位 ---- */
  const iconState = await page.evaluate(() => ({
    leftover: document.querySelectorAll('[data-icon]').length,
    svgs: document.querySelectorAll('.gnav button svg').length,
    navLabels: [...document.querySelectorAll('.gnav button')].map(b => b.textContent.trim()),
    // 图标必须继承 currentColor，才可能跟随主题
    stroke: document.querySelector('.gnav button svg')?.getAttribute('stroke') || null,
  }));
  record('顶栏 4 个导航图标渲染为 svg', iconState.svgs === 4, JSON.stringify(iconState));
  record('无 <i data-icon> 占位残留', iconState.leftover === 0, `leftover=${iconState.leftover}`);
  record('图标使用 currentColor 描边', iconState.stroke === 'currentColor', `stroke=${iconState.stroke}`);

  /* ---- 2. 名册默认收起：面板不可见，且不影响舞台尺寸 ---- */
  const collapsed = await page.evaluate(() => {
    const dock = document.getElementById('rosterDock');
    const panel = document.getElementById('rosterPanel');
    const stage = document.querySelector('.stage');
    return {
      hasDock: !!dock,
      open: dock.classList.contains('open'),
      hoverOpen: dock.classList.contains('hover-open'),
      panelVisible: !!panel && panel.getBoundingClientRect().height > 0,
      stageHeight: stage.getBoundingClientRect().height,
    };
  });
  record('名册条存在', collapsed.hasDock, JSON.stringify(collapsed));
  record('初始未展开（无 open / hover-open）', !collapsed.open && !collapsed.hoverOpen, JSON.stringify(collapsed));
  record('初始面板不可见', !collapsed.panelVisible, `panelVisible=${collapsed.panelVisible}`);
  await page.screenshot({path: `${dir}/roster-collapsed.png`});

  /* ---- 3. 悬停「停留一段时间」后上浮：延迟前不展开，延迟后展开 ---- */
  const bar = page.locator('#rosterBar');
  await bar.hover();
  await page.waitForTimeout(120);            // 明显短于 420ms
  const during = await page.evaluate(() => document.getElementById('rosterDock').classList.contains('hover-open'));
  record('悬停 120ms 时仍未展开（有延迟）', during === false, `hoverOpen=${during}`);

  await page.waitForTimeout(700);            // 越过 420ms
  const after = await page.evaluate(() => {
    const dock = document.getElementById('rosterDock');
    const panel = document.getElementById('rosterPanel');
    const stage = document.querySelector('.stage');
    return {
      hoverOpen: dock.classList.contains('hover-open'),
      panelHeight: panel.getBoundingClientRect().height,
      members: document.querySelectorAll('.roster-list .member').length,
      stageHeight: stage.getBoundingClientRect().height,
    };
  });
  record('停留后自动展开', after.hoverOpen === true, JSON.stringify(after));
  record('展开层确实可见', after.panelHeight > 0, `panelHeight=${after.panelHeight}`);
  record('名册卡片已渲染', after.members > 0, `members=${after.members}`);
  /* 关键：上浮是绝对定位，不得推挤舞台高度 */
  record('展开不改变舞台高度', Math.abs(after.stageHeight - collapsed.stageHeight) < 1,
    `collapsed=${collapsed.stageHeight} open=${after.stageHeight}`);
  await page.screenshot({path: `${dir}/roster-hover-open.png`});

  /* ---- 4. 移开后收起 ----
     名册条贴底，且展开层向上浮出，因此 dock 的命中区域 = 收起条 ∪ 浮出面板。
     必须移到这两者之外才算「移开」，否则仍算悬停（正确行为，非缺陷）。
     先取展开态的整体命中区，再选一个明确落在其上方舞台的点。 */
  const openBox = await page.evaluate(() => {
    const d = document.getElementById('rosterDock').getBoundingClientRect();
    const p = document.getElementById('rosterPanel').getBoundingClientRect();
    return {top: Math.min(d.top, p.top)};            // 浮出面板顶边
  });
  const awayY = Math.max(10, Math.round(openBox.top) - 60);   // 舞台区域内，位于展开层之上
  await page.mouse.move(60, awayY);
  await page.waitForTimeout(400);
  const closed = await page.evaluate((yy) => {
    const dock = document.getElementById('rosterDock');
    const hit = document.elementFromPoint(60, yy);
    return {
      hoverOpen: dock.classList.contains('hover-open'),
      panelVisible: document.getElementById('rosterPanel').getBoundingClientRect().height > 0,
      stillOnDock: !!(hit && hit.closest('#rosterDock')),      // 断言测试点确实在 dock 之外
      y: yy,
    };
  }, awayY);
  record('测试点确实落在名册条之外', closed.stillOnDock === false, JSON.stringify(closed));
  record('移开后收回', !closed.hoverOpen && !closed.panelVisible, JSON.stringify(closed));

  /* ---- 5. 触屏/键盘兜底：点击标题条切换 ---- */
  await bar.click();
  await page.waitForTimeout(200);
  const clicked = await page.evaluate(() => ({
    open: document.getElementById('rosterDock').classList.contains('open'),
    aria: document.getElementById('rosterBar').getAttribute('aria-expanded'),
  }));
  record('点击标题条可展开（无悬停设备兜底）', clicked.open === true, JSON.stringify(clicked));
  await bar.click();
  await page.waitForTimeout(200);

  /* ---- 6. 冗余入口已移除：顶栏不应再出现「回活动室」 ---- */
  const redundant = await page.evaluate(() => ({
    backBtn: document.querySelectorAll('#backBtn, .back-btn').length,
    navCount: document.querySelectorAll('#gnav button').length,
  }));
  record('顶栏无冗余「回活动室」入口', redundant.backBtn === 0, JSON.stringify(redundant));
  record('全局导航恰好 4 项（单一入口）', redundant.navCount === 4, `navCount=${redundant.navCount}`);

  /* ---- 7. 桌宠在活动室隐藏、在工作台显示（用户确认要求） ---- */
  const petRoom = await page.evaluate(() => {
    const p = document.getElementById('deskpet');
    return p ? getComputedStyle(p).display : 'missing';
  });
  record('活动室（陪伴页）桌宠隐藏', petRoom === 'none', `display=${petRoom}`);

  await page.locator('#gnav [data-go="board"]').click();
  await page.locator('#sumika-workbench-frame').waitFor({timeout: 120000});
  await page.waitForTimeout(1500);
  const petBoard = await page.evaluate(() => {
    const p = document.getElementById('deskpet');
    return p ? getComputedStyle(p).display : 'missing';
  });
  record('工作台桌宠显示（跨页常驻）', petBoard !== 'none' && petBoard !== 'missing', `display=${petBoard}`);
  await page.screenshot({path: `${dir}/deskpet-on-board.png`});
} catch (error) {
  errors.push(error.message);
} finally {
  await browser.close();
}

const failed = checks.filter(c => !c.pass);
const result = {checks, errors, status: failed.length || errors.length ? 'failed' : 'passed'};
await writeFile(`${dir}/audit.json`, JSON.stringify(result, null, 2));
for (const c of checks) console.log(`${c.pass ? 'PASS' : 'FAIL'}  ${c.name}  ${c.pass ? '' : '→ ' + c.detail}`);
if (errors.length) console.log('ERRORS:\n' + errors.join('\n'));
console.log(`\n${result.status.toUpperCase()}  ${checks.length - failed.length}/${checks.length} passed`);
process.exitCode = result.status === 'passed' ? 0 : 1;
