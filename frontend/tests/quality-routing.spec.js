import { expect, test } from "@playwright/test";
import { openPage } from "./helpers/navigation.js";

const baseUrl = process.env.SUMIKA_BASE_URL || "http://127.0.0.1:8770/";

test("质量协作仅计划，确认后才执行，且 RPC 带固定角色会话作用域", async ({ page }, testInfo) => {
  const calls = [];
  let task = {
    task_id: "quality-1",
    scope: { owner_id: "sumika", session_id: "default" },
    revision: 3,
    status: "awaiting-confirmation",
    reason: "等待明确确认",
    plan: { goal: "审阅发布说明", nodes: [{ node_id: "review", goal: "检查事实", dependencies: [], acceptance: [] }] },
    states: { review: "pending" },
    results: {},
    budget: { quote: { low_cny: null, typical_cny: 2, high_cny: 3, max_calls: 2, max_tokens: 900 }, rule: { multiplier: "2", extra_cny: "5" }, spent_cny: null, estimated_cny: null, unpriced_calls: 0 },
  };
  await page.route("**/rpc", async (route) => {
    const request = route.request().postDataJSON();
    if (!request.method.startsWith("quality.")) return route.continue();
    calls.push({ method: request.method, params: request.params });
    const result = request.method === "quality.catalog" ? {
      candidates: [
        { candidate_id: "local-reviewer", label: "本地审阅", channel: "local", model_id: "review-1", reasoning_effort: "high", authorized: true, available: true, external: false, pricing_source: "local" },
        { candidate_id: "external-reviewer", label: "外部审阅", channel: "remote", model_id: "review-2", reasoning_effort: "high", authorized: true, available: true, external: true, pricing_source: "catalog" },
      ], capabilities: { native_consultation: false },
    } : request.method === "quality.task.list" ? { tasks: [] } : request.method === "quality.task.plan" ? task : request.method === "quality.task.confirm" ? { ...task, revision: 4, status: "running", states: { review: "running" } } : request.method === "quality.task.budget" ? { ...task, revision: 5, status: "running", budget: { ...task.budget, rule: request.params.budget_rule } } : request.method === "quality.task.get" ? task : { assistant_id: "sumika", role_candidate_id: "local-reviewer", leader_candidate_id: null, budget_rule: { multiplier: "2", extra_cny: "5" } };
    await route.fulfill({ json: { jsonrpc: "2.0", id: request.id, result } });
  });
  await page.addInitScript(() => localStorage.setItem("sumika.onboarded.v1", "1"));
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await expect(page.locator(".wv2-topbar")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("quality-routing-initial.png") });
  await openPage(page, "Tasks");
  const sessionId = await page.locator("[data-conversation-select].active").getAttribute("data-conversation-select");
  expect(sessionId).toBeTruthy();
  task.scope.session_id = sessionId;
  await expect(page.locator("#quality-plan-form")).toBeVisible();
  await page.locator('#quality-plan-form [name="goal"]').fill("审阅发布说明");
  await page.locator("#quality-plan-form").getByRole("button", { name: "生成并报价计划" }).click();
  await expect(page.locator("[data-quality-task]" )).toContainText("awaiting-confirmation");
  await expect(page.locator("[data-quality-task]" )).toContainText("未知 - ¥2.00 - ¥3.00 · 最多 2 次调用 · 900 Token · 已用未知 · 预估未知");
  await page.screenshot({ path: testInfo.outputPath("quality-routing-plan.png") });
  expect(calls.filter((call) => call.method === "quality.task.confirm")).toHaveLength(0);
  const plan = calls.find((call) => call.method === "quality.task.plan");
  expect(plan.params).toEqual({ assistant_id: "sumika", session_id: sessionId, goal: "审阅发布说明", allowed_candidate_ids: ["local-reviewer"], external_allowed: false });
  expect(JSON.stringify(plan.params)).not.toContain("messages");
  await page.getByRole("button", { name: "确认执行" }).click();
  await expect(page.locator("[data-quality-task]" )).toContainText("running");
  await expect(page.getByRole("button", { name: "取消" })).toBeVisible();
  await page.locator("[data-quality-task-budget-form] [name=multiplier]").fill("3");
  await page.getByRole("button", { name: "更新运行预算" }).click();
  expect(calls.find((call) => call.method === "quality.task.budget").params).toEqual({ assistant_id: "sumika", session_id: sessionId, task_id: "quality-1", budget_rule: { multiplier: "3", extra_cny: "5" } });
  expect(calls.find((call) => call.method === "quality.task.confirm").params).toEqual({ assistant_id: "sumika", session_id: sessionId, task_id: "quality-1", revision: 3 });
});

test("质量设置与能力页显示真实刷新状态，自动选择不暗含付费确认", async ({ page }, testInfo) => {
  const calls = [];
  let settings = { assistant_id: "sumika", leader_candidate_id: "official-model", role_candidate_id: null,
    candidate_pool: ["official-model"], selection_mode: { leader: "auto", role: "fixed" }, budget_rule: { multiplier: "2", extra_cny: "5" } };
  const refresh = { schema: "model-refresh/v1", resources: [],
    jobs: { pricing: { state: "needs-review", error: "PricingNeedsReview" }, resources: { state: "needs-review", error: "authenticated-reader-required" } },
    observations: [{ model_id: "glm-4.7-flash", availability_state: "observed", free_claim: false, fresh: false }] };
  await page.route("**/rpc", async (route) => {
    const request = route.request().postDataJSON();
    if (!request.method.startsWith("quality.") && !request.method.startsWith("model.policy.refresh")) return route.continue();
    calls.push(request);
    let result = settings;
    if (request.method === "quality.catalog") result = { candidates: [{ candidate_id: "official-model", label: "已授权测试模型", channel: "api", authorized: true, available: true, external: true }] };
    if (request.method === "quality.settings.set") settings = result = request.params;
    if (request.method === "quality.bindings.select") result = { bindings: { leader: { candidate_id: null, reason: "successful-fixed-samples-required" } } };
    if (request.method === "model.policy.refresh.status") result = refresh;
    if (request.method === "model.policy.refresh") result = { refresh };
    if (request.method === "quality.task.list") result = { tasks: [] };
    if (request.method === "quality.task.plan") result = { task_id: "planned", status: "awaiting-confirmation", goal: request.params.goal };
    await route.fulfill({ json: { jsonrpc: "2.0", id: request.id, result } });
  });
  await page.addInitScript(() => localStorage.setItem("sumika.onboarded.v1", "1"));
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await openPage(page, "Guide");
  await expect(page.locator('[name="leader_selection_mode"]')).toHaveValue("auto");
  await page.locator(".quality-refresh summary").click();
  await expect(page.locator(".quality-refresh")).toContainText("免费状态未确认");
  await page.getByRole("button", { name: "检查价格与额度" }).click();
  await expect(page.locator(".quality-refresh")).toContainText("部分来源待核对");
  expect(calls.filter((call) => call.method === "quality.task.plan")).toHaveLength(0);
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.locator(".quality-refresh").scrollIntoViewIfNeeded();
    expect(await page.locator(".quality-refresh").evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`routing-refresh-${viewport.width}.png`) });
  }
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.screenshot({ path: testInfo.outputPath("routing-refresh-settings.png"), fullPage: true });
  await openPage(page, "Tasks");
  await expect(page.locator('[name="planning_confirmed"]')).not.toBeChecked();
  await page.locator('#quality-plan-form [name="goal"]').fill("比较三个方案");
  await page.locator('#quality-plan-form [name="candidate_id"]').check();
  await page.locator('#quality-plan-form [name="external_allowed"]').check();
  await page.locator('#quality-plan-form [name="planning_confirmed"]').check();
  await page.getByRole("button", { name: "生成并报价计划" }).click();
  expect(calls.find((call) => call.method === "quality.task.plan").params.planning_confirmed).toBe(true);
});
