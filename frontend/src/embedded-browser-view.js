import { safeBenefitsUrl } from "./benefits-view.js";

export const NATIVE_ACCOUNT_PAGES = [
  { id: "modelscope", title: "魔搭额度与签到", url: "https://modelscope.cn/magicube/usage", profile: "modelscope-free-candidates" },
  { id: "ollama", title: "Ollama 用量", url: "https://ollama.com/settings", profile: "ollama-cloud-candidates" },
  { id: "moark", title: "Moark 账单", url: "https://moark.com/serverless-api", profile: "moark-free-candidates" },
];

export function createEmbeddedBrowserState() {
  return { tabs: [], active: "", notice: "", busy: false, draft: "", token: "", attached: false, generation: 0 };
}

export async function browserLinkSite(rawUrl, title, known) {
  const url = new URL(rawUrl);
  if (known && new URL(known.url).href === url.href) return { ...known, title: title || known.title };
  const hash = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(url.href));
  const suffix = Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("").slice(0, 32);
  const accountId = known?.id || `site-${url.hostname.replace(/[^a-zA-Z0-9_-]/g, "-")}`.slice(0, 48);
  return { ...known, id: `link-${suffix}`, tab_id: `link-${suffix}`, account_id: accountId,
    url: url.href, title: title || known?.title || url.hostname };
}

export function createEmbeddedBrowserController({ state, invoke, rpc, render, escapeHtml, isDesktop, showConsultation, hideConsultation,
  setTimer = setTimeout, clearTimer = clearTimeout }) {
  const view = state.embeddedBrowser || (state.embeddedBrowser = createEmbeddedBrowserState());
  let timer = null;
  let stopped = false;
  let pumping = false;
  let boundsBusy = false;
  let boundsSignature = "";
  const usable = () => isDesktop && !state.overlayMode && !globalThis.document?.hidden;
  const selected = () => view.tabs.find((tab) => tab.tab_id === view.active);
  const update = (tab) => {
    if (tab?.tab) tab = { ...tab, ...tab.tab };
    if (!tab || typeof tab.tab_id !== "string") return;
    view.tabs = [...view.tabs.filter((row) => row.tab_id !== tab.tab_id), tab];
  };

  async function list() {
    if (!isDesktop) return;
    const result = await invoke("embedded_browser_list");
    view.tabs = Array.isArray(result) ? result : result?.tabs || [];
    render();
  }

  async function hide() {
    view.generation += 1;
    state.portalPanelOpen = false;
    boundsSignature = "";
    if (isDesktop) {
      await Promise.all([invoke("embedded_browser_hide_all"), hideConsultation()]);
    }
    render();
  }

  async function open(site, { background = false } = {}) {
    if (!isDesktop) throw new Error("请在 Sumika 桌面版打开内置浏览器；不会自动弹外部窗口。");
    const url = safeBenefitsUrl(site.url);
    if (!url) throw new Error("只允许公开 HTTPS 页面；不接受内网、凭据或不安全地址。");
    const tabId = site.tab_id || site.id;
    const accountId = site.account_id || site.id;
    if (!/^[a-zA-Z0-9_-]{1,48}$/.test(tabId) || !/^[a-zA-Z0-9_-]{1,48}$/.test(accountId)) throw new Error("无效网页档案标识");
    if (!background) {
      await hideConsultation();
      await invoke("embedded_browser_hide_all");
      view.generation += 1;
      state.portalPanelOpen = true;
      view.active = tabId;
    }
    const result = await invoke("embedded_browser_open", { tabId, accountId, url, title: site.title || new URL(url).hostname, legacySiteId: site.site_id || site.legacy_site_id || undefined });
    update({ tab_id: tabId, account_id: accountId, url, title: site.title || new URL(url).hostname, ...result });
    if (!background) {
      view.notice = "登录和验证码请直接在本页完成；不同账户独立，原受管浏览器登录不会迁移。";
      boundsSignature = "";
      render();
    }
    return result;
  }

  async function select(tabId) {
    if (view.busy) return;
    if (tabId === "native-consultation") {
      await invoke("embedded_browser_hide_all");
      state.portalPanelOpen = true;
      view.active = tabId;
      boundsSignature = "";
      await showConsultation();
      render();
      return;
    }
    const tab = view.tabs.find((row) => row.tab_id === tabId);
    if (tab) await open({ ...tab, id: tab.tab_id });
  }

  async function close(tabId) {
    view.generation += 1;
    await invoke("embedded_browser_close", { tabId });
    view.tabs = view.tabs.filter((row) => row.tab_id !== tabId);
    if (view.active === tabId) view.active = "";
    boundsSignature = "";
    render();
  }

  async function action(actionName) {
    const tab = selected();
    if (!tab || view.busy && actionName !== "takeover") return;
    const wasBusy = view.busy;
    if (actionName === "takeover") view.generation += 1;
    view.busy = true;
    try {
      const result = await invoke("embedded_browser_action", { tabId: tab.tab_id, action: actionName, attemptId: tab.attempt_id || undefined });
      update({ ...tab, ...result, tab_id: tab.tab_id, takeover: actionName === "takeover" ? true : actionName === "release" ? false : tab.takeover });
      view.notice = result.status === "completed" ? "已读取本次回复；完整内容保留在原网页中。" : result.reason || result.status || "已更新";
    } finally {
      view.busy = wasBusy;
      render();
    }
  }

  async function send(text) {
    const tab = selected();
    if (!tab || view.busy || tab.takeover || ["pending", "unknown", "submitting"].includes(tab.status) || !state.portalPanelOpen || !usable()) return;
    const generation = view.generation;
    const attemptId = globalThis.crypto.randomUUID();
    view.busy = true;
    let submitted = false;
    try {
      const filled = await invoke("embedded_browser_action", { tabId: tab.tab_id, action: "fill", attemptId, text });
      if (filled.status !== "filled") {
        view.notice = filled.reason || filled.status;
        return;
      }
      if (view.generation !== generation || !usable() || !state.portalPanelOpen || selected()?.takeover) return;
      submitted = true;
      const result = await invoke("embedded_browser_action", { tabId: tab.tab_id, action: "submit", attemptId });
      update({ ...tab, status: result.status, attempt_id: attemptId, possibly_sent: result.possibly_sent });
      view.notice = result.reason || result.status;
      view.draft = "";
    } catch {
      if (submitted) update({ ...tab, status: "unknown", attempt_id: attemptId, possibly_sent: true });
      view.notice = submitted ? "提交状态未知，请读取原请求或接管；不会重复发送。" : "填写未完成，没有自动提交。";
    } finally {
      view.busy = false;
      render();
    }
  }

  async function bindAccount(source) {
    const site = NATIVE_ACCOUNT_PAGES.find((row) => row.id === source);
    if (!site) return;
    await open({ ...site, tab_id: `account-${source}`, account_id: source });
    if (!view.attached) await attach();
    await rpc("browser.embedded.bind_portal", { provider_profile_id: site.profile, source });
    view.notice = "已选择内置账户页。请完成登录；绑定页面不代表授予模型调用或已确认免费额度。";
    render();
  }

  async function attach() {
    if (!isDesktop || stopped) return;
    try {
      const result = await rpc("browser.embedded.attach", {});
      view.token = result.token;
      view.attached = Boolean(result.token);
    } catch (error) {
      view.attached = false;
      view.token = "";
      throw error;
    } finally { schedule(); }
  }

  function schedule() {
    if (!stopped && timer === null) timer = setTimer(() => { timer = null; void pump(); }, 2000);
  }

  async function exchange(request) {
    const tabId = request.tab_id;
    const attemptId = request.message_attempt_id;
    const current = async () => usable() && !stopped && (await rpc("browser.embedded.alive", { token: view.token, attempt_id: request.attempt_id })).active;
    const operation = request.operation;
    const nativeAction = (action, extra = {}) => invoke("embedded_browser_action", { tabId, action, attemptId, ...extra });
    const project = (result) => {
      const status = ({ "login-required": "needs-auth", login: "needs-auth", challenge: "waiting-human", limited: "waiting-human", pending: "unknown", interrupted: "unknown" })[result.status] || result.status;
      return { status, tab_id: tabId, ...(attemptId ? { attempt_id: attemptId } : {}),
        page_ready: status === "ready", auth_state: status === "ready" ? "authorized" : "unknown",
        sent: status === "completed", possibly_sent: result.possibly_sent === true || status === "completed" || status === "unknown",
        ...(status === "completed" ? { text: result.text } : {}) };
    };
    if (!await current()) return { status: "not-sent", sent: false, possibly_sent: false };
    if (operation === "close") { await close(tabId); return { status: "closed" }; }
    if (["open", "focus", "authorize"].includes(operation)) {
      await open(request);
      return { status: operation === "focus" ? "focused" : "opened", tab_id: tabId };
    }
    await open(request, { background: !["send", "takeover"].includes(operation) });
    if (["check", "health"].includes(operation)) return project(await nativeAction(attemptId ? "read" : "observe"));
    if (["takeover", "resume"].includes(operation)) {
      const result = await nativeAction(operation === "resume" ? "release" : "takeover");
      const accepted = operation === "takeover" ? result.tab?.takeover === true || result.status === "takeover" : result.tab?.takeover === false || result.status === "released";
      update({ ...view.tabs.find((row) => row.tab_id === tabId), ...result });
      render();
      return { status: accepted ? operation === "resume" ? "resumed" : "takeover" : "unavailable" };
    }
    if (operation !== "send" || !request.automation_supported) return { status: "unsupported", sent: false, possibly_sent: false };
    if (view.busy || view.tabs.some((row) => row.account_id === request.account_id && row.takeover)) return { status: "takeover", sent: false, possibly_sent: false };
    const generation = view.generation;
    view.busy = true;
    let submitted = false;
    try {
      const observed = await nativeAction("observe");
      if (observed.status !== "ready") return project(observed);
      if (!await current() || generation !== view.generation) return { status: "not-sent", sent: false, possibly_sent: false };
      const filled = await nativeAction("fill", { text: request.text });
      if (filled.status !== "filled") return { ...project(filled), sent: false, possibly_sent: false };
      if (!await current() || generation !== view.generation) return { status: "not-sent", sent: false, possibly_sent: false };
      submitted = true;
      let result = await nativeAction("submit");
      update({ ...view.tabs.find((row) => row.tab_id === tabId), status: result.status, attempt_id: attemptId });
      const deadline = Date.now() + 240000;
      while (["pending", "ready"].includes(result.status) && Date.now() < deadline && generation === view.generation && await current()) {
        await new Promise((resolve) => setTimer(resolve, 1500));
        result = await nativeAction("read");
      }
      update({ ...view.tabs.find((row) => row.tab_id === tabId), status: result.status === "pending" ? "unknown" : result.status, attempt_id: attemptId });
      return project(result);
    } catch {
      return { status: submitted ? "unknown" : "not-sent", sent: false, possibly_sent: submitted };
    } finally { view.busy = false; render(); }
  }

  async function pump() {
    if (stopped || pumping) return;
    pumping = true;
    try {
      if (!view.attached) {
        if (usable()) await attach();
        return;
      }
      const result = await rpc("browser.embedded.poll", { token: view.token, accept_requests: usable() && !view.busy });
      const request = result.request;
      if (request) {
        let observation = { state: "needs-review" };
        try {
          if (request.action === "web-chat") {
            observation = await exchange(request);
          } else {
            const site = NATIVE_ACCOUNT_PAGES.find((row) => row.id === request.source);
            if (!site || request.url !== site.url || request.action !== (site.id === "moark" ? "read-receipts" : "read-account")) throw new Error("未知账户读取流程");
            if (view.tabs.some((row) => row.account_id === request.account_id && row.takeover)) observation = { state: "takeover" };
            else {
              await open(request, { background: true });
              const read = await invoke("embedded_browser_action", { tabId: request.tab_id, action: request.action });
              observation = read.observation || { state: read.status || "needs-review" };
            }
          }
        } catch { observation = request.action === "web-chat" ? { status: "unavailable", sent: false, possibly_sent: false } : { state: "needs-review" }; }
        await rpc("browser.embedded.complete", { token: view.token, attempt_id: request.attempt_id, observation });
      }
    } catch {
      view.attached = false;
      view.token = "";
      view.notice = "内置维护连接暂不可用；未切换外部浏览器或付费模型。";
    } finally {
      pumping = false;
      schedule();
    }
  }

  async function syncBounds() {
    if (!isDesktop || boundsBusy) return;
    const rect = globalThis.document?.querySelector("[data-embedded-rect]")?.getBoundingClientRect();
    if (!state.portalPanelOpen || !usable() || !rect || view.active === "native-consultation") {
      if (boundsSignature) { boundsSignature = ""; await invoke("embedded_browser_hide_all"); }
      return;
    }
    const left = Math.max(0, rect.left), top = Math.max(0, rect.top);
    const width = Math.max(0, Math.min(innerWidth, rect.right) - left);
    const height = Math.max(0, Math.min(innerHeight, rect.bottom) - top);
    const signature = JSON.stringify([view.active, left, top, width, height]);
    if (!view.active || width < 1 || height < 1 || signature === boundsSignature) return;
    boundsBusy = true;
    try {
      await invoke("embedded_browser_bounds", { tabId: view.active, x: left, y: top, width, height });
      boundsSignature = signature;
    } finally { boundsBusy = false; }
  }

  function markup(sites, consultationHtml = "") {
    if (!state.portalPanelOpen) return "";
    const tab = selected();
    const pending = tab && ["pending", "unknown", "submitting"].includes(tab.status);
    return `<section class="embedded-workspace" role="region" aria-label="内置浏览器"><header class="embedded-heading"><div><strong>内置浏览器</strong><small>网页聊天 · 咨询 · 账户 · 福利</small></div><button class="ghost-button" type="button" data-embedded-hide>返回客户端</button></header>
      <nav class="embedded-tabs" aria-label="浏览器标签">${view.tabs.map((row) => `<div class="embedded-tab"><button type="button" data-embedded-tab="${escapeHtml(row.tab_id)}" aria-pressed="${view.active === row.tab_id}">${escapeHtml(row.title || row.tab_id)}</button><button type="button" data-embedded-close="${escapeHtml(row.tab_id)}" aria-label="关闭 ${escapeHtml(row.title || row.tab_id)}">关闭</button></div>`).join("")}<button type="button" data-embedded-tab="native-consultation" aria-pressed="${view.active === "native-consultation"}">ChatGPT 咨询</button></nav>
      <div class="embedded-sites">${sites.map((site) => `<button class="ghost-button" type="button" data-embedded-site="${escapeHtml(site.id)}">${escapeHtml(site.title)}</button>`).join("")}${NATIVE_ACCOUNT_PAGES.map((site) => `<button class="ghost-button" type="button" data-embedded-account="${site.id}">${site.title}</button>`).join("")}</div>
      ${view.active === "native-consultation" ? consultationHtml : `<div class="embedded-toolbar"><span>${escapeHtml(tab?.account_id || "尚未选择网页")} · ${escapeHtml(tab?.status || "请选择站点")}${tab?.takeover ? " · 人工接管" : ""}</span>${tab ? `<button type="button" data-embedded-action="observe">检查</button><button type="button" data-embedded-action="${tab.takeover ? "release" : "takeover"}">${tab.takeover ? "交还助手" : "人工接管"}</button><button type="button" data-embedded-action="read" ${!tab.attempt_id || view.busy ? "disabled" : ""}>读取原回复</button>` : ""}</div><div class="embedded-surface" data-embedded-rect><p>${tab ? "正在加载原站。验证码、登录和授权由你在这里完成。" : "选择网页后在这里打开，不新建外部窗口。"}</p></div>${tab ? `<form data-embedded-chat class="embedded-chat"><label>网页消息<input name="text" maxlength="12000" value="${escapeHtml(view.draft)}" autocomplete="off" placeholder="仅支持已验证的聊天站点；账户页不会发送消息" required></label><button type="submit" ${view.busy || pending || tab.takeover ? "disabled" : ""}>发送</button></form>` : ""}`}
      ${view.active === "native-consultation" ? "" : `<details class="embedded-add"><summary>添加其他网页</summary><form class="portal-add-form" id="portal-add-form"><input name="portal_title" type="text" aria-label="新网页名称" placeholder="名称" maxlength="24" required /><input name="portal_url" type="text" aria-label="新网页地址" placeholder="HTTPS 站点地址" maxlength="500" required /><button class="small-button" type="submit">添加网页</button></form></details>`}
      <p class="embedded-notice" role="status">${escapeHtml(view.notice || "旧门户登录保持；旧受管Edge档案不自动复制。未支持的自动化会明确停止。")}</p></section>`;
  }

  function bind(root, sites) {
    const run = (operation) => { void operation().catch((error) => { view.notice = String(error.message || "操作失败"); render(); }); };
    root.querySelector("[data-embedded-hide]")?.addEventListener("click", () => run(hide));
    root.querySelectorAll("[data-embedded-tab]").forEach((button) => button.addEventListener("click", () => run(() => select(button.dataset.embeddedTab))));
    root.querySelectorAll("[data-embedded-close]").forEach((button) => button.addEventListener("click", () => run(() => close(button.dataset.embeddedClose))));
    root.querySelectorAll("[data-embedded-site]").forEach((button) => button.addEventListener("click", () => run(() => open(sites.find((row) => row.id === button.dataset.embeddedSite)))));
    root.querySelectorAll("[data-embedded-account]").forEach((button) => button.addEventListener("click", () => run(() => {
      const site = NATIVE_ACCOUNT_PAGES.find((row) => row.id === button.dataset.embeddedAccount);
      return bindAccount(site.id);
    })));
    root.querySelectorAll("[data-embedded-action]").forEach((button) => button.addEventListener("click", () => run(() => action(button.dataset.embeddedAction))));
    root.querySelector("[data-embedded-chat] input")?.addEventListener("input", (event) => { view.draft = event.target.value; });
    root.querySelector("[data-embedded-chat]")?.addEventListener("submit", (event) => { event.preventDefault(); run(() => send(view.draft)); });
  }

  function dispose() { stopped = true; if (timer !== null) clearTimer(timer); timer = null; view.generation += 1; }
  return { view, open, select, list, hide, close, action, send, bindAccount, attach, pump, exchange, markup, bind, syncBounds, dispose };
}
