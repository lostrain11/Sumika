// Synthetic host reading event through the real runtime, Bridge/SQLite, room
// polling, explicit answer and model-reference pipeline. No device capture.
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output=resolve(process.argv[2]||'.sumika-next/acceptance-20261017-final/behavior-prompt-ui');
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
        if self.path=='/trigger':
            bridge._behavior_runtime.observe_event({'event_id':'host-reading-event','kind':'revisit','source':'reading-tracker'})
            value=bridge._behavior_library.export(scope=bridge._behavior_scope())
        elif self.path=='/snapshot':
            value=bridge._behavior_library.export(scope=bridge._behavior_scope())
        else:value=calls
        body=json.dumps(value,ensure_ascii=False).encode('utf8')
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
settings['memory'].update(enabled=False,auto_extract=False,model_proposals=False)
save(settings,data/'settings.json')
server=serve(data/'settings.json',port=0,workbench_root=data,capability_database=data/'capabilities.sqlite3')
server.sumika_bridge._role_paths=lambda:{'fixture':str(role)}
server.sumika_bridge._role_kinds=lambda:{'fixture':'user'}
bridge=server.sumika_bridge
permission=bridge._behavior_permissions
permission.save({'recording':True,'questions':True,'use_memory':True},revision=permission.load()['revision'])
profiles=bridge._profile_store.load()
bridge._profile_store.select('manual',profiles['profiles'][0]['id'],expected_revision=profiles['revision'])
bridge._behavior_runtime.sync_profile()
manager=bridge.management
state=manager.memory('fixture')
state=manager.memory('fixture','remember',{'expected_revision':state['revision'],'text':'likes tea','request_id':'fixture-fact'})
threading.Thread(target=server.serve_forever,daemon=True).start()
print(json.dumps({'port':server.server_port,'model_port':model.server_port}),flush=True)
try: sys.stdin.read()
finally: server.shutdown(); server.server_close(); model.shutdown(); model.server_close()
`,data],{cwd:candidate,stdio:['pipe','pipe','pipe']});
let diagnostics='';bridge.stderr.on('data',chunk=>diagnostics+=chunk);
const report={passed:false,checks:[],pageErrors:[],candidate,synthetic_host_event:true,real_device_capture:false,external_model_calls:0};
let browser;
try{
 const lines=createInterface({input:bridge.stdout});
 const [line]=await Promise.race([once(lines,'line'),once(bridge,'exit').then(([code])=>{throw Error('Bridge exited '+code+': '+diagnostics);}),new Promise((_,reject)=>{
  const timer=setTimeout(()=>reject(Error('Bridge timeout: '+diagnostics)),20000);timer.unref();
 })]);
 const ready=JSON.parse(line),base='http://127.0.0.1:'+ready.port,fixture='http://127.0.0.1:'+ready.model_port;
 const snapshot=async()=>await(await fetch(fixture+'/snapshot')).json();
 const {chromium}=loadPlaywright();browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 page.on('pageerror',e=>report.pageErrors.push(e.message));
 await page.route('**/api/roles',r=>r.fulfill({json:{active:{id:'fixture'},roles:[{id:'fixture',name:'Fixture',complete:true}]}}));
 await page.goto(base+'/#room');await page.locator('[data-room-input]').waitFor();
 const persisted=await(await fetch(fixture+'/trigger')).json();
 assert.equal(persisted.prompts.length,1);assert.equal(persisted.feedback.length,0);
 const prompt=page.locator('[data-behavior-prompt]');await prompt.waitFor();
 assert.equal(await prompt.getAttribute('data-behavior-prompt'),persisted.prompts[0].prompt_id);
 assert.ok((await prompt.innerText()).includes('来回查看'));
 report.checks.push('runtime_host_event_persists_prompt_before_real_room_poll_display');
 await prompt.getByRole('button',{name:'确认本次',exact:true}).click();
 await prompt.getByText(/请填写这次操作的真实含义/).waitFor();
 assert.equal((await snapshot()).feedback.length,0);
 report.checks.push('empty_confirmation_does_not_create_feedback');
 const meaning='PROMPT_MEANING_比较两个定义';
 await prompt.getByLabel('这次操作的真实含义',{exact:true}).fill(meaning);
 const saved=page.waitForResponse(r=>r.url().endsWith('/api/manage/behavior')&&r.request().postDataJSON()?.action==='prompt_feedback');
 await prompt.getByRole('button',{name:'纠正本次',exact:true}).click();assert.equal((await saved).status(),200);
 await prompt.getByText('已保存本次反馈',{exact:true}).waitFor();
 let state=await snapshot();assert.equal(state.feedback.length,1);
 assert.equal(state.feedback[0].prompt_id,persisted.prompts[0].prompt_id);
 assert.ok(JSON.stringify(state.feedback[0]).includes(meaning));
 report.checks.push('explicit_answer_binds_real_prompt_and_persists_feedback');
 await page.locator('[data-room-input]').fill('你对刚才的操作有什么建议');
 const answered=page.waitForResponse(r=>r.url().endsWith('/api/role/chat')&&r.request().method()==='POST');
 await page.locator('#sendBtn').click();assert.equal((await answered).status(),200);
 const calls=await(await fetch(fixture+'/calls')).json();assert.equal(calls.length,1);
 const system=calls[0].messages[0].content;
 assert.ok(system.includes(meaning));assert.ok(system.includes('推测参考'));
 report.checks.push('next_role_request_receives_historical_explanation_as_uncertain_reference');
 await fetch(fixture+'/trigger');state=await snapshot();assert.equal(state.prompts.length,1);assert.equal(state.feedback.length,1);
 report.checks.push('same_host_event_not_repeated_or_reconfirmed');
 await page.reload();
 await page.locator('[data-room-input]').waitFor();
 const refreshed=await page.request.post(base+'/api/companion/microphone',{
  headers:{'X-Sumika-CSRF':(await(await page.request.get(base+'/api/manage/session')).json()).csrf},data:{action:'status',after:0}});
 const status=await refreshed.json();
 assert.equal(status.behavior_prompt_states[persisted.prompts[0].prompt_id],'answered');
 assert.ok(!status.events.some(event=>event.event==='behavior_prompt'));
 assert.equal(await page.locator('[data-behavior-prompt]').count(),0);
 report.checks.push('reload_does_not_resurrect_answered_prompt_from_event_log');
 await page.screenshot({path:join(output,'behavior-prompt.png')});
 assert.deepEqual(report.pageErrors,[]);report.loopback_model_calls=calls.length;report.passed=true;
}catch(error){report.error=String(error.stack||error);report.diagnostics=diagnostics;process.exitCode=1;}
finally{
 await browser?.close();bridge.stdin.end();
 if(bridge.exitCode===null)await Promise.race([once(bridge,'exit'),new Promise(resolve=>{
  const timer=setTimeout(()=>{bridge.kill();resolve();},10000);timer.unref();
 })]);
 await writeFile(join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}
