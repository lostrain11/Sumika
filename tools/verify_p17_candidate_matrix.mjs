// P17: installed-UI matrix against the CANDIDATE (not the dev tree).
// Spawns a real bridge from E:/SumikaBuild/p17-candidate with a temp
// personal directory, then runs the responsive matrix (8 viewports ×
// 2 zooms × 2 themes × 4 screens) against it.
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdir, mkdtemp, writeFile, readFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output = resolve(process.argv[2] || 'E:/SumikaBuild/p17-matrix-ui');
const candidate = resolve(process.argv[3] || 'E:/SumikaBuild/p17-candidate');
const source = resolve('.');
await mkdir(output, {recursive: true});
const bridgeData = await mkdtemp(join(output,'isolated-'));
const report = {passed: false, checks: {}, phases: []};
const log = message => {report.phases.push({at: new Date().toISOString(), message});
  console.log('[p17-matrix]', message);};

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
               capability_database=data/'capabilities.sqlite3', schedule_directory=data/'schedules')
threading.Thread(target=server.serve_forever, daemon=True).start()
print(json.dumps({'port': server.server_port}), flush=True)
try: sys.stdin.read()
finally: server.shutdown(); server.server_close()
`;

const bridge = spawn(process.env.SUMIKA_TEST_PYTHON || join(candidate,'runtime/python/python.exe'),
  ['-u', '-X', 'utf8', '-B', '-c', bridgeCode,
   bridgeData],
  {cwd: candidate, stdio: ['pipe', 'pipe', 'pipe'],
   env: {...process.env}});

const lines = createInterface({input: bridge.stdout});
const ready = await Promise.race([
  once(lines, 'line').then(([line]) => JSON.parse(line)),
  new Promise((_, reject) => {
    const timer = setTimeout(() => reject(new Error('bridge timeout')), 20000);
    timer.unref();
  }),
  once(bridge, 'exit').then(() => {throw new Error('bridge exited');}),
]).catch(error => {log('bridge error: ' + error.message); return null;});
if (!ready) { process.exitCode = 1; bridge.kill(); process.exit(1); }

const base = `http://127.0.0.1:${ready.port}`;
log('candidate bridge ready on ' + base);

// Now delegate to the matrix logic (inline simplified version).
const {chromium} = loadPlaywright();
const browser = await chromium.launch({channel: 'msedge', headless: true});
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
const pageErrors = [];
page.on('pageerror', error => pageErrors.push(error.message));

const VIEWPORTS = [
  {width: 1920, height: 1080}, {width: 1600, height: 900},
  {width: 1440, height: 900}, {width: 1280, height: 720},
  {width: 1160, height: 800}, {width: 1024, height: 768},
  {width: 960, height: 720}, {width: 900, height: 700},
];
const ZOOMS = [1, 1.25];
const SCREENS = ['room', 'shelf', 'settings', 'board'];
const THEMES = ['light', 'dark'];
const manifestFiles = ['ui/app/companion-session.js','ui/app/companion-text.js','ui/app/management.js','ui/app/bind.js','ui/app/css/settings.css','ui/app/layout.css'];
report.source_comparison = await Promise.all(manifestFiles.map(async path => {
  const hash = async root => { try { return createHash('sha256').update(await readFile(join(root,path))).digest('hex'); } catch {return null;} };
  const source_sha256=await hash(source),candidate_sha256=await hash(candidate);
  return {path,source_sha256,candidate_sha256,matches:source_sha256!==null && source_sha256===candidate_sha256};
}));
report.candidate= candidate; report.source=source; report.cells=[];

let cells = 0, overflow = 0;
try {
  report.checks.selected_source_files_match = report.source_comparison.every(row=>row.matches);
  assert.ok(report.checks.selected_source_files_match, 'candidate selected UI files differ from current source');
  await page.goto(base + '/', {waitUntil: 'domcontentloaded', timeout: 30000});
  for (const viewport of VIEWPORTS) {
    for (const zoom of ZOOMS) {
      const cssWidth = Math.round(viewport.width / zoom);
      const cssHeight = Math.round(viewport.height / zoom);
      await page.setViewportSize({width: cssWidth, height: cssHeight});
      for (const theme of THEMES) {
        await page.evaluate(async value => (await import('/app/theme.js')).setTheme(value),theme);
        for (const screen of SCREENS) {
          await page.goto(`${base}/#${screen}`, {waitUntil:'domcontentloaded',timeout:15000});
          await page.waitForFunction(key=>document.querySelector(`#screen-${key}`)?.classList.contains('show'),screen);
          await page.waitForTimeout(150);
          const metrics=await page.evaluate(()=>({scrollWidth:document.documentElement.scrollWidth,innerWidth:window.innerWidth,
            theme:document.documentElement.dataset.theme,screen:document.querySelector('.screen.show')?.id}));
          assert.equal(metrics.theme,theme);assert.equal(metrics.screen,`screen-${screen}`);
          cells++;if(metrics.scrollWidth>metrics.innerWidth+1)overflow++;
          report.cells.push({viewport,zoom,theme,screen,...metrics});
        }
      }
    }
  }
  report.checks.matrix_cells = cells;
  report.checks.all_128_cells = cells === 128;
  report.checks.horizontal_overflow_cells = overflow;
  report.checks.zero_pageerror = pageErrors.length === 0;
  if (pageErrors.length) report.pageErrors = pageErrors.slice(0, 5);
  report.checks.candidate_bridge_started = true;
  report.passed = cells === 128 && overflow === 0 && pageErrors.length === 0;
} catch (error) {
  report.error = error.message;
} finally {
  await browser.close();
  bridge.stdin.end();
  await Promise.race([once(bridge,'exit'),new Promise(resolve=>{
    const timer=setTimeout(resolve,20000);timer.unref();
  })]);
  if(bridge.exitCode===null)bridge.kill();
  await writeFile(join(output, 'report.json'),
                  JSON.stringify(report, null, 2));
  console.log(JSON.stringify({passed: report.passed,
    checks: report.checks, evidence: join(output, 'report.json')}));
  process.exitCode = report.passed ? 0 : 1;
}
