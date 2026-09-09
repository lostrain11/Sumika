import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
import { startPreview } from './serve.mjs';

const directory = dirname(fileURLToPath(import.meta.url));
const output = resolve(directory,'exports');
const require = createRequire(import.meta.url);
const { PNG } = require('../../../../frontend/node_modules/playwright-core/lib/utilsBundle.js');
await mkdir(output,{recursive:true});
const checks = [], errors = [], requests = [];
const reportPath = resolve(output,'verification.json');
await writeFile(reportPath,JSON.stringify({status:'running',date:new Date().toISOString()})+'\n');
const preview = await startPreview();
let browser;
let page;
const passed = (check,details={}) => checks.push({check,passed:true,...details});
async function ready() {
  await page.waitForFunction(() => document.body.dataset.ready === 'true' || document.body.dataset.error,{},{timeout:60000});
  assert.equal(await page.evaluate(() => document.body.dataset.error),undefined);
  await page.evaluate(() => document.fonts.ready);
}
async function load(parameters='',width=1440,height=900) {
  await page.setViewportSize({width,height});
  await page.goto(`${preview.url}/?${parameters}`,{waitUntil:'networkidle'});
  await ready();
}
async function shot(name) {
  await page.mouse.move(-20,-20);
  await page.evaluate(() => document.activeElement?.blur());
  await page.waitForTimeout(180);
  await page.screenshot({path:resolve(output,`${name}.png`),omitBackground:true});
}
async function layout(label) {
  const result = await page.evaluate(() => {
    const selectors = '.navigation,.main-nav,.nav-actions,.scene-caption,.scene-time,.scene-note,.chat-heading,.composer,.chat-bottom,.wallpaper-controls,.pet-bubble,.category-tabs,.capability,.add-module,dialog[open]';
    const visible = element => { const rect = element.getBoundingClientRect(); return rect.width && rect.height && getComputedStyle(element).opacity !== '0'; };
    return {width:innerWidth,pageWidth:document.documentElement.scrollWidth,items:[...document.querySelectorAll(selectors)].filter(visible).map(element => {
      const rect = element.getBoundingClientRect();
      return {name:element.className || element.tagName,left:rect.left,right:rect.right,overflow:element.scrollWidth-element.clientWidth,vertical:element.classList.contains('capability') ? element.scrollHeight-element.clientHeight : 0};
    })};
  });
  assert.ok(result.pageWidth <= result.width + 1,`${label}: page overflow`);
  for (const item of result.items) {
    assert.ok(item.left >= -1 && item.right <= result.width + 1,`${label}: outside viewport ${item.name}`);
    assert.ok(item.overflow <= 2 && item.vertical <= 2,`${label}: content overflow ${JSON.stringify(item)}`);
  }
  passed('layout',{label});
}
async function canvas(label) {
  await page.waitForTimeout(200);
  const png = PNG.sync.read(await page.locator('#room canvas').screenshot());
  const colors = new Set();
  let visible = 0;
  for (let offset=0;offset<png.data.length;offset+=160) {
    if (png.data[offset+3]) visible++;
    colors.add(`${png.data[offset]>>4},${png.data[offset+1]>>4},${png.data[offset+2]>>4}`);
  }
  assert.ok(visible > 100 && colors.size > 25,`${label}: blank canvas`);
  const result = await page.evaluate(() => {
    const face = window.aPlusPreview.faceBounds();
    const intersections = [];
    for (const element of document.querySelectorAll('.scene-caption,.scene-time,.scene-note,.chat,.wallpaper-controls,.pet-bubble,.pet-controls,.restore-chat')) {
      if (getComputedStyle(element).opacity === '0') continue;
      const rect = element.getBoundingClientRect();
      if (rect.width && rect.height && rect.left < face.right && rect.right > face.left && rect.top < face.bottom && rect.bottom > face.top) intersections.push(element.className);
    }
    return {face,intersections,width:innerWidth,height:innerHeight};
  });
  assert.ok(result.face.left >= 0 && result.face.top >= 0 && result.face.right <= result.width && result.face.bottom <= result.height,`${label}: cropped face`);
  assert.deepEqual(result.intersections,[],`${label}: UI covers face`);
  passed('canvas-and-face',{label,colors:colors.size,face:result.face});
}
async function click(selector) { await page.locator(selector).click(); await page.waitForTimeout(100); }
try {
  browser = await chromium.launch({headless:true});
  page = await browser.newPage({viewport:{width:1440,height:900},deviceScaleFactor:1});
  page.on('pageerror',error => errors.push(error.message));
  page.on('request',request => requests.push({url:request.url(),method:request.method()}));
  await page.addInitScript(() => {
    window.deviceRequests = [];
    for (const method of ['getUserMedia','getDisplayMedia']) {
      if (navigator.mediaDevices) navigator.mediaDevices[method] = () => { window.deviceRequests.push(method); throw new Error('Unexpected device access'); };
    }
  });
  console.log('Client and wallpaper layouts');
  await load();
  assert.equal(await page.locator('.main-nav button').count(),5);
  assert.equal(await page.locator('svg,[data-lucide]').count(),0);
  await layout('client-1440'); await canvas('client-1440'); await shot('companion');
  const firstCanvas = await page.locator('#room canvas').elementHandle();
  await page.getByRole('textbox',{name:'聊天消息'}).fill('收起、切换壁纸后仍保留的草稿');
  await click('[data-chat="close"]');
  assert.equal(await page.locator('.restore-chat').evaluate(element => element === document.activeElement),true);
  assert.equal(await page.locator('#chat').isVisible(),false);
  await layout('client-collapsed'); await canvas('client-collapsed'); await shot('client-collapsed');
  await click('.restore-chat');
  assert.equal(await page.getByRole('textbox',{name:'聊天消息'}).inputValue(),'收起、切换壁纸后仍保留的草稿');
  await click('.nav-actions [data-mode="wallpaper"]');
  assert.equal(await page.locator('.navigation').isVisible(),false);
  assert.equal(await page.locator('#chat').isVisible(),false);
  assert.equal(await page.evaluate(() => document.activeElement.tagName),'BODY');
  await layout('wallpaper'); await canvas('wallpaper'); await shot('wallpaper');
  await click('.wallpaper-controls [data-chat]');
  assert.equal(await page.getByRole('textbox',{name:'聊天消息'}).inputValue(),'收起、切换壁纸后仍保留的草稿');
  await page.getByRole('textbox',{name:'聊天消息'}).fill('');
  await layout('wallpaper-chat'); await canvas('wallpaper-chat'); await shot('wallpaper-chat');
  assert.equal(await firstCanvas.evaluate(element => element === document.querySelector('#room canvas')),true);
  assert.equal(requests.filter(request => request.url.endsWith('.vrm')).length,1);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.navigation').isVisible(),true);
  passed('chat-draft-mode-focus-single-renderer');
  for (const theme of ['sage','blue','berry']) {
    await click(`.chat-bottom [data-theme="${theme}"]`);
    const selected = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--accent'));
    assert.ok(selected.trim().startsWith('#'));
    await shot(`theme-${theme}`);
  }
  await click('.chat-bottom [data-theme="sakura"]');
  assert.equal(requests.filter(request => request.url.endsWith('.vrm')).length,1);
  passed('themes-preserve-renderer');
  await page.setViewportSize({width:1280,height:800});
  await layout('client-1280'); await canvas('client-1280'); await shot('companion-1280');
  await click('.nav-actions [data-mode="wallpaper"]');
  await layout('wallpaper-1280'); await canvas('wallpaper-1280');
  await click('.wallpaper-controls [data-chat]');
  await layout('wallpaper-chat-1280'); await canvas('wallpaper-chat-1280'); await shot('wallpaper-chat-1280');
  await page.setViewportSize({width:1920,height:1080});
  await click('.wallpaper-controls [data-chat]');
  await layout('wallpaper-1920'); await canvas('wallpaper-1920'); await shot('wallpaper-1920');
  await page.keyboard.press('Escape');
  console.log('Capabilities and keyboard behavior');
  await page.setViewportSize({width:1440,height:900});
  await click('[data-page="capabilities"]');
  await layout('capabilities-1440'); await shot('capabilities');
  assert.equal(await page.locator('.add-module').innerText(),'');
  const sizes = await page.locator('.capability,.add-module').evaluateAll(elements => elements.map(element => ({width:element.clientWidth,height:element.clientHeight})));
  assert.ok(sizes.every(size => size.width === sizes[0].width && size.height === sizes[0].height));
  assert.equal(await page.locator('#room canvas').evaluate(element => element.style.visibility),'hidden');
  await page.locator('[data-category="senses"]').focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.locator('[data-category="tools"]').getAttribute('aria-selected'),'true');
  assert.equal(await page.locator('[data-module="translate"]').count(),1);
  await page.keyboard.press('End');
  assert.equal(await page.locator('.capability').count(),0);
  await click('[data-library]'); await click('[data-add="music"]');
  assert.equal(await page.locator('[data-add="music"]').isDisabled(),true);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.querySelector('[data-library]') === document.activeElement);
  assert.match(await page.locator('[data-module="music"]').innerText(),/未启用/);
  await click('[data-remove="music"]');
  assert.equal(await page.locator('.capability').count(),0);
  await click('[data-category="senses"]');
  await click('[data-move="ocr"]');
  assert.equal(await page.locator('.capability').nth(1).getAttribute('data-module'),'ocr');
  await click('[data-config="voice"]');
  assert.match(await page.locator('#dialog-content').innerText(),/麦克风未授权/);
  assert.match(await page.locator('#dialog-content').innerText(),/未配置/);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.querySelector('[data-config="voice"]') === document.activeElement);
  await click('[data-library]');
  await page.keyboard.press('Shift+Tab');
  assert.equal(await page.locator('dialog').evaluate(element => element.contains(document.activeElement)),true);
  await shot('module-library'); await page.keyboard.press('Escape');
  assert.deepEqual(await page.evaluate(() => window.deviceRequests),[]);
  passed('module-states-library-reorder-keyboard-no-devices');
  for (const secondary of ['character','settings','workbench']) {
    await click(`[data-page="${secondary}"]`); await layout(secondary);
  }
  console.log('Pet and narrow layouts');
  await click('[data-page="companion"]');
  await page.getByRole('textbox',{name:'聊天消息'}).fill('桌宠与客户端共用的草稿');
  await click('.nav-actions [data-mode="pet"]');
  await page.setViewportSize({width:480,height:420});
  assert.equal(await page.getByRole('textbox',{name:'聊天消息'}).inputValue(),'桌宠与客户端共用的草稿');
  await page.getByRole('textbox',{name:'聊天消息'}).fill('');
  await page.mouse.move(-20,-20); await page.evaluate(() => document.activeElement?.blur());
  await layout('pet-480'); await canvas('pet-480'); await shot('pet');
  assert.equal(await page.locator('.pet-controls').evaluate(element => getComputedStyle(element).opacity),'0');
  await page.locator('.pet-controls button').first().focus();
  assert.equal(await page.locator('.pet-controls').evaluate(element => getComputedStyle(element).opacity),'1');
  await click('.pet-controls [data-chat]');
  assert.equal(await page.locator('#chat').isVisible(),false);
  await page.locator('.pet-controls button').first().focus();
  await click('.pet-controls [data-chat]');
  await click('[data-transparent]');
  await shot('pet-transparent');
  const alpha = PNG.sync.read(await page.screenshot({omitBackground:true}));
  let clear = 0;
  for (let offset=3;offset<alpha.data.length;offset+=4) if (alpha.data[offset] === 0) clear++;
  assert.ok(clear > alpha.width*alpha.height*.2);
  passed('pet-draft-collapse-focus-alpha',{transparentPixels:clear});
  await page.keyboard.press('Escape');
  await page.setViewportSize({width:390,height:844});
  await layout('client-390'); await canvas('client-390'); await shot('client-390');
  await click('[data-page="capabilities"]'); await layout('capabilities-390'); await shot('capabilities-390');
  await click('[data-library]'); await layout('library-390'); await page.keyboard.press('Escape');
  await click('[data-page="companion"]'); await click('.nav-actions [data-mode="wallpaper"]');
  await layout('wallpaper-390'); await canvas('wallpaper-390');
  await click('.wallpaper-controls [data-chat]'); await layout('wallpaper-chat-390'); await canvas('wallpaper-chat-390');
  await load('page=capabilities');
  assert.equal(await page.locator('#capabilities').isVisible(),true);
  passed('direct-capability-link-loads');
  assert.deepEqual(errors,[]);
  assert.ok(requests.every(request => request.method === 'GET' && new URL(request.url).origin === preview.url),'unexpected remote or mutating request');
  passed('no-runtime-errors-or-external-requests');
  console.log('Exporting comparison boards');
  for (const themes of [false,true]) {
    await page.setViewportSize({width:1920,height:1510});
    await page.goto(`${preview.url}/board.html${themes ? '?themes=1' : ''}`,{waitUntil:'networkidle'});
    await page.waitForFunction(() => document.images.length === 4 && [...document.images].every(image => image.complete && image.naturalWidth > 0));
    await page.evaluate(() => document.fonts.ready);
    await shot(themes ? 'themes' : 'overview');
  }
  passed('comparison-boards');
  await writeFile(reportPath,JSON.stringify({status:'passed',date:new Date().toISOString(),checks,errors,total:checks.length,nativeDesktopIntegration:false},null,2)+'\n');
  console.log(`A+ checks: ${checks.length}/${checks.length} passed`);
} catch (error) {
  await writeFile(reportPath,JSON.stringify({status:'failed',date:new Date().toISOString(),checks,errors,error:error.stack},null,2)+'\n');
  throw error;
} finally {
  await browser?.close();
  await new Promise(done => preview.server.close(done));
}
