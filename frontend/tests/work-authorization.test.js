import assert from "node:assert/strict";
import test from "node:test";
import { createWorkAuthorizationClient } from "../src/work-authorization.js";

test("external approval retains identity and resumes only from the original entry", async () => {
  const calls = [];
  let pending;
  const request = { request_id: "external", assistant_id: "sumika", status: "awaiting-confirmation", external: { limit_enforced: true }, quote: { high_cny: "2" } };
  const rpc = createWorkAuthorizationClient({
    scope: () => ({ assistant_id: "sumika", core_session_id: "core" }),
    transport: async (method, params) => {
      calls.push({ method, params });
      return { accepted: calls.length > 1, work_request: { ...request, status: calls.length > 1 ? "executing" : request.status } };
    },
    onPending: (_, continuation) => { pending = continuation; },
    onResult: () => {},
  });
  const result = rpc("agent.session.prompt", { sessionId: "agent", text: "work" });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 1);
  await pending.resume();
  await result;
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(calls[0].params.core_session_id, "core");
});

test("unknown cost cannot expose a resume callback or issue confirmation", async () => {
  let count = 0;
  let continuation = "unset";
  const request = { status: "awaiting-confirmation", external: { limit_enforced: false }, quote: { high_cny: null } };
  const rpc = createWorkAuthorizationClient({
    scope: () => ({}), transport: async () => { count++; return { accepted: false, work_request: request }; },
    onPending: (_, value) => { continuation = value; }, onResult: () => {},
  });
  await rpc("browser.web_chat.send", { text: "hello" });
  assert.equal(count, 1);
  assert.equal(continuation, null);
});

test("cancellation resolves the pending UI request without dispatching a second cancel", async () => {
  const calls = [];
  let pending;
  const rpc = createWorkAuthorizationClient({
    scope: () => ({}), transport: async method => { calls.push(method); return {
      accepted: false, work_request: { status: "awaiting-confirmation", external: { limit_enforced: true }, quote: { high_cny: "0" } },
    }; }, onResult: () => {}, onPending: (_, value) => { pending = value; },
  });
  const result = rpc("agent.session.prompt", { text: "hello" });
  await new Promise(resolve => setImmediate(resolve));
  pending.cancel();
  assert.equal((await result).accepted, false);
  assert.deepEqual(calls, ["agent.session.prompt"]);
});
