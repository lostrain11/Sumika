#!/usr/bin/env node

/**
 * Run the browser smoke suite against a throwaway in-memory Core.
 *
 * The normal development server uses .sumika, which is intentionally not
 * touched by this runner. A fresh TCP port also avoids attaching tests to a
 * user's already-running Core instance.
 */

import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { once } from "node:events";
import process from "node:process";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(?:([A-Za-z]):)/, "$1:");
const repoRoot = root.endsWith("/") || root.endsWith("\\") ? root.slice(0, -1) : root;

function pythonCandidates() {
  const configured = String(process.env.SUMIKA_PYTHON || "").trim();
  return configured ? [configured] : process.platform === "win32" ? ["python.exe", "python"] : ["python3", "python"];
}

async function freePort() {
  const server = createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  await new Promise((resolve) => server.close(resolve));
  if (!port) throw new Error("could not allocate an isolated test port");
  return port;
}

async function waitForCore(url, child) {
  const deadline = Date.now() + 15000;
  let lastError = "not ready";
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`Sumika Core exited before health check (${child.exitCode})`);
    try {
      const response = await fetch(`${url}/api/health`);
      const body = await response.json();
      if (response.ok && body?.ok === true) return;
      lastError = `HTTP ${response.status}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`timed out waiting for isolated Sumika Core: ${lastError}`);
}

async function spawnCore(port) {
  const args = [
    "-u",
    "-m",
    "sumika_core",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
    "--data-dir",
    ":memory:",
  ];
  const environment = {
    ...process.env,
    PYTHONPATH: `${repoRoot}/backend/src`,
    SUMIKA_DATA_DIR: ":memory:",
    // Browser tests provide explicit Agent protocol fixtures. Never let the
    // throwaway Core attach to a developer's live DSH session roster.
    SUMIKA_AGENT_RUNTIME: "none",
    SUMIKA_AGENT_AUTOSTART: "0",
  };
  let lastError;
  for (const executable of pythonCandidates()) {
    const child = spawn(executable, args, {
      cwd: repoRoot,
      env: environment,
      stdio: "inherit",
      windowsHide: true,
    });
    const errorPromise = once(child, "error").then(([error]) => error);
    const result = await Promise.race([
      errorPromise,
      new Promise((resolve) => setTimeout(() => resolve(null), 100)),
    ]);
    if (!result) return child;
    lastError = result;
  }
  throw new Error(`Python was not found; set SUMIKA_PYTHON to an executable path (${lastError?.message || "unknown error"})`);
}

async function run() {
  const port = await freePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const core = await spawnCore(port);
  let exitCode = 1;
  try {
    await waitForCore(baseUrl, core);
    // Invoke the checked-in Playwright CLI through the current Node runtime.
    // Spawning a .cmd shim is not portable to constrained Windows shells and
    // can fail with EINVAL before Playwright gets a chance to report errors.
    const cliPath = `${repoRoot}/frontend/node_modules/@playwright/test/cli.js`;
    const test = spawn(process.execPath, [cliPath, "test", ...process.argv.slice(2)], {
      cwd: `${repoRoot}/frontend`,
      env: {
        ...process.env,
        SUMIKA_BASE_URL: `${baseUrl}/`,
        SUMIKA_TEST_ISOLATED: "1",
      },
      stdio: "inherit",
      windowsHide: true,
    });
    const [status] = await once(test, "exit");
    exitCode = typeof status === "number" ? status : 1;
  } finally {
    if (core.exitCode === null) {
      core.kill();
      await Promise.race([once(core, "exit"), new Promise((resolve) => setTimeout(resolve, 2000))]);
    }
  }
  process.exitCode = exitCode;
}

run().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
