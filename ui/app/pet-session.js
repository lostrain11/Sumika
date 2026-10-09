import {bridgeFetch} from './bridge-client.js';
import {hydrateIconsAsync} from './icons.js';

export function mountPetSession(host) {
  const section=document.createElement('section');section.dataset.petSession='';
  const state=document.createElement('p');state.setAttribute('role','status');state.className='sumika-form-note';
  const commands=document.createElement('div');commands.className='companion-commands';
  let busy=false, known=false, available=false, alive=false;
  function button(icon,label,action) {
    const element=document.createElement('button');element.type='button';element.className='mini-btn';
    element.title=label;element.setAttribute('aria-label',label);
    const symbol=document.createElement('i');symbol.dataset.icon=icon;symbol.dataset.iconSize='16';element.append(symbol);
    element.addEventListener('click',()=>run(action));commands.append(element);return element;
  }
  const start=button('lucide:play','启动桌宠','start');
  const stop=button('lucide:square','关闭桌宠','stop');
  const refresh=button('act-refresh','刷新桌宠状态','status');
  function controls() {
    start.disabled=busy || !known || !available || alive;
    stop.disabled=busy || (known && !alive);
    refresh.disabled=busy;
  }
  async function run(action) {
    if(busy || !section.isConnected) return;
    busy=true;controls();
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000);
    try {
      const response=await bridgeFetch('/api/companion/pet', {method:'POST',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({action}),signal:controller.signal});
      const value=await response.json();
      if(!response.ok) throw Error(value.error || `HTTP ${response.status}`);
      known=true;available=value.available===true;alive=value.alive===true;
      state.textContent=alive?'桌宠正在运行':available?'桌宠已关闭':'桌宠宿主不可用';
    } catch(error) {
      known=false;state.textContent=`桌宠状态未确认：${error.message}`;
    } finally {clearTimeout(timer);busy=false;controls();}
  }
  section.append(state,commands);host.append(section);hydrateIconsAsync(section);controls();run('status');
  return section;
}
