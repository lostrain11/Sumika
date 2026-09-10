import { expect } from "@playwright/test";

export async function openPage(page, target) {
  if (target === "Chat") {
    const url = new URL(page.url());
    url.search = "?view=companion";
    await page.goto(url.href, { waitUntil: "networkidle" });
    await expect(page.locator(".desktop-overlay-shell")).toBeVisible();
    if (!(await page.locator("#chat-form").isVisible())) {
      await page.locator("[data-pet-chat]").focus();
      await page.locator("[data-pet-chat]").click();
    }
    return;
  }
  if (new URL(page.url()).searchParams.get("view") === "companion") {
    const url = new URL(page.url());
    url.search = "";
    await page.goto(url.href, { waitUntil: "networkidle" });
  }
  await expect(page.locator(".wv2-topbar")).toBeVisible();
  const views = { Workspace: "workspace", Capabilities: "capabilities", Characters: "characters", Settings: "settings", Modules: "settings", Developer: "settings", Guide: "settings" };
  await page.locator(`.wv2-primary-nav [data-wv2-view="${views[target] || "workspace"}"]`).click();
  await expect(page.locator(".workbench-v2")).toHaveAttribute("data-workbench-v2-view", views[target] || "workspace");
  const sections = { Agent: "Agent 工作区", WebWorkbench: "网页工作台", Tasks: "旧任务中心", History: "历史与通知", Notifications: "历史与通知", Modules: "连接配置", Developer: "高级诊断", Guide: "外观与指南" };
  if (!sections[target]) return;
  if (!views[target]) {
    const advanced = page.locator(".wv2-advanced").filter({ has: page.locator('summary', { hasText: /^高级工作区$/ }) });
    if (!(await advanced.evaluate((element) => element.open))) await advanced.locator(":scope > summary").click();
  }
  const summary = page.locator("summary").filter({ hasText: new RegExp("^" + sections[target] + "$") });
  const details = summary.locator("..");
  if (!(await details.evaluate((element) => element.open))) await summary.click();
}
