export function createWebWorkbenchView({
  escapeHtml,
  formatPricingNumber,
  renderPageFrame,
  safeWebWorkbenchText,
  state,
  webAttemptActive,
  webAttemptStatusLabel,
  webConsultationStatusLabel,
  webRouteStatusLabel,
  webWorkbenchProfiles,
}) {
  function renderWebWorkbenchManualResult(profileId, result) {
    const status = String(result?.status || (result?.ok ? "completed" : "unknown"));
    const text = result?.text || result?.result?.answer || "";
    const attemptId = result?.attempt_id || state.webWorkbenchManualAttempts?.[profileId] || "";
    const canCancel = Boolean(attemptId && webAttemptActive(result));
    const retryable = result?.retryable === true && result?.possibly_sent !== true;
    const controls = canCancel
      ? `<button class="ghost-button" type="button" data-web-workbench-manual-cancel="${escapeHtml(attemptId)}">停止等待</button>`
      : retryable
        ? `<button class="ghost-button" type="button" data-web-workbench-manual-retry="${escapeHtml(attemptId)}">重试</button>`
        : "";
    const body = status === "completed" && text
      ? `<small class="web-workbench-trust-label">UNTRUSTED_WEB_RESULT</small><p>${escapeHtml(safeWebWorkbenchText(text)).replaceAll("\n", "<br>")}</p>`
      : `<p class="${status === "failed" ? "plugin-error" : ""}">${escapeHtml(result?.reason || result?.error_code || webAttemptStatusLabel(status))}</p>`;
    return `<article class="web-workbench-manual-result" data-web-workbench-manual-result="${escapeHtml(profileId)}"><strong>${escapeHtml(state.webChatProfiles.find((item) => item.id === profileId)?.name || profileId)}</strong><span class="web-workbench-member-status ${escapeHtml(status)}">${escapeHtml(webAttemptStatusLabel(status))}</span>${body}<div>${controls}</div></article>`;
  }

  function renderRouteBudgetImpact(result) {
    const impact = result?.budget_impact && typeof result.budget_impact === "object" ? result.budget_impact : null;
    if (!impact) return "";
    const usage = impact.usage && typeof impact.usage === "object" ? impact.usage : {};
    const receipt = impact.charge_receipt && typeof impact.charge_receipt === "object" ? impact.charge_receipt : null;
    const usageText = usage.total_tokens != null
      ? `${formatPricingNumber(usage.total_tokens)} token`
      : "usage 未返回";
    const providerCharge = receipt?.provider_charge != null
      ? `${receipt.provider_currency || "单位未知"} ${formatPricingNumber(receipt.provider_charge)}`
      : "站内扣费未知";
    const cashCharge = receipt?.cash_charge != null
      ? `${receipt.cash_currency || "单位未知"} ${formatPricingNumber(receipt.cash_charge)}`
      : "现金折算未知";
    return `<div class="route-budget-impact" data-route-budget-impact><span>${escapeHtml(usageText)}</span><strong>${escapeHtml(providerCharge)}</strong><strong>${escapeHtml(cashCharge)}</strong>${receipt?.evidence_level ? `<small>${escapeHtml(receipt.evidence_level)}</small>` : ""}</div>`;
  }

  function renderWebWorkbenchPendingResult(item) {
    const result = item?.result || {};
    const status = String(item?.status || result.status || "unknown");
    const answer = result.answer || result.summary || "";
    const dispatchId = String(item?.dispatch_id || result.dispatch_id || "");
    const retryable = result.retryable === true && result.possibly_sent !== true;
    const retry = retryable && dispatchId
      ? `<button class="ghost-button" type="button" data-web-workbench-retry="${escapeHtml(dispatchId)}">重试</button>`
      : "";
    return `<article class="web-workbench-manual-result web-workbench-pending-result" data-web-workbench-pending="${escapeHtml(dispatchId)}"><div><strong>${escapeHtml(item?.route_id || "Worker 结果")}</strong><span class="web-workbench-member-status ${escapeHtml(status)}">${escapeHtml(webAttemptStatusLabel(status))}</span></div><small class="web-workbench-trust-label">${item?.worker_kind === "web" ? "UNTRUSTED_WEB_RESULT" : "待主 Agent 接收"}</small>${answer ? `<p>${escapeHtml(safeWebWorkbenchText(answer)).replaceAll("\n", "<br>")}</p>` : `<p class="plugin-error">${escapeHtml(result.error_code || "没有可显示的结果正文")}</p>`}${renderRouteBudgetImpact(result)}<div>${retry}${dispatchId ? `<button class="ghost-button" type="button" data-web-workbench-ack="${escapeHtml(dispatchId)}">标记已接收</button>` : ""}</div></article>`;
  }

  function renderWebWorkbenchProfile(route, profile) {
    const profileId = route.provider_profile_id || "";
    const occupied = route.occupancy && route.occupancy !== "idle";
    const active = Boolean(profile?.active_session);
    const lease = profile?.browser_profile_lease_owner === "other-core";
    const stateText = lease ? "其他 Sumika 实例占用" : webRouteStatusLabel(route);
    const canOpen = Boolean(profileId && !lease && !state.webWorkbenchBusy);
    const controls = profileId
      ? `<button class="small-button" type="button" data-web-workbench-open="${escapeHtml(profileId)}" ${canOpen ? "" : "disabled"}>${active ? "保持打开" : "打开隔离窗口"}</button><button class="ghost-button" type="button" data-web-workbench-focus="${escapeHtml(profileId)}" ${canOpen ? "" : "disabled"}>聚焦</button>${active ? `<button class="ghost-button" type="button" data-web-workbench-close="${escapeHtml(profileId)}" ${state.webWorkbenchBusy ? "disabled" : ""}>关闭</button>` : ""}${occupied && route.occupancy === "agent" ? `<button class="outline-button" type="button" data-web-workbench-takeover="${escapeHtml(profileId)}" ${state.webWorkbenchBusy ? "disabled" : ""}>接管并暂停 Agent</button>` : `<button class="ghost-button" type="button" data-web-workbench-release="${escapeHtml(profileId)}" ${state.webWorkbenchBusy || !occupied ? "disabled" : ""}>交给 Agent</button>`}`
      : `<button class="ghost-button" type="button" data-page="Modules">去模块页配置</button>`;
    return `<article class="web-workbench-profile" data-web-workbench-profile="${escapeHtml(profileId || route.route_id)}"><div class="web-workbench-profile-main"><div class="web-workbench-profile-heading"><span class="status-dot ${route.routable ? "online" : lease ? "warning" : "offline"}"></span><strong>${escapeHtml(route.label || profile?.name || route.adapter_id || "网页 Profile")}</strong><span class="web-workbench-badge">${escapeHtml(stateText)}</span></div><small>${escapeHtml(route.adapter_id || route.provider_key || "web-chat")} · ${escapeHtml((route.domains || []).join(" / ") || profile?.chat_url || "域名未登记")}</small><small>额度：<span class="web-workbench-quota">unknown（不会承诺免费）</span> · 占用：${escapeHtml(route.occupancy || "idle")}</small></div><div class="web-workbench-profile-actions">${controls}</div></article>`;
  }

  function renderWebWorkbenchConsultation(item) {
    const members = Array.isArray(item?.members) ? item.members : [];
    const memberRows = members.length ? members.map((member) => {
      const status = String(member.status || "unknown");
      const answer = member.answer ? safeWebWorkbenchText(member.answer) : "";
      const retry = status === "failed" && member.dispatch_id ? `<button class="ghost-button" type="button" data-web-workbench-retry="${escapeHtml(member.dispatch_id)}">重试</button>` : "";
      return `<article class="web-workbench-member" data-web-workbench-member="${escapeHtml(member.dispatch_id || member.route_id || "member")}"><div><strong>${escapeHtml(member.provider_profile_id || member.route_id || "网页成员")}</strong><span class="web-workbench-member-status ${escapeHtml(status)}">${escapeHtml(webConsultationStatusLabel(status))}</span><small>${member.latency_ms != null ? `${escapeHtml(String(Math.round(Number(member.latency_ms) || 0)))} ms` : "等待响应"}${member.error_code ? ` · ${escapeHtml(member.error_code)}` : ""}</small></div>${answer ? `<details><summary>UNTRUSTED_WEB_RESULT · 查看回答</summary><p>${escapeHtml(answer).replaceAll("\n", "<br>")}</p></details>` : ""}<div>${retry}</div></article>`;
    }).join("") : `<div class="empty-column">尚未分配网页成员</div>`;
    const running = ["queued", "running"].includes(String(item?.status || ""));
    const opinion = item?.opinion_mode === "single-opinion" || item?.single_opinion ? "single-opinion · 单模型意见" : "panel · 独立成员";
    return `<article class="web-workbench-consultation" data-web-workbench-consultation="${escapeHtml(item?.consultation_id || "")}"><div class="web-workbench-consultation-heading"><div><strong>${escapeHtml(webConsultationStatusLabel(item?.status))}</strong><small>${escapeHtml(item?.decision_kind || "small-answer")} · ${escapeHtml(opinion)} · ${Number(item?.successful_count || 0)}/${members.length || "?"} 成功</small></div><div>${running ? `<button class="ghost-button" type="button" data-web-workbench-consultation-cancel="${escapeHtml(item.consultation_id)}">停止当前咨询</button>` : item?.status === "partial" || item?.status === "failed" ? `<button class="ghost-button" type="button" data-web-workbench-consultation-continue="${escapeHtml(item.consultation_id)}">继续复核</button>` : ""}</div></div>${item?.disagreement_detected ? `<div class="web-workbench-disagreement">检测到意见分歧；结果仅供主 Agent/用户审阅。</div>` : ""}<div class="web-workbench-member-list">${memberRows}</div><small class="web-workbench-trust-label">UNTRUSTED_WEB_RESULT · 网页内容不会自动执行</small></article>`;
  }

  function renderWebWorkbench() {
    const catalog = state.webWorkbenchCatalog || {};
    const routes = Array.isArray(catalog.routes) ? catalog.routes : [];
    const profiles = webWorkbenchProfiles();
    const templates = routes.filter((route) => !route.provider_profile_id);
    const readyRoutes = routes.filter((route) => route.routable);
    const workerDraft = state.webWorkbenchWorkerDraft || {};
    const consultationDraft = state.webWorkbenchConsultationDraft || {};
    const manualOptions = profiles.filter(({ route }) => route.routable).map(({ route, profile }) => `<option value="${escapeHtml(profile?.id || route.provider_profile_id)}" ${state.webWorkbenchSelectedProfileId === (profile?.id || route.provider_profile_id) ? "selected" : ""}>${escapeHtml(route.label || profile?.name || route.adapter_id)}</option>`).join("");
    const workerOptions = readyRoutes.map((route) => `<option value="${escapeHtml(route.route_id)}" ${workerDraft.route_id === route.route_id ? "selected" : ""}>${escapeHtml(route.label)} · ${escapeHtml(route.adapter_id || route.provider_key)}</option>`).join("");
    const consultationRows = (state.webWorkbenchConsultations || []).map(renderWebWorkbenchConsultation).join("") || `<div class="empty-column">还没有咨询记录；主 Agent 或你可以在需要时动态发起。</div>`;
    const pendingRows = (state.webWorkbenchPendingResults || []).map(renderWebWorkbenchPendingResult).join("") || `<div class="empty-column">没有等待主 Agent 接收的 Worker 结果。</div>`;
    const notice = state.webWorkbenchNotice ? `<div class="agent-notice" role="status">${escapeHtml(state.webWorkbenchNotice)}</div>` : "";
    return renderPageFrame("网页工作台", "隔离网页 Profile、单次子任务与并行咨询；网页回答始终是不可信外部结果。", `${notice}<section class="web-workbench-safety"><strong>隔离与额度边界</strong><p>运行在受管 Agent Window，不复用你的 Edge 标签页；额度显示 <code>unknown</code>，不会静默切换到付费 API。</p></section><section class="web-workbench-panel" data-web-workbench-catalog><div class="panel-heading"><div><strong>网页 Profiles</strong><small>${escapeHtml(String(catalog.routable_count ?? 0))} 个可咨询 · ${escapeHtml(String(routes.length))} 个目录项 · 最近刷新只读取元数据</small></div><button class="small-button" id="web-workbench-refresh" type="button" ${state.webWorkbenchCatalogBusy ? "disabled" : ""}>${state.webWorkbenchCatalogBusy ? "刷新中" : "刷新目录"}</button></div><div class="web-workbench-profile-list">${profiles.map(({ route, profile }) => renderWebWorkbenchProfile(route, profile)).join("") || `<div class="empty-column">尚未配置网页 Profile。可在模块页创建并完成隔离登录。</div>`}</div>${templates.length ? `<details class="web-workbench-templates"><summary>可配置网页模板（不会直接路由）</summary><div>${templates.map((route) => renderWebWorkbenchProfile(route, null)).join("")}</div></details>` : ""}</section><section class="web-workbench-two-column"><section class="web-workbench-panel"><div class="panel-heading"><div><strong>手动网页查询</strong><small>不经过主 Agent；仍使用同一命名 Profile 的独占写租约。</small></div></div><form id="web-workbench-manual-form" class="web-workbench-form"><label><span>网页 Profile</span><select name="profile_id" ${manualOptions ? "" : "disabled"} required><option value="">选择已授权 Profile</option>${manualOptions}</select></label><label class="web-workbench-wide"><span>问题</span><textarea name="question" rows="3" maxlength="16000" placeholder="输入一个独立的小问题" required>${escapeHtml(state.webWorkbenchManualDrafts[state.webWorkbenchSelectedProfileId] || "")}</textarea></label><button class="outline-button" type="submit" ${manualOptions && !state.webWorkbenchBusy ? "" : "disabled"}>发送网页问题</button></form><div class="web-workbench-manual-results">${Object.entries(state.webWorkbenchManualResults || {}).map(([profileId, result]) => renderWebWorkbenchManualResult(profileId, result)).join("") || `<div class="empty-column">尚无手动回答</div>`}</div></section><section class="web-workbench-panel"><div class="panel-heading"><div><strong>Web Worker</strong><small>一次明确网页子任务；由你选择路由，结果不会直接修改文件。</small></div></div><form id="web-workbench-worker-form" class="web-workbench-form"><label><span>路由</span><select name="route_id" ${workerOptions ? "" : "disabled"} required><option value="">选择可咨询 Profile</option>${workerOptions}</select></label><label class="web-workbench-wide"><span>子任务</span><textarea name="question" rows="3" maxlength="16000" placeholder="例如：只检查这个 API 设计的一个风险点" required>${escapeHtml(workerDraft.question || "")}</textarea></label><button class="outline-button" type="submit" ${workerOptions && !state.webWorkbenchBusy ? "" : "disabled"}>交给 Web Worker</button></form><div class="web-workbench-worker-result">${state.webWorkbenchWorkerResult ? `<article class="web-workbench-manual-result"><strong>${escapeHtml(state.webWorkbenchWorkerResult.status || "结果")}</strong><small class="web-workbench-trust-label">UNTRUSTED_WEB_RESULT</small><p>${escapeHtml(safeWebWorkbenchText(state.webWorkbenchWorkerResult.result?.answer || state.webWorkbenchWorkerResult.reason || "暂无回答")).replaceAll("\n", "<br>")}</p></article>` : `<div class="empty-column">尚无 Web Worker 回合</div>`}</div></section></section><section class="web-workbench-panel web-workbench-pending-panel"><div class="panel-heading"><div><strong>待接收 Worker 结果</strong><small>主 Agent 通过下一次 route.status/pending 调用读取；不会自动修改文件。</small></div></div><div class="web-workbench-pending-results">${pendingRows}</div></section><section class="web-workbench-panel web-workbench-consultation-panel"><div class="panel-heading"><div><strong>多模型咨询面板</strong><small>每次在当前 turn 动态创建 1–5 个不同网页 Provider；最多 3 个并发，5 个成员按 3 + 2 两批执行。</small></div><div class="web-workbench-panel-actions"><button class="ghost-button" type="button" data-web-workbench-pause-all ${state.webWorkbenchBusy ? "disabled" : ""}>暂停 Agent 咨询</button><button class="ghost-button" type="button" data-web-workbench-continue-latest ${state.webWorkbenchBusy ? "disabled" : ""}>继续最近咨询</button></div></div><form id="web-workbench-consultation-form" class="web-workbench-form"><label><span>决策类型</span><select name="decision_kind"><option value="brainstorm" ${consultationDraft.decision_kind === "brainstorm" ? "selected" : ""}>brainstorm · 头脑风暴</option><option value="plan-review" ${consultationDraft.decision_kind === "plan-review" ? "selected" : ""}>plan-review · 计划复核</option><option value="fact-check" ${consultationDraft.decision_kind === "fact-check" ? "selected" : ""}>fact-check · 事实核查</option><option value="counterexample" ${consultationDraft.decision_kind === "counterexample" ? "selected" : ""}>counterexample · 反例</option><option value="small-answer" ${consultationDraft.decision_kind === "small-answer" ? "selected" : ""}>small-answer · 小问题</option></select></label><label><span>成员数</span><select name="max_members"><option value="1" ${Number(consultationDraft.max_members) === 1 ? "selected" : ""}>1 · single-opinion</option><option value="2" ${Number(consultationDraft.max_members) === 2 ? "selected" : ""}>2</option><option value="3" ${Number(consultationDraft.max_members) === 3 || !Number(consultationDraft.max_members) ? "selected" : ""}>3</option><option value="4" ${Number(consultationDraft.max_members) === 4 ? "selected" : ""}>4 · 3 + 1</option><option value="5" ${Number(consultationDraft.max_members) === 5 ? "selected" : ""}>5 · 3 + 2</option></select></label><label class="web-workbench-wide"><span>问题</span><textarea name="question" rows="3" maxlength="16000" placeholder="让多个网页模型独立评审同一个问题" required>${escapeHtml(consultationDraft.question || "")}</textarea></label><label class="web-workbench-wide"><span>必要上下文（可选，禁止粘贴凭据文件）</span><textarea name="context" rows="2" maxlength="24000" placeholder="目标、短 diff 或脱敏工具结果">${escapeHtml(consultationDraft.context || "")}</textarea></label><button class="outline-button" type="submit" ${readyRoutes.length && !state.webWorkbenchBusy ? "" : "disabled"}>启动咨询面板</button></form><div class="web-workbench-consultations">${consultationRows}</div></section>`);
  }

  return { renderWebWorkbench };
}
