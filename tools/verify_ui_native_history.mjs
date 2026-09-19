// Read existing history only: never send, retry, approve or replay a task.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
const require=createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1280,height:720}});
const checks=[], errors=[];
const directory='.sumika-next/evidence/ui-v2';
await mkdir(directory,{recursive:true});
try {
  await page.goto('http://127.0.0.1:8765/#board');
  await page.locator('#sumika-workbench-frame').waitFor({timeout:120000});
  const frame=page.frames().find(f=>f.url().includes(':5175'));
  await frame.getByText('创建并删除临时测试文件',{exact:true}).click({timeout:30000});
  for(const [width,height] of [[1280,720],[1024,576]]) {
    // 1024x576 is the effective CSS viewport of 1280x720 at 125%.
    // This is a layout check, not a browser zoom or font-rendering certification.
    await page.setViewportSize({width,height});
    for(const name of ['轨迹','对话']) {
      await frame.getByText(name,{exact:true}).click();
      await page.screenshot({path:`${directory}/native-${name}-${width}.png`});
      checks.push(`${width}x${height}:${name}`);
    }
    const permission=frame.getByRole('button',{name:/访问模式，当前/});
    await permission.scrollIntoViewIfNeeded();
    const bounds=await permission.boundingBox();
    if(!bounds || bounds.y<0 || bounds.y+bounds.height>height)throw new Error('permission control clipped');
    await frame.getByRole('button',{name:/^用量 /}).click();
    await page.screenshot({path:`${directory}/native-usage-${width}.png`});
    await page.keyboard.press('Escape');
    checks.push(`${width}x${height}:permission and usage`);
  }
  const summary=frame.getByRole('button',{name:'2 次工具调用',exact:true});
  if(await summary.getAttribute('aria-expanded')!=='true')await summary.click();
  const write=frame.getByRole('button',{name:/^写入.*approval-probe/}).first();
  await write.waitFor();
  await write.click();
  await page.waitForTimeout(250);
  await write.scrollIntoViewIfNeeded();
  const frameLayout=await frame.evaluate(()=>{
    const sidebar=document.querySelector('[class$="_sidebarCol"]');
    const shell=sidebar?.closest('[class$="_frame"]');
    return {sidebarX:sidebar?.getBoundingClientRect().x,scrollLeft:shell?.scrollLeft};
  });
  if(frameLayout.sidebarX!==0 || frameLayout.scrollLeft!==0)throw new Error('tool focus shifted outer frame horizontally');
  checks.push('tool focus preserves sidebar position');
  await page.screenshot({path:`${directory}/native-tools.png`});
  checks.push('existing tool summary expanded and file-write detail opened');
  await frame.getByRole('button',{name:/^Pwsh/}).click();
  await page.screenshot({path:`${directory}/native-terminal.png`});
  checks.push('existing terminal detail opened (no replay)');
} catch(error) {
  errors.push(String(error.message).replace(/(https?:\/\/[^\s?]+)\?[^\s]*/g,'$1?[redacted]'));
} finally {await browser.close();}
const result={checks,errors,status:errors.length?'failed':'passed',limits:'Existing historical session only; no pending approvals exercised. Reduced CSS viewport is not actual browser zoom.'};
await writeFile(`${directory}/native-history-audit.json`,JSON.stringify(result,null,2));
console.log(JSON.stringify(result,null,2));process.exitCode=errors.length?1:0;
