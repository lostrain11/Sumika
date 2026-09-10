import { expect, test } from "@playwright/test";

const baseUrl = process.env.SUMIKA_BASE_URL || "http://127.0.0.1:8770/";

test("登录故障显示原因，恢复可用后自动连接但不自动重发", async ({ page }) => {
  let attached = 0;
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.addInitScript(() => {
    localStorage.setItem("sumika.onboarded.v1", "1");
    window.nativeCalls = [];
    window.consultationAvailable = false;
    window.__TAURI_INTERNALS__ = { invoke: async (command, payload) => {
      window.nativeCalls.push({ command, payload });
      if (command === "get_display_mode") return "workspace";
      if (command === "consultation_action" && payload.operation === "observe") {
        return window.consultationAvailable ? { status: "ready" } : { status: "unavailable", reason: "empty-document" };
      }
      if (command === "consultation_action" && payload.operation === "reload") return { status: "loading" };
      return { status: "ready" };
    } };
  });
  await page.route("**/rpc", async (route) => {
    const request = route.request().postDataJSON();
    if (!request.method.startsWith("quality.browser.")) return route.continue();
    const result = request.method === "quality.browser.attach" ? (attached++, { token: "login-recovered" }) : { request: null };
    await route.fulfill({ json: { jsonrpc: "2.0", id: request.id, result } });
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator('[data-inspector-open="files"]').click();
  await page.locator('[data-inspector-open="browser"]').click();
  await page.locator('[data-embedded-tab="native-consultation"]').click();
  await expect(page.locator(".consultation-panel")).toHaveClass(/is-focused/);
  expect((await page.locator("[data-consultation-rect]").boundingBox()).height).toBeGreaterThan(540);
  await page.getByRole("button", { name: "恢复布局", exact: true }).click();
  await expect(page.locator(".consultation-panel")).not.toHaveClass(/is-focused/);
  await page.getByRole("button", { name: "展开网页", exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 900 });
  expect((await page.locator("[data-consultation-rect]").boundingBox()).height).toBeGreaterThan(640);
  await expect(page.locator(".consultation-notice")).toContainText("页面为空");
  expect(attached).toBe(0);
  await page.getByRole("button", { name: "返回登录首页", exact: true }).click();
  await page.evaluate(() => { window.consultationAvailable = true; });
  await expect.poll(() => attached).toBe(1);
  expect(await page.evaluate(() => window.nativeCalls.filter((call) => call.payload?.operation === "reload").length)).toBe(1);
  expect(await page.evaluate(() => window.nativeCalls.filter((call) => ["fill", "submit"].includes(call.payload?.operation)).length)).toBe(0);
});

test("嵌入式咨询只发送一次，未知结果不重试且接管可见", async ({ page }, testInfo) => {
  const nativeCalls = [];
  const bridgeCalls = [];
  let polled = false;
  await page.addInitScript(() => {
    window.__TAURI_INTERNALS__ = { invoke: async (command, payload) => {
      window.nativeCalls.push({ command, payload });
      if (command === "get_display_mode") return "workspace";
      if (command === "consultation_action" && payload.operation === "observe") return { status: "ready", text: "", possibly_sent: false };
      if (command === "consultation_action" && payload.operation === "fill") return { status: "filled", text: "", possibly_sent: false };
      if (command === "consultation_action" && payload.operation === "submit") return { status: "pending", text: "", possibly_sent: true };
      if (command === "consultation_action" && payload.operation === "read") return { status: "unknown", text: "", possibly_sent: true };
      return { status: "ready", text: "", possibly_sent: false };
    } };
    window.nativeCalls = [];
  });
  await page.route("**/rpc", async (route) => {
    const request = route.request().postDataJSON();
    const method = request.method;
    if (!method.startsWith("quality.")) return route.continue();
    bridgeCalls.push({ method, params: request.params });
    const result = method === "quality.catalog" ? { candidates: [{ candidate_id: "local", label: "本地", authorized: true, available: true, external: false }], capabilities: {} }
      : method === "quality.task.list" ? { tasks: [] }
      : method === "quality.settings.get" ? { assistant_id: "sumika", role_candidate_id: "local", leader_candidate_id: null, budget_rule: { multiplier: "2", extra_cny: "5" } }
      : method === "quality.browser.attach" ? { token: "bridge-token", profile: "chatgpt" }
      : method === "quality.browser.poll" ? { request: polled ? null : (polled = true, { attempt_id: "attempt-1", question: "只检查风险", owner_id: "sumika", session_id: "default" }) }
      : method === "quality.browser.complete" ? { accepted: true } : {};
    await route.fulfill({ json: { jsonrpc: "2.0", id: request.id, result } });
  });
  await page.addInitScript(() => localStorage.setItem("sumika.onboarded.v1", "1"));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator('[data-inspector-open="files"]').click();
  await page.locator('[data-inspector-open="browser"]').click();
  await page.locator('[data-embedded-tab="native-consultation"]').click();
  await expect(page.locator("[data-consultation-rect]")).toBeVisible();
  await expect.poll(() => bridgeCalls.filter((call) => call.method === "quality.browser.complete").length).toBe(1);
  await page.screenshot({ path: testInfo.outputPath("consultation-workbench-1440x900.png") });
  expect(await page.evaluate(() => window.nativeCalls.filter((call) => call.command === "consultation_action" && call.payload.operation === "submit").length)).toBe(1);
  expect(bridgeCalls.find((call) => call.method === "quality.browser.complete").params.result).toMatchObject({ status: "unknown", possibly_sent: true });
  expect(bridgeCalls.some((call) => call.method === "quality.browser.poll" && call.params.accept_requests === false)).toBe(true);
  await expect(page.getByRole("button", { name: "读取" })).toBeEnabled();
  await page.getByRole("button", { name: "接管" }).click();
  await expect(page.getByRole("button", { name: "释放" })).toBeVisible();
  await page.getByRole("button", { name: "隐藏" }).click();
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.locator('.wv2-topbar [data-wv2-view="settings"]').click();
  await expect(page.locator('[data-model-binding="work"]')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("consultation-settings-1280x800.png") });
});

test("离开咨询页后，迟到的填写结果不能继续提交", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("sumika.onboarded.v1", "1");
    window.nativeCalls = [];
    window.__TAURI_INTERNALS__ = { invoke: async (command, payload) => {
      window.nativeCalls.push({ command, payload });
      if (command === "get_display_mode") return "workspace";
      if (command === "consultation_action" && payload.operation === "observe") return { status: "login-required" };
      if (command === "consultation_action" && payload.operation === "fill") {
        return new Promise((resolve) => { window.releaseFill = () => resolve({ status: "filled" }); });
      }
      return { status: "ready" };
    } };
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator('[data-inspector-open="files"]').click();
  await page.locator('[data-inspector-open="browser"]').click();
  await page.locator('[data-embedded-tab="native-consultation"]').click();
  await page.getByRole("button", { name: "恢复布局", exact: true }).click();
  await page.locator("#consultation-manual-form textarea").fill("Local fixture only");
  await page.locator("#consultation-manual-form").getByRole("button", { name: "提交", exact: true }).click();
  await expect.poll(() => page.evaluate(() => typeof window.releaseFill)).toBe("function");
  await page.locator('.wv2-topbar [data-wv2-view="settings"]').click();
  await page.evaluate(() => window.releaseFill());
  await expect(page.locator('[data-model-binding="work"]')).toBeVisible();
  expect(await page.evaluate(() => window.nativeCalls.filter((call) => call.payload?.operation === "submit").length)).toBe(0);
  expect(await page.evaluate(() => window.nativeCalls.some((call) => call.command === "consultation_hide"))).toBe(true);
});
