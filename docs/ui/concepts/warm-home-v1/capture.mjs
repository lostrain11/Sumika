import assert from 'node:assert/strict';
import { mkdir, readFile, unlink, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { startPreview } from './serve.mjs';
import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';

const directory=dirname(fileURLToPath(import.meta.url));
const require=createRequire(import.meta.url);
const { PNG }=require('../../../../frontend/node_modules/playwright-core/lib/utilsBundle.js');
const output=resolve(directory,'exports');
await mkdir(output,{recursive:true});
await writeFile(resolve(output,'verification.json'),JSON.stringify({status:'running',date:new Date().toISOString()})+'\n');
const preview=await startPreview();
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:900},deviceScaleFactor:1});
const errors=[];
const requests=[];
page.on('pageerror',error=>errors.push(error.message));
page.on('request',request=>requests.push({url:request.url(),method:request.method()}));
const results=[];

async function load(parameters,width,height) {
  await page.setViewportSize({width,height});
  await page.goto(`${preview.url}/?raw=1&${parameters}`,{waitUntil:'networkidle'});
  await page.waitForFunction(()=>document.body.dataset.ready==='true',{},{timeout:45000});
  await page.evaluate(()=>document.fonts.ready);
}

async function screenshot(name) {
  await page.screenshot({path:resolve(output,name),omitBackground:true});
}

async function verifyCanvas(label) {
  const canvas=page.locator('.room canvas');
  const buffer=await canvas.screenshot();
  const png=PNG.sync.read(buffer);
  const colors=new Set();
  let visible=0;
  for(let index=0;index<png.data.length;index+=160) {
    if(png.data[index+3]>0)visible++;
    colors.add(`${png.data[index]>>4},${png.data[index+1]>>4},${png.data[index+2]>>4}`);
  }
  assert.ok(visible>100,`${label}: blank alpha canvas`);
  assert.ok(colors.size>25,`${label}: insufficient rendered detail (${colors.size} colors)`);
  results.push({check:'canvas',label,colors:colors.size,passed:true});
}

async function verifyLayout(label,width) {
  const details=await page.evaluate(()=>({body:document.documentElement.scrollWidth,controls:[...document.querySelectorAll('textarea,.add-module,.topbar,.composer,.pet-composer,.module-library')].map(element=>{const bounds=element.getBoundingClientRect();return {tag:element.className,left:bounds.left,right:bounds.right,overflow:element.scrollWidth-element.clientWidth};})}));
  assert.ok(details.body<=width+1,`${label}: page overflow`);
  for(const control of details.controls) {
    assert.ok(control.left>=-1 && control.right<=width+1,`${label}: ${control.tag} outside viewport`);
    assert.ok(control.overflow<=2,`${label}: ${control.tag} content overflow`);
  }
  results.push({check:'layout',label,passed:true});
}

try {
  for(const theme of ['afternoon','evening','work']) {
    await load(`theme=${theme}`,1440,900);
    await verifyCanvas(`${theme}-client`);
    await verifyLayout(`${theme}-1440`,1440);
    if(theme==='evening') {
      const color=await page.locator('.chat-message p').first().evaluate(element=>getComputedStyle(element).color);
      assert.equal(color,'rgb(237, 233, 228)','night body text must use the light ink token');
      results.push({check:'night-readable-text',passed:true});
    }
    assert.equal(await page.locator('.main-nav button').count(),4);
    assert.equal(await page.locator('.add-module').innerText(),'');
    await screenshot(`${theme}-client-1440.png`);
    await page.setViewportSize({width:1280,height:800});
    await page.waitForTimeout(350);
    await verifyLayout(`${theme}-1280`,1280);
    await screenshot(`${theme}-client-1280.png`);
    await load(`theme=${theme}&view=pet`,480,420);
    await verifyCanvas(`${theme}-pet`);
    await verifyLayout(`${theme}-pet`,480);
    if(theme==='evening') {
      const placeholder=await page.locator('.pet-composer textarea').evaluate(element=>getComputedStyle(element,'::placeholder').color);
      assert.equal(placeholder,'rgb(166, 173, 167)','night pet placeholder must use the light muted token');
      results.push({check:'night-pet-readable-placeholder',passed:true});
    }
    assert.equal(await page.locator('.main-nav,.module,.module-library').count(),0);
    await screenshot(`${theme}-pet.png`);
  }

  await load('theme=work&library=1',1440,900);
  await page.locator('.module-library').waitFor();
  await page.evaluate(()=>document.activeElement?.blur());
  await screenshot('module-library.png');
  await verifyLayout('module-library',1440);
  assert.equal(await page.locator('[data-add="tasks"]').isDisabled(),true);
  const before=await page.locator('.module').count();
  await page.getByRole('button',{name:'添加语音对话',exact:true}).click();
  await page.waitForFunction(()=>document.body.dataset.ready==='true');
  assert.equal(await page.locator('.module').count(),before+1);
  assert.equal(await page.locator('[data-add="voice"]').isDisabled(),true);
  assert.match(await page.locator('[data-module="voice"]').innerText(),/麦克风权限未授予/);
  await page.keyboard.press('Escape');
  await page.waitForFunction(()=>document.body.dataset.ready==='true');
  await page.locator('[data-module="voice"]').hover();
  await page.locator('[data-remove="voice"]').click();
  await page.waitForFunction(()=>document.body.dataset.ready==='true');
  assert.equal(await page.locator('.module').count(),before);
  await page.locator('[data-module="policy"]').hover();
  await page.locator('[data-move="policy"][data-direction="-1"]').click();
  await page.waitForFunction(()=>document.body.dataset.ready==='true');
  assert.equal(await page.locator('.module').first().getAttribute('data-module'),'policy');
  results.push({check:'module-add-remove-reorder-no-authorization',passed:true});

  await page.getByRole('textbox',{name:'聊天消息'}).fill('保留在两个模式之间的草稿');
  await page.locator('.top-actions [data-view="pet"]').click();
  await page.waitForFunction(()=>document.body.dataset.ready==='true');
  assert.equal(await page.getByRole('textbox',{name:'聊天消息'}).inputValue(),'保留在两个模式之间的草稿');
  await page.locator('.pet-shell').hover();
  await page.locator('[data-collapse]').click();
  await page.waitForFunction(()=>document.body.dataset.ready==='true');
  assert.equal(await page.locator('.pet-composer').count(),0);
  await page.locator('.pet-shell').hover();
  await page.locator('[data-collapse]').click();
  await page.waitForFunction(()=>document.body.dataset.ready==='true');
  await page.locator('.pet-shell').hover();
  await page.locator('[data-transparent]').click();
  await page.setViewportSize({width:480,height:420});
  await page.waitForTimeout(300);
  const transparentShot=PNG.sync.read(await page.screenshot({omitBackground:true}));
  let transparentPixels=0;
  for(let offset=3;offset<transparentShot.data.length;offset+=4) {
    if(transparentShot.data[offset]===0)transparentPixels++;
  }
  assert.ok(transparentPixels>transparentShot.width*transparentShot.height*0.2,'transparent pet retains an opaque background');
  results.push({check:'transparent-pet-alpha',passed:true});
  await screenshot('pet-transparent.png');
  await page.locator('.pet-shell').hover();
  await page.locator('.pet-toolbar [data-view="client"]').click();
  await page.waitForFunction(()=>document.body.dataset.ready==='true');
  assert.equal(await page.getByRole('textbox',{name:'聊天消息'}).inputValue(),'保留在两个模式之间的草稿');
  results.push({check:'mode-draft-collapse-transparent',passed:true});
  await load('theme=afternoon',390,844);
  await screenshot('compact-390.png');
  await page.locator('.add-module').scrollIntoViewIfNeeded();
  await verifyLayout('390-fallback',390);

  for(const theme of ['afternoon','evening','work']) {
    await page.setViewportSize({width:1800,height:1250});
    await page.goto(`${preview.url}/board.html?theme=${theme}`,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>[...document.images].every(image=>image.complete && image.naturalWidth>0));
    await screenshot(`${theme}-board.png`);
  }
  const contact=new PNG({width:1800,height:1250*3});
  for(const [index,theme] of ['afternoon','evening','work'].entries()) {
    const board=PNG.sync.read(await readFile(resolve(output,`${theme}-board.png`)));
    PNG.bitblt(board,contact,0,0,board.width,board.height,0,index*1250);
  }
  await writeFile(resolve(output,'all-designs.png'),PNG.sync.write(contact));
  assert.deepEqual(errors,[],'browser console errors');
  assert.ok(requests.every(request=>request.method==='GET'),'unexpected write request');
  assert.ok(requests.every(request=>new URL(request.url).origin===preview.url),'external resource request');
  assert.ok(requests.every(request=>!new URL(request.url).pathname.startsWith('/api/') && !new URL(request.url).pathname.startsWith('/rpc')),'production API request');
  results.push({check:'local-only-no-api-no-browser-errors',passed:true});
  await writeFile(resolve(output,'verification.json'),JSON.stringify({status:'passed',checks:results,date:new Date().toISOString(),scope:'Isolated design preview. Not native Tauri or live runtime acceptance.'},null,2)+'\n');
  await unlink(resolve(output,'failure.png')).catch(error=>{if(error.code!=='ENOENT')throw error;});
  console.log(JSON.stringify({status:'passed',checks:results.length,output},null,2));
} catch(error) {
  await writeFile(resolve(output,'verification.json'),JSON.stringify({status:'failed',checks:results,message:error.message,errors,date:new Date().toISOString()},null,2)+'\n');
  await page.screenshot({path:resolve(output,'failure.png')}).catch(()=>{});
  console.error('Browser errors:',errors);
  throw error;
} finally {
  await browser.close();
  await new Promise(done=>preview.server.close(done));
}
