// Non-destructive visual audit: navigation and native sidebar controls only.
import {loadPlaywright} from './lib/playwright.mjs';
import {mkdir, writeFile} from 'node:fs/promises';
import {findNativeFrame, waitForNativeFrame} from './lib/native-frame.mjs';
const {chromium} = loadPlaywright();
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
        const frame = findNativeFrame(page, base);
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
  // 用 waitForNativeFrame 而非 if (frame)：取不到时必须失败，
  // 否则主题叠加层与侧栏开关的断言会被静默跳过，把失败伪装成通过。
  const frame=await waitForNativeFrame(page, base, 15000);
  // DSH 0.2 adds a preview notice before the configuration dialog.
  if (await frame.getByText('预览版说明', {exact:true}).count()) {
    await frame.getByRole('button', {name:'继续', exact:true}).click();
  }
  for (const label of ['稍后配置', 'Later', 'Skip']) {
    const button = frame.getByRole('button', {name: label, exact:true});
    if (await button.count()) { await button.first().click(); break; }
  }
  const theme=await frame.evaluate(()=>({palette:document.documentElement.dataset.sumikaPalette,base:getComputedStyle(document.body).getPropertyValue('--dsw-alias-bg-base').trim(),sidebar:getComputedStyle(document.body).getPropertyValue('--dsw-specific-sidebar-fill').trim()}));
  // 这里断言的是「外壳与工作台配色一致」这个真实不变量，而不是写死浅色。
  // 主题偏好属于用户数据，light / dark 都合法；写死浅色会在用户选了暗色时
  // 把正确状态报成缺陷。
  const shellTheme=await page.evaluate(()=>document.documentElement.dataset.theme);
  const expectedBase={light:'#fffdf8',dark:'#151517'}[shellTheme];
  results.push({theme,shellTheme,expectedBase});
  if(theme.palette!==shellTheme) errors.push(`工作台配色 ${theme.palette} 与外壳 ${shellTheme} 不一致`);
  else if(expectedBase&&theme.base!==expectedBase) errors.push(`${shellTheme} 主题的工作台底色为 ${theme.base}，期望 ${expectedBase}`);
  // DSH 自己的首次配置弹窗在全新浏览器上下文里会盖住工作台：它带一层拦截指针事件的
  // 遮罩，会让下面点侧栏开关的动作永远等不到可点击状态（表现为超时，而不是报出遮罩）。
  // 用弹窗自己的「稍后配置」关掉它再继续。
  for (const label of ['稍后配置','Later','Skip']) {
    const button=frame.getByRole('button',{name:label});
    if (await button.count().catch(()=>0)) {
      await button.first().click().catch(()=>{});
      await page.waitForTimeout(800);
      break;
    }
  }
  const toggle=frame.locator('[class*="_logoRow"] [class*="_toggle"]').first();
  await toggle.click({timeout:5000});
  await toggle.hover();
  await page.screenshot({path:`${dir}/sidebar-toggled.png`});
  await toggle.click({timeout:5000});
} catch(error) {errors.push(clean(error.message));}
finally {await browser.close();}
const result={results,errors,status:errors.length||results.some(r=>r.clipped?.length)?'failed':'passed'};
await writeFile(`${dir}/audit.json`,JSON.stringify(result,null,2));
console.log(JSON.stringify(result,null,2));
process.exitCode=result.status==='passed'?0:1;
