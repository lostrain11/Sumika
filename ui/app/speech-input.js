// One-shot microphone input. Recognition fills a draft and never sends a chat.
let active = null;
function renderButton(request) {
  const pending = active === request;
  request.button.disabled = !!request.stopping || (request.stopConfirmed && request.running);
  request.button.textContent = pending ? '■' : '♪';
  request.button.title = pending
    ? (request.stopRequested ? '重试停止语音输入' : '取消语音输入')
    : '录音 5 秒，识别后填入草稿';
}
export async function cancelSpeechInput() {
  const previous = active;
  if (!previous) return;
  if (previous.stopping) return previous.stopping;
  previous.stopRequested = true;
  previous.stopping = (async () => {
    await previous.started;
    if (!previous.id) throw Error('语音请求编号未知，请检查服务状态');
    await previous.api('/api/voice/input/cancel', {method:'POST', body:JSON.stringify({id:previous.id})});
    previous.stopConfirmed = true;
  })();
  renderButton(previous);
  try {
    await previous.stopping;
  } finally {
    previous.stopping = null;
    if (previous.stopConfirmed && !previous.running && active === previous) active = null;
    renderButton(previous);
  }
}

export function bindSpeechInput(button, input, notice, api, role) {
  if (!button || button.dataset.speechBound) return;
  button.dataset.speechBound = 'true';
  button.addEventListener('click', async () => {
    if (active) {
      try { await cancelSpeechInput(); notice.textContent = '录音已取消'; }
      catch { notice.textContent = '未能确认录音已停止，请检查服务状态'; }
      return;
    }
    if (!confirm('使用已选麦克风录音 5 秒并在本机识别？识别文字只填入草稿，不会自动发送。')) return;
    const request = {api, button, role:role(), draft:input.value, id:null, running:true};
    active = request;
    button.textContent = '■'; button.title = '取消语音输入';
    notice.textContent = '正在录音并识别…';
    try {
      request.started = api('/api/voice/input/start', {method:'POST',
        body:JSON.stringify({role_id:request.role, approved:true})}).then(result=>{
          request.id = result.id;
          return result;
        });
      const started = await request.started;
      request.id = started.id;
      if (request.stopRequested) return;
      for (let attempt=0; attempt<75; attempt++) {
        await new Promise(resolve=>setTimeout(resolve,1000));
        if (active !== request || request.stopRequested) return;
        const state = await api('/api/voice/input?id='+encodeURIComponent(request.id));
        if (request.stopRequested) return;
        if (state.state === 'recording') continue;
        if (state.state !== 'completed') throw Error('语音输入未完成，请检查设备和本地识别配置');
        if (role() !== request.role || input.value !== request.draft) {
          notice.textContent = '角色或草稿已变化，未写入识别结果'; return;
        }
        input.value = [request.draft, state.text].filter(Boolean).join(' ');
        input.dispatchEvent(new Event('input', {bubbles:true}));
        notice.textContent = '识别完成，请检查文字后发送'; input.focus();
        return;
      }
      throw Error('语音输入状态未知，请取消后检查服务');
    } catch(error) {
      notice.textContent = error.message;
      if (request.id) {
        try { await cancelSpeechInput(); }
        catch { notice.textContent += '；未能确认停止'; }
      }
    } finally {
      request.running = false;
      if (active === request && (!request.stopRequested || request.stopConfirmed)) active = null;
      renderButton(request);
    }
  });
}
