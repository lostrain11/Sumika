import { mountRoom } from './room.js';

const query = new URLSearchParams(location.search);
const themes = {
  afternoon: { label:'午后陪伴', title:'午后的居所', place:'窗边', activity:'休息', time:'14:32', greeting:'おかえり。', subtitle:'欢迎回来，今天也在这里。', first:'回来啦。\n阳光刚好落在窗边，要一起坐一会儿吗？', reply:'先陪我待一会儿吧。', last:'好呀。\n不着急，我们慢慢来。', pet:'我在这里，\n陪你慢慢来。' },
  evening: { label:'夜晚居所', title:'灯还为你亮着', place:'客厅', activity:'晚间休息', time:'21:08', greeting:'おつかれさま。', subtitle:'今天也辛苦了。', first:'外面已经安静下来了。\n我留了一盏灯，等你回来。', reply:'今天的事情终于忙完了。', last:'那就先把事情放在一边吧。\n剩下的时间，留给自己。', pet:'辛苦啦。\n今晚就慢一点吧。' },
  work: { label:'共同工作', title:'一起，把事情做好', place:'书桌', activity:'工作', time:'10:24', greeting:'一緒に、少しずつ。', subtitle:'今天，从一件小事开始。', first:'桌面收拾好了。\n今天想从哪件事情开始？', reply:'先整理一下新的界面想法。', last:'好，我陪你。\n想到什么，就告诉我。', pet:'桌子收拾好了，\n我陪你一起。' },
};
const initialTheme = Object.hasOwn(themes, query.get('theme')) ? query.get('theme') : 'afternoon';
const state = { theme:initialTheme, view:query.get('view') === 'pet' ? 'pet' : 'client', page:initialTheme === 'work' ? 'work' : 'home', draft:'', library:query.get('library') === '1', transparent:false, chatCollapsed:false, hidden:false, homeModules:['music','note'], workModules:['tasks','policy','note'] };
const modules = {
  music:{ name:'音乐', icon:'music-2', status:'未启用', title:'窗边的轻音乐', detail:'等待连接音乐来源', foot:'播放列表 · 尚未配置' },
  note:{ name:'随手记', icon:'notebook-pen', status:'本地示例', title:'把想法留在这里', detail:'「想和她一起，做一个小小的家。」', foot:'今天 · 1 条示例笔记' },
  tasks:{ name:'今日事项', icon:'list-todo', status:'示例', title:'留一点时间，给重要的事', detail:'task-list', foot:'1 / 3 项完成 · 示例数据' },
  policy:{ name:'模型策略', icon:'route', status:'未配置', title:'推荐后，由你确认', detail:'额度未知 · 未选择连接', foot:'付费回退：不自动启用' },
  voice:{ name:'语音对话', icon:'mic', status:'未启用', title:'听见彼此的声音', detail:'麦克风权限未授予', foot:'ASR / TTS · 尚未配置' },
  vision:{ name:'屏幕观察', icon:'scan-eye', status:'未启用', title:'一起看见眼前', detail:'屏幕权限未授予', foot:'尚未配置 · 不在采集' },
  memory:{ name:'回忆', icon:'book-heart', status:'未启用', title:'属于我们的片段', detail:'当前角色独立记忆', foot:'记忆来源 · 尚未配置' },
};
let room = null;
let roomContext = '';
let renderGeneration = 0;
const app = document.getElementById('app');
const review = document.getElementById('review-bar');
const escape = (value) => String(value).replace(/[&<>"']/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const icon = (name) => `<i data-lucide="${name}" aria-hidden="true"></i>`;
const iconButton = (name, label, attributes='') => `<button type="button" class="icon" aria-label="${label}" data-tip="${label}" ${attributes}>${icon(name)}</button>`;
const currentModules = () => state.page === 'work' ? state.workModules : state.homeModules;

function composer(pet = false) {
  if (pet) return `<form class="pet-composer"><textarea aria-label="聊天消息" rows="1" placeholder="和 Sumika 说点什么…">${escape(state.draft)}</textarea>${iconButton('arrow-up','静态预览，不发送消息','disabled')}</form>`;
  return `<form class="composer"><textarea aria-label="聊天消息" rows="2" placeholder="和 Sumika 说点什么…">${escape(state.draft)}</textarea><div class="composer-bottom">${iconButton('mic','语音未启用','data-notice="语音未启用，当前预览不会访问麦克风"')}<button type="button" class="composer-model" data-notice="模型连接未配置，当前预览不调用模型">${icon('sparkles')}未配置连接${icon('chevron-down')}</button><button class="icon send" type="submit" aria-label="静态预览，不发送消息" disabled>${icon('arrow-up')}</button></div></form>`;
}

function moduleCard(id, index) {
  const entry = modules[id];
  const content = entry.detail === 'task-list' ? `<div class="task-list"><span class="done">${icon('circle-check')}整理今天的想法</span><span>${icon('circle')}画一张新的界面</span><span>${icon('circle')}留出休息的时间</span></div>` : `<strong>${entry.title}</strong><p>${entry.detail}</p>`;
  return `<article class="module" data-module="${id}" tabindex="0"><div class="module-heading">${icon(entry.icon)}<span>${entry.name}</span><span class="module-status">${entry.status}</span></div>${content}<div class="module-foot"><span>${entry.foot}</span></div><div class="module-menu">${iconButton('arrow-left','向前移动',`data-move="${id}" data-direction="-1" ${index === 0 ? 'disabled' : ''}`)}${iconButton('arrow-right','向后移动',`data-move="${id}" data-direction="1" ${index === currentModules().length - 1 ? 'disabled' : ''}`)}${iconButton('x','从当前页移除',`data-remove="${id}"`)}</div></article>`;
}

function moduleGrid(work = false) {
  return `<div class="${work ? 'work-modules' : 'module-strip'}" aria-label="当前页模块">${currentModules().map(moduleCard).join('')}<button type="button" class="add-module" aria-label="添加模块" data-tip="添加模块" data-library>${icon('plus')}</button></div>`;
}

function chat() {
  const theme = themes[state.theme];
  return `<aside class="conversation" aria-label="与 Sumika 的对话"><header class="chat-heading"><span class="profile-dot">澄</span><div><strong>Sumika</strong><small>和你在一起</small></div>${iconButton('history','会话历史','data-notice="这里展示的是独立示例会话，不读取你的聊天历史"')}</header><div class="messages"><p class="chat-date">今天 · ${theme.time}</p><article class="chat-message"><span class="message-label">Sumika</span><p>${theme.first.replaceAll('\n','<br>')}</p><time>${theme.time}</time></article><article class="chat-message user"><span class="message-label">你</span><p>${theme.reply}</p></article><article class="chat-message"><span class="message-label">Sumika</span><p>${theme.last.replaceAll('\n','<br>')}</p></article><span class="message-stamp">${icon('heart')}陪伴，不必匆忙</span></div>${composer()}<footer class="chat-bottom"><span>${icon('shield-check')}本地设计预览</span><span>示例对话 · 未连接服务</span></footer></aside>`;
}

function scene(work = false) {
  const theme = themes[state.theme];
  return `<section class="scene-zone" aria-label="${theme.label}场景"><div class="room" aria-label="示例角色与原创房间" aria-busy="true"></div><div class="scene-meta"><div><small>SUMIKA / ${theme.place}</small><h1>${work ? '在你身边' : theme.greeting}</h1></div><time>${theme.time}<span>日程示意</span></time></div><p class="scene-subtitle">${work ? '一起，从眼前的这一件开始。' : theme.subtitle}</p><div class="scene-footer"><div class="presence"><i></i>Sumika · ${theme.activity}<span> / 场景示意</span></div>${work ? `<div class="work-dialogue"><strong>Sumika</strong><p>${theme.last.replaceAll('\n','<br>')}</p></div>${composer()}` : moduleGrid()}</div></section>`;
}

function workbench() {
  return `<section class="workbench" aria-label="工作台"><div class="work-title"><div><span class="eyebrow">MY WORKSPACE</span><h1>我的工作台</h1><p>今天，和 Sumika 一起。</p></div><div class="work-date"><strong>06</strong>九月 · 星期日</div></div><div class="workspace-tabs"><span>我的模块</span><span>本地工作区 · 示例</span></div>${moduleGrid(true)}<section class="workspace-history"><header class="section-heading"><span>最近的对话</span><small>示例记录</small></header><div class="history-row"><span>${icon('message-circle')}关于我们的小小居所</span><time>今天</time></div><div class="history-row"><span>${icon('message-circle')}新的界面，有了些想法</span><time>昨天</time></div></section></section>`;
}

function detailPage() {
  const character = state.page === 'characters';
  const entries = character ? [['角色','Sumika · VRoid 示例模型'],['场景资源','午后 / 夜晚 / 工作 · 原创构图'],['声音','未配置'],['独立记忆','未启用，不共享']] : [['连接','尚未配置模型服务'],['权限','麦克风、屏幕、摄像头均未授权'],['数据','独立内存示例，不读取生产数据'],['诊断','设计预览，无 Runtime 连接']];
  return `<section class="detail-page"><span class="eyebrow">SUMIKA</span><h1>${character ? '角色与居所' : '设置'}</h1><p>设计预览 · 配置界面待选稿后深化</p><div class="detail-grid">${entries.map(([name,value])=>`<section class="detail-item"><strong>${name}</strong><small>${value}</small></section>`).join('')}</div></section>`;
}

function library() {
  return `<div class="modal-scrim"><section class="module-library" role="dialog" aria-modal="true" aria-labelledby="library-title"><header class="library-title"><h2 id="library-title">添加模块</h2>${iconButton('x','关闭模块库','data-close-library')}</header><div class="library-location">添加到 ${state.page === 'work' ? '工作台' : '陪伴页'}<span> · ${currentModules().length} 个已添加</span></div><p class="library-group">日常与工作</p>${Object.entries(modules).map(([id,entry])=>{ const present=currentModules().includes(id); return `<article class="library-row"><span class="library-icon">${icon(entry.icon)}</span><div><strong>${entry.name}</strong><p class="${entry.status==='未启用' ? 'pending' : ''}">${present ? '已在当前页' : entry.status}${['voice','vision'].includes(id) ? ' · 需要单独授权' : ''}</p></div>${iconButton(present ? 'check' : 'plus', present ? `${entry.name}已添加` : `添加${entry.name}`,`${present ? 'disabled' : ''} data-add="${id}"`)}</article>`;}).join('')}<p class="library-note">添加到页面后再配置。设备权限仍需单独确认。</p></section></div>`;
}

function clientMarkup() {
  const nav=[['home','陪伴','house'],['work','工作台','panels-top-left'],['characters','角色','user-round'],['settings','设置','settings-2']];
  return `<main class="app-shell ${state.theme==='evening' ? 'night' : ''}"><header class="topbar"><div class="wordmark"><span class="brand-icon">${icon('house')}</span><strong>sumika</strong><small>すみか</small></div><nav class="main-nav" aria-label="主导航">${nav.map(([id,label,symbol])=>`<button type="button" data-page="${id}" class="${state.page===id ? 'active' : ''}" aria-current="${state.page===id ? 'page' : 'false'}">${icon(symbol)}${label}</button>`).join('')}</nav><div class="top-actions"><span class="demo-mark"><i class="quiet-dot"></i>设计预览</span>${iconButton('picture-in-picture-2','切换到桌宠','data-view="pet"')}<span class="profile-dot">澄</span></div></header><div class="app-body ${state.page==='work' ? 'work' : ''}">${state.page==='home' ? scene()+chat() : state.page==='work' ? workbench()+scene(true) : detailPage()}</div>${state.library ? library() : ''}</main>`;
}

function petMarkup() {
  const theme=themes[state.theme];
  if (state.hidden) return `<main class="app-shell"><div class="pet-hidden"><button type="button" data-restore-pet>${icon('picture-in-picture-2')}重新显示桌宠预览</button></div></main>`;
  return `<main class="app-shell ${state.theme==='evening' ? 'night' : ''}"><div class="pet-view"><section class="pet-shell ${query.get('tools')==='1' ? 'show-tools' : ''}" aria-label="桌宠预览"><div class="room" aria-label="桌宠场景" aria-busy="true"></div><div class="pet-toolbar">${iconButton('maximize-2','打开完整客户端','data-view="client"')}${iconButton('image','显示或隐藏场景',`data-transparent aria-pressed="${state.transparent}"`)}${iconButton('message-circle','收起或展开聊天',`data-collapse aria-expanded="${!state.chatCollapsed}"`)}${iconButton('x','隐藏桌宠','data-hide-pet')}</div><div class="pet-bubble"><strong>Sumika</strong>${theme.pet.replaceAll('\n','<br>')}</div><span class="pet-caption">设计预览 · ${theme.activity}</span>${state.chatCollapsed ? '' : composer(true)}</section></div></main>`;
}

function paintReview() {
  review.innerHTML=`<div class="review-bar"><div><strong>SUMIKA / DESIGN STUDY 01</strong><span class="review-caption">双模式 · 独立示例</span></div><div class="review-tabs">${Object.entries(themes).map(([id,theme],index)=>`<button type="button" data-theme="${id}" aria-pressed="${state.theme===id}">${String(index+1).padStart(2,'0')} ${theme.label}</button>`).join('')}</div><div class="review-tabs view-tabs"><button type="button" data-view="client" aria-pressed="${state.view==='client'}">客户端</button><button type="button" data-view="pet" aria-pressed="${state.view==='pet'}">桌宠</button><a href="./board.html?theme=${state.theme}">设计板 ↗</a></div></div>`;
}

async function render() {
  const generation=++renderGeneration;
  document.body.dataset.ready='false';
  const roomOptions={variant:state.page==='work' && state.theme!=='evening' ? 'work' : state.theme,compact:state.view==='pet',transparent:state.transparent && state.view==='pet'};
  const nextContext=JSON.stringify(roomOptions);
  const needsRoom=state.view==='pet' ? !state.hidden : ['home','work'].includes(state.page);
  const preservedRoom=room && needsRoom && roomContext===nextContext ? document.querySelector('.room') : null;
  if(preservedRoom) preservedRoom.remove();
  else {room?.dispose();room=null;}
  paintReview();
  app.innerHTML=state.view==='pet' ? petMarkup() : clientMarkup();
  if(state.library) {
    document.querySelector('.topbar')?.setAttribute('inert','');
    document.querySelector('.app-body')?.setAttribute('inert','');
  }
  window.lucide.createIcons();
  if (state.library) document.querySelector('[data-close-library]')?.focus();
  if(preservedRoom) document.querySelector('.room')?.replaceWith(preservedRoom);
  const container=preservedRoom ? null : document.querySelector('.room');
  if (container) {
    try {
      const controller=await mountRoom(container,roomOptions);
      if (generation!==renderGeneration) { controller.dispose(); return; }
      room=controller;
      roomContext=nextContext;
      room.setVisible(!document.hidden);
      container.setAttribute('aria-busy','false');
    } catch(error) {
      document.body.dataset.renderError=error.message;
      notice(`场景载入失败：${error.message}`);
      return;
    }
  }
  if (generation===renderGeneration) document.body.dataset.ready='true';
}

function notice(message) {
  document.querySelector('.preview-notice')?.remove();
  const element=document.createElement('div');
  element.className='preview-notice'; element.role='status'; element.textContent=message;
  document.querySelector('.app-shell')?.append(element);
  setTimeout(()=>element.remove(),4000);
}

document.addEventListener('input',(event)=>{if(event.target.matches('textarea')) state.draft=event.target.value;});
document.addEventListener('submit',(event)=>event.preventDefault());
document.addEventListener('visibilitychange',()=>room?.setVisible(!document.hidden));
document.addEventListener('keydown',(event)=>{
  if (event.key==='Escape' && state.library) { state.library=false; render().then(()=>document.querySelector('[data-library]')?.focus()); }
  if (event.key==='Tab' && state.library) {
    const elements=[...document.querySelectorAll('.module-library button:not(:disabled)')];
    const first=elements[0],last=elements.at(-1);
    if (event.shiftKey && document.activeElement===first) {event.preventDefault();last.focus();}
    else if (!event.shiftKey && document.activeElement===last) {event.preventDefault();first.focus();}
  }
});
document.addEventListener('click',(event)=>{
  const button=event.target.closest('button');
  if(!button || button.disabled)return;
  const data=button.dataset;
  if(data.notice) { notice(data.notice);return; }
  if(data.theme) { state.theme=data.theme;state.page=data.theme==='work' ? 'work':'home';state.library=false; }
  else if(data.view) {state.view=data.view;state.hidden=false;state.library=false;}
  else if(data.page) {state.page=data.page;state.library=false;}
  else if('library' in data) state.library=true;
  else if('closeLibrary' in data) state.library=false;
  else if(data.add) {if(!currentModules().includes(data.add))currentModules().push(data.add);}
  else if(data.remove) {currentModules().splice(currentModules().indexOf(data.remove),1);}
  else if(data.move) {const list=currentModules();const index=list.indexOf(data.move);const next=index+Number(data.direction);if(next>=0 && next<list.length)[list[index],list[next]]=[list[next],list[index]];}
  else if('transparent' in data) {state.transparent=!state.transparent; room?.setTransparent(state.transparent);roomContext=JSON.stringify({variant:state.page==='work' && state.theme!=='evening' ? 'work' : state.theme,compact:true,transparent:state.transparent});button.setAttribute('aria-pressed',String(state.transparent));return;}
  else if('collapse' in data) state.chatCollapsed=!state.chatCollapsed;
  else if('hidePet' in data) state.hidden=true;
  else if('restorePet' in data) state.hidden=false;
  else return;
  void render();
});
if(query.get('raw')==='1') document.body.classList.add('raw');
void render();
