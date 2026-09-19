import test from 'node:test';
import assert from 'node:assert/strict';
import {apply} from './model.mjs';

test('role route does not inherit work selection or suppress rejection',async()=>{
  let hook;apply({on:(name,fn)=>{assert.equal(name,'agent/request');hook=fn;}},{enabled:true,provider:'role-provider',model:'role-model'});
  const work={provider:'work',model:'work',reasoningEffort:'high'};
  assert.deepEqual(await hook({},async()=>work),{provider:'role-provider',model:'role-model'});
  assert.deepEqual(work,{provider:'work',model:'work',reasoningEffort:'high'});
  await assert.rejects(hook({},async()=>{throw Error('rejected');}),/rejected/);
});
test('disabled preset stops model requests',async()=>{
  let hook;apply({on:(_,fn)=>{hook=fn;}},{enabled:false,provider:'p',model:'m'});
  await assert.rejects(hook({},async()=>({provider:'work',model:'work'})),/disabled/);
});
