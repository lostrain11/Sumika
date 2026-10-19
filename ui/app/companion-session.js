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
    if (!response.ok) { const error = Error(result.error || `HTTP ${response.status}`); error.status = response.status; throw error; }
    return result;
  } finally { clearTimeout(timer); }
}
async function endpoint(path, payload) {
  const controller=new AbortController(); const timer=setTimeout(()=>controller.abort(),35000);
  try {
    const response = await bridgeFetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload),signal:controller.signal});
    const result = await response.json();
    if (!response.ok) { const error = Error(result.error || `HTTP ${response.status}`); error.status = response.status; throw error; }
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
  let lastRuntimeRefresh = 0;

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
    if (runtime.effective_profile_id) {
      const found = profiles.find(p => p.id === runtime.effective_profile_id);
      effective = found ? found.name : '（已删除）';
    }
    const candidate = profiles.find(p => p.id === runtime.candidate_profile_id);
    return `当前模式：${effective} · ${reason}${candidate ? ` · 候选：${candidate.name}` : ''}${runtime.target_identity ? ` · 目标：${typeof runtime.target_identity === 'string' ? runtime.target_identity : JSON.stringify(runtime.target_identity)}` : ''}${runtime.unavailable_preferences?.length ? ` · 不可用参考：${runtime.unavailable_preferences.join('、')}` : ''}`;
  }

  async function refreshProfiles() {
    try {
      const data = await loadProfiles();
      const runtime = await loadRuntime();
      profileStatus.textContent = profilesRuntimeLine(runtime, data);
      profileSelect.replaceChildren();
      for (const item of data.profiles || []) {
        const option = document.createElement('option');
        option.value = item.id; option.textContent = item.name;
        profileSelect.append(option);
      }
      const neutral = document.createElement('option'); neutral.value = ''; neutral.textContent = '待选择（普通聊天可用）'; profileSelect.prepend(neutral);
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
            ? '解除暂停' : '暂停观察';
          behaviorToggle.title = permission.effective.can_record ? '行为记录许可已开启' : '行为记录未获许可；解除暂停不会开启许可';
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
    let expectedRevision = data.revision;
    const list = document.createElement('ul'); list.className = 'companion-profile-list';
    list.setAttribute('aria-label', '陪伴模式列表');
    const dialogStatus = node_p('设置只表达参考偏好，画面、声音及行为许可请在连接与权限中管理。安静模式仍可参与已获许可的自动匹配。');
    const write = async payload => {
      const saved = await endpoint('/api/manage/companion-profiles', {...payload, expected_revision: expectedRevision});
      const fresh = await loadProfiles(); expectedRevision = fresh.revision;
      await refreshProfiles(); return saved;
    };
    function addEditor(item = null) {
      const row = document.createElement('li');
      const title = document.createElement('strong'); title.textContent = item?.name || '新模式草稿'; row.append(title);
      const editor = document.createElement('form'); editor.className = 'companion-profile-editor'; editor.hidden = Boolean(item);
      const input = (label, value, type = 'text') => {
        const wrap = document.createElement('label'); wrap.className = 'set-row';
        const caption = document.createElement('span'); caption.textContent = label;
        const control = document.createElement(type === 'textarea' ? 'textarea' : 'input');
        if (type !== 'textarea') control.type = type;
        control.className = 'sumika-field'; control.setAttribute('aria-label', label);
        if (type === 'checkbox') control.checked = Boolean(value); else control.value = value ?? '';
        wrap.append(caption, control); editor.append(wrap); return control;
      };
      const name = input('模式名称', item?.name || ''); name.maxLength = 80; name.required = true;
      const scenario = input('适用场景描述', item?.scenario_description || '', 'textarea'); scenario.maxLength = 2000;
      const instructions = input('回应指引', item?.response_instructions || '', 'textarea'); instructions.maxLength = 2000;
      const auto = input('参与自动匹配', item?.enabled_for_auto, 'checkbox');
      const proactive = input('允许主动回应', item?.settings?.proactive_enabled, 'checkbox');
      const interval = input('主动回应间隔（秒）', item?.settings?.proactive_interval_seconds ?? 300, 'number');
      interval.min = '120'; interval.max = '86400'; interval.step = '1'; interval.required = true;
      const questions = input('允许行为询问', item?.settings?.behavior_prompts_enabled, 'checkbox');
      const sources = ['text', 'image', 'application_audio'].map((source, i) =>
        [source, input(['参考文字', '参考画面', '参考应用声音'][i], (item?.settings?.context_sources || ['text']).includes(source), 'checkbox')]);
      const message = node_p(''); message.setAttribute('role', 'status');
      const save = document.createElement('button'); save.type = 'submit'; save.className = 'mini-btn'; save.textContent = '保存';
      editor.append(save, message);
      editor.addEventListener('submit', async event => {
        event.preventDefault(); if (!editor.reportValidity()) return;
        save.disabled = true;
        const profile = {name: name.value.trim(), scenario_description: scenario.value,
          response_instructions: instructions.value, enabled_for_auto: auto.checked,
          settings: {proactive_enabled: proactive.checked, proactive_interval_seconds: Number(interval.value),
            behavior_prompts_enabled: questions.checked, context_sources: sources.filter(([, field]) => field.checked).map(([source]) => source)}};
        try {
          await write(item ? {action:'update', profile_id:item.id, changes:profile} : {action:'create', profile});
          el.close(); await openProfilesDialog();
        } catch (error) {
          message.textContent = error.status === 409 ? '配置已在其他位置改变。草稿已保留，请复制草稿后关闭并重新打开核对；不会覆盖新版本。' : `保存失败：${error.message}`;
        } finally { save.disabled = false; }
      });
      if (item) {
        for (const [label, action] of [['编辑', null], ['复制', 'duplicate'], ['删除', 'delete']]) {
          const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'mini-btn'; btn.textContent = label;
          btn.addEventListener('click', async () => {
            if (!action) { editor.hidden = !editor.hidden; return; }
            if (action === 'delete' && !confirm(`删除模式「${item.name}」？`)) return;
            btn.disabled = true;
            try { await write({action, profile_id:item.id}); el.close(); await openProfilesDialog(); }
            catch (error) { editor.hidden = false; message.textContent = `操作失败，草稿保留：${error.message}`; }
            finally { btn.disabled = false; }
          }); row.append(btn);
        }
      }
      row.append(editor); list.append(row); return row;
    }
    (data.profiles || []).forEach(addEditor);
    const create = document.createElement('button'); create.type = 'button'; create.className = 'mini-btn';
    create.textContent = '新建模式'; create.setAttribute('aria-label', '新建陪伴模式');
    create.addEventListener('click', () => { const row = addEditor(); row.querySelector('input').focus(); });
    el.append(dialogStatus, list, create); document.body.append(el); el.showModal();
    el.addEventListener('close', () => { el.remove(); suspendPermissionEdits = false; controls(); });
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
      const current = profilesState;
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
      const result = await endpoint('/api/manage/behavior', {
        action: pause ? 'permission_pause' : 'permission_resume',
        revision: state.permission.revision});
      status.textContent = pause ? '行为记录已暂停；恢复需手动操作，重启也不会自动恢复。'
                                 : result.effective?.can_record ? '暂停已解除，行为记录许可有效。' : '暂停已解除；行为记录未获许可，仍未记录。';
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
  let answer = null, activeTurn = null, playbackSpeaking = false, tabSession = false, explicitContext = false, cameraWorking = false;
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
  const cameraRow = document.createElement('div'); cameraRow.className = 'set-row';
  const cameraButton = document.createElement('button');
  cameraButton.type = 'button'; cameraButton.className = 'mini-btn';
  cameraButton.textContent = '摄像头采集一帧';
  cameraButton.addEventListener('click', async () => {
    if (cameraButton.disabled || !confirm('使用默认摄像头采集一帧作为陪学问答上下文？设备采集后立即释放，不保存图片文件。图片会在你提问时发送给已配置的角色模型；点击停止陪学清除上下文。')) return;
    cameraWorking = true; controls();
    const cameraEpoch = epoch;
    try {
      const result = await endpoint('/api/companion/camera', {consent:true});
      if (cameraEpoch !== epoch || !section.isConnected) return;
      if (result.context_active !== true || result.source !== 'camera-frame') throw Error('服务未确认摄像头上下文生效');
      explicitContext = true;
      cameraStatus.textContent = '已采集一帧；可在原消息框提问。停止陪学可清除图片上下文。';
    } catch (error) {
      if (cameraEpoch !== epoch || !section.isConnected) return;
      unknown = true;
      cameraStatus.textContent = `采集结果未确认：${error.message}。可停止陪学清除上下文；不会自动重试。`;
    } finally { cameraWorking = false; controls(); }
  });
  const cameraStatus = document.createElement('p'); cameraStatus.className = 'sumika-form-note';
  cameraStatus.setAttribute('role', 'status'); cameraStatus.dataset.cameraStatus = '';
  cameraRow.append(cameraButton);
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
  const notesBody = document.createElement('div');
  notesList.append(notesSummary, notesBody);
  let notesRevision = 0;
  notesList.addEventListener('toggle', () => { if (notesList.open) loadRecentNotes(); });
  async function loadRecentNotes() {
    const revision = ++notesRevision;
    try {
      const result = await endpoint('/api/companion/notes', {action:'recent', limit:8});
      if (revision !== notesRevision || !section.isConnected) return;
      notesSummary.textContent = `最近笔记（${result.notes.length}）`;
      notesBody.replaceChildren();
      for (const note of result.notes || []) {
        const item = document.createElement('p');
        item.className = 'sumika-form-note';
        const where = note.source?.page ? `第 ${note.source.page} 页`
          : note.source?.media_time_seconds != null ? `视频 ${Math.floor(note.source.media_time_seconds)}s`
          : (note.target || '').split(':')[0];
        item.textContent = `${where} · ${note.text.slice(0, 80)}${note.text.length > 80 ? '…' : ''}`;
        notesBody.append(item);
      }
    } catch {
      if (revision !== notesRevision || !section.isConnected) return;
      notesBody.replaceChildren();
      notesSummary.textContent = '最近笔记（不可用）';
    }
  }
  const option = document.createElement('label'); option.className = 'set-row';
  const title = document.createElement('span'); title.textContent = '主动讨论';
  const discussion = document.createElement('input'); discussion.type = 'checkbox'; discussion.checked = true;
  discussion.setAttribute('aria-label','主动讨论'); option.append(title,discussion);
  function controls() {
    start.disabled = working || cameraWorking || unknown || currentState !== 'stopped' || captureActive || audioActive || !selected;
    stop.disabled = working || (!unknown && currentState === 'stopped' && !captureActive && !audioActive && !explicitContext && !cameraWorking);
    cameraButton.disabled = working || cameraWorking || unknown || captureActive || audioActive || currentState !== 'stopped';
    refresh.disabled = working;
    danmakuButton.disabled = working || unknown || (!captureActive && currentState !== 'running');
    notesButton.disabled = working || unknown || !answer;
    behaviorToggle.disabled = suspendPermissionEdits || working;
    profileSelect.disabled = suspendPermissionEdits || working || !profilesState;
    manageButton.disabled = suspendPermissionEdits || !profilesState;
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
    const hadExplicitContext = explicitContext;
    if (!cameraWorking) explicitContext = state.paste_context?.active === true;
    if (hadExplicitContext && !explicitContext && !cameraWorking) cameraStatus.textContent = '';
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
    if (state.status === 'stopped' && !captureActive) {
      transcript.replaceChildren(); answer = null; activeTurn = null;
      playbackSpeaking = false; playbackStatus.textContent = '朗读：空闲';
    }
    controls();
  }
  async function poll() {
    if (!section.isConnected || working || polling) return;
    polling = true;
    const token = epoch;
    try {
      const state = await call({action:'status',after:cursor});
      if (token === epoch && section.isConnected) render(state);
      if (Date.now() - lastRuntimeRefresh > 5000 && profilesState) {
        lastRuntimeRefresh = Date.now();
        try { const runtime = await loadRuntime(); if(section.isConnected)profileStatus.textContent = profilesRuntimeLine(runtime, profilesState); }
        catch(error) { profileStatus.textContent = `模式运行状态不可用：${error.message}`; }
      }
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
      if (!response.ok) { const error = Error(result.error || `HTTP ${response.status}`); error.status = response.status; throw error; }
      if (result.context_active !== true || !result.target) throw Error('服务未确认粘贴上下文生效');
      status.textContent = `选区文字已生效（${result.chars} 字符）；可在原消息框继续提问。`;
      pasteArea.value = '';
    } catch (error) {
      status.textContent = `上下文注入失败：${error.message}`;
    } finally { pasteBtn.disabled = false; }
  });
  pasteRow.append(pasteArea, pasteBtn);
  section.append(heading,status,targetRow,modeRow,scope,audioRow,audioStatus,browserAudioStatus,captureStatus,playbackStatus,option,commands,cameraRow,cameraStatus,transcript,notesList,profileStatus,profileRow,behaviorRow,pasteRow);
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
