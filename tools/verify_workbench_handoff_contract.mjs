// Execute the shipped dock with current WorkspaceView identities and host replies.
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../extensions/ui/sumika-workbench/lib/client.js',import.meta.url),'utf8');
const components=new Map(),listeners=new Set(),posts=[],composed=[];
const origin='http://127.0.0.1:8766';
const draft={id:'draft',source_message_id:'turn:user',original_user_text:'请检查项目'};
const parent={postMessage(value,target){posts.push({value,target});}};
const window={parent,location:{ancestorOrigins:[origin]},addEventListener:(type,fn)=>listeners.add(fn),removeEventListener:(type,fn)=>listeners.delete(fn)};
const react={useState:initial=>[initial===null?draft:initial,()=>{}],useEffect:()=>{}};
window.__ModuleLoader__={load({factory}){factory(name=>name==='react'?react:{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})}).apply({slots:{
 inject(name,fn){for(const _ of fn()){}},register(options,component){components.set(options.id,component);return null;}
}});}};
vm.runInNewContext(source,{window,document:{referrer:'',documentElement:{dataset:{}}},URL});
const render=(input,owner=true)=>components.get('sumika-role-task-draft')({
 input,inputActions:{setDraft:text=>composed.push(JSON.parse(text))},sessionId:'s',
 useWorkspaces:select=>select({items:owner?[{workspaceId:'native-w',title:'Browser title',sessionIds:['s']}]:[]})});
const button=view=>view.props.children.find(node=>node.type==='button');
for(const input of [{phase:'plain',draft:'keep'}, {phase:'plain',attachmentIds:['a']}, {phase:'busy'}])
 assert.equal(button(render(input)).props.disabled,true);
assert.equal(button(render({phase:'plain'},false)).props.disabled,true);
const action=button(render({phase:'plain'}));
assert.equal(action.props.disabled,false);
const pending=action.props.onClick();
assert.equal(posts[0].value.workspace_id,'native-w');
assert.equal(posts[0].value.session_id,'s');
assert.equal(posts[0].target,origin);
const reply={type:'sumika:task-received',id:'draft',handoff:{context:{source:'dsh-workspace-registry',project:{id:'native-w',name:'Host title'},session_id:'s'}}};
for(const fn of listeners)fn({source:{},origin,data:reply});
assert.equal(composed.length,0);
for(const fn of [...listeners])fn({source:parent,origin,data:reply});
await pending;
assert.equal(composed.length,1);
assert.equal(composed[0].original_user_text,draft.original_user_text);
assert.equal(composed[0].verified_project_context.workspace_title,'Host title');
assert.equal(composed[0].verified_project_context.workspace_id,'native-w');
assert.equal(posts.at(-1).value.type,'sumika:task-consumed');
console.log('Workbench handoff contract passed: current WorkspaceView ID, host-verified context, occupied composer guard, exact reply source, no send action');
