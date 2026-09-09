import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile, unlink } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
import { startPreview } from './serve.mjs';
import { studies } from './studies.js';

const directory=dirname(fileURLToPath(import.meta.url));
const output=resolve(directory,'exports');
const require=createRequire(import.meta.url);
const {PNG}=require('../../../../frontend/node_modules/playwright-core/lib/utilsBundle.js');
await mkdir(output,{recursive:true});
const reportPath=resolve(output,'verification.json');
await writeFile(reportPath,JSON.stringify({status:'running',date:new Date().toISOString()})+'\n');
const preview=await startPreview();
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:900},deviceScaleFactor:1});
const errors=[],requests=[],checks=[];
page.on('pageerror',error=>errors.push(error.message));
page.on('request',request=>requests.push({url:request.url(),method:request.method()}));
await page.addInitScript(()=>{
  window.deviceRequests=[];
  for(const method of ['getUserMedia','getDisplayMedia']) {
    if(navigator.mediaDevices)navigator.mediaDevices[method]=()=>{window.deviceRequests.push(method);throw new Error('Design preview attempted device access');};
  }
});
const passed=(check,details={})=>checks.push({check,passed:true,...details});
async function ready(){
  await page.waitForFunction(()=>document.body.dataset.ready==='true'||document.body.dataset.error,{},{timeout:60000});
  const error=await page.evaluate(()=>document.body.dataset.error);
  assert.equal(error,undefined,'preview rendering error');
  await page.evaluate(()=>document.fonts.ready);
}
async function load(parameters,width=1440,height=900){
  await page.setViewportSize({width,height});
  await page.goto(`${preview.url}/?raw=1&${parameters}`,{waitUntil:'networkidle'});
  await ready();
}
async function shot(name){
  await page.mouse.move(-20,-20);
  await page.evaluate(()=>document.activeElement?.blur());
  await page.waitForTimeout(150);
  await page.screenshot({path:resolve(output,name),omitBackground:true});
}
async function layout(label){
  const result=await page.evaluate(()=>{
    const width=innerWidth;
    const elements=[...document.querySelectorAll('.navigation,.main-nav,.composer,.page-title,.category-tabs,.capability,.add-module,.drawer,.pet-bubble')];
    return {width,body:document.documentElement.scrollWidth,overflow:elements.map(element=>{const bounds=element.getBoundingClientRect();return {name:element.className,left:bounds.left,right:bounds.right,overflow:element.scrollWidth-element.clientWidth,vertical:element.classList.contains('capability')?element.scrollHeight-element.clientHeight:0};})};
  });
  assert.ok(result.body<=result.width+1,`${label}: page horizontal overflow`);
  for(const element of result.overflow){
    assert.ok(element.left>=-1&&element.right<=result.width+1,`${label}: ${element.name} out of bounds`);
    assert.ok(element.overflow<=2,`${label}: ${element.name} horizontal content overflow ${element.overflow}`);
    assert.ok(element.vertical<=2,`${label}: ${element.name} vertical content overflow ${element.vertical}`);
  }
  passed('layout',{label});
}
async function canvas(label){
  const png=PNG.sync.read(await page.locator('.room canvas').screenshot());
  const colors=new Set();
  let visible=0;
  for(let offset=0;offset<png.data.length;offset+=160){if(png.data[offset+3])visible++;colors.add(`${png.data[offset]>>4},${png.data[offset+1]>>4},${png.data[offset+2]>>4}`);}
  assert.ok(visible>100&&colors.size>25,`${label}: blank or uniform canvas`);
  const face=await page.evaluate(()=>{
    const face=window.studyPreview.faceBounds();
    const intersections=[];
    if(face)for(const element of document.querySelectorAll('.scene-title,.scene-clock,.scene-status,.episode-strip,.dialogue,.pet-bubble,.pet-controls,.pet-label,.pet .composer')){
      if(Number(getComputedStyle(element).opacity)===0)continue;
      const bounds=element.getBoundingClientRect();
      if(bounds.left<face.right&&bounds.right>face.left&&bounds.top<face.bottom&&bounds.bottom>face.top)intersections.push(element.className);
    }
    return {face,intersections,width:innerWidth,height:innerHeight};
  });
  assert.ok(face.face,`${label}: face projection unavailable`);
  assert.ok(face.face.left>=0&&face.face.right<=face.width&&face.face.top>=0&&face.face.bottom<=face.height,`${label}: face cropped`);
  assert.deepEqual(face.intersections,[],`${label}: UI covers face`);
  passed('canvas-and-face',{label,colors:colors.size});
}
async function click(selector){await page.locator(selector).click();await ready();}

try {
  for(const id of Object.keys(studies)){
    console.log(`Rendering ${id}: ${studies[id].name}`);
    await load(`study=${id}`);
    assert.equal(await page.locator('.main-nav button').count(),5);
    assert.equal(await page.locator('[data-module]').count(),0);
    await layout(`${id}-companion-1440`);await canvas(`${id}-companion-1440`);
    await shot(`${id}-companion.png`);
    await page.setViewportSize({width:1280,height:800});await page.waitForTimeout(250);
    await layout(`${id}-companion-1280`);await canvas(`${id}-companion-1280`);
    await shot(`${id}-companion-1280.png`);
    await click('[data-page="capabilities"]');
    await layout(`${id}-capabilities-1280`);await shot(`${id}-capabilities-1280.png`);
    await page.setViewportSize({width:1440,height:900});await page.waitForTimeout(100);
    await layout(`${id}-capabilities-1440`);
    assert.equal(await page.locator('.category-tabs [role="tab"]').count(),3);
    assert.equal(await page.locator('.add-module').innerText(),'');
    const dimensions=await page.locator('.capability,.add-module').evaluateAll(elements=>elements.map(element=>({width:element.getBoundingClientRect().width,height:element.getBoundingClientRect().height})));
    assert.ok(dimensions.every(size=>Math.abs(size.width-dimensions[0].width)<1&&size.height===dimensions[0].height));
    await shot(`${id}-capabilities.png`);
    await click('[data-category="tools"]');
    assert.equal(await page.locator('[data-module="translate"]').count(),1);
    assert.equal(await page.locator('[data-module="music"],[data-module="tasks"]').count(),0);
    await click('[data-category="life"]');
    assert.equal(await page.locator('.capability').count(),0);
    await click('[data-library]');
    await click('[data-add="music"]');
    assert.equal(await page.locator('[data-add="music"]').isDisabled(),true);
    await page.keyboard.press('Escape');await ready();
    assert.match(await page.locator('[data-module="music"]').innerText(),/未启用/);
    await page.locator('[data-module="music"]').hover();
    await click('[data-remove="music"]');
    assert.equal(await page.locator('.capability').count(),0);
    passed('categories-add-remove-no-enablement',{label:id});
    await click('[data-page="companion"]');
    await page.getByRole('textbox',{name:'聊天消息'}).fill('两个模式之间保留的草稿');
    await click('.navigation [data-view="pet"]');
    assert.equal(await page.getByRole('textbox',{name:'聊天消息'}).inputValue(),'两个模式之间保留的草稿');
    await page.setViewportSize({width:480,height:420});await page.waitForTimeout(180);
    await page.getByRole('textbox',{name:'聊天消息'}).fill('');
    await layout(`${id}-pet`);await canvas(`${id}-pet`);
    assert.equal(await page.locator('.main-nav,.capability').count(),0);
    await shot(`${id}-pet.png`);
    assert.equal(await page.locator('.pet-controls').evaluate(element=>getComputedStyle(element).opacity),'0');
    await page.locator('.pet-controls button').first().focus();await page.waitForTimeout(180);
    assert.equal(await page.locator('.pet-controls').evaluate(element=>getComputedStyle(element).opacity),'1');
    await click('[data-collapse]');assert.equal(await page.locator('.pet .composer').count(),0);
    await page.locator('.pet').hover();await click('[data-collapse]');
    await page.locator('.pet').hover();await click('[data-transparent]');
    await page.waitForTimeout(200);
    const alpha=PNG.sync.read(await page.screenshot({omitBackground:true}));
    let clear=0;for(let offset=3;offset<alpha.data.length;offset+=4)if(alpha.data[offset]===0)clear++;
    assert.ok(clear>alpha.width*alpha.height*0.2,`${id}: pet alpha must be transparent`);
    await shot(`${id}-pet-transparent.png`);
    await page.getByRole('textbox',{name:'聊天消息'}).fill('切回后仍保留');
    await page.locator('.pet').hover();await click('.pet-controls [data-view="client"]');
    assert.equal(await page.getByRole('textbox',{name:'聊天消息'}).inputValue(),'切回后仍保留');
    assert.deepEqual(await page.evaluate(()=>window.deviceRequests),[]);
    passed('mode-draft-focus-collapse-alpha',{label:id});
  }
  await load('study=b');
  await click('[data-history]');
  assert.match(await page.locator('.history-drawer').innerText(),/阳光刚好落在窗边/);
  await page.keyboard.press('Escape');await ready();
  assert.equal(await page.locator('[data-history]').evaluate(element=>element===document.activeElement),true);
  await click('[data-page="capabilities"]');
  await page.locator('[data-module="ocr"]').hover();
  await click('[data-move="ocr"][data-direction="-1"]');
  assert.equal(await page.locator('.capability').nth(1).getAttribute('data-module'),'ocr');
  await click('[data-config="voice"]');
  assert.match(await page.locator('.configuration').innerText(),/麦克风未授权/);
  await page.keyboard.press('Escape');await ready();
  await click('[data-library]');
  await shot('module-library.png');
  assert.equal(await page.locator('#review').getAttribute('inert'),'');
  await page.locator('.drawer button:not(:disabled)').last().focus();
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('[data-close]').evaluate(element=>element===document.activeElement),true);
  passed('history-focus-reorder-configuration-modal');
  await load('study=c',390,844);
  await layout('compact-client');await canvas('compact-client');await shot('compact-390.png');
  await click('[data-page="capabilities"]');await layout('compact-capabilities');
  await click('[data-category="tools"]');
  await shot('compact-capabilities-390.png');
  for(const id of Object.keys(studies)){
    await page.setViewportSize({width:1920,height:1800});
    await page.goto(`${preview.url}/board.html?study=${id}`,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>document.images.length===3&&[...document.images].every(image=>image.complete&&image.naturalWidth>0));
    await page.evaluate(()=>document.fonts.ready);
    await shot(`${id}-board.png`);
  }
  await page.setViewportSize({width:2400,height:2000});
  await page.goto(`${preview.url}/board.html?overview=1`,{waitUntil:'networkidle'});
  await page.waitForFunction(()=>document.images.length===15&&[...document.images].every(image=>image.complete&&image.naturalWidth>0));
  await shot('overview.png');
  assert.deepEqual(errors,[]);
  assert.ok(requests.every(request=>request.method==='GET'&&new URL(request.url).origin===preview.url),'nonlocal or mutating request');
  assert.ok(requests.every(request=>!/^\/(api|rpc)(\/|$)/.test(new URL(request.url).pathname)),'production API request');
  for(const [path,method,status] of [['/rpc','GET',404],['/.sumika-desktop','GET',404],['/','POST',405]]){
    assert.equal((await fetch(preview.url+path,{method})).status,status);
  }
  passed('local-only-no-api-no-errors');
  for(const id of Object.keys(studies))for(const suffix of ['companion','capabilities','pet','board'])assert.ok((await readFile(resolve(output,`${id}-${suffix}.png`))).length>1000);
  passed('twenty-deliverables-and-overview');
  await writeFile(reportPath,JSON.stringify({status:'passed',date:new Date().toISOString(),checks,scope:'Isolated visual studies only, not native windows, production capabilities or life simulation.'},null,2)+'\n');
  await unlink(resolve(output,'failure.png')).catch(error=>{if(error.code!=='ENOENT')throw error;});
  console.log(JSON.stringify({status:'passed',checks:checks.length,output},null,2));
} catch(error){
  await writeFile(reportPath,JSON.stringify({status:'failed',date:new Date().toISOString(),checks,message:error.message,errors},null,2)+'\n');
  await page.screenshot({path:resolve(output,'failure.png')}).catch(()=>{});
  throw error;
} finally {
  await browser.close();
  await new Promise(done=>preview.server.close(done));
}
