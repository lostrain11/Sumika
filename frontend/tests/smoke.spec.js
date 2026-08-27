import { test, expect } from "@playwright/test";
import { createServer } from "node:http";

const baseUrl = process.env.SUMIKA_BASE_URL || "http://127.0.0.1:8770/";
let providerStub;
let providerStubUrl;

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
  await call("provider.profile.save", {
    profile: {
      id: "playwright-openai-stub",
      name: "Playwright OpenAI-compatible stub",
      adapter_id: "openai-compatible",
      template_id: "openai-compatible",
      processing_location: "local",
      active_base_url: providerStubUrl,
      base_urls: [providerStubUrl],
      model: "playwright-model",
    },
  });
  try { await call("provider.profile.restore", { profile_id: "playwright-openai-stub" }); } catch { /* first run has no archived row */ }
  // Archived profiles remain unavailable after a save; explicitly re-check
  // the isolated stub before activating so each test starts from a usable
  // provider regardless of the previous test's cleanup state.
  await call("provider.profile.health", { profile_id: "playwright-openai-stub" });
  await call("provider.profile.activate", { profile_id: "playwright-openai-stub" });
  await call("character.update", {
    character_id: "sumika",
    name: "Sumika",
    config: {
      language: "zh-CN",
      persona: {
        identity: "",
        traits: "",
        relationship: "",
        speaking_style: "",
        behavior: "",
        boundaries: "",
        response_length: "balanced",
        system_prompt: "",
        greeting: "",
      },
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

async function openCharacterSection(page, section) {
  const details = page.locator(`[data-character-section="${section}"]`);
  if (!(await details.evaluate((element) => element.open))) await details.locator("summary").click();
  return details;
}

test.describe("Sumika UI shell", () => {
  test.beforeAll(async () => {
    providerStub = createServer((request, response) => {
      if (request.method === "GET" && request.url === "/v1/models") {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ data: [{ id: "playwright-model" }] }));
        return;
      }
      if (request.method === "POST" && request.url === "/v1/chat/completions") {
        request.resume();
        request.on("end", () => {
          response.writeHead(200, { "Content-Type": "application/json" });
          response.end(JSON.stringify({
            choices: [{ message: { role: "assistant", content: "Playwright stub reply" } }],
          }));
        });
        return;
      }
      response.writeHead(404, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ error: "not found" }));
    });
    await new Promise((resolve, reject) => {
      providerStub.once("error", reject);
      providerStub.listen(0, "127.0.0.1", resolve);
    });
    const address = providerStub.address();
    providerStubUrl = `http://127.0.0.1:${address.port}/v1`;
  });

  test.afterAll(async () => {
    if (providerStub) await new Promise((resolve) => providerStub.close(resolve));
  });

  test.beforeEach(async ({ page }) => {
    await resetWorkspace(page);
  });

  test("chat, navigation, and Avatar visibility", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await expect(page.locator("body")).toContainText("Sumika 默认 Avatar");

    await page.locator("#chat-input").fill("Playwright smoke message");
    await page.locator("#chat-form button[type=submit]").click();
    await expect(page.locator(".message.assistant").last()).toContainText("Playwright stub reply");

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

  test("unconfigured chat directs the user to Provider setup", async ({ page }) => {
    const llmModule = {
      id: "llm",
      name: "大语言模型",
      capability: "llm",
      description: "对话生成的可替换 provider。",
      enabled: false,
      status: "disabled",
      implementation_id: "openai-compatible",
      implementation: {
        id: "openai-compatible",
        name: "OpenAI-compatible",
        status: "unconfigured",
        config_schema: {},
      },
      implementations: [],
      config: {},
      config_schema: {},
      permissions: [],
      resource_requirements: {},
    };
    await page.route("**/api/provider-profiles*", (route) => route.fulfill({
      contentType: "application/json",
      body: "[]",
    }));
    await page.route("**/api/modules", (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([llmModule]),
    }));
    await page.route("**/api/sessions/*/messages", (route) => route.fulfill({
      contentType: "application/json",
      body: "[]",
    }));
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await expect(page.locator(".empty-chat")).toContainText("先配置 Provider");
    await expect(page.locator("#chat-form .send-button")).toBeDisabled();
    await page.locator('.empty-chat [data-page="Modules"]').click();
    await expect(page.locator("body")).toContainText("自定义连接");
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
          center: element.getBoundingClientRect().top + element.getBoundingClientRect().height / 2,
          border: style.borderWidth,
          background: style.backgroundColor,
        };
      });
    });
    expect(metrics.every(Boolean)).toBe(true);
    const heights = metrics.map((item) => item.height);
    expect(Math.max(...heights) - Math.min(...heights)).toBeLessThanOrEqual(1);
    const centers = metrics.map((item) => item.center);
    expect(Math.max(...centers) - Math.min(...centers)).toBeLessThanOrEqual(1);
    expect(metrics[0].border).toBe("0px");
    expect(metrics[0].background).toBe("rgba(0, 0, 0, 0)");
    await expect(page.locator(".provider-summary")).toHaveCSS("white-space", "nowrap");
    await expect(page.locator(".provider-summary-name")).toBeVisible();
    await expect(page.locator(".provider-summary-state")).toHaveCSS("white-space", "nowrap");
    const palette = await page.evaluate(() => {
      const probe = document.createElement("span");
      probe.style.color = "var(--muted)";
      document.body.append(probe);
      const muted = getComputedStyle(probe).color;
      probe.remove();
      return { task: getComputedStyle(document.querySelector('.nav-item[data-page="Tasks"] .nav-glyph')).color, muted };
    });
    expect(palette.task).toBe(palette.muted);
  });

  test("LLM 模块开关是聊天的唯一启停入口", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Modules"]').click();
    const toggle = page.locator('[data-module-toggle="llm"]');
    if (await toggle.getAttribute("aria-checked") === "true") await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await page.locator('.nav-item[data-page="Chat"]').click();
    await expect(page.locator(".provider-summary")).toContainText("已关闭");
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
    await openCharacterSection(page, "model");
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
    await expect(page.locator(".desktop-overlay-toolbar")).toHaveCount(0);
    await expect(page.locator(".desktop-overlay-status")).toHaveCount(0);
    await expect(page.locator(".desktop-overlay-avatar .avatar-orbit")).toHaveCount(0);
    await expect(page.locator(".desktop-overlay-avatar .avatar-preview-copy")).toHaveCount(0);
    await expect(page.locator("[data-overlay-open-main]")).toBeVisible();
    await expect(page.locator("[data-overlay-hide]")).toBeVisible();
    const surfaceStyle = await page.locator(".desktop-overlay-shell").evaluate((element) => {
      const style = getComputedStyle(element);
      return { background: style.backgroundColor, border: style.borderWidth, shadow: style.boxShadow };
    });
    expect(surfaceStyle.background).toBe("rgba(0, 0, 0, 0)");
    expect(surfaceStyle.border).toBe("0px");
    expect(surfaceStyle.shadow).toBe("none");
    await expect(page.locator(".desktop-overlay-controls")).toHaveCSS("opacity", "0");
    await expect(page.locator(".desktop-overlay-controls")).toHaveCSS("pointer-events", "none");
    await page.locator(".desktop-overlay-shell").hover({ position: { x: 12, y: 12 } });
    await expect(page.locator(".desktop-overlay-controls")).toHaveCSS("opacity", "1");
    await expect(page.locator(".desktop-overlay-controls")).toHaveCSS("pointer-events", "auto");
    await expect(page.locator('[data-vrm-source][data-vrm-status="ready"]')).toBeVisible({ timeout: 15000 });
  });

  test("桌宠浮窗提供可拖动模型区域和聊天输入", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 460 });
    await page.goto(baseUrl + "?mode=overlay", { waitUntil: "networkidle" });
    await expect(page.locator(".overlay-composer")).toBeVisible();
    await expect(page.locator(".desktop-overlay-avatar")).toHaveAttribute("data-overlay-drag-surface", "");
    await expect(page.locator(".overlay-composer")).toHaveAttribute("data-no-drag", "");
    await expect(page.locator(".overlay-composer textarea")).toHaveAttribute("data-no-drag", "");
    const avatarBox = await page.locator(".desktop-overlay-avatar").boundingBox();
    const composerBox = await page.locator(".overlay-composer").boundingBox();
    expect(composerBox.y).toBeGreaterThanOrEqual(avatarBox.y + avatarBox.height);
  });

  test("入门指南 covers the workspace and links to controls", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await expect(page.locator(".nav-item").last()).toHaveAttribute("data-page", "Guide");
    await page.locator('.nav-item[data-page="Guide"]').click();
    await expect(page.locator("h1")).toHaveText("入门指南");
    await expect(page.locator("body")).toContainText("界面地图");
    await expect(page.locator("body")).toContainText("完整基本使用流程");
    await expect(page.locator(".guide-map-item")).toHaveCount(9);
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
    await expect(page.locator(".agent-diagnostics-panel")).toContainText("DSH 能力探针");
    await expect(page.locator(".agent-diagnostics-panel")).toContainText("MCP");
    await expect(page.locator("[data-agent-mcp-status]")).toHaveAttribute("data-agent-mcp-status", /disabled|unavailable|not-exposed/);
  });

  test("Agent workspace fails closed when managed DSH is unavailable", async ({ page }) => {
    await page.route("**/api/agent/status", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ state: "unavailable", ready: false, reason: "测试中未连接 DSH" }),
      });
    });
    await page.route("**/api/agent/provider", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ state: "unavailable", ready: false, reason: "测试中未连接 DSH" }),
      });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Agent"]').click();
    await expect(page.locator(".page-layout h1")).toContainText("Agent 工作区");
    await expect(page.locator(".agent-status-line")).toContainText(/未连接|已关闭/);
    await expect(page.locator("#agent-send")).toBeDisabled();
    await expect(page.locator(".agent-panel").last()).toContainText("BrowserSkill");
  });

  test("Agent workspace hides capabilities not implemented by a portable runtime", async ({ page }) => {
    let submittedPrompt = null;
    await page.route("**/api/agent/status", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, runtime_id: "minimal", runtime_capabilities: [] }),
    }));
    await page.route("**/api/agent/provider", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "runtime-owned", ready: true, runtime_id: "minimal", profile: null }),
    }));
    await page.route("**/rpc", async (route) => {
      const body = route.request().postDataJSON();
      if (body?.method === "agent.session.prompt") submittedPrompt = body.params;
      const result = {
        "browser.profiles": { profiles: [] },
        "browser.sessions": { sessions: [] },
        "agent.sessions": { sessions: [] },
        "agent.session.create": { sessionId: "minimal-session" },
        "agent.session.prompt": { accepted: true, id: "minimal-turn" },
        "agent.session.snapshot": {
          session_id: "minimal-session",
          state: "idle",
          title: "Minimal session",
          plan: { active: true, pending: false, steps: [{ status: "running", title: "unsupported" }] },
          messages: [{ role: "user", content: "执行最小任务" }],
          tools: [],
          approvals: [],
          artifacts: [],
          timeline: [],
          stats: {},
        },
      }[body?.method];
      if (result === undefined) {
        await route.continue();
        return;
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }),
      });
    });

    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Agent"]').click();

    await expect(page.locator(".agent-status-line")).toContainText("minimal 已连接");
    await expect(page.locator("#agent-create-session")).toBeEnabled();
    await expect(page.locator("#agent-prompt")).toBeVisible();
    await expect(page.locator("#agent-mode option[value='plan']")).toHaveCount(0);
    await expect(page.locator("#agent-mode")).toHaveValue("execute");
    await expect(page.locator(".agent-attachment-tools")).toHaveCount(0);
    await expect(page.locator(".agent-provider-panel, .agent-preset-panel, .agent-workspace-panel, .agent-model-panel, .agent-goal-panel, .agent-subagent-panel")).toHaveCount(0);

    await page.locator("#agent-prompt").fill("执行最小任务");
    await page.locator("#agent-send").click();
    await expect.poll(() => submittedPrompt?.mode).toBe("execute");
    expect(submittedPrompt?.content).toEqual([{ type: "text", text: "执行最小任务" }]);
    await expect(page.locator(".agent-session-visible-title")).toHaveText("Minimal session");
    await expect(page.locator(".agent-session-panel .agent-subsection-heading strong", { hasText: "Plan" })).toHaveCount(0);
  });

  test("Agent workspace exposes a synced provider and submits a goal", async ({ page }) => {
    await page.route("**/api/agent/status", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ state: "ready", ready: true, version: "0.1.1-rc.2", commit: "b150a551b8d4" }),
      });
    });
    await page.route("**/api/agent/provider", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          state: "ready",
          ready: true,
          profile_id: "playwright-openai-stub",
          route_id: "sumika-playwright-openai-stub-test",
          model: "playwright-model",
          synced: true,
          active: true,
          profile: { name: "Playwright stub", config: { model: "playwright-model" } },
        }),
      });
    });
    await page.route("**/rpc", async (route) => {
      const body = route.request().postDataJSON();
      const result = {
        "browser.profiles": { profiles: [] },
        "agent.skills": { skills: [{ id: "workspace" }] },
        "agent.mcp.inventory": { available: true, status: "observed", catalog_available: false, observation_source: "session-history", client_installed: true, client_version: "0.1.1-rc.2", server_count: 1, tool_count: 1, entries: [{ name: "github", tools: [{ name: "mcp__github__search" }] }] },
        "agent.subagents": { entries: [], parentAvailable: true },
        "agent.commands": { available: true, entries: [{ name: "plan", description: "Enter or leave plan mode" }] },
        "browser.sessions": { sessions: [] },
        "agent.session.create": {
          sessionId: "playwright-agent-session",
          provider: { route_id: "sumika-playwright-openai-stub-test", model: "playwright-model" },
        },
        "agent.session.snapshot": {
          session_id: "playwright-agent-session",
          state: "idle",
          title: "Playwright Agent 会话",
          plan: { active: false, pending: false, steps: [] },
          messages: [],
          tools: [],
          approvals: [],
          artifacts: [],
          timeline: [],
          stats: {},
        },
        "agent.session.prompt": { accepted: true },
      }[body?.method];
      if (result === undefined) {
        await route.continue();
        return;
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }),
      });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Agent"]').click();
    await expect(page.locator(".agent-status-line")).toContainText("DSH 已连接");
    await expect(page.locator(".agent-provider-panel")).toContainText("Playwright stub");
    await expect(page.locator(".agent-provider-panel")).toContainText("sumika-playwright-openai-stub-test");
    await expect(page.locator(".agent-capability").filter({ hasText: "Commands" })).toContainText("plan");
    await expect(page.locator("[data-agent-mcp-inventory='observed']")).toContainText("mcp__github__search");
    await expect(page.locator("[data-agent-mcp-inventory='observed']")).toContainText("1 服务 · 1 工具");
    await page.locator("#agent-create-session").click();
    await expect(page.locator("body")).toContainText("Agent 会话已创建");
    await expect(page.locator(".agent-session-panel")).toContainText("当前会话");
    await page.locator("#agent-prompt").fill("检查当前工作区");
    await page.locator("#agent-send").click();
    await expect(page.locator("body")).toContainText("目标已提交");
  });

  test("Agent preset lifecycle, Goal revision, and Subagent controls use the pinned DSH contract", async ({ page }) => {
    let createdParams;
    let selectedPreset;
    let goal;
    let childActivity = "running";
    let subagentPrompt;
    let copiedPreset;
    let openedPreset;
    let removedPreset;
    const presets = [
      { id: "standard", name: "标准", trust: "system", is_default: true },
      { id: "advanced", name: "高级", trust: "user" },
    ];
    const calls = [];
    await page.route("**/api/agent/status", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, version: "0.1.1-rc.2", commit: "b150a551b8d4" }),
    }));
    await page.route("**/api/agent/provider", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, profile_id: "playwright-openai-stub", route_id: "sumika-test", model: "model-a", profile: { name: "Playwright stub" } }),
    }));
    await page.route("**/rpc", async (route) => {
      const body = route.request().postDataJSON();
      const method = body?.method;
      calls.push(body);
      let result;
      if (method === "agent.session.create") {
        createdParams = body.params;
        result = { sessionId: "agent-contract", agentPreset: body.params.agentPreset, provider: { route_id: "sumika-test", model: "model-a" } };
      } else if (method === "agent.session.select_preset") {
        selectedPreset = body.params;
        result = { session_id: "agent-contract", agent_preset: body.params.agentPreset };
      } else if (method === "agent.preset.copy") {
        copiedPreset = body.params;
        presets.push({ id: body.params.agentPreset, name: body.params.name, trust: "user" });
        result = { agent_preset: body.params.agentPreset, source: body.params.from };
      } else if (method === "agent.preset.open") {
        openedPreset = body.params.agentPreset;
        result = { agent_preset: body.params.agentPreset, opened: true };
      } else if (method === "agent.preset.remove") {
        removedPreset = body.params;
        const index = presets.findIndex((preset) => preset.id === body.params.agentPreset);
        if (index >= 0) presets.splice(index, 1);
        result = { agent_preset: body.params.agentPreset, removed: true };
      } else if (method === "agent.goal.create") {
        goal = { ref: { id: "goal-contract", revision: 0 }, objective: body.params.objective, phase: "active", max_goal_rounds: body.params.maxGoalRounds };
        result = { ref: goal.ref };
      } else if (method === "agent.goal.pause") {
        goal = { ...goal, ref: { id: goal.ref.id, revision: goal.ref.revision + 1 }, phase: "paused" };
        result = { ref: goal.ref };
      } else if (method === "agent.goal.clear") {
        goal = null;
        result = { cleared: true };
      } else if (method === "agent.subagent.prompt") {
        subagentPrompt = body.params;
        result = { accepted: true, parent_session_id: "agent-contract", child_session_id: "child-contract", message_id: "message-contract" };
      } else if (method === "agent.subagent.interrupt") {
        childActivity = "inactive";
        result = { accepted: true, parent_session_id: "agent-contract", child_session_id: "child-contract" };
      } else if (method === "agent.subagent.history") {
        result = { parent_session_id: "agent-contract", child_session_id: "child-contract", mode: "continuable", messages: [{ role: "assistant", content: "已检查" }] };
      } else if (method === "agent.presets") {
        result = { presets, authorable: true, has_document: true };
      } else if (method === "agent.sessions") {
        result = { sessions: [{ id: "agent-contract", title: "契约测试会话", state: "idle", blank: true, agent_preset: selectedPreset?.agentPreset || "standard" }] };
      } else if (method === "agent.session.snapshot") {
        result = { session_id: "agent-contract", state: "idle", title: "契约测试会话", goal, plan: { active: false, pending: false, steps: [] }, messages: [], tools: [], approvals: [], artifacts: [], timeline: [], stats: {} };
      } else if (method === "agent.subagent.list") {
        result = { entries: [{ kind: "child", id: "child-contract", label: "检查子任务", mode: "continuable", activity: childActivity }], parent_available: true };
      } else if (method === "agent.session.models") {
        result = { current: { provider: "sumika-test", model: "model-a" }, routable: true, groups: [{ id: "sumika-test", name: "Sumika test", models: [{ id: "model-a", name: "Model A" }] }], failures: [] };
      } else if (method === "agent.session.queue") {
        result = { session_id: "agent-contract", known: true, items: [], hidden_context_count: 0 };
      } else if (method === "agent.workspaces") {
        result = { workspaces: [], archived_session_ids: [] };
      } else if (method === "agent.interactions") {
        result = { interactions: [] };
      } else if (method === "agent.skills") {
        result = { skills: [] };
      } else if (method === "agent.mcp.inventory") {
        result = { available: false, status: "not-observed", catalog_available: false, observation_source: "session-history", client_installed: true, client_version: "0.1.1-rc.2", entries: [] };
      } else if (method === "agent.subagents") {
        result = { entries: [] };
      } else if (method === "agent.commands") {
        result = { available: true, entries: [{ name: "plan" }] };
      } else {
        await route.continue();
        return;
      }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }) });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Agent"]').click();
    await page.locator("#agent-create-session").click();
    await expect(page.locator(".agent-session-panel")).toContainText("契约测试会话");
    expect(createdParams.agentPreset).toBe("standard");

    await page.locator("#agent-preset-select").selectOption("advanced");
    await expect(page.locator(".agent-notice")).toContainText("已选择 Preset");
    expect(selectedPreset).toMatchObject({ sessionId: "agent-contract", agentPreset: "advanced" });

    await page.locator("#agent-preset-copy-source").selectOption("standard");
    await page.locator("#agent-preset-copy-id").fill("sumika-work");
    await page.locator("#agent-preset-copy-name").fill("Sumika 工作");
    await page.locator("#agent-preset-copy-form button[type=submit]").click();
    await expect(page.locator(".agent-notice")).toContainText("当前会话 Preset 未改变");
    expect(copiedPreset).toEqual({ from: "standard", agentPreset: "sumika-work", name: "Sumika 工作" });
    await expect(page.locator("#agent-preset-select")).toHaveValue("advanced");
    await expect(page.locator('[data-agent-preset-row="sumika-work"]')).toContainText("Sumika 工作");
    await page.locator('[data-agent-preset-open="sumika-work"]').click();
    await expect(page.locator(".agent-notice")).toContainText("已打开用户 Preset 目录");
    expect(openedPreset).toBe("sumika-work");
    await expect(page.locator('[data-agent-preset-remove="standard"]')).toHaveCount(0);
    const deletionDialogs = [];
    const handleDeletionDialog = async (dialog) => {
      deletionDialogs.push(dialog.type());
      if (dialog.type() === "prompt") await dialog.accept("sumika-work");
      else await dialog.accept();
    };
    page.on("dialog", handleDeletionDialog);
    await page.locator('[data-agent-preset-remove="sumika-work"]').click();
    await expect(page.locator(".agent-notice")).toContainText("用户 Preset 已删除");
    page.off("dialog", handleDeletionDialog);
    expect(deletionDialogs).toEqual(["prompt", "confirm"]);
    expect(removedPreset).toEqual({
      agentPreset: "sumika-work",
      confirm_agent_preset: "sumika-work",
      approved: true,
    });
    await expect(page.locator('[data-agent-preset-row="sumika-work"]')).toHaveCount(0);

    await page.locator('#agent-goal-form input[name="objective"]').fill("完成契约检查");
    await page.locator("#agent-goal-form").getByRole("button", { name: "创建 Goal" }).click();
    await expect(page.locator(".agent-goal-current")).toContainText("完成契约检查");
    await page.locator('[data-agent-goal-action="pause"]').click();
    await expect(page.locator(".agent-goal-current")).toContainText("revision 1");
    const pauseCall = calls.find((item) => item.method === "agent.goal.pause");
    expect(pauseCall.params.ref).toEqual({ id: "goal-contract", revision: 0 });

    await page.once("dialog", (dialog) => dialog.accept());
    await page.locator('[data-agent-goal-action="clear"]').click();
    await expect(page.locator(".agent-goal-panel")).toContainText("当前会话没有活动 Goal");

    await page.locator('[data-agent-subagent-history="child-contract"]').click();
    await expect(page.locator(".agent-subagent-history")).toContainText("已检查");
    await page.once("dialog", (dialog) => dialog.accept("继续检查"));
    await page.locator('[data-agent-subagent-prompt="child-contract"]').click();
    await expect(page.locator(".agent-notice")).toContainText("跟进已提交");
    expect(subagentPrompt).toMatchObject({ parentSessionId: "agent-contract", childSessionId: "child-contract", mode: "continuable", text: "继续检查" });
    await page.locator('[data-agent-subagent-interrupt="child-contract"]').click();
    await expect(page.locator(".agent-notice")).toContainText("中断请求");
  });

  test("Agent workspace registers a directory, switches models, and creates a recoverable fork", async ({ page }) => {
    let selectedModel = "model-a";
    let createdSessionParams;
    let registeredPath;
    let forked = false;
    await page.route("**/api/agent/status", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, version: "0.1.1-rc.2", commit: "b150a551b8d4" }),
    }));
    await page.route("**/api/agent/provider", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, profile_id: "playwright-openai-stub", route_id: "sumika-test", model: "model-a", profile: { name: "Playwright stub" } }),
    }));
    await page.route("**/rpc", async (route) => {
      const body = route.request().postDataJSON();
      const sessionId = forked ? "agent-child" : "agent-parent";
      let result;
      if (body?.method === "agent.workspace.create") {
        registeredPath = body.params.path;
        result = { created: true, workspace: { id: "workspace-new", title: "Sumika", path: registeredPath, session_ids: [] } };
      } else if (body?.method === "agent.session.create") {
        createdSessionParams = body.params;
        result = { sessionId: "agent-parent", provider: { route_id: "sumika-test", model: "model-a" } };
      } else if (body?.method === "agent.session.select_model") {
        selectedModel = body.params.model;
        result = { selected: { provider: body.params.provider, model: body.params.model } };
      } else if (body?.method === "agent.session.fork") {
        forked = true;
        result = { sessionId: "agent-child" };
      } else {
        result = {
          "browser.profiles": { profiles: [] },
          "agent.skills": { skills: [] },
          "agent.mcp.inventory": { available: false, status: "not-observed", catalog_available: false, observation_source: "session-history", client_installed: true, entries: [] },
          "agent.subagents": { entries: [] },
          "agent.commands": { available: true, entries: [{ name: "plan" }] },
          "agent.interactions": { interactions: [] },
          "browser.sessions": { sessions: [] },
          "agent.workspaces": { workspaces: [{ id: "workspace-new", title: "Sumika", path: registeredPath || "D:\\Code\\Sumika", session_ids: forked ? ["agent-parent", "agent-child"] : [] }], archived_session_ids: [] },
          "agent.sessions": { sessions: forked ? [{ id: "agent-child", title: "分支", state: "idle" }, { id: "agent-parent", title: "原会话", state: "idle" }] : [{ id: "agent-parent", title: "原会话", state: "idle" }] },
          "agent.session.snapshot": { session_id: sessionId, state: "idle", title: forked ? "分支" : "原会话", plan: { active: false, pending: false, steps: [] }, messages: [], tools: [], approvals: [], artifacts: [], timeline: [], stats: {} },
          "agent.session.models": { current: { provider: "sumika-test", model: selectedModel }, routable: true, groups: [{ id: "sumika-test", name: "Sumika test", models: [{ id: "model-a", name: "Model A" }, { id: "model-b", name: "Model B" }] }], failures: [] },
        }[body?.method];
      }
      if (result === undefined) return route.continue();
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }) });
    });

    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Agent"]').click();
    await page.locator("#agent-workspace-path").fill("D:\\Code\\Sumika");
    await page.locator("#agent-register-workspace").click();
    await expect(page.locator(".agent-notice")).toContainText("已登记 Workspace");
    expect(registeredPath).toBe("D:\\Code\\Sumika");

    await page.locator("#agent-create-session").click();
    await expect(page.locator(".agent-session-panel")).toContainText("原会话");
    expect(createdSessionParams.workspaceId).toBe("workspace-new");
    expect(createdSessionParams.cwd).toBeUndefined();

    await page.locator("#agent-model-select").selectOption({ label: "Sumika test · Model B" });
    await expect(page.locator(".agent-notice")).toContainText("已切换到 model-b");
    expect(selectedModel).toBe("model-b");

    await page.locator("#agent-fork-session").click();
    await expect(page.locator(".agent-notice")).toContainText("已创建分支会话：agent-child");
    await expect(page.locator(".agent-session-panel")).toContainText("分支");
    await expect(page.locator(".agent-session-row")).toHaveCount(2);
  });

  test("Agent shows safe tool presentation and edits the transient DSH queue", async ({ page }) => {
    let updatedQueue;
    await page.route("**/api/agent/status", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, version: "0.1.1-rc.2", commit: "b150a551b8d4" }),
    }));
    await page.route("**/api/agent/provider", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, profile_id: "playwright-openai-stub", route_id: "sumika-test", model: "model-a", profile: { name: "Playwright stub" } }),
    }));
    await page.route("**/rpc", async (route) => {
      const body = route.request().postDataJSON();
      const result = {
        "browser.profiles": { profiles: [] },
        "agent.skills": { skills: [] },
        "agent.mcp.inventory": { available: false, status: "not-observed", catalog_available: false, observation_source: "session-history", client_installed: true, entries: [] },
        "agent.subagents": { entries: [] },
        "agent.commands": { available: true, entries: [{ name: "plan" }] },
        "agent.session.create": { sessionId: "queue-session", provider: { route_id: "sumika-test", model: "model-a" } },
        "agent.sessions": { sessions: [{ id: "queue-session", title: "队列会话", state: "idle" }] },
        "agent.session.snapshot": {
          session_id: "queue-session",
          state: "idle",
          title: "队列会话",
          plan: { active: false, pending: false, steps: [] },
          messages: [],
          tools: [{ name: "read", status: "completed", call: { card: "generic", title: "读取文件", kind: "read", locations: [{ path: "README.md", line: 1 }] }, result: { card: "read", path: "README.md", line_count: 3 } }],
          approvals: [],
          artifacts: [{ type: "tool/diff", label: "修改文件", status: "completed", file_count: 1, locations: [{ path: "frontend/main.js" }] }],
          timeline: [],
          stats: {},
        },
        "agent.session.models": { current: { provider: "sumika-test", model: "model-a" }, routable: true, groups: [{ id: "sumika-test", name: "Sumika test", models: [{ id: "model-a", name: "Model A" }] }], failures: [] },
        "agent.session.queue": { session_id: "queue-session", known: true, items: [{ id: "queue-item", placement: "queued", text: "检查文档", editable: true, can_remove: true, can_steer: true }], hidden_context_count: 1 },
      }[body?.method];
      if (body?.method === "agent.session.update_queue") {
        updatedQueue = body;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { accepted: true, session_id: "queue-session", item_id: "queue-item", action: "edit" } }) });
        return;
      }
      if (result === undefined) return route.continue();
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }) });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Agent"]').click();
    await page.locator("#agent-create-session").click();
    await expect(page.locator(".agent-queue-subsection")).toContainText("检查文档");
    await expect(page.locator(".agent-tool-card")).toContainText("读取文件");
    await expect(page.locator(".agent-artifact-row")).toContainText("修改文件");
    await expect(page.locator(".agent-artifact-row")).toContainText("frontend/main.js");
    await expect(page.locator("#agent-export-session")).toHaveAttribute("href", "/api/agent/session.export?session_id=queue-session&include_descendants=true");
    await expect(page.locator(".agent-queue-note")).toContainText("1 项");
    await page.locator('[data-agent-queue-input]').fill("更新后的目标");
    await page.locator('[data-agent-queue-action="edit"]').click();
    await expect(page.locator(".agent-notice")).toContainText("已更新待发送消息");
    expect(updatedQueue.params.kind).toBe("edit");
    expect(updatedQueue.params.text).toBe("更新后的目标");
  });

  test("Agent workspace validates and submits a pending DSH question", async ({ page }) => {
    let answered = false;
    let questionBody;
    await page.route("**/api/agent/status", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ state: "ready", ready: true, version: "0.1.1-rc.2", commit: "b150a551b8d4" }),
      });
    });
    await page.route("**/api/agent/provider", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          state: "ready",
          ready: true,
          profile_id: "playwright-openai-stub",
          route_id: "sumika-playwright-openai-stub-test",
          model: "playwright-model",
          synced: true,
          active: true,
          profile: { name: "Playwright stub", config: { model: "playwright-model" } },
        }),
      });
    });
    await page.route("**/rpc", async (route) => {
      const body = route.request().postDataJSON();
      if (body?.method === "agent.interactions") {
        const interactions = answered ? [] : [{
          id: "question-playwright",
          kind: "question",
          session_id: "playwright-agent-session",
          questions: [{
            id: "choice",
            header: "执行方式",
            question: "如何继续？",
            options: [
              { label: "现在执行", description: "在隔离 Workspace 中执行" },
              { label: "仅查看", description: "保持只读" },
            ],
            multiSelect: false,
          }],
        }];
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { interactions } }) });
        return;
      }
      if (body?.method === "agent.question.respond") {
        questionBody = body;
        answered = true;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { accepted: true, kind: "question" } }) });
        return;
      }
      const result = {
        "browser.profiles": { profiles: [] },
        "agent.skills": { skills: [] },
        "agent.mcp.inventory": { available: false, status: "not-observed", catalog_available: false, observation_source: "session-history", client_installed: true, entries: [] },
        "agent.subagents": { entries: [] },
        "agent.commands": { available: true, entries: [{ name: "plan" }] },
        "agent.sessions": { sessions: [{ id: "playwright-agent-session", title: "问题会话", state: "idle" }] },
        "agent.session.snapshot": { session_id: "playwright-agent-session", state: "idle", title: "问题会话", plan: { active: false, pending: false, steps: [] }, messages: [], tools: [], approvals: [], artifacts: [], timeline: [], stats: {} },
      }[body?.method];
      if (result === undefined) {
        await route.continue();
        return;
      }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }) });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Agent"]').click();
    await expect(page.locator(".question-interaction")).toContainText("如何继续？");
    await page.locator('.agent-question-option input[value="现在执行"]').check();
    await page.locator('.question-interaction button[type="submit"]').click();
    await expect(page.locator(".agent-notice")).toContainText("回答已提交");
    await expect.poll(() => questionBody?.params?.answer?.answers?.[0]?.selected).toEqual(["现在执行"]);
    await expect(page.locator(".question-interaction")).toHaveCount(0);
  });

  test("Agent session search and rename fail closed and escape titles", async ({ page }) => {
    let searchQuery = "";
    let searchDisabled = false;
    let sessionTitle = "可见会话标题";
    await page.route("**/api/agent/status", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, version: "0.1.1-rc.2", commit: "b150a551b8d4" }),
    }));
    await page.route("**/api/agent/provider", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, profile_id: "playwright-openai-stub", route_id: "sumika-test", model: "model-a", profile: { name: "Playwright stub" } }),
    }));
    await page.route("**/rpc", async (route) => {
      const body = route.request().postDataJSON();
      const method = body?.method;
      if (method === "agent.sessions.search") {
        searchQuery = body.params.query;
        if (searchDisabled) {
          await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, error: { code: -32030, message: "session search is disabled (openAt never)" } }) });
        } else {
          await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { items: [{ session_id: "search-session", snippet: "契约内容命中" }], has_more: false } }) });
        }
        return;
      }
      if (method === "agent.session.rename") {
        sessionTitle = body.params.title;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { session_id: "search-session", title: sessionTitle, seq: 4 } }) });
        return;
      }
      const result = {
        "browser.profiles": { profiles: [] },
        "browser.sessions": { sessions: [] },
        "browser.downloads": { downloads: [] },
        "agent.interactions": { interactions: [] },
        "agent.skills": { skills: [] },
        "agent.mcp.inventory": { available: false, status: "not-observed", catalog_available: false, observation_source: "session-history", client_installed: true, entries: [] },
        "agent.subagents": { entries: [] },
        "agent.commands": { available: true, entries: [{ name: "plan" }] },
        "agent.presets": { presets: [] },
        "agent.sessions": { sessions: [{ id: "search-session", title: sessionTitle, state: "idle" }] },
        "agent.session.snapshot": { session_id: "search-session", state: "idle", title: sessionTitle, plan: { active: false, pending: false, steps: [] }, messages: [], tools: [], approvals: [], artifacts: [], timeline: [], stats: {} },
        "agent.session.queue": { session_id: "search-session", known: true, items: [], hidden_context_count: 0 },
        "agent.session.models": { current: { provider: "sumika-test", model: "model-a" }, routable: true, groups: [{ id: "sumika-test", name: "Sumika test", models: [{ id: "model-a", name: "Model A" }] }] },
        "agent.workspaces": { workspaces: [], archived_session_ids: [] },
      }[method] || {};
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }) });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Agent"]').click();
    await page.locator("#agent-session-search").fill("契约");
    await page.locator("#agent-session-search-form button[type=submit]").click();
    await expect.poll(() => searchQuery).toBe("契约");
    await expect(page.locator(".agent-session-row")).toContainText("契约内容命中");
    await page.locator('[data-agent-session-select="search-session"]').click();
    await expect(page.locator("#agent-session-title")).toBeVisible();
    await page.locator("#agent-session-title").fill("<新名称>");
    await page.locator("#agent-session-rename").click();
    await expect(page.locator(".agent-session-visible-title")).toHaveText("<新名称>");
    expect(await page.locator(".agent-session-visible-title script")).toHaveCount(0);

    searchDisabled = true;
    await page.locator("#agent-session-search").fill("禁用索引");
    await page.locator("#agent-session-search-form button[type=submit]").click();
    await expect(page.locator(".agent-session-search-notice")).toContainText("搜索不可用");
    await expect(page.locator(".agent-session-list")).toContainText("没有匹配的会话");
  });

  test("Agent image attachments use content blocks and keep image data out of the UI audit", async ({ page }) => {
    const tinyPng = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
    let promptBody;
    let includeAttachment = false;
    let attachmentRead = false;
    await page.route("**/api/agent/status", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, version: "0.1.1-rc.2", commit: "b150a551b8d4" }),
    }));
    await page.route("**/api/agent/provider", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, profile_id: "playwright-openai-stub", route_id: "sumika-test", model: "model-a", profile: { name: "Playwright stub" } }),
    }));
    await page.route("**/rpc", async (route) => {
      const body = route.request().postDataJSON();
      const method = body?.method;
      if (method === "agent.session.prompt") {
        promptBody = body;
        includeAttachment = true;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { accepted: true, id: "turn-image" } }) });
        return;
      }
      if (method === "agent.session.attachment") {
        attachmentRead = true;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { session_id: "image-session", attachment: { attachment_id: "image-1", media_type: "image/png", name: "tiny.png" }, data: tinyPng } }) });
        return;
      }
      const result = {
        "browser.profiles": { profiles: [] },
        "browser.sessions": { sessions: [] },
        "browser.downloads": { downloads: [] },
        "agent.interactions": { interactions: [] },
        "agent.skills": { skills: [] },
        "agent.mcp.inventory": { available: false, status: "not-observed", catalog_available: false, observation_source: "session-history", client_installed: true, entries: [] },
        "agent.subagents": { entries: [] },
        "agent.commands": { available: true, entries: [{ name: "plan" }] },
        "agent.presets": { presets: [] },
        "agent.session.create": { sessionId: "image-session", provider: { route_id: "sumika-test", model: "model-a" } },
        "agent.sessions": { sessions: [{ id: "image-session", title: "图片会话", state: "idle" }] },
        "agent.session.snapshot": { session_id: "image-session", state: "idle", title: "图片会话", plan: { active: false, pending: false, steps: [] }, messages: includeAttachment ? [{ role: "user", content: "图片目标", attachments: [{ attachment_id: "image-1", media_type: "image/png", name: "tiny.png" }] }] : [], tools: [], approvals: [], artifacts: [], timeline: [], stats: {} },
        "agent.session.queue": { session_id: "image-session", known: true, items: [], hidden_context_count: 0 },
        "agent.session.models": { current: { provider: "sumika-test", model: "model-a" }, routable: true, groups: [{ id: "sumika-test", name: "Sumika test", models: [{ id: "model-a", name: "Model A" }] }] },
        "agent.workspaces": { workspaces: [], archived_session_ids: [] },
      }[method] || {};
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }) });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Agent"]').click();
    await page.locator("#agent-create-session").click();
    await page.locator("#agent-image-input").setInputFiles({ name: "tiny.png", mimeType: "image/png", buffer: Buffer.from(tinyPng, "base64") });
    await expect(page.locator(".agent-attachment-chip")).toContainText("tiny.png");
    await page.locator("#agent-send").click();
    await expect.poll(() => promptBody?.params?.content?.find((item) => item.type === "image")?.data).toBe(tinyPng);
    await expect(page.locator('[data-agent-attachment-load="image-1"]')).toBeVisible();
    await page.locator('[data-agent-attachment-load="image-1"]').click();
    await expect(page.locator(".agent-message-image")).toBeVisible();
    expect(attachmentRead).toBe(true);
    await expect(page.locator(".agent-event-list")).not.toContainText(tinyPng);

    await page.locator("#agent-image-input").setInputFiles({ name: "bad.txt", mimeType: "text/plain", buffer: Buffer.from("not an image") });
    await expect(page.locator(".agent-attachment-notice")).toContainText("格式不支持");
    expect(promptBody.params.content.filter((item) => item.type === "image")).toHaveLength(1);
  });

  test("Agent workspace lists and stops isolated browser sessions", async ({ page }) => {
    let navigationApproved = false;
    let tabSelected = false;
    let tabClosed = false;
    let consoleRead = false;
    let networkRead = false;
    await page.route("**/api/agent/status", async (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", ready: true, version: "0.1.1-rc.2", commit: "b150a551b8d4" }),
    }));
    await page.route("**/rpc", async (route) => {
      const body = route.request().postDataJSON();
      if (body?.method === "browser.navigate") {
        navigationApproved = Boolean(body.params.approved);
        const result = navigationApproved
          ? { session_id: "browser-test", executed: true, domain: "example.test" }
          : { session_id: "browser-test", executed: false, policy: { allowed: false, requires_approval: true, domain: "example.test" } };
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }) });
        return;
      }
      if (body?.method === "browser.tab.select") {
        tabSelected = true;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { session_id: "browser-test", executed: true, tab_id: body.params.tab_id } }) });
        return;
      }
      if (body?.method === "browser.tab.close") {
        tabClosed = true;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { session_id: "browser-test", executed: true, tab_id: body.params.tab_id } }) });
        return;
      }
      if (body?.method === "browser.console") {
        consoleRead = true;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { session_id: "browser-test", executed: true, result: { entries: [{ level: "info", message: "safe console summary" }] } } }) });
        return;
      }
      if (body?.method === "browser.network") {
        networkRead = true;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { session_id: "browser-test", executed: true, result: { entries: [{ status: 200, url: "https://example.test/api" }] } } }) });
        return;
      }
      const result = {
        "browser.profiles": { profiles: [] },
        "agent.skills": { skills: [] },
        "agent.mcp.inventory": { available: false, status: "not-observed", catalog_available: false, observation_source: "session-history", client_installed: true, entries: [] },
        "agent.subagents": { entries: [] },
        "agent.commands": { available: true, entries: [{ name: "plan" }] },
        "agent.sessions": { sessions: [] },
        "browser.sessions": { sessions: [{ id: "browser-test", profile: "temporary", state: "ready" }] },
        "browser.tabs": { session_id: "browser-test", ready: true, tabs: [{ id: "tab-1", title: "安全页", url: "https://example.test", active: true }] },
        "browser.tab.create": { session_id: "browser-test", executed: true, url: "chrome://newtab/" },
        "browser.snapshot": { session_id: "browser-test", ready: true, snapshot: { role: "WebArea", name: "安全页" } },
        "browser.downloads": { downloads: [] },
        "browser.observe": { session_id: "browser-test", ready: true, observation: { url: "https://example.test", tree: [{ text: "安全摘要" }] } },
        "browser.request_help": { session_id: "browser-test", backend_requested: true, state: "paused" },
        "browser.session.close": { id: "browser-test", closed: true },
      }[body?.method];
      if (result === undefined) return route.continue();
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }) });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Agent"]').click();
    await expect(page.locator(".browser-session-row")).toContainText("browser-test");
    await expect(page.locator(".browser-tab-row")).toContainText("安全页");
    await page.locator('[data-browser-tabs="browser-test"]').click();
    await page.locator('[data-browser-tab-select="tab-1"]').click();
    await page.locator('[data-browser-snapshot="browser-test"]').click();
    await expect(page.locator(".browser-observation-wrap")).toContainText("WebArea");
    await page.locator("#browser-developer-mode").check();
    page.on("dialog", (dialog) => dialog.accept());
    await page.locator('[data-browser-console="browser-test"]').click();
    await page.locator('[data-browser-network="browser-test"]').click();
    await expect(page.locator(".browser-diagnostic")).toHaveCount(2);
    expect(tabSelected).toBe(true);
    expect(consoleRead).toBe(true);
    expect(networkRead).toBe(true);
    await page.locator("[data-browser-url]").fill("https://example.test");
    await page.locator('[data-browser-navigate="browser-test"]').click();
    await expect(page.locator(".agent-notice")).toContainText("需要确认");
    await page.locator('[data-browser-navigate-approve="browser-test"]').click();
    await expect(page.locator(".agent-notice")).toContainText("导航已提交");
    expect(navigationApproved).toBe(true);
    await page.locator('[data-browser-observe="browser-test"]').click();
    await expect(page.locator(".browser-observation").filter({ hasText: "安全摘要" })).toBeVisible();
    await page.locator('[data-browser-help="browser-test"]').click();
    await expect(page.locator(".agent-notice")).toContainText("已请求人工接管");
    await page.locator('[data-browser-tab-close="tab-1"]').click();
    expect(tabClosed).toBe(true);
    await page.locator('[data-browser-session-close="browser-test"]').click();
    await expect(page.locator("body")).toContainText("隔离浏览器会话已停止");
    await expect(page.locator(".browser-session-row")).toHaveCount(0);
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

  test("角色配置按职责折叠并持久化可生效人格字段", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator('.nav-item[data-page="Characters"]').click();

    const groups = page.locator(".character-settings-group");
    await expect(groups).toHaveCount(3);
    for (const section of ["identity", "persona", "model"]) {
      await expect(page.locator(`[data-character-section="${section}"]`)).not.toHaveAttribute("open", "");
    }
    await expect(page.locator(".avatar-library")).toBeVisible();
    await expect(page.locator(".character-settings-group .avatar-library")).toHaveCount(0);

    await openCharacterSection(page, "identity");
    await page.locator('textarea[name="persona_identity"]').fill("温和可靠的学习搭档");
    await openCharacterSection(page, "persona");
    await page.locator('textarea[name="persona_traits"]').fill("耐心、务实");
    await page.locator('textarea[name="persona_relationship"]').fill("长期合作伙伴");
    await page.locator('select[name="persona_response_length"]').selectOption("concise");
    await page.locator('textarea[name="system_prompt"]').fill("结论优先");
    await page.locator('textarea[name="greeting"]').fill("欢迎回来");
    await page.locator("#character-form button[type=submit]").click();

    await expect(page.locator(".character-notice")).toContainText("已保存");
    await expect(page.locator('[data-character-section="persona"] summary')).toContainText("已设置 4 项 · 简洁");
    await openCharacterSection(page, "identity");
    await expect(page.locator('textarea[name="persona_identity"]')).toHaveValue("温和可靠的学习搭档");
    await openCharacterSection(page, "persona");
    await expect(page.locator('textarea[name="persona_traits"]')).toHaveValue("耐心、务实");
    await expect(page.locator('select[name="persona_response_length"]')).toHaveValue("concise");
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
    await openCharacterSection(page, "model");
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
