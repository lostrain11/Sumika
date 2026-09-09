export function createAgentView({
  AGENT_ROUTING_BUDGETS,
  AGENT_ROUTING_MODES,
  agentMetricValue,
  agentPlanModeAvailable,
  agentPromptCanSend,
  agentRetryState,
  agentRuntimeLabel,
  agentSupports,
  currentAgentSessionWorkspace,
  effectiveAgentMode,
  escapeHtml,
  formatAgentContextUsage,
  formatAgentMetricNumber,
  formatAgentTokenUsage,
  formatBudget,
  formatBytes,
  formatCostRange,
  formatTime,
  mcpCatalogStatusLabel,
  modelPolicyCostLabel,
  modelPolicyDecisionLabel,
  modelPolicyDecisionSummary,
  modelPolicyHealthLabel,
  modelPolicyLocationLabel,
  modelPolicyQuotaFor,
  modelPolicyQuotaLabel,
  renderPageFrame,
  routingBudgetLabel,
  routingModeLabel,
  selectedAgentSession,
  selectedAgentWorkspace,
  skillCatalogStatusLabel,
  state,
  supportedAgentPromptAttachments,
  workspaceRuntimePath,
  workspaceRuntimeStatusLabel,
}) {
  function renderAgentCapabilityCard(title, value, description) {
    const data = value && typeof value === "object" ? value : {};
    const entries = Array.isArray(data.skills) ? data.skills : Array.isArray(data.entries) ? data.entries : Array.isArray(value) ? value : [];
    const unavailable = data.available === false;
    const status = unavailable ? "不可用" : `${entries.length} 项`;
    const names = entries.slice(0, 4).map((entry) => {
      if (typeof entry === "string") return escapeHtml(entry);
      return escapeHtml(entry?.name || entry?.id || entry?.title || "未命名");
    }).join(" · ");
    return `<article class="agent-capability"><div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(status)}</span></div><small>${escapeHtml(description)}</small>${names ? `<code class="agent-capability-items">${names}</code>` : unavailable ? `<code class="agent-capability-items">${escapeHtml(data.error || "当前 Runtime 未提供目录")}</code>` : ""}</article>`;
  }

  function renderAgentMcpCapability(value) {
    const catalog = state.agentMcpCatalog && typeof state.agentMcpCatalog === "object" ? state.agentMcpCatalog : {};
    const useCatalog = Array.isArray(catalog.entries) && (catalog.entries.length > 0 || catalog.catalog_available === true || catalog.status === "configured");
    const data = useCatalog ? catalog : (value && typeof value === "object" ? value : {});
    const entries = Array.isArray(data.entries) ? data.entries : [];
    const tools = entries.flatMap((entry) => Array.isArray(entry?.tools) ? entry.tools : []);
    const status = data.status === "available"
      ? `${Number(data.server_count || entries.length)} 服务 · ${Number(data.tool_count || tools.length)} 工具`
      : data.status === "configured"
        ? `${Number(data.server_count || entries.length)} 项已配置`
        : data.status === "observed"
      ? `${Number(data.server_count || entries.length)} 服务 · ${Number(data.tool_count || tools.length)} 工具`
      : data.status === "unavailable" ? "不可用" : data.status === "not-exposed" ? "未暴露目录" : "尚未观察";
    const dsh = state.agentStatus?.runtime_id === "dsh";
    const packageStatus = dsh
      ? (data.client_installed ? `dsh-mcp-client ${data.client_version || "版本未知"} 已安装` : "受管 profile 尚未发现 dsh-mcp-client")
      : (data.client_installed ? `MCP client ${data.client_version || "版本未知"} 已安装` : "Runtime 未报告 MCP client");
    const names = tools.slice(0, 4).map((tool) => escapeHtml(tool?.name || tool?.tool_name || "未命名")).join(" · ");
    const detail = names || escapeHtml(data.reason || "配置、Runtime 目录和会话观察会分别标注，不会把配置存在当作健康");
    return `<article class="agent-capability" data-agent-mcp-inventory="${escapeHtml(data.status || "not-observed")}" data-agent-mcp-catalog="${useCatalog ? "merged" : "legacy"}"><div><strong>MCP</strong><span>${escapeHtml(status)}</span></div><small>${escapeHtml(packageStatus)}；来源和新鲜度以 Developer 目录为准。</small><code class="agent-capability-items">${detail}</code></article>`;
  }

  function renderAgentMcpCatalogPanel() {
    const data = state.agentMcpCatalog && typeof state.agentMcpCatalog === "object" ? state.agentMcpCatalog : {};
    const entries = Array.isArray(data.entries) ? data.entries : [];
    const rows = entries.length
      ? entries.map((entry) => {
        const tools = Array.isArray(entry.tools) ? entry.tools.slice(0, 8).map((tool) => tool?.name || tool?.tool_name).filter(Boolean).join(" · ") : "";
        const source = entry.source || (Array.isArray(entry.sources) ? entry.sources.join(" + ") : "未知来源");
        return `<div class="agent-catalog-row" data-agent-mcp-catalog-row="${escapeHtml(entry.id || entry.name || "")}"><div><strong>${escapeHtml(entry.name || entry.id || "未命名服务")}</strong><small>${escapeHtml(mcpCatalogStatusLabel(entry.status))} · ${escapeHtml(entry.freshness || "未知新鲜度")} · ${escapeHtml(source)}</small>${tools ? `<code>${escapeHtml(tools)}</code>` : ""}</div><span>${entry.enabled === false ? "已关闭" : `${Number(entry.tool_count || (entry.tools || []).length)} 工具`}</span></div>`;
      }).join("")
      : `<div class="empty-column">${escapeHtml(data.reason || "尚无 MCP 目录记录；可先在用户 Preset 中配置，或选择会话观察工具")}</div>`;
    return `<section class="dev-panel agent-mcp-catalog-panel" data-agent-mcp-catalog-panel><div class="panel-heading"><div><strong>MCP 目录</strong><small>合并 Runtime 实时目录、用户 Preset 配置和会话历史；配置存在不等于连接健康。</small></div><button class="small-button" id="refresh-agent-mcp-catalog" type="button" ${state.agentMcpCatalogBusy ? "disabled" : ""}>${state.agentMcpCatalogBusy ? "读取中" : "刷新"}</button></div><div class="agent-catalog-summary"><span>状态</span><strong>${escapeHtml(mcpCatalogStatusLabel(data.status))}</strong><span>来源</span><strong>${escapeHtml(data.observation_source || "merged")}</strong><span>服务 / 工具</span><strong>${Number(data.server_count || entries.length)} / ${Number(data.tool_count || 0)}</strong></div><div class="agent-catalog-list">${rows}</div></section>`;
  }

  function renderAgentSkillCatalogPanel() {
    const skills = Array.isArray(state.agentSkillsCatalog) ? state.agentSkillsCatalog : [];
    const busy = Boolean(state.agentSkillsBusy);
    const rows = skills.length
      ? skills.map((skill) => {
        let action = "";
         if (["discovered", "revoked"].includes(skill.state)) {
           action = `<button class="small-button" type="button" data-agent-skill-approve="${escapeHtml(skill.candidate_id)}" ${busy ? "disabled" : ""}>批准</button>`;
         } else if (skill.state === "changed") {
           action = `<span class="muted-text">请重新扫描后批准</span>`;
         } else if (skill.state === "approved") {
          action = `<button class="ghost-button" type="button" data-agent-skill-revoke="${escapeHtml(skill.candidate_id)}" ${busy ? "disabled" : ""}>撤销</button>`;
        }
        const permissions = Array.isArray(skill.permissions) && skill.permissions.length ? ` · 权限 ${skill.permissions.slice(0, 4).join(", ")}` : "";
        return `<article class="agent-skill-row" data-agent-skill-row="${escapeHtml(skill.candidate_id || "")}"><div><div class="plugin-row-heading"><strong>${escapeHtml(skill.name || skill.skill_id || "未命名 Skill")}</strong><span class="plugin-state ${escapeHtml(skill.state || "invalid")}">${escapeHtml(skillCatalogStatusLabel(skill.state))}</span></div><small>${escapeHtml(skill.description || "无描述")}${escapeHtml(permissions)} · ${escapeHtml(skill.path_label || "SKILL.md")}</small><code title="SKILL.md SHA-256">${escapeHtml(String(skill.manifest_sha256 || "").slice(0, 16))}${skill.manifest_sha256 ? "…" : ""}</code>${skill.error ? `<p class="plugin-error">${escapeHtml(skill.error)}</p>` : ""}</div><div class="agent-skill-actions">${action}</div></article>`;
      }).join("")
      : `<div class="empty-column">尚未登记用户 Skill；扫描只读取 SKILL.md 元数据，不执行正文。</div>`;
    const notice = state.agentSkillsNotice ? `<small class="agent-skill-notice" role="status">${escapeHtml(state.agentSkillsNotice)}</small>` : "";
    return `<section class="dev-panel agent-skill-catalog-panel" data-agent-skill-catalog-panel><div class="panel-heading"><div><strong>用户 Skill 管理</strong><small>仅扫描元数据和 SHA-256；第三方 Skill 不会自动安装、升级或启用。</small></div><button class="small-button" id="refresh-agent-skills" type="button" ${busy ? "disabled" : ""}>${busy === "refresh" ? "读取中" : "刷新"}</button></div><div class="agent-skill-scan-form"><input id="agent-skills-path" type="text" value="${escapeHtml(state.agentSkillsPath)}" placeholder="可选：.agents/skills 或 SKILL.md 的绝对路径" aria-label="Skill 扫描路径" /><button class="outline-button" id="discover-agent-skills" type="button" ${busy ? "disabled" : ""}>${busy === "discover" ? "扫描中" : "扫描元数据"}</button></div>${notice}<div class="agent-skill-list">${rows}</div></section>`;
  }

  function renderAgentTool(tool) {
    const call = tool?.call && typeof tool.call === "object" ? tool.call : null;
    const result = tool?.result && typeof tool.result === "object" ? tool.result : null;
    const title = call?.title || result?.title || tool?.name || "tool";
    const status = tool?.status || "未知";
    const locationList = [...(call?.locations || []), ...(result?.locations || [])]
      .slice(0, 4)
      .map((location) => `${location.path || ""}${location.line ? `:${location.line}` : ""}`)
      .filter(Boolean)
      .join(" · ");
    const detail = [
      call?.card ? `调用 ${call.card}` : "",
      result?.card ? `结果 ${result.card}` : "",
      result?.exit_code !== undefined ? `退出码 ${result.exit_code}` : "",
      result?.status_code !== undefined ? `HTTP ${result.status_code}` : "",
      locationList,
    ].filter(Boolean).join(" · ");
    const resultText = result?.output || (result?.sources?.length ? `${result.sources.length} 个来源` : "");
    return `<details class="agent-tool-card"><summary><span>${escapeHtml(title)}</span><small>${escapeHtml(status)}</small></summary><div class="agent-tool-detail">${detail ? `<span>${escapeHtml(detail)}</span>` : ""}${resultText ? `<code>${escapeHtml(resultText)}</code>` : ""}</div></details>`;
  }

  function renderAgentQueue(queue) {
    const value = queue && typeof queue === "object" ? queue : {};
    const items = Array.isArray(value.items) ? value.items : [];
    if (!value.known) {
      return `<div class="agent-queue-empty">等待 Runtime 的队列快照；这里是待发送队列，不是聊天历史。</div>`;
    }
    const rows = items.length ? items.map((item) => {
      const placement = item.placement === "steering" ? "steer" : "queued";
      const draft = Object.prototype.hasOwnProperty.call(state.agentQueueDrafts, item.id) ? state.agentQueueDrafts[item.id] : (item.text || "");
      const controls = [
        item.editable ? `<div class="agent-queue-edit"><input data-agent-queue-input type="text" maxlength="12000" value="${escapeHtml(draft)}" aria-label="编辑待发送消息" /><button class="ghost-button" type="button" data-agent-queue-action="edit" data-agent-queue-id="${escapeHtml(item.id)}" ${state.agentBusy ? "disabled" : ""}>保存</button></div>` : "",
        item.can_steer ? `<button class="ghost-button" type="button" data-agent-queue-action="steer" data-agent-queue-id="${escapeHtml(item.id)}" ${state.agentBusy ? "disabled" : ""}>立即 steer</button>` : "",
        item.can_remove ? `<button class="ghost-button" type="button" data-agent-queue-action="remove" data-agent-queue-id="${escapeHtml(item.id)}" ${state.agentBusy ? "disabled" : ""}>移除</button>` : "",
      ].filter(Boolean).join("");
      return `<article class="agent-queue-row" data-agent-queue-row="${escapeHtml(item.id)}"><div class="agent-queue-copy"><div><strong>${escapeHtml(placement)}</strong><code>${escapeHtml(item.id)}</code></div><p>${escapeHtml(item.text || (item.attachment_count ? `${item.attachment_count} 个附件` : "不可编辑内容"))}</p></div><div class="agent-queue-actions">${controls}</div></article>`;
    }).join("") : `<div class="agent-queue-empty">当前没有待发送项目。</div>`;
    const hidden = Number(value.hidden_context_count || 0);
    return `${rows}${hidden ? `<small class="agent-queue-note">另有 ${hidden} 项 Runtime context 隐藏，不会显示或编辑。</small>` : ""}`;
  }

  function renderAgentMessage(message) {
    const role = message?.role === "assistant" ? "Agent" : "你";
    const content = message?.content || "";
    const attachments = agentSupports("attachments") && Array.isArray(message?.attachments) ? message.attachments : [];
    const mediaRows = attachments.map((attachment) => {
      const id = attachment.attachment_id || "";
      const preview = state.agentAttachmentPreviews[id];
      const busy = state.agentAttachmentBusy === id;
      if (preview) return `<img class="agent-message-image" src="${escapeHtml(preview)}" alt="${escapeHtml(attachment.name || "会话图片")}" loading="lazy" />`;
      return `<button class="ghost-button agent-message-attachment" type="button" data-agent-attachment-load="${escapeHtml(id)}" data-agent-attachment-session="${escapeHtml(message.session_id || state.agentSessionId || "")}" ${busy ? "disabled" : ""}>${busy ? "读取中" : "查看图片"}${attachment.name ? ` · ${escapeHtml(attachment.name)}` : ""}</button>`;
    }).join("");
    return `<div class="agent-message-row"><span class="agent-message-role">${role}</span><div>${content ? `<p>${escapeHtml(content)}</p>` : ""}${mediaRows ? `<div class="agent-message-media">${mediaRows}</div>` : ""}</div></div>`;
  }

  function renderAgentArtifact(item) {
    const locations = Array.isArray(item?.locations) ? item.locations.filter((entry) => entry?.path).slice(0, 6) : [];
    const fileCount = Number.isInteger(item?.file_count) ? item.file_count : locations.length;
    const detail = locations.map((entry) => entry.path).join(" · ");
    return `<div class="agent-artifact-row"><div><strong>${escapeHtml(item?.label || item?.type || "产物")}</strong><span>${escapeHtml(item?.status || "可用")}${fileCount ? ` · ${fileCount} 个文件` : ""}</span></div>${detail ? `<small title="${escapeHtml(detail)}">${escapeHtml(detail)}</small>` : ""}</div>`;
  }

  function renderAgentTurnLedger(turns) {
    const values = Array.isArray(turns) ? turns.filter((item) => item && typeof item === "object").slice(-8) : [];
    if (!values.length) return `<div class="agent-turn-empty muted-text">暂无回合摘要</div>`;
    const statusLabels = {
      running: "运行中",
      completed: "已完成",
      cancelled: "已停止",
      aborted: "已中断",
      failed: "失败",
      error: "错误",
      interrupted: "已中断",
      stopped: "已停止",
    };
    const modeLabels = { plan: "Plan", execute: "Execute", readonly: "Readonly" };
    const rows = values.map((item, index) => {
      const status = String(item.status || "running").toLowerCase();
      const mode = modeLabels[String(item.mode || "").toLowerCase()] || "";
      const label = item.turn !== undefined && item.turn !== null ? `回合 ${item.turn}` : `回合 ${index + 1}`;
      const counts = [
        [`${Number(item.steps) || 0}`, "步骤"],
        [`${Number(item.tools) || 0}`, "工具"],
        [`${Number(item.approvals) || 0}`, "审批"],
        [`${Number(item.artifacts) || 0}`, "产物"],
      ].map(([value, name]) => `${value} ${name}`).join(" · ");
      return `<li data-agent-turn-status="${escapeHtml(status)}"><div><strong>${escapeHtml(label)}</strong><span>${escapeHtml(statusLabels[status] || "进行中")}${mode ? ` · ${escapeHtml(mode)}` : ""}</span></div><small>${escapeHtml(counts)}</small></li>`;
    }).join("");
    return `<div class="agent-turn-ledger" data-agent-turn-ledger><div class="agent-subsection-heading"><strong>最近回合</strong><span>${values.length} 个</span></div><ol>${rows}</ol></div>`;
  }

  function renderAgentRuntimeMetrics(snapshot) {
    const stats = snapshot?.stats && typeof snapshot.stats === "object" ? snapshot.stats : {};
    const usage = snapshot?.token_usage && typeof snapshot.token_usage === "object" ? snapshot.token_usage : {};
    const context = snapshot?.context && typeof snapshot.context === "object" ? snapshot.context : {};
    const breakdown = snapshot?.context_breakdown && typeof snapshot.context_breakdown === "object" ? snapshot.context_breakdown : {};
    const statFields = [
      ["turns", "回合"],
      ["steps", "步骤"],
      ["ttftMs", "首 token"],
      ["decodeMs", "生成耗时"],
      ["llmMs", "模型耗时"],
      ["toolMs", "工具耗时"],
      ["decodeTokens", "生成速率基数"],
    ];
    const statRows = statFields.map(([key, label]) => {
      const value = agentMetricValue(stats, key);
      if (value === null) return "";
      const suffix = key.endsWith("Ms") ? " ms" : "";
      return `<div><span>${label}</span><strong>${escapeHtml(`${formatAgentMetricNumber(value)}${suffix}`)}</strong></div>`;
    }).filter(Boolean).join("");
    const tokenText = formatAgentTokenUsage(usage);
    const contextText = formatAgentContextUsage(context);
    const breakdownFields = [
      ["systemTokens", "系统"],
      ["toolsTokens", "工具定义"],
      ["messageTokens", "消息"],
    ];
    const breakdownText = breakdownFields.map(([key, label]) => {
      const value = agentMetricValue(breakdown, key);
      return value === null ? "" : `${label} ${formatAgentMetricNumber(value)}`;
    }).filter(Boolean).join(" · ");
    const budget = snapshot?.budget && typeof snapshot.budget === "object" ? snapshot.budget : null;
    const budgetText = budget
      ? formatBudget(budget)
      : "预算未提供";
    const reason = budget && budget.available === false ? budget.reason : "";
    const statBody = statRows || `<div><span>运行统计</span><strong>暂无</strong></div>`;
    const tokenBody = tokenText || "暂无 token 使用量";
    const contextBody = contextText || "暂无上下文占用数据";
    return `<div class="agent-metric-groups">
      <div class="agent-metric-group agent-runtime-stats"><div class="agent-metric-label">运行统计</div><div class="diagnostic-grid">${statBody}</div></div>
      <div class="agent-metric-group agent-token-usage" data-agent-token-usage><div class="agent-metric-label">Token 使用量</div><strong>${escapeHtml(tokenBody)}</strong></div>
      <div class="agent-metric-group agent-context-usage" data-agent-context-usage><div class="agent-metric-label">上下文占用</div><strong>${escapeHtml(contextBody)}</strong>${breakdownText ? `<small>${escapeHtml(breakdownText)}</small>` : ""}</div>
      <div class="agent-metric-group agent-budget-status" data-agent-budget-status><div class="agent-metric-label">任务预算</div><strong>${escapeHtml(budgetText)}</strong>${reason ? `<small>${escapeHtml(reason)}</small>` : ""}</div>
    </div>`;
  }

  function renderAgentSessionPanel(snapshot) {
    if (!snapshot) {
      const projections = agentSupports("plan") ? "计划、最终消息、工具调用和运行统计" : "最终消息、工具调用和运行统计";
      return `<section class="agent-panel agent-session-panel"><div class="panel-heading"><div><strong>当前会话</strong><small>新建 Agent 会话后，这里显示${projections}。</small></div></div><div class="empty-column">尚未创建 Agent 会话</div></section>`;
    }
    const plan = snapshot.plan || { active: false, pending: false, steps: [] };
    const messages = Array.isArray(snapshot.messages) ? snapshot.messages : [];
    const tools = Array.isArray(snapshot.tools) ? snapshot.tools : [];
    const approvals = Array.isArray(snapshot.approvals) ? snapshot.approvals : [];
    const artifacts = Array.isArray(snapshot.artifacts) ? snapshot.artifacts : [];
    const stateLabel = ({ running: "运行中", completed: "已完成", cancelled: "已停止", error: "失败", idle: "空闲", unavailable: "暂不可读" })[snapshot.state] || snapshot.state || "未知";
    const steps = Array.isArray(plan.steps) && plan.steps.length ? plan.steps.slice(0, 8).map((step) => `<li><span class="plan-step-status">${escapeHtml(step.status || "未知")}</span><span>${escapeHtml(step.title || "未命名步骤")}</span></li>`).join("") : `<li class="muted-text">Runtime 尚未返回可展示的计划步骤</li>`;
    const messageRows = messages.length ? messages.slice(-8).map((message) => renderAgentMessage({ ...message, session_id: snapshot.session_id })).join("") : `<div class="empty-column">尚未收到可展示的消息</div>`;
    const toolRows = tools.length ? tools.slice(-8).map(renderAgentTool).join("") : `<span class="muted-text">暂无工具调用</span>`;
    const approvalRows = approvals.length ? approvals.slice(-6).map((item) => `<span class="agent-chip ${item.status === "pending" ? "pending" : ""}">${escapeHtml(item.action || "需要确认")} · ${escapeHtml(item.status || "未知")}</span>`).join("") : `<span class="muted-text">暂无审批记录</span>`;
    const artifactRows = artifacts.length ? artifacts.slice(-6).map(renderAgentArtifact).join("") : `<span class="muted-text">当前会话没有可展示的 diff 摘要</span>`;
    const running = snapshot.state === "running";
    const retry = agentRetryState(snapshot);
    const retryAction = retry.retryable
      ? retry.imageTarget
        ? `<span class="agent-retry-hint" role="status">最近目标含图片，请重新附加图片</span>`
        : retry.missingTarget
          ? `<span class="agent-retry-hint" role="status">未找到可重试的文本目标</span>`
          : `<button class="small-button" id="agent-retry-turn" type="button" title="重新提交最近一次失败或停止的文本目标" ${state.agentBusy ? "disabled" : ""}>重试最近目标</button>`
      : "";
    const historyAction = state.agentHistoryHasMore && state.agentHistoryBeforeSeq !== null
      ? `<button class="ghost-button agent-history-load-older" id="agent-load-older" type="button" ${state.agentHistoryLoading || state.agentBusy ? "disabled" : ""}>${state.agentHistoryLoading ? "加载中…" : "加载更早消息"}</button>`
      : "";
    const sessionTitle = snapshot.title || snapshot.session_id || "Agent session";
    const titleDraft = state.agentSessionRenameDraft || sessionTitle;
    const renameEditor = agentSupports("session-rename") ? `<div class="agent-session-title-editor"><input id="agent-session-title" type="text" maxlength="240" value="${escapeHtml(titleDraft)}" aria-label="Agent 会话标题" /><button class="ghost-button" id="agent-session-rename" type="button" ${state.agentBusy ? "disabled" : ""}>保存名称</button></div>` : "";
    const exportUrl = `/api/agent/session.export?session_id=${encodeURIComponent(snapshot.session_id || "")}&include_descendants=true`;
    const exportAction = agentSupports("raw-export") ? `<a class="ghost-button" id="agent-export-session" href="${escapeHtml(exportUrl)}" download title="导出 Runtime 原始会话日志、附件和子 Agent 日志">导出原始日志</a>` : "";
    const forkAction = agentSupports("session-fork") ? `<button class="ghost-button" id="agent-fork-session" type="button" title="从最近完成回合创建新会话；原会话保持不变" ${!running && !state.agentBusy ? "" : "disabled"}>创建分支</button>` : "";
    const planSection = agentSupports("plan") ? `<div class="agent-subsection"><div class="agent-subsection-heading"><strong>Plan</strong><span>${plan.active ? "进行中" : plan.pending ? "待确认" : "无活动计划"}</span></div><ol class="agent-plan-list">${steps}</ol></div>` : "";
    const queueSection = agentSupports("queue") ? `<div class="agent-subsection agent-queue-subsection"><div class="agent-subsection-heading"><strong>待发送队列</strong><span>${state.agentQueue.known ? `${state.agentQueue.items.length} 项` : "等待快照"}</span></div><small class="agent-queue-intro">Runtime 的瞬时 inbox；编辑、移除和 steer 不会改写聊天历史。</small><div class="agent-queue-list">${renderAgentQueue(state.agentQueue)}</div></div>` : "";
    return `<section class="agent-panel agent-session-panel"><div class="panel-heading"><div><strong>当前会话 · ${escapeHtml(stateLabel)}</strong><span class="agent-session-visible-title" aria-live="polite">${escapeHtml(sessionTitle)}</span><small>${escapeHtml(snapshot.session_id || "Agent session")}</small>${renameEditor}</div><div class="agent-session-actions">${retryAction}<button class="small-button" id="agent-refresh-session" type="button" ${state.agentBusy ? "disabled" : ""}>刷新</button>${exportAction}${forkAction}<button class="ghost-button" id="agent-cancel-turn" type="button" ${running && !state.agentBusy ? "" : "disabled"}>停止回合</button></div></div><div class="agent-session-grid"><div class="agent-session-main">${planSection}<div class="agent-subsection"><div class="agent-subsection-heading"><strong>最近消息</strong><span>${messages.length} 条</span>${historyAction}</div><div class="agent-message-list">${messageRows}</div></div>${queueSection}</div><aside class="agent-session-meta"><div class="agent-subsection">${renderAgentRuntimeMetrics(snapshot)}</div><div class="agent-subsection">${renderAgentTurnLedger(snapshot.turns)}</div><div class="agent-subsection"><div class="agent-subsection-heading"><strong>工具</strong></div><div class="agent-tool-list">${toolRows}</div></div><div class="agent-subsection"><div class="agent-subsection-heading"><strong>审批</strong></div><div class="agent-chip-list">${approvalRows}</div></div><div class="agent-subsection"><div class="agent-subsection-heading"><strong>产物 / diff</strong></div><div class="agent-artifact-list">${artifactRows}</div></div></aside></div></section>`;
  }

  function renderAgentWorkspacePanel(status) {
    if (!agentSupports("workspaces")) return "";
    const options = [`<option value="">请先登记并选择 Workspace</option>`, ...state.agentWorkspaces.map((workspace) => `<option value="${escapeHtml(workspace.id)}" ${workspace.id === state.agentWorkspaceId ? "selected" : ""}>${escapeHtml(workspace.title || workspace.path)} · ${escapeHtml(workspace.path)}</option>`)].join("");
    const selected = state.agentWorkspaces.find((workspace) => workspace.id === state.agentWorkspaceId);
    return `<section class="agent-panel agent-workspace-panel"><div class="panel-heading"><div><strong>Agent 工作区</strong><small>登记已有目录后，新会话会归入该 Workspace；Sumika 不创建、移动或删除目录。</small></div><button class="small-button" id="agent-refresh-workspaces" type="button" ${status.ready && !state.agentBusy ? "" : "disabled"}>刷新</button></div><label class="agent-workspace-select"><span>新会话位置</span><select id="agent-workspace-select" ${status.ready && !state.agentBusy ? "" : "disabled"}>${options}</select></label><div class="agent-workspace-form"><input id="agent-workspace-path" type="text" value="${escapeHtml(state.agentWorkspacePath)}" placeholder="输入已存在目录的绝对路径" aria-label="登记已有 Agent 工作区路径" /><button class="outline-button" id="agent-register-workspace" type="button" ${status.ready && state.agentWorkspacePath.trim() && !state.agentBusy ? "" : "disabled"}>登记目录</button></div>${selected ? `<small class="agent-workspace-current">当前：${escapeHtml(selected.title)} · ${escapeHtml(selected.session_ids?.length || 0)} 个会话</small>` : ""}</section>`;
  }

  function renderWorkspaceRuntimePanel() {
    const path = workspaceRuntimePath();
    const inspect = state.workspaceRuntimeInspect;
    const workspace = inspect?.workspace;
    const checkpoints = Array.isArray(state.workspaceRuntimeCheckpoints) ? state.workspaceRuntimeCheckpoints : [];
    const selected = checkpoints.find((item) => item.id === state.workspaceRuntimeSelectedId);
    const diff = state.workspaceRuntimeDiff;
    const preview = state.workspaceRuntimePreview;
    const busy = Boolean(state.workspaceRuntimeBusy);
    const notice = state.workspaceRuntimeNotice ? `<div class="workspace-runtime-notice" role="status">${escapeHtml(state.workspaceRuntimeNotice)}</div>` : "";
    const rows = checkpoints.length
      ? checkpoints.map((item) => `<button class="workspace-checkpoint-row ${item.id === state.workspaceRuntimeSelectedId ? "active" : ""}" type="button" data-workspace-checkpoint="${escapeHtml(item.id)}"><span><strong>${escapeHtml(item.name || "Agent checkpoint")}</strong><small>${escapeHtml(formatTime(item.created_at))} · ${escapeHtml(item.branch || "(detached)")}</small></span><span><em>${escapeHtml(item.file_count ?? 0)} 文件</em><code>${escapeHtml(String(item.id || "").slice(0, 16))}</code></span></button>`).join("")
      : `<div class="workspace-runtime-empty">尚未创建 checkpoint</div>`;
    const diffRows = diff?.files?.length
      ? diff.files.map((item) => `<div class="workspace-diff-row"><code>${escapeHtml(item.path)}</code><span class="workspace-diff-${escapeHtml(item.status)}">${escapeHtml(({ added: "新增", removed: "移除", changed: "修改" })[item.status] || item.status || "变化")}</span></div>`).join("")
      : `<div class="workspace-runtime-empty">当前 checkpoint 与工作区一致</div>`;
    const diffSection = selected && diff ? `<div class="workspace-runtime-diff"><div class="workspace-runtime-subheading"><strong>摘要 diff</strong><span>${diff.changed ? `变更 ${escapeHtml(diff.counts?.changed_total ?? 0)} 项${diff.files_truncated ? " · 列表已截断" : ""}` : "无变更"}</span></div><div class="workspace-diff-list">${diffRows}</div>${preview ? `<div class="workspace-restore-preview"><strong>恢复预览</strong><span>将归档 ${escapeHtml(preview.restore?.archive_count ?? 0)} 项，写回 ${escapeHtml(preview.restore?.write_count ?? 0)} 项</span><button class="small-button" type="button" data-workspace-restore="${escapeHtml(selected.id)}" ${busy ? "disabled" : ""}>批准并恢复</button></div>` : `<button class="ghost-button workspace-preview-button" type="button" data-workspace-preview="${escapeHtml(selected.id)}" ${busy ? "disabled" : ""}>预览恢复影响</button>`}</div>` : "";
    const worktreePreview = state.workspaceRuntimeWorktreePreview;
    const worktreeReady = path && state.workspaceRuntimeWorktreeDestination.trim() && state.workspaceRuntimeWorktreeBranch.trim() && !busy;
    const worktreeSection = `<div class="workspace-runtime-operation"><div class="workspace-runtime-subheading"><strong>独立 worktree</strong><span>从当前 HEAD 创建，不带入源目录未提交变更</span></div><div class="workspace-worktree-form"><label><span>目标目录</span><input id="workspace-worktree-destination" type="text" value="${escapeHtml(state.workspaceRuntimeWorktreeDestination)}" placeholder="输入尚不存在的绝对路径" /></label><label><span>新分支</span><input id="workspace-worktree-branch" type="text" maxlength="240" value="${escapeHtml(state.workspaceRuntimeWorktreeBranch)}" placeholder="codex/feature-name" /></label><button class="ghost-button" id="workspace-worktree-preview" type="button" ${worktreeReady ? "" : "disabled"}>预览创建</button></div>${worktreePreview ? `<div class="workspace-operation-preview"><div><strong>${escapeHtml(worktreePreview.worktree?.branch || "新分支")}</strong><code>${escapeHtml(worktreePreview.worktree?.path || "")}</code><small>${worktreePreview.source?.dirty ? "源目录有未提交变更；这些内容不会进入新 worktree。" : "源目录干净；新 worktree 从当前 HEAD 创建。"}</small></div><button class="small-button" id="workspace-worktree-create" type="button" ${busy ? "disabled" : ""}>批准创建</button></div>` : ""}</div>`;
    const commitPreview = state.workspaceRuntimeCommitPreview;
    const commitReady = selected?.baseline_clean === true && state.workspaceRuntimeCommitMessage.trim() && !busy;
    const omittedFiles = Array.isArray(commitPreview?.patch_omitted_files) ? commitPreview.patch_omitted_files : [];
    const patchBody = commitPreview?.patch || "没有可展示的 UTF-8 文本 patch；请检查上方文件摘要和省略项。";
    const commitSection = `<div class="workspace-runtime-operation"><div class="workspace-runtime-subheading"><strong>本地 Git 提交</strong><span>仅限干净 checkpoint 后的变化 · 不运行 hooks · 不签名 · 不 push</span></div><div class="workspace-commit-form"><textarea id="workspace-commit-message" rows="2" maxlength="4000" placeholder="输入 commit message" ${selected?.baseline_clean === true ? "" : "disabled"}>${escapeHtml(state.workspaceRuntimeCommitMessage)}</textarea><button class="ghost-button" id="workspace-commit-preview" type="button" ${commitReady ? "" : "disabled"}>审阅 patch</button></div>${selected && selected.baseline_clean !== true ? `<small class="workspace-operation-warning">当前 checkpoint 不是干净 Git 基线，不能用于提交；请在干净 worktree 中重新创建 checkpoint。</small>` : ""}${commitPreview ? `<div class="workspace-commit-preview"><div class="workspace-runtime-subheading"><strong>${escapeHtml(commitPreview.message_summary || "Commit preview")}</strong><span>${escapeHtml(commitPreview.counts?.changed_total ?? 0)} 个路径${commitPreview.patch_truncated ? " · patch 已截断" : ""}${omittedFiles.length ? ` · ${escapeHtml(omittedFiles.length)} 个文件未展示正文` : ""}</span></div>${omittedFiles.length ? `<div class="workspace-patch-omitted">未展示：${omittedFiles.map((item) => `<code>${escapeHtml(item)}</code>`).join(" ")}</div>` : ""}<pre class="workspace-patch" tabindex="0">${escapeHtml(patchBody)}</pre><div class="workspace-commit-actions"><span>分支 <code>${escapeHtml(commitPreview.workspace?.branch || "")}</code></span><button class="small-button" id="workspace-commit-create" type="button" ${busy ? "disabled" : ""}>批准本地提交</button></div></div>` : ""}</div>`;
    return `<section class="agent-panel workspace-runtime-panel"><div class="panel-heading"><div><strong>Workspace 安全与回滚</strong><small>只记录 Git 文件摘要；恢复前自动保存当前状态并归档将被覆盖的文件。</small></div><span class="agent-chip ${workspace?.dirty ? "pending" : ""}">${escapeHtml(workspaceRuntimeStatusLabel(workspace))}</span></div>${notice}<div class="workspace-runtime-path"><label><span>Git 工作区路径</span><input id="workspace-runtime-path" type="text" value="${escapeHtml(path)}" placeholder="输入已有 Git 仓库的绝对路径" aria-label="Workspace 安全操作路径" /></label><div class="workspace-runtime-actions"><button class="small-button" id="workspace-runtime-inspect" type="button" ${path && !busy ? "" : "disabled"}>检查状态</button><button class="outline-button" id="workspace-runtime-create" type="button" ${path && !busy ? "" : "disabled"}>创建 checkpoint</button></div></div>${workspace ? `<div class="workspace-runtime-meta"><span>${escapeHtml(workspace.title || "Git workspace")}</span><code>${escapeHtml(workspace.branch || "(detached)")}</code><span>HEAD ${escapeHtml(String(workspace.head || "").slice(0, 12) || "-")}</span><span>${escapeHtml(inspect?.checkpoint_count ?? checkpoints.length)} 个 checkpoint</span></div>` : ""}<div class="workspace-checkpoint-form"><input id="workspace-runtime-name" type="text" maxlength="200" value="${escapeHtml(state.workspaceRuntimeCheckpointName)}" placeholder="checkpoint 名称（可选）" aria-label="Checkpoint 名称" /><button class="ghost-button" id="workspace-runtime-refresh" type="button" ${path && !busy ? "" : "disabled"}>刷新列表</button></div><div class="workspace-checkpoint-list">${rows}</div>${diffSection}${worktreeSection}${commitSection}</section>`;
  }

  function renderAgentModelPanel(status) {
    if (!agentSupports("models")) return "";
    const runtimeLabel = agentRuntimeLabel();
    const catalog = state.agentModels || { current: {}, groups: [], failures: [] };
    const current = catalog.current || {};
    const rows = [];
    for (const group of Array.isArray(catalog.groups) ? catalog.groups : []) {
      for (const model of Array.isArray(group.models) ? group.models : []) {
        const selected = group.id === current.provider && model.id === current.model;
        const defaultEffort = model.reasoning?.default_effort || "";
        rows.push(`<option value="${rows.length}" data-agent-provider="${escapeHtml(group.id)}" data-agent-model="${escapeHtml(model.id)}" data-agent-reasoning="${escapeHtml(defaultEffort)}" ${selected ? "selected" : ""}>${escapeHtml(group.name || group.id)} · ${escapeHtml(model.name || model.id)}</option>`);
      }
    }
    const knownCurrent = (catalog.groups || []).some((group) => group.id === current.provider && (group.models || []).some((model) => model.id === current.model));
    if (current.provider && current.model && !knownCurrent) {
      rows.unshift(`<option value="current" data-agent-provider="${escapeHtml(current.provider)}" data-agent-model="${escapeHtml(current.model)}" selected>${escapeHtml(current.provider)} · ${escapeHtml(current.model)}（当前）</option>`);
    }
    const stateLabel = catalog.routable ? "可路由" : state.agentSessionId ? "当前模型不可路由" : "选择会话后加载";
    return `<section class="agent-panel agent-model-panel"><div class="panel-heading"><div><strong>会话模型</strong><small>目录来自 ${escapeHtml(runtimeLabel)} <code>session.models</code>；切换只影响当前 Agent 会话。</small></div><span class="agent-chip ${catalog.routable ? "" : "pending"}">${escapeHtml(stateLabel)}</span></div><label class="agent-model-select"><span>Provider / Model</span><select id="agent-model-select" ${status.ready && state.agentSessionId && rows.length && !state.agentBusy ? "" : "disabled"}>${rows.join("") || `<option>暂无可用模型</option>`}</select></label>${catalog.failures?.length ? `<small class="agent-mode-warning">${escapeHtml(catalog.failures.length)} 个 Provider 目录加载失败；其余可用项不受影响。</small>` : ""}</section>`;
  }

  function renderModelPolicyCostEstimate(estimate) {
    if (!estimate || typeof estimate !== "object") return `<div class="agent-routing-cost-estimate unknown"><span>预计站内扣费</span><strong>未知</strong><span>预计现金成本</span><strong>未知</strong></div>`;
    const provider = estimate.status === "known"
      ? formatCostRange(estimate.provider_charge_min, estimate.provider_charge_max, estimate.provider_currency)
      : "未知";
    const cash = estimate.status === "known" && (estimate.cash_min != null || estimate.cash_max != null)
      ? formatCostRange(estimate.cash_min, estimate.cash_max, estimate.cash_currency)
      : "未知";
    const reasons = Array.isArray(estimate.unknown_reasons) ? estimate.unknown_reasons.join("、") : "";
    return `<div class="agent-routing-cost-estimate ${estimate.status === "known" ? "known" : "unknown"}" data-agent-cost-estimate><span>预计站内扣费</span><strong>${escapeHtml(provider)}</strong><span>预计现金成本</span><strong>${escapeHtml(cash)}</strong>${reasons ? `<small>${escapeHtml(reasons)}</small>` : ""}</div>`;
  }

  function renderAgentRoutingPanel(status) {
    if (!status || (!status.ready && !state.agentModelPolicyCatalog)) return "";
    const catalog = state.agentModelPolicyCatalog || {};
    const entries = Array.isArray(catalog.entries) ? catalog.entries : [];
    const routable = entries.filter((item) => item?.routable === true).length;
    const decision = state.agentRoutingDecision?.decision || null;
    const decisionKey = state.agentRoutingDecisionKey;
    const pending = Boolean(decision && state.agentRoutingPendingKey && state.agentRoutingPendingKey === decisionKey);
    const mode = AGENT_ROUTING_MODES.has(state.agentRoutingMode) ? state.agentRoutingMode : "manual";
    const budget = AGENT_ROUTING_BUDGETS.has(state.agentRoutingBudgetPolicy) ? state.agentRoutingBudgetPolicy : "prefer-free";
    const entryRows = entries.slice(0, 12).map((entry) => {
      const quota = modelPolicyQuotaFor(entry.route_id);
      const stateClass = entry.routable === true ? "ready" : "pending";
      return `<li class="agent-routing-entry ${stateClass}"><div><strong>${escapeHtml(entry.display_name || `${entry.provider_id} · ${entry.model_id}`)}</strong><small>${escapeHtml(modelPolicyLocationLabel(entry.processing_location))} · ${escapeHtml(modelPolicyCostLabel(entry.cost_class))} · ${escapeHtml(entry.quality_tier || "质量未知")}</small></div><span>${escapeHtml(modelPolicyHealthLabel(entry))}${quota ? `<small>${escapeHtml(modelPolicyQuotaLabel(quota))}</small>` : ""}</span></li>`;
    }).join("");
    const catalogStatus = state.agentModelPolicyBusy
      ? "读取中"
      : state.agentModelPolicyCatalog
        ? `${routable} / ${entries.length} 个候选可路由`
        : "尚未读取";
    const decisionActions = pending
      ? `<div class="agent-routing-confirm" role="group" aria-label="模型策略确认"><button class="small-button" id="agent-routing-confirm" type="button" ${state.agentBusy ? "disabled" : ""}>确认并继续</button><button class="ghost-button" id="agent-routing-cancel" type="button" ${state.agentBusy ? "disabled" : ""}>取消</button></div>`
      : "";
    const decisionBlock = decision
      ? `<div class="agent-routing-decision ${pending ? "pending" : ""}" data-agent-routing-decision="${escapeHtml(decision.status || "unknown")}"><div class="agent-routing-decision-heading"><strong>${escapeHtml(modelPolicyDecisionLabel(decision))}</strong><span>${escapeHtml(decision.requires_confirmation ? "需要确认" : "可自动继续")}</span></div><p>${escapeHtml(modelPolicyDecisionSummary(decision))}</p>${renderModelPolicyCostEstimate(decision.cost_estimate)}<small>质量门槛：${escapeHtml(decision.quality_gate?.required || "未知")} · 置信度 ${(Number(decision.confidence || 0) * 100).toFixed(0)}% · ${escapeHtml(decision.quota_impact?.state || "额度未知")}</small>${decision.alternatives?.length ? `<details><summary>其他候选（${decision.alternatives.length}）</summary><ul>${decision.alternatives.slice(0, 4).map((item) => `<li>${escapeHtml(item.display_name || `${item.provider_id} · ${item.model_id}`)} · ${escapeHtml(modelPolicyCostLabel(item.cost_class))}</li>`).join("")}</ul></details>` : ""}${decisionActions}</div>`
      : "";
    const notice = state.agentRoutingNotice ? `<div class="agent-routing-notice" role="status">${escapeHtml(state.agentRoutingNotice)}</div>` : "";
    return `<section class="agent-panel agent-routing-panel" data-agent-routing-panel><div class="panel-heading"><div><strong>模型策略</strong><small>发送前按安全、隐私、能力、质量、额度和成本排序；手动模式沿用模块页当前连接。</small></div><span class="agent-chip ${routable ? "" : "pending"}" data-agent-routing-catalog-status>${escapeHtml(catalogStatus)}</span></div><div class="agent-routing-controls"><label><span>选择策略</span><select id="agent-routing-mode"><option value="manual" ${mode === "manual" ? "selected" : ""}>手动</option><option value="recommendation-then-confirmation" ${mode === "recommendation-then-confirmation" ? "selected" : ""}>推荐后确认</option><option value="automatic" ${mode === "automatic" ? "selected" : ""}>自动（遵守硬门槛）</option></select></label><label><span>预算偏好</span><select id="agent-routing-budget"><option value="prefer-free" ${budget === "prefer-free" ? "selected" : ""}>优先免费 / 本地</option><option value="free-only" ${budget === "free-only" ? "selected" : ""}>仅免费 / 本地</option><option value="allow-paid" ${budget === "allow-paid" ? "selected" : ""}>允许付费（仍需确认）</option><option value="no-paid" ${budget === "no-paid" ? "selected" : ""}>禁止付费</option></select></label><div class="agent-routing-actions"><button class="ghost-button" id="agent-routing-refresh" type="button" ${state.agentModelPolicyBusy ? "disabled" : ""}>刷新目录</button><button class="ghost-button" id="agent-routing-quota" type="button" ${state.agentModelPolicyBusy ? "disabled" : ""}>刷新额度</button></div></div><div class="agent-routing-meta"><span>当前：${escapeHtml(routingModeLabel(mode))}</span><span>${escapeHtml(routingBudgetLabel(budget))}</span><span>最近检查：${escapeHtml(formatTime(catalog.checked_at || state.agentModelPolicyQuota?.checked_at))}</span></div>${notice}${decisionBlock}${entries.length ? `<details class="agent-routing-catalog"><summary>候选目录（${entries.length}）</summary><ul>${entryRows}</ul></details>` : `<div class="empty-column">暂无候选。请先在模块页配置并启用真实 Provider，或连接受管 Agent Runtime。</div>`}</section>`;
  }

  function renderAgentPlanReviewInteraction(item) {
    const questions = Array.isArray(item.questions) ? item.questions : [];
    const question = questions.find((entry) => entry?.intent?.kind === "plan-review") || questions[0] || {};
    const planReview = item.plan_review || {};
    const approve = String(planReview.approve || question.intent?.approve || "Approve");
    const keepPlanning = String(planReview.keep_planning || "Keep planning");
    const drafts = state.agentInteractionDrafts[item.id] || {};
    const detail = question.detail || question.question || "运行时没有提供计划详情。";
    return `<article class="agent-interaction plan-review-interaction" data-agent-plan-review data-agent-interaction-id="${escapeHtml(item.id)}" data-agent-interaction-session="${escapeHtml(item.session_id)}"><div class="agent-interaction-heading"><div><strong>计划审查</strong><small>${escapeHtml(agentRuntimeLabel())} 已暂停，等待确认后才会离开 Plan 模式。</small></div><span class="agent-chip pending">待确认</span></div><div class="agent-plan-review-question">${question.header ? `<strong>${escapeHtml(question.header)}</strong>` : ""}${question.question ? `<p>${escapeHtml(question.question)}</p>` : ""}</div><div class="agent-plan-review-body"><pre class="agent-plan-review-detail">${escapeHtml(detail)}</pre></div><label class="agent-plan-review-feedback"><span>规划意见（可选）</span><input data-agent-plan-review-feedback type="text" maxlength="2000" value="${escapeHtml(drafts.plan_review_feedback || "")}" placeholder="继续规划时可补充修改意见" /></label><div class="agent-plan-review-actions"><button class="small-button" type="button" data-agent-plan-review-action="approve" ${state.agentBusy ? "disabled" : ""}>批准并执行</button><button class="ghost-button" type="button" data-agent-plan-review-action="keep-planning" ${state.agentBusy ? "disabled" : ""}>继续规划</button><button class="ghost-button" type="button" data-agent-plan-review-action="cancel" ${state.agentBusy ? "disabled" : ""}>直接讨论</button></div></article>`;
  }

  function renderAgentInteractions(interactions) {
    const runtimeLabel = agentRuntimeLabel();
    if (!Array.isArray(interactions) || !interactions.length) {
      return `<section class="agent-panel agent-interactions-panel"><div class="panel-heading"><div><strong>待处理交互</strong><small>${escapeHtml(runtimeLabel)} 没有等待用户回答的审批或问题。</small></div></div><div class="empty-column">队列为空</div></section>`;
    }
    const rows = interactions.map((item) => {
      if (item.kind === "approval") {
        return `<article class="agent-interaction approval-interaction"><div class="agent-interaction-copy"><strong>需要批准：${escapeHtml(item.action || "工具操作")}</strong><small>${escapeHtml(item.reason || `${runtimeLabel} 请求用户确认后才能继续`)}</small></div><div class="agent-approval-actions"><button class="small-button" type="button" data-agent-approval="${escapeHtml(item.id)}" data-agent-approval-session="${escapeHtml(item.session_id)}" data-agent-approval-id="${escapeHtml(item.approval_id)}" data-agent-approval-outcome="allowed-once" ${state.agentBusy ? "disabled" : ""}>允许一次</button><button class="ghost-button" type="button" data-agent-approval="${escapeHtml(item.id)}" data-agent-approval-session="${escapeHtml(item.session_id)}" data-agent-approval-id="${escapeHtml(item.approval_id)}" data-agent-approval-outcome="rejected" ${state.agentBusy ? "disabled" : ""}>拒绝</button></div></article>`;
      }
      if (item.kind === "question" && item.plan_review) return renderAgentPlanReviewInteraction(item);
      const questions = Array.isArray(item.questions) ? item.questions : [];
      const drafts = state.agentInteractionDrafts[item.id] || {};
      const questionRows = questions.map((question) => {
        const options = Array.isArray(question.options) ? question.options : [];
        const controlType = question.multiSelect ? "checkbox" : "radio";
        const draft = drafts[question.id] || {};
        const selected = Array.isArray(draft.selected) ? draft.selected : [];
        const optionRows = options.map((option) => `<label class="agent-question-option"><input type="${controlType}" name="answer-${escapeHtml(question.id)}" value="${escapeHtml(option.label)}" ${selected.includes(option.label) ? "checked" : ""} /><span><strong>${escapeHtml(option.label)}</strong>${option.description ? `<small>${escapeHtml(option.description)}</small>` : ""}</span></label>`).join("");
        return `<fieldset class="agent-question" data-agent-question-id="${escapeHtml(question.id)}"><legend>${question.header ? `${escapeHtml(question.header)} · ` : ""}${escapeHtml(question.question)}</legend>${question.detail ? `<p>${escapeHtml(question.detail)}</p>` : ""}${optionRows}<label class="agent-question-custom"><span>其他回答（可选）</span><input data-agent-custom type="text" maxlength="2000" placeholder="输入自定义回答" value="${escapeHtml(draft.custom || "")}" /></label></fieldset>`;
      }).join("");
      return `<form class="agent-interaction question-interaction" data-agent-interaction-form data-agent-interaction-id="${escapeHtml(item.id)}" data-agent-interaction-session="${escapeHtml(item.session_id)}"><div class="agent-interaction-heading"><div><strong>Agent 需要你的回答</strong><small>回答后 ${escapeHtml(runtimeLabel)} 才会继续当前回合；问题内容来自受管运行时。</small></div><span class="agent-chip pending">待回答</span></div>${questionRows}<button class="small-button" type="submit" ${state.agentBusy ? "disabled" : ""}>提交回答</button></form>`;
    }).join("");
    return `<section class="agent-panel agent-interactions-panel"><div class="panel-heading"><div><strong>待处理交互 · ${interactions.length}</strong><small>审批只对当前动作生效；回答不会写入 Sumika 聊天消息。</small></div></div><div class="agent-interaction-list">${rows}</div></section>`;
  }

  function renderAgentPresetPanel(status) {
    if (!agentSupports("presets")) return "";
    const runtimeLabel = agentRuntimeLabel();
    const session = selectedAgentSession();
    const locked = Boolean(session && session.blank === false);
    const presets = Array.isArray(state.agentPresets) ? state.agentPresets : [];
    const effective = session?.agent_preset || state.agentPresetId || presets.find((item) => item.is_default && !item.broken)?.id || "";
    const options = presets.map((preset) => {
      const trustLabel = preset.trust === "system" ? "系统" : preset.trust === "user" ? "用户" : "未知来源";
      const label = `${preset.name || preset.id} · ${trustLabel}${preset.broken ? ` · 不可用：${preset.broken}` : ""}`;
      return `<option value="${escapeHtml(preset.id)}" ${preset.id === effective ? "selected" : ""} ${preset.broken || locked || !status.ready || state.agentBusy ? "disabled" : ""}>${escapeHtml(label)}</option>`;
    }).join("");
    const usable = presets.filter((preset) => preset && preset.id && !preset.broken);
    const copySource = usable.some((preset) => preset.id === state.agentPresetCopySource)
      ? state.agentPresetCopySource
      : (usable[0]?.id || "");
    const copySourceOptions = usable.map((preset) => `<option value="${escapeHtml(preset.id)}" ${preset.id === copySource ? "selected" : ""}>${escapeHtml(preset.name || preset.id)} · ${preset.trust === "system" ? "系统" : preset.trust === "user" ? "用户" : "未知来源"}</option>`).join("");
    const userPresets = presets.filter((preset) => preset.trust === "user");
    const userPresetRows = userPresets.length
      ? userPresets.map((preset) => {
        const validation = state.agentPresetValidation[preset.id];
        const validationLabel = validation?.mountable ? " · 挂载已验证" : "";
        return `<div class="agent-preset-user-row" data-agent-preset-row="${escapeHtml(preset.id)}"><div><strong>${escapeHtml(preset.name || preset.id)}</strong><small><code>${escapeHtml(preset.id)}</code>${preset.broken ? ` · 不可用：${escapeHtml(preset.broken)}` : ` · 用户 Preset${validationLabel}`}</small></div><div class="agent-preset-user-actions"><button class="ghost-button" type="button" data-agent-preset-validate="${escapeHtml(preset.id)}" ${status.ready && !state.agentBusy && !preset.broken ? "" : "disabled"}>验证挂载</button>${state.agentPresetHasDocument ? `<button class="ghost-button" type="button" data-agent-preset-open="${escapeHtml(preset.id)}" ${status.ready && !state.agentBusy ? "" : "disabled"}>打开目录</button>` : `<span class="muted-text">未配置目录打开器</span>`}<button class="ghost-button danger-text" type="button" data-agent-preset-remove="${escapeHtml(preset.id)}" ${status.ready && !state.agentBusy ? "" : "disabled"}>删除</button></div></div>`;
      }).join("")
      : `<small class="muted-text">还没有用户 Preset；复制系统 Preset 后可在 ${escapeHtml(runtimeLabel)} 管理的目录中编辑。</small>`;
    const broken = presets.filter((preset) => preset.broken).length;
    const note = !status.ready
      ? `连接 ${runtimeLabel} 后读取真实 Preset 清单。`
      : locked
        ? "当前会话已经产生回合，Preset 已锁定；新建会话时可重新选择。"
        : `Preset 由 ${runtimeLabel} 管理；Sumika 只通过固定 ID 请求复制、打开或删除用户 Preset，不读取和改写组合文件。`;
    const authoring = status.ready && state.agentPresetAuthorable;
    const copyPanel = authoring
      ? `<form id="agent-preset-copy-form" class="agent-preset-copy-form"><label><span>复制来源</span><select id="agent-preset-copy-source" ${state.agentBusy ? "disabled" : ""}>${copySourceOptions || "<option value=\"\">暂无可复制 Preset</option>"}</select></label><label><span>新 Preset ID</span><input id="agent-preset-copy-id" type="text" maxlength="160" pattern="[a-z0-9][a-z0-9-]*" value="${escapeHtml(state.agentPresetCopyId)}" placeholder="例如 sumika-work" ${state.agentBusy || !usable.length ? "disabled" : ""} /></label><label><span>显示名称（可选）</span><input id="agent-preset-copy-name" type="text" maxlength="240" value="${escapeHtml(state.agentPresetCopyName)}" placeholder="例如 Sumika 工作" ${state.agentBusy || !usable.length ? "disabled" : ""} /></label><button class="outline-button" type="submit" ${state.agentBusy || !copySource || !usable.length ? "disabled" : ""}>复制为用户 Preset</button></form>`
      : `<small class="muted-text">当前 ${escapeHtml(runtimeLabel)} profile 不允许通过 API 创建用户 Preset；请在 Runtime 配置中启用 authorable 后刷新。</small>`;
    return `<section class="agent-panel agent-preset-panel"><div class="panel-heading"><div><strong>Agent Preset</strong><small>${escapeHtml(note)}</small></div><span class="agent-chip ${presets.length ? "" : "pending"}">${presets.length ? `${presets.length} 项` : "未读取"}</span></div><label class="agent-preset-select"><span>${session ? "当前空白会话" : "新会话默认"}</span><select id="agent-preset-select" ${status.ready && !state.agentBusy && !locked && presets.some((item) => !item.broken) ? "" : "disabled"}><option value="">使用 ${escapeHtml(runtimeLabel)} 默认</option>${options}</select></label>${broken ? `<small class="agent-mode-warning">${broken} 个 Preset 因组合错误被保留为不可选状态。</small>` : ""}<div class="agent-preset-authoring"><div class="agent-subsection-heading"><strong>用户 Preset</strong><span>${userPresets.length} 项</span></div><div class="agent-preset-user-list">${userPresetRows}</div><div class="agent-preset-copy-heading"><strong>复制为用户 Preset</strong><small>复制完成后由 ${escapeHtml(runtimeLabel)} 管理文件；Sumika 不展示原始 composition 内容。</small></div>${copyPanel}${renderAgentMcpConfigurationPanel(status, userPresets)}</div></section>`;
  }

  function renderAgentMcpConfigurationPanel(status, userPresets) {
    if (!agentSupports("mcp-configuration")) return "";
    const selectedPreset = userPresets.some((preset) => preset.id === state.agentMcpPresetId)
      ? state.agentMcpPresetId
      : userPresets[0]?.id || "";
    const presetOptions = userPresets.map((preset) => `<option value="${escapeHtml(preset.id)}" ${preset.id === selectedPreset ? "selected" : ""}>${escapeHtml(preset.name || preset.id)}</option>`).join("");
    const rows = state.agentMcpConfigurations.length
      ? state.agentMcpConfigurations.map((configuration) => {
        const target = configuration.transport === "stdio"
          ? `${configuration.command || "-"} · ${(configuration.args || []).length} 参数`
          : configuration.url || "-";
        const credential = configuration.credential;
        const credentialStatus = credential
          ? credential.configured
            ? credential.loaded_at_launch ? `凭据已加载 · ${credential.target}` : `凭据待重启 · ${credential.target}`
            : `凭据未保存 · ${credential.target}`
          : "无凭据";
        return `<div class="agent-mcp-row" data-agent-mcp-row="${escapeHtml(configuration.server_name)}"><div><strong>${escapeHtml(configuration.server_name)}</strong><small>${escapeHtml(configuration.transport)} · ${configuration.enabled ? "已启用" : "未启用"} · ${escapeHtml(credentialStatus)} · ${escapeHtml(target)}</small></div><div class="agent-mcp-row-actions"><button class="ghost-button" type="button" data-agent-mcp-edit="${escapeHtml(configuration.server_name)}" ${state.agentBusy ? "disabled" : ""}>编辑</button><button class="ghost-button danger-text" type="button" data-agent-mcp-remove="${escapeHtml(configuration.server_name)}" ${state.agentBusy ? "disabled" : ""}>移除</button></div></div>`;
      }).join("")
      : `<div class="empty-column">此 Preset 尚无 Sumika 管理的 MCP 连接</div>`;
    const draft = state.agentMcpDraft || {};
    const transport = draft.transport === "streamable-http" ? "streamable-http" : "stdio";
    const targetFields = transport === "stdio"
      ? `<label><span>启动命令</span><input name="command" type="text" maxlength="1024" value="${escapeHtml(draft.command || "")}" placeholder="npx" required /></label><label><span>参数（JSON 数组）</span><textarea name="args" rows="2" maxlength="16384">${escapeHtml(draft.args_text || "[]")}</textarea></label><label><span>工作目录（可选）</span><input name="cwd" type="text" maxlength="4096" value="${escapeHtml(draft.cwd || "")}" /></label>`
      : `<label class="agent-mcp-wide"><span>MCP URL</span><input name="url" type="url" maxlength="2048" value="${escapeHtml(draft.url || "")}" placeholder="http://127.0.0.1:3000/mcp" required /></label>`;
    const credentialFields = state.agentMcpCredentialFieldsSupported
      ? `<div class="agent-mcp-credential agent-mcp-wide"><label class="checkbox-row"><input id="agent-mcp-credential-enabled" name="credential_enabled" type="checkbox" ${draft.credential_enabled ? "checked" : ""} /><span>使用受保护凭据</span></label>${draft.credential_enabled ? `<label><span>${transport === "stdio" ? "目标环境变量" : "目标请求头"}</span><input name="credential_target" type="text" maxlength="64" value="${escapeHtml(draft.credential_target || "")}" placeholder="${transport === "stdio" ? "GITHUB_TOKEN" : "Authorization"}" required /></label>${transport === "streamable-http" ? `<label><span>非敏感前缀（可选）</span><input name="credential_prefix" type="text" maxlength="128" value="${escapeHtml(draft.credential_prefix || "")}" placeholder="Bearer " /></label>` : ""}<label><span>密钥${draft.credential_configured ? "（留空保留）" : ""}</span><input name="credential_value" type="password" maxlength="1800" autocomplete="new-password" value="${escapeHtml(state.agentMcpPendingSecret)}" ${draft.credential_configured ? "" : "required"} /></label>${draft.credential_configured ? `<label class="checkbox-row"><input name="credential_rotate" type="checkbox" ${draft.credential_rotate ? "checked" : ""} /><span>轮换已保存密钥</span></label>` : ""}<small>${draft.credential_configured ? draft.credential_loaded_at_launch ? "密钥已注入当前 DSH；保留密钥时可直接启用。" : "密钥已保存但尚未注入；重启 Sumika 后才能启用。" : "密钥只写入系统凭据库；首次保存后连接会保持关闭，等待重启注入。"}</small>` : `<small>未配置凭据；取消勾选并应用会移除现有受保护凭据。</small>`}</div>`
      : `<small class="agent-mcp-wide muted-text">当前平台没有可用的受保护凭据存储；只能配置无鉴权 MCP。</small>`;
    const preview = state.agentMcpPreview;
    const previewTarget = preview?.configuration?.transport === "stdio"
      ? `${preview.configuration.command || "-"} ${JSON.stringify(preview.configuration.args || [])}`
      : preview?.configuration?.url || "";
    const changeLabel = ({ create: "新增", update: "更新", remove: "移除", noop: "无变化" })[preview?.change] || preview?.change || "";
    const previewCredential = preview?.credential_requires_value
      ? "需要随批准提交新密钥；应用后请重启 Sumika，再次编辑并启用。"
      : preview?.restart_required ? "凭据边界已变化；重启 Sumika 后生效。" : "";
    const previewPanel = preview
      ? `<div class="agent-mcp-preview" data-agent-mcp-preview><div><strong>${escapeHtml(preview.server_name)} · ${escapeHtml(changeLabel)}</strong><span>${preview.configuration?.enabled ? "启用" : preview.action === "remove" ? "移除" : "保持关闭"}</span></div>${previewTarget ? `<code>${escapeHtml(previewTarget)}</code>` : ""}<small>批准后写入受管用户 Preset，保留原文备份并执行真实挂载验证；失败会恢复原文。${previewCredential ? ` ${escapeHtml(previewCredential)}` : ""}</small>${preview.requires_approval ? `<button class="outline-button" id="agent-mcp-apply" type="button" ${state.agentBusy || (preview.credential_requires_value && !state.agentMcpPendingSecret) ? "disabled" : ""}>批准并应用</button>` : `<span class="muted-text">配置与当前文件一致，无需写入。</span>`}</div>`
      : "";
    const packageStatus = state.agentMcpClientInstalled
      ? `dsh-mcp-client ${state.agentMcpClientVersion || "版本未知"}`
      : "受管 profile 未安装 dsh-mcp-client";
    return `<div class="agent-mcp-configuration"><div class="agent-preset-copy-heading"><strong>MCP 连接</strong><small>${escapeHtml(packageStatus)} · 鉴权值保存在系统凭据库，并只在受管 DSH 启动时注入</small></div>${userPresets.length ? `<label class="agent-mcp-preset-select"><span>用户 Preset</span><select id="agent-mcp-preset" ${status.ready && !state.agentBusy ? "" : "disabled"}>${presetOptions}</select></label><div class="agent-mcp-list">${rows}</div><form id="agent-mcp-form" class="agent-mcp-form"><label><span>服务名称</span><input name="server_name" type="text" maxlength="32" pattern="[A-Za-z0-9_-]{1,32}" value="${escapeHtml(draft.server_name || "")}" placeholder="filesystem" required /></label><label><span>传输方式</span><select name="transport"><option value="stdio" ${transport === "stdio" ? "selected" : ""}>stdio</option><option value="streamable-http" ${transport === "streamable-http" ? "selected" : ""}>streamable-http</option></select></label><label><span>工具超时（毫秒）</span><input name="tool_call_timeout_ms" type="number" min="1000" max="600000" step="1000" value="${escapeHtml(draft.tool_call_timeout_ms || 60000)}" /></label>${targetFields}${credentialFields}<label class="checkbox-row agent-mcp-enabled"><input name="enabled" type="checkbox" ${draft.enabled ? "checked" : ""} /><span>写入后启用并验证连接</span></label><button class="outline-button" type="submit" ${status.ready && state.agentMcpClientInstalled && !state.agentBusy ? "" : "disabled"}>生成变更预览</button></form>${previewPanel}` : `<div class="empty-column">先复制一个用户 Preset，再为它配置 MCP。</div>`}</div>`;
  }

  function renderAgentGoalPanel(status) {
    if (!agentSupports("goals")) return "";
    const runtimeLabel = agentRuntimeLabel();
    const goal = state.agentGoal || state.agentSnapshot?.goal;
    const ref = goal?.ref;
    const phase = String(goal?.phase || "").toLowerCase();
    const active = ["active", "running", "armed", "in-progress", "in_progress"].includes(phase);
    const paused = ["paused", "stopped"].includes(phase);
    const completed = ["complete", "completed", "done"].includes(phase);
    const buttons = goal && ref ? [
      active ? `<button class="ghost-button" type="button" data-agent-goal-action="pause" ${state.agentBusy ? "disabled" : ""}>暂停</button>` : "",
      paused ? `<button class="small-button" type="button" data-agent-goal-action="resume" ${state.agentBusy ? "disabled" : ""}>继续</button>` : "",
      !completed && !paused ? `<button class="small-button" type="button" data-agent-goal-action="complete" ${state.agentBusy ? "disabled" : ""}>完成</button>` : "",
      `<button class="ghost-button" type="button" data-agent-goal-action="clear" ${state.agentBusy ? "disabled" : ""}>清除</button>`,
    ].filter(Boolean).join("") : "";
    const summary = goal
      ? `<div class="agent-goal-current"><div><strong>${escapeHtml(goal.objective || "未命名目标")}</strong><small>${escapeHtml(goal.phase || "状态未知")} · revision ${escapeHtml(ref?.revision ?? "?")}</small></div><div class="agent-goal-actions">${buttons}</div></div>`
      : `<div class="empty-column">当前会话没有活动 Goal</div>`;
    const canCreate = status.ready && state.agentSessionId && !state.agentBusy && !goal;
    return `<section class="agent-panel agent-goal-panel"><div class="panel-heading"><div><strong>Goal / 自治目标</strong><small>状态和版本由 ${escapeHtml(runtimeLabel)} projection 提供；每次修改都携带精确 revision。</small></div></div>${summary}<form id="agent-goal-form" class="agent-goal-form"><input name="objective" type="text" maxlength="12000" placeholder="为当前会话创建一个可暂停的目标" ${canCreate ? "" : "disabled"} /><input name="max_goal_rounds" type="number" min="1" max="1000" value="20" aria-label="最大 Goal 回合数" ${canCreate ? "" : "disabled"} /><button class="outline-button" type="submit" ${canCreate ? "" : "disabled"}>${goal ? "当前已有 Goal" : "创建 Goal"}</button></form></section>`;
  }

  function renderAgentSubagentPanel(status) {
    if (!agentSupports("subagents")) return "";
    const runtimeLabel = agentRuntimeLabel();
    const entries = Array.isArray(state.agentSubagents) ? state.agentSubagents : [];
    const rows = entries.length ? entries.map((entry) => {
      const history = state.agentSubagentHistories[entry.id];
      const childLabel = entry.label || entry.id;
      const controls = entry.kind !== "child" ? "" : `${entry.mode === "continuable" ? `<button class="small-button" type="button" data-agent-subagent-prompt="${escapeHtml(entry.id)}" ${status.ready && !state.agentBusy ? "" : "disabled"}>发送跟进</button>` : ""}<button class="ghost-button" type="button" data-agent-subagent-history="${escapeHtml(entry.id)}" ${status.ready && !state.agentBusy ? "" : "disabled"}>查看历史</button>${entry.mode === "continuable" && entry.activity === "running" ? `<button class="ghost-button" type="button" data-agent-subagent-interrupt="${escapeHtml(entry.id)}" ${state.agentBusy ? "disabled" : ""}>中断</button>` : ""}`;
      const historyText = history ? (history.messages || []).slice(-6).map((message) => `${message.role === "assistant" ? "Agent" : "你"}: ${message.content || ""}`).join("\n") : "";
      return `<article class="agent-subagent-row"><div><strong>${escapeHtml(childLabel)}</strong><small>${escapeHtml(entry.id)} · ${escapeHtml(entry.mode || "未知")} · ${escapeHtml(entry.activity || entry.reason || "未知")}</small>${historyText ? `<pre class="agent-subagent-history">${escapeHtml(historyText)}</pre>` : ""}</div><div class="agent-subagent-actions">${controls}</div></article>`;
    }).join("") : `<div class="empty-column">当前会话没有可展示的直接子 Agent</div>`;
    return `<section class="agent-panel agent-subagent-panel"><div class="panel-heading"><div><strong>Subagents</strong><small>只操作当前会话的直接子 Agent；继续发送仅允许 ${escapeHtml(runtimeLabel)} 标记为 continuable 的子 Agent。</small></div><button class="small-button" id="agent-refresh-subagents" type="button" ${status.ready && state.agentSessionId && !state.agentBusy ? "" : "disabled"}>刷新</button></div><div class="agent-subagent-list">${rows}</div></section>`;
  }

  function renderBrowserTab(tab, sessionId) {
    const id = String(tab?.id || "");
    if (!id) return "";
    const active = tab.active === true || state.browserActiveTabs[sessionId] === id;
    return `<div class="browser-tab-row ${active ? "active" : ""}"><button class="browser-tab-select" type="button" data-browser-tab-select="${escapeHtml(id)}" data-browser-tab-session="${escapeHtml(sessionId)}" title="切换到此标签页"><strong>${escapeHtml(tab.title || "未命名标签页")}</strong><small>${escapeHtml(tab.url || "")}</small></button><button class="icon-button browser-tab-close" type="button" data-browser-tab-close="${escapeHtml(id)}" data-browser-tab-session="${escapeHtml(sessionId)}" aria-label="关闭标签页" title="关闭标签页">×</button></div>`;
  }

  function renderBrowserProfiles() {
    if (!state.browserProfiles.length) {
      return `<div class="empty-column">还没有命名 Profile；临时 Profile 会在 24 小时后清理。</div>`;
    }
    return state.browserProfiles.slice(0, 12).map((profile) => {
      const archived = profile.status === "archived" || profile.archived_at;
      const leased = Boolean(profile.leased);
      const owner = profile.character_id ? `角色 ${profile.character_id}` : `Agent ${profile.agent_id || "未指定"}`;
      return `<div class="browser-profile-row ${archived ? "archived" : ""}"><div><strong>${escapeHtml(profile.name || profile.id)}</strong><small>${escapeHtml(owner)} · ${archived ? "已归档" : leased ? "使用中" : "可使用"}${profile.last_used_at ? ` · 最近 ${escapeHtml(profile.last_used_at)}` : ""}</small></div><div class="browser-profile-actions">${!archived ? `<button class="ghost-button" type="button" data-browser-profile-start="${escapeHtml(profile.id)}" ${leased || state.agentBusy ? "disabled" : ""}>打开</button><button class="ghost-button" type="button" data-browser-profile-archive="${escapeHtml(profile.id)}" ${leased || state.agentBusy ? "disabled" : ""}>归档</button>` : `<button class="ghost-button" type="button" data-browser-profile-restore="${escapeHtml(profile.id)}" ${state.agentBusy ? "disabled" : ""}>恢复</button>`}</div></div>`;
    }).join("");
  }

  function renderBrowserSessions() {
    if (!state.browserSessions.length) return `<div class="empty-column">当前没有隔离浏览器会话</div>`;
    return state.browserSessions.slice(0, 8).map((session) => {
      const observation = state.browserObservations[session.id];
      const observationText = observation?.observation ? JSON.stringify(observation.observation, null, 2) : "";
      const snapshot = state.browserSnapshots[session.id];
      const snapshotText = snapshot?.snapshot ? JSON.stringify(snapshot.snapshot, null, 2) : "";
      const diagnostics = state.browserDiagnostics[session.id] || {};
      const tabs = Array.isArray(state.browserTabs[session.id]) ? state.browserTabs[session.id] : [];
      const pending = state.browserNavigationPending[session.id];
      const pendingTab = state.browserTabCreatePending[session.id];
      const tabRows = tabs.length ? tabs.map((tab) => renderBrowserTab(tab, session.id)).join("") : `<div class="empty-column">尚未读取标签页</div>`;
      const diagnosticRows = [
        diagnostics.console ? `<details class="browser-diagnostic"><summary>控制台摘要</summary><pre>${escapeHtml(JSON.stringify(diagnostics.console, null, 2))}</pre></details>` : "",
        diagnostics.network ? `<details class="browser-diagnostic"><summary>网络摘要</summary><pre>${escapeHtml(JSON.stringify(diagnostics.network, null, 2))}</pre></details>` : "",
      ].filter(Boolean).join("");
       const profile = state.browserProfiles.find((item) => item.id === session.profile_id);
       const profileLabel = session.profile === "named" ? (profile?.name || "命名 Profile") : "临时 Profile";
       return `<div class="browser-session-row" data-browser-session-row="${escapeHtml(session.id)}"><div class="browser-session-main"><strong>${escapeHtml(profileLabel)}</strong><small>${escapeHtml(session.id)} · ${escapeHtml(session.state || "未知")}${session.expires_at ? ` · ${escapeHtml(session.expires_at)}` : session.lease_expires_at ? ` · 租约至 ${escapeHtml(session.lease_expires_at)}` : ""}</small><div class="browser-navigation"><input data-browser-url type="url" value="${escapeHtml(state.browserNavigationDrafts[session.id] || "")}" placeholder="https://example.com" aria-label="浏览器导航地址" /><button class="ghost-button" type="button" data-browser-navigate="${escapeHtml(session.id)}" ${state.agentBusy ? "disabled" : ""}>访问</button>${pending ? `<button class="small-button" type="button" data-browser-navigate-approve="${escapeHtml(session.id)}" ${state.agentBusy ? "disabled" : ""}>确认访问 ${escapeHtml(pending.domain || "此域名")}</button>` : ""}</div><div class="browser-tab-toolbar"><strong>标签页 · ${tabs.length}</strong><button class="ghost-button" type="button" data-browser-tabs="${escapeHtml(session.id)}" ${state.agentBusy ? "disabled" : ""}>刷新</button><button class="ghost-button" type="button" data-browser-tab-create="${escapeHtml(session.id)}" ${state.agentBusy ? "disabled" : ""}>新标签</button>${pendingTab ? `<button class="small-button" type="button" data-browser-tab-create-approve="${escapeHtml(session.id)}" ${state.agentBusy ? "disabled" : ""}>确认打开 ${escapeHtml(pendingTab.domain || "此域名")}</button>` : ""}</div><div class="browser-tab-list">${tabRows}</div>${observationText ? `<details class="browser-observation-wrap" open><summary>页面观察</summary><pre class="browser-observation">${escapeHtml(observationText)}</pre></details>` : ""}${snapshotText ? `<details class="browser-observation-wrap"><summary>ARIA snapshot</summary><pre class="browser-observation">${escapeHtml(snapshotText)}</pre></details>` : ""}${diagnosticRows}</div><div class="browser-session-actions"><button class="ghost-button" type="button" data-browser-observe="${escapeHtml(session.id)}" ${state.agentBusy ? "disabled" : ""}>观察页面</button><button class="ghost-button" type="button" data-browser-snapshot="${escapeHtml(session.id)}" ${state.agentBusy ? "disabled" : ""}>ARIA snapshot</button><button class="ghost-button" type="button" data-browser-help="${escapeHtml(session.id)}" ${state.agentBusy ? "disabled" : ""}>请求接管</button><button class="ghost-button" type="button" data-browser-console="${escapeHtml(session.id)}" ${!state.browserDeveloperMode || state.agentBusy ? "disabled" : ""}>读控制台</button><button class="ghost-button" type="button" data-browser-network="${escapeHtml(session.id)}" ${!state.browserDeveloperMode || state.agentBusy ? "disabled" : ""}>读网络</button><button class="ghost-button" type="button" data-browser-session-close="${escapeHtml(session.id)}" ${state.agentBusy ? "disabled" : ""}>停止</button></div></div>`;
    }).join("");
  }

  function renderBrowserDownloads() {
    const rows = state.browserDownloads.length
      ? state.browserDownloads.slice(0, 16).map((item) => `<article class="browser-download-row"><div><strong>${escapeHtml(item.filename || "未命名文件")}</strong><small>${escapeHtml(formatBytes(item.size_bytes))} · SHA-256 <code>${escapeHtml(String(item.sha256 || "").slice(0, 16))}…</code> · ${escapeHtml(item.status === "quarantine" ? "等待确认" : item.imported_at ? "已导入 Workspace" : "已批准")}</small><small>${escapeHtml(item.source_url || "来源未提供")}</small></div>${item.status === "quarantine" ? `<button class="small-button" type="button" data-browser-download-release="${escapeHtml(item.id)}" ${state.agentBusy ? "disabled" : ""}>批准并导入</button>` : ""}</article>`).join("")
      : `<div class="empty-column">暂无隔离下载</div>`;
    return `<section class="browser-downloads"><div class="browser-download-heading"><div><strong>下载隔离队列</strong><small>下载只保存在 quarantine；确认前不会进入 Workspace，也不会自动打开。</small></div><button class="ghost-button" type="button" id="browser-refresh-downloads" ${state.agentBusy ? "disabled" : ""}>刷新</button></div><div class="browser-download-list">${rows}</div></section>`;
  }

  function renderBrowserPanel(browser, browserLabel, browserDetail) {
    return `<section class="agent-panel browser-runtime-panel"><div class="panel-heading"><div><strong>隔离浏览器</strong><small>${escapeHtml(browserDetail)}</small></div><div class="browser-panel-actions"><button class="small-button" id="browser-new-session" type="button" ${browser.state === "disabled" ? "disabled" : ""}>创建临时 Profile</button><button class="ghost-button" id="browser-new-named-profile" type="button" ${browser.state === "disabled" ? "disabled" : ""}>新建命名 Profile</button></div></div><div class="diagnostic-grid"><div><span>状态</span><strong>${escapeHtml(browserLabel)}</strong></div><div><span>后端</span><strong>${escapeHtml(browser.backend || "BrowserSkill")}</strong></div><div><span>活动会话</span><strong>${escapeHtml(browser.active_sessions ?? 0)}</strong></div><div><span>命名 Profile</span><strong>${escapeHtml(browser.named_profiles ?? state.browserProfiles.filter((item) => !item.archived_at).length)}</strong></div><div><span>下载隔离</span><strong>${escapeHtml(browser.quarantined_downloads ?? 0)} 项</strong></div></div><label class="browser-developer-toggle"><input id="browser-developer-mode" type="checkbox" ${state.browserDeveloperMode ? "checked" : ""} /> Developer 诊断（控制台/网络每次读取都需批准）</label><details class="browser-profiles-wrap"><summary>命名 Profile（凭据由 BrowserSkill 管理；Sumika 只保存授权和租约元数据）</summary><div class="browser-profile-list">${renderBrowserProfiles()}</div></details><div class="browser-session-list">${renderBrowserSessions()}</div>${renderBrowserDownloads()}</section>`;
  }

  function renderAgentSessionRow(session, snippet = "") {
    const id = session?.id || session?.session_id || "";
    if (!id) return "";
    const stateLabel = session.state === "running" ? "运行中" : "空闲";
    return `<button class="agent-session-row ${id === state.agentSessionId ? "active" : ""}" type="button" data-agent-session-select="${escapeHtml(id)}"><span class="status-dot ${session.state === "running" ? "warning" : "online"}"></span><span class="agent-session-row-copy"><strong>${escapeHtml(session.title || "未命名 Agent 会话")}</strong><small>${escapeHtml(id)} · ${stateLabel}${snippet ? ` · ${escapeHtml(snippet)}` : ""}</small></span></button>`;
  }

  function renderAgentSessionSearch() {
    const results = state.agentSessionSearchResults;
    const source = results === null
      ? state.agentSessions.slice(0, 8).map((session) => ({ session, snippet: "" }))
      : results.map((item) => ({
        session: state.agentSessions.find((candidate) => candidate.id === item.session_id) || {
          id: item.session_id,
          title: item.session_id,
          state: "idle",
        },
        snippet: item.snippet || "",
      }));
    const rows = source.map(({ session, snippet }) => renderAgentSessionRow(session, snippet)).filter(Boolean).join("");
    const empty = results !== null && !results.length ? "没有匹配的会话" : "暂无受管 Agent 会话";
    const search = agentSupports("session-search")
      ? `<form id="agent-session-search-form" class="agent-session-search"><input id="agent-session-search" type="search" maxlength="512" value="${escapeHtml(state.agentSessionSearchQuery)}" placeholder="搜索会话内容" aria-label="搜索 Agent 会话" /><button class="ghost-button" type="submit" ${state.agentSessionSearchBusy ? "disabled" : ""}>${state.agentSessionSearchBusy ? "搜索中" : "搜索"}</button>${results !== null ? `<button class="ghost-button" type="button" id="agent-session-search-clear">清除</button>` : ""}</form>${state.agentSessionSearchNotice ? `<small class="agent-session-search-notice" role="status">${escapeHtml(state.agentSessionSearchNotice)}</small>` : ""}`
      : "";
    return `${search}<div class="agent-session-list">${rows || `<div class="empty-column">${empty}</div>`}</div>`;
  }

  function renderAgentPromptAttachments() {
    const attachments = supportedAgentPromptAttachments();
    if (!attachments.length) return `<span class="agent-attachment-empty">可附加 PNG、JPEG、WebP 或 GIF</span>`;
    return attachments.map((item, index) => `<span class="agent-attachment-chip"><span>${escapeHtml(item.name || `图片 ${index + 1}`)} · ${escapeHtml(formatBytes(item.bytes || 0))}</span><button class="icon-button" type="button" data-agent-attachment-remove="${index}" aria-label="移除附件" title="移除附件">×</button></span>`).join("");
  }

  function renderAgent() {
    const status = state.agentStatus || {};
    const runtimeLabel = agentRuntimeLabel(status);
    const provider = state.agentProvider || {};
    const browser = state.browserStatus || {};
    const statusLabel = ({ ready: "已连接", unavailable: "未连接", disabled: "已关闭", "policy-only": "策略层已加载" })[status.state] || status.state || "未知";
    const providerLabel = ({ ready: "已同步", "not-synced": "待同步", "restart-required": "需要重启", unavailable: "不可用", unconfigured: "未配置" })[provider.state] || provider.state || "未知";
    const providerRestartRequired = provider.state === "restart-required" || provider.credential_reload_required === true;
    const providerCanSync = provider.state === "ready" || provider.state === "not-synced";
    const credentialStorageLabel = provider.credential_mode === "launch-environment"
      ? "Windows 安全存储"
      : provider.credential_mode === "local-placeholder"
        ? "无敏感凭据"
        : "未使用";
    const credentialSourceLabel = provider.credential_source === "env"
      ? "启动环境 · 只读"
      : provider.credential_source === "file"
        ? "DSH 文件 · 已拒绝"
        : provider.credential_source === "not-required"
          ? "不需要"
          : "未加载";
    const providerReason = provider.reason || provider.error || "";
    const browserLabel = ({ ready: "可执行", "awaiting-extension": "等待扩展", "not-installed": "未安装", unavailable: "不可用", "policy-only": "策略层" })[browser.state] || browser.state || "未知";
    const browserDetail = browser.backend_reason || "敏感操作仍需用户批准；不控制系统级鼠标键盘。";
    const browserPanel = renderBrowserPanel(browser, browserLabel, browserDetail);
    const catalogManagement = `<details class="agent-catalog-management"><summary>目录与批准（MCP / Skills）</summary><div class="agent-catalog-management-body">${renderAgentMcpCatalogPanel()}${renderAgentSkillCatalogPanel()}</div></details>`;
    const notice = state.agentNotice ? `<div class="agent-notice" role="status">${escapeHtml(state.agentNotice)}</div>` : "";
    const capabilities = [
      agentSupports("skills") ? renderAgentCapabilityCard("Skills", state.agentCapabilities.skills, `可复用技能由 ${runtimeLabel} 管理，未经批准不会安装`) : "",
      agentSupports("mcp") ? renderAgentMcpCapability(state.agentCapabilities.mcp) : "",
      agentSupports("subagents") ? renderAgentCapabilityCard("Subagents", state.agentCapabilities.subagents, "子 Agent 由独立会话和预算隔离") : "",
      agentSupports("commands") ? renderAgentCapabilityCard("Commands", state.agentCapabilities.commands, `Plan 和命令通过 ${runtimeLabel} command plane 执行，不写入普通消息`) : "",
    ].filter(Boolean).join("");
    const events = state.agentEvents.length ? state.agentEvents.slice(0, 10).map(renderAgentEventRow).join("") : `<div class="empty-column">尚未收到 Agent 事件</div>`;
    const commandPlane = state.agentCapabilities.commands;
    const planModeAvailable = agentPlanModeAvailable();
    const commandNotice = agentSupports("commands") && state.agentSessionId && !planModeAvailable
      ? `<small class="agent-mode-warning">当前会话或 Preset 未提供 Plan 命令；普通执行仍可用，也不会发送多余的 /plan off。</small>`
      : "";
    const providerPanel = agentSupports("provider-bridge") ? `<section class="agent-panel agent-provider-panel" data-agent-provider-state="${escapeHtml(provider.state || "unknown")}"><div class="panel-heading"><div><strong>当前 Agent Provider</strong><small>新建 Agent 会话时，当前 Sumika 档案会映射到 ${escapeHtml(runtimeLabel)}；远程密钥只从 Windows 安全存储注入受管 Runtime。</small></div><button class="small-button" id="agent-provider-sync" type="button" ${status.ready && provider.profile_id && providerCanSync && !providerRestartRequired ? "" : "disabled"}>${providerRestartRequired ? "重启后同步" : "同步当前档案"}</button></div><div class="diagnostic-grid"><div><span>状态</span><strong>${escapeHtml(providerLabel)}</strong></div><div><span>档案</span><strong>${escapeHtml(provider.profile?.name || "未选择")}</strong></div><div><span>模型</span><strong>${escapeHtml(provider.model || provider.profile?.config?.model || "未配置")}</strong></div><div><span>Runtime binding</span><strong><code>${escapeHtml(provider.route_id || provider.binding_id || "未同步")}</code></strong></div><div><span>凭据持久化</span><strong>${escapeHtml(credentialStorageLabel)}</strong></div><div><span>Runtime 凭据</span><strong>${escapeHtml(credentialSourceLabel)}</strong></div><div><span>Runtime 重载</span><strong>${providerRestartRequired ? "需要重启" : "无需重启"}</strong></div></div>${providerReason ? `<small class="agent-mode-warning agent-provider-reason" role="status">${escapeHtml(providerReason)}</small>` : ""}</section>` : "";
    const mode = effectiveAgentMode();
    const promptAttachments = supportedAgentPromptAttachments();
    const modeOptions = `${planModeAvailable ? `<option value="plan" ${mode === "plan" ? "selected" : ""}>Plan</option>` : ""}<option value="execute" ${mode === "execute" ? "selected" : ""}>执行</option>${agentSupports("readonly") ? `<option value="readonly" ${mode === "readonly" ? "selected" : ""}>只读</option>` : ""}`;
    const hasPromptContent = Boolean(state.agentPromptDraft.trim() || promptAttachments.length);
    const canCreateSession = status.ready && (!agentSupports("workspaces") || Boolean(selectedAgentWorkspace()));
    const canSendPrompt = agentPromptCanSend(status, hasPromptContent, mode);
    const workspaceModeNotice = agentSupports("workspaces")
      ? (!state.agentSessionId && !selectedAgentWorkspace()
        ? `<small class="agent-mode-warning">先登记并选择 Git Workspace，才能新建会话或发送目标。</small>`
        : state.agentSessionId && mode === "execute" && !currentAgentSessionWorkspace()
          ? `<small class="agent-mode-warning">当前会话没有可验证的 Workspace 绑定；请新建一个绑定 Workspace 的会话后再执行。</small>`
          : mode === "execute"
            ? `<small class="agent-execution-safety">执行目标发送前会自动创建可恢复 checkpoint。</small>`
            : "")
      : "";
    const attachmentTools = agentSupports("attachments") ? `<div class="agent-attachment-tools"><input id="agent-image-input" type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden /><button class="ghost-button" id="agent-attach-image" type="button" ${status.ready && !state.agentBusy ? "" : "disabled"}>添加图片</button><div class="agent-attachment-list">${renderAgentPromptAttachments()}</div>${state.agentAttachmentNotice ? `<small class="agent-attachment-notice" role="status">${escapeHtml(state.agentAttachmentNotice)}</small>` : ""}</div>` : "";
    return renderPageFrame("Agent 工作区", `以 ${runtimeLabel} 为运行时，统一展示会话、计划、工具、审批和可选能力。`, `${notice}<div class="agent-toolbar"><div class="agent-status-line"><span class="status-dot ${status.state === "ready" ? "online" : status.state === "disabled" ? "offline" : "warning"}"></span><strong>${escapeHtml(runtimeLabel)} ${escapeHtml(statusLabel)}</strong><code>${escapeHtml(status.version || status.runtime_id || "未配置")}${status.commit ? ` · ${String(status.commit).slice(0, 12)}` : ""}</code></div><div class="agent-actions"><button class="small-button" id="agent-health" type="button" ${state.agentBusy ? "disabled" : ""}>检查连接</button><button class="outline-button" id="agent-create-session" type="button" ${canCreateSession ? "" : "disabled"}>新建 Agent 会话</button></div></div>${renderAgentPresetPanel(status)}${catalogManagement}${providerPanel}${renderAgentRoutingPanel(status)}${renderAgentWorkspacePanel(status)}${renderWorkspaceRuntimePanel()}${renderAgentModelPanel(status)}<section class="agent-panel agent-sessions-panel"><div class="panel-heading"><div><strong>受管 Agent 会话</strong><small>只显示当前 Sumika 受管 ${escapeHtml(runtimeLabel)} 实例的会话元数据；旧聊天会话不会混入。</small></div><button class="small-button" id="agent-refresh-sessions" type="button" ${status.ready && !state.agentBusy ? "" : "disabled"}>刷新</button></div>${renderAgentSessionSearch()}</section>${renderAgentSessionPanel(state.agentSnapshot)}${renderAgentGoalPanel(status)}${renderAgentSubagentPanel(status)}${agentSupports("interactions") ? renderAgentInteractions(state.agentInteractions) : ""}<section class="agent-panel"><div class="panel-heading"><div><strong>运行模式</strong><small>执行能力由 ${escapeHtml(runtimeLabel)} 与 Sumika policy companion 共同决定。</small>${commandNotice}${workspaceModeNotice}</div><select id="agent-mode" aria-label="Agent 模式">${modeOptions}</select></div><div class="agent-composer"><textarea id="agent-prompt" rows="3" maxlength="48000" placeholder="输入 Agent 目标；Runtime 未连接时不会发送或生成回复">${escapeHtml(state.agentPromptDraft)}</textarea><div class="agent-composer-footer">${attachmentTools}<button class="outline-button" id="agent-send" type="button" ${canSendPrompt ? "" : "disabled"}>发送目标</button></div></div></section>${capabilities ? `<section class="agent-capability-grid">${capabilities}</section>` : ""}<div class="agent-two-column"><section class="agent-panel"><div class="panel-heading"><div><strong>事件审计</strong><small>敏感动作默认拒绝，登录凭据和 OTP 不进入模型上下文。</small></div></div><div class="agent-event-list">${events}</div></section>${browserPanel}</div>`);
  }

  function renderAgentEventRow(event) {
    const extensions = event.extensions && typeof event.extensions === "object" ? event.extensions : {};
    const isApproval = event.event_type === "approval/requested" || event.event_type === "agent.approval.requested";
    const nestedEvent = extensions.event && typeof extensions.event === "object" ? extensions.event : {};
    const nestedData = nestedEvent.data && typeof nestedEvent.data === "object" ? nestedEvent.data : {};
    const rpcId = extensions.rpcId || event.rpcId || nestedEvent.rpcId || "";
    const sessionId = event.session_id || extensions.sessionId || nestedEvent.sessionId || "";
    const approvalId = extensions.approvalId || extensions.approval_id || nestedData.approvalId || nestedData.approval_id || nestedData.requestId || nestedData.id || "";
    const action = isApproval && rpcId && sessionId && approvalId
      ? `<div class="agent-approval-actions"><button class="small-button" type="button" data-agent-approval="${escapeHtml(rpcId)}" data-agent-approval-session="${escapeHtml(sessionId)}" data-agent-approval-id="${escapeHtml(approvalId)}" data-agent-approval-outcome="allowed-once" ${state.agentBusy ? "disabled" : ""}>允许一次</button><button class="ghost-button" type="button" data-agent-approval="${escapeHtml(rpcId)}" data-agent-approval-session="${escapeHtml(sessionId)}" data-agent-approval-id="${escapeHtml(approvalId)}" data-agent-approval-outcome="rejected" ${state.agentBusy ? "disabled" : ""}>拒绝</button></div>`
      : "";
    const detail = extensions.toolName ? `${extensions.toolName}${extensions.reason ? ` · ${extensions.reason}` : ""}` : (nestedData.action || nestedData.name || event.content || event.status || "状态更新");
    return `<div class="agent-event-row"><span class="status-dot ${event.status === "completed" || event.status === "ready" ? "online" : event.status === "error" ? "offline" : "warning"}"></span><div><strong>${escapeHtml(event.event_type || "agent.event")}</strong><small>${escapeHtml(detail)} · ${formatTime(event.timestamp)}</small>${action}</div></div>`;
  }

  return { renderAgentMcpCatalogPanel, renderAgentSkillCatalogPanel, renderAgentTurnLedger, renderAgent };
}
