// Execute the delivered slot component with the public DSH selector contract.
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=await readFile(new URL('../extensions/ui/sumika-workbench/lib/client.js',import.meta.url),'utf8');
let status;
const jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
vm.runInNewContext(source,{window:{__ModuleLoader__:{load({factory}){
 const module=factory(name=>name==='react/jsx-runtime'?jsx:{});
 module.apply({slots:{inject(name,callback){
  for(const _ of callback()){}
 },register(options,component){if(options.id==='sumika-session-status')status=component;return null;}}});
}}},document:{documentElement:{dataset:{}}},URL});
assert.equal(typeof status,'function');
function render(kind,running=false,legacy=false){
 const props={sessionId:'one',useSessions:select=>select({byId:{one:{running}}})};
 if(legacy)props.useSessionPendingInteraction=select=>select(new Map([['one',{kind}]]));
 else props.useSessionStatus=select=>select(new Map([['other',{pendingInteraction:{kind:'approval'}}],['one',{pendingInteraction:kind?{kind}:undefined}]]));
 return status(props).props;
}
assert.equal(render(undefined)['data-sumika-session-status'],'idle');
for(const [kind,label] of [['plan-review','计划审阅'],['approval','等待审批'],['question','等待回答']]){
 for(const legacy of [false,true]){
  const value=render(kind,true,legacy);
  assert.equal(value['data-sumika-session-status'],'pending,running');
  assert.deepEqual(Array.from(value.children,p=>p.props.children),[label,'执行中']);
 }
}
assert.equal(render('unrecognized')['data-sumika-session-status'],'idle');
assert.equal(render(undefined,true)['data-sumika-session-status'],'running');
console.log('Workbench status selector contract: passed (new/legacy hooks, scoped pending kinds, running and idle)');
