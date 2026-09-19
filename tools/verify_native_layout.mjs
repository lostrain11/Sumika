import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
import path from 'node:path';
const require=createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/');
const {chromium}=require('playwright');
let input='';for await(const chunk of process.stdin)input+=chunk;
const config=JSON.parse(input);
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1280,height:720}}),errors=[],checks=[];
page.on('pageerror',e=>errors.push(e.message.replace(/\?token=[^\s]+/g,'?[redacted]')));
try{
 await page.goto(config.url);
 const consent=page.getByRole('button',{name:'继续',exact:true});
 await consent.waitFor({timeout:20000});await consent.click();
 const later=page.getByRole('button',{name:'稍后配置',exact:true});
 await later.waitFor({timeout:20000});await later.click();
 checks.push('native startup overlays retained and usable without credentials');
 await page.locator('[data-layout-probe]').waitFor({timeout:30000});
 checks.push('custom root loaded with native slots');
 const transport=await page.evaluate(async endpoint=>{
   const {bridgeFetch}=await import(endpoint+'/app/bridge-client.js');
   const response=await fetch(endpoint+'/api/manage/session');
   if(!response.ok)throw Error('native origin cannot establish bridge session');
   const {csrf}=await response.json();
   const headers={'Content-Type':'application/json'};
   const payload=JSON.stringify({action:'dismiss',id:'nonexistent-isolated-fixture'});
   const denied=await fetch(endpoint+'/api/manage/task-draft',{method:'POST',headers,body:payload});
   const accepted=await fetch(endpoint+'/api/manage/task-draft',{method:'POST',headers:{...headers,'X-Sumika-CSRF':csrf},body:payload});
   const shared=await bridgeFetch('/api/manage/task-draft',{method:'POST',headers,body:payload});
   if(shared.status!==200)throw Error('shared page transport failed');
   let blocked=false;
   try { await bridgeFetch('http://127.0.0.1:1/api/manage/session'); }
   catch { blocked=true; }
   if(!blocked)throw Error('shared transport accepted a foreign endpoint');
   return {denied:denied.status,accepted:accepted.status};
 },config.bridge);
 if(transport.denied!==403||transport.accepted!==200)throw Error('native bridge authorization failed');
 checks.push('real native-origin CORS preflight and scoped-token write; missing token denied');
 checks.push('existing page transport works from native origin and refuses foreign targets');
 const editor=page.locator('[contenteditable=true]').last();
 await editor.waitFor();await editor.fill('UNSENT_LAYOUT_PROBE');
 for(const screen of ['room','shelf','settings','board'])await page.locator(`[data-probe-page=${screen}]`).click();
 if(await editor.innerText()!=='UNSENT_LAYOUT_PROBE')throw new Error('draft lost across navigation');
 checks.push('four pages preserve mounted native composer and draft');
 await editor.fill('');
 await page.screenshot({path:path.join(config.directory,'layout.png')});
}catch(e){errors.push(e.message.replace(/\?token=[^\s]+/g,'?[redacted]'));
 await page.screenshot({path:path.join(config.directory,'failure.png')});
 await writeFile(path.join(config.directory,'failure.txt'),await page.locator('body').innerText());
}
finally{await browser.close();}
const report={checks,errors,limits:'Root and draft feasibility only; no live approval, full component acceptance or production migration.'};
await writeFile(path.join(config.directory,'browser.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify(report));process.exitCode=errors.length?1:0;
