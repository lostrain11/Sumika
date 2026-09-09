const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
const records = (value) => Array.isArray(value) ? value.filter((entry) => entry && typeof entry === "object") : [];
const displayText = (value, fallback = "未知") => value === null || value === undefined || value === "" ? fallback : typeof value === "object" ? JSON.stringify(value) : String(value);
const dateLabel = (value) => typeof value === "string" && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "未知";
const statusLabel = (value) => ({ active: "有效", withdrawn: "已撤回", ready: "新鲜", ok: "新鲜", success: "新鲜", stale: "证据陈旧", never: "未读取", running: "进行中", verified: "已核实", "login-required": "待登录", challenge: "待验证", "needs-review": "待核对", unavailable: "不可用", interrupted: "已中断", error: "读取失败", disabled: "未启用" })[value] || displayText(value);
const configuration = (snapshot) => ({ enabled: snapshot?.enabled === true, checkin_enabled: snapshot?.checkin_enabled === true, browser_instance_id: typeof snapshot?.browser_instance_id === "string" ? snapshot.browser_instance_id : "" });
const sameConfiguration = (left, right) => left.enabled === right.enabled && left.checkin_enabled === right.checkin_enabled && left.browser_instance_id === right.browser_instance_id;
const configurationIssue = (draft) => draft.checkin_enabled && !draft.browser_instance_id ? "未选择签到浏览器" : draft.checkin_enabled && !draft.enabled ? "后台发现未开启" : "";
const sourceStatus = (source) => source?.stale === true && ["ready", "ok", "success"].includes(source.status) ? "证据陈旧" : `${statusLabel(source?.status)}${source?.stale === true ? " · 证据陈旧" : ""}`;

export function benefitsSourceKind(kind) {
  return ({ search: "搜索 RSS", "search-rss": "搜索 RSS", rss: "社区 RSS", "community-rss": "社区 RSS", "public-catalog": "官方目录", "official-catalog": "官方目录", "public-pricing": "官方价格", "public-benefits": "官方额度说明" })[kind] || displayText(kind, "来源类型未知");
}

export function benefitsOfferStatus(offer) {
  return offer?.state === "active" ? ({ lead: "待核实", "free-model": "官网声明", "credit-program": "公开活动" })[offer.kind] || "待核实" : statusLabel(offer?.state);
}

export function safeBenefitsUrl(value) {
  if (typeof value !== "string" || /[\s\\\u0000-\u001f\u007f]/.test(value)) return "";
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.port && url.port !== "443" || url.username || url.password || !/^https:\/\/[^/?#@]+(?:[/?#]|$)/i.test(value)) return "";
    const hostname = url.hostname.toLowerCase().replace(/\.$/, "");
    const labels = hostname.split(".");
    if (labels.length < 2 || labels.some((label) => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)) || !/^[a-z]{2,63}$/.test(labels.at(-1))) return "";
    if (/(^|\.)(localhost|local|localdomain|internal|intranet|lan|home|corp|test|invalid|example|onion|arpa)$/.test(hostname)) return "";
    if (/(^|\.)(nip\.io|sslip\.io|localtest\.me|lvh\.me|vcap\.me|traefik\.me)$/.test(hostname)) return "";
    return url.href;
  } catch {
    return "";
  }
}

function renderLink(title, url) {
  const href = safeBenefitsUrl(url);
  const label = escapeHtml(displayText(title));
  return href ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">${label}</a>` : `<span>${label}</span>`;
}

export function filterBenefitsOffers(offers, tab = "resources") {
  return records(offers).filter((offer) => tab === "leads" ? offer.kind === "lead" : ["free-model", "credit-program"].includes(offer.kind));
}

export function createBenefitsState() {
  return { snapshot: null, loaded: false, draft: null, browsers: [], browsersDetected: false, tab: "resources", open: false, busy: "", notice: "" };
}

export function renderBenefitsOffers(snapshot, tab = "resources", now = Date.now()) {
  const offers = filterBenefitsOffers(snapshot?.offers, tab);
  const sources = new Map(records(snapshot?.sources).map((source) => [source.id, source]));
  if (!offers.length) return `<p class="benefits-empty">${tab === "leads" ? "暂无线索" : "暂无资源"}</p>`;
  return `<ul class="benefits-offers">${offers.map((offer) => {
    const source = sources.get(offer.source_id);
    const kind = ({ lead: "资讯线索", "free-model": "免费模型", "credit-program": "赠送额度" })[offer.kind];
    const expired = offer.expired === true || typeof offer.expires_at === "string" && Number.isFinite(Date.parse(offer.expires_at)) && Date.parse(offer.expires_at) <= now;
    const expiry = dateLabel(offer.expires_at);
    return `<li class="benefits-offer"><div class="benefits-row-heading"><strong>${renderLink(offer.title || offer.model_id || offer.id, offer.url)}</strong><span>${escapeHtml(kind)} · ${escapeHtml(benefitsOfferStatus(offer))}${expired ? " · 已到期" : ""}</span></div>
      <p>${escapeHtml([offer.provider_id, offer.model_id].filter(Boolean).join(" · "))}</p>
      <p class="benefits-evidence">公开证据 · 非账户额度：${escapeHtml(displayText(offer.evidence, "待核对"))}</p>
      <p>来源：${source ? renderLink(source.title || source.id, source.url) : escapeHtml(displayText(offer.source_id, "未知来源"))} · ${escapeHtml(sourceStatus(source))} · ${escapeHtml(benefitsSourceKind(source?.kind))} · 上次成功：${escapeHtml(dateLabel(source?.last_success_at))}</p>
      <p>${offer.stale === true ? "证据陈旧" : "最近观测"}：${escapeHtml(dateLabel(offer.last_seen_at))} · ${expiry === "未知" ? "到期未知" : `到期：${escapeHtml(expiry)}`}</p>
    </li>`;
  }).join("")}</ul>`;
}

export function renderBenefitsGrants(grants) {
  if (!Array.isArray(grants) || !grants.length) return "";
  return `<ul class="benefits-grants" aria-label="发放记录">${grants.map((grant) => {
    if (!grant || typeof grant !== "object" || !("amount" in grant)) return `<li>发放记录：${escapeHtml(displayText(grant))}</li>`;
    const kind = ({ "daily-login": "每日登录", "aliyun-binding": "阿里云绑定" })[grant.kind] || displayText(grant.title || grant.kind, "发放记录");
    const expiry = dateLabel(grant.expires_at);
    return `<li>${escapeHtml(kind)} · ${escapeHtml(displayText(grant.amount))} 魔粒 · ${escapeHtml(displayText(grant.granted_date_display))} · 显示有效期 ${escapeHtml(displayText(grant.validity_days_display))} 天 · ${expiry === "未知" ? "精确到期未知" : `到期：${escapeHtml(expiry)}`}</li>`;
  }).join("")}</ul>`;
}

export function renderBenefitsSection(view = createBenefitsState()) {
  const snapshot = view.snapshot;
  const loaded = view.loaded === true && Boolean(snapshot);
  const saved = configuration(snapshot);
  const draft = view.draft || saved;
  const dirty = !sameConfiguration(draft, saved);
  const busy = Boolean(view.busy);
  const running = snapshot?.running === true || snapshot?.checkin?.state === "running";
  const disabled = !loaded || busy;
  const browsers = records(view.browsersDetected || view.browsers?.length ? view.browsers : snapshot?.browsers).filter((browser) => typeof browser.instance_id === "string" && browser.instance_id);
  const checkin = snapshot?.checkin || {};
  const balance = checkin.available_balance;
  const knownBalance = (typeof balance === "number" || typeof balance === "string" && balance.trim() !== "") && Number.isFinite(Number(balance)) && Number(balance) >= 0;
  const balanceText = knownBalance ? `${displayText(balance)} ${checkin.unit === "magicube" ? "魔粒" : displayText(checkin.unit)}` : "未知";
  const tab = view.tab === "leads" ? "leads" : "resources";
  const sources = records(snapshot?.sources);
  return `<details class="benefits-section" data-benefits data-ui-key="benefits" ${view.open ? "open" : ""}>
    <summary>免费资源与签到</summary>
    <div class="benefits-body" aria-busy="${Boolean(view.busy)}">
      <div class="benefits-toolbar"><span>${!loaded ? view.busy ? "读取中" : "未读取" : snapshot.running ? "进行中" : snapshot.enabled ? "后台发现已开启" : "后台发现已关闭"}</span><button type="button" class="ghost-button" data-benefits-action="refresh" data-benefits-control="refresh" ${busy ? "disabled" : ""}>${!loaded || running ? "读取状态" : "手动刷新"}</button></div>
      <form data-benefits-configure class="benefits-configure">
        <label class="benefits-toggle"><input type="checkbox" name="enabled" data-benefits-control="enabled" ${draft.enabled ? "checked" : ""} ${disabled ? "disabled" : ""}>后台发现</label>
        <label class="benefits-toggle"><input type="checkbox" name="checkin_enabled" data-benefits-control="checkin_enabled" ${draft.checkin_enabled ? "checked" : ""} ${disabled ? "disabled" : ""}>ModelScope 每日自动签到</label>
        <div class="benefits-browser"><label>签到浏览器<select name="browser_instance_id" data-benefits-control="browser_instance_id" ${disabled ? "disabled" : ""}><option value="">未选择</option>${draft.browser_instance_id && !browsers.some((browser) => browser.instance_id === draft.browser_instance_id) ? `<option value="${escapeHtml(draft.browser_instance_id)}" selected>${escapeHtml(draft.browser_instance_id)}（未检测）</option>` : ""}${browsers.map((browser) => `<option value="${escapeHtml(browser.instance_id)}" ${browser.instance_id === draft.browser_instance_id ? "selected" : ""}>${escapeHtml(browser.browser_name || browser.instance_id)} · ${escapeHtml(browser.instance_id)}</option>`).join("")}</select></label><button type="button" class="ghost-button" data-benefits-action="browsers" data-benefits-control="browsers" ${disabled ? "disabled" : ""}>检测浏览器</button></div>
        <div class="benefits-actions"><button type="submit" class="ghost-button" data-benefits-control="save" ${disabled || configurationIssue(draft) ? "disabled" : ""}>保存</button><span>${configurationIssue(draft) || (dirty ? "未保存" : loaded ? "已保存" : "未读取")}</span>${view.browsersDetected && !browsers.length ? "<span>未检测到浏览器</span>" : ""}</div>
      </form>
      <section class="benefits-checkin" aria-label="ModelScope 签到"><div class="benefits-row-heading"><strong>ModelScope 签到 · ${escapeHtml(statusLabel(checkin.state || "never"))}${checkin.stale === true ? " · 观测过期" : ""}</strong><button type="button" class="ghost-button" data-benefits-action="checkin" data-benefits-control="checkin" ${disabled || running || dirty || !saved.browser_instance_id ? "disabled" : ""}>立即签到</button></div><p>${checkin.state === "verified" && checkin.stale !== true ? "账户余额" : "上次观测余额"}：${escapeHtml(balanceText)} · 核实时间：${escapeHtml(dateLabel(checkin.checked_at))}</p>${checkin.error ? `<p class="benefits-error">${escapeHtml(displayText(checkin.error))}</p>` : ""}${renderBenefitsGrants(checkin.grants)}</section>
      <div class="benefits-tabs" role="tablist" aria-label="免费资源分类">${[["resources", "模型与额度"], ["leads", "资讯线索"]].map(([key, label]) => `<button type="button" role="tab" id="benefits-tab-${key}" aria-controls="benefits-offers" aria-selected="${key === tab}" tabindex="${key === tab ? "0" : "-1"}" data-benefits-tab="${key}" data-benefits-control="${key}">${label}（${escapeHtml(filterBenefitsOffers(snapshot?.offers, key).length)}）</button>`).join("")}</div>
      <div id="benefits-offers" role="tabpanel" aria-labelledby="benefits-tab-${tab}">${loaded ? renderBenefitsOffers(snapshot, tab) : '<p class="benefits-empty">尚未读取资源</p>'}</div>
      ${sources.length ? `<ul class="benefits-sources" aria-label="发现来源">${sources.map((source) => `<li><strong>${renderLink(source.title || source.id, source.url)}</strong><span>${escapeHtml(benefitsSourceKind(source.kind))} · ${escapeHtml(sourceStatus(source))} · ${escapeHtml(Number.isSafeInteger(source.item_count) && source.item_count >= 0 ? source.item_count : "未知")} 项 · 上次成功：${escapeHtml(dateLabel(source.last_success_at))}</span>${source.error ? `<span class="benefits-error">${escapeHtml(displayText(source.error))}</span>` : ""}</li>`).join("")}</ul>` : ""}
      <p class="benefits-notice" role="status">${escapeHtml(view.notice || snapshot?.error)}</p>
    </div>
  </details>`;
}

export function createBenefitsController({ state, rpc, getScope, setTimer = setTimeout, clearTimer = clearTimeout }) {
  const view = state.benefits || (state.benefits = createBenefitsState());
  let scope = null;
  let generation = 0;
  let timer = null;
  let inFlight = null;
  let queuedLoad = false;
  let pollCount = 0;
  let root = null;
  let disposed = false;

  function stopPolling() {
    if (timer !== null) clearTimer(timer);
    timer = null;
  }

  function syncScope() {
    const next = disposed ? null : getScope();
    if (scope === next) return false;
    scope = next;
    generation += 1;
    stopPolling();
    queuedLoad = false;
    view.snapshot = null;
    view.loaded = false;
    view.draft = null;
    view.browsers = [];
    view.browsersDetected = false;
    view.notice = "";
    view.open = false;
    return true;
  }

  function redraw() {
    const panel = root?.querySelector("[data-benefits]");
    if (!panel) return;
    view.open = panel.open;
    const focused = (root.ownerDocument || root).activeElement;
    const control = panel.contains(focused) ? focused?.dataset?.benefitsControl : null;
    panel.outerHTML = renderBenefitsSection(view);
    if (control) [...root.querySelectorAll("[data-benefits-control]")].find((element) => element.dataset.benefitsControl === control)?.focus({ preventScroll: true });
  }

  function schedulePoll() {
    stopPolling();
    if (!scope || disposed || inFlight || view.snapshot?.running !== true) return;
    if (pollCount >= 120) {
      view.notice = "状态跟踪已暂停";
      redraw();
      return;
    }
    timer = setTimer(() => {
      timer = null;
      if (syncScope() || !scope) return;
      pollCount += 1;
      void request("status", {}, true);
    }, 2500);
  }

  function validSnapshot(snapshot) {
    return snapshot && typeof snapshot.enabled === "boolean" && typeof snapshot.checkin_enabled === "boolean" && typeof snapshot.browser_instance_id === "string" && typeof snapshot.running === "boolean" && Array.isArray(snapshot.sources) && Array.isArray(snapshot.offers) && snapshot.checkin && typeof snapshot.checkin === "object";
  }

  function request(action, params = {}, polling = false) {
    syncScope();
    if (!scope || disposed) return Promise.resolve();
    if (inFlight) {
      if (action === "status" && inFlight.generation !== generation) queuedLoad = true;
      return inFlight.promise;
    }
    stopPolling();
    if (!polling) pollCount = 0;
    const ticket = { generation, promise: null };
    inFlight = ticket;
    view.busy = action;
    if (!polling) view.notice = "";
    redraw();
    ticket.promise = (async () => {
      let succeeded = false;
      try {
        const result = await rpc(`benefits.${action}`, params);
        syncScope();
        if (generation !== ticket.generation || !scope) return;
        if (action === "browsers") {
          if (!Array.isArray(result?.browsers)) throw new Error("invalid-browsers");
          view.browsers = records(result.browsers);
          view.browsersDetected = true;
        } else {
          if (!validSnapshot(result)) throw new Error("invalid-snapshot");
          const dirty = view.draft && !sameConfiguration(view.draft, configuration(view.snapshot));
          view.snapshot = result;
          view.loaded = true;
          if (!dirty || action === "configure") view.draft = configuration(result);
          if (Array.isArray(result.browsers)) view.browsers = records(result.browsers);
        }
        view.notice = action === "configure" ? "已保存" : "";
        succeeded = true;
      } catch (error) {
        syncScope();
        if (generation === ticket.generation && scope) {
          const label = ({ status: "状态暂不可用", configure: "保存失败", browsers: "浏览器检测失败", refresh: "刷新失败", checkin: "签到未启动" })[action];
          view.notice = action === "status" ? label : `${label}：${displayText(error?.message, "请求失败").slice(0, 240)}`;
        }
      } finally {
        inFlight = null;
        view.busy = "";
        if (generation === ticket.generation && scope) {
          redraw();
          if (succeeded) schedulePoll();
        }
        if (queuedLoad && scope && !disposed) {
          queuedLoad = false;
          void request("status");
        }
      }
    })();
    return ticket.promise;
  }

  async function act(action) {
    syncScope();
    if (!scope || inFlight) return;
    if (action === "refresh" && (!view.loaded || view.snapshot.running || view.snapshot.checkin?.state === "running")) {
      await request("status");
      return;
    }
    if (!view.loaded) return;
    const saved = configuration(view.snapshot);
    const draft = view.draft || saved;
    if (action === "configure") {
      if (configurationIssue(draft)) {
        view.notice = configurationIssue(draft);
        redraw();
        return;
      }
      return request(action, configuration(draft));
    }
    if (action === "checkin" && (view.snapshot.running || view.snapshot.checkin?.state === "running" || !saved.browser_instance_id || !sameConfiguration(draft, saved))) return;
    if (["refresh", "browsers", "checkin"].includes(action)) return request(action);
  }

  function changeDraft(values) {
    if (!view.loaded || inFlight) return;
    view.draft = configuration({ ...view.draft, ...values, ...(values.enabled === false ? { checkin_enabled: false } : {}) });
    view.notice = "";
    redraw();
  }

  function onClick(event) {
    const changed = syncScope();
    if (changed && scope && root.querySelector("[data-benefits]")) void request("status");
    const button = event.target.closest?.("[data-benefits] button");
    if (!button || button.disabled) return;
    if (button.dataset.benefitsTab) {
      view.tab = button.dataset.benefitsTab === "leads" ? "leads" : "resources";
      redraw();
    } else if (button.dataset.benefitsAction) void act(button.dataset.benefitsAction);
  }

  function onChange(event) {
    const field = event.target;
    if (!field.closest?.("[data-benefits-configure]")) return;
    changeDraft({ [field.name]: field.type === "checkbox" ? field.checked : field.value });
  }

  function onSubmit(event) {
    if (!event.target.matches?.("[data-benefits-configure]")) return;
    event.preventDefault();
    void act("configure");
  }

  function onToggle(event) {
    if (event.target.matches?.("[data-benefits]") && event.target.isConnected) view.open = event.target.open;
  }

  function onKeydown(event) {
    const changed = syncScope();
    if (changed && scope && root.querySelector("[data-benefits]")) void request("status");
    const tab = event.target.closest?.("[data-benefits-tab]");
    if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    view.tab = event.key === "Home" ? "resources" : event.key === "End" ? "leads" : view.tab === "leads" ? "resources" : "leads";
    redraw();
    root.querySelector('[data-benefits-tab][aria-selected="true"]')?.focus();
  }

  function onVisibilityChange() {
    if (syncScope() && scope && root.querySelector("[data-benefits]")) void request("status");
  }

  function bind(nextRoot) {
    if (root === nextRoot || disposed) return;
    unbind();
    root = nextRoot;
    root.addEventListener("click", onClick);
    root.addEventListener("change", onChange);
    root.addEventListener("submit", onSubmit);
    root.addEventListener("toggle", onToggle, true);
    root.addEventListener("keydown", onKeydown);
    root.addEventListener("visibilitychange", onVisibilityChange);
  }

  function unbind() {
    if (!root) return;
    root.removeEventListener("click", onClick);
    root.removeEventListener("change", onChange);
    root.removeEventListener("submit", onSubmit);
    root.removeEventListener("toggle", onToggle, true);
    root.removeEventListener("keydown", onKeydown);
    root.removeEventListener("visibilitychange", onVisibilityChange);
    root = null;
  }

  function dispose() {
    disposed = true;
    syncScope();
    stopPolling();
    unbind();
  }

  return { loadStatus: () => request("status"), act, changeDraft, bind, syncScope, dispose };
}
