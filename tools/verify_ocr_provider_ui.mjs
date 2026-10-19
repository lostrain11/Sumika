// Existing module dialog against real isolated Bridge/SQLite; no device access.
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output=resolve(process.argv[2]||'.sumika-next/acceptance-20261018/ocr-provider-ui');
await mkdir(output,{recursive:true});
const data=await mkdtemp(join(output,'isolated-'));
const candidate=resolve(process.env.SUMIKA_TEST_CANDIDATE||'.');
const bridge=spawn(process.env.SUMIKA_TEST_PYTHON||'python',['-u','-X','utf8','-B','-c',`
import sys,json,threading
from pathlib import Path
from extensions.models.settings import example,save
from extensions.roles.roles import import_card
from extensions.capabilities import CapabilityStore
from ui.server import serve
data=Path(sys.argv[1]);product=Path.cwd()
card=data/'card.json'
card.write_text(json.dumps({'spec':'chara_card_v2','data':{'name':'Fixture','description':'Synthetic test'}}),encoding='utf8')
role=import_card(card,data/'roles','fixture')
save(example(role,data/'memory.sqlite3'),data/'settings.json')
server=serve(data/'settings.json',port=0,workbench_root=product,capability_database=data/'capabilities.sqlite3',schedule_directory=data/'schedules')
store=CapabilityStore(data/'capabilities.sqlite3')
store.configure('ocr','windows',enabled=False,options={'fixture_marker':'preserve_same_provider'})
store.close()
threading.Thread(target=server.serve_forever,daemon=True).start()
print(json.dumps({'port':server.server_port}),flush=True)
try: sys.stdin.read()
finally: server.shutdown();server.server_close()
`,data],{cwd:candidate,stdio:['pipe','pipe','pipe']});
let diagnostics='';bridge.stderr.on('data',chunk=>diagnostics+=chunk);
const report={passed:false,candidate,checks:[],pageErrors:[],external_calls:0,device_capture:false};
let browser;
try{
  const lines=createInterface({input:bridge.stdout});
  const [line]=await Promise.race([once(lines,'line'),new Promise((_,reject)=>{
    const timer=setTimeout(()=>reject(Error('Bridge start timeout: '+diagnostics.slice(-2000))),25000);timer.unref();
  })]);
  const base='http://127.0.0.1:'+JSON.parse(line).port;
  const {chromium}=loadPlaywright();browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  page.on('pageerror',e=>report.pageErrors.push(e.message));
  await page.goto(base+'/#shelf');
  await page.getByRole('button',{name:'管理模块',exact:true}).click();
  const modal=page.locator('dialog');
  const row=()=>modal.locator('.sumika-record').filter({has:page.locator('p').filter({hasText:/^ocr · /})});
  await row().getByLabel('实现',{exact:true}).waitFor();
  const providers=await row().getByLabel('实现',{exact:true}).locator('option').evaluateAll(items=>items.map(i=>i.value));
  assert.ok(providers.includes('windows'));report.providers=providers;
  report.checks.push('windows_provider_in_existing_module_dialog');
  const read=()=>page.evaluate(async()=>await(await fetch('/api/manage/modules')).json());
  assert.equal((await read()).modules.find(m=>m.id==='ocr').enabled,false);
  await row().getByLabel('实现',{exact:true}).selectOption('windows');
  let saved=page.waitForResponse(r=>r.url().endsWith('/api/manage/modules/configure')&&r.request().method()==='POST');
  await row().getByRole('button',{name:'应用实现',exact:true}).click();await saved;
  let item=(await read()).modules.find(m=>m.id==='ocr');
  assert.equal(item.enabled,false);assert.equal(item.options.fixture_marker,'preserve_same_provider');
  report.checks.push('same_provider_preserves_disabled_and_options');
  const alternative=providers.find(p=>p!=='windows');
  if(alternative){
    await row().getByLabel('实现',{exact:true}).selectOption(alternative);
    saved=page.waitForResponse(r=>r.url().endsWith('/api/manage/modules/configure')&&r.request().method()==='POST');
    await row().getByRole('button',{name:'应用实现',exact:true}).click();await saved;
    item=(await read()).modules.find(m=>m.id==='ocr');
    assert.equal(item.provider,alternative);assert.equal(item.enabled,false);assert.deepEqual(item.options,{});
    report.checks.push('real_alternative_switch_preserves_disabled_and_uses_provider_options');
  }
  await page.reload();
  await page.getByRole('button',{name:'管理模块',exact:true}).click();
  await row().getByLabel('实现',{exact:true}).waitFor();
  assert.equal(await row().getByLabel('实现',{exact:true}).inputValue(),alternative||'windows');
  report.checks.push('refresh_preserves_selected_provider');
  const beforeOrder=(await read()).modules.map(m=>m.id);
  const index=beforeOrder.indexOf('ocr');
  const move=index>0?'上移':'下移',offset=index>0?-1:1;
  assert.ok(beforeOrder.length>1);
  let response=page.waitForResponse(r=>r.url().endsWith('/api/manage/modules/reorder')&&r.request().method()==='POST');
  await row().getByRole('button',{name:move,exact:true}).click();
  assert.equal((await response).status(),200);
  const expected=[...beforeOrder];[expected[index],expected[index+offset]]=[expected[index+offset],expected[index]];
  assert.deepEqual((await read()).modules.map(m=>m.id),expected);
  report.checks.push('ui_module_reorder_persists_exact_order');
  page.once('dialog',d=>d.dismiss());
  await row().getByRole('button',{name:'移除',exact:true}).click();
  assert.ok((await read()).modules.some(m=>m.id==='ocr'));
  report.checks.push('ui_module_remove_cancel_preserves_registration');
  response=page.waitForResponse(r=>r.url().endsWith('/api/manage/modules/remove')&&r.request().method()==='POST');
  page.once('dialog',d=>d.accept());
  await row().getByRole('button',{name:'移除',exact:true}).click();
  assert.equal((await response).status(),200);
  await row().waitFor({state:'detached'});
  let registry=await read();
  assert.ok(!registry.modules.some(m=>m.id==='ocr'));assert.ok(registry.removed.includes('ocr'));
  await page.reload();
  await page.getByRole('button',{name:'管理模块',exact:true}).click();
  assert.ok(!(await read()).modules.some(m=>m.id==='ocr'));
  report.checks.push('ui_module_remove_and_refresh_do_not_bootstrap_it_back');
  const add=modal.getByRole('button',{name:'添加 ocr（windows）',exact:true});
  await add.waitFor();
  response=page.waitForResponse(r=>r.url().endsWith('/api/manage/modules/add')&&r.request().method()==='POST');
  await add.click();assert.equal((await response).status(),200);
  await row().getByLabel('实现',{exact:true}).waitFor();
  registry=await read();item=registry.modules.find(m=>m.id==='ocr');
  assert.equal(item.provider,'windows');assert.equal(item.enabled,false);
  assert.ok(!registry.removed.includes('ocr'));
  report.checks.push('ui_module_readd_uses_existing_provider_and_stays_disabled');
  await page.screenshot({path:join(output,'modules.png')});
  assert.deepEqual(report.pageErrors,[]);report.passed=true;
}catch(error){report.error=String(error.stack||error);process.exitCode=1;}
finally{
  await browser?.close();bridge.stdin.end();
  if(bridge.exitCode===null)await Promise.race([once(bridge,'exit'),new Promise(resolve=>{
    const timer=setTimeout(()=>{bridge.kill();resolve();},10000);timer.unref();
  })]);
  report.bridge_diagnostics=diagnostics.slice(-2000);
  await writeFile(join(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}
