import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

import { createWorkbenchV2View } from "../src/workbench-v2-view.js";

const css = await readFile(new URL("../src/workbench-v2.css", import.meta.url), "utf8");
const escapeHtml = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

const fixture = {
  view: "workspace",
  assistant: { id: "fixture-assistant", name: "Sumika" },
  workbench: {
    activeProjectId: "fixture-project",
    activeProjectName: "组件测试项目",
    activeConversationId: "fixture-session",
    projects: [
      { id: "fixture-project", name: "组件测试项目", category: "测试", pinned: true },
      { id: "archived-project", name: "已归档项目", category: "资料", archived: true },
    ],
    conversations: [{ id: "fixture-session", title: "前端重构", source: "测试夹具" }],
    schedules: [{ id: "fixture-schedule", title: "每周检查", status: "ready", next_run_label: "周五 18:00" }],
    conversation: {
      session_id: "fixture-session",
      title: "前端重构",
      has_more: true,
      rounds: [
        { id: "r1", messages: [{ role: "user", content: "请实现工作台。" }, { role: "assistant", content: "先完成预检和预算确认。" }] },
        { id: "r2", messages: [{ role: "user", content: "保持成果正文干净。" }, { role: "assistant", content: "成果与附言会分别显示。" }] },
        { id: "r3", messages: [{ role: "user", content: "右侧按需打开。" }] },
      ],
    },
    selectedTask: {
      request_id: "fixture-request",
      assistant_id: "fixture-assistant",
      revision: 1,
      status: "awaiting-confirmation",
      goal: "完成 P10/P12 组件",
      classification: { complexity: "complex", reason: "包含工作台与设置整理" },
      quote: { low_cny: "0.00", typical_cny: "2.00", high_cny: "5.00" },
      artifacts: [{ id: "fixture-artifact", name: "组件实现", format: "source", content: "export function component() {}", verified: true }],
      commentary: "测试夹具附言",
    },
    inspector: {
      open: true,
      active: "files",
      files: [{ id: "file-1", path: "frontend/src/workbench-v2-view.js", status: "modified" }],
    },
  },
  capabilities: {
    status: "ready",
    activeCategory: "perception",
    added_ids: ["asr", "vision"],
    modules: [
      { id: "asr", name: "语音识别", description: "测试夹具模块", category: "perception", enabled: false, configured: true, permission_label: "未授权", registered: true },
      { id: "vision", name: "图像理解", description: "测试夹具模块", category: "perception", enabled: true, configured: true, permission_label: "已授权", registered: true },
      { id: "camera", name: "摄像头", description: "测试夹具模块", category: "perception", enabled: false, configured: false, permission_label: "未授权", registered: true },
    ],
  },
  settings: {
    bindings: {
      work: { mode: "auto", applied_label: "高质量候选", selection_reason: "质量证据最强", cost_label: "按任务报价", candidates: [{ id: "work-a", name: "工作候选 A", available: true, provider: "fixture", reasoning_effort: "high" }] },
      role: { mode: "fixed", candidate_id: "role-old", candidate_name: "失效角色候选", invalid_reason: "健康检查失败", candidates: [{ id: "role-a", name: "角色候选 A", available: true, provider: "fixture", reasoning_effort: "medium" }] },
    },
    budget: { preference: "quality-first", max_cny: "12.00" },
    memory: { summary: "仅用于组件视觉验证" },
  },
  companion: { bubble: "今天也在这里。", composerOpen: true, draft: "聊一句" },
};

async function mount(page, state) {
  const html = createWorkbenchV2View({
    state,
    escapeHtml,
    slots: {
      tasks: () => "<div class='fixture-slot'>旧任务中心由宿主复用</div>",
      agent: () => "<div class='fixture-slot'>Agent 工作区由宿主复用</div>",
      web: () => "<div class='fixture-slot'>网页工作台由宿主复用</div>",
      history: () => "<div class='fixture-slot'>历史与通知由宿主复用</div>",
      schedule: () => "<div class='fixture-slot'>定时工作管理由宿主复用</div>",
      characters: () => "<div class='fixture-slot'>角色编辑器由宿主复用</div>",
      connections: () => "<div class='fixture-slot'>连接配置由宿主复用</div>",
      memory: () => "<div class='fixture-slot'>记忆管理由宿主复用</div>",
      diagnostics: () => "<div class='fixture-slot'>高级诊断由宿主复用</div>",
      scene: () => "<div class='fixture-scene' aria-label='测试场景'><span>SCENE SLOT</span></div>",
    },
  }).render();
  await page.setContent(`<style>html,body,#app{width:100%;height:100%;margin:0;overflow:hidden}.fixture-scene{width:100%;height:100%;display:grid;place-items:center;background:#dfe7dd;color:#47746a}.fixture-slot{padding:12px;border:1px solid #d9ded6}</style><style>${css}</style><div id="app">${html}</div>`);
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }]) {
  test(`静态工作台组件适配 ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await mount(page, fixture);
    await expect(page.locator(".wv2-primary-nav button")).toHaveCount(4);
    await expect(page.locator(".wv2-residence-button")).toBeVisible();
    await expect(page.locator(".wv2-sidebar")).toBeVisible();
    await expect(page.locator(".wv2-task")).toBeVisible();
    await expect(page.locator(".wv2-inspector")).toBeVisible();
    await expect(page.locator(".wv2-commentary")).toContainText("测试夹具附言");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1 && document.documentElement.scrollHeight <= innerHeight + 1)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`workbench-v2-${viewport.width}.png`) });
  });
}

test("能力库与设置组件无服务视觉状态", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await mount(page, { ...fixture, view: "capabilities", capabilities: { ...fixture.capabilities, organize: true, libraryOpen: true } });
  await expect(page.locator(".wv2-capability-card")).toHaveCount(2);
  await expect(page.locator("[data-capability-remove]")).toHaveCount(2);
  await expect(page.locator("[data-capability-add='camera']")).toBeVisible();
  await expect(page.locator(".wv2-module-library")).not.toContainText("添加只改变页面布局");
  await page.screenshot({ path: testInfo.outputPath("workbench-v2-capabilities.png") });

  await mount(page, { ...fixture, view: "settings" });
  await expect(page.locator("[data-model-binding='work']")).toBeVisible();
  await expect(page.locator("[data-model-binding='role'] .wv2-warning")).toContainText("不会静默切换");
  await expect(page.locator("[data-budget-settings] input[name='max_cny']")).toHaveValue("12.00");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("workbench-v2-settings.png") });
});

test("companion 查询对应 480x420 紧凑场景与聊一句", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 480, height: 420 });
  await mount(page, { ...fixture, view: "companion" });
  await expect(page.locator(".wv2-companion-scene")).toBeVisible();
  await expect(page.locator(".wv2-companion-bubble")).toContainText("今天也在这里");
  await expect(page.locator("[data-companion-send]")).toBeVisible();
  await expect(page.locator(".wv2-primary-nav")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1 && document.documentElement.scrollHeight <= innerHeight + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("workbench-v2-companion-480.png"), omitBackground: true });
});

test("外部父任务确认前展示子步骤授权范围", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await mount(page, { ...fixture, workbench: { ...fixture.workbench, selectedTask: {
    request_id: "parent-plan", revision: 1, status: "awaiting-confirmation", goal: "整理报告并核验",
    external: { limit_enforced: true }, quote: { low_cny: "4", typical_cny: "4", high_cny: "4" },
    external_steps: [{ id: "verify", purpose: "核验资料来源", method: "agent.session.prompt", candidate_id: "fixture:bounded",
      high_cny: "2", params: { text: "只核验已有材料，不读取其他目录", sessionId: "child-session" } }],
  } } });
  await expect(page.getByRole("region", { name: "本次授权包含的子步骤" })).toBeVisible();
  await expect(page.locator(".wv2-external-steps")).toContainText("共用总预算");
  await expect(page.locator(".wv2-external-steps")).toContainText("只核验已有材料");
  await page.getByText("查看执行范围", { exact: true }).click();
  await expect(page.locator(".wv2-external-steps pre")).toContainText("child-session");
  await page.getByText("查看执行范围", { exact: true }).click();
  const confirmButton = page.locator(".wv2-budget-confirm button");
  await confirmButton.scrollIntoViewIfNeeded();
  await expect(confirmButton).toBeEnabled();
  await confirmButton.click({ trial: true });
  const bounds = await confirmButton.boundingBox();
  const timeline = await page.locator(".wv2-timeline").boundingBox();
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(timeline.x + timeline.width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("workbench-external-parent.png") });
});
