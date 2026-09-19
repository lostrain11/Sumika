import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1280,height:720}});
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('console',e=>{if(e.type()==='error')errors.push(e.text().slice(0,150));});
const checks=[];
try{
  // Handoff uses an isolated durable-store substitute; never insert test
  // messages or handoffs into the user's personal conversation database.
  let taskDraft=null;
  await page.route('**/api/manage/task-draft',route=>{
    const data=route.request().postDataJSON();
    if(data?.action==='prepare')taskDraft={id:'ui-test-draft',source_message_id:'ui-test-source',original_user_text:'验收草稿，不执行任何命令'};
    if(data?.action==='dismiss')taskDraft=null;
    return route.fulfill({json:{draft:taskDraft}});
  });
  await page.goto('http://127.0.0.1:8765/#settings');
  await page.locator('[data-section="models"]').waitFor({timeout:30000});
  for(const id of ['startup','models','permissions','data','about','appearance']){
    await page.locator(`[data-section="${id}"]`).click();
    if(!await page.locator(`.set-group[data-settings-section="${id}"]`).isVisible())throw new Error(`section ${id} not visible`);
    checks.push(`settings:${id}`);
  }
  if(await page.locator('[data-section="modules"],[data-settings-section="modules"]').count())throw new Error('duplicate settings capability section');
  await page.locator('#gnav [data-go="shelf"]').click();
  await page.locator('#screen-shelf .cap-card').first().waitFor();
  if(!await page.locator('#screen-shelf').isVisible())throw new Error('canonical capability page missing');
  checks.push('module canonical entry');
  await page.locator('#gnav [data-go="room"]').click();
  for(const act of ['work','rest','idle'])await page.locator(`[data-act="${act}"]`).click();
  checks.push('activity controls');
  // Read-only real scope, no user memory modifications or model calls.
  await page.getByRole('button',{name:'管理角色与记忆',exact:true}).click();
  await page.locator('dialog h3').filter({hasText:'关系'}).waitFor({timeout:60000});
  checks.push('role memory dialog');
  await page.getByRole('button',{name:'导入／恢复角色资源包',exact:true}).click();
  await page.getByLabel('ZIP 文件完整路径').waitFor();
  checks.push('role package import form');
  await page.locator('dialog').getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByRole('button',{name:'管理角色与记忆',exact:true}).click();
  await page.getByRole('button',{name:'管理角色资源',exact:true}).click();
  await page.getByRole('heading',{name:'角色资源',exact:true}).waitFor();
  await page.getByRole('button',{name:'导出角色资源包',exact:true}).waitFor();
  checks.push('role resource controls (read-only inspection)');
  await page.locator('dialog').getByRole('button',{name:'关闭',exact:true}).click();
  // Delay role A so it returns after role B; use synthetic data only.
  await page.route('**/api/roles',route=>route.fulfill({json:{active:{id:'a'},roles:[{id:'a',name:'角色A',complete:true},{id:'b',name:'角色B',complete:true}]}}));
  let releaseA;
  const delayedA=new Promise(resolve=>releaseA=resolve);
  await page.route('**/api/manage/roles/*/memory',async route=>{
    const id=new URL(route.request().url()).pathname.split('/')[4];
    if(id==='a')await delayedA;
    await route.fulfill({json:{scope:{role_id:id,project_id:'test'},revision:id,memories:[{id:1,text:`仅属于${id}`,source:'user'}],relations:[]}});
  });
  await page.route('**/api/manage/roles/*/usage',route=>route.fulfill({json:{groups:[]}}));
  await page.getByRole('button',{name:'管理角色与记忆',exact:true}).click();
  await page.locator('dialog select').selectOption('b');
  await page.locator('dialog').getByText('仅属于b',{exact:true}).waitFor();
  releaseA();
  await page.waitForTimeout(200);
  if(await page.locator('dialog').getByText('仅属于a',{exact:true}).count())throw new Error('stale role response replaced selected scope');
  checks.push('out-of-order role selection');
  await page.locator('dialog').getByRole('button',{name:'关闭',exact:true}).click();
  await page.locator('#gnav [data-go="shelf"]').click();
  await page.getByRole('button',{name:'管理模块',exact:true}).click();
  await page.locator('[data-module-manager]').waitFor();
  checks.push('module manager');
  await page.locator('dialog').getByRole('button',{name:'关闭',exact:true}).click();
  await page.locator('.cap-card').filter({hasText:'定时任务'}).click();
  await page.getByRole('button',{name:'管理定时任务',exact:true}).click();
  await page.locator('dialog').getByRole('button',{name:'新建任务',exact:true}).click();
  await page.locator('dialog form').waitFor();checks.push('schedule form');
  await page.locator('dialog').getByRole('button',{name:'关闭',exact:true}).click();
  await page.locator('#gnav [data-go="board"]').click();
  await page.locator('#sumika-workbench-frame').waitFor({timeout:120000});
  const frame=page.frames().find(f=>f.url().includes(':5175'));
  await frame.locator('[data-sumika-enhancement]').waitFor({timeout:20000});
  checks.push('native enhancement slot');
  // Exercise persistence without changing the user's final setting.
  const enhancement=frame.locator('[data-sumika-enhancement]');
  if(await enhancement.getAttribute('aria-disabled')!=='true')throw new Error('planned optimization is active');
  if(!await enhancement.evaluate(e=>!!e.closest('[data-slot="conversation.input.right"]')))throw new Error('optimization outside toolbar');
  checks.push('optimization toolbar reserved, unavailable');
  const editor=frame.locator('[contenteditable="true"]').first();
  const original=await editor.innerText();
  if(!original.trim()) {
    await frame.evaluate(()=>window.dispatchEvent(new MessageEvent('message',{
      source:window.parent,origin:'https://untrusted.example',data:{type:'sumika:task-draft',
        draft:{id:'spoof',source_message_id:'spoof',original_user_text:'not a trusted handoff'}},
    })));
    if(await frame.locator('[data-sumika-role-task]').count())throw new Error('untrusted handoff accepted');
    checks.push('foreign-origin handoff rejected');
    // Synthetic source text only; no model call or private-message artifact.
    await page.evaluate(()=>window.dispatchEvent(new CustomEvent('sumika:prepare-task',{
      detail:{text:'验收草稿，不执行任何命令',sourceMessageId:'ui-test-source'},
    })));
    await frame.locator('[data-sumika-role-task]').waitFor();
    await editor.fill('已有草稿');
    if(!await frame.getByRole('button',{name:'加入当前会话草稿'}).isDisabled())throw new Error('handoff would overwrite a draft');
    await editor.fill('');
    const accept=frame.getByRole('button',{name:'加入当前会话草稿'});
    if(await accept.isEnabled()){
      await accept.click();
      await frame.waitForFunction(()=>document.querySelector('[contenteditable="true"]')?.innerText.includes('original_user_text'));
      const received=JSON.parse(await editor.innerText());
      if(received.original_user_text!=='验收草稿，不执行任何命令' || received.source_message_id!=='ui-test-source'
        || !received.verified_project_context.session_id)throw new Error('handoff lost source or target');
      await editor.fill('');checks.push('manual handoff: native target and preserved original');
    }else{
      await frame.getByRole('button',{name:'取消交接'}).click();
      checks.push('manual handoff: unknown workspace blocked');
    }
  }
  const recovery=await browser.newPage({viewport:{width:1280,height:720}});
  try {
    await recovery.route('**/api/workbench',route=>route.fulfill({json:{running:true,embed_ready:false}}));
    await recovery.goto('http://127.0.0.1:8765/#board');
    await recovery.locator('#screen-board').getByRole('button',{name:'重试',exact:true}).waitFor();
    if(await recovery.locator('#sumika-workbench-frame').count())throw new Error('unready harness still mounted');
    await recovery.locator('#gnav [data-go="settings"]').click();
    await recovery.locator('[data-section="models"]').waitFor();
    await recovery.unroute('**/api/workbench');
    await recovery.locator('#gnav [data-go="board"]').click();
    await recovery.locator('#sumika-workbench-frame').waitFor({timeout:60000});
    checks.push('unready harness isolation and recovery');
  }finally{await recovery.close();}
}catch(error){errors.push(String(error.message).replace(/(https?:\/\/[^\s?]+)\?[^\s]*/g,'$1?[redacted]'));}
finally{await browser.close();}
const result={checks,errors,status:errors.length?'failed':'passed'};
await writeFile('.sumika-next/evidence/ui-v2/management-audit.json',JSON.stringify(result,null,2));
console.log(JSON.stringify(result,null,2));process.exitCode=errors.length?1:0;
