import { projectModules } from "./module-selector.js";

export function createModulesView({
  activeProviderProfile,
  audioCapabilityLabel,
  audioCapabilityStateLabel,
  audioPermissionLabel,
  audioPermissionStateLabel,
  capabilityEntryStatusClass,
  capabilityLocationLabel,
  capabilitySourceLabel,
  capabilityStatusLabel,
  escapeHtml,
  fallbackAudioStatus,
  fallbackVisionStatus,
  formatTime,
  moduleStatusLabel,
  pricingCashLabel,
  pricingEvidenceLabel,
  pricingProviderChargeLabel,
  pricingSourceLabel,
  providerModelEntries,
  providerModelSummary,
  providerProfileStatusLabel,
  renderPageFrame,
  routePricingSnapshotsForProfile,
  state,
  visionPermissionLabel,
  visionPermissionStateLabel,
  visionSourceLabel,
  visionStateLabel,
  webChatAdapter,
  webChatArrayText,
  webChatConfig,
  webChatProfileForModule,
  webChatProfileModel,
  webChatReady,
  webChatStatusLabel,
}) {
  function renderModules() {
    const selection = projectModules(state);
    const notices = [state.moduleNotice, state.providerNotice, state.webChatNotice].filter(Boolean).map((notice) => `<div class="module-notice" role="status">${escapeHtml(notice)}</div>`).join("");
    if (selection.loading || selection.failed || !state.modules.length) {
      const message = selection.loading ? "正在读取模块目录…" : selection.failed ? "模块目录读取失败。未启用任何替代能力，请检查核心连接后重试。" : "当前没有可添加的模块。";
      return renderPageFrame("模块", "只开启需要的能力，配置与权限始终由你决定。", `${notices}<div class="empty-panel" role="status" aria-busy="${selection.loading}">${message}${selection.loading ? "" : '<button class="outline-button" type="button" data-modules-retry>重新读取</button>'}</div>${renderProviderDrawer()}${renderWebChatDrawer()}`);
    }
    const addLibrary = selection.available.length
      ? `<details class="module-add-library" data-ui-key="module-library"><summary class="module-add-tile"><span class="module-add-summary"><strong>未启用的连接与功能</strong><small>${selection.available.length} 项 · 配置与权限独立管理</small></span></summary><div class="module-grid module-add-grid">${selection.available.map((module) => module.id === "llm" ? renderLlmModuleCard(module) : renderModuleAddCard(module)).join("")}</div></details>`
      : "";
    const active = selection.enabled.length ? `<div class="module-grid active-modules">${selection.enabled.map(renderModuleCard).join("")}</div>` : '<div class="empty-panel module-empty">尚无已启用功能</div>';
    const pricing = selection.enabled.some((module) => module.id === "llm") ? `<details class="module-evidence" data-ui-key="route-pricing"><summary>模型费用与定价证据</summary>${renderRoutePricingPanel()}</details>` : "";
    const body = `${active}${addLibrary}${selection.toolsVisible ? renderToolRuntime() : ""}${selection.visionVisible ? renderVisionRuntime() : ""}${selection.audioVisible ? renderAudioRuntime() : ""}${pricing}`;
    return renderPageFrame("模块", "只开启需要的能力，配置与权限始终由你决定。", `${notices}${body}${renderProviderDrawer()}${renderWebChatDrawer()}`);
  }

  function renderModuleAddCard(module) {
    const busy = state.moduleBusy === module.id;
    return `<article class="module-add-card">
      <div class="module-card-top"><span class="module-icon">${escapeHtml(module.capability.toUpperCase())}</span></div>
      <strong>${escapeHtml(module.name)}</strong><p>${escapeHtml(module.description)}</p>
      <button class="small-button" type="button" data-module-toggle="${escapeHtml(module.id)}" ${busy ? "disabled" : ""}>${busy ? "处理中" : "启用功能"}</button>
    </article>`;
  }

  function renderRoutePricingPanel() {
    const snapshots = Array.isArray(state.routePricingCatalog?.snapshots) ? state.routePricingCatalog.snapshots : [];
    const errors = state.routePricingCatalog?.errors && typeof state.routePricingCatalog.errors === "object"
      ? Object.keys(state.routePricingCatalog.errors)
      : [];
    const notice = state.routePricingNotice
      ? `<div class="route-pricing-notice" role="status">${escapeHtml(state.routePricingNotice)}</div>`
      : "";
    const rows = snapshots.slice(0, 80).map((snapshot) => {
      const profile = state.providerProfiles.find((item) => item.id === snapshot.provider_profile_id);
      const sourceVersion = snapshot.source_version ? ` · v${snapshot.source_version}` : "";
      return `<div class="route-pricing-row" data-route-pricing-model="${escapeHtml(snapshot.model_id || "unknown")}">
        <div><strong>${escapeHtml(snapshot.model_id || "未知模型")}</strong><small>${escapeHtml(profile?.name || snapshot.provider_profile_id || "未知档案")} · ${escapeHtml(snapshot.billing_group || "默认分组")}</small></div>
        <div><strong>${escapeHtml(pricingProviderChargeLabel(snapshot))}</strong><small>${escapeHtml(pricingCashLabel(snapshot))}</small></div>
        <div><strong>${escapeHtml(pricingSourceLabel(snapshot.source_type))}${escapeHtml(sourceVersion)}</strong><small>${escapeHtml(pricingEvidenceLabel(snapshot))} · ${escapeHtml(formatTime(snapshot.observed_at))}</small></div>
      </div>`;
    }).join("");
    const status = state.routePricingBusy
      ? "读取中"
      : `${snapshots.length} 条模型/分组证据${errors.length ? ` · ${errors.length} 个来源失败` : ""}`;
    return `<section class="dev-panel route-pricing-panel" data-route-pricing-panel><div class="panel-heading"><div><strong>Route 定价证据</strong><small>站内扣费与实际现金折算分开记录；未知价格不会被当作免费。</small></div><button class="small-button" id="refresh-route-pricing" type="button" ${state.routePricingBusy ? "disabled" : ""}>${state.routePricingBusy ? "刷新中" : "刷新价格"}</button></div><div class="route-pricing-summary"><span>${escapeHtml(status)}</span><span>最近检查：${escapeHtml(formatTime(state.routePricingCatalog?.checked_at))}</span></div>${notice}<div class="route-pricing-list">${rows || `<div class="empty-column">尚无定价证据。可在 Provider 高级设置中选择来源并配置计费分组。</div>`}</div></section>`;
  }

  function renderCapabilityCatalogPanel() {
    const catalog = state.capabilityCatalog;
    const summary = catalog?.summary || {};
    const groups = Array.isArray(catalog?.groups) ? catalog.groups : [];
    const notice = state.capabilityCatalogNotice
      ? `<div class="capability-catalog-notice" role="status">${escapeHtml(state.capabilityCatalogNotice)}</div>`
      : "";
    const groupRows = groups.map((group) => {
      const entries = Array.isArray(group.entries) ? group.entries : [];
      const entryRows = entries.map((entry) => {
        const metadata = entry.metadata && typeof entry.metadata === "object" ? entry.metadata : {};
        const manualLogin = metadata.requires_user_login === true || entry.source_type === "web-chat";
        const stateText = capabilityStatusLabel(entry.status);
        const selectable = entry.selectable === true;
        const selected = entry.selected === true;
        return `<div class="capability-entry" data-capability-entry="${escapeHtml(entry.id || "unknown")}">
          <div class="capability-entry-main"><strong>${escapeHtml(entry.name || entry.id || "未命名实现")}</strong><small>${escapeHtml(capabilitySourceLabel(entry.source_type))} · ${escapeHtml(entry.transport || "未知传输")} · ${escapeHtml(capabilityLocationLabel(entry.processing_location))}</small>${manualLogin ? `<small class="capability-entry-warning">需要人工登录 / 隔离浏览器，不作为 API Provider</small>` : ""}</div>
          <div class="capability-entry-state"><span class="capability-status ${capabilityEntryStatusClass(entry.status)}">${escapeHtml(stateText)}</span>${selected ? `<span class="capability-selected">当前</span>` : selectable ? `<span class="capability-selectable">可选</span>` : ""}</div>
        </div>`;
      }).join("");
      return `<section class="capability-group" data-capability-group="${escapeHtml(group.id || "unknown")}"><div class="capability-group-heading"><strong>${escapeHtml(group.name || group.id || "能力")}</strong><span>${escapeHtml(String(group.entry_count ?? entries.length))}</span></div>${entryRows || `<div class="empty-column">暂无已登记实现</div>`}</section>`;
    }).join("");
    const body = groupRows || (catalog
      ? `<div class="empty-column">当前没有可展示的真实实现。</div>`
      : `<div class="empty-column">目录尚未加载；点击刷新读取当前运行时和 Provider 状态。</div>`);
    return `<section class="dev-panel capability-catalog-panel" data-capability-catalog><div class="panel-heading"><div><strong>统一能力目录</strong><small>各能力的真实实现状态；启停和路由仍在模块页。</small></div><button class="small-button" id="refresh-capability-catalog" type="button" ${state.capabilityCatalogBusy ? "disabled" : ""}>${state.capabilityCatalogBusy ? "读取中" : "刷新"}</button></div>${notice}<div class="capability-catalog-summary"><span>实现 ${escapeHtml(String(summary.entry_count ?? 0))}</span><span>就绪 ${escapeHtml(String(summary.ready_count ?? 0))}</span><span>可选 ${escapeHtml(String(summary.selectable_count ?? 0))}</span>${summary.source_errors ? `<span class="warn">来源错误 ${escapeHtml(String(summary.source_errors))}</span>` : ""}</div><div class="capability-group-grid">${body}</div></section>`;
  }

  function renderToolRuntime() {
    const module = state.modules.find((item) => item.id === "tools");
    const configured = Boolean(module?.enabled && module?.implementation_id === "external-process" && module?.config?.executable);
    const notice = state.toolNotice ? `<div class="tool-notice" role="status">${escapeHtml(state.toolNotice)}</div>` : "";
    const status = !module?.enabled ? "模块未启用" : module.implementation_id !== "external-process" ? "未选择外部进程实现" : module.config?.executable ? "已配置，等待显式调用" : "等待填写可执行文件路径";
    return `<section class="tool-runtime-panel"><div class="tool-runtime-heading"><div><span class="eyebrow">EXTERNAL TOOLS</span><strong>外部软件调用</strong><small>绝对路径直接启动、不经 shell；每次调用都需明确批准。</small></div><button class="outline-button" id="run-tool-test" type="button" ${!configured || state.toolBusy ? "disabled" : ""}>${state.toolBusy ? "调用中" : "审批并测试"}</button></div>${notice}<div class="tool-runtime-status"><span class="module-status ${configured ? "available" : "unconfigured"}">${escapeHtml(status)}</span><code>${escapeHtml(module?.config?.executable || "未配置路径")}</code></div></section>`;
  }

  function renderVisionRuntime() {
    const status = state.visionStatus || fallbackVisionStatus;
    const permissions = status.permissions || [];
    const sources = (status.sources || []).filter((source) => state.modules.some((module) => (module.id === source.id || module.id === "vision") && module.enabled === true));
    const notice = state.visionNotice ? `<div class="vision-notice" role="status">${escapeHtml(state.visionNotice)}</div>` : "";
    const permissionRows = permissions.map((permission) => {
      const busy = state.visionBusy === `permission:${permission.permission_id}`;
      return `<div class="vision-permission-row"><div><strong>${escapeHtml(visionPermissionLabel(permission.permission_id))}</strong><small>${escapeHtml(visionPermissionStateLabel(permission.state))}</small></div><div class="audio-actions"><button class="small-button" type="button" data-vision-permission="${escapeHtml(permission.permission_id)}" data-vision-granted="true" ${busy ? "disabled" : ""}>允许</button><button class="ghost-button" type="button" data-vision-permission="${escapeHtml(permission.permission_id)}" data-vision-granted="false" ${busy ? "disabled" : ""}>拒绝</button></div></div>`;
    }).join("");
    const sourceRows = sources.map((source) => {
      const busy = state.visionBusy === `source:${source.id}`;
      const canStart = source.enabled && source.provider_id !== "none" && !source.running && source.state === "ready";
      return `<div class="vision-source-row"><div><strong>${escapeHtml(visionSourceLabel(source.id))}</strong><small>${escapeHtml(source.provider_id)} · ${escapeHtml(visionStateLabel(source.state))}</small></div><div class="audio-actions">${source.running ? `<button class="small-button" type="button" data-vision-stop="${escapeHtml(source.id)}" ${busy ? "disabled" : ""}>停止</button>` : `<button class="small-button" type="button" data-vision-start="${escapeHtml(source.id)}" ${!canStart || busy ? "disabled" : ""}>启动</button>`}</div></div>`;
    }).join("");
    return `<section class="vision-runtime-panel"><div class="vision-runtime-heading"><div><span class="eyebrow">VISION RUNTIME</span><strong>视觉权限与运行状态</strong><small>授权并启动来源后才能提交一次内存图像；原始数据和摘要不自动写入日志。</small></div><button class="outline-button" id="refresh-vision-status" type="button">刷新</button></div>${notice}<div class="vision-runtime-grid"><div><div class="audio-section-label">来源权限</div>${permissionRows || `<div class="empty-column">暂无权限项</div>`}</div><div><div class="audio-section-label">来源运行</div>${sourceRows || `<div class="empty-column">暂无视觉来源</div>`}</div></div></section>`;
  }

  function renderAudioRuntime() {
    const status = state.audioStatus || fallbackAudioStatus;
    const permissions = status.permissions || [];
    const capabilities = (status.capabilities || []).filter((capability) => state.modules.some((module) => module.id === capability.id && module.enabled === true));
    const notice = state.audioNotice ? `<div class="audio-notice" role="status">${escapeHtml(state.audioNotice)}</div>` : "";
    const permissionRows = permissions.map((permission) => {
      const busy = state.audioBusy === `permission:${permission.permission_id}`;
      return `<div class="audio-permission-row"><div><strong>${escapeHtml(audioPermissionLabel(permission.permission_id))}</strong><small>${escapeHtml(audioPermissionStateLabel(permission.state))}</small></div><div class="audio-actions"><button class="small-button" type="button" data-audio-permission="${escapeHtml(permission.permission_id)}" data-audio-granted="true" ${busy ? "disabled" : ""}>允许</button><button class="ghost-button" type="button" data-audio-permission="${escapeHtml(permission.permission_id)}" data-audio-granted="false" ${busy ? "disabled" : ""}>拒绝</button></div></div>`;
    }).join("");
    const capabilityRows = capabilities.map((capability) => {
      const busy = state.audioBusy === `capability:${capability.id}`;
      const canStart = capability.enabled && capability.provider_id !== "none" && !capability.running;
      return `<div class="audio-capability-row"><div><strong>${escapeHtml(audioCapabilityLabel(capability.id))}</strong><small>${escapeHtml(capability.provider_id)} · ${escapeHtml(audioCapabilityStateLabel(capability.state))}</small></div><div class="audio-actions">${capability.running ? `<button class="small-button" type="button" data-audio-stop="${escapeHtml(capability.id)}" ${busy ? "disabled" : ""}>停止</button>` : `<button class="small-button" type="button" data-audio-start="${escapeHtml(capability.id)}" ${!canStart || busy ? "disabled" : ""}>启动</button>`}</div></div>`;
    }).join("");
    return `<section class="audio-runtime-panel"><div class="audio-runtime-heading"><div><span class="eyebrow">AUDIO RUNTIME</span><strong>语音权限与运行状态</strong><small>显式授权并启动后才会向选定 provider 传音频；原始数据只留在内存。</small></div><button class="outline-button" id="refresh-audio-status" type="button">刷新</button></div>${notice}<div class="audio-runtime-grid"><div><div class="audio-section-label">设备权限</div>${permissionRows || `<div class="empty-column">暂无权限项</div>`}</div><div><div class="audio-section-label">能力运行</div>${capabilityRows || `<div class="empty-column">暂无音频模块</div>`}</div></div></section>`;
  }

  function renderModuleCard(module) {
    if (module.id === "llm") return renderLlmModuleCard(module);
    const busy = state.moduleBusy === module.id;
    const implementationOptions = (module.implementations || []).filter((implementation) => implementation.id !== "none").map((implementation) => `<option value="${escapeHtml(implementation.id)}" ${implementation.id === module.implementation_id ? "selected" : ""}>${escapeHtml(implementation.name)}${implementation.status === "preview" ? " · 预览" : ""}</option>`).join("");
    const permissions = module.permissions?.length ? module.permissions.join(" · ") : "无额外权限";
    return `<article class="module-card ${module.enabled ? "" : "module-disabled"}">
      <div class="module-card-top"><span class="module-icon">${escapeHtml(module.capability.toUpperCase())}</span><span class="module-status ${escapeHtml(module.status)}">${moduleStatusLabel(module)}</span><button class="module-toggle" type="button" role="switch" aria-checked="${module.enabled}" aria-label="切换 ${escapeHtml(module.name)}" data-module-toggle="${escapeHtml(module.id)}" ${busy ? "disabled" : ""}><span class="switch ${module.enabled ? "on" : "off"}"></span></button></div>
      <strong>${escapeHtml(module.name)}</strong><p>${escapeHtml(module.description)}</p>
      <label class="module-select-field">实现方式<select data-module-implementation="${escapeHtml(module.id)}" ${busy ? "disabled" : ""}>${implementationOptions}</select></label>
      ${renderModuleConfig(module)}
      <div class="module-card-meta"><span>权限</span><small>${escapeHtml(permissions)}</small></div>
    </article>`;
  }

  function renderLlmModuleCard(module) {
    const busy = state.moduleBusy === module.id || Boolean(state.providerBusy);
    const apiProfiles = state.providerProfiles.filter((profile) => !profile.archived_at);
    const webProfiles = state.webChatProfiles.filter((profile) => !profile.archived_at);
    const currentWeb = webChatProfileForModule(module);
    const currentApi = activeProviderProfile() || (!currentWeb ? module.profile : null);
    const current = currentWeb || currentApi || apiProfiles[0] || webProfiles[0] || null;
    const available = apiProfiles.filter((profile) => profile.status === "available");
    const pending = apiProfiles.filter((profile) => profile.status !== "available");
    const webAvailable = webProfiles.filter((profile) => webChatReady(profile));
    const webPending = webProfiles.filter((profile) => !webChatReady(profile));
    const webTemplates = state.webChatAdapters
      .filter((adapter) => adapter.id !== "custom")
      .map((adapter) => `<button class="web-chat-template-row" type="button" data-web-chat-new-adapter="${escapeHtml(adapter.id)}"><span><strong>${escapeHtml(adapter.name || adapter.id)}</strong><small>${escapeHtml((adapter.domains || []).join(" · "))} · 模板</small></span><span>添加</span></button>`)
      .join("");
    const rows = [
      available.length ? `<div class="provider-picker-group"><span>可用连接</span>${available.map(renderProviderProfileRow).join("")}</div>` : "",
      pending.length ? `<div class="provider-picker-group"><span>草稿与未就绪</span>${pending.map(renderProviderProfileRow).join("")}</div>` : "",
      webAvailable.length ? `<div class="provider-picker-group"><span>可用网页聊天</span>${webAvailable.map(renderWebChatProfileRow).join("")}</div>` : "",
      webPending.length ? `<div class="provider-picker-group"><span>网页登录与草稿</span>${webPending.map(renderWebChatProfileRow).join("")}</div>` : "",
      webTemplates ? `<div class="provider-picker-group"><span>网页聊天模板</span>${webTemplates}</div>` : "",
    ].join("");
    const currentReady = currentWeb ? webChatReady(currentWeb) : currentApi?.status === "available";
    const summary = current
      ? `<span><strong>${escapeHtml(current.name)}</strong><small>${escapeHtml(currentWeb ? webChatProfileModel(currentWeb) : current.config?.model || "未填写模型")} · ${escapeHtml(currentWeb ? webChatStatusLabel(currentWeb) : providerProfileStatusLabel(current.status))}</small></span>`
      : `<span><strong>尚未配置</strong><small>创建一个真实连接后启用</small></span>`;
    return `<article class="module-card llm-module-card ${module.enabled ? "" : "module-disabled"}">
      <div class="module-card-top"><span class="module-icon">LLM</span><span class="module-status ${escapeHtml(module.status)}">${moduleStatusLabel(module)}</span><button class="module-toggle" type="button" role="switch" aria-checked="${module.enabled}" aria-label="切换 ${escapeHtml(module.name)}" data-module-toggle="${escapeHtml(module.id)}" ${busy || (!module.enabled && !currentReady) ? "disabled" : ""}><span class="switch ${module.enabled ? "on" : "off"}"></span></button></div>
      <strong>${escapeHtml(module.name)}</strong><p>${escapeHtml(module.description)}</p>
      <details class="provider-picker"><summary><span class="provider-picker-label">实现方式</span>${summary}<span class="provider-picker-chevron" aria-hidden="true">⌄</span></summary><div class="provider-picker-menu">${rows || `<div class="provider-picker-empty">还没有保存的连接</div>`}<button class="provider-add-row" type="button" data-provider-new><span aria-hidden="true">＋</span>自定义 API 连接</button><button class="provider-add-row web-chat-add-row" type="button" data-web-chat-new-adapter="custom"><span aria-hidden="true">＋</span>自定义网页聊天</button></div></details>
      <div class="llm-profile-meta"><span>${escapeHtml(currentWeb ? "云端 · 浏览器" : current?.resolved_processing_location === "cloud" ? "云端" : "本地")}</span><code>${escapeHtml(currentWeb ? currentWeb.chat_url || "网页聊天" : current?.config?.active_base_url || "未配置端点")}</code>${currentWeb ? `<button class="ghost-button" type="button" data-web-chat-edit="${escapeHtml(currentWeb.id)}">编辑</button>` : current ? `<button class="ghost-button" type="button" data-provider-edit="${escapeHtml(current.id)}">编辑</button>` : ""}</div>
      <div class="module-card-meta"><span>权限</span><small>密钥使用系统安全凭据存储；当前 Windows 已实现</small></div>
    </article>`;
  }

  function renderProviderProfileRow(profile) {
    const active = activeProviderProfile()?.id === profile.id;
    const status = providerProfileStatusLabel(profile.status);
    return `<div class="provider-profile-row ${active ? "active" : ""}"><button type="button" data-provider-select="${escapeHtml(profile.id)}" ${state.providerBusy ? "disabled" : ""}><span><strong>${escapeHtml(profile.name)}</strong><small>${escapeHtml(providerModelSummary(profile))} · ${escapeHtml(status)}</small></span>${active ? `<span class="provider-active-mark">当前</span>` : ""}</button><button class="icon-button provider-row-edit" type="button" data-provider-edit="${escapeHtml(profile.id)}" title="编辑连接" aria-label="编辑 ${escapeHtml(profile.name)}">⋯</button></div>`;
  }

  function renderProviderModelRows(profile) {
    const rows = providerModelEntries(profile);
    if (!rows.length) return `<div class="provider-model-empty">尚未登记模型；可从端点获取，或手动填写。</div>`;
    const defaultModel = String(profile?.config?.model || "").trim();
    return `<ul class="provider-model-list">${rows.map((row) => {
      const modelId = String(row?.id || "").trim();
      const label = String(row?.name || modelId).trim() || modelId;
      const health = String(row?.health_state || "unknown");
      return `<li><span><strong>${escapeHtml(label)}</strong><small>${escapeHtml(modelId)} · ${escapeHtml(health)}${modelId === defaultModel ? " · 默认" : ""}</small></span><span class="provider-model-actions"><button class="small-button" type="button" data-provider-model-health-profile="${escapeHtml(profile.id)}" data-provider-model-health-id="${escapeHtml(modelId)}" ${state.providerBusy ? "disabled" : ""}>测试</button>${modelId !== defaultModel && row?.enabled !== false ? `<button class="ghost-button" type="button" data-provider-model-select-profile="${escapeHtml(profile.id)}" data-provider-model-select-id="${escapeHtml(modelId)}" ${state.providerBusy ? "disabled" : ""}>设为默认</button>` : ""}</span></li>`;
    }).join("")}</ul>`;
  }

  function renderProviderPricingEvidence(profile) {
    if (!profile?.id) return "";
    const snapshots = routePricingSnapshotsForProfile(profile.id);
    const error = state.routePricingCatalog?.errors?.[profile.id];
    const rows = snapshots.slice(0, 24).map((snapshot) => `<li><span><strong>${escapeHtml(snapshot.model_id || "未知模型")} · ${escapeHtml(snapshot.billing_group || "默认分组")}</strong><small>${escapeHtml(pricingProviderChargeLabel(snapshot))} · ${escapeHtml(pricingCashLabel(snapshot))}</small></span><span><strong>${escapeHtml(pricingSourceLabel(snapshot.source_type))}</strong><small>${escapeHtml(pricingEvidenceLabel(snapshot))} · ${escapeHtml(formatTime(snapshot.observed_at))}</small></span></li>`).join("");
    return `<section class="provider-pricing-evidence" data-provider-pricing-evidence><div class="provider-model-section-heading"><strong>当前定价证据</strong><button class="small-button" type="button" data-provider-pricing-refresh="${escapeHtml(profile.id)}" ${state.routePricingBusy ? "disabled" : ""}>${state.routePricingBusy ? "读取中" : "刷新"}</button></div>${error ? `<div class="provider-pricing-error">来源读取失败：${escapeHtml(error)}</div>` : ""}<ul>${rows || `<li class="provider-model-empty">保存定价配置并刷新后显示；未知不会被当作免费。</li>`}</ul></section>`;
  }

  function renderWebChatProfileRow(profile) {
    const active = webChatProfileForModule()?.id === profile.id;
    const ready = webChatReady(profile);
    const busy = state.webChatBusy;
    const status = webChatStatusLabel(profile);
    const action = profile.archived_at
      ? `<button class="ghost-button" type="button" data-web-chat-restore="${escapeHtml(profile.id)}" ${busy ? "disabled" : ""}>恢复</button>`
      : `<button class="ghost-button" type="button" data-web-chat-edit="${escapeHtml(profile.id)}" ${busy ? "disabled" : ""}>编辑</button><button class="ghost-button" type="button" data-web-chat-authorize="${escapeHtml(profile.id)}" ${busy ? "disabled" : ""}>人工登录</button><button class="ghost-button" type="button" data-web-chat-check="${escapeHtml(profile.id)}" ${busy ? "disabled" : ""}>检查</button>${ready && !profile.auto_chat_enabled ? `<button class="small-button" type="button" data-web-chat-consent="${escapeHtml(profile.id)}" ${busy ? "disabled" : ""}>授权聊天</button>` : ""}${ready && profile.auto_chat_enabled && !active ? `<button class="small-button" type="button" data-web-chat-select="${escapeHtml(profile.id)}" ${busy ? "disabled" : ""}>启用</button>` : ""}${active && profile.auto_chat_enabled ? `<button class="ghost-button" type="button" data-web-chat-consent-off="${escapeHtml(profile.id)}" ${busy ? "disabled" : ""}>停用授权</button>` : ""}<button class="icon-button provider-row-edit" type="button" data-web-chat-archive="${escapeHtml(profile.id)}" title="归档" aria-label="归档 ${escapeHtml(profile.name)}" ${busy || active ? "disabled" : ""}>×</button>`;
    return `<div class="provider-profile-row web-chat-profile-row ${active ? "active" : ""}"><div class="web-chat-profile-main"><strong>${escapeHtml(profile.name)}</strong><small>${escapeHtml(webChatProfileModel(profile))} · ${escapeHtml(status)} · ${escapeHtml(profile.chat_url || "")}</small></div><div class="web-chat-profile-actions">${active ? `<span class="provider-active-mark">当前</span>` : ""}${action}</div></div>`;
  }

  function renderProviderDrawer() {
    if (!state.providerDrawerOpen) return "";
    const profile = state.providerProfiles.find((item) => item.id === state.providerDrawerProfileId) || null;
    const config = profile?.config || {};
    const selectedTemplate = state.providerTemplates.find((item) => item.id === (profile?.template_id || "openai-compatible")) || {};
    const templates = state.providerTemplates.map((template) => `<option value="${escapeHtml(template.id)}" ${template.id === (profile?.template_id || "openai-compatible") ? "selected" : ""}>${escapeHtml(template.name)}</option>`).join("");
    const modelOptions = Array.isArray(selectedTemplate.model_options) ? selectedTemplate.model_options : [];
    const modelDatalist = modelOptions.map((model) => `<option value="${escapeHtml(model)}"></option>`).join("");
    const modelEntries = providerModelEntries(profile);
    const modelLines = modelEntries.map((item) => String(item?.id || "").trim()).filter(Boolean).join("\n");
    const pricing = config.pricing && typeof config.pricing === "object" ? config.pricing : {};
    const pricingRates = pricing.rates && typeof pricing.rates === "object" ? pricing.rates : {};
    const cashConversion = pricing.cash_conversion && typeof pricing.cash_conversion === "object" ? pricing.cash_conversion : {};
    const pricingSource = String(pricing.source_type || "");
    const manual = `<form id="provider-profile-form" class="provider-drawer-form" data-profile-id="${escapeHtml(profile?.id || "")}">
      <div class="provider-form-grid"><label><span>连接名称</span><input name="name" value="${escapeHtml(profile?.name || "")}" maxlength="80" required autofocus /></label><label><span>连接模板</span><select name="template_id" id="provider-template-select">${templates}</select></label></div>
      <label><span>当前 Base URL</span><input name="active_base_url" type="url" value="${escapeHtml(config.active_base_url || "")}" placeholder="https://api.example.com/v1" required /></label>
      <label><span>备用端点（每行一个）</span><textarea name="alternate_urls" rows="3" placeholder="只保存，不自动故障转移">${escapeHtml((config.base_urls || []).filter((value) => value !== config.active_base_url).join("\n"))}</textarea></label>
      <div class="provider-form-grid"><label><span>默认模型</span><input name="model" list="provider-model-options" value="${escapeHtml(config.model || "")}" placeholder="模型 ID" required /><datalist id="provider-model-options">${modelDatalist}</datalist></label><label><span>处理位置</span><select name="processing_location"><option value="auto" ${profile?.processing_location === "auto" ? "selected" : ""}>自动判断</option><option value="local" ${profile?.processing_location === "local" ? "selected" : ""}>本地处理</option><option value="cloud" ${profile?.processing_location === "cloud" ? "selected" : ""}>云端处理</option></select></label></div>
      <label><span>档案模型列表（每行一个）</span><textarea name="models" rows="4" placeholder="同一把 Key 可挂多个模型，例如：\nglm-4.5-air\nglm-4.6\nglm-4.7">${escapeHtml(modelLines)}</textarea><small class="provider-field-hint">请求时每个模型使用独立 route，共用此档案的凭据；“发现模型”只读取 GET /models，不发送聊天请求。</small></label>
      ${profile ? `<section class="provider-model-section"><div class="provider-model-section-heading"><strong>已登记模型</strong><button class="small-button" type="button" data-provider-model-discover="${escapeHtml(profile.id)}" ${state.providerBusy ? "disabled" : ""}>${state.providerBusy === `models:${profile.id}` ? "获取中" : "从端点获取"}</button></div>${renderProviderModelRows(profile)}</section>` : ""}
      <label><span>API Key</span><input name="api_key" type="password" value="" autocomplete="new-password" placeholder="${profile?.has_secrets ? "已安全保存，留空保持不变" : "本地免鉴权服务可以留空"}" /></label>
      ${profile?.has_secrets ? `<label class="provider-clear-secret"><input name="clear_api_key" type="checkbox" /><span>清除已保存的 API Key</span></label>` : ""}
      <details class="provider-advanced"><summary>高级设置</summary><div><div class="provider-form-grid"><label><span>超时（秒）</span><input name="timeout" type="number" min="1" max="300" value="${escapeHtml(config.timeout || 60)}" /></label><label><span>Organization</span><input name="organization" value="${escapeHtml(config.organization || "")}" /></label></div><label><span>Project</span><input name="project" value="${escapeHtml(config.project || "")}" /></label><label><span>额外请求头（JSON）</span><textarea name="headers" rows="4">${escapeHtml(JSON.stringify(config.headers || {}, null, 2))}</textarea></label><label><span>声明式用量查询（JSON，可留空）</span><textarea name="usage_query" rows="4" placeholder='{"enabled":false,"method":"GET","url":"{{baseUrl}}/usage","fields":{}}'>${escapeHtml(config.usage_query ? JSON.stringify(config.usage_query, null, 2) : "")}</textarea></label>
        <section class="provider-pricing-config"><div class="provider-pricing-heading"><strong>Route 定价</strong><small>单价按档案、模型和计费分组隔离</small></div>
          <div class="provider-form-grid"><label><span>定价来源</span><select name="pricing_source_type"><option value="" ${!pricingSource ? "selected" : ""}>未配置</option><option value="direct-official" ${pricingSource === "direct-official" ? "selected" : ""}>官方定价（手动）</option><option value="new-api" ${pricingSource === "new-api" ? "selected" : ""}>New API 公开接口</option><option value="pinai" ${pricingSource === "pinai" ? "selected" : ""}>PinAI 公开接口</option><option value="manual" ${pricingSource === "manual" ? "selected" : ""}>中转站 / 人工录入</option></select></label><label><span>计费分组</span><input name="pricing_billing_group" value="${escapeHtml(pricing.billing_group || "")}" placeholder="留空显示全部分组" /></label></div>
          <div class="provider-form-grid"><label><span>公开价格地址</span><input name="pricing_public_url" type="url" value="${escapeHtml(pricing.public_url || "")}" placeholder="PinAI 可留空；New API 默认使用 Base URL" /></label><label><span>来源页面</span><input name="pricing_source_url" type="url" value="${escapeHtml(pricing.source_url || "")}" placeholder="官方文档或定价页" /></label></div>
          <div class="provider-pricing-rate-grid"><label><span>站内币种</span><input name="pricing_currency" value="${escapeHtml(pricingRates.currency || "")}" placeholder="CNY / USD-credit" /></label><label><span>输入 / 百万 token</span><input name="pricing_input_rate" type="number" min="0" step="any" value="${escapeHtml(pricingRates.input_price_per_million ?? "")}" /></label><label><span>输出 / 百万 token</span><input name="pricing_output_rate" type="number" min="0" step="any" value="${escapeHtml(pricingRates.output_price_per_million ?? "")}" /></label><label><span>缓存读 / 百万 token</span><input name="pricing_cache_read_rate" type="number" min="0" step="any" value="${escapeHtml(pricingRates.cache_read_price_per_million ?? "")}" /></label><label><span>缓存写 / 百万 token</span><input name="pricing_cache_write_rate" type="number" min="0" step="any" value="${escapeHtml(pricingRates.cache_write_price_per_million ?? "")}" /></label><label><span>每请求固定价</span><input name="pricing_request_rate" type="number" min="0" step="any" value="${escapeHtml(pricingRates.request_price ?? "")}" /></label></div>
          <div class="provider-pricing-rate-grid"><label><span>实际支付金额</span><input name="pricing_paid_amount" type="number" min="0" step="any" value="${escapeHtml(cashConversion.paid_amount ?? "")}" /></label><label><span>到账站内余额</span><input name="pricing_credited_amount" type="number" min="0" step="any" value="${escapeHtml(cashConversion.credited_amount ?? "")}" /></label><label><span>现金币种</span><input name="pricing_cash_currency" value="${escapeHtml(cashConversion.currency || "CNY")}" maxlength="16" /></label></div>
          <label><span>价格版本（可选）</span><input name="pricing_source_version" value="${escapeHtml(pricing.source_version || "")}" maxlength="160" /></label>
        </section>${renderProviderPricingEvidence(profile)}
      </div></details>
      <div class="provider-drawer-actions">${profile && !profile.active ? `<button class="ghost-button danger-text" type="button" data-provider-archive="${escapeHtml(profile.id)}">归档</button>` : ""}<span></span><button class="ghost-button" type="submit" data-provider-action="save" ${state.providerBusy ? "disabled" : ""}>保存草稿</button><button class="outline-button" type="submit" data-provider-action="test" ${state.providerBusy ? "disabled" : ""}>测试连接</button><button class="primary-button" type="submit" data-provider-action="activate" ${state.providerBusy ? "disabled" : ""}>保存并启用</button></div>
    </form>`;
    const importer = `<section class="provider-import-pane"><label><span>粘贴配置</span><textarea id="provider-import-raw" rows="9" placeholder="ccswitch://v1/import?... 或 Sumika JSON / OpenAI JSON / Codex TOML">${escapeHtml(state.providerImportRaw)}</textarea></label><div class="provider-import-tools"><input id="provider-import-file" type="file" accept=".json,.toml,.txt" /><button class="outline-button" type="button" id="provider-import-preview" ${state.providerBusy ? "disabled" : ""}>预览导入</button></div><p>导入只生成 Sumika 草稿档案，不注册系统协议，也不会执行 JavaScript。</p>${renderProviderImportPreview()}</section>`;
    return `<div class="provider-drawer-backdrop" data-provider-drawer-close></div><aside class="provider-drawer" role="dialog" aria-modal="true" aria-labelledby="provider-drawer-title"><header><div><span class="eyebrow">PROVIDER PROFILE</span><h2 id="provider-drawer-title">${profile ? "编辑连接" : "自定义连接"}</h2></div><button class="icon-button" type="button" data-provider-drawer-close aria-label="关闭配置抽屉" title="关闭">×</button></header><div class="provider-drawer-tabs" role="tablist"><button type="button" role="tab" aria-selected="${state.providerDrawerMode === "manual"}" data-provider-drawer-mode="manual">手动配置</button><button type="button" role="tab" aria-selected="${state.providerDrawerMode === "import"}" data-provider-drawer-mode="import">导入配置</button></div><div class="provider-drawer-body">${state.providerDrawerMode === "import" ? importer : manual}</div></aside>`;
  }

  function renderWebChatDrawer() {
    if (!state.webChatDrawerOpen) return "";
    const profile = state.webChatProfiles.find((item) => item.id === state.webChatDrawerProfileId) || null;
    const adapterId = profile?.adapter_id || state.webChatDrawerAdapterId || "custom";
    const adapter = webChatAdapter(adapterId);
    const config = webChatConfig(profile);
    const isCustom = adapterId === "custom";
    const defaults = profile ? config : (adapter || {});
    const adapterOptions = state.webChatAdapters.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === adapterId ? "selected" : ""}>${escapeHtml(item.name || item.id)}</option>`).join("");
    const boundId = profile?.browser_profile_id || "";
    const browserOptions = state.browserProfiles
      .filter((item) => !item.archived_at || item.id === boundId)
      .map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === boundId ? "selected" : ""}>${escapeHtml(item.name || item.id)}${item.archived_at ? " · 已归档" : ""}</option>`)
      .join("");
    const domains = Array.isArray(defaults.domains) ? defaults.domains.join("\n") : isCustom ? "" : (adapter?.domains || []).join("\n");
    const chatUrl = defaults.chat_url || (isCustom ? "" : adapter?.chat_url || "");
    const selectors = defaults.selectors && typeof defaults.selectors === "object" ? defaults.selectors : adapter?.selectors || {};
    const loginMarkers = defaults.login_markers || adapter?.login_markers || [];
    const authorizedMarkers = defaults.authorized_markers || adapter?.authorized_markers || [];
    const readyMarkers = defaults.ready_markers || adapter?.ready_markers || [];
    const modelId = defaults.model_id || adapter?.model_id || "web-session";
    const timeout = Number(defaults.response_timeout_seconds || 4);
    const actionBusy = Boolean(state.webChatBusy);
    const noBrowserProfile = !browserOptions;
    const statusNote = profile
      ? `当前状态：${webChatStatusLabel(profile)}；网页聊天额度固定显示为未知，不会作为 API 额度使用。`
      : "登录态只保存在 BrowserSkill 命名 Profile；Sumika 不读取 Cookie、Token、密码或 localStorage。";
    return `<div class="provider-drawer-backdrop" data-web-chat-drawer-close></div><aside class="provider-drawer web-chat-drawer" role="dialog" aria-modal="true" aria-labelledby="web-chat-drawer-title"><header><div><span class="eyebrow">WEB CHAT PROFILE</span><h2 id="web-chat-drawer-title">${profile ? "编辑网页聊天" : "添加网页聊天"}</h2></div><button class="icon-button" type="button" data-web-chat-drawer-close aria-label="关闭网页聊天配置抽屉" title="关闭">×</button></header><div class="provider-drawer-body"><form id="web-chat-profile-form" class="provider-drawer-form" data-profile-id="${escapeHtml(profile?.id || "")}">
      <div class="provider-security-note" role="note"><strong>安全边界</strong><span>${escapeHtml(statusNote)}</span></div>
      <div class="provider-form-grid"><label><span>连接名称</span><input name="name" value="${escapeHtml(profile?.name || (adapter?.name && !isCustom ? adapter.name : ""))}" maxlength="100" required autofocus /></label><label><span>网页适配器</span><select name="adapter_id" id="web-chat-adapter-select">${adapterOptions}</select></label></div>
      <label><span>BrowserSkill 命名 Profile</span><select name="browser_profile_id" required ${noBrowserProfile ? "disabled" : ""}><option value="">${noBrowserProfile ? "先创建命名 Profile" : "选择登录态 Profile"}</option>${browserOptions}</select></label>
      ${noBrowserProfile ? `<div class="web-chat-inline-action"><span>网页登录必须使用独立的命名 Profile。</span><button class="ghost-button" type="button" data-web-chat-create-browser-profile>新建命名 Profile</button></div>` : ""}
      <div class="provider-form-grid"><label><span>聊天页面 URL</span><input name="chat_url" type="url" value="${escapeHtml(chatUrl)}" placeholder="https://chat.example.com/" required /></label><label><span>网页模型标识（可选）</span><input name="model_id" value="${escapeHtml(modelId)}" maxlength="160" placeholder="web-session" /></label></div>
      <details class="provider-advanced web-chat-advanced" ${isCustom ? "open" : ""}><summary>高级：域名、选择器和就绪标记</summary><div>
        <label><span>允许域名（每行一个）</span><textarea name="domains" rows="2" placeholder="chat.example.com">${escapeHtml(domains)}</textarea></label>
        <div class="provider-form-grid"><label><span>输入框 CSS 选择器（每行一个）</span><textarea name="input_selectors" rows="3" required>${escapeHtml(webChatArrayText(selectors.input))}</textarea></label><label><span>发送按钮 CSS 选择器（每行一个）</span><textarea name="send_selectors" rows="3">${escapeHtml(webChatArrayText(selectors.send))}</textarea></label></div>
        <label><span>Assistant 回复 CSS 选择器（每行一个）</span><textarea name="response_selectors" rows="3">${escapeHtml(webChatArrayText(selectors.response))}</textarea></label>
        <div class="provider-form-grid"><label><span>登录提示标记（每行一个）</span><textarea name="login_markers" rows="3">${escapeHtml(webChatArrayText(loginMarkers))}</textarea></label><label><span>已登录标记（每行一个）</span><textarea name="authorized_markers" rows="3">${escapeHtml(webChatArrayText(authorizedMarkers))}</textarea></label></div>
        <label><span>聊天页就绪标记（每行一个）</span><textarea name="ready_markers" rows="2">${escapeHtml(webChatArrayText(readyMarkers))}</textarea></label>
       <div class="provider-form-grid"><label><span>等待回复超时（秒）</span><input name="response_timeout_seconds" type="number" min="0.5" max="15" step="0.5" value="${escapeHtml(timeout)}" /></label><label><span>预算策略</span><select name="budget_policy"><option value="free-only" ${(profile?.budget_policy || "free-only") === "free-only" ? "selected" : ""}>仅允许已确认免费/本地</option><option value="no-paid" ${(profile?.budget_policy || "") === "no-paid" ? "selected" : ""}>禁止付费动作</option></select></label></div>
      </div></details>
      <div class="web-chat-actions"><button class="ghost-button" type="button" data-web-chat-drawer-close>取消</button><span></span>${profile ? `<button class="ghost-button" type="button" data-web-chat-authorize-drawer="${escapeHtml(profile.id)}" ${actionBusy ? "disabled" : ""}>打开人工登录</button><button class="ghost-button" type="button" data-web-chat-check-drawer="${escapeHtml(profile.id)}" ${actionBusy ? "disabled" : ""}>检查页面</button>` : ""}<button class="ghost-button" type="submit" data-web-chat-action="save" ${actionBusy || noBrowserProfile ? "disabled" : ""}>保存草稿</button><button class="outline-button" type="submit" data-web-chat-action="test" ${actionBusy || noBrowserProfile ? "disabled" : ""}>测试连接</button><button class="primary-button" type="submit" data-web-chat-action="activate" ${actionBusy || noBrowserProfile ? "disabled" : ""}>保存并启用</button></div>
    </form></div></aside>`;
  }

  function renderProviderImportPreview() {
    const preview = state.providerImportPreview;
    if (!preview) return "";
    const profile = preview.profile || {};
    const mappings = (preview.field_mapping || []).map((item) => `<div><code>${escapeHtml(item.source)}</code><span>→</span><span>${escapeHtml(item.target)}</span><small>${escapeHtml(item.status)}</small></div>`).join("");
    const unsupported = (preview.unsupported_fields || []).map((item) => `<li><code>${escapeHtml(item.field)}</code>：${escapeHtml(item.value)}</li>`).join("");
    const warnings = (preview.warnings || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    return `<div class="provider-import-preview"><div class="provider-import-heading"><strong>${escapeHtml(profile.name || "导入预览")}</strong><span>${escapeHtml(preview.importer_id)}</span></div><dl><div><dt>端点</dt><dd>${escapeHtml((profile.base_urls || []).join(" · ") || "未提供")}</dd></div><div><dt>模型</dt><dd>${escapeHtml(profile.model || "未提供")}</dd></div><div><dt>密钥</dt><dd>${escapeHtml(Object.values(preview.masked_secrets || {}).join(" · ") || "未提供")}</dd></div></dl><div class="provider-import-mapping">${mappings}</div>${unsupported ? `<div class="provider-import-warning"><strong>未支持字段</strong><ul>${unsupported}</ul></div>` : ""}${warnings ? `<div class="provider-import-warning"><strong>注意</strong><ul>${warnings}</ul></div>` : ""}<button class="primary-button" type="button" id="provider-import-save" ${state.providerBusy ? "disabled" : ""}>保存为草稿</button></div>`;
  }

  function renderModuleConfig(module) {
    const properties = module.config_schema?.properties || {};
    const keys = Object.keys(properties);
    if (!keys.length) return `<div class="module-config-empty">当前实现无需额外配置</div>`;
    const fields = keys.map((key) => {
      const definition = properties[key] || {};
      const type = definition.type || "string";
      const current = module.config?.[key] ?? definition.default ?? (type === "boolean" ? false : "");
      const title = definition.title || key;
      if (type === "boolean") {
        return `<label class="module-field module-checkbox"><input type="checkbox" data-config-key="${escapeHtml(key)}" data-config-type="boolean" ${current ? "checked" : ""} /><span>${escapeHtml(title)}</span></label>`;
      }
      if (type === "array" || type === "object") {
        const text = JSON.stringify(current, null, 2);
        return `<label class="module-field"><span>${escapeHtml(title)}</span><textarea rows="3" data-config-key="${escapeHtml(key)}" data-config-type="${escapeHtml(type)}">${escapeHtml(text)}</textarea></label>`;
      }
      const inputType = definition.format === "password" ? "password" : type === "number" || type === "integer" ? "number" : "text";
      const value = definition.format === "password" ? "" : current;
      const placeholder = definition.format === "password" ? "仅在内存中使用，不写入 SQLite" : "";
      return `<label class="module-field"><span>${escapeHtml(title)}</span><input type="${inputType}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}" data-config-key="${escapeHtml(key)}" data-config-type="${escapeHtml(type)}" data-config-format="${escapeHtml(definition.format || "")}" /></label>`;
    }).join("");
    return `<form class="module-config-form" data-module-config-form="${escapeHtml(module.id)}"><div class="module-config-title">实现配置</div>${fields}<button class="small-button" type="submit" ${state.moduleBusy === module.id ? "disabled" : ""}>${state.moduleBusy === module.id ? "保存中" : "保存配置"}</button></form>`;
  }

  return { renderModules, renderCapabilityCatalogPanel, renderWebChatProfileRow };
}
