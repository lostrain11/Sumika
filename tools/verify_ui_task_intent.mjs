import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire('C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/6f12e0ef1c6e5061/bin/node_modules/');
const {chromium}=require('playwright');
const cases=[
  ['昴，你吃了没',false],['Sumika 项目最近怎么样？',false],
  ['你觉得这个项目应该怎么优化？',false],['如果让你修复这个bug，你会怎么做？',false],
  ['不要修改Sumika的设置',false],['先不实现这个功能',false],
  ['“帮我修复 Sumika 登录故障”这句话是什么意思？',false],
  ['把刚才这个做掉',false],['继续',false],['检查一下',false],
  ['修复这个',false],['以后帮我优化登录页面',false],['更新项目了吗？',false],
  ['帮我修复 Sumika 登录按钮失效的问题',true],
  ['请检查 Sumika 的构建错误',true],['能不能帮我实现网页翻译功能？',true],
  ['把工作区改成项目',true],['帮我把设置页面改成深色',true],
  ['请生成一份项目测试报告',true],['我吃过了。帮我排查登录失败的问题。',true],
];
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1280,height:720}});
const checks=[],errors=[];let modelRequests=0;
try{
  let persistedDraft=null;
  await page.route('**/api/manage/task-draft',route=>{
    const payload=route.request().postDataJSON();
    if(payload?.action==='prepare'){
      const index=Number(payload.source_message_id.replace('fixture-',''));
      persistedDraft={id:'fixture-draft',source_message_id:payload.source_message_id,original_user_text:cases[index][0]};
    } else if(payload?.action==='dismiss')persistedDraft=null;
    return route.fulfill({json:{draft:persistedDraft}});
  });
  await page.route('**/api/role/chat',route=>{modelRequests++;return route.abort();});
  await page.route('**/api/role/chat/history?*',route=>route.fulfill({json:{messages:[
    ...cases.map(([text],i)=>({id:`fixture-${i}`,who:'me',text,at:'2026-09-12T10:00:00',task_intent:{kind:'task',confidence:'high',evidence:text}})),
    ...[null,{kind:'task',confidence:'low',evidence:cases[13][0]},
      {kind:'discussion',confidence:'high',evidence:cases[13][0]},
      {kind:'task',confidence:'high',evidence:'模型编造的请求'}].map(task_intent=>({who:'me',text:cases[13][0],task_intent})),
  ]}}));
  await page.goto('http://127.0.0.1:8765/#room');
  await page.locator('#screen-room .chat-msgs .cm').first().waitFor({timeout:30000});
  const results=await page.evaluate(async cases=>{
    const {hasExplicitTaskIntent}=await import('/app/task-intent.js');
    return cases.map(([text])=>hasExplicitTaskIntent(text));
  },cases);
  for(let i=0;i<cases.length;i++){
    const [text,expected]=cases[i];
    if(results[i]!==expected)throw new Error(`intent mismatch: ${text}`);
    const row=page.locator('#screen-room .chat-msgs .cm').nth(i);
    if(await row.getByRole('button',{name:'转到工作台…',exact:true}).count()!==Number(expected))throw new Error(`render mismatch: ${text}`);
  }
  checks.push(`${cases.length} task/discussion/negation/quote cases and rendered buttons`);
  for(let i=cases.length;i<cases.length+4;i++){
    if(await page.locator('#screen-room .chat-msgs .cm').nth(i).getByRole('button').count())throw new Error('unreliable metadata displayed task entry');
  }
  checks.push('missing, low confidence, discussion and invented evidence suppress task entry');
  if(!page.url().endsWith('#room'))throw new Error('automatically navigated');
  await page.evaluate(()=>window.addEventListener('sumika:prepare-task',e=>window.__taskEvidence=e.detail));
  const task=page.locator('#screen-room .chat-msgs .cm').nth(13);
  await task.getByRole('button',{name:'转到工作台…',exact:true}).click();
  await page.waitForURL('**/#board');
  const detail=await page.evaluate(()=>window.__taskEvidence);
  if(detail?.text!==cases[13][0]||!detail.sourceMessageId)throw new Error('original message lost');
  checks.push('explicit click keeps original text and opens workbench; no automatic dispatch');
  if(modelRequests)throw new Error('unexpected model request');
}catch(error){errors.push(error.message);}
finally{await browser.close();}
const result={checks,errors,status:errors.length?'failed':'passed',modelRequests,limits:'Local conservative display heuristic, not semantic intent certainty or task authorization. History is an isolated browser fixture.'};
await writeFile('.sumika-next/evidence/ui-v2/task-intent.json',JSON.stringify(result,null,2));
console.log(JSON.stringify(result,null,2));process.exitCode=errors.length?1:0;
