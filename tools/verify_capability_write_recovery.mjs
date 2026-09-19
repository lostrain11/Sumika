// Actual capability form functions with shell bootstrap omitted; local API fixture only.
import {createRequire} from 'node:module';
import {readFileSync,readdirSync,existsSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {randomUUID} from 'node:crypto';
import assert from 'node:assert/strict';
const root=process.cwd(),assets=path.join(root,'ui/app');
const runtime=path.join(process.env.LOCALAPPDATA,'OpenAI/Codex/runtimes/cua_node');
const pkg=readdirSync(runtime).map(n=>path.join(runtime,n,'bin/node_modules/playwright/package.json')).find(existsSync);
const {chromium}=createRequire(pkg)('playwright');
const base=path.join(root,'.sumika-next','capability-recovery-'+randomUUID());mkdirSync(base,{recursive:true});
let failRead=false,breakAfterWrite=false,writes=0;
const registry={revision:'one',modules:['voice','asr','microphone'].map(id=>({id,enabled:true,options:{user_authorized:true}}))};
const settings={revision:'one',data:{voice:{enabled:true,input_device:null,tts_voice:'fixture'}}};
const server=http.createServer(async(req,res)=>{
  const json=(data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
  if(req.url.startsWith('/api/')){
    if(req.url==='/api/manage/settings'){
      if(req.method==='POST'){
        let body='';for await(const chunk of req)body+=chunk;
        const value=JSON.parse(body);assert.equal(value.expected_revision,settings.revision);
        Object.assign(settings.data.voice,value.changes.voice);settings.revision+='x';writes++;
        return json({status:'unknown',error:'停止结果未知'},502);
      }
      return json(settings);
    }
    if(req.url==='/api/readiness')return json({capabilities:[]});
    if(req.url==='/api/voice/devices')return json({devices:[]});
    if(req.url==='/api/manage/modules')return json(failRead?{error:'offline'}:registry,failRead?503:200);
    if(req.url.startsWith('/api/manage/modules/')){
      let body='';for await(const chunk of req)body+=chunk;
      const value=JSON.parse(body);assert.equal(value.expected_revision,registry.revision);
      const item=registry.modules.find(m=>m.id===value.id);
      if(req.url.endsWith('microphone_authorization'))item.options.user_authorized=value.enabled;
      else item.enabled=value.enabled;
      registry.revision+='x';writes++;failRead=breakAfterWrite;
      return json({status:'unknown',error:'停止结果未知'},502);
    }
    return json({error:'unexpected fixture route'},404);
  }
  if(req.url==='/'){
    res.setHeader('Content-Type','text/html;charset=utf-8');res.end('<main class="cap-side"><section id="host"></section></main>');return;
  }
  const name=req.url.slice(1);
  if(!/^[a-z-]+\.js$/.test(name)){res.writeHead(404);res.end();return;}
  let source=readFileSync(path.join(assets,name),'utf8');
  if(name==='management.js')source=source.slice(0,source.indexOf('\ntry {'))+'\nexport {capabilitySettings};';
  res.setHeader('Content-Type','text/javascript');res.end(source);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const report={passed:false,scope:'isolated product capability form; no microphone, models or daily writes'};
try{
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.evaluate(async()=>{const m=await import('/management.js');await m.capabilitySettings('speech',document.querySelector('#host'));});
  const voice=page.getByLabel('语音朗读',{exact:true});await voice.uncheck();
  await page.waitForFunction(()=>document.querySelector('[aria-label="语音朗读"]').disabled===false);
  assert.equal(await voice.isChecked(),false);assert.equal(writes,1);
  const permission=page.getByLabel('允许麦克风采集',{exact:true});await permission.uncheck();
  await page.waitForFunction(()=>document.querySelector('[aria-label="允许麦克风采集"]').disabled===false);
  assert.equal(await permission.isChecked(),false);assert.equal(writes,2);
  await page.getByLabel('朗读声音',{exact:true}).fill('new fixture');
  await page.getByRole('button',{name:'保存配置',exact:true}).click();
  await page.getByText('已重新读取保存状态，当前输入保留；没有自动重试保存。').waitFor();
  assert.equal(writes,3);
  await page.getByRole('button',{name:'保存配置',exact:true}).click();
  await page.getByText('没有需要保存的修改').waitFor();assert.equal(writes,3);
  breakAfterWrite=true;
  await page.getByLabel('语音识别',{exact:true}).uncheck();
  await page.getByText('开关状态无法确认，请重新打开详情；没有自动重试。').waitFor();
  assert.equal(await voice.isDisabled(),true);
  assert.equal(await voice.evaluate(el=>el.indeterminate),true);
  assert.equal(await permission.isDisabled(),true);assert.equal(writes,4);
  assert.deepEqual(errors,[]);
  report.passed=true;report.checks=['persisted module state reread','persisted permission reread','settings revision refreshed without resend','unreadable state disabled and indeterminate'];
}finally{
  writeFileSync(path.join(base,'report.json'),JSON.stringify(report,null,2));
  await browser.close();await new Promise(resolve=>server.close(resolve));console.log('ARTIFACT',base,JSON.stringify(report));
}
