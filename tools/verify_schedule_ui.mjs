// Existing schedule UI against an isolated real Bridge; no model or user data.
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output=resolve(process.argv[2]||'.sumika-next/acceptance-20261017/schedule-ui');
await mkdir(output,{recursive:true});
const data=await mkdtemp(join(output,'isolated-'));
const candidate=resolve(process.env.SUMIKA_TEST_CANDIDATE||'.');
const bridge=spawn(process.env.SUMIKA_TEST_PYTHON||'python',['-u','-X','utf8','-B','-c',`
import sys,json,threading
from pathlib import Path
from extensions.models.settings import example,save
from ui.server import serve,BUILTIN_ROLES
data=Path(sys.argv[1])
save(example(BUILTIN_ROLES/'sampleA',data/'memory.sqlite3'),data/'settings.json')
server=serve(data/'settings.json',port=0,workbench_root=data,
    capability_database=data/'capabilities.sqlite3',schedule_directory=data/'schedules')
threading.Thread(target=server.serve_forever,daemon=True).start()
print(json.dumps({'port':server.server_port}),flush=True)
try: sys.stdin.read()
finally: server.shutdown();server.server_close()
`,data],{cwd:candidate,stdio:['pipe','pipe','pipe']});
let diagnostics='';bridge.stderr.on('data',chunk=>diagnostics+=chunk);
const report={passed:false,checks:[],pageErrors:[],synthetic_data:true,external_model_calls:0,candidate};
let browser;
try{
  const lines=createInterface({input:bridge.stdout});
  const [line]=await Promise.race([once(lines,'line'),new Promise((_,reject)=>{
    const timer=setTimeout(()=>reject(Error('Bridge start timeout: '+diagnostics.slice(-2000))),20000);timer.unref();
  })]);
  const base='http://127.0.0.1:'+JSON.parse(line).port;
  const {chromium}=loadPlaywright();browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  page.on('pageerror',e=>report.pageErrors.push(e.message));
  const read=()=>page.evaluate(async()=>await(await fetch('/api/manage/schedules')).json());
  const tick=()=>page.evaluate(async()=>{
    const {csrf}=await(await fetch('/api/manage/session')).json();
    const response=await fetch('/api/manage/schedules/tick',{method:'POST',
      headers:{'Content-Type':'application/json','X-Sumika-CSRF':csrf},body:'{}'});
    if(!response.ok)throw Error(await response.text());
    return response.json();
  });
  await page.goto(base+'/#shelf');
  const scheduleCard=page.locator('.cap-card').filter({hasText:'就绪检查 schedule'});
  await scheduleCard.waitFor();
  assert.ok((await scheduleCard.innerText()).includes(join(data,'schedules')));
  report.checks.push('readiness_card_uses_actual_isolated_schedule_directory');
  await page.getByRole('button',{name:'管理模块',exact:true}).waitFor();
  await scheduleCard.click();
  await page.getByRole('button',{name:'管理定时任务',exact:true}).click();
  const modal=page.locator('dialog');
  await modal.getByRole('button',{name:'新建任务',exact:true}).click();
  await modal.getByLabel('任务内容',{exact:true}).fill('future reminder fixture');
  await modal.getByLabel('周期',{exact:true}).selectOption('once');
  const future=new Date(Date.now()+86400000).toISOString();
  await modal.getByLabel('时间表达式',{exact:true}).fill(future);
  await modal.getByRole('button',{name:'保存定义',exact:true}).click();
  await modal.getByText('future reminder fixture',{exact:true}).waitFor();
  assert.equal((await read()).definitions[0].enabled,false);
  report.checks.push('create_future_once_disabled_without_list_failure');
  await modal.getByRole('button',{name:'启用',exact:true}).click();
  await modal.getByRole('button',{name:'停用',exact:true}).waitFor();
  let state=await read();
  assert.equal(Date.parse(state.definitions[0].next_due),Date.parse(future));
  assert.equal((await tick()).occurrences.length,0);
  report.checks.push('enabled_future_once_has_future_due_and_no_early_notification');
  await modal.getByRole('button',{name:'编辑',exact:true}).click();
  await modal.getByLabel('任务内容',{exact:true}).fill('due reminder fixture');
  await modal.getByLabel('时间表达式',{exact:true}).fill('2026-01-01T00:00:00+00:00');
  await modal.getByRole('button',{name:'保存定义',exact:true}).click();
  await modal.getByText('due reminder fixture',{exact:true}).waitFor();
  state=await read();assert.equal(state.definitions[0].enabled,true);
  assert.equal((await tick()).occurrences[0].state,'notified');
  assert.equal((await tick()).occurrences.length,0);
  await modal.getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByRole('button',{name:'管理定时任务',exact:true}).click();
  await modal.getByRole('button',{name:'标为已读',exact:true}).click();
  await modal.getByRole('button',{name:'标为已读',exact:true}).waitFor({state:'detached'});
  state=await read();assert.equal(state.reminders.length,1);assert.equal(state.reminders[0].seen,true);
  report.checks.push('edit_enabled_reminder_tick_deduplicates_and_acknowledges');
  await modal.getByRole('button',{name:'停用',exact:true}).click();
  await modal.getByRole('button',{name:'启用',exact:true}).waitFor();
  assert.equal((await read()).definitions[0].next_due,null);
  await modal.getByRole('button',{name:'编辑',exact:true}).click();
  await modal.getByLabel('类型',{exact:true}).selectOption('execute');
  await modal.getByRole('button',{name:'保存定义',exact:true}).click();
  await modal.locator('form').waitFor({state:'detached'});
  await modal.getByRole('button',{name:'启用',exact:true}).waitFor();
  await modal.getByRole('button',{name:'启用',exact:true}).click();
  await modal.getByText('执行后端未绑定，此任务不会自动执行。',{exact:true}).waitFor();
  assert.equal((await read()).status.blocked.length,1);
  assert.equal((await tick()).occurrences.length,0);
  report.checks.push('disabled_state_and_unbound_execution_are_explicit');
  page.once('dialog',d=>d.accept());
  await modal.getByRole('button',{name:'删除',exact:true}).click();
  await modal.getByRole('button',{name:'编辑',exact:true}).waitFor({state:'detached'});
  state=await read();assert.equal(state.definitions.length,0);
  assert.equal(state.history.length,1);assert.equal(state.reminders.length,1);
  report.checks.push('delete_definition_preserves_occurrence_and_reminder_history');
  await page.screenshot({path:join(output,'schedule-dialog.png')});
  assert.deepEqual(report.pageErrors,[]);report.checks.push('zero_page_errors');report.passed=true;
}catch(error){report.error=String(error.stack||error);process.exitCode=1;}
finally{
  await browser?.close();bridge.stdin.end();
  if(bridge.exitCode===null)await Promise.race([once(bridge,'exit'),new Promise(resolve=>{
    const timer=setTimeout(()=>{bridge.kill();resolve();},10000);timer.unref();
  })]);
  await writeFile(join(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}
