import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1280,height:720}});
const checks=[],errors=[];
let original;
try{
  await page.goto('http://127.0.0.1:8765/#board');
  await page.locator('iframe').waitFor({timeout:120000});
  let frame=page.frames().find(f=>f.url().includes(':5175'));
  await frame.locator('html[data-sumika-palette]').waitFor();
  await page.locator('[data-go="settings"]').click();
  await page.locator('[data-section="appearance"]').click();
  const select=page.getByLabel('主题配色');original=await select.inputValue();
  await select.selectOption('dark');
  await frame.waitForFunction(()=>document.documentElement.dataset.sumikaPalette==='dark');
  if(await page.locator('html').getAttribute('data-theme')!=='dark')throw new Error('shell not dark');
  await page.screenshot({path:'.sumika-next/evidence/ui-v2/settings-dark.png'});
  checks.push('dark shell and native workbench synchronized');
  for(const screen of ['room','shelf','board']){
    await page.locator(`#gnav [data-go="${screen}"]`).click();
    await page.screenshot({path:`.sumika-next/evidence/ui-v2/${screen}-dark.png`});
  }
  await page.locator('#gnav [data-go="settings"]').click();
  await page.reload();
  await page.locator('[data-section="appearance"]').click();
  if(await page.getByLabel('主题配色').inputValue()!=='dark')throw new Error('theme lost on reload');
  checks.push('theme survives reload');
  await page.emulateMedia({colorScheme:'dark'});
  await page.getByLabel('主题配色').selectOption('system');
  await page.waitForFunction(()=>document.documentElement.dataset.theme==='dark');
  await page.emulateMedia({colorScheme:'light'});
  await page.waitForFunction(()=>document.documentElement.dataset.theme==='light');
  checks.push('system preference responds to OS scheme');
}catch(error){errors.push(error.message);}
finally{
  if(original){
    await page.getByLabel('主题配色').selectOption(original).catch(()=>{});
    await page.locator('[data-go="board"]').click().catch(()=>{});
    await page.waitForTimeout(600);
  }
  await browser.close();
}
const result={checks,errors,status:errors.length?'failed':'passed'};
await writeFile('.sumika-next/evidence/ui-v2/theme-audit.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));process.exitCode=errors.length?1:0;
