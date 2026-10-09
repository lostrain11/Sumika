import assert from 'node:assert/strict';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import {loadPlaywright} from './lib/playwright.mjs';
import {buildPassivePrototype} from './build_passive_browser_prototype.mjs';

const {chromium} = loadPlaywright();
const script = await readFile('extensions/companion/browser_video_snapshot.js','utf8');
const directory = join(process.argv[2] || '.sumika-next', `companion-video-${randomUUID()}`);
await mkdir(directory, {recursive:true});
const report = {passed:false, scope:'Real Edge HTMLVideoElement and TextTrack; generated local video; no BrowserSkill transport or external website compatibility', checks:{}};
const extensionMode=process.argv.includes('--passive-extension');
const extension=extensionMode ? await buildPassivePrototype(join(directory,'extension')) : null;
const browser = extensionMode ? await chromium.launchPersistentContext(join(directory,'profile'),{
  channel:'msedge',headless:true,args:[`--disable-extensions-except=${extension}`,`--load-extension=${extension}`]
}) : await chromium.launch({channel:'msedge',headless:true});
let bridgeProcess;
try {
  const page = await browser.newPage();
  await page.route('https://lesson.test/**', route => route.fulfill({contentType:'text/html',body:'<video width="640" height="360" muted></video>'}));
  await page.goto('https://lesson.test/tutorial?private_token=fixture');
  await page.evaluate(async () => {
    const canvas = document.createElement('canvas');
    canvas.width = 320; canvas.height = 180;
    const context = canvas.getContext('2d');
    let frame = 0;
    const timer = setInterval(() => {
      context.fillStyle = frame++ % 2 ? '#eeeeee' : '#337799';
      context.fillRect(0,0,320,180);
      context.fillStyle = '#111111';context.fillText(`Lesson frame ${frame}`,20,50);
    },50);
    const stream = canvas.captureStream(20);
    const recorder = new MediaRecorder(stream, {mimeType:'video/webm'});
    const chunks = [];
    recorder.ondataavailable = event => chunks.push(event.data);
    const stopped = new Promise(resolve => recorder.onstop = resolve);
    recorder.start();
    await new Promise(resolve => setTimeout(resolve,2200));
    recorder.stop(); await stopped;
    clearInterval(timer);stream.getTracks().forEach(track => track.stop());
    const video = document.querySelector('video');
    video.src = URL.createObjectURL(new Blob(chunks,{type:'video/webm'}));
    const track = video.addTextTrack('subtitles','Lesson','en');
    track.mode = 'hidden';
    track.addCue(new VTTCue(0,0.8,'FIRST_LESSON'));
    track.addCue(new VTTCue(1,1.8,'<b>SECOND_LESSON</b>'));
    window.fixtureTrack = track;
    await video.play();
  });
  const read = () => page.evaluate(`(${script})({origin:'https://lesson.test'})`);
  await page.waitForFunction(() => document.querySelector('video').currentTime > 0.15);
  await page.evaluate(() => document.querySelector('video').pause());
  const first = await read();
  assert.equal(first.valid,true);assert.equal(first.subtitles,'FIRST_LESSON');
  assert.equal(first.paused,true);assert.equal(first.url,'https://lesson.test/tutorial');
  report.checks.playback_time_and_current_cue = true;
  const readFrame = () => page.evaluate(`(${script})({origin:'https://lesson.test',capture_frame:true})`);
  const clean = await readFrame();
  assert.equal(clean.frame_status,'video_element_available');
  assert.equal(clean.image.media_type,'image/jpeg');
  await page.evaluate(() => {
    const overlay = document.createElement('div');
    overlay.id = 'fixture-danmaku';overlay.textContent = '为什么这里取负号';
    overlay.style.cssText = 'position:absolute;top:20px;left:20px;color:red;font-size:40px';
    document.body.append(overlay);
  });
  const withOverlay = await readFrame();
  assert.equal(withOverlay.image.data_base64,clean.image.data_base64);
  await page.evaluate(() => {
    const overlay = document.querySelector('#fixture-danmaku');
    overlay.style.left='200px';overlay.textContent='移动且改变的弹幕';
  });
  assert.equal((await readFrame()).image.data_base64,clean.image.data_base64);
  report.checks.dom_overlay_changes_do_not_change_video_frame = true;
  await page.evaluate(() => {
    history.replaceState(null,'','/tutorial?private_token=other');
  });
  assert.deepEqual((await read()).media_identity, first.media_identity);
  assert.equal((await read()).url,'https://lesson.test/tutorial');
  report.checks.private_query_excluded_from_identity = true;
  await page.evaluate(() => document.querySelector('video').play());
  const playingFirst = await readFrame();
  await page.waitForFunction(position => document.querySelector('video').currentTime > position + 0.15,
    playingFirst.media_time_seconds);
  const playingNext = await readFrame();
  await page.evaluate(() => document.querySelector('video').pause());
  await page.waitForTimeout(50);
  const pausedDuringQuestion = await readFrame();
  await page.evaluate(() => document.querySelector('video').play());
  await page.waitForTimeout(50);
  const resumedDuringQuestion = await readFrame();
  await page.evaluate(async () => {
    const video = document.querySelector('video');
    const sought = new Promise(resolve => video.addEventListener('seeked',resolve,{once:true}));
    video.currentTime = 1.2;await sought;
  });
  const second = await read();
  const playingSeek = await readFrame();
  await page.evaluate(() => document.querySelector('video').pause());
  assert.equal(second.subtitles,'SECOND_LESSON');assert.ok(second.media_time_seconds >= 1.19);
  assert.equal(second.media_identity.media_instance, first.media_identity.media_instance);
  assert.ok(second.media_identity.timeline_revision > first.media_identity.timeline_revision);
  report.checks.seek_replaces_old_cue = true;
  // Actual collector snapshots exercise the production service; the role callback
  // is local. No external model, audio device or user desktop input is involved.
  const bindingCode = `import json, sys
from extensions.companion.browser_video import browser_video_observation
from extensions.companion.qa import CompanionQuestionService
values=json.load(sys.stdin)
first,next_frame,paused,resumed,sought=[browser_video_observation(value,origin='https://lesson.test',target='owned:video',capture_frame=True) for value in values]
def reply(prompt, *, on_delta, images, **kwargs):
    assert images == [dict(first.image)]
    on_delta('first')
    service.update(next_frame)
    service.update(paused)
    service.update(resumed)
    on_delta('second')
    return {'text':'frozen answer'}
service=CompanionQuestionService(reply)
service.update(first)
binding=service.bind_question()
deltas=[]
answer=service.ask('explain',binding=binding,on_delta=deltas.append)
assert answer.get('text') == 'frozen answer', answer
assert answer['observation_at'] == first.observed_at.isoformat()
assert len(deltas) == 2 and answer['context_turns'] == 1
assert service._histories['companion'][0]['media_time_seconds'] == first.media_time_seconds
service.update(sought)
assert service.ask('obsolete question',binding=binding)['status'] == 'stale_response'
print(json.dumps({'normal_playback_retains_frozen_answer':True,'pause_resume_preserve_question':True,'completed_seek_invalidates_binding':True}))
`;
  const bindingProcess = spawn(process.env.SUMIKA_TEST_PYTHON || 'python',
    ['-X','utf8','-B','-c',bindingCode], {stdio:['pipe','pipe','pipe'],windowsHide:true});
  let bindingOutput='', bindingError='';
  bindingProcess.stdout.on('data',value=>{bindingOutput+=value.toString();});
  bindingProcess.stderr.on('data',value=>{bindingError+=value.toString();});
  const bindingDone=once(bindingProcess,'close');
  bindingProcess.stdin.end(JSON.stringify([playingFirst,playingNext,pausedDuringQuestion,resumedDuringQuestion,playingSeek]));
  const [bindingExit]=await bindingDone;
  assert.equal(bindingExit,0,bindingError);
  report.checks.production_question_binding_with_real_playback_and_seek=JSON.parse(bindingOutput);
  await page.evaluate(async () => {
    const video = document.querySelector('video');
    const sought = new Promise(resolve => video.addEventListener('seeked',resolve,{once:true}));
    video.currentTime += 0.05;await sought;
  });
  const smallSeek = await read();
  assert.equal(smallSeek.subtitles,second.subtitles);
  assert.ok(smallSeek.media_time_seconds-second.media_time_seconds < 0.1);
  assert.ok(smallSeek.media_identity.timeline_revision > second.media_identity.timeline_revision);
  assert.deepEqual((await read()).media_identity,smallSeek.media_identity);
  report.checks.small_completed_seek_changes_identity_once = true;
  assert.notEqual((await readFrame()).image.data_base64,clean.image.data_base64);
  report.checks.changed_video_frame_detectable = true;
  await page.evaluate(() => {window.fixtureTrack.mode = 'disabled';});
  const missing = await read();
  assert.equal(missing.valid,false);assert.equal(missing.subtitles,'');
  report.checks.missing_subtitles_invalidates_context = true;
  await page.evaluate(() => {
    const original = document.querySelector('video');
    original.replaceWith(original.cloneNode());
  });
  await page.waitForFunction(() => document.querySelector('video').readyState >= 2);
  const replacement = await read();
  assert.equal(replacement.media_identity.source_fingerprint,missing.media_identity.source_fingerprint);
  assert.notEqual(replacement.media_identity.media_instance,missing.media_identity.media_instance);
  report.checks.replaced_video_element_fences_same_source = true;
  await page.evaluate(() => {
    const other = document.createElement('video');other.width=100;other.height=100;document.body.append(other);
  });
  assert.equal((await read()).reason,'ambiguous_video');
  assert.equal((await page.evaluate(`(${script})({origin:'https://wrong.test'})`)).reason,'origin_changed');
  report.checks.ambiguous_video_and_origin_rejected = true;
  const bili = await browser.newPage();
  await bili.route('https://www.bilibili.com/**', route => route.fulfill({contentType:'text/html',
    body:'<video width="640" height="360"></video>'}));
  await bili.goto('https://www.bilibili.com/video/BVfixture/?p=2&private_token=secret');
  const biliRead = () => bili.evaluate(`(${script})({origin:'https://www.bilibili.com'})`);
  const part2 = await biliRead();
  assert.equal(part2.media_identity.part,2);
  assert.equal(part2.url,'https://www.bilibili.com/video/BVfixture/?p=2');
  await bili.evaluate(() => history.replaceState(null,'','?p=3&private_token=other'));
  const part3 = await biliRead();
  assert.equal(part3.media_identity.part,3);
  assert.notDeepEqual(part2.media_identity,part3.media_identity);
  report.checks.bilibili_part_identity_changes_without_private_query = true;
  if (process.argv.includes('--passive-bridge') || extensionMode) {
    // Reuse this verifier's generated clip and real collector. This exercises
    // HTTP ingress with a protocol fixture, not an installed MV3 extension.
    const clip = await page.evaluate(async () => Array.from(new Uint8Array(
      await (await fetch(document.querySelector('video').src)).arrayBuffer())));
    await bili.evaluate(async bytes => {
      const video = document.querySelector('video');video.muted=true;
      video.src=URL.createObjectURL(new Blob([new Uint8Array(bytes)],{type:'video/webm'}));
      const track=video.addTextTrack('subtitles','Lesson','en');track.mode='hidden';
      track.addCue(new VTTCue(0,2,'PASSIVE_LESSON'));
      await video.play();video.pause();
    },clip);
    const pythonCode = `import sys, threading, json
from pathlib import Path
from ui.server import serve
server=serve(Path(sys.argv[1])/'settings.json',port=0,workbench_root=Path(sys.argv[1]))
server.sumika_bridge._companion.ask=lambda question,**kw: {'text':kw['binding'].observation.text,'target':kw['binding'].observation.target}
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
print(json.dumps({'port':server.server_port}),flush=True)
try: sys.stdin.read()
finally: server.shutdown();server.server_close();thread.join()
`;
    bridgeProcess=spawn(process.env.SUMIKA_TEST_PYTHON || 'python',
      ['-X','utf8','-B','-c',pythonCode,join(directory,'passive-data')],
      {stdio:['pipe','pipe','pipe'],windowsHide:true});
    bridgeProcess.stderr.on('data',()=>{});
    const lines=createInterface({input:bridgeProcess.stdout});
    const ready=await Promise.race([
      once(lines,'line').then(([line])=>JSON.parse(line)),
      new Promise((_,reject)=>{const timer=setTimeout(()=>reject(new Error('bridge start timeout')),15000);timer.unref();}),
      once(bridgeProcess,'exit').then(()=>{throw new Error('bridge exited before ready');})
    ]);
    lines.close();
    const base=`http://127.0.0.1:${ready.port}`;
    const session=await (await fetch(base+'/api/manage/session')).json();
    const worker=extensionMode ? (browser.serviceWorkers()[0] || await browser.waitForEvent('serviceworker',{timeout:10000})) : null;
    const original=worker ? await worker.evaluate(async()=>{
      const tabs=await chrome.tabs.query({url:'https://www.bilibili.com/video/*'});
      if(tabs.length!==1)throw new Error('ambiguous original tab');
      return {tab_id:tabs[0].id,window_id:tabs[0].windowId};
    }) : {tab_id:7};
    const extensionId=worker ? new URL(worker.url()).hostname : 'a'.repeat(32);
    const selection={action:'start',consent:true,extension_id:extensionId,tab_id:original.tab_id,
      origin:'https://www.bilibili.com',capture_frame:true};
    const manage=async payload=>{
      const response=await fetch(base+'/api/companion/passive-browser',{method:'POST',
        headers:{'Content-Type':'application/json','X-Sumika-CSRF':session.csrf},body:JSON.stringify(payload)});
      assert.equal(response.status,200);return response.json();
    };
    let grant;
    if(extensionMode) {
      const offer=await worker.evaluate(configuration=>offerConnection(configuration),
        {base,tab_id:original.tab_id});
      assert.equal(offer.status,'pending');
      assert.equal((await worker.evaluate(()=>pollConnection())).status,'pending');
      assert.equal(await worker.evaluate(()=>connection),null);
      const pending=await manage({action:'pending'});
      assert.equal(pending.requests.length,1);
      assert.equal(pending.requests[0].extension_id,extensionId);
      assert.equal(pending.requests[0].tab_id,original.tab_id);
      assert.ok(!('receipt' in pending.requests[0]));
      await manage({action:'approve',request_id:pending.requests[0].request_id,
        consent:true,capture_frame:true});
      assert.equal((await worker.evaluate(()=>pollConnection())).status,'running');
      grant=await worker.evaluate(()=>connection.grant);
      report.checks.real_mv3_offer_requires_authenticated_sumika_consent=true;
    } else grant=await manage(selection);
    if(extensionMode) {
      const waitFor=async predicate=>{
        const deadline=Date.now()+8000;
        while(Date.now()<deadline) {
          if(await predicate())return;
          await new Promise(resolve=>setTimeout(resolve,100));
        }
        const state=await worker.evaluate(()=>({status:lastStatus,accepted:connection?.accepted||0}));
        throw new Error('extension state timeout: '+JSON.stringify(state));
      };
      await waitFor(()=>worker.evaluate(()=>connection?.accepted>=2));
      const traffic=await worker.evaluate(()=>({frames:connection.frames,heartbeats:connection.heartbeats}));
      assert.equal(traffic.frames,1);assert.ok(traffic.heartbeats>=1);
      report.checks.unchanged_content_sends_heartbeat_without_jpeg=true;
      const question=await fetch(base+'/api/companion/ask',{method:'POST',headers:{
        'Content-Type':'application/json','X-Sumika-CSRF':session.csrf},body:JSON.stringify({question:'what am I watching?'})});
      assert.equal(question.status,200);
      const answer=await question.json();assert.equal(answer.text,'PASSIVE_LESSON');assert.equal(answer.target,grant.target);
      await bili.evaluate(async()=>{
        const video=document.querySelector('video');
        const done=new Promise(resolve=>video.addEventListener('seeked',resolve,{once:true}));
        video.currentTime=1.2;await done;
        video.textTracks[0].activeCues[0].text='CHANGED_PASSIVE_LESSON';
      });
      await waitFor(()=>worker.evaluate(()=>connection?.frames>=2));
      const changed=await fetch(base+'/api/companion/ask',{method:'POST',headers:{
        'Content-Type':'application/json','X-Sumika-CSRF':session.csrf},body:JSON.stringify({question:'what changed?'})});
      assert.equal(changed.status,200);assert.equal((await changed.json()).text,'CHANGED_PASSIVE_LESSON');
      report.checks.changed_cue_updates_bridge_after_initial_generation=true;
      const finalTab=await worker.evaluate(id=>chrome.tabs.get(id),original.tab_id);
      assert.equal(finalTab.id,original.tab_id);assert.equal(finalTab.windowId,original.window_id);
      await manage({action:'pause'});
      await waitFor(()=>worker.evaluate(()=>lastStatus==='rejected:403'));
      const resumed=await manage({action:'resume'});
      assert.notEqual(resumed.token,grant.token);
      await worker.evaluate(configuration=>startConnection(configuration),{base,grant:resumed});
      await waitFor(()=>worker.evaluate(()=>connection?.accepted>=1));
      await manage({action:'stop'});
      await waitFor(()=>worker.evaluate(()=>lastStatus==='rejected:403'));
      await worker.evaluate(configuration=>offerConnection(configuration),
        {base,tab_id:original.tab_id});
      const next=await manage({action:'pending'});
      await manage({action:'approve',request_id:next.requests[0].request_id,
        consent:true,capture_frame:true});
      await worker.evaluate(()=>pollConnection());
      await waitFor(()=>worker.evaluate(()=>connection?.accepted>=1));
      await worker.evaluate(()=>cancelRequestedConnection());
      assert.equal((await manage({action:'status'})).status,'stopped');
      report.checks.real_mv3_extension_cancel_revokes_bridge_grant=true;
      report.checks.real_mv3_content_worker_ingress_and_question_binding=true;
      report.checks.original_tab_and_window_retained=true;
      report.checks.mv3_pause_resume_stop=true;
      report.passive_scope='Actual headless Edge MV3 isolated content script -> service-worker fetch -> isolated Sumika Bridge; local Bilibili-shaped video fixture and local question callback. No real Bilibili site, external model, OS process binding or voice acceptance.';
    } else {
    const push=async (snapshot,sequence,token=grant.token)=>fetch(base+'/api/companion/passive-browser/push',
      {method:'POST',headers:{'Content-Type':'application/json','Origin':'chrome-extension://'+'a'.repeat(32),
        'Authorization':'Bearer '+token},body:JSON.stringify({tab_id:7,sequence,snapshot})});
    const snapshot=()=>bili.evaluate(`(${script})({origin:'https://www.bilibili.com',capture_frame:true})`);
    const before=await snapshot();assert.equal(before.subtitles,'PASSIVE_LESSON');
    assert.ok(before.image);assert.equal((await push(before,0)).status,200);
    await bili.evaluate(()=>{
      const node=document.createElement('div');node.className='bpx-player-dm-dm';
      node.textContent='为什么这里取负号';node.style.cssText='position:absolute;left:20px;top:20px';
      document.body.append(node);
    });
    const after=await snapshot();
    assert.equal(before.image.data_base64,after.image.data_base64);
    assert.equal(after.danmaku[0].text,'为什么这里取负号');
    assert.equal((await push(after,1)).status,200);
    assert.equal((await push(after,1)).status,403);
    await manage({action:'pause'});
    assert.equal((await push(await snapshot(),2)).status,403);
    const resumed=await manage({action:'resume'});
    assert.notEqual(resumed.token,grant.token);
    assert.equal((await push(await snapshot(),3)).status,403);
    assert.equal((await push(await snapshot(),0,resumed.token)).status,200);
    await manage({action:'stop'});
    assert.equal((await push(await snapshot(),1,resumed.token)).status,403);
    report.checks.passive_http_real_video_danmaku_and_lifecycle=true;
    report.passive_scope='Real headless Edge fixed collector -> HTTP protocol fixture -> isolated Sumika Bridge. No installed extension, real Bilibili website, OS process binding or external model acceptance.';
    }
  }
  await bili.evaluate(() => Object.defineProperty(document.querySelector('video'),'seeking',{value:true}));
  const seeking = await biliRead();
  assert.equal(seeking.valid,false);assert.equal(seeking.reason,'video_seeking');
  assert.equal(seeking.subtitles,'');assert.equal(seeking.image,null);
  report.checks.seeking_invalidates_in_between_evidence = true;
  report.samples = {first,second,missing};
  report.passed = true;
} finally {
  if (bridgeProcess && bridgeProcess.exitCode === null) {
    bridgeProcess.stdin.end();
    await Promise.race([once(bridgeProcess,'exit'),new Promise(resolve=>{
      const timer=setTimeout(()=>{bridgeProcess.kill();resolve();},5000);timer.unref();
    })]);
  }
  await browser.close();
  await writeFile(join(directory,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({...report,evidence:join(directory,'report.json')}));
}
