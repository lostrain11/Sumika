import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { once } from "node:events";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../../frontend/node_modules/playwright-core/index.mjs";

const root = fileURLToPath(new URL("../..", import.meta.url));
const directory = resolve(process.argv[2] || "D:/Caches/sumika-embedded-smoke", String(Date.now()));
await mkdir(directory, { recursive: true });
const data = join(directory, "runtime");
const delay = (duration) => new Promise((done) => setTimeout(done, duration));
async function freePort() {
  const server = createServer().listen(0, "127.0.0.1");
  await once(server, "listening");
  const port = server.address().port;
  await new Promise((done) => server.close(done));
  return port;
}
async function until(check, timeout = 45000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try { const value = await check(); if (value) return value; } catch {}
    await delay(200);
  }
  throw new Error("native-smoke-timeout");
}
const cdp = await freePort();
const child = spawn(join(root, "src-tauri/target/debug/sumika-desktop.exe"), [], {
  cwd: root, windowsHide: true, stdio: "ignore", env: { ...process.env,
    SUMIKA_CORE_HOST: "127.0.0.1", SUMIKA_CORE_PORT: String(await freePort()),
    SUMIKA_DESKTOP_DATA_DIR: data, SUMIKA_AGENT_RUNTIME: "none", SUMIKA_AGENT_AUTOSTART: "0",
    SUMIKA_DSH_AUTOSTART: "0", SUMIKA_SMOKE_MAIN_DATA_DIR: join(data, "main-webview"),
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${cdp}` },
});
let browser;
const report = { passed: false, checks: [], model_calls: 0 };
try {
  await until(async () => (await fetch(`http://127.0.0.1:${cdp}/json/version`)).ok);
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${cdp}`);
  const page = await until(() => browser.contexts().flatMap((context) => context.pages())[0]);
  await page.waitForFunction(() => !!window.__TAURI__?.core?.invoke);
  const invoke = (command, args = {}) => page.evaluate(({ command, args }) => window.__TAURI__.core.invoke(command, args), { command, args });
  await page.evaluate(() => localStorage.setItem("sumika.onboarded.v1", "1"));
  await page.reload();
  await page.waitForFunction(() => !!window.__TAURI__?.core?.invoke);
  await page.locator("[data-portal-panel]").click();
  await page.locator('[data-embedded-site="chatgpt"]').click();
  const tabs = await until(async () => {
    const rows = await invoke("embedded_browser_list");
    return rows.some((row) => row.tab_id === "chatgpt" && row.visible) && rows;
  });
  assert.equal(tabs.find((row) => row.tab_id === "chatgpt").site_id, "chatgpt");
  report.checks.push("portal-login-directory-reused", "native-child-visible-inside-workspace");
  await page.screenshot({ path: join(directory, "workspace-controls.png") });
  await assert.rejects(invoke("embedded_browser_open", { tabId: "blocked", accountId: "blocked", url: "https://127.0.0.1/", title: "blocked" }));
  await assert.rejects(invoke("embedded_browser_open", { tabId: "wrong-legacy", accountId: "second", legacySiteId: "chatgpt", url: "https://chatgpt.com/", title: "blocked" }));
  await assert.rejects(invoke("embedded_browser_action", { tabId: "chatgpt", action: "evaluate", text: "arbitrary" }));
  report.checks.push("local-url-and-arbitrary-eval-rejected");
  const takeover = await invoke("embedded_browser_action", { tabId: "chatgpt", action: "takeover" });
  assert.equal(takeover.tab.takeover, true);
  await assert.rejects(invoke("embedded_browser_action", { tabId: "chatgpt", action: "fill", attemptId: "must-not-send", text: "synthetic fixture" }));
  await invoke("embedded_browser_action", { tabId: "chatgpt", action: "release" });
  report.checks.push("takeover-blocks-writes");
  const second = await invoke("embedded_browser_open", { tabId: "chatgpt-second", accountId: "second", url: "https://chatgpt.com/", title: "Second account" });
  assert.notEqual(second.profile_id, tabs[0].profile_id);
  assert.equal(second.visible, false);
  assert.equal((await invoke("embedded_browser_list")).filter((row) => row.visible).length, 1);
  report.checks.push("account-storage-isolated", "background-open-does-not-steal-viewport");
  await page.getByRole("button", { name: "返回客户端" }).click();
  assert.equal((await invoke("embedded_browser_list")).filter((row) => row.visible).length, 0);
  await invoke("set_display_mode", { mode: "pet" });
  await assert.rejects(invoke("embedded_browser_action", { tabId: "chatgpt", action: "observe" }));
  await invoke("set_display_mode", { mode: "workspace" });
  report.checks.push("hidden-viewport-stops-visibility", "pet-mode-stops-automation");
  await invoke("embedded_browser_close", { tabId: "chatgpt" });
  await invoke("embedded_browser_close", { tabId: "chatgpt-second" });
  report.passed = true;
} catch (error) {
  report.error = String(error).slice(0, 1600);
} finally {
  await browser?.close().catch(() => {});
  if (child.exitCode === null) execFileSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
  await writeFile(join(directory, "result.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ ...report, evidence: directory }));
}
if (!report.passed) process.exitCode = 1;
