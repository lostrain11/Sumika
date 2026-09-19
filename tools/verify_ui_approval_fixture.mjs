// Render the installed native approval component with an isolated pending object.
// No approval/request RPC is issued and no host authority is created.
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
const require=createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/');
const {chromium}=require('playwright');
const source=await readFile('runtime/dsh/node_modules/.pnpm/@deepseek-ai+dsh-client-ui-_0042ab2fbacdc55b3b6e01cd122ef81e/node_modules/@deepseek-ai/dsh-client-ui-approval/lib/client.js','utf8');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1024,height:576}});
const checks=[],errors=[];
let original;
try{
  await page.route('**/plugins/**',async route=>{
    if(route.request().resourceType()!=='script')return route.continue();
    let response;
    try{response=await route.fetch();}catch{await route.abort().catch(()=>{});return;}
    let body=await response.text();
    body=body.replace("const jsx = require('react/jsx-runtime');","window.__approvalFixtureRequire = require; const jsx = require('react/jsx-runtime');");
    await route.fulfill({response,body});
  });
  await page.goto('http://127.0.0.1:8765/#board');
  await page.locator('iframe').waitFor({timeout:120000});
  const frame=await (await page.locator('iframe').elementHandle()).contentFrame();
  await frame.waitForURL(url=>url.port==='5175');
  await frame.waitForFunction(()=>typeof window.__approvalFixtureRequire==='function');
  await frame.locator('html[data-sumika-palette]').waitFor();
  await page.locator('#gnav [data-go="settings"]').click();
  await page.locator('[data-section="appearance"]').click();
  original=await page.getByLabel('主题配色').inputValue();
  await page.locator('#gnav [data-go="board"]').click();
  await frame.evaluate(source=>{
    const require=window.__approvalFixtureRequire;
    let registration,Panel,dict;
    new Function('window',source)({__ModuleLoader__:{load:value=>registration=value}});
    registration.factory(require).apply({
      effect:fn=>fn(),locale:{register:(ns,values)=>{dict=values.zh;return ()=>{};}},
      uiSession:{registerPendingInteraction:()=>()=>()=>{}},
      slots:{inject:(_,fn)=>fn(),register:(_,component)=>{Panel=component;return ()=>{};}},
      remote:{$on:()=>{}},
    });
    const React=require('react'),ReactDOM=require('react-dom/client');
    const container=document.createElement('div');
    container.id='approval-fixture';
    container.style.cssText='position:fixed;inset:0;z-index:99999;overflow:auto;background:var(--dsw-alias-bg-base);padding-top:30px;--dsh-composer-text-max-height:200px;--dsh-chat-content-width:680px;--dsh-composer-side-clearance:0px';
    document.body.append(container);
    const root=ReactDOM.createRoot(container);
    window.__fixtureDecisions=[];
    window.__renderApproval=(failure=false)=>root.render(React.createElement(Panel,{
      matched:{key:crypto.randomUUID(),toolName:'fixture-only',callId:'fixture',reason:'隔离审批显示验收：不会执行任何工具。',answer:async decision=>{
        if(failure)throw new Error('fixture failure');window.__fixtureDecisions.push(decision);
      }},
      renderSlot:()=>React.createElement('pre',null,'只读测试详情\n'.repeat(70)),
      t:key=>dict[key]||key,
    }));
    window.__renderApproval();
  },source);
  const fixture=frame.locator('#approval-fixture');
  const buttons=fixture.getByRole('button');await buttons.first().waitFor();
  if(await buttons.count()!==2)throw new Error('Expected native reject and allow-once controls');
  for(const button of await buttons.all()){
    const box=await button.boundingBox();if(!box||box.y+box.height>576)throw new Error('approval action clipped');
  }
  const scroll=fixture.locator('[data-approval-scroll]');
  if(!await scroll.evaluate(el=>el.scrollHeight>el.clientHeight))throw new Error('long detail is not scrollable');
  checks.push('native approval actions visible with scrollable long detail');
  await buttons.first().click();
  await frame.waitForFunction(()=>window.__fixtureDecisions[0]==='rejected');
  await frame.evaluate(()=>window.__renderApproval());await buttons.last().click();
  await frame.waitForFunction(()=>window.__fixtureDecisions[1]==='allowed-once');
  checks.push('reject and allow-once reach fixture only');
  await frame.evaluate(()=>window.__renderApproval(true));await buttons.last().click();
  await frame.waitForFunction(()=>[...document.querySelectorAll('#approval-fixture button')].every(el=>!el.disabled));
  checks.push('failed decision restores available actions');
  await page.screenshot({path:'.sumika-next/evidence/ui-v2/approval-fixture.png'});
  for(const theme of ['light','dark','light']){
    await page.locator('#gnav [data-go="settings"]').click();
    await page.locator('[data-section="appearance"]').click();
    await page.getByLabel('主题配色').selectOption(theme);
    await frame.waitForFunction(theme=>document.documentElement.dataset.sumikaPalette===theme,theme);
    await page.locator('#gnav [data-go="board"]').click();
    const colors=await frame.evaluate(()=>{
      const values=el=>({tag:el.tagName,id:el.id,cls:el.className,bg:getComputedStyle(el).backgroundColor,token:getComputedStyle(el).getPropertyValue('--dsw-alias-bg-base')});
      return {root:values(document.documentElement),body:values(document.body),fixture:values(document.querySelector('#approval-fixture')),card:values(document.querySelector('[data-approval-key]')),roots:[...document.body.children].slice(0,6).map(values)};
    });
    const expected=theme==='light'?'rgb(255, 253, 248)':'rgb(21, 21, 23)';
    if(colors.fixture.bg!==expected)throw new Error(`${theme} palette stale: ${colors.fixture.bg}`);
    const contrast=await buttons.first().evaluate(el=>{
      const s=getComputedStyle(el);
      const lum=value=>{
        const rgb=value.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4;});
        return rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722;
      };
      const a=lum(s.color),b=lum(s.backgroundColor);
      return (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
    });
    if(contrast<4.5)throw new Error(`${theme} reject contrast below 4.5: ${contrast}`);
    checks.push(`${theme} computed background and reject text contrast pass`);
    await page.screenshot({path:`.sumika-next/evidence/ui-v2/approval-${theme}.png`});
  }
}catch(error){errors.push(String(error.message).replace(/(https?:\/\/[^\s?]+)\?[^\s]*/g,'$1?[redacted]'));}
finally{
  if(original){
    await page.locator('#gnav [data-go="settings"]').click().catch(()=>{});
    await page.locator('[data-section="appearance"]').click().catch(()=>{});
    await page.getByLabel('主题配色').selectOption(original).catch(()=>{});
    await page.waitForTimeout(600);
  }
  await browser.close();
}
const result={checks,errors,status:errors.length?'failed':'passed',limits:'Isolated native component only; no real pending host approval or authorization protocol was tested.'};
await writeFile('.sumika-next/evidence/ui-v2/approval-fixture.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));process.exitCode=errors.length?1:0;
