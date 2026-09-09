import { NAV_ITEMS, DRAWER_TITLES, drawerForPage, drawerPages } from "./scene-shell.js";

export function createSceneView({ state, escapeHtml, projectSceneState, currentCharacter, llmStatusLabel, providerName, renderWelcomeCard, renderMessage, renderEmptyChat, renderPage, llmReady, isDesktopShell }) {
  function renderSceneTopbar() {
    const scene = projectSceneState(state);
    const primary = [["Chat", "陪伴"], ["Agent", "工作台"], ["Capabilities", "能力"], ["Characters", "角色"], ["Settings", "设置"]];
    return `<header class="scene-topbar">
      <div class="scene-brand">sumika <small>日常陪伴</small></div>
      <nav class="scene-primary-nav" aria-label="主导航">${primary.map(([page, label]) => {
        const active = page === "Chat" ? scene.activePage === "Chat" : drawerForPage(page) === scene.drawer;
        return `<button class="nav-item ${active ? "active" : ""}" type="button" data-page="${page}" data-dock-drawer="${drawerForPage(page) || ""}" aria-current="${active ? "page" : "false"}">${label}</button>`;
      }).join("")}</nav>
      <div class="scene-topbar-actions"><button class="text-button" type="button" data-overlay-open title="${isDesktopShell ? "切换桌宠窗口" : "预览桌宠布局，原生窗口需桌面版"}">桌宠${isDesktopShell ? "" : "预览"}</button></div>
    </header>`;
  }

  function renderSceneChat() {
    const scene = projectSceneState(state);
    return `<aside class="scene-chat" aria-label="陪伴聊天" ${scene.drawerOpen || !state.chatOpen ? "inert hidden" : ""}>
      <div class="stage-toolbar"><div><span class="eyebrow">WITH YOU</span><h1>和 ${escapeHtml(currentCharacter().name)} 聊聊</h1></div><button class="text-button" type="button" data-chat-toggle aria-label="收起聊天" aria-expanded="true">收起</button></div>
      <div class="chat-session-bar"><label class="compact-field">角色<select id="character-select" aria-label="当前角色">${state.characters.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === state.selectedCharacter ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}</select></label><button class="text-button" id="new-session" type="button" ${state.sessionBusy || !state.connected ? "disabled" : ""}>${state.sessionBusy ? "创建中" : "新会话"}</button></div>
      ${renderWelcomeCard()}
      ${state.sessionNotice ? `<div class="session-notice" role="status">${escapeHtml(state.sessionNotice)}</div>` : ""}
      <div class="message-list" id="message-list">${state.messages.length ? state.messages.map(renderMessage).join("") : renderEmptyChat()}</div>
      ${state.voiceNotice ? `<div class="voice-notice" role="status">${escapeHtml(state.voiceNotice)}</div>` : ""}
      <form class="composer" id="chat-form">
        <textarea id="chat-input" rows="2" aria-label="聊天消息" placeholder="和 ${escapeHtml(currentCharacter().name)} 说点什么…" ${scene.sending || !state.connected ? "disabled" : ""}>${escapeHtml(state.composerDraft)}</textarea>
        <div class="composer-footer"><div class="composer-tools">${state.modules.some((module) => module.id === "asr" && module.enabled) ? `<button type="button" class="text-button" data-audio-record aria-pressed="${state.voiceRecording}">${state.voiceRecording ? "停止录音" : "语音输入"}</button>` : ""}${isDesktopShell ? `<button class="text-button" type="button" data-portal-panel aria-expanded="${state.portalPanelOpen}">网页门户</button>` : ""}<span class="composer-note">${escapeHtml(state.privacy)}</span></div><button class="send-button" type="submit" ${scene.sending || !llmReady() ? "disabled" : ""}>${scene.sending ? "处理中" : "发送"}</button></div>
      </form>
      <button class="provider-summary" type="button" data-page="Modules" aria-label="LLM：${escapeHtml(providerName())}，${escapeHtml(llmStatusLabel())}"><span class="provider-summary-name">${escapeHtml(providerName())}</span><span class="provider-summary-state">${escapeHtml(llmStatusLabel())}</span></button>
    </aside>${!state.chatOpen && !scene.drawerOpen ? '<button class="restore-chat" type="button" data-chat-toggle aria-label="展开聊天" aria-expanded="false">展开聊天</button>' : ""}`;
  }

  function renderDrawer(drawer) {
    if (!drawer || !Object.hasOwn(DRAWER_TITLES, drawer)) return "";
    const pages = drawerPages(drawer);
    const tabs = pages.map((page) => `<button class="nav-item ${state.activePage === page ? "active" : ""}" type="button" data-page="${page}" aria-current="${state.activePage === page ? "page" : "false"}">${escapeHtml(NAV_ITEMS.find(([id]) => id === page)?.[1] || page)}</button>`).join("");
    return `<section class="drawer open" role="region" aria-label="${escapeHtml(DRAWER_TITLES[drawer])}"><header class="drawer-header"><strong class="drawer-title">${escapeHtml(DRAWER_TITLES[drawer])}</strong>${pages.length > 1 ? `<nav class="drawer-tabs" aria-label="${escapeHtml(DRAWER_TITLES[drawer])}子页面">${tabs}</nav>` : ""}<button class="drawer-close" type="button" data-drawer-close aria-label="回到场景">返回陪伴</button></header><div class="drawer-body">${renderPage()}</div></section>`;
  }

  return { renderSceneTopbar, renderSceneDock: () => "", renderSceneChat, renderDrawer };
}
