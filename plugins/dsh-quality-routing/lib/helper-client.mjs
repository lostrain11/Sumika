import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { createInterface } from "node:readline";

const METHODS = new Set(["health", "capabilities", "offline_fixture", "shutdown"]);

function helperEnvironment() {
  const environment = {
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1"
  };
  for (const key of ["SystemRoot", "WINDIR", "TEMP", "TMP"]) {
    if (process.env[key]) environment[key] = process.env[key];
  }
  return environment;
}

class ManagedQualityHelper {
  constructor(config) {
    this.config = config;
    this.process = null;
    this.reader = null;
    this.pending = new Map();
    this.nextId = 1;
    this.stderr = "";
    this.starting = null;
  }

  async start() {
    if (this.process && this.process.exitCode === null) return;
    if (this.starting) return this.starting;
    this.starting = this._start();
    try {
      await this.starting;
    } finally {
      this.starting = null;
    }
  }

  async _start() {
    mkdirSync(this.config.dataDirectory, { recursive: true });
    const child = spawn(
      this.config.pythonExecutable,
      ["-m", "quality_routing.dsh_helper", "--data-dir", this.config.dataDirectory],
      {
        cwd: this.config.dataDirectory,
        env: helperEnvironment(),
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true
      }
    );
    this.process = child;
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", chunk => {
      this.stderr = (this.stderr + chunk).slice(-8000);
    });
    this.reader = createInterface({ input: child.stdout, crlfDelay: Infinity });
    this.reader.on("line", line => this._handleLine(line));
    child.once("error", error => this._failAll(error));
    child.once("exit", code => {
      this._failAll(new Error(`quality-routing helper exited with code ${code}: ${this.stderr}`));
      this.process = null;
    });
    try {
      await this._call("health", {}, this.config.startupTimeoutMs);
    } catch (error) {
      child.kill();
      throw error;
    }
  }

  _handleLine(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      this._failAll(new Error("quality-routing helper returned invalid JSON"));
      return;
    }
    const request = this.pending.get(message.id);
    if (!request) return;
    clearTimeout(request.timer);
    this.pending.delete(message.id);
    if (typeof message.error === "string") request.reject(new Error(message.error));
    else request.resolve(message.result);
  }

  _failAll(error) {
    for (const request of this.pending.values()) {
      clearTimeout(request.timer);
      request.reject(error);
    }
    this.pending.clear();
  }

  _call(method, params, timeoutMs) {
    if (!METHODS.has(method)) return Promise.reject(new Error("unsupported helper method"));
    const child = this.process;
    if (!child || child.exitCode !== null || !child.stdin.writable) {
      return Promise.reject(new Error("quality-routing helper is not running"));
    }
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`quality-routing helper request timed out: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      child.stdin.write(`${JSON.stringify({ id, method, params })}\n`, error => {
        if (!error) return;
        clearTimeout(timer);
        this.pending.delete(id);
        reject(error);
      });
    });
  }

  async call(method) {
    await this.start();
    return this._call(method, {}, this.config.requestTimeoutMs);
  }

  async close() {
    const child = this.process;
    if (!child || child.exitCode !== null) return;
    try {
      await this._call("shutdown", {}, Math.min(this.config.requestTimeoutMs, 2000));
    } catch {
      child.kill();
      return;
    }
    child.stdin.end();
    if (child.exitCode === null) {
      await Promise.race([
        new Promise(resolve => child.once("exit", resolve)),
        new Promise(resolve => setTimeout(resolve, 2000))
      ]);
    }
    if (child.exitCode === null) child.kill();
  }
}

export { ManagedQualityHelper, helperEnvironment };

