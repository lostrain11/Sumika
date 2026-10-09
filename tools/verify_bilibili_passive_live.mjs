// Real public Bilibili passive connector acceptance. No user profile, input,
// audio capture; a model call requires the explicit acceptance flag. The MV3 prototype is loaded
// only in an isolated Edge profile.
import assert from 'node:assert/strict';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import {loadPlaywright} from './lib/playwright.mjs';
import {buildPassivePrototype} from './build_passive_browser_prototype.mjs';

const output=resolve(process.argv[2] || 'E:/SumikaBuild/bilibili-passive-live');
const videoUrl=process.argv.slice(2).find(value=>value.startsWith('https://')) || 'https://www.bilibili.com/video/BV1Lf4y1M72V/';
const allowModel=process.argv.includes('--allow-model');
const seekIndex=process.argv.indexOf('--seek-seconds');
const seekSeconds=seekIndex<0 ? null : Number(process.argv[seekIndex+1]);
if(seekSeconds!==null && (!Number.isFinite(seekSeconds) || seekSeconds<0 || seekSeconds>3600))
  throw Error('--seek-seconds must be 0..3600');
const credentialFile=process.argv[process.argv.indexOf('--credential-file')+1];
if(allowModel && (!credentialFile || process.argv.indexOf('--credential-file')<0))
  throw Error('--allow-model requires --credential-file');
await mkdir(output,{recursive:true});
const extension=await buildPassivePrototype(join(output,'extension'));
const script=await readFile('extensions/companion/browser_video_snapshot.js','utf8');
const {chromium}=loadPlaywright();
const browser=await chromium.launchPersistentContext(join(output,'profile'),{channel:'msedge',headless:true,
  args:['--mute-audio',`--disable-extensions-except=${extension}`,`--load-extension=${extension}`]});
let bridgeProcess;
const settingsFile=resolve(process.env.SUMIKA_SETTINGS||'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/Sumika/role-model-settings.json');
const report={passed:false,scope:'Real public Bilibili page -> isolated MV3 -> Sumika Bridge; no login, input, model, microphone or audio'};
if(allowModel) report.scope='Real public Bilibili page -> isolated MV3 -> Sumika Bridge -> configured multimodal provider; isolated settings, no memory writes';
try {
  const page=browser.pages()[0] || await browser.newPage();
  await page.goto(videoUrl,{waitUntil:'domcontentloaded',timeout:30000});
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2,null,{timeout:25000});
  await page.waitForTimeout(2500);
  if(seekSeconds!==null) {
    await page.evaluate(async seconds=>{
      const video=document.querySelector('video');
      if(!Number.isFinite(video.duration) || seconds>=video.duration)throw Error('seek outside video');
      video.pause();
      const completed=new Promise(resolve=>video.addEventListener('seeked',resolve,{once:true}));
      video.currentTime=seconds;
      await Promise.race([completed,new Promise((_,reject)=>setTimeout(()=>reject(Error('seek timeout')),15000))]);
    },seekSeconds);
    await page.waitForFunction(()=>{const v=document.querySelector('video');return v.readyState>=2 && !v.seeking;},null,{timeout:15000});
    report.owned_seek={requested_seconds:seekSeconds,paused:true};
  }
  const tab=await page.evaluate(()=>({url:location.href,origin:location.origin,
    video:!!document.querySelector('video'),time:document.querySelector('video')?.currentTime}));
  assert.ok(['https://www.bilibili.com','https://bilibili.com'].includes(tab.origin));
  const directory=join(output,'bridge-data');await mkdir(directory,{recursive:true});
  let credential;
  if(allowModel){
    const settings=JSON.parse(await readFile(settingsFile,'utf8'));
    if(settings.provider!=='openai-compatible' || !settings.enabled || !/^[A-Z][A-Z0-9_]*$/.test(settings.key_env))
      throw Error('enabled configured cloud provider required');
    const envText=await readFile(resolve(credentialFile),'utf8');
    const match=envText.match(new RegExp('\\$env:('+settings.key_env+')\\s*=\\s*([\'\"])([^\'\"\\r\\n]+)\\2'));
    if(!match)throw Error('credential assignment unavailable');
    credential={name:match[1],value:match[3]};
  }
  const code=`import sys,threading,json,copy
from pathlib import Path
import base64
from extensions.models.settings import load,save
from ui.server import serve
root=Path(sys.argv[1]);base=load(Path(sys.argv[2]));base['role']['database']=str(root/'role.db');base['role']['memory_provider']='embedded';base['memory']['enabled']=False;base['multimodal']['enabled']=True
save(base,root/'settings.json')
s=serve(root/'settings.json',port=0,workbench_root=root)
if sys.argv[3]!='model':s.sumika_bridge._companion.ask=lambda question,**kw: {'text':kw['binding'].observation.text,'target':kw['binding'].observation.target}
else:
 original=s.sumika_bridge._companion.ask
 def verified_ask(question,**kw):
  observation=kw['binding'].observation
  if observation.image is None:raise ValueError('actual bound video frame required')
  (root/'bound-frame.jpg').write_bytes(base64.b64decode(observation.image['data_base64'],validate=True))
  result=original(question,**kw)
  result['acceptance_binding']={'media_time_seconds':observation.media_time_seconds,'observed_at':observation.observed_at.isoformat(),'target':observation.target,'subtitle_chars':len(observation.text)}
  return result
 s.sumika_bridge._companion.ask=verified_ask
t=threading.Thread(target=s.serve_forever,daemon=True);t.start();print(json.dumps({'port':s.server_port}),flush=True)
try:sys.stdin.read()
finally:s.shutdown();s.server_close();t.join()
`;
  const bridgeEnv={...process.env,PYTHONPATH:resolve('.')};
  if(credential)bridgeEnv[credential.name]=credential.value;
  bridgeProcess=spawn(process.env.SUMIKA_TEST_PYTHON||'python',['-X','utf8','-B','-c',code,directory,
    settingsFile,allowModel?'model':'fixture'],
    {cwd:resolve('.'),env:bridgeEnv,windowsHide:true,stdio:['pipe','pipe','pipe']});
  bridgeProcess.stderr.on('data',()=>{});
  const lines=createInterface({input:bridgeProcess.stdout});
  const ready=await Promise.race([once(lines,'line').then(([line])=>JSON.parse(line)),
    new Promise((_,reject)=>{const timer=setTimeout(()=>reject(Error('bridge timeout')),15000);timer.unref();})]);lines.close();
  const base=`http://127.0.0.1:${ready.port}`;
  const session=await (await fetch(base+'/api/manage/session')).json();
  const worker=browser.serviceWorkers()[0]||await browser.waitForEvent('serviceworker',{timeout:10000});
  const extensionId=new URL(worker.url()).hostname;
  const selection={action:'start',consent:true,extension_id:extensionId,tab_id:page.context().pages().indexOf(page),
    origin:tab.origin,capture_frame:true};
  // Discover the actual Chrome tab id in the worker, avoiding a page-side API.
  selection.tab_id=await worker.evaluate(async url=>{
    const tabs=await chrome.tabs.query({url});if(tabs.length!==1)throw Error('selected tab not unique');return tabs[0].id;
  },videoUrl.split('?')[0]+'*');
  const manage=async value=>{
    const response=await fetch(base+'/api/companion/passive-browser',{method:'POST',
      headers:{'Content-Type':'application/json','X-Sumika-CSRF':session.csrf},body:JSON.stringify(value)});
    assert.equal(response.status,200);return response.json();
  };
  const offer=await worker.evaluate(configuration=>offerConnection(configuration),
    {base,tab_id:selection.tab_id});
  assert.equal(offer.status,'pending');
  assert.equal((await worker.evaluate(()=>pollConnection())).status,'pending');
  assert.equal(await worker.evaluate(()=>connection),null);
  const pending=await manage({action:'pending'});
  assert.equal(pending.requests.length,1);
  assert.equal(pending.requests[0].tab_id,selection.tab_id);
  await manage({action:'approve',request_id:pending.requests[0].request_id,
    consent:true,capture_frame:true});
  const started=await worker.evaluate(()=>pollConnection());
  assert.equal(started.status,'running');
  const grant=await worker.evaluate(()=>connection.grant);
  report.pairing={pending_without_capture:true,authenticated_sumika_approval:true,
    exact_video_bound:!!grant.approved_url};
  const deadline=Date.now()+12000;let accepted=0,lastStatus='';
  while(Date.now()<deadline){
    const state=await worker.evaluate(()=>({accepted:connection?.accepted||0,status:lastStatus}));accepted=state.accepted;lastStatus=state.status;
    if(accepted>=6)break;await new Promise(r=>setTimeout(r,250));
  }
  report.page={url:page.url().split('?')[0],tab,extension_id:extensionId,grant_target:grant.target};
  report.extension={accepted,lastStatus};
  const liveSample=await page.evaluate(`(${script})({origin:${JSON.stringify(tab.origin)},capture_frame:true})`);
  report.sample={valid:liveSample.valid,has_frame:!!liveSample.image,
    frame_status:liveSample.frame_status,has_subtitles:!!liveSample.subtitles,
    media_time_seconds:liveSample.media_time_seconds,
    subtitle_chars:(liveSample.subtitles||'').length};
  const observed=await worker.evaluate(()=>connection ? ({sequence:connection.sequence,
    accepted:connection.accepted,frames:connection.frames,heartbeats:connection.heartbeats}) : null);
  report.observed=observed;
  report.extension_sampling={poll_interval_seconds:1,full_frame_interval_seconds:5,
    note:'Service-worker accepted count includes both heartbeat and full-frame packets; frame content is not retained.'};
  if(accepted>0){
    const ask=await fetch(base+'/api/companion/ask',{method:'POST',headers:{'Content-Type':'application/json','X-Sumika-CSRF':session.csrf},
      body:JSON.stringify({question:allowModel ? '请读出当前视频画面中的文字或公式，并解释它在本节教程中的含义。无法辨认的部分请明确说明，不要根据标题猜测。' : 'what is on screen?'}),
      signal:AbortSignal.timeout(45000)});
    report.question_status=ask.status;
    if(ask.ok)report.answer=await ask.json();
    report.transport_passed=accepted>=6 && report.sample.has_frame;
    report.passed=ask.ok && (report.answer?.observation_target || report.answer?.target)===grant.target &&
      typeof report.answer?.text==='string' && report.answer.text.trim().length>0;
    if(allowModel) {
      report.vision_checks={image_sent:report.answer?.images_used===1,
        actual_frame_bound:report.answer?.acceptance_binding?.target===grant.target,
        source_is_video:report.answer?.observation_source==='video-frame',
        no_tools:report.answer?.role_tools===0,
        no_memory_proposals:report.answer?.memory_proposals===0};
      report.passed=report.passed && Object.values(report.vision_checks).every(Boolean);
      report.bound_frame_evidence=join(directory,'bound-frame.jpg');
    }
    report.capability=report.answer?.text ? (allowModel ? 'multimodal-video-frame-answer' : 'text-or-caption-observation') :
      'observation-bound-question-text-empty-check-frame-or-vision-context';
  } else {
    report.failure=report.sample.has_frame || report.sample.has_subtitles
      ? 'Observation reached Bridge but configured question path returned no non-empty answer'
      : 'Real page supplied no admissible subtitle or clean video frame to the fixed collector';
  }
  await worker.evaluate(()=>cancelRequestedConnection());
  report.pairing.extension_cancel_revokes_bridge=(await manage({action:'status'})).status==='stopped';
  assert.ok(report.pairing.extension_cancel_revokes_bridge);
} catch(error){report.error=String(error?.stack||error);}
finally{
  if(bridgeProcess&&bridgeProcess.exitCode===null){bridgeProcess.stdin.end();await Promise.race([once(bridgeProcess,'exit'),new Promise(r=>{const t=setTimeout(()=>{bridgeProcess.kill();r();},5000);t.unref();})]);}
  await browser.close();await writeFile(join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({...report,evidence:join(output,'report.json')}));
}
if(!(allowModel ? report.passed : report.transport_passed))process.exitCode=2;
