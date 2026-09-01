import Schema from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";
import {
  ROUTE_BRIDGE_PLUGIN_ID,
  ROUTE_BRIDGE_VERSION,
  ROUTE_TOOLS,
  RoutePolicyClient,
  buildRouteMetadata,
  buildRoutePayload,
  containsSensitive,
  gateRouteTool,
  isRouteToolName,
  postJson,
  resolvePolicyEndpoint
} from "./policy.mjs";

const name = "sumika-dsh-route-bridge";
const inject = ["tools"];
const DEFAULT_ENDPOINT = "http://127.0.0.1:8771/rpc";

const Config = Schema.object({
  endpoint: Schema.string().default("").description(`Loopback Sumika Core JSON-RPC endpoint; defaults to ${DEFAULT_ENDPOINT} or SUMIKA_CORE_ENDPOINT.`),
  policyTimeoutMs: Schema.number().default(1500).description("Maximum time for one route bridge request."),
  enabled: Schema.boolean().default(true).description("Install the runtime-neutral route tools.")
});

function positiveInteger(value, fallback, field) {
  const number = Number(value ?? fallback);
  if (!Number.isInteger(number) || number < 100) throw new Error(`${field} must be an integer of at least 100`);
  return number;
}

// DSH 0.1.x requires every native tool to declare a canonical output
// renderer.  The Core already bounds and redacts the bridge response; this
// final projection keeps the renderer total for any JSON value.
const GENERIC_OUTPUT = Object.freeze({
  schema: { type: "json" },
  render: (_args, value) => {
    let text;
    try {
      const encoded = typeof value === "string" ? value : JSON.stringify(value);
      text = encoded === undefined ? String(value) : encoded;
    } catch {
      text = "[unrenderable route result]";
    }
    return [{ type: "text", text: text.slice(0, 32000) }];
  }
});

function installTool(ctx, client, specification) {
  ctx.tools.register(defineTool({
    ...specification,
    output: specification.output || GENERIC_OUTPUT,
    async execute(args, exec) {
      const payload = buildRoutePayload(specification.name, args || {}, exec || {});
      return client.call(specification.name, payload, exec?.signal);
    }
  }));
}

function routeParameters() {
  return {
    request: { type: "object", additionalProperties: true, description: "Runtime-neutral route request; parent IDs may come from the DSH execution context." },
    dispatch: { type: "object", additionalProperties: true, description: "Runtime-neutral dispatch object." },
    refresh: { type: "boolean" },
    wait: { type: "boolean" },
    includeTemplates: { type: "boolean" },
    includeUnavailable: { type: "boolean" },
    dispatchId: { type: "string" },
    consultationId: { type: "string" },
    parentSessionId: { type: "string" },
    parentTurnId: { type: "string" },
    limit: { type: "number" },
    dispatchSelected: { type: "boolean" },
    traceId: { type: "string" },
    maxMembers: { type: "number" },
    replace: { type: "boolean" }
  };
}

function apply(ctx, config = {}) {
  const resolved = {
    endpoint: resolvePolicyEndpoint(config.endpoint),
    policyTimeoutMs: positiveInteger(config.policyTimeoutMs, 1500, "policyTimeoutMs"),
    enabled: config.enabled !== false
  };
  if (!resolved.enabled) return;
  const client = new RoutePolicyClient({
    endpoint: resolved.endpoint,
    timeoutMs: resolved.policyTimeoutMs,
    pluginId: ROUTE_BRIDGE_PLUGIN_ID,
    pluginVersion: ROUTE_BRIDGE_VERSION
  });

  ctx.on("tools/pre-execute", (exec, next) => gateRouteTool(exec, next));

  installTool(ctx, client, {
    name: "sumika_route_catalog",
    description: "List the bounded runtime-neutral route catalog and worker bindings.",
    parameters: { refresh: { type: "boolean" }, includeTemplates: { type: "boolean" }, includeUnavailable: { type: "boolean" } },
    presentCall: () => ({ card: "generic", title: "Sumika route catalog", kind: "route-catalog", rawInput: "catalog" })
  });
  installTool(ctx, client, {
    name: "sumika_route_replan",
    description: "Replan a worker at an explicit Agent turn boundary; this does not make semantic decisions.",
    parameters: routeParameters(),
    presentCall: () => ({ card: "generic", title: "Replan route", kind: "route-replan", rawInput: "replan" })
  });
  installTool(ctx, client, {
    name: "sumika_route_dispatch",
    description: "Dispatch one validated isolated worker and return a bounded structured result.",
    parameters: routeParameters(),
    presentCall: () => ({ card: "generic", title: "Dispatch route worker", kind: "route-dispatch", rawInput: "dispatch" })
  });
  installTool(ctx, client, {
    name: "sumika_route_status",
    description: "Read one route dispatch status without exposing stored prompt or context.",
    parameters: { dispatchId: { type: "string", required: true } },
    presentCall: () => ({ card: "generic", title: "Route status", kind: "route-status", rawInput: "status" })
  });
  installTool(ctx, client, {
    name: "sumika_consultation_start",
    description: "Ask up to five independent web profiles for untrusted advice in bounded three-plus-two waves.",
    parameters: routeParameters(),
    presentCall: () => ({ card: "generic", title: "Start consultation", kind: "consultation-start", rawInput: "consult" })
  });
  installTool(ctx, client, {
    name: "sumika_consultation_status",
    description: "Read consultation progress and bounded UNTRUSTED_WEB_RESULT members.",
    parameters: { consultationId: { type: "string" }, parentSessionId: { type: "string" }, limit: { type: "number" } },
    presentCall: () => ({ card: "generic", title: "Consultation status", kind: "consultation-status", rawInput: "consultation status" })
  });
  installTool(ctx, client, {
    name: "sumika_route_cancel",
    description: "Cancel a pending route dispatch or consultation; already-sent work is never retried automatically.",
    parameters: { dispatchId: { type: "string" }, consultationId: { type: "string" } },
    presentCall: () => ({ card: "generic", title: "Cancel route", kind: "route-cancel", rawInput: "cancel" })
  });
  installTool(ctx, client, {
    name: "sumika_route_retry",
    description: "Retry only a confirmed pre-send route failure.",
    parameters: { dispatchId: { type: "string", required: true }, wait: { type: "boolean" } },
    presentCall: () => ({ card: "generic", title: "Retry route", kind: "route-retry", rawInput: "retry" })
  });
  installTool(ctx, client, {
    name: "sumika_route_arm",
    description: "Arm an explicit parent turn request for a later event boundary.",
    parameters: { ...routeParameters(), replace: { type: "boolean" } },
    presentCall: () => ({ card: "generic", title: "Arm route turn", kind: "route-arm", rawInput: "arm" })
  });
  installTool(ctx, client, {
    name: "sumika_route_pending",
    description: "Read terminal worker results waiting for parent acknowledgement.",
    parameters: { parentSessionId: { type: "string" }, parentTurnId: { type: "string" }, limit: { type: "number" } },
    presentCall: () => ({ card: "generic", title: "Pending route results", kind: "route-pending", rawInput: "pending" })
  });
  installTool(ctx, client, {
    name: "sumika_route_ack",
    description: "Acknowledge one terminal worker result so it is removed from the parent mailbox.",
    parameters: { dispatchId: { type: "string", required: true } },
    presentCall: () => ({ card: "generic", title: "Acknowledge route result", kind: "route-ack", rawInput: "ack" })
  });

  // Registration is intentionally attempted during plugin load as well as
  // before the first tool call.  A transient Core restart simply causes the
  // next call to retry; no route result is fabricated.
  void client.ensureRegistered().catch(() => {});
  if (typeof ctx.effect === "function") ctx.effect(() => () => client.close());
}

export {
  Config,
  ROUTE_BRIDGE_PLUGIN_ID,
  ROUTE_BRIDGE_VERSION,
  ROUTE_TOOLS,
  RoutePolicyClient,
  apply,
  buildRouteMetadata,
  buildRoutePayload,
  containsSensitive,
  gateRouteTool,
  inject,
  isRouteToolName,
  name,
  postJson,
  resolvePolicyEndpoint
};
