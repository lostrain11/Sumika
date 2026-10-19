import {loadPlaywright} from './lib/playwright.mjs';
import {writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const [base,output]=process.argv.slice(2);
if(!base||!output){console.error('usage: node tools/verify_task_handoff_ui.mjs <base-url> <output-dir>');process.exit(2);}
const {chromium}=loadPlaywright();
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage();
const report={passed:false,checks:{},errors:[],responses:[]};
page.on('pageerror',e=>report.errors.push(e.message));
page.on('response',async response=>{
 if(response.url().endsWith('/api/manage/task-draft') && response.request().method()==='POST')
  report.responses.push({request:response.request().postDataJSON(),status:response.status(),body:await response.json()});
});
try{
 await page.goto(base+'/#room');
 await page.getByRole('button',{name:'转到工作台…',exact:true}).click();
 const iframe=page.locator('#sumika-workbench-frame');await iframe.waitFor();
 const frame=await(await iframe.elementHandle()).contentFrame();
 await frame.waitForTimeout(5000);
 if(await frame.getByText('预览版说明',{exact:true}).isVisible())await frame.getByRole('button',{name:'继续',exact:true}).click();
 const onboarding=frame.getByRole('dialog',{name:'开始使用',exact:true});
 if(await onboarding.isVisible())await onboarding.getByRole('button',{name:'关闭',exact:true}).click();
 await frame.getByText('Synthetic acceptance: reply',{exact:false}).first().click();
 await frame.locator('[data-sumika-session-status]').waitFor({state:'attached'});
 const editor=frame.locator('[contenteditable="true"]').first();
 await frame.getByText('请检查验收项目的构建错误',{exact:true}).waitFor();
 const join=frame.getByRole('button',{name:'加入当前会话草稿',exact:true});
 await editor.fill('保留已有验收草稿');
 assert.equal(await join.isDisabled(),true);
 assert.equal(await editor.innerText(),'保留已有验收草稿');
 const pendingDraft=(await(await page.request.get(base+'/api/manage/task-draft')).json()).draft;
 const csrf=(await(await page.request.get(base+'/api/manage/session')).json()).csrf;
 const rejected=await page.request.post(base+'/api/manage/task-draft',{headers:{'X-Sumika-CSRF':csrf},data:{action:'receive',id:pendingDraft.id,workspace_id:'forged-workspace',session_id:'forged-session',projects:[{id:'forged-workspace',name:'Untrusted'}]}});
 assert.equal(rejected.status(),400);
 assert.equal((await(await page.request.get(base+'/api/manage/task-draft')).json()).draft.id,pendingDraft.id);
 report.checks.forged_target_rejected_without_consuming=true;
 report.checks.occupied_composer_preserved=true;
 await editor.fill('');
 const response=page.waitForResponse(r=>r.url().endsWith('/api/manage/task-draft') && r.request().postDataJSON()?.action==='receive');
 await join.click();
 const accepted=await response;
 assert.equal(accepted.status(),200,await accepted.text());
 await editor.filter({hasText:'original_user_text'}).waitFor();
 const envelope=JSON.parse(await editor.innerText());
 assert.equal(envelope.original_user_text,'请检查验收项目的构建错误');
 assert.equal(envelope.verified_project_context.workspace_id,(await accepted.json()).handoff.context.project.id);
 assert.equal(envelope.verified_project_context.session_id,(await accepted.json()).handoff.context.session_id);
 await frame.locator('[data-sumika-role-task]').waitFor({state:'detached'});
 const persisted=await(await page.request.get(base+'/api/manage/task-draft')).json();
 assert.equal(persisted.draft,null);
 report.checks.persisted_user_source_to_native_composer=true;
 report.checks.native_registry_target_verified=true;
 report.checks.consumed_draft_not_offered=true;
 report.checks.explicit_send_not_clicked=true;
 await page.screenshot({path:output+'/handoff-composer.png'});
 await page.getByText('活动室',{exact:true}).first().click();
 await page.getByRole('button',{name:'转到工作台…',exact:true}).click();
 await frame.getByRole('button',{name:'取消交接',exact:true}).click();
 await frame.locator('[data-sumika-role-task]').waitFor({state:'detached'});
 await page.waitForFunction(async()=>!(await(await fetch('/api/manage/task-draft')).json()).draft);
 assert.deepEqual(JSON.parse(await editor.innerText()),envelope);
 report.checks.cancel_dismisses_without_changing_composer=true;
 assert.equal(report.errors.length,0);
 report.passed=true;
}catch(error){report.error=String(error);report.body=(await page.locator('body').innerText()).slice(-1600);await page.screenshot({path:output+'/handoff-failure.png'});throw error;}
finally{await browser.close();await writeFile(output+'/handoff-browser.json',JSON.stringify(report,null,2));}
