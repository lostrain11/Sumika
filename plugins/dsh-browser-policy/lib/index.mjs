import Schema from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";
import {
  BrowserPolicyClient,
  SessionState,
  buildPolicyMetadata,
  classifyTarget,
  domainFromUrl,
  gateBrowserTool,
  isBrowserToolName,
  looksLikeSecretText,
  normalizeHost,
  resolvePolicyEndpoint,
  validateHelpInput
} from "./policy.mjs";

const name = "sumika-dsh-browser-policy";
const inject = ["tools"];
const DEFAULT_ENDPOINT = "http://127.0.0.1:8771/rpc";

const Config = Schema.object({
  endpoint: Schema.string().default("").description(`Loopback Sumika Core JSON-RPC endpoint; defaults to the managed desktop Core (${DEFAULT_ENDPOINT}) or SUMIKA_CORE_ENDPOINT.`),
  policyTimeoutMs: Schema.number().default(1500).description("Maximum time for one pre-execution policy decision."),
  helpTimeoutMs: Schema.number().default(300000).description("Maximum time to wait for a user takeover request."),
  enabled: Schema.boolean().default(true).description("Install the policy gate and human takeover tool.")
});

function positiveInteger(value, fallback, name) {
  const number = Number(value ?? fallback);
  if (!Number.isInteger(number) || number < 100) throw new Error(`${name} must be an integer of at least 100`);
  return number;
}

function apply(ctx, config = {}) {
  const resolved = {
    endpoint: resolvePolicyEndpoint(config.endpoint),
    policyTimeoutMs: positiveInteger(config.policyTimeoutMs, 1500, "policyTimeoutMs"),
    helpTimeoutMs: positiveInteger(config.helpTimeoutMs, 300000, "helpTimeoutMs"),
    enabled: config.enabled !== false
  };
  if (!resolved.enabled) return;

  const state = new SessionState();
  const client = new BrowserPolicyClient({
    endpoint: resolved.endpoint,
    timeoutMs: resolved.policyTimeoutMs,
    helpTimeoutMs: resolved.helpTimeoutMs
  });

  let unregisterPolicySkill = () => {};
  try {
    const skills = typeof ctx.get === "function" ? ctx.get("skills") : undefined;
    if (skills && typeof skills.register === "function") {
      unregisterPolicySkill = skills.register({
        name: "sumika-browser-policy",
        description: "Safety rules for BrowserSkill calls: use browser_request_help for login, OTP, CAPTCHA, and credential input.",
        content: "Use the structured browser_* tools. Never put passwords, OTPs, CAPTCHA answers, API keys, cookies, or other credential values in tool arguments. When a human must act, call browser_request_help and wait for the user in the isolated Agent Window.",
        source: "bundled"
      }) || (() => {});
    }
  } catch {
    // Skills are optional; the pre-execute policy remains authoritative.
  }

  ctx.on("tools/pre-execute", (exec, next) => gateBrowserTool(exec, next, { client, state }));
  ctx.on("tools/result", (exec, result) => {
    try {
      state.observeResult(exec.name, result);
    } catch {
      // Result observers must never affect the authoritative tool outcome.
    }
  });

  ctx.tools.register(defineTool({
    name: "browser_request_help",
    description: "Pause browser work and ask the user to operate the isolated BrowserSkill window. The user must enter passwords, OTPs, CAPTCHA answers, and other credentials themselves; never put those values in this request.",
    parameters: {
      session: {
        type: "string",
        description: "Owned BrowserSkill session id. Omit to use the current session."
      },
      prompt: {
        type: "string",
        required: true,
        description: "Short instruction describing what the user should do in the isolated window, without secret values."
      },
      title: {
        type: "string",
        description: "Optional short heading for the takeover panel."
      },
      target: {
        type: "array",
        items: { type: "string" },
        description: "Optional snapshot refs or CSS selectors to highlight for the user."
      }
    },
    output: {
      schema: {
        type: "object",
        additionalProperties: false,
        properties: {
          session: { type: "string", required: true },
          outcome: { type: "string", required: true },
          requiresHuman: { type: "boolean", required: true },
          redacted: { type: "boolean", required: true }
        }
      },
      render: (_args, value) => [{
        type: "text",
        text: `[session ${value.session}] human browser takeover: ${value.outcome}`
      }]
    },
    timeoutMs: resolved.helpTimeoutMs + 5000,
    async execute(args, exec) {
      const input = validateHelpInput(args, state);
      const result = await client.requestHelp({
        session_id: input.session,
        domain: input.domain,
        reason: input.prompt,
        title: input.title,
        targets: input.targets,
        timeout_ms: resolved.helpTimeoutMs
      }, exec.signal);
      const outcome = typeof result?.outcome === "string" ? result.outcome : "requested";
      return {
        session: input.session,
        outcome: outcome.slice(0, 40),
        requiresHuman: true,
        redacted: true
      };
    },
    presentCall: () => ({
      card: "generic",
      title: "Request human browser help",
      kind: "browser-request-help",
      rawInput: "human takeover"
    })
  }));

  ctx.effect(() => () => {
    unregisterPolicySkill();
    state.sessions.clear();
    state.domains.clear();
    state.currentSession = null;
  });
}

export {
  BrowserPolicyClient,
  Config,
  SessionState,
  apply,
  buildPolicyMetadata,
  classifyTarget,
  domainFromUrl,
  gateBrowserTool,
  isBrowserToolName,
  inject,
  looksLikeSecretText,
  name,
  normalizeHost,
  resolvePolicyEndpoint,
  validateHelpInput
};
