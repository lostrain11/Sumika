import assert from "node:assert/strict";
import test from "node:test";
import { confirmThroughHost, requiresHostConfirmation } from "../src/host-confirmation.js";

function fixture(overrides = {}) {
  const calls = [];
  return { calls, args: { method: "work.authorization.confirm", params: { request_id: "one", revision: 1, max_cny: "2" },
    desktop: true, companion: false,
    transport: async (...args) => { calls.push(["transport", ...args]); return { digest: "fixture-digest" }; },
    invoke: async (...args) => { calls.push(["invoke", ...args]); return { status: "ready" }; },
    openMain: async () => { calls.push(["openMain"]); }, ...overrides } };
}

test("native confirmation binds a detached request and never sends approval by HTTP", async () => {
  const { calls, args } = fixture();
  const pending = confirmThroughHost(args);
  args.params.max_cny = "999";
  assert.equal((await pending).status, "ready");
  assert.equal(calls[0][1], "host.confirmation.digest");
  assert.equal(calls[1][1], "host_confirm");
  assert.equal(calls[1][2].params.max_cny, "2");
});

test("ordinary browser cannot confirm or fall back to HTTP", async () => {
  const { calls, args } = fixture({ desktop: false });
  await assert.rejects(confirmThroughHost(args), /原生工作台/);
  assert.deepEqual(calls, []);
});

test("companion redirects without performing an authorization", async () => {
  const { calls, args } = fixture({ companion: true });
  await assert.rejects(confirmThroughHost(args), /陪伴窗口/);
  assert.deepEqual(calls, [["openMain"]]);
});

test("unknown native submission is not retried", async () => {
  let attempts = 0;
  const { calls, args } = fixture({ invoke: async () => { attempts++; throw new Error("submit-unknown"); } });
  await assert.rejects(confirmThroughHost(args), /submit-unknown/);
  assert.equal(attempts, 1);
  assert.equal(calls.length, 1);
});

test("unrelated RPC is never forwarded by the confirmation helper", async () => {
  const { calls, args } = fixture({ method: "chat.send" });
  await assert.rejects(confirmThroughHost(args), /不支持/);
  assert.deepEqual(calls, []);
  assert.equal(requiresHostConfirmation("agent.approval.respond"), true);
  assert.equal(requiresHostConfirmation("agent.question.respond"), true);
  assert.equal(requiresHostConfirmation("work.task.get"), false);
});
