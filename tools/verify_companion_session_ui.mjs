import {createServer} from 'node:http';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {loadPlaywright} from './lib/playwright.mjs';
const {chromium} = loadPlaywright();
const root = resolve('ui');
let state = 'stopped', captureActive=false, audioActive=false, cursor = 0, events = [], failStart = false, failAudio=false;
const writes = [];
let failQuestion=false;
let petAlive=false,failPet=false;
const server = createServer(async (request,response) => {
  try {
    if (request.url === '/') {
      response.setHeader('Content-Type','text/html');
      response.end('<link rel="stylesheet" href="/app/tokens.css"><link rel="stylesheet" href="/app/css/settings.css"><main class="sumika-capability-settings" style="width:280px;margin:20px"><script type="module">import {mountCompanionSession} from "/app/companion-session.js";mountCompanionSession(document.querySelector("main"));</script></main>');
    } else if (request.url === '/pet-controls') {
      response.setHeader('Content-Type','text/html');
      response.end('<link rel="stylesheet" href="/app/tokens.css"><link rel="stylesheet" href="/app/css/settings.css"><main style="width:280px;margin:20px"><script type="module">import {mountPetSession} from "/app/pet-session.js";mountPetSession(document.querySelector("main"));</script></main>');
    } else if(request.url==='/api/companion/pet') {
      let body='';for await(const chunk of request) body+=chunk;
      const packet=JSON.parse(body);
      if(packet.action!=='status') writes.push({...packet,kind:'pet'});
      if(packet.action==='start') petAlive=true;
      if(packet.action==='stop') petAlive=false;
      response.setHeader('Content-Type','application/json');
      if(failPet && packet.action==='start') {response.statusCode=500;response.end(JSON.stringify({error:'uncertain start'}));}
      else response.end(JSON.stringify({available:true,alive:petAlive,status:petAlive?'running':'stopped'}));
    } else if (request.url === '/api/manage/session') {
      response.setHeader('Content-Type','application/json'); response.end(JSON.stringify({csrf:'fixture'}));
    } else if(request.url==='/api/companion/windows') {
      response.setHeader('Content-Type','application/json'); response.end(JSON.stringify({windows:[{handle:123,process_id:42,process_creation:'7',title:'Tutorial'}]}));
    } else if(request.url==='/api/companion/perception' || request.url==='/api/companion/revoke') {
      let body=''; for await(const chunk of request) body+=chunk;
      const packet=JSON.parse(body);
      if(packet.action==='start') {writes.push({...packet,kind:'capture'});captureActive=true;}
      if(request.url.endsWith('revoke')) {state='stopped';captureActive=audioActive=false;writes.push({action:'revoke'});}
      response.setHeader('Content-Type','application/json'); response.end(JSON.stringify({status:captureActive?'running':'stopped',alive:captureActive,observations:captureActive?1:0}));
    } else if(request.url==='/api/companion/audio') {
      let body=''; for await(const chunk of request) body+=chunk;
      const packet=JSON.parse(body); writes.push({...packet,kind:'application-audio'});
      if(failAudio) {response.statusCode=400; response.end(JSON.stringify({error:'audio unavailable'}));return;}
      audioActive=true; response.setHeader('Content-Type','application/json');response.end(JSON.stringify({status:'running',alive:true}));
    } else if (request.url === '/api/companion/microphone') {
      let body = ''; for await (const chunk of request) body += chunk;
      const packet = JSON.parse(body);
      if (packet.action !== 'status') writes.push(packet);
      if (packet.action === 'start') {
        if (failStart) { response.statusCode=400; response.end(JSON.stringify({error:'fixture failure'})); return; }
        state = 'listening';
      }
      if (packet.action === 'stop') state = 'stopped';
      response.setHeader('Content-Type','application/json');
      response.end(JSON.stringify({status:state,alive:state==='listening',cursor,
        capture:{status:captureActive?'running':'stopped',alive:captureActive,target:{handle:123,process_id:42}},
        application_audio:{status:audioActive?'running':'stopped',alive:audioActive},
        events:events.filter(event=>event.sequence > (packet.after || 0))}));
    } else if(request.url==='/api/companion/ask-stream') {
      let body='';for await(const chunk of request) body+=chunk;
      const packet=JSON.parse(body);writes.push({...packet,kind:'question'});
      response.setHeader('Content-Type','application/x-ndjson');
      response.end(JSON.stringify({event:'delta',text:failQuestion?'stale partial answer':'first '})+'\n'+JSON.stringify({event:'complete',text:'first answer',status:failQuestion?'stale_response':'answered'})+'\n');
    } else {
      const path = resolve(root, '.'+new URL(request.url,'http://localhost').pathname);
      if (!path.startsWith(root+'/') && !path.startsWith(root+'\\')) throw Error('invalid path');
      response.setHeader('Content-Type',path.endsWith('.html')?'text/html; charset=utf-8':path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'image/svg+xml');
      response.end(await readFile(path));
    }
  } catch(error) { response.statusCode=500; response.end(error.message); }
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page = await browser.newPage({viewport:{width:390,height:700}});
const errors = []; page.on('pageerror',error=>errors.push(error.message));
page.on('dialog',dialog=>dialog.accept());
const checks = [];
function check(name,pass) { checks.push({name,pass}); if (!pass) throw Error(name); }
const output = process.argv[2] || 'E:/SumikaBuild/companion-session-ui';
try {
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  const start = page.getByRole('button',{name:'开始陪学'});
  const stop = page.getByRole('button',{name:'停止陪学'});
  await start.waitFor();
  await page.getByLabel('学习窗口').selectOption({label:'Tutorial'});
  await page.waitForFunction(()=>!document.querySelector('[aria-label="开始陪学"]').disabled);
  check('opening details never starts capture',writes.length===0);
  check('application audio defaults off',!(await page.getByLabel('采集应用声音').isChecked()));
  check('text is default mode',await page.getByLabel('交流模式').inputValue()==='text');
  await start.click();await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('文字交流'));
  check('text study never starts microphone',captureActive && !writes.some(value=>value.microphone_consent));
  check('text study scope cannot change during capture',await page.getByLabel('交流模式').isDisabled());
  await stop.click();await page.waitForFunction(()=>!document.querySelector('[aria-label="开始陪学"]').disabled);
  writes.length=0;
  await page.getByLabel('交流模式').selectOption('voice');
  await start.click(); await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('聆听'));
  const admission=writes.find(value=>value.microphone_consent);
  check('start sends both explicit consents',admission.microphone_consent===true && admission.playback_consent===true);
  check('capture binds explicit selected window',writes[0].kind==='capture' && writes[0].process_id===42 && writes[0].handle===123 && writes[0].process_creation==='7');
  check('default start never captures application audio',!writes.some(value=>value.kind==='application-audio'));
  events = [{sequence:1,event:'transcribed',text:'why?'},{sequence:2,event:'delta',text:'<script>answer</script>'}]; cursor=2;
  await page.waitForFunction(()=>document.querySelector('.companion-transcript').textContent.includes('answer'));
  check('event content is text, never HTML',await page.locator('.companion-transcript script').count()===0);
  events.push({sequence:3,event:'error',reason:'ConnectionError'});cursor=3;
  await page.waitForFunction(()=>!document.querySelector('.companion-transcript').textContent.includes('answer'));
  check('failed voice partial removed, question retained',await page.locator('.companion-transcript').textContent()==='why?');
  events.push({sequence:4,event:'user_started',turn:8},{sequence:5,event:'delta',turn:8,text:'complete answer'},
    {sequence:6,event:'playback_ended',turn:8},{sequence:7,event:'user_started',turn:9},
    {sequence:8,event:'delta',turn:9,text:'new provisional'}, {sequence:9,event:'interrupted',turn:8});cursor=9;
  await page.waitForFunction(()=>document.querySelector('.companion-transcript').textContent.includes('new provisional'));
  check('old interruption preserves current and completed answers',await page.locator('.companion-transcript').textContent()==='why?complete answernew provisional');
  events.push({sequence:10,event:'interrupted',turn:9});cursor=10;
  await page.waitForFunction(()=>!document.querySelector('.companion-transcript').textContent.includes('new provisional'));
  check('current interruption removes only provisional answer',await page.locator('.companion-transcript').textContent()==='why?complete answer');
  await stop.click(); await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('停止'));
  check('stop clears transient transcript',await page.locator('.companion-transcript p').count()===0);
  failStart=true; await start.click();
  await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('未确认'));
  check('uncertain write retains stop recovery',await stop.isEnabled());
  await stop.click();
  await page.getByRole('button',{name:'刷新会话状态'}).click();
  await page.waitForFunction(()=>!document.querySelector('[aria-label="开始陪学"]').disabled);
  check('failed start is never replayed',writes.filter(value=>value.action==='start' && value.kind!=='capture').length===2);
  failStart=false;
  await page.getByLabel('采集应用声音').check();
  await start.click();await page.waitForFunction(()=>document.querySelector('[data-application-audio-status]').textContent.includes('采集'));
  const audioAdmission=writes.find(value=>value.kind==='application-audio');
  check('application audio has separate consent and identity',audioAdmission.consent===true && audioAdmission.process_id===42 && audioAdmission.process_creation==='7');
  check('scope frozen during capture',await page.getByLabel('采集应用声音').isDisabled());
  const question=await page.evaluate(async()=>{
    const {sendCompanionText}=await import('/app/companion-text.js');
    const values=[];const handled=await sendCompanionText('explain',text=>values.push(text));
    return {handled,values};
  });
  check('text question streams through selected target',question.handled && question.values.join('|')==='first |first answer' && writes.find(value=>value.kind==='question').expected_target==='window:123:pid:42');
  await stop.click();
  await page.waitForFunction(()=>!document.querySelector('[aria-label="开始陪学"]').disabled);
  check('stop revokes both tracks',!captureActive && !audioActive && state==='stopped');
  check('inactive text remains ordinary chat',await page.evaluate(async()=>{
    const {sendCompanionText}=await import('/app/companion-text.js');
    return await sendCompanionText('ordinary',()=>{})===false;
  }));
  failAudio=true; const beforeMicrophone=writes.filter(value=>value.microphone_consent).length;
  await start.click();await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('未确认'));
  check('audio failure never continues microphone admission',writes.filter(value=>value.microphone_consent).length===beforeMicrophone);
  check('partial start retains stop',await stop.isEnabled());
  await stop.click();
  await page.waitForFunction(()=>!document.querySelector('[aria-label="开始陪学"]').disabled);
  await page.waitForFunction(()=>document.querySelectorAll('.companion-commands svg').length===3);
  check('icons rendered',await page.locator('.companion-commands svg').count()===3);
  check('narrow viewport has no horizontal overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  check('no page exceptions',errors.length===0);
  await mkdir(output,{recursive:true}); await page.screenshot({path:resolve(output,'narrow.png')});
  await page.setViewportSize({width:1440,height:900}); await page.screenshot({path:resolve(output,'desktop.png')});
  await page.setViewportSize({width:340,height:430});
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(['/api/manage/session','/api/companion/microphone','/api/companion/ask-stream','/api/companion/pet'].includes(path)) return route.continue();
    if(path==='/api/role/chat') writes.push({kind:'ordinary-chat',...route.request().postDataJSON()});
    return route.fulfill({contentType:'application/json',body:JSON.stringify({
      modules:[],capabilities:[],messages:[],roles:[],enabled:false,data:{memory:{},role:{},voice:{}},
    })});
  });
  errors.length=0;
  captureActive=true;failStart=false;failAudio=false;events=[];
  await page.goto(`http://127.0.0.1:${server.address().port}/app/index.html?pet=1`);
  await page.locator('[data-dp-input]').waitFor({state:'visible'});
  await page.evaluate(()=>{
    window.petHostMessages=[];
    window.chrome.webview={postMessage:value=>window.petHostMessages.push(value)};
  });
  await page.locator('#deskpet .dp-chara').dispatchEvent('pointerdown',{button:0});
  check('native pet drag delegates to host',await page.evaluate(()=>window.petHostMessages.join()==='sumika:drag'));
  await page.locator('[data-dp-input]').dispatchEvent('pointerdown',{button:0});
  await page.locator('[data-dp-send]').dispatchEvent('pointerdown',{button:0});
  check('interactive pet controls never drag host',await page.evaluate(()=>window.petHostMessages.length===1));
  check('actual pet host composer fits viewport',await page.locator('[data-dp-input]').evaluate(element=>{
    const bounds=element.getBoundingClientRect();return bounds.width>50 && bounds.left>=0 && bounds.right<=innerWidth && bounds.bottom<=innerHeight;
  }));
  await page.locator('[data-dp-input]').fill('Explain the visible formula');
  await page.locator('[data-dp-input]').press('Enter');
  await page.waitForFunction(()=>document.querySelector('[data-dp-log]').textContent.includes('first answer'));
  check('actual pet composer receives bound streamed answer',writes.some(value=>value.question==='Explain the visible formula' && value.expected_target==='window:123:pid:42'));
  check('pet send button restores after answer',await page.locator('[data-dp-send]').isEnabled());
  failQuestion=true;
  const beforeQuestions=writes.filter(value=>value.kind==='question').length;
  await page.locator('[data-dp-input]').fill('Question during page change');
  await page.locator('[data-dp-input]').press('Enter');
  await page.waitForFunction(()=>document.querySelector('[data-dp-log]').textContent.includes('学习内容已变化'));
  check('stale streamed answer is replaced with failure',!(await page.locator('[data-dp-log]').textContent()).includes('stale partial answer'));
  check('study failure is never retried or sent as ordinary chat',writes.filter(value=>value.kind==='question').length===beforeQuestions+1 && !writes.some(value=>value.kind==='ordinary-chat'));
  check('pet composer recovers after stale response',await page.locator('[data-dp-send]').isEnabled());
  await page.screenshot({path:resolve(output,'pet-text.png')});
  await page.locator('[data-dp-min]').click();
  check('pet compact hides composer and exposes existing restore',!(await page.locator('[data-dp-input]').isVisible()) && await page.locator('[data-dp-restore]').isVisible());
  check('compact delegates native resize',await page.evaluate(()=>window.petHostMessages.at(-1)==='sumika:compact'));
  await page.setViewportSize({width:56,height:56});
  check('compact restore fits native viewport',await page.locator('[data-dp-restore]').evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight}));
  await page.screenshot({path:resolve(output,'pet-compact.png')});
  await page.locator('[data-dp-restore]').click();
  await page.setViewportSize({width:340,height:430});
  check('pet expand restores composer and delegates native resize',await page.locator('[data-dp-input]').isVisible() && await page.evaluate(()=>window.petHostMessages.at(-1)==='sumika:expand'));
  await page.goto(`http://127.0.0.1:${server.address().port}/pet-controls`);
  const launch=page.getByRole('button',{name:'启动桌宠'}),close=page.getByRole('button',{name:'关闭桌宠'});
  await page.waitForFunction(()=>!document.querySelector('[aria-label="启动桌宠"]').disabled);
  check('opening pet detail never launches host',!writes.some(value=>value.kind==='pet'));
  await launch.click();await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('正在运行'));
  check('pet controls are single-instance',await launch.isDisabled() && await close.isEnabled());
  await close.click();await page.waitForFunction(()=>!document.querySelector('[aria-label="启动桌宠"]').disabled);
  failPet=true;await launch.click();
  await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('未确认'));
  check('uncertain pet start blocks replay and retains stop',await launch.isDisabled() && await close.isEnabled());
  check('pet launch sends fixed action only',writes.filter(value=>value.kind==='pet').every(value=>Object.keys(value).length===2));
  await close.click();await page.waitForFunction(()=>!document.querySelector('[aria-label="启动桌宠"]').disabled);
  check('pet stop recovers uncertain launch',!petAlive);
  await page.screenshot({path:resolve(output,'pet-controls.png')});
  await writeFile(resolve(output,'report.json'),JSON.stringify({checks,errors},null,2));
  console.log(JSON.stringify({passed:checks.length,output}));
} finally { await browser.close(); await new Promise(done=>server.close(done)); }
