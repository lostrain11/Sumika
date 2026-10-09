// Delivery package P3 soak acceptance: the production companion extension
// against a real isolated Sumika bridge with relayed tab audio into the
// packaged voice interpreter. Generated local lesson only; no real website.
// Usage:
//   node tools/verify_companion_extension_soak.mjs <output-dir> [options]
//   --seconds N            soak duration (default 1800)
//   --subtitles on|off     TextTrack cues present (default on)
//   --muted                video.muted=true (player volume zero still captures)
//   --other-tab            second tab plays audible audio concurrently
//   --seek-every N         seek the video every N seconds (fence checks)
//   --pause-at N           pause at N seconds, expect packets to stop
//   --part-change N        switch ?p= part at N seconds (reconnect + re-consent)
import assert from 'node:assert/strict';
import {mkdir, writeFile, writeFile as write} from 'node:fs/promises';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import {loadPlaywright} from './lib/playwright.mjs';
import {buildCompanionExtension} from './build_companion_extension.mjs';

const args = process.argv.slice(2);
const value = name => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index+1] : null;
};
const directory = join(args[0] || '.sumika-next', `companion-soak-${randomUUID()}`);
const seconds = Number(value('--seconds') || 1800);
const subtitles = (value('--subtitles') || 'on') === 'on';
const muted = args.includes('--muted');
const otherTab = args.includes('--other-tab');
const seekEvery = Number(value('--seek-every') || 0);
const pauseAt = Number(value('--pause-at') || 0);
const partChange = Number(value('--part-change') || 0);
const voskModel = value('--vosk-model') || 'E:/Models/Speech/sumika/vosk-model-small-cn-0.22';
const voicePython = value('--voice-python');
await mkdir(directory, {recursive:true});
const report = {passed:false, scope:'Production MV3 extension in real headless Edge -> isolated Sumika bridge -> packaged voice interpreter (vosk). Generated local lesson; no real website, no external model.', options:{seconds,subtitles,muted,otherTab,seekEvery,pauseAt,partChange}, checks:{}, phases:[]};
const extension = await buildCompanionExtension(join(directory,'extension'));
const {chromium} = loadPlaywright();
const browser = await chromium.launchPersistentContext(join(directory,'profile'),{
  channel:'msedge',headless:true,args:[`--disable-extensions-except=${extension}`,`--load-extension=${extension}`]});
let bridgeProcess;
const log = message => {report.phases.push({at:new Date().toISOString(),message});console.log('[soak]',message);};
try {
  // Speech fixture: SAPI synthesizes a looping Chinese lesson line so the
  // relayed tab audio produces real transcripts through vosk.
  const wavPath = join(directory,'lesson.wav');
  const ps = command => new Promise((resolve,reject)=>{
    const sapi=spawn('powershell',['-NoProfile','-Command',command],{windowsHide:true});
    sapi.on('exit',code=>code===0?resolve():reject(new Error('powershell exit '+code)));
    sapi.on('error',reject);
  });
  const psQuote = value => `'${String(value).replace(/'/g,"''")}'`;
  await ps('Add-Type -AssemblyName System.Speech;'+
    '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;'+
    `$s.SetOutputToWaveFile(${psQuote(wavPath)});`+
    `$s.Speak(${psQuote('第一个知识点，函数在某点的导数等于切线斜率。')});`+
    `$s.Speak(${psQuote('第二个知识点，导数描述瞬时变化率。')});`+
    '$s.Dispose()');
  log('sapi lesson wav generated');
  const pageScript = async options => {
    const SUBTITLES = options.subtitles;
    const MUTED = options.muted;
    const binary = Uint8Array.from(atob(options.wav), c=>c.charCodeAt(0));
    const wavUrl = URL.createObjectURL(new Blob([binary],{type:'audio/wav'}));
    const canvas = document.createElement('canvas');
    canvas.width=320;canvas.height=180;
    const context = canvas.getContext('2d');
    let frame = 0;
    const timer = setInterval(()=>{
      context.fillStyle = frame++ % 2 ? '#eeeeee' : '#337799';
      context.fillRect(0,0,320,180);
      context.fillStyle='#111';context.fillText(`Lesson frame ${frame}`,20,50);
    },50);
    const stream = canvas.captureStream(20);
    const audioElement = document.createElement('audio');
    audioElement.src = wavUrl; audioElement.loop = true;
    document.body.append(audioElement);
    await audioElement.play();
    const audioContext = new AudioContext();
    const source = audioContext.createMediaElementSource(audioElement);
    const destination = audioContext.createMediaStreamDestination();
    source.connect(destination);
    destination.stream.getAudioTracks().forEach(track=>stream.addTrack(track));
    const recorder = new MediaRecorder(stream,{mimeType:'video/webm'});
    const chunks=[];
    recorder.ondataavailable=event=>chunks.push(event.data);
    const stopped=new Promise(resolve=>recorder.onstop=resolve);
    recorder.start();
    await new Promise(resolve=>setTimeout(resolve,2500));
    recorder.stop();await stopped;
    clearInterval(timer);stream.getTracks().forEach(track=>track.stop());
    audioElement.pause();
    const video=document.createElement('video');
    video.width=640;video.height=360;
    video.loop = true;
    video.src=URL.createObjectURL(new Blob(chunks,{type:'video/webm'}));
    document.body.append(video);
    if (SUBTITLES) {
      const track=video.addTextTrack('subtitles','Lesson','en');track.mode='hidden';
      for (let second=0;second<600;second+=4)
        track.addCue(new VTTCue(second,second+2,`LESSON_POINT_${Math.floor(second/4)+1}`));
    }
    video.muted = MUTED;
    video.volume = 0;
    await video.play();
    window.__ready = true;
  };
  const page = await browser.newPage();
  page.on('console',message=>{const text=message.text();if(text.includes('[sumika-audio]'))console.log('[content]',text);});
  await page.route('https://www.bilibili.com/**', route => route.fulfill({contentType:'text/html',body:'<body></body>'}));
  await page.goto('https://www.bilibili.com/video/BVsoak/?p=1');
  const wav = await (async()=>{
    const {readFile} = await import('node:fs/promises');
    return (await readFile(wavPath)).toString('base64');
  })();
  const pageOptions = {wav, subtitles, muted};
  await page.evaluate(pageScript, pageOptions)
    .then(null, error=>{throw new Error('fixture page failed: '+error.message);});
  await page.waitForFunction('window.__ready === true',{timeout:15000});
  log('fixture video with audio track playing');
  if (otherTab) {
    // Concurrent audible playback from a second tab must not break the
    // session; opened after pairing so the lesson tab stays unambiguous.
    const other = await browser.newPage();
    await other.route('https://www.bilibili.com/**', route => route.fulfill({contentType:'text/html',body:'<body></body>'}));
    await other.goto('https://www.bilibili.com/video/BVother/');
    await other.evaluate(()=>{
      const context=new AudioContext();
      const oscillator=context.createOscillator();
      oscillator.connect(context.destination);
      oscillator.start();
      window.__otherAudio=true;
    });
    log('other tab with audible oscillator started');
    report.checks.other_tab_audio_started=true;
  }
  const bridgeData = join(directory,'bridge-data');
  await mkdir(bridgeData,{recursive:true});
  const pythonCode = `import sys, threading, json
from pathlib import Path
data = Path(sys.argv[1])
from extensions.models.settings import example, save, load
config = example(data/'role', data/'memory.sqlite3')
config['enabled'] = True
config['voice'].update({'enabled': True, 'input_device': 0, 'asr_model': sys.argv[2]})
save(config, data/'settings.json')
from extensions.capabilities import CapabilityStore
store = CapabilityStore(data/'capabilities.sqlite3')
store.configure('asr', 'vosk', options={})
store.close()
from ui.server import serve
server=serve(data/'settings.json',port=0,workbench_root=data,capability_database=data/'capabilities.sqlite3')
server.sumika_bridge._companion.ask=lambda question,**kw: {'text':kw['binding'].observation.text,'target':kw['binding'].observation.target}
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
print(json.dumps({'port':server.server_port}),flush=True)
try: sys.stdin.read()
finally: server.shutdown();server.server_close();thread.join()
`;
  bridgeProcess=spawn(process.env.SUMIKA_TEST_PYTHON || 'python',
    ['-X','utf8','-B','-c',pythonCode,bridgeData,voskModel],
    {stdio:['pipe','pipe','pipe'],windowsHide:true,
     env:{...process.env,...(voicePython?{SUMIKA_VOICE_PYTHON:voicePython}:{}),
          SUMIKA_BROWSER_AUDIO_CHILD_LOG:join(directory,'audio-child.log')}});
  bridgeProcess.stderr.on('data',value=>process.stderr.write('[bridge] '+value));
  const lines=createInterface({input:bridgeProcess.stdout});
  const ready=await Promise.race([
    once(lines,'line').then(([line])=>JSON.parse(line)),
    new Promise((_,reject)=>{const timer=setTimeout(()=>reject(new Error('bridge start timeout')),20000);timer.unref();}),
    once(bridgeProcess,'exit').then(()=>{throw new Error('bridge exited before ready');})
  ]);
  const base=`http://127.0.0.1:${ready.port}`;
  log('bridge ready on '+base);
  const session=await (await fetch(base+'/api/manage/session')).json();
  const manage=async payload=>{
    const response=await fetch(base+'/api/companion/passive-browser',{method:'POST',
      headers:{'Content-Type':'application/json','X-Sumika-CSRF':session.csrf},body:JSON.stringify(payload)});
    assert.equal(response.status,200);return response.json();
  };
  const browserAudioStart=async()=>{
    const response=await fetch(base+'/api/companion/browser-audio',{method:'POST',
      headers:{'Content-Type':'application/json','X-Sumika-CSRF':session.csrf},
      body:JSON.stringify({action:'start',consent:true})});
    const result=await response.json();
    assert.equal(response.status,200,'browser audio start: '+JSON.stringify(result));
    return result;
  };
  const worker = browser.serviceWorkers()[0] || await browser.waitForEvent('serviceworker',{timeout:10000});
  worker.on('console',message=>console.log('[extension]',message.text()));
  const tabs=await worker.evaluate(async()=>{
    const found=await chrome.tabs.query({url:'https://www.bilibili.com/video/BVsoak/*'});
    if(found.length!==1)throw new Error('ambiguous original tab');
    return {tab_id:found[0].id};
  });
  const extensionId=new URL(worker.url()).hostname;
  const offer=await worker.evaluate(configuration=>offerConnection(configuration),
    {base,tab_id:tabs.tab_id});
  assert.equal(offer.status,'pending');
  const pending=await manage({action:'pending'});
  assert.equal(pending.requests.length,1);
  // Audio consent is an explicit part of the Sumika approval (P3 bounded audio).
  let grant;
  await manage({action:'approve',request_id:pending.requests[0].request_id,
    consent:true,capture_frame:true,audio:true});
  const pollResult=await worker.evaluate(()=>pollConnection().then(
    value=>value, error=>({error:error.message})));
  log('pollConnection: '+JSON.stringify(pollResult));
  assert.equal(pollResult.status,'running');
  grant=await worker.evaluate(()=>connection.grant);
  assert.equal(grant.audio,true);
  report.checks.production_extension_audio_consent_granted=true;
  log('connection approved with audio consent');
  const videoStatus=await (await fetch(base+'/api/companion/passive-browser',{method:'POST',
    headers:{'Content-Type':'application/json','X-Sumika-CSRF':session.csrf},
    body:JSON.stringify({action:'status'})})).json();
  assert.equal(videoStatus.status,'running');
  await browserAudioStart();
  await worker.evaluate(tabId=>chrome.tabs.sendMessage(tabId,
    {type:'start-audio',consent:true,audio_epoch:connection.grant.audio_epoch}), tabs.tab_id);
  log('browser tab audio recognizer running (vosk pipe mode), capture kicked');
  let audioEpoch = grant.audio_epoch;
  const samples=[];
  const started=Date.now();
  let paused=false;
  let seekCount=0;
  let lastAudioPackets=0;
  let audioPacketsPlateau=0;
  const deadline=started+seconds*1000;
  while (Date.now()<deadline) {
    await new Promise(resolve=>setTimeout(resolve,1000));
    try {
      await fetch(base+'/api/manage/session');
    } catch {
      log('bridge became unreachable');
      report.checks.bridge_unreachable=true;
      break;
    }
    const audioStatus=await (await fetch(base+'/api/companion/browser-audio',{method:'POST',
      headers:{'Content-Type':'application/json','X-Sumika-CSRF':session.csrf},
      body:JSON.stringify({action:'status'})})).json();
    const elapsed=Math.round((Date.now()-started)/1000);
    samples.push({elapsed,audio:audioStatus});
    if (!paused && !audioStatus.alive && !report.checks.audio_stopped_early) {
      report.checks.audio_stopped_early=audioStatus.error||'unknown';
      log('audio track stopped early: '+JSON.stringify(audioStatus));
      break;
    }
    if (pauseAt && elapsed>=pauseAt && !paused) {
      paused=true;
      await page.evaluate(()=>document.querySelector('video').pause());
      const before=audioStatus.queued;
      await new Promise(resolve=>setTimeout(resolve,3000));
      const after=await (await fetch(base+'/api/companion/browser-audio',{method:'POST',
        headers:{'Content-Type':'application/json','X-Sumika-CSRF':session.csrf},
        body:JSON.stringify({action:'status'})})).json();
      // A paused player emits no PCM; the relay must not invent packets.
      assert.ok(after.queued<=1,'paused player still queued packets: '+after.queued);
      report.checks.pause_stops_audio_packets=true;
      log('pause fence verified');
      await page.evaluate(()=>document.querySelector('video').play());
      paused=false;
    }
    if (seekEvery && elapsed % seekEvery === 0 && !paused) {
      seekCount++;
      await page.evaluate(async()=>{
        const video=document.querySelector('video');
        const done=new Promise(resolve=>video.addEventListener('seeked',resolve,{once:true}));
        video.currentTime=Math.max(0,video.currentTime+2);await done;
      });
      // Seek rotates the audio epoch through the extension worker.
      const epoch=await worker.evaluate(()=>connection?.grant?.audio_epoch);
      if (epoch!==audioEpoch) {audioEpoch=epoch;log('audio epoch rotated after seek');}
    }
    if (partChange && elapsed>=partChange && !report.checks.part_change_reconnect) {
      report.checks.part_change_reconnect=true;
      log('switching part (?p=2): reconnect and re-consent required');
      await page.goto('https://www.bilibili.com/video/BVsoak/?p=2');
      await page.evaluate(pageScript, wav);
      await page.waitForFunction('window.__ready === true',{timeout:15000});
      await manage({action:'stop'});
      const offer2=await worker.evaluate(configuration=>offerConnection(configuration),
        {base,tab_id:tabs.tab_id});
      assert.equal(offer2.status,'pending');
      const next=await manage({action:'pending'});
      await manage({action:'approve',request_id:next.requests[0].request_id,
        consent:true,capture_frame:true,audio:true});
      await worker.evaluate(()=>pollConnection());
      await browserAudioStart();
      log('reconnected after part change with fresh consent');
    }
  }
  const finalAudio=await (await fetch(base+'/api/companion/browser-audio',{method:'POST',
    headers:{'Content-Type':'application/json','X-Sumika-CSRF':session.csrf},
    body:JSON.stringify({action:'status'})})).json();
  report.soak={duration_seconds:Math.round((Date.now()-started)/1000),
    audio_status:finalAudio,
    audio_samples:samples.length,
    seek_count:seekCount,
    last_error:finalAudio.error||null};
  // A soak with a speaking lesson must have actually relayed packets
  // (100ms each => ~10/s while playing) and produced real transcripts.
  assert.equal(finalAudio.error,null,'audio track reported: '+finalAudio.error);
  if (!pauseAt) assert.ok(finalAudio.alive,'audio track stopped before soak end');
  assert.ok(samples.length>=seconds/2,'status samples missing');
  assert.ok(finalAudio.received >= seconds*2,
    `expected relayed packets, got ${finalAudio.received}`);
  assert.ok(finalAudio.transcripts >= 1,
    `expected transcripts from the spoken lesson, got ${finalAudio.transcripts}`);
  report.checks.soak_completed_with_healthy_audio_track=true;
  report.checks.tab_audio_relayed_packets=finalAudio.received;
  report.checks.tab_audio_transcripts=finalAudio.transcripts;
  if (muted) report.checks.muted_player_audio_still_captured=true;
  if (subtitles) report.checks.subtitle_cues_present_in_fixture=true;
  else report.checks.no_subtitle_fixture=true;
  report.passed=true;
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
