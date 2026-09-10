import assert from "node:assert/strict";
import test from "node:test";

import {
  WORKBENCH_V2_RPC_METHODS,
  createWorkbenchV2RpcActions,
  createWorkbenchV2View,
  normalizeWorkbenchV2State,
  normalizeScheduleRule,
  resolveClientView,
} from "../src/workbench-v2-view.js";

const escapeHtml = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

test("默认进入工作台，只有 companion 查询进入紧凑场景", () => {
  assert.equal(resolveClientView(""), "workspace");
  assert.equal(resolveClientView("?view=workspace"), "workspace");
  assert.equal(resolveClientView("?foo=1&view=companion"), "companion");
  assert.equal(resolveClientView("?view=companion-extra"), "workspace");
});

test("宿主投影别名归一到稳定字段", () => {
  const normalized = normalizeWorkbenchV2State({
    capabilities: { active_category: "life", libraryOpen: true },
    settings: { memoryOpen: true },
  });
  assert.equal(normalized.capabilities.activeCategory, "life");
  assert.equal(normalized.capabilities.libraryOpen, true);
  assert.equal(normalized.settings.memory.open, true);
});

test("日程规则使用后端原生时区与 weekdays 契约", () => {
  assert.deepEqual(normalizeScheduleRule({ kind: "once", at: "2026-09-10T09:30" }), { kind: "once", timezone: "Asia/Shanghai", at: "2026-09-10T09:30:00+08:00" });
  assert.deepEqual(normalizeScheduleRule({ kind: "daily", time: "09:30" }), { kind: "daily", timezone: "Asia/Shanghai", time: "09:30" });
  assert.deepEqual(normalizeScheduleRule({ kind: "weekly", time: "18:00", weekdays: [0, 4, 4] }), { kind: "weekly", timezone: "Asia/Shanghai", time: "18:00", weekdays: [0, 4] });
  assert.throws(() => normalizeScheduleRule({ kind: "weekly", time: "18:00", weekdays: [] }), /weekdays/);
});

test("RPC 适配器发送统一工作契约，不在确认前提交", async () => {
  const calls = [];
  const resumed = [];
  const actions = createWorkbenchV2RpcActions({
    rpc: async (method, params) => {
      calls.push({ method, params });
      return { request_id: params.request_id, status: "preflight" };
    },
    context: () => ({ assistant_id: "assistant-1", session_id: "session-2" }),
    createRequestId: () => "request-3",
    resumeRoleChat: async (chat, confirmation) => resumed.push({ chat, confirmation }),
  });

  await actions.onTaskPreflight({ goal: "整理发布说明", project_id: "project-4" });
  await actions.onAuthorizationConfirm({ request_id: "request-3", revision: 2, max_cny: "8.50" });
  await actions.onTaskSubmit({ request_id: "request-3" });
  await actions.onTaskList();
  await actions.onTaskGet({ request_id: "request-3" });
  await actions.onTaskCancel({ request_id: "request-3" });
  await actions.onProjectCreate({ name: "文档", category: "工作" });
  await actions.onConversationPage({ session_id: "session-2", cursor: "cursor-1", limit_rounds: 10 });
  await actions.onConversationUpdate({ assistant_id: "assistant-1", session_id: "session-2", changes: { pinned: true } });
  await actions.onRoleAuthorizationConfirm({ request_id: "role-request", revision: 1, max_cny: "1.50", chat: { session_id: "session-2", message: "继续刚才的话" } });

  assert.deepEqual(calls, [
    { method: WORKBENCH_V2_RPC_METHODS.taskPreflight, params: { request_id: "request-3", assistant_id: "assistant-1", session_id: "session-2", goal: "整理发布说明", project_id: "project-4" } },
    { method: WORKBENCH_V2_RPC_METHODS.authorizationConfirm, params: { request_id: "request-3", assistant_id: "assistant-1", revision: 2, max_cny: "8.50" } },
    { method: WORKBENCH_V2_RPC_METHODS.taskSubmit, params: { request_id: "request-3", assistant_id: "assistant-1" } },
    { method: WORKBENCH_V2_RPC_METHODS.taskList, params: { assistant_id: "assistant-1" } },
    { method: WORKBENCH_V2_RPC_METHODS.taskGet, params: { request_id: "request-3", assistant_id: "assistant-1" } },
    { method: WORKBENCH_V2_RPC_METHODS.taskCancel, params: { request_id: "request-3", assistant_id: "assistant-1" } },
    { method: WORKBENCH_V2_RPC_METHODS.projectCreate, params: { name: "文档", category: "工作" } },
    { method: WORKBENCH_V2_RPC_METHODS.conversationPage, params: { session_id: "session-2", cursor: "cursor-1", limit_rounds: 10 } },
    { method: WORKBENCH_V2_RPC_METHODS.conversationUpdate, params: { assistant_id: "assistant-1", session_id: "session-2", changes: { pinned: true } } },
    { method: WORKBENCH_V2_RPC_METHODS.authorizationConfirm, params: { request_id: "role-request", assistant_id: "assistant-1", revision: 1, max_cny: "1.50" } },
  ]);
  assert.deepEqual(resumed, [{ chat: { session_id: "session-2", message: "继续刚才的话" }, confirmation: { request_id: "role-request", status: "preflight" } }]);
  assert.throws(() => actions.onTaskSubmit({ request_id: "role-request", source: "role" }), /chat\.send/);
});

test("付费角色确认继续相同 chat.send，不显示 Provider 故障或工作提交", () => {
  const html = createWorkbenchV2View({
    state: {
      assistant: { id: "assistant-1" },
      workbench: {
        selectedTask: {
          status: "awaiting-confirmation",
          work_request: {
            request_id: "role-request",
            assistant_id: "assistant-1",
            revision: 1,
            status: "awaiting-confirmation",
            request: { source: "role", session_id: "session-1", goal: "陪我聊聊今天的事" },
            quote: { low_cny: "0.10", typical_cny: "0.20", high_cny: "0.50" },
            error: "Provider quota exhausted",
          },
        },
        conversation: { session_id: "session-1" },
      },
    },
    escapeHtml,
  }).render();

  assert.match(html, /免费角色资源不足/);
  assert.match(html, /确认后继续聊天/);
  assert.match(html, /授权后继续本条消息/);
  assert.match(html, /data-request-source="role"/);
  assert.doesNotMatch(html, /Provider quota exhausted/);
  assert.doesNotMatch(html, /data-task-submit/);
});

test("工作台只暴露四个主导航，旧入口进入高级区", () => {
  const html = createWorkbenchV2View({
    state: { view: "workspace" },
    slots: {
      tasks: () => "<div>legacy tasks</div>",
      agent: () => "<div>legacy agent</div>",
      web: () => "<div>legacy web</div>",
      history: () => "<div>legacy history</div>",
    },
    escapeHtml,
  }).render();

  assert.equal((html.match(/data-wv2-view=/g) || []).length, 5);
  assert.match(html, /data-wv2-view="workspace"/);
  assert.match(html, /data-wv2-view="capabilities"/);
  assert.match(html, /data-wv2-view="characters"/);
  assert.match(html, /data-wv2-view="settings"/);
  assert.match(html, /data-wv2-open-residence/);
  assert.match(html, /<summary>高级工作区<\/summary>/);
  assert.match(html, /legacy tasks/);
  assert.doesNotMatch(html, /data-wv2-view="agent"/);
});

test("父任务确认展示子步骤目标与共享预算，内容不能注入页面", () => {
  const html = createWorkbenchV2View({ state: { workbench: { selectedTask: {
    request_id: "parent", status: "awaiting-confirmation", revision: 1,
    external: { limit_enforced: true }, quote: { high_cny: "6" },
    external_steps: [{ id: "one", purpose: "核验资料", method: "agent.session.prompt", candidate_id: "fixture:bounded",
      high_cny: "2", params: { text: "<script>unsafe()</script>", sessionId: "child", core_session_id: "parent-context" } }],
  } } }, escapeHtml }).render();
  assert.match(html, /本次授权包含的子步骤/);
  assert.match(html, /共用总预算/);
  assert.match(html, /核验资料/);
  assert.match(html, /fixture:bounded/);
  assert.match(html, /2 CNY/);
  assert.match(html, /parent-context/);
  assert.match(html, /&lt;script&gt;unsafe\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test("历史按宿主轮次显示，加载固定十轮且清屏不表示删除", () => {
  const html = createWorkbenchV2View({
    state: {
      assistant: { id: "assistant-1", name: "Sumika" },
      workbench: {
        conversation: {
          session_id: "session-1",
          has_more: true,
          cleared: true,
          rounds: [
            { id: "round-1", messages: [{ id: "m1", role: "user", content: "第一问" }, { id: "m2", role: "assistant", content: "第一答" }] },
            { id: "round-2", messages: [{ id: "m3", role: "user", content: "第二问" }, { id: "m4", role: "tool", kind: "tool", label: "读取", content: "工具记录" }, { id: "m5", role: "assistant", content: "第二答" }] },
            { id: "round-3", messages: [{ id: "m6", role: "user", content: "第三问" }] },
          ],
        },
      },
    },
    escapeHtml,
  }).render();

  assert.equal((html.match(/class="wv2-round"/g) || []).length, 3);
  assert.match(html, /加载之前 10 轮/);
  assert.match(html, /记录仍由宿主保留/);
  assert.match(html, /<summary>读取<\/summary>/);
  assert.doesNotMatch(html, /删除历史/);
});

test("对话菜单投影 purpose、置顶和归档事件入口", () => {
  const html = createWorkbenchV2View({ state: { assistant: { id: "assistant-1" }, workbench: { conversations: [{ id: "session-1", title: "发布", purpose: "work", pinned: true, archived: false }] } }, escapeHtml }).render();
  assert.match(html, /⌖ 发布/);
  assert.match(html, />work</);
  assert.match(html, /data-conversation-pin="session-1" data-pinned="true"/);
  assert.match(html, /data-conversation-archive="session-1"/);
});

test("预算、干净成果和角色附言使用独立区域", () => {
  const html = createWorkbenchV2View({
    state: {
      assistant: { id: "assistant-1" },
      workbench: {
        selectedTask: {
          request_id: "request-1",
          assistant_id: "assistant-1",
          revision: 3,
          status: "awaiting-confirmation",
          goal: "生成说明",
          classification: { complexity: "complex", reason: "涉及多个交付物" },
          quote: { low_cny: "1.00", typical_cny: "3.00", high_cny: "6.00" },
          artifacts: [{ id: "artifact-1", name: "正文", content: "只复制这一段", verified: true }],
          commentary: { content: "附言不能进入正文" },
        },
        conversation: {},
      },
    },
    escapeHtml,
  }).render();

  assert.match(html, /等待预算确认/);
  assert.match(html, /¥1\.00 \/ ¥3\.00 \/ ¥6\.00/);
  assert.match(html, /value="6\.00"/);
  assert.match(html, /data-artifact-copy="artifact-1"/);
  assert.match(html, /<pre>只复制这一段<\/pre>/);
  assert.match(html, /class="wv2-commentary"/);
  assert.doesNotMatch(html, /<pre>[^<]*附言不能进入正文/);
  assert.doesNotMatch(html, /data-task-submit/);
});

test("能力添加与整理分离，添加入口不包含启用或授权动作", () => {
  const base = {
    view: "capabilities",
    capabilities: {
      status: "ready",
      active_category: "perception",
      added_ids: ["asr"],
      modules: [
        { id: "asr", name: "语音识别", category: "perception", enabled: false, configured: false, registered: true },
        { id: "camera", name: "摄像头", category: "perception", enabled: false, registered: true },
      ],
    },
  };
  const normal = createWorkbenchV2View({ state: base, escapeHtml }).render();
  const organizing = createWorkbenchV2View({ state: { ...base, capabilities: { ...base.capabilities, organize: true, libraryOpen: true } }, escapeHtml }).render();

  assert.match(normal, /感知与交互/);
  assert.match(normal, /效率工具/);
  assert.match(normal, /生活与陪伴/);
  assert.match(normal, /data-capability-library-open/);
  assert.doesNotMatch(normal, /data-capability-remove/);
  assert.match(organizing, /data-capability-remove="asr"/);
  assert.match(organizing, /data-capability-add="camera"/);
  assert.doesNotMatch(organizing, /data-capability-enable/);
  assert.doesNotMatch(organizing, /添加只改变页面布局/);
});

test("固定候选失效时仍保留在下拉框并解释，不静默替换", () => {
  const html = createWorkbenchV2View({
    state: {
      view: "settings",
      settings: {
        bindings: {
          work: {
            mode: "fixed",
            candidate_id: "leader-old",
            candidate_name: "旧主模型",
            invalid_reason: "价格证据已过期",
            candidates: [{ id: "leader-new", name: "新候选", available: true, provider: "provider-a", reasoning_effort: "high" }],
          },
          role: { mode: "auto", candidates: [] },
        },
        budget: { preference: "quality-first", max_cny: "20.000001" },
        memoryOpen: true,
      },
    },
    escapeHtml,
  }).render();

  assert.match(html, /<option value="leader-old" selected[^>]*>旧主模型 · 不可用：价格证据已过期<\/option>/);
  assert.match(html, /保留当前固定项，不会静默切换/);
  assert.match(html, /value="20\.000001"/);
  assert.match(html, /step="any"/);
  assert.doesNotMatch(html, /value="balanced"/);
  assert.match(html, /管理记忆/);
  assert.match(html, /<summary data-workbench-page="Developer">高级诊断<\/summary>/);
});

test("日程 RPC 保留宿主草稿和明确的免费授权", async () => {
  const calls = [];
  const actions = createWorkbenchV2RpcActions({
    rpc: async (method, params) => calls.push({ method, params }),
    context: { assistant_id: "assistant-1", session_id: "session-1" },
  });
  const draft = { title: "晨间检查", payload: { goal: "检查今天任务" }, rule: { kind: "daily", timezone: "Asia/Shanghai", time: "09:00" }, authorization: { scope_confirmed: true, paid: false } };
  await actions.onScheduleList();
  await actions.onScheduleCreate({ draft });
  await actions.onSchedulePause({ assistant_id: "assistant-1", schedule_id: "schedule-1" });
  await actions.onScheduleRun({ assistant_id: "assistant-1", schedule_id: "schedule-1" });
  await actions.onScheduleHistory({ assistant_id: "assistant-1", schedule_id: "schedule-1" });
  assert.deepEqual(calls, [
    { method: "schedule.list", params: { assistant_id: "assistant-1" } },
    { method: "schedule.create", params: { assistant_id: "assistant-1", draft } },
    { method: "schedule.pause", params: { assistant_id: "assistant-1", schedule_id: "schedule-1" } },
    { method: "schedule.run", params: { assistant_id: "assistant-1", schedule_id: "schedule-1" } },
    { method: "schedule.history", params: { assistant_id: "assistant-1", schedule_id: "schedule-1" } },
  ]);
});

test("任务列表和日程详情使用可选择投影", () => {
  const html = createWorkbenchV2View({ state: { assistant: { id: "assistant-1" }, workbench: {
    tasks: [{ request_id: "request-1", goal: "检查发布", status: "executing" }],
    selectedSchedule: { id: "schedule-1", title: "周检", status: "paused", rule: { kind: "weekly", weekdays: [0, 4], time: "18:00" } },
    scheduleHistory: { runs: [{ scheduled_at: "2026-09-09T18:00:00+08:00", status: "completed" }] },
  } }, escapeHtml }).render();
  assert.match(html, /data-task-get="request-1"/);
  assert.match(html, /data-selected-schedule="schedule-1"/);
  assert.match(html, /每周 0、4 · 18:00/);
  assert.match(html, /data-schedule-history="schedule-1"/);
  assert.match(html, /2026-09-09T18:00:00\+08:00/);
});

test("空状态和未连接插槽明确说明不可用，不生成示例项目或成果", () => {
  const workspace = createWorkbenchV2View({ state: {}, escapeHtml }).render();
  const companion = createWorkbenchV2View({ state: { view: "companion" }, escapeHtml }).render();

  assert.match(workspace, /暂无项目/);
  assert.match(workspace, /暂无对话/);
  assert.match(workspace, /当前显示没有对话/);
  assert.doesNotMatch(workspace, /示例项目|示例成果|demo/i);
  assert.match(companion, /居所场景不可用/);
  assert.match(companion, /聊一句/);
});
