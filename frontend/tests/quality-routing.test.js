import assert from "node:assert/strict";
import test from "node:test";

import { createQualityRoutingView, eligibleQualityCandidates, formatFundingQuote, formatQualityQuote, normalizeQualityRule } from "../src/quality-routing-view.js";

test("区分赠送、已购资源与现金，未知价值不伪装免费", () => {
  assert.equal(formatFundingQuote({ funding_kind: "grant", available: true, free: true }), "赠送额度 · 预计费用 ¥0");
  assert.equal(formatFundingQuote({ funding_kind: "purchased", available: true, resource_value_cny: null, cash_due_cny: "0" }), "已购资源包 · 资源消耗折算 未知 · 现金扣减 ¥0");
  assert.match(formatFundingQuote({ funding_kind: "cash", available: true, cash_balance_cny: "10", cash_due_cny: "0.0002" }), /现金余额 ¥10 · 预计扣减 ¥0.0002/);
  assert.equal(formatFundingQuote({ funding_kind: "unknown", available: true, free: false }), "资金来源未核实 · 费用待核对");
  assert.match(formatFundingQuote({ funding_kind: "grant", available: false, free: true }), /当前额度不可用/);
});

test("质量路由只将已授权且可用的候选放入协作池", () => {
  const candidates = [
    { candidate_id: "ready", authorized: true, available: true },
    { candidate_id: "unauthorized", authorized: false, available: true },
    { candidate_id: "offline", authorized: true, available: false },
    { candidate_id: "harness", channel: "harness", authorized: true, available: false, reason: "verified-text-executor-required" },
  ];
  assert.deepEqual(eligibleQualityCandidates(candidates).map((candidate) => candidate.candidate_id), ["ready"]);
});

test("未知报价不伪装为零成本，预算规则拒绝无效下限", () => {
  assert.equal(formatQualityQuote(null), "报价未知");
  assert.equal(formatQualityQuote({ low_cny: null, typical_cny: undefined, high_cny: "" }), "未知 - 未知 - 未知");
  assert.equal(formatQualityQuote({ low_cny: 1, typical_cny: 2.5, high_cny: 4 }), "¥1.00 - ¥2.50 - ¥4.00");
  assert.deepEqual(normalizeQualityRule({ multiplier: "0.5", extra_cny: "-1" }, { multiplier: "2", extra_cny: "5" }), { multiplier: "2", extra_cny: "5" });
  assert.deepEqual(normalizeQualityRule({ multiplier: "1.5", extra_cny: "0" }), { multiplier: "1.5", extra_cny: "0" });
});

test("暂停任务可更新预算，最终消息对象渲染内容而非对象字符串", () => {
  const state = {
    qualityRouting: {
      catalog: { candidates: [] }, settings: { role_candidate_id: "reviewer" }, activeScope: { assistantId: "sumika", sessionId: "default" }, allowedCandidateIds: [], budgetDraft: {}, tasks: [{
        task_id: "paused-1", status: "paused", final_message: { content: "已等待人工处理", role: "assistant" }, plan: { goal: "复核" }, states: {}, results: {}, budget: { rule: { multiplier: "2", extra_cny: "5" }, quote: null },
      }], selectedTaskId: "paused-1", busy: false,
    },
  };
  const view = createQualityRoutingView({ state, escapeHtml: (value) => String(value), renderConsultation: () => "", renderPageFrame: () => "" });
  const html = view.renderQualityWorkbench();
  assert.match(html, /已等待人工处理/);
  assert.doesNotMatch(html, /\[object Object\]/);
  assert.match(html, /data-quality-task-budget-form="paused-1"/);
});

test("刷新面板区分价格、账户额度与评测，外部文本转义", () => {
  const state = { qualityRouting: { refresh: {
    jobs: { resources: { state: "needs-review", error: "authenticated-reader-required" } },
    resources: [{ name: "<script>alert(1)</script>", provider_profile_id: "official", remaining: 0, reservable_remaining: null, unit: "tokens", available: false, stale: true }],
    observations: [{ model_id: "glm-4.7-flash", free_claim: true, fresh: true, availability_state: "observed" }],
    free_models: { profiles: [{ provider_id: "<free-channel>", state: "ready", next_refresh: 1789000000,
      source: { observed_at: "2026-09-08T00:00:00Z" }, models: [{ model_id: "free-model", reason: "rate-limited", retry_at: 1789000000 }] }] },
  } } };
  const escapeHtml = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  const html = createQualityRoutingView({ state, escapeHtml }).renderRoutingEvidence();
  assert.match(html, /仅观察 · 不可抵扣/);
  assert.match(html, /可预留 未知/);
  assert.match(html, /不代表账户额度或健康/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /到期：未知/);
  assert.match(html, /限流冷却中/);
  assert.match(html, /具体剩余额度未量化/);
  assert.match(html, /&lt;free-channel&gt;/);
});

test("自动选择单独请求规划付费确认，保存设置不等于任务授权", () => {
  const state = { qualityRouting: { settings: { selection_mode: { leader: "auto", role: "fixed" } }, catalog: { candidates: [] }, tasks: [] } };
  const view = createQualityRoutingView({ state, escapeHtml: String, renderConsultation: () => "" });
  assert.match(view.renderQualityWorkbench(), /name="planning_confirmed"/);
  assert.match(view.renderQualitySettings(), /选入池子不授予发送或付费权限/);
  assert.match(view.renderQualitySettings(), /name="leader_selection_mode"/);
});

test("账户展示已购价值、待对账预留和未知Starter额度", () => {
  const state = { qualityRouting: { refresh: { accounts: {
    funding: { projections: [{ provider: "moark", source: "purchased", balance: "9.9933264", available: "9.99", unit: "CNY", inflight_and_unsettled: "0.0033264", fresh: true, entitlement_active: true }] },
    portals: [{ provider_profile_id: "ollama", available_balance: null, used_percent: 0, unit: "USD", fresh: true }],
  } } } };
  const html = createQualityRoutingView({ state, escapeHtml: String }).renderRoutingEvidence();
  assert.match(html, /已购资源包/);
  assert.match(html, /9.9933264/);
  assert.match(html, /在途及待对账 0.0033264/);
  assert.match(html, /可见余额 未知 USD/);
  assert.match(html, /已用 0% · 精确剩余额度未知/);
});
