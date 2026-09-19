import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)(process.argv[2]);
const browser=await chromium.launch({channel:'msedge',headless:true});
try {
 const page=await browser.newPage();
 await page.goto('http://127.0.0.1:8765/#settings');
 await page.evaluate(()=>{
  window.testSlot=null;window.testRef={current:null};window.changes=[];
  window.__ModuleLoader__={load:({factory})=>{
   const jsx=(tag,props)=>({tag,props});
   const mod=factory(name=>name==='react'?{useState:()=>[false,()=>{}],useRef:()=>window.testRef}:{jsx,jsxs:jsx});
   mod.apply({slots:{inject:(name,gen)=>{[...gen()];},register:(desc,component)=>{if(desc.id==='sumika-prompt-enhancement')window.testSlot=component;}}});
  }};
 });
 await page.addScriptTag({content:await readFile('extensions/ui/sumika-workbench/lib/client.js','utf8')});
 let calls=0;
 await page.route('**/api/manage/auxiliary/enhance',async r=>{calls++;await r.fulfill({json:{status:'reported',changed:true,enhanced:'请润色说明，不改代码。',diff:'-原文\n+改写'}});});
 async function open(){await page.evaluate(()=>{
  window.testProps={input:{phase:'plain',draft:'润色说明，不改代码。',attachmentIds:[],occurrences:[]},sessionId:'fixture',inputActions:{setDraft:text=>window.changes.push(text)}};
  window.testSlot(window.testProps).props.onClick();
 });await page.getByRole('button',{name:'确认替换草稿',exact:true}).waitFor();}
 await open();assert.equal(await page.evaluate(()=>window.changes.length),0);
 await page.getByRole('button',{name:'保留原文并关闭',exact:true}).click();assert.equal(await page.evaluate(()=>window.changes.length),0);
 await open();await page.evaluate(()=>{window.testProps={...window.testProps,sessionId:'different'};window.testSlot(window.testProps);});
 await page.getByRole('button',{name:'确认替换草稿',exact:true}).click();assert.equal(await page.evaluate(()=>window.changes.length),0);
 await page.getByRole('button',{name:'保留原文并关闭',exact:true}).click();
 await open();await page.evaluate(()=>{window.testProps.input.draft='用户的新草稿';window.testSlot(window.testProps);});
 await page.getByRole('button',{name:'确认替换草稿',exact:true}).click();assert.equal(await page.evaluate(()=>window.changes.length),0);
 await page.getByRole('button',{name:'保留原文并关闭',exact:true}).click();
 await open();await page.getByRole('button',{name:'确认替换草稿',exact:true}).click();assert.deepEqual(await page.evaluate(()=>window.changes),['请润色说明，不改代码。']);assert.equal(calls,4);
 console.log('PASS preview close, session change, edited draft, explicit apply; mocked provider, no model calls');
}finally{await browser.close();}
