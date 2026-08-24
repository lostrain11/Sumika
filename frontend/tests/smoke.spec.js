import { test, expect } from "@playwright/test";

const baseUrl = process.env.SUMIKA_BASE_URL || "http://127.0.0.1:8770/";

async function resetWorkspace(page) {
  const rpcUrl = `${baseUrl.replace(/\/$/, "")}/rpc`;
  const call = async (method, params) => {
    const response = await page.request.post(rpcUrl, {
      data: { jsonrpc: "2.0", id: `${method}-${Date.now()}`, method, params },
    });
    if (!response.ok()) throw new Error(`${method} reset failed: ${response.status()}`);
    const body = await response.json();
    if (body.error) throw new Error(`${method} reset failed: ${body.error.message}`);
    return body.result;
  };
  await call("provider.profile.activate", { profile_id: "local-ollama" });
  await call("character.update", {
    character_id: "sumika",
    name: "Sumika",
    config: {
      avatar: {
        position: "center",
        opacity: 1,
        scale: 1,
        idle_motion: true,
        auto_rotate: false,
        rotation_speed: 0.12,
        natural_pose: true,
        look_at_enabled: true,
        head_follow_enabled: true,
        look_at_strength: 1,
        head_follow_strength: 0.35,
      },
    },
  });
}

test.describe("Sumika UI shell", () => {
  test.beforeEach(async ({ page }) => {
    await resetWorkspace(page);
  });

  test("chat, navigation, and Avatar visibility", async ({ page }) => {
    // The first Ollama request may include a one-time model load on this machine.
    test.setTimeout(60000);
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await expect(page.locator("body")).toContainText("Sumika 默认 Avatar");

    await page.locator("#chat-input").fill("Playwright smoke message");
    await page.locator("#chat-form button[type=submit]").click();
    // A cold local Ollama model may need to load weights on the first request.
    await expect(page.locator(".message.assistant").last()).toBeVisible({ timeout: 45000 });

    await page.locator('.nav-item[data-page="Modules"]').click();
    await expect(page.locator("body")).toContainText("语音识别");
    await page.locator('.nav-item[data-page="Tasks"]').click();
    await expect(page.locator("body")).toContainText("任务中心");

    await page.locator('.nav-item[data-page="Chat"]').click();
    await page.locator("[data-avatar-toggle]").click();
    await expect(page.locator("body")).toContainText("Avatar 已隐藏");
    await page.locator("[data-avatar-toggle]").click();
    await expect(page.locator("body")).toContainText("Sumika 默认 Avatar");
  });

  test("顶部运行状态使用统一的扁平高度", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    const metrics = await page.evaluate(() => {
      const selectors = [".provider-summary", ".status-chip", ".privacy-chip"];
      return selectors.map((selector) => {
        const element = document.querySelector(selector);
        if (!element) return null;
        const style = getComputedStyle(element);
        return {
          selector,
          height: element.getBoundingClientRect().height,
          border: style.borderWidth,
          background: style.backgroundColor,
        };
      });
    });
    expect(metrics.every(Boolean)).toBe(true);
    const heights = metrics.map((item) => item.height);
    expect(Math.max(...heights) - Math.min(...heights)).toBeLessThanOrEqual(1);
    expect(metrics[0].border).toBe("0px");
    expect(metrics[0].background).toBe("rgba(0, 0, 0, 0)");
  });

  test("LLM 模块开关是聊天的唯一启停入口", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Modules"]').click();
    const toggle = page.locator('[data-module-toggle="llm"]');
    if (await toggle.getAttribute("aria-checked") === "true") await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await page.locator('.nav-item[data-page="Chat"]').click();
    await expect(page.locator(".provider-summary")).toContainText("LLM 已关闭");
    const send = page.locator("#chat-form .send-button");
    await expect(send).toBeDisabled();
    await expect(send).toHaveCSS("cursor", "not-allowed");
    const rejected = await page.evaluate(async () => {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: "default", messages: [{ role: "user", content: "disabled test" }] }),
      });
      return { status: response.status, body: await response.json() };
    });
    expect(rejected.status).toBe(400);
    expect(rejected.body.error.message).toContain("LLM module is disabled");
  });

  test("bundled VRM renders into a live canvas", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    const renderer = page.locator('[data-vrm-source][data-vrm-status="ready"]');
    await expect(renderer).toBeVisible({ timeout: 15000 });
    const canvas = renderer.locator("canvas");
    await expect(canvas).toHaveCount(1);
    const rendered = await canvas.evaluate((element) => {
      const canvas = /** @type {HTMLCanvasElement} */ (element);
      return {
        width: canvas.width,
        height: canvas.height,
        dataUrlLength: canvas.toDataURL("image/png").length,
      };
    });
    expect(rendered.width).toBeGreaterThan(0);
    expect(rendered.height).toBeGreaterThan(0);
    expect(rendered.dataUrlLength).toBeGreaterThan(1000);
  });

  test("中心舞台默认启用待机动作且不自动旋转", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    const stage = page.locator(".avatar-stage .avatar-placeholder");
    await expect(stage).toHaveClass(/avatar-position-center/);
    const renderer = page.locator('[data-vrm-source][data-vrm-status="ready"]');
    await expect(renderer).toHaveAttribute("data-vrm-idle-motion", "true");
    await expect(renderer).toHaveAttribute("data-vrm-auto-rotate", "false");
    await expect(renderer).toHaveAttribute("data-vrm-motion-status", "active");
    const initialYaw = await renderer.getAttribute("data-vrm-yaw");
    await page.waitForTimeout(300);
    await expect(renderer).toHaveAttribute("data-vrm-yaw", initialYaw || "3.142");

    await page.locator('.nav-item[data-page="Characters"]').click();
    const autoRotate = page.locator('input[name="avatar_auto_rotate"]');
    await autoRotate.check();
    await page.locator("#character-form button[type=submit]").click();
    await expect(page.locator(".character-notice")).toContainText("已保存");
    await page.locator('.nav-item[data-page="Chat"]').click();
    const rotatingRenderer = page.locator('[data-vrm-source][data-vrm-status="ready"]');
    await expect(rotatingRenderer).toHaveAttribute("data-vrm-auto-rotate", "true");
    const rotatingYaw = await rotatingRenderer.getAttribute("data-vrm-yaw");
    await page.waitForTimeout(300);
    const nextYaw = await rotatingRenderer.getAttribute("data-vrm-yaw");
    expect(nextYaw).not.toBe(rotatingYaw);
  });

  test("Avatar 信息层与模型画布分离", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    const placeholder = page.locator(".avatar-stage .avatar-placeholder");
    const copy = page.locator(".avatar-stage .avatar-preview-copy");
    await expect(copy).toHaveCount(1);
    expect(await copy.evaluate((element) => element.parentElement?.classList.contains("avatar-presenter"))).toBe(true);
    expect(await copy.evaluate((element) => element.parentElement?.classList.contains("avatar-placeholder"))).toBe(false);
    const placeholderBox = await placeholder.boundingBox();
    const copyBox = await copy.boundingBox();
    expect(placeholderBox).not.toBeNull();
    expect(copyBox).not.toBeNull();
    expect(copyBox.y).toBeGreaterThanOrEqual(placeholderBox.y + placeholderBox.height - 1);
  });

  test("缺失忽略墓碑只在开发者页审计", async ({ page }) => {
    await page.route("**/api/avatar/ignored", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([{
          id: "ignored-missing-test",
          name: "Missing Sample",
          kind: "vrm",
          path: "C:\\\\example\\\\sumika-assets\\\\missing.vrm",
          available: false,
          size_bytes: 0,
          last_known_kind: "vrm",
          reason: "missing_or_inaccessible",
        }]),
      });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Characters"]').click();
    await expect(page.locator(".avatar-ignored")).toContainText("1 条失效忽略记录");
    await expect(page.locator(".avatar-ignored-row")).toHaveCount(0);
    await page.locator('.nav-item[data-page="Developer"]').click();
    await expect(page.locator(".avatar-audit-panel")).toContainText("Missing Sample");
    await expect(page.locator(".avatar-audit-panel")).toContainText("missing.vrm");
    await expect(page.locator("[data-avatar-ignored-clear]")).toBeVisible();
  });

  test("desktop overlay route keeps Avatar and high-frequency controls", async ({ page }) => {
    await page.goto(baseUrl + "?mode=overlay", { waitUntil: "networkidle" });
    await expect(page.locator(".desktop-overlay-shell")).toBeVisible();
    await expect(page.locator(".desktop-overlay-title strong")).not.toBeEmpty();
    await expect(page.locator(".desktop-overlay-title")).toContainText("核心已连接");
    await expect(page.locator("[data-overlay-open-main]")).toBeVisible();
    await expect(page.locator("[data-overlay-hide]")).toBeVisible();
    await expect(page.locator('[data-vrm-source][data-vrm-status="ready"]')).toBeVisible({ timeout: 15000 });
  });

  test("桌宠浮窗提供可拖动模型区域和聊天输入", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 460 });
    await page.goto(baseUrl + "?mode=overlay", { waitUntil: "networkidle" });
    await expect(page.locator(".overlay-composer")).toBeVisible();
    await expect(page.locator(".desktop-overlay-avatar")).toHaveAttribute("data-tauri-drag-region", "");
    await expect(page.locator(".desktop-overlay-avatar")).toContainText("Sumika");
    const avatarBox = await page.locator(".desktop-overlay-avatar").boundingBox();
    const copyBox = await page.locator(".desktop-overlay-avatar .avatar-preview-copy").boundingBox();
    const composerBox = await page.locator(".overlay-composer").boundingBox();
    expect(copyBox.y + copyBox.height).toBeLessThanOrEqual(avatarBox.y + avatarBox.height);
    expect(composerBox.y).toBeGreaterThanOrEqual(avatarBox.y + avatarBox.height);
  });

  test("入门指南 covers the workspace and links to controls", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await expect(page.locator(".nav-item").last()).toHaveAttribute("data-page", "Guide");
    await page.locator('.nav-item[data-page="Guide"]').click();
    await expect(page.locator("h1")).toHaveText("入门指南");
    await expect(page.locator("body")).toContainText("界面地图");
    await expect(page.locator("body")).toContainText("完整基本使用流程");
    await expect(page.locator(".guide-map-item")).toHaveCount(8);
    await expect(page.locator(".guide-flow-item")).toHaveCount(7);
    await page.locator('.guide-jump[data-page="Modules"]').first().click();
    await expect(page.locator("body")).toContainText("语音识别");
  });

  test("语音输入在 ASR 未启动时只显示配置引导", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator("[data-audio-record]").click();
    await expect(page.locator(".voice-notice")).toContainText("请先在“模块”页启用语音识别");
    await expect(page.locator("[data-audio-record]")).toHaveAttribute("aria-pressed", "false");
  });

  test("聊天草稿在工作区重绘后仍保留", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator("#chat-input").fill("等待确认的草稿");
    await page.locator('.nav-item[data-page="Modules"]').click();
    await page.locator('.nav-item[data-page="Chat"]').click();
    await expect(page.locator("#chat-input")).toHaveValue("等待确认的草稿");
  });

  test("开发者页 exposes safe runtime diagnostics", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Developer"]').click();
    await expect(page.locator(".diagnostics-panel")).toContainText("核心诊断");
    await expect(page.locator(".diagnostics-panel")).toContainText("核心日志");
    await expect(page.locator(".diagnostics-panel")).toContainText("PID");
  });

  test("Avatar library explains discovery and binding-safe unregister", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Characters"]').click();
    await expect(page.locator("#discover-avatar-assets")).toContainText("扫描内置目录");
    await expect(page.locator("#import-avatar")).toContainText("选择模型文件");
    await expect(page.locator(".avatar-library")).toContainText("放入 assets/avatars 后可扫描登记");
    const boundRow = page.locator(".avatar-model-row").filter({ hasText: "已绑定" }).first();
    await expect(boundRow.locator("[data-avatar-clear]")).toContainText("解除当前角色绑定");
    await page.locator(".avatar-model-row [data-avatar-inspect]").first().click();
    await expect(page.locator(".avatar-inspection").first()).toContainText("清单检查");
    await expect(page.locator(".avatar-ignored")).toContainText("已忽略模型");
  });

  test("compact viewport stays within the viewport", async ({ page }) => {
    await page.setViewportSize({ width: 860, height: 760 });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    const dimensions = await page.evaluate(() => ({
      viewport: window.innerWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
  });

  test("舞台鼠标跟随会回中且可以按角色关闭", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    const renderer = page.locator('[data-vrm-source][data-vrm-status="ready"]');
    await expect(renderer).toHaveAttribute("data-vrm-look-at-status", "active");
    await expect(renderer).toHaveAttribute("data-vrm-head-follow-status", "active");
    const box = await renderer.boundingBox();
    expect(box).not.toBeNull();
    await page.mouse.move(box.x + box.width * 0.9, box.y + box.height * 0.35);
    await expect.poll(async () => Number(await renderer.getAttribute("data-vrm-head-yaw"))).toBeGreaterThan(0.01);
    await expect(renderer).toHaveAttribute("data-vrm-pointer-state", "active");
    await page.mouse.move(1, 1);
    await expect(renderer).toHaveAttribute("data-vrm-pointer-state", "centered");
    await expect.poll(async () => Math.abs(Number(await renderer.getAttribute("data-vrm-head-yaw")))).toBeLessThan(0.02);

    await page.locator('.nav-item[data-page="Characters"]').click();
    await page.locator('input[name="avatar_natural_pose"]').uncheck();
    await page.locator('input[name="avatar_look_at_enabled"]').uncheck();
    await page.locator('input[name="avatar_head_follow_enabled"]').uncheck();
    await page.locator("#character-form button[type=submit]").click();
    await expect(page.locator(".character-notice")).toContainText("已保存");
    await page.locator('.nav-item[data-page="Chat"]').click();
    const disabledRenderer = page.locator('[data-vrm-source][data-vrm-status="ready"]');
    await expect(disabledRenderer).toHaveAttribute("data-vrm-natural-pose", "false");
    await expect(disabledRenderer).toHaveAttribute("data-vrm-natural-pose-status", "disabled");
    await expect(disabledRenderer).toHaveAttribute("data-vrm-look-at-status", "disabled");
    await expect(disabledRenderer).toHaveAttribute("data-vrm-head-follow-status", "disabled");
  });

  test("Provider picker keeps recent profiles ordered and opens the drawer", async ({ page }) => {
    const profiles = [
      {
        id: "recent-cloud",
        name: "最近云端",
        adapter_id: "openai-compatible",
        status: "available",
        active: true,
        processing_location: "cloud",
        resolved_processing_location: "cloud",
        last_used_at: "2026-08-24T09:00:00Z",
        config: { model: "cloud-model", active_base_url: "https://example.invalid/v1", base_urls: ["https://example.invalid/v1"] },
        has_secrets: true,
      },
      {
        id: "older-local",
        name: "较早本地",
        adapter_id: "openai-compatible",
        status: "available",
        active: false,
        processing_location: "local",
        resolved_processing_location: "local",
        last_used_at: "2026-08-23T09:00:00Z",
        config: { model: "local-model", active_base_url: "http://127.0.0.1:11434/v1", base_urls: ["http://127.0.0.1:11434/v1"] },
        has_secrets: false,
      },
      {
        id: "draft-profile",
        name: "待配置连接",
        adapter_id: "openai-compatible",
        status: "draft",
        active: false,
        processing_location: "auto",
        resolved_processing_location: "cloud",
        config: { model: "", active_base_url: "", base_urls: [] },
        has_secrets: false,
      },
    ];
    await page.route("**/api/provider-profiles*", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(profiles) });
    });
    await page.route("**/api/privacy", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ label: "混合处理", mode: "mixed" }) });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Modules"]').click();
    await page.locator(".provider-picker summary").click();
    const rows = page.locator(".provider-profile-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText("最近云端");
    await expect(rows.nth(1)).toContainText("较早本地");
    await expect(rows.nth(2)).toContainText("待配置连接");
    await expect(page.locator(".privacy-chip")).toContainText("混合处理");
    await page.locator("[data-provider-new]").click();
    await expect(page.locator(".provider-drawer")).toBeVisible();
    await expect(page.locator("#provider-profile-form")).toContainText("当前 Base URL");
    await expect(page.locator("#provider-profile-form")).toContainText("保存草稿");
    await expect(page.locator("#provider-profile-form")).toContainText("测试连接");
    await expect(page.locator("#provider-profile-form")).toContainText("保存并启用");
  });

  test("CC Switch import preview masks secrets and keeps the draft boundary", async ({ page }) => {
    const preview = {
      format: "sumika-provider-profile/v1",
      importer_id: "ccswitch-v1",
      profile: {
        name: "Imported Provider",
        base_urls: ["https://api.example.invalid/v1"],
        model: "gpt-test",
      },
      secret_fields: ["api_key"],
      masked_secrets: { api_key: "sk-t******************st" },
      field_mapping: [
        { source: "endpoint", target: "base_urls", status: "mapped" },
        { source: "apiKey", target: "Credential Manager / api_key", status: "mapped" },
      ],
      unsupported_fields: [{ field: "usageScript", value: "[redacted]" }],
      warnings: ["CC Switch JavaScript 用量脚本已禁用；Sumika 不会执行任意脚本。"],
    };
    await page.route("**/rpc", async (route) => {
      const body = route.request().postDataJSON();
      if (body?.method !== "provider.import.preview") {
        await route.continue();
        return;
      }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: preview }) });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Modules"]').click();
    await page.locator(".provider-picker summary").click();
    await page.locator("[data-provider-new]").click();
    await page.locator('[data-provider-drawer-mode="import"]').click();
    await page.locator("#provider-import-raw").fill("ccswitch://v1/import?apiKey=sk-raw-secret");
    await page.locator("#provider-import-preview").click();
    await expect(page.locator(".provider-import-preview")).toContainText("Imported Provider");
    await expect(page.locator(".provider-import-preview")).toContainText("sk-t******************st");
    await expect(page.locator(".provider-import-preview")).not.toContainText("sk-raw-secret");
    await expect(page.locator(".provider-import-preview")).toContainText("保存为草稿");
  });

  test("draft profile opens for configuration instead of activating", async ({ page }) => {
    const requests = [];
    page.on("request", (request) => {
      if (request.url().endsWith("/rpc") && request.method() === "POST") {
        try {
          requests.push(request.postDataJSON()?.method);
        } catch {
          // Ignore non-JSON requests from the event connection.
        }
      }
    });
    await page.route("**/api/provider-profiles*", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([{
          id: "draft-only",
          name: "需要配置",
          adapter_id: "openai-compatible",
          status: "draft",
          active: false,
          processing_location: "auto",
          resolved_processing_location: "cloud",
          config: { model: "", active_base_url: "", base_urls: [] },
          has_secrets: false,
        }]),
      });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Modules"]').click();
    await page.locator(".provider-picker summary").click();
    await page.locator('[data-provider-select="draft-only"]').click();
    await expect(page.locator(".provider-drawer")).toBeVisible();
    await expect(page.locator("#provider-drawer-title")).toHaveText("编辑连接");
    expect(requests).not.toContain("provider.profile.activate");
  });

  test("Developer can restore an archived profile", async ({ page }) => {
    let restored = false;
    await page.route("**/api/provider-profiles*", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([{
          id: "archived-profile",
          name: "已归档连接",
          adapter_id: "openai-compatible",
          status: restored ? "draft" : "archived",
          archived_at: restored ? null : "2026-08-23T00:00:00Z",
          active: false,
          processing_location: "cloud",
          resolved_processing_location: "cloud",
          config: { model: "archived-model", active_base_url: "https://example.invalid/v1", base_urls: ["https://example.invalid/v1"] },
          has_secrets: false,
        }]),
      });
    });
    await page.route("**/rpc", async (route) => {
      const body = route.request().postDataJSON();
      if (body?.method !== "provider.profile.restore") {
        await route.continue();
        return;
      }
      restored = true;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: {
          id: "archived-profile",
          name: "已归档连接",
          adapter_id: "openai-compatible",
          status: "draft",
          archived_at: null,
          active: false,
          processing_location: "cloud",
          resolved_processing_location: "cloud",
          config: { model: "archived-model", active_base_url: "https://example.invalid/v1", base_urls: ["https://example.invalid/v1"] },
          has_secrets: false,
        } })
      });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Developer"]').click();
    await expect(page.locator('[data-provider-restore="archived-profile"]')).toBeVisible();
    await page.locator('[data-provider-restore="archived-profile"]').click();
    await expect(page.locator(".provider-row").first()).toContainText("已归档连接");
    await expect(page.locator("body")).toContainText("已恢复为草稿");
  });
});
