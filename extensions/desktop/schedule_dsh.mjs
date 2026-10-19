// Thin native human-command adapter. DSH owns rules, timers and deliveries.
import {createHash} from 'node:crypto';
import {mkdir,open,readFile,rename,unlink} from 'node:fs/promises';
import {join} from 'node:path';

const canonical=value=>value && typeof value==='object' ? Array.isArray(value)?value.map(canonical):Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])):value;
const digest=value=>createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex');
export function validateRequest(value,agent,registry){
  if(!value || typeof value!=='object' || Array.isArray(value) ||
     Object.keys(value).some(k=>!['request_id','workspace_id','confirmed','schedule'].includes(k)) ||
     value.confirmed!==true || typeof value.request_id!=='string' ||
     !/^[a-zA-Z0-9-]{16,100}$/.test(value.request_id))throw Error('Explicit confirmed request identity required');
  const header=agent?.session?.header;
  if(!header?.id || header.agentPreset!=='standard' || (header.delegationDepth??0)!==0 ||
     registry.archivedSessionIds.includes(header.id))throw Error('An active main work session is required');
  const workspace=registry.list().find(w=>w.id===value.workspace_id && w.sessionIds.includes(header.id));
  if(!workspace)throw Error('Target session does not belong to selected native workspace');
  const s=value.schedule;
  if(!s || typeof s!=='object' || Array.isArray(s) || Object.keys(s).some(k=>!['title','prompt','at','daily','weekly'].includes(k)) ||
     typeof s.title!=='string' || !s.title.trim() || s.title.length>120 ||
     typeof s.prompt!=='string' || !s.prompt.trim() || s.prompt.length>20000 ||
     ['at','daily','weekly'].filter(k=>Object.hasOwn(s,k)).length!==1)throw Error('Valid once/daily/weekly task required');
  if(Object.hasOwn(s,'at')){
    if(typeof s.at!=='string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(s.at) ||
       !Number.isFinite(Date.parse(s.at)) || new Date(s.at).toISOString()!==s.at)throw Error('Canonical UTC timestamp required');
  }else{
    const rule=s.daily??s.weekly,weekly=Object.hasOwn(s,'weekly');
    if(!rule || typeof rule!=='object' || Array.isArray(rule) || Object.keys(rule).some(k=>!['time','time_zone',...(weekly?['weekdays']:[])].includes(k)) ||
       !/^(?:[01]\d|2[0-3]):[0-5]\d:00$/.test(rule.time))throw Error('Invalid local calendar rule');
    if(typeof rule.time_zone!=='string' || !(rule.time_zone==='UTC'||/^[A-Za-z][\w+.-]*(?:\/[\w+.-]+)+$/.test(rule.time_zone)))throw Error('Explicit IANA timezone required');
    new Intl.DateTimeFormat('en',{timeZone:rule.time_zone});
    if(weekly && (!Array.isArray(rule.weekdays)||rule.weekdays.length!==1||!Number.isInteger(rule.weekdays[0])||rule.weekdays[0]<1||rule.weekdays[0]>7))throw Error('One ISO weekday required');
  }
  return {sessionId:header.id,workspaceId:workspace.id,schedule:s};
}

export function createHandler(ctx,directory){
  // Native create is durable but has no caller idempotency key. Fence before
  // dispatch; interrupted pending records stay UNKNOWN even after restart.
  return async invocation=>{
    let value;
    try{value=JSON.parse(invocation.rawInput);}catch{return {kind:'error',text:'Invalid schedule request JSON'};}
    let target;
    try{target=validateRequest(value,invocation.agent,ctx.workspaceRegistry);}
    catch(error){return {kind:'error',text:error.message};}
    const fingerprint=digest(target),key=digest(value.request_id);
    await mkdir(directory,{recursive:true});
    const path=join(directory,key+'.json');
    let handle;
    try{handle=await open(path,'wx');}
    catch(error){
      if(error.code!=='EEXIST')throw error;
      let prior;
      try{prior=JSON.parse(await readFile(path,'utf8'));}catch{return {kind:'success',text:JSON.stringify({state:'unknown',retry:false,request_id:value.request_id})};}
      if(prior.fingerprint!==fingerprint)return {kind:'error',text:'Request identity conflicts with previous task'};
      return {kind:'success',text:JSON.stringify(prior.result||{state:'unknown',retry:false,request_id:value.request_id})};
    }
    if(target.schedule.at && Date.parse(target.schedule.at)<=Date.now()){
      await handle.close();await unlink(path);
      return {kind:'error',text:'One-shot execution must be in the future'};
    }
    try{await handle.writeFile(JSON.stringify({fingerprint,state:'pending'}));await handle.sync();}
    finally{await handle.close();}
    let result;
    try{
      invocation.signal?.throwIfAborted();
      // Recheck membership after IO, immediately before native admission.
      validateRequest(value,invocation.agent,ctx.workspaceRegistry);
      const record=await ctx.schedule.create(target.sessionId,target.schedule,invocation.signal);
      result={state:'created',request_id:value.request_id,session_id:target.sessionId,record,retry:false};
    }catch(error){
      // A rejection can follow an in-flight durable write: never assume absent.
      result={state:'unknown',request_id:value.request_id,retry:false,
        message:'Creation not confirmed. Inspect native automation tasks; do not automatically create again.'};
    }
    const temp=path+'.tmp';
    try{
      const file=await open(temp,'wx');
      try{await file.writeFile(JSON.stringify({fingerprint,result}));await file.sync();}finally{await file.close();}
      await rename(temp,path);
    }finally{await unlink(temp).catch(error=>{if(error.code!=='ENOENT')throw error;});}
    return {kind:'success',text:JSON.stringify(result)};
  };
}

export function applySchedule(ctx,config){
  if(!config?.scheduleRequests)return;
  ctx.effect(()=>ctx.commands.register({name:'sumika-schedule-create',recordInput:false,
    description:'Create an explicitly confirmed Sumika task in native scheduling; no model call.',
    handler:createHandler(ctx,config.scheduleRequests)}));
}
