import { test, expect } from "@playwright/test";

const baseUrl = process.env.SUMIKA_BASE_URL || "http://127.0.0.1:8770/";

function moduleFixture(id, enabled = false, status = "disabled") {
  return { id, name: id === "llm" ? "大语言模型" : id, capability: id, description: "隔离 UI fixture", enabled, status, implementation_id: "none", implementations: [], config: {}, config_schema: {}, permissions: [] };
}

async function openDrawer(page, target) {
  const primary = target === "Modules" ? "Settings" : target;
  await page.locator(`.scene-primary-nav [data-page="${primary}"]`).click();
  if (target === "Modules") await page.locator('.drawer-tabs [data-page="Modules"]').click();
  await expect(page.locator(".drawer")).toBeVisible();
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
  await openDrawer(page, "Modules");
  await expect(page.locator(".module-add-tile")).toBeVisible();
  await expect(page.locator(".active-modules")).toHaveCount(0);
  await expect(page.locator(".module-add-grid")).toBeHidden();
  await expect(page.locator(".audio-runtime-panel, .vision-runtime-panel, .tool-runtime-panel, [data-capability-catalog]")).toHaveCount(0);
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
  await openDrawer(page, "Modules");
  await expect(page.locator(".drawer-body")).toContainText("模块目录读取失败");
  failing = false;
  slow = true;
  await page.locator("[data-modules-retry]").click();
  await expect(page.locator('.empty-panel[aria-busy="true"]')).toContainText("正在读取");
  await expect(page.locator(".drawer-body")).toContainText("当前没有可添加的模块");
  await expect(page.locator(".drawer-body")).not.toContainText("核心未连接");
});

test("背景、折叠状态与焦点跨重绘保留，Esc 一次只关闭一层", async ({ page }) => {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await openDrawer(page, "Settings");
  await page.locator('[data-appearance-color="#171326"]').click();
  await expect(page.locator(".scene-backdrop")).toHaveCSS("background-color", "rgb(23, 19, 38)");
  await page.keyboard.press("Escape");
  await expect(page.locator('.scene-primary-nav [data-page="Settings"]')).toBeFocused();
  await page.locator("[data-avatar-toggle]").click();
  await expect(page.locator(".scene-backdrop")).toHaveCSS("background-color", "rgb(23, 19, 38)");
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.locator(".scene-backdrop")).toHaveCSS("background-color", "rgb(23, 19, 38)");
  await openDrawer(page, "Modules");
  await expect(page.locator(".provider-picker")).toBeAttached();
  if (!(await page.locator(".provider-picker").isVisible())) await page.locator(".module-add-tile").click();
  await page.locator(".provider-picker > summary").click();
  await page.locator("[data-provider-new]").click();
  await expect(page.locator("#provider-profile-form")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#provider-profile-form")).toHaveCount(0);
  await expect(page.locator(".drawer")).toBeVisible();
  await expect(page.locator(".provider-picker")).toHaveAttribute("open", "");
  await page.keyboard.press("Escape");
  await expect(page.locator(".drawer")).toHaveCount(0);
  await expect(page.locator('.scene-primary-nav [data-page="Settings"]')).toBeFocused();
});

test("桌面门户仅有一个聊天工具入口，保留透明桌宠契约", async ({ page }) => {
  await page.addInitScript(() => { window.__TAURI_INTERNALS__ = { invoke: async (command) => command === "get_display_mode" ? (location.search.includes("overlay") ? "pet" : "workspace") : [] }; });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await expect(page.locator(".scene-primary-nav .nav-item")).toHaveCount(5);
  await expect(page.locator("[data-portal-panel]")).toHaveCount(1);
  await expect(page.locator(".composer-tools [data-portal-panel]")).toBeVisible();
  await expect(page.locator('button[title="附件"]')).toHaveCount(0);
  await page.locator("[data-portal-panel]").click();
  await expect(page.locator(".portal-panel")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".portal-panel")).toHaveCount(0);
  await page.goto(baseUrl + "?mode=overlay", { waitUntil: "networkidle" });
  await expect(page.locator("body")).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await expect(page.locator(".drawer, .scene-primary-nav")).toHaveCount(0);
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
  test(`visual ${width}: 四抽屉可达且不卸载 Avatar`, async ({ page }, testInfo) => {
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 800 });
    await page.addInitScript(() => localStorage.setItem("sumika.onboarded.v1", "1"));
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await expect(page.locator(".vrm-renderer canvas")).toBeVisible();
    const canvas = await page.locator(".vrm-renderer canvas").elementHandle();
    const composer = await page.locator(".composer").boundingBox();

    expect(composer.x).toBeGreaterThanOrEqual(0);
    expect(composer.x + composer.width).toBeLessThanOrEqual(width + 1);
    expect(composer.y + composer.height).toBeLessThanOrEqual(800);
    await page.screenshot({ path: testInfo.outputPath(`scene-${width}.png`) });
    for (const drawer of ["Agent", "Characters", "Modules", "Settings"]) {
      await openDrawer(page, drawer);
      if (drawer === "Modules") {
        await expect(page.locator('.drawer-body [aria-busy="true"]')).toHaveCount(0);
        await page.locator(".module-add-tile").click();
        await expect(page.locator(".module-add-grid")).toBeVisible();
      }
      const heading = page.locator(".drawer h1");
      await expect(heading).toBeVisible();
      await expect(page.locator(".scene-chat")).toHaveAttribute("inert", "");
      const bounds = await page.locator(".drawer").evaluate((element) => { const rect = element.getBoundingClientRect(); return { x: rect.x, width: rect.width }; });
      expect(bounds.x).toBeGreaterThanOrEqual(0);
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(width + 1);
      const overflow = await page.locator(".drawer-body").evaluate((element) => element.scrollWidth - element.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);
      if (width === 1280 || width === 360) await page.screenshot({ path: testInfo.outputPath(`${drawer}-${width}.png`) });
      await page.keyboard.press("Escape");
      await expect(page.locator(".drawer")).toHaveCount(0);
      expect(await canvas.evaluate((element) => element === document.querySelector(".vrm-renderer canvas"))).toBe(true);
    }
    expect(errors).toEqual([]);
  });
}
