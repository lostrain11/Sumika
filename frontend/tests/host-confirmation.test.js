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
  assert.equal(requiresHostConfirmation("agent.mcp.configuration.apply"), true);
  assert.equal(requiresHostConfirmation("agent.session.retry"), true);
  for (const method of ["agent.skills.approve", "agent.skill.approve", "agent.skills.revoke", "agent.skill.revoke"]) {
    assert.equal(requiresHostConfirmation(method), true);
  }
  for (const method of ["workspace.worktree.create", "workspace.commit", "workspace.restore"]) {
    assert.equal(requiresHostConfirmation(method), true);
  }
  assert.equal(requiresHostConfirmation("work.task.get"), false);
});

test("only exact revocations bypass native authority", () => {
  for (const [method, params] of [
    ["module.update", { module_id: "tools", enabled: false }],
    ["audio.permission.set", { permission: "microphone", granted: false }],
    ["vision.permission.set", { permission: "camera.read", granted: false }],
    ["skill.builtin.set", { skill_id: "fixture", enabled: false, sha256: "abc" }],
    ["schedule.pause", { schedule_id: "fixture", paused: true }],
    ["browser.web_chat.profile.consent", { profile_id: "fixture", enabled: false }],
    ["desktop.automation.approval", { operation: "deny" }],
    ["sumika.route.bridge_tools", {}],
  ]) assert.equal(requiresHostConfirmation(method, params), false, method);
  for (const value of [true, "false", 0, 1, null, [], {}]) {
    assert.equal(requiresHostConfirmation("audio.permission.set", { granted: value }), true);
    assert.equal(requiresHostConfirmation("module.update", { enabled: value }), true);
    assert.equal(requiresHostConfirmation("sumika.route.bridge_tools", { register: value }), true);
  }
  assert.equal(requiresHostConfirmation("module.update", { enabled: false, config: {} }), true);
  assert.equal(requiresHostConfirmation("browser.web_chat.profile.consent", { enabled: false, allowed_actions: ["chat.send"] }), true);
  assert.equal(requiresHostConfirmation("desktop.automation.act", { approved: false, request: { approved: true } }), true);
  assert.equal(requiresHostConfirmation("browser.action.execute", { approved: false }), true);
  assert.equal(requiresHostConfirmation("tool.run", { approved: false }), false);
  assert.equal(requiresHostConfirmation("tool.run", { approved: "false" }), true);
  for (const operation of [[], {}, ["deny"], null, 1]) {
    assert.equal(requiresHostConfirmation("desktop.automation.approval", { operation }), true);
  }
  assert.equal(requiresHostConfirmation("desktop.automation.approval", { action: " REVOKE " }), false);
});

test("bridge background calls use native authority without an approval flag", async () => {
  for (const operation of ["attach", "poll", "complete", "alive", "bind_portal"]) {
    const method = `browser.embedded.${operation}`;
    const { calls, args } = fixture({ method, params: {} });
    await confirmThroughHost(args);
    assert.equal(calls[1][1], "host_confirm");
    assert.deepEqual(calls[1][2].params, {});
    const companion = fixture({ method, params: {}, companion: true });
    await assert.rejects(confirmThroughHost(companion.args), /陪伴窗口/);
    assert.deepEqual(companion.calls, [["openMain"]]);
  }
});

test("helper never forwards public revocations, ingestion or unavailable merge actions", async () => {
  for (const [method, params] of [
    ["module.update", { enabled: false }], ["agent.event.ingest", { approved: true }],
    ["work.task.merge.apply", {}], ["work.task.merge.undo", {}],
  ]) {
    const { calls, args } = fixture({ method, params });
    await assert.rejects(confirmThroughHost(args), /不支持/);
    assert.deepEqual(calls, []);
  }
});
