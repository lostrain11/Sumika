// Exercise delivered UI using synthetic writes; user configuration is read only.
import {createRequire} from 'node:module';
import {mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)(process.argv[2]);
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let settings=await (await page.request.get('http://127.0.0.1:8765/api/manage/settings')).json();
  let registry={revision:'r1',candidates:[],modules:[
    {id:'asr',label:'语音识别',provider:'vosk',enabled:true,options:{}},
    {id:'voice',label:'语音朗读',provider:'windows-sapi',enabled:true,options:{}},
    {id:'microphone',label:'麦克风采集',provider:'sounddevice',enabled:true,options:{}},
  ]};
  const writes=[];
  await page.route('**/api/manage/settings',r=>{
    if(r.request().method()==='POST'){
      const data=r.request().postDataJSON();assert.equal(data.expected_revision,settings.revision);
      for(const [section,values] of Object.entries(data.changes))Object.assign(settings.data[section],values);
      writes.push({kind:'settings',changes:data.changes});settings.revision+='x';
    }
    return r.fulfill({json:settings});
  });
  await page.route('**/api/modules',r=>r.fulfill({json:registry}));
  await page.route('**/api/manage/modules**',r=>{
    if(r.request().method()==='POST'){
      const data=r.request().postDataJSON();assert.equal(data.expected_revision,registry.revision);
      const item=registry.modules.find(m=>m.id===data.id);
      if(r.request().url().endsWith('microphone_authorization')){assert.equal(data.confirmed,true);item.options.user_authorized=data.enabled;}
      else item.enabled=data.enabled;
      registry.revision+='x';writes.push({kind:'module',...data});
    }
    return r.fulfill({json:registry});
  });
  await page.route('**/api/voice/devices',r=>r.fulfill({json:{devices:[{index:7,name:'合成验收麦克风',is_default:true}]}}));
  page.on('dialog',d=>d.accept());
  await page.goto('http://127.0.0.1:8765/#settings');
  await page.locator('.set-nav [data-section="data"]').click();
  assert.equal(await page.locator('.set-nav [data-section="voice"]').count(),0);
  assert.equal(await page.locator('.set-main').getByLabel('自动提取记忆',{exact:true}).count(),0);
  await page.getByRole('button',{name:'记录角色用量说明',exact:true}).focus();
  assert.equal(await page.locator('.set-main .sumika-tooltip').filter({hasText:'不是账户余额'}).isVisible(),true);
  await page.locator('#gnav [data-go="shelf"]').click();
  await page.locator('.cap-card[data-capability-id="speech"]').waitFor();
  assert.equal(await page.locator('.cap-card[data-capability-id="speech"]').count(),1);
  assert.equal(await page.locator('[data-capability-id="voice"],[data-capability-id="asr"],[data-capability-id="microphone"]').count(),0);
  await page.locator('.cap-card[data-capability-id="speech"]').click();
  await page.getByLabel('允许麦克风采集',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('允许麦克风采集',{exact:true}).isChecked(),false);
  await page.getByLabel('输入设备',{exact:true}).selectOption('7');
  await page.getByLabel('允许麦克风采集',{exact:true}).check();
  await page.waitForFunction(()=>document.querySelector('[aria-label="允许麦克风采集"]')?.checked===true && document.querySelector('[aria-label="允许麦克风采集"]')?.disabled===false);
  assert.equal(writes.at(-1).enabled,true);
  assert.equal(await page.getByLabel('输入设备',{exact:true}).inputValue(),'7','permission change must preserve unsaved device');
  const saved=page.waitForResponse(r=>r.url().endsWith('/api/manage/settings')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'保存配置',exact:true}).click();
  await saved;
  await page.locator('[data-extra-action][data-ready="true"]').waitFor();
  await page.waitForFunction(()=>document.querySelector('[aria-label="输入设备"]')?.value==='7');
  assert.equal(settings.data.voice.input_device,7);
  await page.locator('.cap-card[data-capability-id="memory"]').click();
  await page.getByLabel('模型记忆提议（需确认）',{exact:true}).waitFor();
  await page.getByLabel('模型记忆提议（需确认）',{exact:true}).check();
  const memorySaved=page.waitForResponse(r=>r.url().endsWith('/api/manage/settings')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'保存配置',exact:true}).click();
  await memorySaved;
  await page.locator('[data-extra-action][data-ready="true"]').waitFor();
  await page.waitForFunction(()=>document.querySelector('[aria-label="模型记忆提议（需确认）"]')?.checked===true);
  assert.equal(settings.data.memory.model_proposals,true);
  await mkdir('.sumika-next/evidence/capability-settings',{recursive:true});
  await page.screenshot({path:'.sumika-next/evidence/capability-settings/memory-desktop.png'});
  await page.setViewportSize({width:1024,height:900});
  await page.screenshot({path:'.sumika-next/evidence/capability-settings/memory-narrow.png'});
  assert.deepEqual(errors,[]);
  console.log('PASS: unique cards; migrated controls; keyboard tooltip; microphone consent; device and memory save; synthetic writes only');
}finally{await browser.close();}
