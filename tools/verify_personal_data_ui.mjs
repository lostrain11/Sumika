// Read-only UI acceptance against an isolated packaged bridge.
import {createRequire} from 'node:module';
import {readdirSync, existsSync, mkdirSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const runtime=path.join(process.env.LOCALAPPDATA,'OpenAI/Codex/runtimes/cua_node');
const pkg=readdirSync(runtime).map(n=>path.join(runtime,n,'bin/node_modules/playwright/package.json')).find(existsSync);
const {chromium}=createRequire(pkg)('playwright');
const origin=process.argv[2];
const output=process.argv[3];mkdirSync(output,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const writes=[];page.on('request',r=>{if(r.method()==='POST')writes.push(r.url());});
  await page.goto(origin+'/#settings');
  await page.locator('.set-nav [data-section="data"]').click();
  const field=page.getByLabel('个人数据目录',{exact:true});
  await field.waitFor();assert.equal(await field.getAttribute('readonly'),'');
  await page.screenshot({path:path.join(output,'data-settings.png')});
  await page.getByRole('button',{name:'迁移数据',exact:true}).click();
  await page.getByRole('dialog').waitFor();
  assert.equal(await page.getByRole('dialog').getByLabel('新的个人数据目录').count(),1);
  await page.screenshot({path:path.join(output,'migration-dialog.png')});
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'从备份恢复',exact:true}).click();
  assert.equal(await page.getByRole('dialog').filter({visible:true}).getByLabel('备份目录（含 snapshot.json）').count(),1);
  await page.screenshot({path:path.join(output,'restore-dialog.png')});
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  writeFileSync(path.join(output,'report.json'),JSON.stringify({passed:true,errors,writes,checks:['data location read only','migration dialog','restore dialog','no automatic writes']},null,2));
  console.log('PASS',output);
} finally {await browser.close();}
