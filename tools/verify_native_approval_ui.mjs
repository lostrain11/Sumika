// Browser half of the isolated real-host approval acceptance. Auth arrives on stdin.
import { createRequire } from 'node:module';
import { readdirSync, existsSync } from 'node:fs';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const config = JSON.parse(input);
const runtimes = path.join(process.env.LOCALAPPDATA, 'OpenAI/Codex/runtimes/cua_node');
const candidate = readdirSync(runtimes).map(name => path.join(runtimes, name, 'bin/node_modules/playwright/package.json'))
  .find(file => existsSync(file));
if (!candidate) throw new Error('Installed Playwright unavailable');
const { chromium } = createRequire(candidate)('playwright');
const browser = await chromium.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const report = { passed: false, decision: config.decision };
page.on('pageerror',error=>{
  (report.browserErrors??=[]).push(error.message.replace(/https?:\/\/\S+/g,'[url]').slice(0,600));
});
try {
  await page.goto(config.url, { waitUntil: 'domcontentloaded' });
  if(config.shell){
    await page.waitForFunction(()=>document.querySelector('.proto')?.textContent==='本地服务已连接');
    report.unconfiguredRoleDoesNotMaskBridgeConnection=true;
  }
  let ui=page;
  async function surface(){
    if(!config.shell)return page;
    const iframe=page.locator('#sumika-workbench-frame');
    await iframe.waitFor({state:'visible',timeout:30000});
    const frame=await (await iframe.elementHandle()).contentFrame();
    await frame.waitForURL(url=>url.protocol==='http:' && url.port!==new URL(config.url).port);
    return frame;
  }
  report.stage='locate-workbench';ui=await surface();
  report.stage='open-native-session';
  for (let i = 0; i < 30; i++) {
    const notice = ui.getByRole('button', { name: /^(继续|Continue)$/ });
    if (await notice.first().isVisible()) await notice.first().click();
    const later = ui.getByRole('button', { name: /^(稍后配置|Later|Skip|Configure later)$/i });
    if (await later.first().isVisible()) await later.first().click();
    const session = ui.getByText(config.title, { exact: true }).first();
    if (await session.isVisible()) {
      try { await session.click({ timeout: 1000 }); break; }
      catch { /* First-run overlay can appear after the visibility check. */ }
    }
    // The native project tree can start collapsed.
    const project = ui.getByText('approval-ui-project', { exact: true }).first();
    if (await project.isVisible()) await project.click({timeout:1000}).catch(()=>{});
    await page.waitForTimeout(500);
  }
  if(config.mode==='attachment-send'){
    report.stage='project-switch-draft';
    const draft='LOCAL_ATTACHMENT_SUBMISSION 中文附件验收，保持原文。';
    const editor=ui.locator('[data-composer-input]').first();
    await editor.fill(draft);
    const other=ui.getByText('attachment-second-project',{exact:true}).first();
    const otherSession=ui.getByText('Other project session',{exact:true}).first();
    const projectRow=ui.getByRole('treeitem').filter({has:other});
    for(let i=0;i<10 && !await otherSession.isVisible();i++){
      if(await projectRow.getAttribute('aria-expanded')==='false')await other.click();
      await page.waitForTimeout(300);
    }
    report.stage='project-switch-open-session';
    await otherSession.click();
    if((await editor.innerText()).includes(draft))throw Error('draft leaked into another project');
    await ui.getByText(config.title,{exact:true}).first().click();
    if(await editor.innerText()!==draft)throw Error('project switch lost draft');
    report.projectSwitchDraftIsolated=true;
    const stageAttachment=async()=>{
      await ui.locator('[data-composer-card] input[type="file"][multiple]').setInputFiles({
        name:'submitted-note.txt',mimeType:'text/plain',buffer:Buffer.from(config.payload,'utf8'),
      });
      await ui.locator('[data-composer-card] [title="submitted-note.txt"]').getByText(/^TXT /).waitFor({state:'visible'});
    };
    await stageAttachment();
    report.stage='draft-reload';
    // Native draft storage is debounced; wait for persisted text before reloading.
    await ui.waitForFunction(text=>Object.keys(localStorage).some(k=>k.startsWith('dsh.conversation.') && localStorage.getItem(k).includes(text)),draft);
    await page.reload({waitUntil:'domcontentloaded'});
    ui=await surface();
    await ui.getByText(config.title,{exact:true}).first().click();
    const restored=ui.locator('[data-composer-input]').first();
    await restored.waitFor({state:'visible'});
    if(await restored.innerText()!==draft)throw Error('reload lost persisted draft');
    report.textDraftRestoredAfterReload=true;
    report.unsentAttachmentRestoredAfterReload=await ui.locator('[data-composer-card] [title="submitted-note.txt"]').count()>0;
    if(!report.unsentAttachmentRestoredAfterReload)await stageAttachment();
    report.stage='attachment-submit';
    const count=await ui.getByText('P2_FIXTURE_DONE',{exact:true}).count();
    await ui.getByRole('button',{name:'发送消息',exact:true}).click();
    await ui.waitForFunction(n=>Array.from(document.querySelectorAll('*')).filter(e=>e.children.length===0 && e.textContent==='P2_FIXTURE_DONE').length>n,count);
    await ui.getByText('submitted-note.txt',{exact:true}).first().waitFor({state:'visible'});
    report.attachmentSubmittedOnce=true;
    report.stage='sent-attachment-reload';
    await page.reload({waitUntil:'domcontentloaded'});
    ui=await surface();
    await ui.getByText(config.title,{exact:true}).first().click();
    await ui.getByText('submitted-note.txt',{exact:true}).first().waitFor({state:'visible'});
    report.sentAttachmentRestoredAfterReload=true;
  }else{
  const label = config.decision === 'reject' ? /^(拒绝|Reject)$/ : /^(允许一次|Allow once)$/;
  const button = ui.getByRole('button', { name: label }).first();
  report.stage='await-approval';
  await button.waitFor({ state: 'visible', timeout: 20000 });
  report.button = await button.innerText();
  if(config.shell){
    await ui.evaluate(()=>window.__sumikaAcceptanceIdentity=crypto.randomUUID());
    const before=await ui.evaluate(()=>window.__sumikaAcceptanceIdentity);
    await page.locator('#gnav [data-go="room"]').click();
    await page.locator('#gnav [data-go="board"]').click();
    {
      const after=await (await surface()).evaluate(()=>window.__sumikaAcceptanceIdentity);
      if(after!==before)throw Error('switching pages recreated workbench');
    }
    await button.waitFor({state:'visible'});
    report.shellPageSwitchPreservedWorkbench=true;
  }
  report.stage='answer-or-cancel';
  await page.screenshot({ path: path.join(config.directory, 'before.png'), fullPage: true });
  if (config.decision === 'cancel') {
    await writeFile(path.join(config.directory, 'ready.json'), JSON.stringify({ approvalVisible: true }));
  } else {
    await button.click();
  }
  await button.waitFor({ state: 'hidden', timeout: 15000 });
  if (config.decision === 'cancel') {
    await page.reload({ waitUntil: 'domcontentloaded' });
    ui=await surface();
    await ui.getByText(config.title, { exact: true }).first().click();
    await page.waitForTimeout(1000);
    if (await ui.getByRole('button', { name: /^(允许一次|Allow once)$/ }).count()) {
      throw new Error('Cancelled approval reappeared');
    }
    report.cancelledApprovalAbsentAfterReload = true;
  }
  if(config.shell && config.decision==='allow'){
    report.stage='composer-draft-page-switch';
    const editor=ui.locator('[contenteditable="true"]').first();
    const draft='未发送的验收草稿：保留原文、标点与代码 `x = 1`。';
    await editor.fill(draft);
    await page.locator('#gnav [data-go="room"]').click();
    await page.locator('#gnav [data-go="board"]').click();
    if(await editor.innerText()!==draft)throw Error('draft changed on shell navigation');
    report.draftPreservedAcrossShellPages=true;
    report.stage='composer-draft-session-switch';
    await ui.getByText('Approval UI reject',{exact:true}).first().click();
    if((await ui.locator('[contenteditable="true"]').first().innerText()).includes(draft))throw Error('draft leaked into another session');
    await ui.getByText(config.title,{exact:true}).first().click();
    if(await editor.innerText()!==draft)throw Error('draft lost on session switch');
    report.draftIsolatedAndRestoredAcrossSessions=true;
    report.stage='native-trace';
    await ui.getByText('轨迹',{exact:true}).click();
    await page.screenshot({path:path.join(config.directory,'trace.png'),fullPage:true});
    await ui.getByText('对话',{exact:true}).click();
    if(await editor.innerText()!==draft)throw Error('draft lost switching trace');
    report.traceNavigationPreservedDraft=true;
    report.stage='native-usage';
    await ui.getByRole('button',{name:/^用量 /}).click();
    await ui.getByText('本轮用量',{exact:true}).waitFor({state:'visible'});
    await page.screenshot({path:path.join(config.directory,'usage.png'),fullPage:true});
    await page.keyboard.press('Escape');
    report.usageControlOpened=true;
    await ui.locator('[data-composer-stats]').getByRole('button',{name:/^[\d,.]+ tok(?: ·|$)/}).click();
    await ui.locator('[data-session-stats-usage]').waitFor({state:'visible'});
    report.sessionUsageOpened=true;
    await page.keyboard.press('Escape');
    report.stage='native-attachment-draft';
    const attachment='acceptance-note.txt';
    await ui.locator('[data-composer-card] input[type="file"][multiple]').setInputFiles({
      name:attachment,mimeType:'text/plain',buffer:Buffer.from('LOCAL_ONLY attachment draft; never submitted.','utf8'),
    });
    const chip=ui.locator('[data-composer-card]').getByText(attachment,{exact:true});
    await chip.waitFor({state:'visible'});
    await ui.locator('[data-composer-card] [title="acceptance-note.txt"]').getByText(/^TXT /).waitFor({state:'visible'});
    await page.locator('#gnav [data-go="room"]').click();
    await page.locator('#gnav [data-go="board"]').click();
    await chip.waitFor({state:'visible'});
    await ui.getByText('Approval UI reject',{exact:true}).first().click();
    if(await ui.locator('[data-composer-card]').getByText(attachment,{exact:true}).count())throw Error('attachment leaked across sessions');
    await ui.getByText(config.title,{exact:true}).first().click();
    await chip.waitFor({state:'visible'});
    if(await editor.innerText()!==draft)throw Error('attachment staging changed draft');
    report.attachmentDraftPreservedAndSessionIsolated=true;
    report.attachmentBoundary='Local draft staging only; not submitted to model.';
    await page.screenshot({path:path.join(config.directory,'attachment-draft.png'),fullPage:true});
    report.stage='native-tool-details';
    await ui.getByRole('button',{name:'1 次工具调用',exact:true}).click();
    await page.screenshot({path:path.join(config.directory,'tool-summary.png'),fullPage:true});
    report.toolSummaryExpanded=true;
    await ui.getByRole('tab',{name:'轨迹',exact:true}).click();
    await ui.locator('tr[data-kind="tool"][data-record-index]').filter({hasText:'web_review_submit'}).first().click();
    const detail=ui.locator('aside[aria-label="事件详情"]');
    await detail.waitFor({state:'visible'});
    await detail.getByRole('tab',{name:'参数',exact:true}).click();
    if(!(await detail.locator('#trajectory-detail-panel').innerText()).includes('LOCAL_ONLY approval acceptance'))throw Error('tool input not shown');
    await detail.getByRole('tab',{name:'结果',exact:true}).click();
    if(!(await detail.locator('#trajectory-detail-panel').innerText()).includes('LOCAL_ONLY'))throw Error('tool result not shown');
    await page.screenshot({path:path.join(config.directory,'tool-result.png'),fullPage:true});
    await detail.getByRole('button',{name:'关闭详情',exact:true}).click();
    await detail.waitFor({state:'hidden'});
    report.toolInputAndResultInspected=true;
  }
  }
  await page.screenshot({ path: path.join(config.directory, 'after.png'), fullPage: true });
  report.passed = true;
} catch (error) {
  // Do not persist URL, credentials or arbitrary browser error strings.
  report.failure = 'native_approval_ui_not_completed';
  report.errorKind=error.name;
  report.errorSummary=error.message.replace(/https?:\/\/\S+/g,'[url]').slice(0,600);
  await writeFile(path.join(config.directory, 'visible-text.txt'), await page.locator('body').innerText());
  await page.screenshot({ path: path.join(config.directory, 'failure.png'), fullPage: true });
  process.exitCode = 1;
} finally {
  await writeFile(path.join(config.directory, 'browser.json'), JSON.stringify(report, null, 2));
  await browser.close();
}
