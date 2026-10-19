// Existing memory dialog against an isolated real Bridge and SQLite repository.
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, writeFile, readFile, readdir} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output=resolve(process.argv[2]||'.sumika-next/acceptance-20261017-final/memory-relations-ui');
await mkdir(output,{recursive:true});
const data=await mkdtemp(join(output,'isolated-'));
const candidate=resolve(process.env.SUMIKA_TEST_CANDIDATE||'.');
const bridge=spawn(process.env.SUMIKA_TEST_PYTHON||'python',['-u','-X','utf8','-B','-c',`
import sys, json, threading
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
other=import_card(card,data/'roles','other')
settings=example(role,data/'memory.sqlite3')
save(settings,data/'settings.json')
with sqlite3.connect(data/'memory.sqlite3') as db:
    usage=UsageStore(db)
    usage.record(scope=settings['role']['project_id'],session='room-fixture',provider='fixture',model='partial-meter',
        prompt_tokens=10,completion_tokens=5,status='reported',category='room')
    usage.record(scope=settings['role']['project_id'],session='room-other',provider='fixture',model='other-role',
        prompt_tokens=2,completion_tokens=1,total_tokens=3,status='reported',category='room')
server=serve(data/'settings.json',port=0,workbench_root=data,capability_database=data/'capabilities.sqlite3')
server.sumika_bridge._role_paths=lambda:{'fixture':str(role),'other':str(other)}
server.sumika_bridge._role_kinds=lambda:{'fixture':'user','other':'user'}
manager=server.sumika_bridge.management
state=manager.memory('fixture')
state=manager.memory('fixture','remember',{'expected_revision':state['revision'],'text':'likes tea','request_id':'fixture-fact'})
for _ in range(2):
    state=manager.memory('fixture','relate',{'expected_revision':state['revision'],'subject':'user','predicate':'likes','object':'tea'})
session=manager.role_session('fixture')
try:
    for suffix,text in [('accept','prefers quiet mornings'),('reject','unconfirmed guess')]:
        session.memory.put_proposal(event_id='fixture:'+suffix,text=text,quote='synthetic user quote',message_id='fixture:'+suffix+':user',**session.scope)
finally:session.close()
threading.Thread(target=server.serve_forever,daemon=True).start()
print(json.dumps({'port':server.server_port}),flush=True)
try: sys.stdin.read()
finally: server.shutdown(); server.server_close()
`,data],{cwd:candidate,stdio:['pipe','pipe','pipe']});
let diagnostics='';bridge.stderr.on('data',chunk=>diagnostics+=chunk);
const report={passed:false,checks:[],pageErrors:[],synthetic_data:true,external_model_calls:0,candidate};
let browser;
try{
  const lines=createInterface({input:bridge.stdout});
  const [line]=await Promise.race([once(lines,'line'),once(bridge,'exit').then(([code])=>{
    throw Error('Bridge exited before ready: '+code+' '+diagnostics.slice(-2000));
  }),new Promise((_,reject)=>{
    const timer=setTimeout(()=>reject(Error('Bridge start timeout: '+diagnostics.slice(-2000))),20000);timer.unref();
  })]);
  const base='http://127.0.0.1:'+JSON.parse(line).port;
  const {chromium}=loadPlaywright();browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  page.on('pageerror',e=>report.pageErrors.push(e.message));
  // Only role discovery is synthetic; memory reads/writes use real HTTP handlers.
  await page.route('**/api/roles',r=>r.fulfill({json:{active:{id:'fixture'},roles:[{id:'fixture',name:'Fixture',complete:true},{id:'other',name:'Other',complete:true}]}}));
  await page.goto(base+'/#room');
  await page.locator('#rosterBar').click();
  await page.getByRole('button',{name:'管理角色与记忆',exact:true}).click();
  const modal=page.locator('dialog');
  await modal.getByRole('heading',{name:'关系（2）',exact:true}).waitFor();
  report.checks.push('existing_dialog_displays_duplicate_relations');
  const usage=await page.evaluate(async()=>await(await fetch('/api/manage/roles/fixture/usage')).json());
  assert.equal(usage.groups.length,1);
  assert.equal(usage.groups[0].model,'partial-meter');
  assert.equal(usage.categories[0].requests,2);
  await modal.getByRole('heading',{name:'当前项目用量（全部业务类别）',exact:true}).waitFor();
  await modal.getByText(/12 输入|输入 12 token/).waitFor();
  await modal.getByText(/输出 6 token.*合计 3 token.*1 次记录计量不完整/).waitFor();
  assert.doesNotMatch(await modal.innerText(),/12 token \+ 6 token/);
  report.checks.push('project_usage_includes_other_role_and_displays_partial_measurement');
  const read=()=>page.evaluate(async()=>await(await fetch('/api/manage/roles/fixture/memory')).json());
  const initial=await read();
  const originalFact=initial.memories[0];
  page.once('dialog',d=>d.dismiss());
  await modal.getByRole('button',{name:'纠正',exact:true}).click();
  assert.equal((await read()).memories[0].record_id,originalFact.record_id);
  report.checks.push('correction_cancel_preserves_fact');
  let dialogs=0;
  const correctionDialogs=d=>{
    dialogs++;
    if(d.type()==='prompt')return d.accept('likes coffee');
    assert.match(d.message(),/likes coffee/);return d.accept();
  };
  page.on('dialog',correctionDialogs);
  await modal.getByRole('button',{name:'纠正',exact:true}).click();
  await modal.getByText('likes coffee',{exact:true}).waitFor();
  page.off('dialog',correctionDialogs);
  assert.equal(dialogs,2);
  const corrected=await read();
  assert.equal(corrected.memories[0].text,'likes coffee');
  assert.notEqual(corrected.memories[0].record_id,originalFact.record_id);
  assert.equal(corrected.memories.length,1);
  report.checks.push('real_http_confirmed_correction_replaces_active_fact');
  // A second client commits while the original dialog still holds its snapshot.
  await page.evaluate(async()=>{
    const state=await(await fetch('/api/manage/roles/fixture/memory')).json();
    const {csrf}=await(await fetch('/api/manage/session')).json();
    const response=await fetch('/api/manage/roles/fixture/memory/remember',{method:'POST',
      headers:{'Content-Type':'application/json','X-Sumika-CSRF':csrf},
      body:JSON.stringify({expected_revision:state.revision,text:'independent fact',request_id:'second-client'})});
    if(!response.ok)throw Error('concurrent fixture write failed: '+await response.text());
  });
  const staleDialogs=d=>d.type()==='prompt'?d.accept('stale change'):d.accept();
  page.on('dialog',staleDialogs);
  await modal.getByRole('button',{name:'纠正',exact:true}).click();
  await modal.locator('[data-management-error]').waitFor();
  page.off('dialog',staleDialogs);
  assert.equal((await read()).memories.find(m=>m.record_id===corrected.memories[0].record_id).text,'likes coffee');
  report.checks.push('stale_dialog_correction_rejected_without_overwrite');
  await modal.getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByRole('button',{name:'管理角色与记忆',exact:true}).click();
  await modal.getByText('likes coffee',{exact:true}).waitFor();
  report.checks.push('correction_persists_after_dialog_reload');
  page.once('dialog',d=>{assert.match(d.message(),/只更新当前这一条/);return d.accept('coffee');});
  await modal.getByRole('button',{name:'编辑',exact:true}).first().click();
  await modal.getByText('user → likes → coffee',{exact:true}).waitFor();
  let state=await read();
  assert.deepEqual(state.relations.map(r=>r.object),['coffee','tea']);
  assert.equal(state.relations[0].record_id,initial.relations[0].record_id);
  assert.equal(state.relations[0].revision,initial.relations[0].revision+1);
  report.checks.push('real_http_edit_changes_only_selected_identity_and_revision');
  page.once('dialog',d=>d.accept());
  await modal.getByRole('button',{name:'删除',exact:true}).first().click();
  await modal.getByRole('heading',{name:'关系（1）',exact:true}).waitFor();
  state=await read();
  assert.equal(state.relations.length,1);
  assert.equal(state.relations[0].record_id,initial.relations[1].record_id);
  report.checks.push('real_http_delete_preserves_other_duplicate');

  // Extend the existing real dialog test to cover the remaining governance
  // actions. Only the isolated fixture database and downloads are affected.
  await modal.getByLabel('新增事实',{exact:true}).fill('manual fixture fact');
  await modal.getByRole('button',{name:'保存事实',exact:true}).click();
  await modal.getByText('manual fixture fact',{exact:true}).waitFor();
  assert.ok((await read()).memories.some(m=>m.text==='manual fixture fact'));
  report.checks.push('ui_manual_fact_persists');

  const proposalRow=text=>modal.locator('.sumika-record').filter({has:page.getByText(text,{exact:true})});
  page.once('dialog',d=>d.accept());
  await proposalRow('prefers quiet mornings').getByRole('button',{name:'确认记住',exact:true}).click();
  await modal.getByRole('heading',{name:'待确认记忆（1）',exact:true}).waitFor();
  await proposalRow('unconfirmed guess').getByRole('button',{name:'忽略',exact:true}).click();
  await modal.getByRole('heading',{name:'待确认记忆（0）',exact:true}).waitFor();
  state=await read();
  assert.ok(state.memories.some(m=>m.text==='prefers quiet mornings'));
  assert.ok(!state.memories.some(m=>m.text==='unconfirmed guess'));
  assert.equal(state.proposals.find(p=>p.event_id==='fixture:reject').status,'rejected');
  report.checks.push('ui_accept_and_ignore_proposals_change_real_repository');

  const downloading=page.waitForEvent('download');
  await modal.getByRole('button',{name:'导出记忆',exact:true}).click();
  const download=await downloading;
  const exportedPath=join(output,'fixture-memory-export.json');
  await download.saveAs(exportedPath);
  const exported=JSON.parse(await readFile(exportedPath,'utf8'));
  assert.equal(exported.schema_version,5);
  assert.equal(exported.memories.filter(m=>m.active).length,state.memories.length);
  assert.equal(exported.ui_scope.role_id,'fixture');
  report.checks.push('ui_download_exports_versioned_scope_and_governance');

  const backupCount=async()=>{try{return(await readdir(join(data,'backups','memory'))).length;}catch(error){if(error.code==='ENOENT')return 0;throw error;}};
  const beforeCancel=await read(),backupsBefore=await backupCount();
  page.once('dialog',d=>d.dismiss());
  await modal.getByRole('button',{name:'重置到角色卡',exact:true}).click();
  assert.deepEqual(await read(),beforeCancel);
  assert.equal(await backupCount(),backupsBefore);
  report.checks.push('reset_cancel_preserves_data_without_backup_write');

  await modal.getByLabel('角色',{exact:true}).selectOption('other');
  await modal.getByText(/记忆作用域：other/).waitFor();
  const otherRead=async()=>await(await page.request.get(base+'/api/manage/roles/other/memory')).json();
  const otherBefore=await otherRead();
  const choose=page.waitForEvent('filechooser');
  await modal.getByRole('button',{name:'恢复备份',exact:true}).click();
  const refused=page.waitForResponse(r=>r.url().endsWith('/roles/other/memory/restore')&&r.request().method()==='POST');
  page.once('dialog',d=>d.accept());
  await(await choose).setFiles(exportedPath);
  assert.equal((await refused).status(),400);
  assert.deepEqual(await otherRead(),otherBefore);
  report.checks.push('ui_foreign_role_restore_refused_without_scope_changes');

  await modal.getByLabel('角色',{exact:true}).selectOption('fixture');
  await modal.getByText('manual fixture fact',{exact:true}).waitFor();
  page.once('dialog',d=>d.accept());
  await modal.getByRole('button',{name:'重置到角色卡',exact:true}).click();
  await modal.getByRole('heading',{name:'关系（0）',exact:true}).waitFor();
  state=await read();
  assert.deepEqual(state.memories.map(m=>m.text),['Synthetic test']);assert.equal(state.relations.length,0);
  assert.ok(!state.proposals.some(p=>(p.status||'pending')==='pending'));
  assert.ok(await backupCount()>backupsBefore);
  report.checks.push('ui_reset_clears_learned_state_and_saves_backup');

  const restoreChoice=page.waitForEvent('filechooser');
  await modal.getByRole('button',{name:'恢复备份',exact:true}).click();
  page.once('dialog',d=>d.accept());
  await(await restoreChoice).setFiles(exportedPath);
  await modal.getByText('manual fixture fact',{exact:true}).waitFor();
  state=await read();
  assert.equal(state.memories.length,beforeCancel.memories.length);
  assert.deepEqual(state.relations.map(r=>r.object),beforeCancel.relations.map(r=>r.object));
  assert.equal(state.proposals.find(p=>p.event_id==='fixture:reject').status,'rejected');
  report.checks.push('ui_same_scope_restore_recovers_facts_relations_and_proposal_status');

  page.once('dialog',d=>d.accept());
  await proposalRow('manual fixture fact').getByRole('button',{name:'遗忘',exact:true}).click();
  await modal.getByText('manual fixture fact',{exact:true}).waitFor({state:'detached'});
  assert.ok(!(await read()).memories.some(m=>m.text==='manual fixture fact'));
  await modal.getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByRole('button',{name:'管理角色与记忆',exact:true}).click();
  await modal.getByText('likes coffee',{exact:true}).waitFor();
  assert.equal(await modal.getByText('manual fixture fact',{exact:true}).count(),0);
  report.checks.push('ui_forget_survives_dialog_reload');
  await page.screenshot({path:join(output,'memory-dialog.png')});
  assert.deepEqual(report.pageErrors,[]);
  report.checks.push('zero_page_errors');report.passed=true;
}catch(error){report.error=String(error.stack||error);process.exitCode=1;}
finally{
  await browser?.close();
  bridge.stdin.end();
  if(bridge.exitCode===null)await Promise.race([once(bridge,'exit'),new Promise(resolve=>{
    const timer=setTimeout(()=>{bridge.kill();resolve();},10000);timer.unref();
  })]);
  await writeFile(join(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}
