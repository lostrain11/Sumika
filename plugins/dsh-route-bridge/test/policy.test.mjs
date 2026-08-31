import { strict as assert } from "node:assert";
import { createServer } from "node:http";
import { test } from "node:test";

import {
  ROUTE_TOOLS,
  RoutePolicyClient,
  buildRoutePayload,
  containsSensitive,
  gateRouteTool,
  postJson,
  resolvePolicyEndpoint
} from "../lib/policy.mjs";

test("endpoint resolution and route tool map stay loopback-only", () => {
  assert.equal(resolvePolicyEndpoint("", { SUMIKA_CORE_HOST: "::1", SUMIKA_CORE_PORT: "8772" }), "http://[::1]:8772/rpc");
  assert.equal(resolvePolicyEndpoint("http://127.0.0.1:9000/custom", {}), "http://127.0.0.1:9000/custom");
  assert.equal(ROUTE_TOOLS.sumika_route_catalog, "sumika.route.catalog");
  assert.throws(() => postJson("https://example.com/rpc", {}), /loopback-only/);
});

test("route payloads take parent ids from execution context and bound context", () => {
  const payload = buildRoutePayload("sumika_route_dispatch", {
    routeId: "web:profile-1",
    question: "review this small design",
    contextRefs: { summary: "short" }
  }, { context: { sessionId: "session-1", turnId: "turn-1" } });
  assert.equal(payload.parent_session_id, "session-1");
  assert.equal(payload.parent_turn_id, "turn-1");
  assert.equal(payload.route_id, "web:profile-1");
  assert.deepEqual(payload.context_refs, { summary: "short" });
  assert.throws(() => buildRoutePayload("sumika_route_dispatch", { routeId: "web:p", question: "x", contextRefs: { api_key: "hidden" } }, { sessionId: "s" }), /credential|sensitive/i);
  assert.throws(() => buildRoutePayload("sumika_route_replan", { question: "x", triggerEvent: "model.streaming" }, { sessionId: "s" }), /trigger_event/i);
});

test("consultation and status payloads are validated without forwarding arbitrary args", () => {
  const consultation = buildRoutePayload("sumika_consultation_start", {
    question: "compare two designs",
    decisionKind: "plan-review",
    maxMembers: 2,
    contextRefs: { goal: "bounded" }
  }, { sessionId: "parent" });
  assert.equal(consultation.parent_session_id, "parent");
  assert.equal(consultation.max_members, 2);
  assert.equal(consultation.decision_kind, "plan-review");
  assert.equal(Object.prototype.hasOwnProperty.call(consultation, "unexpected"), false);
  const status = buildRoutePayload("sumika_consultation_status", {}, { sessionId: "parent" });
  assert.equal(status.parent_session_id, "parent");
  assert.throws(() => buildRoutePayload("sumika_route_status", { dispatchId: "bad id" }, {}), /dispatch_id/);
});

test("pre-execute gate is fail-closed for unknown or sensitive route calls", async () => {
  const next = async () => ({ kind: "allow" });
  assert.deepEqual(await gateRouteTool({ name: "sumika_route_catalog", arguments: {} }, next), { kind: "allow" });
  const unknown = await gateRouteTool({ name: "sumika_route_future", arguments: {} }, next);
  assert.equal(unknown.kind, "deny");
  const denied = await gateRouteTool({ name: "sumika_route_dispatch", arguments: { routeId: "r", question: "x", parentSessionId: "s", context: { token: "secret" } } }, next);
  assert.equal(denied.kind, "deny");
  assert.equal(containsSensitive({ nested: [{ authorization: "Bearer hidden-value" }] }), true);
});

test("client handshakes once and calls the mapped Core method", async () => {
  const calls = [];
  const client = new RoutePolicyClient({
    endpoint: "http://127.0.0.1:8771/rpc",
    post: async (_endpoint, payload) => {
      calls.push(payload);
      if (payload.method === "sumika.route.bridge_tools") return { registered: true, status: "registered" };
      return { schema: "agent-route/v1", routes: [] };
    }
  });
  const result = await client.call("sumika_route_catalog", { refresh: false });
  assert.deepEqual(result.routes, []);
  assert.equal(calls.filter((item) => item.method === "sumika.route.bridge_tools").length, 1);
  await client.call("sumika_route_catalog", { refresh: false });
  assert.equal(calls.filter((item) => item.method === "sumika.route.bridge_tools").length, 1);
  assert.equal(calls.at(-1).method, "sumika.route.catalog");
});

test("postJson returns bounded Core result", async () => {
  const server = createServer((_request, response) => {
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({ result: { registered: true, token: "secret-value", path: "C:\\private\\route" } }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  try {
    const result = await postJson(`http://127.0.0.1:${address.port}/rpc`, { hello: "world" });
    assert.equal(result.registered, true);
    assert.equal(result.token, "[redacted]");
    assert.match(result.path, /LOCAL_PATH/);
  } finally {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});
