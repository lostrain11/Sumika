import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
const {chromium}=createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/')('playwright');
const {url}=await(await fetch('http://127.0.0.1:8765/api/workbench/embed')).json();
const dir='.sumika-next/sidebar-verification';await mkdir(dir,{recursive:true});
const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const p=await b.newPage();const errors=[];p.on('pageerror',e=>errors.push(e.message));const checks=[];
try {
await p.goto(url);await p.waitForTimeout(5000);
for(const label of ['继续','稍后配置']){const x=p.getByRole('button',{name:label,exact:true});if(await x.isVisible().catch(()=>false))await x.click();}
await p.locator('style[data-sumika-sidebar]').waitFor({state:'attached'});
for(const width of [1280,810]){
 await p.setViewportSize({width,height:900});await p.waitForTimeout(700);
 for(let cycle=0;cycle<3;cycle++){
 const toggle=p.locator('[class*="_logoRow"] button[class*="_toggle"]');
 if((await toggle.getAttribute('aria-label')).includes('打开'))await toggle.click();await p.waitForTimeout(500);
 const geometry=await p.evaluate(()=>{
 const t=document.querySelector('[class*="_logoRow"] button[class*="_toggle"]');const n=document.querySelector('button[class*="_newSession"]');const root=document.querySelector('[data-slot="sidebar"] > div');
 const a=t.getBoundingClientRect(),c=n.getBoundingClientRect(),r=root.getBoundingClientRect();
 return {gap:c.top-r.top,overlap:a.left<c.right&&c.left<a.right&&a.top<c.bottom&&c.top<a.bottom};});
 if(geometry.gap<15||geometry.overlap)throw Error('crowded or overlapping header '+JSON.stringify(geometry));
 await toggle.click();await p.waitForTimeout(500);await p.waitForFunction(()=>document.querySelector('[class*="_logoRow"] button[class*="_toggle"]')?.getAttribute('aria-label')?.includes('打开'));await toggle.hover();
 if(!(await toggle.getAttribute('aria-label')).includes('打开'))throw Error('collapse failed');
 const icon=toggle.locator('[class*="_panelIcon"]');if(!await icon.isVisible())throw Error('expand icon missing');
 await toggle.click();await p.waitForTimeout(500);await p.waitForFunction(()=>document.querySelector('[class*="_logoRow"] button[class*="_toggle"]')?.getAttribute('aria-label')?.includes('收起'));
 if(!(await toggle.getAttribute('aria-label')).includes('收起'))throw Error('expand failed');
 }
 checks.push(`${width}: top spacing, non-overlap and three collapse/expand cycles`);
 await p.screenshot({path:`${dir}/expanded-${width}.png`});
}
await p.locator('[class*="_logoRow"] button[class*="_toggle"]').click();
await p.waitForTimeout(500);
await p.getByRole('button',{name:'添加项目',exact:true}).hover();
await p.locator('[role="tooltip"]').waitFor();
const colors=await p.locator('[role="tooltip"]').evaluate(e=>({fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor}));
function lum(s){return s.match(/[\d.]+/g).slice(0,3).map(Number).map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4}).reduce((a,x,i)=>a+x*[.2126,.7152,.0722][i],0);}
const x=lum(colors.fg),y=lum(colors.bg),contrast=(Math.max(x,y)+.05)/(Math.min(x,y)+.05);
if(contrast<4.5)throw Error('tooltip contrast '+contrast);
checks.push('tooltip contrast '+contrast.toFixed(2));
await p.screenshot({path:`${dir}/collapsed.png`});
if(errors.length)throw Error(errors.join('\n'));
await writeFile(`${dir}/report.json`,JSON.stringify({checks,errors,status:'passed'},null,2));console.log(JSON.stringify({checks,errors,status:'passed'}));
}finally{await b.close();}
