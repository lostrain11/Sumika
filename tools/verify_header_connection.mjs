// Exercise product header functions in Edge; no daily service or model calls.
import {createRequire} from 'node:module';
import {readFileSync,readdirSync,existsSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {randomUUID} from 'node:crypto';
import assert from 'node:assert/strict';
const runtime=path.join(process.env.LOCALAPPDATA,'OpenAI/Codex/runtimes/cua_node');
const pkg=readdirSync(runtime).map(n=>path.join(runtime,n,'bin/node_modules/playwright/package.json')).find(existsSync);
const {chromium}=createRequire(pkg)('playwright');
const source=readFileSync('ui/app/bind.js','utf8');
const header=source.slice(source.indexOf('function bindHeader('),source.indexOf('function bindRoster('));
const networkHandlers=source.slice(source.indexOf("window.addEventListener('offline',"),source.indexOf('\nsyncNetworkNotice();',source.indexOf("window.addEventListener('offline',")));
assert.ok(header.includes('async function refreshHeader()'));
const directory=path.resolve('.sumika-next/header-connection-'+randomUUID());
mkdirSync(directory,{recursive:true});
let mode='ok',pending=null,writes=0;
const server=http.createServer((req,res)=>{
  if(req.method!=='GET')writes++;
  if(req.url==='/api/state'){
    const reply=()=>{res.writeHead(mode==='failed'?503:200,{'Content-Type':'application/json'});
      res.end(JSON.stringify({schema_version:1,session:{status:'unknown'},role:{enabled:false}}));};
    if(mode==='held'){pending=reply;return;}
    reply();return;
  }
  res.writeHead(200,{'Content-Type':'text/html;charset=utf-8'});
  res.end(`<span class="model-chip"></span><span class="proto"></span><script>
    const setText=(selector,text)=>document.querySelector(selector).textContent=text;
    async function api(url){const response=await fetch(url);if(!response.ok)throw Error('unavailable');return response.json();}
    ${header}
    window.refreshHeader=refreshHeader;
    const syncNetworkNotice=()=>{};
    ${networkHandlers}
    refreshHeader();
  </script>`);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const context=await browser.newContext();const page=await context.newPage();
const report={passed:false,checks:[]};
const label=async text=>page.waitForFunction(value=>document.querySelector('.proto').textContent===value,text);
try{
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await label('本地服务已连接');report.checks.push('unconfigured role is not a backend outage');
  mode='failed';await page.evaluate(()=>refreshHeader());await label('本地服务连接异常');
  report.checks.push('failed state read is not reported connected');
  mode='ok';await page.evaluate(()=>refreshHeader());await label('本地服务已连接');
  await context.setOffline(true);await label('浏览器离线');
  await context.setOffline(false);await label('本地服务已连接');
  report.checks.push('offline and reconnect refresh connection');
  mode='held';await page.evaluate(()=>{void refreshHeader();});
  await page.waitForFunction(()=>true);
  for(let i=0;i<100&&!pending;i++)await page.waitForTimeout(10);
  assert.ok(pending,'pending read observed');
  mode='failed';await page.evaluate(()=>refreshHeader());await label('本地服务连接异常');
  mode='ok';pending();pending=null;await page.waitForTimeout(100);
  assert.equal(await page.locator('.proto').innerText(),'本地服务连接异常');
  report.checks.push('stale success cannot overwrite newer failure');
  await page.evaluate(()=>refreshHeader());await label('本地服务已连接');
  assert.equal(writes,0);report.writes=writes;
  await page.screenshot({path:path.join(directory,'connected.png')});
  report.passed=true;
}finally{
  await browser.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  writeFileSync(path.join(directory,'report.json'),JSON.stringify(report,null,2));
  console.log(directory,JSON.stringify(report));
}
