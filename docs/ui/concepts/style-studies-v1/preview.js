import { studies, categories, capabilities, demo } from './studies.js';
import { mountRoom } from './room.js';

const query=new URLSearchParams(location.search);
const state={
  study:Object.hasOwn(studies,query.get('study'))?query.get('study'):'a',
  page:query.get('page')==='capabilities'?'capabilities':'companion',
  category:'senses',view:query.get('view')==='pet'?'pet':'client',draft:'',
  added:['voice','screen','ocr','translate'],library:query.get('library')==='1',
  libraryCategory:'senses',configuration:null,history:false,collapsed:false,transparent:false,hidden:false,
};
const app=document.getElementById('app');
const review=document.getElementById('review');
let controller=null;
let roomKey='';
let generation=0;
let previousFocus=null;
const escape=(value)=>String(value).replace(/[&<>"']/g,character=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const icon=(name)=>`<i data-lucide="${name}" aria-hidden="true"></i>`;
const button=(name,label,attributes='')=>`<button type="button" class="icon-button" aria-label="${label}" data-tip="${label}" ${attributes}>${icon(name)}</button>`;
const modalOpen=()=>state.library||Boolean(state.configuration)||state.history;

function navigation() {
  const items=[['companion','陪伴','house'],['workbench','工作台','panels-top-left'],['capabilities','能力','sparkles'],['characters','角色','user-round'],['settings','设置','settings-2']];
  return `<header class="navigation"><a class="wordmark" href="./?study=${state.study}" aria-label="Sumika 设计首页"><span class="brand-mark">${icon('house')}</span><strong>sumika</strong><small>すみか</small></a><nav class="main-nav" aria-label="主导航">${items.map(([id,label,symbol])=>`<button type="button" data-page="${id}" aria-current="${state.page===id?'page':'false'}">${icon(symbol)}<span>${label}</span></button>`).join('')}</nav><div class="nav-end"><span class="demo-mark">设计示例</span>${button('picture-in-picture-2','切换到桌宠','data-view="pet"')}<span class="avatar-dot">澄</span></div></header>`;
}

function compose(compact=false) {
  return `<form class="composer ${compact?'compact':''}"><textarea aria-label="聊天消息" rows="${compact?1:2}" placeholder="和 Sumika 说点什么…">${escape(state.draft)}</textarea><div class="composer-tools">${compact?'':button('mic','语音未配置','data-config="voice"')}<span class="connection-state">未连接服务</span>${button('arrow-up','设计示例，不发送消息','disabled')}</div></form>`;
}

function messageList() {
  return `<div class="messages"><time class="conversation-date">今天 · ${demo.time}</time><article class="message"><span>Sumika</span><p>${demo.first}</p><time>${demo.time}</time></article><article class="message from-user"><span>你</span><p>${demo.user}</p></article><article class="message"><span>Sumika</span><p>${demo.last}</p></article></div>`;
}

function chat() {
  return `<aside class="chat" aria-label="示例会话"><header class="chat-heading"><div><span class="section-index">WITH YOU / 01</span><h2>和 Sumika 聊聊</h2><p>今天，也在这里。</p></div>${button('history','查看示例历史','data-history')}</header>${messageList()}<div class="chat-entry">${compose()}<div class="chat-foot"><span>${icon('shield-check')}仅本地预览</span><span>示例对话</span></div></div></aside>`;
}

function scene() {
  return `<section class="scene" aria-label="示例居所"><div class="room" aria-busy="true"></div><header class="scene-title"><span class="scene-kicker">SUMIKA / DAY 01</span><h1>今天，也在一起。</h1><p>おかえり。欢迎回来。</p></header><div class="scene-clock"><time>${demo.time}</time><span>居所 · 午后</span></div><div class="scene-status"><span class="status-dot"></span>Sumika · 窗边<span>静态场景</span></div>${state.study==='e'?'<div class="episode-strip"><span>01</span><strong>我们的日常</strong><span>日々のこと</span></div>':''}</section>`;
}

function home() {
  if(state.study==='b')return `<div class="home cinematic">${scene()}<section class="dialogue" aria-label="示例会话"><div class="dialogue-copy"><div class="speaker">Sumika <span>すみか</span></div><p>${demo.last}</p><span class="dialogue-time">今天 · ${demo.time}</span></div><div class="dialogue-entry">${button('history','查看示例历史','data-history')}${compose()}</div></section></div>`;
  return `<div class="home">${scene()}${chat()}</div>`;
}

function categoryTabs(current,attribute) {
  return `<div class="category-tabs" role="tablist" aria-label="能力分类">${Object.entries(categories).map(([id,category])=>`<button type="button" role="tab" aria-selected="${current===id}" data-${attribute}="${id}">${icon(category.icon)}<span>${category.name}</span></button>`).join('')}</div>`;
}

function moduleCard(id,index,list) {
  const entry=capabilities[id];
  return `<article class="capability" data-module="${id}" tabindex="0"><header><span class="capability-icon">${icon(entry.icon)}</span><span class="module-code">${entry.english}</span><span class="badge">未启用</span></header><h2>${entry.name}</h2><p class="module-description">${entry.description}</p><dl><div><dt>实现</dt><dd>未配置</dd></div><div><dt>权限</dt><dd>${entry.permission}</dd></div></dl><footer><span class="status-dot"></span><span>等待配置</span>${button('settings-2',`查看${entry.name}配置`,`data-config="${id}"`)}</footer><div class="module-menu">${button('arrow-left','向前移动',`data-move="${id}" data-direction="-1" ${index===0?'disabled':''}`)}${button('arrow-right','向后移动',`data-move="${id}" data-direction="1" ${index===list.length-1?'disabled':''}`)}${button('x',`移除${entry.name}卡片`,`data-remove="${id}"`)}</div></article>`;
}

function capabilityPage() {
  const list=state.added.filter(id=>capabilities[id].category===state.category);
  return `<section class="capabilities-page"><header class="page-title"><div><span class="eyebrow">SUMIKA / CAPABILITIES</span><h1>让她，多懂你一点。</h1><p>${categories[state.category].subtitle}</p></div><span class="page-counter"><strong>${String(state.added.length).padStart(2,'0')}</strong>已添加 · 均未启用</span></header><div class="capabilities-body">${categoryTabs(state.category,'category')}<section class="module-content" role="tabpanel" aria-label="${categories[state.category].name}"><div class="section-heading"><h2>${categories[state.category].name}</h2><span>${list.length} 个已添加</span></div><div class="module-grid">${list.map((id,index)=>moduleCard(id,index,list)).join('')}<button type="button" class="add-module" aria-label="添加模块" data-tip="添加模块" data-library>${icon('plus')}</button></div>${state.category==='life'?'<p class="empty-caption">尚未添加生活与陪伴模块</p>':''}<div class="capability-footer"><span>${icon('shield-check')}设备权限未授予</span><span>配置完成后仍需单独启用与授权</span></div></section></div></section>`;
}

function placeholderPage() {
  const content={workbench:['工作台',['会话','任务','模型策略']],characters:['角色与居所',['角色','场景资源','声音']],settings:['设置',['外观与窗口','连接与权限','数据与诊断']]}[state.page];
  return `<section class="placeholder-page"><span class="eyebrow">SUMIKA / DESIGN STUDY</span><h1>${content[0]}</h1><p>设计示例 · 本页将在选稿后深化</p><div>${content[1].map(label=>`<section><h2>${label}</h2><span>尚未配置</span></section>`).join('')}</div></section>`;
}

function pet() {
  if(state.hidden)return `<div class="pet-hidden"><button type="button" data-show-pet>${icon('picture-in-picture-2')}显示桌宠预览</button></div>`;
  return `<div class="pet-surface"><section class="pet" aria-label="桌宠设计示例"><div class="room" aria-busy="true"></div><div class="pet-controls">${button('maximize-2','打开完整客户端','data-view="client"')}${button('image','显示或隐藏背景',`data-transparent aria-pressed="${state.transparent}"`)}${button('message-circle','收起或展开聊天',`data-collapse aria-expanded="${!state.collapsed}"`)}${button('x','隐藏桌宠','data-hide-pet')}</div><div class="pet-bubble"><strong>Sumika</strong><p>${demo.pet}</p></div><span class="pet-label">设计示例 · 静态场景</span>${state.collapsed?'':compose(true)}</section></div>`;
}

function library() {
  const entries=Object.entries(capabilities).filter(([,entry])=>entry.category===state.libraryCategory);
  return `<div class="scrim"><section class="drawer" role="dialog" aria-modal="true" aria-labelledby="library-title"><header class="drawer-title"><div><span class="eyebrow">MODULE LIBRARY</span><h2 id="library-title">添加模块</h2></div>${button('x','关闭模块库','data-close')}</header>${categoryTabs(state.libraryCategory,'library-category')}<div class="library-list">${entries.map(([id,entry])=>`<article class="library-item"><span class="capability-icon">${icon(entry.icon)}</span><div><h3>${entry.name}</h3><p>${state.added.includes(id)?'已添加 · 未启用':'未添加 · 未配置'}</p></div>${button(state.added.includes(id)?'check':'plus',state.added.includes(id)?`${entry.name}已添加`:`添加${entry.name}`,`data-add="${id}" ${state.added.includes(id)?'disabled':''}`)}</article>`).join('')}</div><p class="drawer-note">添加仅改变页面布局，不启用功能或授予权限。</p></section></div>`;
}

function configuration() {
  const entry=capabilities[state.configuration];
  return `<div class="scrim"><section class="drawer configuration" role="dialog" aria-modal="true" aria-labelledby="configuration-title"><header class="drawer-title"><div><span class="eyebrow">${entry.english}</span><h2 id="configuration-title">${entry.name}</h2></div>${button('x','关闭配置示例','data-close')}</header><p class="configuration-description">${entry.description}</p><dl><div><dt>实现来源</dt><dd>${entry.source} · 未选择</dd></div><div><dt>组合能力</dt><dd>${entry.dependency}</dd></div><div><dt>启用状态</dt><dd>未启用</dd></div><div><dt>权限状态</dt><dd>${entry.permission}</dd></div></dl><p class="drawer-note">配置界面示例 · 未连接真实服务</p></section></div>`;
}

function history() {
  return `<div class="scrim"><section class="drawer history-drawer" role="dialog" aria-modal="true" aria-labelledby="history-title"><header class="drawer-title"><h2 id="history-title">示例会话</h2>${button('x','关闭示例历史','data-close')}</header>${messageList()}</section></div>`;
}

function paintReview() {
  review.innerHTML=`<div class="review-title">SUMIKA <span>风格对照 / 设计示例</span></div><div class="study-selector" aria-label="设计方案">${Object.entries(studies).map(([id,study])=>`<button type="button" data-study="${id}" aria-pressed="${state.study===id}">${id.toUpperCase()}<span>${study.name}</span></button>`).join('')}</div><div class="review-links"><a href="./board.html?study=${state.study}">设计板</a><a href="./board.html?overview=1">总览</a></div>`;
}

async function render() {
  const version=++generation;
  document.body.dataset.ready='false';
  delete document.body.dataset.error;
  const needsRoom=state.view==='pet'?!state.hidden:state.page==='companion';
  const nextKey=JSON.stringify({variant:state.study,compact:state.view==='pet',transparent:state.view==='pet'&&state.transparent});
  const preserved=controller&&needsRoom&&roomKey===nextKey?document.querySelector('.room'):null;
  if(preserved)preserved.remove();
  else {controller?.dispose();controller=null;}
  document.body.dataset.view=state.view;
  document.body.dataset.study=state.study;
  paintReview();
  app.innerHTML=`<main class="shell study-${state.study} ${state.view==='pet'?'pet-mode':''}">${state.view==='pet'?pet():navigation()+`<div class="page-content">${state.page==='companion'?home():state.page==='capabilities'?capabilityPage():placeholderPage()}</div>`}${state.library?library():state.configuration?configuration():state.history?history():''}</main>`;
  window.lucide.createIcons();
  if(preserved)document.querySelector('.room')?.replaceWith(preserved);
  if(modalOpen()) {
    document.querySelector('.navigation')?.setAttribute('inert','');
    document.querySelector('.page-content')?.setAttribute('inert','');
    document.querySelector('.pet-surface')?.setAttribute('inert','');
    review.setAttribute('inert','');
    document.querySelector('[data-close]')?.focus();
  } else review.removeAttribute('inert');
  try {
    const container=preserved?null:document.querySelector('.room');
    if(container) {
      const room=await mountRoom(container,JSON.parse(nextKey));
      if(version!==generation){room.dispose();return;}
      controller=room;roomKey=nextKey;
      container.setAttribute('aria-busy','false');
    }
    if(version===generation)document.body.dataset.ready='true';
  } catch(error) {
    if(version!==generation)return;
    document.body.dataset.error=error.message;
    const alert=document.createElement('p');alert.className='render-error';alert.role='alert';alert.textContent=`场景载入失败：${error.message}`;app.append(alert);
  }
}

function closeModal() {
  state.library=false;state.configuration=null;state.history=false;
  void render().then(()=>{if(previousFocus)document.querySelector(previousFocus)?.focus();});
}

document.addEventListener('input',event=>{if(event.target.matches('textarea'))state.draft=event.target.value;});
document.addEventListener('submit',event=>event.preventDefault());
document.addEventListener('visibilitychange',()=>controller?.setVisible(!document.hidden));
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&modalOpen()){closeModal();return;}
  if(event.key==='Tab'&&modalOpen()) {
    const buttons=[...document.querySelectorAll('.drawer button:not(:disabled)')];
    const first=buttons[0],last=buttons.at(-1);
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  }
});
document.addEventListener('click',event=>{
  const target=event.target.closest('button');
  if(!target||target.disabled||document.body.dataset.ready!=='true')return;
  const data=target.dataset;
  if('close'in data){closeModal();return;}
  if(data.study)state.study=data.study;
  else if(data.page)state.page=data.page;
  else if(data.view){state.view=data.view;state.hidden=false;state.history=false;}
  else if(data.category)state.category=data.category;
  else if(data.libraryCategory)state.libraryCategory=data.libraryCategory;
  else if('library'in data){state.library=true;state.libraryCategory=state.category;previousFocus='[data-library]';}
  else if(data.add){if(!state.added.includes(data.add))state.added.push(data.add);}
  else if(data.remove){state.added=state.added.filter(id=>id!==data.remove);}
  else if(data.move){
    const list=state.added.filter(id=>capabilities[id].category===state.category);
    const index=list.indexOf(data.move),next=index+Number(data.direction);
    if(next<0||next>=list.length)return;
    const from=state.added.indexOf(list[index]),to=state.added.indexOf(list[next]);
    [state.added[from],state.added[to]]=[state.added[to],state.added[from]];
  }
  else if(data.config){state.configuration=data.config;previousFocus=`[data-config="${data.config}"]`;}
  else if('history'in data){state.history=true;previousFocus='[data-history]';}
  else if('collapse'in data)state.collapsed=!state.collapsed;
  else if('transparent'in data){
    state.transparent=!state.transparent;controller?.setTransparent(state.transparent);
    roomKey=JSON.stringify({variant:state.study,compact:true,transparent:state.transparent});
    target.setAttribute('aria-pressed',String(state.transparent));return;
  }
  else if('hidePet'in data)state.hidden=true;
  else if('showPet'in data)state.hidden=false;
  else return;
  void render();
});

window.studyPreview={faceBounds:()=>controller?.getFaceBounds?.()??null};
if(query.get('raw')==='1')document.body.classList.add('raw');
void render();
