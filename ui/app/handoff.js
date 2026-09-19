import {bridgeFetch as fetch} from './bridge-client.js';
// Personal persisted handoff; native composer still requires an explicit click.
let pending = null;
let draftBusy = false;
async function draftRequest(payload) {
  const options = {};
  if (payload) {
    const response=await fetch('/api/manage/session');
    if(!response.ok)throw new Error('无法验证本地连接');
    options.method='POST';
    options.headers={'Content-Type':'application/json','X-Sumika-CSRF':(await response.json()).csrf};
    options.body=JSON.stringify(payload);
  }
  const response=await fetch('/api/manage/task-draft',options);
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||'交接草稿保存失败');
  return result.draft;
}
const restored = draftRequest().then(value=>{pending=value;publish();}).catch(()=>{});
window.addEventListener('sumika:chat-cleared', async()=>{
  await restored;
  const previous=pending?.id;
  try {
    const remaining=await draftRequest();
    if(pending?.id===previous){pending=remaining;publish();}
  } catch {
    // Do not keep offering a source that the user has cleared locally.
    if(pending?.id===previous){pending=null;publish();}
  }
});
let enhancementEnabled = false;
let settingsRevision = 0;
function publishSettings() {
  const dest=target();
  if(dest)dest.frame.contentWindow.postMessage({type:'sumika:enhancement-settings',enabled:enhancementEnabled},dest.origin);
}
window.addEventListener('sumika:workbench-settings',event=>{
  settingsRevision++;
  enhancementEnabled=event.detail?.enabled===true;
  publishSettings();
});
async function refreshSettings() {
  const revision=++settingsRevision;
  let enabled=false;
  try {
    const response=await fetch('/api/manage/settings');
    if(response.ok)enabled=(await response.json()).data.prompt_enhancement.enabled===true;
  } catch {}
  if(revision!==settingsRevision)return;
  enhancementEnabled=enabled;
  publishSettings();
}
function target() {
  const frame = document.getElementById('sumika-workbench-frame');
  if (!frame?.contentWindow) return null;
  return {frame, origin: new URL(frame.src, location.href).origin};
}
function publish() {
  const dest = target();
  if (dest) dest.frame.contentWindow.postMessage({type:'sumika:task-draft', draft:pending}, dest.origin);
}
window.addEventListener('sumika:prepare-task', async event => {
  const {text, sourceMessageId} = event.detail || {};
  if (typeof text !== 'string' || !text.trim() || typeof sourceMessageId !== 'string') return;
  if(draftBusy)return;
  draftBusy=true;
  try {
    await restored;
    if (pending && !confirm('已有尚未接收的交接草稿，要替换吗？')) return;
    pending = await draftRequest({action:'prepare',source_message_id:sourceMessageId,expected_id:pending?.id||null});
    location.hash = 'board';
    publish();
  } catch(error) {alert(error.message);}
  finally {draftBusy=false;}
});
window.addEventListener('message', async event => {
  const dest = target();
  if (!dest || event.source !== dest.frame.contentWindow || event.origin !== dest.origin) return;
  if (event.data?.type === 'sumika:task-ready') publish();
  if (event.data?.type === 'sumika:task-receive' && pending?.id === event.data.id) {
    try {
      const response=await fetch('/api/manage/session');
      const csrf=(await response.json()).csrf;
      const received=await fetch('/api/manage/task-draft',{method:'POST',headers:{'Content-Type':'application/json','X-Sumika-CSRF':csrf},body:JSON.stringify({action:'receive',id:pending.id,projects:event.data.projects||[],receipts:event.data.receipts||[]})});
      const value=await received.json();
      if(!received.ok) throw new Error(value.error||'交接接收失败');
      pending={...pending,...(value.handoff||{}),state:'received'}; publish();
      event.source.postMessage({type:'sumika:task-received',id:pending.id,handoff:pending},event.origin);
    } catch(error) { event.source.postMessage({type:'sumika:task-receive-error',id:event.data.id,error:error.message},event.origin); }
  }
  if (event.data?.type === 'sumika:enhancement-ready') void refreshSettings();
  if (event.data?.type === 'sumika:task-consumed' && pending?.id === event.data.id) {
    const id=pending.id;
    try {const remaining=await draftRequest({action:'dismiss',id});if(pending?.id===id){pending=remaining;publish();}}
    catch {alert('草稿可能已加入工作台，但接收状态未保存。不会自动发送，请检查当前草稿。');}
  }
});
