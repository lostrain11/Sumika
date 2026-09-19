import {createRequire} from 'node:module';
const {chromium}=createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/')('playwright');
const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});const p=await b.newPage();let rows=Array.from({length:8},(_,i)=>({id:'fixture'+i,who:i%2?'role':'me',text:'历史消息'+i,at:'2026-01-01T12:00:00Z'})),clears=0;
try{
await p.route('**/api/role/chat/history?*',r=>{const q=new URL(r.request().url()).searchParams;const end=q.has('before')?Number(q.get('before')):rows.length;const start=Math.max(0,end-3);return r.fulfill({json:{messages:rows.slice(start,end),before:start,has_more:start>0,supports_clear:true}});});
await p.route('**/api/role/chat/clear',r=>{clears++;rows=[];return r.fulfill({json:{cleared:true}});});
await p.goto('http://127.0.0.1:8765/#room');const msgs=p.locator('#screen-room .chat-msgs .cm');await p.waitForFunction(()=>document.querySelectorAll('#screen-room .chat-msgs .cm').length===3);
await p.locator('[data-room-older]').click();await p.waitForFunction(()=>document.querySelectorAll('#screen-room .chat-msgs .cm').length===6);
await p.locator('[data-room-older]').click();await p.waitForFunction(()=>document.querySelectorAll('#screen-room .chat-msgs .cm').length===8);
p.once('dialog',d=>d.dismiss());await p.locator('[data-room-clear]').click();if(clears)throw Error('cancel cleared chat');
p.once('dialog',d=>d.accept());await p.locator('[data-room-clear]').click();await p.locator('[data-room-empty]').waitFor();if(clears!==1)throw Error('duplicate clear');
console.log('passed: 3 recent, 3 older per click, all 8, cancel preserves, confirmed clear once; fixtures only');
}finally{await b.close();}
