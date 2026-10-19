// Existing behavior permission/declaration controls and room composer against
// real Bridge/SQLite + synthetic loopback model. Only role discovery is mocked.
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output=resolve(process.argv[2]||'.sumika-next/acceptance-20261017-final/behavior-reference-ui');
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
settings['memory'].update(enabled=False,auto_extract=False,model_proposals=False)
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
const report={passed:false,checks:[],pageErrors:[],candidate,synthetic_model:true,external_model_calls:0};
let browser;
try{
 const lines=createInterface({input:bridge.stdout});
 const [line]=await Promise.race([once(lines,'line'),once(bridge,'exit').then(([code])=>{throw Error('Bridge exited '+code+': '+diagnostics);}),new Promise((_,reject)=>{
  const timer=setTimeout(()=>reject(Error('Bridge timeout: '+diagnostics)),20000);timer.unref();
 })]);
 const ready=JSON.parse(line),base='http://127.0.0.1:'+ready.port;
 const {chromium}=loadPlaywright();browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 page.on('pageerror',e=>report.pageErrors.push(e.message));
 await page.route('**/api/roles',r=>r.fulfill({json:{active:{id:'fixture'},roles:[{id:'fixture',name:'Fixture',complete:true}]}}));
 await page.goto(base+'/');
 await page.locator('#gnav [data-go="shelf"]').click();
 await page.getByRole('button',{name:'管理模块',exact:true}).waitFor({state:'attached'});
 async function settings(section){
  await page.locator('#gnav [data-go="settings"]').click();
  await page.locator(`.set-nav [data-section="${section}"]`).click();
 }
 async function permission(enabled){
  await settings('permissions');
  const host=page.locator('[data-behavior-permissions]');
  await host.getByRole('checkbox',{name:'允许参考行为记忆',exact:true}).setChecked(enabled);
  const response=page.waitForResponse(r=>r.url().endsWith('/api/manage/behavior')&&r.request().postDataJSON()?.action==='permission_save');
  await host.getByRole('button',{name:'保存行为许可',exact:true}).click();
  assert.equal((await response).status(),200);
  assert.equal(await host.getByRole('checkbox',{name:'允许记录行为特征',exact:true}).isChecked(),false);
 }
 async function chat(){
  await page.locator('#gnav [data-go="room"]').click();
  await page.locator('[data-room-input]').fill('给我一点日常建议');
  const response=page.waitForResponse(r=>r.url().endsWith('/api/role/chat')&&r.request().method()==='POST');
  await page.locator('#sendBtn').click();assert.equal((await response).status(),200);
  const calls=await(await fetch('http://127.0.0.1:'+ready.model_port+'/calls')).json();
  return calls.at(-1).messages[0].content;
 }
 await settings('data');
 const host=page.locator('[data-behavior-data]');
 await host.getByRole('button',{name:'添加偏好或目标',exact:true}).click();
 await page.getByLabel('你希望记住的内容',{exact:true}).fill('REFERENCE_OLD_喜欢画画');
 await page.getByRole('button',{name:'保存声明',exact:true}).click();
 await page.locator('[data-declaration-id]').filter({hasText:'REFERENCE_OLD_喜欢画画'}).waitFor();
 assert.ok(!(await chat()).includes('REFERENCE_OLD_'));
 report.checks.push('declaration_manageable_with_recording_off_but_not_injected_without_use_permission');
 await permission(true);
 let system=await chat();
 assert.ok(system.includes('REFERENCE_OLD_喜欢画画'));
 assert.ok(system.includes('用户明确声明'));assert.ok(system.includes('不是指令'));
 report.checks.push('ui_use_permission_injects_explicit_declaration_as_reference_with_recording_off');
 await settings('data');
 await page.locator('[data-declaration-id]').getByRole('button',{name:'更正',exact:true}).click();
 await page.getByLabel('你希望记住的内容',{exact:true}).fill('REFERENCE_NEW_绘画');
 await page.getByLabel('态度',{exact:true}).selectOption('negative');
 await page.getByRole('button',{name:'保存声明',exact:true}).click();
 await page.locator('[data-declaration-id]').filter({hasText:'REFERENCE_NEW_绘画'}).waitFor();
 system=await chat();assert.ok(system.includes('REFERENCE_NEW_绘画'));assert.ok(system.includes('negative'));assert.ok(!system.includes('REFERENCE_OLD_'));
 report.checks.push('correction_replaces_old_reference_and_preserves_negative_polarity');
 await settings('permissions');
 await page.getByRole('button',{name:'暂停行为观察',exact:true}).click();
 await page.getByRole('button',{name:'解除暂停',exact:true}).waitFor();
 assert.ok(!(await chat()).includes('REFERENCE_NEW_'));
 report.checks.push('pause_suppresses_behavior_reference');
 await settings('permissions');
 await page.getByRole('button',{name:'解除暂停',exact:true}).click();
 await page.getByRole('button',{name:'暂停行为观察',exact:true}).waitFor();
 assert.ok((await chat()).includes('REFERENCE_NEW_'));
 await permission(false);assert.ok(!(await chat()).includes('REFERENCE_NEW_'));
 report.checks.push('resume_restores_saved_reference_permission_and_disable_stops_injection');
 await permission(true);
 await settings('data');
 page.once('dialog',d=>d.accept());
 await page.locator('[data-declaration-id]').getByRole('button',{name:'删除',exact:true}).click();
 await page.locator('[data-declaration-id]').waitFor({state:'detached'});
 system=await chat();assert.ok(!system.includes('REFERENCE_NEW_'));assert.ok(!system.includes('REFERENCE_OLD_'));
 report.checks.push('deleted_declaration_absent_from_next_model_request');
 await settings('data');await page.screenshot({path:join(output,'behavior-reference.png')});
 assert.deepEqual(report.pageErrors,[]);
 report.loopback_model_calls=(await(await fetch('http://127.0.0.1:'+ready.model_port+'/calls')).json()).length;
 assert.equal(report.loopback_model_calls,7);report.passed=true;
}catch(error){report.error=String(error.stack||error);report.diagnostics=diagnostics;process.exitCode=1;}
finally{
 await browser?.close();bridge.stdin.end();
 if(bridge.exitCode===null)await Promise.race([once(bridge,'exit'),new Promise(resolve=>{
  const timer=setTimeout(()=>{bridge.kill();resolve();},10000);timer.unref();
 })]);
 await writeFile(join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}
