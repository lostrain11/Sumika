import {bridgeFetch as fetch} from './bridge-client.js';
// Data binding for the D design shell: keeps the design markup and replaces the
// mock content with the real backend. Never presents mock data as real: the mock
// timeline and approval card are hidden once the real DSH instance is embedded.

import {hasExplicitTaskIntent} from './task-intent.js';
import {bindSpeechInput, cancelSpeechInput} from './speech-input.js';
import {bindSpeechPlayback, cancelSpeechPlayback} from './speech-playback.js';

const COLORS = [
  ['#c24e6e', '#f9e8ed'],
  ['#47746a', '#e9f1ee'],
  ['#7fb1c9', '#eaf3f8'],
  ['#c9a24a', '#f8f1dd'],
];

// The design shell carries its own stylesheet, so the frame styling is injected
// here instead of relying on a separate app stylesheet.
const style = document.createElement('style');
style.textContent = `
.sumika-dsh-frame { width: 100%; height: calc(100vh - 200px); min-height: 520px;
  border: 1px solid var(--line, #e2dccd); border-radius: 9px; background: #fff; margin: 10px 0; }
#screen-board { overflow: hidden; }
#sumika-workbench-frame { position: absolute; inset: 0; }
/* The shell must never be taller than the viewport: the design's
   .screen{height:calc(100% - 64px)} resolved against a stale 100% and pushed the
   composer and the sidebar footer out of reach under body{overflow:hidden}.
   A fixed-viewport flex column makes the active screen take exactly what is left. */
html, body { height: 100%; overflow: hidden; }
body { display: flex; flex-direction: column; }
.topbar { flex: 0 0 auto; }
.screen { flex: 1 1 auto; min-height: 0; height: auto; }
/* The design's floating deskpet still carries sample dialogue; it must not sit
   on top of the real workbench. */
body.on-board #deskpet { display: none; }
.wb-task { display: flex; align-items: center; gap: 8px; padding: 3px 6px;
  font-size: 12px; color: var(--muted, #7d8a86); }
.wb-task em { margin-left: auto; font-style: normal; opacity: .7; }
.roster .member em { display: block; font-size: 11px; font-style: normal; opacity: .65; }
`;
document.head.appendChild(style);

async function api(path, options) {
  const headers = {'Content-Type':'application/json', ...options?.headers};
  if (options?.method && !['GET','HEAD'].includes(options.method.toUpperCase())) {
    const session = await fetch('/api/manage/session');
    if (!session.ok) throw new Error('无法验证本地连接，请刷新页面');
    headers['X-Sumika-CSRF'] = (await session.json()).csrf;
  }
  // Never retry a write on token failure: its outcome may be unknown.
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => ({ error: 'invalid response' }));
  if (!response.ok) throw Object.assign(new Error(payload.error || payload.message || 'failed'), { payload, status:response.status });
  return payload;
}

function setText(selector, text) {
  const node = document.querySelector(selector);
  if (node) node.textContent = text;
}

const escapeHTML = value => String(value).replace(/[&<>"']/g,
  char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));

function bindHeader(state) {
  setText('.model-chip', `${state.role?.model || '未配置模型'} ▾`);
  const proto = document.querySelector('.proto');
  if (proto) {
    proto.textContent = '本地服务已连接';
    proto.title = '已收到 Sumika 本地服务响应。角色模型与工作台的可用状态分别判断。';
  }
}

let headerRevision = 0;
async function refreshHeader() {
  const revision = ++headerRevision;
  const unavailable = (text) => {
    const proto = document.querySelector('.proto');
    if (proto) {
      proto.textContent = text;
      proto.title = '当前无法确认本地服务连接；已有会话和草稿不会重新发送。';
    }
  };
  if (!navigator.onLine) {
    unavailable('浏览器离线');
    return;
  }
  try {
    const state = await api('/api/state');
    if (revision === headerRevision && navigator.onLine) bindHeader(state);
  } catch {
    if (revision === headerRevision) unavailable('本地服务连接异常');
  }
}

function bindRoster(payload) {
  const roster = document.querySelector('.roster');
  if (!roster) return;
  const all = payload.roles || [];
  // A roster entry is a whole character: its name, its card and its model.
  const roles = all.filter(role => role.complete === true);
  const unfinished = all.filter(role => role.complete !== true);
  const activeId = payload.active?.id;
  roster.querySelectorAll('.member').forEach(node => node.remove());
  const anchor = roster.querySelector('h3');
  let previous = anchor;
  roles.forEach((role, index) => {
    const [color, soft] = COLORS[index % COLORS.length];
    const button = document.createElement('button');
    button.className = 'member' + (role.id === activeId ? ' active' : '');
    button.dataset.name = role.name;
    button.dataset.sub = role.has_model_3d ? '实机 VRM · 已绑定模型' : '角色卡 · 立绘占位';
    button.dataset.color = color;
    button.dataset.soft = soft;
    button.dataset.speech = `${role.name}：准备好了。`;
    button.dataset.roleId = role.id;
    button.style.setProperty('--mc', color);
    // Same element shape as the design's roster: avatar, name + status lines, and
    // the VRM badge — so the stylesheet applies unchanged.
    const initial = role.name.trim().slice(0, 1) || '角';
    const sub = `${role.kind === 'user' ? '用户导入' : 'Sumika 内置'} · `
      + (role.has_model_3d ? '已绑定 VRM' : '角色卡 · 立绘占位');
    button.dataset.sub = sub;
    button.innerHTML = `<span class="ava" style="background:linear-gradient(135deg,${soft},${color})">${escapeHTML(initial)}</span>`
      + `<span><span class="nm">${escapeHTML(role.name)}</span><span class="st">${escapeHTML(sub)}</span></span>`
      + (role.has_model_3d ? '<span class="bind">VRM</span>' : '');
    button.addEventListener('click', async () => {
      if (roster.dataset.selecting === '1') return;
      roster.dataset.selecting = '1';
      try {
        await api('/api/roles/select', { method: 'POST', body: JSON.stringify({ id: role.id }) });
        document.querySelectorAll('.roster .member').forEach(node => node.classList.remove('active'));
        button.classList.add('active');
        window.sumikaSyncRolePresentation?.({name: role.name, sub, color, soft});
        setText('#roomOwner', `${role.name}的房间`);
        setText('#chatChara', role.name);
        setText('#atChip', `@${role.name}`);
        setText('#stageChara', role.name);
        window.sumikaRoleVrm = {
          id: role.id, name: role.name, modelUrl: role.model_3d_url || null,
        };
        window.sumikaUpdateRoleView?.();
        // Each role keeps its own session, so switching reloads that transcript.
        await loadRoomChat(role.id);
      } catch (error) {
        setText('#roomOwner', `切换失败：${error.message}`);
      } finally {
        delete roster.dataset.selecting;
      }
    });
    if (previous) previous.after(button);
    else roster.appendChild(button);
    previous = button;
  });
  const count = document.getElementById('memberCount');
  if (count) count.textContent = String(roles.length);
  // The design's placeholder assistant is called 澄花; every surface that shows
  // the speaking role must follow the active one instead.
  const active = roles.find(role => role.id === activeId);
  if (active) {
    const [color, soft] = COLORS[roles.indexOf(active) % COLORS.length];
    window.sumikaSyncRolePresentation?.({name: active.name,
      sub: active.kind === 'user' ? '用户导入' : 'Sumika 内置', color, soft});
    setText('#chatChara', active.name);
    setText('#stageChara', active.name);
    setText('#roomOwner', `${active.name}的房间`);
    setText('#atChip', `@${active.name}`);
    const sub = document.getElementById('stageCharaSub');
    const origin = active.kind === 'user' ? '用户导入' : 'Sumika 内置';
    if (sub) {
      sub.textContent = `${origin} · ${active.has_model_3d ? '已绑定 VRM' : '立绘占位'}`;
    }
    // The stage renders the active role's own asset; a role without a VRM shows
    // the placeholder illustration instead of borrowing another model.
    window.sumikaRoleVrm = {
      id: active.id, name: active.name, modelUrl: active.model_3d_url || null,
    };
    window.sumikaUpdateRoleView?.();
  }
  roster.querySelectorAll('.sumika-unfinished').forEach(node => node.remove());
  if (unfinished.length > 0) {
    const note = document.createElement('p');
    note.className = 'hint sumika-unfinished';
    note.style.margin = '6px 0 0';
    note.style.fontSize = '10px';
    const labels = { card: '缺角色卡', model_3d: '缺 3D 模型' };
    const headline = document.createElement('span');
    headline.textContent = '未完整（不计入名册）：';
    note.appendChild(headline);
    unfinished.forEach((role, index) => {
      const line = document.createElement('span');
      line.style.display = 'block';
      line.textContent = `${role.name}（${(role.missing || []).map(kind => labels[kind] || kind).join('、') || '缺少资产'}）`;
      note.appendChild(line);
      // A role that only lacks its model can be completed right here; the file
      // stays on this machine, it is never uploaded.
      if ((role.missing || []).includes('model_3d') && role.kind === 'user') {
        const fix = document.createElement('span');
        fix.style.cssText = 'display:flex;gap:4px;margin:2px 0 4px';
        const field = document.createElement('input');
        field.placeholder = 'D:\\路径\\model.vrm';
        field.setAttribute('data-attach-path', role.id);
        field.style.cssText = 'flex:1;min-width:0;font-size:9.5px;padding:2px 4px;'
          + 'border:1px solid var(--line);border-radius:5px;background:#fff';
        const button = document.createElement('button');
        button.className = 'mini-btn';
        button.style.cssText = 'font-size:9.5px;padding:2px 8px;white-space:nowrap';
        button.textContent = '补挂模型';
        button.addEventListener('click', async () => {
          const path = field.value.trim();
          if (!path) { button.textContent = '先填路径'; return; }
          button.textContent = '附加中…';
          try {
            await api('/api/roles/attach', {
              method: 'POST',
              body: JSON.stringify({ id: role.id, kind: 'model_3d', path }),
            });
            bindRoster(await api('/api/roles'));
          } catch (error) {
            button.textContent = `失败：${(error.payload || {}).error || error.message}`;
          }
        });
        fix.append(field, button);
        note.appendChild(fix);
      }
    });
    roster.appendChild(note);
  }
  // The active role must be one the roster can actually show; if it is not, say
  // so and switch to the first whole character instead of leaving a hidden role
  // driving the room.
  if (roles.length > 0 && !roles.some(role => role.id === activeId) && !bindRoster.switching) {
    bindRoster.switching = true;
    const chosen = roles[0];
    api('/api/roles/select', { method: 'POST', body: JSON.stringify({ id: chosen.id }) })
      .then(() => api('/api/roles'))
      .then(fresh => { bindRoster.switching = false; bindRoster(fresh); return loadRoomChat(fresh.active?.id); })
      .catch(() => { bindRoster.switching = false; });
    const hint = document.createElement('p');
    hint.className = 'hint sumika-unfinished';
    hint.style.margin = '6px 0 0';
    hint.style.fontSize = '10px';
    hint.textContent = `当前角色未完整，已切到 ${chosen.name}`;
    roster.appendChild(hint);
  }
}

// ---- 活动室对话（真实角色服务） ---------------------------------------------
//
// The design's chat column shipped with sample messages and an inert composer.
// Both are replaced: the transcript comes from the bridge for this role's own
// session, and a failure is shown as a failure instead of a plausible reply.

let roomChatRoleId = null;
let roomChatEpoch = 0;
let roomMessages = [];
let roomBefore = null;
let roomHasMore = false;
let roomHistoryBusy = false;
let roomSending = false;
let roomSupportsClear=false;
let roomLegacyEarlier=[];

function syncRoomHistoryControls() {
  const more=document.querySelector('[data-room-older]');
  if(more){more.hidden=!roomHasMore;more.disabled=roomHistoryBusy;}
  const clear=document.querySelector('[data-room-clear]');
  if(clear){clear.disabled=!roomSupportsClear || roomHistoryBusy || roomSending || !roomMessages.length;clear.title=roomSupportsClear?'仅清空当前聊天，保留长期记忆':'当前运行服务尚不支持清空，需更新后端';}
}

function roomSessionId(roleId) {
  return `room-${roleId || 'default'}`;
}

function roomMessageNode({ who, text, at, isError, task_intent, id, state }) {
  const mine = who === 'me';
  const name = document.getElementById('chatChara')?.textContent || '她';
  const node = document.createElement('div');
  node.className = `cm ${mine ? 'user' : 'agent'}`;
  if (isError) node.dataset.roomError = '1';
  const label = document.createElement('span');
  label.className = 'who';
  label.textContent = mine ? `我 · ${(at || '').slice(11, 16)}` : `${name} · ${(at || '').slice(11, 16)}`;
  const bubble = document.createElement('div');
  bubble.className = 'bub';
  bubble.textContent = text;
  if (isError) {
    bubble.style.color = '#b04a4a';
    bubble.style.borderColor = '#e0b3b3';
  }
  node.append(label, bubble);
  if (!mine && !isError && typeof text === 'string' && text.trim()) {
    const playback = document.createElement('button');
    playback.type = 'button'; playback.className = 'mini-btn room-playback';
    playback.textContent = '朗读';
    node.append(playback);
    if (text.length > 4000) {
      playback.disabled = true; playback.title = '单次朗读最多支持 4000 字符';
    } else {
      bindSpeechPlayback(playback, {key:JSON.stringify([roomChatRoleId,id || at,text]),
        text, roleId:roomChatRoleId, api});
    }
  }
  if (mine && state === 'unknown') {
    const status = document.createElement('small');
    status.textContent = '回复结果未确认，不会自动重发';
    node.append(status);
  }
  if (mine && !isError && task_intent?.kind === 'task' && task_intent.confidence === 'high'
      && typeof task_intent.evidence === 'string' && task_intent.evidence.trim()
      && text.includes(task_intent.evidence) && hasExplicitTaskIntent(text)) {
    const sourceMessageId = id;
    if (!sourceMessageId) return node;
    const handoff = document.createElement('button');
    handoff.type = 'button';
    handoff.className = 'mini-btn';
    handoff.textContent = '转到工作台…';
    handoff.addEventListener('click', () => window.dispatchEvent(new CustomEvent('sumika:prepare-task', {
      detail: {text, sourceMessageId},
    })));
    node.append(handoff);
  }
  return node;
}

function renderRoomMessages(messages) {
  const list = document.querySelector('#screen-room .chat-msgs');
  if (!list) return;
  list.textContent = '';
  // The stage bubble repeats the latest real line instead of the design's
  // invented greeting, so nothing on this screen speaks without a source.
  const bubble = document.getElementById('speechBub');
  const lastRole = [...(messages || [])].reverse().find(message => message.who !== 'me');
  if (bubble) {
    bubble.textContent = lastRole?.text
      || '还没有对话。在下面发一句，她的回答会出现在这里和右侧对话栏。';
  }
  if (!messages || messages.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'cm agent';
    empty.dataset.roomEmpty = '1';
    const label = document.createElement('span');
    label.className = 'who';
    label.textContent = '还没有对话记录';
    const bubble = document.createElement('div');
    bubble.className = 'bub';
    bubble.textContent = '在下面输入第一句话。角色模型没配置好时这里会如实报错，不会替她编答案。';
    empty.append(label, bubble);
    list.appendChild(empty);
    return;
  }
  messages.forEach(message => list.appendChild(roomMessageNode(message)));
  list.scrollTop = list.scrollHeight;
}

async function loadRoomChat(roleId) {
  if (roleId !== roomChatRoleId) { await cancelSpeechInput(); await cancelSpeechPlayback(); }
  const epoch = ++roomChatEpoch;
  roomChatRoleId = roleId || null;
  const session = encodeURIComponent(roomSessionId(roleId));
  const payload = await api(`/api/role/chat/history?session=${session}&role_id=${encodeURIComponent(roleId || '')}&limit=3`);
  if (epoch !== roomChatEpoch) return;
  // Older bridges return an unpaged list; display only the requested tail.
  roomMessages=(payload.messages || []).slice(-3);
  roomBefore=payload.before ?? null;
  roomSupportsClear=payload.supports_clear===true;
  roomLegacyEarlier=payload.has_more===undefined?(payload.messages||[]).slice(0,-3):[];
  roomHasMore=payload.has_more === true || roomLegacyEarlier.length>0;
  renderRoomMessages(roomMessages);
  syncRoomHistoryControls();
  window.sumikaDeskpet?.reload?.();
}

async function sendRoomMessage(text) {
  roomSending=true;syncRoomHistoryControls();
  const epoch = roomChatEpoch;
  const roleId = roomChatRoleId;
  const list = document.querySelector('#screen-room .chat-msgs');
  if (!list) return;
  // The empty-state bubble is not a message: drop it before the first real one.
  list.querySelector('[data-room-empty]')?.remove();
  const stamp = new Date().toISOString();
  const userNode = roomMessageNode({ who: 'me', text, at: stamp });
  list.appendChild(userNode);
  list.scrollTop = list.scrollHeight;
  try {
    const result = await api('/api/role/chat', {
      method: 'POST',
      body: JSON.stringify({ message: text, session: roomSessionId(roleId), role_id: roleId }),
    });
    if (epoch !== roomChatEpoch) {roomSending=false;syncRoomHistoryControls();return;}
    const reply = typeof result.text === 'string' ? result.text.trim() : '';
    userNode.replaceWith(roomMessageNode({who:'me',text,at:stamp,task_intent:result.task_intent,id:result.source_message_id}));
    list.appendChild(roomMessageNode({
      who: 'role', at: new Date().toISOString(),
      id: result.source_message_id?.replace(/:user$/, ':assistant'),
      text: reply || '（模型没有返回文本）', isError: !reply,
    }));
    if(reply)await loadRoomChat(roleId).catch(()=>{});
  } catch (error) {
    if (epoch !== roomChatEpoch) {roomSending=false;syncRoomHistoryControls();return;}
    const detail = (error.payload || {}).message || error.message;
    list.appendChild(roomMessageNode({
      who: 'role', at: new Date().toISOString(), text: `发送失败：${detail}`, isError: true,
    }));
  }
  roomSending=false;syncRoomHistoryControls();
  list.scrollTop = list.scrollHeight;
  window.sumikaDeskpet?.reload?.();
}

async function bindRoomChat(activeRoleId) {
  const composer = document.querySelector('#screen-room .chat-composer');
  if (!composer) return;
  const head=document.querySelector('#screen-room .chat-head');
  if(head && !head.querySelector('[data-room-clear]')) {
    const controls=document.createElement('div');controls.className='room-history-controls';
    const more=document.createElement('button');more.type='button';more.className='mini-btn';
    more.dataset.roomOlder='';more.textContent='加载更早';more.hidden=true;
    const clear=document.createElement('button');clear.type='button';clear.className='mini-btn';
    clear.dataset.roomClear='';clear.textContent='清空聊天';
    const notice=document.createElement('small');notice.dataset.roomHistoryNotice='';notice.setAttribute('role','status');
    more.addEventListener('click',async()=>{
      if(roomHistoryBusy || !roomHasMore)return;
      const epoch=roomChatEpoch,role=roomChatRoleId;
      roomHistoryBusy=true;syncRoomHistoryControls();notice.textContent='';
      try {
        const payload=roomLegacyEarlier.length?{messages:roomLegacyEarlier.splice(-3),before:null,has_more:roomLegacyEarlier.length>0}:await api(`/api/role/chat/history?session=${encodeURIComponent(roomSessionId(role))}&role_id=${encodeURIComponent(role)}&limit=3&before=${roomBefore}`);
        if(epoch!==roomChatEpoch)return;
        const list=document.querySelector('#screen-room .chat-msgs'),height=list.scrollHeight,top=list.scrollTop;
        roomMessages=[...(payload.messages||[]),...roomMessages];roomBefore=payload.before;
        roomHasMore=payload.has_more===true;renderRoomMessages(roomMessages);
        list.scrollTop=top+list.scrollHeight-height;
      }catch(error){if(epoch===roomChatEpoch)notice.textContent=`加载失败：${error.message}`;}
      finally{roomHistoryBusy=false;syncRoomHistoryControls();}
    });
    clear.addEventListener('click',async()=>{
      if(roomHistoryBusy || roomSending || !confirm('清空当前角色的聊天？长期记忆和角色资源会保留。'))return;
      const epoch=roomChatEpoch,role=roomChatRoleId;
      roomHistoryBusy=true;syncRoomHistoryControls();notice.textContent='';
      try {
        await cancelSpeechPlayback();
        await api('/api/role/chat/clear',{method:'POST',body:JSON.stringify({role_id:role,session:roomSessionId(role)})});
        if(epoch!==roomChatEpoch)return;
        await loadRoomChat(role);
        window.dispatchEvent(new Event('sumika:chat-cleared'));
      }catch(error){if(epoch===roomChatEpoch)notice.textContent=`未清空：${error.message}`;}
      finally{roomHistoryBusy=false;syncRoomHistoryControls();}
    });
    controls.append(more,clear,notice);head.append(controls);
  }
  // Shared with the floating deskpet so both surfaces speak to one session.
  window.sumikaRoomSession = () => roomSessionId(roomChatRoleId);
  window.sumikaRoomReload = () => loadRoomChat(roomChatRoleId);
  const field = composer.querySelector('.input');
  let input = field;
  if (field && field.tagName !== 'INPUT') {
    input = document.createElement('input');
    input.type = 'text';
    input.className = field.className;
    input.placeholder = '说点什么…';
    input.setAttribute('data-room-input', '');
    input.style.cssText = 'border:none;background:transparent;outline:none;'
      + 'font:inherit;color:inherit;width:100%;min-width:0';
    field.replaceWith(input);
  }
  const submit = () => {
    const text = (input?.value || '').trim();
    if (!text) return;
    if (input) input.value = '';
    sendRoomMessage(text);
  };
  input?.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
  });
  composer.querySelector('#sendBtn')?.addEventListener('click', submit);
  bindSpeechInput(composer.querySelector('.voice'), input,
    document.querySelector('[data-room-history-notice]'), api, () => roomChatRoleId);
  await loadRoomChat(activeRoleId);
}

// ---- 角色导入（用户自己的卡与模型） ------------------------------------------
//
// Imported roles belong to the user: the card travels as text, the model is a
// path on this machine. Nothing is bundled, nothing is uploaded off the machine.

function roleImportForm() {
  const wrapper = document.createElement('div');
  wrapper.className = 'sumika-import';
  wrapper.style.cssText = 'display:none;flex-direction:column;gap:6px;margin-top:8px;'
    + 'padding:9px;border:1px dashed var(--line);border-radius:9px;background:var(--paper)';
  wrapper.innerHTML = `
    <label style="font-size:10px;color:var(--muted)">角色 id（字母/数字/-）</label>
    <input data-import="id" placeholder="例如 ando-subaru" style="font-size:11px;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:#fff">
    <label style="font-size:10px;color:var(--muted)">角色卡（Tavern V2/V3 JSON）</label>
    <input data-import="card" type="file" accept=".json,application/json" style="font-size:10px">
    <label style="font-size:10px;color:var(--muted)">显示名（留空就用角色卡里的名字）</label>
    <input data-import="name" placeholder="角色卡自带的名字" style="font-size:11px;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:#fff">
    <label style="font-size:10px;color:var(--muted)">3D 模型路径（可选，本机 .vrm）</label>
    <input data-import="model" placeholder="D:\\路径\\model.vrm" style="font-size:10px;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:#fff">
    <div style="display:flex;gap:6px;align-items:center">
      <button data-import="submit" class="mini-btn" style="font-size:11px;white-space:nowrap">导入</button>
      <button data-import="cancel" class="mini-btn" style="font-size:11px;white-space:nowrap">取消</button>
      <span data-import="status" style="font-size:10px;color:var(--muted);line-height:1.4"></span>
    </div>`;
  return wrapper;
}

async function bindRoleImport(rolesPayload) {
  const roster = document.querySelector('.roster');
  if (!roster) return;
  const footer = roster.querySelector('.roster-foot');
  const trigger = footer?.querySelector('.import-btn');
  if (!footer || !trigger) return;
  const form = roleImportForm();
  footer.appendChild(form);
  trigger.removeAttribute('disabled');
  trigger.style.cursor = 'pointer';
  trigger.textContent = '＋ 导入角色卡 / 模型';
  trigger.addEventListener('click', () => {
    const open = form.style.display === 'flex';
    form.style.display = open ? 'none' : 'flex';
  });
  const status = text => {
    const node = form.querySelector('[data-import="status"]');
    if (node) node.textContent = text;
  };
  form.querySelector('[data-import="cancel"]').addEventListener('click', () => {
    form.style.display = 'none';
    status('');
  });
  // The card carries the character's own name; show it so the user can see what
  // will appear in the roster and only override it when they want to.
  form.querySelector('[data-import="card"]').addEventListener('change', async event => {
    const file = event.target.files?.[0];
    const nameField = form.querySelector('[data-import="name"]');
    if (!file || !nameField) return;
    try {
      const parsed = JSON.parse(await file.text());
      const cardName = parsed?.data?.name;
      if (!nameField.value && typeof cardName === 'string') {
        nameField.placeholder = cardName;
        status(`角色卡名字：${cardName}`);
      }
    } catch {
      status('这个文件不是有效的 JSON 角色卡');
    }
  });
  form.querySelector('[data-import="submit"]').addEventListener('click', async () => {
    const id = form.querySelector('[data-import="id"]').value.trim();
    const file = form.querySelector('[data-import="card"]').files?.[0];
    const displayName = form.querySelector('[data-import="name"]').value.trim();
    const modelPath = form.querySelector('[data-import="model"]').value.trim();
    if (!id) { status('先填角色 id'); return; }
    if (!file) { status('先选择角色卡 JSON'); return; }
    status('读取角色卡…');
    try {
      const card = await file.text();
      status('导入中…');
      const result = await api('/api/roles/import', {
        method: 'POST',
        body: JSON.stringify({ id, card, modelPath: modelPath || null,
                               name: displayName || null }),
      });
      status(result.model_3d ? '已导入（含 3D 模型）' : '已导入（未带 3D 模型）');
      const fresh = await api('/api/roles');
      bindRoster(fresh);
      await loadRoomChat(fresh.active?.id || null);
    } catch (error) {
      const detail = (error.payload || {}).error || error.message;
      status(`导入失败：${detail}`);
    }
  });
}

function bindTree(tree) {
  const side = document.querySelector('.wb-side');
  if (!side || !tree.phases) return;
  side.querySelectorAll('.wb-proj').forEach(node => node.remove());
  const project = document.createElement('div');
  project.className = 'wb-proj open';
  const phases = tree.phases.slice(0, 9);
  project.innerHTML = `<button class="wb-proj-head">`
    + `<i class="dot" style="background:var(--rose)"></i>`
    + `<span class="nm">${tree.project?.name?.slice(0, 24) || 'sumika-next'}`
    + `<small>${tree.project?.path || ''}</small></span>`
    + `<b>${phases.length}</b></button>`;
  const body = document.createElement('div');
  body.className = 'wb-proj-body';
  phases.forEach(phase => {
    const dot = phase.status === 'complete' ? '#6f9c7a'
      : (phase.status === 'planned' ? '#cbbfa6' : 'var(--rose)');
    const row = document.createElement('div');
    row.className = 'wb-task';
    row.innerHTML = `<i class="dot" style="background:${dot}"></i>`
      + `<span>${phase.id} · ${phase.name}</span>`
      + `<em>${(phase.tasks || []).length} 项</em>`;
    body.appendChild(row);
  });
  project.appendChild(body);
  const anchor = side.querySelector('.wb-search');
  if (anchor) anchor.after(project);
  else side.appendChild(project);
  side.querySelectorAll('.wb-proj-head').forEach(head => {
    head.addEventListener('click', () => head.parentElement.classList.toggle('open'));
  });
}

/**
 * Make sure the managed instance is up and hand back the URL the workbench
 * screen frames. Never navigates: the workbench is a screen of this page, so the
 * user stays in the shell.
 */
async function ensureWorkbenchUrl() {
  let status;
  try {
    status = await api('/api/workbench');
    if (!status.running) {
      status = await api('/api/workbench/start', {
        method: 'POST', body: JSON.stringify({ port: 5175 }),
      });
    }
    if (!status.embed_ready) return { url: null, error: 'DSH 实例未就绪' };
    const { url } = await api('/api/workbench/embed');
    if (!url) return { url: null, error: 'DSH 未返回可用地址' };
    return { url, error: null };
  } catch (error) {
    const message = (error.payload || {}).message || error.message;
    return { url: null, error: message };
  }
}

let workbenchLoad = null;
async function bindWorkbench() {
  const screen = document.getElementById('screen-board');
  if (!screen || screen.querySelector('iframe')) return;
  if (workbenchLoad) return workbenchLoad;
  workbenchLoad = (async () => {
    try {
      const layout = await fetch('/api/manage/workbench-layout').then(r => r.ok ? r.json() : null);
      if (layout) screen.dataset.workbenchMode = layout.mode || 'iframe-fallback';
    } catch (_) { screen.dataset.workbenchMode = 'iframe-fallback'; }
    screen.replaceChildren();
    const state = document.createElement('div');
    state.className = 'sumika-loading';
    state.textContent = '正在连接工作台…';
    screen.append(state);
    const {url, error} = await ensureWorkbenchUrl();
    if (url) {
      const frame = document.createElement('iframe');
      frame.id = 'sumika-workbench-frame';
      frame.title = 'Sumika 工作台';
      frame.src = url;
      // Keep the native DSH surface aware of the Sumika shell route without
      // creating a second navigator or duplicating session state.
      const syncRoute = () => {
        if (!frame.contentWindow) return;
        frame.contentWindow.postMessage({type:'sumika:host-route',route:(location.hash||'#room').slice(1)}, new URL(frame.src).origin);
      };
      window.addEventListener('hashchange', syncRoute);
      frame.addEventListener('load', syncRoute, {once:false});
      frame.style.cssText = 'width:100%;height:100%;border:0;display:block';
      const wrapper = document.createElement('div');
      wrapper.className = 'sumika-workbench-host';
      wrapper.style.cssText='position:relative;width:100%;height:100%;min-height:0';
      const notice=document.createElement('div');
      notice.className='sumika-workbench-status';
      notice.textContent='正在加载 DSH 工作台…';
      notice.style.cssText='position:absolute;z-index:2;top:12px;left:50%;transform:translateX(-50%);padding:6px 10px;border:1px solid var(--line);border-radius:7px;background:var(--paper);color:var(--muted);font-size:11px;pointer-events:none';
      frame.addEventListener('load',()=>{notice.remove();});
      frame.addEventListener('error',()=>{
        notice.style.pointerEvents='auto';notice.style.cursor='pointer';notice.textContent='工作台加载失败，点击重试';
        notice.onclick=()=>{notice.onclick=null;notice.textContent='正在重新连接…';frame.src=url;};
      });
      wrapper.append(frame,notice);screen.replaceChildren(wrapper);
    } else {
      state.className = 'sumika-region-error';
      state.textContent = `工作台未连接：${error || '实例未就绪'} `;
      const retry = document.createElement('button');
      retry.className = 'mini-btn'; retry.textContent = '重试';
      retry.addEventListener('click', bindWorkbench);
      state.append(retry);
    }
  })();
  try { await workbenchLoad; } finally { workbenchLoad = null; }
}

// ---- capability switches (R-107/R-108) -------------------------------------
//
// Readiness and enablement are two different facts and are shown as such:
// /api/readiness says the dependency is present, /api/modules is the registry the
// executors actually consult. A capability that has no registry entry has no
// switch here — it must not look controllable.

const NATIVE_CARDS = [
  { icon: '⌨', title: '终端执行', text: '受管终端命令、测试与构建，高危操作进入待确认。' },
  { icon: '✎', title: '文件编辑', text: '代码搜索、阅读与补丁写入，写入前创建检查点。' },
  { icon: '⧉', title: '子代理', text: '独立任务与代码审查交由原生子 Agent，可并行。' },
  { icon: '❖', title: 'Skills', text: '领域技能包，安装前经安全审查。' },
  { icon: '⬡', title: 'MCP 连接', text: '第三方工具服务器，按来源与作用域显式授权。' },
];

/** Design's `.sw2` switch, wired to a real toggle. */
function switchElement(enabled, onToggle) {
  const node = document.createElement('span');
  node.className = 'sw2' + (enabled ? ' on' : '');
  node.setAttribute('role', 'switch');
  node.setAttribute('aria-checked', enabled ? 'true' : 'false');
  node.setAttribute('data-capability-switch', '');
  node.tabIndex = 0;
  node.style.cursor = 'pointer';
  const fire = () => onToggle(!enabled);
  node.addEventListener('click', fire);
  node.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      fire();
    }
  });
  return node;
}

function statusPill(text, variant) {
  const node = document.createElement('span');
  node.className = `st ${variant}`;
  node.textContent = text;
  return node;
}

function capabilityCard({ icon, title, status, statusClass, text, source, enabled, onToggle,
                          capabilityId }) {
  const card = document.createElement('div');
  card.className = 'cap-card';
  card.tabIndex = 0;
  if (capabilityId) card.dataset.capabilityId = capabilityId;
  const top = document.createElement('div');
  top.className = 'top';
  const glyph = document.createElement('div');
  glyph.className = 'cap-ic';
  glyph.style.background = 'var(--green-soft)';
  glyph.textContent = icon;
  const heading = document.createElement('h4');
  heading.textContent = title;
  top.append(glyph, heading);
  if (status) top.appendChild(statusPill(status, statusClass));
  const body = document.createElement('p');
  body.textContent = text;
  const foot = document.createElement('div');
  foot.className = 'foot';
  const origin = document.createElement('span');
  origin.className = 'src';
  origin.textContent = source;
  foot.appendChild(origin);
  if (typeof onToggle === 'function') foot.appendChild(switchElement(enabled, onToggle));
  card.append(top, body, foot);
  return card;
}

async function capabilityState() {
  const [registry, readiness, settings] = await Promise.all([api('/api/modules'), api('/api/readiness'),api('/api/manage/settings')]);
  const raw=registry.modules||[];
  const modules=raw.filter(m=>!['voice','asr','microphone','memory','memory-semantic'].includes(m.id));
  const speech=raw.filter(m=>['voice','asr'].includes(m.id));
  modules.push({id:'speech',label:'语音交互',purpose:'语音识别、朗读与输入设备；麦克风需单独授权。',
    enabled:speech.some(m=>m.enabled),provider:'本地语音模块',detailOnly:true});
  modules.push({id:'memory',label:'长期记忆',purpose:'管理记忆检索、自动提取与待确认提议。',
    enabled:settings.data.memory.enabled!==false,provider:settings.data.role.memory_provider,detailOnly:true});
  return { modules, readiness:(readiness.capabilities||[]).filter(m=>!['voice','asr','microphone','memory','memory-semantic'].includes(m.id)) };
}

async function toggleCapability(id, enabled) {
  await api('/api/capabilities/toggle', {
    method: 'POST',
    body: JSON.stringify({ id, enabled }),
  });
}

function setNote(node, text, ok) {
  if (!node) return;
  node.textContent = text;
  node.style.color = ok ? '' : 'var(--danger, #b04a4a)';
}

/** Fill one `.kv` row in an info panel, keeping the panel's own markup. */
function setRow(panel, label, value, ok) {
  const row = Array.from(panel.querySelectorAll('.kv'))
    .find(node => node.querySelector('span')?.textContent.trim() === label);
  if (!row) return;
  const target = row.querySelector('b');
  if (!target) return;
  target.textContent = value;
  target.classList.toggle('ok', ok === true);
}

/** The capability detail panel mirrors the selected card; never invents values. */
function renderCapabilityDetail(card, entry, readinessRow, version) {
  window.dispatchEvent(new CustomEvent('sumika-capability-selected', {detail:{id:entry?.id || readinessRow?.id}}));
  const side = document.querySelector('.cap-side');
  if (!side) return;
  const hero = side.querySelector('.hero-d');
  if (hero) {
    const glyph = hero.querySelector('.cap-ic');
    const title = hero.querySelector('h4');
    const text = hero.querySelector('p');
    if (title) title.textContent = entry?.label || card?.querySelector('h4')?.textContent || '未选择';
    if (text) {
      text.textContent = entry?.purpose || readinessRow?.detail
        || '点选左侧卡片查看这一项的真实来源与状态';
    }
    if (glyph) glyph.textContent = card?.querySelector('.cap-ic')?.textContent || '◈';
  }
  const panels = side.querySelectorAll('.panel:not([data-extra-action])');
  if (panels[0]) {
    if (entry) {
      setRow(panels[0], '状态', entry.enabled ? '已启用' : '已停用', entry.enabled);
      setRow(panels[0], '来源', entry.detailOnly ? `能力配置 · ${entry.provider}` : `注册表 · ${entry.provider}`);
      setRow(panels[0], '版本', '—');
      setRow(panels[0], '权限', '执行前经授权与审批');
      setRow(panels[0], '数据', '按所选工具与模型的数据策略处理');
    } else if (readinessRow) {
      setRow(panels[0], '状态', readinessRow.ready ? '依赖就绪 · 未登记' : '依赖缺失', false);
      setRow(panels[0], '来源', '就绪检查');
      setRow(panels[0], '版本', '—');
      setRow(panels[0], '权限', '—');
      setRow(panels[0], '数据', '按所选工具与模型的数据策略处理');
    } else {
      setRow(panels[0], '状态', 'Harness 自带', true);
      setRow(panels[0], '来源', 'DSH 原生');
      setRow(panels[0], '版本', version || '—');
      setRow(panels[0], '权限', '由 DSH 权限策略管理');
      setRow(panels[0], '数据', '按所选工具与模型的数据策略处理');
    }
  }
}

let selectedCapability = null;
async function bindCapabilityScreens() {
  const shelf = document.querySelector('#screen-shelf .cap-main');
  if (!shelf) return;

  const render = async () => {
    const { modules, readiness } = await capabilityState();
    const release = await api('/api/workbench').then(status => status.version).catch(() => null);
    const registered = new Set(modules.map(item => item.id));
    const runToggle = async (id, enabled) => {
      try {
        await toggleCapability(id, enabled);
      } catch (error) {
        setNote(document.querySelector('#capability-note'), `切换失败：${error.message}`, false);
      }
      await render();
    };

    if (shelf) {
      const head = shelf.querySelector('.cap-head');
      shelf.querySelectorAll('.cap-group').forEach(node => node.remove());

      const note = document.createElement('span');
      note.className = 'cap-note';
      note.id = 'capability-note';
      note.textContent = '✓ 配置仅保存于本机 · 开关即时生效';
      if (head) {
        const existing = head.querySelector('.cap-note');
        if (existing) existing.replaceWith(note);
        else head.appendChild(note);
      }

      const registryGroup = document.createElement('section');
      registryGroup.className = 'cap-group';
      registryGroup.innerHTML = '<h2><b>扩展模块</b> 独立扩展层 · 可开关</h2>';
      const registryGrid = document.createElement('div');
      registryGrid.className = 'cap-grid';
      if (modules.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'hint';
        empty.textContent = '注册表为空：本机没有可执行的能力，或注册表文件尚未创建。'
          + '启动一次桥接会按真实依赖补齐缺失项（见 docs/project/capability-registry.md）。';
        registryGroup.appendChild(empty);
      }
      modules.forEach(item => {
        registryGrid.appendChild(capabilityCard({
          icon: '◈',
          title: item.label || item.id,
          status: item.enabled ? '已启用' : '已停用',
          statusClass: item.enabled ? 'on' : 'rsv',
          text: `${item.purpose || ''}${item.purpose ? ' ' : ''}实现：${item.provider}`,
          source: item.detailOnly ? '点击查看详细设置' : `扩展 ${item.id}`,
          capabilityId: item.id,
          enabled: item.enabled,
          onToggle: item.detailOnly ? undefined : next => runToggle(item.id, next),
        }));
      });
      registryGroup.appendChild(registryGrid);
      shelf.appendChild(registryGroup);

      const readyOnly = readiness.filter(item => !registered.has(item.id));
      const readyGroup = document.createElement('section');
      readyGroup.className = 'cap-group';
      readyGroup.innerHTML = '<h2><b>就绪视图</b> 依赖检查 · 无独立开关</h2>';
      const readyGrid = document.createElement('div');
      readyGrid.className = 'cap-grid';
      readyOnly.forEach(item => {
        readyGrid.appendChild(capabilityCard({
          icon: item.ready ? '✓' : '—',
          title: item.label || item.id,
          status: item.ready ? '就绪' : '不可用',
          statusClass: item.ready ? 'basic' : 'rsv',
          text: item.detail || '',
          source: `就绪检查 ${item.id}`,
        }));
      });
      readyGroup.appendChild(readyGrid);
      shelf.appendChild(readyGroup);

      const nativeGroup = document.createElement('section');
      nativeGroup.className = 'cap-group';
      nativeGroup.innerHTML = '<h2><b>DSH 原生</b> 由 Harness 自带 · 不由 Sumika 开关</h2>';
      const nativeGrid = document.createElement('div');
      nativeGrid.className = 'cap-grid';
      NATIVE_CARDS.forEach(card => {
        nativeGrid.appendChild(capabilityCard({
          icon: card.icon, title: card.title, status: '原生', statusClass: 'basic',
          text: card.text, source: 'DSH 原生',
        }));
      });
      nativeGroup.appendChild(nativeGrid);
      shelf.appendChild(nativeGroup);

      // Clicking a card fills the detail column; the first registry entry is the
      // default so the panel never shows a capability that is not present.
      const detail = [
        ...modules.map(item => ({ card: null, entry: item, readinessRow: null })),
        ...readyOnly.map(item => ({ card: null, entry: null, readinessRow: item })),
        ...NATIVE_CARDS.map(item => ({ card: null, entry: null, readinessRow: null })),
      ];
      const cards = Array.from(shelf.querySelectorAll('.cap-card'));
      cards.forEach((card, index) => {
        if (index < detail.length) detail[index].card = card;
        card.style.cursor = 'pointer';
        card.setAttribute('tabindex', '0');
        const select = () => {
          const target = detail.find(entry => entry.card === card);
          selectedCapability = target?.entry?.id || target?.readinessRow?.id || card.querySelector('h4')?.textContent;
          cards.forEach(item => item.classList.toggle('selected', item === card));
          renderCapabilityDetail(card, target?.entry, target?.readinessRow, release);
        };
        card.addEventListener('click', event => {
          if (event.target.closest('[data-capability-switch]')) return;
          select();
        });
        card.addEventListener('keydown', event => {
          if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); }
        });
      });
      const selected = detail.find(item => (item.entry?.id || item.readinessRow?.id || item.card?.querySelector('h4')?.textContent) === selectedCapability) || detail[0];
      if (selected?.card) selected.card.click();

      // Present capabilities by user task; implementation origin stays in detail.
      const businessGroups = new Map();
      for (const [id, title] of [['development','开发'],['office','办公'],['companion','陪伴']]) {
        const section = document.createElement('section');section.className = 'cap-group';
        const heading = document.createElement('h2');const label = document.createElement('b');
        label.textContent = title;heading.append(label);section.append(heading);
        const grid = document.createElement('div');grid.className = 'cap-grid';section.append(grid);
        businessGroups.set(id,{section,grid});
      }
      for (const item of detail) {
        const id = item.entry?.id || item.readinessRow?.id;
        const group = !id || ['desktop','browser','schedule'].includes(id) ? 'development'
          : ['ocr','office','office-render'].includes(id) ? 'office' : 'companion';
        if(item.card)businessGroups.get(group).grid.append(item.card);
      }
      shelf.querySelectorAll('.cap-group').forEach(el=>el.remove());
      for(const {section,grid} of businessGroups.values())if(grid.children.length)shelf.append(section);

      const side = document.querySelector('.cap-side');
      const panels = side ? side.querySelectorAll('.panel:not([data-extra-action])') : [];
      if (panels[1]) {
        const enabledCount = modules.filter(item => item.enabled).length;
        const unavailable = readiness.filter(item => !item.ready).length;
        const cells = panels[1].querySelectorAll('.st-grid > div');
        const values = [enabledCount, modules.length - enabledCount, unavailable];
        cells.forEach((cell, index) => {
          const number = cell.querySelector('b');
          if (number && values[index] !== undefined) number.textContent = String(values[index]);
          const label = cell.querySelector('span');
          if (label) label.textContent = ['已启用','已停用','依赖缺失'][index];
        });
        const heading = panels[1].querySelector('h3 b');
        if (heading) heading.textContent = `${modules.length} 项能力`;
      }
      if (panels[2]) {
        const notes = panels[2].querySelector('.note-p');
        if (notes) {
          notes.innerHTML = '① 关闭开关只停用能力，历史数据与授权记录保留；<br>'
            + '② 「就绪」表示依赖已安装，与「已启用」分别显示，不互相代替；<br>'
            + '③ 权限、MCP 与凭据在设置 ·「连接与权限」内管理。';
        }
      }
    }


  };

  try {
    await render();
  } catch (error) {
    setNote(document.querySelector('.cap-note'), `能力数据读取失败：${error.message}`, false);
  }
}

/**
 * Settings facts that really are facts: the harness release from the managed
 * instance, the project the records describe, and the role service's own model.
 * The working model and the DSH credential live in the harness and are handed
 * over to it instead of being restated here.
 */
async function bindSettingsFacts(tree) {
  const [status, state] = await Promise.all([
    api('/api/workbench').catch(() => null),
    api('/api/state').catch(() => null),
  ]);

  const side = document.querySelector('.set-side');
  if (side) {
    const panel = side.querySelector('.panel');
    if (panel) {
      setRow(panel, 'DSH', status?.version
        ? `${status.version}${status.verified ? ' · 已验收' : ' · 未验收'}`
        : '未安装', Boolean(status?.version));
      setRow(panel, '项目', tree?.project?.path || tree?.project?.name || '未找到项目记录');
      setRow(panel, '数据', '本机 · 未上传', true);
    }

  }

  const modelsGroup = Array.from(document.querySelectorAll('#screen-settings .set-group'))
    .find(group => /模型与连接/.test(group.querySelector('h2')?.textContent || ''));
  if (!modelsGroup) return;
  const rows = Array.from(modelsGroup.querySelectorAll('.set-row'));
  const rowFor = name => rows.find(row => (row.querySelector('div')?.textContent || '').startsWith(name));

  const roleRow = rowFor('角色模型');
  const roleValue = roleRow?.querySelector('.val');
  if (roleValue) {
    roleValue.innerHTML = state?.role?.enabled === false
      ? '<span class="rsv-tag">已停用</span>'
      : `<b class="ok">● 已启用</b><b>${state?.role?.model || '未配置模型'}</b>`;
  }

  for (const name of ['工作模型', 'API 凭据']) {
    const row = rowFor(name);
    const value = row?.querySelector('.val');
    if (!value) continue;
    if (name === 'API 凭据') {
      // DSH keeps this in the profile's .credentials.yaml as plain text, so the
      // design's "本地加密保存" wording would be a false statement.
      const hint = row.querySelector('div small');
      if (hint) hint.textContent = '由 DSH 保存于本机 profile，不上传、不进 Git';
    }
    value.innerHTML = '<b>由 DSH 工作台管理</b>'
      + (name === '工作模型' ? '<button class="mini-btn">打开工作台 →</button>' : '');
    // The workbench is a screen of this page now, so these entries switch to it
    // instead of opening anything.
    const button = value.querySelector('button');
    if (button) button.addEventListener('click', () => { location.hash = 'board'; });
  }
}

/**
 * Mark the parts of the settings screen that are still the design's placeholder
 * and disable their controls, so a click cannot look like a working switch. Also
 * removes the two values that were never real: the sample checkpoint hash and the
 * MCP authorization count.
 */
const UNWIRED_REASON = '设计稿占位项，当前版本未接入后端';

function markGroupUnwired(group) {
  const heading = group.querySelector('h2');
  if (heading && !heading.querySelector('.rsv-tag')) {
    const tag = document.createElement('span');
    tag.className = 'rsv-tag';
    tag.textContent = '未接入';
    tag.title = UNWIRED_REASON;
    tag.style.marginLeft = '8px';
    heading.appendChild(tag);
  }
  group.querySelectorAll('button').forEach(node => {
    node.disabled = true;
    node.title = UNWIRED_REASON;
    node.style.opacity = '.55';
    node.style.cursor = 'default';
  });
}

async function bindUnwiredSettings() {
  const groups = Array.from(document.querySelectorAll('#screen-settings .set-group'));
  const byName = name => groups.find(group => (group.querySelector('h2')?.textContent || '').includes(name));

  for (const name of ['外观', '数据与存储', '关于']) {
    const group = byName(name);
    if (group) markGroupUnwired(group);
  }

  const checkpoint = Array.from(byName('数据与存储')?.querySelectorAll('.set-row') || [])
    .find(row => (row.querySelector('div')?.textContent || '').startsWith('检查点'));
  if (checkpoint) {
    const value = checkpoint.querySelector('.val');
    if (value) value.innerHTML = '<b>由连续性记录与 Git 管理</b>';
  }

  const permissions = byName('连接与权限');
  if (permissions) {
    const mcp = Array.from(permissions.querySelectorAll('.set-row'))
      .find(row => (row.querySelector('div')?.textContent || '').startsWith('MCP'));
    if (mcp) {
      const value = mcp.querySelector('.val');
      if (value) {
        value.textContent = '';
        const label = document.createElement('b');
        label.textContent = '由 DSH 工作台管理';
        const button = document.createElement('button');
        button.className = 'mini-btn';
        button.textContent = '打开工作台 →';
        button.addEventListener('click', () => { location.hash = 'board'; });
        value.append(label, button);
      }
    }
  }
}

// Each region has its own load/error state. One unavailable provider must not
// strand the rest of the client in its prototype state.
const syncBoard = () => {
  const active = location.hash === '#board';
  document.body.classList.toggle('on-board', active);
  if (active) void bindWorkbench();
};
window.addEventListener('hashchange', syncBoard);
syncBoard();
// A browser network outage must not destroy the iframe or its unsent draft.
// Native DSH owns transport reconnection; the shell never replays requests.
const networkNotice = document.createElement('div');
networkNotice.className = 'sumika-network-notice';
networkNotice.setAttribute('role', 'status');
networkNotice.hidden = true;
document.body.append(networkNotice);
function syncNetworkNotice() {
  networkNotice.hidden = navigator.onLine;
  networkNotice.textContent = navigator.onLine ? ''
    : '浏览器处于离线状态。当前页面与未发送草稿已保留，请恢复连接后检查任务状态。';
}
window.addEventListener('offline', () => { syncNetworkNotice(); void refreshHeader(); });
window.addEventListener('online', () => {
  syncNetworkNotice();
  void refreshHeader();
  // Network availability can lag behind the browser's online event.
  // Only repeat this read; never repeat an outstanding task or write.
  setTimeout(() => void refreshHeader(), 500);
});
syncNetworkNotice();
const showRegionError = (selector, error) => {
  const region = document.querySelector(selector);
  if (!region) return;
  const note = document.createElement('p');
  note.className = 'sumika-region-error';
  note.textContent = `暂时无法加载：${error.message}`;
  region.prepend(note);
};
void refreshHeader();
void api('/api/roles').then(async roles => {
  bindRoster(roles);
  await bindRoleImport(roles);
  await bindRoomChat(roles.active?.id || null);
}).catch(error => showRegionError('.roster', error));
window.sumikaSettingsReady = Promise.allSettled([
  bindCapabilityScreens().catch(error => showRegionError('.cap-main', error)),
  api('/api/tree').catch(() => ({})).then(bindSettingsFacts)
    .catch(error => showRegionError('.set-main', error)),
  bindUnwiredSettings(),
]);
window.addEventListener('sumika-modules-changed', () => void bindCapabilityScreens());
window.addEventListener('sumika-role-resources-changed', () => {
  void api('/api/roles').then(bindRoster).catch(error=>showRegionError('.roster',error));
});
