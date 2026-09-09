import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';
import { webcrypto } from 'node:crypto';

const source = readFileSync(new URL('../src/sumika_core/integrations/account_portals.py', import.meta.url), 'utf8');
const expression = source.match(/MOARK_RECEIPTS_EXPRESSION = r"""([\s\S]*?)"""/)[1];
const profile = 'https://moark.com/api/base/synthetic-account/profile';
const receipt = { id:'receipt-1', trace_id:'trace-1', resource_info:{ident:'package-1'}, request:{model:'fixture-model',messages:'private-body'},
  code:200, status:1, charge_source:0, free:false, price:0.0009136 };

async function observe(options = {}) {
  const calls = [];
  const stages = [];
  const controller = new AbortController();
  const context = {
    location:{origin:'https://moark.com',pathname:'/serverless-api',...options.location},
    performance:{getEntriesByType:() => (options.resources ?? [profile]).map(name => ({name}))},
    crypto:options.cancelDuringHash ? {subtle:{digest:async (...args) => { const value = await webcrypto.subtle.digest(...args); controller.abort(); return value; }}} : webcrypto,
    TextEncoder, URL, AbortSignal: options.fastTimeout ? {any:AbortSignal.any.bind(AbortSignal),timeout:() => AbortSignal.timeout(20)} : AbortSignal,
    control:{signal:controller.signal,onStage:stage => stages.push(stage)},
    fetch:async (endpoint, parameters) => {
      calls.push({endpoint,parameters});
      if (options.hang) return new Promise((resolve,reject) => parameters.signal.addEventListener('abort', () => reject(Error('private-abort-message')), {once:true}));
      if (options.fetchError) throw Error('private-network-message');
      const body = options.body ?? JSON.stringify({total:1,items:[receipt]});
      return {ok:!options.httpStatus,status:options.httpStatus ?? 200,text:async () => body};
    },
  };
  if (options.cancelBeforeStart) controller.abort();
  if (options.legacyParser) context.JSON = {parse:(text, reviver) => JSON.parse(text, (key,value) => reviver(key,value)),stringify:JSON.stringify};
  const script = expression.trim().replace(/\}\)\(\)$/, '})(control)');
  const result = JSON.parse(await runInNewContext(script, context, {timeout:1000}));
  return {result,calls,stages};
}

test('fixed receipt projection keeps exact decimals and exports hashes but no bodies or identity', async () => {
  const body = JSON.stringify({total:1,items:[receipt]}).replace('0.0009136','0.0009136000000000001');
  const {result,calls} = await observe({body});
  assert.equal(result.state,'verified');
  assert.equal(result.receipts[0].amount,'0.0009136000000000001');
  assert.match(result.receipts[0].evidence_id,/^[a-f0-9]{64}$/);
  assert.equal(calls.length,1);
  assert.equal(calls[0].endpoint,'/api/base/synthetic-account/inference-logs?page=1&size=100');
  assert.equal(calls[0].parameters.method,'GET');
  assert.equal(calls[0].parameters.credentials,'include');
  assert.equal(calls[0].parameters.redirect,'error');
  for (const forbidden of ['private-body','synthetic-account','trace-1','package-1','receipt-1']) {
    assert.equal(JSON.stringify(result).includes(forbidden),false);
  }
});

test('missing resource evidence is not classified as logged out and performs no request', async () => {
  const {result,calls} = await observe({resources:[]});
  assert.deepEqual(result,{state:'needs-review',reason:'profile-resource-unavailable'});
  assert.equal(calls.length,0);
});

test('ambiguous accounts fail closed while duplicates and unrelated resources cannot select another account', async () => {
  const ambiguous = await observe({resources:[profile,'https://moark.com/api/base/other-account/profile']});
  assert.equal(ambiguous.result.reason,'ambiguous-account-profile');
  assert.equal(ambiguous.calls.length,0);
  const valid = await observe({resources:['not a url',profile,profile,'https://other.invalid/api/base/not-mine/profile']});
  assert.equal(valid.result.state,'verified');
  assert.equal(valid.calls.length,1);
});

test('unsupported lossless JSON parsing fails before requesting billing logs', async () => {
  const {result,calls} = await observe({legacyParser:true});
  assert.equal(result.reason,'lossless-json-parser-unavailable');
  assert.equal(calls.length,0);
});

test('official errors keep only fixed status codes, never response or thrown text', async () => {
  for (const [httpStatus,reason] of [[401,'official-log-auth-rejected'],[403,'official-log-forbidden'],[429,'official-log-rate-limited'],[500,'official-log-read-failed']]) {
    const {result} = await observe({httpStatus,body:'private-response-body'});
    assert.deepEqual(result,{state:'needs-review',reason});
  }
  assert.deepEqual((await observe({fetchError:true})).result,{state:'needs-review',reason:'official-log-read-failed'});
});

test('malformed and changing schema preserve diagnostic stage without partial evidence', async () => {
  for (const [body,reason] of [['{','invalid-log-json'],['null','invalid-log-schema'],['{}','invalid-log-schema'],
    [JSON.stringify({total:2,items:[receipt]}),'log-pagination-changed-or-unbounded'],
    [JSON.stringify({total:1,items:[null]}),'invalid-log-schema'],
    [JSON.stringify({total:1,items:[{...receipt,price:'secret'}]}),'invalid-log-amount-or-model'],
    [JSON.stringify({total:1,items:[{...receipt,trace_id:''}]}),'invalid-receipt-identity']]) {
    const {result} = await observe({body});
    assert.deepEqual(result,{state:'needs-review',reason});
    assert.equal('receipts' in result,false);
  }
});

test('wrong origin or page does not fetch and cannot expose unrelated content', async () => {
  for (const location of [{origin:'https://other.invalid'},{pathname:'/settings'}]) {
    const {result,calls} = await observe({location});
    assert.deepEqual(result,{state:'needs-review',reason:'wrong-page'});
    assert.equal(calls.length,0);
  }
});

test('cancelled readers make no new request or export partial receipts', async () => {
  const before = await observe({cancelBeforeStart:true});
  assert.equal(before.result.reason,'receipt-read-cancelled');
  assert.equal(before.calls.length,0);
  const during = await observe({cancelDuringHash:true});
  assert.equal(during.result.reason,'receipt-read-cancelled');
  assert.equal(during.calls.length,1);
  assert.equal('receipts' in during.result,false);
  assert.deepEqual(during.stages,['fetch','body','parse','hash']);
});

test('stalled HTTP requests are aborted and classified without retries', async () => {
  const keepAlive = setTimeout(() => {}, 1000);
  try {
    const {result,calls,stages} = await observe({hang:true,fastTimeout:true});
    assert.equal(result.reason,'official-log-read-timeout');
    assert.equal(calls.length,1);
    assert.deepEqual(stages,['fetch']);
  } finally { clearTimeout(keepAlive); }
});
