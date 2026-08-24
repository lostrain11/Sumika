const state = {
  activePage: "Chat",
  overlayMode: new URLSearchParams(window.location.search).get("mode") === "overlay",
  providerId: "",
  providers: [],
  providerProfiles: [],
  providerTemplates: [],
  providerDrawerOpen: false,
  providerDrawerMode: "manual",
  providerDrawerProfileId: null,
  providerBusy: null,
  providerNotice: "",
  providerImportRaw: "",
  providerImportFilename: "",
  providerImportPreview: null,
  ccsManifest: null,
  ccsReport: null,
  ccsBusy: false,
  plugins: [],
  modules: [],
  audioStatus: { permissions: [], capabilities: [] },
  visionStatus: { permissions: [], sources: [] },
  memories: [],
  snapshots: [],
  tasks: [],
  avatarModels: [],
  avatarIgnored: [],
  avatarInspections: {},
  avatarState: { driver: "none", driver_status: "ready", character_id: "sumika", model: null, state: {} },
  sessions: [],
  activeSessionId: "default",
  characters: [],
  messages: [],
  composerDraft: "",
  events: [],
  diagnostics: null,
  desktopStatus: null,
  taskOpen: true,
  sending: false,
  connected: false,
  privacy: "本地处理",
  selectedCharacter: "sumika",
  moduleBusy: null,
  moduleNotice: "",
  characterBusy: false,
  characterNotice: "",
  audioBusy: null,
  audioNotice: "",
  voiceRecording: false,
  voiceNotice: "",
  visionBusy: null,
  visionNotice: "",
  memoryBusy: null,
  memoryNotice: "",
  toolBusy: false,
  toolNotice: "",
  pluginBusy: null,
  pluginNotice: "",
  pluginPath: "",
  pluginConfigId: null,
  selectedTaskId: null,
  taskBusy: null,
  taskNotice: "",
  avatarBusy: null,
  avatarNotice: "",
  avatarVisible: true,
  vrmViewer: null,
  vrmViewerModulePromise: null,
  vrmMountGeneration: 0,
  chatAutoScroll: true,
  sessionBusy: false,
  sessionNotice: "",
  snapshotBusy: null,
  snapshotNotice: "",
  selectedSnapshotId: null,
  snapshotDiff: null,
  snapshotDraftScope: "system",
  snapshotDraftTargetId: "",
  notificationFilter: "all",
};

const navItems = [
  ["Chat", "聊天"],
  ["Characters", "角色"],
  ["Modules", "模块"],
  ["Tasks", "任务"],
  ["History", "历史"],
  ["Notifications", "通知"],
  ["Settings", "设置"],
  ["Developer", "开发者"],
  ["Guide", "入门指南"],
];

const fallbackModules = [];

const fallbackAvatarState = { driver: "none", driver_status: "ready", character_id: "sumika", model: null, presentation: {}, state: {} };
const fallbackAudioStatus = {
  permissions: [
    { permission_id: "microphone", state: "unknown", updated_at: null },
    { permission_id: "audio_output", state: "unknown", updated_at: null },
  ],
  capabilities: [
    { id: "asr", enabled: false, provider_id: "none", provider_status: "unconfigured", state: "disabled", running: false, permissions: { microphone: "unknown" } },
    { id: "tts", enabled: false, provider_id: "none", provider_status: "unconfigured", state: "disabled", running: false, permissions: { audio_output: "unknown" } },
    { id: "vad", enabled: false, provider_id: "none", provider_status: "unconfigured", state: "disabled", running: false, permissions: { microphone: "unknown" } },
  ],
};
const fallbackVisionStatus = {
  permissions: [
    { permission_id: "screen.read", state: "unknown", updated_at: null },
    { permission_id: "camera.read", state: "unknown", updated_at: null },
  ],
  sources: [
    { id: "screen", enabled: false, provider_id: "none", provider_status: "unconfigured", state: "disabled", running: false, permissions: { "screen.read": "unknown" } },
    { id: "camera", enabled: false, provider_id: "none", provider_status: "unconfigured", state: "disabled", running: false, permissions: { "camera.read": "unknown" } },
  ],
};

const app = document.querySelector("#app");
const isDesktopShell = Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__);
// Tauri production assets use a tauri:// origin while the Python core remains
// the single HTTP/WebSocket boundary. Development still loads from the core,
// so relative URLs preserve the browser preview and the existing dev shell.
let coreBaseUrl = isDesktopShell && !["http:", "https:"].includes(location.protocol)
  ? "http://127.0.0.1:8771"
  : "";
let activeAudioCapture = null;

function coreUrl(path) {
  if (!coreBaseUrl) return path;
  return `${coreBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function currentCharacter() {
  return state.characters.find((item) => item.id === state.selectedCharacter) || {
    id: "sumika",
    name: "默认角色",
    config: {},
  };
}

function currentSession() {
  return state.sessions.find((item) => item.id === state.activeSessionId) || state.sessions[0] || { id: "default", title: "初始会话", character_id: state.selectedCharacter };
}

function currentSessionId() {
  return currentSession().id || "default";
}

function syncActiveSession() {
  if (!state.sessions.some((item) => item.id === state.activeSessionId)) {
    state.activeSessionId = state.sessions[0]?.id || "default";
  }
}

function providerName() {
  const llm = state.modules.find((item) => item.id === "llm");
  const profile = activeProviderProfile() || llm?.profile;
  if (profile?.name) return profile.name;
  if (!state.providerProfiles.length) return "未配置 Provider";
  if (llm?.implementation_id && llm.implementation_id !== "none" && llm?.implementation?.name) return llm.implementation.name;
  const real = (llm?.implementations || []).find((item) => item.id !== "none");
  if (real?.name) return real.name;
  if (llm?.implementation_id) return state.providers.find((item) => item.id === llm.implementation_id)?.name || llm.implementation_id;
  return state.providers.find((item) => item.id === state.providerId)?.name || "未连接 Provider";
}

function normalizeModule(module) {
  if (!module || module.implementation_id !== "none") return module;
  const real = (module.implementations || []).find((item) => item.id !== "none");
  if (!real) return module;
  return { ...module, implementation_id: real.id, implementation: real, config_schema: real.config_schema || {} };
}

function currentLlmModule() {
  return state.modules.find((item) => item.id === "llm") || null;
}

function activeProviderProfile() {
  const llm = currentLlmModule();
  const profileId = llm?.profile_id || llm?.config?.profile_id;
  return state.providerProfiles.find((profile) => profile.id === profileId) || state.providerProfiles.find((profile) => profile.active) || null;
}

function llmReady() {
  const module = currentLlmModule();
  const profile = activeProviderProfile() || module?.profile;
  return Boolean(state.connected && module?.enabled && module.implementation_id !== "none" && profile?.status === "available");
}

function llmStatusLabel() {
  const module = currentLlmModule();
  if (!state.connected) return "核心未连接";
  if (!module?.enabled) return "LLM 已关闭";
  if (llmReady()) return "LLM 就绪";
  return "LLM 未就绪";
}

function avatarDriverLabel(driver) {
  return ({ none: "未启用", live2d: "Live2D（未接入渲染器）", vrm: "VRM / 3D" })[driver] || driver || "未启用";
}

function currentAvatarModel() {
  return state.avatarState?.model || state.avatarModels.find((model) => model.id === currentCharacter().config?.avatar_model_id) || null;
}

function avatarPreviewUrl(model) {
  return model?.metadata?.preview_path ? coreUrl(`/api/avatar/models/${encodeURIComponent(model.id)}/thumbnail`) : "";
}

function avatarModelFileUrl(model) {
  return model?.id ? coreUrl(`/api/avatar/models/${encodeURIComponent(model.id)}/file`) : "";
}

function currentAvatarPresentation() {
  const value = currentCharacter().config?.avatar;
  const config = value && typeof value === "object" ? value : {};
  const position = ["left", "center", "right"].includes(config.position) ? config.position : "center";
  const opacity = Math.min(1, Math.max(0, Number.isFinite(Number(config.opacity)) ? Number(config.opacity) : 1));
  const scale = Math.min(2.5, Math.max(0.5, Number.isFinite(Number(config.scale)) ? Number(config.scale) : 1));
  const rotationSpeed = Math.min(0.4, Math.max(0.05, Number.isFinite(Number(config.rotation_speed)) ? Number(config.rotation_speed) : 0.12));
  const lookAtStrength = Math.min(1, Math.max(0, Number.isFinite(Number(config.look_at_strength)) ? Number(config.look_at_strength) : 1));
  const headFollowStrength = Math.min(1, Math.max(0, Number.isFinite(Number(config.head_follow_strength)) ? Number(config.head_follow_strength) : 0.35));
  return {
    position,
    opacity,
    scale,
    idleMotion: config.idle_motion !== false,
    autoRotate: config.auto_rotate === true,
    rotationSpeed,
    naturalPose: config.natural_pose !== false,
    lookAtEnabled: config.look_at_enabled !== false,
    headFollowEnabled: config.head_follow_enabled !== false,
    lookAtStrength,
    headFollowStrength,
  };
}

function render() {
  rememberChatScrollPreference();
  if (state.activePage !== "Chat" && activeAudioCapture) {
    discardAudioCapture(activeAudioCapture);
    activeAudioCapture = null;
    state.voiceRecording = false;
  }
  const avatarSurfaceSelector = state.overlayMode
    ? ".desktop-overlay-avatar"
    : state.activePage === "Chat" ? ".avatar-stage" : null;
  const previousAvatarSurface = avatarSurfaceSelector ? document.querySelector(avatarSurfaceSelector) : null;
  const preserveAvatarSurface = Boolean(
    previousAvatarSurface
    && previousAvatarSurface.dataset.avatarSignature === avatarRenderSignature()
    && state.avatarVisible,
  );
  if (preserveAvatarSurface) {
    // Detach and reinsert the whole stage in the same synchronous turn. This
    // keeps the WebGL canvas, animation clock and pointer listeners alive while
    // chat status/messages repaint around it.
    previousAvatarSurface.remove();
  } else {
    disposeVrmViewer();
  }
  document.body.dataset.sumikaMode = state.overlayMode ? "overlay" : "workspace";
  if (state.overlayMode) {
    app.innerHTML = renderOverlay();
    if (preserveAvatarSurface) {
      document.querySelector(".desktop-overlay-avatar")?.replaceWith(previousAvatarSurface);
      updatePreservedAvatarSurface(previousAvatarSurface);
    }
    bindEvents();
    if (!preserveAvatarSurface) queueVrmViewerMount();
    return;
  }
  app.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar" aria-label="主导航">
        <div class="brand-lockup">
          <div class="brand-mark">S</div>
          <div><strong>Sumika</strong><span>local companion</span></div>
        </div>
        <nav class="nav-list">
          ${navItems.map(([id, label]) => `
            <button class="nav-item ${state.activePage === id ? "active" : ""}" data-page="${id}">
              <span class="nav-glyph">${glyph(id)}</span><span>${label}</span>
            </button>`).join("")}
        </nav>
        <div class="sidebar-footer">
          <div class="runtime-dot"><i></i> 核心服务 ${state.connected ? "已连接" : "未连接"}</div>
          <button class="developer-link" data-page="Developer">开发者模式 <span>›</span></button>
        </div>
      </aside>
      <main class="main-shell">
        ${renderTopbar()}
        ${renderPage()}
      </main>
    </div>`;
  if (preserveAvatarSurface) {
    document.querySelector(".avatar-stage")?.replaceWith(previousAvatarSurface);
    updatePreservedAvatarSurface(previousAvatarSurface);
  }
  bindEvents();
  if (!preserveAvatarSurface) queueVrmViewerMount();
  scheduleScrollMessages();
}

function avatarRenderSignature() {
  const model = currentAvatarModel();
  return JSON.stringify({
    character: state.selectedCharacter,
    characterName: currentCharacter().name,
    visible: state.avatarVisible,
    driver: state.avatarState?.driver || currentCharacter().config?.avatar_driver || "none",
    driverStatus: state.avatarState?.driver_status || "ready",
    model: model?.id || null,
    presentation: currentAvatarPresentation(),
  });
}

function updatePreservedAvatarSurface(surface) {
  if (!surface) return;
  const hint = surface.querySelector(".speech-hint");
  if (hint) hint.textContent = state.sending ? "正在思考..." : "今天也一起完成一点小目标吧。";
}

function disposeVrmViewer() {
  state.vrmMountGeneration += 1;
  state.vrmViewer?.destroy?.();
  state.vrmViewer = null;
}

function queueVrmViewerMount() {
  const element = document.querySelector("[data-vrm-source]");
  if (!element || !state.avatarVisible) return;
  if (!state.vrmViewerModulePromise) {
    // The Python core serves this public bundle at the web root; keep it a
    // runtime import so the same shell works in the dev server and Tauri.
    const viewerModuleUrl = coreUrl("/vendor/sumika-vrm-viewer.js");
    state.vrmViewerModulePromise = import(/* @vite-ignore */ viewerModuleUrl);
  }
  const source = element.dataset.vrmSource;
  const presentation = currentAvatarPresentation();
  const generation = ++state.vrmMountGeneration;
  state.vrmViewerModulePromise
    .then(({ mountVrmViewer }) => mountVrmViewer(element, source, {
      idleMotion: presentation.idleMotion,
      autoRotate: presentation.autoRotate,
      rotationSpeed: presentation.rotationSpeed,
      naturalPose: presentation.naturalPose,
      lookAtEnabled: presentation.lookAtEnabled,
      headFollowEnabled: presentation.headFollowEnabled,
      lookAtStrength: presentation.lookAtStrength,
      headFollowStrength: presentation.headFollowStrength,
    }))
    .then((viewer) => {
      if (!element.isConnected || generation !== state.vrmMountGeneration) {
        viewer.destroy();
        return;
      }
      state.vrmViewer = viewer;
      element.closest(".avatar-placeholder")?.classList.add("vrm-live");
    })
    .catch((error) => {
      if (element.isConnected && generation === state.vrmMountGeneration) {
        element.dataset.vrmStatus = "error";
        element.dataset.vrmError = error?.message || "VRM renderer unavailable";
        element.closest(".avatar-placeholder")?.classList.add("vrm-error");
      }
    });
}

function renderTopbar() {
  const llm = currentLlmModule();
  const llmClass = !state.connected || !llm?.enabled ? "offline" : llmReady() ? "online" : "warning";
  return `
    <header class="topbar">
      <div class="breadcrumb"><span class="eyebrow">WORKSPACE</span><strong>${escapeHtml(pageTitle())}</strong></div>
      <div class="topbar-controls">
        <label class="compact-field">角色
          <select id="character-select">${state.characters.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === state.selectedCharacter ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}</select>
        </label>
        <div class="topbar-status-group" aria-label="运行状态">
        <button class="provider-summary topbar-status-item" type="button" data-page="Modules" title="在模块页管理大语言模型">
          <span class="provider-summary-label">LLM</span><strong>${escapeHtml(providerName())}</strong><i class="status-dot ${llmClass}"></i><small>${escapeHtml(llmStatusLabel())}</small>
        </button>
        <span class="status-chip topbar-status-item"><i class="status-dot ${state.connected ? "online" : "offline"}"></i>${state.connected ? "核心已连接" : "核心未连接"}</span>
        <span class="privacy-chip topbar-status-item"><span class="privacy-icon">◉</span>${state.privacy}</span>
        </div>
        <button class="icon-button" type="button" data-avatar-toggle title="${state.avatarVisible ? "隐藏 Avatar 预览" : "显示 Avatar 预览"}" aria-label="${state.avatarVisible ? "隐藏 Avatar 预览" : "显示 Avatar 预览"}" aria-pressed="${state.avatarVisible}">${state.avatarVisible ? "◉" : "○"}</button>
        ${isDesktopShell ? '<button class="outline-button desktop-overlay-open" type="button" data-overlay-open title="打开可拖动的桌宠浮窗">桌宠模式</button>' : ""}
      </div>
    </header>`;
}

function pageTitle() {
  return navItems.find(([id]) => id === state.activePage)?.[1] || "聊天";
}

function renderPage() {
  switch (state.activePage) {
    case "Guide": return renderGuide();
    case "Chat": return renderChat();
    case "Characters": return renderCharacters();
    case "Modules": return renderModules();
    case "Tasks": return renderTasks();
    case "History": return renderHistory();
    case "Notifications": return renderNotifications();
    case "Settings": return renderSettings();
    case "Developer": return renderDeveloper();
    default: return renderChat();
  }
}

function renderGuide() {
  const pageDetails = {
    Chat: ["进行文字对话、切换会话、查看 Avatar 和实时状态；桌面端还可打开可拖动的桌宠模式。", "输入框、发送、新会话、Avatar 开关、桌宠模式"],
    Characters: ["通过折叠的身份、人格和高级设置管理每个角色，并单独处理 Avatar 资产绑定。", "展开分组、保存角色、导入/绑定模型"],
    Modules: ["按能力启停模块，并为 LLM 选择可复用连接档案。", "开关、最近连接、配置抽屉、导入预览"],
    Tasks: ["查看任务生命周期、预算、权限、日志、产物和批准动作。", "创建任务、展开任务、批准/暂停/取消"],
    History: ["切换本地会话，浏览或维护按角色隔离的长期记忆。", "会话行、记忆新增/删除、模块跳转"],
    Notifications: ["按严重级别查看权限、失败、批准和恢复通知。", "筛选按钮、通知中的查看"],
    Settings: ["管理数据快照、导入导出、差异检查和恢复。", "快照范围、创建、选择、导出/恢复/导入"],
    Developer: ["检查 provider、扫描插件 manifest、配置外部启动器和查看事件。", "刷新、扫描、批准、配置、测试调用、撤销"],
  };
  const navigation = navItems
    .filter(([id]) => id !== "Guide")
    .map(([id, label]) => {
      const details = pageDetails[id];
      return '<article class="guide-map-item"><div class="guide-map-icon">' + glyph(id) + '</div><div class="guide-map-copy"><strong>' +
        escapeHtml(label) + '</strong><p>' + escapeHtml(details[0]) + '</p><small>可操作：' +
        escapeHtml(details[1]) + '</small></div><button class="small-button guide-jump" type="button" data-page="' +
        escapeHtml(id) + '">打开</button></article>';
    }).join("");
  const flow = [
    ["01", "启动并确认核心和隐私状态", "Windows 桌面端每次启动运行 .\\tools\\run-desktop.ps1。桌面核心默认使用 8771，浏览器预览使用 8770，日志在 .sumika-desktop\\logs\\；macOS 和 Linux 当前使用文档中的 Python 核心命令。打开后先看左下角“核心服务”和顶部状态；摄像头、屏幕、麦克风不会因为打开页面自动启动。", "Chat", "启动脚本 / 顶部状态 / 左侧底部"],
    ["02", "选择角色与 Avatar", "顶部“角色”下拉框用于快速切换。进入“角色”页后点击“使用”切换角色；身份、人格和模型表现默认折叠，按需展开并统一保存。Avatar 模型库仍单独负责导入、刷新、绑定或解除绑定。", "Characters", "顶部角色下拉框 / 角色页"],
     ["03", "选择模型 Provider", "顶部 LLM 状态入口只负责查看和跳转。到“模块”页展开“实现方式”可选择最近用过的健康连接；点击“＋自定义连接”打开配置抽屉，填写 Ollama 或兼容 API，也可以粘贴经过预览的配置。保存后先测试，确认模型可用再启用。", "Modules", "顶部 LLM 状态 / 连接档案 / 配置抽屉"],
    ["04", "只启用需要的模块", "在“模块”页逐张处理：右上角开关是唯一启停入口，连接或实现控件只负责替换后端。语音、视觉、长期记忆默认关闭；涉及设备或数据的能力还要在同页明确授予权限。顶部隐私状态会按所有启用模块显示本地、云端或混合处理。", "Modules", "模块开关 / 实现选择 / 权限按钮"],
    ["05", "创建会话并发送第一条消息", "回到“聊天”，点击“新会话”获得独立记录，在输入框写下问题并点击“发送”。右侧“当前状态”显示生成状态、任务、隐私采集和最近事件；Avatar 右上角圆形按钮可以隐藏或显示，桌面端点击“桌宠模式”后可拖动模型区域移动浮窗并直接聊天。", "Chat", "新会话 / 输入框 / 发送 / Avatar 开关 / 桌宠模式"],
    ["06", "审计任务与结果", "需要长任务或外部工具时进入“任务”：点击任务卡展开详情，查看自治等级、预算、权限、日志和产物，并在“等待批准”时明确批准。重要提醒会进入“通知”，历史会话和记忆在“历史”查看。", "Tasks", "任务卡 / 通知筛选 / 历史会话"],
    ["07", "试用后创建恢复点", "进入“设置”的数据与备份区域，选择系统、模块、角色或记忆范围，创建命名快照。点击快照先看差异，再导出或恢复；恢复前核心会自动创建恢复前快照。", "Settings", "快照范围 / 创建 / 差异 / 恢复"],
  ].map(([number, title, text, page, location]) => {
    const targetLabel = navItems.find(([id]) => id === page)?.[1] || page;
    return '<article class="guide-flow-item"><span class="guide-flow-number">' + number +
      '</span><div class="guide-flow-copy"><div class="guide-flow-heading"><strong>' + escapeHtml(title) +
      '</strong><span>' + escapeHtml(location) + '</span></div><p>' + escapeHtml(text) +
      '</p><button class="link-button guide-jump" type="button" data-page="' + escapeHtml(page) +
      '">前往' + escapeHtml(targetLabel) + ' ↗</button></div></article>';
  }).join("");
  return renderPageFrame("入门指南", "先了解界面地图，再按一条完整流程完成第一次本地对话。",
    '<div class="guide-intro"><div><span class="eyebrow">START HERE</span><strong>建议第一次按 01 → 07 顺序操作</strong><p>指南中的跳转按钮会打开对应页面；不会自动启用模块、授予权限、启动外部软件或改变数据。</p></div><button class="outline-button guide-jump" type="button" data-page="Chat">从聊天开始 ↗</button></div>' +
    '<section class="guide-section"><div class="guide-section-heading"><div><span class="eyebrow">WORKSPACE MAP</span><strong>界面地图</strong><small>侧边导航中的每个页面，以及它负责的操作。</small></div></div><div class="guide-map-grid">' + navigation + '</div></section>' +
    '<section class="guide-section"><div class="guide-section-heading"><div><span class="eyebrow">BASIC FLOW</span><strong>完整基本使用流程</strong><small>按顺序完成一次“配置 → 对话 → 审计 → 恢复点”闭环。</small></div></div><div class="guide-flow">' + flow + '</div></section>' +
    '<section class="guide-section guide-quick-reference"><div class="guide-section-heading"><div><span class="eyebrow">CONTROL SURFACE</span><strong>当前窗口的可操作位置</strong><small>顶部和聊天页上的控件是高频入口，复杂设置仍在对应页面完成。</small></div></div><div class="guide-control-grid">' +
      '<article><strong>左侧导航</strong><p>点击页面名称切换工作区；底部“开发者模式”直接打开 Developer。</p></article>' +
       '<article><strong>顶部栏</strong><p>切换角色，查看 LLM、核心连接与隐私状态；点击 LLM 状态可进入模块页，右侧圆形按钮控制 Avatar 可见性，桌面端的“桌宠模式”打开可拖动浮窗。</p></article>' +
      '<article><strong>聊天舞台</strong><p>“新会话”、输入框和“发送”可直接操作；Avatar 下方状态文字显示驱动和模型。</p></article>' +
      '<article><strong>右侧状态面板</strong><p>可折叠查看 LLM、当前任务、隐私采集和最近事件；“查看全部/管理/审计”会跳转。</p></article>' +
      '<article><strong>模块与权限</strong><p>模块卡片的开关、实现选择和配置表单会持久化到本机；设备权限和运行按钮必须逐项确认。</p></article>' +
      '<article><strong>安全边界</strong><p>插件扫描不会执行代码；外部软件、任务和视觉采集都需要明确操作或批准。原始视觉数据默认即时丢弃。</p></article>' +
    '</div></section>' +
    '<section class="guide-section guide-reserved"><div class="guide-section-heading"><div><span class="eyebrow">CURRENT LIMITS</span><strong>首版中的预留入口</strong><small>这些控件保留了交互位置，但当前不会执行完整功能。</small></div></div><div class="guide-reserved-list">' +
       '<span>聊天页“附件”圆钮：附件处理尚未接入。</span><span>聊天页“语音”圆钮：需先在模块页配置、授权并启动 ASR；随后会在本机录音并把识别文字填入输入框。</span><span>聊天页“更多操作”：菜单尚未接入。</span><span>内容页标题右侧“查看文档”：文档链接尚未接入。</span><span>设置页“常规 / 隐私与权限 / 快捷键 / 外观与 Avatar”：当前是信息架构占位；可用数据和快照操作在同页内容区。</span><span>开发者 Provider 行中的“manifest”：详情查看尚未接入。</span><span>当前 Avatar 渲染器支持 VRM；其他模型格式可以保留登记信息，待对应驱动通过审核后再启用。</span>' +
    '</div></section>');
}

function renderChat() {
  return `
    <section class="chat-layout page-layout">
      <div class="chat-stage">
        <div class="stage-toolbar"><span class="live-label"><i></i> ${escapeHtml(currentCharacter().name)} 在线</span><div class="toolbar-actions"><button class="text-button" id="new-session" type="button" ${state.sessionBusy ? "disabled" : ""}>${state.sessionBusy ? "创建中" : "新会话"}</button><button class="icon-button" type="button" title="更多操作">•••</button></div></div>
        ${state.sessionNotice ? `<div class="session-notice" role="status">${escapeHtml(state.sessionNotice)}</div>` : ""}
           <div class="avatar-stage" data-avatar-signature="${escapeHtml(avatarRenderSignature())}" aria-label="Avatar 预览">
           <div class="avatar-orbit" aria-hidden="true"></div>${state.avatarVisible ? renderAvatarPresenter() : `<div class="avatar-hidden-state" role="status"><span>Avatar 已隐藏</span></div>`}
           <div class="speech-hint">${state.sending ? "正在思考..." : "今天也一起完成一点小目标吧。"}</div>
         </div>
        <div class="message-list" id="message-list">
          ${state.messages.length ? state.messages.map(renderMessage).join("") : renderEmptyChat()}
        </div>
        ${state.voiceNotice ? `<div class="voice-notice" role="status">${escapeHtml(state.voiceNotice)}</div>` : ""}
        <form class="composer" id="chat-form">
          <textarea id="chat-input" rows="1" placeholder="和 ${escapeHtml(currentCharacter().name)} 说点什么..." ${state.sending || !state.connected ? "disabled" : ""}>${escapeHtml(state.composerDraft)}</textarea>
          <div class="composer-footer"><div class="composer-tools"><button type="button" class="round-button" title="附件">＋</button><button type="button" class="round-button ${state.voiceRecording ? "recording" : ""}" data-audio-record title="${state.voiceRecording ? "停止录音" : "语音输入"}" aria-label="${state.voiceRecording ? "停止录音" : "语音输入"}" aria-pressed="${state.voiceRecording}">⌁</button><span class="composer-note">语音按需启用 · 本地优先</span></div><button class="send-button" type="submit" ${state.sending || !llmReady() ? "disabled" : ""}>${state.sending ? "处理中" : "发送"}<span>↗</span></button></div>
        </form>
      </div>
      ${renderInspector()}
    </section>`;
}

function renderEmptyChat() {
  if (!state.connected) {
    return '<div class="empty-chat"><span class="empty-icon">✦</span><strong>核心未连接</strong><p>启动 Sumika 核心后才能发送消息。</p></div>';
  }
  if (!state.providerProfiles.length) {
    return '<div class="empty-chat"><span class="empty-icon">✦</span><strong>先配置 Provider</strong><p>Sumika 不会自动安装模型或选择连接。</p><button class="outline-button" type="button" data-page="Modules">前往模块页</button></div>';
  }
  if (!currentLlmModule()?.enabled) {
    return '<div class="empty-chat"><span class="empty-icon">✦</span><strong>LLM 已关闭</strong><p>在模块页选择已测试的连接并主动启用。</p><button class="outline-button" type="button" data-page="Modules">前往模块页</button></div>';
  }
  const greeting = currentPersonaConfig().greeting.trim();
  if (greeting) {
    return `<div class="empty-chat empty-chat-greeting"><span class="empty-icon">✦</span><strong>${escapeHtml(currentCharacter().name)} 的问候</strong><p>${escapeHtml(greeting).replaceAll("\n", "<br>")}</p></div>`;
  }
  return `<div class="empty-chat"><span class="empty-icon">✦</span><strong>从一个问题开始</strong><p>当前使用 ${escapeHtml(providerName())}。发送前请确认模型服务状态为“可用”。</p></div>`;
}

function renderOverlay() {
  const status = state.connected ? "核心已连接" : "核心未连接";
  return `<main class="desktop-overlay-shell" aria-label="桌面 Avatar 浮窗">
    <div class="desktop-overlay-toolbar" data-tauri-drag-region>
      <div class="desktop-overlay-title"><i class="status-dot ${state.connected ? "online" : "offline"}"></i><strong>${escapeHtml(currentCharacter().name)}</strong><small>${escapeHtml(status)}</small></div>
      <div class="desktop-overlay-actions">
        <button class="icon-button" type="button" data-overlay-open-main title="打开 Sumika 主窗口" aria-label="打开 Sumika 主窗口">↗</button>
        <button class="icon-button" type="button" data-overlay-hide title="隐藏桌面 Avatar 浮窗" aria-label="隐藏桌面 Avatar 浮窗">×</button>
      </div>
    </div>
    <div class="desktop-overlay-avatar" data-avatar-signature="${escapeHtml(avatarRenderSignature())}" data-tauri-drag-region aria-label="Avatar 预览，可拖动桌宠窗口">
      <div class="avatar-orbit" aria-hidden="true"></div>
      ${state.avatarVisible ? renderAvatarPresenter() : `<div class="avatar-hidden-state" role="status"><span>Avatar 已隐藏</span></div>`}
    </div>
    <form class="overlay-composer" id="chat-form">
      <textarea id="chat-input" rows="1" placeholder="和 ${escapeHtml(currentCharacter().name)} 说点什么..." ${state.sending || !state.connected ? "disabled" : ""}>${escapeHtml(state.composerDraft)}</textarea>
      <button class="send-button" type="submit" ${state.sending || !llmReady() ? "disabled" : ""} title="发送消息">${state.sending ? "处理中" : "发送"}<span>↗</span></button>
    </form>
    <div class="desktop-overlay-status"><span>${state.sending ? "正在思考..." : "等待互动"}</span><small>拖动模型区域移动桌宠 · 复杂设置在主窗口</small></div>
  </main>`;
}

function renderAvatarPresenter() {
  const avatarModel = currentAvatarModel();
  const avatarDriver = state.avatarState?.driver || currentCharacter().config?.avatar_driver || "none";
  const presentation = currentAvatarPresentation();
  const avatarPreview = avatarPreviewUrl(avatarModel);
  const avatarSource = avatarDriver === "vrm" ? avatarModelFileUrl(avatarModel) : "";
  return `<div class="avatar-presenter avatar-position-${presentation.position}" style="opacity:${presentation.opacity};transform:scale(${presentation.scale})">
    <div class="avatar-placeholder avatar-${escapeHtml(avatarDriver)} avatar-position-${presentation.position} ${avatarPreview ? "has-preview" : ""}">
      ${avatarSource ? `<div class="vrm-renderer" data-vrm-source="${escapeHtml(avatarSource)}" data-vrm-idle-motion="${presentation.idleMotion}" data-vrm-auto-rotate="${presentation.autoRotate}" data-vrm-rotation-speed="${presentation.rotationSpeed}" data-vrm-status="idle" aria-label="VRM Avatar 实时渲染" aria-busy="true"></div>` : ""}
      ${avatarPreview ? `<img class="avatar-preview-image" src="${escapeHtml(avatarPreview)}" alt="${escapeHtml(avatarModel?.name || "Avatar 模型")}" />` : ""}
    </div>
    <div class="avatar-preview-copy"><span>${escapeHtml(avatarDriverLabel(avatarDriver))}</span><strong>${escapeHtml(currentCharacter().name)}</strong><small>${escapeHtml(avatarModel?.name || "未绑定模型")} · ${escapeHtml(state.avatarState?.driver_status || "ready")}</small></div>
  </div>`;
}

function renderMessage(message) {
  const role = message.role === "user" ? "你" : currentCharacter().name;
  return `<article class="message ${message.role}"><div class="message-meta"><span>${role}</span><time>${formatTime(message.created_at)}</time></div><div class="message-body">${escapeHtml(message.content).replaceAll("\n", "<br>")}</div></article>`;
}

function renderInspector() {
  const event = state.events[0];
  const visionRunning = (state.visionStatus?.sources || []).filter((source) => source.running);
  const visionState = visionRunning.length ? `运行中 · ${visionRunning.map((source) => visionSourceLabel(source.id)).join("、")}` : "未启用 · 原始数据不落盘";
  return `<aside class="inspector ${state.taskOpen ? "" : "collapsed"}">
    <div class="inspector-header"><div><span class="eyebrow">LIVE STATE</span><strong>当前状态</strong></div><button class="icon-button" id="toggle-inspector" title="折叠状态面板">${state.taskOpen ? "›" : "‹"}</button></div>
    ${state.taskOpen ? `<div class="inspector-body">
       <div class="state-card"><div class="state-card-head"><span class="state-icon">◌</span><div><strong>${state.sending ? "LLM 生成中" : llmStatusLabel()}</strong><small>${escapeHtml(providerName())}</small></div><i class="pulse-dot ${state.sending ? "active" : ""}"></i></div><div class="progress-track"><span style="width:${state.sending ? "62" : llmReady() ? "100" : "18"}%"></span></div><div class="state-card-foot"><span>${state.sending ? "正在接收 token" : llmReady() ? "模型服务就绪" : !currentLlmModule()?.enabled ? "模块已关闭" : "等待模型服务"}</span><span>${state.sending ? "运行中" : llmReady() ? "ready" : "off"}</span></div></div>
      <div class="inspector-section"><div class="section-label"><span>任务</span><button class="link-button" data-page="Tasks">查看全部</button></div><div class="task-row"><span class="task-status done">✓</span><div><strong>文字对话</strong><small>当前会话 · ${state.events.length} 个事件</small></div><span class="task-chevron">›</span></div></div>
      <div class="inspector-section"><div class="section-label"><span>隐私采集</span><button class="link-button" data-page="Modules">管理</button></div><div class="permission-row"><span class="permission-icon">◉</span><div><strong>摄像头 / 屏幕</strong><small>${escapeHtml(visionState)}</small></div><span class="switch ${visionRunning.length ? "on" : "off"}"></span></div></div>
      <div class="inspector-section"><div class="section-label"><span>最近事件</span><button class="link-button" data-page="Developer">审计</button></div>${event ? `<div class="event-row"><span class="event-dot"></span><div><strong>${escapeHtml(event.event_type)}</strong><small>${formatTime(event.timestamp)}</small></div></div>` : `<div class="muted-row">暂无事件</div>`}</div>
    </div>` : ""}
  </aside>`;
}

function renderCharacters() {
  const cards = state.characters.map((character) => {
    const model = state.avatarModels.find((item) => item.id === character.config?.avatar_model_id);
    const preview = avatarPreviewUrl(model);
    return `<article class="character-card ${character.id === state.selectedCharacter ? "selected" : ""}"><div class="character-art">${preview ? `<img class="character-art-image" src="${escapeHtml(preview)}" alt="${escapeHtml(model?.name || "Avatar 模型")}" />` : ""}<div class="character-art-copy"><span>${escapeHtml(avatarDriverLabel(character.config?.avatar_driver || "none"))}</span><strong>${escapeHtml(character.name)}</strong></div></div><div class="character-card-body"><div><strong>${escapeHtml(character.name)}</strong><small>${escapeHtml(model?.name || "未绑定 Avatar 模型")} · ${character.config?.memory_enabled ? "记忆已启用" : "记忆默认关闭"}</small></div><button class="small-button" data-character="${escapeHtml(character.id)}">${character.id === state.selectedCharacter ? "当前角色" : "使用"}</button></div></article>`;
  }).join("");
  return renderPageFrame("角色", "Sumika 是项目名；每个角色都有独立名称、persona、Avatar 和记忆空间。", `<div class="character-grid">${cards}<button class="add-card" id="add-character"><span>＋</span><strong>创建角色</strong><small>从独立配置开始</small></button></div>${renderCharacterEditor()}${renderAvatarLibrary()}`);
}

function currentPersonaConfig() {
  const value = currentCharacter().config?.persona;
  const persona = value && typeof value === "object" ? value : {};
  return {
    identity: String(persona.identity || ""),
    traits: String(persona.traits || ""),
    relationship: String(persona.relationship || ""),
    speakingStyle: String(persona.speaking_style || ""),
    behavior: String(persona.behavior || ""),
    boundaries: String(persona.boundaries || ""),
    responseLength: ["concise", "balanced", "detailed"].includes(persona.response_length) ? persona.response_length : "balanced",
    systemPrompt: String(persona.system_prompt || ""),
    greeting: String(persona.greeting || ""),
  };
}

function personaSummary(persona) {
  const fields = [persona.traits, persona.relationship, persona.speakingStyle, persona.behavior, persona.boundaries, persona.systemPrompt, persona.greeting];
  const count = fields.filter((value) => value.trim()).length;
  const response = persona.responseLength === "balanced" ? "" : ` · ${persona.responseLength === "concise" ? "简洁" : "详细"}`;
  return count ? `已设置 ${count} 项${response}` : "尚未设置";
}

function avatarPositionLabel(position) {
  return ({ left: "左侧", center: "居中", right: "右侧" })[position] || "居中";
}

function avatarPresentationSummary(presentation) {
  return `${avatarPositionLabel(presentation.position)} · ${(presentation.opacity * 100).toFixed(0)}% · ${presentation.scale.toFixed(2)}x · ${presentation.idleMotion ? "待机开启" : "静态"}`;
}

function renderCharacterEditor() {
  const character = currentCharacter();
  const config = character.config || {};
  const persona = currentPersonaConfig();
  const presentation = currentAvatarPresentation();
  const notice = state.characterNotice ? `<div class="character-notice" role="status">${escapeHtml(state.characterNotice)}</div>` : "";
  const languageLabels = { "zh-CN": "简体中文", "zh-TW": "繁體中文", "ja-JP": "日本語", "en-US": "English" };
  const language = languageLabels[config.language] || config.language || "未设置语言";
  return `<section class="character-editor"><div class="character-editor-heading"><div><span class="eyebrow">CHARACTER EDITOR</span><strong>当前角色配置</strong><small>角色身份、人格和模型表现分开管理；设置保存后会按角色持久化。</small></div></div>${notice}<form id="character-form">
    <details class="character-settings-group" data-character-section="identity">
      <summary><span>角色身份</span><small>${escapeHtml(character.name)} · ${escapeHtml(language)}</small></summary>
      <div class="character-settings-body"><div class="character-settings-grid">
        <label class="character-field"><span>角色名称</span><input name="name" type="text" maxlength="100" value="${escapeHtml(character.name)}" required /></label>
        <label class="character-field"><span>语言</span><select name="language"><option value="zh-CN" ${config.language === "zh-CN" ? "selected" : ""}>简体中文（zh-CN）</option><option value="zh-TW" ${config.language === "zh-TW" ? "selected" : ""}>繁體中文（zh-TW）</option><option value="ja-JP" ${config.language === "ja-JP" ? "selected" : ""}>日本語（ja-JP）</option><option value="en-US" ${config.language === "en-US" ? "selected" : ""}>English（en-US）</option></select></label>
        <label class="character-field character-field-wide"><span>角色身份 / 定位</span><textarea name="persona_identity" rows="3" maxlength="4000" placeholder="例如：温和、可靠的学习搭档">${escapeHtml(persona.identity)}</textarea></label>
      </div></div>
    </details>
    <details class="character-settings-group" data-character-section="persona">
      <summary><span>人格设定</span><small>${escapeHtml(personaSummary(persona))}</small></summary>
      <div class="character-settings-body"><div class="character-settings-grid">
        <label class="character-field"><span>核心特质</span><textarea name="persona_traits" rows="3" maxlength="4000" placeholder="每行写一项特质">${escapeHtml(persona.traits)}</textarea></label>
        <label class="character-field"><span>与用户关系</span><textarea name="persona_relationship" rows="3" maxlength="2000" placeholder="例如：长期合作的伙伴">${escapeHtml(persona.relationship)}</textarea></label>
        <label class="character-field"><span>说话风格</span><textarea name="persona_speaking_style" rows="3" maxlength="3000" placeholder="例如：自然、口语化、少用套话">${escapeHtml(persona.speakingStyle)}</textarea></label>
        <label class="character-field"><span>行为习惯</span><textarea name="persona_behavior" rows="3" maxlength="3000" placeholder="描述角色通常如何回应">${escapeHtml(persona.behavior)}</textarea></label>
        <label class="character-field character-field-wide"><span>边界 / 禁忌</span><textarea name="persona_boundaries" rows="3" maxlength="3000" placeholder="描述不应做或不应说的内容">${escapeHtml(persona.boundaries)}</textarea></label>
        <label class="character-field"><span>回答长度</span><select name="persona_response_length"><option value="concise" ${persona.responseLength === "concise" ? "selected" : ""}>简洁</option><option value="balanced" ${persona.responseLength === "balanced" ? "selected" : ""}>平衡</option><option value="detailed" ${persona.responseLength === "detailed" ? "selected" : ""}>详细</option></select></label>
        <label class="character-field character-field-wide"><span>系统提示词</span><textarea name="system_prompt" rows="4" maxlength="20000" placeholder="补充需要长期遵循的指令">${escapeHtml(persona.systemPrompt)}</textarea></label>
        <label class="character-field character-field-wide"><span>首次问候</span><textarea name="greeting" rows="2" maxlength="2000" placeholder="新会话为空时显示，可选">${escapeHtml(persona.greeting)}</textarea></label>
      </div></div>
    </details>
    <details class="character-settings-group" data-character-section="model">
      <summary><span>高级设置</span><small>模型表现 · ${escapeHtml(avatarPresentationSummary(presentation))}</small></summary>
      <div class="character-settings-body"><section class="character-settings-subsection"><div class="character-settings-subsection-heading"><strong>模型表现</strong><small>只影响当前角色的 Avatar 渲染，不修改模型文件。</small></div><div class="character-settings-grid">
        <label class="character-field"><span>Avatar 位置</span><select name="avatar_position"><option value="left" ${presentation.position === "left" ? "selected" : ""}>左侧</option><option value="center" ${presentation.position === "center" ? "selected" : ""}>居中</option><option value="right" ${presentation.position === "right" ? "selected" : ""}>右侧</option></select></label>
        <label class="character-field"><span>透明度 <output id="avatar-opacity-value">${presentation.opacity.toFixed(2)}</output></span><input name="avatar_opacity" type="range" min="0" max="1" step="0.05" value="${presentation.opacity}" data-range-output="avatar-opacity-value" /></label>
        <label class="character-field"><span>缩放 <output id="avatar-scale-value">${presentation.scale.toFixed(2)}</output></span><input name="avatar_scale" type="range" min="0.5" max="2.5" step="0.05" value="${presentation.scale}" data-range-output="avatar-scale-value" /></label>
        <div class="character-field character-field-toggle"><span>自然站姿</span><label class="toggle-control"><input name="avatar_natural_pose" type="checkbox" ${presentation.naturalPose ? "checked" : ""} /><span>运行时将 T 姿态调整为放松站姿</span></label></div>
        <div class="character-field character-field-toggle"><span>视线跟随</span><label class="toggle-control"><input name="avatar_look_at_enabled" type="checkbox" ${presentation.lookAtEnabled ? "checked" : ""} /><span>眼睛跟随 Avatar 舞台，缺少 LookAt 时安全降级</span></label></div>
        <label class="character-field"><span>视线强度 <output id="avatar-look-at-strength-value">${presentation.lookAtStrength.toFixed(2)}</output></span><input name="avatar_look_at_strength" type="range" min="0" max="1" step="0.05" value="${presentation.lookAtStrength}" data-range-output="avatar-look-at-strength-value" /></label>
        <div class="character-field character-field-toggle"><span>头部跟随</span><label class="toggle-control"><input name="avatar_head_follow_enabled" type="checkbox" ${presentation.headFollowEnabled ? "checked" : ""} /><span>头颈慢速小幅跟随，待机时保留呼吸动作</span></label></div>
        <label class="character-field"><span>头部强度 <output id="avatar-head-follow-strength-value">${presentation.headFollowStrength.toFixed(2)}</output></span><input name="avatar_head_follow_strength" type="range" min="0" max="1" step="0.05" value="${presentation.headFollowStrength}" data-range-output="avatar-head-follow-strength-value" /></label>
        <div class="character-field character-field-toggle"><span>待机动作</span><label class="toggle-control"><input name="avatar_idle_motion" type="checkbox" ${presentation.idleMotion ? "checked" : ""} /><span>呼吸、轻微摆动和眨眼（默认开启）</span></label></div>
        <div class="character-field character-field-toggle"><span>自动旋转</span><label class="toggle-control"><input name="avatar_auto_rotate" type="checkbox" ${presentation.autoRotate ? "checked" : ""} /><span>中心原地缓慢转身（默认关闭）</span></label></div>
        <label class="character-field"><span>旋转速度 <output id="avatar-rotation-speed-value">${presentation.rotationSpeed.toFixed(2)}</output></span><input name="avatar_rotation_speed" type="range" min="0.05" max="0.4" step="0.01" value="${presentation.rotationSpeed}" data-range-output="avatar-rotation-speed-value" /></label>
      </div></section></div>
    </details>
    <button class="small-button" type="submit" ${state.characterBusy ? "disabled" : ""}>${state.characterBusy ? "保存中" : "保存角色配置"}</button>
  </form></section>`;
}

function renderAvatarLibrary() {
  const notice = state.avatarNotice ? `<div class="avatar-notice" role="status">${escapeHtml(state.avatarNotice)}</div>` : "";
  const rows = state.avatarModels.length ? state.avatarModels.map((model) => {
    const bindings = state.characters.filter((character) => character.config?.avatar_model_id === model.id);
    const bindingText = bindings.length ? ` · 已绑定：${bindings.map((character) => character.name).join("、")}` : "";
    const boundToCurrent = currentCharacter().config?.avatar_model_id === model.id;
    const bindingHint = bindings.length ? `<small class="avatar-model-binding-hint">${boundToCurrent ? "当前角色已绑定" : `已绑定到：${escapeHtml(bindings.map((character) => character.name).join("、"))}`}</small>` : "";
    const availability = model.metadata?.availability === "available" ? "文件可用" : "文件状态待刷新";
    const refreshing = state.avatarBusy === `refresh:${model.id}`;
    const inspecting = state.avatarBusy === `inspect:${model.id}`;
    const unregistering = state.avatarBusy === `unregister:${model.id}`;
    const bindingAction = boundToCurrent
      ? `<button class="small-button" data-avatar-clear="${escapeHtml(model.id)}" ${refreshing || unregistering ? "disabled" : ""}>解除当前角色绑定</button>`
      : `<button class="small-button" data-avatar-select="${escapeHtml(model.id)}" ${refreshing || unregistering ? "disabled" : ""}>绑定当前角色</button>`;
    const managed = model.metadata?.managed_directory === "assets/avatars" || model.metadata?.auto_discovered || model.metadata?.bundled;
    const removeLabel = managed ? "忽略" : "移除登记";
    const inspection = state.avatarInspections[model.id];
     return `<article class="avatar-model-row"><div class="avatar-model-type">${escapeHtml(model.kind.toUpperCase())}</div><div class="avatar-model-info"><strong>${escapeHtml(model.name)}</strong><small>${escapeHtml(model.path)} · ${formatBytes(model.size_bytes)} · ${availability}${escapeHtml(bindingText)}</small>${bindingHint}${inspection ? renderAvatarInspection(inspection) : ""}</div><div class="avatar-model-actions">${bindingAction}<button class="outline-button" data-avatar-inspect="${escapeHtml(model.id)}" title="检查模型清单引用和文件完整性" ${inspecting || refreshing || unregistering ? "disabled" : ""}>${inspecting ? "检查中" : "检查"}</button><button class="outline-button" data-avatar-refresh="${escapeHtml(model.id)}" title="重新检查文件是否存在、大小和修改时间" ${refreshing || unregistering || inspecting ? "disabled" : ""}>${refreshing ? "刷新中" : "刷新"}</button><button class="ghost-button" data-avatar-unregister="${escapeHtml(model.id)}" title="${managed ? "从自动扫描中忽略，不删除原文件" : "移除登记，不删除原文件"}" ${refreshing || unregistering || inspecting ? "disabled" : ""}>${unregistering ? "处理中" : removeLabel}</button></div></article>`;
  }).join("") : `<div class="empty-panel">还没有登记模型。导入只登记元数据，不执行模型文件。</div>`;
  const availableIgnored = state.avatarIgnored.filter((model) => model.available);
  const missingIgnoredCount = state.avatarIgnored.filter((model) => !model.available).length;
  const ignoredRows = availableIgnored.length ? availableIgnored.map((model) => {
    const busy = state.avatarBusy === `restore:${model.path}`;
    return `<article class="avatar-model-row avatar-ignored-row"><div class="avatar-model-type">${escapeHtml(model.kind.toUpperCase())}</div><div class="avatar-model-info"><strong>${escapeHtml(model.name)}</strong><small>${escapeHtml(model.path)} · ${formatBytes(model.size_bytes)} · 文件可用</small><small class="avatar-model-binding-hint">已忽略自动扫描；原文件未删除</small></div><div class="avatar-model-actions"><button class="small-button" data-avatar-restore="${escapeHtml(model.path)}" ${busy ? "disabled" : ""}>${busy ? "恢复中" : "恢复登记"}</button></div></article>`;
  }).join("") : `<div class="empty-panel">当前没有可恢复的已忽略模型。</div>`;
  const missingNotice = missingIgnoredCount ? `<div class="avatar-audit-summary" role="status"><span>有 ${missingIgnoredCount} 条失效忽略记录，路径当前不存在或不可访问，未确认模型已被删除。</span><button class="link-button" type="button" data-page="Developer">在开发者页审计 ↗</button></div>` : "";
  return `<section class="avatar-library"><div class="avatar-library-heading"><div><span class="eyebrow">AVATAR ASSETS</span><strong>本地模型</strong><small>VRM 可直接在 Sumika 中渲染。放入 assets/avatars 后可扫描登记；桌面版选择模型文件会打开系统对话框，浏览器预览模式需粘贴绝对路径。</small></div><div class="avatar-library-actions"><button class="outline-button" id="discover-avatar-assets" title="扫描仓库 assets/avatars 中的新模型" ${state.avatarBusy === "discover" ? "disabled" : ""}>${state.avatarBusy === "discover" ? "扫描中" : "扫描内置目录"}</button><button class="outline-button" id="import-avatar">选择模型文件</button></div></div>${notice}<div class="avatar-model-list">${rows}</div><section class="avatar-ignored"><div class="avatar-library-heading"><div><span class="eyebrow">IGNORED ASSETS</span><strong>已忽略模型</strong><small>仅显示当前仍可访问的受管模型；恢复登记不会自动绑定当前角色。</small></div></div>${missingNotice}<div class="avatar-model-list">${ignoredRows}</div></section></section>`;
}

function renderAvatarAssetAudit() {
  const missing = state.avatarIgnored.filter((model) => !model.available);
  const availableCount = state.avatarIgnored.filter((model) => model.available).length;
  const notice = state.avatarBusy?.startsWith("clear-ignored:") ? "清除中" : "";
  const rows = missing.length ? missing.map((model) => {
    const busy = state.avatarBusy === `clear-ignored:${model.path}`;
    const reason = model.reason === "missing_or_inaccessible" ? "路径当前不存在或不可访问" : (model.reason || "缺少可恢复文件");
    return `<article class="avatar-audit-row"><div class="avatar-model-type">${escapeHtml(String(model.last_known_kind || model.kind).toUpperCase())}</div><div class="avatar-model-info"><strong>${escapeHtml(model.name)}</strong><small>${escapeHtml(model.path)}</small><small class="avatar-audit-reason">${escapeHtml(reason)} · 忽略墓碑仍会阻止自动登记</small></div><button class="ghost-button" type="button" data-avatar-ignored-clear="${escapeHtml(model.path)}" ${busy ? "disabled" : ""}>${busy ? "清除中" : "清除忽略记录"}</button></article>`;
  }).join("") : `<div class="empty-column">没有缺失的忽略墓碑。</div>`;
  return `<section class="dev-panel avatar-audit-panel"><div class="panel-heading"><div><strong>Avatar 资产审计</strong><small>缺失记录只保留路径墓碑，不代表已确认删除。清除仅修改本机元数据，不删除任何文件。</small></div><span class="muted-text">可用忽略 ${availableCount} 条</span></div>${notice ? `<div class="avatar-notice" role="status">${notice}</div>` : ""}<div class="avatar-audit-list">${rows}</div></section>`;
}

function renderAvatarInspection(inspection) {
  const statusLabel = ({ ready: "正常", warning: "有警告", error: "有错误" })[inspection.status] || inspection.status || "未知";
  const references = Array.isArray(inspection.referenced_files) ? inspection.referenced_files.length : 0;
  const details = [...(inspection.errors || []).slice(0, 2), ...(inspection.warnings || []).slice(0, 2)];
  const detailText = details.length ? ` · ${details.map((item) => escapeHtml(item)).join("；")}` : "";
  return `<div class="avatar-inspection" data-avatar-inspection><small>清单检查：${statusLabel} · 引用 ${references} 个文件${detailText}</small></div>`;
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderModules() {
  const modules = state.modules;
  const notices = [state.moduleNotice, state.providerNotice].filter(Boolean).map((notice) => `<div class="module-notice" role="status">${escapeHtml(notice)}</div>`).join("");
  const body = modules.length
    ? `${renderToolRuntime()}${renderVisionRuntime()}${renderAudioRuntime()}<div class="module-grid">${modules.map(renderModuleCard).join("")}</div>`
    : `<div class="empty-panel">核心未连接，模块目录暂不可用。启动核心后刷新此页。</div>`;
  return renderPageFrame("模块", "每个模块都有可替换实现。连接档案可保存、测试并随时切换。", `${notices}${body}${renderProviderDrawer()}`);
}

function renderToolRuntime() {
  const module = state.modules.find((item) => item.id === "tools");
  const configured = Boolean(module?.enabled && module?.implementation_id === "external-process" && module?.config?.executable);
  const notice = state.toolNotice ? `<div class="tool-notice" role="status">${escapeHtml(state.toolNotice)}</div>` : "";
  const status = !module?.enabled ? "模块未启用" : module.implementation_id !== "external-process" ? "未选择外部进程实现" : module.config?.executable ? "已配置，等待显式调用" : "等待填写可执行文件路径";
  return `<section class="tool-runtime-panel"><div class="tool-runtime-heading"><div><span class="eyebrow">EXTERNAL TOOLS</span><strong>外部软件调用</strong><small>仅启动配置的绝对路径，不经过 shell；每次调用都要求明确批准，审计事件只保留哈希、大小和状态。</small></div><button class="outline-button" id="run-tool-test" type="button" ${!configured || state.toolBusy ? "disabled" : ""}>${state.toolBusy ? "调用中" : "审批并测试"}</button></div>${notice}<div class="tool-runtime-status"><span class="module-status ${configured ? "available" : "unconfigured"}">${escapeHtml(status)}</span><code>${escapeHtml(module?.config?.executable || "未配置路径")}</code></div></section>`;
}

function renderVisionRuntime() {
  const status = state.visionStatus || fallbackVisionStatus;
  const permissions = status.permissions || [];
  const sources = status.sources || [];
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
  return `<section class="vision-runtime-panel"><div class="vision-runtime-heading"><div><span class="eyebrow">VISION RUNTIME</span><strong>视觉权限与运行状态</strong><small>核心不负责抓取设备。桌面桥接只有在用户授权并启动来源后，才可提交一次内存图像；原始数据和摘要都不会自动写入事件日志。</small></div><button class="outline-button" id="refresh-vision-status" type="button">刷新</button></div>${notice}<div class="vision-runtime-grid"><div><div class="audio-section-label">来源权限</div>${permissionRows || `<div class="empty-column">暂无权限项</div>`}</div><div><div class="audio-section-label">来源运行</div>${sourceRows || `<div class="empty-column">暂无视觉来源</div>`}</div></div></section>`;
}

function visionPermissionLabel(permission) {
  return ({ "screen.read": "屏幕读取", "camera.read": "摄像头读取" })[permission] || permission;
}

function visionPermissionStateLabel(value) {
  return ({ unknown: "尚未决定", granted: "已允许", denied: "已拒绝" })[value] || value || "未知";
}

function visionSourceLabel(source) {
  return ({ screen: "屏幕", camera: "摄像头" })[source] || source;
}

function visionStateLabel(value) {
  return ({ disabled: "模块未启用", unconfigured: "未选择实现", permission_required: "等待权限", ready: "已就绪", running: "运行中", available: "可用", error: "错误" })[value] || value || "未知";
}

function renderAudioRuntime() {
  const status = state.audioStatus || fallbackAudioStatus;
  const permissions = status.permissions || [];
  const capabilities = status.capabilities || [];
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
  return `<section class="audio-runtime-panel"><div class="audio-runtime-heading"><div><span class="eyebrow">AUDIO RUNTIME</span><strong>语音权限与运行状态</strong><small>只有显式授权并启动后，选定 provider 才会收到音频。原始数据仅在调用期间保留在内存。</small></div><button class="outline-button" id="refresh-audio-status" type="button">刷新</button></div>${notice}<div class="audio-runtime-grid"><div><div class="audio-section-label">设备权限</div>${permissionRows || `<div class="empty-column">暂无权限项</div>`}</div><div><div class="audio-section-label">能力运行</div>${capabilityRows || `<div class="empty-column">暂无音频模块</div>`}</div></div></section>`;
}

function audioPermissionLabel(permission) {
  return ({ microphone: "麦克风", audio_output: "音频输出" })[permission] || permission;
}

function audioPermissionStateLabel(state) {
  return ({ unknown: "尚未决定", granted: "已允许", denied: "已拒绝" })[state] || state || "未知";
}

function audioCapabilityLabel(capability) {
  return ({ asr: "语音识别（ASR）", tts: "语音合成（TTS）", vad: "语音活动检测（VAD）" })[capability] || capability;
}

function audioCapabilityStateLabel(state) {
  return ({ disabled: "模块未启用", unconfigured: "未选择实现", permission_required: "等待权限", ready: "已就绪", running: "运行中", available: "可用", error: "错误" })[state] || state || "未知";
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
  const profiles = state.providerProfiles.filter((profile) => !profile.archived_at);
  const current = activeProviderProfile() || module.profile || profiles[0] || null;
  const available = profiles.filter((profile) => profile.status === "available");
  const pending = profiles.filter((profile) => profile.status !== "available");
  const rows = [
    available.length ? `<div class="provider-picker-group"><span>可用连接</span>${available.map(renderProviderProfileRow).join("")}</div>` : "",
    pending.length ? `<div class="provider-picker-group"><span>草稿与未就绪</span>${pending.map(renderProviderProfileRow).join("")}</div>` : "",
  ].join("");
  const summary = current
    ? `<span><strong>${escapeHtml(current.name)}</strong><small>${escapeHtml(current.config?.model || "未填写模型")} · ${providerProfileStatusLabel(current.status)}</small></span>`
    : `<span><strong>尚未配置</strong><small>创建一个真实连接后启用</small></span>`;
  return `<article class="module-card llm-module-card ${module.enabled ? "" : "module-disabled"}">
    <div class="module-card-top"><span class="module-icon">LLM</span><span class="module-status ${escapeHtml(module.status)}">${moduleStatusLabel(module)}</span><button class="module-toggle" type="button" role="switch" aria-checked="${module.enabled}" aria-label="切换 ${escapeHtml(module.name)}" data-module-toggle="${escapeHtml(module.id)}" ${busy || (!module.enabled && current?.status !== "available") ? "disabled" : ""}><span class="switch ${module.enabled ? "on" : "off"}"></span></button></div>
    <strong>${escapeHtml(module.name)}</strong><p>${escapeHtml(module.description)}</p>
    <details class="provider-picker"><summary><span class="provider-picker-label">实现方式</span>${summary}<span class="provider-picker-chevron" aria-hidden="true">⌄</span></summary><div class="provider-picker-menu">${rows || `<div class="provider-picker-empty">还没有保存的连接</div>`}<button class="provider-add-row" type="button" data-provider-new><span aria-hidden="true">＋</span>自定义连接</button></div></details>
    <div class="llm-profile-meta"><span>${escapeHtml(current?.resolved_processing_location === "cloud" ? "云端" : "本地")}</span><code>${escapeHtml(current?.config?.active_base_url || "未配置端点")}</code>${current ? `<button class="ghost-button" type="button" data-provider-edit="${escapeHtml(current.id)}">编辑</button>` : ""}</div>
    <div class="module-card-meta"><span>权限</span><small>密钥使用系统安全凭据存储；当前 Windows 已实现</small></div>
  </article>`;
}

function renderProviderProfileRow(profile) {
  const active = activeProviderProfile()?.id === profile.id;
  const status = providerProfileStatusLabel(profile.status);
  return `<div class="provider-profile-row ${active ? "active" : ""}"><button type="button" data-provider-select="${escapeHtml(profile.id)}" ${state.providerBusy ? "disabled" : ""}><span><strong>${escapeHtml(profile.name)}</strong><small>${escapeHtml(profile.config?.model || "未填写模型")} · ${escapeHtml(status)}</small></span>${active ? `<span class="provider-active-mark">当前</span>` : ""}</button><button class="icon-button provider-row-edit" type="button" data-provider-edit="${escapeHtml(profile.id)}" title="编辑连接" aria-label="编辑 ${escapeHtml(profile.name)}">⋯</button></div>`;
}

function providerProfileStatusLabel(status) {
  return ({ available: "可用", unavailable: "未就绪", draft: "草稿", archived: "已归档" })[status] || status || "未知";
}

function renderProviderDrawer() {
  if (!state.providerDrawerOpen) return "";
  const profile = state.providerProfiles.find((item) => item.id === state.providerDrawerProfileId) || null;
  const config = profile?.config || {};
  const templates = state.providerTemplates.map((template) => `<option value="${escapeHtml(template.id)}" ${template.id === (profile?.template_id || "openai-compatible") ? "selected" : ""}>${escapeHtml(template.name)}</option>`).join("");
  const manual = `<form id="provider-profile-form" class="provider-drawer-form" data-profile-id="${escapeHtml(profile?.id || "")}">
    <div class="provider-form-grid"><label><span>连接名称</span><input name="name" value="${escapeHtml(profile?.name || "")}" maxlength="80" required autofocus /></label><label><span>连接模板</span><select name="template_id" id="provider-template-select">${templates}</select></label></div>
    <label><span>当前 Base URL</span><input name="active_base_url" type="url" value="${escapeHtml(config.active_base_url || "")}" placeholder="https://api.example.com/v1" required /></label>
    <label><span>备用端点（每行一个）</span><textarea name="alternate_urls" rows="3" placeholder="只保存，不自动故障转移">${escapeHtml((config.base_urls || []).filter((value) => value !== config.active_base_url).join("\n"))}</textarea></label>
    <div class="provider-form-grid"><label><span>模型</span><input name="model" value="${escapeHtml(config.model || "")}" placeholder="模型 ID" required /></label><label><span>处理位置</span><select name="processing_location"><option value="auto" ${profile?.processing_location === "auto" ? "selected" : ""}>自动判断</option><option value="local" ${profile?.processing_location === "local" ? "selected" : ""}>本地处理</option><option value="cloud" ${profile?.processing_location === "cloud" ? "selected" : ""}>云端处理</option></select></label></div>
    <label><span>API Key</span><input name="api_key" type="password" value="" autocomplete="new-password" placeholder="${profile?.has_secrets ? "已安全保存，留空保持不变" : "本地免鉴权服务可以留空"}" /></label>
    ${profile?.has_secrets ? `<label class="provider-clear-secret"><input name="clear_api_key" type="checkbox" /><span>清除已保存的 API Key</span></label>` : ""}
    <details class="provider-advanced"><summary>高级设置</summary><div><div class="provider-form-grid"><label><span>超时（秒）</span><input name="timeout" type="number" min="1" max="300" value="${escapeHtml(config.timeout || 60)}" /></label><label><span>Organization</span><input name="organization" value="${escapeHtml(config.organization || "")}" /></label></div><label><span>Project</span><input name="project" value="${escapeHtml(config.project || "")}" /></label><label><span>额外请求头（JSON）</span><textarea name="headers" rows="4">${escapeHtml(JSON.stringify(config.headers || {}, null, 2))}</textarea></label><label><span>声明式用量查询（JSON，可留空）</span><textarea name="usage_query" rows="4" placeholder='{"enabled":false,"method":"GET","url":"{{baseUrl}}/usage","fields":{}}'>${escapeHtml(config.usage_query ? JSON.stringify(config.usage_query, null, 2) : "")}</textarea></label></div></details>
    <div class="provider-drawer-actions">${profile && !profile.active ? `<button class="ghost-button danger-text" type="button" data-provider-archive="${escapeHtml(profile.id)}">归档</button>` : ""}<span></span><button class="ghost-button" type="submit" data-provider-action="save" ${state.providerBusy ? "disabled" : ""}>保存草稿</button><button class="outline-button" type="submit" data-provider-action="test" ${state.providerBusy ? "disabled" : ""}>测试连接</button><button class="primary-button" type="submit" data-provider-action="activate" ${state.providerBusy ? "disabled" : ""}>保存并启用</button></div>
  </form>`;
  const importer = `<section class="provider-import-pane"><label><span>粘贴配置</span><textarea id="provider-import-raw" rows="9" placeholder="ccswitch://v1/import?... 或 Sumika JSON / OpenAI JSON / Codex TOML">${escapeHtml(state.providerImportRaw)}</textarea></label><div class="provider-import-tools"><input id="provider-import-file" type="file" accept=".json,.toml,.txt" /><button class="outline-button" type="button" id="provider-import-preview" ${state.providerBusy ? "disabled" : ""}>预览导入</button></div><p>导入只生成 Sumika 草稿档案，不注册系统协议，也不会执行 JavaScript。</p>${renderProviderImportPreview()}</section>`;
  return `<div class="provider-drawer-backdrop" data-provider-drawer-close></div><aside class="provider-drawer" role="dialog" aria-modal="true" aria-labelledby="provider-drawer-title"><header><div><span class="eyebrow">PROVIDER PROFILE</span><h2 id="provider-drawer-title">${profile ? "编辑连接" : "自定义连接"}</h2></div><button class="icon-button" type="button" data-provider-drawer-close aria-label="关闭配置抽屉" title="关闭">×</button></header><div class="provider-drawer-tabs" role="tablist"><button type="button" role="tab" aria-selected="${state.providerDrawerMode === "manual"}" data-provider-drawer-mode="manual">手动配置</button><button type="button" role="tab" aria-selected="${state.providerDrawerMode === "import"}" data-provider-drawer-mode="import">导入配置</button></div><div class="provider-drawer-body">${state.providerDrawerMode === "import" ? importer : manual}</div></aside>`;
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

function moduleStatusLabel(module) {
  if (module.status === "disabled") return "未启用";
  if (module.status === "unconfigured") return "待配置";
  if (module.status === "preview") return "预览";
  if (module.status === "available") return "可用";
  if (module.status === "error") return "未就绪";
  return "就绪";
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

function renderTasks() {
  const tasks = state.tasks;
  const columns = [
    ["running", "运行中", ["pending", "running"]],
    ["waiting", "等待批准", ["waiting_approval"]],
    ["completed", "已完成", ["completed"]],
    ["attention", "失败 / 暂停", ["failed", "paused", "cancelled"]],
  ];
  const notice = state.taskNotice ? `<div class="task-notice" role="status">${escapeHtml(state.taskNotice)}</div>` : "";
  const createButton = `<div class="task-toolbar"><span>任务状态、预算和产物均保存在本机事件记录中。</span><button class="outline-button" id="add-task">创建任务</button></div>`;
  const board = columns.map(([id, title, statuses]) => {
    const items = tasks.filter((task) => statuses.includes(task.status));
    return `<section class="task-column" data-task-column="${id}"><div class="column-title"><span>${title}</span><b>${items.length}</b></div>${items.length ? items.map(renderTaskCard).join("") : `<div class="empty-column">暂无任务</div>`}</section>`;
  }).join("");
  return renderPageFrame("任务中心", "主动任务、模块测试和未来自修改实验都在这里审计。", `${notice}${createButton}<div class="task-board">${board}</div>`);
}

function renderTaskCard(task) {
  const expanded = state.selectedTaskId === task.id;
  const progress = Math.round((Number(task.progress) || 0) * 100);
  const busy = state.taskBusy === task.id;
  return `<article class="task-large-card ${expanded ? "task-expanded" : ""}">
    <button class="task-open" type="button" data-task-open="${escapeHtml(task.id)}" aria-expanded="${expanded}"><div class="task-large-head"><span class="task-status ${taskStatusClass(task.status)}">${taskStatusIcon(task.status)}</span><div><strong>${escapeHtml(task.title)}</strong><small>${escapeHtml(task.id)} · ${taskAutonomyLabel(task.autonomy_level)}</small></div><span class="task-chevron">${expanded ? "⌄" : "›"}</span></div></button>
    <div class="task-progress"><span style="width:${progress}%"></span></div><div class="task-large-foot"><span>${taskStatusLabel(task.status)} · ${progress}%</span><span>${formatBudget(task.budget)}</span></div>
    ${expanded ? renderTaskDetail(task, busy) : ""}
  </article>`;
}

function renderTaskDetail(task, busy) {
  const permissions = task.permissions?.length ? task.permissions.join(" · ") : "无额外权限";
  const logs = task.logs?.length ? task.logs.slice(-4).map((log) => `<li>${escapeHtml(log.message || JSON.stringify(log))}</li>`).join("") : "<li>暂无日志</li>";
  const artifacts = task.artifacts?.length ? task.artifacts.map((artifact) => `<li>${escapeHtml(artifact.name || artifact.path || JSON.stringify(artifact))}</li>`).join("") : "<li>暂无产物</li>";
  return `<div class="task-detail"><div class="task-detail-grid"><div><span>自治等级</span><strong>${taskAutonomyLabel(task.autonomy_level)}</strong></div><div><span>权限</span><strong>${escapeHtml(permissions)}</strong></div><div><span>预算</span><strong>${escapeHtml(formatBudget(task.budget))}</strong></div><div><span>结果</span><strong>${escapeHtml(task.result?.summary || "暂无")}</strong></div></div><div class="task-detail-lists"><div><span>最近日志</span><ul>${logs}</ul></div><div><span>产物 / diff</span><ul>${artifacts}</ul></div></div>${renderTaskActions(task, busy)}</div>`;
}

function renderTaskActions(task, busy) {
  if (task.id === "core-service") return "";
  const actions = [];
  if (["pending", "running"].includes(task.status)) actions.push(["request", "请求批准", false]);
  if (task.status === "waiting_approval" || task.status === "paused") actions.push(["approve", "批准并运行", true]);
  if (["pending", "running", "waiting_approval", "paused"].includes(task.status)) actions.push(["paused", "暂停"]);
  if (!["completed", "failed", "cancelled"].includes(task.status)) actions.push(["cancelled", "取消"]);
  if (!actions.length) return "";
  return `<div class="task-actions">${actions.map(([action, label, approved]) => action === "request" || action === "approve" ? `<button class="small-button" type="button" data-task-run="${escapeHtml(task.id)}" data-task-approved="${approved}" ${busy ? "disabled" : ""}>${label}</button>` : `<button class="small-button" type="button" data-task-status="${action}" data-task-id="${escapeHtml(task.id)}" ${busy ? "disabled" : ""}>${label}</button>`).join("")}</div>`;
}

function taskStatusLabel(status) {
  return ({ pending: "排队", running: "运行中", waiting_approval: "等待批准", paused: "已暂停", completed: "已完成", failed: "失败", cancelled: "已取消" })[status] || status;
}

function taskStatusClass(status) {
  return ({ pending: "pending", running: "running", waiting_approval: "waiting", paused: "paused", completed: "done", failed: "failed", cancelled: "cancelled" })[status] || "pending";
}

function taskStatusIcon(status) {
  return ({ pending: "·", running: "◌", waiting_approval: "!", paused: "Ⅱ", completed: "✓", failed: "×", cancelled: "–" })[status] || "·";
}

function taskAutonomyLabel(level) {
  return ({ L0: "L0 关闭主动性", L1: "L1 提出建议", L2: "L2 用户批准", L3: "L3 隔离实验" })[level] || level || "L0";
}

function formatBudget(budget = {}) {
  const tokens = Number(budget.token_limit) || 0;
  const seconds = Number(budget.time_limit_seconds) || 0;
  if (!tokens && !seconds) return "无预算消耗";
  return `${tokens ? `${tokens} tokens` : "不限 token"}${seconds ? ` · ${seconds}s` : ""}`;
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

function notificationFromEvent(event) {
  if (!event || typeof event !== "object") return null;
  const type = String(event.event_type || "");
  const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
  const task = payload.task && typeof payload.task === "object" ? payload.task : null;
  if (type === "snapshot.restore.failed") return { severity: "danger", title: "快照恢复失败", detail: "恢复没有完成，当前数据未被这次操作覆盖。", event_type: type, timestamp: event.timestamp, page: "Settings" };
  if (type === "task.failed" || task?.status === "failed") return { severity: "danger", title: task?.title || "任务执行失败", detail: "任务已停止，请查看任务日志和产物。", event_type: type, timestamp: event.timestamp, page: "Tasks" };
  if (type === "provider.status" && payload.status === "error") return { severity: "danger", title: "Provider 运行失败", detail: `Provider ${payload.provider_id || "unknown"} 返回错误状态。`, event_type: type, timestamp: event.timestamp, page: "Developer" };
  if (type === "audio.permission.changed" || type === "vision.permission.changed") return { severity: "warning", title: "权限状态已改变", detail: `${payload.permission_id || "采集权限"} 当前状态：${payload.state || "unknown"}。`, event_type: type, timestamp: event.timestamp, page: "Settings" };
  if (task?.status === "waiting_approval") return { severity: "warning", title: `等待批准：${task.title || "任务"}`, detail: "任务需要用户批准后才会继续运行。", event_type: type, timestamp: event.timestamp, page: "Tasks" };
  if (type === "snapshot.restored") return { severity: "info", title: "快照已恢复", detail: "恢复前快照已自动保存，可在设置中回滚。", event_type: type, timestamp: event.timestamp, page: "Settings" };
  if (type === "snapshot.imported") return { severity: "info", title: "快照已导入", detail: "导入内容已保存为待审核快照，尚未改变当前数据。", event_type: type, timestamp: event.timestamp, page: "Settings" };
  if (type === "tool.completed" || type === "tool.failed") return { severity: "info", title: "外部工具调用完成", detail: "调用结果已记录在开发者审计中。", event_type: type, timestamp: event.timestamp, page: "Developer" };
  return null;
}

function renderSettings() {
  return renderPageFrame("设置", "参考分区设置和 schema-driven form，复杂配置按需展开。", `<div class="settings-layout"><div class="settings-nav"><button class="settings-item active">常规</button><button class="settings-item">隐私与权限</button><button class="settings-item active">数据与备份</button><button class="settings-item">快捷键</button><button class="settings-item">外观与 Avatar</button></div><div class="settings-content"><section class="settings-section"><div class="setting-title"><div><strong>本地运行</strong><small>核心服务默认只监听 localhost</small></div><span class="switch on"></span></div><div class="setting-title"><div><strong>长期记忆</strong><small>记忆模块默认关闭，按类别授权</small></div><span class="switch off"></span></div><div class="setting-title"><div><strong>语音输出</strong><small>按前台应用和专注模式自动降级</small></div><span class="switch off"></span></div></section><section class="settings-section"><div class="section-label"><span>数据目录</span><button class="link-button" type="button">查看</button></div><div class="path-box">.sumika/ <span>本机加密备份 · 可选局域网副本</span></div></section>${renderSnapshotSettings()}</div></div>`);
}

function renderSnapshotSettings() {
  const notice = state.snapshotNotice ? `<div class="snapshot-notice" role="status">${escapeHtml(state.snapshotNotice)}</div>` : "";
  const busy = Boolean(state.snapshotBusy);
  const selected = state.snapshotDiff?.snapshot;
  const selectedDiff = state.snapshotDiff?.diff;
  const rows = state.snapshots.length ? state.snapshots.map((snapshot) => {
    const active = snapshot.id === state.selectedSnapshotId;
    const counts = Object.values(snapshot.table_counts || {}).reduce((total, value) => total + Number(value || 0), 0);
    return `<button class="snapshot-row ${active ? "active" : ""}" type="button" data-snapshot-select="${escapeHtml(snapshot.id)}"><span class="snapshot-icon">◫</span><span class="snapshot-row-main"><strong>${escapeHtml(snapshot.name)}</strong><small>${snapshotScopeLabel(snapshot.scope)}${snapshot.target_id ? ` · ${escapeHtml(snapshot.target_id)}` : ""} · ${formatDate(snapshot.created_at)}</small></span><span class="snapshot-row-meta">${counts} 条记录</span><span class="snapshot-chevron">›</span></button>`;
  }).join("") : `<div class="empty-panel">还没有命名快照</div>`;
  const diffPanel = selected && selectedDiff ? `<div class="snapshot-diff"><div class="snapshot-diff-heading"><div><span class="eyebrow">RESTORE REVIEW</span><strong>${escapeHtml(selected.name)}</strong><small>恢复前会自动生成同范围快照，事件审计不会被覆盖。</small></div><div class="snapshot-diff-actions"><button class="small-button" type="button" data-snapshot-export="${escapeHtml(selected.id)}" ${busy ? "disabled" : ""} title="导出未加密 JSON 快照包" aria-label="导出未加密 JSON 快照包">⇩ 导出</button><button class="small-button" type="button" data-snapshot-restore="${escapeHtml(selected.id)}" ${busy ? "disabled" : ""}>恢复此快照</button></div></div><div class="snapshot-diff-summary"><span class="${selectedDiff.changed ? "warn" : "ok"}">${selectedDiff.changed ? "检测到变更" : "当前已一致"}</span><span>${snapshotDiffCount(selectedDiff)} 个表有差异</span></div><div class="snapshot-diff-table">${selectedDiff.tables.map((table) => `<div class="snapshot-diff-row"><span>${snapshotTableLabel(table.table)}</span><span>新增 ${table.added} · 删除 ${table.removed} · 修改 ${table.changed}</span></div>`).join("")}</div></div>` : "";
  const scope = state.snapshotDraftScope || "system";
  const targetOptions = snapshotTargetOptions(scope);
  const targetControl = scope === "system" ? "" : `<select id="snapshot-target" aria-label="快照目标"><option value="">全部${snapshotScopeLabel(scope)}</option>${targetOptions.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === state.snapshotDraftTargetId ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}</select>`;
  return `<section class="settings-section snapshot-settings"><div class="snapshot-heading"><div><span class="eyebrow">DATA & BACKUPS</span><strong>命名快照</strong><small>会话、角色、模块和记忆分开保存；恢复前先查看差异。</small></div><div class="snapshot-create"><select id="snapshot-scope" aria-label="快照范围"><option value="system" ${scope === "system" ? "selected" : ""}>完整系统</option><option value="modules" ${scope === "modules" ? "selected" : ""}>模块设置</option><option value="characters" ${scope === "characters" ? "selected" : ""}>角色</option><option value="memories" ${scope === "memories" ? "selected" : ""}>记忆</option></select>${targetControl}<button class="outline-button" id="create-snapshot" type="button" ${busy ? "disabled" : ""}>创建快照</button><button class="outline-button" id="import-snapshot" type="button" ${busy ? "disabled" : ""} title="导入未加密 JSON 快照包" aria-label="导入未加密 JSON 快照包">⇧ 导入</button><input id="snapshot-file" type="file" accept="application/json,.json" hidden /></div></div>${notice}<div class="snapshot-list">${rows}</div>${diffPanel}</section>`;
}

function snapshotTargetOptions(scope) {
  if (scope === "modules") return state.modules.map((item) => ({ id: item.id, label: item.name || item.id }));
  if (scope === "characters") return state.characters.map((item) => ({ id: item.id, label: item.name || item.id }));
  if (scope === "memories") return state.memories.map((item) => ({ id: item.id, label: `${item.category || "记忆"} · ${(item.content || "").slice(0, 32)}` }));
  return [];
}

function snapshotScopeLabel(scope) {
  return ({ system: "完整系统", modules: "模块设置", characters: "角色", memories: "记忆" })[scope] || scope || "未知范围";
}

function snapshotTableLabel(table) {
  return ({ sessions: "会话", messages: "消息", characters: "角色", module_settings: "模块设置", provider_profiles: "Provider 档案", tasks: "任务", avatar_models: "Avatar 登记", audio_permissions: "音频权限", vision_permissions: "视觉权限", memories: "记忆" })[table] || table;
}

function snapshotDiffCount(diff) {
  return (diff?.tables || []).filter((table) => table.added || table.removed || table.changed).length;
}

function renderDeveloper() {
  const notice = state.pluginNotice ? `<div class="plugin-notice" role="status">${escapeHtml(state.pluginNotice)}</div>` : "";
  const providerNotice = state.providerNotice ? `<div class="plugin-notice" role="status">${escapeHtml(state.providerNotice)}</div>` : "";
  const pluginRows = state.plugins.length ? state.plugins.map(renderPluginRow).join("") : `<div class="empty-column">还没有扫描到本地 manifest</div>`;
  const pluginPanel = `<section class="dev-panel plugin-panel"><div class="panel-heading"><div><strong>本地插件 manifest</strong><small>只读取清单并等待批准；不会导入、启动代码或安装依赖。</small></div><button class="small-button" id="refresh-plugins" ${state.pluginBusy ? "disabled" : ""}>刷新</button></div><div class="plugin-scan-form"><input id="plugin-path" type="text" value="${escapeHtml(state.pluginPath)}" placeholder="插件目录或 manifest.json 的绝对路径" aria-label="插件目录或 manifest 路径" /><button class="outline-button" id="discover-plugins" ${state.pluginBusy ? "disabled" : ""}>扫描</button></div>${notice}<div class="plugin-list">${pluginRows}</div></section>`;
  const diagnostics = state.diagnostics;
  const diagnosticPanel = `<section class="dev-panel diagnostics-panel"><div class="panel-heading"><div><strong>核心诊断</strong><small>只显示运行元数据；详细运行线索写入本机日志，不包含聊天正文、密钥或原始媒体。</small></div><button class="small-button" id="refresh-diagnostics">刷新</button></div>${diagnostics ? `<div class="diagnostic-grid"><div><span>进程</span><strong>PID ${escapeHtml(diagnostics.pid)}</strong></div><div><span>运行时间</span><strong>${escapeHtml(formatDuration(diagnostics.uptime_seconds))}</strong></div><div><span>事件</span><strong>${escapeHtml(diagnostics.event_count)} 条</strong></div><div><span>模块 / Provider / Avatar</span><strong>${escapeHtml(diagnostics.module_count)} / ${escapeHtml(diagnostics.provider_count)} / ${escapeHtml(diagnostics.avatar_count)}</strong></div></div><div class="diagnostic-path"><span>数据目录</span><code>${escapeHtml(diagnostics.data_dir || "-")}</code><span>核心日志</span><code>${escapeHtml(diagnostics.log_path || "仅 stderr")}</code></div>` : `<div class="empty-column">诊断信息尚未加载</div>`}</section>`;
  const desktopStatus = state.desktopStatus;
  const desktopPanel = isDesktopShell ? `<section class="dev-panel desktop-status-panel" data-desktop-status><div class="panel-heading"><div><strong>桌面生命周期</strong><small>Rust 壳负责核心进程；异常退出会有限次退避重启。</small></div><button class="small-button" id="refresh-desktop-status">刷新</button></div>${desktopStatus ? `<div class="diagnostic-grid"><div><span>核心地址</span><strong>${escapeHtml(desktopStatus.host)}:${escapeHtml(desktopStatus.port)}</strong></div><div><span>Python PID</span><strong>${escapeHtml(desktopStatus.pid || "-")}</strong></div><div><span>状态</span><strong>${desktopStatus.running ? "运行中" : "已停止"}</strong></div><div><span>本次重启</span><strong>${escapeHtml(desktopStatus.restart_count)}</strong></div></div><div class="diagnostic-path"><span>桌面日志</span><code>${escapeHtml(desktopStatus.log_path || "-")}</code></div>` : `<div class="empty-column">桌面状态尚未加载</div>`}</section>` : "";
  const avatarAuditPanel = renderAvatarAssetAudit();
  const profileRows = state.providerProfiles.map((profile) => `<div class="provider-row"><span class="status-dot ${profile.status === "available" ? "online" : "offline"}"></span><div><strong>${escapeHtml(profile.name)}</strong><small>${escapeHtml(profile.adapter_id)} · ${escapeHtml(providerProfileStatusLabel(profile.status))}</small></div>${profile.status === "archived" ? `<button class="ghost-button" type="button" data-provider-restore="${escapeHtml(profile.id)}" ${state.providerBusy ? "disabled" : ""}>恢复</button>` : `<button class="ghost-button" type="button" data-provider-health="${escapeHtml(profile.id)}" ${state.providerBusy ? "disabled" : ""}>测试</button>`}</div>`).join("") || `<div class="empty-column">暂无 Provider 档案</div>`;
  return renderPageFrame("开发者", "查看 manifest、事件、健康检查和 provider 运行边界。", `<div class="developer-grid">${providerNotice}<section class="dev-panel"><div class="panel-heading"><strong>Provider 健康</strong><button class="small-button" id="refresh-health">刷新</button></div>${profileRows}</section>${renderCcsCompatibilityPanel()}${pluginPanel}${diagnosticPanel}${desktopPanel}${avatarAuditPanel}<section class="dev-panel"><div class="panel-heading"><strong>事件流</strong><span class="muted-text">${state.events.length} 条</span></div><div class="event-log">${state.events.slice(0, 12).map((event) => `<div class="log-row"><code>${escapeHtml(event.event_type)}</code><span>${escapeHtml(JSON.stringify(event.payload).slice(0, 100))}</span></div>`).join("") || `<div class="empty-column">暂无事件</div>`}</div></section></div>`);
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

function pluginStatusLabel(status) {
  return ({ discovered: "待批准", changed: "清单已变化", approved: "已批准", revoked: "已撤销", invalid: "无效" })[status] || status || "未知";
}

function renderPageFrame(title, description, content) {
  return `<section class="page-layout content-page"><div class="page-heading"><div><span class="eyebrow">SUMIKA CORE</span><h1>${title}</h1><p>${description}</p></div><button class="outline-button">查看文档 ↗</button></div>${content}</section>`;
}

function glyph(id) {
  return ({ Guide: "?", Chat: "◉", Characters: "◇", Modules: "▦", Tasks: "◌", History: "▤", Notifications: "♢", Settings: "⚙", Developer: "⌘" })[id] || "·";
}

function formatTime(value) {
  if (!value) return "刚刚";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "刚刚" : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function formatDate(value) {
  if (!value) return "刚刚";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "刚刚" : date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}

function formatDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return "-";
  if (value < 60) return `${value.toFixed(1)} 秒`;
  const minutes = Math.floor(value / 60);
  return `${minutes} 分 ${Math.floor(value % 60)} 秒`;
}

function bindEvents() {
  document.querySelectorAll("[data-page]").forEach((element) => element.addEventListener("click", () => {
    state.activePage = element.dataset.page;
    if (state.activePage === "Developer") void loadProviderProfiles(true, true);
    render();
  }));
  document.querySelector("#character-select")?.addEventListener("change", (event) => {
    state.selectedCharacter = event.target.value;
    state.sessionNotice = "";
    loadMessages();
    loadAvatarState();
    loadMemories();
  });
  document.querySelector("[data-avatar-toggle]")?.addEventListener("click", () => {
    state.avatarVisible = !state.avatarVisible;
    render();
  });
  document.querySelector("[data-overlay-open]")?.addEventListener("click", openDesktopOverlay);
  document.querySelector("[data-overlay-open-main]")?.addEventListener("click", openMainWindow);
  document.querySelector("[data-overlay-hide]")?.addEventListener("click", hideDesktopOverlay);
  document.querySelector("#toggle-inspector")?.addEventListener("click", () => {
    state.taskOpen = !state.taskOpen;
    render();
  });
  document.querySelector("#chat-form")?.addEventListener("submit", sendMessage);
  document.querySelector("#message-list")?.addEventListener("scroll", rememberChatScrollPreference, { passive: true });
  document.querySelector("#chat-input")?.addEventListener("input", (event) => {
    state.composerDraft = event.target.value;
  });
  document.querySelector("[data-audio-record]")?.addEventListener("click", toggleVoiceCapture);
  document.querySelector("#new-session")?.addEventListener("click", createSession);
  document.querySelectorAll("[data-session-select]").forEach((element) => element.addEventListener("click", () => {
    selectSession(element.dataset.sessionSelect);
  }));
  document.querySelectorAll("[data-character]").forEach((element) => element.addEventListener("click", () => {
    state.selectedCharacter = element.dataset.character;
    loadMessages();
    loadAvatarState();
    loadMemories();
  }));
  document.querySelector("#character-form")?.addEventListener("submit", saveCharacter);
  document.querySelectorAll("[data-range-output]").forEach((element) => element.addEventListener("input", () => {
    const output = document.querySelector(`#${element.dataset.rangeOutput}`);
    if (output) output.value = Number(element.value).toFixed(2);
  }));
  document.querySelector("#add-character")?.addEventListener("click", createCharacter);
  document.querySelector("#import-avatar")?.addEventListener("click", importAvatar);
  document.querySelector("#discover-avatar-assets")?.addEventListener("click", discoverAvatarAssets);
  document.querySelectorAll("[data-avatar-select]").forEach((element) => element.addEventListener("click", () => {
    selectAvatar(element.dataset.avatarSelect);
  }));
  document.querySelectorAll("[data-avatar-clear]").forEach((element) => element.addEventListener("click", () => {
    clearAvatar(element.dataset.avatarClear);
  }));
  document.querySelectorAll("[data-avatar-refresh]").forEach((element) => element.addEventListener("click", () => {
    refreshAvatar(element.dataset.avatarRefresh);
  }));
  document.querySelectorAll("[data-avatar-inspect]").forEach((element) => element.addEventListener("click", () => {
    inspectAvatar(element.dataset.avatarInspect);
  }));
  document.querySelectorAll("[data-avatar-unregister]").forEach((element) => element.addEventListener("click", () => {
    unregisterAvatar(element.dataset.avatarUnregister);
  }));
  document.querySelectorAll("[data-avatar-restore]").forEach((element) => element.addEventListener("click", () => {
    restoreAvatar(element.dataset.avatarRestore);
  }));
  document.querySelectorAll("[data-avatar-ignored-clear]").forEach((element) => element.addEventListener("click", () => {
    clearIgnoredAvatar(element.dataset.avatarIgnoredClear);
  }));
  document.querySelector("#refresh-health")?.addEventListener("click", refreshProviderHealth);
  document.querySelectorAll("[data-provider-new]").forEach((element) => element.addEventListener("click", () => openProviderDrawer()));
  document.querySelectorAll("[data-provider-edit]").forEach((element) => element.addEventListener("click", () => openProviderDrawer(element.dataset.providerEdit)));
  document.querySelectorAll("[data-provider-select]").forEach((element) => element.addEventListener("click", () => selectProviderProfile(element.dataset.providerSelect)));
  document.querySelectorAll("[data-provider-health]").forEach((element) => element.addEventListener("click", () => testProviderProfile(element.dataset.providerHealth)));
  document.querySelectorAll("[data-provider-restore]").forEach((element) => element.addEventListener("click", () => restoreProviderProfile(element.dataset.providerRestore)));
  document.querySelectorAll("[data-provider-drawer-close]").forEach((element) => element.addEventListener("click", closeProviderDrawer));
  document.querySelectorAll("[data-provider-drawer-mode]").forEach((element) => element.addEventListener("click", () => {
    state.providerDrawerMode = element.dataset.providerDrawerMode;
    state.providerImportPreview = null;
    render();
  }));
  document.querySelector("#provider-profile-form")?.addEventListener("submit", saveProviderProfileFromForm);
  document.querySelector("#provider-template-select")?.addEventListener("change", applyProviderTemplate);
  document.querySelectorAll("[data-provider-archive]").forEach((element) => element.addEventListener("click", () => archiveProviderProfile(element.dataset.providerArchive)));
  document.querySelector("#provider-import-raw")?.addEventListener("input", (event) => {
    state.providerImportRaw = event.target.value;
    state.providerImportPreview = null;
  });
  document.querySelector("#provider-import-file")?.addEventListener("change", loadProviderImportFile);
  document.querySelector("#provider-import-preview")?.addEventListener("click", previewProviderImport);
  document.querySelector("#provider-import-save")?.addEventListener("click", saveProviderImport);
  document.querySelector("#check-ccs-compatibility")?.addEventListener("click", checkCcsCompatibility);
  document.querySelector("#refresh-diagnostics")?.addEventListener("click", loadDiagnostics);
  document.querySelector("#refresh-desktop-status")?.addEventListener("click", loadDesktopStatus);
  document.querySelector("#refresh-plugins")?.addEventListener("click", loadPlugins);
  document.querySelector("#discover-plugins")?.addEventListener("click", discoverPlugins);
  document.querySelector("#plugin-path")?.addEventListener("input", (event) => {
    state.pluginPath = event.target.value;
  });
  document.querySelectorAll("[data-plugin-approve]").forEach((element) => element.addEventListener("click", () => {
    approvePlugin(element.dataset.pluginApprove);
  }));
  document.querySelectorAll("[data-plugin-revoke]").forEach((element) => element.addEventListener("click", () => {
    revokePlugin(element.dataset.pluginRevoke);
  }));
  document.querySelectorAll("[data-plugin-config]").forEach((element) => element.addEventListener("click", () => {
    state.pluginConfigId = element.dataset.pluginConfig;
    render();
  }));
  document.querySelectorAll("[data-plugin-config-close]").forEach((element) => element.addEventListener("click", () => {
    state.pluginConfigId = null;
    render();
  }));
  document.querySelectorAll("[data-plugin-launcher-form]").forEach((element) => element.addEventListener("submit", (event) => {
    event.preventDefault();
    configurePlugin(element.dataset.pluginLauncherForm, element);
  }));
  document.querySelectorAll("[data-plugin-run]").forEach((element) => element.addEventListener("click", () => {
    runPlugin(element.dataset.pluginRun);
  }));
  document.querySelector("#run-tool-test")?.addEventListener("click", runToolTest);
  document.querySelector("#refresh-audio-status")?.addEventListener("click", loadAudioStatus);
  document.querySelector("#refresh-vision-status")?.addEventListener("click", loadVisionStatus);
  document.querySelectorAll("[data-audio-permission]").forEach((element) => element.addEventListener("click", () => {
    setAudioPermission(element.dataset.audioPermission, element.dataset.audioGranted === "true");
  }));
  document.querySelectorAll("[data-audio-start]").forEach((element) => element.addEventListener("click", () => {
    controlAudio(element.dataset.audioStart, "start");
  }));
  document.querySelectorAll("[data-audio-stop]").forEach((element) => element.addEventListener("click", () => {
    controlAudio(element.dataset.audioStop, "stop");
  }));
  document.querySelectorAll("[data-vision-permission]").forEach((element) => element.addEventListener("click", () => {
    setVisionPermission(element.dataset.visionPermission, element.dataset.visionGranted === "true");
  }));
  document.querySelectorAll("[data-vision-start]").forEach((element) => element.addEventListener("click", () => {
    controlVision(element.dataset.visionStart, "start");
  }));
  document.querySelectorAll("[data-vision-stop]").forEach((element) => element.addEventListener("click", () => {
    controlVision(element.dataset.visionStop, "stop");
  }));
  document.querySelector("#add-memory")?.addEventListener("click", createMemory);
  document.querySelectorAll("[data-memory-delete]").forEach((element) => element.addEventListener("click", () => {
    deleteMemory(element.dataset.memoryDelete);
  }));
  document.querySelector("#add-task")?.addEventListener("click", createTask);
  document.querySelectorAll("[data-task-open]").forEach((element) => element.addEventListener("click", () => {
    state.selectedTaskId = state.selectedTaskId === element.dataset.taskOpen ? null : element.dataset.taskOpen;
    render();
  }));
  document.querySelectorAll("[data-task-status]").forEach((element) => element.addEventListener("click", () => {
    updateTask(element.dataset.taskId, { status: element.dataset.taskStatus });
  }));
  document.querySelectorAll("[data-task-run]").forEach((element) => element.addEventListener("click", () => {
    runTask(element.dataset.taskRun, element.dataset.taskApproved === "true");
  }));
  document.querySelectorAll("[data-module-toggle]").forEach((element) => element.addEventListener("click", () => {
    const module = state.modules.find((item) => item.id === element.dataset.moduleToggle);
    if (module) updateModule({ module_id: module.id, enabled: !module.enabled });
  }));
  document.querySelectorAll("[data-module-implementation]").forEach((element) => element.addEventListener("change", () => {
    updateModule({ module_id: element.dataset.moduleImplementation, implementation_id: element.value });
  }));
  document.querySelectorAll("[data-module-config-form]").forEach((element) => element.addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      updateModule({ module_id: element.dataset.moduleConfigForm, config: readModuleConfig(element) });
    } catch (error) {
      state.moduleNotice = error.message;
      render();
    }
  }));
  document.querySelector("#create-snapshot")?.addEventListener("click", createSnapshot);
  document.querySelector("#import-snapshot")?.addEventListener("click", () => document.querySelector("#snapshot-file")?.click());
  document.querySelector("#snapshot-file")?.addEventListener("change", importSnapshotFile);
  document.querySelector("#snapshot-scope")?.addEventListener("change", (event) => {
    state.snapshotDraftScope = event.target.value;
    state.snapshotDraftTargetId = "";
    render();
  });
  document.querySelector("#snapshot-target")?.addEventListener("change", (event) => {
    state.snapshotDraftTargetId = event.target.value;
  });
  document.querySelectorAll("[data-snapshot-select]").forEach((element) => element.addEventListener("click", () => {
    inspectSnapshot(element.dataset.snapshotSelect);
  }));
  document.querySelectorAll("[data-snapshot-restore]").forEach((element) => element.addEventListener("click", () => {
    restoreSnapshot(element.dataset.snapshotRestore);
  }));
  document.querySelectorAll("[data-snapshot-export]").forEach((element) => element.addEventListener("click", () => {
    exportSnapshot(element.dataset.snapshotExport);
  }));
  document.querySelectorAll("[data-notification-filter]").forEach((element) => element.addEventListener("click", () => {
    state.notificationFilter = element.dataset.notificationFilter || "all";
    render();
  }));
}

async function api(path, options = {}) {
  const response = await fetch(coreUrl(path), { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  return response.json();
}

async function rpc(method, params = {}) {
  const response = await api("/rpc", { method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method, params }) });
  if (response.error) throw new Error(response.error.message || "JSON-RPC request failed");
  return response.result;
}

async function invokeDesktop(command, args = {}) {
  if (!isDesktopShell) throw new Error("桌面浮窗只在 Tauri 桌面版可用");
  const invoke = window.__TAURI__?.core?.invoke;
  if (typeof invoke === "function") return invoke(command, args);
  const internals = window.__TAURI_INTERNALS__?.invoke;
  if (typeof internals === "function") return internals(command, args);
  throw new Error("Tauri invoke 桥接不可用，请从桌面客户端启动");
}

async function openDesktopOverlay() {
  try {
    await invokeDesktop("show_overlay");
  } catch (error) {
    state.sessionNotice = `打开桌面 Avatar 失败：${error.message}`;
    render();
  }
}

async function hideDesktopOverlay() {
  try {
    await invokeDesktop("hide_overlay");
  } catch (error) {
    state.sessionNotice = `隐藏桌面 Avatar 失败：${error.message}`;
    render();
  }
}

async function openMainWindow() {
  try {
    await invokeDesktop("open_main_window");
  } catch (error) {
    state.sessionNotice = `打开 Sumika 主窗口失败：${error.message}`;
    render();
  }
}

async function loadProviders(shouldRender = true) {
  try {
    state.providers = await api("/api/providers");
    state.connected = true;
    syncProviderSelection();
  } catch (error) {
    state.providers = [];
    state.connected = false;
  }
  if (shouldRender) render();
}

async function loadProviderProfiles(shouldRender = true, includeArchived = false) {
  try {
    state.providerProfiles = await api(`/api/provider-profiles${includeArchived ? "?include_archived=true" : ""}`);
    syncProviderSelection();
  } catch {
    state.providerProfiles = [];
  }
  if (shouldRender) render();
}

async function loadPrivacy(shouldRender = true) {
  try {
    const privacy = await api("/api/privacy");
    state.privacy = privacy.label || "本地处理";
  } catch {
    state.privacy = "状态未知";
  }
  if (shouldRender) render();
}

async function refreshProviderHealth() {
  await Promise.all([loadProviders(false), loadProviderProfiles(false, state.activePage === "Developer"), loadPrivacy(false)]);
  state.providerNotice = "Provider 状态已刷新";
  render();
}

function openProviderDrawer(profileId = null) {
  state.providerDrawerOpen = true;
  state.providerDrawerMode = "manual";
  state.providerDrawerProfileId = profileId || null;
  state.providerImportPreview = null;
  render();
  requestAnimationFrame(() => document.querySelector(".provider-drawer input[autofocus]")?.focus());
}

function closeProviderDrawer() {
  state.providerDrawerOpen = false;
  state.providerDrawerProfileId = null;
  state.providerImportPreview = null;
  render();
}

function applyProviderTemplate(event) {
  const template = state.providerTemplates.find((item) => item.id === event.target.value);
  const form = document.querySelector("#provider-profile-form");
  if (!template || !form) return;
  if (!form.elements.name.value.trim()) form.elements.name.value = template.name;
  form.elements.active_base_url.value = template.base_url || "";
  if (!form.elements.model.value.trim()) form.elements.model.value = template.model || "";
  form.elements.processing_location.value = template.processing_location || "auto";
}

function readProviderProfileForm(form) {
  let headers = {};
  let usageQuery = null;
  try {
    headers = form.elements.headers.value.trim() ? JSON.parse(form.elements.headers.value) : {};
    usageQuery = form.elements.usage_query.value.trim() ? JSON.parse(form.elements.usage_query.value) : null;
  } catch {
    throw new Error("高级设置中的 JSON 格式不正确");
  }
  const activeBaseUrl = form.elements.active_base_url.value.trim();
  const alternateUrls = form.elements.alternate_urls.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  const payload = {
    id: form.dataset.profileId || undefined,
    name: form.elements.name.value.trim(),
    adapter_id: "openai-compatible",
    template_id: form.elements.template_id.value,
    processing_location: form.elements.processing_location.value,
    active_base_url: activeBaseUrl,
    base_urls: [activeBaseUrl, ...alternateUrls],
    model: form.elements.model.value.trim(),
    timeout: Number(form.elements.timeout.value || 60),
    organization: form.elements.organization.value.trim(),
    project: form.elements.project.value.trim(),
    headers,
    usage_query: usageQuery,
  };
  const apiKey = form.elements.api_key.value;
  if (apiKey) payload.api_key = apiKey;
  if (form.elements.clear_api_key?.checked) payload.clear_secrets = ["api_key"];
  return payload;
}

async function saveProviderProfileFromForm(event) {
  event.preventDefault();
  if (state.providerBusy) return;
  const action = event.submitter?.dataset.providerAction || "save";
  let payload;
  try {
    payload = readProviderProfileForm(event.currentTarget);
  } catch (error) {
    state.providerNotice = error.message;
    render();
    return;
  }
  state.providerBusy = action;
  state.providerNotice = "";
  render();
  try {
    let profile = await rpc("provider.profile.save", { profile: payload });
    replaceProviderProfile(profile);
    state.providerDrawerProfileId = profile.id;
    if (action === "test" || action === "activate") {
      const health = await rpc("provider.profile.health", { profile_id: profile.id });
      profile = health.profile;
      replaceProviderProfile(profile);
      if (!health.ok) throw new Error(health.error || "连接或模型检查失败");
      state.providerNotice = `${profile.name} 连接测试通过`;
    } else {
      state.providerNotice = `${profile.name} 已保存；测试通过前不会启用`;
    }
    if (action === "activate") {
      await activateProviderProfile(profile.id);
      state.providerDrawerOpen = false;
      state.providerNotice = `${profile.name} 已保存并启用`;
    }
  } catch (error) {
    state.providerNotice = `Provider 操作失败：${error.message}`;
  } finally {
    state.providerBusy = null;
    await loadProviderProfiles(false);
    await loadPrivacy(false);
    render();
  }
}

function replaceProviderProfile(profile) {
  state.providerProfiles = [profile, ...state.providerProfiles.filter((item) => item.id !== profile.id)];
}

async function selectProviderProfile(profileId) {
  const profile = state.providerProfiles.find((item) => item.id === profileId);
  if (!profile) return;
  if (profile.status !== "available") {
    state.providerNotice = `${profile.name} 尚未就绪，请完成配置并测试连接`;
    openProviderDrawer(profileId);
    return;
  }
  if (state.providerBusy) return;
  state.providerBusy = `activate:${profileId}`;
  state.providerNotice = "";
  render();
  try {
    await activateProviderProfile(profileId);
    state.providerNotice = `${profile.name} 已启用`;
  } catch (error) {
    state.providerNotice = `启用连接失败：${error.message}`;
  } finally {
    state.providerBusy = null;
    await loadProviderProfiles(false);
    await loadPrivacy(false);
    render();
  }
}

async function activateProviderProfile(profileId) {
  const result = await rpc("provider.profile.activate", { profile_id: profileId });
  state.providerProfiles = state.providerProfiles.map((item) => ({ ...item, active: item.id === profileId }));
  if (result.profile) replaceProviderProfile({ ...result.profile, active: true });
  if (result.module) state.modules = state.modules.map((module) => module.id === "llm" ? normalizeModule(result.module) : module);
  state.privacy = result.privacy?.label || state.privacy;
  syncProviderSelection();
}

async function testProviderProfile(profileId) {
  if (state.providerBusy) return;
  state.providerBusy = `health:${profileId}`;
  render();
  try {
    const result = await rpc("provider.profile.health", { profile_id: profileId });
    replaceProviderProfile(result.profile);
    state.providerNotice = result.ok ? `${result.profile.name} 连接测试通过` : `${result.profile.name}：${result.error || "未就绪"}`;
  } catch (error) {
    state.providerNotice = `连接测试失败：${error.message}`;
  } finally {
    state.providerBusy = null;
    render();
  }
}

async function archiveProviderProfile(profileId) {
  if (!window.confirm("归档后不会出现在实现方式列表，可由后端恢复。继续吗？")) return;
  state.providerBusy = `archive:${profileId}`;
  render();
  try {
    await rpc("provider.profile.archive", { profile_id: profileId });
    state.providerProfiles = state.providerProfiles.filter((item) => item.id !== profileId);
    state.providerDrawerOpen = false;
    state.providerNotice = "连接已归档，凭据未被永久删除";
  } catch (error) {
    state.providerNotice = `归档失败：${error.message}`;
  } finally {
    state.providerBusy = null;
    render();
  }
}

async function restoreProviderProfile(profileId) {
  if (state.providerBusy) return;
  state.providerBusy = `restore:${profileId}`;
  render();
  try {
    const profile = await rpc("provider.profile.restore", { profile_id: profileId });
    replaceProviderProfile(profile);
    state.providerNotice = `${profile.name} 已恢复为草稿，请重新测试连接`;
  } catch (error) {
    state.providerNotice = `恢复失败：${error.message}`;
  } finally {
    state.providerBusy = null;
    render();
  }
}

async function loadProviderImportFile(event) {
  const file = event.currentTarget.files?.[0];
  if (!file) return;
  state.providerImportRaw = await file.text();
  state.providerImportFilename = file.name;
  state.providerImportPreview = null;
  render();
}

async function previewProviderImport() {
  const raw = document.querySelector("#provider-import-raw")?.value || state.providerImportRaw;
  if (!raw.trim() || state.providerBusy) return;
  state.providerImportRaw = raw;
  state.providerBusy = "import-preview";
  render();
  try {
    state.providerImportPreview = await rpc("provider.import.preview", { raw, filename: state.providerImportFilename });
    state.providerNotice = "导入内容已解析，请核对脱敏预览";
  } catch (error) {
    state.providerImportPreview = null;
    state.providerNotice = `导入预览失败：${error.message}`;
  } finally {
    state.providerBusy = null;
    render();
  }
}

async function saveProviderImport() {
  if (!state.providerImportPreview || state.providerBusy) return;
  state.providerBusy = "import-save";
  render();
  try {
    const result = await rpc("provider.import.save", { raw: state.providerImportRaw, filename: state.providerImportFilename });
    replaceProviderProfile(result.profile);
    state.providerDrawerMode = "manual";
    state.providerDrawerProfileId = result.profile.id;
    state.providerImportPreview = null;
    state.providerNotice = `${result.profile.name} 已作为草稿保存；测试通过后才能启用`;
  } catch (error) {
    state.providerNotice = `保存导入失败：${error.message}`;
  } finally {
    state.providerBusy = null;
    render();
  }
}

async function checkCcsCompatibility() {
  if (state.ccsBusy) return;
  state.ccsBusy = true;
  render();
  try {
    state.ccsReport = await rpc("integration.ccswitch.check", {});
  } catch (error) {
    state.ccsReport = { status: "check_failed", error: error.message };
  } finally {
    state.ccsBusy = false;
    render();
  }
}

async function loadDiagnostics(shouldRender = true) {
  try {
    state.diagnostics = await api("/api/diagnostics");
  } catch {
    state.diagnostics = null;
  }
  if (shouldRender) render();
}

async function loadDesktopStatus(shouldRender = true) {
  if (!isDesktopShell) return;
  try {
    state.desktopStatus = await invokeDesktop("core_status");
    if (state.desktopStatus?.host && state.desktopStatus?.port) {
      coreBaseUrl = `http://${state.desktopStatus.host}:${state.desktopStatus.port}`;
    }
  } catch {
    state.desktopStatus = null;
  }
  if (shouldRender) render();
}

async function loadPlugins(shouldRender = true) {
  try {
    state.plugins = await api("/api/plugins");
  } catch {
    state.plugins = [];
  }
  if (shouldRender) render();
}

async function discoverPlugins() {
  if (state.pluginBusy) return;
  const input = document.querySelector("#plugin-path");
  const path = input?.value.trim();
  if (!path) {
    state.pluginNotice = "请输入插件目录或 manifest.json 的绝对路径。";
    render();
    return;
  }
  state.pluginPath = path;
  state.pluginBusy = "discover";
  state.pluginNotice = "正在读取 manifest；不会执行 entrypoint。";
  render();
  try {
    const discovered = await rpc("plugin.discover", { paths: [path] });
    state.plugins = mergePlugins(state.plugins, discovered);
    await refreshPluginRuntimeState();
    state.pluginNotice = `扫描完成：发现 ${discovered.length} 个 manifest；请逐项批准登记。`;
  } catch (error) {
    state.pluginNotice = `插件扫描失败：${error.message}`;
  } finally {
    state.pluginBusy = null;
    render();
  }
}

async function approvePlugin(candidateId) {
  if (state.pluginBusy) return;
  const plugin = state.plugins.find((item) => item.candidate_id === candidateId);
  if (!plugin || !window.confirm(`批准登记 ${plugin.plugin_id || "这个插件"}？这一步不会启动代码或安装依赖。`)) return;
  state.pluginBusy = `approve:${candidateId}`;
  state.pluginNotice = "正在重新校验 manifest 哈希和 entrypoint…";
  render();
  try {
    const approved = await rpc("plugin.approve", { candidate_id: candidateId });
    state.plugins = mergePlugins(state.plugins, [approved]);
    await refreshPluginRuntimeState();
    state.pluginNotice = `${approved.plugin_id} 已批准登记；运行时接入仍需单独配置。`;
  } catch (error) {
    state.pluginNotice = `批准失败：${error.message}`;
  } finally {
    state.pluginBusy = null;
    render();
  }
}

async function revokePlugin(candidateId) {
  if (state.pluginBusy || !window.confirm("撤销这个插件的登记状态？原始文件不会被删除。")) return;
  state.pluginBusy = `revoke:${candidateId}`;
  state.pluginNotice = "正在撤销登记…";
  render();
  try {
    const revoked = await rpc("plugin.revoke", { candidate_id: candidateId });
    state.plugins = mergePlugins(state.plugins, [revoked]);
    await refreshPluginRuntimeState();
    state.pluginNotice = "插件登记已撤销，原始文件未删除。";
  } catch (error) {
    state.pluginNotice = `撤销失败：${error.message}`;
  } finally {
    state.pluginBusy = null;
    render();
  }
}

async function configurePlugin(candidateId, form) {
  if (state.pluginBusy) return;
  const formData = new FormData(form);
  let argumentsValue;
  try {
    argumentsValue = JSON.parse(String(formData.get("arguments") || "[]"));
  } catch {
    state.pluginNotice = "启动参数必须是有效 JSON 数组。";
    render();
    return;
  }
  const launcher = {
    executable: String(formData.get("executable") || "").trim(),
    arguments: argumentsValue,
    working_directory: String(formData.get("working_directory") || "").trim(),
    timeout_seconds: Number.parseInt(String(formData.get("timeout_seconds") || "30"), 10),
  };
  state.pluginBusy = `configure:${candidateId}`;
  state.pluginNotice = "正在校验启动器；不会启动进程。";
  render();
  try {
    const configured = await rpc("plugin.configure", { candidate_id: candidateId, launcher });
    state.plugins = mergePlugins(state.plugins, [configured]);
    await refreshPluginRuntimeState();
    state.pluginConfigId = null;
    state.pluginNotice = "启动配置已保存；只有测试调用并明确批准后才会启动。";
  } catch (error) {
    state.pluginNotice = `启动配置保存失败：${error.message}`;
  } finally {
    state.pluginBusy = null;
    render();
  }
}

async function runPlugin(candidateId) {
  if (state.pluginBusy) return;
  const plugin = state.plugins.find((item) => item.candidate_id === candidateId);
  if (!plugin || !window.confirm(`测试调用 ${plugin.plugin_id || "这个插件"}？这会启动已配置的软件并发送一次 JSON。`)) return;
  const raw = window.prompt("发送给插件的 JSON 输入", "{}");
  if (raw === null) return;
  let input;
  try {
    input = JSON.parse(raw);
  } catch {
    state.pluginNotice = "测试输入不是有效 JSON。";
    render();
    return;
  }
  state.pluginBusy = `run:${candidateId}`;
  state.pluginNotice = "正在等待明确批准后调用插件…";
  render();
  try {
    const result = await rpc("plugin.run", { candidate_id: candidateId, input, approved: true });
    const summary = JSON.stringify(result.execution?.result ?? result);
    state.pluginNotice = `调用完成：${summary.length > 500 ? summary.slice(0, 500) + "…" : summary}`;
  } catch (error) {
    state.pluginNotice = `插件调用失败：${error.message}`;
  } finally {
    state.pluginBusy = null;
    render();
  }
}

function mergePlugins(current, incoming) {
  const next = new Map(current.map((item) => [item.candidate_id, item]));
  incoming.forEach((item) => next.set(item.candidate_id, item));
  return [...next.values()].sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
}

async function loadModules(shouldRender = true) {
  try {
    state.modules = (await api("/api/modules")).map(normalizeModule);
    syncProviderSelection();
  } catch {
    state.modules = fallbackModules;
  }
  await loadMemories(false);
  if (shouldRender) render();
}

async function loadMemories(shouldRender = true) {
  const characterId = state.selectedCharacter;
  const module = state.modules.find((item) => item.id === "memory");
  if (!module?.enabled || module.implementation_id === "none") {
    state.memories = [];
    if (shouldRender) render();
    return;
  }
  try {
    const memories = await api(`/api/memories?character_id=${encodeURIComponent(characterId)}`);
    if (state.selectedCharacter === characterId) state.memories = memories;
  } catch {
    if (state.selectedCharacter === characterId) state.memories = [];
  }
  if (shouldRender) render();
}

async function loadAudioStatus(shouldRender = true) {
  try {
    state.audioStatus = await api("/api/audio/status");
  } catch {
    state.audioStatus = fallbackAudioStatus;
  }
  if (shouldRender) render();
}

async function loadVisionStatus(shouldRender = true) {
  try {
    state.visionStatus = await api("/api/vision/status");
  } catch {
    state.visionStatus = fallbackVisionStatus;
  }
  if (shouldRender) render();
}

async function refreshPluginRuntimeState() {
  await Promise.all([
    loadPlugins(false),
    loadProviders(false),
    loadModules(false),
    loadAudioStatus(false),
    loadVisionStatus(false),
  ]);
  render();
}

async function loadSnapshots(shouldRender = true) {
  try {
    state.snapshots = await rpc("snapshot.list");
  } catch {
    state.snapshots = [];
  }
  if (shouldRender) render();
}

async function inspectSnapshot(snapshotId) {
  if (!snapshotId || state.snapshotBusy) return;
  state.snapshotBusy = `inspect:${snapshotId}`;
  state.snapshotNotice = "";
  render();
  try {
    state.snapshotDiff = await rpc("snapshot.diff", { snapshot_id: snapshotId });
    state.selectedSnapshotId = snapshotId;
  } catch (error) {
    state.snapshotNotice = `读取快照差异失败：${error.message}`;
  } finally {
    state.snapshotBusy = null;
    render();
  }
}

async function createSnapshot() {
  if (state.snapshotBusy) return;
  const name = window.prompt("快照名称", "我的命名快照");
  if (!name?.trim()) return;
  const scope = document.querySelector("#snapshot-scope")?.value || "system";
  const targetId = document.querySelector("#snapshot-target")?.value || undefined;
  state.snapshotBusy = "create";
  state.snapshotNotice = "正在创建快照…";
  render();
  try {
    const snapshot = await rpc("snapshot.create", { name: name.trim(), scope, target_id: targetId });
    state.snapshots = [snapshot, ...state.snapshots.filter((item) => item.id !== snapshot.id)];
    state.selectedSnapshotId = snapshot.id;
    state.snapshotDiff = await rpc("snapshot.diff", { snapshot_id: snapshot.id });
    state.snapshotNotice = `已创建“${snapshot.name}”。`;
  } catch (error) {
    state.snapshotNotice = `创建快照失败：${error.message}`;
  } finally {
    state.snapshotBusy = null;
    render();
  }
}

async function restoreSnapshot(snapshotId) {
  const selected = state.snapshots.find((item) => item.id === snapshotId) || state.snapshotDiff?.snapshot;
  if (!selected || state.snapshotBusy) return;
  if (!window.confirm(`将恢复“${selected.name}”的${snapshotScopeLabel(selected.scope)}数据。恢复前会自动创建快照，是否继续？`)) return;
  state.snapshotBusy = `restore:${snapshotId}`;
  state.snapshotNotice = "正在创建恢复前快照并恢复…";
  render();
  try {
    const result = await rpc("snapshot.restore", { snapshot_id: snapshotId });
    state.snapshotNotice = `已恢复“${selected.name}”；恢复前快照为“${result.pre_restore_snapshot.name}”。`;
    await Promise.all([loadSnapshots(false), loadModules(false), loadMemories(false)]);
    state.snapshotDiff = await rpc("snapshot.diff", { snapshot_id: snapshotId });
    state.characters = await api("/api/characters");
    state.sessions = await api("/api/sessions");
    syncActiveSession();
    state.tasks = await api("/api/tasks");
    await loadAvatarState();
  } catch (error) {
    state.snapshotNotice = `恢复快照失败：${error.message}`;
  } finally {
    state.snapshotBusy = null;
    render();
  }
}

async function exportSnapshot(snapshotId) {
  if (!snapshotId || state.snapshotBusy) return;
  state.snapshotBusy = `export:${snapshotId}`;
  state.snapshotNotice = "正在准备导出包…";
  render();
  try {
    const packageValue = await rpc("snapshot.export", { snapshot_id: snapshotId });
    const name = packageValue.snapshot?.name || "sumika-snapshot";
    const blob = new Blob([JSON.stringify(packageValue, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${name.replaceAll(/[^\w\u4e00-\u9fff.-]+/g, "_").slice(0, 80) || "sumika-snapshot"}.sumika.json`;
    link.click();
    URL.revokeObjectURL(link.href);
    state.snapshotNotice = "快照已导出。导出包未加密，请按敏感文件处理。";
  } catch (error) {
    state.snapshotNotice = `导出快照失败：${error.message}`;
  } finally {
    state.snapshotBusy = null;
    render();
  }
}

async function importSnapshotFile(event) {
  const input = event.currentTarget;
  const file = input.files?.[0];
  input.value = "";
  if (!file || state.snapshotBusy) return;
  if (!window.confirm("导入后只会保存为新的待审核快照，不会立即恢复当前数据。是否继续？")) return;
  state.snapshotBusy = "import";
  state.snapshotNotice = "正在校验导入包…";
  render();
  try {
    const packageValue = JSON.parse(await file.text());
    const imported = await rpc("snapshot.import", { package: packageValue });
    state.snapshots = [imported, ...state.snapshots.filter((item) => item.id !== imported.id)];
    state.selectedSnapshotId = imported.id;
    state.snapshotDiff = await rpc("snapshot.diff", { snapshot_id: imported.id });
    state.snapshotNotice = `已导入“${imported.name}”；请先查看差异再恢复。`;
  } catch (error) {
    state.snapshotNotice = `导入快照失败：${error.message}`;
  } finally {
    state.snapshotBusy = null;
    render();
  }
}

async function loadInitialData() {
  await loadDesktopStatus(false);
  try {
    const [providers, providerProfiles, providerTemplates, privacy, ccsManifest, modules, plugins, audioStatus, visionStatus, tasks, sessions, characters, events, avatarModels, avatarIgnored, snapshots] = await Promise.all([api("/api/providers"), api("/api/provider-profiles"), api("/api/provider-templates"), api("/api/privacy"), api("/api/integrations/ccswitch"), api("/api/modules"), api("/api/plugins"), api("/api/audio/status"), api("/api/vision/status"), api("/api/tasks"), api("/api/sessions"), api("/api/characters"), api("/api/events"), api("/api/avatar/models"), api("/api/avatar/ignored"), rpc("snapshot.list")]);
    state.providers = providers;
    state.providerProfiles = providerProfiles;
    state.providerTemplates = providerTemplates;
    state.privacy = privacy.label || "本地处理";
    state.ccsManifest = ccsManifest;
    state.modules = modules.map(normalizeModule);
    // provider.list performs the real endpoint health check. Refresh the
    // module metadata after it completes so the schema form shows the same
    // ready/error status instead of a startup-time "unconfigured" snapshot.
    try {
      state.modules = (await api("/api/modules")).map(normalizeModule);
    } catch {
      // Keep the concurrently loaded module list if the metadata refresh fails.
    }
    state.plugins = plugins;
    state.audioStatus = audioStatus;
    state.visionStatus = visionStatus;
    state.tasks = tasks;
    state.avatarModels = avatarModels;
    state.avatarIgnored = avatarIgnored;
    state.snapshots = snapshots;
    syncProviderSelection();
    state.sessions = sessions;
    syncActiveSession();
    state.characters = characters;
    state.events = events;
    await loadMemories(false);
    state.avatarState = await rpc("avatar.state", { character_id: state.selectedCharacter });
    state.connected = true;
    await loadDiagnostics(false);
    await loadMessages();
  } catch {
    state.providers = [];
    state.providerProfiles = [];
    state.providerTemplates = [];
    state.ccsManifest = null;
    state.modules = [];
    state.plugins = [];
    state.audioStatus = fallbackAudioStatus;
    state.visionStatus = fallbackVisionStatus;
    state.tasks = [];
    state.avatarModels = [];
    state.avatarIgnored = [];
    state.snapshots = [];
    state.diagnostics = null;
    state.avatarState = fallbackAvatarState;
    state.characters = [{ id: "sumika", name: "Sumika", config: { language: "zh-CN", memory_enabled: false, persona: { identity: "", traits: "", relationship: "", speaking_style: "", behavior: "", boundaries: "", response_length: "balanced", system_prompt: "", greeting: "" }, avatar: { position: "center", opacity: 1, scale: 1, idle_motion: true, auto_rotate: false, rotation_speed: 0.12, natural_pose: true, look_at_enabled: true, head_follow_enabled: true, look_at_strength: 1, head_follow_strength: 0.35 } } }];
    state.sessions = [{ id: "default", title: "初始会话", character_id: "sumika" }];
    state.activeSessionId = "default";
    state.memories = [];
    state.connected = false;
    render();
  }
}

async function createTask() {
  const title = window.prompt("任务名称", "新的模块测试");
  if (!title?.trim()) return;
  try {
    const response = await api("/rpc", { method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method: "task.create", params: { title: title.trim(), autonomy_level: "L2" } }) });
    state.tasks = [response.result, ...state.tasks];
    state.selectedTaskId = response.result.id;
    state.taskNotice = "任务已创建，等待用户批准后才会运行。";
    render();
  } catch (error) {
    state.taskNotice = `创建任务失败：${error.message}`;
    render();
  }
}

async function updateTask(taskId, params) {
  if (state.taskBusy) return;
  state.taskBusy = taskId;
  state.taskNotice = "";
  render();
  try {
    const response = await api("/rpc", { method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method: "task.update", params: { task_id: taskId, ...params } }) });
    state.tasks = state.tasks.map((task) => task.id === taskId ? response.result : task);
    state.taskNotice = `${response.result.title}：${taskStatusLabel(response.result.status)}`;
  } catch (error) {
    state.taskNotice = `任务更新失败：${error.message}`;
  } finally {
    state.taskBusy = null;
    render();
  }
}

async function runTask(taskId, approved) {
  if (state.taskBusy) return;
  state.taskBusy = taskId;
  state.taskNotice = "";
  render();
  try {
    const response = await rpc("task.run", { task_id: taskId, handler_id: "core-health", approved });
    state.tasks = state.tasks.map((task) => task.id === taskId ? response : task);
    state.selectedTaskId = taskId;
    state.taskNotice = approved ? `${response.title}：${taskStatusLabel(response.status)}` : `${response.title}：等待用户批准`;
  } catch (error) {
    state.taskNotice = `任务运行失败：${error.message}`;
  } finally {
    state.taskBusy = null;
    render();
  }
}

function syncProviderSelection() {
  const llm = state.modules.find((module) => module.id === "llm");
  const profileId = llm?.profile_id || llm?.config?.profile_id;
  if (profileId && state.providerProfiles.some((profile) => profile.id === profileId)) {
    state.providerId = profileId;
    return;
  }
  if (!state.providerProfiles.some((profile) => profile.id === state.providerId)) {
    state.providerId = state.providerProfiles[0]?.id || "";
  }
}

function readModuleConfig(form) {
  const config = {};
  form.querySelectorAll("[data-config-key]").forEach((field) => {
    const key = field.dataset.configKey;
    if (field.dataset.configType === "boolean") {
      config[key] = field.checked;
      return;
    }
    if (field.value === "" && field.dataset.configFormat === "password") return;
    if (field.dataset.configType === "number") {
      config[key] = Number(field.value);
      return;
    }
    if (field.dataset.configType === "integer") {
      config[key] = Number.parseInt(field.value, 10);
      return;
    }
    if (field.dataset.configType === "array" || field.dataset.configType === "object") {
      try {
        config[key] = JSON.parse(field.value);
      } catch {
        throw new Error(`配置字段 ${key} 不是有效 JSON`);
      }
      return;
    }
    config[key] = field.value;
  });
  return config;
}

async function updateModule(params) {
  if (state.moduleBusy) return;
  state.moduleBusy = params.module_id;
  state.moduleNotice = "";
  render();
  try {
    const response = await api("/rpc", { method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method: "module.update", params }) });
    const updated = response.result;
    state.modules = state.modules.map((module) => module.id === updated.id ? normalizeModule(updated) : module);
    await loadAudioStatus(false);
    await loadVisionStatus(false);
    await loadMemories(false);
    if (updated.id === "llm") {
      await loadProviderProfiles(false);
      await loadPrivacy(false);
      syncProviderSelection();
    }
    state.moduleNotice = updated.secret_fields_not_persisted?.length ? `已保存配置；敏感字段仅在本次运行中使用：${updated.secret_fields_not_persisted.join("、")}` : `${updated.name} 已更新`;
  } catch (error) {
    state.moduleNotice = `模块更新失败：${error.message}`;
  } finally {
    state.moduleBusy = null;
    render();
  }
}

async function runToolTest() {
  if (state.toolBusy) return;
  const raw = window.prompt("发送给外部软件的 JSON 输入", "{}");
  if (raw === null) return;
  let input;
  try {
    input = JSON.parse(raw);
  } catch {
    state.toolNotice = "测试输入不是有效 JSON。";
    render();
    return;
  }
  if (!window.confirm("这会启动已配置的外部软件并发送一次输入，是否批准？")) return;
  state.toolBusy = true;
  state.toolNotice = "";
  render();
  try {
    const result = await rpc("tool.run", { tool_id: "manual-test", input, approved: true });
    const summary = JSON.stringify(result.result);
    state.toolNotice = `调用完成：${summary.length > 500 ? summary.slice(0, 500) + "…" : summary}`;
  } catch (error) {
    state.toolNotice = `外部工具调用失败：${error.message}`;
  } finally {
    state.toolBusy = false;
    render();
  }
}

async function createMemory() {
  if (state.memoryBusy) return;
  const module = state.modules.find((item) => item.id === "memory");
  const configuredCategories = Array.isArray(module?.config?.categories) ? module.config.categories : [];
  const category = window.prompt("记忆类别", configuredCategories[0] || "preferences");
  if (!category?.trim()) return;
  const content = window.prompt("记忆内容");
  if (!content?.trim()) return;
  state.memoryBusy = "new";
  state.memoryNotice = "";
  render();
  try {
    const memory = await rpc("memory.add", { character_id: state.selectedCharacter, category: category.trim(), content: content.trim(), source: "user" });
    state.memories = [memory, ...state.memories];
    state.memoryNotice = "记忆已保存；事件日志只保留审计摘要。";
  } catch (error) {
    state.memoryNotice = `记忆保存失败：${error.message}`;
  } finally {
    state.memoryBusy = null;
    render();
  }
}

async function deleteMemory(memoryId) {
  if (state.memoryBusy || !window.confirm("删除这条长期记忆？删除后正文不会保留在记忆库中。")) return;
  state.memoryBusy = memoryId;
  state.memoryNotice = "";
  render();
  try {
    await rpc("memory.delete", { memory_id: memoryId });
    state.memories = state.memories.filter((memory) => memory.id !== memoryId);
    state.memoryNotice = "记忆已删除。";
  } catch (error) {
    state.memoryNotice = `记忆删除失败：${error.message}`;
  } finally {
    state.memoryBusy = null;
    render();
  }
}

async function setAudioPermission(permissionId, granted) {
  const busyId = `permission:${permissionId}`;
  if (state.audioBusy) return;
  state.audioBusy = busyId;
  state.audioNotice = "";
  render();
  try {
    state.audioStatus = await rpc("audio.permission.set", { permission_id: permissionId, granted });
    state.audioNotice = `${audioPermissionLabel(permissionId)}权限已${granted ? "允许" : "拒绝"}。`;
  } catch (error) {
    state.audioNotice = `权限更新失败：${error.message}`;
  } finally {
    state.audioBusy = null;
    render();
  }
}

async function setVisionPermission(permissionId, granted) {
  const busyId = `permission:${permissionId}`;
  if (state.visionBusy) return;
  state.visionBusy = busyId;
  state.visionNotice = "";
  render();
  try {
    state.visionStatus = await rpc("vision.permission.set", { permission_id: permissionId, granted });
    state.visionNotice = `${visionPermissionLabel(permissionId)}权限已${granted ? "允许" : "拒绝"}。`;
  } catch (error) {
    state.visionNotice = `视觉权限更新失败：${error.message}`;
  } finally {
    state.visionBusy = null;
    render();
  }
}

async function controlAudio(capability, action) {
  if (state.audioBusy) return;
  state.audioBusy = `capability:${capability}`;
  state.audioNotice = "";
  render();
  try {
    state.audioStatus = await rpc(`audio.${action}`, { capability });
    state.audioNotice = `${audioCapabilityLabel(capability)}已${action === "start" ? "启动" : "停止"}。`;
  } catch (error) {
    state.audioNotice = `音频运行操作失败：${error.message}`;
  } finally {
    state.audioBusy = null;
    render();
  }
}

const VOICE_RECORDING_LIMIT_MS = 30_000;

async function toggleVoiceCapture() {
  if (activeAudioCapture) {
    stopVoiceCapture();
    return;
  }
  const asr = (state.audioStatus?.capabilities || []).find((item) => item.id === "asr");
  if (!asr?.running) {
    state.voiceNotice = "请先在“模块”页启用语音识别、选择实现并启动 ASR。";
    render();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof window.MediaRecorder !== "function") {
    state.voiceNotice = "当前环境不支持浏览器麦克风录音，请在桌面版或支持 MediaRecorder 的浏览器中使用。";
    render();
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const track = stream.getAudioTracks()[0];
    const settings = track?.getSettings?.() || {};
    const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]
      .find((value) => MediaRecorder.isTypeSupported?.(value));
    const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    const capture = {
      stream,
      recorder,
      chunks: [],
      sampleRate: Number(settings.sampleRate) || 48_000,
      channels: Number(settings.channelCount) || 1,
      timeoutId: null,
      discarded: false,
    };
    activeAudioCapture = capture;
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) capture.chunks.push(event.data);
    });
    recorder.addEventListener("error", (event) => {
      capture.discarded = true;
      discardAudioCapture(capture);
      if (activeAudioCapture === capture) activeAudioCapture = null;
      state.voiceRecording = false;
      state.voiceNotice = `录音失败：${event.error?.message || "MediaRecorder 错误"}`;
      render();
    }, { once: true });
    recorder.addEventListener("stop", () => { void finishVoiceCapture(capture); }, { once: true });
    recorder.start();
    capture.timeoutId = window.setTimeout(() => {
      if (activeAudioCapture === capture) {
        state.voiceNotice = "录音已达到 30 秒，正在提交识别。";
        stopVoiceCapture();
      }
    }, VOICE_RECORDING_LIMIT_MS);
    state.voiceRecording = true;
    state.voiceNotice = "正在录音，最长 30 秒；再次点击语音按钮停止。";
    render();
  } catch (error) {
    stream?.getTracks().forEach((track) => track.stop());
    state.voiceRecording = false;
    state.voiceNotice = `无法开始录音：${error.message || "麦克风权限被拒绝"}`;
    render();
  }
}

function stopVoiceCapture() {
  const capture = activeAudioCapture;
  if (!capture) return;
  state.voiceRecording = false;
  state.voiceNotice = state.voiceNotice || "正在处理录音...";
  render();
  if (capture.recorder.state === "recording") {
    capture.recorder.stop();
  } else {
    void finishVoiceCapture(capture);
  }
}

async function finishVoiceCapture(capture) {
  if (capture.discarded) {
    discardAudioCapture(capture);
    if (activeAudioCapture === capture) activeAudioCapture = null;
    return;
  }
  if (activeAudioCapture === capture) activeAudioCapture = null;
  clearAudioCaptureTimer(capture);
  state.voiceRecording = false;
  try {
    const blob = new Blob(capture.chunks, { type: capture.recorder.mimeType || "audio/webm" });
    if (!blob.size) throw new Error("没有收到音频数据");
    const wav = await audioBlobToWav(blob);
    const result = await rpc("audio.asr.transcribe", {
      audio_base64: arrayBufferToBase64(wav),
      sample_rate: 16_000,
      channels: 1,
      language: currentCharacter().config?.language || "zh-CN",
    });
    const transcript = String(result?.text || "").trim();
    if (!transcript) throw new Error("ASR 没有返回文字");
    state.composerDraft = transcript;
    state.voiceNotice = "识别完成，请确认文字后发送。";
  } catch (error) {
    state.voiceNotice = `语音识别失败：${error.message || "未知错误"}`;
  } finally {
    discardAudioCapture(capture);
    render();
    document.querySelector("#chat-input")?.focus();
  }
}

function clearAudioCaptureTimer(capture) {
  if (capture.timeoutId !== null) {
    window.clearTimeout(capture.timeoutId);
    capture.timeoutId = null;
  }
}

function discardAudioCapture(capture) {
  capture.discarded = true;
  clearAudioCaptureTimer(capture);
  if (capture.recorder && capture.recorder.state !== "inactive") {
    try { capture.recorder.stop(); } catch { /* the stream is still released below */ }
  }
  capture.stream?.getTracks().forEach((track) => track.stop());
}

async function audioBlobToWav(blob) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) throw new Error("当前环境无法解码录音格式");
  const context = new AudioContextClass();
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    return encodePcmWav(decoded, 16_000);
  } finally {
    const closeResult = context.close?.();
    if (closeResult && typeof closeResult.catch === "function") await closeResult.catch(() => {});
  }
}

function encodePcmWav(audioBuffer, targetRate) {
  if (!audioBuffer?.length || !audioBuffer.numberOfChannels || !Number.isFinite(audioBuffer.sampleRate) || audioBuffer.sampleRate <= 0) {
    throw new Error("录音没有有效音频帧");
  }
  const sourceRate = audioBuffer.sampleRate;
  const frameCount = Math.max(1, Math.ceil(audioBuffer.length * targetRate / sourceRate));
  const channels = Array.from({ length: audioBuffer.numberOfChannels }, (_, index) => audioBuffer.getChannelData(index));
  const samples = new Float32Array(frameCount);
  for (let index = 0; index < frameCount; index += 1) {
    const sourcePosition = index * sourceRate / targetRate;
    const lower = Math.floor(sourcePosition);
    const upper = Math.min(lower + 1, audioBuffer.length - 1);
    const fraction = sourcePosition - lower;
    let value = 0;
    channels.forEach((channel) => {
      value += channel[lower] * (1 - fraction) + channel[upper] * fraction;
    });
    samples[index] = value / Math.max(1, channels.length);
  }
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeAscii(view, 8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, targetRate, true);
  view.setUint32(28, targetRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, index) => {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  });
  return buffer;
}

function writeAscii(view, offset, value) {
  for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

async function controlVision(source, action) {
  if (state.visionBusy) return;
  state.visionBusy = `source:${source}`;
  state.visionNotice = "";
  render();
  try {
    state.visionStatus = await rpc(`vision.${action}`, { source });
    state.visionNotice = `${visionSourceLabel(source)}已${action === "start" ? "启动" : "停止"}；当前仍需桌面桥接提交图像。`;
  } catch (error) {
    state.visionNotice = `视觉运行操作失败：${error.message}`;
  } finally {
    state.visionBusy = null;
    render();
  }
}

async function loadMessages() {
  syncActiveSession();
  state.chatAutoScroll = true;
  const sessionId = currentSessionId();
  try {
    const messages = await api(`/api/sessions/${encodeURIComponent(sessionId)}/messages`);
    if (currentSessionId() === sessionId) state.messages = messages;
  } catch {
    if (currentSessionId() === sessionId) state.messages = [];
  }
  render();
  scrollMessages(true);
}

async function sendMessage(event) {
  event.preventDefault();
  const input = document.querySelector("#chat-input");
  const content = String(input?.value ?? state.composerDraft).trim();
  if (!content || state.sending) return;
  if (!state.connected || !state.providerProfiles.length) {
    state.sessionNotice = "核心未连接，当前没有可用的真实 Provider。";
    render();
    return;
  }
  const llm = currentLlmModule();
  if (!llm?.enabled) {
    state.sessionNotice = "大语言模型模块已关闭，请到“模块”页打开 LLM 开关。";
    render();
    return;
  }
  const selectedProvider = activeProviderProfile() || llm.profile;
  if (!selectedProvider || selectedProvider.status !== "available") {
    state.sessionNotice = `${selectedProvider?.name || "当前 Provider"} 尚未就绪，请先在模块页测试连接。`;
    render();
    return;
  }
  const sessionId = currentSessionId();
  state.sessionNotice = "";
  state.sending = true;
  state.chatAutoScroll = true;
  state.messages.push({ role: "user", content, created_at: new Date().toISOString() });
  state.composerDraft = "";
  input.value = "";
  render();
  try {
    const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ session_id: sessionId, character_id: state.selectedCharacter, messages: [{ role: "user", content }] }) });
    if (state.activeSessionId === sessionId) state.messages.push(result.message);
    try {
      state.sessions = await api("/api/sessions");
      syncActiveSession();
    } catch {
      // A successful chat should not be presented as failed when history refresh is unavailable.
    }
  } catch (error) {
    if (state.activeSessionId === sessionId) state.messages.push({ role: "assistant", content: `核心服务暂时不可用：${error.message}`, created_at: new Date().toISOString() });
  } finally {
    state.sending = false;
    await refreshEvents();
    render();
    scrollMessages();
  }
}

async function createSession() {
  if (state.sessionBusy) return;
  state.sessionBusy = true;
  state.sessionNotice = "";
  render();
  try {
    const session = await rpc("session.create", { character_id: state.selectedCharacter });
    state.sessions = [session, ...state.sessions.filter((item) => item.id !== session.id)];
    state.activeSessionId = session.id;
    state.messages = [];
    state.activePage = "Chat";
  } catch (error) {
    state.sessionNotice = `新会话创建失败：${error.message}`;
  } finally {
    state.sessionBusy = false;
    render();
    if (!state.sessionNotice) document.querySelector("#chat-input")?.focus();
  }
}

async function selectSession(sessionId) {
  const session = state.sessions.find((item) => item.id === sessionId);
  if (!session || state.sessionBusy) return;
  state.activeSessionId = session.id;
  if (session.character_id && state.characters.some((item) => item.id === session.character_id)) {
    state.selectedCharacter = session.character_id;
    await Promise.all([loadAvatarState(false), loadMemories(false)]);
  }
  state.activePage = "Chat";
  await loadMessages();
}

async function createCharacter() {
  const name = window.prompt("角色名称", "新角色");
  if (!name?.trim()) return;
  try {
    const character = await api("/rpc", { method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method: "character.create", params: { name: name.trim(), config: { language: "zh-CN", memory_enabled: false, persona: { identity: "", traits: "", relationship: "", speaking_style: "", behavior: "", boundaries: "", response_length: "balanced", system_prompt: "", greeting: "" }, avatar: { position: "center", opacity: 1, scale: 1, idle_motion: true, auto_rotate: false, rotation_speed: 0.12 } } } }) });
    state.characters.push(character.result);
    state.selectedCharacter = character.result.id;
    await loadAvatarState();
    render();
  } catch (error) {
    window.alert(`创建失败：${error.message}`);
  }
}

async function saveCharacter(event) {
  event.preventDefault();
  if (state.characterBusy) return;
  const form = event.currentTarget;
  const formData = new FormData(form);
  const name = String(formData.get("name") || "").trim();
  state.characterBusy = true;
  state.characterNotice = "";
  render();
  try {
    const character = await rpc("character.update", {
      character_id: state.selectedCharacter,
      name,
      config: {
        language: String(formData.get("language") || "zh-CN"),
        persona: {
          identity: String(formData.get("persona_identity") || ""),
          traits: String(formData.get("persona_traits") || ""),
          relationship: String(formData.get("persona_relationship") || ""),
          speaking_style: String(formData.get("persona_speaking_style") || ""),
          behavior: String(formData.get("persona_behavior") || ""),
          boundaries: String(formData.get("persona_boundaries") || ""),
          response_length: String(formData.get("persona_response_length") || "balanced"),
          system_prompt: String(formData.get("system_prompt") || ""),
          greeting: String(formData.get("greeting") || ""),
        },
        avatar: {
          position: String(formData.get("avatar_position") || "center"),
          opacity: Number(formData.get("avatar_opacity")),
          scale: Number(formData.get("avatar_scale")),
          idle_motion: formData.get("avatar_idle_motion") === "on",
          auto_rotate: formData.get("avatar_auto_rotate") === "on",
          rotation_speed: Number(formData.get("avatar_rotation_speed")),
          natural_pose: formData.get("avatar_natural_pose") === "on",
          look_at_enabled: formData.get("avatar_look_at_enabled") === "on",
          head_follow_enabled: formData.get("avatar_head_follow_enabled") === "on",
          look_at_strength: Number(formData.get("avatar_look_at_strength")),
          head_follow_strength: Number(formData.get("avatar_head_follow_strength")),
        },
      },
    });
    state.characters = state.characters.map((item) => item.id === character.id ? character : item);
    state.characterNotice = `${character.name} 的配置已保存。`;
    await loadAvatarState();
  } catch (error) {
    state.characterNotice = `角色配置保存失败：${error.message}`;
  } finally {
    state.characterBusy = false;
    render();
  }
}

async function loadAvatarState(shouldRender = true) {
  const characterId = state.selectedCharacter;
  try {
    const avatarState = await rpc("avatar.state", { character_id: characterId });
    if (state.selectedCharacter === characterId) state.avatarState = avatarState;
  } catch {
    if (state.selectedCharacter === characterId) state.avatarState = fallbackAvatarState;
  }
  if (shouldRender) render();
}

async function chooseAvatarPath() {
  const nativeDialog = window.__TAURI__?.dialog?.open;
  if (typeof nativeDialog === "function") {
    const selected = await nativeDialog({
      multiple: false,
      directory: false,
      filters: [{ name: "Avatar 模型", extensions: ["vrm", "model3.json", "model.json"] }],
    });
    return Array.isArray(selected) ? selected[0] : selected;
  }
  if (isDesktopShell) {
    const selected = await invokeDesktop("plugin:dialog|open", { options: {
      multiple: false,
      directory: false,
      filters: [{ name: "Avatar 模型", extensions: ["vrm", "model3.json", "model.json"] }],
    } });
    return Array.isArray(selected) ? selected[0] : selected;
  }
  return window.prompt("当前浏览器预览模式无法读取文件的绝对路径，请粘贴 Live2D .model3.json/.model.json 或 VRM 文件的绝对路径");
}

async function importAvatar() {
  let path;
  try {
    path = await chooseAvatarPath();
  } catch (error) {
    state.avatarNotice = `打开文件选择器失败：${error.message}`;
    render();
    return;
  }
  if (typeof path !== "string" || !path.trim()) return;
  try {
    const model = await rpc("avatar.import", { path: path.trim() });
    if (!state.avatarModels.some((item) => item.id === model.id)) state.avatarModels = [model, ...state.avatarModels];
    state.avatarNotice = `${model.name} 已登记；当前仍使用预览驱动。`;
  } catch (error) {
    state.avatarNotice = `模型登记失败：${error.message}`;
  }
  render();
}

async function discoverAvatarAssets() {
  if (state.avatarBusy) return;
  state.avatarBusy = "discover";
  state.avatarNotice = "";
  render();
  try {
    const models = await rpc("avatar.discover", {});
    state.avatarModels = models;
    state.avatarIgnored = await rpc("avatar.ignored", {});
    state.avatarNotice = models.length
      ? `已扫描 assets/avatars，当前共有 ${models.length} 个已登记模型。`
      : "assets/avatars 中没有找到支持的 VRM 或 Live2D 模型。";
  } catch (error) {
    state.avatarNotice = `扫描内置目录失败：${error.message}`;
  } finally {
    state.avatarBusy = null;
    render();
  }
}

async function refreshAvatar(modelId) {
  if (state.avatarBusy) return;
  state.avatarBusy = `refresh:${modelId}`;
  state.avatarNotice = "";
  render();
  try {
    const model = await rpc("avatar.refresh", { model_id: modelId });
    state.avatarModels = state.avatarModels.map((item) => item.id === model.id ? model : item);
    if (state.avatarState?.model?.id === model.id) state.avatarState = { ...state.avatarState, model };
    state.avatarNotice = `${model.name} 的文件元数据已刷新。`;
  } catch (error) {
    state.avatarNotice = `模型刷新失败：${error.message}`;
  } finally {
    state.avatarBusy = null;
    render();
  }
}

async function inspectAvatar(modelId) {
  if (state.avatarBusy) return;
  state.avatarBusy = `inspect:${modelId}`;
  state.avatarNotice = "";
  render();
  try {
    const inspection = await rpc("avatar.inspect", { model_id: modelId });
    state.avatarInspections = { ...state.avatarInspections, [modelId]: inspection };
    const statusLabel = ({ ready: "正常", warning: "有警告", error: "有错误" })[inspection.status] || inspection.status;
    state.avatarNotice = `清单检查完成：${statusLabel}。`;
  } catch (error) {
    state.avatarNotice = `模型检查失败：${error.message}`;
  } finally {
    state.avatarBusy = null;
    render();
  }
}

async function unregisterAvatar(modelId) {
  if (state.avatarBusy) return;
  const model = state.avatarModels.find((item) => item.id === modelId);
  if (!model) return;
  const managed = model.metadata?.managed_directory === "assets/avatars" || model.metadata?.auto_discovered || model.metadata?.bundled;
  const bindings = state.characters.filter((character) => character.config?.avatar_model_id === modelId);
  if (bindings.length) {
    state.avatarNotice = `无法处理“${model.name}”：仍绑定到 ${bindings.map((character) => character.name).join("、")}。请先在对应角色行点击“解除当前角色绑定”。`;
    render();
    return;
  }
  if (!window.confirm(`${managed ? "忽略" : "移除"}“${model.name}”的登记？原始模型文件不会被删除。`)) return;
  state.avatarBusy = `unregister:${modelId}`;
  state.avatarNotice = "";
  render();
  try {
    const result = await rpc("avatar.unregister", { model_id: modelId });
    state.avatarModels = state.avatarModels.filter((item) => item.id !== result.model.id);
    if (managed) {
      state.avatarIgnored = await rpc("avatar.ignored", {});
      state.avatarNotice = `${result.model.name} 已忽略自动扫描，原文件未删除。`;
    } else {
      state.avatarNotice = `${result.model.name} 已移除登记，原文件未删除。`;
    }
  } catch (error) {
    state.avatarNotice = `模型登记处理失败：${error.message}`;
  } finally {
    state.avatarBusy = null;
    render();
  }
}

async function selectAvatar(modelId) {
  const model = state.avatarModels.find((item) => item.id === modelId);
  if (!model) return;
  try {
    const result = await rpc("avatar.select", { character_id: state.selectedCharacter, model_id: model.id, driver_id: model.kind });
    state.avatarState = result.state;
    state.characters = state.characters.map((character) => character.id === result.character.id ? result.character : character);
    state.avatarNotice = `${model.name} 已绑定到 ${result.character.name}。`;
  } catch (error) {
    state.avatarNotice = `Avatar 绑定失败：${error.message}`;
  }
  render();
}

async function clearAvatar(modelId) {
  if (!modelId) return;
  try {
    const result = await rpc("avatar.select", { character_id: state.selectedCharacter, model_id: null, driver_id: "none" });
    state.avatarState = result.state;
    state.characters = state.characters.map((character) => character.id === result.character.id ? result.character : character);
    state.avatarNotice = "当前角色已解除 Avatar 绑定。";
  } catch (error) {
    state.avatarNotice = `解除绑定失败：${error.message}`;
  }
  render();
}

async function restoreAvatar(path) {
  if (state.avatarBusy) return;
  state.avatarBusy = `restore:${path}`;
  state.avatarNotice = "";
  render();
  try {
    const model = await rpc("avatar.restore", { path });
    state.avatarModels = [model, ...state.avatarModels.filter((item) => item.path !== model.path)];
    state.avatarIgnored = state.avatarIgnored.filter((item) => item.path !== path);
    state.avatarNotice = `${model.name} 已恢复登记；请按需点击“绑定当前角色”。`;
  } catch (error) {
    state.avatarNotice = `恢复登记失败：${error.message}`;
  } finally {
    state.avatarBusy = null;
    render();
  }
}

async function clearIgnoredAvatar(path) {
  if (state.avatarBusy) return;
  state.avatarBusy = `clear-ignored:${path}`;
  state.avatarNotice = "";
  render();
  try {
    await rpc("avatar.ignored.clear", { path });
    state.avatarIgnored = state.avatarIgnored.filter((item) => item.path !== path);
    state.avatarNotice = "忽略记录已清除；没有删除模型文件。";
  } catch (error) {
    state.avatarNotice = `清除忽略记录失败：${error.message}`;
  } finally {
    state.avatarBusy = null;
    render();
  }
}

async function refreshEvents() {
  try { state.events = await api("/api/events"); } catch { /* the UI can keep its last event state */ }
}

function connectEvents() {
  if (!window.WebSocket) return;
  const endpoint = coreBaseUrl ? new URL(coreBaseUrl) : window.location;
  const protocol = endpoint.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${endpoint.host}/ws/events`);
  socket.addEventListener("open", () => { state.connected = true; render(); });
  socket.addEventListener("message", (event) => {
    try {
      const value = JSON.parse(event.data);
      if (value.event_type !== "connection.ready") {
        state.events.unshift(value);
        if (value.event_type === "module.changed" && value.payload?.module) {
          const changed = value.payload.module;
          state.modules = state.modules.map((module) => module.id === changed.id ? normalizeModule(changed) : module);
          syncProviderSelection();
          loadAudioStatus();
          loadVisionStatus();
          if (changed.id === "memory") loadMemories();
        }
        if (value.event_type.startsWith("audio.")) {
          loadAudioStatus();
        }
        if (value.event_type.startsWith("vision.")) {
          loadVisionStatus();
        }
        if (value.event_type.startsWith("memory.")) {
          loadMemories();
        }
        if ((value.event_type === "task.created" || value.event_type === "task.updated") && value.payload?.task) {
          const changed = value.payload.task;
          const exists = state.tasks.some((task) => task.id === changed.id);
          state.tasks = exists ? state.tasks.map((task) => task.id === changed.id ? changed : task) : [changed, ...state.tasks];
        }
        if (value.event_type === "avatar.changed" && value.payload) {
          state.avatarState = value.payload;
        }
        if (value.event_type === "character.changed" && value.payload?.character) {
          const changed = value.payload.character;
          state.characters = state.characters.some((character) => character.id === changed.id) ? state.characters.map((character) => character.id === changed.id ? changed : character) : [...state.characters, changed];
          if (changed.id === state.selectedCharacter) loadAvatarState();
        }
        if (value.event_type === "avatar.model.imported" && value.payload?.model) {
          const model = value.payload.model;
          if (!state.avatarModels.some((item) => item.id === model.id)) state.avatarModels = [model, ...state.avatarModels];
          state.avatarIgnored = state.avatarIgnored.filter((item) => item.path !== model.path);
        }
        if (value.event_type === "avatar.model.refreshed" && value.payload?.model) {
          const model = value.payload.model;
          state.avatarModels = state.avatarModels.map((item) => item.id === model.id ? model : item);
          if (state.avatarState?.model?.id === model.id) state.avatarState = { ...state.avatarState, model };
        }
        if (value.event_type === "avatar.model.unregistered" && value.payload?.model) {
          const model = value.payload.model;
          state.avatarModels = state.avatarModels.filter((item) => item.id !== model.id);
          if (model.metadata?.managed_directory === "assets/avatars" || model.metadata?.auto_discovered || model.metadata?.bundled) {
            void rpc("avatar.ignored", {}).then((ignored) => { state.avatarIgnored = ignored; render(); }).catch(() => {});
          }
        }
        if (value.event_type === "avatar.model.restored" && value.payload?.model) {
          const model = value.payload.model;
          state.avatarModels = [model, ...state.avatarModels.filter((item) => item.path !== model.path)];
          state.avatarIgnored = state.avatarIgnored.filter((item) => item.path !== model.path);
        }
        if (value.event_type === "avatar.ignored.cleared" && value.payload?.path) {
          state.avatarIgnored = state.avatarIgnored.filter((item) => item.path !== value.payload.path);
        }
        if (["plugin.approved", "plugin.configured", "plugin.revoked", "plugin.discovered"].includes(value.event_type)) {
          void refreshPluginRuntimeState();
        }
        if (value.event_type?.startsWith("provider.profile.")) {
          void Promise.all([loadProviderProfiles(false, state.activePage === "Developer"), loadPrivacy(false)]).then(render);
        }
        if ((value.event_type === "snapshot.created" || value.event_type === "snapshot.imported") && value.payload?.snapshot) {
          const snapshot = value.payload.snapshot;
          state.snapshots = [snapshot, ...state.snapshots.filter((item) => item.id !== snapshot.id)];
        }
        if (value.event_type === "snapshot.restored") {
          loadSnapshots(false);
        }
        // Token events can arrive dozens of times per answer. A full render
        // destroys and remounts the VRM canvas, so only repaint on the first
        // token (for remote chats) and on completion.
        if (value.event_type === "llm.token") {
          if (!state.sending) {
            state.sending = true;
            render();
          }
          return;
        }
        if (value.event_type === "chat.completed") state.sending = false;
        render();
      }
    } catch { /* ignore malformed event frames at the UI boundary */ }
  });
  socket.addEventListener("close", () => { state.connected = false; setTimeout(connectEvents, 2500); render(); });
}

function rememberChatScrollPreference() {
  const list = document.querySelector("#message-list");
  if (!list) return;
  const distance = list.scrollHeight - list.scrollTop - list.clientHeight;
  state.chatAutoScroll = distance <= 48;
}

function scheduleScrollMessages(force = false) {
  if (!force && !state.chatAutoScroll) return;
  requestAnimationFrame(() => scrollMessages(force));
}

function scrollMessages(force = false) {
  const list = document.querySelector("#message-list");
  if (!list || (!force && !state.chatAutoScroll)) return;
  const scrollToEnd = () => {
    if (list.isConnected) list.scrollTop = list.scrollHeight;
  };
  scrollToEnd();
  requestAnimationFrame(scrollToEnd);
}

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.providerDrawerOpen) closeProviderDrawer();
});

render();
loadInitialData();
connectEvents();
