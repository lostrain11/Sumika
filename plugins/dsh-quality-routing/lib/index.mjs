import Schema from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";

import { ManagedQualityHelper } from "./helper-client.mjs";
import { QUALITY_ROUTING_TOOLS, resolveHelperConfig } from "./policy.mjs";

const name = "sumika-dsh-quality-routing";
const inject = ["tools"];

const Config = Schema.object({
  pythonExecutable: Schema.string().default("").description("Absolute Python executable from an environment containing quality-routing."),
  dataDirectory: Schema.string().default("").description("Absolute private data directory owned by this helper instance."),
  startupTimeoutMs: Schema.number().default(5000).description("Maximum helper startup time."),
  requestTimeoutMs: Schema.number().default(10000).description("Maximum time for one helper request."),
  enabled: Schema.boolean().default(false).description("Start the independent managed helper and install its tools.")
});

const OUTPUT = Object.freeze({
  schema: { type: "json" },
  render: (_args, value) => {
    const encoded = JSON.stringify(value);
    return [{ type: "text", text: (encoded === undefined ? String(value) : encoded).slice(0, 32000) }];
  }
});

function installTool(ctx, client, specification) {
  ctx.tools.register(defineTool({
    ...specification,
    parameters: {},
    output: OUTPUT,
    execute: () => client.call(specification.method)
  }));
}

async function apply(ctx, config = {}) {
  const resolved = resolveHelperConfig(config);
  if (!resolved.enabled) return;
  const client = new ManagedQualityHelper(resolved);
  await client.start();
  installTool(ctx, client, {
    name: "quality_routing_component_status",
    method: "capabilities",
    description: "Read independent quality-routing capabilities. This tool cannot approve or invoke a model.",
    presentCall: () => ({ card: "generic", title: "Quality routing status", kind: "quality-routing-status", rawInput: "status" })
  });
  installTool(ctx, client, {
    name: "quality_routing_offline_fixture",
    method: "offline_fixture",
    description: "Run the deterministic offline lifecycle fixture. It does not call or evaluate a real model.",
    presentCall: () => ({ card: "generic", title: "Offline routing fixture", kind: "quality-routing-fixture", rawInput: "fixture" })
  });
  if (typeof ctx.effect === "function") ctx.effect(() => () => client.close());
}

export { Config, ManagedQualityHelper, QUALITY_ROUTING_TOOLS, apply, inject, name, resolveHelperConfig };

