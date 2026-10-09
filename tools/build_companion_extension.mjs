// Assemble the production Sumika companion MV3 extension.
// Sources stay single-copy in extensions/companion; the output is a fixed,
// Bilibili-scoped extension with an explicit user popup. There is no research
// PCM export, no silent installation and no browser policy change.
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';

export async function buildCompanionExtension(directory) {
  directory=resolve(directory);
  await mkdir(directory,{recursive:true});
  const collector=await readFile(new URL('../extensions/companion/browser_video_snapshot.js',import.meta.url),'utf8');
  const audio=await readFile(new URL('../extensions/companion/browser_audio_capture.js',import.meta.url),'utf8');
  const worklet=await readFile(new URL('../extensions/companion/browser_audio_worklet.js',import.meta.url),'utf8');
  const manifest={manifest_version:3,name:'Sumika 陪学连接',version:'1.0.0',
    description:'把当前B站视频页的公开画面、字幕与播放器声音作为学习参考送给本机 Sumika；仅在您每次明确连接后工作。',
    host_permissions:['https://www.bilibili.com/*','https://bilibili.com/*','http://127.0.0.1/*'],
    background:{service_worker:'worker.js'},
    action:{default_popup:'popup.html'},
    content_scripts:[{matches:['https://www.bilibili.com/video/*','https://bilibili.com/video/*'],
      js:['content.js'],run_at:'document_idle',all_frames:false}],
    web_accessible_resources:[{resources:['player-pcm-worklet.js'],
      matches:['https://www.bilibili.com/*','https://bilibili.com/*']}]};
  await writeFile(join(directory,'manifest.json'),JSON.stringify(manifest,null,2));
  await writeFile(join(directory,'player-pcm-worklet.js'),worklet);
  await writeFile(join(directory,'content.js'),`(() => {
const collect=${collector};
const createAudio=${audio};
let epoch=0;
let audioCapture=null;
let audioBusy=false;
let currentAudioEpoch=null;
const send=message=>chrome.runtime.sendMessage(message).catch(()=>{});

// ---- video observation polling (subtitles, clean frames, playback state) ----
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  if(sender.id!==chrome.runtime.id) return;
  if(message?.type==='stop') {epoch++;respond({stopped:true});return;}
  if(message?.type==='start-audio') {
    if(message.consent!==true || typeof message.audio_epoch!=='string') {respond({started:false});return;}
    // Idempotent per epoch: the connect flow and the host re-kick must not
    // restart a live capture (a fresh capture would restart its sequence).
    if(audioCapture && audioCapture.status().state==='recording' && currentAudioEpoch===message.audio_epoch) {
      respond({started:true,already:true});return;
    }
    (async()=>{
      await audioCapture?.stop();
      currentAudioEpoch=message.audio_epoch;
      let restartTimer=null;
      audioCapture=createAudio({consent:true,origin:location.origin,
        readSnapshot:collect,workletUrl:chrome.runtime.getURL('player-pcm-worklet.js'),
        onPcm:packet=>{
          if(audioBusy)throw Error('audio consumer busy');
          audioBusy=true;
          const done=()=>{audioBusy=false;};
          send({type:'audio-packet',sequence:packet.sequence,sample_offset:packet.sample_offset,
                media_identity:packet.media_identity,pcm_base64:btoa(String.fromCharCode(...new Uint8Array(packet.pcm)))})
            .then(result=>{done();if(result?.accepted===false)audioCapture?.stop();})
            .catch(()=>{done();audioCapture?.stop();});
        }});
      await audioCapture.start();
      console.log('[sumika-audio] capture started, epoch', currentAudioEpoch);
      const watch=async()=>{
        // Seek, rate or pause stops capture; the worker rotates the audio
        // epoch and asks this script to restart within the same video.
        const status=audioCapture.status();
        if(status.state!=='recording') {
          console.log('[sumika-audio] capture state', status.state, status.reason||'');
          send({type:'audio-stopped',reason:status.reason||status.state});
          return;
        }
        setTimeout(watch,500);
      };
      watch();
      return {started:true};
    })().then(respond,error=>{console.log('[sumika-audio] start failed:',error.message);respond({started:false,error:error.message});});
    return true;
  }
  if(message?.type==='stop-audio') {
    (async()=>{await audioCapture?.stop();return {stopped:true};})().then(respond);
    return true;
  }
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
  await writeFile(join(directory,'worker.js'),`
let connection=null;
let lastStatus='idle';
let requestedConnection=null;
let audioActive=false;
// One loopback bridge, one approved tab. The popup is the only entry; page
// messages can never start collection or set consent.
function bridgeBase(value) {
  const base=new URL(value);
  if(base.protocol!=='http:' || base.hostname!=='127.0.0.1' || base.username || base.password || base.pathname!=='/' || base.search || base.hash)
    throw new Error('loopback bridge required');
  return base.origin;
}
function baseOrigin(){return connection?.base || requestedConnection?.base || null;}
async function post(path, payload, extra) {
  const headers={'Content-Type':'application/json'};
  const token=connection?.grant?.token;
  if(token)headers.Authorization='Bearer '+token;
  const response=await fetch(baseOrigin()+path,{method:'POST',headers,
    body:JSON.stringify(payload),signal:AbortSignal.timeout(5000),...extra});
  const result=await response.json().catch(()=>null);
  if(!response.ok){
    console.log('[sumika] post '+path+' -> '+response.status+' '+JSON.stringify(result));
    throw new Error('bridge rejected '+path+':'+response.status+(result?.error?':'+result.error:''));
  }
  return result;
}
async function offerConnection(configuration) {
  const base=bridgeBase(configuration.base);
  const tab=await chrome.tabs.get(configuration.tab_id);
  const url=new URL(tab.url);
  if(!['https://www.bilibili.com','https://bilibili.com'].includes(url.origin) || !/^\\/video\\/[A-Za-z0-9]+\\/?$/.test(url.pathname))
    throw new Error('current Bilibili video tab required');
  const part=url.searchParams.get('p');
  // Match the collector's canonical form: ?p= only survives when part > 1.
  const canonical=url.origin+url.pathname+(part && +part>1?'?p='+part:'');
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
  const base=bridgeBase(configuration.base);
  const grant=configuration.grant;
  if(grant.extension_id!==chrome.runtime.id || !Number.isInteger(grant.tab_id) ||
    !['https://www.bilibili.com','https://bilibili.com'].includes(grant.origin)) throw new Error('invalid grant scope');
  await stopConnection();
  const tab=await chrome.tabs.get(grant.tab_id);
  const url=new URL(tab.url);
  if(url.origin!==grant.origin || !url.pathname.startsWith('/video/'))throw new Error('selected video tab changed');
  if(grant.approved_url) {
    const part=url.searchParams.get('p');
    const current=url.origin+url.pathname+(part && +part>1?'?p='+part:'');
    if(current!==grant.approved_url){
      console.log('[sumika] approved_url mismatch:',JSON.stringify(current),'vs',JSON.stringify(grant.approved_url));
      throw new Error('approved video changed; reconnect required');
    }
  }
  const owner=connection={base:base.origin,grant,sequence:0,audio_sequence:0,accepted:0,busy:false,audioBusy:false};
  try {
    const result=await chrome.tabs.sendMessage(grant.tab_id,{type:'start',origin:grant.origin,capture_frame:grant.capture_frame});
    if(!result?.started)throw new Error('collector did not start');
    if(grant.audio) {
      await chrome.tabs.sendMessage(grant.tab_id,{type:'start-audio',consent:true,audio_epoch:grant.audio_epoch});
      audioActive=true;
    }
    lastStatus='running';return {status:lastStatus,tab_id:tab.id,audio:grant.audio===true};
  } catch(error) {if(connection===owner)connection=null;throw error;}
}
async function stopConnection() {
  const old=connection;connection=null;lastStatus='stopped';audioActive=false;
  if(old)try{await chrome.tabs.sendMessage(old.grant.tab_id,{type:'stop'});}catch{}
  try{await chrome.tabs.sendMessage(old.grant.tab_id,{type:'stop-audio'});}catch{}
  return {status:lastStatus};
}
function ownedSender(message,sender,owner) {
  return sender.id===chrome.runtime.id && owner && sender.tab?.id===owner.grant.tab_id &&
    sender.frameId===0 && new URL(sender.url).origin===owner.grant.origin;
}
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  if(sender.id!==chrome.runtime.id)return;
  if(message?.type==='popup-offer') {
    offerConnection({base:message.base,tab_id:message.tabId})
      .then(respond,error=>respond({error:error.message}));
    return true;
  }
  if(message?.type==='popup-poll') {
    (async()=>{
      if(requestedConnection)return {...await pollConnection(),audio:audioActive};
      if(connection)return {status:'running',tab_id:connection.grant.tab_id,audio:audioActive};
      return {status:'stopped',audio:false};
    })().then(respond,error=>respond({error:error.message}));
    return true;
  }
  if(message?.type==='popup-disconnect') {
    cancelRequestedConnection().then(respond,error=>respond({error:error.message}));
    return true;
  }
  const owner=connection;
  if(message?.type==='audio-packet') {
    if(!ownedSender(message,sender,owner) || owner.audioBusy) {respond({accepted:false});return;}
    owner.audioBusy=true;
    (async()=>{
      try {
        const result=await post('/api/companion/passive-browser/audio',{
          tab_id:owner.grant.tab_id,audio_epoch:owner.grant.audio_epoch,
          sequence:message.sequence,media_identity:message.media_identity,
          sample_rate:16000,channels:1,format:'pcm_s16le',
          sample_offset:message.sample_offset,pcm_base64:message.pcm_base64});
        respond({accepted:result?.status==='accepted'});
      } catch {
        // A transport failure stops the audio track only; the approved video
        // connection stays alive for frames, subtitles and heartbeats.
        respond({accepted:false});
      }
      finally {owner.audioBusy=false;}
    })();
    return true;
  }
  if(message?.type==='audio-stopped') {
    if(!ownedSender(message,sender,owner)) {respond({});return;}
    console.log('[sumika] audio stopped:',message.reason);
    // Only player changes (seek/rate/pause) rotate the epoch under the
    // standing consent; transport rejections wait for the host recognizer.
    if(message.reason!=='player_changed') {respond({restarted:false});return;}
    (async()=>{
      const epoch=await post('/api/companion/passive-browser/audio-epoch',{});
      owner.grant.audio_epoch=epoch.audio_epoch;
      await chrome.tabs.sendMessage(owner.grant.tab_id,
        {type:'start-audio',consent:true,audio_epoch:epoch.audio_epoch});
      return {restarted:true};
    })().then(respond,()=>respond({restarted:false}));
    return true;
  }
  if(!['snapshot','heartbeat'].includes(message?.type) || !ownedSender(message,sender,owner) || owner.busy) {
    respond({accepted:false});return;
  }
  owner.busy=true;
  (async()=>{
    try {
      const result=await post('/api/companion/passive-browser/push',
        message.type==='heartbeat'
          ? {tab_id:owner.grant.tab_id,sequence:owner.sequence++,heartbeat:true}
          : {tab_id:owner.grant.tab_id,sequence:owner.sequence++,snapshot:message.snapshot});
      const accepted=result?.status!=='rejected';
      lastStatus=accepted?'running':'rejected';
      if(accepted)owner.accepted++;
      else {connection=null;console.log('[sumika] video push rejected:',JSON.stringify(result));}
      respond({accepted});
    } catch(error) {if(connection===owner){connection=null;lastStatus='network_failed';console.log('[sumika] video push failed:',error.message);}respond({accepted:false});}
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
// If the host recognizer starts after the connection, re-kick capture with
// the current epoch; transport rejections above keep this bounded and quiet.
setInterval(()=>{
  if(connection?.grant?.audio)
    chrome.tabs.sendMessage(connection.grant.tab_id,
      {type:'start-audio',consent:true,audio_epoch:connection.grant.audio_epoch}).catch(()=>{});
},5000);
`);
  await writeFile(join(directory,'popup.html'),`<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><style>
  body{font:14px system-ui,sans-serif;width:260px;margin:0;padding:12px;}
  button{width:100%;margin:4px 0;padding:8px;font-size:14px;}
  #status{margin-top:8px;white-space:pre-line;color:#333;}
</style></head>
<body>
  <strong>Sumika 陪学连接</strong>
  <p id="hint">把当前B站视频页连接到本机 Sumika。画面、字幕与播放器声音只发送到 127.0.0.1，且每次连接都需在 Sumika 中确认。</p>
  <button id="connect">连接本页</button>
  <button id="disconnect">断开</button>
  <div id="status">状态：未连接</div>
  <script src="popup.js"></script>
</body></html>
`);
  await writeFile(join(directory,'popup.js'),`const statusEl=document.getElementById('status');
const BASE='http://127.0.0.1:8765/';
function show(text){statusEl.textContent='状态：'+text;}
function refresh(){
  chrome.runtime.sendMessage({type:'popup-poll'},result=>{
    if(!result){show('扩展状态未知');return;}
    if(result.error){show('错误：'+result.error);return;}
    const audio=result.audio?'（含播放器声音）':'';
    if(result.status==='running')show('运行中'+audio);
    else if(result.status==='pending')show('等待在 Sumika 中确认…');
    else if(result.status==='paused')show('已暂停');
    else show('未连接');
  });
}
document.getElementById('connect').addEventListener('click',()=>{
  chrome.tabs.query({active:true,currentWindow:true},tabs=>{
    const tab=tabs[0];
    if(!tab || !new URL(tab.url||'').hostname.endsWith('bilibili.com')){show('请先打开B站视频页');return;}
    show('正在请求连接…');
    chrome.runtime.sendMessage({type:'popup-offer',base:BASE,tabId:tab.id},result=>{
      if(!result || result.error){show('错误：'+(result?.error||'扩展无响应'));return;}
      show('等待在 Sumika 中确认…');
      setTimeout(refresh,500);
    });
  });
});
document.getElementById('disconnect').addEventListener('click',()=>{
  chrome.runtime.sendMessage({type:'popup-disconnect'},()=>{show('已断开');});
});
refresh();
setInterval(refresh,2000);
`);
  await writeFile(join(directory,'README.md'),`# Sumika 陪学连接（浏览器扩展）

手动安装（开发者模式），不做静默安装、不修改浏览器策略：

1. 解压本目录到任意固定位置。
2. 打开浏览器的扩展管理页（地址输入 \`chrome://extensions\` 或 \`edge://extensions\`）。
3. 打开「开发者模式」，选择「加载解压缩的扩展」，指向本目录。
4. 保持 Sumika 正在运行（默认 127.0.0.1:8765；如端口不同，请修改 popup.js 中的 BASE）。
5. 在B站视频页点击工具栏中的扩展图标，选择「连接本页」，然后在 Sumika 中确认采集范围。
   画面/字幕随画面观察进入学习上下文；播放器声音需在确认时单独勾选授权。

边界：扩展只在 bilibili.com/video 页面运行；所有数据只发往本机 127.0.0.1；
令牌只在内存中，扩展重启后需要重新连接；页面内容永远是参考资料，不会成为工具指令或授权。
`);
  return directory;
}
if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  if(!process.argv[2])throw new Error('output directory required');
  console.log(await buildCompanionExtension(process.argv[2]));
}
