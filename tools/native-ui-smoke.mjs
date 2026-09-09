import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { mkdir, mkdtemp, writeFile, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { chromium } from "../frontend/node_modules/playwright-core/index.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const require = createRequire(import.meta.url);
const { PNG } = require("../frontend/node_modules/playwright-core/lib/utilsBundle.js");
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
    try { if (await check()) return; } catch {}
    await delay(150);
  }
  throw new Error(`Timed out: ${label}`);
}
const corePort = await port();
const cdpPort = await port();
const child = spawn(join(root, "src-tauri/target/debug/sumika-desktop.exe"), [], {
  cwd: root, windowsHide: true, stdio: "ignore",
  env: { ...process.env, SUMIKA_CORE_HOST: "127.0.0.1", SUMIKA_CORE_PORT: String(corePort),
    SUMIKA_DESKTOP_DATA_DIR: data, SUMIKA_AGENT_RUNTIME: "none", SUMIKA_AGENT_AUTOSTART: "0",
    SUMIKA_DSH_AUTOSTART: "0", WEBVIEW2_USER_DATA_FOLDER: join(data, "webview"),
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${cdpPort}` },
});
let browser;
let page;
const checks = [];
const record = (name) => { checks.push(name); console.log(`PASS ${name}`); };
async function capture(name, transparent = false) {
  const pixels = PNG.sync.read(await page.locator(".vrm-renderer canvas").screenshot());
  const colors = new Set();
  let clear = 0;
  for (let offset = 0; offset < pixels.data.length; offset += 4) {
    if (pixels.data[offset + 3] === 0) clear++;
    if (offset % 128 === 0) colors.add(`${pixels.data[offset] >> 4},${pixels.data[offset + 1] >> 4},${pixels.data[offset + 2] >> 4}`);
  }
  assert(colors.size > 25, "native scene must have nonblank pixels");
  if (transparent) assert(clear > pixels.width * pixels.height * .2, "transparent pet must contain alpha pixels");
  await page.screenshot({ path: join(evidence, `${name}.png`), omitBackground: true });
}
const nativeSnapshot = () => page.evaluate(async () => {
  const current = window.__TAURI__.window.getCurrentWindow();
  return { label: current.label, mode: await window.__TAURI__.core.invoke("get_display_mode"),
    size: await current.innerSize(), position: await current.outerPosition(),
    maximized: await current.isMaximized(), minimized: await current.isMinimized(),
    decorated: await current.isDecorated(), top: await current.isAlwaysOnTop(),
    scale: await current.scaleFactor(), windows: (await window.__TAURI__.window.getAllWindows()).length };
});
const windowAction = (action) => {
  assert(["maximize", "restore", "move", "close"].includes(action));
  const script = `Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class SmokeWindow { [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hwnd, int command); [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int width, int height, uint flags); [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wparam, IntPtr lparam); }'; $handle = (Get-Process -Id ${child.pid}).MainWindowHandle; if ($handle -eq 0) { throw 'No native window' }; ${action === "move" ? "[SmokeWindow]::SetWindowPos($handle,[IntPtr]::Zero,120,100,0,0,0x15)" : action === "close" ? "[SmokeWindow]::PostMessage($handle,0x10,[IntPtr]::Zero,[IntPtr]::Zero)" : `[SmokeWindow]::ShowWindowAsync($handle,${action === "maximize" ? 3 : 9})`} | Out-Null`;
  execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], { windowsHide: true });
};
try {
  await until(async () => (await fetch(`http://127.0.0.1:${cdpPort}/json/version`)).ok, "WebView2 CDP");
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${cdpPort}`);
  await until(() => browser.contexts()[0]?.pages().length, "main webview");
  page = browser.contexts()[0].pages()[0];
  await page.waitForSelector(".scene-primary-nav");
  const models = await (await fetch(`http://127.0.0.1:${corePort}/api/avatar/models`)).json();
  const sample = models.find((model) => model.kind === "vrm");
  assert(sample, "bundled sample VRM must exist");
  const selection = await (await fetch(`http://127.0.0.1:${corePort}/rpc`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: "isolated-avatar", method: "avatar.select", params: { character_id: "sumika", model_id: sample.id, driver_id: "vrm" } }),
  })).json();
  assert(!selection.error, JSON.stringify(selection.error));
  await page.evaluate(() => localStorage.setItem("sumika.onboarded.v1", "1"));
  await page.reload();
  await page.waitForSelector('[data-vrm-status="ready"]', { timeout: 30000 });
  await until(() => page.locator(".vrm-renderer").getAttribute("data-vrm-render-status").then((status) => status === "running"), "running renderer");
  const original = await nativeSnapshot();
  assert.equal(original.windows, 1);
  assert.equal(original.mode, "workspace");
  const canvas = await page.locator(".vrm-renderer canvas").elementHandle();
  await page.locator("#chat-input").fill("Native isolated draft");
  await until(() => page.locator(".scene-note").innerText().then((value) => value.includes("核心已连接")), "Core connected");
  await capture("native-workspace");
  await page.locator("[data-overlay-open]").click();
  await page.waitForSelector(".desktop-overlay-shell");
  const pet = await nativeSnapshot();
  assert.equal(pet.windows, 1);
  assert.equal(pet.mode, "pet");
  assert.equal(pet.decorated, false);
  assert.equal(pet.top, true);
  assert.equal(Math.round(pet.size.width / pet.scale), 480);
  assert.equal(Math.round(pet.size.height / pet.scale), 420);
  assert.equal(await page.locator("#chat-input").inputValue(), "Native isolated draft");
  assert(await canvas.evaluate((element) => element === document.querySelector(".vrm-renderer canvas")));
  record("one native window, same canvas and draft, borderless 480x420 pet");
  await page.mouse.move(-10, -10);
  await page.evaluate(() => document.activeElement?.blur());
  assert(await page.locator("#chat-input").isEnabled());
  await capture("native-pet");
  await page.locator("[data-pet-background]").focus();
  await page.locator("[data-pet-background]").click();
  await page.mouse.move(-10, -10);
  await page.evaluate(() => document.activeElement?.blur());
  await capture("native-pet-transparent", true);
  record("native opaque and transparent canvas pixels verified");
  windowAction("move");
  const moved = await nativeSnapshot();
  await page.locator("[data-overlay-open-main]").focus();
  await page.locator("[data-overlay-open-main]").click();
  await page.waitForSelector(".scene-primary-nav");
  const restored = await nativeSnapshot();
  assert.deepEqual(restored.size, original.size);
  assert.deepEqual(restored.position, original.position);
  assert(restored.decorated && !restored.top);
  await page.locator("[data-overlay-open]").click();
  await page.waitForSelector(".desktop-overlay-shell");
  assert.deepEqual((await nativeSnapshot()).position, moved.position);
  record("workspace bounds and moved pet bounds restored independently");
  await page.locator("[data-overlay-hide]").focus();
  await page.locator("[data-overlay-hide]").click();
  await until(async () => (await nativeSnapshot()).minimized, "minimized workspace");
  await until(async () => await page.locator(".vrm-renderer").getAttribute("data-vrm-render-status") === "paused", "minimized renderer pause");
  windowAction("restore");
  await until(async () => await page.locator(".vrm-renderer").getAttribute("data-vrm-render-status") === "running", "restored renderer");
  assert.equal(await page.locator("#chat-input").inputValue(), "Native isolated draft");
  record("hidden pet minimizes to workspace, rendering pauses and resumes");
  windowAction("maximize");
  await until(async () => (await nativeSnapshot()).maximized, "maximize");
  await page.locator("[data-overlay-open]").click();
  await page.waitForSelector(".desktop-overlay-shell");
  await page.locator("[data-overlay-open-main]").focus();
  await page.locator("[data-overlay-open-main]").click();
  await page.waitForSelector(".scene-primary-nav");
  assert.equal((await nativeSnapshot()).maximized, true);
  record("maximized workspace restored after pet mode");
  await page.locator('.scene-primary-nav [data-page="Capabilities"]').click();
  await until(async () => await page.locator(".vrm-renderer").getAttribute("data-vrm-render-status") === "paused", "capability renderer pause");
  await page.locator(".capability-add-tile").click();
  await page.screenshot({ path: join(evidence, "native-module-library.png") });
  record("capability library accessible in native WebView2");
  await page.keyboard.press("Escape");
  for (const target of ["Agent", "Characters", "Settings"]) {
    await page.locator(`.scene-primary-nav [data-page="${target}"]`).click();
    await page.screenshot({ path: join(evidence, `native-${target.toLowerCase()}.png`) });
  }
} catch (error) {
  if (page) await page.screenshot({ path: join(evidence, "failure.png") }).catch(() => {});
  await writeFile(join(evidence, "result.json"), JSON.stringify({ passed: false, checks, error: String(error) }, null, 2));
  throw error;
} finally {
  if (child.exitCode === null) {
    try { windowAction("close"); } catch {}
    await until(() => child.exitCode !== null, "native exit", 15000).catch(() => {
      execFileSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true });
    });
  }
  if (browser) await browser.close();
  await until(async () => {
    try { await fetch(`http://127.0.0.1:${corePort}/api/health`); return false; } catch { return true; }
  }, "managed Core cleanup");
  assert(data.startsWith(evidence + "\\") || data.startsWith(evidence + "/"));
  await rm(data, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 });
  console.log(`Evidence: ${evidence}`);
}
record("native process and managed Core exit cleanly; isolated runtime removed");
await writeFile(join(evidence, "result.json"), JSON.stringify({ passed: true, scope: "native UI only; no DSH or model calls", checks }, null, 2));
