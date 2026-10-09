// Isolated silent playback process, native WASAPI clock probe. No microphone,
// desktop input, paid model, raw PCM storage or daily browser profile.
import assert from 'node:assert/strict';
import {mkdir, writeFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {loadPlaywright} from './lib/playwright.mjs';

const output=resolve(process.argv[2]);
const helper=resolve(process.argv[3]);
const playerMode=process.argv.includes('--player-clock');
await mkdir(output,{recursive:true});
const {chromium}=loadPlaywright();
const browser=await chromium.launchPersistentContext(join(output,'profile'),{
  channel:'msedge',headless:true,args:['--autoplay-policy=no-user-gesture-required']});
const report={passed:false,scope:'Owned headless Edge silent WebAudio -> process loopback -> optional native packet clock. No player-clock or ASR alignment claim.'};
let child;
try {
  const cdp=await browser.browser().newBrowserCDPSession();
  const {processInfo}=await cdp.send('SystemInfo.getProcessInfo');
  const processes=processInfo.filter(item=>item.type==='browser');
  assert.equal(processes.length,1);
  const pid=processes[0].id;
  const page=browser.pages()[0]||await browser.newPage();
  await page.goto('about:blank');
  if(playerMode)await page.evaluate(async()=>{
    // An actual HTML video timeline with a silent audio track. No other tab or
    // media element exists in this owned browser process.
    const canvas=document.createElement('canvas');canvas.width=320;canvas.height=180;
    const painter=canvas.getContext('2d');painter.fillRect(0,0,320,180);
    const audio=new AudioContext();const source=audio.createOscillator();
    const gain=audio.createGain();gain.gain.value=0;
    const destination=audio.createMediaStreamDestination();
    source.connect(gain).connect(destination);source.start();await audio.resume();
    const stream=new MediaStream([...canvas.captureStream(10).getVideoTracks(),...destination.stream.getAudioTracks()]);
    const recorder=new MediaRecorder(stream,{mimeType:'video/webm'}),chunks=[];
    recorder.ondataavailable=e=>chunks.push(e.data);
    const finished=new Promise(resolve=>recorder.onstop=resolve);recorder.start();
    await new Promise(resolve=>setTimeout(resolve,7000));recorder.stop();await finished;
    source.stop();await audio.close();stream.getTracks().forEach(track=>track.stop());
    const video=document.createElement('video');video.width=320;video.height=180;
    video.src=URL.createObjectURL(new Blob(chunks,{type:'video/webm'}));
    document.body.append(video);await video.play();
  });
  else
  await page.evaluate(async()=>{
    const audio=new AudioContext();
    const source=audio.createOscillator();const gain=audio.createGain();
    gain.gain.value=0;source.connect(gain).connect(audio.destination);
    source.start();await audio.resume();globalThis.clockProbeAudio=audio;
  });
  const code=`import sys,json,threading,time,ctypes
from array import array
from extensions.desktop.process_audio import ProcessAudioCapture
from extensions.companion.application_audio import SegmentedApplicationAudioTrack
from extensions.companion.media_clock import PlayerClockCorrelation
from extensions.companion.context_fusion import ContextFusion
from extensions.companion.contracts import ObservationBundle
from dataclasses import replace
from sumika_next.runtime_ownership import process_identity
pid=int(sys.argv[1]); creation=process_identity(pid)
clock=[]; count=[0]; pcm_bytes=[0]; nonzero=[False]
peak=[0];square=[0];sample_count=[0]
frequency=ctypes.c_longlong();ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(frequency))
player_mode=sys.argv[3]=='player'
identity={'url':'owned-local-video','media_instance':1,'timeline_revision':0}
player=PlayerClockCorrelation(target='owned:clock',media_identity=identity,owner_verified=True) if player_mode else None
fusion=ContextFusion()
if player_mode:
    fusion.visual(ObservationBundle.now(source='video-frame',target='owned:clock',valid=True,
        text='local clock lesson',metadata={'media_identity':identity}))
    fusion.bind_player_clock(player)
def qpc():
    counter=ctypes.c_longlong();ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(counter))
    return counter.value*10000000//frequency.value
writing=threading.Lock()
def output(value):
    with writing: print(json.dumps(value),flush=True)
def commands():
    for line in sys.stdin:
        try:
            command=json.loads(line)
            if command['command']=='clock':
                output({'request_id':command['request_id'],'qpc':qpc()})
            elif command['command']=='anchor':
                player.observe(target='owned:clock',media_identity=identity,**command['sample'])
                output({'request_id':command['request_id'],'accepted':True})
        except Exception as error:
            output({'request_id':command.get('request_id'),'error':str(error)})
def timing(value):
    counter=ctypes.c_longlong();ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(counter))
    if value is not None:
        clock.append({**value,'arrival_qpc_100ns':counter.value*10000000/frequency.value})
        del clock[:-1024]
def pcm(value):
    count[0]+=1;pcm_bytes[0]+=len(value);nonzero[0]=nonzero[0] or any(value)
    samples=array('h',value)
    peak[0]=max(peak[0],max(abs(sample) for sample in samples))
    square[0]+=sum(sample*sample for sample in samples);sample_count[0]+=len(samples)
capture=ProcessAudioCapture(sys.argv[2],process_id=pid,creation_time=creation,approved=True)
segments=[]
class OwnedCapture:
    process_id=pid
    creation_time=creation
    def start(self, on_pcm, on_timing=None):
        def forward_timing(value):
            timing(value)
            on_timing(value)
        def forward_pcm(value):
            pcm(value)
            on_pcm(value)
        return capture.start(forward_pcm,on_timing=forward_timing)
    def stop(self): capture.stop()
    def status(self): return capture.status()
class LocalDecoder:
    # This marker is a protocol fixture, never a recognized speech claim.
    def load_model(self): pass
    def _recognize(self,audio,rate,cancelled):
        return 'LOCAL_CLOCK_SEGMENT_FIXTURE'
def transcript(value):
    segments.append(dict(value.metadata))
    if player_mode:
        fusion.audio(replace(value,metadata={**value.metadata,'media_identity':identity}))
track=SegmentedApplicationAudioTrack(OwnedCapture(),LocalDecoder(),target='owned:clock',
    on_transcript=transcript,segment_seconds=1)
result={'passed':False,'pcm_saved':False,'process_id':pid}
try:
    track.start();print('READY',flush=True)
    if player_mode: threading.Thread(target=commands,daemon=True).start()
    threading.Event().wait(5)
    valid=[p for p in clock if p['timestamp_valid'] and p['qpc_position']>0]
    result.update(packets=count[0],pcm_bytes=pcm_bytes[0],nonzero_pcm=nonzero[0],
        peak_pcm16=peak[0],rms_pcm16=(square[0]/max(1,sample_count[0]))**.5,
        clock_packets=len(clock),valid_clock_packets=len(valid),capture_status=capture.status())
    if valid:
        result.update(qpc_span_seconds=(valid[-1]['qpc_position']-valid[0]['qpc_position'])/10000000,
                      packet_clock_samples=[{key:p[key] for key in ('device_position','qpc_position','sample_rate')} for p in valid[:5]],
                      monotonic_qpc=all(b['qpc_position']>=a['qpc_position'] for a,b in zip(valid,valid[1:])),
                      max_arrival_delay_seconds=max((p['arrival_qpc_100ns']-p['qpc_position'])/10000000 for p in valid),
                      discontinuities=sum(bool(p['data_discontinuity']) for p in clock))
    spans=[segment['capture_clock_span'] for segment in segments]
    known=[span for span in spans if span['known']]
    result.update(segment_count=len(spans),known_segment_count=len(known),
        segment_spans=spans,decoder='local-fixture-not-ASR',
        player_time_unknown=all(segment['media_position_known'] is False and segment['media_time_seconds'] is None for segment in segments),
        segment_duration_verified=all(abs((span['end_qpc_position']-span['start_qpc_position'])/10000000-1)<.01 for span in known))
    result['passed']=len(valid)>=2 and result['monotonic_qpc'] and result['qpc_span_seconds']>1 and capture.status()['error'] is None and len(known)>=3 and result['player_time_unknown'] and result['segment_duration_verified']
    if player_mode:
        references=fusion.current().metadata.get('application_audio',[])
        mapped=[reference['metadata'].get('player_clock_span') for reference in references]
        result['player_intervals']=mapped
        result['known_player_intervals']=sum(bool(value and value['known']) for value in mapped)
        result['passed']=result['passed'] and result['known_player_intervals']>=2
        player.revoke()
        result['revoked_player_unknown']=all(not player.correlate(span,target='owned:clock',media_identity=identity)['known'] for span in spans)
        result['passed']=result['passed'] and result['revoked_player_unknown']
finally:
    track.stop();result['stopped']=capture.status()['state']=='stopped'
    result['segment_state_cleared']=not track._clock_coverage.packets and not track._queue and not track._buffer
    result['passed']=result['passed'] and result['stopped'] and result['segment_state_cleared']
    print(json.dumps(result),flush=True)
`;
  child=spawn(process.env.SUMIKA_TEST_PYTHON||'python',['-X','utf8','-B','-c',code,String(pid),helper,playerMode?'player':'native'],
    {cwd:resolve('.'),windowsHide:true,stdio:['pipe','pipe','pipe']});
  let diagnostic='';child.stderr.on('data',data=>{diagnostic+=data;});
  const lines=createInterface({input:child.stdout});
  let result;
  const requests=new Map();let requestId=0;let started;
  const ready=new Promise(resolve=>{started=resolve;});
  lines.on('line',line=>{
    if(line==='READY'){started();return;}
    try {
      const packet=JSON.parse(line);
      if(packet.request_id){requests.get(packet.request_id)?.(packet);requests.delete(packet.request_id);}
      else result=packet;
    }catch{}
  });
  const exited=once(child,'exit');
  const request=async command=>{
    const id=++requestId;
    const response=new Promise(resolve=>requests.set(id,resolve));
    child.stdin.write(JSON.stringify({...command,request_id:id})+'\n');
    const packet=await Promise.race([response,new Promise((_,reject)=>{
      const timer=setTimeout(()=>reject(Error('player clock request timeout')),3000);timer.unref();})]);
    if(packet.error)throw Error(packet.error);
    return packet;
  };
  if(playerMode) {
    await Promise.race([ready,exited.then(()=>{throw Error('probe exited before ready');})]);
    for(let index=0;index<19;index++) {
      const before=await request({command:'clock'});
      const state=await page.evaluate(()=>{
        const video=document.querySelector('video');
        return {media_time_seconds:video.currentTime,playback_rate:video.playbackRate,
          paused:video.paused,seeking:video.seeking,ended:video.ended};
      });
      const after=await request({command:'clock'});
      await request({command:'anchor',sample:{...state,qpc_before:before.qpc,qpc_after:after.qpc}});
      await new Promise(resolve=>setTimeout(resolve,200));
    }
    report.scope='Actual owned HTML video player reads bracketed by native QPC -> native WASAPI segment spans -> production ContextFusion intervals. Local decoder fixture, no ASR/player audio isolation for ordinary browsers or exact synchronization claim.';
  }
  const [exitCode]=await Promise.race([exited,new Promise((_,reject)=>{
    const timer=setTimeout(()=>reject(Error('clock probe timeout')),20000);timer.unref();})]);
  lines.close();
  report.native=result;report.exit_code=exitCode;
  if(!result)report.failure='Native clock probe returned no structured result';
  report.passed=exitCode===0 && result?.passed && result?.stopped;
  // Native/fixture errors contain no credentials or personal browser data.
  if(exitCode!==0)report.diagnostic=diagnostic.slice(-2000);
} catch(error){report.error=String(error.message);}
finally {
  if(child&&child.exitCode===null){child.kill();await once(child,'exit');}
  await browser.close();await writeFile(join(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({...report,evidence:join(output,'report.json')}));
}
if(!report.passed)process.exitCode=2;
