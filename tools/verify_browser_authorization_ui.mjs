import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {chromium}=require(process.argv[2]);
const source=(await readFile('ui/app/management.js','utf8')).replaceAll('\r\n','\n');
// Exercise the shipped dialog and shared helpers without booting unrelated modules.
const helpers=source.slice(source.indexOf('let csrf;'),source.indexOf('async function buildSettings'));
const dialogCode=source.slice(source.indexOf('async function openBrowsers(){'),source.indexOf('\ntry {\n  await window.sumikaSettingsReady;'));
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
 const page=await browser.newPage();
 let mode='reported',state='stale',enabled=true;const writes=[];
 await page.route('**/*',route=>{
  const path=new URL(route.request().url()).pathname;
  if(!path.startsWith('/api/'))return route.fulfill({contentType:'text/html',body:'<html><body></body></html>'});
  const action=path.split('/').pop();
  let data={};
  if(route.request().method()==='POST'){
   if(action==='toggle')enabled=route.request().postDataJSON().enabled;
   writes.push(route.request().postDataJSON());state=action==='bind'?'ready':action==='revoke'?'unauthorized':'unbound';
  }else if(action==='browsers')data={enabled,sites:[{id:'chatgpt.com',url:'https://chatgpt.com',profile:'p',read:true,send:true}]};
  else if(action==='status')data={sites:{'chatgpt.com':{state}}};
  else if(action==='browser-sessions')data={inventory:mode,status:{status:'healthy'},sessions:[{session_id:'s',browser_instance_id:'b',agent_window_id:2}],tabs:{s:[
   {tab_id:1,scope:'agent',window_id:2,url:'https://chatgpt.com/c/one'},
   {tab_id:2,scope:'agent',window_id:2,url:'https://chatgpt.com/c/two'},
   {tab_id:3,scope:'agent',window_id:2,url:'http://chatgpt.com/'},
   {tab_id:4,scope:'agent',window_id:2,url:'https://chatgpt.com:444/'},
   {tab_id:5,scope:'user',window_id:2,url:'https://chatgpt.com/'},
   {tab_id:6,scope:'agent',window_id:9,url:'https://chatgpt.com/'},
  ]}};
  return route.fulfill({json:data});
 });
 await page.goto('http://sumika.test/');
 await page.addScriptTag({content:helpers+'\n'+dialogCode+'\nwindow.openBrowsers=openBrowsers;'});
 page.on('dialog',d=>d.accept());
 await page.evaluate(()=>window.openBrowsers());
 assert.match(await page.locator('dialog').innerText(),/绑定已失效/);
 const select=page.getByLabel('受管页面');
 assert.equal(await select.locator('option').count(),3);
 assert.equal(await page.getByRole('button',{name:'绑定所选页面'}).isDisabled(),true);
 await select.selectOption('1');await page.getByRole('button',{name:'绑定所选页面'}).click();
 await page.getByText('连接：绑定可用 · 登录：未核验',{exact:true}).waitFor();
 assert.equal(writes[0].tab_id,2);
 assert.equal(await page.getByRole('button',{name:'打开本站页面',exact:true}).isDisabled(),true);
 await page.getByLabel('打开站点的受管会话').selectOption('0');
 await page.getByRole('button',{name:'打开本站页面',exact:true}).click();
 await page.getByText('连接：未绑定 · 登录：未核验',{exact:true}).waitFor();
 assert.deepEqual(writes.at(-1),{site:'chatgpt.com',session_id:'s',browser_instance_id:'b',agent_window_id:2,confirmed:true});
 await page.getByRole('button',{name:'保存授权'}).click();
 await page.getByText('连接：未绑定 · 登录：未核验',{exact:true}).waitFor();
 await page.getByRole('button',{name:'撤销授权'}).click();
 await page.getByText('连接：未授权读取 · 登录：未核验',{exact:true}).waitFor();
 mode='unknown';await page.getByRole('button',{name:'刷新状态'}).click();
 await page.getByText('受管页面列表未知，请恢复连接后刷新。',{exact:true}).waitFor();
 assert.match(await page.locator('dialog').innerText(),/活动会话：未知/);
 assert.equal(await page.getByLabel('受管页面').count(),0);
 await page.getByLabel('启用网页咨询',{exact:true}).uncheck();
 await page.getByText('已关闭。保留授权、绑定和历史，不进行新的网页操作。',{exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'打开受管窗口',exact:true}).isDisabled(),true);
 assert.deepEqual(writes.at(-1),{enabled:false,confirmed:true});
 await page.getByRole('button',{name:'刷新状态'}).click();
 assert.equal(await page.getByLabel('启用网页咨询',{exact:true}).isChecked(),false);
 console.log('PASS: stale, explicit tab selection, exact origin/scope/window, refresh after mutations, unknown inventory. No real authorization writes.');
}finally{await browser.close();}

