import {createRequire} from 'node:module';
import {readFileSync,readdirSync,existsSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {randomUUID} from 'node:crypto';
const root=process.cwd(), runtime=path.join(process.env.LOCALAPPDATA,'OpenAI/Codex/runtimes/cua_node');
const pkg=readdirSync(runtime).map(n=>path.join(runtime,n,'bin/node_modules/playwright/package.json')).find(existsSync);
const {chromium}=createRequire(pkg)('playwright');
const base=path.join(root,'.sumika-next','playback-ui-'+randomUUID());mkdirSync(base,{recursive:true});
const html=readFileSync('ui/app/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
const server=http.createServer((req,res)=>{
 if(req.url==='/speech-playback.js'){res.setHeader('Content-Type','text/javascript');res.end(readFileSync('ui/app/speech-playback.js'));}
 else if(req.url==='/app/layout.css'){res.setHeader('Content-Type','text/css');res.end(readFileSync('ui/app/layout.css'));}
 else {res.setHeader('Content-Type','text/html;charset=utf-8');res.end(html);}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.on('pageerror',e=>errors.push(e.message));
const report={passed:false,hardware_used:false};
try{
 await page.goto(`http://127.0.0.1:${server.address().port}/#room`);
 const source=readFileSync('ui/app/bind.js','utf8');
 const renderer=source.slice(source.indexOf('function roomMessageNode('),source.indexOf('function renderRoomMessages('));
 await page.evaluate(async(renderer)=>{
  const m=await import('/speech-playback.js');
  window.fixture={starts:0,cancels:0,state:'processing'};
  const api=async(route,options)=>{
   if(!route.startsWith('/api/voice/output'))throw Error('unexpected API');
   if(route.endsWith('/start')){fixture.starts++;fixture.body=JSON.parse(options.body);if(fixture.denied)throw Object.assign(Error('语音未启用'),{status:403});if(fixture.delay)await new Promise(r=>fixture.release=r);return {id:'test-'+fixture.starts};}
   if(route.endsWith('/cancel')){fixture.cancels++;if(fixture.hangStop)await new Promise(()=>{});if(fixture.failStop)throw Error('stop unknown');return {state:'cancelled'};}
   return {state:fixture.state};
  };
  window.make=new Function('bindSpeechPlayback','api','roomChatRoleId','hasExplicitTaskIntent',renderer+';return roomMessageNode;')(m.bindSpeechPlayback,api,'one',()=>false);
  fixture.cancel=m.cancelSpeechPlayback;
  const list=document.querySelector('.chat-msgs');list.textContent='';
  const notice=document.createElement('small');notice.dataset.roomHistoryNotice='';list.after(notice);
  fixture.render=()=>{list.replaceChildren(make({who:'me',text:'测试',id:'u'}),make({who:'role',text:'今天也辛苦了，先休息一会儿吧。',id:'a'}),make({who:'role',text:'另一条回复',id:'b'}),make({who:'role',text:'错误',isError:true}));};
  fixture.render();
 },renderer);
 const buttons=page.locator('.room-playback');
 if(await buttons.count()!==2 || await page.evaluate(()=>fixture.starts)!==0)throw Error('wrong buttons or autoplay');
 await buttons.nth(0).click();await page.waitForFunction(()=>fixture.starts===1);
 if(!(await buttons.nth(1).isDisabled()))throw Error('parallel playback allowed');
 await page.evaluate(()=>fixture.render());await page.waitForFunction(()=>document.querySelector('.room-playback').textContent==='停止');
 await page.evaluate(()=>fixture.failStop=true);await buttons.nth(0).click();await page.waitForFunction(()=>document.querySelector('.room-playback').textContent==='重试停止');
 await page.evaluate(()=>fixture.failStop=false);await buttons.nth(0).click();await page.waitForFunction(()=>document.querySelector('.room-playback').textContent==='朗读');
 if(await page.evaluate(()=>fixture.starts)!==1)throw Error('stop replay');
 await page.evaluate(()=>{fixture.delay=true;});await buttons.nth(0).click();await page.waitForFunction(()=>!!fixture.release);await buttons.nth(0).click();await page.evaluate(()=>fixture.release());await page.waitForFunction(()=>document.querySelector('.room-playback').textContent==='朗读');
 await page.evaluate(()=>{fixture.delay=false;fixture.state='completed';});await buttons.nth(0).click();await page.waitForFunction(()=>document.querySelector('[data-room-history-notice]').textContent==='朗读完成');
 await page.evaluate(()=>{fixture.denied=true;});await buttons.nth(0).click();await page.waitForFunction(()=>document.querySelector('[data-room-history-notice]').textContent.includes('语音未启用'));if(await buttons.nth(0).isDisabled())throw Error('denial locked UI');
 await page.evaluate(()=>{fixture.denied=false;fixture.state='processing';});await buttons.nth(0).click();await page.evaluate(()=>fixture.cancel());await page.waitForFunction(()=>document.querySelector('.room-playback').textContent==='朗读');
 // A start which never settles must not keep cancellation pending forever.
 await page.clock.install();
 await page.evaluate(()=>{fixture.delay=true;fixture.release=null;});
 await buttons.nth(0).click();await page.waitForFunction(()=>!!fixture.release);
 await page.evaluate(()=>{fixture.cancelDone=false;fixture.cancel().catch(()=>{}).finally(()=>fixture.cancelDone=true);});
 await page.clock.runFor(15001);
 if(!await page.evaluate(()=>fixture.cancelDone))throw Error('unbounded cancellation wait');
 if(!await buttons.nth(0).isDisabled())throw Error('unknown ID allowed replay');
 const startsBefore=await page.evaluate(()=>fixture.starts);
 await page.evaluate(()=>fixture.release());
 await page.waitForFunction(()=>!document.querySelector('.room-playback').disabled);
 await buttons.nth(0).click();
 await page.waitForFunction(()=>document.querySelector('.room-playback').textContent==='朗读');
 if(await page.evaluate(()=>fixture.starts)!==startsBefore)throw Error('late ID replayed start');
 await page.evaluate(()=>{fixture.delay=false;fixture.hangStop=true;});
 await buttons.nth(0).click();
 await page.evaluate(()=>{fixture.cancelDone=false;fixture.cancel().catch(()=>{}).finally(()=>fixture.cancelDone=true);});
 await page.clock.runFor(15001);
 if(!await page.evaluate(()=>fixture.cancelDone))throw Error('unbounded stop response');
 if(await buttons.nth(0).isDisabled())throw Error('timed-out stop cannot retry');
 await page.evaluate(()=>{fixture.hangStop=false;});await buttons.nth(0).click();
 await page.waitForFunction(()=>document.querySelector('.room-playback').textContent==='朗读');
 if(errors.length)throw Error(errors.join('\n'));
 await page.locator('#screen-room .chat').screenshot({path:path.join(base,'chat.png')});
 report.passed=true;report.checks=['only role replies have controls; no autoplay','one playback at a time','history rerender preserves stop control','failed stop can retry without starting','early stop waits for request ID','completion resets UI','disabled voice explains rejection','role-switch cancellation API','hung start ends wait as unknown without replay','late ID allows explicit stop without another start','hung cancel ends wait and permits explicit retry'];
}finally{writeFileSync(path.join(base,'report.json'),JSON.stringify(report,null,2));await browser.close();await new Promise(r=>server.close(r));console.log(base,JSON.stringify(report));}
