import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import {
  BrowserPolicyClient,
  SessionState,
  buildPolicyMetadata,
  classifyTarget,
  domainFromUrl,
  gateBrowserTool,
  isBrowserToolName,
  validateHelpInput,
  resolvePolicyEndpoint
} from "../lib/policy.mjs";

test("policy endpoint follows explicit config, managed Core environment, and desktop default", () => {
  assert.equal(resolvePolicyEndpoint("http://127.0.0.1:3000/rpc", { SUMIKA_CORE_PORT: "8771" }), "http://127.0.0.1:3000/rpc");
  assert.equal(resolvePolicyEndpoint("", { SUMIKA_CORE_ENDPOINT: "http://127.0.0.1:8772/rpc" }), "http://127.0.0.1:8772/rpc");
  assert.equal(resolvePolicyEndpoint("", { SUMIKA_CORE_HOST: "127.0.0.1", SUMIKA_CORE_PORT: "8773" }), "http://127.0.0.1:8773/rpc");
  assert.equal(resolvePolicyEndpoint("", {}), "http://127.0.0.1:8771/rpc");
});

test("URL and target helpers return only bounded metadata", () => {
  assert.deepEqual(domainFromUrl("https://Example.com/path?token=private"), { domain: "example.com", newTab: false });
  assert.deepEqual(domainFromUrl("chrome://newtab/"), { domain: null, newTab: true });
  assert.equal(classifyTarget("@e12"), "snapshot_ref");
  assert.equal(classifyTarget("#password"), "css_selector");
  assert.throws(() => domainFromUrl("https://user:secret@example.com/"));
});

test("session tracking follows successful BrowserSkill result fields", () => {
  const state = new SessionState();
  state.observeResult("browser_session_start", { isError: false, value: { sessionId: "bsk-1", url: "https://example.com/" } });
  assert.equal(state.currentSession, "bsk-1");
  assert.equal(state.domains.get("bsk-1"), "example.com");
  state.observeResult("browser_navigate", { isError: false, value: { session: "bsk-1", finalUrl: "https://other.example/" } });
  assert.equal(state.domains.get("bsk-1"), "other.example");
  state.observeResult("browser_session_stop", { isError: false, value: { stopped: "bsk-1" } });
  assert.equal(state.sessions.has("bsk-1"), false);
});

test("policy metadata never includes browser target or value", () => {
  const state = new SessionState();
  state.remember("bsk-1", "https://example.com/");
  const metadata = buildPolicyMetadata({
    name: "browser_fill",
    arguments: { session: "bsk-1", target: "#password", value: "private-secret" }
  }, state);
  assert.equal(metadata.sensitive, true);
  assert.equal(metadata.value_length, 14);
  assert.equal(Object.hasOwn(metadata, "value"), false);
  assert.equal(Object.hasOwn(metadata, "target"), false);
});

test("gate maps allow, ask, deny, and an unavailable Core to the DSH seam", async () => {
  const state = new SessionState();
  state.remember("bsk-1", "https://example.com/");
  const calls = [];
  const next = async () => {
    calls.push("next");
    return { kind: "allow" };
  };
  const allowed = await gateBrowserTool(
    { name: "browser_snapshot", arguments: { session: "bsk-1" }, signal: new AbortController().signal },
    next,
    { state, client: { evaluate: async () => ({ decision: "allow" }) } }
  );
  assert.deepEqual(allowed, { kind: "allow" });
  assert.deepEqual(calls, ["next"]);
  const asked = await gateBrowserTool(
    { name: "browser_click", arguments: { session: "bsk-1", target: "@e1" }, signal: new AbortController().signal },
    next,
    { state, client: { evaluate: async () => ({ decision: "ask", reason: "approval" }) } }
  );
  assert.deepEqual(asked, { kind: "ask", reason: "approval" });
  const denied = await gateBrowserTool(
    { name: "browser_fill", arguments: { session: "bsk-1", target: "#password", value: "secret" }, signal: new AbortController().signal },
    next,
    { state, client: { evaluate: async () => ({ decision: "deny", reason: "manual" }) } }
  );
  assert.deepEqual(denied, { kind: "deny", reason: "manual" });
  const unavailable = await gateBrowserTool(
    { name: "browser_snapshot", arguments: { session: "bsk-1" }, signal: new AbortController().signal },
    next,
    { state, client: { evaluate: async () => { throw new Error("offline"); } } }
  );
  assert.equal(unavailable.kind, "deny");
  assert.equal(calls.length, 1);
});

test("unknown browser tools fail closed while unrelated tools pass through", async () => {
  assert.equal(isBrowserToolName("browser_hover"), true);
  assert.equal(isBrowserToolName("shell"), false);
  let nextCalls = 0;
  const next = async () => {
    nextCalls += 1;
    return { kind: "allow" };
  };
  const unknown = await gateBrowserTool(
    { name: "browser_hover", arguments: {}, signal: new AbortController().signal },
    next,
    { state: new SessionState(), client: { evaluate: async () => ({ decision: "allow" }) } }
  );
  assert.deepEqual(unknown, { kind: "deny", reason: "unsupported browser tool; Sumika policy mapping is required" });
  const unrelated = await gateBrowserTool({ name: "shell", arguments: {} }, next, {
    state: new SessionState(),
    client: { evaluate: async () => ({ decision: "allow" }) }
  });
  assert.deepEqual(unrelated, { kind: "allow" });
  assert.equal(nextCalls, 1);
});

test("human help validates ownership and uses a separate client method", async () => {
  const state = new SessionState();
  state.remember("bsk-1", "https://accounts.example/");
  const input = validateHelpInput({ session: "bsk-1", prompt: "Complete the login in the isolated window", target: ["#login"] }, state);
  assert.equal(input.domain, "accounts.example");
  assert.throws(() => validateHelpInput({ session: "bsk-1", prompt: "password: private-secret" }, state));
  assert.throws(() => validateHelpInput({ session: "foreign", prompt: "continue" }, state));
  const requests = [];
  const client = new BrowserPolicyClient({ post: async (_endpoint, request) => { requests.push(request); return { outcome: "continued" }; } });
  const result = await client.requestHelp({ session_id: input.session, domain: input.domain, reason: input.prompt, targets: input.targets }, new AbortController().signal);
  assert.equal(result.outcome, "continued");
  assert.equal(requests[0].method, "browser.policy.request_help");
});

test("the real policy client sends JSON-RPC only to loopback and validates the decision", async () => {
  const requests = [];
  const server = createServer((request, response) => {
    let body = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => { body += chunk; });
    request.on("end", () => {
      requests.push(JSON.parse(body));
      response.setHeader("content-type", "application/json");
      response.end(JSON.stringify({ jsonrpc: "2.0", id: requests[0].id, result: { decision: "allow", reason: "ok" } }));
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    const client = new BrowserPolicyClient({ endpoint: `http://127.0.0.1:${address.port}/rpc` });
    const result = await client.evaluate({ tool_name: "browser_snapshot", action: "snapshot", session_id: "bsk-1" }, new AbortController().signal);
    assert.equal(result.decision, "allow");
    assert.equal(requests[0].method, "browser.policy.evaluate");
    assert.equal(Object.hasOwn(requests[0].params, "value"), false);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
