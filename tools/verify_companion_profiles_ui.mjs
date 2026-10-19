// P16 UI verification: companion detail profile management against the real
// bridge — templates, runtime line, select, CRUD dialog, permission pause.
// Real bridge with a temp personal directory; no model calls, no capture.
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, writeFile, readFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output = resolve(process.argv[2] || 'E:/SumikaBuild/companion-profiles-ui');
await mkdir(output, {recursive: true});
const bridgeData = await mkdtemp(join(output, 'isolated-'));
const candidate = resolve(process.env.SUMIKA_TEST_CANDIDATE || '.');
const report = {passed: false, checks: {}, phases: [], candidate,
  synthetic_data: true, api_fixtures: true, real_capture: false};
const log = message => {report.phases.push({at: new Date().toISOString(), message});
  console.log('[ui]', message);};

const bridgeCode = `
import sys, threading, json
from pathlib import Path
data = Path(sys.argv[1])
from extensions.models.settings import example, load, save
config = example(data/'role', data/'sumika.db')
config['enabled'] = True
save(config, data/'settings.json')
from extensions.capabilities import CapabilityStore
store = CapabilityStore(data/'capabilities.sqlite3')
store.configure('memory', 'embedded', options={})
store.close()
from ui.server import serve
server = serve(data/'settings.json', port=0, workbench_root=data,
               capability_database=data/'capabilities.sqlite3', schedule_directory=data/'schedules')
bridge = server.sumika_bridge
library, scope = bridge._behavior_library, bridge._behavior_scope()
library.observe({'event_id':'real-ui-event', 'kind':'revisit', 'source':'ui-acceptance'}, scope=scope)
prompt = library.record_prompt('revisit', event_id='real-ui-event', scope=scope)
library.feedback({'feedback_id':'real-ui-feedback', 'user_event_id':'real-ui-reply',
    'prompt_id':prompt['prompt_id'], 'verdict':'confirm', 'label':'找公式'}, scope=scope)
threading.Thread(target=server.serve_forever, daemon=True).start()
print(json.dumps({'port': server.server_port, 'source_root':str(Path.cwd())}), flush=True)
try: sys.stdin.read()
finally: server.shutdown(); server.server_close()
`;
const bridge = spawn(process.env.SUMIKA_TEST_PYTHON || 'python',
  ['-u', '-X', 'utf8', '-B', '-c', bridgeCode, bridgeData],
  {cwd: candidate, stdio: ['pipe', 'pipe', 'pipe']});
let diagnostics=''; bridge.stderr.on('data', chunk=>diagnostics+=chunk);
let base = null;
let browser, page;
try {
const lines = createInterface({input: bridge.stdout});
await Promise.race([once(lines, 'line').then(([line]) => {
  const ready=JSON.parse(line); report.source_root=ready.source_root;
  assert.equal(resolve(ready.source_root), candidate);
  base = 'http://127.0.0.1:' + ready.port;
}), new Promise((_, reject) => { const timer=setTimeout(() => reject(new Error('bridge start timeout: '+diagnostics.slice(-2000))), 20000);timer.unref(); })]);
log('bridge ready on ' + base);

const {chromium} = loadPlaywright();
browser = await chromium.launch({channel: 'msedge', headless: true});
  page = await browser.newPage({viewport: {width: 900, height: 900}});
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('response',async response=>{if(response.status()>=400&&response.url().includes('/api/manage/behavior'))log(`behavior HTTP ${response.status()}: ${await response.text()}`);});
  await page.route('**/api/companion/microphone',route=>route.fulfill({json:{status:'stopped',cursor:0,events:[],capture:{alive:false,status:'stopped'},application_audio:{alive:false,status:'stopped'}}}));
  await page.route('**/api/companion/windows',route=>route.fulfill({json:{windows:[]}}));
  await page.goto(base + '/', {waitUntil: 'domcontentloaded', timeout: 60000});
  await page.evaluate(async () => {
    const host = document.createElement('main');
    host.style.width = '860px';
    document.body.append(host);
    const {mountCompanionSession} = await import('/app/companion-session.js');
    mountCompanionSession(host);
  });
  // Profiles + permission load asynchronously; wait for the real content.
  await page.waitForFunction(
    () => document.querySelector('[data-companion-profiles]')?.textContent
      .includes('手动选择'), {timeout: 10000});

  const runtimeLine = await page.locator('[data-companion-profiles]').textContent();
  report.checks.runtime_line_templates = runtimeLine.includes('学习')
    && runtimeLine.includes('手动选择');
  log('runtime line: ' + runtimeLine);

  const profileSelect = page.locator('select[aria-label="陪伴模式"]');
  const options = await profileSelect.locator('option').allTextContents();
  report.checks.templates_listed = ['学习', '游戏', '安静']
    .every(name => options.includes(name));

  // Manual select of 游戏.
  const gameValue = await profileSelect.locator('option', {hasText: '游戏'})
    .getAttribute('value');
  await profileSelect.selectOption(gameValue);
  // The change handler performs a revision-guarded HTTP write followed by
  // two reads.  A fixed sleep makes this acceptance check race the bridge
  // under a cold bundled runtime; wait for the server-confirmed projection.
  await page.waitForFunction(() => {
    const text = document.querySelector('[data-companion-profiles]')?.textContent || '';
    return text.includes('游戏') && text.includes('手动选择');
  }, {timeout: 30000});
  report.checks.manual_select_persists =
    (await page.locator('[data-companion-profiles]').textContent())
      .includes('游戏');

  // All profile parameters are editable and survive the real store roundtrip.
  await page.locator('button[aria-label="管理陪伴模式"]').click();
  await page.getByRole('button',{name:'新建陪伴模式',exact:true}).click();
  let editor=page.locator('.companion-profile-editor').last();
  await editor.getByLabel('模式名称',{exact:true}).fill('自定义第四场景');
  await editor.getByLabel('适用场景描述',{exact:true}).fill('比较两份技术文档');
  await editor.getByLabel('回应指引',{exact:true}).fill('回答时列出差异');
  await editor.getByLabel('允许主动回应',{exact:true}).check();
  await editor.getByLabel('主动回应间隔（秒）',{exact:true}).fill('420');
  await editor.getByLabel('允许行为询问',{exact:true}).check();
  await editor.getByLabel('参考画面',{exact:true}).check();
  await editor.getByLabel('参考应用声音',{exact:true}).check();
  await editor.getByRole('button',{name:'保存',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('dialog ul')?.textContent.includes('自定义第四场景'));
  const row=page.locator('dialog li').filter({has:page.locator('strong',{hasText:'自定义第四场景'})});
  await row.getByRole('button',{name:'编辑',exact:true}).click();editor=row.locator('form');
  report.checks.all_profile_settings_persist=await editor.getByLabel('允许主动回应',{exact:true}).isChecked()
    &&await editor.getByLabel('允许行为询问',{exact:true}).isChecked()
    &&await editor.getByLabel('参考应用声音',{exact:true}).isChecked()
    &&await editor.getByLabel('主动回应间隔（秒）',{exact:true}).inputValue()==='420';
  await editor.getByLabel('模式名称',{exact:true}).fill('保留并发草稿');
  let postedRevision;
  await page.route('**/api/manage/companion-profiles',async route=>{
    if(route.request().method()==='POST'&&route.request().postDataJSON().action==='update'){
      postedRevision=route.request().postDataJSON().expected_revision;
      await route.fulfill({status:409,json:{error:'revision conflict'}});
    }else await route.continue();
  });
  await editor.getByRole('button',{name:'保存',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('dialog')?.textContent.includes('草稿已保留'));
  report.checks.conflict_keeps_draft=await editor.getByLabel('模式名称',{exact:true}).inputValue()==='保留并发草稿'&&Number.isInteger(postedRevision);
  await page.unroute('**/api/manage/companion-profiles');
  await page.locator('dialog header button').click();
  await page.getByRole('button',{name:'管理陪伴模式',exact:true}).click();
  let newRow=page.locator('dialog li').filter({has:page.locator('strong',{hasText:'自定义第四场景'})});
  await newRow.getByRole('button',{name:'复制',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('dialog li').length===5);
  report.checks.duplicate_is_independent=await page.evaluate(async()=>{
    const {bridgeFetch}=await import('/app/bridge-client.js');const data=await(await bridgeFetch('/api/manage/companion-profiles')).json();
    return data.profiles.length===5&&new Set(data.profiles.map(p=>p.id)).size===5;
  });
  const gameRow=page.locator('dialog li').filter({has:page.locator('strong',{hasText:/^游戏$/})});
  page.once('dialog',dialog=>dialog.accept());await gameRow.getByRole('button',{name:'删除',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('dialog li').length===4);
  await page.locator('dialog header button').click();
  report.checks.delete_manual_keeps_neutral=await profileSelect.inputValue()==='';
  const toggle=page.locator('button[aria-label="暂停或恢复行为记录"]');
  await toggle.click();await page.waitForFunction(()=>document.querySelector('[aria-label="暂停或恢复行为记录"]')?.textContent==='解除暂停');
  await toggle.click();await page.waitForTimeout(200);
  report.checks.resume_does_not_claim_recording=!(await page.locator('[data-companion-session]').textContent()).includes('行为记录已恢复。');
  report.checks.single_manage_entry=await page.getByRole('button',{name:'管理陪伴模式',exact:true}).count()===1;

  // Real isolated management API: explicit declarations survive reload,
  // can be corrected/deleted, and ordinary viewing never exports history.
  let exportReads=0;
  page.on('request',r=>{if(r.url().endsWith('/api/manage/behavior')&&r.postDataJSON()?.action==='export')exportReads++;});
  await page.evaluate(()=>location.hash='#settings');
  await page.locator('.set-nav [data-section="data"]').click();
  const behaviorData=page.locator('[data-behavior-data]');
  await behaviorData.getByRole('button',{name:'添加偏好或目标',exact:true}).click();
  await page.getByLabel('你希望记住的内容',{exact:true}).fill('隔离验收：喜欢画画');
  await page.getByRole('button',{name:'保存声明',exact:true}).click();
  await page.locator('[data-declaration-id]').filter({hasText:'隔离验收：喜欢画画'}).waitFor();
  await page.reload({waitUntil:'domcontentloaded'});
  await page.locator('.set-nav [data-section="data"]').click();
  let declaration=page.locator('[data-declaration-id]').filter({hasText:'隔离验收：喜欢画画'});
  await declaration.waitFor();
  report.checks.real_declaration_reload=true;
  await declaration.getByRole('button',{name:'更正',exact:true}).click();
  await page.getByLabel('态度',{exact:true}).selectOption('negative');
  await page.getByRole('button',{name:'保存声明',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-behavior-declarations]')?.textContent.includes('避免 / 不喜欢'));
  report.checks.real_declaration_correction=true;
  await page.screenshot({path:join(output,'behavior-data-real.png')});
  await page.setViewportSize({width:560,height:900});
  report.checks.data_no_horizontal_overflow=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth);
  await page.screenshot({path:join(output,'behavior-data-narrow.png')});
  await page.setViewportSize({width:900,height:900});
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('[data-declaration-id]').getByRole('button',{name:'删除',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-declaration-id]').length===0);
  report.checks.real_declaration_delete=true;
  await behaviorData.getByRole('button',{name:'查看分层记录',exact:true}).click();
  const realFeedback=page.locator('[data-feedback-id="real-ui-feedback"]');
  await realFeedback.waitFor();
  await realFeedback.getByRole('button',{name:'更正解释',exact:true}).click();
  await page.getByLabel('真实含义或解释',{exact:true}).fill('比较定义');
  await page.getByRole('button',{name:'保存更正',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-feedback-id="real-ui-feedback"]')?.textContent.includes('比较定义'));
  await page.reload({waitUntil:'domcontentloaded'});
  await page.locator('.set-nav [data-section="data"]').click();
  await page.getByRole('button',{name:'查看分层记录',exact:true}).click();
  await realFeedback.waitFor();
  assert.ok((await realFeedback.innerText()).includes('比较定义'));
  report.checks.real_feedback_correction_survives_reload=true;
  page.once('dialog',dialog=>dialog.accept());
  await realFeedback.getByRole('button',{name:'删除解释',exact:true}).click();
  await realFeedback.waitFor({state:'detached'});
  await page.reload({waitUntil:'domcontentloaded'});
  await page.locator('.set-nav [data-section="data"]').click();
  await page.getByRole('button',{name:'查看分层记录',exact:true}).click();
  await page.getByText('这一层暂无记录。',{exact:true}).waitFor();
  report.checks.real_feedback_delete_survives_reload=true;
  report.checks.view_does_not_export=exportReads===0;
  page.once('dialog',dialog=>dialog.accept());
  const deletedResponse=page.waitForResponse(response=>response.url().endsWith('/api/manage/behavior')
    && response.request().method()==='POST' && response.request().postDataJSON()?.action==='delete');
  await page.getByRole('button',{name:'删除全部行为记录',exact:true}).click();
  assert.ok((await deletedResponse).ok());
  const remaining=await page.evaluate(async()=>{
    const {bridgeFetch}=await import('/app/bridge-client.js');
    return await(await bridgeFetch('/api/manage/behavior',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'export'})})).json();
  });
  assert.ok(['events','frames','episodes','prompts','feedback','patterns','progress'].every(layer=>remaining[layer]?.length===0));
  report.checks.real_delete_all_clears_all_layers=true;

  // Exercise existing permission/data sections with isolated API fixtures.
  const permission={revision:3,recording:false,use_memory:true,questions:false,startup_resume:false,question_profile:'medium',paused:false,revoked:false,excluded_apps:['sumika','sumikapet','sumikaprocessaudio']};
  let deleteAll=false,feedback=null,permissionSaved=null,feedbackLabel='找公式',forgotFeedback=false;
  const effective=()=>({paused:permission.paused,can_record:permission.recording&&!permission.paused,can_use_memory:permission.use_memory&&!permission.paused,can_answer_questions:permission.questions&&!permission.paused});
  await page.route('**/api/manage/behavior',async route=>{
    const body=route.request().postDataJSON();let value={};
    if(body.action==='permission_status')value={permission,effective:effective()};
    else if(body.action==='permission_save'){permissionSaved=body;Object.assign(permission,body.mutations);permission.revision++;value={effective:effective()};}
    else if(body.action==='permission_pause'||body.action==='permission_resume'){permission.paused=body.action==='permission_pause';permission.revision++;value={effective:effective()};}
    else if(body.action==='status')value={revision:7,root:'fixture/behavior',events_by_kind:{pdf:1}};
    else if(body.action==='activity_overview')value={effective_seconds:300,switch_count:2,buckets:[{date:'2026-10-17',hour:10,app_name:'reader.exe',effective_seconds:300}],operations:{find:3},input_quality:[],progress:[],activity_affinity:[]};
    else if(body.action==='declarations'||body.action==='habits')value={records:[]};
    else if(body.action==='list_layer')value={records:body.layer==='feedback'?(forgotFeedback?[]:[{feedback_id:'f1',label:feedbackLabel,at:'2026-10-17'}]):[{episode_id:'ep1',pattern:'find|scroll',source:'fixture'}],next_cursor:null};
    else if(body.action==='correct'){if(body.feedback_id==='f1'&&body.revision===7)feedbackLabel=body.corrected;}
    else if(body.action==='forget_feedback'){forgotFeedback=body.feedback_id==='f1'&&body.revision===7;}
    else if(body.action==='export')value={events:[{event_id:'e1'}],episodes:[{episode_id:'ep1'}],feedback:[{corrected:'找公式'}],prompts:[],patterns:[],progress:[]};
    else if(body.action==='delete'){deleteAll=body.all_records===true&&body.confirmed===true&&body.revision===7;}
    else if(body.action==='prompt_feedback'){feedback=body;}
    await route.fulfill({json:value});
  });
  // Reload rebuilds settings with the fixture baseline and keeps writes isolated.
  await page.reload({waitUntil:'domcontentloaded'});
  await page.locator('[data-behavior-permissions]').waitFor({state:'attached'});
  await page.evaluate(()=>location.hash='#settings');
  await page.locator('.set-nav [data-section="permissions"]').click();
  await page.getByLabel('允许主动行为询问',{exact:true}).check();
  await page.getByLabel('随 Sumika 启动恢复已保存许可',{exact:true}).check();
  await page.getByLabel('询问频率',{exact:true}).selectOption('quiet');
  await page.getByRole('button',{name:'保存行为许可',exact:true}).click();
  await page.waitForTimeout(150);
  report.checks.independent_permission_switches=permissionSaved?.mutations.recording===false&&permissionSaved?.mutations.use_memory===true&&permissionSaved?.mutations.questions===true&&permissionSaved?.mutations.startup_resume===true;
  report.checks.question_profile_persists=permissionSaved?.mutations.question_profile==='quiet';
  await page.locator('.set-nav [data-section="data"]').click();
  await page.getByRole('button',{name:'查看分层记录',exact:true}).click();
  await page.locator('[data-feedback-id="f1"]').waitFor();
  report.checks.all_layers_visible=await page.getByLabel('记录层',{exact:true}).locator('option').count()===6;
  report.checks.activity_overview_visible=(await page.locator('[data-behavior-overview]').textContent()).includes('5.0 分钟');
  await page.locator('[data-feedback-id="f1"]').getByRole('button',{name:'更正解释',exact:true}).click();
  await page.getByLabel('真实含义或解释',{exact:true}).fill('比较定义');
  await page.getByRole('button',{name:'保存更正',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-feedback-id="f1"]')?.textContent.includes('比较定义'));
  report.checks.inline_feedback_correction=feedbackLabel==='比较定义';
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('[data-feedback-id="f1"]').getByRole('button',{name:'删除解释',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-feedback-id]').length===0);
  report.checks.inline_feedback_delete=forgotFeedback;
  await page.getByLabel('记录层',{exact:true}).selectOption('episodes');
  await page.getByText('find|scroll',{exact:true}).waitFor();
  page.on('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'删除全部行为记录',exact:true}).click();await page.waitForTimeout(100);
  report.checks.delete_all_explicit=deleteAll;
  await page.route('**/api/companion/microphone',route=>route.fulfill({json:{status:'stopped',cursor:1,events:[{sequence:1,event:'behavior_prompt',prompt_id:'prompt-fixture',kind:'pdf_revisit',text:'这次是在找公式还是比较定义？'}]}}));
  await page.evaluate(()=>location.hash='#room');
  const prompt=page.locator('[data-behavior-prompt="prompt-fixture"]');await prompt.waitFor({timeout:6000});
  await prompt.getByRole('button',{name:'确认本次',exact:true}).click();
  report.checks.confirm_requires_meaning=feedback===null;
  await prompt.getByLabel('这次操作的真实含义',{exact:true}).fill('在比较两个定义');
  await prompt.getByRole('button',{name:'纠正本次',exact:true}).click();await page.waitForTimeout(100);
  report.checks.prompt_feedback_explicit=feedback?.prompt_id==='prompt-fixture'&&feedback?.verdict==='correct'&&feedback?.corrected==='在比较两个定义';
  await page.screenshot({path:join(output,'behavior-prompt.png')});

  report.checks.zero_pageerror = pageErrors.length === 0;
  if (pageErrors.length) report.pageerrors = pageErrors;
  report.passed = Object.values(report.checks).every(Boolean);
  log('passed: ' + report.passed);
  process.exitCode = report.passed ? 0 : 1;
} catch(error) {
  report.error=String(error); report.diagnostics=diagnostics.slice(-4000);
  if(page){await page.screenshot({path:join(output,'failure.png')});log((await page.locator('[data-behavior-data]').textContent().catch(()=>''))+' '+(await page.locator('dialog').allTextContents()).join(' '));}
  throw error;
} finally {
  await browser?.close();
  if(bridge.exitCode===null){
    bridge.stdin.end();
    await Promise.race([once(bridge,'exit'),new Promise(resolve=>{
      const timer=setTimeout(resolve,15000);timer.unref();
    })]);
    if(bridge.exitCode===null)bridge.kill();
  }
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({passed: report.passed, checks: report.checks,
    evidence: join(output, 'report.json')}));
}
