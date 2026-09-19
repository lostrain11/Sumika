// Browser-network outage only. Does not stop the user's server or send tasks.
import {createRequire} from 'node:module';
import {writeFile,mkdir} from 'node:fs/promises';
const require=createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const context=await browser.newContext({viewport:{width:1280,height:720}});
const page=await context.newPage();
const checks=[],errors=[];
let editor,original;
try {
  await page.goto('http://127.0.0.1:8765/#board');
  await page.locator('#sumika-workbench-frame').waitFor({timeout:120000});
  const frame=page.frames().find(f=>f.url().includes(':5175'));
  editor=frame.locator('[contenteditable="true"]').first();
  await editor.waitFor();original=await editor.innerText();
  if(original.trim())throw new Error('Existing draft found; refusing to replace it');
  await editor.fill('离线验收草稿，不发送');
  const frameElement=await page.locator('#sumika-workbench-frame').elementHandle();
  await context.setOffline(true);
  await page.locator('.sumika-network-notice').waitFor({state:'visible'});
  const blocked=await page.evaluate(async()=>{
    try {await fetch('/api/workbench',{cache:'no-store'});return false;}catch{return true;}
  });
  if(!blocked)throw new Error('HTTP was not actually offline');
  checks.push('browser offline and HTTP blocked');
  await page.locator('#gnav [data-go="room"]').click();
  await page.locator('#gnav [data-go="board"]').click();
  if(!await frameElement.evaluate(el=>el.isConnected))throw new Error('iframe replaced');
  if((await editor.innerText()).trim()!=='离线验收草稿，不发送')throw new Error('draft lost offline');
  checks.push('navigation preserves iframe and unsent draft');
  await context.setOffline(false);
  await page.locator('.sumika-network-notice').waitFor({state:'hidden'});
  if(!await page.evaluate(async()=> (await fetch('/api/workbench',{cache:'no-store'})).ok))throw new Error('HTTP did not recover');
  if((await editor.innerText()).trim()!=='离线验收草稿，不发送')throw new Error('draft changed after recovery');
  checks.push('online HTTP recovery preserves draft');
}catch(error){errors.push(String(error.message).replace(/(https?:\/\/[^\s?]+)\?[^\s]*/g,'$1?[redacted]'));}
finally {
  await context.setOffline(false);
  if(editor && original==='')await editor.fill('').catch(()=>{});
  await browser.close();
}
const result={checks,errors,status:errors.length?'failed':'passed',limits:'Browser network and HTTP only; no server crash, interrupted execution, or pending approval exercised.'};
await mkdir('.sumika-next/evidence/ui-v2',{recursive:true});
await writeFile('.sumika-next/evidence/ui-v2/offline-audit.json',JSON.stringify(result,null,2));
console.log(JSON.stringify(result,null,2));process.exitCode=errors.length?1:0;
