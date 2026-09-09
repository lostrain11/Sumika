import { mountRoom } from '/shared/room.js';
import { categories, capabilities } from '/shared/studies.js';

const themes = {
  sage:{name:'草绿',accent:'#50725f',tint:'#eef3ed'},
  sakura:{name:'樱粉',accent:'#a94067',tint:'#f9eff3'},
  blue:{name:'青蓝',accent:'#21798b',tint:'#edf5f7'},
  berry:{name:'莓红',accent:'#b42f54',tint:'#fcecf0'},
};
const query = new URLSearchParams(location.search);
const state = {
  mode:['client','wallpaper','pet'].includes(query.get('mode')) ? query.get('mode') : 'client',
  page:query.get('page') === 'capabilities' ? 'capabilities' : 'companion',
  chat:query.get('chat') !== 'closed',
  clientChat:true,
  theme:Object.hasOwn(themes,query.get('theme')) ? query.get('theme') : 'sakura',
  category:'senses',
  modules:['voice','screen','ocr','translate'],
  transparent:query.get('transparent') === '1',
};
const select = selector => document.querySelector(selector);
const all = selector => [...document.querySelectorAll(selector)];
const dialog = select('#dialog');
let room;
let dialogOpener;

function renderThemes() {
  all('.swatches').forEach(element => {
    element.innerHTML = Object.entries(themes).map(([id,theme]) => `<button class="swatch" style="--swatch:${theme.accent}" data-theme="${id}" aria-label="${theme.name}" title="${theme.name}" aria-pressed="${state.theme === id}"></button>`).join('');
  });
}
function applyTheme() {
  const theme = themes[state.theme];
  document.documentElement.style.setProperty('--accent',theme.accent);
  document.documentElement.style.setProperty('--tint',theme.tint);
  all('[data-theme]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.theme === state.theme)));
}
function renderModules() {
  select('.category-tabs').innerHTML = Object.entries(categories).map(([id,category]) => `<button id="tab-${id}" role="tab" aria-controls="module-grid" aria-selected="${id === state.category}" tabindex="${id === state.category ? 0 : -1}" data-category="${id}">${category.name}</button>`).join('');
  const modules = state.modules.filter(id => capabilities[id].category === state.category);
  select('#module-grid').setAttribute('aria-labelledby',`tab-${state.category}`);
  select('#module-grid').innerHTML = modules.map((id,index) => {
    const item = capabilities[id];
    return `<article class="capability" data-module="${id}"><header><h2>${item.name}</h2><span>未启用</span></header><p class="dependency">${item.source} · 未配置</p><p class="permission">${item.permission}</p><footer><button data-config="${id}">配置</button><div class="module-actions"><button data-move="${id}" aria-label="前移${item.name}" ${index === 0 ? 'disabled' : ''}>前移</button><button data-remove="${id}" aria-label="移除${item.name}">移除</button></div></footer></article>`;
  }).join('') + '<button class="add-module" aria-label="添加模块" title="添加模块" data-library><span class="plus" aria-hidden="true"></span></button>';
}
function showLibrary() {
  openDialog('添加模块',Object.entries(capabilities).filter(([,item]) => item.category === state.category).map(([id,item]) => `<section class="library-item"><div><h3>${item.name}</h3><p>${item.source} · 未启用</p></div><button data-add="${id}" ${state.modules.includes(id) ? 'disabled' : ''}>${state.modules.includes(id) ? '已添加' : '添加'}</button></section>`).join(''));
}
function openDialog(title,content) {
  if (!dialog.open) dialogOpener = document.activeElement;
  select('#dialog-title').textContent = title;
  select('#dialog-content').innerHTML = content;
  if (!dialog.open) dialog.showModal();
}
function renderSecondary() {
  const titles = {workbench:'工作台',character:'角色',settings:'设置'};
  const content = state.page === 'workbench'
    ? '<section class="setting-row"><div>会话与任务<p>未连接工作区</p></div><span>待接入</span></section><section class="setting-row"><div>模型策略<p>未连接服务</p></div><span>待接入</span></section>'
    : state.page === 'character'
      ? '<section class="setting-row"><div>Sumika<p>AvatarSample_A · 示例角色</p></div><span>窗边小憩</span></section><section class="setting-row"><div>角色主题色</div><div class="swatches" aria-label="角色主题色"></div></section>'
      : '<section class="setting-row"><div>角色主题色</div><div class="swatches" aria-label="角色主题色"></div></section><section class="setting-row"><div>桌面壁纸<p>原生桌面层未接入</p></div><button data-mode="wallpaper">预览构图</button></section><section class="setting-row"><div>桌宠背景</div><label><input type="checkbox" data-background '+(state.transparent ? 'checked' : '')+'> 透明</label></section>';
  select('#secondary').innerHTML = `<h1>${titles[state.page]}</h1>${content}`;
  renderThemes();
}
function updateView() {
  document.body.dataset.mode = state.mode;
  document.body.dataset.chat = state.chat ? 'open' : 'closed';
  document.body.dataset.page = state.page;
  select('#companion').hidden = state.page !== 'companion';
  select('#capabilities').hidden = state.page !== 'capabilities';
  select('#secondary').hidden = ['companion','capabilities'].includes(state.page);
  all('[data-page]').forEach(button => {
    if (button.dataset.page === state.page) button.setAttribute('aria-current','page');
    else button.removeAttribute('aria-current');
  });
  all('[data-chat]').forEach(button => {
    button.setAttribute('aria-expanded',String(state.chat));
    if (button.dataset.chat === 'toggle') button.textContent = state.chat ? '收起聊天' : '展开聊天';
  });
  const transparent = state.mode === 'pet' && state.transparent;
  document.documentElement.classList.toggle('transparent',transparent);
  select('[data-transparent]').textContent = state.transparent ? '显示场景' : '透明背景';
  room?.setTransparent(transparent);
  room?.setVisible(state.page === 'companion' && !document.hidden);
}
function setChat(open) {
  const focusWasInChat = select('#chat').contains(document.activeElement);
  state.chat = open;
  updateView();
  if (!open && focusWasInChat) {
    const selector = state.mode === 'client' ? '.restore-chat' : `.${state.mode === 'pet' ? 'pet' : 'wallpaper'}-controls [data-chat]`;
    select(selector).focus({preventScroll:true});
  }
}
function setMode(mode) {
  if (state.mode === 'client') state.clientChat = state.chat;
  state.mode = mode;
  state.page = 'companion';
  state.chat = mode === 'wallpaper' ? false : mode === 'client' ? state.clientChat : true;
  updateView();
  if (mode === 'client') select('[data-page="companion"]').focus({preventScroll:true});
  else document.activeElement?.blur();
}
document.addEventListener('click',event => {
  const button = event.target.closest('button');
  if (!button || button.disabled) return;
  const data = button.dataset;
  if (data.theme) { state.theme = data.theme; applyTheme(); }
  if (data.chat) setChat(data.chat === 'open' || (data.chat === 'toggle' && !state.chat));
  if (data.mode) setMode(data.mode);
  if (data.page) {
    state.page = data.page;
    if (data.page === 'capabilities') renderModules();
    else if (data.page !== 'companion') renderSecondary();
    updateView();
  }
  if (data.category) { state.category = data.category; renderModules(); select(`[data-category="${data.category}"]`).focus(); }
  if ('library' in data) showLibrary();
  if ('close' in data) dialog.close();
  if (data.add && !state.modules.includes(data.add)) { state.modules.push(data.add); renderModules(); showLibrary(); select('[data-close]').focus(); }
  if (data.remove) { state.modules = state.modules.filter(id => id !== data.remove); renderModules(); select('[data-library]').focus(); }
  if (data.move) {
    const index = state.modules.indexOf(data.move);
    const previous = state.modules.slice(0,index).findLastIndex(id => capabilities[id].category === state.category);
    if (previous >= 0) [state.modules[index],state.modules[previous]] = [state.modules[previous],state.modules[index]];
    renderModules();
    select(`[data-config="${data.move}"]`).focus();
  }
  if (data.config) {
    const item = capabilities[data.config];
    openDialog(item.name,`<div class="configuration"><p>实现方式 <strong>未配置</strong></p><p>${item.dependency}</p><p>${item.permission}</p><p>功能状态 <strong>未启用</strong></p></div>`);
  }
  if ('transparent' in data) { state.transparent = !state.transparent; updateView(); }
});
dialog.addEventListener('close',() => {
  if (dialogOpener?.isConnected) dialogOpener.focus();
  else select('[data-library]').focus();
});
document.addEventListener('keydown',event => {
  if (dialog.open && event.key === 'Tab') {
    const focusable = [...dialog.querySelectorAll('button:not(:disabled),input:not(:disabled),[tabindex="0"]')];
    const first = focusable[0];
    const last = focusable.at(-1);
    if ((event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    }
  }
  const tab = event.target.closest('[data-category]');
  if (tab && ['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
    event.preventDefault();
    const keys = Object.keys(categories);
    const current = keys.indexOf(state.category);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? keys.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + keys.length) % keys.length;
    select(`[data-category="${keys[next]}"]`).click();
  }
  if (event.key === 'Escape' && !dialog.open && state.mode !== 'client') setMode('client');
});
select('[data-page="companion"]').closest('header').querySelector('.brand').addEventListener('click',event => { event.preventDefault(); state.page = 'companion'; updateView(); });
select('.composer').addEventListener('submit',event => event.preventDefault());
document.addEventListener('change',event => {
  if (event.target.matches('[data-background]')) { state.transparent = event.target.checked; updateView(); }
});
document.addEventListener('visibilitychange',() => room?.setVisible(state.page === 'companion' && !document.hidden));
window.addEventListener('pagehide',() => room?.setVisible(false));
window.addEventListener('pageshow',updateView);
renderThemes();
applyTheme();
renderModules();
if (state.mode !== 'client') state.page = 'companion';
updateView();
try {
  select('#companion').hidden = false;
  room = await mountRoom(select('#room'),{variant:'a',transparent:state.mode === 'pet' && state.transparent});
  updateView();
  document.body.dataset.ready = 'true';
} catch (error) { document.body.dataset.error = error.message; }
window.aPlusPreview = { faceBounds:() => room?.getFaceBounds(), snapshot:() => ({...state,modules:[...state.modules]}) };
