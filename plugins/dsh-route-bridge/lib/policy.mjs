import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";

export const ROUTE_TOOLS = Object.freeze({
  sumika_route_catalog: "sumika.route.catalog",
  sumika_route_replan: "sumika.route.replan",
  sumika_route_dispatch: "sumika.route.dispatch",
  sumika_route_status: "sumika.route.status",
  sumika_consultation_start: "sumika.consultation.start",
  sumika_consultation_status: "sumika.consultation.status",
  sumika_route_cancel: "sumika.route.cancel",
  sumika_route_retry: "sumika.route.retry"
});

export const ROUTE_BRIDGE_PLUGIN_ID = "sumika.dsh-route-bridge";
export const ROUTE_BRIDGE_VERSION = "0.1.0";

const LOOPBACK_RE = /^(?:localhost|127(?:\.\d{1,3}){3}|\[?::1\]?)$/i;
const IDENTIFIER_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$/;
const TOKEN_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/;
const SECRET_RE = /(?:sk-[a-z0-9_-]{8,}|pk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{8,}|eyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}|(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|passcode|secret|cookie|authorization|otp|private[_ -]?key)\s*[:=]\s*[^\s,;]+)/i;
const SENSITIVE_KEY_RE = /(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|passcode|secret|cookie|authorization|otp|private[_ -]?key|credential|token)/i;
const SENSITIVE_FILE_RE = /(?:^|[\\/])(?:\.env(?:\.[^\\/]*)?|credentials?\.json|cookies?\.json|token\.json|secrets?\.(?:json|toml|yaml|yml))$/i;
const ABSOLUTE_PATH_RE = /(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+|\/(?:Users|home|root|private|mnt)\/)/;
const EVENT_BOUNDARIES = new Set(["turn.started", "tool.completed", "approval.resolved", "turn.completed", "turn.failed"]);
const MAX_BODY_BYTES = 512 * 1024;
const MAX_CONTEXT_BYTES = 28 * 1024;

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

function parsedLoopbackEndpoint(endpoint) {
  let parsed;
  try { parsed = new URL(endpoint); } catch { throw new Error("route bridge endpoint is invalid"); }
  if (!["http:", "https:"].includes(parsed.protocol) || !LOOPBACK_RE.test(parsed.hostname)) throw new Error("route bridge endpoint must be loopback-only");
  if (!parsed.pathname || parsed.pathname === "/") parsed.pathname = "/rpc";
  return parsed;
}

export function isRouteToolName(value) {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(ROUTE_TOOLS, value);
}

export function isIdentifier(value, { field = "identifier", required = true } = {}) {
  if (value === undefined || value === null || value === "") {
    if (required) throw new Error(`${field} is required`);
    return null;
  }
  const text = String(value).trim();
  if (!IDENTIFIER_RE.test(text)) throw new Error(`${field} is invalid`);
  return text;
}

function token(value, field, { required = true } = {}) {
  if (value === undefined || value === null || value === "") {
    if (required) throw new Error(`${field} is required`);
    return null;
  }
  const text = String(value).trim().toLowerCase();
  if (!TOKEN_RE.test(text)) throw new Error(`${field} is invalid`);
  return text;
}

export function looksLikeSecret(value) {
  return typeof value === "string" && SECRET_RE.test(value);
}

export function containsSensitive(value, depth = 0) {
  if (depth > 7) return true;
  if (typeof value === "string") return looksLikeSecret(value);
  if (Array.isArray(value)) return value.slice(0, 96).some((item) => containsSensitive(item, depth + 1));
  if (!value || typeof value !== "object") return false;
  return Object.entries(value).slice(0, 96).some(([key, item]) => SENSITIVE_KEY_RE.test(key) || containsSensitive(item, depth + 1));
}

function assertBounded(value, depth = 0, budget = MAX_CONTEXT_BYTES, keyName = "context") {
  if (depth > 6) throw new Error("context-too-deep");
  if (typeof value === "string") {
    if (value.length > Math.min(24_000, budget)) throw new Error("context-too-large");
    if (looksLikeSecret(value)) throw new Error("sensitive-context");
    return value.replace(ABSOLUTE_PATH_RE, "<LOCAL_PATH>");
  }
  if (value === null || typeof value === "boolean" || typeof value === "number") return value;
  if (Array.isArray(value)) {
    if (value.length > 64) throw new Error(`${keyName} has too many items`);
    const result = value.map((item) => assertBounded(item, depth + 1, budget, keyName));
    if (JSON.stringify(result).length > budget) throw new Error("context-too-large");
    return result;
  }
  if (typeof value !== "object") throw new Error(`${keyName} must be JSON data`);
  const entries = Object.entries(value);
  if (entries.length > 64) throw new Error(`${keyName} has too many fields`);
  const result = {};
  let remaining = budget;
  for (const [rawKey, item] of entries) {
    const key = String(rawKey);
    if (key.length > 120 || /[\u0000-\u001f\u007f]/.test(key)) throw new Error(`${keyName} contains an invalid key`);
    if (SENSITIVE_KEY_RE.test(key)) throw new Error("sensitive-context");
    if ((key === "path" || key === "file" || key === "filename" || key === "workspace_path") && typeof item === "string" && SENSITIVE_FILE_RE.test(item)) throw new Error("sensitive-context");
    const safe = assertBounded(item, depth + 1, Math.max(256, remaining), key);
    result[key] = safe;
    remaining -= JSON.stringify(safe).length;
    if (remaining <= 0) throw new Error("context-too-large");
  }
  return result;
}

export function validateContext(value, field = "context_refs") {
  const safe = assertBounded(value ?? {}, 0, MAX_CONTEXT_BYTES, field);
  if (JSON.stringify(safe).length > MAX_CONTEXT_BYTES) throw new Error("context-too-large");
  return safe;
}

function boolean(value, field, fallback = false) {
  if (value === undefined) return fallback;
  if (typeof value !== "boolean") throw new Error(`${field} must be a boolean`);
  return value;
}

function boundedInteger(value, field, fallback, min, max) {
  if (value === undefined || value === null || value === "") return fallback;
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`${field} is invalid`);
  return value;
}

function parentIds(args, exec) {
  const context = exec?.context && typeof exec.context === "object" ? exec.context : {};
  const session = args.parent_session_id ?? args.parentSessionId ?? args.session_id ?? args.sessionId ?? context.parent_session_id ?? context.parentSessionId ?? context.session_id ?? context.sessionId ?? exec?.session_id ?? exec?.sessionId;
  const turn = args.parent_turn_id ?? args.parentTurnId ?? args.turn_id ?? args.turnId ?? context.parent_turn_id ?? context.parentTurnId ?? context.turn_id ?? context.turnId ?? exec?.turn_id ?? exec?.turnId;
  return {
    parent_session_id: isIdentifier(session, { field: "parent_session_id" }),
    parent_turn_id: isIdentifier(turn, { field: "parent_turn_id", required: false })
  };
}

const REQUEST_FIELDS = Object.freeze([
  "task_kind", "taskKind", "phase", "task_stage", "taskStage", "trigger_event", "triggerEvent",
  "risk", "difficulty", "required_capabilities", "requiredCapabilities", "privacy_constraints",
  "privacyConstraints", "budget_remaining", "budgetRemaining", "remaining_budget", "budget_unit",
  "latency_target_ms", "latencyTargetMs", "confirmation_mode", "confirmationMode", "budget_policy",
  "budgetPolicy", "preferred_route", "preferredRoute", "min_quality_tier", "minQualityTier",
  "workspace_access", "workspaceAccess", "depth", "decision_key", "decisionKey", "route_id", "routeId",
  "auto_dispatch", "autoDispatch", "quota_consent", "quotaConsent", "confirmed", "approved", "metadata",
  "question", "task_text", "taskText", "context_refs", "contextRefs", "decision_kind", "decisionKind",
  "max_members", "maxMembers", "route_constraints", "routeConstraints", "continuation_of", "continuationOf",
  "consultation_id", "consultationId"
]);

function copyFields(source, fields = REQUEST_FIELDS) {
  const output = {};
  for (const key of fields) if (Object.prototype.hasOwnProperty.call(source, key)) output[key] = source[key];
  return output;
}

function normalizeCapabilities(value) {
  if (value === undefined) return undefined;
  if (typeof value === "string") return [token(value, "required_capability")];
  if (!Array.isArray(value) || value.length > 24) throw new Error("required_capabilities is invalid");
  return value.map((item) => token(item, "required_capability"));
}

function normalizeRequest(raw, exec, { consultation = false } = {}) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("request must be an object");
  if (containsSensitive(raw)) throw new Error("credential-shaped route input is not allowed");
  const result = copyFields(raw);
  const ids = parentIds(raw, exec);
  result.parent_session_id = ids.parent_session_id;
  if (ids.parent_turn_id) result.parent_turn_id = ids.parent_turn_id;
  if (result.required_capabilities !== undefined || result.requiredCapabilities !== undefined) {
    result.required_capabilities = normalizeCapabilities(result.required_capabilities ?? result.requiredCapabilities);
    delete result.requiredCapabilities;
  }
  if (result.privacy_constraints !== undefined || result.privacyConstraints !== undefined) {
    result.privacy_constraints = normalizeCapabilities(result.privacy_constraints ?? result.privacyConstraints);
    delete result.privacyConstraints;
  }
  if (result.context_refs !== undefined || result.contextRefs !== undefined) {
    result.context_refs = validateContext(result.context_refs ?? result.contextRefs);
    delete result.contextRefs;
  }
  if (result.metadata !== undefined) result.metadata = validateContext(result.metadata, "metadata");
  if (result.trigger_event !== undefined || result.triggerEvent !== undefined) {
    const event = String(result.trigger_event ?? result.triggerEvent).trim().toLowerCase();
    if (!EVENT_BOUNDARIES.has(event)) throw new Error("trigger_event is invalid");
    result.trigger_event = event;
    delete result.triggerEvent;
  }
  if (consultation) {
    result.question = String(result.question ?? result.task_text ?? result.taskText ?? "").trim();
    if (!result.question || result.question.length > 16_000) throw new Error("question must contain 1-16000 characters");
    if (looksLikeSecret(result.question)) throw new Error("sensitive-context");
    result.decision_kind = String(result.decision_kind ?? result.decisionKind ?? "small-answer").trim().toLowerCase();
    if (!["brainstorm", "plan-review", "fact-check", "counterexample", "small-answer"].includes(result.decision_kind)) throw new Error("decision_kind is invalid");
    result.max_members = boundedInteger(result.max_members ?? result.maxMembers, "max_members", 3, 1, 3);
    if (result.route_constraints !== undefined || result.routeConstraints !== undefined) {
      result.route_constraints = validateContext(result.route_constraints ?? result.routeConstraints, "route_constraints");
      delete result.routeConstraints;
    }
    if (result.continuation_of !== undefined || result.continuationOf !== undefined) {
      result.continuation_of = isIdentifier(result.continuation_of ?? result.continuationOf, { field: "continuation_of", required: false });
      delete result.continuationOf;
    }
  }
  return result;
}

export function buildRoutePayload(toolName, args = {}, exec = {}) {
  if (!isRouteToolName(toolName)) return null;
  if (!args || typeof args !== "object" || Array.isArray(args)) throw new Error("route arguments must be an object");
  if (containsSensitive(args)) throw new Error("credential-shaped route input is not allowed");
  switch (toolName) {
    case "sumika_route_catalog":
      return {
        include_templates: boolean(args.include_templates ?? args.includeTemplates, "include_templates", true),
        include_unavailable: boolean(args.include_unavailable ?? args.includeUnavailable, "include_unavailable", true),
        refresh: boolean(args.refresh, "refresh", false)
      };
    case "sumika_route_replan": {
      const source = args.request && typeof args.request === "object" ? { ...args.request, ...copyFields(args, ["parent_session_id", "parentSessionId", "parent_turn_id", "parentTurnId", "session_id", "sessionId"]) } : args;
      const payload = normalizeRequest(source, exec);
      if (args.dispatch_selected !== undefined || args.dispatchSelected !== undefined) payload.dispatch_selected = boolean(args.dispatch_selected ?? args.dispatchSelected, "dispatch_selected");
      if (args.refresh !== undefined) payload.refresh = boolean(args.refresh, "refresh");
      return payload;
    }
    case "sumika_route_dispatch": {
      const source = args.dispatch && typeof args.dispatch === "object" ? { ...args.dispatch, ...copyFields(args, ["parent_session_id", "parentSessionId", "parent_turn_id", "parentTurnId", "session_id", "sessionId"]) } : args;
      const payload = normalizeRequest(source, exec);
      payload.dispatch_id = isIdentifier(source.dispatch_id ?? source.dispatchId, { field: "dispatch_id", required: false }) || undefined;
      payload.route_id = isIdentifier(source.route_id ?? source.routeId, { field: "route_id" });
      payload.question = String(source.question ?? source.text ?? source.prompt ?? "").trim();
      if (!payload.question || payload.question.length > 16_000 || looksLikeSecret(payload.question)) throw new Error("question is invalid");
      payload.worker_kind = source.worker_kind ?? source.workerKind;
      if (payload.worker_kind !== undefined) token(payload.worker_kind, "worker_kind");
      payload.context_refs = validateContext(source.context_refs ?? source.contextRefs ?? {});
      payload.wait = boolean(args.wait, "wait", false);
      return payload;
    }
    case "sumika_route_status": {
      return { dispatch_id: isIdentifier(args.dispatch_id ?? args.dispatchId, { field: "dispatch_id" }) };
    }
    case "sumika_consultation_start": {
      const source = args.request && typeof args.request === "object" ? { ...args.request, ...copyFields(args, ["parent_session_id", "parentSessionId", "parent_turn_id", "parentTurnId", "session_id", "sessionId"]) } : args;
      const payload = normalizeRequest(source, exec, { consultation: true });
      payload.consultation_id = isIdentifier(source.consultation_id ?? source.consultationId, { field: "consultation_id", required: false }) || undefined;
      payload.wait = boolean(args.wait, "wait", false);
      return payload;
    }
    case "sumika_consultation_status": {
      const payload = {};
      if (args.consultation_id ?? args.consultationId) payload.consultation_id = isIdentifier(args.consultation_id ?? args.consultationId, { field: "consultation_id" });
      if (args.parent_session_id ?? args.parentSessionId) payload.parent_session_id = isIdentifier(args.parent_session_id ?? args.parentSessionId, { field: "parent_session_id" });
      if (args.limit !== undefined) payload.limit = boundedInteger(args.limit, "limit", 50, 1, 100);
      if (!payload.consultation_id && !payload.parent_session_id) {
        const ids = parentIds(args, exec);
        payload.parent_session_id = ids.parent_session_id;
      }
      return payload;
    }
    case "sumika_route_cancel": {
      const payload = {};
      if (args.dispatch_id ?? args.dispatchId) payload.dispatch_id = isIdentifier(args.dispatch_id ?? args.dispatchId, { field: "dispatch_id" });
      if (args.consultation_id ?? args.consultationId) payload.consultation_id = isIdentifier(args.consultation_id ?? args.consultationId, { field: "consultation_id" });
      if (!payload.dispatch_id && !payload.consultation_id) throw new Error("dispatch_id or consultation_id is required");
      return payload;
    }
    case "sumika_route_retry":
      return {
        dispatch_id: isIdentifier(args.dispatch_id ?? args.dispatchId, { field: "dispatch_id" }),
        wait: boolean(args.wait, "wait", false)
      };
    default:
      throw new Error("unsupported route tool");
  }
}

export function buildRouteMetadata(exec) {
  if (!exec || typeof exec !== "object") return { session_id: null, turn_id: null };
  const context = exec.context && typeof exec.context === "object" ? exec.context : {};
  const session = exec.session_id ?? exec.sessionId ?? context.session_id ?? context.sessionId ?? null;
  const turn = exec.turn_id ?? exec.turnId ?? context.turn_id ?? context.turnId ?? null;
  return {
    session_id: session === null ? null : isIdentifier(session, { field: "session_id" }),
    turn_id: turn === null ? null : isIdentifier(turn, { field: "turn_id" })
  };
}

export async function gateRouteTool(exec, next) {
  if (!exec || typeof exec.name !== "string" || !exec.name.startsWith("sumika_")) return next();
  if (!isRouteToolName(exec.name)) return { kind: "deny", reason: "unsupported Sumika route tool" };
  try {
    buildRoutePayload(exec.name, exec.arguments || {}, exec);
  } catch (error) {
    return { kind: "deny", reason: error instanceof Error ? error.message : "invalid route arguments" };
  }
  return next();
}

function safeResult(value, depth = 0) {
  if (depth > 7) return "[truncated]";
  if (typeof value === "string") {
    if (looksLikeSecret(value)) return "[redacted]";
    return value.replace(ABSOLUTE_PATH_RE, "<LOCAL_PATH>").slice(0, 32_000);
  }
  if (value === null || typeof value === "boolean" || typeof value === "number") return value;
  if (Array.isArray(value)) return value.slice(0, 128).map((item) => safeResult(item, depth + 1));
  if (value && typeof value === "object") {
    const result = {};
    for (const [key, item] of Object.entries(value).slice(0, 128)) {
      if (SENSITIVE_KEY_RE.test(key)) result[key] = "[redacted]";
      else result[key] = safeResult(item, depth + 1);
    }
    return result;
  }
  return String(value).slice(0, 32_000);
}

export function postJson(endpoint, payload, { timeoutMs = 1500, signal } = {}) {
  const parsed = parsedLoopbackEndpoint(endpoint);
  const body = JSON.stringify(payload);
  if (Buffer.byteLength(body) > MAX_BODY_BYTES) return Promise.reject(new Error("route bridge request is too large"));
  const transport = parsed.protocol === "https:" ? httpsRequest : httpRequest;
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer;
    let req;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      if (signal) signal.removeEventListener("abort", onAbort);
      error ? reject(error) : resolve(value);
    };
    const onAbort = () => { req?.destroy(); finish(new Error("route bridge request aborted")); };
    req = transport({
      hostname: parsed.hostname.replace(/^\[|\]$/g, ""),
      port: parsed.port || undefined,
      path: `${parsed.pathname}${parsed.search}`,
      method: "POST",
      headers: { "content-type": "application/json", "content-length": Buffer.byteLength(body) }
    }, (response) => {
      let text = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        text += chunk;
        if (Buffer.byteLength(text) > MAX_BODY_BYTES) response.destroy(new Error("route bridge response is too large"));
      });
      response.on("error", () => finish(new Error("route bridge response failed")));
      response.on("end", () => {
        if (response.statusCode < 200 || response.statusCode >= 300) return finish(new Error(`route bridge endpoint returned HTTP ${response.statusCode}`));
        try {
          const parsedBody = JSON.parse(text);
          if (parsedBody?.error) return finish(new Error("route bridge endpoint rejected the request"));
          finish(null, safeResult(parsedBody?.result ?? parsedBody));
        } catch { finish(new Error("route bridge endpoint returned invalid JSON")); }
      });
    });
    req.on("error", () => finish(new Error("route bridge endpoint unavailable")));
    timer = setTimeout(() => { req.destroy(); finish(new Error("route bridge endpoint timed out")); }, Math.max(100, Number(timeoutMs) || 1500));
    if (signal) { if (signal.aborted) return onAbort(); signal.addEventListener("abort", onAbort, { once: true }); }
    req.write(body); req.end();
  });
}

export class RoutePolicyClient {
  constructor({ endpoint, timeoutMs = 1500, post = postJson, pluginId = ROUTE_BRIDGE_PLUGIN_ID, pluginVersion = ROUTE_BRIDGE_VERSION } = {}) {
    this.endpoint = resolvePolicyEndpoint(endpoint);
    this.timeoutMs = timeoutMs;
    this.post = post;
    this.pluginId = pluginId;
    this.pluginVersion = pluginVersion;
    this.registration = null;
    this.registrationPromise = null;
  }

  async register(signal) {
    const result = await this.post(this.endpoint, {
      jsonrpc: "2.0",
      id: `route-register-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      method: "sumika.route.bridge_tools",
      params: {
        register: true,
        plugin_id: this.pluginId,
        plugin_version: this.pluginVersion,
        tools: Object.keys(ROUTE_TOOLS)
      }
    }, { timeoutMs: this.timeoutMs, signal });
    if (!result || result.registered !== true) throw new Error(result?.reason || "route bridge registration rejected");
    this.registration = result;
    return result;
  }

  ensureRegistered(signal) {
    if (this.registration?.registered === true) return Promise.resolve(this.registration);
    if (!this.registrationPromise) {
      this.registrationPromise = this.register(signal).catch((error) => {
        this.registrationPromise = null;
        throw error;
      });
    }
    return this.registrationPromise;
  }

  async call(toolName, params = {}, signal) {
    if (!isRouteToolName(toolName)) throw new Error("unsupported route tool");
    await this.ensureRegistered(signal);
    const result = await this.post(this.endpoint, {
      jsonrpc: "2.0",
      id: `route-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      method: ROUTE_TOOLS[toolName],
      params
    }, { timeoutMs: this.timeoutMs, signal });
    return result;
  }

  close() {
    this.registration = null;
    this.registrationPromise = null;
  }
}
