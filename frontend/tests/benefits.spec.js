import { expect, test } from "@playwright/test";

const baseUrl = process.env.SUMIKA_BASE_URL || "http://127.0.0.1:8770/";

test("免费资源入口区分资讯与账户证据，配置和签到均需显式操作", async ({ page }, testInfo) => {
  const calls = [];
  let snapshot = {
    schema: "free-benefits/v1", enabled: false, checkin_enabled: false, browser_instance_id: "", running: false,
    sources: [{ id: "official", title: "官方免费额度说明", url: "https://console.groq.com/docs/rate-limits", kind: "public-benefits", status: "ready", last_success_at: "2026-09-08T02:00:00Z", item_count: 1 }],
    offers: [
      { id: "credit", source_id: "official", title: "新渠道免费开发者额度 · 设计测试示例", url: "https://console.groq.com/docs/rate-limits", provider_id: "groq", kind: "credit-program", evidence: "免费方案仍受速率与账号条件约束", state: "active", stale: false, last_seen_at: "2026-09-08T02:00:00Z", expires_at: null },
      { id: "lead", source_id: "community", title: "社区发现的免费模型与限时 API 额度资讯，尚待到官网逐项核实账户适用范围", url: "https://www.v2ex.com/feed/share.xml", kind: "lead", evidence: "社区 RSS 线索，不表示已获得额度", state: "active", stale: true, last_seen_at: "2026-09-07T02:00:00Z", expires_at: null },
    ], checkin: { state: "never", checked_at: null, available_balance: null, unit: "magicube", grants: [] },
  };
  await page.route("**/rpc", async (route) => {
    const request = route.request().postDataJSON();
    if (!request.method.startsWith("benefits.")) return route.continue();
    calls.push(request);
    if (request.method === "benefits.configure") snapshot = { ...snapshot, ...request.params };
    if (request.method === "benefits.checkin") snapshot = { ...snapshot, checkin: {
      state: "verified", checked_at: "2026-09-08T02:00:00Z", available_balance: 242, unit: "magicube", stale: false,
      grants: [{ kind: "daily-login", amount: 200, granted_date_display: "2026-09-08", validity_days_display: 1, expires_at: null }],
    } };
    const result = request.method === "benefits.browsers" ? { browsers: [{ instance_id: "fixture-edge", browser_name: "Edge" }] } : snapshot;
    await route.fulfill({ json: { jsonrpc: "2.0", id: request.id, result } });
  });
  await page.addInitScript(() => localStorage.setItem("sumika.onboarded.v1", "1"));
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator('.wv2-topbar [data-wv2-view="settings"]').click();
  const panel = page.locator("[data-benefits]");
  await expect(panel).toBeVisible();
  await panel.locator(":scope > summary").click();
  await expect(panel.getByText("后台发现已关闭", { exact: true })).toBeVisible();
  expect(calls.every((call) => call.method === "benefits.status")).toBe(true);
  await expect(panel.locator('[data-benefits-action="checkin"]')).toBeDisabled();
  await panel.locator('[name="enabled"]').check();
  await panel.locator('[data-benefits-control="save"]').click();
  expect(calls.find((call) => call.method === "benefits.configure").params.checkin_enabled).toBe(false);
  await panel.locator('[data-benefits-action="browsers"]').click();
  await panel.locator('[name="browser_instance_id"]').selectOption("fixture-edge");
  await panel.locator('[name="checkin_enabled"]').check();
  await panel.locator('[data-benefits-control="save"]').click();
  await expect(panel.locator('[data-benefits-action="checkin"]')).toBeEnabled();
  expect(calls.filter((call) => call.method === "benefits.checkin")).toHaveLength(0);
  await panel.locator('[data-benefits-action="checkin"]').click();
  await expect(panel).toContainText("242 魔粒");
  await expect(panel).toContainText("每日登录");
  await expect(panel).not.toContainText('"granted_date_display"');
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await panel.scrollIntoViewIfNeeded();
    expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    await panel.screenshot({ path: testInfo.outputPath(`benefits-${viewport.width}.png`) });
  }
  await panel.locator('[data-benefits-tab="leads"]').focus();
  await page.keyboard.press("Enter");
  await expect(panel.locator('[role="tabpanel"]')).toContainText("待核实");
  await expect(panel.locator('[role="tabpanel"]')).toContainText("证据陈旧");
  await page.keyboard.press("ArrowLeft");
  await expect(panel.locator('[data-benefits-tab="resources"]')).toBeFocused();
  await panel.locator('[name="enabled"]').uncheck();
  await expect(panel.locator('[name="checkin_enabled"]')).not.toBeChecked();
  await panel.locator('[data-benefits-control="save"]').click();
  expect(calls.filter((call) => call.method === "benefits.configure").at(-1).params.enabled).toBe(false);
});
