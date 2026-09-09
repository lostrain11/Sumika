import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { once } from "node:events";
import {
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { createServer } from "node:net";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../../frontend/node_modules/playwright-core/index.mjs";

const root = fileURLToPath(new URL("../..", import.meta.url));
const executable = join(root, "src-tauri", "target", "debug", "sumika-desktop.exe");
const evidence = resolve(
  process.argv[2] || "D:/Caches/sumika-consultation-smoke",
  String(Date.now()),
);
await mkdir(evidence, { recursive: true });
const dataDir = await mkdtemp(join(evidence, "runtime-"));
const delay = (milliseconds) => new Promise((done) => setTimeout(done, milliseconds));

async function freePort() {
  const server = createServer().listen(0, "127.0.0.1");
  await once(server, "listening");
  const value = server.address().port;
  await new Promise((done) => server.close(done));
  return value;
}

async function until(check, label, timeout = 45000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const value = await check();
      if (value) return value;
    } catch {}
    await delay(200);
  }
  throw new Error(`Timed out: ${label}`);
}

async function connectWebview(port, pageLabel) {
  await until(async () => {
    const response = await fetch(`http://127.0.0.1:${port}/json/version`);
    return response.ok;
  }, `${pageLabel} CDP`);
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  const page = await until(
    () => browser.contexts().flatMap((context) => context.pages())[0],
    pageLabel,
  );
  return { browser, page, port };
}

function terminateTree(desktop) {
  if (desktop.exitCode !== null) return;
  execFileSync("taskkill.exe", ["/PID", String(desktop.pid), "/T", "/F"], {
    windowsHide: true,
    stdio: "ignore",
  });
}

function captureNative(desktop, path) {
  const outputPath = resolve(path).replaceAll("'", "''");
  const script = [
    "Add-Type -AssemblyName System.Drawing",
    `$process = Get-Process -Id ${desktop.pid}`,
    "$handle = $process.MainWindowHandle",
    "if ($handle -eq 0) { throw 'No native main window' }",
    "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class SumikaSmokeRect { [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; } [DllImport(\"user32.dll\")] public static extern bool GetWindowRect(IntPtr hwnd, out RECT rect); }'",
    "$rect = New-Object SumikaSmokeRect+RECT",
    "if (-not [SumikaSmokeRect]::GetWindowRect($handle, [ref]$rect)) { throw 'GetWindowRect failed' }",
    "$width = $rect.Right - $rect.Left",
    "$height = $rect.Bottom - $rect.Top",
    "$bitmap = New-Object System.Drawing.Bitmap($width, $height)",
    "$graphics = [System.Drawing.Graphics]::FromImage($bitmap)",
    "$graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)",
    `$bitmap.Save('${outputPath}', [System.Drawing.Imaging.ImageFormat]::Png)`,
    "$graphics.Dispose()",
    "$bitmap.Dispose()",
  ].join("; ");
  execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
    windowsHide: true,
    stdio: "ignore",
  });
}

async function launch(corePort) {
  const mainCdpPort = await freePort();
  const desktop = spawn(executable, [], {
    cwd: root,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      SUMIKA_CORE_HOST: "127.0.0.1",
      SUMIKA_CORE_PORT: String(corePort),
      SUMIKA_DESKTOP_DATA_DIR: dataDir,
      SUMIKA_AGENT_RUNTIME: "none",
      SUMIKA_AGENT_AUTOSTART: "0",
      SUMIKA_DSH_AUTOSTART: "0",
      WEBVIEW2_USER_DATA_FOLDER: join(dataDir, "main-webview"),
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${mainCdpPort}`,
    },
  });
  launchingDesktop = desktop;
  const output = [];
  desktop.stdout.on("data", (chunk) => output.push(chunk.toString()));
  desktop.stderr.on("data", (chunk) => output.push(chunk.toString()));
  try {
    const main = await connectWebview(mainCdpPort, "main webview");
    await main.page.waitForFunction(() => Boolean(window.__TAURI__?.core?.invoke));
    launchingDesktop = undefined;
    return { desktop, main, output };
  } catch (error) {
    error.desktopExitCode = desktop.exitCode;
    error.desktopOutput = output.join("").slice(0, 4096);
    throw error;
  }
}

async function invoke(page, command, args = {}) {
  return page.evaluate(
    ({ command, args }) => window.__TAURI__.core.invoke(command, args),
    { command, args },
  );
}

const metadata = { passed: false, checks: [], cycles: [] };
let active;
let launchingDesktop;
try {
  active = await launch(await freePort());
  const core = await invoke(active.main.page, "core_status");
  const displayMode = await invoke(active.main.page, "get_display_mode");
  assert.equal(core.running, true);
  assert.equal(displayMode, "workspace");
  metadata.checks.push("main core_status and get_display_mode authorized");

  const opened = await invoke(active.main.page, "consultation_open");
  assert.notEqual(opened.status, "closed");
  await invoke(active.main.page, "consultation_set_bounds", {
    x: 24,
    y: 36,
    width: 620,
    height: 480,
  });
  const probe = await until(async () => {
    try {
      return await invoke(active.main.page, "consultation_smoke_probe");
    } catch (error) {
      if (String(error).includes("about:blank")) return null;
      throw error;
    }
  }, "consultation child initial navigation");
  assert.equal(probe.label, "consultation-chatgpt");
  assert.equal(Math.round(probe.width / probe.scale_factor), 620, JSON.stringify(probe));
  assert.equal(Math.round(probe.height / probe.scale_factor), 480, JSON.stringify(probe));
  metadata.checks.push("child webview exists with requested bounds");

  assert(["api-absent", "rejected"].includes(probe.remote_ipc), JSON.stringify(probe));
  assert.equal(probe.remote_core_fetch, "rejected", JSON.stringify(probe));
  metadata.checks.push(`remote child IPC blocked (${probe.remote_ipc})`);
  metadata.checks.push("remote child Core fetch rejected by CORS");
  captureNative(active.desktop, join(evidence, "consultation-open.png"));

  await invoke(active.main.page, "consultation_hide");
  const hidden = await invoke(active.main.page, "consultation_action", {
    operation: "status",
    attemptId: null,
    text: null,
  });
  assert.equal(hidden.status, "hidden");
  await invoke(active.main.page, "consultation_open");
  const takeover = await invoke(active.main.page, "consultation_action", {
    operation: "takeover",
    attemptId: null,
    text: null,
  });
  assert.equal(takeover.status, "takeover");
  const released = await invoke(active.main.page, "consultation_action", {
    operation: "release",
    attemptId: null,
    text: null,
  });
  assert.notEqual(released.status, "takeover");
  metadata.checks.push("hide, reopen, takeover, and explicit release function");

  metadata.cycles.push({
    phase: "before-crash",
    mainUrl: active.main.page.url(),
    probe,
  });

  await active.main.browser.close();
  terminateTree(active.desktop);
  await until(() => active.desktop.exitCode !== null, "first process crash termination", 15000);
  active = undefined;

  active = await launch(await freePort());
  const reopened = await invoke(active.main.page, "consultation_open");
  assert.notEqual(reopened.status, "closed");
  const recoveredProbe = await until(async () => {
    try {
      return await invoke(active.main.page, "consultation_smoke_probe");
    } catch (error) {
      if (String(error).includes("about:blank")) return null;
      throw error;
    }
  }, "consultation child navigation after crash");
  assert.equal(recoveredProbe.label, "consultation-chatgpt");
  metadata.checks.push("profile lease recovered after forced owner termination");
  metadata.cycles.push({
    phase: "after-crash",
    mainUrl: active.main.page.url(),
    probe: recoveredProbe,
  });
  await invoke(active.main.page, "consultation_close");
  metadata.passed = true;
} catch (error) {
  metadata.error = String(error);
  metadata.desktopExitCode = error.desktopExitCode;
  metadata.desktopOutput = error.desktopOutput;
  throw error;
} finally {
  if (launchingDesktop) {
    try {
      terminateTree(launchingDesktop);
    } catch {}
  }
  if (active) {
    await active.main.browser.close().catch(() => {});
    try {
      terminateTree(active.desktop);
    } catch {}
  }
  const desktopLog = await readFile(join(dataDir, "logs", "desktop.log"), "utf8").catch(
    () => null,
  );
  if (desktopLog !== null) {
    await writeFile(join(evidence, "desktop.log"), desktopLog);
  }
  await writeFile(join(evidence, "result.json"), JSON.stringify(metadata, null, 2));
  assert(
    dataDir.startsWith(`${evidence}\\`) || dataDir.startsWith(`${evidence}/`),
    "isolated runtime path escaped evidence directory",
  );
  await rm(dataDir, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 });
  console.log(`Evidence: ${evidence}`);
}
