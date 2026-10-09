// Generate an isolated research extension; no installed-browser changes or UI.
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';

export async function buildPassivePrototype(directory,{audioProbe=false}={}) {
  directory=resolve(directory);
  await mkdir(directory,{recursive:true});
  const collector=await readFile(new URL('../extensions/companion/browser_video_snapshot.js',import.meta.url),'utf8');
  const manifest={manifest_version:3,name:'Sumika passive connector research',version:'0.0.1',
    host_permissions:['https://www.bilibili.com/*','https://bilibili.com/*','http://127.0.0.1/*'],
    background:{service_worker:'worker.js'},
    content_scripts:[{matches:['https://www.bilibili.com/video/*','https://bilibili.com/video/*'],
      js:['content.js'],run_at:'document_idle',all_frames:false}]};
  if(audioProbe)manifest.web_accessible_resources=[{resources:['player-pcm-worklet.js'],
    matches:['https://www.bilibili.com/*','https://bilibili.com/*']}];
  await writeFile(join(directory,'manifest.json'),JSON.stringify(manifest,null,2));
  await writeFile(join(directory,'content.js'),`(() => {
const collect=${collector};
let epoch=0;
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  if(sender.id!==chrome.runtime.id) return;
  if(message?.type==='stop') {epoch++;respond({stopped:true});return;}
  if(message?.type!=='start' || message.origin!==location.origin || typeof message.capture_frame!=='boolean') return;
  const owner=++epoch;
  let tick=0;
  let previousState=null;
  let previousContent=null;
  const poll=async()=>{
    if(owner!==epoch)return;
    try {
      tick++;
      const state=collect({origin:message.origin,capture_frame:false});
      if(!state.ok) {epoch++;return;}
      const signature=JSON.stringify({identity:state.media_identity,subtitles:state.subtitles,
        paused:state.paused,ended:state.ended,seeking:state.seeking,rate:state.playback_rate});
      const changed=signature!==previousState;
      const full=changed || tick===1 || (message.capture_frame && tick%5===0);
      const snapshot=full ? (message.capture_frame ? collect({origin:message.origin,capture_frame:true}) : state) : null;
      if(full && !snapshot.ok) {epoch++;return;}
      const content=snapshot ? JSON.stringify({state:signature,image:snapshot.image,
        frame_status:snapshot.frame_status,danmaku:(snapshot.danmaku||[]).map(item=>item.text)}) : previousContent;
      const upload=full && content!==previousContent;
      const result=await chrome.runtime.sendMessage(upload ? {type:'snapshot',snapshot} : {type:'heartbeat'});
      if(!result?.accepted) {epoch++;return;}
      previousState=signature;
      if(upload)previousContent=content;
    } catch {epoch++;return;}
    if(owner===epoch)setTimeout(poll,1000);
  };
  respond({started:true});poll();
});
})();`);
  if(audioProbe) {
    const audio=await readFile(new URL('../extensions/companion/browser_audio_capture.js',import.meta.url),'utf8');
    const worklet=await readFile(new URL('../extensions/companion/browser_audio_worklet.js',import.meta.url),'utf8');
    await writeFile(join(directory,'player-pcm-worklet.js'),worklet);
    const content=await readFile(join(directory,'content.js'),'utf8');
    await writeFile(join(directory,'content.js'),content+`\n(() => {
const collect=${collector};
const create=${audio};
let capture=null;
let metrics={packets:0,nonzero_packets:0,max_rms:0};
let samples=[],sampleEnabled=false;
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  if(sender.id!==chrome.runtime.id || !message?.type?.startsWith('research-player-audio-'))return;
  (async()=>{
    if(message.type==='research-player-audio-start') {
      await capture?.stop();metrics={packets:0,nonzero_packets:0,max_rms:0};
      samples=[];sampleEnabled=message.sample_pcm===true;
      capture=create({consent:message.consent,origin:location.origin,readSnapshot:collect,
        workletUrl:chrome.runtime.getURL('player-pcm-worklet.js'),onPcm:packet=>{
          const pcm=new Int16Array(packet.pcm.buffer);let sum=0;
          for(const value of pcm)sum+=(value/32768)**2;
          const rms=Math.sqrt(sum/pcm.length);
          metrics.packets++;if(rms>0.00001)metrics.nonzero_packets++;
          metrics.max_rms=Math.max(metrics.max_rms,rms);
          metrics.sample_rate=packet.sample_rate;metrics.track=packet.track;
          metrics.media_position_known=packet.media_position_known;
          if(sampleEnabled){
            if(samples.length>=100)throw Error('research PCM sample budget exceeded');
            samples.push(packet.pcm);
          }
        }});
      await capture.start();
    } else if(message.type==='research-player-audio-take'){
      let binary='';for(const sample of samples)for(const byte of sample)binary+=String.fromCharCode(byte);
      samples=[];sampleEnabled=false;
      return {pcm_base64:btoa(binary),sample_rate:16000};
    } else if(message.type==='research-player-audio-stop'){await capture?.stop();samples=[];sampleEnabled=false;}
    else if(message.type!=='research-player-audio-status')throw Error('unknown research action');
    return {...metrics,...capture?.status(),captured_packets:metrics.packets};
  })().then(respond,error=>respond({error:error.message,...metrics,...capture?.status()}));
  return true;
});
})();`);
  }
  await writeFile(join(directory,'worker.js'),`
let connection=null;
let lastStatus='idle';
let requestedConnection=null;
// Prototype configuration is invoked only by an owned-browser test harness.
// No externally_connectable, page messages, UI or persisted bearer secret.
function bridgeBase(value) {
  const base=new URL(value);
  if(base.protocol!=='http:' || base.hostname!=='127.0.0.1' || base.username || base.password || base.pathname!=='/' || base.search || base.hash)
    throw new Error('loopback bridge required');
  return base.origin;
}
async function offerConnection(configuration) {
  const base=bridgeBase(configuration.base);
  const tab=await chrome.tabs.get(configuration.tab_id);
  const url=new URL(tab.url);
  if(!['https://www.bilibili.com','https://bilibili.com'].includes(url.origin) || !/^\\/video\\/[A-Za-z0-9]+\\/?$/.test(url.pathname))
    throw new Error('current Bilibili video tab required');
  // Drop tracking parameters. Only the selected part participates in identity.
  const part=url.searchParams.get('p');
  const canonical=url.origin+url.pathname+(part && /^[1-9][0-9]{0,5}$/.test(part)?'?p='+part:'');
  await cancelRequestedConnection();
  const response=await fetch(base+'/api/companion/passive-browser/request',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({tab_id:tab.id,origin:url.origin,title:(tab.title||'').slice(0,512),url:canonical}),
    signal:AbortSignal.timeout(5000)});
  if(!response.ok)throw new Error('connection request rejected:'+response.status);
  const receipt=await response.json();
  requestedConnection={base,tab_id:tab.id,receipt:{request_id:receipt.request_id,receipt:receipt.receipt}};
  return {status:receipt.status,tab_id:tab.id};
}
async function pollConnection() {
  const pending=requestedConnection;
  if(!pending)throw new Error('connection request unavailable');
  const response=await fetch(pending.base+'/api/companion/passive-browser/receipt',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pending.receipt),
    signal:AbortSignal.timeout(5000)});
  if(!response.ok)throw new Error('connection receipt rejected:'+response.status);
  const result=await response.json();
  if(requestedConnection!==pending)throw new Error('connection request superseded');
  if(result.status==='approved' && connection?.grant.token!==result.grant.token)
    return startConnection({base:pending.base,grant:result.grant});
  return {status:result.status};
}
async function cancelRequestedConnection() {
  const pending=requestedConnection;requestedConnection=null;
  await stopConnection();
  if(pending) {
    const response=await fetch(pending.base+'/api/companion/passive-browser/cancel',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pending.receipt),
      signal:AbortSignal.timeout(5000)});
    if(!response.ok && response.status!==403)throw new Error('connection withdrawal failed');
  }
  return {status:'stopped'};
}
async function startConnection(configuration) {
  const base=new URL(configuration.base);
  if(base.protocol!=='http:' || base.hostname!=='127.0.0.1' || base.username || base.password || base.pathname!=='/' || base.search || base.hash)
    throw new Error('loopback bridge required');
  const grant=configuration.grant;
  if(grant.extension_id!==chrome.runtime.id || !Number.isInteger(grant.tab_id) ||
    !['https://www.bilibili.com','https://bilibili.com'].includes(grant.origin)) throw new Error('invalid grant scope');
  await stopConnection();
  const tab=await chrome.tabs.get(grant.tab_id);
  const url=new URL(tab.url);
  if(url.origin!==grant.origin || !url.pathname.startsWith('/video/'))throw new Error('selected video tab changed');
  if(grant.approved_url) {
    const part=url.searchParams.get('p');
    const current=url.origin+url.pathname+(part && /^[1-9][0-9]{0,5}$/.test(part)?'?p='+part:'');
    if(current!==grant.approved_url)throw new Error('approved video changed; reconnect required');
  }
  const owner=connection={base:base.origin,grant,sequence:0,accepted:0,frames:0,heartbeats:0,busy:false};
  try {
    const result=await chrome.tabs.sendMessage(grant.tab_id,{type:'start',origin:grant.origin,capture_frame:grant.capture_frame});
    if(!result?.started)throw new Error('collector did not start');
    lastStatus='running';return {status:lastStatus,tab_id:tab.id,window_id:tab.windowId};
  } catch(error) {if(connection===owner)connection=null;throw error;}
}
async function stopConnection() {
  const old=connection;connection=null;lastStatus='stopped';
  if(old)try{await chrome.tabs.sendMessage(old.grant.tab_id,{type:'stop'});}catch{}
  return {status:lastStatus};
}
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  const owner=connection;
  if(!['snapshot','heartbeat'].includes(message?.type) || sender.id!==chrome.runtime.id || !owner ||
    sender.tab?.id!==owner.grant.tab_id || sender.frameId!==0 ||
    new URL(sender.url).origin!==owner.grant.origin || owner.busy) {
    respond({accepted:false});return;
  }
  owner.busy=true;
  (async()=>{
    try {
      const response=await fetch(owner.base+'/api/companion/passive-browser/push',{
        method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+owner.grant.token},
        body:JSON.stringify(message.type==='heartbeat'
          ? {tab_id:owner.grant.tab_id,sequence:owner.sequence++,heartbeat:true}
          : {tab_id:owner.grant.tab_id,sequence:owner.sequence++,snapshot:message.snapshot}),
        signal:AbortSignal.timeout(5000)});
      if(connection!==owner) {respond({accepted:false});return;}
      const result=response.ok ? await response.json() : null;
      const accepted=response.ok && result?.status!=='rejected';
      lastStatus=accepted?'running':'rejected:'+response.status;
      if(accepted){owner.accepted++;if(message.type==='heartbeat')owner.heartbeats++;else owner.frames++;}
      if(!accepted)connection=null;
      respond({accepted});
    } catch {if(connection===owner){connection=null;lastStatus='network_failed';}respond({accepted:false});}
    finally {owner.busy=false;}
  })();
  return true;
});
chrome.tabs.onRemoved.addListener(tab=>{
  if(requestedConnection?.tab_id===tab)cancelRequestedConnection().catch(()=>{});
  else if(connection?.grant.tab_id===tab)stopConnection();
});
chrome.tabs.onUpdated.addListener((tab,change)=>{
  if(requestedConnection?.tab_id===tab && change.url)cancelRequestedConnection().catch(()=>{});
  else if(connection?.grant.tab_id===tab && change.url)stopConnection();
});
`);
  await writeFile(join(directory,'README.txt'),'Isolated MV3 research prototype. Fixed passive collector only. Configure via owned-browser verifier; no production consent UI or extension installation. Service worker restart drops grant and requires explicit reauthorization. Never persist tokens.\n');
  return directory;
}
if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  if(!process.argv[2])throw new Error('isolated output directory required');
  console.log(await buildPassivePrototype(process.argv[2]));
}
