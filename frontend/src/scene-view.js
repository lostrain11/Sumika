import { NAV_ITEMS, DRAWER_TITLES, drawerForPage, drawerPages } from "./scene-shell.js";

export function createSceneView({
  state,
  escapeHtml,
  projectSceneState,
  currentCharacter,
  currentLlmModule,
  llmReady,
  llmStatusLabel,
  providerName,
  renderWelcomeCard,
  renderMessage,
  renderEmptyChat,
  renderPage,
  glyph,
  isDesktopShell,
}) {
  function renderSceneTopbar() {
    const llm = currentLlmModule();
    const llmClass = !state.connected || !llm?.enabled ? "offline" : llmReady() ? "online" : "warning";
    const llmStatus = llmStatusLabel().replace(/^LLM\s*/, "");
    const primaryItems = [
      ["Chat", "陪伴"],
      ["Agent", "工作台"],
      ["Modules", "能力"],
      ["Characters", "角色"],
      ["Settings", "设置"],
    ];
    const activePage = projectSceneState(state).activePage;
    const primaryActive = (page) => page === "Chat"
      ? activePage === "Chat"
      : drawerForPage(page) === projectSceneState(state).drawer;
    return `
    <header class="scene-topbar" ${projectSceneState(state).drawerOpen ? "inert" : ""}>
      <a class="scene-brand" href="#" data-page="Chat" aria-label="返回陪伴场景">sumika <small>日常陪伴</small></a>
      <nav class="scene-primary-nav" aria-label="主导航">
        ${primaryItems.map(([page, label]) => `<button class="primary-nav-item ${primaryActive(page) ? "active" : ""}" type="button" data-page="${page}" aria-current="${primaryActive(page) ? "page" : "false"}">${label}</button>`).join("")}
      </nav>
      <div class="scene-topbar-actions">
      <div class="scene-pill scene-character-pill">
        <label class="compact-field" style="gap:6px">角色
          <select id="character-select">${state.characters.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === state.selectedCharacter ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}</select>
        </label>
      </div>
      <div class="scene-pill" style="gap:10px">
        <button class="provider-summary topbar-status-item" type="button" data-page="Modules" title="在模块页管理大语言模型：${escapeHtml(llmStatusLabel())}" aria-label="LLM：${escapeHtml(providerName())}，${escapeHtml(llmStatusLabel())}">
          <i class="status-dot ${llmClass}" aria-hidden="true"></i><strong class="provider-summary-name">${escapeHtml(providerName())}</strong><small class="provider-summary-state">${escapeHtml(llmStatus)}</small>
        </button>
        <span class="status-chip topbar-status-item"><i class="status-dot ${state.connected ? "online" : "offline"}"></i>${state.connected ? "核心已连接" : "核心未连接"}</span>
        <span class="privacy-chip topbar-status-item"><span class="privacy-icon">◉</span>${escapeHtml(state.privacy)}</span>
        <button class="icon-button" type="button" data-avatar-toggle title="${state.avatarVisible ? "隐藏 Avatar" : "显示 Avatar"}" aria-label="${state.avatarVisible ? "隐藏 Avatar 预览" : "显示 Avatar 预览"}" aria-pressed="${state.avatarVisible}">${state.avatarVisible ? "◉" : "○"}</button>
        ${isDesktopShell ? '<button class="outline-button desktop-overlay-open" type="button" data-overlay-open title="打开可拖动的桌宠浮窗">桌宠</button>' : ""}
      </div>
      </div>
    </header>`;
  }

  function renderSceneDock() {
    return "";
  }

  function renderSceneChat() {
    const scene = projectSceneState(state);
    const portalButton = isDesktopShell ? `<button class="round-button" type="button" data-portal-panel title="网页门户" aria-label="网页门户" aria-expanded="${state.portalPanelOpen}">◨</button>` : "";
    return `
    <div class="scene-chat" ${scene.drawerOpen ? "inert" : ""}>
      <div class="stage-toolbar"><span class="live-label"><i></i> ${escapeHtml(currentCharacter().name)} · ${!state.connected ? "离线" : scene.sending ? "回复中" : "陪伴中"}</span><div class="toolbar-actions"><button class="text-button" id="new-session" type="button" ${state.sessionBusy || !state.connected ? "disabled" : ""}>${state.sessionBusy ? "创建中" : "新会话"}</button><button class="text-button" type="button" data-overlay-open title="切换到桌宠模式">桌宠</button></div></div>
      ${renderWelcomeCard()}
      ${state.sessionNotice ? `<div class="session-notice" role="status">${escapeHtml(state.sessionNotice)}</div>` : ""}
      <div class="message-list scroll-hidden" id="message-list">
        ${state.messages.length ? state.messages.map(renderMessage).join("") : renderEmptyChat()}
      </div>
      ${state.voiceNotice ? `<div class="voice-notice" role="status">${escapeHtml(state.voiceNotice)}</div>` : ""}
      <form class="composer" id="chat-form">
        <div class="dialogue-nameplate"><i aria-hidden="true"></i>${escapeHtml(currentCharacter().name)}</div>
        <textarea id="chat-input" rows="1" aria-label="聊天消息" placeholder="和 ${escapeHtml(currentCharacter().name)} 说点什么..." ${scene.sending || !state.connected ? "disabled" : ""}>${escapeHtml(state.composerDraft)}</textarea>
        <div class="composer-footer"><div class="composer-tools"><button type="button" class="round-button ${state.voiceRecording ? "recording" : ""}" data-audio-record title="${state.voiceRecording ? "停止录音" : "语音输入"}" aria-label="${state.voiceRecording ? "停止录音" : "语音输入"}" aria-pressed="${state.voiceRecording}">⌁</button>${portalButton}<span class="composer-note">语音按需启用 · 本地优先</span></div><button class="send-button" type="submit" ${scene.sending || !llmReady() ? "disabled" : ""}>${scene.sending ? "处理中" : "发送"}<span>↗</span></button></div>
      </form>
    </div>`;
  }

  function renderDrawer(drawer) {
    if (!drawer || !Object.hasOwn(DRAWER_TITLES, drawer)) return "";
    const pages = drawerPages(drawer);
    const tabs = pages.map((page) => {
      const item = NAV_ITEMS.find(([id]) => id === page);
      const active = projectSceneState(state).activePage === page;
      return `<button class="nav-item ${active ? "active" : ""}" type="button" data-page="${page}" aria-current="${active ? "page" : "false"}">${glyph(page)} ${escapeHtml(item?.[1] || page)}</button>`;
    }).join("");
    return `
    <section class="drawer open" role="region" aria-label="${escapeHtml(DRAWER_TITLES[drawer])}">
      <header class="drawer-header">
        <div class="drawer-title"><span class="eyebrow">SUMIKA</span><strong>${escapeHtml(DRAWER_TITLES[drawer])}</strong></div>
        ${pages.length > 1 ? `<nav class="drawer-tabs">${tabs}</nav>` : ""}
        <button class="drawer-close" type="button" data-drawer-close title="回到场景" aria-label="回到场景">✕</button>
      </header>
      <div class="drawer-body">${renderPage()}</div>
    </section>`;
  }

  return { renderSceneTopbar, renderSceneDock, renderSceneChat, renderDrawer };
}
