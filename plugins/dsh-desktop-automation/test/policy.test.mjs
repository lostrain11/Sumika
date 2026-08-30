import { strict as assert } from "node:assert";
import { createServer } from "node:http";
import { test } from "node:test";

import {
  DesktopPolicyClient,
  buildDesktopMetadata,
  containsSensitive,
  gateDesktopTool,
  isDesktopToolName,
  postJson,
  resolvePolicyEndpoint
} from "../lib/policy.mjs";

test("endpoint resolution stays on the configured loopback", () => {
  assert.equal(
    resolvePolicyEndpoint("", { SUMIKA_CORE_HOST: "::1", SUMIKA_CORE_PORT: "8772" }),
    "http://[::1]:8772/rpc"
  );
  assert.equal(
    resolvePolicyEndpoint("http://127.0.0.1:9000/custom", {}),
    "http://127.0.0.1:9000/custom"
  );
  assert.equal(buildDesktopMetadata({ name: "desktop_unknown", arguments: {} }), null);
});

test("desktop metadata and sensitive input are bounded", () => {
  assert.equal(isDesktopToolName("desktop_app_act"), true);
  assert.equal(isDesktopToolName("browser_click"), false);
  const metadata = buildDesktopMetadata({
    name: "desktop_app_act",
    arguments: { session_id: "session-1", request: { action: "click" } }
  });
  assert.equal(metadata.session_id, "session-1");
  assert.equal(metadata.sensitive, false);
  assert.equal(
    containsSensitive({ nested: [{ authorization: "Bearer hidden-value" }] }),
    true
  );
  assert.equal(containsSensitive({ text: "ordinary note" }), false);
  assert.throws(
    () => buildDesktopMetadata({ name: "desktop_app_observe", arguments: { session_id: "bad id" } }),
    /session_id is invalid/
  );
});

test("pre-execute gate denies unknown and credential-shaped desktop calls", async () => {
  const next = async () => ({ kind: "allow" });
  const allowed = await gateDesktopTool(
    { name: "desktop_app_observe", arguments: { session_id: "session-1" } },
    next
  );
  assert.deepEqual(allowed, { kind: "allow" });

  const unknown = await gateDesktopTool(
    { name: "desktop_app_future", arguments: {} },
    next
  );
  assert.equal(unknown.kind, "deny");

  const denied = await gateDesktopTool(
    {
      name: "desktop_app_act",
      arguments: { request: { action: "fill", args: { password: "secret" } } }
    },
    next
  );
  assert.equal(denied.kind, "deny");
  assert.match(denied.reason, /credential|user/i);
});

test("policy client emits a standard JSON-RPC request through the injected transport", async () => {
  const calls = [];
  const client = new DesktopPolicyClient({
    endpoint: "http://127.0.0.1:8771/rpc",
    post: async (endpoint, payload, options) => {
      calls.push({ endpoint, payload, options });
      return { accepted: true, token: "must not be logged" };
    }
  });
  const result = await client.call("desktop.automation.catalog", { refresh: false });
  assert.deepEqual(result, { accepted: true, token: "must not be logged" });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].endpoint, "http://127.0.0.1:8771/rpc");
  assert.equal(calls[0].payload.jsonrpc, "2.0");
  assert.equal(calls[0].payload.method, "desktop.automation.catalog");
  assert.deepEqual(calls[0].payload.params, { refresh: false });
  assert.equal(calls[0].options.timeoutMs, 1500);
});

test("postJson only talks to loopback and redacts bounded response fields", async () => {
  const server = createServer((_request, response) => {
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({ result: { ok: true, token: "secret-value", path: "C:\\private\\app" } }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  try {
    const value = await postJson(`http://127.0.0.1:${address.port}/rpc`, { hello: "world" });
    assert.equal(value.ok, true);
    assert.equal(value.token, "[redacted]");
    assert.equal(value.path, "[redacted]");
  } finally {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
  assert.throws(
    () => postJson("https://example.com/rpc", {}),
    /loopback-only/
  );
});
