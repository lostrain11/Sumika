// P16 UI verification: companion detail profile management against the real
// bridge — templates, runtime line, select, CRUD dialog, permission pause.
// Real bridge with a temp personal directory; no model calls, no capture.
import {spawn} from 'node:child_process';
import {mkdir, writeFile, readFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output = resolve(process.argv[2] || 'E:/SumikaBuild/companion-profiles-ui');
await mkdir(output, {recursive: true});
await mkdir(join(output, 'bridge-data'), {recursive: true});
const report = {passed: false, checks: {}, phases: []};
const log = message => {report.phases.push({at: new Date().toISOString(), message});
  console.log('[ui]', message);};

const bridgeCode = `
import sys, threading, json
from pathlib import Path
data = Path(sys.argv[1])
from extensions.models.settings import example, load, save
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
const bridge = spawn(process.env.SUMIKA_TEST_PYTHON || 'python',
  ['-u', '-X', 'utf8', '-B', '-c', bridgeCode, join(output, 'bridge-data')],
  {cwd: resolve('.'), stdio: ['pipe', 'pipe', 'ignore']});
let base = null;
const lines = createInterface({input: bridge.stdout});
await Promise.race([once(lines, 'line').then(([line]) => {
  base = 'http://127.0.0.1:' + JSON.parse(line).port;
}), new Promise((_, reject) => setTimeout(() => reject(new Error('bridge start timeout')), 20000))]);
log('bridge ready on ' + base);

const {chromium} = loadPlaywright();
const browser = await chromium.launch({channel: 'msedge', headless: true});
let page;
try {
  page = await browser.newPage({viewport: {width: 900, height: 900}});
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto(base + '/', {waitUntil: 'domcontentloaded', timeout: 60000});
  await page.evaluate(async () => {
    const host = document.createElement('main');
    host.style.width = '860px';
    document.body.append(host);
    const {mountCompanionSession} = await import('/app/companion-session.js');
    mountCompanionSession(host);
  });
  // Profiles + permission load asynchronously; wait for the real content.
  await page.waitForFunction(
    () => document.querySelector('[data-companion-profiles]')?.textContent
      .includes('手动选择'), {timeout: 10000});

  const runtimeLine = await page.locator('[data-companion-profiles]').textContent();
  report.checks.runtime_line_templates = runtimeLine.includes('学习')
    && runtimeLine.includes('手动选择');
  log('runtime line: ' + runtimeLine);

  const profileSelect = page.locator('select[aria-label="陪伴模式"]');
  const options = await profileSelect.locator('option').allTextContents();
  report.checks.templates_listed = ['学习', '游戏', '安静']
    .every(name => options.includes(name));

  // Manual select of 游戏.
  const gameValue = await profileSelect.locator('option', {hasText: '游戏'})
    .getAttribute('value');
  await profileSelect.selectOption(gameValue);
  await page.waitForTimeout(800);
  report.checks.manual_select_persists =
    (await page.locator('[data-companion-profiles]').textContent())
      .includes('游戏');

  // CRUD dialog: open, create, close.
  await page.locator('button[aria-label="管理陪伴模式"]').click();
  const dialogList = page.locator('dialog.sumika-dialog ul[aria-label="陪伴模式列表"]');
  await dialogList.waitFor({state: 'visible', timeout: 5000});
  await page.locator('button[aria-label="新建陪伴模式"]').click();
  await page.waitForTimeout(800);
  const items = await dialogList.locator('li').count();
  report.checks.dialog_create = items >= 4;  // 3 templates + 1 new
  await page.locator('dialog.sumika-dialog header button').click();
  await page.waitForTimeout(300);

  // Permission pause: the toggle reads 暂停记录 (recording was granted at
  // store init? No — default grants nothing, so it reads 恢复记录 only after
  // grant; here it must read 暂停记录 because can_record is false → the
  // toggle shows 恢复记录… wait: paused=false, can_record=false (default).
  // The toggle label reflects paused state only.
  const toggle = page.locator('button[aria-label="暂停或恢复行为记录"]');
  const toggleText = await toggle.textContent();
  report.checks.permission_toggle_visible =
    toggleText.includes('暂停记录') || toggleText.includes('恢复记录');
  await toggle.click();
  await page.waitForTimeout(800);
  report.checks.permission_toggle_toggles =
    !(await toggle.textContent() === toggleText);

  report.checks.zero_pageerror = pageErrors.length === 0;
  if (pageErrors.length) report.pageerrors = pageErrors;
  report.passed = Object.values(report.checks).every(Boolean);
  log('passed: ' + report.passed);
} finally {
  await browser.close();
  bridge.kill();
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({passed: report.passed, checks: report.checks,
    evidence: join(output, 'report.json')}));
}
