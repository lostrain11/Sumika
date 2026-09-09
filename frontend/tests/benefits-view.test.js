import assert from "node:assert/strict";
import test from "node:test";

import { benefitsOfferStatus, benefitsSourceKind, createBenefitsController, createBenefitsState, filterBenefitsOffers, renderBenefitsGrants, renderBenefitsOffers, renderBenefitsSection, safeBenefitsUrl } from "../src/benefits-view.js";
import { createQualityRoutingView } from "../src/quality-routing-view.js";

function snapshot(overrides = {}) {
  return { schema: "benefits/v1", enabled: false, checkin_enabled: false, browser_instance_id: "", running: false, sources: [], offers: [], checkin: { state: "never", checked_at: null, available_balance: null, unit: "magicube", grants: [], error: null }, ...overrides };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; });
  return { promise, resolve, reject };
}

function harness(responder = () => snapshot()) {
  const state = { benefits: createBenefitsState() };
  const calls = [];
  const timers = new Map();
  let scope = "Settings:sumika:default";
  let nextTimer = 0;
  const controller = createBenefitsController({
    state,
    getScope: () => scope,
    rpc: (method, params) => { calls.push({ method, params }); return responder(method, params); },
    setTimer: (callback, delay) => { const handle = ++nextTimer; timers.set(handle, { callback, delay }); return handle; },
    clearTimer: (handle) => timers.delete(handle),
  });
  return {
    state, controller, calls, timers,
    setScope: (next, sync = true) => { scope = next; if (sync) controller.syncScope(); },
    tick: async () => {
      assert.equal(timers.size, 1);
      const [handle, timer] = [...timers][0];
      timers.delete(handle);
      assert.equal(timer.delay, 2500);
      timer.callback();
      await Promise.resolve();
      await Promise.resolve();
    },
  };
}

test("external links accept only public HTTPS DNS names without credentials", () => {
  const unsafe = [
    "", null, {}, "javascript:alert(1)", "data:text/html,hello", "file:///etc/passwd", "/relative", "//example.com", "http://example.com",
    "https://user:password@example.com", "https://user@example.com", "https://@example.com", "https://example.com@localhost", "https://example.com\\@localhost",
    "https://localhost", "https://localhost.", "https://sub.localhost", "https://intranet", "https://printer.local", "https://service.internal", "https://router.home.arpa",
    "https://127.0.0.1", "https://127.1", "https://2130706433", "https://0x7f000001", "https://0177.0.0.1", "https://10.0.0.1", "https://172.16.1.2",
    "https://192.168.1.1", "https://169.254.169.254", "https://100.64.0.1", "https://0.0.0.0", "https://[::1]", "https://[fd00::1]", "https://[::ffff:127.0.0.1]",
    "https://127.0.0.1.nip.io", "https://10.0.0.1.sslip.io", "https://localtest.me", "https://lvh.me", "https://%6cocalhost", "https://example..com", "https://a.invalid",
    " https://example.com", "https://exa\nmple.com", "https://example.com/\u0000", "https://example.com:99999", "https://example.com:8080",
  ];
  for (const url of unsafe) assert.equal(safeBenefitsUrl(url), "", String(url));
  assert.equal(safeBenefitsUrl("https://www.modelscope.cn/my/magicube"), "https://www.modelscope.cn/my/magicube");
  assert.equal(safeBenefitsUrl("https://new-ai-provider.example.com/free?sort=latest&limit=10#credits"), "https://new-ai-provider.example.com/free?sort=latest&limit=10#credits");
});

test("resources and leads include new providers, withdrawn offers and stale evidence", () => {
  const offers = [
    { id: "new-provider", kind: "free-model", provider_id: "not-in-catalog", state: "withdrawn", stale: true },
    { id: "credits", kind: "credit-program", provider_id: null },
    { id: "news", kind: "lead" },
    { id: "unsupported", kind: "unknown" }, null,
  ];
  assert.deepEqual(filterBenefitsOffers(offers).map((offer) => offer.id), ["new-provider", "credits"]);
  assert.deepEqual(filterBenefitsOffers(offers, "leads").map((offer) => offer.id), ["news"]);
  assert.deepEqual(filterBenefitsOffers(null), []);
});

test("all source, offer, browser, grant and service strings are escaped", () => {
  const hostile = '<img src=x onerror="alert(1)">&\'attack';
  const value = snapshot({
    browser_instance_id: hostile,
    browsers: [{ instance_id: hostile, browser_name: hostile }],
    sources: [{ id: "source", title: hostile, url: "javascript:alert(1)", status: hostile, error: hostile, item_count: hostile }],
    offers: [{ id: hostile, title: hostile, url: 'https://example.com/free?a=1&b="bad"', model_id: hostile, provider_id: hostile, source_id: "source", kind: "free-model", state: hostile, evidence: { public: hostile } }],
    checkin: { state: hostile, available_balance: 12, unit: hostile, grants: [hostile, { title: hostile }], error: hostile },
  });
  const html = renderBenefitsSection({ ...createBenefitsState(), loaded: true, snapshot: value, notice: hostile });
  assert.doesNotMatch(html, /<img|<script|href="javascript:|\[object Object\]/);
  assert.match(html, /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;&amp;&#39;attack/);
  assert.match(html, /href="https:\/\/example.com\/free\?a=1&amp;b=%22bad%22"/);
  assert.match(html, /rel="noopener noreferrer" referrerpolicy="no-referrer"/);
});

test("offer rows distinguish public evidence, source freshness and expiry", () => {
  const value = snapshot({
    sources: [{ id: "official", title: "新渠道官网", url: "https://new-provider.example.com", status: "stale", last_success_at: "2026-09-01T01:00:00Z" }],
    offers: [
      { id: "free", title: "LongModel".repeat(100), kind: "free-model", state: "withdrawn", stale: true, source_id: "official", evidence: "每日限免", expires_at: null },
      { id: "old-credit", title: "旧赠送额度", kind: "credit-program", state: "active", expires_at: "2000-01-01T00:00:00Z", evidence: "100 credits" },
      { id: "news", title: "未接入渠道资讯", kind: "lead", state: "active", url: "https://news.example.com", expires_at: "not-a-date" },
    ],
  });
  const html = renderBenefitsOffers(value);
  assert.match(html, /已撤回/);
  assert.match(html, /证据陈旧/);
  assert.match(html, /公开证据 · 非账户额度/);
  assert.match(html, /来源：<a[^>]+>新渠道官网<\/a> · 证据陈旧 · 来源类型未知 · 上次成功：2026/);
  assert.match(html, /到期未知/);
  assert.match(html, /已到期/);
  assert.doesNotMatch(html, /未接入渠道资讯/);
  assert.match(renderBenefitsOffers(value, "leads"), /未接入渠道资讯/);
});

test("initial section is collapsed and configuration stays inert until loaded", () => {
  const state = createBenefitsState();
  const html = renderBenefitsSection(state);
  assert.match(html, /<summary>免费资源与签到<\/summary>/);
  assert.doesNotMatch(html, /<details[^>]+\bopen\b|<input[^>]+checked/);
  assert.match(html, /name="enabled"[^>]*disabled/);
  assert.match(html, /name="checkin_enabled"[^>]*disabled/);
  assert.match(html, /data-benefits-action="checkin"[^>]*disabled/);
  assert.match(html, /模型与额度（0）/);
  assert.match(html, /资讯线索（0）/);
});

test("checkin states and unknown or zero balances stay distinct from public offers", () => {
  const labels = { never: "未读取", running: "进行中", verified: "已核实", "login-required": "待登录", challenge: "待验证", "needs-review": "待核对", unavailable: "不可用", interrupted: "已中断" };
  for (const [state, label] of Object.entries(labels)) {
    const html = renderBenefitsSection({ ...createBenefitsState(), loaded: true, snapshot: snapshot({ checkin: { state, unit: "magicube", available_balance: 0, grants: [] } }) });
    assert.match(html, new RegExp(`ModelScope 签到 · ${label}`));
    assert.match(html, /余额：0 魔粒/);
    assert.match(html, state === "verified" ? /账户余额/ : /上次观测余额/);
  }
  for (const balance of [null, undefined, "", " ", false, -1, "not-a-number"]) {
    assert.match(renderBenefitsSection({ ...createBenefitsState(), loaded: true, snapshot: snapshot({ checkin: { state: "never", available_balance: balance } }) }), /余额：未知/);
  }
});

test("routing evidence appends a sibling section without changing existing resources", () => {
  const state = { qualityRouting: {}, benefits: createBenefitsState() };
  const html = createQualityRoutingView({ state, escapeHtml: String }).renderRoutingEvidence();
  assert.match(html, /模型资源与刷新状态/);
  assert.match(html, /data-model-refresh/);
  assert.match(html, /<\/details><details class="benefits-section"/);
});

test("loading status never detects browsers, enables discovery or signs in", async () => {
  const { controller, calls, state } = harness();
  assert.equal(calls.length, 0);
  await controller.loadStatus();
  assert.deepEqual(calls, [{ method: "benefits.status", params: {} }]);
  assert.equal(state.benefits.loaded, true);
  assert.deepEqual(state.benefits.draft, { enabled: false, checkin_enabled: false, browser_instance_id: "" });
  controller.dispose();
});

test("explicit save enables discovery alone and sends the complete configuration", async () => {
  const { controller, calls, state } = harness((method, params) => snapshot(method === "benefits.configure" ? params : {}));
  await controller.loadStatus();
  controller.changeDraft({ enabled: true });
  assert.equal(calls.length, 1);
  assert.equal(state.benefits.snapshot.enabled, false);
  assert.match(renderBenefitsSection(state.benefits), /未保存/);
  await controller.act("configure");
  assert.deepEqual(calls[1], { method: "benefits.configure", params: { enabled: true, checkin_enabled: false, browser_instance_id: "" } });
  assert.equal(state.benefits.snapshot.enabled, true);
  assert.equal(state.benefits.notice, "已保存");
  controller.dispose();
});

test("browser detection is explicit and never chooses the first browser", async () => {
  const { controller, state, calls } = harness((method) => method === "benefits.browsers" ? { browsers: [{ instance_id: "edge-profile", browser_name: "Edge" }] } : snapshot());
  await controller.loadStatus();
  await controller.act("browsers");
  assert.deepEqual(calls.map((call) => call.method), ["benefits.status", "benefits.browsers"]);
  assert.equal(state.benefits.draft.browser_instance_id, "");
  assert.match(renderBenefitsSection(state.benefits), /Edge · edge-profile/);
  assert.doesNotMatch(renderBenefitsSection(state.benefits), /value="edge-profile" selected/);
  await controller.loadStatus();
  assert.equal(state.benefits.browsers[0].instance_id, "edge-profile");
  controller.dispose();
});

test("auto-checkin requires browser selection and saving a draft is explicit", async () => {
  const { controller, state, calls } = harness((method, params) => snapshot(method === "benefits.configure" ? params : {}));
  await controller.loadStatus();
  controller.changeDraft({ checkin_enabled: true });
  await controller.act("configure");
  assert.equal(calls.length, 1);
  assert.equal(state.benefits.notice, "未选择签到浏览器");
  controller.changeDraft({ browser_instance_id: "user-chosen-edge" });
  assert.equal(calls.length, 1);
  await controller.act("configure");
  assert.equal(calls.length, 1);
  assert.equal(state.benefits.notice, "后台发现未开启");
  controller.changeDraft({ enabled: true });
  await controller.act("configure");
  assert.deepEqual(calls[1].params, { enabled: true, checkin_enabled: true, browser_instance_id: "user-chosen-edge" });
  controller.dispose();
});

test("manual checkin works with automatic checkin off but not with an unsaved browser", async () => {
  let value = snapshot();
  const { controller, calls } = harness((method, params) => {
    if (method === "benefits.configure") value = snapshot(params);
    return value;
  });
  await controller.loadStatus();
  await controller.act("checkin");
  assert.equal(calls.length, 1);
  controller.changeDraft({ browser_instance_id: "edge-explicit" });
  await controller.act("checkin");
  assert.equal(calls.length, 1);
  await controller.act("configure");
  assert.equal(value.checkin_enabled, false);
  await controller.act("checkin");
  assert.deepEqual(calls.at(-1), { method: "benefits.checkin", params: {} });
  controller.dispose();
});

test("manual refresh starts discovery and polls only while the returned snapshot runs", async () => {
  let reading = 0;
  const context = harness((method) => {
    if (method === "benefits.refresh") return snapshot({ running: true });
    reading += 1;
    return snapshot({ running: reading === 2 });
  });
  await context.controller.loadStatus();
  assert.equal(context.timers.size, 0);
  await context.controller.act("refresh");
  assert.deepEqual(context.calls[1], { method: "benefits.refresh", params: {} });
  await context.tick();
  assert.equal(context.timers.size, 1);
  await context.tick();
  assert.equal(context.timers.size, 0);
  assert.equal(context.state.benefits.snapshot.running, false);
  context.controller.dispose();
});

test("an unresolved poll blocks overlapping reads and actions", async () => {
  const pending = deferred();
  let count = 0;
  const context = harness(() => ++count === 1 ? snapshot({ running: true }) : pending.promise);
  await context.controller.loadStatus();
  await context.tick();
  assert.equal(context.calls.length, 2);
  assert.equal(context.timers.size, 0);
  const duplicate = context.controller.loadStatus();
  await context.controller.act("refresh");
  await context.controller.act("browsers");
  assert.equal(context.calls.length, 2);
  pending.resolve(snapshot());
  await duplicate;
  assert.equal(context.state.benefits.busy, "");
  assert.equal(context.timers.size, 0);
  context.controller.dispose();
});

test("polling preserves unsaved preferences and stops on transport failure", async () => {
  let count = 0;
  const context = harness(() => {
    count += 1;
    if (count === 3) throw new Error('<script>alert("RPC")</script>');
    return snapshot({ running: true });
  });
  await context.controller.loadStatus();
  context.controller.changeDraft({ enabled: true });
  await context.tick();
  assert.equal(context.state.benefits.draft.enabled, true);
  assert.equal(context.state.benefits.snapshot.enabled, false);
  await context.tick();
  assert.equal(context.timers.size, 0);
  assert.equal(context.state.benefits.notice, "状态暂不可用");
  assert.doesNotMatch(renderBenefitsSection(context.state.benefits), /<script>/);
  context.controller.dispose();
});

test("failed saves keep the draft without changing persisted settings", async () => {
  const context = harness((method) => {
    if (method === "benefits.configure") throw new Error("backend-unavailable");
    return snapshot();
  });
  await context.controller.loadStatus();
  context.controller.changeDraft({ enabled: true });
  await context.controller.act("configure");
  assert.equal(context.state.benefits.snapshot.enabled, false);
  assert.equal(context.state.benefits.draft.enabled, true);
  assert.equal(context.state.benefits.notice, "保存失败：backend-unavailable");
  context.controller.dispose();
});

test("leaving the app view cancels timers and rejects late responses", async () => {
  const pending = deferred();
  let count = 0;
  const context = harness(() => ++count === 1 ? snapshot({ running: true }) : pending.promise);
  await context.controller.loadStatus();
  await context.tick();
  context.setScope(null);
  pending.resolve(snapshot({ enabled: true }));
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(context.state.benefits.loaded, false);
  assert.equal(context.state.benefits.snapshot, null);
  assert.equal(context.timers.size, 0);
  await context.controller.loadStatus();
  assert.equal(context.calls.length, 2);
  context.controller.dispose();
});

test("a changed scope queues one fresh read behind the old request", async () => {
  const pending = deferred();
  let count = 0;
  const context = harness(() => ++count === 1 ? pending.promise : snapshot({ browser_instance_id: "new-scope-browser" }));
  const oldRequest = context.controller.loadStatus();
  context.setScope("Capabilities:sumika:default");
  void context.controller.loadStatus();
  void context.controller.loadStatus();
  assert.equal(context.calls.length, 1);
  pending.resolve(snapshot({ enabled: true, running: true }));
  await oldRequest;
  await Promise.resolve();
  assert.equal(context.calls.length, 2);
  assert.equal(context.state.benefits.snapshot.enabled, false);
  assert.equal(context.state.benefits.snapshot.browser_instance_id, "new-scope-browser");
  assert.equal(context.timers.size, 0);
  context.controller.dispose();
});

test("timer rechecks app scope even without a redraw", async () => {
  const context = harness(() => snapshot({ running: true }));
  await context.controller.loadStatus();
  context.setScope("Settings:different-assistant:different-session", false);
  await context.tick();
  assert.equal(context.calls.length, 1);
  assert.equal(context.timers.size, 0);
  assert.equal(context.state.benefits.loaded, false);
  context.controller.dispose();
});

test("poll count is bounded and disposal stops all future activity", async () => {
  const context = harness(() => snapshot({ running: true }));
  await context.controller.loadStatus();
  for (let iteration = 0; iteration < 120; iteration += 1) await context.tick();
  assert.equal(context.timers.size, 0);
  assert.equal(context.calls.length, 121);
  assert.equal(context.state.benefits.notice, "状态跟踪已暂停");
  await context.controller.loadStatus();
  assert.equal(context.timers.size, 1);
  context.controller.dispose();
  assert.equal(context.timers.size, 0);
  await context.controller.loadStatus();
  await context.controller.act("refresh");
  assert.equal(context.calls.length, 122);
});

test("missing RPCs and legacy empty fixtures leave the controls inert", async () => {
  for (const responder of [() => ({}), () => undefined, () => { throw new Error("Method not found"); }]) {
    const context = harness(responder);
    await context.controller.loadStatus();
    assert.equal(context.state.benefits.loaded, false);
    assert.equal(context.state.benefits.notice, "状态暂不可用");
    await context.controller.act("checkin");
    await context.controller.act("configure");
    await context.controller.act("browsers");
    assert.equal(context.calls.length, 1);
    assert.equal(context.timers.size, 0);
    context.controller.dispose();
  }
});

test("delegated handlers bind once and survive capability subtree redraws", async () => {
  const listeners = new Map();
  let added = 0;
  const root = {
    addEventListener: (type, listener) => { added += 1; listeners.set(type, listener); },
    removeEventListener: (type) => listeners.delete(type),
    querySelector: () => null,
  };
  const context = harness((method, params) => snapshot(method === "benefits.configure" ? params : {}));
  context.controller.bind(root);
  context.controller.bind(root);
  assert.equal(added, 6);
  await context.controller.loadStatus();
  listeners.get("change")({ target: { name: "enabled", type: "checkbox", checked: true, closest: () => ({}) } });
  assert.equal(context.state.benefits.draft.enabled, true);
  assert.equal(context.calls.length, 1);
  let prevented = false;
  listeners.get("submit")({ target: { matches: () => true }, preventDefault: () => { prevented = true; } });
  await Promise.resolve();
  assert.equal(prevented, true);
  assert.equal(context.calls.at(-1).method, "benefits.configure");
  context.controller.dispose();
  assert.equal(listeners.size, 0);
});

test("source kinds distinguish search RSS, community RSS and official catalogs", () => {
  for (const [kind, label] of [["search", "搜索 RSS"], ["rss", "社区 RSS"], ["community-rss", "社区 RSS"], ["public-catalog", "官方目录"], ["public-pricing", "官方价格"]]) {
    assert.equal(benefitsSourceKind(kind), label);
  }
  const html = renderBenefitsSection({ ...createBenefitsState(), loaded: true, snapshot: snapshot({ sources: [{ id: "rss", title: "社区订阅", kind: "rss", status: "ready", stale: true }] }) });
  assert.match(html, /社区 RSS · 证据陈旧/);
  assert.doesNotMatch(html, /新鲜|RSS.*<input/);
});

test("backend expired flags and historical checkin balances cannot imply fresh quota or routing", () => {
  const html = renderBenefitsSection({ ...createBenefitsState(), loaded: true, snapshot: snapshot({
    offers: [{ id: "expired", title: "往期活动", kind: "credit-program", state: "active", expired: true, automatic_routing_authorized: false }],
    checkin: { state: "verified", stale: true, available_balance: 242, unit: "magicube", automatic_routing_authorized: false },
  }) });
  assert.match(html, /已到期/);
  assert.match(html, /上次观测余额：242 魔粒/);
  assert.match(html, /观测过期/);
  assert.doesNotMatch(html, /账户余额：|自动可路由/);
});

test("grant rows show evidence validity without manufacturing exact expiry", () => {
  const html = renderBenefitsGrants([{ kind: "daily-login", amount: 200, granted_date_display: "2026-09-08", validity_days_display: 1, expires_at: null }, { kind: "aliyun-binding", amount: 50, granted_date_display: "2026-09-08", validity_days_display: 1 }]);
  assert.match(html, /每日登录 · 200 魔粒 · 2026-09-08 · 显示有效期 1 天 · 精确到期未知/);
  assert.match(html, /阿里云绑定 · 50 魔粒/);
  assert.doesNotMatch(html, /2026-09-09/);
});

test("unchanged saved auto-checkin settings can explicitly revalidate the binding", async () => {
  const value = snapshot({ enabled: true, checkin_enabled: true, browser_instance_id: "edge-profile" });
  const context = harness(() => value);
  await context.controller.loadStatus();
  await context.controller.act("configure");
  assert.deepEqual(context.calls.at(-1), { method: "benefits.configure", params: { enabled: true, checkin_enabled: true, browser_instance_id: "edge-profile" } });
  context.controller.dispose();
});

test("a failed running poll can be manually read again without duplicate discovery", async () => {
  let count = 0;
  const context = harness(() => {
    count += 1;
    if (count === 2) throw new Error("temporarily-unavailable");
    return snapshot({ running: count === 1 });
  });
  await context.controller.loadStatus();
  await context.tick();
  assert.equal(context.timers.size, 0);
  assert.match(renderBenefitsSection(context.state.benefits), /data-benefits-control="refresh" >读取状态/);
  await context.controller.act("refresh");
  assert.deepEqual(context.calls.map((call) => call.method), ["benefits.status", "benefits.status", "benefits.status"]);
  assert.equal(context.state.benefits.snapshot.running, false);
  context.controller.dispose();
});

test("background discovery and automatic checkin can be disabled while work is running", async () => {
  const context = harness((method, params) => snapshot(method === "benefits.configure" ? params : { enabled: true, checkin_enabled: true, browser_instance_id: "edge-profile", running: true }));
  await context.controller.loadStatus();
  const html = renderBenefitsSection(context.state.benefits);
  assert.doesNotMatch(html, /name="enabled"[^>]*disabled|name="checkin_enabled"[^>]*disabled/);
  assert.match(html, /data-benefits-action="checkin"[^>]*disabled/);
  context.controller.changeDraft({ enabled: false, checkin_enabled: false });
  await context.controller.act("configure");
  assert.deepEqual(context.calls.at(-1), { method: "benefits.configure", params: { enabled: false, checkin_enabled: false, browser_instance_id: "edge-profile" } });
  assert.equal(context.state.benefits.snapshot.enabled, false);
  assert.equal(context.state.benefits.snapshot.checkin_enabled, false);
  assert.equal(context.timers.size, 0);
  context.controller.dispose();
});

test("errors from explicit actions remain escaped and identify the failed binding", async () => {
  const context = harness((method) => {
    if (method === "benefits.configure") throw new Error('profile-missing<unsafe>"');
    return snapshot();
  });
  await context.controller.loadStatus();
  context.controller.changeDraft({ browser_instance_id: "chosen-edge" });
  await context.controller.act("configure");
  assert.match(renderBenefitsSection(context.state.benefits), /保存失败：profile-missing&lt;unsafe&gt;&quot;/);
  assert.equal(context.state.benefits.snapshot.browser_instance_id, "");
  context.controller.dispose();
});

test("active public entries are claims or unverified leads, never account availability", () => {
  assert.equal(benefitsOfferStatus({ kind: "lead", state: "active" }), "待核实");
  assert.equal(benefitsOfferStatus({ kind: "free-model", state: "active" }), "官网声明");
  assert.equal(benefitsOfferStatus({ kind: "credit-program", state: "active" }), "公开活动");
  const offers = [
    { id: "rss-old", title: "旧资讯", kind: "lead", state: "active", stale: true, source_id: "feed", last_seen_at: "2026-08-01T00:00:00Z" },
    { id: "public-free", title: "官方模型", kind: "free-model", state: "active" },
    { id: "removed", title: "已移出官方目录", kind: "free-model", state: "withdrawn" },
  ];
  const value = snapshot({ offers, sources: [{ id: "feed", kind: "community-rss", status: "ready", item_count: 0 }] });
  const leads = renderBenefitsOffers(value, "leads");
  assert.match(leads, /资讯线索 · 待核实/);
  assert.match(leads, /证据陈旧/);
  assert.doesNotMatch(leads, /有效|已撤回/);
  const resources = renderBenefitsOffers(value);
  assert.match(resources, /免费模型 · 官网声明/);
  assert.match(resources, /免费模型 · 已撤回/);
  assert.doesNotMatch(resources, /免费模型 · 有效|账户可用/);
});
