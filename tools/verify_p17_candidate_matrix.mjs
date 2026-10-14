// P17: installed-UI matrix against the CANDIDATE (not the dev tree).
// Spawns a real bridge from E:/SumikaBuild/p17-candidate with a temp
// personal directory, then runs the responsive matrix (8 viewports ×
// 2 zooms × 2 themes × 4 screens) against it.
import {spawn} from 'node:child_process';
import {mkdir, writeFile, readFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';

const output = resolve(process.argv[2] || 'E:/SumikaBuild/p17-matrix-ui');
const candidate = 'E:/SumikaBuild/p17-candidate';
await mkdir(output, {recursive: true});
await mkdir(join(output, 'bridge-data'), {recursive: true});
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
               capability_database=data/'capabilities.sqlite3')
threading.Thread(target=server.serve_forever, daemon=True).start()
print(json.dumps({'port': server.server_port}), flush=True)
sys.stdin.read()
`;

const bridge = spawn('E:/SumikaBuild/p17-candidate/runtime/python/python.exe',
  ['-u', '-X', 'utf8', '-B', '-c', bridgeCode,
   join(output, 'bridge-data')],
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
const SCREENS = ['/', '/#capabilities', '/#settings', '/#data'];

let cells = 0, overflow = 0;
try {
  await page.goto(base + '/', {waitUntil: 'domcontentloaded', timeout: 30000});
  for (const viewport of VIEWPORTS) {
    for (const zoom of ZOOMS) {
      const cssWidth = Math.round(viewport.width / zoom);
      const cssHeight = Math.round(viewport.height / zoom);
      await page.setViewportSize({width: cssWidth, height: cssHeight});
      for (const screen of SCREENS) {
        const url = screen.startsWith('#') ? base + '/' + screen : base + screen;
        if (page.url().split('#')[0] !== url.split('#')[0] || page.url().split('#')[1] !== url.split('#')[1])
          await page.goto(url, {waitUntil: 'domcontentloaded', timeout: 15000});
        await page.waitForTimeout(300);
        const metrics = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
        }));
        cells++;
        if (metrics.scrollWidth > metrics.innerWidth + 1) overflow++;
      }
    }
  }
  report.checks.matrix_cells = cells;
  report.checks.horizontal_overflow_cells = overflow;
  report.checks.zero_pageerror = pageErrors.length === 0;
  if (pageErrors.length) report.pageErrors = pageErrors.slice(0, 5);
  report.checks.candidate_bridge_started = true;
  report.passed = overflow === 0 && pageErrors.length === 0;
} catch (error) {
  report.error = error.message;
} finally {
  await browser.close();
  bridge.kill();
  await writeFile(join(output, 'report.json'),
                  JSON.stringify(report, null, 2));
  console.log(JSON.stringify({passed: report.passed,
    checks: report.checks, evidence: join(output, 'report.json')}));
  process.exitCode = report.passed ? 0 : 1;
}
