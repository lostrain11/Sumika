// Non-destructive visual audit: navigation and native sidebar controls only.
import {createRequire} from 'node:module';
import {mkdir, writeFile} from 'node:fs/promises';
const require = createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/');
const {chromium} = require('playwright');
const base = process.argv[2] || 'http://127.0.0.1:8765';
const dir = '.sumika-next/evidence/ui-v2';
await mkdir(dir, {recursive: true});
const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless:true});
const context = await browser.newContext({viewport:{width:1440,height:900}});
const page = await context.newPage();
const errors = [];
const clean = text => String(text).replace(/(https?:\/\/[^\s?]+)\?[^\s]*/g, '$1?[redacted]');
page.on('pageerror', e => errors.push(clean(e.message)));
page.on('console', e => { if (e.type()==='error') errors.push(clean(e.text()).slice(0,300)); });
const results = [];
try {
  await page.goto(base+'/#room', {waitUntil:'domcontentloaded'});
  await page.waitForTimeout(3000);
  for (const size of [{width:1440,height:900},{width:1280,height:720},{width:1160,height:800}]) {
    await page.setViewportSize(size);
    for (const screen of ['room','shelf','settings','board']) {
      await page.locator(`#gnav [data-go="${screen}"]`).click();
      if (screen==='board') {
        await page.locator('#sumika-workbench-frame').waitFor({timeout:120000});
        const frame = page.frames().find(f => f.url().includes(':5175'));
        if (frame) await frame.locator('body').waitFor();
      }
      await page.waitForTimeout(screen==='board'?1500:300);
      const layout=await page.evaluate(() => {
        const visible = [...document.querySelectorAll('.screen.show, .topbar, .screen.show .cap-side, .screen.show .set-side, .screen.show .chat')];
        return visible.map(n=>{const r=n.getBoundingClientRect();return {selector:n.id||n.className,right:r.right,bottom:r.bottom,left:r.left,top:r.top};});
      });
      const clipped = layout.filter(r=>r.right>size.width+1 || r.left < -1 || r.bottom>size.height+1);
      results.push({screen,...size,clipped});
      await page.screenshot({path:`${dir}/${screen}-${size.width}.png`});
    }
  }
  const frame=page.frames().find(f=>f.url().includes(':5175'));
  if (frame) {
    const theme=await frame.evaluate(()=>({palette:document.documentElement.dataset.sumikaPalette,base:getComputedStyle(document.body).getPropertyValue('--dsw-alias-bg-base').trim(),sidebar:getComputedStyle(document.body).getPropertyValue('--dsw-specific-sidebar-fill').trim()}));
    results.push({theme});
    if(theme.palette!=='light'||theme.base!=='#fffdf8') errors.push('Sumika theme overlay did not apply');
    const toggle=frame.locator('[class*="_logoRow"] [class*="_toggle"]').first();
    await toggle.click({timeout:5000});
    await toggle.hover();
    await page.screenshot({path:`${dir}/sidebar-toggled.png`});
    await toggle.click({timeout:5000});
  }
} catch(error) {errors.push(clean(error.message));}
finally {await browser.close();}
const result={results,errors,status:errors.length||results.some(r=>r.clipped?.length)?'failed':'passed'};
await writeFile(`${dir}/audit.json`,JSON.stringify(result,null,2));
console.log(JSON.stringify(result,null,2));
process.exitCode=result.status==='passed'?0:1;
