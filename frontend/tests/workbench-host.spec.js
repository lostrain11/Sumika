import { expect, test } from "@playwright/test";
import { openPage } from "./helpers/navigation.js";
import { baseUrl, installWorkbenchFixture, quotedRequest, confirmFixture } from "./helpers/workbench-fixture.js";

test("内置Skill默认关闭、独立启停，设置页不执行路径检查", async ({ page, context }) => {
  const fixture = await installWorkbenchFixture(context);
  const rows = ["project-progress", "troubleshooting-notes", "tool-registry"].map(id => ({ id, title: id, description: "隔离Skill fixture", publisher: "Sumika", enabled: false, sha256: "fixture-digest", runtime_status: "API开发按需加载" }));
  fixture.handlers["skill.builtin.list"] = () => ({ skills: rows });
  fixture.handlers["skill.builtin.set"] = params => {
    expect(params.assistant_id).toBe("sumika");
    const row = rows.find(item => item.id === params.skill_id);
    expect(params.sha256).toBe(row.sha256);
    row.enabled = params.enabled;
    if (params.skill_id === "tool-registry") row.config_path = "isolated-fixture/config/paths.json";
    return { skills: rows };
  };
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator('[data-wv2-view="settings"]').click();
  const skills = page.locator("[data-builtin-skills]");
  await expect(skills.locator("input[type=checkbox]")).toHaveCount(3);
  const tool = skills.locator('[data-builtin-skill="tool-registry"]');
  const progress = skills.locator('[data-builtin-skill="project-progress"]');
  await expect(tool).not.toBeChecked();
  await expect(progress).not.toBeChecked();
  const settingResponse = page.waitForResponse(response => response.url().endsWith("/rpc") && response.request().postDataJSON()?.method === "skill.builtin.set");
  await tool.check();
  expect(await (await settingResponse).json()).not.toHaveProperty("error");
  await expect(tool).toBeEnabled();
  await expect(tool).toBeChecked();
  await expect(progress).not.toBeChecked();
  await expect(skills).toContainText("paths.json");
  await progress.check();
  await expect(progress).toBeEnabled();
  await tool.uncheck();
  await expect(tool).toBeEnabled();
  await expect(progress).toBeChecked();
  await progress.uncheck();
  await expect(progress).toBeEnabled();
  expect(fixture.calls.filter(call => /helper|preflight|submit/.test(call.method))).toHaveLength(0);
  expect(fixture.calls.filter(call => call.method === "skill.builtin.set")).toHaveLength(4);
  await expect(skills.locator('input[type="text"]')).toHaveCount(0);
});

test("开发入口保留项目目录、测试范围和独立diff，确认前不派发", async ({ page, context }) => {
  const fixture = await installWorkbenchFixture(context);
  let project;
  fixture.handlers["project.create"] = params => (project = { ...params, id: "development-project", conversations: [] });
  fixture.handlers["project.list"] = () => ({ projects: project ? [project] : [] });
  fixture.handlers["work.task.preflight"] = params => {
    expect(params.project_id).toBe("development-project");
    expect(params.development).toEqual({ test_commands: [["python", "test_answer.py"]] });
    return (fixture.request = { ...quotedRequest(params), development: { directory: project.directory, ...params.development, max_calls: 20 } });
  };
  confirmFixture(fixture);
  fixture.handlers["work.task.submit"] = () => (fixture.request = { ...fixture.request, status: "completed",
    development_workspace: { path: "D:/isolated/development-fixture", files: ["answer.py"], skipped: [] },
    development_diff: { patch: "-answer = 1\n+answer = 2" }, development_events: [{ name: "run_test", result: { exit_code: 0 } }] });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByText("＋ 新建项目", { exact: true }).click();
  await page.locator('[data-project-create] [name="name"]').fill("开发 fixture");
  await page.locator('[data-project-create] [name="directory"]').fill("D:/source-fixture");
  await page.locator('[data-project-create] button').click();
  await expect(page.locator(".wv2-project-row.active")).toContainText("开发 fixture");
  await page.locator('[data-task-preflight] [name="goal"]').fill("修复answer");
  await page.getByText("工作方式与测试", { exact: true }).click();
  await page.locator('[name="development_mode"]').selectOption("development");
  await page.locator('[name="test_commands"]').fill('["python", "test_answer.py"]');
  await page.locator('[data-task-preflight] button[type="submit"]').click();
  await expect(page.locator(".wv2-development")).toContainText("D:/source-fixture");
  await expect(page.locator(".wv2-development")).toContainText("不构成操作系统沙箱");
  expect(fixture.calls.filter(call => call.method === "work.task.submit")).toHaveLength(0);
  await page.locator(".wv2-budget-confirm button").click();
  await page.getByText("审查文件差异", { exact: true }).click();
  await expect(page.locator(".wv2-diff")).toContainText("+answer = 2");
  expect(fixture.calls.filter(call => call.method === "work.task.submit")).toHaveLength(1);
});

test("真实宿主：项目到版本化预算确认再到干净成果", async ({ page, context }) => {
  const fixture = await installWorkbenchFixture(context);
  const content = "# 验收成果\n只包含用户要求的正文";
  fixture.handlers["work.task.preflight"] = params => (fixture.request = quotedRequest(params));
  confirmFixture(fixture);
  fixture.handlers["work.task.submit"] = params => {
    expect(fixture.request.authorization).toEqual({ revision: 7, max_cny: "2" });
    expect(params.request_id).toBe(fixture.request.request_id);
    fixture.request = { ...fixture.request, status: "completed", artifacts: [{ id: "clean-artifact", title: "干净正文", content, verified: true }], commentary: { content: "角色附言独立保存" } };
    return fixture.request;
  };
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await expect(page.locator(".wv2-topbar")).toBeVisible();
  expect(fixture.calls.filter(call => call.method === "work.task.preflight" || call.method === "fixture.chat")).toEqual([]);
  await page.getByText("＋ 新建项目", { exact: true }).click();
  await page.locator('[data-project-create] [name="name"]').fill("E2E 隔离项目");
  await page.locator('[data-project-create] [name="category"]').fill("programming");
  await page.locator("[data-project-create] button").click();
  await expect(page.locator(".wv2-project-row.active")).toContainText("E2E 隔离项目");
  const projectId = await page.locator(".wv2-project-row.active [data-project-select]").getAttribute("data-project-select");
  await page.locator("[data-conversation-create]").click();
  await expect.poll(() => fixture.calls.filter(call => call.method === "conversation.attach").length).toBe(1);
  const attachment = fixture.calls.find(call => call.method === "conversation.attach").params;
  expect(attachment).toEqual(expect.objectContaining({ project_id: projectId, source: "core", assistant_id: "sumika" }));
  await page.locator('[data-task-preflight] [name="goal"]').fill("整理项目验收报告");
  await page.locator("[data-task-preflight] button").click();
  await expect(page.locator(".wv2-budget-confirm")).toBeVisible();
  expect(fixture.request.request.project_id).toBe(projectId);
  expect(fixture.request.request.session_id).toBe(attachment.source_id);
  expect(fixture.calls.filter(call => call.method === "work.task.submit")).toEqual([]);
  await page.locator(".wv2-budget-confirm button").click();
  await expect(page.locator(".wv2-artifacts pre")).toHaveText(content);
  await expect(page.locator(".wv2-commentary")).toContainText("角色附言独立保存");
  await expect(page.locator(".wv2-artifacts")).not.toContainText("角色附言独立保存");
  await page.locator("[data-artifact-copy]").click();
  await expect.poll(() => page.evaluate(async () => (await navigator.clipboard.readText()).replace(/\r\n/g, "\n"))).toBe(content);
});

test("真实宿主：最近三轮、加载历史及清屏不删除记录", async ({ page, context }) => {
  const fixture = await installWorkbenchFixture(context);
  const rounds = Array.from({ length: 13 }, (_, index) => ({ id: "round-" + index, messages: [{ id: "message-" + index, role: "user", content: "历史轮次 " + index }] }));
  fixture.handlers["conversation.page"] = params => {
    if (params.before) { expect(params.before).toBe("older-cursor"); expect(params.limit).toBe(10); return { turns: rounds.slice(0, 10), has_more: false, next_before: null }; }
    return params.limit === 10 ? { turns: rounds.slice(3), has_more: true, next_before: "older-cursor" } : { turns: rounds.slice(-3), has_more: true, next_before: "older-cursor" };
  };
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await expect(page.locator(".wv2-round")).toHaveCount(3);
  await expect(page.locator(".wv2-round").first()).toContainText("历史轮次 10");
  await page.locator("[data-conversation-page]").click();
  await expect(page.locator(".wv2-round")).toHaveCount(13);
  await expect(page.locator(".wv2-round").first()).toContainText("历史轮次 0");
  await expect(page.locator(".wv2-round").last()).toContainText("历史轮次 12");
  const beforeClear = fixture.calls.length;
  await page.locator("[data-clear-display]").click();
  await expect(page.locator(".wv2-round")).toHaveCount(0);
  expect(fixture.calls.slice(beforeClear).filter(call => /delete|clear/.test(call.method))).toEqual([]);
  await page.locator("[data-conversation-page]").click();
  await expect(page.locator(".wv2-round")).toHaveCount(10);
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.locator(".wv2-round")).toHaveCount(3);
  expect(rounds).toHaveLength(13);
});

test("真实宿主：主模型和角色分别自动手动，固定失效不换模", async ({ page, context }) => {
  const fixture = await installWorkbenchFixture(context);
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await openPage(page, "Settings");
  for (const [role, purpose, candidate] of [["work", "leader", "paid-leader"], ["role", "role", "free-role"]]) {
    const form = page.locator('[data-model-binding="' + role + '"]');
    await expect(form.locator('[value="auto"]')).toBeChecked();
    await form.getByText("固定", { exact: true }).click();
    await form.locator("select").selectOption(candidate);
    await form.locator('button[type="submit"]').click();
    await expect.poll(() => fixture.settings[purpose + "_candidate_id"]).toBe(candidate);
    await form.getByText("自动", { exact: true }).click();
    await form.locator('button[type="submit"]').click();
    await expect.poll(() => fixture.settings.selection_mode[purpose]).toBe("auto");
    expect(fixture.settings[purpose + "_candidate_id"]).toBe(candidate);
    await form.getByText("固定", { exact: true }).click();
    await expect(form.locator("select")).toHaveValue(candidate);
    await form.locator('button[type="submit"]').click();
  }
  fixture.candidates.find(row => row.candidate_id === "paid-leader").available = false;
  await page.reload({ waitUntil: "networkidle" });
  await openPage(page, "Settings");
  await expect(page.locator('[data-model-binding="work"] select')).toHaveValue("paid-leader");
  await expect(page.locator('[data-model-binding="work"] .wv2-warning')).toContainText("不会静默切换");
  expect(fixture.calls.filter(call => ["fixture.chat", "work.task.preflight", "work.authorization.confirm", "work.task.submit"].includes(call.method))).toEqual([]);
});

test("真实宿主：付费角色确认只恢复原消息，不提交工作任务", async ({ page, context }) => {
  const fixture = await installWorkbenchFixture(context);
  let replies = 0;
  fixture.handlers.chat = params => {
    if (!fixture.request?.authorization) {
      fixture.request = quotedRequest({ request_id: "paid-role", assistant_id: "sumika", session_id: params.session_id, goal: params.messages[0].content }, "role");
      return { accepted: false, status: "awaiting-confirmation", work_request: fixture.request };
    }
    replies++;
    expect(params.session_id).toBe(fixture.request.request.session_id);
    expect(params.messages).toEqual([{ role: "user", content: "本次付费角色交流" }]);
    fixture.request = { ...fixture.request, status: "completed" };
    return { message: { role: "assistant", content: "隔离角色回复" } };
  };
  confirmFixture(fixture);
  await page.goto(baseUrl + "?view=companion", { waitUntil: "networkidle" });
  await page.locator("[data-pet-chat]").focus();
  await page.locator("[data-pet-chat]").click();
  await page.locator("#chat-input").fill("本次付费角色交流");
  const opened = page.waitForEvent("popup");
  await page.locator("#chat-form button").click();
  const main = await opened;
  await main.waitForLoadState("networkidle");
  await expect(main.locator(".wv2-role-confirmation")).toBeVisible();
  expect(replies).toBe(0);
  expect(fixture.calls.filter(call => call.method === "work.authorization.confirm")).toEqual([]);
  await main.locator(".wv2-budget-confirm button").click();
  await expect.poll(() => replies).toBe(1);
  expect(fixture.calls.filter(call => call.method === "work.task.submit")).toEqual([]);
  expect(fixture.calls.filter(call => call.method === "fixture.chat")).toHaveLength(2);
});

for (const source of ["agent", "web"]) {
  for (const enforced of [true, false]) {
    test("真实宿主：" + source + (enforced ? " 按版本确认后恢复原入口" : " 未知费用不能伪造上限"), async ({ page, context }) => {
      const fixture = await installWorkbenchFixture(context);
      const dispatched = [];
      let executions = 0;
      const method = source === "agent" ? "agent.session.prompt" : "sumika.route.dispatch";
      fixture.handlers[method] = params => {
        dispatched.push(structuredClone(params));
        if (!fixture.request) fixture.request = quotedRequest(params, source, enforced);
        if (!fixture.request.authorization) return { accepted: false, status: "awaiting-confirmation", work_request: fixture.request, work_request_id: fixture.request.request_id };
        executions++;
        fixture.request = { ...fixture.request, status: "executing", reserved_cny: "2" };
        return { accepted: true, id: "fixture-turn", dispatch_id: "fixture-dispatch", status: "completed", work_request: fixture.request };
      };
      confirmFixture(fixture);
      fixture.handlers["work.task.cancel"] = () => (fixture.request = { ...fixture.request, status: "cancel-requested" });
      fixture.handlers[source === "agent" ? "agent.session.cancel" : "sumika.route.cancel"] = () => ({ accepted: true });
      if (source === "agent") {
        await context.route("**/api/agent/status", route => route.fulfill({ json: { state: "ready", ready: true, runtime_id: "fixture", runtime_capabilities: ["commands", "plan"] } }));
        await context.route("**/api/agent/provider", route => route.fulfill({ json: { state: "ready", ready: true, profile_id: "host-fixture", model: "offline-fixture" } }));
        fixture.handlers["agent.session.create"] = () => ({ id: "fixture-session" });
        fixture.handlers["agent.sessions"] = () => ({ sessions: [] });
        fixture.handlers["agent.commands"] = () => ({ available: true, entries: [{ name: "plan" }] });
        fixture.handlers["agent.session.snapshot"] = () => ({ session_id: "fixture-session", state: "idle", messages: [], tools: [], approvals: [], artifacts: [], timeline: [], stats: {}, plan: { active: false, steps: [] } });
      } else {
        fixture.handlers["sumika.route.catalog"] = () => ({ routes: [{ route_id: "web:offline", worker_kind: "web", label: "隔离网页", routable: true, status: "ready", occupancy: "idle" }] });
        fixture.handlers["sumika.route.pending"] = () => ({ results: [] });
        fixture.handlers["sumika.consultation.status"] = () => ({ consultations: [] });
      }
      await page.goto(baseUrl, { waitUntil: "networkidle" });
      await openPage(page, source === "agent" ? "Agent" : "WebWorkbench");
      if (source === "agent") {
        await page.locator("#agent-prompt").fill("隔离原来源请求");
        await page.locator("#agent-send").click();
      } else {
        await page.locator('#web-workbench-worker-form [name="route_id"]').selectOption("web:offline");
        await page.locator('#web-workbench-worker-form [name="question"]').fill("隔离原来源请求");
        await page.locator('#web-workbench-worker-form button[type="submit"]').click();
      }
      await expect(page.locator(".wv2-budget-confirm")).toBeVisible();
      expect(executions).toBe(0);
      expect(dispatched).toHaveLength(1);
      expect(dispatched[0].client_request_id).toMatch(/^[0-9a-f-]{36}$/);
      expect(dispatched[0].core_session_id).toBeTruthy();
      if (enforced) {
        await page.locator(".wv2-budget-confirm button").click();
        await expect.poll(() => executions).toBe(1);
        expect(dispatched).toHaveLength(2);
        expect(dispatched[1]).toEqual(dispatched[0]);
        await page.locator("[data-task-cancel]").click();
        await expect.poll(() => fixture.calls.filter(call => call.method === "work.task.cancel").length).toBe(1);
        expect(fixture.calls.filter(call => call.method === (source === "agent" ? "agent.session.cancel" : "sumika.route.cancel"))).toEqual([]);
        expect(fixture.request.status).toBe("cancel-requested");
        expect(fixture.request.reserved_cny).toBe("2");
      } else {
        await expect(page.locator(".wv2-task")).toContainText(/硬上限|费用未知/);
        await page.locator('.wv2-budget-confirm [name="max_cny"]').fill("2");
        await expect(page.locator(".wv2-budget-confirm button")).toBeDisabled();
        expect(fixture.calls.filter(call => call.method === "work.authorization.confirm")).toEqual([]);
      }
      expect(fixture.calls.filter(call => call.method === "work.task.submit")).toEqual([]);
    });
  }
}
