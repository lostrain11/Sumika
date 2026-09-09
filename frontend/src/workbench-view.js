export function createWorkbenchView({
  escapeHtml,
  formatAgentContextUsage,
  formatAgentTaskUsage,
  formatAgentTokenUsage,
  formatBudget,
  formatDate,
  notificationFromEvent,
  renderAgentTurnLedger,
  renderQualityWorkbench,
  renderPageFrame,
  state,
  taskAutonomyLabel,
  taskStatusClass,
  taskStatusIcon,
  taskStatusLabel,
}) {
  function renderTasks() {
    const tasks = [...state.agentTasks, ...state.tasks];
    const columns = [
      ["running", "运行中", ["pending", "running"]],
      ["waiting", "等待批准", ["waiting_approval"]],
      ["completed", "已完成", ["completed"]],
      ["attention", "失败 / 暂停", ["failed", "paused", "cancelled"]],
    ];
    const notice = state.taskNotice ? `<div class="task-notice" role="status">${escapeHtml(state.taskNotice)}</div>` : "";
    const liveCount = state.agentTasks.filter((task) => task.projection_state !== "stale" && task.stale !== true).length;
    const staleCount = state.agentTasks.length - liveCount;
    const projectionNotice = state.agentTasks.length
      ? `<span class="task-projection-state ${staleCount ? "stale" : "live"}" data-agent-projection-state="${staleCount ? "stale" : "live"}">${staleCount ? `最后已知 · ${staleCount} 条` : `实时 · ${liveCount} 条`}</span>`
      : (state.agentStatus?.ready ? "暂无 Agent Session 投影" : "Agent Runtime 未连接；暂无可恢复投影");
    const createButton = `<div class="task-toolbar"><span>本地任务保存在事件记录中；Agent 会话为 Runtime 只读投影。${projectionNotice}</span><button class="outline-button" id="add-task">创建任务</button></div>`;
    const board = columns.map(([id, title, statuses]) => {
      const items = tasks.filter((task) => statuses.includes(task.status));
      return `<section class="task-column" data-task-column="${id}"><div class="column-title"><span>${title}</span><b>${items.length}</b></div>${items.length ? items.map(renderTaskCard).join("") : `<div class="empty-column">暂无任务</div>`}</section>`;
    }).join("");
    return renderPageFrame("任务中心", "授权协作、任务状态与结果都在这里审计。", `${renderQualityWorkbench()}${notice}${createButton}<div class="task-board">${board}</div>`);
  }

  function renderTaskCard(task) {
    const expanded = state.selectedTaskId === task.id;
    const progress = Math.round((Number(task.progress) || 0) * 100);
    const busy = state.taskBusy === task.id;
    const source = task.read_only ? `${String(task.runtime_id || "Agent").toUpperCase()} · 只读` : taskAutonomyLabel(task.autonomy_level);
    const usage = task.read_only ? formatAgentTaskUsage(task.metrics) : formatBudget(task.budget);
    const staleLabel = task.stale === true || task.projection_state === "stale" ? " · 最后已知" : "";
    return `<article class="task-large-card ${expanded ? "task-expanded" : ""} ${staleLabel ? "task-stale" : ""}">
      <button class="task-open" type="button" data-task-open="${escapeHtml(task.id)}" aria-expanded="${expanded}"><div class="task-large-head"><span class="task-status ${taskStatusClass(task.status)}">${taskStatusIcon(task.status)}</span><div><strong>${escapeHtml(task.title)}</strong><small>${escapeHtml(task.id)} · ${escapeHtml(source)}</small></div><span class="task-chevron">${expanded ? "⌄" : "›"}</span></div></button>
      <div class="task-progress"><span style="width:${progress}%"></span></div><div class="task-large-foot"><span>${taskStatusLabel(task.status)} · ${progress}%${staleLabel}</span><span>${escapeHtml(usage)}</span></div>
      ${expanded ? renderTaskDetail(task, busy) : ""}
    </article>`;
  }

  function renderTaskDetail(task, busy) {
    if (task.read_only) return renderAgentTaskDetail(task);
    const permissions = task.permissions?.length ? task.permissions.join(" · ") : "无额外权限";
    const logs = task.logs?.length ? task.logs.slice(-4).map((log) => `<li>${escapeHtml(log.message || JSON.stringify(log))}</li>`).join("") : "<li>暂无日志</li>";
    const artifacts = task.artifacts?.length ? task.artifacts.map((artifact) => `<li>${escapeHtml(artifact.name || artifact.path || JSON.stringify(artifact))}</li>`).join("") : "<li>暂无产物</li>";
    return `<div class="task-detail"><div class="task-detail-grid"><div><span>自治等级</span><strong>${taskAutonomyLabel(task.autonomy_level)}</strong></div><div><span>权限</span><strong>${escapeHtml(permissions)}</strong></div><div><span>预算</span><strong>${escapeHtml(formatBudget(task.budget))}</strong></div><div><span>结果</span><strong>${escapeHtml(task.result?.summary || "暂无")}</strong></div></div><div class="task-detail-lists"><div><span>最近日志</span><ul>${logs}</ul></div><div><span>产物 / diff</span><ul>${artifacts}</ul></div></div>${renderTaskActions(task, busy)}</div>`;
  }

  function renderAgentTaskDetail(task) {
    const permissions = task.permissions?.length ? task.permissions.join(" · ") : "当前无待处理审批";
    const logs = task.logs?.length ? task.logs.slice(-4).map((log) => `<li>${escapeHtml(log.message || JSON.stringify(log))}</li>`).join("") : "<li>暂无 Runtime 事件</li>";
    const artifacts = task.artifacts?.length ? task.artifacts.map((artifact) => `<li>${escapeHtml(artifact.label || artifact.name || artifact.type || "Agent 产物")}</li>`).join("") : "<li>暂无产物</li>";
    const workspace = task.workspace;
    const workspaceLabel = workspace ? `${workspace.title || workspace.id || "Workspace"}${workspace.branch ? ` · ${workspace.branch}` : ""}${workspace.dirty ? " · 有未提交变更" : ""}${Number.isFinite(Number(workspace.checkpoint_count)) ? ` · ${Number(workspace.checkpoint_count)} checkpoint` : ""}` : "未关联 Workspace";
    const metrics = task.metrics || {};
    const turns = Array.isArray(task.turns) ? task.turns : (Array.isArray(task.result?.turns) ? task.result.turns : []);
    const tokenUsage = formatAgentTokenUsage(metrics.token_usage || {});
    const contextUsage = formatAgentContextUsage(metrics.context || {});
    const budget = task.budget && typeof task.budget === "object" ? task.budget : {};
    const budgetDetail = budget.available === false || Object.keys(budget).length === 0
      ? (budget.reason || "Runtime 未提供任务预算上限")
      : formatBudget(budget);
    const isStale = task.stale === true || task.projection_state === "stale";
    const freshness = isStale
      ? `最后已知${task.stale_reason ? `：${task.stale_reason}` : "；Runtime 当前不可用"}`
      : "实时 Runtime 投影";
    const summary = task.result?.summary || (isStale ? "Runtime 暂不可用，以下为最后已知状态" : "暂无");
    return `<div class="task-detail task-agent-projection" data-task-read-only="true" data-agent-projection="${isStale ? "stale" : "live"}"><div class="task-projection-banner ${isStale ? "stale" : "live"}" role="status">${escapeHtml(freshness)}；此卡片只读，不能据此执行或批准操作。</div><div class="task-detail-grid"><div><span>来源</span><strong>${escapeHtml(String(task.runtime_id || "Agent").toUpperCase())} Session（只读）</strong></div><div><span>会话</span><strong>${escapeHtml(task.session_id || "-")}</strong></div><div><span>真实消耗</span><strong>${escapeHtml(formatAgentTaskUsage(metrics))}</strong></div><div><span>Token 明细</span><strong>${escapeHtml(tokenUsage || "暂无")}</strong></div><div><span>上下文</span><strong>${escapeHtml(contextUsage || "暂无")}</strong></div><div><span>预算</span><strong>${escapeHtml(budgetDetail)}</strong></div><div><span>Workspace</span><strong>${escapeHtml(workspaceLabel)}</strong></div><div><span>待处理权限</span><strong>${escapeHtml(permissions)}</strong></div><div><span>结果</span><strong>${escapeHtml(summary)}</strong></div></div><div class="task-detail-lists"><div><span>最近 Runtime 事件</span><ul>${logs}</ul></div><div><span>产物 / diff</span><ul>${artifacts}</ul></div></div>${renderAgentTurnLedger(turns)}<div class="task-actions"><button class="small-button" type="button" data-agent-task-session="${escapeHtml(task.session_id || "")}">在 Agent 中打开</button></div></div>`;
  }

  function renderTaskActions(task, busy) {
    if (task.read_only) return "";
    if (task.id === "core-service") return "";
    const actions = [];
    if (["pending", "running"].includes(task.status)) actions.push(["request", "请求批准", false]);
    if (task.status === "waiting_approval" || task.status === "paused") actions.push(["approve", "批准并运行", true]);
    if (["pending", "running", "waiting_approval", "paused"].includes(task.status)) actions.push(["paused", "暂停"]);
    if (!["completed", "failed", "cancelled"].includes(task.status)) actions.push(["cancelled", "取消"]);
    if (!actions.length) return "";
    return `<div class="task-actions">${actions.map(([action, label, approved]) => action === "request" || action === "approve" ? `<button class="small-button" type="button" data-task-run="${escapeHtml(task.id)}" data-task-approved="${approved}" ${busy ? "disabled" : ""}>${label}</button>` : `<button class="small-button" type="button" data-task-status="${action}" data-task-id="${escapeHtml(task.id)}" ${busy ? "disabled" : ""}>${label}</button>`).join("")}</div>`;
  }

  function renderHistory() {
    const sessions = `<section class="history-section"><div class="history-section-heading"><div><span class="eyebrow">SESSIONS</span><strong>会话记录</strong><small>聊天记录与长期记忆分开保存。</small></div></div><div class="history-list">${state.sessions.length ? state.sessions.map((session) => `<button class="history-row ${session.id === state.activeSessionId ? "selected" : ""}" type="button" data-session-select="${escapeHtml(session.id)}" aria-current="${session.id === state.activeSessionId ? "page" : "false"}"><span class="history-icon">▤</span><div><strong>${escapeHtml(session.title)}</strong><small>${formatDate(session.updated_at)} · ${escapeHtml(session.character_id || "无角色")}</small></div><span>›</span></button>`).join("") : `<div class="empty-panel">暂无历史会话</div>`}</div></section>`;
    return renderPageFrame("会话历史", "本地保存，可按会话删除或导出；与长期记忆分离。", `${sessions}${renderMemoryBrowser()}`);
  }

  function renderMemoryBrowser() {
    const module = state.modules.find((item) => item.id === "memory");
    const enabled = Boolean(module?.enabled && module.implementation_id !== "none");
    const categories = Array.isArray(module?.config?.categories) && module.config.categories.length ? module.config.categories : ["preferences"];
    const notice = state.memoryNotice ? `<div class="memory-notice" role="status">${escapeHtml(state.memoryNotice)}</div>` : "";
    const headingAction = enabled ? `<button class="outline-button" id="add-memory" type="button" ${state.memoryBusy ? "disabled" : ""}>新增记忆</button>` : `<button class="link-button" data-page="Modules">去模块设置</button>`;
    const rows = state.memories.length ? state.memories.map((memory) => `<article class="memory-row"><div class="memory-row-head"><span class="memory-category">${escapeHtml(memory.category)}</span><time>${formatDate(memory.updated_at)}</time><button class="ghost-button" type="button" data-memory-delete="${escapeHtml(memory.id)}" ${state.memoryBusy === memory.id ? "disabled" : ""}>删除</button></div><p>${escapeHtml(memory.content)}</p><small>${escapeHtml(memory.source || "unknown")} · ${escapeHtml(memory.id)}</small></article>`).join("") : `<div class="empty-panel">${enabled ? "当前角色还没有长期记忆" : "长期记忆模块未启用；启用后才会读取或写入。"}</div>`;
    return `<section class="memory-browser"><div class="memory-browser-heading"><div><span class="eyebrow">LONG-TERM MEMORY</span><strong>记忆浏览</strong><small>${enabled ? `当前实现：${escapeHtml(module.implementation_id)} · 允许类别：${escapeHtml(categories.join("、"))}` : "默认关闭，按模块和类别单独授权"}</small></div>${headingAction}</div>${notice}<div class="memory-list">${rows}</div></section>`;
  }

  function renderNotifications() {
    const notifications = state.events.map(notificationFromEvent).filter(Boolean);
    const filtered = state.notificationFilter === "all" ? notifications : notifications.filter((item) => item.severity === state.notificationFilter);
    const filters = [["all", "全部"], ["danger", "需要处理"], ["warning", "等待确认"], ["info", "提示"]].map(([id, label]) => `<button class="notification-filter ${state.notificationFilter === id ? "active" : ""}" type="button" data-notification-filter="${id}">${label}<b>${id === "all" ? notifications.length : notifications.filter((item) => item.severity === id).length}</b></button>`).join("");
    const body = filtered.length ? `<div class="notification-list">${filtered.map((item) => `<article class="notification-row ${item.severity}"><span class="notification-severity" aria-hidden="true"></span><div class="notification-row-main"><div><strong>${escapeHtml(item.title)}</strong><time>${formatDate(item.timestamp)}</time></div><p>${escapeHtml(item.detail)}</p><small>${escapeHtml(item.event_type)}</small></div>${item.page ? `<button class="ghost-button" type="button" data-page="${escapeHtml(item.page)}">查看</button>` : ""}</article>`).join("")}</div>` : `<div class="notification-empty"><span class="empty-icon">✓</span><strong>现在没有需要处理的通知</strong><p>重要事项会在这里出现，安静时段不会打扰当前任务。</p></div>`;
    return renderPageFrame("通知中心", "主动发现、权限申请和预算警告按严重级别归档。", `<div class="notification-toolbar">${filters}</div><div class="notification-panel">${body}</div>`);
  }

  return { renderTasks, renderHistory, renderNotifications };
}
