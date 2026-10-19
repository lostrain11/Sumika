// Existing Sumika dialog -> real Bridge -> native commands, synthetic tasks only.
import {loadPlaywright} from './lib/playwright.mjs';
import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import assert from 'node:assert/strict';
let input='';for await(const part of process.stdin)input+=part;
const {base,output,workspace,session}=JSON.parse(input);
const {chromium}=loadPlaywright();
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1400,height:980}});
const report={passed:false,pageErrors:[],checks:[]};
page.on('pageerror',e=>report.pageErrors.push(e.message));
try{
  await page.goto(base+'/#board');
  const native=page.frameLocator('#sumika-workbench-frame');
  await native.locator('[data-sumika-native-layout-ready]').waitFor({state:'attached'});
  if(await native.getByText('预览版说明',{exact:true}).isVisible().catch(()=>false))await native.getByRole('button',{name:'继续',exact:true}).click();
  for(const name of ['稍后配置','Later','Skip'])if(await native.getByRole('button',{name,exact:true}).isVisible().catch(()=>false)){await native.getByRole('button',{name,exact:true}).click();break;}
  const onboarding=native.getByRole('dialog',{name:'开始使用',exact:true});
  if(await onboarding.isVisible().catch(()=>false))await onboarding.getByRole('button',{name:'关闭',exact:true}).click();
  await page.evaluate(()=>location.hash='shelf');
  await page.getByRole('button',{name:'管理模块',exact:true}).waitFor();
  await page.locator('.cap-card').filter({hasText:'就绪检查 schedule'}).click();
  await page.getByRole('button',{name:'管理定时任务',exact:true}).click();
  const modal=page.locator('dialog.sumika-dialog');
  await modal.getByRole('button',{name:'新建任务',exact:true}).click();
  await modal.getByLabel('任务内容',{exact:true}).fill('BROWSER_SYNTHETIC_DAILY');
  await modal.getByLabel('类型',{exact:true}).selectOption('execute');
  await modal.getByLabel('目标项目',{exact:true}).selectOption(workspace);
  await modal.getByLabel('目标会话',{exact:true}).selectOption(session);
  await modal.getByLabel('时区',{exact:true}).fill('Asia/Shanghai');
  const create=modal.getByRole('button',{name:'确认并创建原生任务',exact:true});
  let admissions=0;page.on('request',r=>{if(r.url().endsWith('/api/manage/schedules/native-create'))admissions++;});
  page.once('dialog',d=>d.dismiss());await create.click();assert.equal(admissions,0);
  report.checks.push('cancel_confirmation_does_not_dispatch');
  page.once('dialog',d=>d.accept());await create.click();
  await modal.getByText(/已创建原生任务/).waitFor();
  assert.equal(admissions,1);assert.equal(await create.isDisabled(),true);
  const state=await page.evaluate(async()=>await(await fetch('/api/manage/schedules')).json());
  assert.equal(state.definitions.length,0);
  report.checks.push('confirmed_explicit_target_creates_native_only_and_locks_form');
  await page.screenshot({path:join(output,'schedule-create.png'),animations:'disabled'});
  await modal.getByRole('button',{name:'新建任务',exact:true}).click();
  await modal.getByLabel('任务内容',{exact:true}).fill('BROWSER_SYNTHETIC_UNKNOWN');
  await modal.getByLabel('类型',{exact:true}).selectOption('execute');
  await modal.getByLabel('目标项目',{exact:true}).selectOption(workspace);
  await modal.getByLabel('目标会话',{exact:true}).selectOption(session);
  await modal.getByLabel('时区',{exact:true}).fill('Asia/Shanghai');
  let persistedId;
  const cutResponse=async route=>{
    // Native persistence succeeds; only the browser's response is lost.
    const response=await route.fetch();const result=await response.json();
    assert.equal(result.state,'created');persistedId=result.record.id;
    await route.abort('connectionreset');
  };
  await page.route('**/api/manage/schedules/native-create',cutResponse);
  page.once('dialog',d=>d.accept());await create.click();
  await modal.getByText(/未确认创建结果/).waitFor();
  assert.ok(persistedId);assert.equal(await create.isDisabled(),true);
  assert.equal(admissions,2);
  await page.unroute('**/api/manage/schedules/native-create',cutResponse);
  report.checks.push('response_lost_after_real_persistence_is_unknown_and_not_retried');
  await modal.getByRole('button',{name:'打开原生自动化任务',exact:true}).click();
  await modal.waitFor({state:'detached'});
  await native.getByRole('heading',{name:'自动化任务',exact:true}).waitFor();
  await native.getByText('BROWSER_SYNTHETIC_DAILY',{exact:true}).waitFor();
  await native.getByText('BROWSER_SYNTHETIC_UNKNOWN',{exact:true}).waitFor();
  report.checks.push('origin_checked_bridge_opens_existing_native_manager');
  await page.screenshot({path:join(output,'schedule-native-manager.png'),animations:'disabled'});
  assert.deepEqual(report.pageErrors,[]);report.passed=true;
}catch(error){report.error=String(error.stack||error);process.exitCode=1;
  await writeFile(join(output,'browser-failed.txt'),await page.locator('body').innerText());
  await page.screenshot({path:join(output,'browser-failed.png')});
}finally{
  await writeFile(join(output,'browser-report.json'),JSON.stringify(report,null,2));
  await browser.close();console.log(JSON.stringify(report));
}
