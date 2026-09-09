import { spawn, execFileSync } from "node:child_process";
import { createServer } from "node:net";
import { once } from "node:events";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join, resolve } from "node:path";
import { chromium } from "../frontend/node_modules/playwright-core/index.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const directory = resolve(process.argv[2] || "D:/Caches/sumika-login-probe", String(Date.now()));
await mkdir(directory, { recursive: true });
async function freePort() {
  const server = createServer().listen(0, "127.0.0.1");
  await once(server, "listening");
  const port = server.address().port;
  await new Promise((done) => server.close(done));
  return port;
}
const pause = (milliseconds) => new Promise((done) => setTimeout(done, milliseconds));
const debugPort = await freePort();
const environment = { ...process.env, SUMIKA_CORE_HOST: "127.0.0.1", SUMIKA_CORE_PORT: String(await freePort()),
  SUMIKA_DESKTOP_DATA_DIR: join(directory, "runtime"), SUMIKA_SMOKE_MAIN_DATA_DIR: join(directory, "main"),
  SUMIKA_AGENT_RUNTIME: "none", SUMIKA_AGENT_AUTOSTART: "0", SUMIKA_DSH_AUTOSTART: "0",
  WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${debugPort}` };
delete environment.WEBVIEW2_USER_DATA_FOLDER;
const child = spawn(join(root, "src-tauri/target/debug/sumika-desktop.exe"), [], {
  cwd: root, env: environment, windowsHide: true, stdio: ["ignore", "ignore", "pipe"],
});
let startupError = "";
child.stderr.on("data", (chunk) => { startupError = (startupError + chunk.toString()).slice(0, 1000); });
const report = { model_calls: 0, credentials_entered: false, isolated: true, observations: [] };
let browser;
try {
  report.step = "connect";
  for (let attempt = 0; attempt < 60; attempt++) {
    if (child.exitCode !== null) throw new Error(`isolated-client-exited: ${child.exitCode}; ${startupError}`);
    try { if ((await fetch(`http://127.0.0.1:${debugPort}/json/version`)).ok) break; } catch {}
    await pause(500);
  }
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${debugPort}`, { timeout: 10000 });
  const page = browser.contexts().flatMap((context) => context.pages()).find((page) => new URL(page.url()).hostname === "tauri.localhost");
  await page.waitForFunction(() => !!window.__TAURI__?.core?.invoke);
  const invoke = (operation) => page.evaluate((operation) => window.__TAURI__.core.invoke("consultation_action", { operation }), operation);
  report.step = "open-workspace";
  await page.locator("[data-portal-panel]").click();
  report.step = "open-consultation";
  await page.locator('[data-embedded-tab="native-consultation"]').click();
  await pause(3000);
  for (const stage of ["homepage", "login"]) {
    report.step = stage;
    if (stage === "login") await invoke("login");
    for (let attempt = 0; attempt < 6; attempt++) {
      await pause(2000);
      const current = await invoke("status");
      report.observations.push({ stage, status: current.status, reason: current.reason, navigation: current.navigation });
    }
  }
  report.finished = true;
} catch (error) {
  report.finished = false;
  report.error_type = error.name;
  report.exit_code = child.exitCode;
  report.error = String(error.message).replace(/https?:\/\/[^\s"'<>]+/g, (url) => {
    try { return new URL(url).origin; } catch { return "[url]"; }
  }).slice(0, 600);
} finally {
  await browser?.close().catch(() => {});
  if (child.exitCode === null) execFileSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
  await writeFile(join(directory, "result.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ ...report, evidence: directory }));
}
if (!report.finished) process.exitCode = 1;
