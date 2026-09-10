import { renderBenefitsSection } from "./benefits-view.js";

export function normalizeQualityRule(rule, fallback = { multiplier: "1", extra_cny: "0" }) {
  const multiplier = Number(rule?.multiplier);
  const extra = Number(rule?.extra_cny);
  return {
    multiplier: Number.isFinite(multiplier) && multiplier >= 1 ? String(multiplier) : fallback.multiplier,
    extra_cny: Number.isFinite(extra) && extra >= 0 ? String(extra) : fallback.extra_cny,
  };
}

export function eligibleQualityCandidates(candidates = []) {
  return candidates.filter((candidate) => candidate?.authorized === true && candidate?.available === true);
}

export function formatQualityQuote(quote) {
  if (!quote) return "报价未知";
  const amount = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) ? `¥${Number(value).toFixed(2)}` : "未知";
  return `${amount(quote.low_cny)} - ${amount(quote.typical_cny)} - ${amount(quote.high_cny)}`;
}

export function formatFundingQuote(quote) {
  if (!quote) return "资金来源未核实";
  const money = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) && Number(value) >= 0 ? `¥${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 8 })}` : "未知";
  const labels = { grant: "赠送额度", purchased: "已购资源包", cash: "现金余额", free: "零价服务", local: "本地执行", mixed: "混合抵扣", unknown: "资金来源未核实" };
  const label = labels[quote.funding_kind] || labels.unknown;
  if (quote.available === false) return `${label} · 当前额度不可用`;
  if (quote.funding_kind === "purchased" || quote.funding_kind === "mixed") return `${label} · 资源消耗折算 ${money(quote.resource_value_cny)} · 现金扣减 ${money(quote.cash_due_cny)}`;
  if (quote.funding_kind === "cash") return `${label} ${money(quote.cash_balance_cny)} · 预计扣减 ${money(quote.cash_due_cny)}`;
  return quote.free === true ? `${label} · 预计费用 ¥0` : `${label} · 费用待核对`;
}

export function createQualityRoutingView({ escapeHtml, renderConsultation, renderPageFrame, state, includeBenefits = true }) {
  const quality = () => state.qualityRouting;
  const catalog = () => quality().catalog || { candidates: [], capabilities: {} };
  const candidates = () => Array.isArray(catalog().candidates) ? catalog().candidates : [];
  const candidateLabel = (candidate) => [candidate.label || candidate.candidate_id, candidate.channel, candidate.model_id, candidate.reasoning_effort, formatFundingQuote(candidate.cost_quote)].filter(Boolean).join(" · ");
  const candidateOptions = (selectedId, emptyLabel) => [`<option value="">${emptyLabel}</option>`, ...eligibleQualityCandidates(candidates()).map((candidate) => `<option value="${escapeHtml(candidate.candidate_id)}" ${candidate.candidate_id === selectedId ? "selected" : ""}>${escapeHtml(candidateLabel(candidate))}</option>`)].join("");

  function renderRoutingEvidence() {
    const refresh = quality().refresh;
    const labels = { ready: "新鲜", stale: "已过期", "needs-review": "需核对", never: "未读取", observed: "观察中", "pending-evaluation": "待评测", retired: "已下线", degraded: "已降级" };
    const status = (value) => labels[value] || value || "未知";
    const date = (value) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : "未知";
    const count = (value) => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString() : "未知";
    const jobs = Object.entries(refresh?.jobs || {}).map(([key, job]) => `<div><strong>${escapeHtml(({ resources: "资源包 · 每日", pricing: "价格 · 每12小时", catalog: "目录 · 每12小时" })[key] || key)}</strong><span>${escapeHtml(status(job.state))}</span><small>上次成功：${escapeHtml(date(job.last_success_at))}${job.error ? ` · ${escapeHtml(job.error)}` : ""}</small></div>`).join("");
    const resources = (refresh?.resources || []).map((pack) => `<div><strong>${escapeHtml(pack.name || pack.pack_id)}</strong><span>${pack.available ? "已绑定资源包" : "仅观察 · 不可抵扣"}</span><small>${escapeHtml(pack.provider_profile_id)} · ${escapeHtml((pack.applies_to || []).join("、"))}</small><small>观测余额 ${escapeHtml(count(pack.remaining))} ${escapeHtml(pack.unit)} · 可预留 ${escapeHtml(count(pack.reservable_remaining))} · ${pack.stale ? "已过期" : "观测有效"}</small><small>观察：${escapeHtml(date(pack.observed_at))} · 到期：${escapeHtml(date(pack.expires_at))}</small></div>`).join("");
    const observations = (refresh?.observations || []).map((entry) => `<div><strong>${escapeHtml(entry.model_id)}</strong><span>${escapeHtml(status(entry.availability_state))}</span><small>${entry.free_claim === true ? "官网标注免费（价格证据，不代表账户额度或健康）" : "免费状态未确认"} · ${entry.fresh ? "观测有效" : "待刷新"}</small><small>${escapeHtml(entry.source_url || "未知来源")} · ${escapeHtml(date(entry.observed_at))}</small></div>`).join("");
    const bindings = quality().selection?.bindings;
    const freeReasons = { "qualified-bounded-text": "可用 · 已验证短文本", "fixed-evaluation-required": "待任务评测", "execution-binding-changed": "待任务评测或配置已变更", "profile-unavailable": "尚未启用", "refresh-required": "需刷新免费证据", "price-stale": "价格证据已过期", "free-evidence-withdrawn": "免费声明已撤回", "free-evidence-missing": "暂无免费证据", "account-allowance-binding-required": "待绑定账户额度", "account-entitlement-required": "需核查账户权益", "rate-limited": "限流冷却中", "submission-uncertain": "请求状态不明 · 暂停重发", "account-binding-changed": "账户已变更 · 需重新绑定", "authenticated-health-expired": "需更新账户健康检查" };
    const freeProfiles = (refresh?.free_models?.profiles || []).map((profile) => `<div><strong>${escapeHtml(profile.provider_id)}</strong><span>${escapeHtml(status(profile.state))}</span><small>免费证据：${escapeHtml(date(profile.source?.observed_at))} · 下次检查：${escapeHtml(date(new Date(profile.next_refresh * 1000).toISOString()))}</small>${(profile.models || []).map((model) => `<small>${escapeHtml(model.model_id)} · ${escapeHtml(freeReasons[model.reason] || model.reason)}${model.retry_at ? ` · ${escapeHtml(date(new Date(model.retry_at * 1000).toISOString()))} 后可重新选择` : ""}</small>`).join("")}<small>具体剩余额度未量化；遇到账户拒绝会停止，不切换付费。</small></div>`).join("");
    const resolution = bindings ? ["leader", "role"].map((purpose) => `<p>${purpose === "leader" ? "负责人" : "角色"}：${escapeHtml(bindings[purpose]?.candidate_id || "未选出")} · ${escapeHtml(bindings[purpose]?.reason || "未知")}</p>`).join("") : "";
    const decimal = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) && Number(value) >= 0 ? Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 8 }) : "未知";
    const accounts = (refresh?.accounts?.funding?.projections || []).map((account) => `<div><strong>${escapeHtml(account.provider)}</strong><span>${escapeHtml(({ grant: "赠送额度", purchased: "已购资源包", cash: "现金余额", unknown: "来源待核对" })[account.source] || "来源待核对")} · ${account.fresh && account.entitlement_active ? "观测有效" : "待刷新或已到期"}</span><small>余额 ${escapeHtml(decimal(account.balance))} ${escapeHtml(account.unit)} · 可预留 ${escapeHtml(decimal(account.available))}</small><small>在途及待对账 ${escapeHtml(decimal(account.inflight_and_unsettled))} · 未取得逐请求账单时保留费用估算</small><small>观察：${escapeHtml(date(account.observed_at))} · 数据有效至：${escapeHtml(date(account.expires_at))}</small></div>`).join("");
    const portalReason = (reason) => ({ "account-binding-unverified": "尚未验证网页与 API 为同一账户", "model-cost-category-unverified": "尚未核实每个型号的额度消耗", "absolute-free-usage-quota-not-displayed": "官网未提供可计算的剩余额度", "login-required": "请先登录账户", "browser-not-connected": "账户浏览器尚未连接" })[reason] || "账户、计价与扣费证据未齐全，暂不自动路由";
    const portals = (refresh?.accounts?.portals || []).map((portal) => `<div><strong>${escapeHtml(portal.provider_profile_id)}</strong><span>账户权益 · ${portal.fresh ? "观测有效" : "待刷新"} · 仅观察</span><small>可见余额 ${escapeHtml(decimal(portal.available_balance))} ${escapeHtml(portal.unit || "")}</small>${portal.used_percent != null ? `<small>已用 ${escapeHtml(decimal(portal.used_percent))}% · 精确剩余额度未知</small>` : ""}<small>${escapeHtml(portalReason(portal.reason))}</small><small>观察：${escapeHtml(date(portal.observed_at))}</small></div>`).join("");
    return `<details class="quality-refresh"><summary>模型资源与刷新状态</summary><p>刷新不调用 AI；健康检查与评测另行授权。应用关闭时不刷新上游。</p>${resolution}<button type="button" class="ghost-button" data-model-refresh ${quality().refreshBusy ? "disabled" : ""}>${quality().refreshBusy ? "正在刷新…" : "检查价格与额度"}</button><p role="status">${escapeHtml(quality().refreshNotice || "")}</p><div class="quality-refresh-grid">${jobs || "尚未读取刷新状态。"}${accounts}${portals}${freeProfiles}${resources}${observations}</div></details>${includeBenefits ? renderBenefitsSection(state.benefits) : ""}`;
  }

  function renderQualitySettings() {
    const settings = quality().settings;
    const rule = normalizeQualityRule(settings?.budget_rule, { multiplier: "2", extra_cny: "5" });
    const loading = quality().settingsBusy && !settings;
    const busy = quality().settingsBusy;
    const notice = quality().settingsNotice ? `<div class="quality-notice" role="status">${escapeHtml(quality().settingsNotice)}</div>` : "";
    return `<section class="settings-section quality-settings" aria-labelledby="quality-settings-title">
      <div class="quality-section-heading"><div><span class="eyebrow">QUALITY ROUTING</span><strong id="quality-settings-title">质量协作</strong><small>规则只影响之后创建的任务。</small></div><button class="ghost-button" type="button" data-quality-settings-refresh ${busy ? "disabled" : ""}>刷新</button></div>
      ${loading ? '<div class="empty-panel" aria-busy="true">正在读取质量协作设置…</div>' : `<form id="quality-settings-form" class="quality-settings-form">
        <label>角色候选<select name="role_candidate_id" aria-label="角色候选">${candidateOptions(settings?.role_candidate_id || "", "未配置")}</select></label>
        <label>负责人候选<select name="leader_candidate_id" aria-label="负责人候选">${candidateOptions(settings?.leader_candidate_id || "", "未配置")}</select></label>
        <fieldset class="quality-selection-modes"><legend>候选选择方式</legend>${[["leader", "负责人"], ["role", "角色"]].map(([purpose, label]) => `<label>${label}<select name="${purpose}_selection_mode"><option value="fixed" ${settings?.selection_mode?.[purpose] !== "auto" ? "selected" : ""}>固定指定（保持原设置）</option><option value="auto" ${settings?.selection_mode?.[purpose] === "auto" ? "selected" : ""}>在授权池中自动选择</option></select></label>`).join("")}<p>自动模式需要健康证据及至少三次固定评测；榜单不代替验收。选入池子不授予发送或付费权限。</p><div class="quality-candidate-list">${candidates().map((candidate) => `<label class="quality-candidate"><input type="checkbox" name="selection_candidate" value="${escapeHtml(candidate.candidate_id)}" ${(settings?.candidate_pool || []).includes(candidate.candidate_id) ? "checked" : ""}/><span>${escapeHtml(candidateLabel(candidate))}</span></label>`).join("") || "尚无候选。"}</div></fieldset>
        <fieldset class="quality-budget-fields"><legend>未来任务预算规则</legend><label>倍率<input name="multiplier" type="number" min="1" step="0.1" inputmode="decimal" value="${escapeHtml(rule.multiplier)}" required /></label><label>额外预算（CNY）<input name="extra_cny" type="number" min="0" step="0.01" inputmode="decimal" value="${escapeHtml(rule.extra_cny)}" required /></label><button class="ghost-button" type="button" data-quality-budget-defaults>恢复默认</button></fieldset>
        <div class="quality-form-actions"><button class="outline-button" type="submit" ${busy ? "disabled" : ""}>保存质量协作设置</button><span>未选择外部候选，也不会发送聊天历史。</span></div>
      </form>`}${notice}${renderRoutingEvidence()}</section>`;
  }

  function renderTaskBudget(task) {
    const budget = task?.budget;
    if (!budget) return "尚未返回预算";
    const knownAmount = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
    const spent = knownAmount(budget.spent_cny) ? `已用 ¥${Number(budget.spent_cny).toFixed(2)}` : "已用未知";
    const estimated = knownAmount(budget.estimated_cny) ? `预估 ¥${Number(budget.estimated_cny).toFixed(2)}` : "预估未知";
    const unpriced = Number(budget.unpriced_calls || 0);
    const limits = budget.quote ? `最多 ${Number.isFinite(Number(budget.quote.max_calls)) ? budget.quote.max_calls : "未知"} 次调用 · ${Number.isFinite(Number(budget.quote.max_tokens)) ? budget.quote.max_tokens : "未知"} Token` : "调用与 Token 上限未知";
    return `${formatQualityQuote(budget.quote)} · ${limits} · ${spent} · ${estimated}${unpriced ? ` · ${unpriced} 次未报价` : ""}`;
  }

  function renderTask(task) {
    const selected = quality().selectedTaskId === task.task_id;
    const budgetEditable = ["running", "pending", "planning", "finalizing", "paused", "needs-attention", "ready", "awaiting-confirmation"].includes(String(task.status));
    const awaitingConfirmation = ["planned", "waiting_approval", "awaiting_confirmation", "awaiting-confirmation"].includes(String(task.status));
    const nodes = Array.isArray(task.plan?.nodes) ? task.plan.nodes : [];
    const results = task.results && typeof task.results === "object" ? Object.entries(task.results) : [];
    const finalMessage = typeof task.final_message === "object" && task.final_message !== null ? task.final_message.content : task.final_message;
    const delivery = finalMessage || task.workflow_error;
    return `<article class="quality-task ${selected ? "selected" : ""}" data-quality-task="${escapeHtml(task.task_id)}">
      <button class="quality-task-open" type="button" data-quality-task-select="${escapeHtml(task.task_id)}" aria-expanded="${selected}"><span><strong>${escapeHtml(task.plan?.goal || task.goal || "质量协作任务")}</strong><small>${escapeHtml(task.task_id)} · ${escapeHtml(task.status || "未知")}</small></span><span>${selected ? "收起" : "查看"}</span></button>
      <p class="quality-task-budget">${escapeHtml(renderTaskBudget(task))}</p>
      ${selected ? `<div class="quality-task-detail"><p>${escapeHtml(task.reason || "计划仅会在明确确认后执行。")}</p>${delivery ? `<div class="quality-result"><strong>${task.workflow_error ? "工作流错误" : "最终消息"}</strong><p>${escapeHtml(delivery)}</p></div>` : ""}<div class="quality-task-actions">${awaitingConfirmation ? `<button class="small-button" type="button" data-quality-task-confirm="${escapeHtml(task.task_id)}" ${quality().busy ? "disabled" : ""}>确认执行</button>` : ""}${!["completed", "failed", "cancelled"].includes(String(task.status)) ? `<button class="ghost-button" type="button" data-quality-task-cancel="${escapeHtml(task.task_id)}" ${quality().busy ? "disabled" : ""}>取消</button>` : ""}<button class="ghost-button" type="button" data-quality-task-refresh="${escapeHtml(task.task_id)}" ${quality().busy ? "disabled" : ""}>刷新状态</button></div>${budgetEditable ? `<form class="quality-task-budget-form" data-quality-task-budget-form="${escapeHtml(task.task_id)}"><label>倍率<input name="multiplier" type="number" min="1" step="0.1" inputmode="decimal" value="${escapeHtml(normalizeQualityRule(task.budget?.rule, { multiplier: "2", extra_cny: "5" }).multiplier)}" required /></label><label>额外预算（CNY）<input name="extra_cny" type="number" min="0" step="0.01" inputmode="decimal" value="${escapeHtml(normalizeQualityRule(task.budget?.rule, { multiplier: "2", extra_cny: "5" }).extra_cny)}" required /></label><button class="ghost-button" type="submit" ${quality().busy ? "disabled" : ""}>更新运行预算</button></form>` : ""}<div class="quality-node-list">${nodes.length ? nodes.map((node) => `<div><strong>${escapeHtml(node.goal || node.node_id)}</strong><small>${escapeHtml(task.states?.[node.node_id] || "未开始")}</small></div>`).join("") : "<div>尚未返回计划节点。</div>"}</div>${results.length ? `<div class="quality-result-list">${results.map(([nodeId, result]) => `<div class="quality-result"><strong>${escapeHtml(nodeId)}</strong><p>${escapeHtml(result?.text || "未提供文本结果")}</p></div>`).join("")}</div>` : ""}</div>` : ""}
    </article>`;
  }

  function renderQualityWorkbench() {
    const value = quality();
    const available = eligibleQualityCandidates(candidates());
    const selectedIds = new Set(value.allowedCandidateIds || []);
    const rule = normalizeQualityRule(value.budgetDraft, { multiplier: "2", extra_cny: "5" });
    const scope = value.activeScope;
    const automatic = Object.values(value.settings?.selection_mode || {}).includes("auto");
    const hasConfiguredLead = Boolean(value.settings?.role_candidate_id || value.settings?.leader_candidate_id || automatic);
    const canPlan = Boolean(scope?.assistantId && scope?.sessionId && selectedIds.size && hasConfiguredLead);
    const notice = value.notice ? `<div class="quality-notice" role="status">${escapeHtml(value.notice)}</div>` : "";
    const candidateRows = available.length ? available.map((candidate) => `<label class="quality-candidate"><input type="checkbox" name="candidate_id" value="${escapeHtml(candidate.candidate_id)}" ${selectedIds.has(candidate.candidate_id) ? "checked" : ""} ${value.busy ? "disabled" : ""}/><span><strong>${escapeHtml(candidate.label || candidate.candidate_id)}</strong><small>${escapeHtml([candidate.channel, candidate.model_id, candidate.reasoning_effort, candidate.pricing_source].filter(Boolean).join(" · "))}</small></span>${candidate.external ? "<em>外部</em>" : ""}</label>`).join("") : '<div class="empty-panel">没有已授权且可用的候选。请先在连接与权限中完成授权。</div>';
    const tasks = Array.isArray(value.tasks) ? value.tasks : [];
    return `<section class="quality-workbench" aria-labelledby="quality-workbench-title"><div class="quality-section-heading"><div><span class="eyebrow">AUTHORIZED COLLABORATION</span><strong id="quality-workbench-title">质量协作</strong><small>作用域：${escapeHtml(scope ? `${scope.assistantId} / ${scope.sessionId}` : "当前角色与会话")}</small></div><button class="ghost-button" type="button" data-quality-workbench-refresh ${value.busy ? "disabled" : ""}>刷新</button></div>
      <form id="quality-plan-form" class="quality-plan-form"><label class="quality-goal-field">目标<textarea name="goal" rows="3" required placeholder="描述要规划的协作目标">${escapeHtml(value.goalDraft || "")}</textarea></label><fieldset><legend>已授权候选</legend><div class="quality-candidate-list">${candidateRows}</div></fieldset><label class="quality-external"><input name="external_allowed" type="checkbox" ${value.externalAllowed ? "checked" : ""} ${value.busy ? "disabled" : ""}/><span>允许本次计划使用外部候选</span></label><p class="quality-disclosure">未勾选不允许外部发送；不提交聊天历史。</p><label class="quality-override"><input name="budget_override" type="checkbox" ${value.budgetOverride ? "checked" : ""} ${value.busy ? "disabled" : ""}/><span>为本次任务覆盖预算</span></label><div class="quality-budget-fields ${value.budgetOverride ? "" : "disabled"}"><label>倍率<input name="multiplier" type="number" min="1" step="0.1" inputmode="decimal" value="${escapeHtml(rule.multiplier)}" ${value.budgetOverride ? "required" : "disabled"}/></label><label>额外预算（CNY）<input name="extra_cny" type="number" min="0" step="0.01" inputmode="decimal" value="${escapeHtml(rule.extra_cny)}" ${value.budgetOverride ? "required" : "disabled"}/></label><button class="ghost-button" type="button" data-quality-task-budget-defaults ${value.budgetOverride ? "" : "disabled"}>恢复默认</button></div>${automatic ? `<label class="quality-external"><input name="planning_confirmed" type="checkbox" ${value.planningConfirmed ? "checked" : ""}/><span>允许本次负责人规划调用（可能付费或费用未知，最多一次、4000输出 Token）</span></label>` : ""}<div class="quality-form-actions"><button class="outline-button" type="submit" ${!canPlan || value.busy ? "disabled" : ""}>生成并报价计划</button><span>${hasConfiguredLead ? "生成计划会调用负责人；子任务须再次确认。" : "请先在设置配置角色或负责人。"}</span></div></form>${renderConsultation()}${notice}<section class="quality-task-list" aria-label="质量协作任务"><div class="quality-list-heading"><strong>当前会话任务</strong><small>${tasks.length} 项</small></div>${tasks.length ? tasks.map(renderTask).join("") : '<div class="empty-panel">尚无已授权计划。</div>'}</section></section>`;
  }

  return { renderQualitySettings, renderQualityWorkbench, renderRoutingEvidence };
}
