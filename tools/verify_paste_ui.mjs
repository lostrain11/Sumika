// P16: verify PDF paste fallback UI in companion detail.
// Isolated bridge plus stubbed ask stream: real UI send path, zero model/capture calls.
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output = resolve(process.argv[2] || 'E:/SumikaBuild/p16-paste-ui');
const candidate = process.argv[3] ? resolve(process.argv[3]) : null;
await mkdir(output, {recursive: true});
const bridgeData = await mkdtemp(join(output, 'isolated-'));
const report = {passed: false, checks: {}, phases: [], runtime_root: candidate || resolve('.'),
  scope: 'Real bridge/UI, stubbed ask stream; no device capture or model quality claim'};
const log = (message) => {
  report.phases.push({at: new Date().toISOString(), message: message});
  console.log('[paste-ui]', message);
};

const bridgeCode = `
import sys, threading, json
from pathlib import Path
data = Path(sys.argv[1])
from extensions.models.settings import example, save
config = example(data/'role', data/'sumika.db')
config['enabled'] = True
save(config, data/'settings.json')
from extensions.capabilities import CapabilityStore
store = CapabilityStore(data/'capabilities.sqlite3')
store.configure('memory', 'embedded', options={})
store.close()
from ui.server import serve
server = serve(data/'settings.json', port=0, workbench_root=data,
               capability_database=data/'capabilities.sqlite3')
threading.Thread(target=server.serve_forever, daemon=True).start()
print(json.dumps({'port': server.server_port}), flush=True)
try: sys.stdin.read()
finally: server.shutdown(); server.server_close()
`;

const bridge = spawn(candidate ? join(candidate,'runtime/python/python.exe') : 'python', ['-u', '-X', 'utf8', '-B', '-c', bridgeCode,
  bridgeData],
  {cwd: candidate || resolve('.'), stdio: ['pipe', 'pipe', 'pipe'],
   env: {...process.env}});

const lines = createInterface({input: bridge.stdout});
const ready = await Promise.race([
  once(lines, 'line').then(([line]) => JSON.parse(line)),
  new Promise((_, reject) => {
    const timer = setTimeout(() => reject(new Error('bridge timeout')), 20000);
    timer.unref();
  }),
]).catch(e => {log('bridge error: ' + e.message); return null;});
assert(ready, 'bridge start failed');
const base = `http://127.0.0.1:${ready.port}`;
log('bridge ready on ' + base);

const {chromium} = loadPlaywright();
const browser = await chromium.launch({channel: 'msedge', headless: true});
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
const pageErrors = [];
page.on('pageerror', error => pageErrors.push(error.message));

try {
  let asks=0, ordinaryChat=0;
  const pasted='导数的几何意义是切线斜率。链式法则用于复合函数求导。';
  await page.route('**/api/companion/ask-stream',async route=>{
    const body=route.request().postDataJSON();assert.equal(body.expected_target,'user-paste');assert.equal(body.session,'companion');
    assert.equal(body.question,'选区讲了什么？');asks++;
    await route.fulfill({status:200,contentType:'application/x-ndjson',body:JSON.stringify({event:'delta',text:'粘贴材料说明导数与链式法则。'})+'\n'+JSON.stringify({event:'complete',status:'completed',text:'粘贴材料说明导数与链式法则。'})+'\n'});
  });
  await page.route('**/api/role/chat',async route=>{ordinaryChat++;await route.fulfill({json:{text:'unexpected fallback'}});});
  await page.goto(base+'/',{waitUntil:'domcontentloaded'});
  await page.waitForSelector('[data-room-input]');
  await page.evaluate(async()=>{
    const host=document.createElement('main');host.style.width='800px';document.body.append(host);
    const {mountCompanionSession}=await import('/app/companion-session.js');mountCompanionSession(host);
  });
  const details=page.locator('details.companion-paste');await details.locator('summary').click();
  await page.locator('textarea.companion-paste-input').fill(pasted);
  const pasteResponse=page.waitForResponse(response=>response.url()===base+'/api/companion/paste-context');
  await page.getByRole('button',{name:'将粘贴的选区文字作为上下文发送',exact:true}).click();
  const response=await pasteResponse;
  assert.ok(response.ok());
  const accepted=await response.json();
  assert.equal(accepted.target,'user-paste');assert.equal(accepted.chars,pasted.length);
  assert.equal(accepted.context_active,true);
  await page.waitForFunction(()=>document.querySelector('[data-companion-session] [role=status]')?.textContent.includes('已生效'));
  report.checks.real_bridge_paste_acknowledged=true;
  await page.locator('[data-room-input]').fill('选区讲了什么？');
  await page.locator('#sendBtn').click();
  await page.waitForFunction(()=>document.querySelector('#screen-room .chat-msgs')?.textContent.includes('粘贴材料说明导数与链式法则。'));
  report.checks.actual_send_uses_paste=asks===1&&ordinaryChat===0;
  report.checks.zero_pageerror=pageErrors.length===0;
  await page.screenshot({path:join(output,'paste-response.png')});
  report.passed=Object.values(report.checks).every(Boolean);

} catch (error) {
  report.error = error.message;
  log('ERROR: ' + error.message);
} finally {
  await browser.close();
  bridge.stdin.end();
  await Promise.race([once(bridge,'exit'),new Promise(resolve=>{
    const timer=setTimeout(resolve,20000);timer.unref();
  })]);
  if(bridge.exitCode===null) {
    bridge.kill();
    await once(bridge,'exit');
  }
  report.checks.bridge_stopped=bridge.exitCode!==null || bridge.signalCode!==null;
  report.passed=report.passed && report.checks.bridge_stopped;
  await writeFile(join(output, 'report.json'),
                  JSON.stringify(report, null, 2));
  console.log(JSON.stringify({passed: report.passed, checks: report.checks,
    evidence: join(output, 'report.json')}));
  process.exitCode = report.passed ? 0 : 1;
}
