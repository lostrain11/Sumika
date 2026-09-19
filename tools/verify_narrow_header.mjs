import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
const {chromium}=createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/')('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});const page=await browser.newPage();const checks=[];
const dir='.sumika-next/narrow-header';await mkdir(dir,{recursive:true});
try{await page.goto('http://127.0.0.1:8765/#board');await page.locator('#sumika-workbench-frame').waitFor();
for(const width of [360,480,810]){
 await page.setViewportSize({width,height:800});await page.waitForTimeout(500);
 const result=await page.evaluate(()=>{
 const head=document.querySelector('.topbar'),items=[...head.querySelectorAll('.brand,.gnav button,.back-btn')].filter(e=>e.getBoundingClientRect().width);
 return {overflow:document.documentElement.scrollWidth>innerWidth, bad:items.filter(e=>{const r=e.getBoundingClientRect();return getComputedStyle(e).whiteSpace!=='nowrap'||r.left<0||r.right>innerWidth||r.bottom>head.getBoundingClientRect().bottom;}).map(e=>e.textContent)};
 });
 if(result.overflow||result.bad.length)throw Error(JSON.stringify({width,...result}));
 checks.push(`${width}: navigation horizontal and within header`);await page.screenshot({path:`${dir}/${width}.png`});
}
await writeFile(`${dir}/report.json`,JSON.stringify({checks,status:'passed'},null,2));console.log(JSON.stringify({checks,status:'passed'}));
}finally{await browser.close();}
