const NAV_ITEMS = Object.freeze([
  Object.freeze(["workspace", "工作台"]),
  Object.freeze(["capabilities", "能力"]),
  Object.freeze(["characters", "角色"]),
  Object.freeze(["settings", "设置"]),
]);

const CAPABILITY_CATEGORIES = Object.freeze([
  Object.freeze(["perception", "感知与交互"]),
  Object.freeze(["productivity", "效率工具"]),
  Object.freeze(["life", "生活与陪伴"]),
]);

export const WORKBENCH_V2_ACTIONS = Object.freeze([
  "onNavigate",
  "onOpenResidence",
  "onProjectCreate",
  "onProjectList",
  "onProjectSelect",
  "onProjectUpdate",
  "onProjectGet",
  "onProjectArchive",
  "onConversationCreate",
  "onConversationSelect",
  "onConversationSearch",
  "onConversationUpdate",
  "onScheduleSelect",
  "onScheduleList",
  "onScheduleCreate",
  "onSchedulePause",
  "onScheduleRun",
  "onScheduleHistory",
  "onConversationPage",
  "onClearConversationDisplay",
  "onTaskPreflight",
  "onTaskSubmit",
  "onTaskGet",
  "onTaskList",
  "onTaskCancel",
  "onAuthorizationConfirm",
  "onRoleAuthorizationConfirm",
  "onArtifactCopy",
  "onInspectorChange",
  "onCapabilityCategoryChange",
  "onCapabilityLibraryChange",
  "onCapabilityOrganizeChange",
  "onCapabilityLayoutChange",
  "onCapabilityConfigure",
  "onModelBindingSave",
  "onBuiltinSkillToggle",
  "onBudgetSettingsSave",
  "onOpenMemory",
  "onCompanionComposerToggle",
  "onCompanionSend",
  "onDraftChange",
  "onError",
]);

export const WORKBENCH_V2_RPC_METHODS = Object.freeze({
  taskPreflight: "work.task.preflight",
  taskSubmit: "work.task.submit",
  authorizationConfirm: "work.authorization.confirm",
  taskList: "work.task.list",
  taskGet: "work.task.get",
  taskCancel: "work.task.cancel",
  projectList: "project.list",
  projectCreate: "project.create",
  projectUpdate: "project.update",
  projectGet: "project.get",
  projectArchive: "project.archive",
  conversationPage: "conversation.page",
  conversationUpdate: "conversation.update",
  scheduleList: "schedule.list",
  scheduleCreate: "schedule.create",
  schedulePause: "schedule.pause",
  scheduleRun: "schedule.run",
  scheduleHistory: "schedule.history",
});

const fallbackEscapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
})[character]);

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const asArray = (value) => Array.isArray(value) ? value : [];
const asText = (value, fallback = "") => value === undefined || value === null || value === "" ? fallback : String(value);
const validView = (value) => NAV_ITEMS.some(([id]) => id === value) ? value : "workspace";

function contextValue(context, key) {
  const value = typeof context === "function" ? context() : context;
  return value?.[key];
}

function requireText(value, name) {
  const normalized = asText(value).trim();
  if (!normalized) throw new TypeError(`${name} is required`);
  return normalized;
}

export function resolveClientView(search = "") {
  const query = asText(search).replace(/^\?/, "").split("&");
  const view = query.map((part) => part.split("=")).find(([key]) => decodeURIComponent(key || "") === "view")?.[1];
  return decodeURIComponent(view || "") === "companion" ? "companion" : "workspace";
}

export function normalizeScheduleRule({ kind, timezone = "Asia/Shanghai", at, time, weekdays, weekday } = {}) {
  if (!new Set(["once", "daily", "weekly"]).has(kind)) throw new TypeError("schedule rule kind is invalid");
  if (kind === "once") {
    const local = requireText(at, "once.at");
    const zoned = /(?:Z|[+-]\d{2}:\d{2})$/.test(local) ? local : `${local}${/:\d{2}:\d{2}$/.test(local) ? "" : ":00"}+08:00`;
    return { kind, timezone, at: zoned };
  }
  if (kind === "daily") return { kind, timezone, time: requireText(time, "daily.time") };
  const values = asArray(weekdays).length ? weekdays : [weekday];
  const normalized = [...new Set(values.map(Number).filter((value) => Number.isInteger(value) && value >= 0 && value <= 6))];
  if (!normalized.length) throw new TypeError("weekly.weekdays is required");
  return { kind, timezone, time: requireText(time, "weekly.time"), weekdays: normalized };
}

export function createWorkbenchV2RpcActions({ rpc, context = {}, createRequestId, resumeRoleChat } = {}) {
  if (typeof rpc !== "function") throw new TypeError("rpc is required");
  const call = (method, params = {}) => rpc(method, params);
  const scope = () => ({
    assistant_id: requireText(contextValue(context, "assistant_id"), "assistant_id"),
    session_id: requireText(contextValue(context, "session_id"), "session_id"),
  });
  const requestScope = (payload) => ({
    request_id: requireText(payload?.request_id, "request_id"),
    assistant_id: requireText(payload?.assistant_id || contextValue(context, "assistant_id"), "assistant_id"),
  });
  return {
    onTaskPreflight: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.taskPreflight, {
      request_id: requireText(payload.request_id || createRequestId?.(), "request_id"),
      ...scope(),
      goal: requireText(payload.goal, "goal"),
      project_id: payload.project_id || null,
    }),
    onTaskSubmit: (payload) => {
      if (payload?.source === "role") throw new TypeError("role confirmations must resume chat.send instead of work.task.submit");
      return call(WORKBENCH_V2_RPC_METHODS.taskSubmit, requestScope(payload));
    },
    onAuthorizationConfirm: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.authorizationConfirm, {
      ...requestScope(payload),
      revision: payload.revision,
      max_cny: payload.max_cny,
    }),
    onRoleAuthorizationConfirm: async (payload = {}) => {
      if (typeof resumeRoleChat !== "function") throw new TypeError("resumeRoleChat is required for paid role confirmation");
      const confirmation = await call(WORKBENCH_V2_RPC_METHODS.authorizationConfirm, {
        ...requestScope(payload),
        revision: payload.revision,
        max_cny: payload.max_cny,
      });
      return resumeRoleChat(payload.chat, confirmation);
    },
    onTaskList: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.taskList, {
      assistant_id: requireText(payload.assistant_id || contextValue(context, "assistant_id"), "assistant_id"),
    }),
    onTaskGet: (payload) => call(WORKBENCH_V2_RPC_METHODS.taskGet, requestScope(payload)),
    onTaskCancel: (payload) => call(WORKBENCH_V2_RPC_METHODS.taskCancel, requestScope(payload)),
    onProjectList: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.projectList, payload),
    onProjectCreate: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.projectCreate, payload),
    onProjectUpdate: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.projectUpdate, payload),
    onProjectGet: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.projectGet, payload),
    onProjectArchive: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.projectArchive, payload),
    onConversationPage: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.conversationPage, payload),
    onConversationUpdate: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.conversationUpdate, payload),
    onScheduleList: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.scheduleList, {
      assistant_id: requireText(payload.assistant_id || contextValue(context, "assistant_id"), "assistant_id"),
    }),
    onScheduleCreate: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.scheduleCreate, {
      assistant_id: requireText(payload.assistant_id || contextValue(context, "assistant_id"), "assistant_id"),
      draft: payload.draft,
    }),
    onSchedulePause: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.schedulePause, payload),
    onScheduleRun: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.scheduleRun, payload),
    onScheduleHistory: (payload = {}) => call(WORKBENCH_V2_RPC_METHODS.scheduleHistory, payload),
  };
}

export function normalizeWorkbenchV2State(value) {
  const state = isObject(value) ? value : {};
  const workbench = isObject(state.workbench) ? state.workbench : {};
  const selectedTaskValue = isObject(workbench.selectedTask?.work_request) ? workbench.selectedTask.work_request : workbench.selectedTask;
  const conversation = isObject(workbench.conversation) ? workbench.conversation : {};
  const capabilities = isObject(state.capabilities) ? state.capabilities : {};
  const settings = isObject(state.settings) ? state.settings : {};
  return {
    view: state.view === "companion" ? "companion" : validView(state.view),
    assistant: isObject(state.assistant) ? state.assistant : {},
    workbench: {
      ...workbench,
      projects: asArray(workbench.projects),
      conversations: asArray(workbench.conversations),
      schedules: asArray(workbench.schedules),
      maintenance: asArray(workbench.maintenance),
      tasks: asArray(workbench.tasks),
      selectedTask: isObject(selectedTaskValue) ? selectedTaskValue : null,
      selectedSchedule: isObject(workbench.selectedSchedule) ? workbench.selectedSchedule : null,
      scheduleHistory: asArray(workbench.scheduleHistory?.runs || workbench.scheduleHistory),
      conversation: {
        ...conversation,
        rounds: asArray(conversation.rounds),
      },
      inspector: isObject(workbench.inspector) ? workbench.inspector : {},
    },
    capabilities: {
      ...capabilities,
      modules: asArray(capabilities.modules),
      activeCategory: capabilities.activeCategory || capabilities.active_category || "perception",
    },
    settings: {
      ...settings,
      bindings: isObject(settings.bindings) ? settings.bindings : {},
      budget: isObject(settings.budget) ? settings.budget : {},
      memory: { ...(isObject(settings.memory) ? settings.memory : {}), open: settings.memory?.open ?? settings.memoryOpen === true },
    },
    companion: isObject(state.companion) ? state.companion : {},
    sources: isObject(state.sources) ? state.sources : {},
  };
}

const normalizeState = normalizeWorkbenchV2State;

function statusLabel(status) {
  return ({
    received: "已接收",
    preflight: "预检中",
    "awaiting-clarification": "等待澄清",
    "awaiting-confirmation": "等待预算确认",
    ready: "可执行",
    planning: "规划中",
    executing: "执行中",
    verifying: "验证中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    "cancel-requested": "已请求停止，等待上游确认",
    "submission-unknown": "提交状态未知",
    unavailable: "来源不可用",
  })[status] || asText(status, "状态未知");
}

function safeClass(value) {
  return asText(value, "unknown").replace(/[^a-z0-9_-]/gi, "-");
}

function quoteText(quote) {
  if (!isObject(quote)) return "费用未知";
  const amount = (value) => value === null || value === undefined || value === "" ? "未知" : `¥${value}`;
  return `${amount(quote.low_cny)} / ${amount(quote.typical_cny)} / ${amount(quote.high_cny)}`;
}

function sourceUnavailable(escapeHtml, label, source) {
  const reason = source?.reason || "宿主尚未连接此来源";
  return `<div class="wv2-unavailable" role="status"><strong>${escapeHtml(label)}不可用</strong><span>${escapeHtml(reason)}</span></div>`;
}

export function createWorkbenchV2View({ state = {}, actions = {}, slots = {}, escapeHtml = fallbackEscapeHtml } = {}) {
  const getState = typeof state === "function" ? state : () => state;
  const drafts = new Map();
  const projectTitles = new Map();
  let boundRoot = null;
  let cleanup = () => {};

  const encode = (value) => escapeHtml(asText(value));
  const action = (name, payload, event) => {
    const callback = actions[name];
    if (typeof callback !== "function") return undefined;
    try {
      const result = callback(payload, event);
      if (result && typeof result.catch === "function") result.catch((error) => actions.onError?.(error));
      return result;
    } catch (error) {
      actions.onError?.(error);
      return undefined;
    }
  };
  const trustedSlot = (name, current, fallbackLabel = name) => {
    const renderer = slots[name];
    if (typeof renderer === "function") return asText(renderer(current));
    return sourceUnavailable(escapeHtml, fallbackLabel, current.sources[name]);
  };

  function renderNavigation(current) {
    return `<header class="wv2-topbar"><a class="wv2-brand" href="#" data-wv2-view="workspace" aria-label="Sumika 工作台"><strong>SUMIKA</strong><span>WORKSPACE</span></a><nav class="wv2-primary-nav" aria-label="主导航">${NAV_ITEMS.map(([id, label]) => `<button type="button" data-wv2-view="${id}" class="${current.view === id ? "active" : ""}" aria-current="${current.view === id ? "page" : "false"}">${label}</button>`).join("")}</nav><button class="wv2-residence-button" type="button" data-wv2-open-residence>打开居所</button></header>`;
  }

  function renderProjects(current) {
    const data = current.workbench;
    const filter = asText(data.projectFilter);
    const projects = data.projects.filter((project) => project.archived !== true);
    const archived = data.projects.filter((project) => project.archived === true);
    const projectRows = projects.map((project) => {
      const active = project.id === data.activeProjectId;
      const title = projectTitles.has(project.id) ? projectTitles.get(project.id) : asText(project.name, "未命名项目");
      return `<li class="wv2-project-row ${active ? "active" : ""}"><button type="button" data-project-select="${encode(project.id)}"><strong>${encode(title)}</strong><span>${encode(project.category || "未分类")}</span></button><details><summary aria-label="管理${encode(title)}">•••</summary><form data-project-update="${encode(project.id)}"><label>名称<input name="name" value="${encode(title)}" maxlength="120" required></label><label>分类<input name="category" value="${encode(project.category)}" maxlength="80"></label><label>项目目录<input name="directory" value="${encode(project.directory || "")}" placeholder="绝对路径，可选"></label><label class="wv2-check"><input name="pinned" type="checkbox" ${project.pinned ? "checked" : ""}>置顶</label><div><button type="submit">保存</button><button type="button" data-project-archive="${encode(project.id)}">归档</button></div></form></details></li>`;
    }).join("");
    return `<aside class="wv2-sidebar" aria-label="项目、对话和定时工作"><div class="wv2-sidebar-actions"><button type="button" data-conversation-create>＋ 新建对话</button><details><summary>＋ 新建项目</summary><form data-project-create><label>名称<input name="name" maxlength="120" required></label><label>分类<input name="category" maxlength="80"></label><label>项目目录<input name="directory" placeholder="绝对路径，可选"></label><button type="submit">创建</button></form></details></div><form class="wv2-search" data-conversation-search role="search"><input name="query" type="search" value="${encode(filter)}" placeholder="搜索项目与对话" aria-label="搜索项目与对话"><button type="submit" aria-label="搜索">⌕</button></form><section><h2>项目</h2><ul class="wv2-rail-list">${projectRows || "<li class=\"wv2-empty\">暂无项目</li>"}</ul>${archived.length ? `<details class="wv2-archived"><summary>已归档 ${archived.length}</summary><ul>${archived.map((project) => `<li><button type="button" data-project-select="${encode(project.id)}">${encode(project.name || "未命名项目")}</button></li>`).join("")}</ul></details>` : ""}</section>${renderConversations(current)}${renderTaskList(current)}${renderSchedules(current)}</aside>`;
  }

  function renderConversations(current) {
    const data = current.workbench;
    const rows = data.conversations.map((conversation) => {
      const unavailable = conversation.available === false;
      return `<li class="wv2-conversation-row"><button type="button" data-conversation-select="${encode(conversation.id)}" class="${conversation.id === data.activeConversationId ? "active" : ""}"><strong>${conversation.pinned ? "⌖ " : ""}${encode(conversation.title || "未命名对话")}</strong><span>${unavailable ? `来源不可用 · ${encode(conversation.unavailable_reason || "无法继续")}` : encode(conversation.updated_label || conversation.purpose || conversation.source || "")}</span></button><details><summary aria-label="管理${encode(conversation.title || "对话")}">•••</summary><div><button type="button" data-conversation-pin="${encode(conversation.id)}" data-pinned="${conversation.pinned === true}">${conversation.pinned ? "取消置顶" : "置顶"}</button><button type="button" data-conversation-archive="${encode(conversation.id)}">归档</button></div></details></li>`;
    }).join("");
    return `<section><h2>对话</h2><ul class="wv2-rail-list">${rows || "<li class=\"wv2-empty\">暂无对话</li>"}</ul></section>`;
  }

  function renderTaskList(current) {
    const rows = current.workbench.tasks.map((task) => `<li><button type="button" data-task-get="${encode(task.request_id)}" class="${task.request_id === current.workbench.selectedTask?.request_id ? "active" : ""}"><strong>${encode(task.goal || task.request?.goal || "未命名任务")}</strong><span>${encode(statusLabel(task.status))}</span></button></li>`).join("");
    return `<section><h2>工作任务</h2><ul class="wv2-rail-list">${rows || "<li class=\"wv2-empty\">暂无工作任务</li>"}</ul></section>`;
  }

  function renderSchedules(current) {
    const rows = current.workbench.schedules.map((schedule) => `<li class="wv2-schedule-row"><button type="button" data-schedule-select="${encode(schedule.id)}"><strong>${encode(schedule.title || "未命名定时工作")}</strong><span>${encode(schedule.next_run_label || statusLabel(schedule.status))}</span></button><details><summary aria-label="管理${encode(schedule.title || "定时工作")}">•••</summary><div><button type="button" data-schedule-run="${encode(schedule.id)}">立即运行</button><button type="button" data-schedule-pause="${encode(schedule.id)}">${schedule.status === "paused" ? "恢复" : "暂停"}</button><button type="button" data-schedule-history="${encode(schedule.id)}">运行记录</button></div></details></li>`).join("");
    const maintenance = current.workbench.maintenance.length ? `<details class="wv2-archived"><summary>应用维护 ${current.workbench.maintenance.length}</summary><ul>${current.workbench.maintenance.map((item) => `<li><button type="button" data-schedule-select="${encode(item.id)}">${encode(item.title || item.name || "维护任务")}</button></li>`).join("")}</ul></details>` : "";
    return `<section><h2>定时工作</h2><ul class="wv2-rail-list">${rows || "<li class=\"wv2-empty\">暂无定时工作</li>"}</ul><details class="wv2-schedule-create"><summary>＋ 新建定时工作</summary><form data-schedule-create><label>名称<input name="title" maxlength="120" required></label><label>目标<textarea name="goal" rows="3" required></textarea></label><label>频率<select name="kind"><option value="once">一次</option><option value="daily">每天</option><option value="weekly">每周</option></select></label><label>日期与时间<input name="at" type="datetime-local"></label><label>时间<input name="time" type="time"></label><label>星期<select name="weekday"><option value="1">周一</option><option value="2">周二</option><option value="3">周三</option><option value="4">周四</option><option value="5">周五</option><option value="6">周六</option><option value="0">周日</option></select></label><input name="timezone" type="hidden" value="Asia/Shanghai"><button type="submit">创建仅免费日程</button></form></details>${maintenance}</section>`;
  }

  function renderRounds(current) {
    const conversation = current.workbench.conversation;
    const rows = conversation.rounds.map((round) => `<section class="wv2-round" data-round-id="${encode(round.id)}">${asArray(round.messages).map((message) => {
      if (message.kind === "tool" || message.role === "tool") return `<details class="wv2-tool-record"><summary>${encode(message.label || "工具记录")}</summary><pre>${encode(message.content)}</pre></details>`;
      return `<article class="wv2-message ${safeClass(message.role)}"><span>${message.role === "user" ? "你" : encode(message.author || current.assistant.name || "Sumika")}</span><div>${encode(message.content)}</div></article>`;
    }).join("")}</section>`).join("");
    const cleared = conversation.cleared ? `<div class="wv2-cleared" role="status">当前显示已清空；记录仍由宿主保留，可主动加载恢复。</div>` : "";
    return `${conversation.has_more ? `<button class="wv2-load-history" type="button" data-conversation-page>加载之前 10 轮</button>` : ""}${cleared}${rows || (conversation.status === "loading" ? "<div class=\"wv2-empty\">正在读取最近三轮…</div>" : "<div class=\"wv2-empty\">当前显示没有对话</div>")}`;
  }

  function renderSchedulePanel(current) {
    const schedule = current.workbench.selectedSchedule;
    if (!schedule) return "";
    const rule = schedule.rule || {};
    const ruleLabel = rule.kind === "once" ? rule.at : rule.kind === "daily" ? `每天 ${rule.time || ""}` : rule.kind === "weekly" ? `每周 ${asArray(rule.weekdays).join("、")} · ${rule.time || ""}` : "规则未知";
    const history = current.workbench.scheduleHistory;
    return `<section class="wv2-task wv2-schedule-panel" data-selected-schedule="${encode(schedule.id)}"><header><div><span class="wv2-status">${encode(statusLabel(schedule.status))}</span><h2>${encode(schedule.title || "未命名定时工作")}</h2></div><div><button type="button" data-schedule-run="${encode(schedule.id)}">立即运行</button><button type="button" data-schedule-pause="${encode(schedule.id)}">${schedule.status === "paused" ? "恢复" : "暂停"}</button><button type="button" data-schedule-history="${encode(schedule.id)}">运行记录</button></div></header><p>${encode(ruleLabel)}</p>${history.length ? `<ul class="wv2-schedule-history">${history.map((run) => `<li><strong>${encode(run.started_at || run.scheduled_at || "时间未知")}</strong><span>${encode(statusLabel(run.status))}</span></li>`).join("")}</ul>` : ""}</section>`;
  }

  function renderTask(current) {
    const request = current.workbench.selectedTask;
    if (!isObject(request)) return "";
    const classification = isObject(request.classification) ? request.classification : {};
    const requestDetails = isObject(request.request) ? request.request : {};
    const roleRequest = requestDetails.source === "role" || request.source === "role";
    const artifacts = asArray(request.artifacts);
    const canConfirm = request.status === "awaiting-confirmation" || request.status === "ready" && !request.authorization;
    const canSubmit = request.status === "ready" && !roleRequest && !request.external;
    const confirmationBlocked = request.quote?.high_cny == null || request.external && (request.external.limit_enforced !== true || request.external_resume_available === false);
    const active = ["planning", "executing", "verifying"].includes(request.status);
    const terminal = ["completed", "failed", "cancelled", "submission-unknown"].includes(request.status);
    const goal = request.goal || requestDetails.goal || "工作请求";
    const confirmationCopy = encode(roleRequest ? "授权后继续本条消息，不创建工作任务。" : request.external ? (confirmationBlocked ? request.status_detail || "无法确认可靠费用上限；请检查原来源入口。" : "确认当前版本后，继续原来源请求。") : "确认当前目标、范围和消费上限。");
    const confirmationLabel = roleRequest ? "确认后继续聊天" : "确认预算";
    return `<section class="wv2-task ${roleRequest ? "wv2-role-confirmation" : ""}" data-request-id="${encode(request.request_id)}" data-request-source="${encode(requestDetails.source || request.source || "workbench")}"><header><div><span class="wv2-status wv2-status-${safeClass(request.status)}">${encode(statusLabel(request.status))}</span><h2>${encode(goal)}</h2></div>${!terminal && !roleRequest ? `<button type="button" data-task-cancel="${encode(request.request_id)}">取消</button>` : ""}</header>${roleRequest ? `<div class="wv2-role-notice" role="status">合格免费角色资源当前不足，需要确认本次付费角色预算后继续。</div>` : ""}<div class="wv2-task-summary"><div><span>${roleRequest ? "用途" : "分类"}</span><strong>${roleRequest ? "角色交流" : encode(classification.complexity === "complex" ? "复杂工作" : classification.complexity === "simple" ? "简单工作" : "待判定")}</strong><small>${encode(classification.reason || classification.rationale)}</small></div><div><span>预算（低 / 常见 / 上限）</span><strong>${encode(quoteText(request.quote))}</strong><small>${encode(request.funding?.funding_kind || request.funding_kind || "资金类型未知")}</small></div><div><span>进度</span><strong>${encode(request.progress_label || statusLabel(request.status))}</strong><small>${encode(request.status_detail)}</small></div></div>${renderDevelopment(request)}${renderExternalSteps(request)}${canConfirm ? `<form class="wv2-budget-confirm" data-authorization-confirm data-request-source="${roleRequest ? "role" : "workbench"}"><label>本次消费上限（CNY）<input name="max_cny" type="number" min="0" step="0.01" value="${encode(request.authorization_max_cny ?? request.quote?.high_cny ?? "")}" ${request.quote?.high_cny == null ? "placeholder=\"费用边界未知\"" : ""} required></label><p>${confirmationCopy}</p><button type="submit" ${confirmationBlocked ? "disabled" : ""}>${confirmationLabel}</button></form>` : ""}${canSubmit ? `<button class="wv2-primary-action" type="button" data-task-submit="${encode(request.request_id)}">开始工作</button>` : ""}${active ? `<div class="wv2-progress" role="progressbar" aria-label="任务进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Number(request.progress_percent) || 0}"><span style="width:${Math.max(0, Math.min(100, Number(request.progress_percent) || 0))}%"></span></div>` : ""}${artifacts.length ? renderArtifacts(current, artifacts, request) : ""}${request.commentary ? `<aside class="wv2-commentary"><span>角色附言</span><p>${encode(isObject(request.commentary) ? request.commentary.content : request.commentary)}</p></aside>` : ""}${request.error && !roleRequest ? `<div class="wv2-error" role="alert">${encode(request.error)}</div>` : ""}</section>`;
  }

  function renderDevelopment(request) {
    if (!request.development) return "";
    const spec = request.development;
    const workspace = request.development_workspace;
    return `<section class="wv2-development" aria-label="开发执行范围"><h3>隔离开发</h3><p>源目录：${encode(spec.directory)}</p><p>最多 ${encode(spec.max_calls)} 次模型调用；不自动合入、提交或发布。</p><p>测试以当前用户权限在本机运行，源码副本不构成操作系统沙箱。</p><pre>${encode(JSON.stringify(spec.test_commands, null, 2))}</pre>${asArray(request.assumptions).map((item) => `<p>${encode(item)}</p>`).join("")}${workspace ? `<p>副本：${encode(workspace.path)}</p><p>已复制 ${asArray(workspace.files).length} 个文件，跳过 ${asArray(workspace.skipped).length} 个文件。</p><button type="button" data-inspector-open="diff">审查文件差异</button>` : ""}<details><summary>开发执行记录 ${asArray(request.development_events).length}</summary>${asArray(request.development_events).map((item) => `<article><strong>${encode(item.name || "模型回复")}</strong><pre>${encode(item.text || JSON.stringify(item.result, null, 2))}</pre></article>`).join("")}</details></section>`;
  }

  function renderExternalSteps(request) {
    if (request.parent_authorization) return `<p class="wv2-shared-budget">本步骤计入父任务 ${encode(request.parent_authorization.request_id)} 的共享预算，不额外叠加一份消费授权。</p>`;
    const steps = asArray(request.external_steps);
    if (!steps.length) return "";
    return `<section class="wv2-external-steps" aria-label="本次授权包含的子步骤"><h3>本次授权包含的子步骤</h3><p>与当前任务共用总预算；只允许下列目标、渠道和范围，不自动扩大授权。执行仍由原宿主调度。</p><ol>${steps.map((step) => `<li><strong>${encode(step.purpose)}</strong><p>${encode(step.params?.text || step.params?.question || step.params?.goal || "继续指定任务")}</p><p>${encode(step.candidate_id)} · 上界 ${step.high_cny == null ? "未知，不能执行" : `${encode(step.high_cny)} CNY`}</p><details><summary>查看执行范围</summary><pre>${encode(JSON.stringify({ method: step.method, params: step.params }, null, 2))}</pre></details></li>`).join("")}</ol></section>`;
  }

  function renderArtifacts(current, artifacts, request) {
    return `<section class="wv2-artifacts"><header><div><span>工作成果</span><strong>可直接复制使用</strong></div><button type="button" data-inspector-open="artifacts">在右侧查看</button></header>${artifacts.map((artifact) => `<article><div><strong>${encode(artifact.name || artifact.title || "未命名成果")}</strong><span>${encode(artifact.format || artifact.type || "正文")}${artifact.verification === "source-completed" ? " · 来源已完成，未独立验证" : artifact.verified === false ? " · 未验证" : artifact.verified === true ? " · 已验证" : ""}</span></div><button type="button" data-artifact-copy="${encode(artifact.id)}" aria-label="复制${encode(artifact.name || artifact.title || "成果正文")}">复制正文</button><pre>${encode(artifact.content || artifact.text || "")}</pre></article>`).join("")}</section>`;
  }

  function renderComposer(current) {
    const conversation = current.workbench.conversation;
    const key = conversation.session_id || current.workbench.activeConversationId || "new";
    const draft = drafts.has(key) ? drafts.get(key) : asText(current.workbench.draft);
    return `<form class="wv2-composer" data-task-preflight data-draft-key="${encode(key)}"><textarea name="goal" rows="3" placeholder="描述要完成的工作" aria-label="工作目标" required>${encode(draft)}</textarea><details class="wv2-development-options"><summary>工作方式与测试</summary><label>工作方式<select name="development_mode"><option value="text" ${current.workbench.developmentMode !== "development" ? "selected" : ""}>文本工作</option><option value="development" ${current.workbench.developmentMode === "development" ? "selected" : ""}>开发：隔离副本改码</option></select></label><label>测试命令（每行一个 JSON 参数数组）<textarea name="test_commands" rows="2" placeholder='["python", "-m", "unittest", "discover"]'>${encode(current.workbench.testCommands || "")}</textarea></label><small>测试在本机执行，使用当前用户权限；不自动安装依赖。</small></details><footer><span>提交后预检报价</span><button type="submit">预检并报价</button></footer></form>`;
  }

  function renderAdvanced(current) {
    const entries = [
      ["tasks", "旧任务中心"],
      ["agent", "Agent 工作区"],
      ["web", "网页工作台"],
      ["history", "历史与通知"],
      ["schedule", "定时工作管理"],
    ];
    const pages = { tasks: "Tasks", agent: "Agent", web: "WebWorkbench", history: "History" };
    return `<details class="wv2-advanced"><summary>高级工作区</summary>${entries.map(([id, label]) => `<details><summary data-workbench-page="${pages[id] || "Workspace"}">${label}</summary>${trustedSlot(id, current, label)}</details>`).join("")}</details>`;
  }

  function renderInspector(current) {
    const inspector = current.workbench.inspector;
    if (!inspector.open) return "";
    const active = ["files", "artifacts", "diff", "browser"].includes(inspector.active) ? inspector.active : "files";
    const tabs = [["files", "文件"], ["artifacts", "成果"], ["diff", "Diff"], ["browser", "浏览器"]];
    let content = "";
    if (active === "browser") content = trustedSlot("browser", current, "内置浏览器");
    else if (active === "diff") content = inspector.diff ? `<pre class="wv2-diff">${encode(inspector.diff)}</pre>` : sourceUnavailable(escapeHtml, "Diff", current.sources.diff);
    else {
      const items = asArray(active === "files" ? inspector.files : inspector.artifacts);
      content = items.length ? `<ul class="wv2-inspector-list">${items.map((item) => `<li><button type="button" data-inspector-item="${encode(item.id || item.path)}"><strong>${encode(item.name || item.path || item.title)}</strong><span>${encode(item.status || item.type || "")}</span></button></li>`).join("")}</ul>` : sourceUnavailable(escapeHtml, active === "files" ? "文件" : "成果", current.sources[active]);
    }
    return `<aside class="wv2-inspector"><header><nav aria-label="右侧工具">${tabs.map(([id, label]) => `<button type="button" data-inspector-open="${id}" class="${active === id ? "active" : ""}">${label}</button>`).join("")}</nav><button type="button" data-inspector-close aria-label="关闭右侧工具">×</button></header><div class="wv2-inspector-body">${content}</div></aside>`;
  }

  function renderWorkspace(current) {
    const inspector = renderInspector(current);
    return `<main class="wv2-workspace ${inspector ? "with-inspector" : ""}">${renderProjects(current)}<section class="wv2-center"><header class="wv2-center-heading"><div><span>${encode(current.workbench.activeProjectName || "工作台")}</span><h1>${encode(current.workbench.conversation.title || "新工作")}</h1></div><div><button type="button" data-clear-display>仅清当前显示</button><button type="button" data-inspector-open="files">打开右侧工具</button></div></header><div class="wv2-timeline">${renderRounds(current)}${renderSchedulePanel(current)}${renderTask(current)}</div>${renderComposer(current)}${renderAdvanced(current)}</section>${inspector}</main>`;
  }

  function moduleStatus(module) {
    if (module.available === false) return module.unavailable_reason || "不可用";
    if (module.enabled) return "已启用";
    if (module.configured === false) return "待配置";
    return module.status_label || module.status || "未启用";
  }

  function renderCapabilities(current) {
    const data = current.capabilities;
    if (data.status === "loading") return `<main class="wv2-page"><div class="wv2-page-empty" aria-busy="true">正在读取能力目录…</div></main>`;
    if (data.status === "error") return `<main class="wv2-page">${sourceUnavailable(escapeHtml, "能力目录", { reason: data.error || current.sources.capabilities?.reason })}</main>`;
    const active = CAPABILITY_CATEGORIES.some(([id]) => id === data.activeCategory) ? data.activeCategory : "perception";
    const addedIds = new Set(asArray(data.added_ids));
    const inCategory = data.modules.filter((module) => module.category === active);
    const added = inCategory.filter((module) => addedIds.has(module.id));
    const library = inCategory.filter((module) => !addedIds.has(module.id));
    return `<main class="wv2-page wv2-capabilities"><header class="wv2-page-heading"><div><span>CAPABILITIES</span><h1>能力</h1></div><button type="button" data-capability-organize aria-pressed="${data.organize === true}">${data.organize ? "完成整理" : "整理"}</button></header><nav class="wv2-tabs" role="tablist" aria-label="能力分类">${CAPABILITY_CATEGORIES.map(([id, label]) => `<button type="button" role="tab" data-capability-category="${id}" aria-selected="${active === id}" tabindex="${active === id ? 0 : -1}">${label}</button>`).join("")}</nav><div class="wv2-capability-grid">${added.map((module, index) => `<article class="wv2-capability-card"><header><strong>${encode(module.name || module.id)}</strong><span>${encode(moduleStatus(module))}</span></header><p>${encode(module.description)}</p><dl><div><dt>配置</dt><dd>${encode(module.configuration_label || (module.configured ? "已配置" : "未配置"))}</dd></div><div><dt>权限</dt><dd>${encode(module.permission_label || "未授权")}</dd></div></dl><footer><button type="button" data-capability-configure="${encode(module.id)}">配置</button>${data.organize ? `<span><button type="button" data-capability-move="up" data-module-id="${encode(module.id)}" aria-label="上移${encode(module.name || module.id)}" ${index === 0 ? "disabled" : ""}>↑</button><button type="button" data-capability-move="down" data-module-id="${encode(module.id)}" aria-label="下移${encode(module.name || module.id)}" ${index === added.length - 1 ? "disabled" : ""}>↓</button><button type="button" data-capability-remove="${encode(module.id)}" aria-label="移除${encode(module.name || module.id)}">×</button></span>` : ""}</footer></article>`).join("")}<button type="button" class="wv2-add-tile" data-capability-library-open aria-label="打开模块库">＋</button></div><dialog class="wv2-module-library" ${data.libraryOpen ? "open" : ""} aria-labelledby="wv2-module-library-title"><header><div><span>MODULE LIBRARY</span><h2 id="wv2-module-library-title">模块库</h2></div><button type="button" data-capability-library-close aria-label="关闭模块库">×</button></header><div>${library.length ? library.map((module) => `<article><div><strong>${encode(module.name || module.id)}</strong><span>${encode(moduleStatus(module))}</span></div><p>${encode(module.description)}</p><button type="button" data-capability-add="${encode(module.id)}" aria-label="添加${encode(module.name || module.id)}" title="添加到能力页；不会启用或授权" ${module.registered === false ? "disabled" : ""}>＋</button></article>`).join("") : "<p class=\"wv2-empty\">当前分类没有可添加模块</p>"}</div><p>添加只改变页面布局，不启用能力、不授予权限，也不开始外部调用。</p></dialog></main>`;
  }

  function candidateOptions(binding) {
    const candidates = asArray(binding.candidates);
    const selectedId = asText(binding.candidate_id);
    const hasSelected = candidates.some((candidate) => candidate.id === selectedId);
    const values = !selectedId || hasSelected ? candidates : [{ id: selectedId, name: binding.candidate_name || selectedId, available: false, reason: binding.invalid_reason || "已固定候选当前不在目录中" }, ...candidates];
    return values.map((candidate) => {
      const selected = candidate.id === selectedId;
      const invalid = candidate.available === false;
      const suffix = invalid ? ` · 不可用：${candidate.reason || candidate.health || "原因未知"}` : ` · ${candidate.provider || "渠道未知"} · ${candidate.reasoning_effort || "推理强度未知"}`;
      return `<option value="${encode(candidate.id)}" ${selected ? "selected" : ""} ${invalid && !selected ? "disabled" : ""}>${encode(candidate.name || candidate.id)}${encode(suffix)}</option>`;
    }).join("");
  }

  function renderBinding(kind, label, binding) {
    const fixed = binding.mode === "fixed";
    const selected = asArray(binding.candidates).find((candidate) => candidate.id === binding.candidate_id);
    const invalidReason = fixed && (selected?.available === false || binding.invalid_reason) ? binding.invalid_reason || selected?.reason || selected?.health || "候选当前不可用；不会自动替换" : "";
    return `<form class="wv2-binding" data-model-binding="${kind}"><header><div><span>${encode(kind === "work" ? "MAIN MODEL" : "ROLE MODEL")}</span><h2>${label}</h2></div><div class="wv2-segmented"><label><input type="radio" name="mode" value="auto" ${fixed ? "" : "checked"}><span>自动</span></label><label><input type="radio" name="mode" value="fixed" ${fixed ? "checked" : ""}><span>固定</span></label></div></header><label>候选<select name="candidate_id" ${fixed ? "" : "disabled"}>${candidateOptions(binding)}</select></label><div class="wv2-binding-evidence"><span>当前应用：${encode(binding.applied_label || binding.applied_candidate_id || "尚未选择")}</span><span>选择依据：${encode(binding.selection_reason || "尚无有效证据")}</span><span>费用：${encode(binding.cost_label || "未知")}</span></div>${invalidReason ? `<p class="wv2-warning" role="status">${encode(invalidReason)}；保留当前固定项，不会静默切换。</p>` : ""}<button type="submit">保存${label}设置</button></form>`;
  }

  function renderSettings(current) {
    const settings = current.settings;
    const budget = settings.budget;
    const skillsPanel = `<section class="wv2-settings-section" data-builtin-skills><h2>内置 Skill</h2><p>按需启用，作用于后续请求。启用不增加文件、执行或消费权限。</p>${(settings.builtinSkills || []).map((row) => `<article><label><input type="checkbox" data-builtin-skill="${encode(row.id)}" data-sha256="${encode(row.sha256)}" ${row.enabled ? "checked" : ""}>${encode(row.title)}</label><p>${encode(row.description)}</p><small>${encode(row.publisher)} · ${encode(row.runtime_status)}</small>${row.update_available ? "<p>内容已更新，请重新启用。</p>" : ""}${row.config_path ? `<p>本地配置：<code>${encode(row.config_path)}</code></p>` : ""}</article>`).join("")}</section>`;
    const memoryPanel = skillsPanel + (settings.memory?.open === true ? trustedSlot("memory", current, "记忆管理") : "")
      + (typeof slots.benefits === "function" ? asText(slots.benefits(current)) : "");
    return `<main class="wv2-page wv2-settings"><header class="wv2-page-heading"><div><span>SETTINGS</span><h1>设置</h1></div></header><details class="wv2-settings-section" ${settings.connectionsOpen ? "open" : ""}><summary data-workbench-page="Modules">连接配置</summary>${trustedSlot("connections", current, "连接配置")}</details><section class="wv2-settings-grid">${renderBinding("work", "负责工作", settings.bindings.work || {})}${renderBinding("role", "负责交流", settings.bindings.role || {})}</section><form class="wv2-budget-settings" data-budget-settings><header><span>BUDGET</span><h2>费用与上限</h2></header><label>费用偏好<select name="preference"><option value="quality-first" ${budget.preference !== "free-only" ? "selected" : ""}>工作质量优先</option><option value="free-only" ${budget.preference === "free-only" ? "selected" : ""}>仅使用明确免费资源</option></select></label><label>默认任务消费上限（CNY）<input name="max_cny" type="number" min="0" step="0.01" value="${encode(budget.max_cny)}" placeholder="未设置"></label><p>付费请求仍需确认。</p><button type="submit">保存预算设置</button></form><section class="wv2-memory-settings"><div><span>MEMORY</span><h2>记忆</h2><p>${encode(settings.memory?.summary || "手动管理长期记忆")}</p></div><button type="button" data-open-memory>管理记忆</button></section>${memoryPanel}<details class="wv2-settings-section"><summary data-workbench-page="Settings">外观与指南</summary>${trustedSlot("preferences", current, "外观与指南")}</details><details class="wv2-advanced"><summary data-workbench-page="Developer">高级诊断</summary>${trustedSlot("diagnostics", current, "高级诊断")}</details></main>`;
  }

  function renderCharacters(current) {
    return `<main class="wv2-page wv2-characters"><header class="wv2-page-heading"><div><span>CHARACTERS</span><h1>角色</h1></div></header>${trustedSlot("characters", current, "角色管理")}</main>`;
  }

  function renderCompanion(current) {
    const data = current.companion;
    const scene = typeof slots.scene === "function" ? asText(slots.scene(current)) : sourceUnavailable(escapeHtml, "居所场景", current.sources.scene);
    return `<main class="wv2-companion ${data.transparent ? "transparent" : ""}"><div class="wv2-companion-scene">${scene}</div>${data.bubble ? `<div class="wv2-companion-bubble">${encode(data.bubble)}</div>` : ""}<button type="button" class="wv2-chat-once" data-companion-toggle aria-expanded="${data.composerOpen === true}">聊一句</button>${data.composerOpen ? `<form data-companion-send><input name="message" value="${encode(data.draft)}" aria-label="聊一句" autocomplete="off" required><button type="submit">发送</button></form>` : ""}</main>`;
  }

  function render() {
    const current = normalizeState(getState());
    if (current.view === "companion") return renderCompanion(current);
    const content = current.view === "capabilities" ? renderCapabilities(current)
      : current.view === "characters" ? renderCharacters(current)
        : current.view === "settings" ? renderSettings(current)
          : renderWorkspace(current);
    return `<div class="workbench-v2" data-workbench-v2-view="${current.view}">${renderNavigation(current)}${content}</div>`
      .replaceAll('step="0.01"', 'step="any"')
      .replace('<option value="1">周一</option><option value="2">周二</option><option value="3">周三</option><option value="4">周四</option><option value="5">周五</option><option value="6">周六</option><option value="0">周日</option>', '<option value="0">周一</option><option value="1">周二</option><option value="2">周三</option><option value="3">周四</option><option value="4">周五</option><option value="5">周六</option><option value="6">周日</option>')
      .replace("合格免费角色资源当前不足，需要确认本次付费角色预算后继续。", "免费角色资源不足，本次继续需要确认预算。")
      .replace("<p>添加只改变页面布局，不启用能力、不授予权限，也不开始外部调用。</p>", "");
  }

  function bind(root) {
    if (!root) return () => {};
    const click = (event) => {
      const target = event.target.closest?.("button, a");
      if (!target || !root.contains(target)) return;
      if (target.matches("a[href='#']")) event.preventDefault();
      const current = normalizeState(getState());
      const request = current.workbench.selectedTask || {};
      if (target.dataset.wv2View) action("onNavigate", { view: target.dataset.wv2View }, event);
      else if (target.hasAttribute("data-wv2-open-residence")) action("onOpenResidence", {}, event);
      else if (target.hasAttribute("data-conversation-create")) action("onConversationCreate", { project_id: current.workbench.activeProjectId || null }, event);
      else if (target.dataset.projectSelect) action("onProjectSelect", { project_id: target.dataset.projectSelect }, event);
      else if (target.dataset.projectArchive) action("onProjectArchive", { project_id: target.dataset.projectArchive }, event);
      else if (target.dataset.conversationSelect) action("onConversationSelect", { session_id: target.dataset.conversationSelect }, event);
      else if (target.dataset.conversationPin) action("onConversationUpdate", { assistant_id: current.assistant.id, session_id: target.dataset.conversationPin, changes: { pinned: target.dataset.pinned !== "true" } }, event);
      else if (target.dataset.conversationArchive) action("onConversationUpdate", { assistant_id: current.assistant.id, session_id: target.dataset.conversationArchive, changes: { archived: true } }, event);
      else if (target.dataset.scheduleSelect) action("onScheduleSelect", { schedule_id: target.dataset.scheduleSelect }, event);
      else if (target.dataset.scheduleRun) action("onScheduleRun", { assistant_id: current.assistant.id, schedule_id: target.dataset.scheduleRun }, event);
      else if (target.dataset.schedulePause) action("onSchedulePause", { assistant_id: current.assistant.id, schedule_id: target.dataset.schedulePause }, event);
      else if (target.dataset.scheduleHistory) action("onScheduleHistory", { assistant_id: current.assistant.id, schedule_id: target.dataset.scheduleHistory }, event);
      else if (target.hasAttribute("data-conversation-page")) action("onConversationPage", { assistant_id: current.assistant.id, session_id: current.workbench.conversation.session_id, cursor: current.workbench.conversation.cursor, limit_rounds: 10 }, event);
      else if (target.hasAttribute("data-clear-display")) action("onClearConversationDisplay", { assistant_id: current.assistant.id, session_id: current.workbench.conversation.session_id, through_message_id: current.workbench.conversation.last_message_id || null }, event);
      else if (target.dataset.taskGet) action("onTaskGet", { request_id: target.dataset.taskGet, assistant_id: current.assistant.id }, event);
      else if (target.dataset.taskSubmit) action("onTaskSubmit", { request_id: target.dataset.taskSubmit, assistant_id: request.assistant_id || current.assistant.id, source: request.request?.source || request.source || "workbench" }, event);
      else if (target.dataset.taskCancel) action("onTaskCancel", { request_id: target.dataset.taskCancel, assistant_id: request.assistant_id || current.assistant.id }, event);
      else if (target.dataset.artifactCopy) {
        const artifact = asArray(request.artifacts).find((item) => String(item.id) === target.dataset.artifactCopy);
        action("onArtifactCopy", { artifact, text: artifact?.content || artifact?.text || "" }, event);
      } else if (target.dataset.inspectorOpen) action("onInspectorChange", { open: true, active: target.dataset.inspectorOpen }, event);
      else if (target.hasAttribute("data-inspector-close")) action("onInspectorChange", { open: false, active: current.workbench.inspector.active }, event);
      else if (target.dataset.capabilityCategory) action("onCapabilityCategoryChange", { category: target.dataset.capabilityCategory }, event);
      else if (target.hasAttribute("data-capability-organize")) action("onCapabilityOrganizeChange", { organize: current.capabilities.organize !== true }, event);
      else if (target.hasAttribute("data-capability-library-open")) action("onCapabilityLibraryChange", { open: true }, event);
      else if (target.hasAttribute("data-capability-library-close")) action("onCapabilityLibraryChange", { open: false }, event);
      else if (target.dataset.capabilityAdd) action("onCapabilityLayoutChange", { action: "add", module_id: target.dataset.capabilityAdd }, event);
      else if (target.dataset.capabilityRemove) action("onCapabilityLayoutChange", { action: "remove", module_id: target.dataset.capabilityRemove }, event);
      else if (target.dataset.capabilityMove) action("onCapabilityLayoutChange", { action: `move-${target.dataset.capabilityMove}`, module_id: target.dataset.moduleId }, event);
      else if (target.dataset.capabilityConfigure) action("onCapabilityConfigure", { module_id: target.dataset.capabilityConfigure }, event);
      else if (target.hasAttribute("data-open-memory")) action("onOpenMemory", {}, event);
      else if (target.hasAttribute("data-companion-toggle")) action("onCompanionComposerToggle", { open: current.companion.composerOpen !== true }, event);
    };
    const submit = (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !root.contains(form)) return;
      event.preventDefault();
      const values = new FormData(form);
      const current = normalizeState(getState());
      const request = current.workbench.selectedTask || {};
      if (form.matches("[data-task-preflight]")) {
        const key = form.dataset.draftKey || "new";
        const goal = asText(values.get("goal")).trim();
        if (!goal) return;
        drafts.set(key, "");
        const development = values.get("development_mode") === "development" ? { test_commands: asText(values.get("test_commands")).split("\n").filter((line) => line.trim()).map((line) => JSON.parse(line)) } : null;
        action("onTaskPreflight", { goal, project_id: current.workbench.activeProjectId || null, ...(development ? { development } : {}) }, event);
      } else if (form.matches("[data-authorization-confirm]")) {
        if (request.quote?.high_cny == null || request.external && (request.external.limit_enforced !== true || request.external_resume_available === false)) return;
        const payload = { request_id: request.request_id, assistant_id: request.assistant_id || current.assistant.id, revision: request.revision, max_cny: asText(values.get("max_cny")) };
        if (form.dataset.requestSource === "role") {
          action("onRoleAuthorizationConfirm", {
            ...payload,
            chat: current.workbench.roleResume?.chat || {
              assistant_id: payload.assistant_id,
              session_id: request.request?.session_id || current.workbench.conversation.session_id,
              message: request.request?.goal || request.goal,
            },
          }, event);
        } else {
          action("onAuthorizationConfirm", payload, event);
        }
      } else if (form.matches("[data-project-create]")) {
        action("onProjectCreate", { name: asText(values.get("name")).trim(), category: asText(values.get("category")).trim() || null, directory: asText(values.get("directory")).trim() || null }, event);
      } else if (form.matches("[data-project-update]")) {
        const projectId = form.dataset.projectUpdate;
        action("onProjectUpdate", { project_id: projectId, name: asText(values.get("name")).trim(), category: asText(values.get("category")).trim() || null, directory: asText(values.get("directory")).trim() || null, pinned: values.get("pinned") === "on" }, event);
      } else if (form.matches("[data-conversation-search]")) {
        action("onConversationSearch", { query: asText(values.get("query")).trim() }, event);
      } else if (form.matches("[data-schedule-create]")) {
        const rule = normalizeScheduleRule({ kind: asText(values.get("kind")), timezone: asText(values.get("timezone"), "Asia/Shanghai"), at: values.get("at"), time: values.get("time"), weekday: values.get("weekday") });
        action("onScheduleCreate", {
          assistant_id: current.assistant.id,
          draft: {
            title: asText(values.get("title")).trim(),
            payload: { goal: asText(values.get("goal")).trim() },
            rule,
            authorization: { scope_confirmed: true, paid: false },
          },
        }, event);
      } else if (form.matches("[data-model-binding]")) {
        const controls = [...form.querySelectorAll("input, select, button")].map(field => [field, field.disabled]);
        controls.forEach(([field]) => { field.disabled = true; });
        const pending = action("onModelBindingSave", { role: form.dataset.modelBinding, mode: asText(values.get("mode")), candidate_id: values.get("mode") === "fixed" ? asText(values.get("candidate_id")) : null }, event);
        Promise.resolve(pending).finally(() => controls.forEach(([field, disabled]) => { field.disabled = disabled; })).catch(() => {});
      } else if (form.matches("[data-budget-settings]")) {
        action("onBudgetSettingsSave", { preference: asText(values.get("preference")), max_cny: asText(values.get("max_cny")) || null }, event);
      } else if (form.matches("[data-companion-send]")) {
        action("onCompanionSend", { message: asText(values.get("message")).trim() }, event);
      }
    };
    const input = (event) => {
      const field = event.target;
      if (field.matches?.("[data-task-preflight] [name='test_commands']")) {
        action("onDraftChange", { kind: "development-tests", value: field.value }, event);
      } else if (field.matches?.("[data-task-preflight] [name='goal']")) {
        const key = field.closest("form")?.dataset.draftKey || "new";
        drafts.set(key, field.value);
        action("onDraftChange", { kind: "work", key, value: field.value }, event);
      } else if (field.matches?.("[data-project-update] [name='name']")) {
        const projectId = field.closest("form")?.dataset.projectUpdate;
        if (projectId) projectTitles.set(projectId, field.value);
        action("onDraftChange", { kind: "project-title", key: projectId, value: field.value }, event);
      }
    };
    const change = (event) => {
      if (event.target.matches?.("[data-builtin-skill]")) {
        const field = event.target;
        field.disabled = true;
        action("onBuiltinSkillToggle", { skill_id: field.dataset.builtinSkill, enabled: field.checked, sha256: field.dataset.sha256 }, event);
        return;
      }
      if (event.target.matches?.("[name='development_mode']")) action("onDraftChange", { kind: "development-mode", value: event.target.value }, event);
      const mode = event.target.matches?.("[data-model-binding] [name='mode']") ? event.target : null;
      if (!mode) return;
      const select = mode.closest("form")?.querySelector("[name='candidate_id']");
      if (select) select.disabled = mode.value !== "fixed";
    };
    const keydown = (event) => {
      if (event.key === "Escape" && normalizeState(getState()).capabilities.libraryOpen) {
        event.preventDefault();
        action("onCapabilityLibraryChange", { open: false }, event);
        root.querySelector("[data-capability-library-open]")?.focus();
        return;
      }
      const tab = event.target.closest?.("[data-capability-category]");
      if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const index = CAPABILITY_CATEGORIES.findIndex(([id]) => id === tab.dataset.capabilityCategory);
      const next = event.key === "Home" ? 0 : event.key === "End" ? CAPABILITY_CATEGORIES.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + CAPABILITY_CATEGORIES.length) % CAPABILITY_CATEGORIES.length;
      const category = CAPABILITY_CATEGORIES[next][0];
      action("onCapabilityCategoryChange", { category }, event);
      root.querySelector(`[data-capability-category="${category}"]`)?.focus();
    };
    root.addEventListener("click", click);
    root.addEventListener("submit", submit);
    root.addEventListener("input", input);
    root.addEventListener("change", change);
    root.addEventListener("keydown", keydown);
    return () => {
      root.removeEventListener("click", click);
      root.removeEventListener("submit", submit);
      root.removeEventListener("input", input);
      root.removeEventListener("change", change);
      root.removeEventListener("keydown", keydown);
    };
  }

  function mount(root) {
    cleanup();
    boundRoot = root;
    root.innerHTML = render();
    cleanup = bind(root);
    return api;
  }

  function update() {
    if (boundRoot) mount(boundRoot);
    return api;
  }

  function destroy() {
    cleanup();
    cleanup = () => {};
    boundRoot = null;
  }

  const api = Object.freeze({ render, bind, mount, update, destroy });
  return api;
}
