import { test, expect } from "@playwright/test";
import { openPage } from "./helpers/navigation.js";

const baseUrl = process.env.SUMIKA_BASE_URL || "http://127.0.0.1:8770/";

function moduleFixture(id, enabled = false, status = "disabled") {
  return { id, name: id === "llm" ? "大语言模型" : id, capability: id, description: "隔离 UI fixture", enabled, status, implementation_id: "none", implementations: [], config: {}, config_schema: {}, permissions: [] };
}

test("模块库严格隐藏停用能力，打开目录不授权，启用失败状态仍可见", async ({ page }) => {
  let modules = [moduleFixture("llm"), moduleFixture("memory"), moduleFixture("asr"), moduleFixture("vision"), moduleFixture("tools")];
  const writes = [];
  await page.route("**/api/modules", (route) => route.fulfill({ json: modules }));
  await page.route("**/rpc", async (route) => {
    const request = route.request().postDataJSON();
    if (request.method !== "module.update") return route.continue();
    writes.push(request.params);
    modules = modules.map((module) => module.id === request.params.module_id ? { ...module, enabled: request.params.enabled, status: request.params.enabled ? "error" : "disabled" } : module);
    return route.fulfill({ json: { jsonrpc: "2.0", id: request.id, result: modules.find((module) => module.id === request.params.module_id) } });
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await openPage(page, "Modules");
  await expect(page.locator(".module-add-tile")).toBeVisible();
  await expect(page.locator(".active-modules")).toHaveCount(0);
  await expect(page.locator(".module-add-grid")).toBeHidden();
  await expect(page.locator(".wv2-settings-section").filter({ has: page.locator('[data-workbench-page="Modules"]') }).locator(".audio-runtime-panel, .vision-runtime-panel, .tool-runtime-panel, [data-capability-catalog]")).toHaveCount(0);
  await page.locator(".module-add-tile").click();
  await expect(page.locator(".module-add-grid .llm-module-card")).toBeVisible();
  expect(writes).toEqual([]);
  await page.locator('[data-module-toggle="memory"]').click();
  await expect(page.locator('.active-modules [data-module-toggle="memory"]')).toHaveAttribute("aria-checked", "true");
  await expect(page.locator(".active-modules .module-status")).toHaveClass(/error/);
  expect(writes).toEqual([{ module_id: "memory", enabled: true }]);
  await page.locator('.active-modules [data-module-toggle="memory"]').click();
  await expect(page.locator('.active-modules [data-module-toggle="memory"]')).toHaveCount(0);
  await expect(page.locator('.module-add-grid [data-module-toggle="memory"]')).toBeVisible();
});

test("模块目录失败可重试，加载与空目录不伪装成离线", async ({ page }) => {
  let failing = false;
  let slow = false;
  await page.route("**/api/modules", async (route) => {
    if (slow) await new Promise((resolve) => setTimeout(resolve, 600));
    return failing ? route.fulfill({ status: 503, json: { error: "unavailable" } }) : route.fulfill({ json: [] });
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  failing = true;
  await openPage(page, "Modules");
  await expect(page.locator(".wv2-settings")).toContainText("模块目录读取失败");
  failing = false;
  slow = true;
  await page.locator("[data-modules-retry]").click();
  await expect(page.locator('.empty-panel[aria-busy="true"]')).toContainText("正在读取");
  await expect(page.locator(".wv2-settings")).toContainText("当前没有可添加的模块");
  await expect(page.locator(".wv2-settings")).not.toContainText("核心未连接");
});

test("背景、折叠状态与焦点跨重绘保留，Esc 一次只关闭一层", async ({ page }) => {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await openPage(page, "Guide");
  await page.locator('[data-appearance-color="#171326"]').click();
  await expect(page.locator('[data-appearance-color="#171326"]')).toHaveClass(/active/);
  await page.reload({ waitUntil: "networkidle" });
  await openPage(page, "Guide");
  await expect(page.locator('[data-appearance-color="#171326"]')).toHaveClass(/active/);
  await openPage(page, "Modules");
  if (!(await page.locator(".provider-picker").isVisible())) await page.locator(".module-add-tile").click();
  await page.locator(".provider-picker > summary").click();
  await page.locator("[data-provider-new]").click();
  await expect(page.locator("#provider-profile-form")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#provider-profile-form")).toHaveCount(0);
  await expect(page.locator(".wv2-settings")).toBeVisible();
  await expect(page.locator(".provider-picker")).toHaveAttribute("open", "");
  await page.keyboard.press("Escape");
  await expect(page.locator(".provider-picker")).not.toHaveAttribute("open", "");
  await expect(page.locator(".provider-picker > summary")).toBeFocused();
  await expect(page.locator(".wv2-settings")).toBeVisible();
  await openPage(page, "Chat");
  await expect(page.locator(".desktop-overlay-shell")).toHaveCSS("background-color", "rgb(23, 19, 38)");
});
test("桌面门户仅有一个浏览器工具入口，保留透明桌宠契约", async ({ page }) => {
  await page.addInitScript(() => { window.__TAURI_INTERNALS__ = { invoke: async (command) => command === "get_display_mode" ? (location.search.includes("companion") ? "pet" : "workspace") : [] }; });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await expect(page.locator(".wv2-primary-nav button")).toHaveCount(4);
  await expect(page.locator(".wv2-inspector")).toHaveCount(0);
  await page.locator('[data-inspector-open="files"]').click();
  await expect(page.locator('[data-inspector-open="browser"]')).toHaveCount(1);
  await page.locator('[data-inspector-open="browser"]').click();
  await expect(page.getByRole("region", { name: "内置浏览器", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".wv2-inspector")).toHaveCount(0);
  await page.goto(baseUrl + "?view=companion", { waitUntil: "networkidle" });
  await expect(page.locator("body")).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await expect(page.locator(".drawer, .wv2-topbar")).toHaveCount(0);
  await page.locator("[data-pet-chat]").focus();
  await page.locator("[data-pet-chat]").click();
  await expect(page.locator(".overlay-composer")).toBeVisible();
});
test("重绘仅保留当前角色的未保存字段，不覆盖外部更新或跨角色复制", async ({ page }) => {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  const result = await page.evaluate(async () => {
    const { createViewState } = await import("/src/view-state.js");
    const root = document.createElement("div");
    document.body.append(root);
    const controller = createViewState(root);
    const markup = (name) => `<form id="character-form"><input name="name" value="${name}"><input name="avatar_head_follow_enabled" type="checkbox" checked></form>`;
    root.innerHTML = markup("Original");
    controller.restore("Characters:first");
    root.querySelector('[name="name"]').value = "Draft";
    root.querySelector('[type="checkbox"]').checked = false;
    controller.capture();
    root.innerHTML = markup("Original");
    controller.restore("Characters:first");
    const draft = root.querySelector('[name="name"]').value;
    const checked = root.querySelector('[type="checkbox"]').checked;
    controller.capture();
    root.innerHTML = markup("Second");
    controller.restore("Characters:second");
    const second = root.querySelector('[name="name"]').value;
    controller.capture();
    root.innerHTML = markup("Server updated");
    controller.restore("Characters:second");
    const updated = root.querySelector('[name="name"]').value;
    root.remove();
    return { draft, checked, second, updated };
  });
  expect(result).toEqual({ draft: "Draft", checked: false, second: "Second", updated: "Server updated" });
});

for (const width of [360, 640, 900, 1280]) {
  test("visual " + width + ": 工作台入口可达，独立陪伴保留画布", async ({ page }, testInfo) => {
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.setViewportSize({ width, height: 800 });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    const popup = page.waitForEvent("popup");
    await page.locator("[data-wv2-open-residence]").click();
    const companion = await popup;
    await companion.bringToFront();
    await expect(companion.locator('[data-vrm-status="ready"]')).toBeVisible({ timeout: 15000 });
    await expect(companion.locator(".vrm-renderer canvas")).toBeVisible();
    const canvas = await companion.locator(".vrm-renderer canvas").elementHandle();
    const composer = await page.locator(".wv2-composer").boundingBox();
    expect(composer.x).toBeGreaterThanOrEqual(0);
    expect(composer.x + composer.width).toBeLessThanOrEqual(width + 1);
    expect(composer.y + composer.height).toBeLessThanOrEqual(800);
    for (const target of ["Agent", "Characters", "Modules", "Settings"]) {
      await openPage(page, target);
      if (target === "Modules") {
        await expect(page.locator('.wv2-settings [aria-busy="true"]')).toHaveCount(0);
        await page.locator(".module-add-tile").click();
        await expect(page.locator(".module-add-grid")).toBeVisible();
      }
      await expect(page.locator(".wv2-topbar")).toBeVisible();
      await expect(page.locator(".scene-chat, .drawer")).toHaveCount(0);
      const surface = page.locator(target === "Agent" ? ".wv2-center" : ".wv2-page");
      await expect(surface).toBeVisible();
      await expect.poll(() => surface.evaluate(element => {
        const bounds = element.getBoundingClientRect();
        return bounds.width > 0 && bounds.x >= 0 && bounds.right <= innerWidth + 1
          && element.scrollWidth - element.clientWidth <= 1;
      })).toBe(true);
      if (width === 1280 || width === 360) await page.screenshot({ path: testInfo.outputPath(target + "-" + width + ".png") });
      expect(await canvas.evaluate(element => element === document.querySelector(".vrm-renderer canvas"))).toBe(true);
    }
    await companion.close();
    expect(errors).toEqual([]);
  });
}
