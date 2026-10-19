// Approved role-resource editor against an isolated real Bridge and role store.
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output=resolve(process.argv[2]||'.sumika-next/acceptance-20261017-final/role-resources-ui');
await mkdir(output,{recursive:true});
const data=await mkdtemp(join(output,'isolated-'));
const candidate=resolve(process.env.SUMIKA_TEST_CANDIDATE||'.');
const bridge=spawn(process.env.SUMIKA_TEST_PYTHON||'python',['-u','-X','utf8','-B','-c',`
import sys, json, threading, hashlib
from pathlib import Path
from extensions.models.settings import example, save
from extensions.roles.roles import import_card, attach_asset, export_package, import_package, load_role
from ui.server import serve
data=Path(sys.argv[1])
card=data/'card.json'
card.write_text(json.dumps({'spec':'chara_card_v2','data':{'name':'Fixture','description':'Synthetic test'}}),encoding='utf8')
role=import_card(card,data/'roles','fixture')
other=import_card(card,data/'roles','other')
sample=Path.cwd()/'extensions/roles/defaults/sampleA/AvatarSample_A.vrm'
attached=attach_asset('fixture',data/'roles','model_3d',sample)
package=export_package('fixture',data/'roles',data/'real-vrm-roundtrip.zip')
restored=load_role(import_package(package,data/'restored'))
real_vrm_roundtrip=(hashlib.sha256(sample.read_bytes()).hexdigest()==
    hashlib.sha256(Path(restored['assets']['model_3d']).read_bytes()).hexdigest()
    and restored['verified']['status']=='ok')
bundle=data/'resource-bundle'
(bundle/'textures').mkdir(parents=True)
(bundle/'model.model3.json').write_text('{"texture":"textures/face.png"}',encoding='utf8')
(bundle/'textures/face.png').write_bytes(b'synthetic dependency')
settings=example(role,data/'memory.sqlite3')
save(settings,data/'settings.json')
server=serve(data/'settings.json',port=0,workbench_root=data,capability_database=data/'capabilities.sqlite3')
server.sumika_bridge._role_paths=lambda:{'fixture':str(role),'other':str(other)}
server.sumika_bridge._role_kinds=lambda:{'fixture':'user','other':'user'}
threading.Thread(target=server.serve_forever,daemon=True).start()
print(json.dumps({'port':server.server_port,'real_vrm_roundtrip':real_vrm_roundtrip}),flush=True)
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
  const ready=JSON.parse(line);
  assert.equal(ready.real_vrm_roundtrip,true);
  report.checks.push('real_15mb_vrm_import_export_restore_byte_identical');
  const base='http://127.0.0.1:'+ready.port;
  const {chromium}=loadPlaywright();browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  page.on('pageerror',e=>report.pageErrors.push(e.message));
  await page.route('**/api/roles',async route=>{
    const state=await(await fetch(base+'/api/manage/roles/fixture/resources')).json();
    await route.fulfill({json:{active:{id:'fixture'},roles:[
      {id:'fixture',name:'Fixture',complete:true,theme:state.theme},
      {id:'other',name:'Other',complete:true,theme:{}}]}});
  });
  await page.goto(base+'/#room');
  await page.locator('#rosterBar').click();
  await page.getByRole('button',{name:'管理角色与记忆',exact:true}).click();
  await page.getByRole('button',{name:'管理角色资源',exact:true}).click();
  const modal=page.locator('dialog').last();
  await modal.getByLabel('背景设定',{exact:true}).fill('Browser synthetic background');
  await modal.getByRole('button',{name:'添加世界书条目',exact:true}).click();
  await modal.getByLabel('条目内容',{exact:true}).fill('Browser worldbook fact');
  await modal.getByLabel('关键词（每行一个）',{exact:true}).fill('garden\nblue');
  await modal.getByLabel('角色主色（#RRGGBB，留空用默认）',{exact:true}).fill('#123456');
  await modal.getByLabel('角色浅色（#RRGGBB，留空用默认）',{exact:true}).fill('#abcdef');
  const save=()=>modal.getByRole('button',{name:'保存背景、世界书与配色',exact:true}).click();
  await save();await modal.getByText(/已完成，恢复副本/).waitFor();
  const read=async()=>await(await fetch(base+'/api/manage/roles/fixture/resources')).json();
  let state=await read();assert.equal(state.background,'Browser synthetic background');
  assert.deepEqual(state.worldbook[0].keys,['garden','blue']);assert.equal(state.theme.accent,'#123456');
  await page.waitForFunction(()=>document.documentElement.style.getPropertyValue('--chara')==='#123456');
  report.checks.push('existing_dialog_real_http_save_backup_and_theme');
  await modal.getByLabel('角色主色（#RRGGBB，留空用默认）',{exact:true}).fill('invalid');
  await save();await modal.getByText('theme colors must be #RRGGBB',{exact:true}).waitFor();
  assert.equal((await read()).theme.accent,'#123456');
  report.checks.push('invalid_theme_rejected_without_overwrite');
  await modal.getByLabel('角色主色（#RRGGBB，留空用默认）',{exact:true}).fill('');
  await modal.getByLabel('角色浅色（#RRGGBB，留空用默认）',{exact:true}).fill('');
  await save();
  await page.waitForFunction(()=>document.documentElement.style.getPropertyValue('--chara')!=='#123456');
  assert.deepEqual((await read()).theme,{});
  report.checks.push('clearing_role_theme_restores_default');
  page.on('dialog',dialog=>dialog.accept());
  await modal.getByLabel('资源类型',{exact:true}).selectOption('model_2d');
  await modal.getByLabel('本机资源文件或目录路径',{exact:true}).fill(join(data,'resource-bundle'));
  const attached=page.waitForResponse(response=>response.url().endsWith('/resources/attach'));
  await modal.getByRole('button',{name:'绑定资源',exact:true}).click();
  const attachedResponse=await attached;assert.equal(attachedResponse.status(),200);
  const attachedState=await attachedResponse.json();
  assert.ok(attachedState.assets.includes('model_2d'));
  assert.ok(attachedState.backup);
  report.checks.push('directory_resource_imported_from_existing_path_field_with_backup');
  await page.screenshot({path:join(output,'role-resources.png'),fullPage:true});
  await modal.getByRole('button',{name:'关闭',exact:true}).click();
  await page.evaluate(()=>location.hash='#shelf');
  const card=page.locator('.cap-card').filter({has:page.getByRole('heading',{name:'角色卡 · 世界书',exact:true})});
  await card.click();await page.getByRole('button',{name:'管理角色资源',exact:true}).click();
  const reopened=page.locator('dialog');
  assert.equal(await reopened.getByLabel('背景设定',{exact:true}).inputValue(),'Browser synthetic background');
  assert.equal(await reopened.getByLabel('条目内容',{exact:true}).inputValue(),'Browser worldbook fact');
  await reopened.getByLabel('资源所属角色',{exact:true}).selectOption('other');
  await page.waitForFunction(()=>document.querySelectorAll('dialog[open]').length===1);
  await page.getByText('角色：Fixture · other',{exact:true}).waitFor();
  assert.equal(await page.locator('dialog').getByLabel('背景设定',{exact:true}).inputValue(),'');
  report.checks.push('capability_card_reopens_same_editor_and_other_role_isolated');
  await page.unroute('**/api/roles');
  // A hash change alone keeps the intentionally synthetic roster in memory.
  await page.goto(base+'/?real-assets=1#room');
  await page.waitForFunction(()=>document.querySelector('#vrmLive')?.dataset.vrmMounted==='1',{},{timeout:30000});
  assert.equal(await page.locator('#vrmLive').getAttribute('data-vrm-src'),'/api/roles/fixture/asset/model_3d');
  assert.ok(await page.locator('#vrmLive canvas').count());
  await page.screenshot({path:join(output,'real-imported-vrm.png'),fullPage:false});
  report.checks.push('real_imported_vrm_consumed_by_existing_stage_renderer');
  assert.deepEqual(report.pageErrors,[]);report.passed=true;
} catch(error){report.error=error.stack;process.exitCode=1;}
finally{
  if(browser)await browser.close();bridge.stdin.end();
  if(bridge.exitCode===null)await Promise.race([once(bridge,'exit'),new Promise(resolve=>{
    const timer=setTimeout(()=>{bridge.kill();resolve();},10000);timer.unref();
  })]);
  bridge.stdout.destroy();bridge.stderr.destroy();
  report.diagnostics=diagnostics.slice(-2500);
  await writeFile(join(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
}
