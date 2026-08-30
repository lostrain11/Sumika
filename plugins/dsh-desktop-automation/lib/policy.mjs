import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";

export const DESKTOP_TOOLS = Object.freeze({
  desktop_app_catalog: "catalog",
  desktop_app_open: "open",
  desktop_app_observe: "observe",
  desktop_app_act: "act",
  desktop_app_close: "close",
  desktop_app_takeover: "takeover",
  desktop_automation_approval: "approval"
});

const LOOPBACK_RE = /^(?:localhost|127(?:\.\d{1,3}){3}|\[?::1\]?)$/i;
const IDENTIFIER_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/;
const SECRET_RE = /(?:sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{8,}|(?:api[_ -]?key|token|password|secret|cookie|otp|private[_ -]?key)\s*[:=]\s*[^\s,;]+)/i;
const SENSITIVE_KEY_RE = /(?:password|passwd|passcode|otp|secret|token|api[-_ ]?key|authorization|cookie|credential|private[-_ ]?key)/i;

export function resolvePolicyEndpoint(configuredEndpoint, environment = (typeof process !== "undefined" ? process.env : {})) {
  const configured = typeof configuredEndpoint === "string" ? configuredEndpoint.trim() : "";
  if (configured) return configured;
  const fromEnvironment = typeof environment?.SUMIKA_CORE_ENDPOINT === "string" ? environment.SUMIKA_CORE_ENDPOINT.trim() : "";
  if (fromEnvironment) return fromEnvironment;
  const host = typeof environment?.SUMIKA_CORE_HOST === "string" && environment.SUMIKA_CORE_HOST.trim() ? environment.SUMIKA_CORE_HOST.trim() : "127.0.0.1";
  const port = Number(environment?.SUMIKA_CORE_PORT || 8771);
  if (Number.isInteger(port) && port > 0 && port <= 65535) {
    const authority = host.includes(":") && !host.startsWith("[") ? `[${host}]` : host;
    return `http://${authority}:${port}/rpc`;
  }
  return "http://127.0.0.1:8771/rpc";
}

function loopbackEndpoint(endpoint) {
  let parsed;
  try { parsed = new URL(endpoint); } catch { throw new Error("policy endpoint is invalid"); }
  if (!["http:", "https:"].includes(parsed.protocol) || !LOOPBACK_RE.test(parsed.hostname)) throw new Error("policy endpoint must be loopback-only");
  if (!parsed.pathname || parsed.pathname === "/") parsed.pathname = "/rpc";
  return parsed;
}

export function isDesktopToolName(value) {
  return typeof value === "string" && value.startsWith("desktop_");
}

export function looksLikeSecretText(value) {
  return typeof value === "string" && SECRET_RE.test(value);
}

export function containsSensitive(value, depth = 0) {
  if (depth > 5) return false;
  if (typeof value === "string") return looksLikeSecretText(value);
  if (Array.isArray(value)) return value.slice(0, 96).some((item) => containsSensitive(item, depth + 1));
  if (!value || typeof value !== "object") return false;
  return Object.entries(value).slice(0, 96).some(([key, item]) => SENSITIVE_KEY_RE.test(key) || containsSensitive(item, depth + 1));
}

export function buildDesktopMetadata(exec) {
  const name = typeof exec?.name === "string" ? exec.name : "";
  const action = DESKTOP_TOOLS[name];
  if (!action) return null;
  const args = exec?.arguments && typeof exec.arguments === "object" && !Array.isArray(exec.arguments) ? exec.arguments : {};
  const appId = args.app_id ?? args.appId ?? null;
  const sessionId = args.session_id ?? args.sessionId ?? null;
  if (appId !== null && (!IDENTIFIER_RE.test(String(appId)) || String(appId).length > 160)) throw new Error("app_id is invalid");
  if (sessionId !== null && (!IDENTIFIER_RE.test(String(sessionId)) || String(sessionId).length > 160)) throw new Error("session_id is invalid");
  return {
    tool_name: name,
    action,
    app_id: appId === null ? null : String(appId),
    session_id: sessionId === null ? null : String(sessionId),
    sensitive: containsSensitive(args),
    argument_count: Object.keys(args).length
  };
}

export async function gateDesktopTool(exec, next) {
  if (!exec || typeof exec.name !== "string") return next();
  if (!isDesktopToolName(exec.name)) return next();
  if (!DESKTOP_TOOLS[exec.name]) return { kind: "deny", reason: "unsupported desktop tool; Sumika mapping is required" };
  try {
    const metadata = buildDesktopMetadata(exec);
    if (metadata.sensitive) return { kind: "deny", reason: "credential-shaped desktop input must be entered by the user in the application window" };
  } catch (error) {
    return { kind: "deny", reason: error instanceof Error ? error.message : "invalid desktop arguments" };
  }
  return next();
}

function safeResult(value, depth = 0) {
  if (depth > 5) return "[truncated]";
  if (typeof value === "string") return looksLikeSecretText(value) ? "[redacted]" : value.slice(0, 16000);
  if (value === null || typeof value === "boolean" || typeof value === "number") return value;
  if (Array.isArray(value)) return value.slice(0, 96).map((item) => safeResult(item, depth + 1));
  if (value && typeof value === "object") {
    const result = {};
    for (const [key, item] of Object.entries(value).slice(0, 96)) {
      if (SENSITIVE_KEY_RE.test(key) || /(?:path|file|directory|executable|launcher)/i.test(key)) result[key] = "[redacted]";
      else result[key] = safeResult(item, depth + 1);
    }
    return result;
  }
  return String(value).slice(0, 16000);
}

export function postJson(endpoint, payload, { timeoutMs = 1500, signal } = {}) {
  const parsed = loopbackEndpoint(endpoint);
  const body = JSON.stringify(payload);
  if (body.length > 256 * 1024) return Promise.reject(new Error("policy request is too large"));
  const transport = parsed.protocol === "https:" ? httpsRequest : httpRequest;
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      if (signal) signal.removeEventListener("abort", onAbort);
      error ? reject(error) : resolve(value);
    };
    const onAbort = () => { req.destroy(); finish(new Error("desktop policy request aborted")); };
    const req = transport({
      hostname: parsed.hostname.replace(/^\[|\]$/g, ""),
      port: parsed.port || undefined,
      path: `${parsed.pathname}${parsed.search}`,
      method: "POST",
      headers: { "content-type": "application/json", "content-length": Buffer.byteLength(body) }
    }, (response) => {
      let text = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { text += chunk; if (text.length > 256 * 1024) response.destroy(new Error("desktop policy response is too large")); });
      response.on("error", () => finish(new Error("desktop policy response failed")));
      response.on("end", () => {
        if (response.statusCode < 200 || response.statusCode >= 300) return finish(new Error(`desktop policy endpoint returned HTTP ${response.statusCode}`));
        try {
          const parsedBody = JSON.parse(text);
          if (parsedBody?.error) return finish(new Error("desktop policy endpoint rejected the request"));
          finish(null, safeResult(parsedBody?.result ?? parsedBody));
        } catch { finish(new Error("desktop policy endpoint returned invalid JSON")); }
      });
    });
    req.on("error", () => finish(new Error("desktop policy endpoint unavailable")));
    timer = setTimeout(() => { req.destroy(); finish(new Error("desktop policy endpoint timed out")); }, Math.max(100, Number(timeoutMs) || 1500));
    if (signal) { if (signal.aborted) return onAbort(); signal.addEventListener("abort", onAbort, { once: true }); }
    req.write(body); req.end();
  });
}

export class DesktopPolicyClient {
  constructor({ endpoint, timeoutMs = 1500, post = postJson } = {}) {
    this.endpoint = resolvePolicyEndpoint(endpoint);
    this.timeoutMs = timeoutMs;
    this.post = post;
  }

  call(method, params = {}, signal) {
    return this.post(this.endpoint, {
      jsonrpc: "2.0",
      id: `desktop-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      method,
      params
    }, { timeoutMs: this.timeoutMs, signal });
  }
}
