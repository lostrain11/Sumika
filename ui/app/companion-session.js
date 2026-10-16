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
  // P16: companion profiles (companion-profiles-plan §4). Placement per the
  // confirmed choice: the existing companion detail, no new navigation.
  const profileStatus = document.createElement('p');
  profileStatus.className = 'sumika-form-note'; profileStatus.setAttribute('role', 'status');
  profileStatus.dataset.companionProfiles = '';
  const profileRow = document.createElement('label'); profileRow.className = 'set-row';
  const profileTitle = document.createElement('span'); profileTitle.textContent = '陪伴模式';
  const profileSelect = document.createElement('select'); profileSelect.setAttribute('aria-label', '陪伴模式');
  const behaviorRow = document.createElement('label'); behaviorRow.className = 'set-row';
  const behaviorTitle = document.createElement('span'); behaviorTitle.textContent = '行为记录';
  const behaviorToggle = document.createElement('button');
  behaviorToggle.type = 'button'; behaviorToggle.className = 'mini-btn';
  behaviorToggle.setAttribute('aria-label', '暂停或恢复行为记录');
  behaviorRow.append(behaviorTitle, behaviorToggle);
  const manageButton = document.createElement('button');
  manageButton.type = 'button'; manageButton.className = 'mini-btn';
  manageButton.textContent = '管理模式…';
  manageButton.setAttribute('aria-label', '管理陪伴模式');
  profileRow.append(profileTitle, profileSelect, manageButton);

  let profilesState = null;
  let profileRevision = null;
  let suspendPermissionEdits = false;

  async function loadProfiles() {
    const response = await bridgeFetch('/api/manage/companion-profiles');
    const data = await response.json();
    if (!response.ok) throw Error(data.error || `HTTP ${response.status}`);
    profilesState = data;
    profileRevision = data.revision;
    return data;
  }

  async function loadRuntime() {
    const response = await bridgeFetch('/api/manage/companion-profiles',
      {method: 'POST', headers: {'Content-Type': 'application/json'},
       body: JSON.stringify({action: 'runtime'})});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function profilesRuntimeLine(runtime, data) {
    const reasons = {manual: '手动选择', matched: '自动匹配', ambiguous: '自动匹配存疑',
                     unknown: '未确定', suspended: '已暂停'};
    const reason = reasons[runtime.reason] || runtime.reason || '未知';
    const profiles = data.profiles || [];
    let effective = '无';
    if (runtime.reason === 'manual' && data.manual_profile_id) {
      const found = profiles.find(p => p.id === data.manual_profile_id);
      effective = found ? found.name : '（已删除）';
    } else if (runtime.effective_profile_id) {
      const found = profiles.find(p => p.id === runtime.effective_profile_id);
      effective = found ? found.name : runtime.effective_profile_id;
    }
    return `当前模式：${effective} · ${reason}`;
  }

  async function refreshProfiles() {
    try {
      const data = await loadProfiles();
      const runtime = await loadRuntime().catch(() => ({}));
      profileStatus.textContent = profilesRuntimeLine(runtime, data);
      profileSelect.replaceChildren();
      for (const item of data.profiles || []) {
        const option = document.createElement('option');
        option.value = item.id; option.textContent = item.name;
        profileSelect.append(option);
      }
      const auto = document.createElement('option');
      auto.value = '__auto__'; auto.textContent = '自动匹配';
      profileSelect.append(auto);
      profileSelect.value = data.selection_policy === 'auto'
        ? '__auto__' : (data.manual_profile_id || '');
      // P10: the behavior recording permission drives the pause button.
      try {
        const permissionResponse = await bridgeFetch('/api/manage/behavior',
          {method: 'POST', headers: {'Content-Type': 'application/json'},
           body: JSON.stringify({action: 'permission_status'})});
        const permission = await permissionResponse.json();
        if (permissionResponse.ok) {
          behaviorToggle.textContent = permission.effective.paused
            ? '恢复记录' : '暂停记录';
          behaviorToggle.dataset.paused = permission.effective.paused
            ? 'true' : 'false';
        }
      } catch { behaviorToggle.textContent = '行为记录状态未知'; }
    } catch (error) {
      profileStatus.textContent = `模式状态不可用：${error.message}`;
    }
  }

  function profilesDialog() {
    document.querySelector('dialog.sumika-dialog')?.remove();
    const el = document.createElement('dialog');
    el.className = 'sumika-dialog';
    const head = document.createElement('header');
    const closeBtn = document.createElement('button');
    closeBtn.type = 'button'; closeBtn.textContent = '关闭';
    closeBtn.addEventListener('click', () => el.close());
    head.append(Object.assign(document.createElement('h2'), {textContent: '管理陪伴模式'}), closeBtn);
    el.append(head);
    return el;
  }

  async function openProfilesDialog() {
    suspendPermissionEdits = true;
    const el = profilesDialog();
    let data;
    try { data = await loadProfiles(); }
    catch (error) { suspendPermissionEdits = false; el.remove();
      profileStatus.textContent = `模式列表不可用：${error.message}`; return; }
    const list = document.createElement('ul');
    list.setAttribute('aria-label', '陪伴模式列表');
    for (const item of data.profiles || []) {
      const row = document.createElement('li');
      row.textContent = `${item.name}${item.enabled_for_auto ? '（自动）' : ''}`;
      const editBtn = document.createElement('button');
      editBtn.type = 'button'; editBtn.className = 'mini-btn'; editBtn.textContent = '编辑';
      const dupBtn = document.createElement('button');
      dupBtn.type = 'button'; dupBtn.className = 'mini-btn'; dupBtn.textContent = '复制';
      const delBtn = document.createElement('button');
      delBtn.type = 'button'; delBtn.className = 'mini-btn'; delBtn.textContent = '删除';
      row.append(editBtn, dupBtn, delBtn);
      const editor = document.createElement('div'); editor.hidden = true;
      const nameInput = document.createElement('input');
      nameInput.value = item.name; nameInput.maxLength = 80;
      nameInput.setAttribute('aria-label', '模式名称');
      const scenarioInput = document.createElement('input');
      scenarioInput.value = item.scenario_description || ''; scenarioInput.maxLength = 2000;
      scenarioInput.setAttribute('aria-label', '适用场景描述');
      const instructionsInput = document.createElement('input');
      instructionsInput.value = item.response_instructions || ''; instructionsInput.maxLength = 2000;
      instructionsInput.setAttribute('aria-label', '回应指引');
      const saveBtn = document.createElement('button');
      saveBtn.type = 'button'; saveBtn.textContent = '保存';
      const errorLine = document.createElement('p'); errorLine.className = 'sumika-form-note';
      editor.append(nameInput, scenarioInput, instructionsInput, saveBtn, errorLine);
      editBtn.addEventListener('click', () => { editor.hidden = !editor.hidden; });
      saveBtn.addEventListener('click', async () => {
        saveBtn.disabled = true;
        try {
          const current = await loadProfiles();
          const saved = await endpoint('/api/manage/companion-profiles', {
            action: 'update', profile_id: item.id,
            expected_revision: current.revision,
            changes: {name: nameInput.value,
                      scenario_description: scenarioInput.value,
                      response_instructions: instructionsInput.value}});
          if (saved.status === 'updated') { errorLine.textContent = '已保存'; await refreshProfiles(); }
        } catch (error) { errorLine.textContent = `保存失败：${error.message}`; }
        finally { saveBtn.disabled = false; }
      });
      dupBtn.addEventListener('click', async () => {
        dupBtn.disabled = true;
        try {
          const current = await loadProfiles();
          await endpoint('/api/manage/companion-profiles', {
            action: 'duplicate', profile_id: item.id,
            expected_revision: current.revision});
          el.close(); await openProfilesDialog(); await refreshProfiles();
        } catch (error) { dupBtn.disabled = false;
          errorLine.textContent = `复制失败：${error.message}`; }
      });
      delBtn.addEventListener('click', async () => {
        delBtn.disabled = true;
        try {
          const current = await loadProfiles();
          await endpoint('/api/manage/companion-profiles', {
            action: 'delete', profile_id: item.id,
            expected_revision: current.revision});
          row.remove();
          await refreshProfiles();
        } catch (error) { delBtn.disabled = false;
          errorLine.textContent = `删除失败：${error.message}`; }
      });
      row.append(editor);
      list.append(row);
    }
    const createBtn = document.createElement('button');
    createBtn.type = 'button'; createBtn.textContent = '新建模式';
    createBtn.className = 'mini-btn';
    createBtn.setAttribute('aria-label', '新建陪伴模式');
    const createError = document.createElement('p'); createError.className = 'sumika-form-note';
    createBtn.addEventListener('click', async () => {
      createBtn.disabled = true;
      try {
        const current = await loadProfiles();
        await endpoint('/api/manage/companion-profiles', {
          action: 'create', expected_revision: current.revision,
          profile: {name: `新模式 ${new Date().toLocaleTimeString()}`,
                    enabled_for_auto: false, scenario_description: '',
                    response_instructions: '',
                    settings: {proactive_enabled: false,
                               proactive_interval_seconds: 300,
                               behavior_prompts_enabled: false,
                               context_sources: ['text']}}});
        el.close(); await openProfilesDialog(); await refreshProfiles();
      } catch (error) { createBtn.disabled = false;
        createError.textContent = `新建失败：${error.message}`; }
    });
    el.append(node_p('选择后自动按场景匹配；手动选择优先于自动。'), list,
              createBtn, createError);
    document.body.append(el); el.showModal();
    el.addEventListener('close', () => { el.remove(); suspendPermissionEdits = false; });
  }

  function node_p(text) {
    const p = document.createElement('p'); p.className = 'sumika-form-note';
    p.textContent = text; return p;
  }

  manageButton.addEventListener('click', openProfilesDialog);
  profileSelect.addEventListener('change', async () => {
    if (profileSelect.value === '') return;
    profileSelect.disabled = true;
    try {
      const current = await loadProfiles();
      await endpoint('/api/manage/companion-profiles', {
        action: 'select',
        selection_policy: profileSelect.value === '__auto__' ? 'auto' : 'manual',
        profile_id: profileSelect.value === '__auto__' ? null : profileSelect.value,
        expected_revision: current.revision});
      await refreshProfiles();
    } catch (error) {
      profileStatus.textContent = `模式切换未确认：${error.message}`;
      await refreshProfiles().catch(() => {});
    } finally { profileSelect.disabled = false; }
  });
  behaviorToggle.addEventListener('click', async () => {
    if (behaviorToggle.disabled) return;
    behaviorToggle.disabled = true;
    try {
      const pause = behaviorToggle.dataset.paused !== 'true';
      const current = await bridgeFetch('/api/manage/behavior', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'permission_status'})});
      const state = await current.json();
      await endpoint('/api/manage/behavior', {
        action: pause ? 'permission_pause' : 'permission_resume',
        revision: state.permission.revision});
      status.textContent = pause ? '行为记录已暂停；恢复需手动操作，重启也不会自动恢复。'
                                 : '行为记录已恢复。';
      await refreshProfiles();
    } catch (error) { status.textContent = `行为记录操作未确认：${error.message}`; }
    finally { controls(); }
  });

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
  const browserAudioStatus=document.createElement('p'); browserAudioStatus.className='sumika-form-note';
  browserAudioStatus.setAttribute('role','status'); browserAudioStatus.dataset.browserAudioStatus='';
  browserAudioStatus.hidden=true;
  const captureStatus=document.createElement('p'); captureStatus.className='sumika-form-note';
  captureStatus.setAttribute('role','status'); captureStatus.dataset.captureStatus='';
  const playbackStatus=document.createElement('p'); playbackStatus.className='sumika-form-note';
  playbackStatus.setAttribute('role','status'); playbackStatus.dataset.playbackStatus='';
  let selected = null, captureActive=false, audioActive=false, cursor = 0, timer, working = false, polling = false, epoch = 0, unknown = true, currentState = 'unknown';
  let answer = null, activeTurn = null, playbackSpeaking = false, tabSession = false;
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
  // P06: the explicit danmaku summary entry. There is no automatic periodic
  // summary; the result is audience discussion, never course facts.
  const danmakuButton = command('chara-chat','总结当前弹幕', async () => {
    if (danmakuButton.disabled) return;
    danmakuButton.disabled = true;
    try {
      const result = await endpoint('/api/companion/danmaku', {action:'summarize'});
      if (result.status === 'empty') status.textContent = '当前时间窗内没有待总结的弹幕';
      else if (result.status === 'skipped') status.textContent = `弹幕摘要暂未启动：${result.reason || '后台预算或失败状态'}`;
      else if (result.status === 'started') status.textContent = `正在总结 ${result.entries} 条弹幕（观众讨论，非课程内容）…`;
    } catch (error) { status.textContent = `弹幕摘要失败：${error.message}`; }
    finally { controls(); }
  });
  // P06: save the LAST answer as an explicit note under its frozen source —
  // a page flip after the answer does not change what gets saved. The client
  // supplies no provenance; the server resolves it or fails closed.
  const notesButton = command('act-save','保存当前回答为笔记', async () => {
    if (notesButton.disabled) return;
    notesButton.disabled = true;
    try {
      const result = await endpoint('/api/companion/notes', {action:'save_answer'});
      if (result.status === 'saved') status.textContent = '笔记已保存（含回答时的来源）';
      loadRecentNotes();
    } catch (error) { status.textContent = `笔记保存失败：${error.message}`; }
    finally { controls(); }
  });
  const notesList = document.createElement('details');
  notesList.className = 'companion-notes';
  const notesSummary = document.createElement('summary');
  notesSummary.textContent = '最近笔记';
  notesList.append(notesSummary);
  notesList.addEventListener('toggle', () => { if (notesList.open) loadRecentNotes(); });
  async function loadRecentNotes() {
    try {
      const result = await endpoint('/api/companion/notes', {action:'recent', limit:8});
      notesSummary.textContent = `最近笔记（${result.notes.length}）`;
      for (const note of result.notes || []) {
        const item = document.createElement('p');
        item.className = 'sumika-form-note';
        const where = note.source?.page ? `第 ${note.source.page} 页`
          : note.source?.media_time_seconds != null ? `视频 ${Math.floor(note.source.media_time_seconds)}s`
          : (note.target || '').split(':')[0];
        item.textContent = `${where} · ${note.text.slice(0, 80)}${note.text.length > 80 ? '…' : ''}`;
        notesList.append(item);
      }
    } catch { notesSummary.textContent = '最近笔记（不可用）'; }
  }
  const option = document.createElement('label'); option.className = 'set-row';
  const title = document.createElement('span'); title.textContent = '主动讨论';
  const discussion = document.createElement('input'); discussion.type = 'checkbox'; discussion.checked = true;
  discussion.setAttribute('aria-label','主动讨论'); option.append(title,discussion);
  function controls() {
    start.disabled = working || unknown || currentState !== 'stopped' || captureActive || audioActive || !selected;
    stop.disabled = working || (!unknown && currentState === 'stopped' && !captureActive && !audioActive);
    refresh.disabled = working;
    danmakuButton.disabled = working || unknown || (!captureActive && currentState !== 'running');
    notesButton.disabled = working || unknown || !answer;
    behaviorToggle.disabled = suspendPermissionEdits || working || unknown;
    profileSelect.disabled = suspendPermissionEdits || working || unknown;
    manageButton.disabled = suspendPermissionEdits || unknown;
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
    // P05/F-01: a live Bilibili tab session keeps the companion controls
    // active even though no window capture runs for it.
    if(state.passive?.status==='running') captureActive=true;
    if(state.application_audio) {
      audioActive=state.application_audio.alive;
      const audioLabels={stopped:'已停止',paused:'已暂停',starting:'正在启动',running:'正在采集',stopping:'正在停止',error:'异常'};
      audioStatus.textContent=`应用声音：${audioLabels[state.application_audio.status] || '状态未知'}${state.application_audio.error ? ` · ${state.application_audio.error}` : ''}`;
    } else {audioStatus.textContent='应用声音：状态未知';}
    if(state.browser_audio) {
      const relay=state.browser_audio;
      // P3 capability gaps get explicit wording instead of a bare code.
      const relayGaps={'player audio track unavailable':'该播放器没有可采集的音轨',
        'player audio already active':'采集已在进行',
        'player changed during audio start':'连接期间播放器已变化',
        'player origin changed':'页面来源已变化',
        'media element audio capture unavailable':'该播放器不支持音频采集',
        'unambiguous playing video required':'需要唯一正在播放的视频',
        '16kHz browser audio unavailable':'音频采集初始化失败',
        'player_changed':'播放器已更换或暂停',
        'audio_consumer_overflow':'识别队列溢出，音轨已停止',
        'audio_consumer_failed':'识别进程异常，音轨已停止',
        'invalid_audio_packet':'音频包校验失败，音轨已停止',
        'browser audio queue overflow':'中继队列溢出，音轨已停止'};
      if (relay.alive || relay.error) {
        const relayLabels={starting:'正在连接',running:'正在收音',stopped:'已停止'};
        browserAudioStatus.hidden=false;
        browserAudioStatus.textContent=`网页声音：${relayLabels[relay.status] || '状态未知'}${relay.error ? ` · ${relayGaps[relay.error] || relay.error}` : ''}`;
      } else { browserAudioStatus.hidden=true; browserAudioStatus.textContent=''; }
    } else { browserAudioStatus.hidden=true; browserAudioStatus.textContent=''; }
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
      if (event.event === 'danmaku_summary')
        line(`弹幕讨论（观众讨论，非课程内容）：${event.text || ''}`, 'her');
      if (event.event === 'danmaku_summary_error')
        status.textContent = `弹幕摘要失败：${event.reason || event.error || '未知原因'}`;
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
    if (state.status === 'stopped' && !captureActive) { transcript.replaceChildren(); answer = null; activeTurn = null; }
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
        // P05/F-01: a Bilibili tab target connects through the extension
        // (approve + bounded audio) instead of window capture.
        if(selected?.kind==='tab-pending' || selected?.kind==='tab-live'){
          tabSession=true; captureActive=true;
          if(selected.kind==='tab-pending') {
            await endpoint('/api/companion/passive-browser',{action:'approve',
              request_id:selected.request_id, consent:true, capture_frame:true,
              audio:applicationAudio.checked});
          }
          const deadline=Date.now()+15000;
          while(true) {
            const state=await endpoint('/api/companion/microphone',{action:'status',after:cursor});
            if(state.passive?.status==='running') break;
            if(Date.now()>deadline) throw Error('B站标签页连接未就绪');
            await new Promise(done=>setTimeout(done,300));
          }
          if (payload.mode === 'text') {
            await endpoint('/api/companion/session',{action:'start',mode:'text',
              proactive:payload.proactive});
          } else {
            // Voice on a tab: the mic binds to the published tab observation.
            const micDeadline=Date.now()+15000;
            let micError=null;
            while(Date.now()<micDeadline){
              try { await endpoint('/api/companion/microphone',{action:'start',
                mode:'voice',microphone_consent:true,playback_consent:true,
                proactive:payload.proactive}); micError=null; break; }
              catch(error){ micError=error; await new Promise(done=>setTimeout(done,500)); }
            }
            if(micError) throw micError;
          }
        } else {
        captureActive=true;
        await endpoint('/api/companion/perception',{action:'start',handle:selected.handle,
          process_id:selected.process_id,process_creation:selected.process_creation,consent:true});
        if (payload.mode === 'text') {
          // F-05: the text session applies the proactive settings itself.
          await endpoint('/api/companion/session',{action:'start',mode:'text',
            proactive:payload.proactive});
        }
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
      }
      if(payload.action==='stop') {
        await endpoint('/api/companion/revoke',{});
        if(tabSession){
          await endpoint('/api/companion/passive-browser',{action:'stop'});
          tabSession=false;
        }
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
      // P05/F-01: Bilibili tabs (pending requests and the live connection)
      // are first-class targets in the SAME selector — no second entry.
      try {
        const tabsResponse=await bridgeFetch('/api/companion/passive-browser', {
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({action:'targets'})});
        const tabs=await tabsResponse.json();
        if(tabsResponse.ok) {
          for(const request of tabs.pending || []) {
            const option=document.createElement('option');
            option.value=JSON.stringify({kind:'tab-pending',request_id:request.request_id,
              title:request.title,url:request.url,tab_id:request.tab_id});
            option.textContent=`B站标签页（待确认）：${request.title}`;
            targets.append(option);
          }
          if(tabs.passive?.status==='running' && tabs.passive?.target) {
            const option=document.createElement('option');
            option.value=JSON.stringify({kind:'tab-live',target:tabs.passive.target,
              tab_id:tabs.passive.target, title:'B站标签页（已连接）'});
            option.textContent='B站标签页（已连接）';
            targets.append(option);
          }
        }
      } catch(_) { /* tab targets are additive; windows remain usable */ }
      selected=null; targets.value=''; controls();
    } catch(error) { status.textContent=`窗口列表不可用：${error.message}`; }
    finally { scan.disabled=false; }
  }
  targets.addEventListener('change',()=>{
    selected=targets.value ? JSON.parse(targets.value) : null;
    if(selected?.kind==='tab-pending') {
      scope.textContent=`目标：${selected.title} · 连接后采集画面字幕${applicationAudio.checked?'和标签页声音':''}，不启动窗口画面采集。`;
    } else if(selected?.kind==='tab-live') {
      scope.textContent='目标：B站标签页（已连接） · 采集画面字幕，不启动窗口画面采集。';
    } else {
      scope.textContent=selected ? `目标：${selected.title} · 仅采集窗口画面；应用声音需另行授权。` : '仅采集所选窗口画面；应用声音需另行授权。';
    }
    controls();
  });
  scan.addEventListener('click',loadTargets);
  mode.addEventListener('change',controls);
  // P06/搁置恢复: PDF paste fallback — when the automatic selection is
  // unavailable (selection_unavailable), the user can paste the selected
  // text here. The paste becomes a user-paste observation for Q&A context.
  const pasteRow = document.createElement('details');
  pasteRow.className = 'companion-paste';
  const pasteSummary = document.createElement('summary');
  pasteSummary.textContent = 'PDF 选区粘贴（自动选区不可用时）';
  pasteRow.append(pasteSummary);
  const pasteArea = document.createElement('textarea');
  pasteArea.className = 'companion-paste-input';
  pasteArea.rows = 4;
  pasteArea.placeholder = '从 PDF 复制选中的文字，粘贴到这里作为问答上下文…';
  pasteArea.setAttribute('aria-label', '粘贴 PDF 选区文字');
  const pasteBtn = document.createElement('button');
  pasteBtn.type = 'button'; pasteBtn.className = 'mini-btn';
  pasteBtn.textContent = '作为上下文发送';
  pasteBtn.setAttribute('aria-label', '将粘贴的选区文字作为上下文发送');
  pasteBtn.addEventListener('click', async () => {
    const text = pasteArea.value.trim();
    if (!text) { status.textContent = '请先粘贴选区文字'; return; }
    pasteBtn.disabled = true;
    try {
      const response = await bridgeFetch('/api/companion/paste-context', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text.slice(0, 12000)})});
      const result = await response.json();
      if (!response.ok) throw Error(result.error || `HTTP ${response.status}`);
      status.textContent = '选区文字已作为上下文注入。';
      pasteArea.value = '';
    } catch (error) {
      status.textContent = `上下文注入失败：${error.message}`;
    } finally { pasteBtn.disabled = false; }
  });
  pasteRow.append(pasteArea, pasteBtn);
  section.append(heading,status,targetRow,modeRow,scope,audioRow,audioStatus,browserAudioStatus,captureStatus,playbackStatus,option,commands,transcript,notesList,profileStatus,profileRow,behaviorRow,pasteRow);
  const profilesManageRow = document.createElement('div');
  profilesManageRow.className = 'set-row';
  profilesManageRow.append(manageButton);
  section.append(profilesManageRow);
  host.append(section);
  loadTargets();
  refreshProfiles();
  hydrateIconsAsync(section);
  controls(); poll();
  timer = setInterval(() => {
    if (!section.isConnected) { clearInterval(timer); return; }
    if (!working) poll();
  }, 1000);
  return section;
}
