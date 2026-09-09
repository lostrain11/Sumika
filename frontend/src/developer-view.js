export function createDeveloperView({
  agentRuntimeLabel,
  escapeHtml,
  formatDuration,
  formatTime,
  isDesktopShell,
  pluginStatusLabel,
  providerProfileStatusLabel,
  renderAgentMcpCatalogPanel,
  renderAgentSkillCatalogPanel,
  renderAvatarAssetAudit,
  renderCapabilityCatalogPanel,
  renderPageFrame,
  renderWebChatProfileRow,
  state,
}) {
  function renderDeveloper() {
    const notice = state.pluginNotice ? `<div class="plugin-notice" role="status">${escapeHtml(state.pluginNotice)}</div>` : "";
    const providerNotice = state.providerNotice ? `<div class="plugin-notice" role="status">${escapeHtml(state.providerNotice)}</div>` : "";
    const webChatNotice = state.webChatNotice ? `<div class="plugin-notice" role="status">${escapeHtml(state.webChatNotice)}</div>` : "";
    const pluginRows = state.plugins.length ? state.plugins.map(renderPluginRow).join("") : `<div class="empty-column">还没有扫描到本地 manifest</div>`;
    const pluginPanel = `<section class="dev-panel plugin-panel"><div class="panel-heading"><div><strong>本地插件 manifest</strong><small>只读取清单并等待批准；不会导入、启动代码或安装依赖。</small></div><button class="small-button" id="refresh-plugins" ${state.pluginBusy ? "disabled" : ""}>刷新</button></div><div class="plugin-scan-form"><input id="plugin-path" type="text" value="${escapeHtml(state.pluginPath)}" placeholder="插件目录或 manifest.json 的绝对路径" aria-label="插件目录或 manifest 路径" /><button class="outline-button" id="discover-plugins" ${state.pluginBusy ? "disabled" : ""}>扫描</button></div>${notice}<div class="plugin-list">${pluginRows}</div></section>`;
    const diagnostics = state.diagnostics;
    const diagnosticPanel = `<section class="dev-panel diagnostics-panel"><div class="panel-heading"><div><strong>核心诊断</strong><small>只显示运行元数据；详细运行线索写入本机日志，不包含聊天正文、密钥或原始媒体。</small></div><button class="small-button" id="refresh-diagnostics">刷新</button></div>${diagnostics ? `<div class="diagnostic-grid"><div><span>进程</span><strong>PID ${escapeHtml(diagnostics.pid)}</strong></div><div><span>运行时间</span><strong>${escapeHtml(formatDuration(diagnostics.uptime_seconds))}</strong></div><div><span>事件</span><strong>${escapeHtml(diagnostics.event_count)} 条</strong></div><div><span>模块 / Provider / Avatar</span><strong>${escapeHtml(diagnostics.module_count)} / ${escapeHtml(diagnostics.provider_count)} / ${escapeHtml(diagnostics.avatar_count)}</strong></div></div><div class="diagnostic-path"><span>数据目录</span><code>${escapeHtml(diagnostics.data_dir || "-")}</code><span>核心日志</span><code>${escapeHtml(diagnostics.log_path || "仅 stderr")}</code></div>` : `<div class="empty-column">诊断信息尚未加载</div>`}</section>`;
    const agentDiagnosticPanel = renderAgentDiagnosticsPanel();
    const desktopStatus = state.desktopStatus;
    const desktopPanel = isDesktopShell ? `<section class="dev-panel desktop-status-panel" data-desktop-status><div class="panel-heading"><div><strong>桌面生命周期</strong><small>Rust 壳负责核心与可选 Agent Runtime 进程；异常退出会有限次退避重启。</small></div><button class="small-button" id="refresh-desktop-status">刷新</button></div>${desktopStatus ? `<div class="diagnostic-grid"><div><span>核心地址</span><strong>${escapeHtml(desktopStatus.host)}:${escapeHtml(desktopStatus.port)}</strong></div><div><span>Python PID</span><strong>${escapeHtml(desktopStatus.pid || "-")}</strong></div><div><span>状态</span><strong>${desktopStatus.running ? "运行中" : "已停止"}</strong></div><div><span>本次重启</span><strong>${escapeHtml(desktopStatus.restart_count)}</strong></div><div><span>Agent Runtime</span><strong>${escapeHtml(desktopStatus.agent_runtime_id || "-")}</strong></div><div><span>Runtime 进程</span><strong>${desktopStatus.agent_managed ? `${escapeHtml(desktopStatus.agent_pid || "-")} · ${desktopStatus.agent_running ? "运行中" : "已停止"}` : "外部或未启动"}</strong></div></div><div class="diagnostic-path"><span>桌面日志</span><code>${escapeHtml(desktopStatus.log_path || "-")}</code><span>Runtime endpoint</span><code>${escapeHtml(desktopStatus.agent_endpoint || "-")}</code></div>` : `<div class="empty-column">桌面状态尚未加载</div>`}</section>` : "";
    const avatarAuditPanel = renderAvatarAssetAudit();
    const evolutionPanel = `<section class="dev-panel evolution-panel"><div class="panel-heading"><div><strong>Evolution Knowledge Registry</strong><small>只读参考索引；安装、升级和正式启用仍需用户批准。</small></div><button class="small-button" id="refresh-evolution-registry" type="button">刷新</button></div><div class="evolution-list">${state.evolutionRegistry.length ? state.evolutionRegistry.map((entry) => `<div class="evolution-row"><div><strong>${escapeHtml(entry.id)}</strong><small>${escapeHtml(entry.kind || "reference")} · ${escapeHtml(entry.license || "未登记许可证")}</small></div><code>${escapeHtml(entry.commit || entry.version || "未固定")}</code></div>`).join("") : `<div class="empty-column">尚未加载参考登记</div>`}</div></section>`;
    const profileRows = state.providerProfiles.map((profile) => `<div class="provider-row"><span class="status-dot ${profile.status === "available" ? "online" : "offline"}"></span><div><strong>${escapeHtml(profile.name)}</strong><small>${escapeHtml(profile.adapter_id)} · ${escapeHtml(providerProfileStatusLabel(profile.status))}</small></div>${profile.status === "archived" ? `<button class="ghost-button" type="button" data-provider-restore="${escapeHtml(profile.id)}" ${state.providerBusy ? "disabled" : ""}>恢复</button>` : `<button class="ghost-button" type="button" data-provider-health="${escapeHtml(profile.id)}" ${state.providerBusy ? "disabled" : ""}>测试</button>`}</div>`).join("") || `<div class="empty-column">暂无 Provider 档案</div>`;
    return renderPageFrame("开发者", "查看 manifest、事件、健康检查和 provider 运行边界。", `<div class="developer-grid">${providerNotice}${webChatNotice}${renderCapabilityCatalogPanel()}<section class="dev-panel"><div class="panel-heading"><strong>Provider 健康</strong><button class="small-button" id="refresh-health">刷新</button></div>${profileRows}</section>${renderWebChatArchivePanel()}${renderCcsCompatibilityPanel()}${evolutionPanel}${pluginPanel}${renderAgentMcpCatalogPanel()}${renderAgentSkillCatalogPanel()}${diagnosticPanel}${agentDiagnosticPanel}${desktopPanel}${avatarAuditPanel}<section class="dev-panel"><div class="panel-heading"><strong>事件流</strong><span class="muted-text">${state.events.length} 条</span></div><div class="event-log">${state.events.slice(0, 12).map((event) => `<div class="log-row"><code>${escapeHtml(event.event_type)}</code><span>${escapeHtml(JSON.stringify(event.payload).slice(0, 100))}</span></div>`).join("") || `<div class="empty-column">暂无事件</div>`}</div></section></div>`);
  }

  function renderWebChatArchivePanel() {
    const archived = state.webChatProfiles.filter((profile) => profile.archived_at || profile.status === "archived");
    const rows = archived.length
      ? archived.map(renderWebChatProfileRow).join("")
      : `<div class="empty-column">暂无已归档网页连接</div>`;
    return `<section class="dev-panel web-chat-archive-panel" data-web-chat-archive-panel><div class="panel-heading"><div><strong>已归档网页连接</strong><small>归档只隐藏连接档案，不删除 BrowserSkill 登录态；恢复后仍需重新检查和授权。</small></div></div><div class="provider-profile-list">${rows}</div></section>`;
  }

  function renderAgentDiagnosticsPanel() {
    const report = state.agentDiagnostics;
    const runtime = report?.runtime || {};
    const mcp = report?.mcp || {};
    const runtimeLabel = agentRuntimeLabel();
    const statusLabels = {
      available: "可用",
      "not-exposed": "未暴露",
      "session-scoped": "需会话",
      unavailable: "不可用",
      rejected: "被拒绝",
      disabled: "已关闭",
    };
    const statusClass = (status) => Object.prototype.hasOwnProperty.call(statusLabels, status) ? status : "unknown";
    const statusLabel = (status) => statusLabels[status] || status || "未知";
    const rows = Array.isArray(report?.capabilities)
      ? report.capabilities.map((item) => `<div class="agent-diagnostic-row"><div><strong>${escapeHtml(item.label || item.id || "能力")}</strong><small><code>${escapeHtml(item.endpoint || "-")}</code> · ${escapeHtml(item.detail || "")}</small></div><span class="agent-diagnostic-status ${statusClass(item.status)}">${escapeHtml(statusLabel(item.status))}</span></div>`).join("")
      : "";
    const mcpStatus = statusClass(mcp.status);
    const mcpClient = runtimeLabel === "DSH"
      ? (mcp.client_installed ? `dsh-mcp-client ${mcp.client_version || "已挂载"}` : "受管 web profile 未发现 dsh-mcp-client")
      : (mcp.client_installed ? `MCP client ${mcp.client_version || "已挂载"}` : "Runtime 未报告 MCP client");
    return `<section class="dev-panel agent-diagnostics-panel" data-agent-diagnostics><div class="panel-heading"><div><strong>${escapeHtml(runtimeLabel)} 能力探针</strong><small>只读诊断接口；不执行工具、不读取密钥。</small></div><button class="small-button" id="refresh-agent-diagnostics" type="button" ${state.agentDiagnosticsBusy ? "disabled" : ""}>${state.agentDiagnosticsBusy ? "检查中" : "检查"}</button></div>${report ? `<div class="diagnostic-grid agent-diagnostic-summary"><div><span>运行时</span><strong>${escapeHtml(runtime.ready ? "已连接" : runtime.state || "未连接")}</strong></div><div><span>客户端版本</span><strong>${escapeHtml(runtime.version || "-")}</strong></div><div><span>协议版本</span><strong>${escapeHtml(runtime.protocol_version || "未读取")}</strong></div><div><span>检查时间</span><strong>${escapeHtml(formatTime(report.checked_at))}</strong></div></div><div class="agent-diagnostic-mcp" data-agent-mcp-status="${escapeHtml(mcp.status || "unknown")}"><div><strong>MCP</strong><span class="agent-diagnostic-status ${mcpStatus}">${escapeHtml(statusLabel(mcp.status))}</span></div><small>${escapeHtml(mcp.reason || "未读取 MCP 状态")}</small><code>${escapeHtml(mcpClient)}</code></div><div class="agent-diagnostic-list">${rows || `<div class="empty-column">没有可探测的 Runtime 能力</div>`}</div>${report.runtime?.error ? `<p class="plugin-error">${escapeHtml(report.runtime.error)}</p>` : ""}` : `<div class="empty-column">尚未检查 Runtime 能力</div>`}</section>`;
  }

  function renderCcsCompatibilityPanel() {
    const manifest = state.ccsManifest;
    const report = state.ccsReport;
    const status = report ? ({ up_to_date: "已是最新", release_only: "仅发布版本变化", review_required: "需要人工复核", protocol_incompatible: "协议不兼容", check_failed: "检查失败" })[report.status] || report.status : "尚未检查";
    const changed = (report?.changes || []).filter((item) => item.changed);
    return `<section class="dev-panel ccs-compatibility-panel"><div class="panel-heading"><div><strong>外部导入兼容性</strong><small>CC Switch 只是可拆卸的 ccswitch-v1 转换器，不参与 Provider 运行时。</small></div><button class="small-button" id="check-ccs-compatibility" type="button" ${state.ccsBusy ? "disabled" : ""}>${state.ccsBusy ? "检查中" : "检查 CCS 更新"}</button></div><div class="ccs-baseline"><span>基线</span><code>${escapeHtml(manifest?.upstream_tag || "-")} · ${escapeHtml((manifest?.upstream_commit || "").slice(0, 12) || "-")}</code><span>状态</span><strong class="ccs-status ${escapeHtml(report?.status || "idle")}">${escapeHtml(status)}</strong></div>${report ? `<div class="ccs-report"><p>上游 ${escapeHtml(report.latest_tag || "未知")}；本次检查不会复制代码、迁移档案或启用字段。</p><div><span>本地夹具</span><strong>${escapeHtml(report.fixtures ? `${report.fixtures.passed}/${report.fixtures.total}` : "-")}</strong><span>关键文件变化</span><strong>${changed.length}</strong></div>${changed.length ? `<ul>${changed.map((item) => `<li><code>${escapeHtml(item.path)}</code><span>${escapeHtml(item.category)}</span></li>`).join("")}</ul>` : ""}${report.error ? `<p class="plugin-error">${escapeHtml(report.error)}</p>` : ""}</div>` : `<div class="empty-column">只在手动点击时联网检查，不在本机后台轮询。</div>`}</section>`;
  }

  function renderPluginRow(plugin) {
    const busy = Boolean(state.pluginBusy);
    const capabilities = Array.isArray(plugin.manifest?.capabilities) ? plugin.manifest.capabilities : [];
    const isTool = capabilities.includes("tool");
    let actions = "";
    if (["discovered", "changed", "revoked"].includes(plugin.state)) {
      actions = `<button class="small-button" type="button" data-plugin-approve="${escapeHtml(plugin.candidate_id)}" ${busy ? "disabled" : ""}>${plugin.state === "revoked" ? "重新批准" : "批准登记"}</button>`;
    } else if (plugin.state === "approved") {
      actions = `${isTool ? `<button class="small-button" type="button" data-plugin-config="${escapeHtml(plugin.candidate_id)}" ${busy ? "disabled" : ""}>${plugin.launcher && Object.keys(plugin.launcher).length ? "启动配置" : "配置启动器"}</button>${plugin.launcher && Object.keys(plugin.launcher).length ? `<button class="small-button" type="button" data-plugin-run="${escapeHtml(plugin.candidate_id)}" ${busy ? "disabled" : ""}>测试调用</button>` : ""}` : `<span class="muted-text">等待 ${escapeHtml(capabilities.join(" / ") || "未知")} 适配器</span>`}<button class="ghost-button" type="button" data-plugin-revoke="${escapeHtml(plugin.candidate_id)}" ${busy ? "disabled" : ""}>撤销</button>`;
    } else {
      actions = `<span class="muted-text">请修复后重新扫描</span>`;
    }
    const form = state.pluginConfigId === plugin.candidate_id ? renderPluginLauncherForm(plugin) : "";
    return `<article class="plugin-row"><div class="plugin-row-main"><div class="plugin-row-heading"><strong>${escapeHtml(plugin.plugin_id || "未识别插件")}</strong><span class="plugin-state ${escapeHtml(plugin.state || "invalid")}">${pluginStatusLabel(plugin.state)}</span>${plugin.launcher && Object.keys(plugin.launcher).length ? `<span class="plugin-state configured">已配置</span>` : ""}</div><small>v${escapeHtml(plugin.version || "?")} · ${escapeHtml(capabilities.join(" / ") || "无能力声明")} · ${escapeHtml(plugin.manifest_path || "未知路径")}</small>${plugin.error ? `<p class="plugin-error">${escapeHtml(plugin.error)}</p>` : `<code>${escapeHtml(plugin.manifest_sha256 || "")}</code>`}${form}</div><div class="plugin-row-actions">${actions}</div></article>`;
  }

  function renderPluginLauncherForm(plugin) {
    const launcher = plugin.launcher && typeof plugin.launcher === "object" ? plugin.launcher : {};
    const separator = String(plugin.root_path || "").includes("\\") ? "\\" : "/";
    const entrypoint = `${plugin.root_path || ""}${separator}${plugin.manifest?.entrypoint || ""}`;
    const argumentsValue = launcher.arguments?.length ? launcher.arguments : [entrypoint];
    return `<form class="plugin-launcher-form" data-plugin-launcher-form="${escapeHtml(plugin.candidate_id)}"><label><span>启动程序绝对路径</span><input name="executable" type="text" value="${escapeHtml(launcher.executable || "")}" required /></label><label><span>固定参数（JSON 数组）</span><textarea name="arguments" rows="2">${escapeHtml(JSON.stringify(argumentsValue))}</textarea></label><div class="plugin-launcher-grid"><label><span>工作目录</span><input name="working_directory" type="text" value="${escapeHtml(launcher.working_directory || plugin.root_path || "")}" /></label><label><span>超时秒数</span><input name="timeout_seconds" type="number" min="1" max="120" value="${escapeHtml(launcher.timeout_seconds || 30)}" /></label></div><div class="plugin-launcher-actions"><button class="small-button" type="submit" ${state.pluginBusy ? "disabled" : ""}>保存启动配置</button><button class="ghost-button" type="button" data-plugin-config-close>取消</button></div></form>`;
  }

  return { renderDeveloper };
}
