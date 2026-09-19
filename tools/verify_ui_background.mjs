import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage();const checks=[],errors=[];
try{
  await page.goto('http://127.0.0.1:8765/#settings');
  await page.locator('[data-section="appearance"]').click();
  const encoded=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=16;canvas.height=16;const ctx=canvas.getContext('2d');ctx.fillStyle='#ccddcc';ctx.fillRect(0,0,16,16);return canvas.toDataURL().split(',')[1];});
  const file={name:'background.png',mimeType:'image/png',buffer:Buffer.from(encoded,'base64')};
  await page.getByLabel('选择本地背景图片').setInputFiles(file);
  await page.getByText('已保存本地背景',{exact:true}).waitFor();checks.push('local background saved');
  await page.reload();
  await page.locator('[data-section="appearance"]').click();
  await page.getByText('当前使用本地背景',{exact:true}).waitFor();
  if(await page.locator('#screen-room .stage').getAttribute('data-custom-background')!=='true')throw new Error('background not restored');
  checks.push('background survives reload');
  await page.getByLabel('选择本地背景图片').setInputFiles({name:'invalid.png',mimeType:'image/png',buffer:Buffer.from('not an image')});
  await page.getByText(/背景未更改/).waitFor();
  if(await page.locator('#screen-room .stage').getAttribute('data-custom-background')!=='true')throw new Error('invalid file erased background');
  checks.push('invalid image preserves saved background');
  await page.getByRole('button',{name:'恢复部室午后'}).click();
  await page.getByText('已恢复默认背景',{exact:true}).waitFor();
  await page.reload();
  await page.locator('[data-section="appearance"]').click();
  await page.getByText('当前使用部室午后',{exact:true}).waitFor();checks.push('default restore persists');
}catch(error){errors.push(error.message);}
finally{await browser.close();}
const result={checks,errors,status:errors.length?'failed':'passed'};
await writeFile('.sumika-next/evidence/ui-v2/background-audit.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));process.exitCode=errors.length?1:0;
