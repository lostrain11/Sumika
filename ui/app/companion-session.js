import {bridgeFetch} from './bridge-client.js';
import {hydrateIconsAsync} from './icons.js';

async function call(payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 35000);
  try {
    const response = await bridgeFetch('/api/companion/microphone', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload), signal:controller.signal,
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || `HTTP ${response.status}`);
    return result;
  } finally { clearTimeout(timer); }
}
async function endpoint(path, payload) {
  const controller=new AbortController(); const timer=setTimeout(()=>controller.abort(),35000);
  try {
    const response = await bridgeFetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload),signal:controller.signal});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || `HTTP ${response.status}`);
    return result;
  } finally {clearTimeout(timer);}
}

export function mountCompanionSession(host) {
  const section = document.createElement('section');
  section.dataset.companionSession = ''; section.className='companion-session';
  const heading = document.createElement('h3');
  heading.textContent = '陪学会话';
  const status = document.createElement('p');
  status.className = 'sumika-form-note'; status.setAttribute('role','status');
  const commands = document.createElement('div');
  commands.className = 'companion-commands';
  function command(symbol, label, action) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'mini-btn';
    button.title = label; button.setAttribute('aria-label', label);
    const icon = document.createElement('i'); icon.dataset.icon = symbol; icon.dataset.iconSize = '16';
    button.append(icon); button.addEventListener('click', action); commands.append(button);
    return button;
  }
  const transcript = document.createElement('div');
  transcript.className = 'companion-transcript'; transcript.setAttribute('aria-live','polite');
  const targetRow = document.createElement('label'); targetRow.className = 'set-row';
  const targetLabel = document.createElement('span'); targetLabel.textContent = '学习窗口';
  const targets = document.createElement('select'); targets.setAttribute('aria-label','学习窗口');
  const emptyTarget = document.createElement('option'); emptyTarget.value=''; emptyTarget.textContent='请选择窗口'; targets.append(emptyTarget);
  const scan = document.createElement('button'); scan.type='button'; scan.className='mini-btn'; scan.textContent='刷新'; scan.title='刷新窗口列表';
  targetRow.append(targetLabel,targets,scan);
  const modeRow=document.createElement('label');modeRow.className='set-row';
  const modeTitle=document.createElement('span');modeTitle.textContent='交流模式';
  const mode=document.createElement('select');mode.setAttribute('aria-label','交流模式');
  for(const [value,text] of [['text','文字'],['voice','连续语音']]) {
    const item=document.createElement('option');item.value=value;item.textContent=text;mode.append(item);
  }
  modeRow.append(modeTitle,mode);
  const scope = document.createElement('p'); scope.className='sumika-form-note'; scope.textContent='仅采集所选窗口画面、可见正文与选中片段；应用声音需另行授权。';
  const audioRow=document.createElement('label'); audioRow.className='set-row';
  const audioLabel=document.createElement('span'); audioLabel.textContent='采集应用声音';
  const applicationAudio=document.createElement('input'); applicationAudio.type='checkbox';
  applicationAudio.setAttribute('aria-label','采集应用声音'); audioRow.append(audioLabel,applicationAudio);
  const audioStatus=document.createElement('p'); audioStatus.className='sumika-form-note';
  audioStatus.setAttribute('role','status'); audioStatus.dataset.applicationAudioStatus='';
  const captureStatus=document.createElement('p'); captureStatus.className='sumika-form-note';
  captureStatus.setAttribute('role','status'); captureStatus.dataset.captureStatus='';
  const playbackStatus=document.createElement('p'); playbackStatus.className='sumika-form-note';
  playbackStatus.setAttribute('role','status'); playbackStatus.dataset.playbackStatus='';
  let selected = null, captureActive=false, audioActive=false, cursor = 0, timer, working = false, polling = false, epoch = 0, unknown = true, currentState = 'unknown';
  let answer = null, activeTurn = null, playbackSpeaking = false;
  const labels = {stopped:'已停止',starting:'正在启动',listening:'正在聆听',stopping:'正在停止',error:'服务异常'};
  const start = command('chara-voice','开始陪学', async () => {
    if (working || unknown || currentState !== 'stopped') return;
    if (!confirm(`采集「${selected?.title || ''}」的窗口画面？${mode.value==='voice' ? '使用已选麦克风持续识别提问，并播放角色回答。' : '文字交流，不使用麦克风或朗读。'}画面会发送给已配置角色模型；${applicationAudio.checked ? '同时采集该应用进程声音，转写将作为角色参考内容，与麦克风提问分开处理。' : '应用声音不采集。'}`)) return;
    if (!selected) return;
    await mutate({action:'start',mode:mode.value,microphone_consent:mode.value==='voice',playback_consent:mode.value==='voice',
      process_id:selected.process_id, handle:selected.handle, process_creation:selected.process_creation,
      proactive:{enabled:discussion.checked,interval_seconds:120}});
  });
  const stop = command('lucide:square','停止陪学', () => mutate({action:'stop'}));
  const refresh = command('act-refresh','刷新会话状态', () => poll());
  const option = document.createElement('label'); option.className = 'set-row';
  const title = document.createElement('span'); title.textContent = '主动讨论';
  const discussion = document.createElement('input'); discussion.type = 'checkbox'; discussion.checked = true;
  discussion.setAttribute('aria-label','主动讨论'); option.append(title,discussion);
  function controls() {
    start.disabled = working || unknown || currentState !== 'stopped' || captureActive || audioActive || !selected;
    stop.disabled = working || (!unknown && currentState === 'stopped' && !captureActive && !audioActive);
    refresh.disabled = working;
    discussion.disabled = working || unknown || captureActive || currentState !== 'stopped';
    mode.disabled=working || unknown || captureActive || audioActive || currentState!=='stopped';
    targets.disabled = working || captureActive || currentState !== 'stopped';
    scan.disabled = working || captureActive || currentState !== 'stopped';
    applicationAudio.disabled=working || unknown || captureActive || audioActive || currentState!=='stopped';
  }
  function line(text, who) {
    const paragraph = document.createElement('p'); paragraph.dataset.who = who;
    paragraph.textContent = text; transcript.append(paragraph);
    while (transcript.childElementCount > 12) transcript.firstElementChild.remove();
    return paragraph;
  }
  function render(state) {
    unknown = false; currentState = state.status;
    if (state.capture) {
      captureActive=state.capture.alive;
      const captureLabels={stopped:'已停止',starting:'正在启动',running:'正在采集',paused:'已暂停',stopping:'正在停止',error:'异常'};
      captureStatus.textContent=`画面：${captureLabels[state.capture.status] || '状态未知'}${state.capture.error ? ` · ${state.capture.error}` : ''}`;
    } else {captureStatus.textContent='画面：状态未知';}
    if(state.application_audio) {
      audioActive=state.application_audio.alive;
      const audioLabels={stopped:'已停止',paused:'已暂停',starting:'正在启动',running:'正在采集',stopping:'正在停止',error:'异常'};
      audioStatus.textContent=`应用声音：${audioLabels[state.application_audio.status] || '状态未知'}${state.application_audio.error ? ` · ${state.application_audio.error}` : ''}`;
    } else {audioStatus.textContent='应用声音：状态未知';}
    status.textContent = `${state.status==='stopped' && captureActive ? '正在观察 · 文字交流' : labels[state.status] || '状态未知'}${state.target ? ` · ${state.target}` : ''}`;
    let speaking = playbackSpeaking;
    for (const event of state.events || []) {
      if (event.sequence <= cursor) continue;
      if (event.event === 'user_started' || event.event === 'proactive_started' || event.event === 'discuss_started') {
        if (answer) answer.remove();
        answer = null; activeTurn = event.turn ?? null;
      }
      const current = event.turn == null || activeTurn == null || event.turn === activeTurn;
      if (!current) continue;
      if (event.event === 'transcribed') line(event.text, 'me');
      if (event.event === 'delta') {
        answer ||= line('', 'her');
        answer.textContent = (answer.textContent + (event.text || '')).slice(-64000);
      }
      if (event.event === 'proactive_text') line(`主动讨论：${event.text || ''}`, 'her');
      if (event.event === 'playback_started') speaking = true;
      if (event.event === 'playback_ended') { speaking = false; answer = null; }
      if (event.event === 'interrupted' || event.event === 'error') {
        if (answer) answer.remove();
        answer = null;
      }
      if (event.event === 'error') status.textContent = `回答失败：${event.reason || '未知原因'}`;
      if (event.event === 'coordinator_failed') status.textContent = `陪学协调器已停止：${event.reason || '未知原因'}；请重新开始会话`;
    }
    playbackSpeaking = speaking;
    playbackStatus.textContent = `朗读：${speaking ? '正在朗读' : '空闲'}`;
    cursor = state.cursor ?? cursor;
    if (state.status === 'stopped') { transcript.replaceChildren(); answer = null; activeTurn = null; }
    controls();
  }
  async function poll() {
    if (!section.isConnected || working || polling) return;
    polling = true;
    const token = epoch;
    try {
      const state = await call({action:'status',after:cursor});
      if (token === epoch && section.isConnected) render(state);
    } catch (error) {
      if (token === epoch && section.isConnected) {
        unknown = true; status.textContent = `状态无法确认：${error.message}`; controls();
      }
    } finally { polling = false; }
  }
  async function mutate(payload) {
    if (working) return;
    epoch += 1;
    working = true; controls();
    try {
      if (payload.action === 'start') {
        captureActive=true;
        await endpoint('/api/companion/perception',{action:'start',handle:selected.handle,
          process_id:selected.process_id,process_creation:selected.process_creation,consent:true});
        const deadline=Date.now()+15000;
        while(true) {
          const capture=await endpoint('/api/companion/perception',{action:'status'});
          if(capture.status==='running' && capture.observations>0) break;
          if(capture.status==='error' || !capture.alive || Date.now()>deadline) throw Error('窗口画面采集未就绪');
          await new Promise(done=>setTimeout(done,200));
        }
        if(applicationAudio.checked) {
          audioActive=true;
          await endpoint('/api/companion/audio',{action:'start',consent:true,
            process_id:selected.process_id,process_creation:selected.process_creation});
        }
      }
      if(payload.action==='stop') {
        await endpoint('/api/companion/revoke',{});
        captureActive=false;
        audioActive=false;
      }
      render(await call(payload.action==='start' && payload.mode==='text' ? {action:'status',after:cursor} : payload));
    }
    catch (error) {
      unknown = true; status.textContent = `操作结果未确认：${error.message}`;
      // Status is read-only; never replay an uncertain start or stop request.
    } finally { working = false; controls(); }
  }
  async function loadTargets() {
    scan.disabled=true;
    try {
      const response=await bridgeFetch('/api/companion/windows');
      const data=await response.json();
      if(!response.ok) throw Error(data.error || '窗口列表不可用');
      targets.replaceChildren(emptyTarget);
      for(const value of data.windows || []) {
        const option=document.createElement('option'); option.value=JSON.stringify(value);
        option.textContent=value.title; targets.append(option);
      }
      selected=null; targets.value=''; controls();
    } catch(error) { status.textContent=`窗口列表不可用：${error.message}`; }
    finally { scan.disabled=false; }
  }
  targets.addEventListener('change',()=>{
    selected=targets.value ? JSON.parse(targets.value) : null;
    scope.textContent=selected ? `目标：${selected.title} · 仅采集窗口画面；应用声音需另行授权。` : '仅采集所选窗口画面；应用声音需另行授权。';
    controls();
  });
  scan.addEventListener('click',loadTargets);
  mode.addEventListener('change',controls);
  section.append(heading,status,targetRow,modeRow,scope,audioRow,audioStatus,captureStatus,playbackStatus,option,commands,transcript); host.append(section);
  loadTargets();
  hydrateIconsAsync(section);
  controls(); poll();
  timer = setInterval(() => {
    if (!section.isConnected) { clearInterval(timer); return; }
    if (!working) poll();
  }, 1000);
  return section;
}
