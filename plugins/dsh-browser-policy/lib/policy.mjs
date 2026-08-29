import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";

export const TOOL_ACTIONS = Object.freeze({
  browser_session_start: "session_start",
  browser_session_stop: "session_stop",
  browser_session_list: "session_list",
  browser_navigate: "navigate",
  browser_snapshot: "snapshot",
  browser_observe: "observe",
  browser_click: "click",
  browser_fill: "fill",
  browser_press: "press",
  browser_screenshot: "screenshot",
  browser_emulate: "emulate",
  browser_request_help: "request_help"
});

/** Browser tools are a closed policy surface, even when another plugin adds one. */
export function isBrowserToolName(value) {
  return typeof value === "string" && value.startsWith("browser_");
}

const SECRET_RE = /(?:sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{8,}|(?:api[_ -]?key|token|password|secret|otp)\s*[:=]\s*[^\s,;]+)/i;
const SESSION_RE = /^[A-Za-z0-9._:-]{1,160}$/;
const LOOPBACK_RE = /^(?:localhost|127(?:\.\d{1,3}){3}|\[?::1\]?)$/i;
export const DEFAULT_POLICY_ENDPOINT = "http://127.0.0.1:8771/rpc";

export function resolvePolicyEndpoint(configuredEndpoint, environment = (typeof process !== "undefined" ? process.env : {})) {
  const configured = typeof configuredEndpoint === "string" ? configuredEndpoint.trim() : "";
  if (configured) return configured;
  const fromEnvironment = typeof environment?.SUMIKA_CORE_ENDPOINT === "string" ? environment.SUMIKA_CORE_ENDPOINT.trim() : "";
  if (fromEnvironment) return fromEnvironment;
  const host = typeof environment?.SUMIKA_CORE_HOST === "string" && environment.SUMIKA_CORE_HOST.trim()
    ? environment.SUMIKA_CORE_HOST.trim()
    : "127.0.0.1";
  const port = Number(environment?.SUMIKA_CORE_PORT || 8771);
  if (Number.isInteger(port) && port > 0 && port <= 65535) {
    const authority = host.includes(":") && !host.startsWith("[") ? `[${host}]` : host;
    return `http://${authority}:${port}/rpc`;
  }
  return DEFAULT_POLICY_ENDPOINT;
}

export function looksLikeSecretText(value) {
  return typeof value === "string" && SECRET_RE.test(value);
}

export function normalizeHost(value) {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value !== "string") throw new Error("domain must be text or null");
  let host = value.trim().toLowerCase().replace(/\.$/, "");
  if (!host || host.length > 253 || /[\s\u0000-\u001f\u007f\/?#@]/.test(host)) throw new Error("domain is invalid");
  if (host.startsWith("[") && host.endsWith("]")) host = host.slice(1, -1);
  if (host.includes(":")) {
    if (!/^[0-9a-f:]+$/i.test(host)) throw new Error("domain is invalid");
    return host;
  }
  if (!/^[a-z0-9\u0080-\uffff](?:[a-z0-9\u0080-\uffff-]{0,61}[a-z0-9\u0080-\uffff])?(?:\.[a-z0-9\u0080-\uffff](?:[a-z0-9\u0080-\uffff-]{0,61}[a-z0-9\u0080-\uffff])?)*$/i.test(host)) throw new Error("domain is invalid");
  return host;
}

export function domainFromUrl(value) {
  if (typeof value !== "string" || value.trim().length === 0) throw new Error("url must be a non-empty string");
  const raw = value.trim();
  if (raw.length > 4096) throw new Error("url is too long");
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("url is invalid");
  }
  if (parsed.protocol === "chrome:" && parsed.hostname === "newtab" && parsed.pathname === "/" && !parsed.search && !parsed.hash) return { domain: null, newTab: true };
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error("url must be http(s) or chrome://newtab/");
  if (parsed.username || parsed.password) throw new Error("url must not contain embedded credentials");
  return { domain: normalizeHost(parsed.hostname), newTab: false };
}

export function classifyTarget(value) {
  if (value === undefined || value === null || String(value).trim() === "") return "none";
  if (typeof value !== "string") throw new Error("target must be text or null");
  const target = value.trim();
  if (/^@?e\d+$/i.test(target)) return "snapshot_ref";
  if (/^[#\.\[:]/.test(target)) return "css_selector";
  return "unknown";
}

export class SessionState {
  constructor() {
    this.sessions = new Set();
    this.domains = new Map();
    this.currentSession = null;
  }

  resolve(explicit) {
    const candidate = explicit === undefined || explicit === null || String(explicit).trim() === "" ? this.currentSession : String(explicit).trim();
    return candidate || null;
  }

  remember(sessionId, url) {
    if (typeof sessionId !== "string" || !SESSION_RE.test(sessionId.trim())) return;
    const id = sessionId.trim();
    this.sessions.add(id);
    this.currentSession = id;
    if (typeof url === "string" && url.trim()) {
      try {
        const parsed = domainFromUrl(url);
        this.domains.set(id, parsed.domain);
      } catch {
        // A backend result is untrusted metadata; ignore malformed URLs.
      }
    }
  }

  forget(sessionId) {
    if (typeof sessionId !== "string") return;
    const id = sessionId.trim();
    this.sessions.delete(id);
    this.domains.delete(id);
    if (this.currentSession === id) this.currentSession = [...this.sessions].at(-1) ?? null;
  }

  observeResult(toolName, result) {
    if (!result || result.isError === true || typeof result.value !== "object" || result.value === null) return;
    const value = result.value;
    if (toolName === "browser_session_start") {
      this.remember(value.sessionId ?? value.session, value.url);
      return;
    }
    if (toolName === "browser_session_stop") {
      this.forget(value.stopped ?? value.session ?? value.sessionId);
      return;
    }
    if (toolName === "browser_session_list" && Array.isArray(value.sessions)) {
      let markedCurrent = null;
      for (const entry of value.sessions) {
        if (!entry || typeof entry.sessionId !== "string" || !SESSION_RE.test(entry.sessionId.trim())) continue;
        const id = entry.sessionId.trim();
        this.sessions.add(id);
        if (entry.current === true) markedCurrent = id;
      }
      if (markedCurrent !== null) this.currentSession = markedCurrent;
      return;
    }
    const sessionId = value.session ?? value.sessionId;
    if (typeof sessionId === "string") {
      if (!this.sessions.has(sessionId)) return;
      this.currentSession = sessionId;
      const url = value.finalUrl ?? value.final_url ?? value.url;
      if (typeof url === "string" && url.trim()) {
        try {
          const parsed = domainFromUrl(url);
          this.domains.set(sessionId, parsed.domain);
        } catch {
          // Ignore malformed backend metadata.
        }
      }
    }
  }
}

export function buildPolicyMetadata(exec, state) {
  const toolName = typeof exec?.name === "string" ? exec.name : "";
  const action = TOOL_ACTIONS[toolName];
  if (!action) return null;
  const args = exec?.arguments && typeof exec.arguments === "object" && !Array.isArray(exec.arguments) ? exec.arguments : {};
  const sessionId = state.resolve(args.session);
  const currentDomain = sessionId ? (state.domains.get(sessionId) ?? null) : null;
  let domain = currentDomain;
  let newTab = false;
  if ((toolName === "browser_session_start" || toolName === "browser_navigate") && args.url !== undefined) {
    const parsed = domainFromUrl(args.url);
    domain = parsed.domain;
    newTab = parsed.newTab;
  } else if (toolName === "browser_session_start" && args.url === undefined) {
    newTab = true;
  }
  const target = args.target;
  const targetKind = toolName === "browser_click" || toolName === "browser_fill" || toolName === "browser_press" ? classifyTarget(target) : "none";
  const value = typeof args.value === "string" ? args.value : "";
  const sensitive = (toolName === "browser_fill" && (/(password|passwd|passcode|otp|one[-_ ]?time|secret|token|api[-_ ]?key|verification|captcha)/i.test(String(target ?? "")) || looksLikeSecretText(value))) || (toolName === "browser_session_start" && args.device !== undefined);
  if (sessionId !== null && !SESSION_RE.test(sessionId)) throw new Error("session_id is invalid");
  return {
    tool_name: toolName,
    action,
    session_id: sessionId,
    domain,
    current_domain: currentDomain,
    target_kind: targetKind,
    value_length: value.length,
    sensitive,
    session_known: sessionId !== null && state.sessions.has(sessionId),
    new_tab: newTab
  };
}

function loopbackEndpoint(endpoint) {
  let parsed;
  try {
    parsed = new URL(endpoint);
  } catch {
    throw new Error("policy endpoint is invalid");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error("policy endpoint must use http or https");
  if (!LOOPBACK_RE.test(parsed.hostname)) throw new Error("policy endpoint must be loopback-only");
  if (parsed.pathname === "/" || parsed.pathname === "") parsed.pathname = "/rpc";
  return parsed;
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
      if (error) reject(error); else resolve(value);
    };
    const onAbort = () => {
      req.destroy();
      finish(new Error("policy request aborted"));
    };
    const req = transport({
      hostname: parsed.hostname.replace(/^\[|\]$/g, ""),
      port: parsed.port || undefined,
      path: `${parsed.pathname}${parsed.search}`,
      method: "POST",
      headers: {
        "content-type": "application/json",
        "content-length": Buffer.byteLength(body)
      }
    }, (response) => {
      let text = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        text += chunk;
        if (text.length > 256 * 1024) response.destroy(new Error("policy response is too large"));
      });
      response.on("error", (error) => finish(new Error(`policy response failed: ${error.message}`)));
      response.on("end", () => {
        if (response.statusCode < 200 || response.statusCode >= 300) return finish(new Error(`policy endpoint returned HTTP ${response.statusCode}`));
        try {
          const parsedBody = JSON.parse(text);
          if (parsedBody && parsedBody.error) return finish(new Error("policy endpoint rejected the request"));
          const value = parsedBody?.result ?? parsedBody;
          if (!value || typeof value !== "object" || !["allow", "ask", "deny"].includes(value.decision)) return finish(new Error("policy endpoint returned an invalid decision"));
          finish(null, {
            decision: value.decision,
            reason: typeof value.reason === "string" ? value.reason.slice(0, 600) : "browser policy decision",
            requires_human: value.requires_human === true,
            audit_id: typeof value.audit_id === "string" ? value.audit_id.slice(0, 100) : "",
            tool_name: typeof value.tool_name === "string" ? value.tool_name.slice(0, 100) : "",
            action: typeof value.action === "string" ? value.action.slice(0, 80) : "",
            session_id: typeof value.session_id === "string" ? value.session_id.slice(0, 160) : null,
            domain: typeof value.domain === "string" ? value.domain.slice(0, 253) : null,
            value_length: Number.isInteger(value.value_length) ? value.value_length : 0,
            sensitive: value.sensitive === true
          });
        } catch {
          finish(new Error("policy endpoint returned invalid JSON"));
        }
      });
    });
    req.on("error", (error) => finish(new Error(`policy endpoint unavailable: ${error.message}`)));
    timer = setTimeout(() => {
      req.destroy();
      finish(new Error("policy endpoint timed out"));
    }, Math.max(100, Number(timeoutMs) || 1500));
    if (signal) {
      if (signal.aborted) return onAbort();
      signal.addEventListener("abort", onAbort, { once: true });
    }
    req.write(body);
    req.end();
  });
}

export class BrowserPolicyClient {
  constructor({ endpoint, timeoutMs = 1500, helpTimeoutMs = 300000, post = postJson } = {}) {
    this.endpoint = resolvePolicyEndpoint(endpoint);
    this.timeoutMs = timeoutMs;
    this.helpTimeoutMs = helpTimeoutMs;
    this.post = post;
  }

  evaluate(metadata, signal) {
    return this.post(this.endpoint, {
      jsonrpc: "2.0",
      id: `browser-policy-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      method: "browser.policy.evaluate",
      params: metadata
    }, { timeoutMs: this.timeoutMs, signal });
  }

  requestHelp(params, signal) {
    return this.post(this.endpoint, {
      jsonrpc: "2.0",
      id: `browser-help-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      method: "browser.policy.request_help",
      params
    }, { timeoutMs: this.helpTimeoutMs, signal });
  }
}

export async function gateBrowserTool(exec, next, { client, state }) {
  if (!exec || typeof exec.name !== "string") return next();
  if (!TOOL_ACTIONS[exec.name]) {
    // Do not let a newly introduced browser tool bypass the Core policy until
    // its metadata mapping and tests have been reviewed and pinned.
    if (isBrowserToolName(exec.name)) {
      return { kind: "deny", reason: "unsupported browser tool; Sumika policy mapping is required" };
    }
    return next();
  }
  let metadata;
  try {
    metadata = buildPolicyMetadata(exec, state);
  } catch (error) {
    return { kind: "deny", reason: error instanceof Error ? error.message : "invalid browser arguments" };
  }
  if (exec.signal?.aborted) return { kind: "deny", reason: "browser operation was cancelled" };
  let decision;
  try {
    decision = await client.evaluate(metadata, exec.signal);
  } catch {
    return { kind: "deny", reason: "Sumika browser policy core is unavailable; browser operation was denied" };
  }
  if (decision.decision === "allow") return next();
  if (decision.decision === "ask") return { kind: "ask", reason: decision.reason || "browser operation requires user approval" };
  return { kind: "deny", reason: decision.reason || "browser operation was denied by Sumika policy" };
}

export function validateHelpInput(args, state) {
  if (!args || typeof args !== "object") throw new Error("human takeover arguments are invalid");
  const session = state.resolve(args.session);
  if (!session || !state.sessions.has(session)) throw new Error("human takeover requires an owned browser session");
  const prompt = typeof args.prompt === "string" ? args.prompt.trim() : "";
  if (!prompt || prompt.length > 2000) throw new Error("prompt must be between 1 and 2000 characters");
  if (looksLikeSecretText(prompt)) throw new Error("prompt must not contain credential values");
  const title = args.title === undefined ? null : (typeof args.title === "string" ? args.title.trim() : "");
  if (title !== null && title.length > 120) throw new Error("title is too long");
  if (!Array.isArray(args.target ?? [])) throw new Error("target must be an array");
  const targets = (args.target ?? []).map((value) => {
    if (typeof value !== "string" || !value.trim() || value.trim().length > 160) throw new Error("target is invalid");
    return value.trim();
  });
  if (targets.length > 8) throw new Error("at most 8 targets are allowed");
  return {
    session,
    domain: state.domains.get(session) ?? null,
    prompt,
    title: title || null,
    targets
  };
}
