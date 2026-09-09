import { test, expect } from "@playwright/test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { PNG } = require("../node_modules/playwright-core/lib/utilsBundle.js");
const baseUrl = process.env.SUMIKA_BASE_URL || "http://127.0.0.1:8770/";

async function open(page) {
  await page.addInitScript(() => localStorage.setItem("sumika.onboarded.v1", "1"));
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await expect(page.locator('[data-vrm-status="ready"]')).toBeVisible();
}

async function checkCanvas(page, label, testInfo) {
  const image = PNG.sync.read(await page.locator(".vrm-renderer canvas").screenshot());
  const colors = new Set();
  for (let offset = 0; offset < image.data.length; offset += 128) colors.add(`${image.data[offset] >> 4},${image.data[offset + 1] >> 4},${image.data[offset + 2] >> 4}`);
  expect(colors.size).toBeGreaterThan(25);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`${label}.png`), omitBackground: true });
}

test("A+ same canvas and draft across layouts, paused rendering and transparency", async ({ page }, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  expect(await page.locator(".scene-primary-nav").innerText()).toMatch(/陪伴\s+工作台\s+能力\s+角色\s+设置/);
  const originalCanvas = await page.locator(".vrm-renderer canvas").elementHandle();
  await page.locator("#chat-input").fill("A+ draft preserved");
  await checkCanvas(page, "companion-1440", testInfo);
  await page.getByRole("button", { name: "收起聊天", exact: true }).click();
  await expect(page.locator(".scene-chat")).toBeHidden();
  await expect(page.locator(".restore-chat")).toBeFocused();
  await page.locator(".restore-chat").click();
  await expect(page.locator("#chat-input")).toHaveValue("A+ draft preserved");
  await page.locator('[data-character-theme="berry"]').click();
  await page.locator('.scene-primary-nav [data-page="Capabilities"]').click();
  await expect(page.locator(".vrm-renderer")).toHaveAttribute("data-vrm-render-status", "paused");
  await page.keyboard.press("Escape");
  await expect(page.locator(".vrm-renderer")).toHaveAttribute("data-vrm-render-status", "running");
  await page.locator("[data-overlay-open]").click();
  await page.setViewportSize({ width: 480, height: 420 });
  await expect(page.locator("#chat-input")).toHaveValue("A+ draft preserved");
  await checkCanvas(page, "pet-480", testInfo);
  const composer = await page.locator(".overlay-composer").boundingBox();
  expect(composer.width).toBeGreaterThan(440);
  await expect(page.locator(".overlay-composer .send-button")).toHaveCSS("font-size", "12px");
  await expect(page.locator(".pet-bubble")).toBeVisible();
  await page.locator("[data-pet-background]").focus();
  await page.locator("[data-pet-background]").click();
  await page.mouse.move(-20, -20);
  await page.evaluate(() => document.activeElement?.blur());
  const transparent = PNG.sync.read(await page.screenshot({ omitBackground: true }));
  let clear = 0;
  for (let offset = 3; offset < transparent.data.length; offset += 4) if (!transparent.data[offset]) clear++;
  expect(clear).toBeGreaterThan(transparent.width * transparent.height * .2);
  await checkCanvas(page, "pet-transparent", testInfo);
  await page.locator("[data-pet-chat]").focus();
  await page.locator("[data-pet-chat]").click();
  await expect(page.locator("#chat-form")).toBeHidden();
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(page.locator("#chat-input")).toHaveValue("A+ draft preserved");
  await checkCanvas(page, "companion-1280", testInfo);
  await page.setViewportSize({ width: 390, height: 844 });
  await checkCanvas(page, "companion-mobile", testInfo);
  expect(await originalCanvas.evaluate((element) => element === document.querySelector(".vrm-renderer canvas"))).toBe(true);
  expect(errors).toEqual([]);
});

test("A+ rejected native transition preserves layout; dragging excludes input and buttons", async ({ page }) => {
  await page.addInitScript((endpoint) => {
    window.displayTest = { fail: true, drags: 0 };
    window.__TAURI_INTERNALS__ = { invoke: async (command, payload) => {
      if (command === "core_status") return { host: new URL(endpoint).hostname, port: new URL(endpoint).port };
      if (command === "get_display_mode") return "workspace";
      if (command === "set_display_mode") {
        if (window.displayTest.fail) throw new Error("injected window failure");
        return payload.mode;
      }
      if (command === "start_pet_drag") window.displayTest.drags++;
      return [];
    } };
  }, baseUrl);
  await open(page);
  const canvas = await page.locator(".vrm-renderer canvas").elementHandle();
  await page.locator("#chat-input").fill("preserved after native rejection");
  await page.locator("[data-overlay-open]").click();
  await expect(page.locator(".session-notice")).toContainText("injected window failure");
  await expect(page.locator(".scene-primary-nav")).toBeVisible();
  await expect(page.locator("#chat-input")).toHaveValue("preserved after native rejection");
  await page.evaluate(() => { window.displayTest.fail = false; });
  await page.locator("[data-overlay-open]").click();
  await expect(page.locator(".desktop-overlay-shell")).toBeVisible();
  await page.locator("#chat-input").dispatchEvent("pointerdown", { button: 0, isPrimary: true });
  await page.locator("[data-overlay-open-main]").dispatchEvent("pointerdown", { button: 0, isPrimary: true });
  expect(await page.evaluate(() => window.displayTest.drags)).toBe(0);
  await page.locator("[data-overlay-drag-surface]").dispatchEvent("pointerdown", { button: 0, isPrimary: true });
  expect(await page.evaluate(() => window.displayTest.drags)).toBe(1);
  expect(await canvas.evaluate((element) => element === document.querySelector(".vrm-renderer canvas"))).toBe(true);
});

test("A+ capability library only changes layout, keyboard return and reload", async ({ page }, testInfo) => {
  const modules = ["asr", "screen", "tools"].map((id) => ({ id, name: id, enabled: false, implementation_id: "none", status: "disabled", permissions: id === "asr" ? ["microphone"] : [] }));
  const writes = [];
  await page.route("**/api/modules", (route) => route.fulfill({ json: modules }));
  page.on("request", (request) => { if (request.url().endsWith("/rpc")) { const body = request.postDataJSON(); if (/update|permission|start|send/.test(body?.method)) writes.push(body.method); } });
  await open(page);
  await page.locator('.scene-primary-nav [data-page="Capabilities"]').click();
  await expect(page.locator("[data-capability-card]")).toHaveCount(0);
  await expect(page.locator(".capability-add-tile")).toHaveText("＋");
  await page.locator(".capability-add-tile").click();
  await page.locator('[data-capability-add="asr"]').click();
  await expect(page.locator('[data-capability-add="asr"]')).toHaveCount(0);
  await page.locator('[data-capability-add="screen"]').click();
  await expect(page.locator('[data-capability-add="ocr"]')).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(page.locator(".capability-add-tile")).toBeFocused();
  await expect(page.locator('[data-capability-card][data-module-id="asr"]')).toContainText("未启用");
  await expect(page.locator('[data-capability-card][data-module-id="asr"]')).toContainText("未知");
  await page.locator('[data-capability-move="up"][data-module-id="screen"]').click();
  await expect(page.locator("[data-capability-card]").first()).toHaveAttribute("data-module-id", "screen");
  const heights = await page.locator("[data-capability-card],.capability-add-tile").evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height));
  expect(Math.max(...heights) - Math.min(...heights)).toBeLessThan(2);
  await page.screenshot({ path: testInfo.outputPath("capabilities.png") });
  await page.reload({ waitUntil: "networkidle" });
  await page.locator('.scene-primary-nav [data-page="Capabilities"]').click();
  await expect(page.locator("[data-capability-card]").first()).toHaveAttribute("data-module-id", "screen");
  await page.locator('[data-capability-remove="asr"]').click();
  await page.locator('[data-capability-tab="perception"]').focus();
  await page.keyboard.press("End");
  await expect(page.locator('[data-capability-tab="life"]')).toBeFocused();
  expect(writes).toEqual([]);
});

test("A+ unavailable VRM bundle reports an explicit error without a fake canvas", async ({ page }) => {
  await page.route("**/vendor/sumika-vrm-viewer.js", (route) => route.abort());
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await expect(page.locator('.vrm-renderer [role="alert"]')).toContainText("角色加载失败");
  await expect(page.locator(".vrm-renderer canvas")).toHaveCount(0);
  await expect(page.locator("[data-vrm-source]")).toHaveAttribute("data-vrm-status", "error");
});
