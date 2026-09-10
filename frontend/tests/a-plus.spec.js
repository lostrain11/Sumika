import { test, expect } from "@playwright/test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { PNG } = require("../node_modules/playwright-core/lib/utilsBundle.js");
const baseUrl = process.env.SUMIKA_BASE_URL || "http://127.0.0.1:8770/";
const companionUrl = new URL("?view=companion", baseUrl).href;

async function openCompanion(page) {
  await page.addInitScript(() => localStorage.setItem("sumika.onboarded.v1", "1"));
  await page.goto(companionUrl, { waitUntil: "networkidle" });
  await expect(page.locator(".desktop-overlay-shell")).toBeVisible();
  await expect(page.locator('[data-vrm-status="ready"]')).toBeVisible();
  await page.locator(".desktop-overlay-shell").hover({ position: { x: 10, y: 100 } });
}

async function checkCanvas(page, label, testInfo) {
  const pixels = PNG.sync.read(await page.locator(".vrm-renderer canvas").screenshot({ omitBackground: true }));
  const colors = new Set();
  for (let offset = 0; offset < pixels.data.length; offset += 128) {
    colors.add([pixels.data[offset] >> 4, pixels.data[offset + 1] >> 4, pixels.data[offset + 2] >> 4].join(","));
  }
  expect(colors.size).toBeGreaterThan(25);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(label + ".png"), omitBackground: true });
}

test("A+ companion retains canvas and draft across sizes, collapse and transparent background", async ({ page }, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 480, height: 420 });
  await openCompanion(page);
  const canvas = await page.locator(".vrm-renderer canvas").elementHandle();
  await page.locator("[data-pet-chat]").click();
  await page.locator("#chat-input").fill("A+ draft preserved");
  await checkCanvas(page, "companion-compact", testInfo);
  await page.locator("[data-pet-chat]").click();
  await expect(page.locator("#chat-form")).toBeHidden();
  await expect(page.locator("[data-pet-chat]")).toBeFocused();
  await page.locator("[data-pet-chat]").click();
  await expect(page.locator("#chat-input")).toHaveValue("A+ draft preserved");
  for (const size of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(size);
    await checkCanvas(page, "companion-" + size.width, testInfo);
    await expect(page.locator("#chat-input")).toHaveValue("A+ draft preserved");
  }
  await page.locator("[data-pet-background]").click();
  await page.mouse.move(-20, -20);
  await page.evaluate(() => document.activeElement?.blur());
  const pixels = PNG.sync.read(await page.locator(".vrm-renderer canvas").screenshot({ omitBackground: true }));
  let clear = 0;
  for (let offset = 3; offset < pixels.data.length; offset += 4) if (!pixels.data[offset]) clear++;
  expect(clear).toBeGreaterThan(pixels.width * pixels.height * 0.2);
  expect(await canvas.evaluate((element) => element === document.querySelector(".vrm-renderer canvas"))).toBe(true);
  expect(errors).toEqual([]);
});

test("A+ rejected native size change preserves draft; dragging excludes input and buttons", async ({ page }) => {
  await page.addInitScript((endpoint) => {
    window.displayTest = { fail: true, drags: 0 };
    window.__TAURI_INTERNALS__ = { invoke: async (command) => {
      if (command === "core_status") return { host: new URL(endpoint).hostname, port: new URL(endpoint).port };
      if (command === "get_display_mode") return "pet";
      if (command === "set_companion_mode" && window.displayTest.fail) throw new Error("injected window failure");
      if (command === "start_pet_drag") window.displayTest.drags++;
      return [];
    } };
  }, baseUrl);
  await openCompanion(page);
  const canvas = await page.locator(".vrm-renderer canvas").elementHandle();
  await page.locator("[data-pet-chat]").click();
  await page.locator("#chat-input").fill("preserved after native rejection");
  await page.locator('[data-companion-size="panorama"]').click();
  await expect(page.locator(".pet-notice")).toContainText("injected window failure");
  await expect(page.locator("#chat-input")).toHaveValue("preserved after native rejection");
  expect(await page.locator("body").getAttribute("data-companion-size")).not.toBe("panorama");
  await page.evaluate(() => { window.displayTest.fail = false; });
  await page.locator('[data-companion-size="panorama"]').click();
  await expect(page.locator("body")).toHaveAttribute("data-companion-size", "panorama");
  await page.locator("#chat-input").dispatchEvent("pointerdown", { button: 0, isPrimary: true });
  await page.locator("[data-overlay-open-main]").dispatchEvent("pointerdown", { button: 0, isPrimary: true });
  expect(await page.evaluate(() => window.displayTest.drags)).toBe(0);
  await page.locator("[data-overlay-drag-surface]").dispatchEvent("pointerdown", { button: 0, isPrimary: true });
  expect(await page.evaluate(() => window.displayTest.drags)).toBe(1);
  expect(await canvas.evaluate((element) => element === document.querySelector(".vrm-renderer canvas"))).toBe(true);
});

test("A+ workbench module library changes layout only and preserves keyboard operation", async ({ page }) => {
  const modules = ["asr", "screen", "tools"].map((id) => ({ id, name: id, enabled: false, implementation_id: "none", status: "disabled", permissions: id === "asr" ? ["microphone"] : [] }));
  const writes = [];
  await page.route("**/api/modules", (route) => route.fulfill({ json: modules }));
  page.on("request", (request) => {
    if (request.url().endsWith("/rpc")) {
      const body = request.postDataJSON();
      if (/update|permission|start|send/.test(body?.method)) writes.push(body.method);
    }
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator('[data-wv2-view="capabilities"]').click();
  await expect(page.locator(".wv2-capability-card")).toHaveCount(0);
  await expect(page.locator(".wv2-add-tile")).toHaveText("＋");
  await page.locator(".wv2-add-tile").click();
  await page.locator('[data-capability-add="asr"]').click();
  await expect(page.locator('[data-capability-add="asr"]')).toHaveCount(0);
  await page.locator('[data-capability-add="screen"]').click();
  await expect(page.locator('[data-capability-add="ocr"]')).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(page.locator(".wv2-add-tile")).toBeFocused();
  await expect(page.locator(".wv2-capability-card").first()).toContainText("未授权");
  await page.locator("[data-capability-organize]").click();
  await page.locator('[data-capability-move="up"][data-module-id="screen"]').click();
  await expect(page.locator(".wv2-capability-card").first().locator("[data-capability-configure]")).toHaveAttribute("data-capability-configure", "screen");
  const heights = await page.locator(".wv2-capability-card,.wv2-add-tile").evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height));
  expect(Math.max(...heights) - Math.min(...heights)).toBeLessThan(2);
  await page.reload({ waitUntil: "networkidle" });
  await page.locator('[data-wv2-view="capabilities"]').click();
  await expect(page.locator(".wv2-capability-card").first().locator("[data-capability-configure]")).toHaveAttribute("data-capability-configure", "screen");
  await page.locator("[data-capability-organize]").click();
  await page.locator('[data-capability-remove="asr"]').click();
  await page.locator('[data-capability-category="perception"]').focus();
  await page.keyboard.press("End");
  await expect(page.locator('[data-capability-category="life"]')).toBeFocused();
  expect(writes).toEqual([]);
});

test("A+ unavailable VRM bundle reports an explicit error without a fake canvas", async ({ page }) => {
  await page.route("**/vendor/sumika-vrm-viewer.js", (route) => route.abort());
  await page.goto(companionUrl, { waitUntil: "networkidle" });
  await expect(page.locator('.vrm-renderer [role="alert"]')).toContainText("角色加载失败");
  await expect(page.locator(".vrm-renderer canvas")).toHaveCount(0);
  await expect(page.locator("[data-vrm-source]")).toHaveAttribute("data-vrm-status", "error");
});
