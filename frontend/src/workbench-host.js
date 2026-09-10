import { createWorkbenchV2View } from "./workbench-v2-view.js";
import { projectCapabilityLayout, changeCapabilityLayout, writeCapabilityLayout } from "./capability-layout.js";

export function createWorkbenchHost({ state, rpc, render, slots, selectSession, createSession, openResidence, sendRole, setInspector, navigate = () => {}, storage = localStorage }) {
  const model = { view: "workspace", projects: [], tasks: [], schedules: [], selectedTask: null, selectedProject: null, query: "",
    inspector: { open: false, active: "files" }, category: "perception", libraryOpen: false, organize: false,
    settings: null, catalog: [], selection: null, notice: "", busy: false, memoryOpen: false, connectionsOpen: false,
    selectedSchedule: null, scheduleRuns: [], maintenance: [], builtinSkills: [] };
  const scope = () => ({ assistant_id: state.selectedCharacter, session_id: state.activeSessionId });
  const scopeKey = () => `${state.selectedCharacter}:${state.activeSessionId}`;
  let bindingCleanup = () => {};
  let refreshing = null;
  const history = new Map();
  const externalContinuations = new Map();
  const safeRead = (key, fallback) => { try { return JSON.parse(storage.getItem(key)) ?? fallback; } catch { return fallback; } };
  const category = (value) => ({ 学习: "learning", 编程: "programming", 生活: "life", 健康: "health", "健康与运动": "health", 创作: "research", "研究与创作": "research", 自定义: "custom" })[value] || value || "custom";
  const problem = (error) => { model.notice = error.message || "操作未完成"; render(); };

  async function loadHistory({ older = false, reset = false } = {}) {
    const key = scopeKey();
    const previous = history.get(key);
    if (previous?.cleared && !older && !reset) return;
    const params = { ...scope() };
    if (older && previous?.cursor) params.before = previous.cursor;
    if (older) params.limit = 10;
    const page = await rpc("conversation.page", params);
    if (scopeKey() !== key) return;
    const rounds = older && !previous?.cleared ? [...page.turns, ...(previous?.rounds || [])] : page.turns;
    const unique = [...new Map(rounds.map((round) => [round.id, round])).values()];
    history.set(key, { rounds: unique, cursor: page.next_before, has_more: page.has_more, cleared: false });
    state.messages = unique.flatMap((round) => round.messages);
  }

  async function refresh() {
    if (!state.connected) return;
    if (refreshing) { await refreshing; return refresh(); }
    let finishRefresh;
    refreshing = new Promise(resolve => { finishRefresh = resolve; });
    const owner = state.selectedCharacter;
    try {
      const results = await Promise.allSettled([
        rpc("project.list", { assistant_id: owner, archived: null }), rpc("work.task.list", { assistant_id: owner }),
        rpc("schedule.list", { assistant_id: owner }), rpc("quality.settings.get", { assistant_id: owner }),
        rpc("quality.catalog", { assistant_id: owner }), rpc("quality.bindings.select", { assistant_id: owner }),
        rpc("skill.builtin.list", { assistant_id: owner }),
      ]);
      if (owner !== state.selectedCharacter) return;
      for (const [index, result] of results.entries()) {
        if (result.status === "rejected") { model.notice = result.reason.message; continue; }
        const data = result.value;
        if (index === 0) model.projects = data.projects;
        if (index === 1) {
          model.tasks = data.tasks;
          if (model.selectedTask) model.selectedTask = data.tasks.find((task) => task.request_id === model.selectedTask.request_id) || model.selectedTask;
          else model.selectedTask = data.tasks.find((task) => task.request?.source === "role" && task.status === "awaiting-confirmation") || null;
          if (model.selectedTask?.request?.source === "role") model.roleResume = { chat: { session_id: model.selectedTask.request.session_id, message: model.selectedTask.goal } };
        }
        if (index === 2) { model.schedules = data.schedules; model.maintenance = data.maintenance || []; }
        if (index === 3) model.settings = data;
        if (index === 4) model.catalog = data.candidates;
        if (index === 5) model.selection = data;
        if (index === 6) model.builtinSkills = data.skills || [];
      }
    } finally { refreshing = null; finishRefresh(); }
  }

  function projection() {
    const layout = projectCapabilityLayout({ state, storage });
    const binding = (purpose) => {
      const selected = model.selection?.bindings?.[purpose] || {};
      const chosen = model.catalog.find((row) => row.candidate_id === selected.candidate_id);
      return { mode: model.settings?.selection_mode?.[purpose] || "auto", candidate_id: model.settings?.[`${purpose}_candidate_id`],
        candidates: model.catalog.map((row) => ({ ...row, id: row.candidate_id, name: row.label, label: `${row.label} · ${row.model_id} · ${row.reasoning_effort || "默认推理"}` })),
        applied_candidate_id: selected.candidate_id, applied_label: chosen ? `${chosen.label} · ${chosen.reasoning_effort || "默认推理"}` : "未就绪",
        selection_reason: selected.reason, invalid_reason: selected.candidate_id ? "" : selected.reason,
        cost_label: chosen?.cost_quote?.free ? "免费（发送前重新核验）" : chosen?.cost_quote?.effective_cost_cny != null ? `参考请求 ¥${chosen.cost_quote.effective_cost_cny}` : "未知" };
    };
    const activeHistory = history.get(scopeKey()) || { rounds: [], has_more: false };
    const project = model.projects.find((row) => row.id === model.selectedProject);
    const conversationIds = project ? new Set(project.conversations.filter((row) => row.source === "core").map((row) => row.source_id)) : null;
    const rows = state.sessions.filter((row) => row.character_id === state.selectedCharacter && row.purpose !== "chat" && (!conversationIds || conversationIds.has(row.id)))
      .sort((left, right) => Number(!!right.pinned) - Number(!!left.pinned));
    return { view: model.view, assistant: { id: state.selectedCharacter, name: state.characters.find((row) => row.id === state.selectedCharacter)?.name },
      workbench: { projects: model.projects.filter((row) => !model.query || `${row.name} ${row.summary}`.includes(model.query)),
        conversations: rows.filter((row) => !model.query || row.title.includes(model.query)),
        schedules: model.schedules.map((row) => ({ ...row, status: row.state, next_run_label: row.next_at })),
        selectedSchedule: model.selectedSchedule, scheduleHistory: model.scheduleRuns, maintenance: model.maintenance,
        tasks: model.tasks, selectedTask: model.selectedTask ? { ...model.selectedTask, external_resume_available: externalContinuations.has(model.selectedTask.request_id) } : null, activeProjectId: model.selectedProject, activeProjectName: project?.name,
        activeConversationId: state.activeSessionId, projectFilter: model.query, draft: state.workDraft || "", developmentMode: state.developmentMode || "text", testCommands: state.developmentTests || "",
        conversation: { ...activeHistory, session_id: state.activeSessionId, title: rows.find((row) => row.id === state.activeSessionId)?.title },
        inspector: { ...model.inspector, diff: model.selectedTask?.development_diff?.patch || state.workspaceRuntimeDiff?.diff || "", files: (model.selectedTask?.development_workspace?.files || []).map((path) => ({ path })), artifacts: model.selectedTask?.artifacts || [] },
        roleResume: model.roleResume },
      capabilities: { modules: [...layout.added, ...layout.library].map((row) => ({ ...row, available: row.registered,
        enabled: row.module?.enabled, configured: !!row.module?.implementation_id && row.module.implementation_id !== "none" })),
        added_ids: layout.added.map((row) => row.id), activeCategory: model.category, libraryOpen: model.libraryOpen, organize: model.organize,
        status: state.moduleCatalogStatus },
      settings: { bindings: { work: binding("leader"), role: binding("role") }, budget: model.settings?.budget_preferences || {}, memory: { open: model.memoryOpen }, connectionsOpen: model.connectionsOpen, builtinSkills: model.builtinSkills },
      sources: { files: { reason: "在项目中绑定工作目录后查看文件" }, diff: { reason: "当前没有文件改动" } } };
  }

  const actions = {
    onBuiltinSkillToggle: async (data) => { try { await rpc("skill.builtin.set", { ...scope(), ...data }); } finally { await refresh(); render(); } },
    onNavigate: async ({ view }) => {
      if (view !== "workspace") {
        model.inspector.open = false;
        await setInspector({ open: false, active: model.inspector.active });
      }
      if (view === "settings") await refresh();
      model.view = view;
      model.notice = "";
      render();
      navigate({ workspace: "Workspace", settings: "Settings", capabilities: "Capabilities", characters: "Characters" }[view]);
    },
    onOpenResidence: openResidence,
    onProjectCreate: async (data) => { const project = await rpc("project.create", { ...scope(), name: data.name, category: category(data.category), directory: data.directory || null }); model.selectedProject = project.id; await refresh(); render(); },
    onProjectSelect: ({ project_id }) => { model.selectedProject = project_id; model.selectedTask = null; render(); },
    onProjectUpdate: async (data) => { await rpc("project.update", { ...scope(), project_id: data.project_id, name: data.name, category: category(data.category), directory: data.directory || null }); await refresh(); render(); },
    onProjectArchive: async (data) => { await rpc("project.archive", { ...scope(), ...data }); await refresh(); render(); },
    onConversationCreate: async () => { await createSession(); if (model.selectedProject) await rpc("conversation.attach", { ...scope(), project_id: model.selectedProject, source: "core", source_id: state.activeSessionId }); await refresh(); await loadHistory({ reset: true }); render(); },
    onConversationSelect: async ({ session_id }) => { model.selectedTask = null; await selectSession(session_id); await loadHistory(); render(); },
    onConversationUpdate: async ({ session_id, changes }) => { const updated = await rpc("conversation.update", { assistant_id: state.selectedCharacter, session_id, changes }); state.sessions = state.sessions.map((row) => row.id === session_id ? updated : row); render(); },
    onConversationSearch: ({ query }) => { model.query = query; render(); },
    onScheduleCreate: async ({ draft }) => { await rpc("schedule.create", { assistant_id: state.selectedCharacter, draft: { ...draft, project_id: model.selectedProject } }); await refresh(); render(); },
    onScheduleSelect: async ({ schedule_id }) => { model.selectedSchedule = model.schedules.find((row) => row.id === schedule_id) || null; model.scheduleRuns = (await rpc("schedule.history", { assistant_id: state.selectedCharacter, schedule_id })).runs; render(); },
    onSchedulePause: async ({ schedule_id }) => { const current = model.schedules.find((row) => row.id === schedule_id); await rpc("schedule.pause", { assistant_id: state.selectedCharacter, schedule_id, paused: current?.state !== "paused" }); await refresh(); render(); },
    onScheduleRun: async ({ schedule_id }) => { await rpc("schedule.run", { assistant_id: state.selectedCharacter, schedule_id }); await actions.onScheduleSelect({ schedule_id }); await refresh(); render(); },
    onScheduleHistory: async (data) => actions.onScheduleSelect(data),
    onConversationPage: async () => { const timeline = document.querySelector(".wv2-timeline"); const height = timeline?.scrollHeight || 0; await loadHistory({ older: true }); render(); const next = document.querySelector(".wv2-timeline"); if (next) next.scrollTop = next.scrollHeight - height; },
    onClearConversationDisplay: () => { history.set(scopeKey(), { rounds: [], cleared: true, has_more: true, cursor: null }); state.messages = []; model.selectedTask = null; render(); },
    onTaskPreflight: async ({ goal, development }) => { if (model.busy) return; model.busy = true; try { model.selectedTask = await rpc("work.task.preflight", { ...scope(), request_id: crypto.randomUUID(), goal, project_id: model.selectedProject, ...(development ? { development } : {}) });
      if (model.selectedTask.status === "ready") model.selectedTask = await rpc("work.task.submit", { ...scope(), request_id: model.selectedTask.request_id });
      await loadHistory(); render(); } finally { model.busy = false; } },
    onTaskSubmit: async (data) => { if (model.selectedTask?.external) throw new Error("请从原来源入口继续此请求"); model.selectedTask = await rpc("work.task.submit", { ...scope(), ...data }); render(); },
    onTaskGet: async ({ request_id }) => { model.selectedTask = await rpc("work.task.get", { assistant_id: state.selectedCharacter, request_id }); render(); },
    onAuthorizationConfirm: async (data) => {
      const request = model.selectedTask;
      if (request?.external) {
        const continuation = externalContinuations.get(data.request_id);
        if (!continuation || request.external.limit_enforced !== true || request.quote?.high_cny == null) throw new Error(request.status_detail || "原入口无法承诺费用上限");
        model.selectedTask = await rpc("work.authorization.confirm", { ...data, assistant_id: request.assistant_id });
        await continuation.resume();
        if (["completed", "failed", "cancelled", "submission-unknown"].includes(model.selectedTask.status)) externalContinuations.delete(data.request_id);
      } else {
        model.selectedTask = await rpc("work.authorization.confirm", { ...scope(), ...data });
        model.selectedTask = await rpc("work.task.submit", { ...scope(), request_id: model.selectedTask.request_id });
      }
      render();
    },
    onRoleAuthorizationConfirm: async (data) => { await rpc("work.authorization.confirm", { ...scope(), request_id: data.request_id, revision: data.revision, max_cny: data.max_cny }); await sendRole(data.chat.message, data.chat.session_id); await refresh(); render(); },
    onTaskCancel: async (data) => { model.selectedTask = await rpc("work.task.cancel", { ...scope(), ...data }); await externalContinuations.get(data.request_id)?.cancel(); externalContinuations.delete(data.request_id); render(); },
    onArtifactCopy: ({ text }) => navigator.clipboard.writeText(text),
    onInspectorChange: async (data) => { model.inspector = data; await setInspector(data); render(); },
    onCapabilityCategoryChange: ({ category }) => { model.category = category; render(); },
    onCapabilityLibraryChange: ({ open }) => {
      model.libraryOpen = open;
      render();
      document.querySelector(open ? "[data-capability-library-close]" : "[data-capability-library-open]")?.focus();
    },
    onCapabilityOrganizeChange: ({ organize }) => { model.organize = organize; render(); },
    onCapabilityLayoutChange: ({ action, module_id }) => { const layout = projectCapabilityLayout({ state, storage }); const item = [...layout.added, ...layout.library].find((row) => row.id === module_id); if (action === "add" && !item?.registered) return;
      writeCapabilityLayout(changeCapabilityLayout({ ...layout.persisted, order: layout.added.map((row) => row.id) }, action, module_id), storage);
      render();
      if (model.libraryOpen) document.querySelector("[data-capability-library-close]")?.focus();
    },
    onCapabilityConfigure: () => { model.view = "settings"; model.connectionsOpen = true; render(); },
    onModelBindingSave: async ({ role, mode, candidate_id }) => { const purpose = role === "work" ? "leader" : "role"; const data = { ...scope(), selection_mode: { [purpose]: mode } }; if (mode === "fixed") data[`${purpose}_candidate_id`] = candidate_id;
      if (mode === "auto" && !model.settings?.candidate_pool?.length) data.candidate_pool = model.catalog.filter((row) => row.available && row.authorized).map((row) => row.candidate_id);
      await rpc("quality.settings.set", data); await refresh(); render(); },
    onBudgetSettingsSave: async (data) => { await rpc("quality.settings.set", { ...scope(), budget_preferences: data }); await refresh(); render(); },
    onOpenMemory: () => { model.memoryOpen = !model.memoryOpen; render(); },
    onDraftChange: ({ kind, value }) => { if (kind === "work") state.workDraft = value; if (kind === "development-mode") state.developmentMode = value; if (kind === "development-tests") state.developmentTests = value; },
    onError: problem,
  };
  const view = createWorkbenchV2View({ state: projection, actions, slots });
  return { model, refresh, loadHistory, actions,
    render: () => view.render(),
    bind: (root) => { bindingCleanup(); bindingCleanup = view.bind(root); },
    observeExternalRequest: (request, continuation) => { if (request.assistant_id !== state.selectedCharacter) return; model.selectedTask = request; if (continuation) externalContinuations.set(request.request_id, continuation); },
    showExternalApproval: (request, continuation) => { model.selectedTask = request; model.view = "workspace"; if (continuation) externalContinuations.set(request.request_id, continuation); else externalContinuations.delete(request.request_id); },
    showRoleApproval: (request, chat) => { model.selectedTask = request; model.roleResume = { chat }; model.view = "workspace"; },
    history: () => history.get(scopeKey()),
    destroy: () => { bindingCleanup(); view.destroy(); },
  };
}
