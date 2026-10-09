/* 验证设置页说明文本走「悬停提示」且不在选项下方常驻。 */
import {createRequire} from 'node:module';
import {mkdir, writeFile} from 'node:fs/promises';
const require = createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/df473e5367fa2b42/bin/node_modules/');
const {chromium} = require('playwright');
const base = process.argv[2] || 'http://127.0.0.1:8765';
const dir = '.sumika-next/evidence/ui-tooltip';
await mkdir(dir, {recursive: true});

const browser = await chromium.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
});
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
const errors = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', e => { if (e.type() === 'error') errors.push(e.text().slice(0, 200)); });
const checks = [];
const record = (name, pass, detail) => checks.push({name, pass, detail});

try {
  await page.goto(base + '/#settings', {waitUntil: 'domcontentloaded'});
  await page.waitForTimeout(3000);
  await page.waitForFunction(() => window.sumikaIconsReady, null, {timeout: 20000}).catch(() => {});

  /* management.js 会重渲染设置区，等它稳定 */
  await page.waitForTimeout(1500);

  /* ---- 1. 说明文本不再常驻在选项下方 ---- */
  const inline = await page.evaluate(() => ({
    smallInSetRow: document.querySelectorAll('#screen-settings .set-row small').length,
    /* 只统计「说明性」的 small；状态文本（role=status，如“当前使用部室午后”）属于必要反馈 */
    explainSmall: [...document.querySelectorAll('#screen-settings .set-row small')]
      .filter(n => n.getAttribute('role') !== 'status')
      .map(n => n.textContent.trim()),
    noteInRow: document.querySelectorAll('#screen-settings .set-row .sumika-form-note').length,
  }));
  record('设置行内无常驻说明文本（状态文本除外）', inline.explainSmall.length === 0,
    JSON.stringify(inline.explainSmall));
  record('设置行内无常驻说明段落', inline.noteInRow === 0, JSON.stringify(inline));

  /* ---- 2. 提示是「悬停触发」，默认不可见 ----
     设置页是按分区切换的（未选中的 .set-group 为 display:none），
     因此必须切到含提示的分区再断言，否则量到的是隐藏容器里的 0×0 元素。 */
  const sectionNames = await page.evaluate(() =>
    [...document.querySelectorAll('#screen-settings .set-nav button')].map(b => b.textContent.trim()));

  /* 找出「哪个分区里有可见触发器」：逐个切换分区测量 */
  let target = null;
  for (const name of sectionNames) {
    const btn = page.locator('#screen-settings .set-nav button', {hasText: name});
    if (!(await btn.count())) continue;
    await btn.first().click();
    await page.waitForTimeout(700);
    const found = await page.evaluate(() => {
      const all = [...document.querySelectorAll('#screen-settings .sumika-field-help')];
      const idx = all.findIndex((n) => { const b = n.getBoundingClientRect(); return b.width > 0 && b.height > 0; });
      return idx;
    });
    if (found >= 0) { target = {name, idx: found}; break; }
  }
  record('存在可交互的悬停提示触发器', !!target,
    target ? `分区「${target.name}」idx=${target.idx}` : `已遍历分区：${sectionNames.join(' / ')}`);

  if (target) {
    const first = page.locator('#screen-settings .sumika-field-help').nth(target.idx);
    const tip = first.locator('.sumika-tooltip');
    const beforeVisible = await tip.isVisible().catch(() => false);
    record('提示默认不可见', beforeVisible === false, `visible=${beforeVisible}`);

    const text = (await tip.textContent().catch(() => '')) || '';
    record('提示内有实际说明文本', text.trim().length > 0, `text="${text.trim().slice(0, 60)}"`);

    /* 悬停后应显示，且不改变布局（绝对定位） */
    const rowBefore = await first.locator('xpath=ancestor::*[contains(@class,"set-row")]').first().boundingBox();
    await first.hover();
    await page.waitForTimeout(400);
    const afterVisible = await tip.isVisible().catch(() => false);
    record('悬停后提示显示', afterVisible === true, `visible=${afterVisible}`);
    const rowAfter = await first.locator('xpath=ancestor::*[contains(@class,"set-row")]').first().boundingBox();
    record('提示不改变行高（绝对定位，不挤压布局）',
      Math.abs(rowBefore.height - rowAfter.height) < 1,
      `before=${rowBefore.height} after=${rowAfter.height}`);

    /* 提示必须落在视口内，不被裁切 */
    const tipBox = await tip.boundingBox();
    const inside = tipBox && tipBox.x >= 0 && tipBox.y >= 0
      && tipBox.x + tipBox.width <= 1440 && tipBox.y + tipBox.height <= 900;
    record('提示完整落在视口内', !!inside, JSON.stringify(tipBox));
    await page.screenshot({path: `${dir}/tooltip-hover.png`});

    /* 点击切到「模型与连接」分区后再验一次（动态渲染区） */
    const navBtn = page.locator('#screen-settings .set-nav button', {hasText: '模型与连接'});
    if (await navBtn.count()) {
      await navBtn.first().click();
      await page.waitForTimeout(1200);
      const n2 = await page.locator('#screen-settings .sumika-field-help').count();
      record('动态渲染分区同样有提示触发器', n2 > 0, `count=${n2}`);
    }
  }
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
