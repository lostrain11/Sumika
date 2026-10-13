// P05/F-01 E2E: real bridge + real extension popup connect + REAL product UI
// approve + tab audio + a text question through the product routing function,
// then disconnect. Real public Bilibili video; bridge-level chat stub returns
// provenance markers (no paid model calls).
import {spawn} from 'node:child_process';
import {mkdir, writeFile, readFile} from 'node:fs/promises';
import {readdirSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import assert from 'node:assert/strict';
import {loadPlaywright} from './lib/playwright.mjs';
import {buildCompanionExtension} from './build_companion_extension.mjs';

const output = resolve(process.argv[2] || 'E:/SumikaBuild/companion-wiring-e2e');
await mkdir(output, {recursive: true});
await mkdir(join(output, 'bridge-data'), {recursive: true});
// Global watchdog: run 58 hung >20 minutes (unbounded browser.close() once the
// track churned). A stuck harness must die loudly with its evidence on disk.
setTimeout(() => {
  console.log('[e2e] GLOBAL WATCHDOG: run exceeded 8 minutes; dumping and exiting');
  try {writeFileSync(join(output, 'report.json'), JSON.stringify({
    passed: false, watchdog: '8-minute global timeout', checks: report.checks,
    phases: report.phases}, null, 2));} catch { }
  process.exit(124);
}, 8 * 60 * 1000).unref();
const voskModel = 'E:/Models/Speech/sumika/vosk-model-small-cn-0.22';
const voicePython = 'E:/SumikaBuild/p05-stage-check/runtime/voice/python.exe';
const videoUrl = 'https://www.bilibili.com/video/BV1QN4y1c7RQ/';
const markers = join(output, 'model-markers.jsonl');
const report = {passed: false, scope: 'Real bridge + real extension + real product '
  + 'page; chat stub returns provenance markers (no paid model calls)',
  checks: {}, phases: []};
const log = message => {report.phases.push({at: new Date().toISOString(), message});
  console.log('[e2e]', message);};

const bridgeCode = `
import sys, threading, json
from pathlib import Path
data = Path(sys.argv[1]); markers = Path(sys.argv[2])
_log = open(data/'bridge-log.txt', 'w', encoding='utf8')
sys.stdout = _log; sys.stderr = _log
try:
    from extensions.models.settings import load, save
    base = load(Path(sys.argv[3]))
    base["role"]["database"] = str(data/"role.db"); base["role"]["memory_provider"]="embedded"
    base["memory"]["enabled"] = False; base["enabled"] = True
    base.setdefault("voice", {}).update({"enabled": True, "input_device": None,
        "sample_rate": 16000, "asr_model": sys.argv[4]})
    save(base, data/"settings.json")
    from extensions.capabilities import CapabilityStore
    store = CapabilityStore(data/"capabilities.sqlite3")
    store.configure("microphone", "sounddevice", options={"user_authorized": True})
    store.configure("asr", "vosk", options={})
    store.configure("voice", "windows-sapi", options={})
    store.close()
    from ui.server import serve
    server = serve(data/"settings.json", port=0, workbench_root=data,
                   capability_database=data/"capabilities.sqlite3")
    def stub(prompt, **kwargs):
        marker = "E2E_TARGET_OK" if "browser-passive" in prompt else "E2E_NO_TAB_CONTEXT"
        with open(markers, "a", encoding="utf8") as out:
            out.write(marker + " | " + prompt[:4000].replace(chr(10), " ") + chr(10))
        return {"text": marker + " 回答"}
    server.sumika_bridge._companion._role_chat = stub
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(json.dumps({"port": server.server_port}), flush=True)
    sys.stdin.read()
except BaseException:
    _log.write(traceback.format_exc()); _log.flush()
    raise
`;

const extension = await buildCompanionExtension(join(output, 'extension'));
const settings = 'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/Sumika/role-model-settings.json';
const logPath = join(output, 'bridge-data', 'bridge-log.txt');
const bridge = spawn(process.env.SUMIKA_TEST_PYTHON || 'python',
  ['-u', '-X', 'utf8', '-B', '-c', bridgeCode,
   join(output, 'bridge-data'), markers, settings, voskModel],
  {cwd: resolve('.'), stdio: ['pipe', 'ignore', 'pipe'],
   env: {...process.env, SUMIKA_VOICE_PYTHON: voicePython,
         SUMIKA_BROWSER_AUDIO_CHILD_LOG: join(output, 'audio-child.log'),
         SUMIKA_PASSIVE_DIAG: join(output, 'passive-diag.log')}});
bridge.on('error', error => console.log('[bridge spawn error]', error.message));
bridge.on('exit', (code, signal) => console.log('[bridge exit]', code, signal));
bridge.stderr.setEncoding('utf8');
bridge.stderr.on('data', value => process.stderr.write('[bridge] ' + value));
let base = null;
for (let i = 0; i < 120 && !base; i++) {
  await new Promise(r => setTimeout(r, 250));
  try {
    const text = await readFile(logPath, 'utf8');
    for (const line of text.split('\n')) {
      if (line.trim().startsWith('{') && line.includes('port')) {
        base = 'http://127.0.0.1:' + JSON.parse(line).port;
      }
    }
  } catch { }
  if (bridge.exitCode !== null) break;
}
assert(base, 'bridge start timeout; data dir contents: '
  + readdirSync(join(output, 'bridge-data')).join(','));
log('bridge ready on ' + base);

const {chromium} = loadPlaywright();
const browser = await chromium.launchPersistentContext(join(output, 'profile'), {
  channel: 'msedge', headless: true,
  args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`]});
try {
  // 1. Real public video tab + product POPUP connect.
  const video = await browser.newPage();
  await video.goto(videoUrl, {waitUntil: 'domcontentloaded', timeout: 60000});
  video.on('console', message => console.log('[content]', message.text()));
  await video.evaluate(() => {const v = document.querySelector('video');
    if (v) {v.muted = true; v.volume = 0; v.play().catch(() => {});}});
  const worker = browser.serviceWorkers()[0]
    || await browser.waitForEvent('serviceworker', {timeout: 15000});
  worker.on('console', message => console.log('[sw]', message.text()));
  const extensionId = new URL(worker.url()).hostname;
  // The popup's own handler wraps chrome.tabs.query + offerConnection; in
  // the harness the active-tab query cannot see the video window, so the
  // product's worker function is invoked directly (same request path).
  const tabId = await worker.evaluate(async url => {
    const tabs = await chrome.tabs.query({url: url.replace(/\?.*$/, '') + '*'});
    if (tabs.length !== 1) throw new Error('video tab not found: ' + tabs.length);
    return tabs[0].id;
  }, videoUrl);
  const connectResult = await worker.evaluate(async configuration =>
    offerConnection(configuration), {base, tab_id: tabId});
  log('offerConnection: ' + JSON.stringify(connectResult));
  report.checks.popup_connect_requested = connectResult.status === 'pending';
  // Probe pending through the SAME authenticated route the UI uses.
  const session = await (await fetch(base + '/api/manage/session')).json();
  const pendingProbe = await (await fetch(base + '/api/companion/passive-browser', {
    method: 'POST', headers: {'Content-Type': 'application/json',
      'X-Sumika-CSRF': session.csrf},
    body: JSON.stringify({action: 'pending'})})).json();
  log('authenticated pending: ' + JSON.stringify(pendingProbe));

  // 2. The REAL product page approves through the companion detail UI.
  const page = await browser.newPage({viewport: {width: 900, height: 900}});
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
  const detail = page.locator('main section').filter({has: page.getByLabel('学习窗口')}).first();
  // Two 刷新 buttons exist in the section (window list and status); the
  // window-list one carries the explanatory title.
  await detail.locator('button[title="刷新窗口列表"]').click();
  const pendingOption = page.locator('select[aria-label="学习窗口"] option',
    {hasText: 'B站标签页（待确认）'});
  // The popup posts /request on click; the refresh above may have raced it,
  // so click 刷新 again until the pending option is rendered.
  // Select the tab the moment it appears: each refresh rebuilds the
  // selector, so the option must be taken immediately.
  let pendingValue = null;
  for (let i = 0; i < 15; i++) {
    await detail.locator('button[title="刷新窗口列表"]').click();
    await page.waitForTimeout(500);
    const option = page.locator('select[aria-label="学习窗口"] option',
      {hasText: 'B站标签页（待确认）'});
    if (await option.count() > 0) {
      pendingValue = await option.getAttribute('value');
      await page.selectOption('select[aria-label="学习窗口"]', {value: pendingValue});
      report.checks.pending_tab_listed_in_product_selector = true;
      break;
    }
  }
  assert(pendingValue, 'the pending Bilibili tab never appeared in the selector');
  await page.locator('input[aria-label="采集应用声音"]').check();
  page.on('dialog', dialog => dialog.accept());
  await detail.getByRole('button', {name: '开始陪学'}).click();
  log('UI approve sent through the companion detail');
  report.checks.ui_approve_via_product_detail = true;
  // The extension learns the approval through its product poll (the popup
  // drives the same call on its 2s timer).
  // The video's audio track can lag playback start (MSE buffering); a real
  // user retries the connection — bounded polls do the same.
  let pollResult = null;
  for (let attempt = 0; attempt < 10; attempt++) {
    pollResult = await worker.evaluate(() =>
      pollConnection().then(value => value, error => ({error: error.message})));
    log('pollConnection attempt ' + attempt + ': ' + JSON.stringify(pollResult));
    if (pollResult.status === 'running') break;
    await new Promise(r => setTimeout(r, 3000));
  }
  report.checks.extension_poll_after_approve = pollResult.status === 'running';

  // 3. The passive session goes live; audio lazy-starts from the first
  //    relayed packet; transcripts prove the rebuilt recognizer loop.
  let audio = null;
  for (let i = 0; i < 120; i++) {
    await new Promise(r => setTimeout(r, 500));
    try {
      const session = await (await fetch(base + '/api/manage/session')).json();
      const status = await (await fetch(base + '/api/companion/microphone', {
        method: 'POST', headers: {'Content-Type': 'application/json',
          'X-Sumika-CSRF': session.csrf},
        body: JSON.stringify({action: 'status', after: 0})})).json();
      if (status.passive?.status === 'running'
          && status.browser_audio?.alive
          && status.browser_audio?.transcripts > 0) {audio = status; break;}
      if (i % 8 === 0) console.log('[e2e] audio wait', i,
        'passive=', status.passive?.status,
        'audio=', JSON.stringify(status.browser_audio));
    } catch { }
  }
  assert(audio, 'tab audio never became healthy');
  assert(audio.browser_audio.transcripts > 0,
    'expected transcripts from the lazy-started recognizer');
  report.checks.tab_audio_lazy_started_transcripts = audio.browser_audio.transcripts;
  report.checks.tab_audio_seconds = audio.browser_audio.audio_seconds;
  log('tab audio live with ' + audio.browser_audio.transcripts + ' transcripts');

  // 4. A text question through the PRODUCT routing function: the stubbed
  //    chat echoes provenance markers proving the tab context reached it.
  //    Bounded: an unbounded evaluate is how run 58 hung for >20 minutes.
  const answer = await Promise.race([
    page.evaluate(async () => {
      const {sendCompanionText} = await import('/app/companion-text.js');
      window.__e2eAnswer = '';
      await sendCompanionText('这节课在讲什么？', text => {window.__e2eAnswer = text;});
      return window.__e2eAnswer;
    }),
    new Promise((_, reject) => setTimeout(() => reject(new Error(
      'text question did not settle in 60s (bridge handler stuck?)')), 60000))]);
  assert(answer.includes('E2E_TARGET_OK'),
         'the answer must come from the tab context, got: ' + answer);
  report.checks.text_question_routed_to_tab_context = true;
  log('text question answered from the tab context');

  const markerLog = await readFile(markers, 'utf8');
  report.checks.model_prompt_contains_tab_target =
    markerLog.includes('browser-passive');

  // 5. Disconnect through the product stop, with request diagnostics.
  //    First record whether the passive grant is STILL running at this point:
  //    run 58 lost the grant mid-run, long before any stop click.
  const stopCalls = [];
  page.on('request', request => {
    const url = request.url();
    if (url.endsWith('/api/companion/revoke')
        || (url.endsWith('/api/companion/passive-browser')
            && request.method() === 'POST'))
      stopCalls.push('/api/' + url.split('/api/')[1]);
  });
  const statusProbe = async () => {
    const session = await (await fetch(base + '/api/manage/session')).json();
    return (await fetch(base + '/api/companion/passive-browser', {
      method: 'POST', headers: {'Content-Type': 'application/json',
        'X-Sumika-CSRF': session.csrf},
      body: JSON.stringify({action: 'status'})})).json();
  };
  const preStop = await statusProbe();
  report.checks.passive_still_running_before_stop = preStop.status === 'running';
  log('pre-stop passive status: ' + JSON.stringify(preStop));
  assert(preStop.status === 'running',
    'the passive grant died before the stop click (run-58 symptom); diag: '
    + join(output, 'passive-diag.log'));
  await detail.getByRole('button', {name: '停止陪学'}).click();
  let stopOk = false;
  for (let i = 0; i < 20; i++) {
    await page.waitForTimeout(500);
    const stopped = await statusProbe();
    if (stopped.status !== 'running') {stopOk = true; break;}
  }
  report.checks.ui_stop_requests_sent = stopCalls;
  report.checks.ui_stop_disconnects_tab = stopOk;
  assert(stopOk, 'the tab session must stop with the UI; requests: '
    + JSON.stringify(stopCalls));
  report.passed = true;
} finally {
  await browser.close();
  bridge.kill();
  try {const diag = await readFile(join(output, 'passive-diag.log'), 'utf8');
    console.log('[e2e] passive-diag tail:\n' + diag.trim().split('\n').slice(-40).join('\n'));
  } catch { }
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({passed: report.passed, checks: report.checks,
    evidence: join(output, 'report.json')}));
}
