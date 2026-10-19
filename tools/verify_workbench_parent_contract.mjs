// Run the shipped client hooks with explicit parent identity and referrer.
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../extensions/ui/sumika-workbench/lib/client.js',import.meta.url),'utf8');
function mount(referrer,{standalone=false,ancestor}={}){
 const components=new Map(),listeners=new Set(),posts=[],drafts=[],panels=[];
 const parent={postMessage:(value,origin)=>posts.push({value,origin})};
 const window={parent,location:{ancestorOrigins:ancestor?[ancestor]:[]},addEventListener:(type,fn)=>listeners.add(fn),removeEventListener:(type,fn)=>listeners.delete(fn)};
 if(standalone)window.parent=window;
 const document={referrer,documentElement:{dataset:{}}};
 const react={useState:()=>[null,value=>drafts.push(value)],useEffect:fn=>fn()};
 window.__ModuleLoader__={load({factory}){factory(name=>name==='react'?react:{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})}).apply({slots:{
  inject(name,fn){for(const _ of fn()){}},register(options,component){components.set(options.id,component);return null;}
 },layout:{selectPanel:id=>panels.push(id)}});}};
 vm.runInNewContext(source,{window,document,URL});
 const overlay=components.get('sumika-native-layout-bridge')();
 overlay.type(overlay.props);
 components.get('sumika-role-task-draft')({});
 return {posts,drafts,panels,document,parent,send(event){for(const listener of listeners)listener(event);}};
}
for(const port of [8765,8766,51789]){
 const origin=`http://127.0.0.1:${port}`,host=mount(origin+'/#board');
 assert.ok(host.posts.some(p=>p.value.type==='sumika:task-ready'));
 assert.ok(host.posts.every(p=>p.origin===origin));
 const draft={id:'draft',source_message_id:'message',original_user_text:'核对测试项目'};
 host.send({source:{},origin,data:{type:'sumika:task-draft',draft}});
 host.send({source:host.parent,origin:'http://127.0.0.1:1111',data:{type:'sumika:task-draft',draft}});
 assert.equal(host.drafts.length,0);
 host.send({source:host.parent,origin,data:{type:'sumika:task-draft',draft}});
 assert.equal(host.drafts.length,1);
 host.send({source:host.parent,origin,data:{type:'sumika:host-route',route:'settings'}});
 assert.equal(host.document.documentElement.dataset.sumikaHostRoute,'settings');
 host.send({source:{},origin,data:{type:'sumika:native-schedule-open',id:'forged'}});
 host.send({source:host.parent,origin:'https://evil.example',data:{type:'sumika:native-schedule-open',id:'forged'}});
 assert.equal(host.panels.length,0);
 host.send({source:host.parent,origin,data:{type:'sumika:native-schedule-open',id:'confirmed'}});
 assert.deepEqual(host.panels,['schedules']);
 assert.ok(host.posts.some(p=>p.value.type==='sumika:native-schedule-opened'&&p.value.id==='confirmed'));
}
for(const referrer of ['', 'https://example.com/', 'http://localhost:8765/', 'http://127.0.0.1.attacker.test/', 'http://user:secret@127.0.0.1:8765/']){
 assert.equal(mount(referrer).posts.length,0);
}
assert.equal(mount('http://127.0.0.1:8765/',{standalone:true}).posts.length,0);
assert.ok(mount('',{ancestor:'http://127.0.0.1:8766'}).posts.length>0);
assert.equal(mount('http://127.0.0.1:8765/',{ancestor:'https://evil.example'}).posts.length,0);
console.log('Workbench parent contract passed: arbitrary loopback port, exact source/origin, invalid parent rejected');
