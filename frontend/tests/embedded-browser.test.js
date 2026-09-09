import assert from "node:assert/strict";
import test from "node:test";
import { browserLinkSite, createEmbeddedBrowserController } from "../src/embedded-browser-view.js";

const site = { id: "chatgpt", url: "https://chatgpt.com/", title: "ChatGPT" };

test("同站不同路径独立标签，保留同一已选账户", async () => {
  const known = { id: "moark", site_id: "moark", url: "https://moark.com/", title: "Moark" };
  const home = await browserLinkSite(known.url, "", known);
  const billing = await browserLinkSite("https://moark.com/serverless-api", "账单", known);
  const pricing = await browserLinkSite("https://moark.com/pricing", "价格", known);
  assert.equal(home.id, known.id);
  assert.equal(billing.account_id, known.id);
  assert.equal(billing.site_id, known.site_id);
  assert.notEqual(billing.tab_id, pricing.tab_id);
  assert.equal((await browserLinkSite(billing.url, "", known)).tab_id, billing.tab_id);
});
function fixture(overrides = {}) {
  const calls = [];
  const state = { portalPanelOpen: false, overlayMode: false };
  const controller = createEmbeddedBrowserController({
    state, isDesktop: true, render() {}, escapeHtml: String,
    showConsultation: async () => {}, hideConsultation: async () => {},
    setTimer: () => 1, clearTimer() {},
    invoke: async (command, payload) => {
      calls.push({ command, payload });
      if (overrides.invoke) return overrides.invoke(command, payload);
      return payload?.action === "fill" ? { status: "filled" } : {};
    },
    rpc: async (method, params) => {
      calls.push({ method, params });
      if (overrides.rpc) return overrides.rpc(method, params);
      return { token: "fixture-token" };
    },
  });
  return { controller, state, calls };
}

test("仅桌面公开 HTTPS 页可开；不同账户保留明确标识", async () => {
  const { controller, calls } = fixture();
  for (const url of ["http://example.com", "https://127.0.0.1", "https://user:password@chatgpt.com/"]) {
    await assert.rejects(controller.open({ ...site, url }));
  }
  await controller.open({ ...site, tab_id: "chat-alice", account_id: "alice" });
  const opened = calls.find((row) => row.command === "embedded_browser_open");
  assert.equal(opened.payload.accountId, "alice");
  assert.equal(opened.payload.tabId, "chat-alice");
  assert.ok(!calls.some((row) => /open_portal|browser\.session/.test(row.command || row.method)));
});

test("隐藏之后迟到的填写结果不会提交", async () => {
  let completeFill;
  const { controller, calls } = fixture({ invoke: async (command, payload) => payload?.action === "fill"
    ? new Promise((resolve) => { completeFill = resolve; }) : {} });
  await controller.open(site);
  const sending = controller.send("synthetic fixture");
  await controller.hide();
  completeFill({ status: "filled" });
  await sending;
  assert.equal(calls.filter((row) => row.payload?.action === "submit").length, 0);
});

test("提交状态未知不重发，保留原 attempt 供读取", async () => {
  const { controller, calls } = fixture({ invoke: async (command, payload) => {
    if (payload?.action === "fill") return { status: "filled" };
    if (payload?.action === "submit") throw new Error("transport lost");
    return {};
  } });
  await controller.open(site);
  await controller.send("synthetic fixture");
  assert.equal(controller.view.tabs[0].status, "unknown");
  assert.ok(controller.view.tabs[0].attempt_id);
  await controller.send("synthetic fixture");
  await controller.action("read");
  assert.equal(calls.filter((row) => row.payload?.action === "submit").length, 1);
  assert.equal(calls.find((row) => row.payload?.action === "read").payload.attemptId, controller.view.tabs[0].attempt_id);
});

test("账户维护保持当前标签和可见性，不触发模型", async () => {
  const request = { source: "ollama", tab_id: "account-ollama", account_id: "ollama", url: "https://ollama.com/settings", action: "read-account", attempt_id: "read-once" };
  let delivered = false;
  const { controller, state, calls } = fixture({ rpc: async (method) => method.endsWith(".poll")
    ? { request: delivered ? null : (delivered = true, request) } : { token: "fixture-token" },
  invoke: async (command, payload) => payload?.action === "read-account" ? { observation: { state: "verified", free_usage_percent: "0" } } : {} });
  await controller.open(site);
  await controller.attach();
  await controller.pump();
  await controller.pump();
  assert.equal(controller.view.active, "chatgpt");
  assert.equal(state.portalPanelOpen, true);
  assert.equal(calls.filter((row) => row.payload?.action === "read-account").length, 1);
  assert.equal(calls.filter((row) => row.method === "browser.embedded.complete").length, 1);
  assert.ok(!calls.some((row) => ["submit", "fill"].includes(row.payload?.action)));
});

test("核心启动晚于页面时重连维护桥，不发送网页消息", async () => {
  let attempts = 0;
  const { controller, calls } = fixture({ rpc: async (method) => {
    if (method === "browser.embedded.attach") {
      attempts += 1;
      if (attempts === 1) throw new Error("core-not-ready");
      return { token: "reconnected" };
    }
    return { request: null };
  } });
  await assert.rejects(controller.attach());
  assert.equal(controller.view.attached, false);
  await controller.pump();
  assert.equal(controller.view.attached, true);
  assert.equal(controller.view.token, "reconnected");
  await controller.pump();
  assert.equal(attempts, 2);
  assert.equal(calls.filter((row) => row.method === "browser.embedded.poll").length, 1);
  assert.ok(!calls.some((row) => row.command));
});

test("失效维护连接重新绑定，桌宠不重连", async () => {
  const { controller, state, calls } = fixture({ rpc: async (method) => {
    if (method === "browser.embedded.poll") throw new Error("core-restarted");
    return { token: "new-core" };
  } });
  await controller.attach();
  await controller.pump();
  assert.equal(controller.view.attached, false);
  state.overlayMode = true;
  await controller.pump();
  assert.equal(calls.filter((row) => row.method === "browser.embedded.attach").length, 1);
  state.overlayMode = false;
  await controller.pump();
  assert.equal(controller.view.attached, true);
  assert.equal(calls.filter((row) => row.method === "browser.embedded.attach").length, 2);
});

test("用户接管阻止同一账户后台读取", async () => {
  const request = { source: "ollama", tab_id: "account-ollama", account_id: "ollama", url: "https://ollama.com/settings", action: "read-account", attempt_id: "read-once" };
  const { controller, calls } = fixture({ rpc: async (method) => method.endsWith(".poll") ? { request } : { token: "fixture-token" } });
  await controller.open({ id: "ollama", url: request.url });
  await controller.action("takeover");
  await controller.attach();
  await controller.pump();
  assert.equal(calls.find((row) => row.method === "browser.embedded.complete").params.observation.state, "takeover");
  assert.equal(calls.filter((row) => row.payload?.action === "read-account").length, 0);
});

test("桌宠不接收后台网页操作", async () => {
  const { controller, state, calls } = fixture();
  state.overlayMode = true;
  await controller.attach();
  await controller.pump();
  assert.equal(calls.find((row) => row.method === "browser.embedded.poll").params.accept_requests, false);
});

test("后端网页任务取消后不提交，原 attempt 不重新排队", async () => {
  let active = true;
  const { controller, calls } = fixture({
    rpc: async (method) => method.endsWith(".alive") ? { active } : { token: "fixture-token" },
    invoke: async (command, payload) => {
      if (payload?.action === "observe") return { status: "ready" };
      if (payload?.action === "fill") { active = false; return { status: "filled" }; }
      return {};
    },
  });
  const result = await controller.exchange({ tab_id: "task-chat", account_id: "task-account", url: site.url,
    operation: "send", automation_supported: true, attempt_id: "host-request", message_attempt_id: "message-one", text: "fixture" });
  assert.equal(result.status, "not-sent");
  assert.equal(result.possibly_sent, false);
  assert.equal(calls.filter((row) => row.payload?.action === "submit").length, 0);
});

test("后端与手动网页操作共用同一标签，不打开外部窗口", async () => {
  const { controller, calls } = fixture({ rpc: async () => ({ active: true }) });
  const result = await controller.exchange({ tab_id: "task-chat", account_id: "task-account", url: site.url, operation: "open", attempt_id: "host-open" });
  assert.equal(result.status, "opened");
  assert.equal(controller.view.active, "task-chat");
  assert.equal(calls.filter((row) => row.command === "embedded_browser_open").length, 1);
});
