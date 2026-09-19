import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)(process.argv[2]);
const script=await readFile('extensions/desktop/consultation_snapshot.js','utf8');
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
 const page=await browser.newPage();
 await page.route('**/*',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}));
 for(const site of ['chatgpt.com','www.kimi.com']){
  await page.goto('https://'+site+'/');
  const gpt=site==='chatgpt.com';
  await page.setContent(gpt?`<div id="prompt-textarea"></div><div data-message-author-role="user" data-message-id="u">review</div><div data-conversation-screenshot-content><div data-message-author-role="assistant" data-message-id="a"><div class="markdown">answer</div></div><button data-testid="copy-turn-action-button">copy</button></div>`:
   `<div class="chat-input-editor"></div><div class="chat-content-list"><div class="chat-content-item chat-content-item-user"><div class="user-content__text">review</div></div><div class="chat-content-item chat-content-item-assistant"><div class="thinking-container"><div class="markdown">private reasoning</div></div><div class="markdown">answer</div><div class="segment-assistant-actions-content"><svg name="Copy"></svg><svg name="Refresh"></svg></div></div></div>`);
  const run=()=>page.evaluate(`(${script})(${JSON.stringify({origin:'https://'+site})})`);
  let s=await run();assert.equal(s.turns.length,2);assert.equal(s.turns[1].text,'answer');assert.equal(s.turns[1].terminal,true);
  if(gpt){
   await page.locator('[data-message-author-role="user"]').evaluate(e=>{
    e.innerHTML='<div data-testid="collapsible-user-message-root"><div data-testid="collapsible-user-message-content" style="white-space:pre-wrap">first\n\nsecond</div><button data-testid="collapsible-user-message-toggle">展开</button></div>';
   });
   assert.equal((await run()).turns[0].text,'first\n\nsecond');
  }
  await page.evaluate(g=>{const b=document.createElement('button');if(g)b.dataset.testid='stop-button';else b.className='stop-button';b.textContent='stop';document.body.append(b);},gpt);
  assert.equal((await run()).generating,true);
  await page.locator(gpt?'[data-testid="copy-turn-action-button"]':'.segment-assistant-actions-content').evaluate(e=>e.remove());
  assert.equal((await run()).turns[1].terminal,false);
  assert.equal((await page.evaluate(`(${script})({origin:'https://wrong.test'})`)).ok,false);
 }
 await page.goto('https://chat.deepseek.com/a/chat/s/test');
 await page.setContent(`<textarea></textarea><div data-virtual-list-item-key="1"><div class="ds-message d29f3d7d">review</div></div><div data-virtual-list-item-key="2"><div class="ds-message"><div class="ds-assistant-message-main-content">answer</div></div>${Array.from({length:6},(_,i)=>`<div role="button" ${i===4?'aria-label="朗读"':''}>control</div>`).join('')}</div>`);
 const ds=()=>page.evaluate(`(${script})({origin:'https://chat.deepseek.com'})`);
 assert.equal((await ds()).turns[1].terminal,true);
 await page.locator('[aria-label="朗读"]').evaluate(e=>e.remove());
 assert.equal((await ds()).turns[1].terminal,false);
 await page.setContent('<textarea></textarea>');
 assert.equal((await ds()).reason,'history_not_loaded');
 console.log('PASS: three site collectors, exact origin, terminal controls, active generation, reasoning excluded. Offline fixture only.');
}finally{await browser.close();}
