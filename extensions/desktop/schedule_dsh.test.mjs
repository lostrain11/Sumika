import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,readdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {createHandler} from './schedule_dsh.mjs';

test('native admission fences duplicate, concurrent, conflicting and uncertain creation',async()=>{
  const dir=await mkdtemp(join(tmpdir(),'sumika-schedule-'));
  try{
    let calls=0;
    const ctx={workspaceRegistry:{archivedSessionIds:[],list:()=>[{id:'w',sessionIds:['s']}]},schedule:{create:async()=>{calls++;return {id:'native'};}}};
    const value={request_id:'request-1234567890',workspace_id:'w',confirmed:true,schedule:{title:'Task',prompt:'Synthetic',daily:{time:'09:00:00',time_zone:'Asia/Shanghai'}}};
    const invoke=(v=value)=>({rawInput:JSON.stringify(v),agent:{session:{header:{id:'s',agentPreset:'standard',delegationDepth:0}}},signal:new AbortController().signal});
    const run=createHandler(ctx,dir);
    const outcomes=await Promise.all([run(invoke()),run(invoke())]);
    assert.equal(calls,1);assert.ok(outcomes.some(x=>JSON.parse(x.text).state==='created'));
    assert.equal(JSON.parse((await createHandler(ctx,dir)(invoke())).text).record.id,'native');
    assert.equal(calls,1);
    assert.equal((await run(invoke({...value,schedule:{...value.schedule,prompt:'different'}}))).kind,'error');
    assert.equal((await run(invoke({...value,workspace_id:'forged'}))).kind,'error');
    for(const header of [{id:'s',agentPreset:'role'},{id:'s',agentPreset:'standard',delegationDepth:1}]){
      const invocation=invoke();invocation.agent.session.header=header;
      assert.equal((await run(invocation)).kind,'error');
    }
    ctx.workspaceRegistry.archivedSessionIds=['s'];
    assert.equal((await run(invoke())).kind,'error');ctx.workspaceRegistry.archivedSessionIds=[];
    const invalid={...value,request_id:'invalid-1234567890',schedule:{...value.schedule,daily:{time:'25:00:00',time_zone:'UTC'}}};
    assert.equal((await run(invoke(invalid))).kind,'error');assert.equal((await readdir(dir)).length,1);
    ctx.schedule.create=async()=>{calls++;throw Error('after durable write');};
    const uncertain={...value,request_id:'uncertain-1234567890'};
    assert.equal(JSON.parse((await run(invoke(uncertain))).text).state,'unknown');
    await createHandler(ctx,dir)(invoke(uncertain));assert.equal(calls,2);
    const pending=createHash('sha256').update(JSON.stringify(value.request_id)).digest('hex')+'.json';
    await writeFile(join(dir,pending),'');
    // A torn fence is never permission to dispatch again.
    const before=calls;await run(invoke());assert.equal(calls,before);
  }finally{await rm(dir,{recursive:true,force:true});}
});

test('cancelled requests never reach native scheduler',async()=>{
  const dir=await mkdtemp(join(tmpdir(),'sumika-cancel-'));
  try{
    let calls=0;
    const ctx={workspaceRegistry:{archivedSessionIds:[],list:()=>[{id:'w',sessionIds:['s']}]},schedule:{create:async()=>{calls++;}}};
    const signal=AbortSignal.abort();
    const result=await createHandler(ctx,dir)({rawInput:JSON.stringify({request_id:'cancelled-1234567890',workspace_id:'w',confirmed:true,schedule:{title:'a',prompt:'b',weekly:{time:'09:00:00',time_zone:'UTC',weekdays:[7]}}}),agent:{session:{header:{id:'s',agentPreset:'standard'}}},signal});
    assert.equal(JSON.parse(result.text).state,'unknown');assert.equal(calls,0);
  }finally{await rm(dir,{recursive:true,force:true});}
});
