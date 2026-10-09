import {spawn} from 'node:child_process';
import {createServer} from 'node:net';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {loadPlaywright} from './lib/playwright.mjs';

const product=resolve(process.argv[2]);
const output=resolve(process.argv[3]);
await mkdir(output,{recursive:false});
const reservation=createServer();
await new Promise(done=>reservation.listen(0,'127.0.0.1',done));
const port=reservation.address().port;
await new Promise(done=>reservation.close(done));
const bridge=spawn(resolve(product,'runtime/python/python.exe'),['-X','utf8','-B','-m','ui.server',
  '--settings',resolve(output,'data/settings.json'),'--capabilities',resolve(output,'data/capabilities.db'),
  '--schedules',resolve(output,'data/schedules'),'--port',String(port)],{cwd:product,windowsHide:true});
let log='';bridge.stdout.on('data',value=>log+=value);bridge.stderr.on('data',value=>log+=value);
const origin=`http://127.0.0.1:${port}`;
let browser,csrf;
const report={passed:false,checks:[],scope:'Actual capability UI and packaged bridge; no models or devices'};
const api=async action=>{
  const response=await fetch(origin+'/api/companion/pet',{method:'POST',
    headers:{'Content-Type':'application/json','X-Sumika-CSRF':csrf,'Origin':origin},body:JSON.stringify({action})});
  const value=await response.json();if(!response.ok)throw Error(value.error);return value;
};
try {
  const deadline=Date.now()+20000;
  while(true) {
    if(bridge.exitCode!==null)throw Error('bridge exited');
    try {const response=await fetch(origin+'/api/manage/session');if(response.ok){csrf=(await response.json()).csrf;break;}}
    catch(error){if(Date.now()>deadline)throw error;}
    if(Date.now()>deadline)throw Error('bridge timeout');
    await new Promise(done=>setTimeout(done,200));
  }
  const {chromium}=loadPlaywright();
  browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  await page.goto(origin);
  await page.locator('#gnav button[data-go="shelf"]').click();
  await page.getByText('桌宠模式',{exact:true}).waitFor();
  const card=page.locator('.cap-card').filter({has:page.locator('h4',{hasText:'桌宠模式'})});
  if(await card.count()!==1)throw Error('pet capability entry is missing or duplicated');
  await card.click();
  const start=page.getByRole('button',{name:'启动桌宠',exact:true});
  await start.waitFor();await start.click();
  await page.waitForFunction(()=>document.querySelector('[data-pet-session] [role="status"]').textContent.includes('正在运行'));
  const state=await api('status');if(!state.alive || !state.pid)throw Error('actual pet not running');
  report.checks.push('single capability entry','real API-owned pet process','launch disabled while alive');
  if(!await start.isDisabled())throw Error('duplicate launch is enabled');
  report.pid=state.pid;
  await page.screenshot({path:resolve(output,'capability.png')});
  await page.getByRole('button',{name:'关闭桌宠',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-pet-session] [role="status"]').textContent.includes('已关闭'));
  if((await api('status')).alive)throw Error('pet survived UI stop');
  report.checks.push('UI stop reclaims pet');report.passed=true;
} finally {
  if(csrf)await api('stop').catch(()=>{});
  if(browser)await browser.close();
  bridge.kill();
  await new Promise(done=>bridge.exitCode!==null?done():bridge.once('exit',done));
  await writeFile(resolve(output,'bridge.log'),log);
  await writeFile(resolve(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
}
