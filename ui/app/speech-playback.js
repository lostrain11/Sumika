// Explicit playback only; no microphone or model calls.
let active = null;
const controls = new Set();
// A timeout means the outcome is unknown, not that the server stopped work.
function bounded(promise) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(Error('语音服务响应超时')), 15000);
  })]).finally(() => clearTimeout(timer));
}
function render() {
  for (const item of controls) {
    if (!item.button.isConnected) { controls.delete(item); continue; }
    const selected = active?.key === item.key;
    item.button.textContent = selected ? (active.unknown ? '重试停止' : '停止') : '朗读';
    item.button.disabled = !!active && (!selected || !!active.stopping || (active.unknown && !active.id));
    item.button.setAttribute('aria-pressed', String(selected));
    item.button.title = selected ? '停止当前朗读' : '使用已配置的本地语音朗读此回复';
  }
}
function notice(text) {
  const target = document.querySelector('[data-room-history-notice]');
  if (target) target.textContent = text;
}
export async function cancelSpeechPlayback() {
  const request = active;
  if (!request) return;
  if (request.stopping) return request.stopping;
  request.stopRequested = true;
  request.stopping = (async () => {
    if (!request.id) await request.started;
    if (!request.id) throw Error('朗读请求编号未知，请检查服务状态');
    const result = await bounded(request.api('/api/voice/output/cancel', {
      method:'POST', body:JSON.stringify({id:request.id})}));
    if (result.state !== 'cancelled') throw Error('未能确认朗读停止');
    if (active === request) active = null;
    notice('朗读已停止');
  })();
  render();
  try { await request.stopping; }
  catch (error) { request.unknown = true; notice(request.id ? '未能确认朗读停止，请重试停止' : '朗读请求编号未知，请检查服务状态；不会自动重发'); throw error; }
  finally { request.stopping = null; render(); }
}
export function bindSpeechPlayback(button, {key, text, roleId, api}) {
  controls.add({button, key});
  // The caller inserts the node synchronously before this microtask.
  queueMicrotask(render);
  button.addEventListener('click', async () => {
    if (active) {
      if (active.key === key) { try { await cancelSpeechPlayback(); } catch {} }
      return;
    }
    const request = {key, api, id:null, stopRequested:false};
    active = request; render(); notice('正在朗读…');
    try {
      request.started = bounded(api('/api/voice/output/start', {method:'POST',
        body:JSON.stringify({role_id:roleId, text, approved:true})}).then(result => {
          if (!result.id) throw Error('朗读请求编号未知');
          request.id = result.id;
          if (active === request && request.unknown) {
            notice('已取得朗读请求编号，请点击重试停止');
            render();
          }
          return result;
        }));
      await request.started;
      for (let attempt=0; attempt<75; attempt++) {
        if (active !== request || request.stopRequested) return;
        await new Promise(resolve=>setTimeout(resolve,1000));
        if (active !== request || request.stopRequested) return;
        const result = await bounded(api('/api/voice/output?id='+encodeURIComponent(request.id)));
        if (active !== request || request.stopRequested) return;
        if (result.state === 'processing') continue;
        if (['completed','cancelled','error'].includes(result.state)) {
          active = null; notice(result.state === 'completed' ? '朗读完成' : result.state === 'cancelled' ? '朗读已停止' : '朗读失败，请检查语音配置');
          return;
        }
        throw Error('朗读状态未知');
      }
      throw Error('朗读超时');
    } catch (error) {
      if (active !== request) return;
      if (!request.id && error.status === 403) {
        active = null; notice('无法朗读：'+error.message);
      } else {
        request.unknown = true;
        notice(request.id ? '朗读状态未知，请点击重试停止' : '朗读启动结果未知，请检查服务状态；不会自动重发');
      }
    } finally { render(); }
  });
}
