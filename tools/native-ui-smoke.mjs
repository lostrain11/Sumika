import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, writeFile, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { once } from "node:events";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";

const root = fileURLToPath(new URL("..", import.meta.url));
const dependencyRoot = existsSync(join(root, "frontend/node_modules/playwright-core/index.mjs"))
  ? root
  : "D:/Code/Sumika";
const { chromium } = await import(pathToFileURL(join(dependencyRoot, "frontend/node_modules/playwright-core/index.mjs")));
const require = createRequire(pathToFileURL(join(dependencyRoot, "frontend/package.json")));
const { PNG } = require(join(dependencyRoot, "frontend/node_modules/playwright-core/lib/utilsBundle.js"));
const evidence = resolve(process.argv[2] || "D:/Caches/sumika-ui-smoke", String(Date.now()));
await mkdir(evidence, { recursive: true });
const data = await mkdtemp(join(evidence, "runtime-"));
const delay = (milliseconds) => new Promise((done) => setTimeout(done, milliseconds));

async function port() {
  const server = createServer().listen(0, "127.0.0.1");
  await once(server, "listening");
  const value = server.address().port;
  await new Promise((done) => server.close(done));
  return value;
}

async function until(check, label, timeout = 30000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      if (await check()) return;
    } catch {}
    await delay(150);
  }
  throw new Error(`Timed out: ${label}`);
}

const corePort = await port();
const cdpPort = await port();
const binary = resolve(process.env.SUMIKA_SMOKE_BINARY || join(root, "src-tauri/target/debug/sumika-desktop.exe"));
const child = spawn(binary, [], {
  cwd: root,
  windowsHide: true,
  stdio: "ignore",
  env: {
    ...process.env,
    SUMIKA_CORE_HOST: "127.0.0.1",
    SUMIKA_CORE_PORT: String(corePort),
    SUMIKA_DESKTOP_DATA_DIR: data,
    SUMIKA_AGENT_RUNTIME: "none",
    SUMIKA_AGENT_AUTOSTART: "0",
    SUMIKA_DSH_AUTOSTART: "0",
    SUMIKA_SMOKE_MAIN_DATA_DIR: join(data, "shell-webviews"),
    WEBVIEW2_USER_DATA_FOLDER: join(data, "webview"),
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${cdpPort}`,
  },
});

let browser;
let mainPage;
let companionPage;
const checks = [];
const limitations = [];
const record = (name) => {
  checks.push(name);
  console.log(`PASS ${name}`);
};
async function invoke(page, command, args = {}) {
  let timer;
  try {
    return await Promise.race([
      page.evaluate(({ commandName, commandArgs }) => window.__TAURI__.core.invoke(commandName, commandArgs),
        { commandName: command, commandArgs: args }),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Native command timed out: ${command}`)), 15000); }),
    ]);
  } finally { clearTimeout(timer); }
}

async function capture(page, name, transparent = false) {
  const pixels = PNG.sync.read(await page.locator(".vrm-renderer canvas").screenshot({ omitBackground: transparent }));
  const colors = new Set();
  let clear = 0;
  for (let offset = 0; offset < pixels.data.length; offset += 4) {
    if (pixels.data[offset + 3] === 0) clear += 1;
    if (offset % 128 === 0) {
      colors.add(`${pixels.data[offset] >> 4},${pixels.data[offset + 1] >> 4},${pixels.data[offset + 2] >> 4}`);
    }
  }
  assert(colors.size > 25, "native scene must have nonblank pixels");
  if (transparent) {
    assert(clear > pixels.width * pixels.height * 0.2, "transparent companion must contain alpha pixels");
  }
  await page.screenshot({ path: join(evidence, `${name}.png`), omitBackground: true });
}

async function pagesByWindowLabel() {
  const result = new Map();
  for (const page of browser.contexts()[0]?.pages() || []) {
    const label = await page.evaluate(() => window.__TAURI__?.window?.getCurrentWindow()?.label).catch(() => "");
    if (label) result.set(label, page);
  }
  return result;
}

async function closeNativeWindow(label) {
  const state = await invoke(mainPage, "native_windows_state");
  const handle = state[label].native_handle;
  assert(Number.isSafeInteger(handle) && handle > 0, "native window handle must be valid");
  const script = `Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class SmokeWindow { [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId); [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wparam, IntPtr lparam); }'; $handle=[IntPtr]${handle}; $windowPid=0; [SmokeWindow]::GetWindowThreadProcessId($handle,[ref]$windowPid) | Out-Null; if($windowPid -ne ${child.pid}){ throw 'Native window is outside the isolated test process' }; if(-not [SmokeWindow]::PostMessage($handle,0x10,[IntPtr]::Zero,[IntPtr]::Zero)){ throw 'Native close message failed' }`;
  execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], { windowsHide: true });
}

function foregroundWindowHandle() {
  const script = "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class SmokeForeground { [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow(); }'; [SmokeForeground]::GetForegroundWindow().ToInt64()";
  return execFileSync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-Command", script],
    { windowsHide: true, encoding: "utf8" },
  ).trim();
}

try {
  await until(async () => (await fetch(`http://127.0.0.1:${cdpPort}/json/version`)).ok, "WebView2 CDP");
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${cdpPort}`);
  await until(async () => (await pagesByWindowLabel()).size === 2, "two native webviews");
  const pages = await pagesByWindowLabel();
  mainPage = pages.get("main");
  companionPage = pages.get("companion");
  assert(mainPage && companionPage, "main and companion native webviews must exist");
  await mainPage.waitForSelector(".wv2-topbar", { state: "attached" });
  await companionPage.waitForSelector(".desktop-overlay-shell", { state: "attached" });
  assert.equal(new URL(companionPage.url()).searchParams.get("view"), "companion");
  const coreStatus = await invoke(mainPage, "core_status");
  assert.equal(coreStatus.port, corePort);
  assert.equal(coreStatus.running, true);
  assert.equal(await invoke(mainPage, "get_display_mode"), "workspace");
  record("trusted shell command channel and isolated Core are healthy");

  const confirmationParams = { request_id: "smoke-nonexistent", assistant_id: "sumika", revision: 1, max_cny: "0" };
  const confirmationMethod = "work.authorization.confirm";
  async function coreRpc(method, params) {
    return (await fetch(`http://127.0.0.1:${corePort}/rpc`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: "host-boundary", method, params }),
    })).json();
  }
  const denied = await coreRpc(confirmationMethod, { ...confirmationParams, approved: true, trusted: true });
  assert.equal(denied.error.code, -32041);
  const confirmationPreview = await coreRpc("host.confirmation.digest", { method: confirmationMethod, params: confirmationParams });
  const confirmationArgs = { method: confirmationMethod, params: confirmationParams, digest: confirmationPreview.result.digest };
  const nativeResult = await invoke(mainPage, "host_confirm", confirmationArgs).then(() => "", String);
  assert.match(nativeResult, /not found/i);
  assert.doesNotMatch(nativeResult, /trusted native host|invalid-host-response/i);
  assert.match(await invoke(companionPage, "host_confirm", confirmationArgs).then(() => "", String), /restricted to the main webview/);
  assert.match(await invoke(mainPage, "host_confirm", { ...confirmationArgs, method: "chat.send" }).then(() => "", String), /unsupported-host-confirmation/);
  const questionMethod = "agent.question.respond";
  const questionParams = { rpcId: "smoke-nonexistent", sessionId: "smoke-nonexistent", answer: { answers: [{ id: "plan-review", selected: ["Approve"] }] } };
  assert.equal((await coreRpc(questionMethod, questionParams)).error.code, -32041);
  const questionPreview = await coreRpc("host.confirmation.digest", { method: questionMethod, params: questionParams });
  assert.match(await invoke(companionPage, "host_confirm", { method: questionMethod, params: questionParams, digest: questionPreview.result.digest }).then(() => "", String), /restricted to the main webview/);
  record("private native bootstrap works; HTTP forgery, companion confirmation and arbitrary RPC are denied");
  record("Plan Review cannot approve through ordinary HTTP or the companion window");

  const models = await (await fetch(`http://127.0.0.1:${corePort}/api/avatar/models`)).json();
  const sample = models.find((model) => model.kind === "vrm");
  assert(sample, "bundled sample VRM must exist");
  const selection = await (await fetch(`http://127.0.0.1:${corePort}/rpc`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: "isolated-avatar",
      method: "avatar.select",
      params: { character_id: "sumika", model_id: sample.id, driver_id: "vrm" },
    }),
  })).json();
  assert(!selection.error, JSON.stringify(selection.error));
  for (const page of [mainPage, companionPage]) {
    await page.evaluate(() => localStorage.setItem("sumika.onboarded.v1", "1"));
  }
  await mainPage.reload();
  await mainPage.waitForSelector(".wv2-topbar");

  const initial = await invoke(mainPage, "native_windows_state");
  assert.equal(initial.main.label, "main");
  assert.equal(initial.companion.label, "companion");
  assert.equal(initial.main.visible, true);
  assert.equal(initial.companion.visible, false);
  assert.equal(initial.tray_available, true);
  assert.equal((await mainPage.evaluate(() => window.__TAURI__.window.getAllWindows())).length, 2);
  record("main and companion are two real native windows; tray is installed");

  await mainPage.locator('.wv2-composer textarea[name="goal"]').fill("Main isolated draft");
  await mainPage.screenshot({ path: join(evidence, "native-workspace.png"), omitBackground: true });
  const foregroundBeforeCompanion = foregroundWindowHandle();
  assert.equal(await invoke(mainPage, "set_display_mode", { mode: "pet" }), "pet");
  await until(async () => (await invoke(mainPage, "native_windows_state")).companion.visible, "companion visible");
  assert.equal(foregroundWindowHandle(), foregroundBeforeCompanion);
  assert.equal((await invoke(mainPage, "native_windows_state")).companion.focused, false);

  await companionPage.reload();
  await companionPage.waitForSelector(".desktop-overlay-shell");
  await companionPage.waitForSelector('[data-vrm-status="ready"]', { timeout: 30000 });
  await until(
    () => companionPage.locator(".vrm-renderer").getAttribute("data-vrm-render-status").then((status) => status === "running"),
    "companion renderer",
  );
  await companionPage.locator(".desktop-overlay-shell").hover({ position: { x: 10, y: 100 } });
  await companionPage.locator("[data-pet-chat]").click();
  await companionPage.locator("#chat-input").fill("Companion isolated draft");
  assert.equal(await mainPage.locator('.wv2-composer textarea[name="goal"]').inputValue(), "Main isolated draft");
  const mainCore = await invoke(mainPage, "core_status");
  const companionCore = await invoke(companionPage, "core_status");
  assert(mainCore.running && companionCore.running);
  assert.equal(mainCore.pid, companionCore.pid);
  assert.equal(mainCore.restart_count, companionCore.restart_count);
  assert.match(
    await invoke(companionPage, "embedded_browser_list").then(() => "", (error) => String(error)),
    /restricted to the main webview/,
  );
  record("independent drafts share one Core PID; companion browser command is rejected");

  let state = await invoke(mainPage, "set_companion_mode", { mode: "compact" });
  assert.equal(state.companion_mode, "compact");
  assert.equal(state.companion.decorated, false);
  assert.equal(state.companion.always_on_top, true);
  assert.equal(Math.round(state.companion.size.width / state.companion.scale_factor), 480);
  assert.equal(Math.round(state.companion.size.height / state.companion.scale_factor), 420);
  await capture(companionPage, "native-companion-compact");

  const moved = await invoke(mainPage, "set_companion_bounds", {
    x: 160,
    y: 120,
    width: 480,
    height: 420,
  });
  state = await invoke(mainPage, "set_companion_mode", { mode: "panorama" });
  assert.equal(state.companion_mode, "panorama");
  assert.equal(state.companion.decorated, true);
  assert.equal(Math.round(state.companion.size.width / state.companion.scale_factor), 1120);
  assert.equal(Math.round(state.companion.size.height / state.companion.scale_factor), 720);
  await capture(companionPage, "native-companion-panorama");
  state = await invoke(mainPage, "set_companion_mode", { mode: "compact" });
  assert.deepEqual(state.companion.position, moved.companion.position);
  record("compact and panorama retain independent native bounds");

  state = await invoke(mainPage, "set_companion_mode", { mode: "fullscreen" });
  assert.equal(state.companion.fullscreen, true);
  await capture(companionPage, "native-companion-fullscreen");
  state = await invoke(mainPage, "set_companion_mode", { mode: "compact" });
  assert.equal(state.companion.fullscreen, false);
  state = await invoke(mainPage, "set_companion_always_on_top", { alwaysOnTop: false });
  assert.equal(state.companion.always_on_top, false);
  state = await invoke(mainPage, "set_companion_always_on_top", { alwaysOnTop: true });
  assert.equal(state.companion.always_on_top, true);

  state = await invoke(mainPage, "set_companion_transparent", { transparent: true });
  assert.equal(state.companion_transparent, true);
  const backgroundButton = companionPage.locator("[data-pet-background]");
  if ((await backgroundButton.getAttribute("aria-pressed")) !== "true") await backgroundButton.click();
  await companionPage.mouse.move(-10, -10);
  await companionPage.evaluate(() => document.activeElement?.blur());
  await capture(companionPage, "native-companion-transparent", true);
  record("fullscreen, transparent background and manual always-on-top are functional");

  await companionPage.evaluate(async () => {
    window.__sumikaNativeRenderEvents = [];
    window.__sumikaNativeRenderUnlisten = await window.__TAURI__.event.listen(
      "native-render-visibility-changed",
      (event) => window.__sumikaNativeRenderEvents.push(event.payload),
    );
  });
  await invoke(companionPage, "set_window_minimized", { minimized: true });
  await until(async () => (await invoke(mainPage, "native_windows_state")).companion.minimized, "companion minimized");
  await until(
    () => companionPage.evaluate(() => window.__sumikaNativeRenderEvents.some((event) => event.rendering === false && event.reason === "minimized")),
    "companion minimize render event",
  );
  await invoke(companionPage, "set_window_minimized", { minimized: false });
  await until(
    () => companionPage.evaluate(() => window.__sumikaNativeRenderEvents.some((event) => event.rendering === true && event.reason === "restored")),
    "companion restore render event",
  );
  record("minimize and restore publish renderer lifecycle notifications");

  await closeNativeWindow("companion");
  await until(async () => !(await invoke(mainPage, "native_windows_state")).companion.visible, "companion close hides");
  assert.equal((await invoke(mainPage, "native_windows_state")).main.visible, true);
  await invoke(mainPage, "show_companion");
  await closeNativeWindow("main");
  await until(async () => !(await invoke(companionPage, "native_windows_state")).main.visible, "main close hides");
  state = await invoke(companionPage, "native_windows_state");
  assert.equal(state.companion.visible, true);
  assert.equal((await fetch(`http://127.0.0.1:${corePort}/api/health`)).ok, true);
  await invoke(companionPage, "show_main_window");
  await until(async () => (await invoke(mainPage, "native_windows_state")).main.visible, "main tray-path restore");
  record("each close hides only that window; restore keeps the managed Core alive");

  if (state.monitor_count < 2) {
    limitations.push("Multi-monitor hot-unplug recovery was not hardware-verified; Rust geometry tests cover missing-monitor fallback.");
  } else {
    limitations.push("Multiple monitors were detected, but physical hot-unplug was not automated in this smoke.");
  }
} catch (error) {
  if (mainPage) await mainPage.screenshot({ path: join(evidence, "failure-main.png") }).catch(() => {});
  if (companionPage) await companionPage.screenshot({ path: join(evidence, "failure-companion.png") }).catch(() => {});
  await writeFile(
    join(evidence, "result.json"),
    JSON.stringify({ passed: false, checks, limitations, error: String(error) }, null, 2),
  );
  throw error;
} finally {
  if (child.exitCode === null && mainPage) {
    await invoke(mainPage, "exit_application").catch(() => {});
  }
  await until(() => child.exitCode !== null, "native exit", 15000).catch(() => {
    execFileSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true });
  });
  if (browser) await browser.close();
  await until(async () => {
    try {
      await fetch(`http://127.0.0.1:${corePort}/api/health`);
      return false;
    } catch {
      return true;
    }
  }, "managed Core cleanup");
  assert(data.startsWith(`${evidence}\\`) || data.startsWith(`${evidence}/`));
  await rm(data, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 });
  console.log(`Evidence: ${evidence}`);
}

record("native process and owned Core exit cleanly; isolated runtime removed");
await writeFile(
  join(evidence, "result.json"),
  JSON.stringify({ passed: true, scope: "isolated native UI only; no DSH, login or model calls", checks, limitations }, null, 2),
);
