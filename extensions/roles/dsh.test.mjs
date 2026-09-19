import {test} from 'node:test';
import assert from 'node:assert/strict';
import {apply,latestUser,acceptedUsers} from './dsh.mjs';
import {realpathSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

test('only direct user originals drive retrieval',()=>{
  const original={id:'u',source:{kind:'user'},content:[{type:'text',text:' raw\n```code``` '}]};
  assert.equal(latestUser([{type:'agent/inbox/spliced',data:{inserted:[original]}}]),' raw\n```code``` ');
  assert.equal(latestUser([{type:'user/message',surfaceOp:'append',data:{...original,source:{kind:'plugin'}}}]),null);
  assert.equal(latestUser([{type:'user/message',surfaceOp:'replace',data:original}]),null);
});
test('disabled performs no I/O or registrations',async()=>{
  await apply(new Proxy({},{get(){throw Error('unexpected access');}}),{enabled:false});
  await assert.rejects(apply({},{enabled:'true'}),/explicit enabled/);
});
test('writes accept only native admitted RPC user messages',()=>{
  const m={id:'id',source:{kind:'user',rpcId:'rpc'},content:[{type:'text',text:'记住：原文'}]};
  assert.deepEqual(acceptedUsers([m,{...m,source:{kind:'plugin',rpcId:'rpc'}},{...m,source:{kind:'model'}},{...m,source:{kind:'user'}},{...m,id:undefined}]),[{id:'id',text:'记住：原文'}]);
});
test('native rejection and unbound workspace never start role workers',async()=>{
  const root=realpathSync(fileURLToPath(new URL('../..',import.meta.url)));
  const handlers=new Map();
  const ctx={on(name,fn){handlers.set(name,fn);},effect(){}};
  await apply(ctx,{enabled:true,projects:{[root]:root+'/pyproject.toml'},python:'MUST_NOT_RUN',core:'MUST_NOT_RUN',runtimeEntry:root+'/runtime/dsh/node_modules/@deepseek-ai/dsh/package.json'});
  const rejected={kind:'reject'};
  assert.equal(await handlers.get('agent/pre-step')({agent:{},turn:1},async()=>rejected),rejected);
  const downstream={kind:'enter',messages:[]};
  assert.equal(await handlers.get('agent/pre-step')({agent:{session:{header:{cwd:root+'/docs'}}},turn:1},async()=>downstream),downstream);
});
