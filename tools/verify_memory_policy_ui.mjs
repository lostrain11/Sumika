// Existing memory switches and room composer against real isolated Bridge/SQLite
// and a synthetic loopback Ollama model. Role discovery is the only API fixture.
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output=resolve(process.argv[2]||'.sumika-next/acceptance-20261017-final/memory-policy-ui');
await mkdir(output,{recursive:true});
const data=await mkdtemp(join(output,'isolated-'));
const candidate=resolve(process.env.SUMIKA_TEST_CANDIDATE||'.');
const bridge=spawn(process.env.SUMIKA_TEST_PYTHON||'python',['-u','-X','utf8','-B','-c',String.raw`
import sys, json, threading, os, re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import sqlite3
from pathlib import Path
from extensions.models.usage import UsageStore
from extensions.models.settings import example, save
from extensions.roles.roles import import_card
from ui.server import serve
data=Path(sys.argv[1])
card=data/'card.json'
card.write_text(json.dumps({'spec':'chara_card_v2','data':{'name':'Fixture','description':'Synthetic test'}}),encoding='utf8')
role=import_card(card,data/'roles','fixture')
calls=[]
class Model(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        body=json.dumps(calls,ensure_ascii=False).encode('utf8')
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
    def do_POST(self):
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        calls.append(request)
        system=request['messages'][0]['content']
        message=request['messages'][-1]['content']
        found=re.search(r'\[sumika-memory-[a-f0-9]+\]',system)
        text='这是本机合成回复。'
        if found:
            text+=found.group()+json.dumps({'memories':[{'text':message,'quote':message,'kind':'preference','confidence':0.99}],'intent':{'kind':'chat','confidence':'high','evidence':''}},ensure_ascii=False)
        body=json.dumps({'message':{'role':'assistant','content':text},'done':True,'done_reason':'stop','prompt_eval_count':10,'eval_count':10},ensure_ascii=False).encode('utf8')
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
model=ThreadingHTTPServer(('127.0.0.1',0),Model)
threading.Thread(target=model.serve_forever,daemon=True).start()
os.environ['SUMIKA_POLICY_FIXTURE_KEY']='synthetic-loopback-only'
settings=example(role,data/'memory.sqlite3')
settings.update(enabled=True,provider='ollama',endpoint='http://127.0.0.1:'+str(model.server_port))
settings['memory'].update(enabled=True,auto_extract=True,model_proposals=True)
save(settings,data/'settings.json')
server=serve(data/'settings.json',port=0,workbench_root=data,capability_database=data/'capabilities.sqlite3')
server.sumika_bridge._role_paths=lambda:{'fixture':str(role)}
server.sumika_bridge._role_kinds=lambda:{'fixture':'user'}
manager=server.sumika_bridge.management
state=manager.memory('fixture')
state=manager.memory('fixture','remember',{'expected_revision':state['revision'],'text':'likes tea','request_id':'fixture-fact'})
threading.Thread(target=server.serve_forever,daemon=True).start()
print(json.dumps({'port':server.server_port,'model_port':model.server_port}),flush=True)
try: sys.stdin.read()
finally: server.shutdown(); server.server_close(); model.shutdown(); model.server_close()
`,data],{cwd:candidate,stdio:['pipe','pipe','pipe']});
let diagnostics='';bridge.stderr.on('data',chunk=>diagnostics+=chunk);
const report={passed:false,checks:[],pageErrors:[],synthetic_model:true,external_model_calls:0,candidate};
let browser;
try{
 const lines=createInterface({input:bridge.stdout});
 const [line]=await Promise.race([once(lines,'line'),once(bridge,'exit').then(([code])=>{throw Error('Bridge exited '+code+': '+diagnostics);}),new Promise((_,reject)=>{
  const timer=setTimeout(()=>reject(Error('Bridge timeout: '+diagnostics.slice(-1500))),20000);timer.unref();
 })]);
 const ready=JSON.parse(line),base='http://127.0.0.1:'+ready.port;
 const {chromium}=loadPlaywright();browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 page.on('pageerror',e=>report.pageErrors.push(e.message));
 // Discover only this isolated imported fixture role, never the personal store.
 await page.route('**/api/roles',r=>r.fulfill({json:{active:{id:'fixture'},roles:[{id:'fixture',name:'Fixture',complete:true}]}}));
 const read=async()=>await(await page.request.get(base+'/api/manage/roles/fixture/memory')).json();
 const calls=async()=>await(await fetch('http://127.0.0.1:'+ready.model_port+'/calls')).json();
 async function configure(enabled,extract=true,proposals=true){
  await page.goto(base+'/');
  await page.locator('#gnav button[data-go="shelf"]').click();
  await page.getByRole('button',{name:'管理模块',exact:true}).waitFor();
  await page.locator('.cap-card[data-capability-id="memory"]').click();
  const panel=page.locator('[data-extra-action][data-capability-id="memory"]');
  await panel.getByRole('checkbox',{name:'使用长期记忆',exact:true}).setChecked(enabled);
  await panel.getByRole('checkbox',{name:'自动提取记忆',exact:true}).setChecked(extract);
  await panel.getByRole('checkbox',{name:'模型记忆提议（需确认）',exact:true}).setChecked(proposals);
  const response=page.waitForResponse(r=>r.url().endsWith('/api/manage/settings')&&r.request().method()==='POST');
  await panel.getByRole('button',{name:'保存配置',exact:true}).click();
  assert.equal((await response).status(),200);
  const persisted=(await(await page.request.get(base+'/api/manage/settings')).json()).data.memory;
  assert.equal(persisted.enabled,enabled);assert.equal(persisted.auto_extract,extract);assert.equal(persisted.model_proposals,proposals);
 }
 async function chat(message,session){
  await page.locator('#gnav button[data-go="room"]').click();
  await page.locator('[data-room-input]').fill(message);
  const pending=page.waitForResponse(r=>r.url().endsWith('/api/role/chat')&&r.request().method()==='POST');
  await page.locator('#sendBtn').click();
  const response=await pending;
  assert.equal(response.status(),200,await response.text());
  return await response.json();
 }
 const initial=await read();
 assert.equal(initial.memories.length,1);
 await configure(false);
 let result=await chat('我喜欢关闭测试茶','off');
 assert.equal(result.memory_proposals,0);assert.deepEqual(result.auto_extracted,[]);
 let state=await read();assert.equal(state.memories.length,1);assert.equal(state.proposals.length,0);
 let sent=(await calls()).at(-1).messages[0].content;
 assert.ok(!sent.includes('likes tea'));assert.ok(!sent.includes('[sumika-memory-'));
 report.checks.push('ui_disabled_stops_retrieval_rule_writes_and_model_proposals_preserves_data');
 await configure(true,false,false);
 result=await chat('likes tea','on-read');
 sent=(await calls()).at(-1).messages[0].content;
 assert.ok(sent.includes('likes tea'));assert.ok(!sent.includes('[sumika-memory-'));
 assert.deepEqual(result.auto_extracted,[]);assert.equal(result.memory_proposals,0);
 report.checks.push('ui_reenabled_retrieves_existing_fact_without_implicitly_enabling_extraction');
 await configure(true,true,false);
 result=await chat('我喜欢规则测试咖啡','rule');
 assert.equal(result.auto_extracted.length,1);assert.equal(result.memory_proposals,0);
 state=await read();assert.ok(state.memories.some(m=>m.text.includes('规则测试咖啡')));
 report.checks.push('ui_rule_extraction_persists_explicit_self_statement');
 await configure(true,false,true);
 result=await chat('我喜欢提议测试乌龙茶','proposal');
 assert.deepEqual(result.auto_extracted,[]);assert.equal(result.memory_proposals,1);
 state=await read();assert.equal(state.proposals.length,1);
 assert.ok(!state.memories.some(m=>m.text.includes('提议测试乌龙茶')));
 assert.ok(!result.text.includes('[sumika-memory-'));
 report.checks.push('ui_model_proposal_is_pending_not_confirmed_fact_and_envelope_hidden');
 await configure(false,false,true);
 await chat('我喜欢再次关闭测试红茶','off-again');
 state=await read();assert.equal(state.proposals.length,1);assert.equal(state.memories.length,2);
 report.checks.push('disable_after_enabled_chat_invalidates_cached_chat_settings');
 await page.screenshot({path:join(output,'memory-policy.png')});
 assert.deepEqual(report.pageErrors,[]);
 report.loopback_model_calls=(await calls()).length;assert.equal(report.loopback_model_calls,5);
 report.passed=true;
}catch(error){report.error=String(error.stack||error);report.diagnostics=diagnostics;process.exitCode=1;}
finally{
 await browser?.close();bridge.stdin.end();
 if(bridge.exitCode===null)await Promise.race([once(bridge,'exit'),new Promise(resolve=>{
  const timer=setTimeout(()=>{bridge.kill();resolve();},10000);timer.unref();
 })]);
 await writeFile(join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}
