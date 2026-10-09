import {loadPlaywright} from './lib/playwright.mjs';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {buildPassivePrototype} from './build_passive_browser_prototype.mjs';
import {spawn} from 'node:child_process';
const output=resolve(process.argv[2] || 'E:/SumikaBuild/bilibili-dom-probe');
const audioProbe=process.argv.includes('--audio-track-probe');
const option=name=>{const index=process.argv.indexOf(name);return index<0 ? null : process.argv[index+1];};
const voicePython=option('--voice-python'),sensevoiceModel=option('--sensevoice-model');
if(!!voicePython!==!!sensevoiceModel || (voicePython && !audioProbe))
  throw Error('ASR probe requires --audio-track-probe --voice-python and --sensevoice-model');
await mkdir(output,{recursive:true});
const {chromium}=loadPlaywright();
const extension=audioProbe ? await buildPassivePrototype(resolve(output,'extension'),{audioProbe:true}) : null;
const browser=await chromium.launchPersistentContext(resolve(output,'profile'),{channel:'msedge',headless:true,
  args:['--mute-audio','--autoplay-policy=no-user-gesture-required',
    ...(extension ? [`--disable-extensions-except=${extension}`,`--load-extension=${extension}`] : [])]});
try {
  const page=await browser.newPage();
  await page.goto('https://www.bilibili.com/video/BV1Lf4y1M72V/',{waitUntil:'domcontentloaded',timeout:30000});
  await page.waitForTimeout(4000);
  const result=await page.evaluate(()=>{
    const video=document.querySelector('video');
    video?.pause();
    return {video:!!video,time:video?.currentTime,
      subtitleNodes:[...document.querySelectorAll('[class*="subtitle"]')].slice(0,40).map(element=>({
        tag:element.tagName,cls:element.className,label:element.getAttribute('aria-label'),
        title:element.getAttribute('title'),visible:!!element.getClientRects().length,
        text:element.textContent?.slice(0,200)}))};
  });
  const collector=await readFile('extensions/companion/browser_video_snapshot.js','utf8');
  const sample=()=>page.evaluate(`(${collector})({origin:'https://www.bilibili.com'})`);
  const before=await sample();
  const frameSample=()=>page.evaluate(`(${collector})({origin:'https://www.bilibili.com',capture_frame:true})`);
  const clean=await frameSample();
  await page.evaluate(()=>{
    const overlay=document.createElement('div');
    overlay.id='sumika-overlay-fixture';overlay.textContent='移动弹幕独立图层测试';
    overlay.style.cssText='position:fixed;top:120px;left:200px;color:red;font-size:32px;z-index:999999;pointer-events:none';
    document.body.append(overlay);
  });
  const overlay=await frameSample();
  await page.evaluate(()=>{
    const node=document.querySelector('#sumika-overlay-fixture');
    node.style.left='500px';node.textContent='第二条弹幕测试';
  });
  const moved=await frameSample();
  result.clean_frame={status:clean.frame_status,encoded_bytes:clean.image?.data_base64.length,
    dom_overlay_excluded:!!clean.image && clean.image.data_base64===overlay.image?.data_base64
      && clean.image.data_base64===moved.image?.data_base64};
  await page.evaluate(async()=>{
    const video=document.querySelector('video');
    if(!video || !Number.isFinite(video.duration) || video.duration<20) throw Error('seekable tutorial unavailable');
    await new Promise((done,reject)=>{
      const timeout=setTimeout(()=>reject(Error('video seek timed out')),12000);
      video.addEventListener('seeked',()=>{clearTimeout(timeout);done();},{once:true});
      video.currentTime=15;
    });
  });
  const after=await sample();
  await page.evaluate(async()=>{
    const video=document.querySelector('video');
    await new Promise((done,reject)=>{
      const timeout=setTimeout(()=>reject(Error('small seek timed out')),12000);
      video.addEventListener('seeked',()=>{clearTimeout(timeout);done();},{once:true});
      video.currentTime+=0.05;
    });
  });
  const smallSeek=await sample();
  result.samples={before,after,smallSeek};
  result.checks={pause_reported:before.paused===true,
    clean_video_frame_available:clean.frame_status==='video_element_available',
    dom_overlay_excluded:result.clean_frame.dom_overlay_excluded,
    seek_position_updated:Math.abs(after.media_time_seconds-15)<0.2,
    seek_revision_updated:after.media_identity.timeline_revision>before.media_identity.timeline_revision,
    small_seek_revision_updated:smallSeek.media_identity.timeline_revision>after.media_identity.timeline_revision
      && smallSeek.media_time_seconds-after.media_time_seconds<0.1,
    no_subtitle_never_invents_text:before.subtitles==='' && after.subtitles==='' && !after.valid};
  if(audioProbe) {
    result.player_audio=await page.evaluate(async()=>{
      const video=document.querySelector('video');
      const report={supported:typeof video.captureStream==='function',
        scope:'Selected HTML video stream only; no system/microphone capture, PCM persistence or ASR',samples:[]};
      if(!report.supported)return report;
      let stream,context;
      const original={muted:video.muted,volume:video.volume};
      try {
        video.muted=false;video.volume=0.65;
        await video.play();
        stream=video.captureStream();
        for(let attempt=0;attempt<20 && !stream.getAudioTracks().length;attempt++)
          await new Promise(done=>setTimeout(done,100));
        report.tracks=stream.getAudioTracks().map(track=>({kind:track.kind,
          readyState:track.readyState,muted:track.muted,settings:track.getSettings()}));
        if(!report.tracks.length)return report;
        context=new AudioContext();await context.resume();
        const source=context.createMediaStreamSource(new MediaStream(stream.getAudioTracks()));
        const analyser=context.createAnalyser();analyser.fftSize=2048;source.connect(analyser);
        // No connection to the speakers. --mute-audio independently silences
        // this owned browser's ordinary player output.
        const values=new Float32Array(analyser.fftSize);
        for(const setting of [{name:'normal',muted:false,volume:0.65},
                              {name:'volume_zero',muted:false,volume:0},
                              {name:'player_muted',muted:true,volume:0.65}]) {
          video.muted=setting.muted;video.volume=setting.volume;
          const start=video.currentTime;
          let maxRms=0,nonzero=0;
          for(let index=0;index<30;index++) {
            await new Promise(done=>setTimeout(done,50));
            analyser.getFloatTimeDomainData(values);
            const rms=Math.sqrt(values.reduce((sum,value)=>sum+value*value,0)/values.length);
            maxRms=Math.max(maxRms,rms);if(rms>0.00001)nonzero++;
          }
          report.samples.push({...setting,start,end:video.currentTime,max_rms:maxRms,nonzero_samples:nonzero,
            track_muted:stream.getAudioTracks()[0]?.muted});
        }
        report.audio_available=report.samples[0].nonzero_samples>0;
        report.independent_of_player_volume=report.samples.every(sample=>sample.nonzero_samples>0);
      } catch(error) {report.error=error.name+': '+error.message;}
      finally {
        stream?.getTracks().forEach(track=>track.stop());
        if(context)await context.close();
        video.pause();video.muted=original.muted;video.volume=original.volume;
      }
      return report;
    });
    const worker=browser.serviceWorkers()[0] || await browser.waitForEvent('serviceworker');
    const tab=await worker.evaluate(async()=>{
      const tabs=await chrome.tabs.query({});
      return tabs.find(tab=>tab.url?.startsWith('https://www.bilibili.com/video/'))?.id;
    });
    const send=(type,extra={})=>worker.evaluate(({tab,type,extra})=>
      chrome.tabs.sendMessage(tab,{type:'research-player-audio-'+type,...extra}),{tab,type,extra});
    result.content_audio={consent_rejected:await send('start',{consent:false})};
    await page.evaluate(async()=>{const video=document.querySelector('video');video.muted=true;video.volume=0;await video.play();});
    result.content_audio.start=await send('start',{consent:true,sample_pcm:!!voicePython});
    await page.waitForTimeout(voicePython ? 8000 : 2000);
    result.content_audio.running=await send('status');
    const pcm=voicePython ? await send('take') : null;
    await page.evaluate(()=>document.querySelector('video').pause());
    await page.waitForTimeout(300);
    result.content_audio.paused=await send('status');
    await page.waitForTimeout(500);
    result.content_audio.after_pause=await send('status');
    await send('stop');
    result.checks.content_audio_16k_pcm=result.content_audio.running.sample_rate===16000 &&
      result.content_audio.running.track==='selected-media-element' && result.content_audio.running.nonzero_packets>0;
    result.checks.content_audio_requires_consent=!!result.content_audio.consent_rejected.error;
    result.checks.content_audio_pause_revokes=result.content_audio.paused.state==='unavailable' &&
      result.content_audio.paused.captured_packets===result.content_audio.after_pause.captured_packets;
    result.checks.content_audio_never_invents_position=result.content_audio.running.media_position_known===false;
    if(voicePython){
      const code=`import asyncio,base64,json,sys,time
from extensions.companion.audio_providers import SenseVoicePcmProvider
line=sys.stdin.readline(500001)
if len(line)>500000 or not line.endswith(chr(10)):raise ValueError('bounded sample required')
packet=json.loads(line)
audio=base64.b64decode(packet['pcm_base64'],validate=True)
if packet['sample_rate']!=16000 or not 0<len(audio)<=320000:raise ValueError('bounded 16kHz PCM required')
provider=SenseVoicePcmProvider(sys.argv[1]);began=time.perf_counter();provider.load_model()
text=asyncio.run(provider(audio,sample_rate=16000))
print(json.dumps({'text':text,'audio_seconds':len(audio)/32000,'load_and_asr_ms':round((time.perf_counter()-began)*1000,1),'pcm_persisted':False},ensure_ascii=False))
`;
      result.content_audio.asr=await new Promise((done,reject)=>{
        const child=spawn(voicePython,['-X','utf8','-B','-c',code,sensevoiceModel],{
          cwd:resolve('.'),env:{...process.env,PYTHONPATH:resolve('.')},windowsHide:true,stdio:['pipe','pipe','pipe']});
        let stdout='',stderr='';
        const timer=setTimeout(()=>{child.kill();},30000);
        child.stdout.on('data',chunk=>{stdout+=chunk;});child.stderr.on('data',chunk=>{stderr+=chunk;});
        child.once('error',error=>{clearTimeout(timer);reject(error);});
        child.once('exit',code=>{clearTimeout(timer);if(code!==0)reject(Error('isolated ASR failed: '+stderr.slice(-500)));
          else {try{done(JSON.parse(stdout));}catch(error){reject(error);}}});
        child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify(pcm)+'\n');
      });
      result.checks.content_audio_asr=!!result.content_audio.asr.text.trim();
    }
  }
  result.passed=Object.values(result.checks).every(Boolean);
  await writeFile(resolve(output,'report.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
  if(!result.passed) throw Error('Bilibili probe checks failed');
} finally {await browser.close();}
