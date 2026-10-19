import {test} from 'node:test';
import assert from 'node:assert/strict';
import {realpathSync,mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {identity,submissionIdentity,approvalGate,apply,scopedProjects} from './review_dsh.mjs';

const root=realpathSync('.');
const projects=new Set([root]),presets=new Set(['work']);
const exec={name:'web_review_submit',callId:'one',agent:{session:{header:{id:'s',cwd:root,agentPreset:'work'}}}};
test('submission identity distinguishes native turns but preserves retry and historical ownership',()=>{
  const at=(turn,step)=>({...exec,agent:{session:{...exec.agent.session,
    snapshotEvents:()=>[{type:'step/start',data:{turn,step}}]}}});
  const first=submissionIdentity(at(1,1),projects,presets);
  assert.deepEqual(submissionIdentity(at(1,1),projects,presets),first);
  assert.notEqual(submissionIdentity(at(2,1),projects,presets).request_id,first.request_id);
  assert.notEqual(submissionIdentity(at(1,2),projects,presets).request_id,first.request_id);
  assert.equal(first.owner,identity(exec,projects,presets).owner);
  assert.throws(()=>submissionIdentity(exec,projects,presets),/live native/);
});
test('native approval cannot be promoted from denial',async()=>{
  const denial={kind:'deny',reason:'policy'};
  assert.equal(await approvalGate(exec,async()=>denial),denial);
  assert.equal((await approvalGate(exec,async()=>({kind:'allow'}))).kind,'ask');
  assert.equal((await approvalGate({...exec,name:'web_review_result'},async()=>({kind:'allow'}))).kind,'allow');
});
test('identity binds call/session/project and excludes roles or delegated agents',()=>{
  const first=identity(exec,projects,presets);
  assert.deepEqual(identity(exec,projects,presets),first);
  assert.notEqual(identity({...exec,callId:'two'},projects,presets).request_id,first.request_id);
  for(const patch of [{id:'other'},{agentPreset:'sumika-role'},{delegationDepth:1}]){
    const changed={...exec,agent:{session:{header:{...exec.agent.session.header,...patch}}}};
    if(patch.id)assert.notEqual(identity(changed,projects,presets).owner,first.owner);
    else assert.throws(()=>identity(changed,projects,presets));
  }
  assert.throws(()=>identity(exec,new Set(),presets));
});
test('disabled adapter registers nothing',async()=>{
  await apply(new Proxy({},{get(){throw Error('unexpected access')}}),{enabled:false});
  await assert.rejects(apply({},{enabled:'true'}),/explicit/);
});
test('native registry membership is rechecked and cannot admit unrelated sessions',()=>{
  let members=['s'];
  const registry={list:()=>[{path:root,sessionIds:members}]};
  assert.equal(identity(exec,scopedProjects(exec,new Set(),registry),presets).owner,identity(exec,projects,presets).owner);
  members=[];
  assert.throws(()=>identity(exec,scopedProjects(exec,new Set(),registry),presets));
  members=['other'];
  assert.throws(()=>identity(exec,scopedProjects(exec,new Set(),registry),presets));
});
test('user switch checked live before approvals; status and local cancellation remain available',async()=>{
  const temp=mkdtempSync(join(tmpdir(),'sumika-review-switch-'));
  try{
    const registry=join(temp,'authorizations.json');
    const tools=new Map(),hooks=new Map();
    const ctx={workspaceRegistry:{list:()=>[{path:root,sessionIds:['s']}]},
      tools:{register(tool){tools.set(tool.name,tool)},get(name){return tools.get(name)}},on(n,fn){hooks.set(n,fn)}};
    await apply(ctx,{enabled:true,projects:[],registeredWorkspaces:true,workPresets:['work'],root,python:'MUST_NOT_RUN',registry,
      runtimeEntry:realpathSync('runtime/dsh/node_modules/@deepseek-ai/dsh/package.json')});
    const gate=hooks.get('tools/pre-execute');
    assert.equal((await gate(exec,async()=>({kind:'allow'}))).kind,'deny');
    for(const action of ['status','cancel'])assert.equal((await gate({...exec,name:'web_review_result',arguments:{action}},async()=>({kind:'allow'}))).kind,'allow');
    assert.equal((await gate({...exec,name:'web_review_result',arguments:{action:'collect'}},async()=>({kind:'allow'}))).kind,'deny');
    writeFileSync(registry,JSON.stringify({schema_version:1,sites:{},enabled:true}));
    assert.equal((await gate(exec,async()=>({kind:'allow'}))).kind,'ask');
    writeFileSync(registry,JSON.stringify({schema_version:1,sites:{},enabled:false}));
    assert.equal((await gate(exec,async()=>({kind:'allow'}))).kind,'deny');
    writeFileSync(registry,'invalid');
    assert.equal((await gate(exec,async()=>({kind:'allow'}))).kind,'deny');
  }finally{rmSync(temp,{recursive:true,force:true});}
});
test('register with actual installed DSH schema; rejected scope never launches worker',async()=>{
  const tools=new Map(),hooks=new Map();
  const ctx={tools:{register(tool){tools.set(tool.name,tool)},get(name){return tools.get(name)}},on(name,fn){hooks.set(name,fn)}};
  await apply(ctx,{enabled:true,projects:[root],workPresets:['work'],root,python:'MUST_NOT_RUN',registry:'unused',
    runtimeEntry:realpathSync('runtime/dsh/node_modules/@deepseek-ai/dsh/package.json')});
  assert.equal(tools.size,2);assert.ok(hooks.has('tools/pre-execute'));
  const pending=tools.get('web_review_submit').presentCall({site:'chatgpt.com',prompt:'exact review'});
  assert.equal(pending.rawInput.prompt,'exact review');
  await assert.rejects(tools.get('web_review_result').execute({request_id:'other-session',action:'collect'},exec),/another session/);
});
