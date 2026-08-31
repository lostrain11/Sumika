import Schema from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";
import {
  DesktopPolicyClient,
  containsSensitive,
  gateDesktopTool,
  isDesktopToolName,
  resolvePolicyEndpoint
} from "./policy.mjs";

const name = "sumika-dsh-desktop-automation";
const inject = ["tools"];
const DEFAULT_ENDPOINT = "http://127.0.0.1:8771/rpc";

const Config = Schema.object({
  endpoint: Schema.string().default("").description(`Loopback Sumika Core JSON-RPC endpoint; defaults to ${DEFAULT_ENDPOINT} or SUMIKA_CORE_ENDPOINT.`),
  policyTimeoutMs: Schema.number().default(1500).description("Maximum time for one desktop bridge request."),
  enabled: Schema.boolean().default(true).description("Install the controlled desktop automation tools.")
});

function positiveInteger(value, fallback, field) {
  const number = Number(value ?? fallback);
  if (!Number.isInteger(number) || number < 100) throw new Error(`${field} must be an integer of at least 100`);
  return number;
}

function scalar(value, field, limit = 160) {
  if (typeof value !== "string" && typeof value !== "number") throw new Error(`${field} must be a scalar identifier`);
  const text = String(value).trim();
  if (!text || text.length > limit || !/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(text)) throw new Error(`${field} is invalid`);
  return text;
}

function objectOrEmpty(value, field) {
  if (value === undefined || value === null) return {};
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${field} must be an object`);
  return value;
}

// Keep the DSH tool contract valid for bridge responses whose shape is owned
// by the Core.  The policy client has already applied its bounded redaction.
const GENERIC_OUTPUT = Object.freeze({
  schema: { type: "json" },
  render: (_args, value) => {
    let text;
    try {
      const encoded = typeof value === "string" ? value : JSON.stringify(value);
      text = encoded === undefined ? String(value) : encoded;
    } catch {
      text = "[unrenderable desktop result]";
    }
    return [{ type: "text", text: text.slice(0, 32000) }];
  }
});

function installTool(ctx, client, specification) {
  ctx.tools.register(defineTool({
    ...specification,
    output: specification.output || GENERIC_OUTPUT,
    async execute(args, exec) {
      const value = await specification.run(args || {}, exec, client);
      return value;
    }
  }));
}

function apply(ctx, config = {}) {
  const resolved = {
    endpoint: resolvePolicyEndpoint(config.endpoint),
    policyTimeoutMs: positiveInteger(config.policyTimeoutMs, 1500, "policyTimeoutMs"),
    enabled: config.enabled !== false
  };
  if (!resolved.enabled) return;
  const client = new DesktopPolicyClient({ endpoint: resolved.endpoint, timeoutMs: resolved.policyTimeoutMs });

  // Unknown desktop_* names are rejected before they can reach a newly added
  // plugin.  The Core remains the authoritative approval and lease boundary.
  ctx.on("tools/pre-execute", (exec, next) => gateDesktopTool(exec, next));

  installTool(ctx, client, {
    name: "desktop_app_catalog",
    description: "List explicitly registered desktop applications and their safe health projection.",
    parameters: { refresh: { type: "boolean", description: "Run a read-only adapter health check." } },
    run: (_args, _exec, bridge) => bridge.call("desktop.automation.catalog", { refresh: _args.refresh === true }, _exec?.signal),
    presentCall: () => ({ card: "generic", title: "Desktop application catalog", kind: "desktop-catalog", rawInput: "catalog" })
  });

  installTool(ctx, client, {
    name: "desktop_app_open",
    description: "Open an approved desktop application session using an exclusive profile lease.",
    parameters: {
      appId: { type: "string", required: true },
      profileId: { type: "string" },
      owner: { type: "string", description: "agent, manual, or system" },
      options: { type: "object", additionalProperties: true },
      approved: { type: "boolean", description: "Must be true after the user/DSH approval gate." }
    },
    run: (args, exec, bridge) => {
      const appId = scalar(args.appId ?? args.app_id, "appId");
      const profileId = args.profileId ?? args.profile_id;
      if (profileId !== undefined) scalar(profileId, "profileId");
      const options = objectOrEmpty(args.options, "options");
      if (containsSensitive(options)) throw new Error("desktop options must not contain credentials");
      return bridge.call("desktop.automation.open", {
        app_id: appId,
        profile_id: profileId === undefined ? undefined : String(profileId),
        owner: args.owner === undefined ? "agent" : String(args.owner),
        options,
        approved: args.approved === true
      }, exec?.signal);
    },
    presentCall: () => ({ card: "generic", title: "Open desktop application", kind: "desktop-open", rawInput: "open" })
  });

  installTool(ctx, client, {
    name: "desktop_app_observe",
    description: "Read a bounded observation from an owned desktop application session.",
    parameters: { sessionId: { type: "string", required: true }, options: { type: "object", additionalProperties: true } },
    run: (args, exec, bridge) => bridge.call("desktop.automation.observe", {
      session_id: scalar(args.sessionId ?? args.session_id, "sessionId"),
      options: objectOrEmpty(args.options, "options")
    }, exec?.signal),
    presentCall: () => ({ card: "generic", title: "Observe desktop application", kind: "desktop-observe", rawInput: "observe" })
  });

  installTool(ctx, client, {
    name: "desktop_app_act",
    description: "Perform one structured action through an owned desktop session. Sensitive values must be entered by the user in the application window.",
    parameters: {
      request: { type: "object", additionalProperties: true, required: true },
      approved: { type: "boolean", description: "One-time approval for the requested action." },
      approvalId: { type: "string" }
    },
    run: (args, exec, bridge) => {
      const request = objectOrEmpty(args.request, "request");
      if (!Object.keys(request).length) throw new Error("request must not be empty");
      if (containsSensitive(request)) throw new Error("credential-shaped desktop input must be entered by the user in the application window");
      const payload = { ...request };
      if (payload.approved === undefined) payload.approved = args.approved === true;
      if (payload.approval_id === undefined && args.approvalId !== undefined) payload.approval_id = scalar(args.approvalId, "approvalId");
      return bridge.call("desktop.automation.act", { request: payload }, exec?.signal);
    },
    presentCall: () => ({ card: "generic", title: "Act on desktop application", kind: "desktop-act", rawInput: "act" })
  });

  installTool(ctx, client, {
    name: "desktop_app_close",
    description: "Close an owned desktop automation session after explicit approval.",
    parameters: { sessionId: { type: "string", required: true }, approved: { type: "boolean" } },
    run: (args, exec, bridge) => bridge.call("desktop.automation.close", {
      session_id: scalar(args.sessionId ?? args.session_id, "sessionId"),
      approved: args.approved === true
    }, exec?.signal),
    presentCall: () => ({ card: "generic", title: "Close desktop session", kind: "desktop-close", rawInput: "close" })
  });

  installTool(ctx, client, {
    name: "desktop_app_takeover",
    description: "Request explicit foreground human takeover for an approved desktop session.",
    parameters: { sessionId: { type: "string", required: true }, enabled: { type: "boolean" }, approved: { type: "boolean" } },
    run: (args, exec, bridge) => bridge.call("desktop.automation.takeover", {
      session_id: scalar(args.sessionId ?? args.session_id, "sessionId"),
      enabled: args.enabled !== false,
      approved: args.approved === true
    }, exec?.signal),
    presentCall: () => ({ card: "generic", title: "Request desktop takeover", kind: "desktop-takeover", rawInput: "takeover" })
  });

  installTool(ctx, client, {
    name: "desktop_automation_approval",
    description: "Inspect or resolve Sumika desktop approvals and permissions; granting a permission requires exact user confirmation.",
    parameters: { operation: { type: "string", required: true }, appId: { type: "string" }, scope: { type: "string" }, approvalId: { type: "string" }, approved: { type: "boolean" }, confirmAppId: { type: "string" } },
    run: (args, exec, bridge) => {
      const operation = String(args.operation || "").trim().toLowerCase();
      if (!["list", "status", "grant", "revoke", "approve", "deny", "resolve"].includes(operation)) throw new Error("approval operation is invalid");
      const payload = { operation, approved: args.approved === true };
      if (args.appId !== undefined) payload.app_id = scalar(args.appId, "appId");
      if (args.confirmAppId !== undefined) payload.confirm_app_id = scalar(args.confirmAppId, "confirmAppId");
      if (args.approvalId !== undefined) payload.approval_id = scalar(args.approvalId, "approvalId");
      if (args.scope !== undefined) payload.scope = String(args.scope);
      return bridge.call("desktop.automation.approval", payload, exec?.signal);
    },
    presentCall: () => ({ card: "generic", title: "Desktop approval", kind: "desktop-approval", rawInput: "approval" })
  });

  if (typeof ctx.effect === "function") ctx.effect(() => () => {});
}

export {
  Config,
  DesktopPolicyClient,
  apply,
  containsSensitive,
  gateDesktopTool,
  inject,
  isDesktopToolName,
  name,
  resolvePolicyEndpoint
};
