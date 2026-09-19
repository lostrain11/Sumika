const allowed=new Set(['light','dark','system']);
const media=matchMedia('(prefers-color-scheme: dark)');
let preference=localStorage.getItem('sumika-theme');
if(!allowed.has(preference))preference=null;
function render(){
  document.documentElement.dataset.theme=preference==='dark'||(preference==='system'&&media.matches)?'dark':'light';
  window.dispatchEvent(new CustomEvent('sumika:theme-rendered',{detail:preference||'light'}));
}
function send(){
  const frame=document.getElementById('sumika-workbench-frame');
  if(frame?.contentWindow && preference)frame.contentWindow.postMessage({type:'sumika:theme-set',preference},new URL(frame.src).origin);
}
export function setTheme(value){
  if(!allowed.has(value))return;
  localStorage.setItem('sumika-theme',value);preference=value;render();send();
}
export function getTheme(){return preference||'light';}
window.addEventListener('message',event=>{
  const frame=document.getElementById('sumika-workbench-frame');
  if(!frame || event.source!==frame.contentWindow || event.origin!==new URL(frame.src).origin)return;
  if(event.data?.type==='sumika:theme-ready'){
    if(preference)send();
    else if(allowed.has(event.data.preference)){preference=event.data.preference;render();}
  }
  if(event.data?.type==='sumika:theme-state' && allowed.has(event.data.preference)){
    preference=event.data.preference;localStorage.setItem('sumika-theme',preference);render();
  }
});
media.addEventListener('change',render);render();
