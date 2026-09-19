// Isolated browser contract test using product markup/module, no microphone/API.
import {createRequire} from 'node:module';
import {readFileSync,readdirSync,existsSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {randomUUID} from 'node:crypto';
const root=process.cwd();
const runtime=path.join(process.env.LOCALAPPDATA,'OpenAI/Codex/runtimes/cua_node');
const pkg=readdirSync(runtime).map(n=>path.join(runtime,n,'bin/node_modules/playwright/package.json')).find(existsSync);
const {chromium}=createRequire(pkg)('playwright');
const base=path.join(root,'.sumika-next','speech-ui-'+randomUUID());mkdirSync(base,{recursive:true});
const html=readFileSync(path.join(root,'ui/app/index.html'),'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
const server=http.createServer((req,res)=>{
  if(req.url==='/speech-input.js'){
    res.setHeader('Content-Type','text/javascript');res.end(readFileSync(path.join(root,'ui/app/speech-input.js')));
  }else{res.setHeader('Content-Type','text/html;charset=utf-8');res.end(html);}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const report={passed:false,microphone_opened:false};
try{
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.evaluate(async()=>{
    const {bindSpeechInput,cancelSpeechInput}=await import('/speech-input.js');
    const composer=document.querySelector('#screen-room .chat-composer');
    const old=composer.querySelector('.input'),input=document.createElement('input');input.className=old.className;old.replaceWith(input);
    const notice=document.createElement('small');notice.id='speech-test-notice';composer.append(notice);
    window.fixture={role:'one',starts:0,cancels:0,pending:false,input,cancel:cancelSpeechInput};
    const api=async(route)=>{
      if(route.endsWith('/start')){
        fixture.starts++;
        if(fixture.delayStart)await new Promise(resolve=>fixture.releaseStart=resolve);
        return {id:'local-'+fixture.starts};
      }
      if(route.endsWith('/cancel')){
        fixture.cancels++;
        if(fixture.failCancel)throw Error('fixture stop unknown');
        return {state:'cancelled'};
      }
      return {state:fixture.pending?'recording':'completed',text:'本地识别文字'};
    };
    bindSpeechInput(composer.querySelector('.voice'),input,notice,api,()=>fixture.role);
  });
  const button=page.getByRole('button',{name:'语音输入'});
  page.once('dialog',d=>d.dismiss());await button.click();
  if(await page.evaluate(()=>fixture.starts)!==0)throw Error('declined confirmation started capture');
  await page.evaluate(()=>fixture.input.value='已有草稿');
  page.once('dialog',d=>d.accept());await button.click();
  await page.waitForFunction(()=>fixture.input.value==='已有草稿 本地识别文字');
  await page.waitForFunction(()=>document.querySelector('.voice').textContent==='♪');
  await page.evaluate(()=>{fixture.pending=true;fixture.failCancel=true;});
  page.once('dialog',d=>d.accept());await button.click();await button.click();
  await page.waitForFunction(()=>document.querySelector('#speech-test-notice').textContent.includes('未能确认'));
  await page.waitForTimeout(1200);
  if(await button.getAttribute('title')!=='重试停止语音输入')throw Error('failed cancel lost request');
  const beforeRetry=await page.evaluate(()=>fixture.starts);
  await page.evaluate(()=>fixture.failCancel=false);await button.click();
  await page.waitForFunction(()=>document.querySelector('.voice').textContent==='♪');
  if(await page.evaluate(()=>fixture.starts)!==beforeRetry)throw Error('stop retry started a new capture');
  await page.evaluate(()=>{fixture.delayStart=true;fixture.pending=true;});
  page.once('dialog',d=>d.accept());await button.click();
  await page.waitForFunction(()=>!!fixture.releaseStart);
  const beforeEarlyCancel=await page.evaluate(()=>fixture.cancels);
  await button.click();
  await page.evaluate(()=>fixture.releaseStart());
  await page.waitForFunction(()=>document.querySelector('.voice').textContent==='♪');
  if(await page.evaluate(()=>fixture.cancels)!==beforeEarlyCancel+1)throw Error('early cancel did not stop exactly once');
  await page.evaluate(()=>{fixture.delayStart=false;fixture.failCancel=false;fixture.pending=false;});
  page.once('dialog',d=>d.accept());await button.click();
  await page.evaluate(()=>{fixture.input.value='用户新草稿';fixture.role='two';});
  await page.waitForFunction(()=>document.querySelector('#speech-test-notice').textContent.includes('未写入'));
  if(await page.evaluate(()=>fixture.input.value)!=='用户新草稿')throw Error('stale result overwrote input');
  await page.evaluate(()=>fixture.pending=true);
  page.once('dialog',d=>d.accept());await button.click();await button.click();
  await page.waitForFunction(()=>document.querySelector('#speech-test-notice').textContent==='录音已取消');
  await page.waitForFunction(()=>document.querySelector('.voice').textContent==='♪');
  if(errors.length)throw Error('page errors');
  await page.locator('#screen-room .chat-composer').screenshot({path:path.join(base,'composer.png')});
  report.passed=true;report.checks=['confirmation dismissal sends nothing','transcript appends to unchanged draft','role/draft changes reject late result','cancel invokes stop once','failed cancellation retains request for explicit stop retry without new capture','cancel before start response stops exactly once after request ID arrives'];
}finally{
  writeFileSync(path.join(base,'report.json'),JSON.stringify(report,null,2));
  await browser.close();await new Promise(resolve=>server.close(resolve));
  console.log('ARTIFACT',base,JSON.stringify(report));
}
