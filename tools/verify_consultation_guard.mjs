// Usage: node tools/verify_consultation_guard.mjs <path-to-playwright-package>
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {chromium}=require(process.argv[2] || 'playwright');
const script=await readFile(new URL('../extensions/desktop/consultation_guard.js',import.meta.url),'utf8');
const browser=await chromium.launch({headless:true,channel:'msedge'});
try {
 const page=await browser.newPage();
 await page.route('**/*',r=>r.fulfill({contentType:'text/html',body:'<textarea id="editor"></textarea><button id="send" onclick="window.sent=(window.sent||0)+1">Send</button>'}));
 await page.goto('https://fixture.invalid/');
 const config={origin:'https://fixture.invalid',editor:'#editor',submit:'#send',prompt:'测试原文'};
 const run=(action,extra={})=>page.evaluate(`(${script})(${JSON.stringify({...config,action,...extra})})`);
 assert.equal((await run('inspect')).empty,true);
 assert.equal((await run('fill',{expectedPath:'/changed-thread'})).reason,'thread_changed');
 assert.equal(await page.locator('#editor').inputValue(),'');
 await page.locator('#editor').fill('用户草稿');
 assert.equal((await run('fill')).reason,'draft_present');
 assert.equal(await page.locator('#editor').inputValue(),'用户草稿');
 await page.locator('#editor').fill('');
 assert.equal((await run('fill',{origin:'https://other.invalid'})).reason,'origin_changed');
 assert.equal(await page.locator('#editor').inputValue(),'');
 assert.equal((await run('fill')).filled,true);
 await page.locator('#editor').fill('用户改动');
 assert.equal((await run('submit')).reason,'draft_changed');
 assert.equal(await page.evaluate('window.sent||0'),0);
 await page.locator('#editor').fill(config.prompt);
 await page.locator('#send').evaluate(e=>e.disabled=true);
 assert.equal((await run('ready')).ready,false);
 assert.equal(await page.evaluate('window.sent||0'),0);
 assert.equal((await run('submit')).reason,'submit_disabled');
 await page.locator('#send').evaluate(e=>e.disabled=false);
 assert.equal((await run('ready')).ready,true);
 assert.equal(await page.evaluate('window.sent||0'),0);
 assert.equal((await run('submit')).submitted,true);
 assert.equal(await page.evaluate('window.sent'),1);
 await page.locator('#editor').evaluate(e=>e.outerHTML='<div id="editor" contenteditable="true" style="min-height:40px"><p><br></p></div>');
 assert.equal((await run('inspect')).empty,true);
 assert.equal((await run('fill')).filled,true);
 assert.equal((await run('fill')).reason,'draft_present');
 // A selected file is never submitted as a side effect of a text-only review.
 await page.evaluate(()=>{const input=document.createElement('input');input.type='file';input.id='upload';document.body.append(input);});
 await page.locator('#upload').setInputFiles({name:'fixture.txt',mimeType:'text/plain',buffer:Buffer.from('synthetic fixture only')});
 assert.equal((await run('submit')).reason,'selected_files_present');
 assert.equal(await page.evaluate('window.sent'),1);
 await page.locator('#upload').setInputFiles([]);
 for(const html of ['<p><img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"></p>',
   '<span contenteditable="false">mention</span>','<span data-attachment="file"></span>','<p><a href="https://example.test">link</a></p>']){
  await page.locator('#editor').evaluate((e,html)=>e.innerHTML=html,html);
  assert.equal((await run('fill')).reason,'complex_draft_present');
  assert.equal((await run('submit')).reason,'complex_draft_present');
 }
 assert.equal(await page.evaluate('window.sent'),1);
 // Lexical-style deferred commit: request an edit once, then verify before click.
 await page.locator('#editor').evaluate(e=>e.innerHTML='<p><br></p>');
 await page.evaluate(()=>{window.originalExec=document.execCommand;document.execCommand=(action,_ui,text)=>{if(action==='insertText'){setTimeout(()=>document.querySelector('#editor').textContent=text,150);return true;}return false;};});
 const deferred=await run('fill');assert.equal(deferred.fill_requested,true);assert.equal(deferred.filled,false);
 assert.equal((await run('ready')).ready,false);
 assert.equal((await run('submit')).submitted,undefined);
 await page.waitForTimeout(200);
 assert.equal((await run('ready')).ready,true);
 assert.equal((await run('submit')).submitted,true);
 assert.equal(await page.evaluate('window.sent'),2);
 await page.evaluate(()=>document.execCommand=window.originalExec);
 // Real ChatGPT ProseMirror paragraphs: CSS adds visual blank lines, not text.
 await page.locator('#editor').evaluate(e=>{e.className='ProseMirror';e.innerHTML='<p>first</p><p><br class="ProseMirror-trailingBreak"></p><p>second<br>line<br class="ProseMirror-trailingBreak"></p>';});
 const multiline='first\n\nsecond\nline';
 assert.notEqual(await page.locator('#editor').innerText(),multiline);
 assert.equal((await run('ready',{prompt:multiline})).ready,true);
 assert.equal((await run('submit',{prompt:'first\nsecond\nline'})).reason,'draft_changed');
 assert.equal((await run('submit',{prompt:multiline+' '})).reason,'draft_changed');
 assert.equal(await page.evaluate('window.sent'),2);
 assert.equal((await run('submit',{prompt:multiline})).submitted,true);
 assert.equal(await page.evaluate('window.sent'),3);
 console.log('PASS: existing/changed draft, wrong origin, disabled send, single click, contenteditable; external requests=0');
} finally {await browser.close();}
