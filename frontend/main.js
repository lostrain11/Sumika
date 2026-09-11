import {
  NAV_ITEMS,
  pageLabel,
} from "./src/scene-shell.js";
import {
  projectSceneState,
  scenePageAfterDrawerClose,
  scenePageAfterNavigation,
} from "./src/scene-store.js";
import { createSceneView } from "./src/a-plus-scene-view.js";
import { createPageView, renderPageFrame } from "./src/page-view.js";
import { createViewState } from "./src/view-state.js";
import { createDeveloperView } from "./src/developer-view.js";
import { createWebWorkbenchView } from "./src/web-workbench-view.js";
import { createAgentView } from "./src/agent-view.js";
import { createWorkbenchView } from "./src/workbench-view.js";
import { createWorkAuthorizationClient } from "./src/work-authorization.js";
import { confirmThroughHost, requiresHostConfirmation } from "./src/host-confirmation.js";
import { createWorkbenchHost } from "./src/workbench-host.js";
import { createSettingsView } from "./src/settings-view.js";
import { createModulesView } from "./src/modules-view.js";
import { createCharactersView } from "./src/characters-view.js";
import { CHARACTER_THEMES, displayMode, readDisplayPreferences, writeDisplayPreferences } from "./src/display-state.js";
import { createCapabilityPage } from "./src/capability-page.js";
import { createQualityRoutingView, normalizeQualityRule } from "./src/quality-routing-view.js";
import { createBenefitsController, createBenefitsState, renderBenefitsSection } from "./src/benefits-view.js";
import { createConsultationView, consultationNotice } from "./src/consultation-view.js";
import { browserLinkSite, createEmbeddedBrowserController } from "./src/embedded-browser-view.js";

const QUALITY_ROUTING_STYLESHEET = new URL("./src/quality-routing.css", import.meta.url).href;
const CONSULTATION_STYLESHEET = new URL("./src/consultation.css", import.meta.url).href;
const WORKBENCH_STYLESHEET = new URL("./src/workbench-v2.css", import.meta.url).href;
const companionWindow = new URLSearchParams(window.location.search).get("view") === "companion";

function ensureQualityRoutingStylesheet() {
  if (document.querySelector('link[data-quality-routing-styles]')) return;
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = QUALITY_ROUTING_STYLESHEET;
  stylesheet.dataset.qualityRoutingStyles = "";
  document.head.append(stylesheet);
}

function ensureConsultationStylesheet() {
  if (document.querySelector('link[data-consultation-styles]')) return;
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = CONSULTATION_STYLESHEET;
  stylesheet.dataset.consultationStyles = "";
  document.head.append(stylesheet);
}

const AGENT_SESSION_PREFERENCE_KEY = "sumika.agent.active-session.v1";
const AGENT_ROUTING_PREFERENCE_KEY = "sumika.agent.routing-policy.v1";

const state = {
  activePage: companionWindow ? "Chat" : "Workspace",
  chatOpen: true,
  petChatOpen: false,
  displayBusy: false,
  displayPreferences: readDisplayPreferences(localStorage),
  overlayMode: companionWindow || ["overlay", "pet"].includes(new URLSearchParams(window.location.search).get("mode")),
  providerId: "",
  providers: [],
  providerProfiles: [],
  providerTemplates: [],
  providerDrawerOpen: false,
  providerDrawerMode: "manual",
  providerDrawerProfileId: null,
  providerBusy: null,
  providerNotice: "",
  routePricingCatalog: { schema: "route-pricing/v1", snapshots: [], errors: {}, checked_at: null },
  routePricingBusy: false,
  routePricingNotice: "",
  // Browser DOM chat accounts are a separate connection kind. Their
  // authentication state is owned by BrowserSkill named Profiles; Sumika
  // keeps only these safe projections and editable selector metadata.
  webChatAdapters: [],
  webChatProfiles: [],
  webChatDrawerOpen: false,
  webChatDrawerMode: "manual",
  webChatDrawerProfileId: null,
  webChatDrawerAdapterId: "custom",
  webChatBusy: null,
  webChatNotice: "",
  // Web Workbench is a UI projection over the runtime-neutral route bridge.
  // It never stores browser cookies, snapshots, or full route context.
  webWorkbenchCatalog: { schema: "agent-route/v1", routes: [], count: 0, routable_count: 0, quota_state: "unknown" },
  webWorkbenchCatalogBusy: false,
  webWorkbenchConsultations: [],
  webWorkbenchConsultationRequests: {},
  webWorkbenchConsultationDraft: { question: "", context: "", decision_kind: "brainstorm", max_members: 3 },
  webWorkbenchWorkerDraft: { route_id: "", question: "" },
  webWorkbenchWorkerResult: null,
  webWorkbenchWorkerDispatchId: "",
  webWorkbenchManualDrafts: {},
  webWorkbenchManualResults: {},
  webWorkbenchManualAttempts: {},
  webWorkbenchPendingResults: [],
  webWorkbenchSelectedProfileId: "",
  webWorkbenchNotice: "",
  webWorkbenchBusy: null,
  webWorkbenchAutoRefresh: false,
  webWorkbenchPollTimer: null,
  webWorkbenchPollInFlight: false,
  providerImportRaw: "",
  providerImportFilename: "",
  providerImportPreview: null,
  ccsManifest: null,
  ccsReport: null,
  ccsBusy: false,
  plugins: [],
  modules: [],
  moduleCatalogStatus: "loading",
  audioStatus: { permissions: [], capabilities: [] },
  visionStatus: { permissions: [], sources: [] },
  memories: [],
  snapshots: [],
  tasks: [],
  benefits: createBenefitsState(),
  qualityRouting: {
    settings: null,
    catalog: null,
    settingsBusy: false,
    settingsNotice: "",
    refresh: null,
    refreshBusy: false,
    refreshNotice: "",
    selection: null,
    planningConfirmed: false,
    activeScope: null,
    tasks: [],
    selectedTaskId: null,
    goalDraft: "",
    allowedCandidateIds: [],
    externalAllowed: false,
    budgetOverride: false,
    budgetDraft: { multiplier: "2", extra_cny: "5" },
    busy: false,
    notice: "",
    requestGeneration: 0,
  },
  consultation: { visible: false, focused: true, status: "未打开", notice: "", busy: false, token: "", attached: false, ready: false, takeover: false, activeAttemptId: "", recoverableAttemptId: "", manualDraft: "", pollTimer: null, pollInFlight: false, generation: 0 },
  agentTasks: [],
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
  characterCreating: false,
  portalPanelOpen: false,
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
  agentStatus: { state: "unavailable", ready: false },
  agentDiagnostics: null,
  agentDiagnosticsBusy: false,
  agentProvider: { state: "unconfigured", ready: false },
  browserStatus: { state: "policy-only", ready: false },
  browserProfiles: [],
  browserSessions: [],
  browserTabs: {},
  browserActiveTabs: {},
  browserObservations: {},
  browserSnapshots: {},
  browserDiagnostics: {},
  browserNavigationDrafts: {},
  browserTabDrafts: {},
  browserNavigationPending: {},
  browserTabCreatePending: {},
  browserDeveloperMode: false,
  browserDownloads: [],
  agentCapabilities: { skills: [], mcp: { status: "not-observed", entries: [] }, subagents: [], commands: [] },
  agentMcpCatalog: { status: "not-observed", entries: [], catalog_available: false },
  agentMcpCatalogBusy: false,
  agentSkillsCatalog: [],
  agentSkillsBusy: null,
  agentSkillsPath: "",
  agentSkillsNotice: "",
  agentPresets: [],
  agentPresetAuthorable: false,
  agentPresetHasDocument: false,
  agentPresetId: "",
  agentPresetCopySource: "",
  agentPresetCopyId: "",
  agentPresetCopyName: "",
  agentPresetValidation: {},
  agentMcpPresetId: "",
  agentMcpConfigurations: [],
  agentMcpClientInstalled: false,
  agentMcpClientVersion: "",
  agentMcpCredentialFieldsSupported: false,
  agentMcpCredentialStorage: "unavailable",
  agentMcpPendingSecret: "",
  agentMcpDraft: {
    server_name: "",
    transport: "stdio",
    enabled: false,
    command: "",
    args_text: "[]",
    cwd: "",
    url: "",
    tool_call_timeout_ms: 60000,
    credential_enabled: false,
    credential_present: false,
    credential_target: "",
    credential_prefix: "",
    credential_rotate: false,
    credential_configured: false,
    credential_loaded_at_launch: false,
    credential_restart_required: false,
  },
  agentMcpPreview: null,
  agentSessions: [],
  agentSessionSearchQuery: "",
  agentSessionSearchResults: null,
  agentSessionSearchBusy: false,
  agentSessionSearchNotice: "",
  agentSessionRenameDraft: "",
  agentWorkspaces: [],
  agentWorkspaceId: "",
  agentWorkspacePath: "",
  workspaceRuntimePath: "",
  workspaceRuntimeInspect: null,
  workspaceRuntimeCheckpoints: [],
  workspaceRuntimeSelectedId: null,
  workspaceRuntimeDiff: null,
  workspaceRuntimePreview: null,
  workspaceRuntimeCheckpointName: "",
  workspaceRuntimeWorktreeDestination: "",
  workspaceRuntimeWorktreeBranch: "",
  workspaceRuntimeWorktreePreview: null,
  workspaceRuntimeCommitMessage: "",
  workspaceRuntimeCommitPreview: null,
  workspaceRuntimeBusy: null,
  workspaceRuntimeNotice: "",
  agentSessionId: null,
  agentSnapshot: null,
  agentHistoryBeforeSeq: null,
  agentHistoryHasMore: false,
  agentHistoryPagingStarted: false,
  agentHistoryLoading: false,
  agentQueue: { known: false, items: [], hidden_context_count: 0, updated_at: null },
  agentQueueDrafts: {},
  agentModels: { current: {}, routable: false, groups: [], failures: [] },
  agentRoutingMode: "manual",
  agentRoutingBudgetPolicy: "prefer-free",
  agentRoutingDecision: null,
  agentRoutingDecisionKey: "",
  agentRoutingApprovedKey: "",
  agentRoutingPendingKey: "",
  agentRoutingBusy: false,
  agentRoutingNotice: "",
  agentModelPolicyCatalog: null,
  agentModelPolicyQuota: null,
  agentModelPolicyBusy: false,
  agentModelPolicyLoadedAt: 0,
  agentInteractions: [],
  agentInteractionDrafts: {},
  agentSubagents: [],
  agentSubagentHistories: {},
  agentGoal: null,
  agentEvents: [],
  agentMode: "plan",
  agentPromptDraft: "",
  agentPromptAttachments: [],
  agentAttachmentNotice: "",
  agentAttachmentPreviews: {},
  agentAttachmentBusy: null,
  agentBusy: null,
  agentNotice: "",
  agentSyncing: false,
  agentSyncQueued: false,
  evolutionRegistry: [],
  capabilityCatalog: null,
  capabilityCatalogBusy: false,
  capabilityCatalogNotice: "",
};

/* Per-character accent: one CSS variable drives every derived tint via
   color-mix, so a character card's theme color reskins the whole shell. */
function applyCharacterTheme() {
  const accent = CHARACTER_THEMES[state.displayPreferences.theme] || String(currentCharacter().config?.theme?.accent || "").trim();
  const root = document.documentElement;
  if (/^#[0-9a-fA-F]{6}$|^#[0-9a-fA-F]{3}$/.test(accent)) {
    root.style.setProperty("--accent", accent);
  } else {
    root.style.removeProperty("--accent");
  }
}

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
let agentSyncTimer = null;
let agentSyncInFlight = false;
let agentWorkspaceRequestGeneration = 0;
let agentSessionGeneration = 0;
let agentCapabilitiesRequestGeneration = 0;
let agentSnapshotRequestGeneration = 0;
const AGENT_SYNC_INTERVAL_MS = 15_000;

const {
  renderSceneTopbar,
  renderSceneDock,
  renderSceneChat,
  renderDrawer,
} = createSceneView({
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
});

function invalidateAgentWorkspaceRequests() {
  agentWorkspaceRequestGeneration += 1;
}

function setAgentSessionId(value) {
  const next = value || null;
  if (state.agentSessionId !== next) {
    agentSessionGeneration += 1;
    invalidateAgentWorkspaceRequests();
  }
  state.agentSessionId = next;
}

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

function qualityRoutingScope() {
  return Object.freeze({ assistantId: String(state.selectedCharacter || "sumika"), sessionId: String(currentSessionId() || "default") });
}

function sameQualityRoutingScope(left, right) {
  return Boolean(left && right && left.assistantId === right.assistantId && left.sessionId === right.sessionId);
}

function qualityRoutingScopeIsCurrent(scope, generation) {
  return sameQualityRoutingScope(scope, qualityRoutingScope()) && generation === state.qualityRouting.requestGeneration;
}

function invalidateQualityRoutingScope() {
  const quality = state.qualityRouting;
  quality.requestGeneration += 1;
  quality.activeScope = null;
  quality.tasks = [];
  quality.selectedTaskId = null;
  quality.notice = "";
  quality.selection = null;
  quality.settings = null;
  quality.planningConfirmed = false;
  benefitsView.syncScope();
}

function syncActiveSession() {
  if (!state.sessions.some((item) => item.id === state.activeSessionId)) {
    state.activeSessionId = state.sessions[0]?.id || "default";
    invalidateQualityRoutingScope();
  }
}

function providerName() {
  const llm = state.modules.find((item) => item.id === "llm");
  const profile = webChatProfileForModule() || activeProviderProfile() || llm?.profile;
  if (profile?.name) return profile.name;
  if (!state.providerProfiles.length && !state.webChatProfiles.length) return "未配置 Provider";
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
  if (String(llm?.implementation_id || "").startsWith("web-chat:")) return null;
  const profileId = llm?.profile_id || llm?.config?.profile_id;
  return state.providerProfiles.find((profile) => profile.id === profileId) || state.providerProfiles.find((profile) => profile.active) || null;
}

function isWebChatProfile(profile) {
  return Boolean(profile?.adapter_id && String(profile.id || "").startsWith("web-chat-"));
}

function webChatProfileForModule(module = currentLlmModule()) {
  const implementation = String(module?.implementation_id || "");
  if (!implementation.startsWith("web-chat:")) return null;
  const suffix = implementation.slice("web-chat:".length);
  const profileId = module?.profile_id || module?.config?.profile_id || suffix;
  if (profileId !== suffix) return null;
  return state.webChatProfiles.find((profile) => profile.id === profileId)
    || (module?.profile?.id === profileId ? module.profile : null);
}

function webChatReady(profile) {
  return Boolean(
    profile
    && profile.status === "ready"
    && profile.auth_state === "authorized"
    && profile.auto_chat_enabled === true,
  );
}

function activeLlmConnection() {
  const web = webChatProfileForModule();
  if (web) return { kind: "web-chat", profile: web };
  const apiProfile = activeProviderProfile();
  return apiProfile ? { kind: "api", profile: apiProfile } : null;
}

function hasLlmConnections() {
  return state.providerProfiles.some((profile) => !profile.archived_at)
    || state.webChatProfiles.some((profile) => !profile.archived_at);
}

function webChatStatusLabel(profile) {
  if (profile?.archived_at || profile?.status === "archived") return "已归档";
  if (profile?.status === "ready" && profile?.auth_state === "authorized" && profile?.auto_chat_enabled) return "可用";
  if (profile?.status === "draft") return "草稿";
  if (profile?.auth_state === "needs-auth") return "需要登录";
  if (profile?.status === "unavailable") return "未就绪";
  return "待检查";
}

function webChatAdapter(adapterId) {
  return state.webChatAdapters.find((item) => item.id === adapterId) || null;
}

function webChatConfig(profile) {
  const value = profile?.config;
  return value && typeof value === "object" ? value : {};
}

function webChatArrayText(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === "string" && item.trim()).join("\n") : "";
}

function webChatProfileModel(profile) {
  return webChatConfig(profile).model_id || "网页会话";
}

function llmReady() {
  const module = currentLlmModule();
  const webProfile = webChatProfileForModule(module);
  if (webProfile) return Boolean(state.connected && module?.enabled && webChatReady(webProfile));
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
  const benefitsScopeChanged = benefitsView.syncScope();
  viewState.capture();
  const scene = projectSceneState(state);
  rememberChatScrollPreference();
  rememberFocusedAgentQueueDraft();
  if (state.activePage !== "Chat" && activeAudioCapture) {
    discardAudioCapture(activeAudioCapture);
    activeAudioCapture = null;
    state.voiceRecording = false;
  }
  applyCharacterTheme();
  if (state.connected && state.selectedCharacter !== sharedAssistantId) {
    sharedAssistantId = state.selectedCharacter;
    localStorage.setItem("sumika:active-assistant:v1", sharedAssistantId);
  }
  if (!state.overlayMode) {
    disposeVrmViewer();
    document.body.dataset.sumikaMode = "workspace";
    app.innerHTML = workbenchHost.render();
    if (workbenchHost.model.notice) {
      const notice = document.createElement("div");
      notice.className = "wv2-host-notice";
      notice.setAttribute("role", "status");
      notice.textContent = workbenchHost.model.notice;
      app.prepend(notice);
    }
    bindEvents();
    workbenchHost.bind(app);
    if (benefitsScopeChanged && app.querySelector("[data-benefits]")) void benefitsView.loadStatus();
    viewState.restore(`work:${state.selectedCharacter}:${currentSessionId()}`);
    if (state.consultation.visible) requestAnimationFrame(() => void syncConsultationBounds());
    requestAnimationFrame(() => void embeddedView.syncBounds().catch(() => {}));
    return;
  }
  const avatarSurfaceSelector = "[data-avatar-signature]";
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
    app.innerHTML = renderOverlay() + '<div class="cw-companion-controls"><button type="button" data-companion-size="compact">小窗</button><button type="button" data-companion-size="panorama">全景</button><button type="button" data-companion-size="fullscreen">全屏</button><button type="button" data-chat-clear>清屏</button><button type="button" data-chat-history>之前对话</button></div>';
    if (preserveAvatarSurface) {
      document.querySelector(".desktop-overlay-avatar")?.replaceWith(previousAvatarSurface);
      previousAvatarSurface.className = "desktop-overlay-avatar";
      previousAvatarSurface.setAttribute("data-overlay-drag-surface", "");
      updatePreservedAvatarSurface(previousAvatarSurface);
    }
    bindEvents();
    viewState.restore(`pet:${state.selectedCharacter}`);
    if (!preserveAvatarSurface) queueVrmViewerMount();
    updateSceneVisibility();
    return;
  }
  const drawer = scene.drawer;
  app.innerHTML = `
    <div class="scene-shell ${drawer ? "drawer-open" : ""} ${state.chatOpen ? "" : "chat-collapsed"}" data-drawer="${drawer || ""}">
      <div class="scene-backdrop"><div class="scene-backdrop-image"></div></div>
      <div class="scene-viewport">
        <div class="avatar-stage" data-avatar-signature="${escapeHtml(avatarRenderSignature())}" aria-label="Avatar 预览">
          ${scene.avatarVisible ? renderAvatarPresenter() : `<div class="avatar-hidden-state" role="status"><span>Avatar 已隐藏</span></div>`}
        </div>
        <div class="scene-caption"><span>WITH SUMIKA</span><p>今天，也在一起。</p><small>固定房间 · ${scene.sending ? "回复中" : "陪伴"}</small></div>
        <div class="scene-note"><button class="text-button" type="button" data-avatar-toggle aria-label="${state.avatarVisible ? "隐藏 Avatar 预览" : "显示 Avatar 预览"}" aria-pressed="${state.avatarVisible}">${state.avatarVisible ? "隐藏角色" : "显示角色"}</button><span>${state.connected ? "核心已连接" : "核心未连接"}</span></div>
      </div>
      ${renderSceneTopbar()}
      ${renderSceneDock()}
      ${renderSceneChat()}
      <div class="character-theme-options" aria-label="角色主题色">${Object.entries(CHARACTER_THEMES).map(([theme, color]) => `<button type="button" class="theme-swatch" data-character-theme="${theme}" aria-label="${({ sakura: "樱粉", sage: "草绿", blue: "青蓝", berry: "莓红" })[theme]}主题" aria-pressed="${state.displayPreferences.theme === theme}" style="--swatch:${color}"></button>`).join("")}<button class="text-button" type="button" data-character-theme="auto">跟随角色</button></div>
      ${renderPortalPanel()}
      ${renderDrawer(drawer)}
    </div>`;
  if (preserveAvatarSurface) {
    document.querySelector(".avatar-stage")?.replaceWith(previousAvatarSurface);
    previousAvatarSurface.className = "avatar-stage";
    previousAvatarSurface.removeAttribute("data-overlay-drag-surface");
    updatePreservedAvatarSurface(previousAvatarSurface);
  }
  bindEvents();
  applyAppearance();
  viewState.restore(`${state.activePage}:${state.selectedCharacter}`);
  if (state.consultation.visible) requestAnimationFrame(() => void syncConsultationBounds());
  requestAnimationFrame(() => void embeddedView.syncBounds().catch(() => {}));
  if (!preserveAvatarSurface) queueVrmViewerMount();
  scheduleScrollMessages();
  updateSceneVisibility();
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
      roomEnabled: true,
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
      updateSceneVisibility();
      element.closest(".avatar-placeholder")?.classList.add("vrm-live");
    })
    .catch((error) => {
      if (element.isConnected && generation === state.vrmMountGeneration) {
        element.dataset.vrmStatus = "error";
        element.dataset.vrmError = error?.message || "VRM renderer unavailable";
        element.closest(".avatar-placeholder")?.classList.add("vrm-error");
        const notice = document.createElement("div");
        notice.className = "vrm-renderer-status";
        notice.setAttribute("role", "alert");
        notice.textContent = `角色加载失败：${element.dataset.vrmError}`;
        element.replaceChildren(notice);
      }
    });
}

function renderPage() {
  return pageView(state.activePage);
}

function updateSceneVisibility() {
  const appearance = readAppearance();
  state.vrmViewer?.setRoomVisible?.(!(state.overlayMode ? state.displayPreferences.transparent : appearance.backgroundImage || appearance.backgroundColor));
  state.vrmViewer?.setVisible?.(state.nativeRenderVisible !== false && !document.hidden && (state.overlayMode || state.activePage === "Chat"));
}

function renderEmptyChat() {
    if (!state.connected) {
    return '<div class="empty-chat"><span class="empty-icon">✦</span><strong>核心未连接</strong><p>启动 Sumika 核心后才能发送消息。</p></div>';
  }
  if (!hasLlmConnections()) {
    return '<div class="empty-chat"><span class="empty-icon">✦</span><strong>先配置 Provider</strong><p>Sumika 不会自动安装模型或选择连接。</p><button class="outline-button" type="button" data-page="Modules">前往模块页</button></div>';
  }
  if (!currentLlmModule()?.enabled) {
    return '<div class="empty-chat"><span class="empty-icon">✦</span><strong>LLM 已关闭</strong><p>在模块页选择已测试的连接并主动启用。</p><button class="outline-button" type="button" data-page="Modules">前往模块页</button></div>';
  }
  const webProfile = webChatProfileForModule();
  if (webProfile && !webChatReady(webProfile)) {
    return `<div class="empty-chat"><span class="empty-icon">✦</span><strong>网页聊天尚未就绪</strong><p>${escapeHtml(webChatStatusLabel(webProfile))}；请在模块页打开隔离浏览器、检查登录和授权。</p><button class="outline-button" type="button" data-page="Modules">配置网页聊天</button></div>`;
  }
  const apiProfile = activeProviderProfile() || currentLlmModule()?.profile;
  if (!webProfile && (!apiProfile || apiProfile.status !== "available")) {
    return '<div class="empty-chat"><span class="empty-icon">✦</span><strong>当前连接未就绪</strong><p>请在模块页测试真实连接；未就绪时不会生成替代回复。</p><button class="outline-button" type="button" data-page="Modules">检查连接</button></div>';
  }
  const greeting = currentPersonaConfig().greeting.trim();
  if (greeting) {
    return `<div class="empty-chat empty-chat-greeting"><span class="empty-icon">✦</span><strong>${escapeHtml(currentCharacter().name)} 的问候</strong><p>${escapeHtml(greeting).replaceAll("\n", "<br>")}</p></div>`;
  }
  return `<div class="empty-chat"><span class="empty-icon">✦</span><strong>从一个问题开始</strong><p>当前使用 ${escapeHtml(providerName())}。发送前请确认模型服务状态为“可用”。</p></div>`;
}

function renderOverlay() {
  const reply = state.messages.filter((message) => message.role === "assistant").at(-1)?.content || (state.connected ? "我在这里。" : "核心未连接");
  return `<main class="desktop-overlay-shell ${state.displayPreferences.transparent ? "pet-transparent" : ""} ${state.petChatOpen ? "" : "pet-chat-collapsed"}" aria-label="桌面 Avatar 浮窗" style="background-color: ${state.displayPreferences.transparent ? "transparent" : escapeHtml(readAppearance().backgroundColor || "")}">
    <div class="desktop-overlay-controls" data-no-drag>
      <button class="text-button" type="button" data-no-drag data-overlay-open-main>返回客户端</button>
      <button class="text-button" type="button" data-no-drag data-avatar-toggle>显示 / 隐藏角色</button>
      <button class="text-button" type="button" data-no-drag data-pet-chat aria-expanded="${state.petChatOpen}">${state.petChatOpen ? "收起聊天" : "展开聊天"}</button>
      <button class="text-button" type="button" data-no-drag data-pet-background aria-pressed="${state.displayPreferences.transparent}">${state.displayPreferences.transparent ? "显示场景" : "透明背景"}</button>
      ${isDesktopShell ? '<button class="text-button" type="button" data-no-drag data-overlay-hide title="恢复客户端并最小化，可从任务栏找回">隐藏</button>' : ""}
    </div>
    <div class="desktop-overlay-avatar" data-avatar-signature="${escapeHtml(avatarRenderSignature())}" data-overlay-drag-surface aria-label="${escapeHtml(currentCharacter().name)} Avatar，可按住模型拖动桌宠窗口">
      ${state.avatarVisible ? renderAvatarPresenter() : `<div class="avatar-hidden-state" role="status"><span>Avatar 已隐藏</span></div>`}
    </div>
    ${state.sessionNotice ? `<div class="pet-notice" role="status">${escapeHtml(state.sessionNotice)}</div>` : `<div class="pet-bubble" role="status">${escapeHtml(state.sending ? "正在回复…" : String(reply).slice(0, 54))}${!state.sending && String(reply).length > 54 ? "…" : ""}</div>`}
    ${!llmReady() ? renderEmptyChat() : ""}
    <form class="overlay-composer" id="chat-form" data-no-drag ${state.petChatOpen ? "" : "hidden inert"}>
      <textarea id="chat-input" aria-label="聊天消息" data-no-drag rows="1" placeholder="和 ${escapeHtml(currentCharacter().name)} 说点什么…" ${state.sending || !state.connected ? "disabled" : ""}>${escapeHtml(state.composerDraft)}</textarea>
      <button class="send-button" data-no-drag type="submit" ${state.sending || !llmReady() ? "disabled" : ""} aria-label="发送消息">${state.sending ? "处理中" : "发送"}</button>
    </form>
    <span class="sr-only" role="status" aria-live="polite">${state.sending ? "正在思考" : "桌宠等待互动"}</span>
  </main>`;
}

function onboarded() {
  return localStorage.getItem("sumika.onboarded.v1") === "1";
}

function markOnboarded() {
  if (!onboarded()) {
    localStorage.setItem("sumika.onboarded.v1", "1");
    render();
  }
}

function renderWelcomeCard() {
  if (onboarded() || projectSceneState(state).drawerOpen) return "";
  return `
    <aside class="welcome-card">
      <strong>欢迎来到 Sumika</strong>
      <p>从顶部进入工作台、能力、角色和设置。在「设置 → 连接与权限」配置模型后开始对话；添加能力卡片不会启用设备。</p>
      <div class="welcome-actions"><button class="small-button" type="button" data-page="Guide">查看入门指南</button><button class="ghost-button" type="button" data-onboard-dismiss>知道了</button></div>
    </aside>`;
}

/* Web portals: raw provider chat sites in their own Tauri windows, one
   persistent isolated login per site. Desktop shell only; no persona
   injection and no Agent access — these are the user's own sessions. */
const PORTALS_STORAGE_KEY = "sumika.portals.v1";
const PORTAL_PRESETS = [
  { id: "kimi", title: "Kimi", url: "https://www.kimi.com" },
  { id: "chatgpt", title: "ChatGPT", url: "https://chatgpt.com/" },
  { id: "zhipu", title: "智谱清言", url: "https://chatglm.cn" },
  { id: "deepseek", title: "DeepSeek", url: "https://chat.deepseek.com" },
  { id: "qwen", title: "通义千问", url: "https://tongyi.aliyun.com/qianwen/" },
  { id: "doubao", title: "豆包", url: "https://www.doubao.com/chat/" },
];

function readCustomPortals() {
  try {
    const value = JSON.parse(localStorage.getItem(PORTALS_STORAGE_KEY) || "[]");
    return Array.isArray(value)
      ? value.filter((item) => item && typeof item.id === "string" && typeof item.url === "string" && typeof item.title === "string")
      : [];
  } catch {
    return [];
  }
}

function writeCustomPortals(portals) {
  localStorage.setItem(PORTALS_STORAGE_KEY, JSON.stringify(portals));
}

function portalDefinitions() {
  const custom = readCustomPortals();
  const seen = new Set(PORTAL_PRESETS.map((preset) => preset.id));
  return [...PORTAL_PRESETS, ...custom.filter((item) => !seen.has(item.id))].map((site) => ({ ...site, legacy_site_id: site.id }));
}

let portalOpenSites = [];

async function refreshPortalList() {
  try {
    const entries = await invokeDesktop("portal_list");
    portalOpenSites = Array.isArray(entries) ? entries.map((entry) => entry.site_id) : [];
  } catch {
    portalOpenSites = [];
  }
  render();
}

async function togglePortal(site) {
  try {
    await embeddedView.open(site);
  } catch (error) {
    window.alert(`门户打开失败：${error.message}`);
    void refreshPortalList();
  }
}

function addCustomPortal(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const title = String(new FormData(form).get("portal_title") || "").trim();
  const url = String(new FormData(form).get("portal_url") || "").trim();
  if (!title || !url) return;
  const id = `custom-${title.replace(/[^a-zA-Z0-9]+/g, "-").toLowerCase().replace(/^-+|-+$/g, "") || Date.now().toString(36)}`.slice(0, 40);
  const portals = readCustomPortals().filter((item) => item.id !== id);
  portals.push({ id, title, url: url.startsWith("http") ? url : `https://${url}` });
  writeCustomPortals(portals);
  state.portalPanelOpen = true;
  render();
}

function renderPortalPanel() {
  return embeddedView.markup(portalDefinitions(), state.embeddedBrowser?.active === "native-consultation" ? renderConsultation() : "");
}

function renderAvatarPresenter({ compact = false } = {}) {
  const avatarModel = currentAvatarModel();
  const avatarDriver = state.avatarState?.driver || currentCharacter().config?.avatar_driver || "none";
  const presentation = currentAvatarPresentation();
  const avatarPreview = avatarPreviewUrl(avatarModel);
  const avatarSource = avatarDriver === "vrm" ? avatarModelFileUrl(avatarModel) : "";
  return `<div class="avatar-presenter avatar-position-${presentation.position}${compact ? " avatar-presenter-compact" : ""}" style="opacity:${presentation.opacity};transform:scale(${presentation.scale})">
    <div class="avatar-placeholder avatar-${escapeHtml(avatarDriver)} avatar-position-${presentation.position} ${avatarPreview ? "has-preview" : ""}">
      ${avatarSource ? `<div class="vrm-renderer" data-vrm-source="${escapeHtml(avatarSource)}" data-vrm-idle-motion="${presentation.idleMotion}" data-vrm-auto-rotate="${presentation.autoRotate}" data-vrm-rotation-speed="${presentation.rotationSpeed}" data-vrm-status="idle" aria-label="VRM Avatar 实时渲染" aria-busy="true"></div>` : ""}
      ${avatarPreview ? `<img class="avatar-preview-image" src="${escapeHtml(avatarPreview)}" alt="${escapeHtml(avatarModel?.name || "Avatar 模型")}" />` : ""}
    </div>
    ${compact ? "" : `<div class="avatar-preview-copy"><span>${escapeHtml(avatarDriverLabel(avatarDriver))}</span><strong>${escapeHtml(currentCharacter().name)}</strong><small>${escapeHtml(avatarModel?.name || "未绑定模型")} · ${escapeHtml(state.avatarState?.driver_status || "ready")}</small></div>`}
  </div>`;
}

function renderMessage(message) {
  const role = message.role === "user" ? "你" : currentCharacter().name;
  return `<article class="message ${message.role}"><div class="message-meta"><span>${escapeHtml(role)}</span><time>${formatTime(message.created_at)}</time></div><div class="message-body">${escapeHtml(message.content).replaceAll("\n", "<br>")}</div></article>`;
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

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function pricingSourceLabel(value) {
  return ({
    "direct-official": "官方定价",
    "new-api": "New API",
    pinai: "PinAI",
    manual: "手动录入",
  })[String(value || "").toLowerCase()] || "来源未知";
}

function pricingConfidenceLabel(value) {
  return ({
    official: "官方",
    published: "公开发布",
    manual: "人工录入",
    observed: "运行观测",
    low: "低可信",
    unknown: "未知",
  })[String(value || "").toLowerCase()] || "未知";
}

function formatPricingNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "未知";
  return number.toLocaleString("zh-CN", { maximumFractionDigits: 8 });
}

function routePricingSnapshotsForProfile(profileId, modelId = "") {
  const snapshots = Array.isArray(state.routePricingCatalog?.snapshots) ? state.routePricingCatalog.snapshots : [];
  return snapshots.filter((item) => item?.provider_profile_id === profileId && (!modelId || item?.model_id === modelId));
}

function pricingProviderChargeLabel(snapshot) {
  const currency = snapshot?.currency || "单位未知";
  if (snapshot?.request_price != null) return `${currency} ${formatPricingNumber(snapshot.request_price)} / 请求`;
  if (snapshot?.billing_expression) return `${currency} 动态计费`;
  const input = snapshot?.input_price_per_million;
  const output = snapshot?.output_price_per_million;
  if (input == null && output == null) return `${currency} 单价未知`;
  const parts = [];
  if (input != null) parts.push(`输入 ${formatPricingNumber(input)}`);
  if (output != null) parts.push(`输出 ${formatPricingNumber(output)}`);
  if (snapshot?.cache_read_price_per_million != null) parts.push(`缓存读 ${formatPricingNumber(snapshot.cache_read_price_per_million)}`);
  return `${currency} · ${parts.join(" · ")} / 百万 token`;
}

function pricingCashLabel(snapshot) {
  if (!snapshot?.cash_currency || snapshot?.cash_rate == null) return "现金折算未知";
  return `1 ${snapshot.currency || "站内单位"} ≈ ${formatPricingNumber(snapshot.cash_rate)} ${snapshot.cash_currency}`;
}

function pricingEvidenceLabel(snapshot) {
  const confidence = pricingConfidenceLabel(snapshot?.confidence);
  return snapshot?.fresh === false ? `已过期 · ${confidence}` : confidence;
}

function capabilityStatusLabel(status) {
  return ({
    available: "可用",
    ready: "就绪",
    healthy: "健康",
    running: "运行中",
    low: "额度较低",
    "not-applicable": "不适用",
    disabled: "已关闭",
    unconfigured: "未配置",
    draft: "草稿",
    "needs-auth": "需要登录",
    unavailable: "不可用",
    error: "错误",
    discovered: "已发现",
    changed: "有变化",
    revoked: "已撤销",
    invalid: "无效",
    configured: "已配置",
    observed: "已观察",
    "not-exposed": "未暴露",
    "not-installed": "未安装",
    "awaiting-extension": "等待扩展",
    "policy-only": "仅策略",
    declared: "已声明",
    preview: "预览",
    approved: "已批准",
    rejected: "已拒绝",
    "session-scoped": "按会话",
  })[status] || status || "未知";
}

function capabilitySourceLabel(source) {
  return ({
    builtin: "内置",
    control: "模块控制",
    provider: "Provider 适配器",
    "provider-profile": "连接档案",
    plugin: "插件",
    skill: "Skill",
    harness: "Harness",
    "harness-model": "Harness 模型",
    "browser-runtime": "浏览器运行时",
    mcp: "MCP",
    "external-process": "外部软件",
    "web-chat": "网页聊天",
  })[source] || source || "未知来源";
}

function capabilityLocationLabel(location) {
  return ({ local: "本地", cloud: "云端", mixed: "混合", unknown: "位置未知" })[location] || location || "位置未知";
}

function capabilityEntryStatusClass(status) {
  return String(status || "unknown").replace(/[^a-z0-9-]/gi, "-").slice(0, 40) || "unknown";
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

function providerModelEntries(profile) {
  const rows = profile?.config?.models;
  if (Array.isArray(rows) && rows.length) return rows;
  const fallback = String(profile?.config?.model || "").trim();
  return fallback ? [{ id: fallback, name: fallback, enabled: true, health_state: "unknown" }] : [];
}

function providerModelSummary(profile) {
  const rows = providerModelEntries(profile);
  const enabled = rows.filter((row) => row?.enabled !== false).map((row) => String(row?.id || "").trim()).filter(Boolean);
  if (!enabled.length) return "未填写模型";
  const shown = enabled.slice(0, 2).join("、");
  return enabled.length > 2 ? `${shown} 等 ${enabled.length} 个模型` : shown;
}

function providerProfileStatusLabel(status) {
  return ({ available: "可用", unavailable: "未就绪", draft: "草稿", archived: "已归档" })[status] || status || "未知";
}

function moduleStatusLabel(module) {
  if (module.status === "disabled") return "未启用";
  if (module.status === "unconfigured") return "待配置";
  if (module.status === "preview") return "预览";
  if (module.status === "available") return "可用";
  if (module.status === "error") return "未就绪";
  return "就绪";
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
  if (budget && budget.available === false) return "预算未提供";
  const tokens = Number(budget.token_limit) || 0;
  const seconds = Number(budget.time_limit_seconds) || 0;
  if (!tokens && !seconds) return "无预算消耗";
  return `${tokens ? `${tokens} tokens` : "不限 token"}${seconds ? ` · ${seconds}s` : ""}`;
}

function finiteAgentMetric(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function formatAgentMetricNumber(value) {
  const number = finiteAgentMetric(value);
  if (number === null) return "-";
  return Number.isInteger(number) ? number.toLocaleString("zh-CN") : number.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function agentMetricValue(source, key) {
  if (!source || typeof source !== "object") return null;
  return finiteAgentMetric(source[key]);
}

function formatAgentTokenUsage(usage = {}) {
  const fields = [
    ["uncachedInputTokens", "输入"],
    ["outputTokens", "输出"],
    ["cacheReadTokens", "缓存读"],
    ["cacheWriteTokens", "缓存写"],
  ];
  const parts = fields
    .map(([key, label]) => {
      const value = agentMetricValue(usage, key);
      return value === null ? "" : `${label} ${formatAgentMetricNumber(value)} token`;
    })
    .filter(Boolean);
  return parts.join(" · ");
}

function formatAgentContextUsage(context = {}) {
  const projected = agentMetricValue(context, "projectedTokens");
  const pressure = agentMetricValue(context, "pressureTokens");
  const window = agentMetricValue(context, "contextWindow");
  const parts = [];
  if (projected !== null && window !== null && window > 0) {
    const percent = Math.min(100, (projected / window) * 100);
    parts.push(`${formatAgentMetricNumber(projected)} / ${formatAgentMetricNumber(window)} token (${percent.toFixed(1)}%)`);
  } else if (projected !== null) {
    parts.push(`${formatAgentMetricNumber(projected)} token`);
  } else if (window !== null) {
    parts.push(`窗口 ${formatAgentMetricNumber(window)} token`);
  }
  if (pressure !== null) parts.push(`压力 ${formatAgentMetricNumber(pressure)} token`);
  return parts.join(" · ");
}

function formatAgentTaskUsage(metrics = {}) {
  const stats = metrics?.stats || {};
  const context = metrics?.context || {};
  const usage = metrics?.token_usage || {};
  const parts = [];
  const turns = agentMetricValue(stats, "turns");
  const steps = agentMetricValue(stats, "steps");
  const output = agentMetricValue(usage, "outputTokens") ?? agentMetricValue(stats, "outputTokens") ?? agentMetricValue(stats, "decodeTokens");
  const input = agentMetricValue(usage, "uncachedInputTokens");
  const cacheRead = agentMetricValue(usage, "cacheReadTokens");
  const cacheWrite = agentMetricValue(usage, "cacheWriteTokens");
  const projected = agentMetricValue(context, "projectedTokens");
  if (turns !== null) parts.push(`${formatAgentMetricNumber(turns)} turn`);
  if (steps !== null) parts.push(`${formatAgentMetricNumber(steps)} step`);
  if (output !== null) parts.push(`${formatAgentMetricNumber(output)} 输出 token`);
  if (input !== null) parts.push(`${formatAgentMetricNumber(input)} 输入 token`);
  if (cacheRead !== null) parts.push(`${formatAgentMetricNumber(cacheRead)} 缓存读`);
  if (cacheWrite !== null) parts.push(`${formatAgentMetricNumber(cacheWrite)} 缓存写`);
  if (projected !== null) parts.push(`${formatAgentMetricNumber(projected)} 上下文 token`);
  const elapsed = (agentMetricValue(stats, "llmMs") || 0) + (agentMetricValue(stats, "toolMs") || 0);
  if (elapsed) parts.push(`${(elapsed / 1000).toFixed(2)}s`);
  return parts.join(" · ") || "暂无运行统计";
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

/* Appearance: one local-only record (solid color or a local image). Nothing
   leaves the machine; video/web dynamic wallpapers are a later layer. */
const APPEARANCE_STORAGE_KEY = "sumika.appearance.v1";
const APPEARANCE_SWATCHES = [
  { id: "", label: "默认房间", value: "" },
  { id: "night-violet", label: "暗紫", value: "#171326" },
  { id: "deep-forest", label: "墨绿", value: "#12211d" },
  { id: "ember", label: "暖赭", value: "#241519" },
  { id: "abyss", label: "渊青", value: "#0f1d26" },
];

function readAppearance() {
  try {
    const value = JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function writeAppearance(value) {
  localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(value || {}));
}

function applyAppearance() {
  const shell = document.querySelector(".scene-shell");
  if (!shell) return;
  const backdrop = shell.querySelector(".scene-backdrop");
  if (!backdrop) return;
  const appearance = readAppearance();
  backdrop.style.backgroundImage = "";
  backdrop.style.backgroundColor = "";
  if (appearance.backgroundImage) {
    backdrop.style.backgroundImage = `url("${appearance.backgroundImage}")`;
    backdrop.style.backgroundSize = "cover";
    backdrop.style.backgroundPosition = "center";
  } else if (appearance.backgroundColor) {
    backdrop.style.background = appearance.backgroundColor;
  }
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

function agentRuntimeLabel(status = state.agentStatus) {
  const id = String(status?.runtime_id || "").trim().toLowerCase();
  if (id === "dsh") return "DSH";
  if (!id && status?.version && status?.commit) return "DSH";
  if (id === "unavailable" || !id) return "Agent Runtime";
  return id;
}

function agentRuntimePreferenceId(status = state.agentStatus) {
  const id = String(status?.runtime_id || "").trim().toLowerCase();
  if (id) return id;
  return status?.version && status?.commit ? "dsh" : "";
}

function readAgentSessionPreference() {
  try {
    const value = JSON.parse(window.localStorage.getItem(AGENT_SESSION_PREFERENCE_KEY) || "null");
    const runtimeId = String(value?.runtime_id || "").trim().toLowerCase();
    const sessionId = String(value?.session_id || "").trim();
    if (!runtimeId || runtimeId.length > 80 || !sessionId || sessionId.length > 160) return null;
    if (/\p{Cc}/u.test(runtimeId) || /\p{Cc}/u.test(sessionId)) return null;
    return { runtime_id: runtimeId, session_id: sessionId };
  } catch {
    return null;
  }
}

function rememberAgentSession(sessionId) {
  const runtimeId = agentRuntimePreferenceId();
  const value = String(sessionId || "").trim();
  if (!runtimeId || !value || value.length > 160 || /\p{Cc}/u.test(value)) return;
  try {
    window.localStorage.setItem(AGENT_SESSION_PREFERENCE_KEY, JSON.stringify({ runtime_id: runtimeId, session_id: value }));
  } catch {
    // Session continuity is best-effort when browser storage is unavailable.
  }
}

function clearAgentSessionPreference() {
  try {
    window.localStorage.removeItem(AGENT_SESSION_PREFERENCE_KEY);
  } catch {
    // An unavailable preference store must not block the Agent runtime.
  }
}

const AGENT_ROUTING_MODES = new Set(["manual", "recommendation-then-confirmation", "automatic"]);
const AGENT_ROUTING_BUDGETS = new Set(["prefer-free", "free-only", "allow-paid", "no-paid"]);

function readAgentRoutingPreference() {
  try {
    const value = JSON.parse(window.localStorage.getItem(AGENT_ROUTING_PREFERENCE_KEY) || "null");
    const mode = String(value?.mode || "manual").trim().toLowerCase();
    const budget = String(value?.budget_policy || "prefer-free").trim().toLowerCase();
    return {
      mode: AGENT_ROUTING_MODES.has(mode) ? mode : "manual",
      budget_policy: AGENT_ROUTING_BUDGETS.has(budget) ? budget : "prefer-free",
    };
  } catch {
    return { mode: "manual", budget_policy: "prefer-free" };
  }
}

function rememberAgentRoutingPreference() {
  try {
    window.localStorage.setItem(AGENT_ROUTING_PREFERENCE_KEY, JSON.stringify({
      mode: AGENT_ROUTING_MODES.has(state.agentRoutingMode) ? state.agentRoutingMode : "manual",
      budget_policy: AGENT_ROUTING_BUDGETS.has(state.agentRoutingBudgetPolicy) ? state.agentRoutingBudgetPolicy : "prefer-free",
    }));
  } catch {
    // Routing preferences are best effort and must not block a turn.
  }
}

function resetAgentRoutingDecision() {
  state.agentRoutingDecision = null;
  state.agentRoutingDecisionKey = "";
  state.agentRoutingApprovedKey = "";
  state.agentRoutingPendingKey = "";
  state.agentRoutingNotice = "";
}

function routingModeLabel(mode) {
  return ({
    manual: "手动",
    "recommendation-then-confirmation": "推荐后确认",
    automatic: "自动",
  })[mode] || "手动";
}

function routingBudgetLabel(policy) {
  return ({
    "prefer-free": "优先免费 / 本地",
    "free-only": "仅免费 / 本地",
    "allow-paid": "允许付费（仍需确认）",
    "no-paid": "禁止付费",
  })[policy] || "优先免费 / 本地";
}

function routingTaskKey(text, mode) {
  const attachments = supportedAgentPromptAttachments().map((item) => `${item.name || "image"}:${item.bytes || 0}`).join("|");
  return JSON.stringify({
    session: state.agentSessionId || "new",
    text: String(text || "").slice(0, 4000),
    mode: effectiveAgentMode(),
    routing: mode,
    budget: state.agentRoutingBudgetPolicy,
    attachments,
  });
}

function agentRoutingRequest(text, requestedMode, approved = false) {
  const policyMode = state.agentRoutingMode;
  if (!AGENT_ROUTING_MODES.has(policyMode) || policyMode === "manual") return null;
  const config = {
    task_kind: requestedMode === "plan" ? "plan" : "code",
    task_text: String(text || "").slice(0, 4000),
    budget_policy: AGENT_ROUTING_BUDGETS.has(state.agentRoutingBudgetPolicy) ? state.agentRoutingBudgetPolicy : "prefer-free",
    confirmation_mode: policyMode,
  };
  if (approved) config.approved = true;
  return config;
}

function agentSupports(capability) {
  const values = state.agentStatus?.runtime_capabilities;
  if (Array.isArray(values)) return values.includes(capability);
  // Compatibility with a Core predating capability discovery.
  if (capability === "readonly") return false;
  return state.agentStatus?.runtime_id === "dsh" || Boolean(state.agentStatus?.version && state.agentStatus?.commit);
}

function effectiveAgentMode() {
  const mode = ["plan", "execute", "readonly"].includes(state.agentMode) ? state.agentMode : "execute";
  if (mode === "plan" && !agentPlanModeAvailable()) return "execute";
  if (mode === "readonly" && !agentSupports("readonly")) return "execute";
  return mode;
}

function agentPlanModeAvailable() {
  if (!agentSupports("plan")) return false;
  if (!state.agentSessionId) return false;
  const commands = state.agentCapabilities?.commands;
  if (commands?.available !== true || !Array.isArray(commands.entries)) return false;
  return commands.entries.some((entry) => {
    const name = typeof entry === "string" ? entry : entry?.name || entry?.id || entry?.command;
    return String(name || "").replace(/^\//, "").trim().toLowerCase() === "plan";
  });
}

function supportedAgentPromptAttachments() {
  if (!agentSupports("attachments") || !Array.isArray(state.agentPromptAttachments)) return [];
  return state.agentPromptAttachments;
}

function skillCatalogStatusLabel(status) {
  return ({ discovered: "待批准", changed: "哈希已变化", approved: "已批准", revoked: "已撤销", invalid: "不可读" })[status] || status || "未知";
}

function mcpCatalogStatusLabel(status) {
  return ({ available: "Runtime 在线", configured: "已配置", observed: "已观察", "not-exposed": "未暴露目录", unavailable: "不可用", rejected: "被拒绝", "not-observed": "尚未观察" })[status] || status || "未知";
}

function agentRetryState(snapshot) {
  const stateValue = String(snapshot?.state || "").trim().toLowerCase();
  const retryable = ["error", "failed", "failure", "cancelled", "canceled", "aborted", "interrupted", "stopped"].includes(stateValue);
  if (!retryable || !agentSupports("retry")) return { retryable: false, imageTarget: false, missingTarget: false };
  const messages = Array.isArray(snapshot?.messages) ? snapshot.messages : [];
  const target = [...messages].reverse().find((message) => message?.role === "user");
  if (!target) return { retryable: true, imageTarget: false, missingTarget: true };
  const attachments = Array.isArray(target.attachments) ? target.attachments : [];
  return {
    retryable: true,
    imageTarget: attachments.length > 0,
    missingTarget: !String(target.content || "").trim() && attachments.length === 0,
  };
}

function selectedAgentWorkspace() {
  return state.agentWorkspaces.find((workspace) => workspace.id === state.agentWorkspaceId) || null;
}

function currentAgentSessionWorkspace() {
  if (!state.agentSessionId) return null;
  return state.agentWorkspaces.find((workspace) => (workspace.session_ids || []).includes(state.agentSessionId)) || null;
}

function agentWorkspaceForPrompt() {
  return state.agentSessionId ? currentAgentSessionWorkspace() : selectedAgentWorkspace();
}

function agentPromptCanSend(status, hasContent, mode) {
  if (!status.ready || !hasContent || state.agentBusy) return false;
  if (!agentSupports("workspaces")) return true;
  if (!state.agentSessionId) return Boolean(selectedAgentWorkspace());
  return Boolean(currentAgentSessionWorkspace());
}

function workspaceRuntimePath() {
  const selected = state.agentWorkspaces.find((workspace) => workspace.id === state.agentWorkspaceId);
  return String(state.workspaceRuntimePath || selected?.path || state.agentWorkspacePath || "").trim();
}

function workspaceRuntimeStatusLabel(workspace) {
  if (!workspace) return "尚未检查";
  const counts = workspace.status_counts || {};
  const changed = Number(workspace.total_file_count ?? workspace.file_count ?? 0);
  if (!workspace.dirty) return "干净";
  const details = Object.entries(counts).map(([key, value]) => `${key} ${value}`).join(" · ");
  return `${changed} 项变更${details ? ` · ${details}` : ""}`;
}

function modelPolicyCostLabel(value) {
  return ({
    local: "本地",
    "free-limited": "免费额度",
    "paid-low": "低价付费",
    "paid-high": "高价付费",
    unknown: "成本未知",
  })[String(value || "").toLowerCase()] || "成本未知";
}

function formatCostRange(minimum, maximum, currency) {
  if (minimum == null && maximum == null) return "未知";
  const low = minimum == null ? maximum : minimum;
  const high = maximum == null ? minimum : maximum;
  const unit = currency || "单位未知";
  if (Number(low) === Number(high)) return `${unit} ${formatPricingNumber(low)}`;
  return `${unit} ${formatPricingNumber(low)}–${formatPricingNumber(high)}`;
}

function modelPolicyLocationLabel(value) {
  return ({ local: "本地处理", cloud: "云端处理", mixed: "混合处理" })[String(value || "").toLowerCase()] || "位置未知";
}

function modelPolicyHealthLabel(entry) {
  if (entry?.routable === true) return "可用";
  const auth = String(entry?.auth_state || "").toLowerCase();
  const quota = String(entry?.quota_state || "").toLowerCase();
  const health = String(entry?.health_state || "").toLowerCase();
  if (auth === "needs-auth") return "需要认证";
  if (["exhausted", "expired", "blocked"].includes(quota)) return "额度不可用";
  if (health === "unavailable" || health === "error") return "连接不可用";
  if (entry?.requires_browser) return "需浏览器授权";
  return "未就绪";
}

function modelPolicyQuotaFor(routeId) {
  const snapshots = Array.isArray(state.agentModelPolicyCatalog?.quotas)
    ? state.agentModelPolicyCatalog.quotas
    : [];
  return snapshots.find((item) => item?.route_id === routeId)
    || (Array.isArray(state.agentModelPolicyQuota?.snapshots)
      ? state.agentModelPolicyQuota.snapshots.find((item) => item?.route_id === routeId)
      : null);
}

function modelPolicyQuotaLabel(snapshot) {
  if (!snapshot) return "额度未观测";
  const stateLabel = ({
    available: "额度可用",
    low: "额度较低",
    exhausted: "额度已用尽",
    expired: "额度已过期",
    "needs-auth": "额度需认证",
    blocked: "额度被阻断",
    unknown: "额度未知",
  })[snapshot.state] || "额度未知";
  const remaining = snapshot.remaining_min != null
    ? `${Number(snapshot.remaining_min).toFixed(2)}${snapshot.unit ? ` ${snapshot.unit}` : ""}`
    : "";
  return `${stateLabel}${remaining ? ` · 剩余约 ${remaining}` : ""}${snapshot.stale ? " · 需刷新" : ""}`;
}

function modelPolicyDecisionLabel(decision) {
  return ({
    selected: "已选择",
    "needs-confirmation": "等待确认",
    "no-compatible-route": "没有合规候选",
  })[decision?.status] || "未决定";
}

function modelPolicyDecisionSummary(decision) {
  if (!decision) return "尚未对当前目标进行 preflight。";
  const selected = decision.selected_entry;
  if (!selected) return `策略无法继续：${(decision.reason_codes || []).slice(0, 3).join("、") || "没有满足门槛的模型"}。`;
  const route = selected.display_name || `${selected.provider_id || "Provider"} · ${selected.model_id || "模型"}`;
  const reasons = Array.isArray(decision.reason_codes) ? decision.reason_codes.slice(0, 3).join("、") : "";
  const estimate = decision.cost_estimate;
  const cost = estimate?.status === "known"
    ? (estimate.cash_min != null || estimate.cash_max != null
      ? formatCostRange(estimate.cash_min, estimate.cash_max, estimate.cash_currency)
      : formatCostRange(estimate.provider_charge_min, estimate.provider_charge_max, estimate.provider_currency))
    : modelPolicyCostLabel(decision.estimated_cost);
  return `${route} · ${modelPolicyLocationLabel(selected.processing_location)} · ${cost}${reasons ? ` · ${reasons}` : ""}`;
}

function selectedAgentSession() {
  return state.agentSessions.find((session) => session.id === state.agentSessionId) || null;
}

function webRouteStatusLabel(route) {
  const status = String(route?.status || "unknown");
  if (route?.routable) return "可咨询";
  return ({
    ready: "可用但被占用",
    "needs-auth": "需要登录",
    unavailable: "未就绪",
    archived: "已归档",
    waiting: "等待人工接管",
  })[status] || (route?.reason === "profile-not-configured" ? "尚未配置" : status);
}

function webConsultationStatusLabel(status) {
  return ({
    queued: "排队中",
    running: "进行中",
    completed: "已完成",
    partial: "部分完成",
    failed: "全部失败",
    cancelled: "已停止",
    "waiting-human": "等待人工操作",
    unknown: "状态未知",
    interrupted: "已中断",
  })[String(status || "unknown")] || String(status || "未知");
}

function safeWebWorkbenchText(value, limit = 6000) {
  let text = String(value || "");
  text = text.replace(/(?:sk|pk)-[A-Za-z0-9_-]{8,}/gi, "<REDACTED_KEY>");
  text = text.replace(/Bearer\s+[A-Za-z0-9._~+/=-]{8,}/gi, "Bearer <REDACTED>");
  text = text.replace(/((?:api[_ -]?key|token|secret|password|cookie|authorization)\s*[:=]\s*)[^\s,;]+/gi, "$1<REDACTED>");
  text = text.replace(/(?:[A-Za-z]:[\\/]|\\\\)[^\n\r ]+/g, "<LOCAL_PATH>");
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function webAttemptStatusLabel(status) {
  return ({
    accepted: "已接收",
    running: "等待网页回复",
    completed: "已完成",
    failed: "发送前失败",
    "possibly-sent": "已发送但未确认",
    "waiting-human": "等待人工操作",
    cancelled: "已停止",
    interrupted: "已中断",
    unknown: "状态未知",
  })[String(status || "unknown")] || String(status || "未知");
}

function webAttemptActive(result) {
  return ["accepted", "running"].includes(String(result?.status || ""));
}

function webWorkbenchProfiles() {
  const routes = Array.isArray(state.webWorkbenchCatalog?.routes) ? state.webWorkbenchCatalog.routes : [];
  return routes.filter((route) => route?.provider_profile_id).map((route) => ({
    route,
    profile: state.webChatProfiles.find((item) => item.id === route.provider_profile_id) || null,
  }));
}

function webWorkbenchParentSessionId() {
  // The bridge requires a parent id for audit correlation.  Prefer the active
  // DSH session, then the normal chat session; neither value is sent as page
  // content or persisted by the browser workbench.
  return String(state.agentSessionId || currentSessionId() || "workbench").trim() || "workbench";
}

function webWorkbenchContextFromText(value) {
  const text = String(value || "").trim();
  return text ? { user_context: text } : {};
}

function webWorkbenchActiveConsultation(item) {
  return ["queued", "running"].includes(String(item?.status || ""));
}

function webWorkbenchRememberRequest(request) {
  if (!request?.consultation_id) return;
  state.webWorkbenchConsultationRequests = {
    ...state.webWorkbenchConsultationRequests,
    [request.consultation_id]: {
      question: request.question,
      context: request.context || "",
      decision_kind: request.decision_kind,
      max_members: Number(request.max_members) || 3,
      parent_session_id: request.parent_session_id,
      parent_turn_id: request.parent_turn_id || null,
    },
  };
}

function webWorkbenchShouldPoll() {
  const manualActive = Object.entries(state.webWorkbenchManualAttempts || {}).some(([profileId, attemptId]) => (
    Boolean(attemptId) && webAttemptActive(state.webWorkbenchManualResults?.[profileId])
  ));
  return Boolean(
    ["queued", "running"].includes(String(state.webWorkbenchWorkerResult?.status || ""))
    || (state.webWorkbenchConsultations || []).some(webWorkbenchActiveConsultation)
    || manualActive,
  );
}

function scheduleWebWorkbenchPoll() {
  if (state.webWorkbenchPollTimer !== null) return;
  if (!webWorkbenchShouldPoll()) return;
  state.webWorkbenchPollTimer = window.setTimeout(() => {
    state.webWorkbenchPollTimer = null;
    void pollWebWorkbenchRuns();
  }, 900);
}

function stopWebWorkbenchPoll() {
  if (state.webWorkbenchPollTimer !== null) {
    window.clearTimeout(state.webWorkbenchPollTimer);
    state.webWorkbenchPollTimer = null;
  }
}

async function loadWebWorkbenchConsultations(shouldRender = true) {
  try {
    const result = await rpc("sumika.consultation.status", { limit: 50 });
    state.webWorkbenchConsultations = Array.isArray(result?.consultations) ? result.consultations : [];
  } catch (error) {
    if (shouldRender) state.webWorkbenchNotice = `咨询记录读取失败：${String(error.message || "未知错误").slice(0, 240)}`;
  }
  if (shouldRender) render();
  if (webWorkbenchShouldPoll()) scheduleWebWorkbenchPoll();
}

async function loadWebWorkbenchPending(shouldRender = true) {
  try {
    const result = await rpc("sumika.route.pending", {
      parent_session_id: webWorkbenchParentSessionId(),
      limit: 50,
    });
    state.webWorkbenchPendingResults = Array.isArray(result?.results) ? result.results : [];
  } catch (error) {
    if (shouldRender) state.webWorkbenchNotice = `待接收结果读取失败：${String(error.message || "未知错误").slice(0, 240)}`;
  }
  if (shouldRender) render();
}

async function loadWebWorkbenchData(shouldRender = true, refresh = false) {
  if (state.webWorkbenchCatalogBusy) return;
  state.webWorkbenchCatalogBusy = true;
  if (shouldRender) render();
  try {
    // Keep the profile projection and route catalog from the same refresh so
    // a just-finished login/consent cannot leave stale controls visible.
    await loadWebChatData(false, false);
    state.webWorkbenchCatalog = await rpc("sumika.route.catalog", {
      include_templates: true,
      refresh: Boolean(refresh),
    });
    await loadWebWorkbenchConsultations(false);
    await loadWebWorkbenchPending(false);
    const profiles = webWorkbenchProfiles();
    if (!profiles.some(({ profile }) => profile?.id === state.webWorkbenchSelectedProfileId)) {
      state.webWorkbenchSelectedProfileId = profiles.find(({ route }) => route.routable)?.profile?.id || "";
    }
    state.webWorkbenchNotice = "";
  } catch (error) {
    state.webWorkbenchNotice = `网页工作台读取失败：${String(error.message || "未知错误").slice(0, 240)}`;
    if (!state.webWorkbenchCatalog) state.webWorkbenchCatalog = { schema: "agent-route/v1", routes: [], count: 0, routable_count: 0, quota_state: "unknown" };
  } finally {
    state.webWorkbenchCatalogBusy = false;
    if (shouldRender) render();
  }
  if (webWorkbenchShouldPoll()) scheduleWebWorkbenchPoll();
}

async function pollWebWorkbenchRuns() {
  if (state.webWorkbenchPollInFlight) return;
  if (!webWorkbenchShouldPoll()) return;
  state.webWorkbenchPollInFlight = true;
  try {
    for (const [profileId, attemptId] of Object.entries(state.webWorkbenchManualAttempts || {})) {
      const current = state.webWorkbenchManualResults?.[profileId];
      if (!attemptId || !webAttemptActive(current)) continue;
      const result = await rpc("browser.web_chat.message.status", { attempt_id: attemptId });
      state.webWorkbenchManualResults = {
        ...state.webWorkbenchManualResults,
        [profileId]: result,
      };
      if (result?.status === "completed") {
        state.webWorkbenchManualDrafts = { ...state.webWorkbenchManualDrafts, [profileId]: "" };
      }
    }
    if (state.webWorkbenchWorkerDispatchId) {
      const result = await rpc("sumika.route.status", { dispatch_id: state.webWorkbenchWorkerDispatchId });
      if (result && typeof result === "object") {
        // Keep the outer lifecycle projection.  Flattening to ``dispatch``
        // drops terminal status, retryability and possibly-sent markers.
        state.webWorkbenchWorkerResult = result;
      }
    }
    await loadWebWorkbenchConsultations(false);
    await loadWebWorkbenchPending(false);
    // Occupancy is derived from the coordinator and can change while a worker
    // finishes; refresh the catalog before repainting the controls.
    state.webWorkbenchCatalog = await rpc("sumika.route.catalog", { include_templates: true });
    if (state.activePage === "WebWorkbench") render();
  } catch (error) {
    state.webWorkbenchNotice = `网页运行状态读取失败：${String(error.message || "未知错误").slice(0, 240)}`;
    if (state.activePage === "WebWorkbench") render();
  } finally {
    state.webWorkbenchPollInFlight = false;
    if (webWorkbenchShouldPoll()) scheduleWebWorkbenchPoll();
  }
}

function updateWebWorkbenchDraftFromForm(form) {
  if (!form) return;
  const question = String(form.elements.question?.value || "");
  if (form.id === "web-workbench-worker-form") {
    state.webWorkbenchWorkerDraft = {
      route_id: String(form.elements.route_id?.value || ""),
      question,
    };
  } else if (form.id === "web-workbench-consultation-form") {
    state.webWorkbenchConsultationDraft = {
      question,
      context: String(form.elements.context?.value || ""),
      decision_kind: String(form.elements.decision_kind?.value || "brainstorm"),
      max_members: Number(form.elements.max_members?.value || 3),
    };
  }
}

async function ensureNativeWebProfile(profileId) {
  if (!isDesktopShell) throw new Error("网页操作请从 Sumika 桌面版的内置浏览器进行，不会弹出外部窗口。");
  const profile = state.webChatProfiles.find((row) => row.id === profileId);
  if (profile?.config?.transport === "native" || profile?.transport === "native") return profile;
  const bound = await rpc("browser.web_chat.profile.bind_native", { profile_id: profileId, approved: true });
  replaceWebChatProfile(bound);
  return bound;
}

async function openWebWorkbenchProfile(profileId) {
  if (!profileId || state.webWorkbenchBusy) return;
  state.webWorkbenchBusy = `open:${profileId}`;
  state.webWorkbenchNotice = "正在打开内置网页标签…";
  render();
  try {
    await ensureNativeWebProfile(profileId);
    const result = await rpc("browser.web_chat.profile.open", { profile_id: profileId, approved: true });
    replaceWebChatProfile(result);
    state.webWorkbenchSelectedProfileId = profileId;
    state.webWorkbenchNotice = "内置标签已打开。原受管浏览器数据保留，需要时在此重新登录。";
  } catch (error) {
    state.webWorkbenchNotice = `打开内置网页失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
  }
}

async function focusWebWorkbenchProfile(profileId) {
  if (!profileId || state.webWorkbenchBusy) return;
  state.webWorkbenchBusy = `focus:${profileId}`;
  state.webWorkbenchNotice = "正在定位内置网页标签…";
  render();
  try {
    await ensureNativeWebProfile(profileId);
    const result = await rpc("browser.web_chat.profile.focus", { profile_id: profileId, approved: true });
    replaceWebChatProfile(result);
    state.webWorkbenchSelectedProfileId = profileId;
    state.webWorkbenchNotice = result.focused === false ? "内置标签未就绪，请检查桌面连接。" : "已定位内置网页标签。";
  } catch (error) {
    state.webWorkbenchNotice = `聚焦网页窗口失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
  }
}

async function closeWebWorkbenchProfile(profileId) {
  if (!profileId || state.webWorkbenchBusy) return;
  state.webWorkbenchBusy = `close:${profileId}`;
  render();
  try {
    const result = await rpc("browser.web_chat.profile.close", { profile_id: profileId, approved: true });
    replaceWebChatProfile(result);
    state.webWorkbenchNotice = "网页标签已关闭，登录档案保留。";
  } catch (error) {
    state.webWorkbenchNotice = `关闭网页窗口失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
  }
}

async function setWebWorkbenchOccupancy(profileId, owner = "idle") {
  if (!profileId || state.webWorkbenchBusy) return;
  state.webWorkbenchBusy = `occupancy:${profileId}`;
  render();
  try {
    await rpc("sumika.route.occupancy", { profile_id: profileId, owner });
    state.webWorkbenchNotice = owner === "idle" ? "已释放网页 Profile；Agent 可在下一次 dispatch 中使用。" : `网页 Profile 已标记为 ${owner}。`;
  } catch (error) {
    state.webWorkbenchNotice = `更新网页占用状态失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
  }
}

async function takeoverWebWorkbenchProfile(profileId) {
  if (!profileId || state.webWorkbenchBusy) return;
  state.webWorkbenchBusy = `takeover:${profileId}`;
  state.webWorkbenchNotice = "正在暂停该 Profile 上的 Agent 回合并交给你接管…";
  render();
  try {
    const result = await rpc("sumika.route.takeover", { profile_id: profileId });
    state.webWorkbenchNotice = result.cancelled_dispatches?.length
      ? `已请求接管，并停止 ${result.cancelled_dispatches.length} 个 Agent 回合。`
      : "已请求接管；若网页正在发送，状态会在下一次刷新中更新。";
  } catch (error) {
    state.webWorkbenchNotice = `接管网页 Profile 失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
  }
}

async function sendWebWorkbenchManual(event) {
  event.preventDefault();
  if (state.webWorkbenchBusy) return;
  const form = event.currentTarget;
  const profileId = String(form.elements.profile_id?.value || "").trim();
  const question = String(form.elements.question?.value || "").trim();
  if (!profileId || !question) {
    state.webWorkbenchNotice = "请选择已授权网页 Profile 并填写问题。";
    render();
    return;
  }
  state.webWorkbenchSelectedProfileId = profileId;
  state.webWorkbenchManualDrafts = { ...state.webWorkbenchManualDrafts, [profileId]: question };
  state.webWorkbenchBusy = "manual-send";
  state.webWorkbenchNotice = "正在通过隔离网页发送；回答会在同一 attempt 中更新，不会重复发送。";
  render();
  try {
    await ensureNativeWebProfile(profileId);
    const result = await rpc("browser.web_chat.message.start", {
      profile_id: profileId,
      text: question,
      owner: "manual",
    });
    const attemptId = String(result?.attempt_id || "").trim();
    state.webWorkbenchManualAttempts = {
      ...state.webWorkbenchManualAttempts,
      [profileId]: attemptId,
    };
    state.webWorkbenchManualResults = { ...state.webWorkbenchManualResults, [profileId]: result };
    if (result?.accepted && attemptId) {
      state.webWorkbenchManualDrafts = { ...state.webWorkbenchManualDrafts, [profileId]: "" };
      state.webWorkbenchNotice = "网页消息已发送；正在等待同一 attempt 的明确回复。";
      scheduleWebWorkbenchPoll();
    } else {
      state.webWorkbenchNotice = String(result?.reason || result?.error_code || "网页查询未接受");
    }
  } catch (error) {
    state.webWorkbenchManualResults = { ...state.webWorkbenchManualResults, [profileId]: { ok: false, reason: error.message } };
    state.webWorkbenchNotice = `网页查询失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    render();
    void loadWebWorkbenchData(false, false);
  }
}

async function cancelWebWorkbenchManual(attemptId) {
  const identifier = String(attemptId || "").trim();
  if (!identifier || state.webWorkbenchBusy) return;
  state.webWorkbenchBusy = `manual-cancel:${identifier}`;
  state.webWorkbenchNotice = "正在停止网页回合；已发送的消息不会自动重发。";
  render();
  try {
    const result = await rpc("browser.web_chat.message.cancel", { attempt_id: identifier });
    const profileId = Object.entries(state.webWorkbenchManualAttempts || {}).find(([, value]) => value === identifier)?.[0];
    if (profileId) {
      state.webWorkbenchManualResults = { ...state.webWorkbenchManualResults, [profileId]: result };
    }
  } catch (error) {
    state.webWorkbenchNotice = `停止网页回合失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
  }
}

async function acknowledgeWebWorkbenchPending(dispatchId) {
  const identifier = String(dispatchId || "").trim();
  if (!identifier || state.webWorkbenchBusy) return;
  state.webWorkbenchBusy = `route-ack:${identifier}`;
  state.webWorkbenchNotice = "正在确认已收到 Worker 结果…";
  render();
  try {
    await rpc("sumika.route.ack", { dispatch_id: identifier });
    state.webWorkbenchPendingResults = state.webWorkbenchPendingResults.filter((item) => item.dispatch_id !== identifier);
    state.webWorkbenchNotice = "Worker 结果已确认；正文不会被自动执行。";
  } catch (error) {
    state.webWorkbenchNotice = `确认 Worker 结果失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    render();
  }
}

async function startWebWorkbenchWorker(event) {
  event.preventDefault();
  if (state.webWorkbenchBusy) return;
  const form = event.currentTarget;
  const routeId = String(form.elements.route_id?.value || state.webWorkbenchWorkerDraft.route_id || "").trim();
  const question = String(form.elements.question?.value || state.webWorkbenchWorkerDraft.question || "").trim();
  if (!routeId || !question) {
    state.webWorkbenchNotice = "请选择可用路由并填写子任务。";
    render();
    return;
  }
  state.webWorkbenchWorkerDraft = { route_id: routeId, question };
  state.webWorkbenchBusy = "worker-start";
  state.webWorkbenchNotice = "Web Worker 已提交，等待隔离网页事件…";
  render();
  try {
    const result = await rpc("sumika.route.dispatch", {
      parent_session_id: webWorkbenchParentSessionId(),
      parent_turn_id: state.agentSnapshot?.turn_id || undefined,
      route_id: routeId,
      mode: "web-worker",
      question,
      context_refs: { source: "web-workbench" },
    });
    const dispatch = result?.dispatch || {};
    state.webWorkbenchWorkerDispatchId = dispatch.dispatch_id || "";
    state.webWorkbenchWorkerResult = dispatch;
    state.webWorkbenchWorkerDraft = { route_id: routeId, question: "" };
    if (result?.accepted === false) {
      state.webWorkbenchNotice = `Web Worker 未接受：${result.reason || dispatch.error_code || "route-unavailable"}`;
    } else {
      state.webWorkbenchNotice = "Web Worker 已排队；结果会保持 UNTRUSTED_WEB_RESULT。";
    }
  } catch (error) {
    state.webWorkbenchWorkerResult = { status: "failed", reason: error.message };
    state.webWorkbenchNotice = `Web Worker 提交失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
    scheduleWebWorkbenchPoll();
  }
}

async function startWebWorkbenchConsultation(event) {
  event.preventDefault();
  if (state.webWorkbenchBusy) return;
  const form = event.currentTarget;
  updateWebWorkbenchDraftFromForm(form);
  const draft = state.webWorkbenchConsultationDraft;
  const question = String(draft.question || "").trim();
  const maxMembers = Math.max(1, Math.min(5, Number(draft.max_members) || 3));
  if (!question) {
    state.webWorkbenchNotice = "请填写咨询问题。";
    render();
    return;
  }
  state.webWorkbenchBusy = "consultation-start";
  state.webWorkbenchNotice = "正在动态分配独立网页成员；成员不会互相看到回答。";
  render();
  const request = {
    parent_session_id: webWorkbenchParentSessionId(),
    parent_turn_id: state.agentSnapshot?.turn_id || undefined,
    question,
    decision_kind: draft.decision_kind || "brainstorm",
    required_capabilities: ["text"],
    context_refs: webWorkbenchContextFromText(draft.context),
    max_members: maxMembers,
  };
  try {
    const result = await rpc("sumika.consultation.start", request);
    if (!result?.consultation_id) throw new Error("核心未返回 consultation_id");
    webWorkbenchRememberRequest({ ...request, consultation_id: result.consultation_id, context: draft.context });
    state.webWorkbenchConsultations = [result, ...state.webWorkbenchConsultations.filter((item) => item.consultation_id !== result.consultation_id)];
    state.webWorkbenchConsultationDraft = { ...draft, question: "", context: "", max_members: maxMembers };
    state.webWorkbenchNotice = result.status === "failed"
      ? "没有可用网页 Profile；未生成替代意见。"
      : "咨询面板已启动；结果只作为外部建议，不会自动执行。";
  } catch (error) {
    state.webWorkbenchNotice = `启动咨询面板失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
    scheduleWebWorkbenchPoll();
  }
}

async function cancelWebWorkbenchConsultation(consultationId) {
  if (!consultationId || state.webWorkbenchBusy) return;
  state.webWorkbenchBusy = `consultation-cancel:${consultationId}`;
  state.webWorkbenchNotice = "正在停止咨询成员…";
  render();
  try {
    await rpc("sumika.route.cancel", { consultation_id: consultationId });
    state.webWorkbenchNotice = "已发送停止请求；最终状态以咨询事件为准。";
  } catch (error) {
    state.webWorkbenchNotice = `停止咨询失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
  }
}

async function continueWebWorkbenchConsultation(consultationId) {
  if (!consultationId || state.webWorkbenchBusy) return;
  const previous = state.webWorkbenchConsultationRequests[consultationId];
  if (!previous?.question) {
    state.webWorkbenchNotice = "该咨询来自较早的核心记录，问题正文未保存在 UI；请重新填写问题后发起复核。";
    render();
    return;
  }
  state.webWorkbenchBusy = `consultation-continue:${consultationId}`;
  state.webWorkbenchNotice = "正在发起一次新的复核回合…";
  render();
  try {
    const request = {
      parent_session_id: previous.parent_session_id || webWorkbenchParentSessionId(),
      parent_turn_id: previous.parent_turn_id || undefined,
      question: previous.question,
      decision_kind: previous.decision_kind || "fact-check",
      required_capabilities: ["text"],
      context_refs: webWorkbenchContextFromText(previous.context),
      max_members: Math.max(1, Math.min(5, Number(previous.max_members) || 3)),
      continuation_of: consultationId,
    };
    const result = await rpc("sumika.consultation.start", request);
    webWorkbenchRememberRequest({ ...request, consultation_id: result.consultation_id, context: previous.context });
    state.webWorkbenchNotice = "复核回合已启动；它使用新的成员分配，不会把旧回答发送给成员。";
  } catch (error) {
    state.webWorkbenchNotice = `继续复核失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
    scheduleWebWorkbenchPoll();
  }
}

async function retryWebWorkbenchDispatch(dispatchId) {
  if (!dispatchId || state.webWorkbenchBusy) return;
  state.webWorkbenchBusy = `retry:${dispatchId}`;
  state.webWorkbenchNotice = "正在重试已确认的发送前失败回合…";
  render();
  try {
    const result = await rpc("sumika.route.retry", { dispatch_id: dispatchId });
    const dispatch = result?.dispatch || result;
    if (dispatch?.dispatch_id) {
      state.webWorkbenchWorkerDispatchId = dispatch.dispatch_id;
      state.webWorkbenchWorkerResult = dispatch;
    }
    state.webWorkbenchNotice = "重试已排队；不会重复发送已确认成功的消息。";
  } catch (error) {
    state.webWorkbenchNotice = `网页回合重试失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
    scheduleWebWorkbenchPoll();
  }
}

async function pauseAllWebWorkbenchConsultations() {
  if (state.webWorkbenchBusy) return;
  const active = state.webWorkbenchConsultations.filter(webWorkbenchActiveConsultation);
  if (!active.length && !webWorkbenchShouldPoll()) {
    state.webWorkbenchNotice = "当前没有运行中的网页咨询。";
    render();
    return;
  }
  state.webWorkbenchBusy = "pause-all";
  state.webWorkbenchNotice = "正在停止运行中的网页咨询…";
  render();
  try {
    await Promise.all(active.map((item) => rpc("sumika.route.cancel", { consultation_id: item.consultation_id })));
    if (["queued", "running"].includes(String(state.webWorkbenchWorkerResult?.status || "")) && state.webWorkbenchWorkerDispatchId) {
      await rpc("sumika.route.cancel", { dispatch_id: state.webWorkbenchWorkerDispatchId });
    }
    state.webWorkbenchNotice = "已停止当前网页咨询；可以从失败/部分结果处继续复核。";
  } catch (error) {
    state.webWorkbenchNotice = `暂停网页咨询失败：${error.message}`;
  } finally {
    state.webWorkbenchBusy = null;
    await loadWebWorkbenchData(false, false);
    render();
  }
}

async function continueLatestWebWorkbenchConsultation() {
  const candidate = state.webWorkbenchConsultations.find((item) => ["partial", "failed", "waiting-human"].includes(String(item?.status || "")));
  if (!candidate) {
    state.webWorkbenchNotice = "没有可继续复核的部分或失败咨询。";
    render();
    return;
  }
  await continueWebWorkbenchConsultation(candidate.consultation_id);
}

function pluginStatusLabel(status) {
  return ({ discovered: "待批准", changed: "清单已变化", approved: "已批准", revoked: "已撤销", invalid: "无效" })[status] || status || "未知";
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

function loadWorkbenchPage(page) {
  state.activePage = page;
  if (["Modules", "Capabilities", "Settings"].includes(page)) void loadModules(true);
  if (["Modules", "Developer"].includes(page)) {
    void loadCapabilityCatalog(true, false);
    void loadRoutePricing(true, false);
    void loadWebChatData(true, page === "Developer");
  }
  if (page === "Developer") {
    void loadProviderProfiles(true, true);
    void loadEvolutionRegistry(true);
    void loadAgentDiagnostics(true);
  }
  if (["Developer", "Agent"].includes(page)) void loadAgentRuntime(true);
  if (page === "Agent") void loadAgentModelPolicy(true, false);
  if (page === "WebWorkbench") void loadWebWorkbenchData(true, false);
  if (page === "Tasks") { void loadTasks(true); void loadQualityRoutingWorkbench(true); }
  if (["Settings", "Capabilities"].includes(page)) void loadQualityRoutingSettings(true);
}

function bindEvents() {
  document.querySelectorAll("[data-workbench-page]").forEach((element) => element.addEventListener("click", (event) => {
    event.preventDefault();
    element.parentElement.open = !element.parentElement.open;
    if (element.parentElement.open) loadWorkbenchPage(element.dataset.workbenchPage);
  }));
  document.querySelectorAll("[data-chat-clear]").forEach((button) => button.addEventListener("click", workbenchHost.actions.onClearConversationDisplay));
  document.querySelectorAll("[data-chat-history]").forEach((button) => button.addEventListener("click", workbenchHost.actions.onConversationPage));
  document.querySelectorAll("[data-companion-size]").forEach((button) => button.addEventListener("click", () => void setCompanionSize(button.dataset.companionSize)));
  embeddedView.bind(document, portalDefinitions());
  benefitsView.bind(document);
  capabilityPage.bindCapabilities({ root: document.querySelector(".capability-page")?.parentElement, onConfigure: (moduleId) => {
    state.activePage = "Modules";
    render();
    const toggle = [...document.querySelectorAll("[data-module-toggle]")].find((element) => element.dataset.moduleToggle === moduleId);
    const library = toggle?.closest("details");
    if (library) library.open = true;
    toggle?.scrollIntoView({ block: "center" });
    toggle?.focus({ preventScroll: true });
  } });
  document.querySelectorAll("[data-page]").forEach((element) => element.addEventListener("click", () => {
    if (state.overlayMode) {
      window.open(location.origin + location.pathname + "?view=settings&connections=1", "sumika-workspace");
      return;
    }
    if (!state.overlayMode) {
      const target = element.dataset.page;
      const view = { Characters: "characters", Capabilities: "capabilities", Modules: "settings", Developer: "settings", Settings: "settings", Guide: "settings" }[target] || "workspace";
      workbenchHost.model.view = view;
      if (target === "Modules") workbenchHost.model.connectionsOpen = true;
      loadWorkbenchPage(target);
      render();
      return;
    }
    if (state.portalPanelOpen) void embeddedView.hide();
    state.activePage = scenePageAfterNavigation(element.dataset.page);
    if (state.consultation.visible && state.activePage !== "Tasks") void changeConsultationVisibility("hide");
    state.portalPanelOpen = false;
    if (["Modules", "Capabilities"].includes(state.activePage)) void loadModules(true);
    if (state.activePage === "Modules" || state.activePage === "Developer") void loadCapabilityCatalog(true, false);
    if (state.activePage === "Modules" || state.activePage === "Developer") void loadRoutePricing(true, false);
    if (state.activePage === "Modules" || state.activePage === "Developer") void loadWebChatData(true, state.activePage === "Developer");
    if (state.activePage === "Developer") void loadProviderProfiles(true, true);
    if (state.activePage === "Developer") void loadEvolutionRegistry(true);
    if (state.activePage === "Developer") void loadAgentDiagnostics(true);
    if (state.activePage === "Developer" || state.activePage === "Agent") void loadAgentRuntime(true);
    if (state.activePage === "Agent") void loadAgentModelPolicy(true, false);
    if (state.activePage === "WebWorkbench") void loadWebWorkbenchData(true, false);
    if (state.activePage === "Tasks") void loadTasks(true);
    if (["Settings", "Capabilities"].includes(state.activePage)) void loadQualityRoutingSettings(true);
    if (state.activePage === "Tasks") void loadQualityRoutingWorkbench(true);
    render();
  }));
  document.querySelectorAll("[data-chat-toggle]").forEach((element) => element.addEventListener("click", () => {
    state.chatOpen = !state.chatOpen;
    render();
    document.querySelector(state.chatOpen ? "#chat-input" : ".restore-chat")?.focus({ preventScroll: true });
  }));
  document.querySelectorAll("[data-character-theme]").forEach((element) => element.addEventListener("click", () => {
    state.displayPreferences.theme = element.dataset.characterTheme;
    if (!writeDisplayPreferences(localStorage, state.displayPreferences)) state.sessionNotice = "外观只在当前窗口生效，浏览器存储不可用。";
    render();
  }));
  document.querySelector("[data-pet-chat]")?.addEventListener("click", () => {
    state.petChatOpen = !state.petChatOpen;
    render();
    document.querySelector("[data-pet-chat]")?.focus({ preventScroll: true });
  });
  document.querySelector("[data-pet-background]")?.addEventListener("click", () => {
    state.displayPreferences.transparent = !state.displayPreferences.transparent;
    if (!writeDisplayPreferences(localStorage, state.displayPreferences)) state.sessionNotice = "外观只在当前窗口生效，浏览器存储不可用。";
    render();
    document.querySelector("[data-pet-background]")?.focus({ preventScroll: true });
  });
  document.querySelector("#character-select")?.addEventListener("change", (event) => {
    state.selectedCharacter = event.target.value;
    invalidateQualityRoutingScope();
    state.sessionNotice = "";
    loadMessages();
    loadAvatarState();
    loadMemories();
  });
  document.querySelector("[data-drawer-close]")?.addEventListener("click", () => {
    state.activePage = scenePageAfterDrawerClose();
    markOnboarded();
    render();
  });
  document.querySelector("[data-onboard-dismiss]")?.addEventListener("click", markOnboarded);
  document.querySelector("[data-portal-panel]")?.addEventListener("click", () => {
    if (state.portalPanelOpen) void embeddedView.hide();
    else { state.portalPanelOpen = true; render(); void embeddedView.list().catch(() => {}); }
  });
  document.querySelector("#portal-add-form")?.addEventListener("submit", addCustomPortal);
  document.querySelectorAll("[data-appearance-color]").forEach((element) => element.addEventListener("click", () => {
    const next = readAppearance();
    delete next.backgroundImage;
    next.backgroundColor = element.dataset.appearanceColor || "";
    writeAppearance(next);
    applyAppearance();
    render();
  }));
  document.querySelector("#appearance-image-button")?.addEventListener("click", () => {
    document.querySelector("#appearance-image")?.click();
  });
  document.querySelector("#appearance-image")?.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 4_500_000) {
      window.alert("背景图请小于 4.5 MB；更大的图片请先压缩。");
      event.target.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const next = readAppearance();
      next.backgroundImage = String(reader.result);
      delete next.backgroundColor;
      writeAppearance(next);
      applyAppearance();
      render();
    };
    reader.readAsDataURL(file);
  });
  document.querySelector("#appearance-image-clear")?.addEventListener("click", () => {
    const next = readAppearance();
    delete next.backgroundImage;
    writeAppearance(next);
    applyAppearance();
    render();
  });
  document.querySelector("[data-modules-retry]")?.addEventListener("click", () => void loadModules(true));
  document.querySelector("[data-avatar-toggle]")?.addEventListener("click", () => {
    state.avatarVisible = !state.avatarVisible;
    render();
  });
  document.querySelector("[data-overlay-open]")?.addEventListener("click", openDesktopOverlay);
  document.querySelector("[data-overlay-open-main]")?.addEventListener("click", openMainWindow);
  document.querySelector("[data-overlay-hide]")?.addEventListener("click", hideDesktopOverlay);
  document.querySelector(".desktop-overlay-shell")?.addEventListener("pointerdown", (event) => {
    void startOverlayDrag(event);
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
    invalidateQualityRoutingScope();
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
  document.querySelector("#character-create-form")?.addEventListener("submit", submitCharacterCreation);
  document.querySelector("[data-character-create-cancel]")?.addEventListener("click", () => {
    state.characterCreating = false;
    render();
  });
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
  document.querySelector("#refresh-capability-catalog")?.addEventListener("click", () => {
    void loadCapabilityCatalog(true, true);
  });
  document.querySelector("#agent-health")?.addEventListener("click", checkAgentHealth);
  document.querySelector("#agent-provider-sync")?.addEventListener("click", syncAgentProvider);
  document.querySelector("#refresh-agent-mcp-catalog")?.addEventListener("click", () => {
    void loadAgentMcpCatalog();
  });
  document.querySelector("#refresh-agent-skills")?.addEventListener("click", () => {
    void loadAgentSkills(true, true);
  });
  document.querySelector("#discover-agent-skills")?.addEventListener("click", () => {
    void discoverAgentSkills();
  });
  document.querySelector("#agent-skills-path")?.addEventListener("input", (event) => {
    state.agentSkillsPath = event.target.value;
  });
  document.querySelectorAll("[data-agent-skill-approve]").forEach((element) => element.addEventListener("click", () => {
    void approveAgentSkill(element.dataset.agentSkillApprove);
  }));
  document.querySelectorAll("[data-agent-skill-revoke]").forEach((element) => element.addEventListener("click", () => {
    void revokeAgentSkill(element.dataset.agentSkillRevoke);
  }));
  document.querySelector("#refresh-evolution-registry")?.addEventListener("click", loadEvolutionRegistry);
  document.querySelector("#agent-mode")?.addEventListener("change", (event) => {
    state.agentMode = event.target.value;
  });
  document.querySelector("#agent-routing-mode")?.addEventListener("change", (event) => {
    const value = String(event.target.value || "manual").toLowerCase();
    state.agentRoutingMode = AGENT_ROUTING_MODES.has(value) ? value : "manual";
    resetAgentRoutingDecision();
    rememberAgentRoutingPreference();
    render();
  });
  document.querySelector("#agent-routing-budget")?.addEventListener("change", (event) => {
    const value = String(event.target.value || "prefer-free").toLowerCase();
    state.agentRoutingBudgetPolicy = AGENT_ROUTING_BUDGETS.has(value) ? value : "prefer-free";
    resetAgentRoutingDecision();
    rememberAgentRoutingPreference();
    render();
  });
  document.querySelector("#agent-routing-refresh")?.addEventListener("click", () => {
    void loadAgentModelPolicy(true, true);
  });
  document.querySelector("#agent-routing-quota")?.addEventListener("click", () => {
    void loadAgentModelPolicy(true, true);
  });
  document.querySelector("#agent-routing-confirm")?.addEventListener("click", () => {
    void sendAgentPrompt({ approvedRouting: true });
  });
  document.querySelector("#agent-routing-cancel")?.addEventListener("click", () => {
    state.agentRoutingPendingKey = "";
    state.agentRoutingApprovedKey = "";
    state.agentRoutingNotice = "已取消本次模型选择；目标仍保留在输入框中。";
    render();
  });
  document.querySelector("#agent-create-session")?.addEventListener("click", createAgentSession);
  document.querySelector("#agent-refresh-workspaces")?.addEventListener("click", () => loadAgentWorkspaces());
  document.querySelector("#agent-session-search-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    void searchAgentSessions();
  });
  document.querySelector("#agent-session-search")?.addEventListener("input", (event) => {
    state.agentSessionSearchQuery = event.target.value;
  });
  document.querySelector("#agent-session-search-clear")?.addEventListener("click", clearAgentSessionSearch);
  document.querySelector("#agent-session-title")?.addEventListener("input", (event) => {
    state.agentSessionRenameDraft = event.target.value;
  });
  document.querySelector("#agent-session-rename")?.addEventListener("click", renameAgentSession);
  document.querySelector("#agent-workspace-select")?.addEventListener("change", (event) => {
    invalidateAgentWorkspaceRequests();
    state.agentWorkspaceId = event.target.value;
    const selected = state.agentWorkspaces.find((workspace) => workspace.id === state.agentWorkspaceId);
    state.workspaceRuntimePath = selected?.path || "";
    state.workspaceRuntimeInspect = null;
    state.workspaceRuntimeCheckpoints = [];
    state.workspaceRuntimeSelectedId = null;
    state.workspaceRuntimeDiff = null;
    state.workspaceRuntimePreview = null;
    state.workspaceRuntimeWorktreePreview = null;
    state.workspaceRuntimeCommitPreview = null;
    state.workspaceRuntimeNotice = selected ? "已切换 Workspace；检查状态后可创建 checkpoint。" : "";
    render();
  });
  document.querySelector("#agent-workspace-path")?.addEventListener("input", (event) => {
    state.agentWorkspacePath = event.target.value;
    const button = document.querySelector("#agent-register-workspace");
    if (button) button.disabled = !state.agentStatus?.ready || !state.agentWorkspacePath.trim() || Boolean(state.agentBusy);
  });
  document.querySelector("#agent-register-workspace")?.addEventListener("click", registerAgentWorkspace);
  document.querySelector("#workspace-runtime-path")?.addEventListener("input", (event) => {
    state.workspaceRuntimePath = event.target.value;
    state.workspaceRuntimeWorktreePreview = null;
    state.workspaceRuntimeCommitPreview = null;
    const worktreeCreate = document.querySelector("#workspace-worktree-create");
    const commitCreate = document.querySelector("#workspace-commit-create");
    if (worktreeCreate) worktreeCreate.disabled = true;
    if (commitCreate) commitCreate.disabled = true;
    const ready = Boolean(state.workspaceRuntimePath.trim()) && !state.workspaceRuntimeBusy;
    const inspect = document.querySelector("#workspace-runtime-inspect");
    const create = document.querySelector("#workspace-runtime-create");
    const refresh = document.querySelector("#workspace-runtime-refresh");
    if (inspect) inspect.disabled = !ready;
    if (create) create.disabled = !ready;
    if (refresh) refresh.disabled = !ready;
    const worktreePreview = document.querySelector("#workspace-worktree-preview");
    if (worktreePreview) worktreePreview.disabled = !ready || !state.workspaceRuntimeWorktreeDestination.trim() || !state.workspaceRuntimeWorktreeBranch.trim();
  });
  document.querySelector("#workspace-runtime-inspect")?.addEventListener("click", inspectWorkspaceRuntime);
  document.querySelector("#workspace-runtime-create")?.addEventListener("click", createWorkspaceRuntimeCheckpoint);
  document.querySelector("#workspace-runtime-refresh")?.addEventListener("click", () => loadWorkspaceRuntime());
  document.querySelector("#workspace-runtime-name")?.addEventListener("input", (event) => {
    state.workspaceRuntimeCheckpointName = event.target.value;
  });
  document.querySelector("#workspace-worktree-destination")?.addEventListener("input", (event) => {
    state.workspaceRuntimeWorktreeDestination = event.target.value;
    state.workspaceRuntimeWorktreePreview = null;
    const create = document.querySelector("#workspace-worktree-create");
    if (create) create.disabled = true;
    const button = document.querySelector("#workspace-worktree-preview");
    if (button) button.disabled = !workspaceRuntimePath() || !state.workspaceRuntimeWorktreeDestination.trim() || !state.workspaceRuntimeWorktreeBranch.trim() || Boolean(state.workspaceRuntimeBusy);
  });
  document.querySelector("#workspace-worktree-branch")?.addEventListener("input", (event) => {
    state.workspaceRuntimeWorktreeBranch = event.target.value;
    state.workspaceRuntimeWorktreePreview = null;
    const create = document.querySelector("#workspace-worktree-create");
    if (create) create.disabled = true;
    const button = document.querySelector("#workspace-worktree-preview");
    if (button) button.disabled = !workspaceRuntimePath() || !state.workspaceRuntimeWorktreeDestination.trim() || !state.workspaceRuntimeWorktreeBranch.trim() || Boolean(state.workspaceRuntimeBusy);
  });
  document.querySelector("#workspace-worktree-preview")?.addEventListener("click", previewWorkspaceRuntimeWorktree);
  document.querySelector("#workspace-worktree-create")?.addEventListener("click", createWorkspaceRuntimeWorktree);
  document.querySelector("#workspace-commit-message")?.addEventListener("input", (event) => {
    state.workspaceRuntimeCommitMessage = event.target.value;
    state.workspaceRuntimeCommitPreview = null;
    const create = document.querySelector("#workspace-commit-create");
    if (create) create.disabled = true;
    const selected = state.workspaceRuntimeCheckpoints.find((item) => item.id === state.workspaceRuntimeSelectedId);
    const button = document.querySelector("#workspace-commit-preview");
    if (button) button.disabled = selected?.baseline_clean !== true || !state.workspaceRuntimeCommitMessage.trim() || Boolean(state.workspaceRuntimeBusy);
  });
  document.querySelector("#workspace-commit-preview")?.addEventListener("click", previewWorkspaceRuntimeCommit);
  document.querySelector("#workspace-commit-create")?.addEventListener("click", commitWorkspaceRuntimeChanges);
  document.querySelectorAll("[data-workspace-checkpoint]").forEach((element) => element.addEventListener("click", () => {
    state.workspaceRuntimeCommitPreview = null;
    void loadWorkspaceRuntimeDiff(element.dataset.workspaceCheckpoint);
  }));
  document.querySelectorAll("[data-workspace-preview]").forEach((element) => element.addEventListener("click", () => {
    void previewWorkspaceRuntimeRestore(element.dataset.workspacePreview);
  }));
  document.querySelectorAll("[data-workspace-restore]").forEach((element) => element.addEventListener("click", () => {
    void restoreWorkspaceRuntime(element.dataset.workspaceRestore);
  }));
  document.querySelector("#agent-model-select")?.addEventListener("change", selectAgentModel);
  document.querySelector("#agent-preset-select")?.addEventListener("change", selectAgentPreset);
  document.querySelector("#agent-preset-copy-form")?.addEventListener("submit", copyAgentPreset);
  document.querySelector("#agent-preset-copy-source")?.addEventListener("change", (event) => {
    state.agentPresetCopySource = event.target.value;
  });
  document.querySelector("#agent-preset-copy-id")?.addEventListener("input", (event) => {
    state.agentPresetCopyId = event.target.value;
  });
  document.querySelector("#agent-preset-copy-name")?.addEventListener("input", (event) => {
    state.agentPresetCopyName = event.target.value;
  });
  document.querySelectorAll("[data-agent-preset-open]").forEach((element) => element.addEventListener("click", () => {
    void openAgentPresetDocument(element.dataset.agentPresetOpen);
  }));
  document.querySelectorAll("[data-agent-preset-validate]").forEach((element) => element.addEventListener("click", () => {
    void validateAgentPresetMount(element.dataset.agentPresetValidate);
  }));
  document.querySelectorAll("[data-agent-preset-remove]").forEach((element) => element.addEventListener("click", () => {
    void removeAgentPreset(element.dataset.agentPresetRemove);
  }));
  document.querySelector("#agent-mcp-preset")?.addEventListener("change", (event) => {
    state.agentMcpPresetId = event.target.value;
    state.agentMcpPreview = null;
    state.agentMcpPendingSecret = "";
    state.agentMcpDraft = emptyAgentMcpDraft();
    void loadAgentMcpConfigurations();
  });
  document.querySelector("#agent-mcp-form")?.addEventListener("submit", previewAgentMcpConfiguration);
  document.querySelector('#agent-mcp-form select[name="transport"]')?.addEventListener("change", (event) => {
    state.agentMcpDraft.transport = event.target.value;
    state.agentMcpDraft.credential_target = "";
    state.agentMcpDraft.credential_prefix = "";
    state.agentMcpPendingSecret = "";
    state.agentMcpPreview = null;
    render();
  });
  document.querySelectorAll("#agent-mcp-form input, #agent-mcp-form textarea").forEach((element) => element.addEventListener("input", (event) => {
    if (event.target.name === "credential_value") {
      state.agentMcpPendingSecret = event.target.value;
      state.agentMcpPreview = null;
      return;
    }
    const key = event.target.name === "args" ? "args_text" : event.target.name;
    state.agentMcpDraft[key] = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    state.agentMcpPreview = null;
  }));
  document.querySelector("#agent-mcp-credential-enabled")?.addEventListener("change", (event) => {
    state.agentMcpDraft.credential_enabled = event.target.checked;
    if (!event.target.checked) state.agentMcpPendingSecret = "";
    state.agentMcpPreview = null;
    render();
  });
  document.querySelectorAll("[data-agent-mcp-edit]").forEach((element) => element.addEventListener("click", () => {
    editAgentMcpConfiguration(element.dataset.agentMcpEdit);
  }));
  document.querySelectorAll("[data-agent-mcp-remove]").forEach((element) => element.addEventListener("click", () => {
    void previewAgentMcpRemoval(element.dataset.agentMcpRemove);
  }));
  document.querySelector("#agent-mcp-apply")?.addEventListener("click", applyAgentMcpPreview);
  document.querySelector("#agent-send")?.addEventListener("click", sendAgentPrompt);
  document.querySelector("#agent-prompt")?.addEventListener("input", (event) => {
    state.agentPromptDraft = event.target.value;
    if (state.agentRoutingDecisionKey && state.agentRoutingDecisionKey !== routingTaskKey(state.agentPromptDraft, state.agentRoutingMode)) {
      state.agentRoutingDecision = null;
      state.agentRoutingDecisionKey = "";
      state.agentRoutingPendingKey = "";
      state.agentRoutingApprovedKey = "";
      state.agentRoutingNotice = "";
    }
    const button = document.querySelector("#agent-send");
    if (button) {
      button.disabled = !agentPromptCanSend(
        state.agentStatus,
        Boolean(state.agentPromptDraft.trim() || supportedAgentPromptAttachments().length),
        effectiveAgentMode(),
      );
    }
  });
  document.querySelector("#agent-attach-image")?.addEventListener("click", () => document.querySelector("#agent-image-input")?.click());
  document.querySelector("#agent-image-input")?.addEventListener("change", handleAgentImageSelection);
  document.querySelectorAll("[data-agent-attachment-remove]").forEach((element) => element.addEventListener("click", () => removeAgentAttachment(Number(element.dataset.agentAttachmentRemove))));
  document.querySelectorAll("[data-agent-attachment-load]").forEach((element) => element.addEventListener("click", () => {
    void loadAgentAttachment(element.dataset.agentAttachmentSession, element.dataset.agentAttachmentLoad);
  }));
  document.querySelector("#agent-retry-turn")?.addEventListener("click", retryAgentTurn);
  document.querySelector("#agent-refresh-session")?.addEventListener("click", () => loadAgentSnapshot());
  document.querySelector("#agent-load-older")?.addEventListener("click", loadOlderAgentHistory);
  document.querySelector("#agent-refresh-subagents")?.addEventListener("click", () => loadAgentSubagents());
  document.querySelector("#agent-goal-form")?.addEventListener("submit", createAgentGoal);
  document.querySelectorAll("[data-agent-goal-action]").forEach((element) => element.addEventListener("click", () => {
    void agentGoalAction(element.dataset.agentGoalAction);
  }));
  document.querySelectorAll("[data-agent-subagent-history]").forEach((element) => element.addEventListener("click", () => {
    void loadAgentSubagentHistory(element.dataset.agentSubagentHistory);
  }));
  document.querySelectorAll("[data-agent-subagent-prompt]").forEach((element) => element.addEventListener("click", () => {
    void promptAgentSubagent(element.dataset.agentSubagentPrompt);
  }));
  document.querySelectorAll("[data-agent-subagent-interrupt]").forEach((element) => element.addEventListener("click", () => {
    void interruptAgentSubagent(element.dataset.agentSubagentInterrupt);
  }));
  document.querySelectorAll("[data-agent-queue-action]").forEach((element) => element.addEventListener("click", () => {
    const row = element.closest("[data-agent-queue-row]");
    const input = row?.querySelector("[data-agent-queue-input]");
    const itemId = element.dataset.agentQueueId;
    const text = input?.value ?? (Object.prototype.hasOwnProperty.call(state.agentQueueDrafts, itemId) ? state.agentQueueDrafts[itemId] : "");
    void updateAgentQueue(itemId, element.dataset.agentQueueAction, text);
  }));
  document.querySelectorAll("[data-agent-queue-input]").forEach((element) => element.addEventListener("input", (event) => {
    const itemId = element.closest("[data-agent-queue-row]")?.dataset.agentQueueRow;
    if (itemId) state.agentQueueDrafts = { ...state.agentQueueDrafts, [itemId]: event.target.value };
  }));
  document.querySelector("#agent-fork-session")?.addEventListener("click", forkAgentSession);
  document.querySelector("#agent-cancel-turn")?.addEventListener("click", cancelAgentTurn);
  document.querySelector("#agent-refresh-sessions")?.addEventListener("click", () => loadAgentSessions());
  document.querySelectorAll("[data-agent-session-select]").forEach((element) => element.addEventListener("click", () => selectAgentSession(element.dataset.agentSessionSelect)));
  document.querySelectorAll("[data-agent-approval]").forEach((element) => element.addEventListener("click", () => {
    respondAgentApproval({
      rpcId: element.dataset.agentApproval,
      sessionId: element.dataset.agentApprovalSession,
      approvalId: element.dataset.agentApprovalId,
      outcome: element.dataset.agentApprovalOutcome,
    });
  }));
  document.querySelectorAll("[data-agent-interaction-form]").forEach((element) => element.addEventListener("submit", (event) => {
    event.preventDefault();
    void respondAgentQuestion(element);
  }));
  document.querySelectorAll("[data-agent-interaction-form] input").forEach((element) => element.addEventListener("change", () => captureAgentInteractionDraft(element.closest("[data-agent-interaction-form]"))));
  document.querySelectorAll("[data-agent-interaction-form] [data-agent-custom]").forEach((element) => element.addEventListener("input", () => captureAgentInteractionDraft(element.closest("[data-agent-interaction-form]"))));
  document.querySelectorAll("[data-agent-plan-review-action]").forEach((element) => element.addEventListener("click", () => {
    const interaction = element.closest("[data-agent-plan-review]");
    const action = element.dataset.agentPlanReviewAction;
    if (action === "cancel") void cancelAgentInteraction(interaction);
    else void respondAgentPlanReview(interaction, action);
  }));
  document.querySelectorAll("[data-agent-plan-review-feedback]").forEach((element) => element.addEventListener("input", () => {
    const interaction = element.closest("[data-agent-plan-review]");
    if (!interaction) return;
    const id = interaction.dataset.agentInteractionId;
    const existing = state.agentInteractionDrafts[id] || {};
    state.agentInteractionDrafts = { ...state.agentInteractionDrafts, [id]: { ...existing, plan_review_feedback: element.value } };
  }));
  document.querySelector("#browser-new-session")?.addEventListener("click", createBrowserSession);
  document.querySelectorAll("[data-browser-session-close]").forEach((element) => element.addEventListener("click", () => closeBrowserSession(element.dataset.browserSessionClose)));
  document.querySelector("#browser-new-named-profile")?.addEventListener("click", createNamedBrowserProfile);
  document.querySelectorAll("[data-browser-profile-start]").forEach((element) => element.addEventListener("click", () => startNamedBrowserProfile(element.dataset.browserProfileStart)));
  document.querySelectorAll("[data-browser-profile-archive]").forEach((element) => element.addEventListener("click", () => archiveBrowserProfile(element.dataset.browserProfileArchive)));
  document.querySelectorAll("[data-browser-profile-restore]").forEach((element) => element.addEventListener("click", () => restoreBrowserProfile(element.dataset.browserProfileRestore)));
  document.querySelectorAll("[data-browser-observe]").forEach((element) => element.addEventListener("click", () => observeBrowserSession(element.dataset.browserObserve)));
  document.querySelectorAll("[data-browser-snapshot]").forEach((element) => element.addEventListener("click", () => inspectBrowserSnapshot(element.dataset.browserSnapshot)));
  document.querySelectorAll("[data-browser-help]").forEach((element) => element.addEventListener("click", () => requestBrowserHelp(element.dataset.browserHelp)));
  document.querySelectorAll("[data-browser-console]").forEach((element) => element.addEventListener("click", () => readBrowserDiagnostic(element.dataset.browserConsole, "console")));
  document.querySelectorAll("[data-browser-network]").forEach((element) => element.addEventListener("click", () => readBrowserDiagnostic(element.dataset.browserNetwork, "network")));
  document.querySelectorAll("[data-browser-url]").forEach((element) => element.addEventListener("input", (event) => {
    const session = element.closest(".browser-session-row")?.querySelector("[data-browser-navigate]")?.dataset.browserNavigate;
    if (session) state.browserNavigationDrafts[session] = event.target.value;
  }));
  document.querySelectorAll("[data-browser-navigate]").forEach((element) => element.addEventListener("click", () => navigateBrowserSession(element.dataset.browserNavigate, false)));
  document.querySelectorAll("[data-browser-navigate-approve]").forEach((element) => element.addEventListener("click", () => navigateBrowserSession(element.dataset.browserNavigateApprove, true)));
  document.querySelectorAll("[data-browser-tabs]").forEach((element) => element.addEventListener("click", () => refreshBrowserTabs(element.dataset.browserTabs)));
  document.querySelectorAll("[data-browser-tab-create]").forEach((element) => element.addEventListener("click", () => createBrowserTab(element.dataset.browserTabCreate, false)));
  document.querySelectorAll("[data-browser-tab-create-approve]").forEach((element) => element.addEventListener("click", () => createBrowserTab(element.dataset.browserTabCreateApprove, true)));
  document.querySelectorAll("[data-browser-tab-select]").forEach((element) => element.addEventListener("click", () => selectBrowserTab(element.dataset.browserTabSession, element.dataset.browserTabSelect)));
  document.querySelectorAll("[data-browser-tab-close]").forEach((element) => element.addEventListener("click", () => closeBrowserTab(element.dataset.browserTabSession, element.dataset.browserTabClose)));
  document.querySelector("#browser-refresh-downloads")?.addEventListener("click", () => loadBrowserDownloads());
  document.querySelectorAll("[data-browser-download-release]").forEach((element) => element.addEventListener("click", () => releaseBrowserDownload(element.dataset.browserDownloadRelease)));
  document.querySelector("#browser-developer-mode")?.addEventListener("change", (event) => {
    state.browserDeveloperMode = event.target.checked;
    render();
  });
  document.querySelectorAll("[data-provider-new]").forEach((element) => element.addEventListener("click", () => openProviderDrawer()));
  document.querySelectorAll("[data-provider-edit]").forEach((element) => element.addEventListener("click", () => openProviderDrawer(element.dataset.providerEdit)));
  document.querySelectorAll("[data-provider-select]").forEach((element) => element.addEventListener("click", () => selectProviderProfile(element.dataset.providerSelect)));
  document.querySelectorAll("[data-provider-health]").forEach((element) => element.addEventListener("click", () => testProviderProfile(element.dataset.providerHealth)));
  document.querySelectorAll("[data-provider-model-discover]").forEach((element) => element.addEventListener("click", () => discoverProviderModels(element.dataset.providerModelDiscover)));
  document.querySelectorAll("[data-provider-model-select-profile]").forEach((element) => element.addEventListener("click", () => selectProviderModel(element.dataset.providerModelSelectProfile, element.dataset.providerModelSelectId)));
  document.querySelectorAll("[data-provider-model-health-profile]").forEach((element) => element.addEventListener("click", () => testProviderModel(element.dataset.providerModelHealthProfile, element.dataset.providerModelHealthId)));
  document.querySelector("#refresh-route-pricing")?.addEventListener("click", () => loadRoutePricing(true, true));
  document.querySelectorAll("[data-provider-pricing-refresh]").forEach((element) => element.addEventListener("click", () => loadRoutePricing(true, true)));
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
  document.querySelectorAll("[data-web-chat-new-adapter]").forEach((element) => element.addEventListener("click", () => {
    openWebChatDrawer(null, element.dataset.webChatNewAdapter || "custom");
  }));
  document.querySelectorAll("[data-web-chat-edit]").forEach((element) => element.addEventListener("click", () => {
    openWebChatDrawer(element.dataset.webChatEdit);
  }));
  document.querySelectorAll("[data-web-chat-select]").forEach((element) => element.addEventListener("click", () => {
    void activateWebChatProfile(element.dataset.webChatSelect);
  }));
  document.querySelectorAll("[data-web-chat-authorize]").forEach((element) => element.addEventListener("click", () => {
    void authorizeWebChatProfile(element.dataset.webChatAuthorize);
  }));
  document.querySelectorAll("[data-web-chat-check]").forEach((element) => element.addEventListener("click", () => {
    void checkWebChatProfile(element.dataset.webChatCheck);
  }));
  document.querySelectorAll("[data-web-chat-consent]").forEach((element) => element.addEventListener("click", () => {
    void setWebChatConsent(element.dataset.webChatConsent, true);
  }));
  document.querySelectorAll("[data-web-chat-consent-off]").forEach((element) => element.addEventListener("click", () => {
    void setWebChatConsent(element.dataset.webChatConsentOff, false);
  }));
  document.querySelectorAll("[data-web-chat-archive]").forEach((element) => element.addEventListener("click", () => {
    void archiveWebChatProfile(element.dataset.webChatArchive);
  }));
  document.querySelectorAll("[data-web-chat-restore]").forEach((element) => element.addEventListener("click", () => {
    void restoreWebChatProfile(element.dataset.webChatRestore);
  }));
  document.querySelectorAll("[data-web-chat-drawer-close]").forEach((element) => element.addEventListener("click", closeWebChatDrawer));
  document.querySelector("#web-chat-profile-form")?.addEventListener("submit", saveWebChatProfileFromForm);
  document.querySelector("#web-chat-adapter-select")?.addEventListener("change", (event) => {
    const nextAdapterId = String(event.target.value || "custom");
    const form = event.target.closest("form");
    const previousAdapterId = state.webChatDrawerAdapterId || "custom";
    state.webChatDrawerAdapterId = nextAdapterId;
    applyWebChatAdapterTemplate(form, nextAdapterId, previousAdapterId);
    const advanced = form?.querySelector(".web-chat-advanced");
    if (advanced) advanced.open = nextAdapterId === "custom";
  });
  document.querySelector("[data-web-chat-create-browser-profile]")?.addEventListener("click", () => {
    void createNamedBrowserProfileForWebChat();
  });
  document.querySelectorAll("[data-web-chat-authorize-drawer]").forEach((element) => element.addEventListener("click", () => {
    void authorizeWebChatProfile(element.dataset.webChatAuthorizeDrawer);
  }));
  document.querySelectorAll("[data-web-chat-check-drawer]").forEach((element) => element.addEventListener("click", () => {
    void checkWebChatProfile(element.dataset.webChatCheckDrawer);
  }));
  document.querySelector("#web-workbench-refresh")?.addEventListener("click", () => {
    void loadWebWorkbenchData(true, true);
  });
  document.querySelector("#web-workbench-manual-form")?.addEventListener("submit", sendWebWorkbenchManual);
  document.querySelector("#web-workbench-worker-form")?.addEventListener("submit", startWebWorkbenchWorker);
  document.querySelector("#web-workbench-consultation-form")?.addEventListener("submit", startWebWorkbenchConsultation);
  document.querySelector("#web-workbench-manual-form select[name=profile_id]")?.addEventListener("change", (event) => {
    state.webWorkbenchSelectedProfileId = event.target.value;
    render();
  });
  document.querySelector("#web-workbench-worker-form")?.addEventListener("input", (event) => {
    updateWebWorkbenchDraftFromForm(event.currentTarget);
  });
  document.querySelector("#web-workbench-consultation-form")?.addEventListener("input", (event) => {
    updateWebWorkbenchDraftFromForm(event.currentTarget);
  });
  document.querySelectorAll("[data-web-workbench-open]").forEach((element) => element.addEventListener("click", () => {
    void openWebWorkbenchProfile(element.dataset.webWorkbenchOpen);
  }));
  document.querySelectorAll("[data-web-workbench-focus]").forEach((element) => element.addEventListener("click", () => {
    void focusWebWorkbenchProfile(element.dataset.webWorkbenchFocus);
  }));
  document.querySelectorAll("[data-web-workbench-close]").forEach((element) => element.addEventListener("click", () => {
    void closeWebWorkbenchProfile(element.dataset.webWorkbenchClose);
  }));
  document.querySelectorAll("[data-web-workbench-takeover]").forEach((element) => element.addEventListener("click", () => {
    void takeoverWebWorkbenchProfile(element.dataset.webWorkbenchTakeover);
  }));
  document.querySelectorAll("[data-web-workbench-release]").forEach((element) => element.addEventListener("click", () => {
    void setWebWorkbenchOccupancy(element.dataset.webWorkbenchRelease, "idle");
  }));
  document.querySelectorAll("[data-web-workbench-consultation-cancel]").forEach((element) => element.addEventListener("click", () => {
    void cancelWebWorkbenchConsultation(element.dataset.webWorkbenchConsultationCancel);
  }));
  document.querySelectorAll("[data-web-workbench-consultation-continue]").forEach((element) => element.addEventListener("click", () => {
    void continueWebWorkbenchConsultation(element.dataset.webWorkbenchConsultationContinue);
  }));
  document.querySelectorAll("[data-web-workbench-retry]").forEach((element) => element.addEventListener("click", () => {
    void retryWebWorkbenchDispatch(element.dataset.webWorkbenchRetry);
  }));
  document.querySelectorAll("[data-web-workbench-manual-cancel]").forEach((element) => element.addEventListener("click", () => {
    void cancelWebWorkbenchManual(element.dataset.webWorkbenchManualCancel);
  }));
  document.querySelectorAll("[data-web-workbench-ack]").forEach((element) => element.addEventListener("click", () => {
    void acknowledgeWebWorkbenchPending(element.dataset.webWorkbenchAck);
  }));
  document.querySelector("[data-web-workbench-pause-all]")?.addEventListener("click", () => {
    void pauseAllWebWorkbenchConsultations();
  });
  document.querySelector("[data-web-workbench-continue-latest]")?.addEventListener("click", () => {
    void continueLatestWebWorkbenchConsultation();
  });
  document.querySelector("#check-ccs-compatibility")?.addEventListener("click", checkCcsCompatibility);
  document.querySelector("#refresh-diagnostics")?.addEventListener("click", loadDiagnostics);
  document.querySelector("#refresh-agent-diagnostics")?.addEventListener("click", () => loadAgentDiagnostics());
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
  document.querySelector("#quality-settings-form")?.addEventListener("submit", saveQualityRoutingSettings);
  document.querySelector("[data-quality-settings-refresh]")?.addEventListener("click", () => void loadQualityRoutingSettings(true));
  document.querySelectorAll("[data-model-refresh]").forEach((button) => button.addEventListener("click", () => void refreshModelEvidence()));
  document.querySelector("#quality-plan-form [name=planning_confirmed]")?.addEventListener("change", (event) => {
    state.qualityRouting.planningConfirmed = event.currentTarget.checked;
  });
  document.querySelector("[data-quality-budget-defaults]")?.addEventListener("click", (event) => {
    restoreQualityRule(event.currentTarget.closest("form"));
  });
  document.querySelector("#quality-plan-form")?.addEventListener("submit", planQualityRoutingTask);
  document.querySelector("#quality-plan-form [name=goal]")?.addEventListener("input", (event) => {
    state.qualityRouting.goalDraft = event.target.value;
  });
  document.querySelector("#quality-plan-form [name=external_allowed]")?.addEventListener("change", (event) => {
    const form = event.currentTarget.closest("form");
    state.qualityRouting.goalDraft = form.elements.goal.value;
    state.qualityRouting.allowedCandidateIds = qualityCandidateIdsFromForm(form);
    state.qualityRouting.externalAllowed = event.currentTarget.checked;
    render();
  });
  document.querySelector("#quality-plan-form [name=budget_override]")?.addEventListener("change", (event) => {
    const form = event.currentTarget.closest("form");
    state.qualityRouting.goalDraft = form.elements.goal.value;
    state.qualityRouting.allowedCandidateIds = qualityCandidateIdsFromForm(form);
    state.qualityRouting.externalAllowed = form.elements.external_allowed.checked;
    state.qualityRouting.budgetOverride = event.currentTarget.checked;
    state.qualityRouting.budgetDraft = {
      multiplier: form.elements.multiplier.value,
      extra_cny: form.elements.extra_cny.value,
    };
    render();
  });
  document.querySelectorAll("#quality-plan-form [name=multiplier], #quality-plan-form [name=extra_cny]").forEach((element) => element.addEventListener("input", () => {
    const form = element.closest("form");
    state.qualityRouting.budgetDraft = { multiplier: form.elements.multiplier.value, extra_cny: form.elements.extra_cny.value };
  }));
  document.querySelector("[data-quality-task-budget-defaults]")?.addEventListener("click", (event) => {
    restoreQualityRule(event.currentTarget.closest("form"));
  });
  document.querySelector("[data-quality-workbench-refresh]")?.addEventListener("click", () => void loadQualityRoutingWorkbench(true));
  document.querySelectorAll("[data-quality-task-select]").forEach((element) => element.addEventListener("click", () => {
    state.qualityRouting.selectedTaskId = state.qualityRouting.selectedTaskId === element.dataset.qualityTaskSelect ? null : element.dataset.qualityTaskSelect;
    render();
  }));
  document.querySelectorAll("[data-quality-task-confirm]").forEach((element) => element.addEventListener("click", () => {
    void updateQualityRoutingTask(element.dataset.qualityTaskConfirm, "confirm");
  }));
  document.querySelectorAll("[data-quality-task-cancel]").forEach((element) => element.addEventListener("click", () => {
    void updateQualityRoutingTask(element.dataset.qualityTaskCancel, "cancel");
  }));
  document.querySelectorAll("[data-quality-task-refresh]").forEach((element) => element.addEventListener("click", () => {
    void updateQualityRoutingTask(element.dataset.qualityTaskRefresh, "get");
  }));
  document.querySelectorAll("[data-quality-task-budget-form]").forEach((element) => element.addEventListener("submit", updateRunningQualityTaskBudget));
  document.querySelector("[data-consultation-open]")?.addEventListener("click", () => void openConsultation());
  document.querySelector("[data-consultation-hide]")?.addEventListener("click", () => void changeConsultationVisibility("hide"));
  document.querySelector("[data-consultation-close]")?.addEventListener("click", () => void changeConsultationVisibility("close"));
  document.querySelector("[data-consultation-observe]")?.addEventListener("click", async () => {
    try { await observeConsultation({ attach: true }); } catch (error) { state.consultation.notice = `检查失败：${error.message}`; render(); }
  });
  document.querySelector("[data-consultation-read]")?.addEventListener("click", async () => {
    try {
      const attemptId = state.consultation.activeAttemptId || state.consultation.recoverableAttemptId;
      const result = await invokeDesktop("consultation_action", { operation: "read", attemptId });
      state.consultation.status = consultationStatus(result);
      if (state.consultation.status === "completed") state.consultation.recoverableAttemptId = "";
      render();
    } catch (error) { state.consultation.notice = `读取失败：${error.message}`; render(); }
  });
  document.querySelector("[data-consultation-takeover]")?.addEventListener("click", async () => {
    try { await invokeDesktop("consultation_action", { operation: "takeover" }); state.consultation.takeover = true; state.consultation.notice = "已接管网页咨询。"; render(); } catch (error) { state.consultation.notice = `接管失败：${error.message}`; render(); }
  });
  document.querySelector("[data-consultation-reload]")?.addEventListener("click", async () => {
    try {
      state.consultation.ready = false;
      const result = await invokeDesktop("consultation_action", { operation: "reload" });
      state.consultation.status = consultationStatus(result);
      state.consultation.notice = consultationNotice(result);
    } catch (error) { state.consultation.notice = `返回首页失败：${error.message}`; }
    render();
  });
  document.querySelector("[data-consultation-focus]")?.addEventListener("click", () => {
    state.consultation.focused = !state.consultation.focused;
    render();
    requestAnimationFrame(syncConsultationBounds);
  });
  document.querySelector("[data-consultation-login]")?.addEventListener("click", async () => {
    try {
      state.consultation.ready = false;
      const result = await invokeDesktop("consultation_action", { operation: "login" });
      state.consultation.status = consultationStatus(result);
      state.consultation.notice = consultationNotice(result);
    } catch (error) { state.consultation.notice = `打开登录页失败：${error.message}`; }
    render();
  });
  document.querySelector("[data-consultation-release]")?.addEventListener("click", async () => {
    try { await invokeDesktop("consultation_action", { operation: "release" }); state.consultation.takeover = false; state.consultation.notice = "已释放网页咨询。"; render(); } catch (error) { state.consultation.notice = `释放失败：${error.message}`; render(); }
  });
  document.querySelector("#consultation-manual-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = String(event.currentTarget.elements.text.value || "").trim();
    if (!text || state.consultation.busy || state.consultation.takeover || !state.consultation.visible) return;
    const generation = state.consultation.generation;
    const attemptId = consultationAttemptId();
    state.consultation.busy = true;
    state.consultation.manualDraft = text;
    try {
      const filled = await invokeDesktop("consultation_action", { operation: "fill", attemptId, text });
      if (!state.consultation.visible || state.consultation.generation !== generation || state.consultation.takeover) return;
      if (consultationStatus(filled) !== "filled") throw new Error(consultationStatus(filled));
      await invokeDesktop("consultation_action", { operation: "submit", attemptId });
      state.consultation.activeAttemptId = attemptId;
      state.consultation.manualDraft = "";
    } catch (error) { state.consultation.notice = `手动提交失败：${error.message}`; }
    finally { state.consultation.busy = false; render(); }
  });
  document.querySelector("#consultation-manual-form textarea")?.addEventListener("input", (event) => {
    state.consultation.manualDraft = event.target.value;
  });
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
  document.querySelectorAll("[data-agent-task-session]").forEach((element) => element.addEventListener("click", () => {
    void openAgentTask(element.dataset.agentTaskSession);
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

function rpc(method, params = {}) {
  return workAuthorizationRpc(method, params);
}

async function transportRpc(method, params = {}) {
  if (requiresHostConfirmation(method)) {
    return confirmThroughHost({ method, params, desktop: isDesktopShell, companion: companionWindow,
      transport: transportRpc, invoke: invokeDesktop, openMain: openMainWindow });
  }
  const response = await api("/rpc", { method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method, params }) });
  if (response.error) throw new Error(response.error.message || "JSON-RPC request failed");
  return response.result;
}

function qualityCandidateIdsFromForm(form) {
  return [...form.querySelectorAll('input[name="candidate_id"]:checked')].map((input) => input.value).filter(Boolean);
}

function qualityRuleFromForm(form) {
  const value = normalizeQualityRule({
    multiplier: form.querySelector('[name="multiplier"]')?.value,
    extra_cny: form.querySelector('[name="extra_cny"]')?.value,
  }, { multiplier: "", extra_cny: "" });
  if (!value.multiplier || !value.extra_cny) throw new Error("预算倍率必须不小于 1，额外预算必须不小于 0。");
  return value;
}

function qualityTaskParams(scope, task) {
  return { assistant_id: scope.assistantId, session_id: scope.sessionId, task_id: task.task_id };
}

function replaceQualityTask(task) {
  if (!task?.task_id) return;
  const tasks = state.qualityRouting.tasks;
  const index = tasks.findIndex((item) => item.task_id === task.task_id);
  if (index >= 0) tasks.splice(index, 1, task);
  else tasks.unshift(task);
}

async function loadQualityRoutingSettings(shouldRender = true) {
  void benefitsView.loadStatus();
  const scope = qualityRoutingScope();
  const generation = state.qualityRouting.requestGeneration;
  state.qualityRouting.settingsBusy = true;
  state.qualityRouting.settingsNotice = "";
  if (shouldRender) render();
  const [settingsResult, catalogResult, refreshResult, selectionResult] = await Promise.allSettled([
    rpc("quality.settings.get", { assistant_id: scope.assistantId }),
    rpc("quality.catalog", { assistant_id: scope.assistantId }),
    rpc("model.policy.refresh.status", {}),
    rpc("quality.bindings.select", { assistant_id: scope.assistantId }),
  ]);
  if (!qualityRoutingScopeIsCurrent(scope, generation)) return;
  if (settingsResult.status === "fulfilled") state.qualityRouting.settings = settingsResult.value;
  else state.qualityRouting.settingsNotice = `读取质量协作设置失败：${settingsResult.reason?.message || "请求失败"}`;
  if (catalogResult.status === "fulfilled") state.qualityRouting.catalog = catalogResult.value;
  else if (!state.qualityRouting.settingsNotice) state.qualityRouting.settingsNotice = `读取候选目录失败：${catalogResult.reason?.message || "请求失败"}`;
  state.qualityRouting.settingsBusy = false;
  state.qualityRouting.refresh = refreshResult.status === "fulfilled" ? refreshResult.value : null;
  state.qualityRouting.selection = selectionResult.status === "fulfilled" ? selectionResult.value : null;
  if (shouldRender) render();
}

async function refreshModelEvidence() {
  const quality = state.qualityRouting;
  if (quality.refreshBusy) return;
  quality.refreshBusy = true;
  quality.refreshNotice = "正在只读检查已配置来源，不调用模型…";
  render();
  try {
    const result = await rpc("model.policy.refresh", { kind: "all", force: true });
    quality.refresh = result.refresh;
    quality.refreshNotice = Object.values(result.refresh?.jobs || {}).some((job) => job.state !== "ready")
      ? "部分来源待核对；保留旧观测，但不把它当作新鲜免费额度。" : "来源检查完成；模型健康和固定评测仍独立进行。";
  } catch (error) {
    quality.refreshNotice = `刷新失败：${error.message}`;
  } finally {
    quality.refreshBusy = false;
    render();
  }
}

async function loadQualityRoutingWorkbench(shouldRender = true) {
  const scope = qualityRoutingScope();
  const generation = state.qualityRouting.requestGeneration;
  const quality = state.qualityRouting;
  quality.activeScope = scope;
  quality.busy = true;
  quality.notice = "";
  if (shouldRender) render();
  const [catalogResult, tasksResult, settingsResult] = await Promise.allSettled([
    rpc("quality.catalog", { assistant_id: scope.assistantId }),
    rpc("quality.task.list", { assistant_id: scope.assistantId, session_id: scope.sessionId }),
    rpc("quality.settings.get", { assistant_id: scope.assistantId }),
  ]);
  if (!qualityRoutingScopeIsCurrent(scope, generation)) return;
  if (catalogResult.status === "fulfilled") {
    quality.catalog = catalogResult.value;
    if (!quality.allowedCandidateIds.length) {
      quality.allowedCandidateIds = (catalogResult.value?.candidates || []).filter((candidate) => candidate.authorized && candidate.available && !candidate.external).map((candidate) => candidate.candidate_id);
    }
  } else quality.notice = `读取候选目录失败：${catalogResult.reason?.message || "请求失败"}`;
  if (tasksResult.status === "fulfilled") quality.tasks = Array.isArray(tasksResult.value?.tasks) ? tasksResult.value.tasks : [];
  else if (!quality.notice) quality.notice = `读取协作任务失败：${tasksResult.reason?.message || "请求失败"}`;
  if (settingsResult.status === "fulfilled") quality.settings = settingsResult.value;
  else if (!quality.notice) quality.notice = `读取质量协作设置失败：${settingsResult.reason?.message || "请求失败"}`;
  quality.busy = false;
  if (shouldRender) render();
}

async function saveQualityRoutingSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const scope = qualityRoutingScope();
  const generation = state.qualityRouting.requestGeneration;
  if (state.qualityRouting.settingsBusy) return;
  let budgetRule;
  try {
    budgetRule = qualityRuleFromForm(form);
  } catch (error) {
    state.qualityRouting.settingsNotice = error.message;
    render();
    return;
  }
  state.qualityRouting.settingsBusy = true;
  state.qualityRouting.settingsNotice = "正在保存质量协作设置…";
  render();
  try {
    const settings = await rpc("quality.settings.set", {
      assistant_id: scope.assistantId,
      role_candidate_id: form.elements.role_candidate_id.value || null,
      leader_candidate_id: form.elements.leader_candidate_id.value || null,
      selection_mode: { leader: form.elements.leader_selection_mode.value, role: form.elements.role_selection_mode.value },
      candidate_pool: [...form.querySelectorAll('[name="selection_candidate"]:checked')].map((input) => input.value),
      budget_rule: budgetRule,
    });
    if (qualityRoutingScopeIsCurrent(scope, generation)) {
      state.qualityRouting.settings = settings;
      state.qualityRouting.selection = null;
      state.qualityRouting.settingsNotice = "质量协作设置已保存；预算规则只应用于之后创建的任务。";
    }
  } catch (error) {
    if (qualityRoutingScopeIsCurrent(scope, generation)) state.qualityRouting.settingsNotice = `保存失败：${error.message}`;
  } finally {
    if (qualityRoutingScopeIsCurrent(scope, generation)) {
      state.qualityRouting.settingsBusy = false;
      render();
    }
  }
}

function restoreQualityRule(form) {
  const multiplier = form.querySelector('[name="multiplier"]');
  const extra = form.querySelector('[name="extra_cny"]');
  if (multiplier) multiplier.value = "2";
  if (extra) extra.value = "5";
  state.qualityRouting.budgetDraft = { multiplier: "2", extra_cny: "5" };
}

async function planQualityRoutingTask(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const scope = qualityRoutingScope();
  const generation = state.qualityRouting.requestGeneration;
  const quality = state.qualityRouting;
  const goal = String(form.elements.goal.value || "").trim();
  const allowedCandidateIds = qualityCandidateIdsFromForm(form);
  const externalAllowed = form.elements.external_allowed.checked;
  const budgetOverride = form.elements.budget_override.checked;
  if (!goal || !allowedCandidateIds.length || quality.busy) return;
  let budgetRule = null;
  if (budgetOverride) {
    try {
      budgetRule = qualityRuleFromForm(form);
    } catch (error) {
      quality.notice = error.message;
      render();
      return;
    }
  }
  quality.goalDraft = goal;
  quality.allowedCandidateIds = allowedCandidateIds;
  quality.externalAllowed = externalAllowed;
  quality.budgetOverride = budgetOverride;
  quality.busy = true;
  quality.notice = "正在生成授权计划与报价…";
  render();
  try {
    let task = await rpc("quality.task.plan", {
      assistant_id: scope.assistantId,
      session_id: scope.sessionId,
      goal,
      allowed_candidate_ids: allowedCandidateIds,
      external_allowed: externalAllowed,
      ...(Object.values(quality.settings?.selection_mode || {}).includes("auto") ? { planning_confirmed: form.elements.planning_confirmed?.checked === true } : {}),
    });
    if (budgetRule && task?.task_id) task = await rpc("quality.task.budget", { ...qualityTaskParams(scope, task), budget_rule: budgetRule });
    if (qualityRoutingScopeIsCurrent(scope, generation)) {
      replaceQualityTask(task);
      quality.selectedTaskId = task?.task_id || null;
      quality.notice = "计划和报价已返回；请核对后明确确认执行。";
    }
  } catch (error) {
    if (qualityRoutingScopeIsCurrent(scope, generation)) quality.notice = `生成计划失败：${error.message}`;
  } finally {
    if (qualityRoutingScopeIsCurrent(scope, generation)) {
      quality.busy = false;
      render();
    }
  }
}

async function updateQualityRoutingTask(taskId, action) {
  const quality = state.qualityRouting;
  const scope = qualityRoutingScope();
  const generation = quality.requestGeneration;
  const task = quality.tasks.find((item) => item.task_id === taskId);
  if (!task || !sameQualityRoutingScope(quality.activeScope, scope) || quality.busy) return;
  quality.busy = true;
  quality.notice = action === "confirm" ? "正在确认执行…" : action === "cancel" ? "正在取消任务…" : "正在刷新任务状态…";
  render();
  try {
    const method = action === "confirm" ? "quality.task.confirm" : action === "cancel" ? "quality.task.cancel" : "quality.task.get";
    const params = qualityTaskParams(scope, task);
    if (action === "confirm") params.revision = task.revision;
    const result = await rpc(method, params);
    if (qualityRoutingScopeIsCurrent(scope, generation)) {
      replaceQualityTask(result);
      quality.notice = action === "confirm" ? "已确认执行；进度和结果会随刷新更新。" : action === "cancel" ? "任务已取消。" : "任务状态已刷新。";
    }
  } catch (error) {
    if (qualityRoutingScopeIsCurrent(scope, generation)) quality.notice = `任务操作失败：${error.message}`;
  } finally {
    if (qualityRoutingScopeIsCurrent(scope, generation)) {
      quality.busy = false;
      render();
    }
  }
}

async function updateRunningQualityTaskBudget(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const taskId = form.dataset.qualityTaskBudgetForm;
  const quality = state.qualityRouting;
  const scope = qualityRoutingScope();
  const generation = quality.requestGeneration;
  const task = quality.tasks.find((item) => item.task_id === taskId);
  if (!task || !sameQualityRoutingScope(quality.activeScope, scope) || quality.busy) return;
  let budgetRule;
  try {
    budgetRule = qualityRuleFromForm(form);
  } catch (error) {
    quality.notice = error.message;
    render();
    return;
  }
  quality.busy = true;
  quality.notice = "正在更新运行预算…";
  render();
  try {
    const result = await rpc("quality.task.budget", { ...qualityTaskParams(scope, task), budget_rule: budgetRule });
    if (qualityRoutingScopeIsCurrent(scope, generation)) {
      replaceQualityTask(result);
      quality.notice = "运行预算已更新。";
    }
  } catch (error) {
    if (qualityRoutingScopeIsCurrent(scope, generation)) quality.notice = `更新运行预算失败：${error.message}`;
  } finally {
    if (qualityRoutingScopeIsCurrent(scope, generation)) {
      quality.busy = false;
      render();
    }
  }
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
  return switchDisplayMode("pet");
}

function consultationStatus(result) {
  const status = String(result?.status || "unavailable");
  return status === "login" ? "login-required" : status;
}

function consultationAttemptId() {
  return globalThis.crypto?.randomUUID?.() || `manual-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function stopConsultationPoll() {
  if (state.consultation.pollTimer) clearTimeout(state.consultation.pollTimer);
  state.consultation.pollTimer = null;
}

async function syncConsultationBounds() {
  const consultation = state.consultation;
  if (!consultation.visible || !isDesktopShell || consultation.boundsBusy) return;
  const surface = document.querySelector("[data-consultation-rect]");
  const rect = surface?.getBoundingClientRect();
  const container = surface?.closest(consultation.focused ? ".consultation-panel" : ".embedded-workspace, .drawer-body")?.getBoundingClientRect();
  if (!rect || !container) return;
  const left = Math.max(0, container.left, rect.left);
  const top = Math.max(0, container.top, rect.top);
  const right = Math.min(innerWidth, container.right, rect.right);
  const bottom = Math.min(innerHeight, container.bottom, rect.bottom);
  const generation = consultation.generation;
  consultation.boundsBusy = true;
  try {
    if (right - left < 1 || bottom - top < 1) {
      if (!consultation.surfaceHidden) await invokeDesktop("consultation_hide");
      consultation.surfaceHidden = true;
      return;
    }
    await invokeDesktop("consultation_set_bounds", { x: left, y: top, width: right - left, height: bottom - top });
    if (consultation.surfaceHidden && consultation.visible && consultation.generation === generation) {
      await invokeDesktop("consultation_open");
      consultation.surfaceHidden = false;
    }
  } catch (error) {
    consultation.notice = `调整咨询区域失败：${error.message}`;
  } finally {
    consultation.boundsBusy = false;
  }
}

window.addEventListener("resize", () => void syncConsultationBounds());
document.addEventListener("scroll", () => void syncConsultationBounds(), true);
window.addEventListener("resize", () => void embeddedView.syncBounds().catch(() => {}));

async function completeConsultationAttempt(attemptId, result) {
  if (!state.consultation.attached || !attemptId) return;
  try {
    await rpc("quality.browser.complete", { token: state.consultation.token, attempt_id: attemptId, result });
  } catch (error) {
    state.consultation.notice = `提交咨询结果失败：${error.message}`;
  }
}

async function runConsultationRequest(request, generation) {
  const consultation = state.consultation;
  if (!request || !consultation.visible || consultation.surfaceHidden || consultation.generation !== generation
      || consultation.takeover || !consultation.ready || consultation.activeAttemptId || consultation.recoverableAttemptId) return;
  consultation.activeAttemptId = request.attempt_id;
  try {
    const filled = await invokeDesktop("consultation_action", { operation: "fill", attemptId: request.attempt_id, text: request.question });
    if (!consultation.visible || consultation.generation !== generation || consultation.takeover) return;
    if (consultationStatus(filled) !== "filled") {
      await completeConsultationAttempt(request.attempt_id, { status: consultationStatus(filled) === "login-required" ? "login-required" : "failed", text: filled?.text || "", possibly_sent: false });
      consultation.activeAttemptId = "";
      return;
    }
    if (!consultation.visible || consultation.generation !== generation || consultation.takeover) return;
    const submitted = await invokeDesktop("consultation_action", { operation: "submit", attemptId: request.attempt_id });
    const status = consultationStatus(submitted);
    if (status === "pending") return;
    await completeConsultationAttempt(request.attempt_id, { status: ["login-required", "challenge", "limited"].includes(status) ? status : "unknown", text: submitted?.text || "", possibly_sent: submitted?.possibly_sent === true });
    if (submitted?.possibly_sent) consultation.recoverableAttemptId = request.attempt_id;
    consultation.activeAttemptId = "";
  } catch (error) {
    await completeConsultationAttempt(request.attempt_id, { status: "unknown", text: "", possibly_sent: true });
    consultation.recoverableAttemptId = request.attempt_id;
    consultation.notice = `自动咨询状态未知：${error.message}`;
    consultation.activeAttemptId = "";
  }
}

async function pollConsultation() {
  const consultation = state.consultation;
  if (!consultation.visible || consultation.surfaceHidden || consultation.pollInFlight) return;
  const generation = consultation.generation;
  consultation.pollInFlight = true;
  try {
    if (!consultation.attached) {
      await observeConsultation({ attach: true });
      return;
    }
    if (consultation.activeAttemptId) {
      await rpc("quality.browser.poll", { token: consultation.token, accept_requests: false });
      if (!consultation.visible || consultation.generation !== generation) return;
      const read = await invokeDesktop("consultation_action", { operation: "read", attemptId: consultation.activeAttemptId });
      const status = consultationStatus(read);
      if (!["pending", "ready"].includes(status)) {
        await completeConsultationAttempt(consultation.activeAttemptId, { status: status === "completed" ? "completed" : ["login-required", "challenge", "limited"].includes(status) ? status : "unknown", text: read?.text || "", possibly_sent: read?.possibly_sent === true });
        if (status === "unknown") consultation.recoverableAttemptId = consultation.activeAttemptId;
        consultation.activeAttemptId = "";
      }
    }
    if (!consultation.visible || consultation.generation !== generation) return;
    if (!consultation.activeAttemptId && !consultation.takeover && !consultation.surfaceHidden && !consultation.recoverableAttemptId) {
      await observeConsultation();
      if (!consultation.visible || consultation.generation !== generation || !consultation.ready) return;
      const next = await rpc("quality.browser.poll", { token: consultation.token, accept_requests: true });
      await runConsultationRequest(next?.request, generation);
    }
  } catch (error) {
    consultation.notice = `咨询轮询失败：${error.message}`;
  } finally {
    consultation.pollInFlight = false;
    if (consultation.visible && !consultation.surfaceHidden) consultation.pollTimer = setTimeout(() => void pollConsultation(), 2000);
    render();
  }
}

async function observeConsultation({ attach = false } = {}) {
  const consultation = state.consultation;
  const generation = consultation.generation;
  const observed = await invokeDesktop("consultation_action", { operation: "observe" });
  if (!consultation.visible || consultation.generation !== generation) return observed;
  consultation.status = consultationStatus(observed);
  consultation.ready = consultation.status === "ready";
  consultation.notice = consultationNotice(observed);
  if (attach && consultation.ready && !consultation.attached && !consultation.takeover) {
    const bridge = await rpc("quality.browser.attach", {});
    consultation.token = bridge.token;
    consultation.attached = Boolean(bridge.token);
  }
  return observed;
}

async function openConsultation() {
  if (!isDesktopShell || state.consultation.busy) {
    state.consultation.notice = isDesktopShell ? state.consultation.notice : "网页咨询仅在桌面版可用。";
    render();
    return;
  }
  state.consultation.busy = true;
  try {
    await invokeDesktop("embedded_browser_hide_all");
    state.portalPanelOpen = true;
    state.embeddedBrowser.active = "native-consultation";
    await invokeDesktop("consultation_open");
    state.consultation.visible = true;
    state.avatarVisible = false;
    render();
    requestAnimationFrame(syncConsultationBounds);
    await observeConsultation({ attach: true });
    stopConsultationPoll();
    state.consultation.pollTimer = setTimeout(() => void pollConsultation(), 2000);
  } catch (error) {
    state.consultation.notice = `打开网页咨询失败：${error.message}`;
  } finally {
    state.consultation.busy = false;
    render();
  }
}

async function changeConsultationVisibility(action) {
  state.consultation.generation += 1;
  stopConsultationPoll();
  state.consultation.busy = true;
  try {
    if (action === "hide") await invokeDesktop("consultation_hide");
    else await invokeDesktop("consultation_close");
    state.consultation.visible = false;
    state.consultation.attached = false;
    state.consultation.token = "";
    state.consultation.ready = false;
    state.consultation.surfaceHidden = false;
    state.consultation.activeAttemptId = "";
    state.consultation.recoverableAttemptId = "";
    state.avatarVisible = true;
  } catch (error) {
    state.consultation.notice = `${action === "hide" ? "隐藏" : "关闭"}网页咨询失败：${error.message}`;
  } finally {
    state.consultation.busy = false;
    render();
  }
}

async function switchDisplayMode(mode) {
  if (mode === "pet" && state.portalPanelOpen) await embeddedView.hide();
  if (state.displayBusy) return;
  state.displayBusy = true;
  try {
    const applied = isDesktopShell ? await invokeDesktop("set_display_mode", { mode: displayMode(mode) }) : displayMode(mode);
    state.overlayMode = isDesktopShell ? companionWindow : displayMode(applied) === "pet";
    if (state.overlayMode && state.consultation.visible) void changeConsultationVisibility("hide");
    if (state.sessionNotice.startsWith("切换显示模式失败：")) state.sessionNotice = "";
    state.portalPanelOpen = false;
    if (state.overlayMode && activeAudioCapture) {
      discardAudioCapture(activeAudioCapture);
      activeAudioCapture = null;
      state.voiceRecording = false;
    }
  } catch (error) {
    state.sessionNotice = `切换显示模式失败：${error.message}`;
  } finally {
    state.displayBusy = false;
    render();
  }
}

async function hideDesktopOverlay() {
  try {
    const applied = await invokeDesktop("hide_pet");
    state.overlayMode = companionWindow || displayMode(applied) === "pet";
    render();
  } catch (error) {
    state.sessionNotice = `隐藏桌面 Avatar 失败：${error.message}`;
    render();
  }
}

async function openMainWindow() {
  if (isDesktopShell) return invokeDesktop("show_main_window");
  return window.open(location.origin + location.pathname, "sumika-workspace");
}

async function setCompanionSize(mode) {
  try {
    if (isDesktopShell) await invokeDesktop("set_companion_mode", { mode });
    else if (mode === "fullscreen") await document.documentElement.requestFullscreen();
    document.body.dataset.companionSize = mode;
    render();
  } catch (error) { state.sessionNotice = error.message; render(); }
}

async function startOverlayDrag(event) {
  if (!isDesktopShell || event.button !== 0 || event.isPrimary === false) return;
  if (!event.target.closest("[data-overlay-drag-surface]") || event.target.closest("[data-no-drag],button,input,textarea,select,a")) return;
  event.preventDefault();
  try {
    await invokeDesktop("start_pet_drag");
  } catch (error) {
    console.warn("Sumika desktop pet drag failed", error);
  }
}

async function loadProviders(shouldRender = true) {
  try {
    state.providers = await api("/api/providers");
    state.connected = true;
    await workbenchHost.refresh();
    syncProviderSelection();
  } catch (error) {
    state.providers = [];
    state.connected = false;
  }
  if (shouldRender) render();
}

async function loadCapabilityCatalog(shouldRender = true, refresh = false) {
  if (state.capabilityCatalogBusy) return;
  state.capabilityCatalogBusy = true;
  if (shouldRender) render();
  try {
    const query = new URLSearchParams();
    if (refresh) query.set("refresh", "true");
    state.capabilityCatalog = await api(`/api/capabilities${query.toString() ? `?${query.toString()}` : ""}`);
    const errors = Number(state.capabilityCatalog?.summary?.source_errors || 0);
    state.capabilityCatalogNotice = errors ? `目录已读取，但有 ${errors} 个来源暂不可用。` : "";
  } catch (error) {
    if (!state.capabilityCatalog) state.capabilityCatalog = null;
    state.capabilityCatalogNotice = `统一能力目录暂不可用：${error.message}`;
  } finally {
    state.capabilityCatalogBusy = false;
    if (shouldRender) render();
  }
}

async function loadAgentRuntime(shouldRender = true) {
  try {
    state.agentStatus = await api("/api/agent/status");
  } catch {
    state.agentStatus = { state: "unavailable", ready: false, reason: "核心未连接" };
    state.agentProvider = { state: "unavailable", ready: false, reason: "核心未连接" };
  }
  if (!agentSupports("attachments")) {
    state.agentPromptAttachments = [];
    state.agentAttachmentNotice = "";
  }
  try {
    state.browserStatus = await api("/api/browser/status");
  } catch {
    state.browserStatus = { state: "unavailable", ready: false };
  }
  try {
    const result = await rpc("browser.profiles", { include_archived: true });
    state.browserProfiles = Array.isArray(result?.profiles) ? result.profiles : [];
  } catch {
    state.browserProfiles = [];
  }
  try {
    const result = await rpc("browser.sessions");
    state.browserSessions = Array.isArray(result?.sessions) ? result.sessions : [];
  } catch {
    state.browserSessions = [];
  }
  await Promise.all([loadBrowserDownloads(false), ...state.browserSessions.map((session) => loadBrowserTabs(session.id, false))]);
  try {
    state.agentProvider = await api("/api/agent/provider");
  } catch {
    state.agentProvider = { state: "unavailable", ready: false };
  }
  // Directory views are useful even when DSH is offline.  MCP is queried only
  // while its page is visible because the catalog may require several runtime
  // probes; Skill discovery itself remains local metadata-only bookkeeping.
  if (state.activePage === "Agent" || state.activePage === "Developer") {
    await Promise.all([
      loadAgentSkills(false),
      loadAgentMcpCatalog(false),
    ]);
  }
  if (state.agentStatus?.ready) {
    await Promise.all([loadAgentWorkspaces(false), loadAgentSessions(false)]);
    if (state.agentSessionId) await loadAgentWorkspaces(false);
    await loadAgentPresets(false);
    await Promise.all([loadAgentCapabilities(false), loadAgentInteractions(false)]);
    await loadAgentMcpConfigurations(false);
  } else {
    state.agentPresets = [];
    state.agentPresetAuthorable = false;
    state.agentPresetHasDocument = false;
    state.agentPresetId = "";
    state.agentPresetValidation = {};
    state.agentMcpPresetId = "";
    state.agentMcpConfigurations = [];
    state.agentMcpClientInstalled = false;
    state.agentMcpClientVersion = "";
    state.agentMcpCredentialFieldsSupported = false;
    state.agentMcpCredentialStorage = "unavailable";
    state.agentMcpPendingSecret = "";
    state.agentMcpPreview = null;
    state.agentSubagents = [];
    state.agentSubagentHistories = {};
    state.agentGoal = null;
    state.agentInteractions = [];
    state.agentWorkspaces = [];
    state.agentQueue = { known: false, items: [], hidden_context_count: 0, updated_at: null };
    state.agentModels = { current: {}, routable: false, groups: [], failures: [] };
  }
  if (state.agentStatus?.ready && state.agentSessionId) {
    await Promise.all([loadAgentSnapshot(false), loadAgentModels(false), loadAgentQueue(false), loadAgentSubagents(false)]);
  }
  if (state.activePage === "Agent") await loadAgentModelPolicy(false, false);
  if (shouldRender) render();
}

async function loadAgentModelPolicy(shouldRender = true, refresh = false) {
  if (state.agentModelPolicyBusy) return;
  if (!refresh && state.agentModelPolicyCatalog && Date.now() - state.agentModelPolicyLoadedAt < 15_000) {
    return;
  }
  state.agentModelPolicyBusy = true;
  if (shouldRender) render();
  const sessionQuery = state.agentSessionId ? `&session_id=${encodeURIComponent(state.agentSessionId)}` : "";
  try {
    const [catalog, quota] = await Promise.all([
      api(`/api/model-policy/catalog?refresh=${refresh ? "true" : "false"}${sessionQuery}`),
      api(`/api/model-policy/quota?refresh=${refresh ? "true" : "false"}`),
    ]);
    state.agentModelPolicyCatalog = catalog && typeof catalog === "object" ? catalog : null;
    state.agentModelPolicyQuota = quota && typeof quota === "object" ? quota : null;
    state.agentModelPolicyLoadedAt = Date.now();
    if (state.agentRoutingNotice.startsWith("策略目录")) state.agentRoutingNotice = "";
  } catch (error) {
    state.agentRoutingNotice = `策略目录读取失败：${error.message}`;
  } finally {
    state.agentModelPolicyBusy = false;
    if (shouldRender) render();
  }
}

async function syncAgentState({ immediate = false } = {}) {
  // A refresh must never rebuild the Agent surface while a user mutation is
  // in flight. Queue one follow-up instead; the operation's own render keeps
  // the current draft and confirmation state visible meanwhile.
  if (state.agentBusy) {
    state.agentSyncQueued = true;
    return false;
  }
  if (agentSyncInFlight) {
    state.agentSyncQueued = true;
    return false;
  }
  agentSyncInFlight = true;
  state.agentSyncing = true;
  try {
    await loadAgentRuntime(false);
    await loadCapabilityCatalog(false, false);
    await loadAgentTaskProjections(false);
    return true;
  } catch {
    return false;
  } finally {
    agentSyncInFlight = false;
    state.agentSyncing = false;
    const rerun = state.agentSyncQueued && !state.agentBusy;
    state.agentSyncQueued = false;
    if (!state.agentBusy) render();
    if (rerun) {
      window.setTimeout(() => { void syncAgentState({ immediate: true }); }, 0);
    }
    // `immediate` is intentionally a scheduling hint for callers (focus,
    // reconnect, visibility); it does not bypass the busy guard above.
    void immediate;
  }
}

function scheduleAgentStateSync() {
  if (agentSyncTimer !== null) window.clearTimeout(agentSyncTimer);
  agentSyncTimer = window.setTimeout(async () => {
    agentSyncTimer = null;
    await syncAgentState();
    scheduleAgentStateSync();
  }, AGENT_SYNC_INTERVAL_MS);
}

async function loadAgentInteractions(shouldRender = true) {
  if (!state.agentStatus?.ready || !agentSupports("interactions")) {
    state.agentInteractions = [];
    if (shouldRender) render();
    return;
  }
  try {
    const result = await rpc("agent.interactions", state.agentSessionId ? { sessionId: state.agentSessionId } : {});
    state.agentInteractions = Array.isArray(result?.interactions) ? result.interactions : [];
  } catch {
    state.agentInteractions = [];
  }
  if (shouldRender) render();
}

async function loadBrowserDownloads(shouldRender = true) {
  try {
    const result = await rpc("browser.downloads");
    state.browserDownloads = Array.isArray(result?.downloads) ? result.downloads : [];
  } catch {
    state.browserDownloads = [];
  }
  if (shouldRender) render();
}

async function loadBrowserTabs(sessionId, shouldRender = true) {
  if (!sessionId) return;
  try {
    const result = await rpc("browser.tabs", { session_id: sessionId, scope: "agent" });
    const tabs = Array.isArray(result?.tabs) ? result.tabs : [];
    state.browserTabs = { ...state.browserTabs, [sessionId]: tabs };
    const active = tabs.find((tab) => tab.active === true)?.id;
    if (active) state.browserActiveTabs = { ...state.browserActiveTabs, [sessionId]: active };
  } catch {
    state.browserTabs = { ...state.browserTabs, [sessionId]: [] };
  }
  if (shouldRender) render();
}

async function loadAgentQueue(shouldRender = true) {
  if (!state.agentSessionId || !state.agentStatus?.ready || !agentSupports("queue")) {
    state.agentQueue = { known: false, items: [], hidden_context_count: 0, updated_at: null };
    if (shouldRender) render();
    return;
  }
  try {
    state.agentQueue = await rpc("agent.session.queue", { sessionId: state.agentSessionId });
  } catch {
    state.agentQueue = { known: false, items: [], hidden_context_count: 0, updated_at: null };
  }
  if (shouldRender) render();
}

async function loadAgentSessions(shouldRender = true) {
  if (!state.agentStatus?.ready) {
    state.agentSessions = [];
    state.agentSessionSearchResults = null;
    state.agentSessionSearchNotice = "";
    if (shouldRender) render();
    return;
  }
  try {
    const result = await rpc("agent.sessions");
    state.agentSessions = Array.isArray(result?.sessions) ? result.sessions : [];
    let selected = state.agentSessions.find((session) => session.id === state.agentSessionId);
    if (!selected && state.agentSessions.length) {
      const preference = readAgentSessionPreference();
      const runtimeId = agentRuntimePreferenceId();
      const preferred = preference?.runtime_id === runtimeId
        ? state.agentSessions.find((session) => session.id === preference.session_id)
        : null;
      selected = preferred || state.agentSessions[0];
      const previousSessionId = state.agentSessionId;
      setAgentSessionId(selected.id);
      if (previousSessionId !== state.agentSessionId) resetAgentHistoryPaging();
      state.agentNotice = preferred
        ? `已恢复上次 Agent 会话：${selected.title || selected.id}`
        : previousSessionId
          ? `原 Agent 会话已不可用，已切换到最近会话：${selected.title || selected.id}`
          : `已打开最近 Agent 会话：${selected.title || selected.id}`;
    }
    if (selected) {
      state.agentPresetId = selected.agent_preset || "";
      if (!state.agentSessionRenameDraft) state.agentSessionRenameDraft = selected.title || "";
      rememberAgentSession(selected.id);
    } else if (!state.agentSessionId) {
      setAgentSessionId(null);
      state.agentSnapshot = null;
      state.agentGoal = null;
      resetAgentHistoryPaging();
      state.agentSessionRenameDraft = "";
      clearAgentSessionPreference();
    }
  } catch {
    state.agentSessions = [];
  }
  if (shouldRender) render();
}

async function searchAgentSessions() {
  const query = String(state.agentSessionSearchQuery || "").trim();
  if (!query || state.agentSessionSearchBusy || !state.agentStatus?.ready || !agentSupports("session-search")) {
    if (!query) {
      state.agentSessionSearchResults = null;
      state.agentSessionSearchNotice = "";
      render();
    }
    return;
  }
  state.agentSessionSearchBusy = true;
  state.agentSessionSearchNotice = `正在搜索受管 ${agentRuntimeLabel()} 会话…`;
  render();
  try {
    const result = await rpc("agent.sessions.search", { query });
    state.agentSessionSearchResults = Array.isArray(result?.items) ? result.items : [];
    state.agentSessionSearchNotice = result?.has_more
      ? "结果已达到当前上限，请缩小搜索范围。"
      : `找到 ${state.agentSessionSearchResults.length} 个会话。`;
  } catch (error) {
    state.agentSessionSearchResults = [];
    state.agentSessionSearchNotice = `搜索不可用：${error.message}`;
  } finally {
    state.agentSessionSearchBusy = false;
    render();
  }
}

function clearAgentSessionSearch() {
  state.agentSessionSearchQuery = "";
  state.agentSessionSearchResults = null;
  state.agentSessionSearchNotice = "";
  render();
}

async function renameAgentSession() {
  if (!state.agentSessionId || state.agentBusy) return;
  const title = String(state.agentSessionRenameDraft || document.querySelector("#agent-session-title")?.value || "").trim();
  if (!title) {
    state.agentNotice = "会话名称不能为空。";
    render();
    return;
  }
  state.agentBusy = "rename-session";
  state.agentNotice = "正在保存会话名称…";
  render();
  try {
    const result = await rpc("agent.session.rename", { sessionId: state.agentSessionId, title });
    state.agentSessions = state.agentSessions.map((session) => session.id === state.agentSessionId ? { ...session, title: result.title } : session);
    if (state.agentSnapshot?.session_id === state.agentSessionId) state.agentSnapshot = { ...state.agentSnapshot, title: result.title };
    state.agentSessionRenameDraft = result.title || title;
    state.agentNotice = "会话名称已保存。";
  } catch (error) {
    state.agentNotice = `保存会话名称失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function handleAgentImageSelection(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;
  const current = Array.isArray(state.agentPromptAttachments) ? state.agentPromptAttachments : [];
  const accepted = [];
  const rejected = [];
  for (const file of files) {
    if (!["image/png", "image/jpeg", "image/webp", "image/gif"].includes(file.type)) {
      rejected.push(`${file.name || "图片"}：格式不支持`);
      continue;
    }
    if (file.size > 12 * 1024 * 1024) {
      rejected.push(`${file.name || "图片"}：超过 12 MB`);
      continue;
    }
    if (current.length + accepted.length >= 16) {
      rejected.push("最多附加 16 张图片");
      break;
    }
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error("读取失败"));
        reader.readAsDataURL(file);
      });
      const comma = dataUrl.indexOf(",");
      const data = comma >= 0 ? dataUrl.slice(comma + 1) : "";
      if (!data) throw new Error("数据为空");
      accepted.push({ name: file.name || "图片", mediaType: file.type, data, bytes: file.size });
    } catch {
      rejected.push(`${file.name || "图片"}：读取失败`);
    }
  }
  state.agentPromptAttachments = [...current, ...accepted];
  state.agentAttachmentNotice = rejected.length ? rejected.join("；") : (accepted.length ? `已添加 ${accepted.length} 张图片。` : "");
  render();
}

function removeAgentAttachment(index) {
  if (!Number.isInteger(index) || index < 0 || index >= state.agentPromptAttachments.length) return;
  state.agentPromptAttachments = state.agentPromptAttachments.filter((_, itemIndex) => itemIndex !== index);
  state.agentAttachmentNotice = "";
  render();
}

async function loadAgentAttachment(sessionId, attachmentId) {
  const session = String(sessionId || "").trim();
  const id = String(attachmentId || "").trim();
  if (!session || !id || state.agentAttachmentBusy) return;
  state.agentAttachmentBusy = id;
  render();
  try {
    const result = await rpc("agent.session.attachment", { sessionId: session, attachmentId: id });
    const mediaType = result?.attachment?.media_type;
    const data = result?.data;
    if (!/^image\/(png|jpeg|webp|gif)$/.test(String(mediaType || "")) || typeof data !== "string") {
      throw new Error("附件格式无效");
    }
    const nextPreviews = { ...state.agentAttachmentPreviews, [id]: `data:${mediaType};base64,${data}` };
    const previewIds = Object.keys(nextPreviews);
    state.agentAttachmentPreviews = Object.fromEntries(previewIds.slice(-8).map((previewId) => [previewId, nextPreviews[previewId]]));
    state.agentNotice = "已读取会话图片；图片正文不会进入 Sumika 审计日志。";
  } catch (error) {
    state.agentNotice = `读取会话图片失败：${error.message}`;
  } finally {
    state.agentAttachmentBusy = null;
    render();
  }
}

async function loadAgentPresets(shouldRender = true) {
  if (!state.agentStatus?.ready || !agentSupports("presets")) {
    state.agentPresets = [];
    state.agentPresetAuthorable = false;
    state.agentPresetHasDocument = false;
    state.agentPresetValidation = {};
    state.agentMcpPresetId = "";
    state.agentMcpConfigurations = [];
    state.agentMcpClientInstalled = false;
    state.agentMcpClientVersion = "";
    state.agentMcpPreview = null;
    if (shouldRender) render();
    return;
  }
  try {
    const result = await rpc("agent.presets");
    state.agentPresets = Array.isArray(result?.presets) ? result.presets : [];
    state.agentPresetAuthorable = result?.authorable === true;
    state.agentPresetHasDocument = result?.has_document === true || result?.hasDocument === true;
    const usable = state.agentPresets.filter((item) => item && item.id && !item.broken);
    const knownIds = new Set(state.agentPresets.map((item) => item?.id).filter(Boolean));
    state.agentPresetValidation = Object.fromEntries(
      Object.entries(state.agentPresetValidation).filter(([id]) => knownIds.has(id))
    );
    const selected = usable.find((item) => item.is_default);
    if (!state.agentPresetId && selected) state.agentPresetId = selected.id;
    if (!state.agentPresetCopySource || !usable.some((item) => item.id === state.agentPresetCopySource)) {
      state.agentPresetCopySource = usable[0]?.id || "";
    }
    const userPresets = usable.filter((item) => item.trust === "user");
    if (!userPresets.some((item) => item.id === state.agentMcpPresetId)) {
      state.agentMcpPresetId = userPresets[0]?.id || "";
      state.agentMcpConfigurations = [];
      state.agentMcpPreview = null;
    }
  } catch {
    state.agentPresets = [];
    state.agentPresetAuthorable = false;
    state.agentPresetHasDocument = false;
    state.agentPresetValidation = {};
    state.agentMcpPresetId = "";
    state.agentMcpConfigurations = [];
    state.agentMcpClientInstalled = false;
    state.agentMcpClientVersion = "";
    state.agentMcpPreview = null;
  }
  if (shouldRender) render();
}

async function loadAgentMcpConfigurations(shouldRender = true) {
  const preset = validAgentPresetSlug(state.agentMcpPresetId);
  const entry = state.agentPresets.find((item) => item.id === preset && item.trust === "user" && !item.broken);
  if (!state.agentStatus?.ready || !agentSupports("mcp-configuration") || !entry) {
    state.agentMcpConfigurations = [];
    state.agentMcpClientInstalled = false;
    state.agentMcpClientVersion = "";
    state.agentMcpCredentialFieldsSupported = false;
    state.agentMcpCredentialStorage = "unavailable";
    state.agentMcpPendingSecret = "";
    state.agentMcpPreview = null;
    if (shouldRender) render();
    return;
  }
  try {
    const result = await rpc("agent.mcp.configurations", { agentPreset: preset });
    state.agentMcpConfigurations = Array.isArray(result?.configurations) ? result.configurations : [];
    state.agentMcpClientInstalled = result?.client_installed === true;
    state.agentMcpClientVersion = result?.client_version || "";
    state.agentMcpCredentialFieldsSupported = result?.credential_fields_supported === true;
    state.agentMcpCredentialStorage = result?.credential_storage || "unavailable";
  } catch (error) {
    state.agentMcpConfigurations = [];
    state.agentMcpClientInstalled = false;
    state.agentMcpClientVersion = "";
    state.agentMcpCredentialFieldsSupported = false;
    state.agentMcpCredentialStorage = "unavailable";
    state.agentMcpPendingSecret = "";
    state.agentNotice = `MCP 配置读取失败：${error.message}`;
  }
  if (shouldRender) render();
}

async function loadAgentSubagents(shouldRender = true) {
  if (!state.agentSessionId || !state.agentStatus?.ready || !agentSupports("subagents")) {
    state.agentSubagents = [];
    state.agentSubagentHistories = {};
    if (shouldRender) render();
    return;
  }
  try {
    const result = await rpc("agent.subagent.list", { parentSessionId: state.agentSessionId });
    state.agentSubagents = Array.isArray(result?.entries) ? result.entries : [];
    const validIds = new Set(state.agentSubagents.filter((entry) => entry.kind === "child").map((entry) => entry.id));
    state.agentSubagentHistories = Object.fromEntries(Object.entries(state.agentSubagentHistories).filter(([id]) => validIds.has(id)));
  } catch {
    state.agentSubagents = [];
  }
  if (shouldRender) render();
}

async function loadAgentWorkspaces(shouldRender = true) {
  const requestGeneration = ++agentWorkspaceRequestGeneration;
  const sessionGeneration = agentSessionGeneration;
  const sessionId = state.agentSessionId;
  if (!state.agentStatus?.ready || !agentSupports("workspaces")) {
    if (requestGeneration !== agentWorkspaceRequestGeneration) return;
    state.agentWorkspaces = [];
    if (shouldRender) render();
    return;
  }
  try {
    const result = await rpc("agent.workspaces");
    if (requestGeneration !== agentWorkspaceRequestGeneration || sessionGeneration !== agentSessionGeneration || sessionId !== state.agentSessionId) return;
    state.agentWorkspaces = Array.isArray(result?.workspaces) ? result.workspaces : [];
    const owner = state.agentWorkspaces.find((workspace) => (workspace.session_ids || []).includes(sessionId));
    if (owner) {
      state.agentWorkspaceId = owner.id;
      state.workspaceRuntimePath = owner.path || state.workspaceRuntimePath;
    }
    else if (state.agentWorkspaceId && !state.agentWorkspaces.some((workspace) => workspace.id === state.agentWorkspaceId)) state.agentWorkspaceId = "";
    const selected = state.agentWorkspaces.find((workspace) => workspace.id === state.agentWorkspaceId);
    if (!state.workspaceRuntimePath && selected?.path) state.workspaceRuntimePath = selected.path;
  } catch {
    if (requestGeneration !== agentWorkspaceRequestGeneration || sessionGeneration !== agentSessionGeneration || sessionId !== state.agentSessionId) return;
    state.agentWorkspaces = [];
  }
  if (requestGeneration === agentWorkspaceRequestGeneration && sessionGeneration === agentSessionGeneration && sessionId === state.agentSessionId && shouldRender) render();
}

async function loadAgentModels(shouldRender = true) {
  if (!state.agentSessionId || !state.agentStatus?.ready || !agentSupports("models")) {
    state.agentModels = { current: {}, routable: false, groups: [], failures: [] };
    if (shouldRender) render();
    return;
  }
  try {
    state.agentModels = await rpc("agent.session.models", { sessionId: state.agentSessionId });
  } catch (error) {
    state.agentModels = { current: {}, routable: false, groups: [], failures: [{ id: "catalog", name: agentRuntimeLabel(), message: error.message }] };
  }
  if (shouldRender) render();
}

async function selectAgentSession(sessionId) {
  const value = String(sessionId || "").trim();
  if (!value || state.agentBusy) return;
  setAgentSessionId(value);
  rememberAgentSession(value);
  resetAgentHistoryPaging();
  state.agentGoal = null;
  state.agentSubagentHistories = {};
  state.agentNotice = `已选择 Agent 会话：${value}`;
  const selected = state.agentSessions.find((session) => session.id === value);
  state.agentPresetId = selected?.agent_preset || "";
  state.agentSessionRenameDraft = selected?.title || "";
  await Promise.all([loadAgentSnapshot(false), loadAgentCapabilities(false), loadAgentModels(false), loadAgentInteractions(false), loadAgentQueue(false), loadAgentSubagents(false), loadAgentMcpCatalog(false)]);
  await loadAgentWorkspaces(false);
  state.agentModelPolicyLoadedAt = 0;
  await loadAgentModelPolicy(false, false);
  render();
}

async function loadEvolutionRegistry(shouldRender = true) {
  try { state.evolutionRegistry = await api("/api/evolution/registry"); } catch { state.evolutionRegistry = []; }
  if (shouldRender) render();
}

async function loadAgentCapabilities(shouldRender = true) {
  const requestGeneration = ++agentCapabilitiesRequestGeneration;
  const sessionGeneration = agentSessionGeneration;
  const sessionId = state.agentSessionId;
  if (!state.agentStatus?.ready) return;
  const values = {};
  const capabilityMethods = [["skills", "skills", "agent.skills"], ["mcp", "mcp", "agent.mcp.inventory"], ["subagents", "subagents", "agent.subagents"], ["commands", "commands", "agent.commands"]];
  for (const [key, capability, method] of capabilityMethods.filter(([, capability]) => agentSupports(capability))) {
    const params = key === "subagents"
      ? (sessionId ? { parentSessionId: sessionId } : {})
      : (sessionId ? { sessionId } : {});
    try { values[key] = await rpc(method, params); } catch { values[key] = { available: false }; }
  }
  if (requestGeneration !== agentCapabilitiesRequestGeneration || sessionGeneration !== agentSessionGeneration || sessionId !== state.agentSessionId) return;
  state.agentCapabilities = { ...state.agentCapabilities, ...values };
  if (shouldRender) render();
}

async function loadAgentMcpCatalog(shouldRender = true) {
  if (state.agentMcpCatalogBusy) return;
  state.agentMcpCatalogBusy = true;
  if (shouldRender) render();
  const params = state.agentSessionId ? { sessionId: state.agentSessionId } : {};
  try {
    state.agentMcpCatalog = await rpc("agent.mcp.catalog", params);
  } catch (error) {
    state.agentMcpCatalog = {
      available: false,
      status: state.agentStatus?.ready ? "unavailable" : "unavailable",
      catalog_available: false,
      entries: [],
      server_count: 0,
      tool_count: 0,
      reason: String(error.message || "MCP 目录不可用").slice(0, 240),
    };
  } finally {
    state.agentMcpCatalogBusy = false;
  }
  if (shouldRender) render();
}

async function loadAgentSkills(shouldRender = true, refresh = false) {
  if (state.agentSkillsBusy) return;
  state.agentSkillsBusy = refresh ? "refresh" : "load";
  if (shouldRender) render();
  try {
    const result = await rpc("agent.skills.catalog", { refresh });
    state.agentSkillsCatalog = Array.isArray(result?.skills) ? result.skills : [];
  } catch (error) {
    state.agentSkillsNotice = `Skill 目录读取失败：${String(error.message || "未知错误").slice(0, 240)}`;
  } finally {
    state.agentSkillsBusy = null;
  }
  if (shouldRender) render();
}

async function discoverAgentSkills() {
  if (state.agentSkillsBusy) return;
  const input = document.querySelector("#agent-skills-path");
  const rawPath = String(input?.value || state.agentSkillsPath || "").trim();
  state.agentSkillsPath = rawPath;
  state.agentSkillsBusy = "discover";
  state.agentSkillsNotice = "正在读取 Skill 元数据和哈希；不会执行正文。";
  render();
  try {
    const params = rawPath ? { paths: [rawPath] } : {};
    const result = await rpc("agent.skills.discover", params);
    state.agentSkillsCatalog = Array.isArray(result?.skills) ? result.skills : [];
    state.agentSkillsNotice = `扫描完成：发现 ${Number(result?.count || state.agentSkillsCatalog.length)} 个 Skill 候选。`;
  } catch (error) {
    state.agentSkillsNotice = `Skill 扫描失败：${error.message}`;
  } finally {
    state.agentSkillsBusy = null;
    render();
  }
}

async function approveAgentSkill(candidateId) {
  const skill = state.agentSkillsCatalog.find((item) => item.candidate_id === candidateId);
  if (!skill || state.agentSkillsBusy) return;
  if (!window.confirm(`批准登记 Skill“${skill.name || skill.skill_id || candidateId}”？只保存元数据，不会执行或安装它。`)) return;
  state.agentSkillsBusy = `approve:${candidateId}`;
  state.agentSkillsNotice = "正在重新读取 SKILL.md，确认哈希未变化…";
  render();
  try {
    const result = await rpc("agent.skills.approve", { candidate_id: candidateId, approved: true, confirm_skill_id: candidateId });
    state.agentSkillsCatalog = state.agentSkillsCatalog.map((item) => item.candidate_id === candidateId ? result : item);
    state.agentSkillsNotice = "Skill 已批准登记；活动会话仍由 DSH skill.list 决定。";
  } catch (error) {
    state.agentSkillsNotice = `批准 Skill 失败：${error.message}`;
  } finally {
    state.agentSkillsBusy = null;
    render();
  }
}

async function revokeAgentSkill(candidateId) {
  const skill = state.agentSkillsCatalog.find((item) => item.candidate_id === candidateId);
  if (!skill || state.agentSkillsBusy || !window.confirm(`撤销 Skill“${skill.name || skill.skill_id || candidateId}”的登记？原始文件不会被删除。`)) return;
  state.agentSkillsBusy = `revoke:${candidateId}`;
  render();
  try {
    const result = await rpc("agent.skills.revoke", { candidate_id: candidateId, approved: true, confirm_skill_id: candidateId });
    state.agentSkillsCatalog = state.agentSkillsCatalog.map((item) => item.candidate_id === candidateId ? result : item);
    state.agentSkillsNotice = "Skill 登记已撤销；运行中的 DSH 会话不会被静默改写。";
  } catch (error) {
    state.agentSkillsNotice = `撤销 Skill 失败：${error.message}`;
  } finally {
    state.agentSkillsBusy = null;
    render();
  }
}

function agentSnapshotItemKey(item, index) {
  if (!item || typeof item !== "object") return `index:${index}:${String(item)}`;
  if (item.call_id) return `call:${item.call_id}`;
  if (item.id) return `id:${item.id}`;
  const sequence = item.seq ?? item.completed_seq;
  if (sequence !== undefined && sequence !== null) {
    return `seq:${sequence}:${item.type || item.name || item.role || "item"}`;
  }
  return `value:${JSON.stringify(item)}`;
}

function resetAgentHistoryPaging() {
  state.agentHistoryBeforeSeq = null;
  state.agentHistoryHasMore = false;
  state.agentHistoryPagingStarted = false;
  state.agentHistoryLoading = false;
}

function mergeAgentSnapshotItems(older, current) {
  const merged = new Map();
  for (const [index, item] of [...(Array.isArray(older) ? older : []), ...(Array.isArray(current) ? current : [])].entries()) {
    if (!item || typeof item !== "object") continue;
    merged.set(agentSnapshotItemKey(item, index), item);
  }
  return [...merged.values()].sort((left, right) => {
    const leftSeq = Number(left.seq ?? left.start_seq ?? left.end_seq ?? left.completed_seq);
    const rightSeq = Number(right.seq ?? right.start_seq ?? right.end_seq ?? right.completed_seq);
    if (Number.isFinite(leftSeq) && Number.isFinite(rightSeq) && leftSeq !== rightSeq) return leftSeq - rightSeq;
    return 0;
  });
}

function mergeAgentSnapshot(current, incoming, { prepend = false, preserveCollections = false, mergeCollections = false } = {}) {
  if (!current || current.session_id !== incoming.session_id) return incoming;
  const merged = { ...current, ...incoming };
  const collections = ["messages", "timeline", "tools", "approvals", "artifacts", "turns"];
  for (const key of collections) {
    if (prepend) {
      merged[key] = mergeAgentSnapshotItems(incoming[key], current[key]);
    } else if (mergeCollections) {
      merged[key] = mergeAgentSnapshotItems(current[key], incoming[key]);
    } else if (preserveCollections && Array.isArray(current[key]) && (!Array.isArray(incoming[key]) || incoming[key].length === 0)) {
      merged[key] = current[key];
    }
  }
  return merged;
}

async function loadAgentSnapshot(shouldRender = true, includeHistory = true, options = {}) {
  const append = options?.append === true;
  const beforeSeq = options?.beforeSeq;
  // History paging must be atomic from the UI's point of view. Event-driven
  // background refreshes that begin while the older page is in flight can
  // otherwise win the generation race and hide the page we just loaded.
  if (!append && state.agentHistoryLoading) return;
  const requestGeneration = ++agentSnapshotRequestGeneration;
  if (!state.agentSessionId || !state.agentStatus?.ready) {
    state.agentSnapshot = null;
    state.agentGoal = null;
    resetAgentHistoryPaging();
    if (shouldRender) render();
    return;
  }
  try {
    const pagingWasStarted = state.agentHistoryPagingStarted;
    const incoming = await rpc("agent.session.snapshot", {
      sessionId: state.agentSessionId,
      maxMessages: includeHistory ? 8 : 1,
      include_history: includeHistory,
      ...(Number.isInteger(beforeSeq) && beforeSeq >= 0 ? { beforeSeq } : {}),
    });
    // Snapshot requests can overlap during initial navigation, event sync and
    // history paging. Only the newest response may update the visible state;
    // an older response must not resurrect a stale history cursor.
    if (requestGeneration !== agentSnapshotRequestGeneration) return;
    if (append) {
      state.agentSnapshot = mergeAgentSnapshot(state.agentSnapshot, incoming, { prepend: true });
    } else if (!includeHistory) {
      state.agentSnapshot = mergeAgentSnapshot(state.agentSnapshot, incoming, { preserveCollections: true });
    } else if (pagingWasStarted) {
      state.agentSnapshot = mergeAgentSnapshot(state.agentSnapshot, incoming, { mergeCollections: true });
    } else {
      state.agentSnapshot = incoming;
    }
    if (includeHistory && (append || !pagingWasStarted)) {
      state.agentHistoryHasMore = Boolean(incoming?.has_more);
      state.agentHistoryBeforeSeq = state.agentHistoryHasMore && Number.isInteger(incoming?.history_cursor)
        ? incoming.history_cursor
        : null;
    }
    if (append) state.agentHistoryPagingStarted = true;
    // Older Runtime projections may omit goal entirely. Only an explicit null
    // clears the local receipt; a missing field must not make a just-created
    // goal disappear while its projection is catching up.
    if (Object.prototype.hasOwnProperty.call(state.agentSnapshot || {}, "goal")) {
      state.agentGoal = state.agentSnapshot.goal || null;
    }
    if (!state.agentSessionRenameDraft && state.agentSnapshot?.title) {
      state.agentSessionRenameDraft = state.agentSnapshot.title;
    }
  } catch (error) {
    // A running turn can briefly make history unavailable. Keep the last
    // stable snapshot visible instead of replacing it with a fake state.
    if (!state.agentSnapshot) {
      state.agentSnapshot = {
        session_id: state.agentSessionId,
        state: "unavailable",
        error: error.message,
        messages: [],
        tools: [],
        approvals: [],
        artifacts: [],
        timeline: [],
        plan: { active: false, pending: false, steps: [] },
      };
    }
  }
  if (shouldRender) render();
}

async function loadOlderAgentHistory() {
  if (
    state.agentHistoryLoading
    || state.agentBusy
    || !state.agentSessionId
    || !state.agentStatus?.ready
    || !state.agentHistoryHasMore
    || !Number.isInteger(state.agentHistoryBeforeSeq)
  ) return;
  const list = document.querySelector(".agent-message-list");
  const previousHeight = list?.scrollHeight || 0;
  const previousTop = list?.scrollTop || 0;
  state.agentHistoryLoading = true;
  state.agentNotice = "正在读取更早的 Agent 会话记录…";
  render();
  try {
    await loadAgentSnapshot(false, true, { append: true, beforeSeq: state.agentHistoryBeforeSeq });
    state.agentNotice = state.agentHistoryHasMore ? "已加载更早的会话记录。" : "已加载全部会话记录。";
  } catch (error) {
    state.agentNotice = `读取更早记录失败：${error.message}`;
  } finally {
    state.agentHistoryLoading = false;
    render();
    requestAnimationFrame(() => {
      const next = document.querySelector(".agent-message-list");
      if (!next || !previousHeight) return;
      next.scrollTop = Math.max(0, next.scrollHeight - previousHeight + previousTop);
    });
  }
}

async function checkAgentHealth() {
  if (state.agentBusy) return;
  state.agentBusy = "health";
  state.agentNotice = `正在检查受管 ${agentRuntimeLabel()} 运行时…`;
  render();
  try {
    const result = await rpc("agent.health");
    state.agentStatus = { ...state.agentStatus, ...result };
    try { state.agentProvider = await api("/api/agent/provider"); } catch { /* status remains visible */ }
    if (result.ok) {
      await Promise.all([loadAgentCapabilities(false), loadAgentWorkspaces(false), loadAgentSessions(false), loadAgentPresets(false), loadAgentSubagents(false)]);
      await loadAgentMcpConfigurations(false);
      if (state.agentSessionId) await loadAgentModels(false);
    }
    const runtimeLabel = agentRuntimeLabel({ ...state.agentStatus, ...result });
    state.agentNotice = result.ok ? `${runtimeLabel} 已连接` : `${runtimeLabel} 未就绪：${result.error || "请先启动对应 Runtime"}`;
  } catch (error) {
    state.agentNotice = `${agentRuntimeLabel()} 连接检查失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function syncAgentProvider() {
  if (state.agentBusy || !state.agentStatus?.ready) return;
  const profile = activeProviderProfile();
  if (!profile) {
    state.agentNotice = "没有可同步的 Sumika Provider 档案，请先在模块页配置并测试连接。";
    render();
    return;
  }
  state.agentBusy = "provider-sync";
  state.agentNotice = `正在把当前 Provider 档案同步到受管 ${agentRuntimeLabel()}…`;
  render();
  try {
    const result = await rpc("agent.provider.sync", { profile_id: profile.id });
    state.agentProvider = { ...result, state: "ready", ready: true };
    state.agentNotice = `${profile.name} 已同步到 ${agentRuntimeLabel()}；新建会话会选择 ${result.model || profile.config?.model}。`;
  } catch (error) {
    state.agentNotice = `Provider 同步失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function registerAgentWorkspace() {
  const path = state.agentWorkspacePath.trim();
  if (!path || state.agentBusy || !state.agentStatus?.ready) return;
  state.agentBusy = "workspace";
  state.agentNotice = "正在登记已有目录；不会创建或移动文件…";
  render();
  try {
    const result = await rpc("agent.workspace.create", { path });
    state.agentWorkspaceId = result.workspace?.id || "";
    state.workspaceRuntimePath = result.workspace?.path || path;
    state.agentWorkspacePath = "";
    await loadAgentWorkspaces(false);
    state.agentNotice = result.created ? `已登记 Workspace：${result.workspace?.title || path}` : `该目录已登记：${result.workspace?.title || path}`;
  } catch (error) {
    state.agentNotice = `Workspace 登记失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function loadWorkspaceRuntime(pathValue = workspaceRuntimePath(), shouldRender = true) {
  const path = String(pathValue || "").trim();
  state.workspaceRuntimePath = path;
  state.workspaceRuntimePreview = null;
  state.workspaceRuntimeWorktreePreview = null;
  state.workspaceRuntimeCommitPreview = null;
  if (!path) {
    state.workspaceRuntimeInspect = null;
    state.workspaceRuntimeCheckpoints = [];
    state.workspaceRuntimeSelectedId = null;
    state.workspaceRuntimeDiff = null;
    state.workspaceRuntimePreview = null;
    if (shouldRender) render();
    return;
  }
  try {
    const [inspect, checkpoints] = await Promise.all([
      rpc("workspace.inspect", { path }),
      rpc("workspace.checkpoints", { path }),
    ]);
    state.workspaceRuntimeInspect = inspect;
    state.workspaceRuntimeCheckpoints = Array.isArray(checkpoints?.checkpoints) ? checkpoints.checkpoints : [];
    if (!state.workspaceRuntimeSelectedId || !state.workspaceRuntimeCheckpoints.some((item) => item.id === state.workspaceRuntimeSelectedId)) {
      state.workspaceRuntimeSelectedId = state.workspaceRuntimeCheckpoints[0]?.id || null;
    }
    state.workspaceRuntimeNotice = "工作区状态已更新。";
    if (state.workspaceRuntimeSelectedId) await loadWorkspaceRuntimeDiff(state.workspaceRuntimeSelectedId, false);
  } catch (error) {
    state.workspaceRuntimeInspect = null;
    state.workspaceRuntimeCheckpoints = [];
    state.workspaceRuntimeSelectedId = null;
    state.workspaceRuntimeDiff = null;
    state.workspaceRuntimePreview = null;
    state.workspaceRuntimeNotice = `Workspace 检查失败：${error.message}`;
  }
  if (shouldRender) render();
}

async function loadWorkspaceRuntimeDiff(checkpointId, shouldRender = true) {
  const id = String(checkpointId || "").trim();
  const path = workspaceRuntimePath();
  if (!id || !path) return;
  state.workspaceRuntimeSelectedId = id;
  state.workspaceRuntimePreview = null;
  state.workspaceRuntimeCommitPreview = null;
  try {
    state.workspaceRuntimeDiff = await rpc("workspace.checkpoint.diff", { path, checkpoint_id: id });
  } catch (error) {
    state.workspaceRuntimeDiff = null;
    state.workspaceRuntimeNotice = `读取 diff 失败：${error.message}`;
  }
  if (shouldRender) render();
}

async function inspectWorkspaceRuntime() {
  if (state.workspaceRuntimeBusy) return;
  const path = workspaceRuntimePath();
  if (!path) return;
  state.workspaceRuntimeBusy = "inspect";
  state.workspaceRuntimeNotice = "正在检查 Git 工作区…";
  render();
  await loadWorkspaceRuntime(path, false);
  state.workspaceRuntimeBusy = null;
  render();
}

async function createWorkspaceRuntimeCheckpoint() {
  if (state.workspaceRuntimeBusy) return;
  const path = workspaceRuntimePath();
  if (!path) return;
  state.workspaceRuntimeBusy = "create";
  state.workspaceRuntimeNotice = "正在创建 checkpoint；只保存文件摘要和受控副本…";
  render();
  try {
    const result = await rpc("workspace.checkpoint.create", {
      path,
      name: state.workspaceRuntimeCheckpointName.trim() || "Agent checkpoint",
    });
    state.workspaceRuntimeCheckpointName = "";
    state.workspaceRuntimeSelectedId = result.checkpoint?.id || null;
    await loadWorkspaceRuntime(path, false);
    state.workspaceRuntimeNotice = `checkpoint 已创建：${result.checkpoint?.name || result.checkpoint?.id}`;
  } catch (error) {
    state.workspaceRuntimeNotice = `创建 checkpoint 失败：${error.message}`;
  } finally {
    state.workspaceRuntimeBusy = null;
    render();
  }
}

async function previewWorkspaceRuntimeWorktree() {
  if (state.workspaceRuntimeBusy) return;
  const sourcePath = workspaceRuntimePath();
  const destinationPath = state.workspaceRuntimeWorktreeDestination.trim();
  const branch = state.workspaceRuntimeWorktreeBranch.trim();
  if (!sourcePath || !destinationPath || !branch) return;
  state.workspaceRuntimeBusy = "worktree-preview";
  state.workspaceRuntimeNotice = "正在验证新分支和 worktree 目标；不会修改 Git 状态…";
  render();
  try {
    state.workspaceRuntimeWorktreePreview = await rpc("workspace.worktree.preview", {
      source_path: sourcePath,
      destination_path: destinationPath,
      branch,
    });
    state.workspaceRuntimeNotice = "worktree 创建预览已生成；尚未创建目录或分支。";
  } catch (error) {
    state.workspaceRuntimeWorktreePreview = null;
    state.workspaceRuntimeNotice = `worktree 预览失败：${error.message}`;
  } finally {
    state.workspaceRuntimeBusy = null;
    render();
  }
}

async function createWorkspaceRuntimeWorktree() {
  if (state.workspaceRuntimeBusy) return;
  const preview = state.workspaceRuntimeWorktreePreview;
  const sourcePath = workspaceRuntimePath();
  const branch = String(preview?.worktree?.branch || "");
  const destinationPath = String(preview?.worktree?.path || "");
  const previewToken = preview?.preview_token;
  if (!sourcePath || !branch || !destinationPath || !previewToken) return;
  if (!window.confirm("确认创建该 Git 分支与独立 worktree？源目录未提交变更不会被复制；失败时 Sumika 不会自动删除 Git 留下的分支或目录。")) return;
  const confirmBranch = window.prompt("输入新分支名以确认", branch);
  if (confirmBranch !== branch) return;
  const confirmDestination = window.prompt("输入完整目标目录以确认", destinationPath);
  if (confirmDestination !== destinationPath) return;
  state.workspaceRuntimeBusy = "worktree-create";
  state.workspaceRuntimeNotice = "正在创建独立 worktree…";
  render();
  try {
    const result = await rpc("workspace.worktree.create", {
      source_path: sourcePath,
      destination_path: destinationPath,
      branch,
      approved: true,
      confirm_branch: confirmBranch,
      confirm_destination: confirmDestination,
      preview_token: previewToken,
    });
    state.workspaceRuntimeWorktreePreview = null;
    state.workspaceRuntimePath = result.worktree?.path || destinationPath;
    state.agentWorkspacePath = state.workspaceRuntimePath;
    await loadWorkspaceRuntime(state.workspaceRuntimePath, false);
    state.workspaceRuntimeNotice = `独立 worktree 已创建：${result.worktree?.branch || branch}；可在上方 Agent 工作区登记该目录。`;
  } catch (error) {
    state.workspaceRuntimeNotice = `worktree 创建失败：${error.message}`;
  } finally {
    state.workspaceRuntimeBusy = null;
    render();
  }
}

async function previewWorkspaceRuntimeCommit() {
  if (state.workspaceRuntimeBusy) return;
  const path = workspaceRuntimePath();
  const checkpointId = String(state.workspaceRuntimeSelectedId || "");
  const message = state.workspaceRuntimeCommitMessage.trim();
  if (!path || !checkpointId || !message) return;
  state.workspaceRuntimeBusy = "commit-preview";
  state.workspaceRuntimeNotice = "正在生成受控本地提交预览…";
  render();
  try {
    state.workspaceRuntimeCommitPreview = await rpc("workspace.commit.preview", {
      path,
      checkpoint_id: checkpointId,
      message,
    });
    state.workspaceRuntimeNotice = "提交预览已生成；请审阅 patch。当前尚未暂存或提交文件。";
  } catch (error) {
    state.workspaceRuntimeCommitPreview = null;
    state.workspaceRuntimeNotice = `提交预览失败：${error.message}`;
  } finally {
    state.workspaceRuntimeBusy = null;
    render();
  }
}

async function commitWorkspaceRuntimeChanges() {
  if (state.workspaceRuntimeBusy) return;
  const path = workspaceRuntimePath();
  const checkpointId = String(state.workspaceRuntimeSelectedId || "");
  const preview = state.workspaceRuntimeCommitPreview;
  const branch = String(preview?.workspace?.branch || "");
  const previewToken = preview?.preview_token;
  const message = state.workspaceRuntimeCommitMessage.trim();
  if (!path || !checkpointId || !branch || !previewToken || !message) return;
  if (!window.confirm("确认按当前 patch 创建本地 Git commit？此操作不运行 hooks、不签名，也不会 push。")) return;
  const confirmBranch = window.prompt("输入当前分支名以确认本地提交", branch);
  if (confirmBranch !== branch) return;
  state.workspaceRuntimeBusy = "commit";
  state.workspaceRuntimeNotice = "正在暂存已批准路径并创建本地 commit…";
  render();
  try {
    const result = await rpc("workspace.commit", {
      path,
      checkpoint_id: checkpointId,
      message,
      approved: true,
      confirm_branch: confirmBranch,
      preview_token: previewToken,
    });
    state.workspaceRuntimeCommitPreview = null;
    state.workspaceRuntimeCommitMessage = "";
    await loadWorkspaceRuntime(path, false);
    state.workspaceRuntimeNotice = `本地 commit 已创建：${String(result.commit || "").slice(0, 12)}；未 push。`;
  } catch (error) {
    state.workspaceRuntimeNotice = `本地提交失败：${error.message}`;
  } finally {
    state.workspaceRuntimeBusy = null;
    render();
  }
}

async function previewWorkspaceRuntimeRestore(checkpointId) {
  if (state.workspaceRuntimeBusy) return;
  const path = workspaceRuntimePath();
  const id = String(checkpointId || "").trim();
  if (!path || !id) return;
  state.workspaceRuntimeBusy = "preview";
  state.workspaceRuntimeNotice = "正在计算恢复影响…";
  render();
  try {
    state.workspaceRuntimeSelectedId = id;
    state.workspaceRuntimePreview = await rpc("workspace.restore.preview", { path, checkpoint_id: id });
    state.workspaceRuntimeNotice = "恢复预览已生成；当前文件不会被修改。";
  } catch (error) {
    state.workspaceRuntimePreview = null;
    state.workspaceRuntimeNotice = `恢复预览失败：${error.message}`;
  } finally {
    state.workspaceRuntimeBusy = null;
    render();
  }
}

async function restoreWorkspaceRuntime(checkpointId) {
  if (state.workspaceRuntimeBusy) return;
  const path = workspaceRuntimePath();
  const id = String(checkpointId || "").trim();
  const token = state.workspaceRuntimePreview?.restore?.preview_token;
  if (!path || !id || !token) return;
  if (!window.confirm("确认恢复这个 Workspace checkpoint？当前变更会先被归档，恢复可通过自动 checkpoint 撤销。")) return;
  const confirmation = window.prompt("输入 checkpoint ID 以确认恢复", id);
  if (confirmation !== id) return;
  state.workspaceRuntimeBusy = "restore";
  state.workspaceRuntimeNotice = "正在归档当前变更并恢复 checkpoint…";
  render();
  try {
    const result = await rpc("workspace.restore", {
      path,
      checkpoint_id: id,
      preview_token: token,
      approved: true,
      confirm_checkpoint: id,
    });
    state.workspaceRuntimePreview = null;
    await loadWorkspaceRuntime(path, false);
    state.workspaceRuntimeNotice = `已恢复 checkpoint；恢复前状态保存为 ${result.pre_restore_checkpoint?.id || "新 checkpoint"}。`;
  } catch (error) {
    state.workspaceRuntimeNotice = `Workspace 恢复失败：${error.message}`;
  } finally {
    state.workspaceRuntimeBusy = null;
    render();
  }
}

async function selectAgentModel(event) {
  const option = event.target.selectedOptions?.[0];
  const provider = option?.dataset.agentProvider;
  const model = option?.dataset.agentModel;
  if (!provider || !model || !state.agentSessionId || state.agentBusy) return;
  state.agentBusy = "model";
  state.agentNotice = `正在切换当前会话模型：${model}…`;
  render();
  try {
    const params = { sessionId: state.agentSessionId, provider, model };
    if (option.dataset.agentReasoning) params.reasoningEffort = option.dataset.agentReasoning;
    await rpc("agent.session.select_model", params);
    await loadAgentModels(false);
    state.agentNotice = `当前 Agent 会话已切换到 ${model}`;
  } catch (error) {
    state.agentNotice = `模型切换失败：${error.message}`;
    await loadAgentModels(false);
  } finally {
    state.agentBusy = null;
    render();
  }
}

function usableAgentPresetId(value) {
  const id = String(value || "").trim();
  const preset = state.agentPresets.find((item) => item.id === id);
  return id && preset && !preset.broken ? id : "";
}

async function selectAgentPreset(event) {
  const value = String(event.target.value || "").trim();
  const session = selectedAgentSession();
  const previous = state.agentPresetId;
  const runtimeLabel = agentRuntimeLabel();
  if (state.agentBusy || !state.agentStatus?.ready) return;
  if (!value) {
    // The portable contract exposes no "clear preset" mutation. Do not pretend that choosing
    // the visual default can rewrite a blank session that already has one.
    if (session?.agent_preset) {
      state.agentPresetId = session.agent_preset;
      state.agentNotice = `当前空白会话已有 Preset；${runtimeLabel} 不支持清除，请新建会话使用默认。`;
    } else {
      state.agentPresetId = "";
      state.agentNotice = `新建 Agent 会话将使用 ${runtimeLabel} 默认 Preset。`;
    }
    render();
    return;
  }
  const preset = usableAgentPresetId(value);
  if (!preset) {
    state.agentNotice = "所选 Preset 不可用，未发送请求。";
    render();
    return;
  }
  if (!session) {
    state.agentPresetId = preset;
    state.agentNotice = "已选择 Agent Preset；创建会话时生效。";
    render();
    return;
  }
  if (session.blank === false) {
    state.agentPresetId = session.agent_preset || previous;
    state.agentNotice = "当前会话已经产生回合，Preset 已锁定；请新建会话切换。";
    render();
    return;
  }
  state.agentBusy = "preset";
  state.agentNotice = "正在为当前空白会话选择 Preset…";
  render();
  try {
    const result = await rpc("agent.session.select_preset", { sessionId: session.id, agentPreset: preset });
    const selected = usableAgentPresetId(result?.agent_preset) || preset;
    state.agentPresetId = selected;
    state.agentSessions = state.agentSessions.map((item) => item.id === session.id ? { ...item, agent_preset: selected } : item);
    state.agentNotice = `当前空白会话已选择 Preset：${selected}`;
  } catch (error) {
    state.agentPresetId = previous;
    state.agentNotice = `Preset 选择失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

function validAgentPresetSlug(value) {
  const id = String(value || "").trim();
  return id.length > 0 && id.length <= 160 && /^[a-z0-9][a-z0-9-]*$/.test(id) ? id : "";
}

function validAgentPresetDisplayName(value) {
  const name = String(value || "").trim();
  if (!name) return "";
  if (name.length > 240 || /[\u0000-\u001f\u007f:\/\\]/.test(name)) return "";
  return name;
}

function emptyAgentMcpDraft(configuration = {}) {
  const credential = configuration.credential && typeof configuration.credential === "object"
    ? configuration.credential
    : null;
  return {
    server_name: configuration.server_name || "",
    transport: configuration.transport === "streamable-http" ? "streamable-http" : "stdio",
    enabled: configuration.enabled === true,
    command: configuration.command || "",
    args_text: JSON.stringify(Array.isArray(configuration.args) ? configuration.args : []),
    cwd: configuration.cwd || "",
    url: configuration.url || "",
    tool_call_timeout_ms: Number(configuration.tool_call_timeout_ms || 60000),
    credential_enabled: Boolean(credential),
    credential_present: Boolean(credential),
    credential_target: credential?.target || "",
    credential_prefix: credential?.prefix || "",
    credential_rotate: false,
    credential_configured: credential?.configured === true,
    credential_loaded_at_launch: credential?.loaded_at_launch === true,
    credential_restart_required: credential?.restart_required === true,
  };
}

function editAgentMcpConfiguration(serverName) {
  const configuration = state.agentMcpConfigurations.find((item) => item.server_name === serverName);
  if (!configuration || state.agentBusy) return;
  state.agentMcpPendingSecret = "";
  state.agentMcpDraft = emptyAgentMcpDraft(configuration);
  state.agentMcpPreview = null;
  state.agentNotice = `正在编辑 MCP 连接：${configuration.server_name}`;
  render();
}

function agentMcpConfigurationFromForm(form) {
  const data = new FormData(form);
  const serverName = String(data.get("server_name") || "").trim();
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(serverName)) throw new Error("服务名称只能使用字母、数字、下划线和连字符，最长 32 字符");
  const transport = String(data.get("transport") || "stdio");
  const timeout = Number.parseInt(String(data.get("tool_call_timeout_ms") || "60000"), 10);
  if (!Number.isInteger(timeout) || timeout < 1000 || timeout > 600000) throw new Error("工具超时必须是 1000 到 600000 毫秒");
  const configuration = {
    server_name: serverName,
    transport,
    enabled: data.get("enabled") === "on",
    tool_call_timeout_ms: timeout,
  };
  if (transport === "stdio") {
    const command = String(data.get("command") || "").trim();
    if (!command) throw new Error("stdio 连接需要启动命令");
    let args;
    try {
      args = JSON.parse(String(data.get("args") || "[]"));
    } catch {
      throw new Error("参数必须是有效的 JSON 数组");
    }
    if (!Array.isArray(args) || args.length > 64 || !args.every((item) => typeof item === "string")) throw new Error("参数必须是最多 64 项的字符串数组");
    configuration.command = command;
    configuration.args = args;
    const cwd = String(data.get("cwd") || "").trim();
    if (cwd) configuration.cwd = cwd;
  } else if (transport === "streamable-http") {
    const url = String(data.get("url") || "").trim();
    let parsed;
    try { parsed = new URL(url); } catch { throw new Error("请输入有效的 MCP URL"); }
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || parsed.hash) throw new Error("MCP URL 只能使用 HTTP(S)，且不能包含凭据或片段");
    configuration.url = url;
  } else {
    throw new Error("不支持的 MCP 传输方式");
  }
  if (state.agentMcpCredentialFieldsSupported) {
    if (data.get("credential_enabled") === "on") {
      const target = String(data.get("credential_target") || "").trim();
      const prefix = transport === "streamable-http" ? String(data.get("credential_prefix") || "") : "";
      if (!target) throw new Error("使用受保护凭据时必须填写目标环境变量或请求头");
      const secretProvided = Boolean(String(data.get("credential_value") || ""));
      const sameTarget = target === state.agentMcpDraft.credential_target;
      if (state.agentMcpDraft.credential_configured && sameTarget && secretProvided && data.get("credential_rotate") !== "on") {
        throw new Error("替换已保存密钥时请勾选“轮换已保存密钥”");
      }
      configuration.credential = {
        target,
        prefix,
        rotate: data.get("credential_rotate") === "on",
      };
    } else if (state.agentMcpDraft.credential_present) {
      configuration.credential = null;
    }
  }
  return configuration;
}

async function previewAgentMcpConfiguration(event) {
  event.preventDefault();
  const preset = validAgentPresetSlug(state.agentMcpPresetId);
  if (!preset || state.agentBusy || !state.agentStatus?.ready || !state.agentMcpClientInstalled) return;
  let configuration;
  try {
    state.agentMcpPendingSecret = String(new FormData(event.currentTarget).get("credential_value") || "");
    configuration = agentMcpConfigurationFromForm(event.currentTarget);
  } catch (error) {
    state.agentMcpPendingSecret = "";
    state.agentNotice = `MCP 配置无效：${error.message}`;
    render();
    return;
  }
  const credentialState = {
    credential_configured: state.agentMcpDraft.credential_configured,
    credential_loaded_at_launch: state.agentMcpDraft.credential_loaded_at_launch,
    credential_restart_required: state.agentMcpDraft.credential_restart_required,
  };
  state.agentMcpDraft = { ...emptyAgentMcpDraft(configuration), ...credentialState };
  state.agentBusy = "mcp-preview";
  state.agentNotice = `正在生成 ${configuration.server_name} 的受管配置预览…`;
  render();
  try {
    state.agentMcpPreview = await rpc("agent.mcp.configuration.preview", {
      agentPreset: preset,
      action: "upsert",
      configuration,
    });
    state.agentNotice = state.agentMcpPreview?.requires_approval
      ? "MCP 变更预览已生成；确认目标后再批准应用。"
      : "MCP 配置与当前文件一致。";
  } catch (error) {
    state.agentMcpPreview = null;
    state.agentMcpPendingSecret = "";
    state.agentNotice = `MCP 预览失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function previewAgentMcpRemoval(serverName) {
  const preset = validAgentPresetSlug(state.agentMcpPresetId);
  const configuration = state.agentMcpConfigurations.find((item) => item.server_name === serverName);
  if (!preset || !configuration || state.agentBusy || !state.agentStatus?.ready) return;
  state.agentMcpPendingSecret = "";
  state.agentBusy = "mcp-preview-remove";
  state.agentNotice = `正在生成 ${serverName} 的移除预览…`;
  render();
  try {
    state.agentMcpPreview = await rpc("agent.mcp.configuration.preview", {
      agentPreset: preset,
      action: "remove",
      configuration: { server_name: serverName },
    });
    state.agentNotice = "MCP 移除预览已生成；批准后才会改写 Preset。";
  } catch (error) {
    state.agentMcpPreview = null;
    state.agentNotice = `MCP 移除预览失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function applyAgentMcpPreview() {
  const preview = state.agentMcpPreview;
  const preset = validAgentPresetSlug(state.agentMcpPresetId);
  if (!preview?.preview_token || !preview.requires_approval || !preset || state.agentBusy) return;
  if (preview.credential_requires_value && !state.agentMcpPendingSecret) {
    state.agentNotice = "此次 MCP 变更需要新密钥；请返回表单填写后重新生成预览。";
    render();
    return;
  }
  if (!window.confirm(`批准对用户 Preset “${preset}”执行 MCP ${preview.change === "remove" ? "移除" : "写入"}并进行真实挂载验证？`)) return;
  state.agentBusy = "mcp-apply";
  state.agentNotice = "正在备份 Preset、应用 MCP 配置并验证挂载…";
  render();
  try {
    const result = await rpc("agent.mcp.configuration.apply", {
      agentPreset: preset,
      previewToken: preview.preview_token,
      approved: true,
      confirm_agent_preset: preset,
      ...(preview.credential_requires_value ? { credentialValue: state.agentMcpPendingSecret } : {}),
    });
    state.agentMcpPreview = null;
    state.agentPresetValidation = {
      ...state.agentPresetValidation,
      [preset]: {
        mountable: result?.mountable === true,
        validation_session_archived: result?.validation_session_archived === true,
      },
    };
    await loadAgentPresets(false);
    await loadAgentMcpConfigurations(false);
    state.agentNotice = result?.applied
      ? result.restart_required
        ? `MCP 配置已${result.change === "remove" ? "移除" : "应用"}；请重启 Sumika 载入新的凭据边界，再编辑连接并启用。`
        : `MCP 配置已${result.change === "remove" ? "移除" : "应用"}；原文备份已保留，验证会话已归档。新会话将使用更新后的 Preset。`
      : "MCP 配置没有变化。";
  } catch (error) {
    state.agentNotice = `MCP 配置应用失败：${error.message}`;
  } finally {
    state.agentMcpPendingSecret = "";
    state.agentBusy = null;
    render();
  }
}

async function copyAgentPreset(event) {
  event.preventDefault();
  if (state.agentBusy || !state.agentStatus?.ready || !state.agentPresetAuthorable) return;
  const source = validAgentPresetSlug(state.agentPresetCopySource || document.querySelector("#agent-preset-copy-source")?.value);
  const destination = validAgentPresetSlug(state.agentPresetCopyId || document.querySelector("#agent-preset-copy-id")?.value);
  const nameDraft = state.agentPresetCopyName || document.querySelector("#agent-preset-copy-name")?.value || "";
  const name = validAgentPresetDisplayName(nameDraft);
  if (!source) {
    state.agentNotice = "请选择有效的 Preset 来源。";
    render();
    return;
  }
  if (!destination) {
    state.agentNotice = "新 Preset ID 只能使用小写字母、数字和连字符。";
    render();
    return;
  }
  if (source === destination) {
    state.agentNotice = "新 Preset ID 必须与来源不同。";
    render();
    return;
  }
  if (state.agentPresets.some((preset) => preset.id === destination)) {
    state.agentNotice = "这个 Preset ID 已存在；请换一个新的 ID。";
    render();
    return;
  }
  if (nameDraft.trim() && !name) {
    state.agentNotice = "显示名称不能包含路径分隔符、冒号或控制字符。";
    render();
    return;
  }
  state.agentBusy = "preset-copy";
  state.agentNotice = `正在让 ${agentRuntimeLabel()} 创建用户 Preset…`;
  render();
  try {
    const result = await rpc("agent.preset.copy", {
      from: source,
      agentPreset: destination,
      ...(name ? { name } : {}),
    });
    state.agentPresetCopyId = "";
    state.agentPresetCopyName = "";
    state.agentPresetCopySource = destination;
    await loadAgentPresets(false);
    state.agentMcpPresetId = destination;
    state.agentMcpDraft = emptyAgentMcpDraft();
    state.agentMcpPreview = null;
    await loadAgentMcpConfigurations(false);
    state.agentNotice = `用户 Preset 已创建：${result?.agent_preset || destination}；当前会话 Preset 未改变。`;
  } catch (error) {
    state.agentNotice = `创建用户 Preset 失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function openAgentPresetDocument(presetId) {
  const id = validAgentPresetSlug(presetId);
  const preset = state.agentPresets.find((item) => item.id === id);
  if (!id || !preset || preset.trust !== "user" || state.agentBusy || !state.agentStatus?.ready || !state.agentPresetHasDocument) return;
  state.agentBusy = "preset-open";
  state.agentNotice = `正在打开用户 Preset 目录：${id}…`;
  render();
  try {
    const result = await rpc("agent.preset.open", { agentPreset: id });
    state.agentNotice = result?.opened
      ? `已打开用户 Preset 目录：${id}`
      : `${agentRuntimeLabel()} 没有可用的系统目录打开器；为保护隐私，Sumika 不显示本地路径。`;
  } catch (error) {
    state.agentNotice = `打开 Preset 目录失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function validateAgentPresetMount(presetId) {
  const id = validAgentPresetSlug(presetId);
  const preset = state.agentPresets.find((item) => item.id === id);
  if (!id || !preset || preset.broken || state.agentBusy || !state.agentStatus?.ready) return;
  const workspace = state.agentWorkspaces.find((item) => item.id === state.agentWorkspaceId);
  state.agentBusy = "preset-validate";
  state.agentNotice = `正在验证 Preset 挂载：${id}…`;
  render();
  try {
    const result = await rpc("agent.preset.validate", {
      agentPreset: id,
      ...(workspace?.id ? { workspaceId: workspace.id } : {}),
    });
    state.agentPresetValidation = {
      ...state.agentPresetValidation,
      [id]: {
        mountable: result?.mountable === true,
        validation_session_archived: result?.validation_session_archived === true,
      },
    };
    state.agentNotice = result?.mountable && result?.validation_session_archived
      ? `Preset 挂载已验证：${id}；空白验证会话已归档。`
      : `Preset 挂载验证未得到完整确认：${id}`;
  } catch (error) {
    state.agentNotice = `Preset 挂载验证失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function removeAgentPreset(presetId) {
  const id = validAgentPresetSlug(presetId);
  const preset = state.agentPresets.find((item) => item.id === id);
  if (!id || !preset || preset.trust !== "user" || state.agentBusy || !state.agentStatus?.ready) return;
  const confirmation = window.prompt(
    `删除用户 Preset “${preset.name || id}”将由 ${agentRuntimeLabel()} 永久移除，Sumika 不提供内置恢复。请输入完整 Preset ID：${id}`,
    "",
  );
  if (confirmation === null) return;
  if (confirmation !== id) {
    state.agentNotice = "Preset ID 确认不匹配，未执行删除。";
    render();
    return;
  }
  if (!window.confirm(`确认永久删除用户 Preset “${id}”？系统 Preset 不受此操作影响。`)) return;
  const resetDefault = state.agentPresetId === id;
  state.agentBusy = "preset-remove";
  state.agentNotice = `正在删除用户 Preset：${id}…`;
  render();
  try {
    const result = await rpc("agent.preset.remove", {
      agentPreset: id,
      confirm_agent_preset: id,
      approved: true,
    });
    if (result?.removed !== true) throw new Error(`${agentRuntimeLabel()} 未确认删除结果`);
    if (resetDefault) state.agentPresetId = "";
    if (state.agentPresetCopySource === id) state.agentPresetCopySource = "";
    if (state.agentMcpPresetId === id) {
      state.agentMcpPresetId = "";
      state.agentMcpConfigurations = [];
      state.agentMcpPreview = null;
    }
    const nextValidation = { ...state.agentPresetValidation };
    delete nextValidation[id];
    state.agentPresetValidation = nextValidation;
    await loadAgentPresets(false);
    state.agentNotice = `用户 Preset 已删除：${id}${resetDefault ? `；新会话已恢复使用 ${agentRuntimeLabel()} 默认 Preset` : ""}。`;
  } catch (error) {
    state.agentNotice = `删除用户 Preset 失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

function currentAgentGoal() {
  return state.agentGoal || state.agentSnapshot?.goal || null;
}

function goalReceiptRef(result, fallback = null) {
  const ref = result?.ref;
  if (ref && typeof ref === "object" && ref.id && Number.isInteger(ref.revision)) return { id: String(ref.id), revision: ref.revision };
  return fallback;
}

async function createAgentGoal(event) {
  event.preventDefault();
  if (state.agentBusy || !state.agentStatus?.ready || !state.agentSessionId || currentAgentGoal()) return;
  const form = event.currentTarget;
  const objective = String(new FormData(form).get("objective") || "").trim();
  const maxGoalRounds = Number.parseInt(String(new FormData(form).get("max_goal_rounds") || "20"), 10);
  if (!objective) {
    state.agentNotice = "Goal 目标不能为空。";
    render();
    return;
  }
  if (!Number.isInteger(maxGoalRounds) || maxGoalRounds < 1 || maxGoalRounds > 1000) {
    state.agentNotice = "最大 Goal 回合数必须是 1 到 1000 的整数。";
    render();
    return;
  }
  state.agentBusy = "goal-create";
  state.agentNotice = `正在创建 ${agentRuntimeLabel()} Goal…`;
  render();
  try {
    const result = await rpc("agent.goal.create", { sessionId: state.agentSessionId, objective, maxGoalRounds });
    const ref = goalReceiptRef(result);
    if (!ref) throw new Error(`${agentRuntimeLabel()} 未返回 Goal revision`);
    state.agentGoal = { ref, objective, phase: "active", max_goal_rounds: maxGoalRounds };
    state.agentNotice = "Goal 已创建；后续暂停、继续和完成都会校验 revision。";
    void loadAgentSnapshot(false, false);
  } catch (error) {
    state.agentNotice = `Goal 创建失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function agentGoalAction(action) {
  const goal = currentAgentGoal();
  const ref = goalReceiptRef(goal);
  if (!goal || !ref || !state.agentSessionId || state.agentBusy || !state.agentStatus?.ready) return;
  if (!["pause", "resume", "complete", "clear"].includes(action)) return;
  if (action === "clear" && !window.confirm(`清除当前 Goal？这只清除 ${agentRuntimeLabel()} 目标，不删除会话消息。`)) return;
  state.agentBusy = `goal-${action}`;
  state.agentNotice = action === "clear" ? `正在清除 ${agentRuntimeLabel()} Goal…` : `正在${action === "pause" ? "暂停" : action === "resume" ? "继续" : "完成"} ${agentRuntimeLabel()} Goal…`;
  render();
  try {
    const result = await rpc(`agent.goal.${action}`, { sessionId: state.agentSessionId, ref });
    if (action === "clear") {
      state.agentGoal = null;
      state.agentNotice = "Goal 已清除。";
    } else {
      const nextRef = goalReceiptRef(result, ref);
      const phase = { pause: "paused", resume: "active", complete: "completed" }[action];
      state.agentGoal = { ...goal, ref: nextRef, phase };
      state.agentNotice = `Goal 已${action === "pause" ? "暂停" : action === "resume" ? "继续" : "完成"}。`;
    }
    await loadAgentSnapshot(false, false);
  } catch (error) {
    state.agentNotice = `Goal 操作失败：${error.message}；正在刷新最新 revision。`;
    await loadAgentSnapshot(false, false);
  } finally {
    state.agentBusy = null;
    render();
  }
}

function agentSubagentEntry(childId) {
  return state.agentSubagents.find((entry) => entry.kind === "child" && entry.id === String(childId || "")) || null;
}

async function loadAgentSubagentHistory(childId) {
  const entry = agentSubagentEntry(childId);
  if (!entry || !state.agentSessionId || state.agentBusy || !state.agentStatus?.ready) return;
  state.agentBusy = `subagent-history:${entry.id}`;
  state.agentNotice = "正在读取子 Agent 历史…";
  render();
  try {
    const result = await rpc("agent.subagent.history", {
      parentSessionId: state.agentSessionId,
      childSessionId: entry.id,
      mode: entry.mode,
      maxMessages: 12,
    });
    state.agentSubagentHistories = { ...state.agentSubagentHistories, [entry.id]: result };
    state.agentNotice = `已读取子 Agent ${entry.label || entry.id} 的最近历史。`;
  } catch (error) {
    state.agentNotice = `子 Agent 历史读取失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function promptAgentSubagent(childId) {
  const entry = agentSubagentEntry(childId);
  if (!entry || entry.mode !== "continuable" || !state.agentSessionId || state.agentBusy || !state.agentStatus?.ready) return;
  const text = window.prompt(`给 ${entry.label || entry.id} 发送跟进`, "");
  if (text === null || !text.trim()) return;
  if (text.trim().length > 12000) {
    state.agentNotice = "子 Agent 跟进内容不能超过 12000 个字符。";
    render();
    return;
  }
  state.agentBusy = `subagent-prompt:${entry.id}`;
  state.agentNotice = "正在向子 Agent 发送跟进…";
  render();
  try {
    await rpc("agent.subagent.prompt", {
      parentSessionId: state.agentSessionId,
      childSessionId: entry.id,
      mode: "continuable",
      text: text.trim(),
    });
    state.agentNotice = "跟进已提交；文本不会写入 Sumika 审计日志。";
    await loadAgentSubagents(false);
  } catch (error) {
    state.agentNotice = `子 Agent 跟进失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function interruptAgentSubagent(childId) {
  const entry = agentSubagentEntry(childId);
  if (!entry || entry.mode !== "continuable" || entry.activity !== "running" || !state.agentSessionId || state.agentBusy || !state.agentStatus?.ready) return;
  state.agentBusy = `subagent-interrupt:${entry.id}`;
  state.agentNotice = "正在请求中断子 Agent…";
  render();
  try {
    await rpc("agent.subagent.interrupt", {
      parentSessionId: state.agentSessionId,
      childSessionId: entry.id,
      mode: "continuable",
    });
    await loadAgentSubagents(false);
    state.agentNotice = `已发送子 Agent 中断请求；最终状态以 ${agentRuntimeLabel()} 刷新结果为准。`;
  } catch (error) {
    state.agentNotice = `子 Agent 中断失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function forkAgentSession() {
  if (!state.agentSessionId || state.agentSnapshot?.state === "running" || state.agentBusy || !state.agentStatus?.ready) return;
  const sourceSessionId = state.agentSessionId;
  state.agentBusy = "fork";
  state.agentNotice = "正在从最近完成回合创建可恢复分支；原会话不会改变…";
  render();
  try {
    const result = await rpc("agent.session.fork", { sessionId: sourceSessionId });
    setAgentSessionId(result.sessionId);
    rememberAgentSession(state.agentSessionId);
    resetAgentHistoryPaging();
    state.agentGoal = null;
    state.agentSubagentHistories = {};
    state.agentSessionRenameDraft = "";
    await Promise.all([loadAgentSessions(false), loadAgentSnapshot(false), loadAgentModels(false), loadAgentCapabilities(false), loadAgentQueue(false), loadAgentSubagents(false)]);
    await loadAgentWorkspaces(false);
    const forkedSession = selectedAgentSession();
    state.agentPresetId = forkedSession?.agent_preset || "";
    state.agentNotice = `已创建分支会话：${result.sessionId}；原会话仍可从列表打开。`;
  } catch (error) {
    state.agentNotice = `创建分支失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function createAgentSession() {
  if (state.agentBusy || !state.agentStatus?.ready) return;
  const workspace = selectedAgentWorkspace();
  if (agentSupports("workspaces") && !workspace) {
    state.agentNotice = "请先登记并选择 Git Workspace，再新建 Agent 会话。";
    render();
    return;
  }
  state.agentBusy = "create-session";
  state.agentNotice = `正在创建 ${agentRuntimeLabel()} 会话…`;
  render();
  try {
    const profile = activeProviderProfile();
    const location = workspace ? { workspaceId: workspace.id } : { cwd: "." };
    const selectedPreset = usableAgentPresetId(state.agentPresetId);
    const result = await rpc("agent.session.create", { ...location, characterId: state.selectedCharacter, provider_profile_id: profile?.id, ...(selectedPreset ? { agentPreset: selectedPreset } : {}) });
    setAgentSessionId(result.id || result.sessionId || null);
    rememberAgentSession(state.agentSessionId);
    resetAgentHistoryPaging();
    state.agentGoal = null;
    state.agentSubagentHistories = {};
    state.agentSessionRenameDraft = "";
    if (result.agentPreset) state.agentPresetId = result.agentPreset;
    if (result.provider) state.agentProvider = { ...state.agentProvider, ...result.provider, state: "ready", ready: true };
    await Promise.all([loadAgentSessions(false), loadAgentSnapshot(false), loadAgentCapabilities(false), loadAgentModels(false), loadAgentQueue(false), loadAgentSubagents(false)]);
    await loadAgentWorkspaces(false);
    state.agentModelPolicyLoadedAt = 0;
    await loadAgentModelPolicy(false, false);
    state.agentNotice = `Agent 会话已创建：${result.id || result.sessionId || "已连接"}`;
  } catch (error) {
    state.agentNotice = `创建 Agent 会话失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function preflightAgentRouting(text, requestedMode, key) {
  const routing = agentRoutingRequest(text, requestedMode, false);
  if (!routing) return null;
  if (state.agentRoutingDecision && state.agentRoutingDecisionKey === key) return state.agentRoutingDecision;
  state.agentRoutingBusy = true;
  state.agentBusy = "routing";
  state.agentRoutingNotice = "正在检查候选模型的连接、额度和质量门槛…";
  render();
  try {
    const result = await rpc("model.policy.preflight", {
      ...routing,
      ...(state.agentSessionId ? { sessionId: state.agentSessionId } : {}),
    });
    const decision = result?.decision;
    state.agentRoutingDecision = result && typeof result === "object" ? result : null;
    state.agentRoutingDecisionKey = key;
    state.agentRoutingPendingKey = decision?.requires_confirmation ? key : "";
    if (!decision?.selected_route) {
      state.agentRoutingApprovedKey = "";
      state.agentRoutingNotice = "没有满足当前安全、隐私、质量和预算门槛的模型；目标尚未发送。";
    } else if (decision.requires_confirmation) {
      state.agentRoutingApprovedKey = "";
      state.agentRoutingNotice = "策略已给出候选，请确认后才会创建会话或执行回合。";
    } else {
      state.agentRoutingApprovedKey = key;
      state.agentRoutingNotice = "策略通过硬门槛，将使用推荐候选继续。";
    }
    return state.agentRoutingDecision;
  } catch (error) {
    state.agentRoutingDecision = null;
    state.agentRoutingDecisionKey = key;
    state.agentRoutingPendingKey = "";
    state.agentRoutingApprovedKey = "";
    state.agentRoutingNotice = `模型策略检查失败：${error.message}`;
    return null;
  } finally {
    state.agentRoutingBusy = false;
    state.agentBusy = null;
    render();
  }
}

async function sendAgentPrompt({ approvedRouting = false } = {}) {
  const input = document.querySelector("#agent-prompt");
  const text = (input?.value ?? state.agentPromptDraft ?? "").trim();
  const attachments = supportedAgentPromptAttachments();
  if ((!text && !attachments.length) || state.agentBusy || !state.agentStatus?.ready) return;
  const requestedMode = effectiveAgentMode();
  const initialWorkspace = agentWorkspaceForPrompt();
  if (agentSupports("workspaces") && !state.agentSessionId && !initialWorkspace) {
    state.agentNotice = "请先登记并选择 Git Workspace，再发送 Agent 目标。";
    render();
    return;
  }
  if (agentSupports("workspaces") && state.agentSessionId && !initialWorkspace) {
    state.agentNotice = "当前会话没有可验证的 Workspace 绑定；请新建一个绑定 Workspace 的会话后再发送。";
    render();
    return;
  }
  const routingKey = routingTaskKey(text, state.agentRoutingMode);
  const routing = agentRoutingRequest(text, requestedMode, approvedRouting || state.agentRoutingApprovedKey === routingKey);
  if (routing) {
    const existing = state.agentRoutingDecisionKey === routingKey ? state.agentRoutingDecision : null;
    if (!existing || (existing.decision?.requires_confirmation && !approvedRouting && state.agentRoutingApprovedKey !== routingKey)) {
      await preflightAgentRouting(text, requestedMode, routingKey);
    }
    const decision = state.agentRoutingDecisionKey === routingKey ? state.agentRoutingDecision?.decision : null;
    if (!decision?.selected_route) {
      if (!state.agentRoutingNotice) state.agentRoutingNotice = "没有可用的模型候选；目标尚未发送。";
      render();
      return;
    }
    if (decision.requires_confirmation && !approvedRouting && state.agentRoutingApprovedKey !== routingKey) {
      state.agentRoutingPendingKey = routingKey;
      state.agentRoutingNotice = "请在模型策略面板确认候选后继续；目标和附件仍保留。";
      render();
      return;
    }
    state.agentRoutingApprovedKey = routingKey;
    state.agentRoutingPendingKey = "";
  }
  state.agentBusy = "prompt";
  state.agentNotice = `目标已提交，等待 ${agentRuntimeLabel()} 事件…`;
  render();
  try {
    if (!state.agentSessionId) {
      const profile = routing ? null : activeProviderProfile();
      const workspace = selectedAgentWorkspace();
      const location = workspace ? { workspaceId: workspace.id } : { cwd: "." };
      const selectedPreset = usableAgentPresetId(state.agentPresetId);
      const createParams = { ...location, characterId: state.selectedCharacter, ...(profile?.id ? { provider_profile_id: profile.id } : {}), ...(selectedPreset ? { agentPreset: selectedPreset } : {}) };
      if (routing) {
        createParams.routing = { ...routing, approved: true };
        createParams.routingApproved = true;
      }
      const session = await rpc("agent.session.create", createParams);
      if (session?.accepted === false) {
        if (session.routing) {
          state.agentRoutingDecision = session.routing;
          state.agentRoutingDecisionKey = routingKey;
          state.agentRoutingPendingKey = session.reason === "confirmation-required" ? routingKey : "";
        }
        throw new Error(session.reason === "confirmation-required" ? "模型策略需要确认" : "模型策略没有接受本次会话");
      }
      setAgentSessionId(session.sessionId || session.id || null);
      if (!state.agentSessionId) throw new Error(`${agentRuntimeLabel()} 未返回 sessionId`);
      rememberAgentSession(state.agentSessionId);
      resetAgentHistoryPaging();
      state.agentGoal = null;
      state.agentSubagentHistories = {};
      state.agentSessionRenameDraft = "";
      if (session.agentPreset) state.agentPresetId = session.agentPreset;
      if (session.provider) state.agentProvider = { ...state.agentProvider, ...session.provider, state: "ready", ready: true };
      await Promise.all([loadAgentSessions(false), loadAgentCapabilities(false), loadAgentModels(false), loadAgentQueue(false), loadAgentSubagents(false)]);
      await loadAgentWorkspaces(false);
      state.agentModelPolicyLoadedAt = 0;
      await loadAgentModelPolicy(false, false);
    }
    const content = [
      ...(text ? [{ type: "text", text }] : []),
      ...attachments.map((item) => ({ type: "image", mediaType: item.mediaType, data: item.data, name: item.name })),
    ];
    const mode = requestedMode;
    const promptParams = { text, content, mode, sessionId: state.agentSessionId || undefined };
    const workspace = currentAgentSessionWorkspace();
    // Every prompt for a workspace-capable runtime must carry the session's
    // verified workspace.  Execute is the only mode that creates a
    // checkpoint; Plan still needs the binding so the runtime cannot silently
    // plan against a different directory.
    if (agentSupports("workspaces")) {
      if (!workspace) throw new Error("Runtime 尚未确认当前会话的 Workspace 绑定，请刷新后重试");
      promptParams.workspaceId = workspace.id;
    }
    if (mode === "execute" && agentPlanModeAvailable() && state.agentSnapshot?.plan?.active === true) {
      promptParams.leave_plan = true;
    }
    if (routing) {
      promptParams.routing = { ...routing, approved: true };
      promptParams.routingApproved = true;
    }
    const result = await rpc("agent.session.prompt", promptParams);
    if (result?.accepted === false) {
      if (result.routing) {
        state.agentRoutingDecision = result.routing;
        state.agentRoutingDecisionKey = routingKey;
        state.agentRoutingPendingKey = result.reason === "confirmation-required" ? routingKey : "";
      }
      throw new Error(result.reason === "confirmation-required" ? "模型策略需要确认" : "Runtime 未接受目标");
    }
    state.agentEvents.unshift({ event_type: "agent.turn.accepted", status: "running", content: result.id || "已接受", timestamp: new Date().toISOString() });
    state.agentPromptDraft = "";
    state.agentPromptAttachments = [];
    state.agentAttachmentNotice = "";
    // Repaint when the Runtime publishes the accepted prompt projection. Some
    // deployments do not emit a follow-up event, so a silent refresh would
    // leave newly attached media invisible until the user manually refreshes.
    void loadAgentSnapshot(true);
    void loadAgentQueue(true);
    if (result.workspace_checkpoint?.id) {
      state.workspaceRuntimePath = workspace?.path || state.workspaceRuntimePath;
      state.agentNotice = `目标已提交；执行前 checkpoint ${result.workspace_checkpoint.id} 已创建。`;
      if (workspace?.path) void loadWorkspaceRuntime(workspace.path, true);
    } else {
      state.agentNotice = "目标已提交；工具调用和审批会显示在本页。";
    }
  } catch (error) {
    state.agentNotice = `Agent 目标未发送：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function retryAgentTurn() {
  const sessionId = String(state.agentSessionId || "").trim();
  const snapshot = state.agentSnapshot;
  const retry = agentRetryState(snapshot);
  if (!sessionId || !retry.retryable || retry.imageTarget || retry.missingTarget || state.agentBusy || !state.agentStatus?.ready) return;
  if (!window.confirm("将重新提交当前会话最近一次失败或停止的文本目标。不会重复提交图片或工具结果，是否继续？")) return;
  state.agentBusy = "retry";
  state.agentNotice = `正在让 ${agentRuntimeLabel()} 重试最近目标…`;
  render();
  try {
    const workspace = currentAgentSessionWorkspace();
    const result = await rpc("agent.session.retry", {
      sessionId,
      approved: true,
      confirmSessionId: sessionId,
      ...(workspace ? { workspaceId: workspace.id } : {}),
    });
    if (result?.accepted === false) throw new Error("Runtime 未接受重试请求");
    state.agentNotice = result?.workspace_checkpoint?.id
      ? `重试已提交；执行前 checkpoint ${result.workspace_checkpoint.id} 已创建。`
      : `重试已提交；${agentRuntimeLabel()} 会通过事件确认最终状态。`;
    await Promise.all([
      loadAgentSnapshot(false, false),
      loadAgentQueue(false),
      loadAgentInteractions(false),
    ]);
  } catch (error) {
    state.agentNotice = `重试失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
    void syncAgentState();
  }
}

async function cancelAgentTurn() {
  if (state.agentBusy || !state.agentSessionId || !state.agentStatus?.ready) return;
  state.agentBusy = "cancel";
  state.agentNotice = `正在请求 ${agentRuntimeLabel()} 停止当前回合…`;
  render();
  try {
    await rpc("agent.session.cancel", { sessionId: state.agentSessionId });
    await Promise.all([loadAgentSnapshot(false), loadAgentQueue(false)]);
    state.agentNotice = `已发送停止请求；${agentRuntimeLabel()} 会通过事件确认最终状态。`;
  } catch (error) {
    state.agentNotice = `停止回合失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function updateAgentQueue(itemId, action, text = "") {
  if (!itemId || !["edit", "remove", "steer"].includes(action) || state.agentBusy || !state.agentSessionId || !state.agentStatus?.ready) return;
  if (action === "edit" && !String(text).trim()) {
    state.agentNotice = "待发送消息不能为空。";
    render();
    return;
  }
  state.agentBusy = "queue";
  state.agentNotice = action === "remove" ? `正在从 ${agentRuntimeLabel()} 队列移除项目…` : action === "steer" ? `正在请求 ${agentRuntimeLabel()} 立即 steer…` : "正在保存待发送消息…";
  render();
  try {
    await rpc("agent.session.update_queue", {
      sessionId: state.agentSessionId,
      itemId,
      kind: action,
      ...(action === "edit" ? { text: String(text).trim() } : {}),
    });
    await loadAgentQueue(false);
    if (action === "edit") {
      const drafts = { ...state.agentQueueDrafts };
      delete drafts[itemId];
      state.agentQueueDrafts = drafts;
    }
    state.agentNotice = action === "remove" ? "已从队列移除。" : action === "steer" ? `已请求 steer；最终顺序由 ${agentRuntimeLabel()} 队列快照确认。` : "已更新待发送消息。";
  } catch (error) {
    state.agentNotice = `队列操作失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function respondAgentApproval({ rpcId, sessionId, approvalId, outcome }) {
  if (!rpcId || !sessionId || !approvalId || !["allowed-once", "rejected"].includes(outcome) || state.agentBusy) return;
  state.agentBusy = "approval";
  state.agentNotice = outcome === "allowed-once" ? "已允许这一次操作，等待 Agent 继续…" : "已拒绝这一次操作。";
  render();
  try {
    await rpc("agent.approval.respond", { rpcId, sessionId, approvalId, outcome });
    state.agentInteractions = state.agentInteractions.filter((item) => item.id !== rpcId);
  } catch (error) {
    state.agentNotice = `审批响应失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

function captureAgentInteractionDraft(form) {
  if (!form) return;
  const id = form.dataset.agentInteractionId;
  if (!id) return;
  const draft = {};
  form.querySelectorAll("[data-agent-question-id]").forEach((group) => {
    draft[group.dataset.agentQuestionId] = {
      selected: [...group.querySelectorAll("input[type=radio]:checked, input[type=checkbox]:checked")].map((input) => input.value),
      custom: group.querySelector("[data-agent-custom]")?.value || "",
    };
  });
  state.agentInteractionDrafts = { ...state.agentInteractionDrafts, [id]: draft };
}

async function respondAgentQuestion(form) {
  const rpcId = form.dataset.agentInteractionId;
  const sessionId = form.dataset.agentInteractionSession;
  const interaction = state.agentInteractions.find((item) => item.id === rpcId && item.kind === "question");
  if (!rpcId || !sessionId || !interaction || state.agentBusy) return;
  captureAgentInteractionDraft(form);
  const draft = state.agentInteractionDrafts[rpcId] || {};
  const answers = [];
  for (const question of interaction.questions || []) {
    const group = [...form.querySelectorAll("[data-agent-question-id]")].find((item) => item.dataset.agentQuestionId === question.id);
    if (!group) return;
    const selected = [...group.querySelectorAll("input[type=radio]:checked, input[type=checkbox]:checked")].map((input) => input.value);
    const saved = draft[question.id] || {};
    const finalSelected = selected.length ? selected : (Array.isArray(saved.selected) ? saved.selected : []);
    const custom = (group.querySelector("[data-agent-custom]")?.value || saved.custom || "").trim();
    const answer = { id: question.id, selected: finalSelected };
    if (custom) answer.custom = custom;
    answers.push(answer);
  }
  state.agentBusy = "question";
  state.agentNotice = `正在提交回答，等待 ${agentRuntimeLabel()} 继续…`;
  render();
  try {
    await rpc("agent.question.respond", { rpcId, sessionId, answer: { answers } });
    state.agentInteractions = state.agentInteractions.filter((item) => item.id !== rpcId);
    const drafts = { ...state.agentInteractionDrafts };
    delete drafts[rpcId];
    state.agentInteractionDrafts = drafts;
    state.agentNotice = `回答已提交；${agentRuntimeLabel()} 会通过事件确认当前回合状态。`;
    void loadAgentSnapshot(false, false);
  } catch (error) {
    state.agentNotice = `回答未提交：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function respondAgentPlanReview(form, action) {
  const rpcId = form?.dataset.agentInteractionId;
  const sessionId = form?.dataset.agentInteractionSession;
  const interaction = state.agentInteractions.find((item) => item.id === rpcId && item.kind === "question" && item.plan_review);
  if (!rpcId || !sessionId || !interaction || !["approve", "keep-planning"].includes(action) || state.agentBusy) return;
  const question = (interaction.questions || []).find((item) => item?.intent?.kind === "plan-review") || interaction.questions?.[0];
  const planReview = interaction.plan_review || {};
  const label = action === "approve" ? String(planReview.approve || question?.intent?.approve || "Approve") : String(planReview.keep_planning || "Keep planning");
  if (!question?.id || !label) return;
  const workspace = currentAgentSessionWorkspace();
  if (action === "approve" && agentSupports("workspaces") && !workspace) {
    state.agentNotice = "当前计划会话没有可验证的 Workspace 绑定；请刷新后重试。";
    render();
    return;
  }
  const answer = { id: question.id, selected: [label] };
  if (action === "keep-planning") {
    const feedback = (form.querySelector("[data-agent-plan-review-feedback]")?.value || "").trim();
    // DSH treats a non-empty custom response as the single-select "other"
    // choice.  Sending it alongside a selected label is rejected by the
    // runtime, while an empty selection still means "keep planning" to the
    // plan-mode controller.
    if (feedback) {
      answer.selected = [];
      answer.custom = feedback;
    }
  }
  state.agentBusy = "plan-review";
  state.agentNotice = action === "approve" ? "正在批准计划，等待 Agent 进入执行…" : "正在请求 Agent 继续规划…";
  render();
  try {
    const result = await rpc("agent.question.respond", {
      rpcId,
      sessionId,
      answer: { answers: [answer] },
      ...(action === "approve" && workspace ? { workspaceId: workspace.id } : {}),
    });
    state.agentInteractions = state.agentInteractions.filter((item) => item.id !== rpcId);
    const drafts = { ...state.agentInteractionDrafts };
    delete drafts[rpcId];
    state.agentInteractionDrafts = drafts;
    state.agentNotice = action === "approve"
      ? result?.workspace_checkpoint?.id
        ? `计划已批准；执行前 checkpoint ${result.workspace_checkpoint.id} 已创建。`
        : "计划已批准；Agent 会从下一步开始执行。"
      : "已选择继续规划；等待 Agent 更新计划。";
    void loadAgentSnapshot(false, false);
  } catch (error) {
    state.agentNotice = `计划审查响应失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function cancelAgentInteraction(form) {
  const rpcId = form?.dataset.agentInteractionId;
  const sessionId = form?.dataset.agentInteractionSession;
  const interaction = state.agentInteractions.find((item) => item.id === rpcId && item.kind === "question" && item.plan_review);
  if (!rpcId || !sessionId || !interaction || state.agentBusy) return;
  state.agentBusy = "plan-review-cancel";
  state.agentNotice = "正在关闭计划审查，保留当前 Plan 模式…";
  render();
  try {
    await rpc("agent.question.cancel", { rpcId, sessionId });
    state.agentInteractions = state.agentInteractions.filter((item) => item.id !== rpcId);
    const drafts = { ...state.agentInteractionDrafts };
    delete drafts[rpcId];
    state.agentInteractionDrafts = drafts;
    state.agentNotice = "已关闭计划审查；Agent 保持 Plan 模式并等待你的新消息。";
  } catch (error) {
    state.agentNotice = `关闭计划审查失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function createBrowserSession() {
  if (state.agentBusy || state.browserStatus?.state === "disabled") return;
  state.agentBusy = "browser-session";
  try {
    const result = await rpc("browser.session.create", { profile: "temporary", character_id: state.selectedCharacter });
    state.agentNotice = `隔离浏览器 Profile 已登记：${result.id}`;
    state.browserSessions = [result, ...state.browserSessions];
    state.browserStatus = { ...state.browserStatus, active_sessions: state.browserSessions.length };
    await loadBrowserTabs(result.id, false);
    await loadBrowserDownloads(false);
  } catch (error) {
    state.agentNotice = `隔离浏览器尚未可用：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function createNamedBrowserProfile() {
  if (state.agentBusy || !state.selectedCharacter) return;
  const name = window.prompt("命名 Profile 名称", `${state.selectedCharacter} 浏览器`);
  if (name === null || !name.trim()) return;
  state.agentBusy = "browser-profile-create";
  try {
    const result = await rpc("browser.profile.create", {
      name: name.trim(),
      character_id: state.selectedCharacter,
      approved: true,
    });
    state.browserProfiles = [result, ...state.browserProfiles.filter((item) => item.id !== result.id)];
    state.agentNotice = `命名 Profile 已保存：${result.name}`;
  } catch (error) {
    state.agentNotice = `命名 Profile 创建失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function startNamedBrowserProfile(profileId) {
  const profile = state.browserProfiles.find((item) => item.id === profileId);
  if (!profile || state.agentBusy || profile.status === "archived") return;
  state.agentBusy = `browser-profile-start:${profileId}`;
  try {
    const result = await rpc("browser.session.create", {
      profile: "named",
      profile_id: profileId,
      character_id: state.selectedCharacter,
      agent_id: state.agentSessionId || undefined,
      approved: true,
    });
    state.browserSessions = [result, ...state.browserSessions.filter((item) => item.id !== result.id)];
    state.browserStatus = { ...state.browserStatus, active_sessions: state.browserSessions.length };
    await loadBrowserTabs(result.id, false);
    state.agentNotice = `已打开命名 Profile：${profile.name}`;
  } catch (error) {
    state.agentNotice = `命名 Profile 尚未打开：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function archiveBrowserProfile(profileId) {
  if (state.agentBusy || !profileId || !window.confirm("归档这个命名 Profile？凭据和元数据会保留，可恢复。")) return;
  state.agentBusy = `browser-profile-archive:${profileId}`;
  try {
    const result = await rpc("browser.profile.archive", { profile_id: profileId, approved: true });
    state.browserProfiles = state.browserProfiles.map((item) => item.id === profileId ? result : item);
    state.agentNotice = `${result.name} 已归档，可在此恢复。`;
  } catch (error) {
    state.agentNotice = `Profile 归档失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function restoreBrowserProfile(profileId) {
  if (state.agentBusy || !profileId) return;
  state.agentBusy = `browser-profile-restore:${profileId}`;
  try {
    const result = await rpc("browser.profile.restore", { profile_id: profileId, approved: true });
    state.browserProfiles = state.browserProfiles.map((item) => item.id === profileId ? result : item);
    state.agentNotice = `${result.name} 已恢复。`;
  } catch (error) {
    state.agentNotice = `Profile 恢复失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function createBrowserTab(sessionId, approved = false) {
  if (!sessionId || state.agentBusy) return;
  const pending = state.browserTabCreatePending[sessionId];
  // Bind an approval to the exact URL that produced the pending decision.
  let target;
  if (approved && pending?.url) {
    target = pending.url;
  } else {
    const url = window.prompt("新标签页地址（留空使用新标签页）", "chrome://newtab/");
    if (url === null) return;
    target = url.trim() || "chrome://newtab/";
  }
  state.agentBusy = "browser-tab-create";
  state.agentNotice = approved ? "正在打开已批准的浏览器标签页…" : "正在检查新标签页策略…";
  render();
  try {
    const result = await rpc("browser.tab.create", { session_id: sessionId, url: target, approved: Boolean(approved) });
    if (result.executed) {
      const next = { ...state.browserTabCreatePending };
      delete next[sessionId];
      state.browserTabCreatePending = next;
      await loadBrowserTabs(sessionId, false);
      state.agentNotice = "浏览器标签页已创建。";
    } else if (result.policy?.requires_approval) {
      state.browserTabCreatePending = { ...state.browserTabCreatePending, [sessionId]: { url: target, domain: result.policy.domain } };
      state.agentNotice = "打开该域名需要确认；确认后才会创建标签页。";
    } else {
      state.agentNotice = "标签页尚未创建：" + (result.reason || "BrowserSkill 未连接");
    }
  } catch (error) {
    state.agentNotice = `创建标签页失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function refreshBrowserTabs(sessionId) {
  if (!sessionId || state.agentBusy) return;
  state.agentBusy = "browser-tabs";
  state.agentNotice = "正在刷新隔离浏览器标签页…";
  render();
  try {
    await loadBrowserTabs(sessionId, false);
    state.agentNotice = "标签页列表已刷新。";
  } catch (error) {
    state.agentNotice = `刷新标签页失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function selectBrowserTab(sessionId, tabId) {
  if (!sessionId || !tabId || state.agentBusy) return;
  state.agentBusy = "browser-tab-select";
  state.agentNotice = "正在切换浏览器标签页…";
  render();
  try {
    const result = await rpc("browser.tab.select", { session_id: sessionId, tab_id: tabId });
    if (!result.executed) throw new Error(result.reason || "标签页尚未连接");
    state.browserActiveTabs = { ...state.browserActiveTabs, [sessionId]: tabId };
    await loadBrowserTabs(sessionId, false);
    state.agentNotice = "已切换当前标签页。";
  } catch (error) {
    state.agentNotice = `切换标签页失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function closeBrowserTab(sessionId, tabId) {
  if (!sessionId || !tabId || state.agentBusy || !window.confirm("关闭这个隔离浏览器标签页？此操作需要单次批准。")) return;
  state.agentBusy = "browser-tab-close";
  state.agentNotice = "正在关闭已批准的浏览器标签页…";
  render();
  try {
    const result = await rpc("browser.tab.close", { session_id: sessionId, tab_id: tabId, approved: true });
    if (!result.executed) throw new Error(result.reason || "标签页未关闭");
    await loadBrowserTabs(sessionId, false);
    state.agentNotice = "标签页已关闭。";
  } catch (error) {
    state.agentNotice = `关闭标签页失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function inspectBrowserSnapshot(sessionId) {
  if (!sessionId || state.agentBusy) return;
  state.agentBusy = "browser-snapshot";
  state.agentNotice = "正在读取受限 ARIA snapshot…";
  render();
  try {
    const result = await rpc("browser.snapshot", { session_id: sessionId, tab_id: state.browserActiveTabs[sessionId] });
    state.browserSnapshots = { ...state.browserSnapshots, [sessionId]: result };
    state.agentNotice = result.ready ? "ARIA snapshot 已更新；内容仅保留在当前页面。" : "浏览器暂不可观察：" + (result.reason || "等待扩展连接");
  } catch (error) {
    state.agentNotice = `读取 ARIA snapshot 失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function readBrowserDiagnostic(sessionId, stream) {
  if (!sessionId || !["console", "network"].includes(stream) || state.agentBusy || !state.browserDeveloperMode) return;
  const label = stream === "console" ? "控制台" : "网络";
  if (!window.confirm(`读取当前标签页的${label}诊断？敏感内容会在边界脱敏，但仍只建议用于排错。`)) return;
  state.agentBusy = `browser-${stream}`;
  state.agentNotice = `正在读取${label}诊断…`;
  render();
  try {
    const result = await rpc(`browser.${stream}`, { session_id: sessionId, tab_id: state.browserActiveTabs[sessionId], developer_mode: true, approved: true, limit: 50 });
    state.browserDiagnostics = { ...state.browserDiagnostics, [sessionId]: { ...(state.browserDiagnostics[sessionId] || {}), [stream]: result } };
    state.agentNotice = result.executed ? `${label}诊断已更新。` : `${label}诊断未执行：${result.reason || "策略拒绝"}`;
  } catch (error) {
    state.agentNotice = `读取${label}诊断失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function releaseBrowserDownload(downloadId) {
  if (!downloadId || state.agentBusy) return;
  const item = state.browserDownloads.find((entry) => entry.id === downloadId);
  if (!item || item.status !== "quarantine") return;
  const defaultWorkspace = state.agentWorkspaces.find((workspace) => workspace.id === state.agentWorkspaceId)?.path || "";
  const workspacePath = window.prompt("输入已存在的 Workspace 目录；不会覆盖同名文件", defaultWorkspace);
  if (workspacePath === null || !workspacePath.trim()) return;
  if (!window.confirm(`确认把“${item.filename || "这个文件"}”导入 Workspace？文件会先校验 SHA-256。`)) return;
  state.agentBusy = "browser-download-release";
  state.agentNotice = "正在批准并导入隔离下载…";
  render();
  try {
    const result = await rpc("browser.download.release", { download_id: downloadId, approved: true, workspace_path: workspacePath.trim() });
    state.browserDownloads = state.browserDownloads.map((entry) => entry.id === downloadId ? result : entry);
    state.browserStatus = { ...state.browserStatus, quarantined_downloads: state.browserDownloads.filter((entry) => entry.status === "quarantine").length };
    state.agentNotice = result.imported_at ? `已导入 Workspace：${result.destination_name || result.filename}` : "下载已批准。";
  } catch (error) {
    state.agentNotice = `导入隔离下载失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function observeBrowserSession(sessionId) {
  if (!sessionId || state.agentBusy) return;
  state.agentBusy = "browser-observe";
  state.agentNotice = "正在读取隔离浏览器的安全页面观察…";
  render();
  try {
    const result = await rpc("browser.observe", { session_id: sessionId });
    state.browserObservations = { ...state.browserObservations, [sessionId]: result };
    state.agentNotice = result.ready ? "页面观察已更新；原始页面内容不会写入事件日志。" : "浏览器暂不可观察：" + (result.reason || "等待扩展连接");
  } catch (error) {
    state.agentNotice = "页面观察失败：" + error.message;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function requestBrowserHelp(sessionId) {
  if (!sessionId || state.agentBusy) return;
  state.agentBusy = "browser-help";
  state.agentNotice = "正在暂停 Agent 并请求隔离窗口接管…";
  render();
  try {
    const result = await rpc("browser.request_help", {
      session_id: sessionId,
      domain: "当前页面",
      reason: "请在隔离浏览器窗口中完成需要人工输入或确认的步骤",
    });
    state.agentNotice = result.backend_requested === false
      ? "接管请求已登记，但 BrowserSkill 尚未连接：" + (result.backend_error || "等待扩展")
      : "已请求人工接管；凭据、OTP 和验证码不会进入 Sumika 日志。";
  } catch (error) {
    state.agentNotice = "接管请求失败：" + error.message;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function navigateBrowserSession(sessionId, approved) {
  if (!sessionId || state.agentBusy) return;
  const url = String(state.browserNavigationDrafts[sessionId] || "").trim();
  const pending = state.browserNavigationPending[sessionId];
  const target = approved && pending?.url ? pending.url : url;
  if (!target) {
    state.agentNotice = "请输入要访问的 http(s) 地址。";
    render();
    return;
  }
  state.agentBusy = "browser-navigate";
  state.agentNotice = approved ? "正在执行已批准的浏览器导航…" : "正在检查浏览器导航策略…";
  render();
  try {
    const result = await rpc("browser.navigate", { session_id: sessionId, url: target, approved: Boolean(approved) });
    if (result.executed) {
      const nextPending = { ...state.browserNavigationPending };
      delete nextPending[sessionId];
      state.browserNavigationPending = nextPending;
      state.browserNavigationDrafts = { ...state.browserNavigationDrafts, [sessionId]: "" };
      state.agentNotice = "导航已提交到隔离 BrowserSkill 会话。";
    } else if (result.policy?.requires_approval) {
      state.browserNavigationPending = { ...state.browserNavigationPending, [sessionId]: { url: target, domain: result.policy.domain } };
      state.agentNotice = "该导航需要确认；确认后才会访问目标域名。";
    } else {
      state.agentNotice = "导航尚未执行：" + (result.reason || "BrowserSkill 未连接");
    }
  } catch (error) {
    state.agentNotice = "浏览器导航失败：" + error.message;
  } finally {
    state.agentBusy = null;
    render();
  }
}

async function closeBrowserSession(sessionId) {
  if (!sessionId || state.agentBusy) return;
  state.agentBusy = "browser-close";
  try {
    await rpc("browser.session.close", { session_id: sessionId });
    state.browserSessions = state.browserSessions.filter((item) => item.id !== sessionId);
    const observations = { ...state.browserObservations };
    delete observations[sessionId];
    state.browserObservations = observations;
    const pending = { ...state.browserNavigationPending };
    delete pending[sessionId];
    state.browserNavigationPending = pending;
    const drafts = { ...state.browserNavigationDrafts };
    delete drafts[sessionId];
    state.browserNavigationDrafts = drafts;
    state.browserStatus = { ...state.browserStatus, active_sessions: state.browserSessions.length };
    state.agentNotice = "隔离浏览器会话已停止；临时 Profile 记录已从当前运行时移除。";
  } catch (error) {
    state.agentNotice = `停止隔离浏览器会话失败：${error.message}`;
  } finally {
    state.agentBusy = null;
    render();
  }
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

async function loadRoutePricing(shouldRender = true, refresh = false) {
  if (state.routePricingBusy) return;
  state.routePricingBusy = true;
  if (shouldRender) render();
  try {
    const result = await api(`/api/model-policy/pricing?refresh=${refresh ? "true" : "false"}`);
    state.routePricingCatalog = result && typeof result === "object"
      ? result
      : { schema: "route-pricing/v1", snapshots: [], errors: {}, checked_at: null };
    const failures = Object.keys(state.routePricingCatalog?.errors || {}).length;
    state.routePricingNotice = failures ? `${failures} 个定价来源暂不可用；已有证据不会伪装成最新价格。` : "";
  } catch (error) {
    state.routePricingNotice = `定价证据读取失败：${error.message}`;
  } finally {
    state.routePricingBusy = false;
    if (shouldRender) render();
  }
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
  await Promise.all([
    loadProviders(false),
    loadProviderProfiles(false, state.activePage === "Developer"),
    loadRoutePricing(false, false),
    loadWebChatData(false, state.activePage === "Developer"),
    loadPrivacy(false),
  ]);
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

function openWebChatDrawer(profileId = null, adapterId = "custom") {
  state.webChatDrawerOpen = true;
  state.webChatDrawerProfileId = profileId || null;
  const profile = profileId ? state.webChatProfiles.find((item) => item.id === profileId) : null;
  state.webChatDrawerAdapterId = profile?.adapter_id || adapterId || "custom";
  state.webChatNotice = "";
  render();
  requestAnimationFrame(() => document.querySelector(".web-chat-drawer input[autofocus]")?.focus());
}

function applyWebChatAdapterTemplate(form, adapterId, previousAdapterId = "custom") {
  if (!form) return;
  const adapter = webChatAdapter(adapterId);
  const previous = webChatAdapter(previousAdapterId);
  const fields = {
    domains: (adapter?.domains || []).join("\n"),
    chat_url: adapter?.chat_url || "",
    model_id: adapter?.model_id || "web-session",
    input_selectors: webChatArrayText(adapter?.selectors?.input),
    send_selectors: webChatArrayText(adapter?.selectors?.send),
    response_selectors: webChatArrayText(adapter?.selectors?.response),
    login_markers: webChatArrayText(adapter?.login_markers),
    authorized_markers: webChatArrayText(adapter?.authorized_markers),
    ready_markers: webChatArrayText(adapter?.ready_markers),
  };
  const previousFields = {
    domains: (previous?.domains || []).join("\n"),
    chat_url: previous?.chat_url || "",
    model_id: previous?.model_id || "web-session",
    input_selectors: webChatArrayText(previous?.selectors?.input),
    send_selectors: webChatArrayText(previous?.selectors?.send),
    response_selectors: webChatArrayText(previous?.selectors?.response),
    login_markers: webChatArrayText(previous?.login_markers),
    authorized_markers: webChatArrayText(previous?.authorized_markers),
    ready_markers: webChatArrayText(previous?.ready_markers),
  };
  Object.entries(fields).forEach(([name, value]) => {
    const field = form.elements[name];
    if (!field) return;
    const current = String(field.value || "").trim();
    // Replace empty values or values that still equal the old preset.  A
    // user's custom selector/marker is never silently overwritten.
    if (!current || current === String(previousFields[name] || "").trim()) field.value = value;
  });
  const nameField = form.elements.name;
  if (nameField && (!String(nameField.value || "").trim() || String(nameField.value).trim() === String(previous?.name || "").trim())) {
    nameField.value = adapter?.name && adapterId !== "custom" ? adapter.name : "";
  }
}

function closeWebChatDrawer() {
  state.webChatDrawerOpen = false;
  state.webChatDrawerProfileId = null;
  state.webChatNotice = "";
  render();
}

function replaceWebChatProfile(profile) {
  if (!profile?.id) return;
  state.webChatProfiles = [profile, ...state.webChatProfiles.filter((item) => item.id !== profile.id)];
}

function webChatFormLines(value) {
  return String(value || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function readWebChatProfileForm(form) {
  const adapterId = String(form.elements.adapter_id.value || "custom").trim().toLowerCase();
  const name = String(form.elements.name.value || "").trim();
  const domains = webChatFormLines(form.elements.domains.value);
  const selectors = {
    input: webChatFormLines(form.elements.input_selectors.value),
    send: webChatFormLines(form.elements.send_selectors.value),
    response: webChatFormLines(form.elements.response_selectors.value),
  };
  if (!name) throw new Error("连接名称不能为空");
  if (!form.elements.browser_profile_id.value) throw new Error("请选择 BrowserSkill 命名 Profile");
  if (!form.elements.chat_url.value.trim()) throw new Error("聊天页面 URL 不能为空");
  if (!selectors.input.length) throw new Error("至少填写一个输入框选择器");
  const timeout = Number(form.elements.response_timeout_seconds.value || 4);
  if (!Number.isFinite(timeout) || timeout < 0.5 || timeout > 15) throw new Error("等待回复超时必须在 0.5–15 秒之间");
  return {
    name,
    adapter_id: adapterId,
    browser_profile_id: form.elements.browser_profile_id.value,
    browser_instance: String(form.elements.browser_instance?.value || "").trim() || undefined,
    budget_policy: form.elements.budget_policy.value || "free-only",
    config: {
      name,
      domains,
      chat_url: form.elements.chat_url.value.trim(),
      model_id: String(form.elements.model_id.value || "web-session").trim() || "web-session",
      selectors,
      login_markers: webChatFormLines(form.elements.login_markers.value),
      authorized_markers: webChatFormLines(form.elements.authorized_markers.value),
      ready_markers: webChatFormLines(form.elements.ready_markers.value),
      response_timeout_seconds: timeout,
    },
  };
}

async function loadWebChatData(shouldRender = true, includeArchived = false) {
  const profileQuery = includeArchived ? "?include_archived=true" : "";
  try {
    const result = await api("/api/browser/web-chat/adapters");
    state.webChatAdapters = Array.isArray(result?.adapters) ? result.adapters : [];
  } catch {
    state.webChatAdapters = [];
  }
  try {
    const result = await api(`/api/browser/web-chat/profiles${profileQuery}`);
    state.webChatProfiles = Array.isArray(result?.profiles) ? result.profiles : [];
  } catch {
    state.webChatProfiles = [];
  }
  if (shouldRender) render();
}

async function createNamedBrowserProfileForWebChat() {
  await createNamedBrowserProfile();
  try {
    const result = await rpc("browser.profiles", { include_archived: false });
    state.browserProfiles = Array.isArray(result?.profiles) ? result.profiles : state.browserProfiles;
  } catch {
    // The browser page will show the existing error notice.
  }
  render();
}

async function saveWebChatProfileFromForm(event) {
  event.preventDefault();
  if (state.webChatBusy) return;
  const form = event.currentTarget;
  const action = event.submitter?.dataset.webChatAction || "save";
  let payload;
  try {
    payload = readWebChatProfileForm(form);
  } catch (error) {
    state.webChatNotice = error.message;
    render();
    return;
  }
  state.webChatBusy = action;
  state.webChatNotice = "";
  render();
  try {
    const profileId = form.dataset.profileId;
    const method = profileId ? "browser.web_chat.profile.update" : "browser.web_chat.profile.create";
    const result = await rpc(method, {
      ...(profileId ? { profile_id: profileId } : {}),
      ...payload,
      draft: action === "save",
      approved: true,
    });
    let profile = result;
    replaceWebChatProfile(profile);
    state.webChatDrawerProfileId = profile.id;
    if (action === "save") {
      state.webChatNotice = `${profile.name} 已保存为草稿；登录和检查通过后才能启用。`;
    } else {
      await ensureNativeWebProfile(profile.id);
      const checked = await rpc("browser.web_chat.profile.check", { profile_id: profile.id, approved: true });
      profile = checked;
      replaceWebChatProfile(profile);
      if (!checked.ready) throw new Error(checked.reason || "网页聊天页面尚未就绪");
      if (action === "activate") {
        if (!profile.auto_chat_enabled) {
          profile = await rpc("browser.web_chat.profile.consent", {
            profile_id: profile.id,
            enabled: true,
            allowed_actions: ["chat.read", "chat.send"],
            approved: true,
          });
          replaceWebChatProfile(profile);
        }
        const activated = await rpc("browser.web_chat.profile.activate", { profile_id: profile.id, approved: true });
        replaceWebChatProfile(activated.profile || activated);
        state.modules = state.modules.map((module) => module.id === "llm" ? normalizeModule(activated.module) : module);
        state.privacy = activated.privacy?.label || state.privacy;
        state.webChatDrawerOpen = false;
        state.webChatNotice = `${profile.name} 已检查并启用；聊天会通过隔离浏览器发送。`;
      } else {
        state.webChatNotice = `${profile.name} 页面检查通过；仍需点击“授权聊天”后才会自动发送。`;
      }
    }
    await loadWebChatData(false, state.activePage === "Developer");
    await loadPrivacy(false);
  } catch (error) {
    state.webChatNotice = `网页聊天操作失败：${error.message}`;
  } finally {
    state.webChatBusy = null;
    render();
  }
}

async function authorizeWebChatProfile(profileId) {
  if (!profileId || state.webChatBusy) return;
  state.webChatBusy = `authorize:${profileId}`;
  state.webChatNotice = "正在打开内置网页登录标签…";
  render();
  try {
    await ensureNativeWebProfile(profileId);
    const result = await rpc("browser.web_chat.profile.authorize", { profile_id: profileId, approved: true });
    replaceWebChatProfile(result);
    state.webChatNotice = "请在内置标签中完成登录；不读取登录字段、不迁移 Cookie。完成后点击“检查”。";
  } catch (error) {
    state.webChatNotice = `打开网页登录失败：${error.message}`;
  } finally {
    state.webChatBusy = null;
    render();
  }
}

async function checkWebChatProfile(profileId) {
  if (!profileId || state.webChatBusy) return;
  state.webChatBusy = `check:${profileId}`;
  state.webChatNotice = "正在读取有限页面状态…";
  render();
  try {
    await ensureNativeWebProfile(profileId);
    const result = await rpc("browser.web_chat.profile.check", { profile_id: profileId, approved: true });
    replaceWebChatProfile(result);
    state.webChatNotice = result.ready ? `${result.name || "网页聊天"} 已登录且页面就绪。` : (result.reason || "网页聊天尚未就绪");
  } catch (error) {
    state.webChatNotice = `网页状态检查失败：${error.message}`;
  } finally {
    state.webChatBusy = null;
    render();
  }
}

async function setWebChatConsent(profileId, enabled) {
  if (!profileId || state.webChatBusy) return;
  state.webChatBusy = `consent:${profileId}`;
  render();
  try {
    const result = await rpc("browser.web_chat.profile.consent", {
      profile_id: profileId,
      enabled,
      allowed_actions: ["chat.read", "chat.send"],
      approved: true,
    });
    replaceWebChatProfile(result);
    state.webChatNotice = enabled ? "已授权普通网页聊天；敏感网页登录和提交仍会暂停。" : "已关闭网页聊天自动发送授权。";
  } catch (error) {
    state.webChatNotice = `网页聊天授权变更失败：${error.message}`;
  } finally {
    state.webChatBusy = null;
    render();
  }
}

async function activateWebChatProfile(profileId) {
  if (!profileId || state.webChatBusy) return;
  const profile = state.webChatProfiles.find((item) => item.id === profileId);
  if (!profile) return;
  if (!webChatReady(profile)) {
    openWebChatDrawer(profileId);
    state.webChatNotice = "请先人工登录、检查页面并授权普通聊天。";
    return;
  }
  state.webChatBusy = `activate:${profileId}`;
  render();
  try {
    const result = await rpc("browser.web_chat.profile.activate", { profile_id: profileId, approved: true });
    replaceWebChatProfile(result.profile || result);
    if (result.module) state.modules = state.modules.map((module) => module.id === "llm" ? normalizeModule(result.module) : module);
    state.privacy = result.privacy?.label || state.privacy;
    state.webChatNotice = `${profile.name} 已启用`;
  } catch (error) {
    state.webChatNotice = `启用网页聊天失败：${error.message}`;
  } finally {
    state.webChatBusy = null;
    await loadWebChatData(false, state.activePage === "Developer");
    await loadPrivacy(false);
    render();
  }
}

async function archiveWebChatProfile(profileId) {
  if (!profileId || state.webChatBusy || !window.confirm("归档该网页连接？登录态仍由 BrowserSkill 保留，可恢复；不会删除浏览器数据。")) return;
  state.webChatBusy = `archive:${profileId}`;
  render();
  try {
    const result = await rpc("browser.web_chat.profile.archive", { profile_id: profileId, approved: true });
    replaceWebChatProfile(result);
    state.webChatNotice = `${result.name} 已归档。`;
  } catch (error) {
    state.webChatNotice = `归档网页连接失败：${error.message}`;
  } finally {
    state.webChatBusy = null;
    await loadWebChatData(false, true);
    render();
  }
}

async function restoreWebChatProfile(profileId) {
  if (!profileId || state.webChatBusy) return;
  state.webChatBusy = `restore:${profileId}`;
  render();
  try {
    const result = await rpc("browser.web_chat.profile.restore", { profile_id: profileId, approved: true });
    replaceWebChatProfile(result);
    state.webChatNotice = `${result.name} 已恢复；需要重新检查登录状态。`;
  } catch (error) {
    state.webChatNotice = `恢复网页连接失败：${error.message}`;
  } finally {
    state.webChatBusy = null;
    await loadWebChatData(false, true);
    render();
  }
}

function applyProviderTemplate(event) {
  const template = state.providerTemplates.find((item) => item.id === event.target.value);
  const form = document.querySelector("#provider-profile-form");
  if (!template || !form) return;
  if (!form.elements.name.value.trim()) form.elements.name.value = template.name;
  form.elements.active_base_url.value = template.base_url || "";
  if (!form.elements.model.value.trim()) form.elements.model.value = template.model || "";
  if (form.elements.models && !form.elements.models.value.trim()) {
    form.elements.models.value = (Array.isArray(template.model_options) && template.model_options.length
      ? template.model_options
      : (template.model ? [template.model] : [])).join("\n");
  }
  form.elements.processing_location.value = template.processing_location || "auto";
  const datalist = document.querySelector("#provider-model-options");
  if (datalist) {
    datalist.innerHTML = (Array.isArray(template.model_options) ? template.model_options : [])
      .map((model) => `<option value="${escapeHtml(model)}"></option>`)
      .join("");
  }
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
  const modelLines = (form.elements.models?.value || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  const defaultModel = form.elements.model.value.trim();
  if (defaultModel && !modelLines.includes(defaultModel)) modelLines.unshift(defaultModel);
  const readOptionalNumber = (name, label) => {
    const raw = String(form.elements[name]?.value ?? "").trim();
    if (!raw) return null;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0) throw new Error(`${label}必须是非负数字`);
    return value;
  };
  const pricingSource = String(form.elements.pricing_source_type?.value || "").trim();
  let pricing = null;
  if (pricingSource) {
    const rates = {};
    const currency = String(form.elements.pricing_currency?.value || "").trim();
    if (currency) rates.currency = currency;
    for (const [field, key, label] of [
      ["pricing_input_rate", "input_price_per_million", "输入单价"],
      ["pricing_output_rate", "output_price_per_million", "输出单价"],
      ["pricing_cache_read_rate", "cache_read_price_per_million", "缓存读取单价"],
      ["pricing_cache_write_rate", "cache_write_price_per_million", "缓存写入单价"],
      ["pricing_request_rate", "request_price", "每请求单价"],
    ]) {
      const value = readOptionalNumber(field, label);
      if (value != null) rates[key] = value;
    }
    const paidAmount = readOptionalNumber("pricing_paid_amount", "实际支付金额");
    const creditedAmount = readOptionalNumber("pricing_credited_amount", "到账站内余额");
    if ((paidAmount == null) !== (creditedAmount == null)) throw new Error("实际支付金额和到账站内余额必须同时填写");
    if (creditedAmount === 0) throw new Error("到账站内余额必须大于 0");
    pricing = {
      source_type: pricingSource,
      billing_group: String(form.elements.pricing_billing_group?.value || "").trim(),
      public_url: String(form.elements.pricing_public_url?.value || "").trim(),
      source_url: String(form.elements.pricing_source_url?.value || "").trim(),
      source_version: String(form.elements.pricing_source_version?.value || "").trim(),
      rates,
      cash_conversion: paidAmount == null ? null : {
        paid_amount: paidAmount,
        credited_amount: creditedAmount,
        currency: String(form.elements.pricing_cash_currency?.value || "CNY").trim().toUpperCase(),
      },
    };
  }
  const payload = {
    id: form.dataset.profileId || undefined,
    name: form.elements.name.value.trim(),
    adapter_id: "openai-compatible",
    template_id: form.elements.template_id.value,
    processing_location: form.elements.processing_location.value,
    active_base_url: activeBaseUrl,
    base_urls: [activeBaseUrl, ...alternateUrls],
    model: defaultModel,
    models: [...new Set(modelLines)],
    timeout: Number(form.elements.timeout.value || 60),
    organization: form.elements.organization.value.trim(),
    project: form.elements.project.value.trim(),
    headers,
    usage_query: usageQuery,
    pricing,
  };
  const apiKey = form.elements.api_key.value;
  if (apiKey) payload.api_key = apiKey;
  if (form.elements.clear_api_key?.checked) payload.clear_secrets = ["api_key"];
  return payload;
}

async function discoverProviderModels(profileId) {
  if (!profileId || state.providerBusy) return;
  state.providerBusy = `models:${profileId}`;
  state.providerNotice = "";
  render();
  try {
    const result = await rpc("provider.profile.models", { profile_id: profileId, discover: true });
    if (result.profile) replaceProviderProfile(result.profile);
    state.providerDrawerProfileId = profileId;
    if (!result.ok) throw new Error(result.error || "端点未返回模型列表");
    const count = Array.isArray(result.models) ? result.models.length : 0;
    state.providerNotice = `${result.profile?.name || profileId} 已获取 ${count} 个模型；逐个测试后才会进入可用路由`;
  } catch (error) {
    state.providerNotice = `获取模型列表失败：${error.message}`;
  } finally {
    state.providerBusy = null;
    await loadProviderProfiles(false);
    await loadRoutePricing(false, true);
    render();
  }
}

async function selectProviderModel(profileId, modelId) {
  if (!profileId || !modelId || state.providerBusy) return;
  state.providerBusy = `select-model:${profileId}:${modelId}`;
  render();
  try {
    const result = await rpc("provider.profile.model.select", { profile_id: profileId, model_id: modelId });
    if (result.profile) replaceProviderProfile(result.profile);
    state.providerNotice = `${modelId} 已设为默认模型；请重新测试连接后再启用`;
  } catch (error) {
    state.providerNotice = `选择模型失败：${error.message}`;
  } finally {
    state.providerBusy = null;
    await loadProviderProfiles(false);
    render();
  }
}

async function testProviderModel(profileId, modelId) {
  if (!profileId || !modelId || state.providerBusy) return;
  state.providerBusy = `health-model:${profileId}:${modelId}`;
  render();
  try {
    const result = await rpc("provider.profile.health", { profile_id: profileId, model_id: modelId });
    if (result.profile) replaceProviderProfile(result.profile);
    state.providerNotice = result.ok ? `${modelId} 连接测试通过` : `${modelId}：${result.error || "未就绪"}`;
  } catch (error) {
    state.providerNotice = `模型测试失败：${error.message}`;
  } finally {
    state.providerBusy = null;
    await loadProviderProfiles(false);
    render();
  }
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
    await loadRoutePricing(false, true);
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
    await loadRoutePricing(false, true);
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
    await loadRoutePricing(false, true);
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
    await loadRoutePricing(false, true);
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

async function loadAgentDiagnostics(shouldRender = true) {
  if (state.agentDiagnosticsBusy) return;
  state.agentDiagnosticsBusy = true;
  if (shouldRender) render();
  try {
    state.agentDiagnostics = await rpc("agent.diagnostics");
  } catch (error) {
    state.agentDiagnostics = {
      checked_at: new Date().toISOString(),
      runtime: { state: "unavailable", ready: false, error: error.message },
      capabilities: [],
      mcp: { available: false, status: "unavailable", endpoint: "mcp.list", reason: "核心未连接" },
      summary: { unavailable: 1 },
    };
  } finally {
    state.agentDiagnosticsBusy = false;
    if (shouldRender) render();
  }
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
  state.moduleCatalogStatus = "loading";
  if (shouldRender) render();
  try {
    state.modules = (await api("/api/modules")).map(normalizeModule);
    state.moduleCatalogStatus = "ready";
    syncProviderSelection();
  } catch {
    state.moduleCatalogStatus = "error";
  }
  await loadWebChatData(false, state.activePage === "Developer");
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

async function loadAgentTaskProjections(shouldRender = true) {
  if (!state.agentStatus?.ready) {
    // The Core can still serve a redacted last-known projection while DSH is
    // offline.  Ask for it explicitly instead of clearing the task center.
    try {
      const result = await rpc("agent.task.projections", { limit: 24 });
      state.agentTasks = Array.isArray(result?.tasks) ? result.tasks : [];
    } catch {
      // Keep an already-rendered cache during a transient Core reconnect.
      if (!Array.isArray(state.agentTasks)) state.agentTasks = [];
    }
    if (shouldRender) render();
    return;
  }
  try {
    const result = await rpc("agent.task.projections", { limit: 24 });
    state.agentTasks = Array.isArray(result?.tasks) ? result.tasks : [];
  } catch {
    // Keep the last stable projection on a transient request failure. It is
    // rendered as stale only when the Core explicitly marks it so.
  }
  if (shouldRender) render();
}

async function loadTasks(shouldRender = true) {
  try {
    state.tasks = await api("/api/tasks");
  } catch {
    state.tasks = [];
  }
  await loadAgentTaskProjections(false);
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
    await loadTasks(false);
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
    await loadRoutePricing(false, false);
    await loadWebChatData(false, false);
    state.providerTemplates = providerTemplates;
    state.privacy = privacy.label || "本地处理";
    state.ccsManifest = ccsManifest;
    state.modules = modules.map(normalizeModule);
    state.moduleCatalogStatus = "ready";
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
    const savedAssistant = localStorage.getItem("sumika:active-assistant:v1");
    if (characters.some((row) => row.id === savedAssistant)) state.selectedCharacter = savedAssistant;
    state.events = events;
    await loadAgentRuntime(false);
    await loadAgentTaskProjections(false);
    state.agentEvents = events.filter((event) => String(event.event_type || "").startsWith("agent.") || String(event.event_type || "").startsWith("browser."));
    await loadMemories(false);
    state.avatarState = await rpc("avatar.state", { character_id: state.selectedCharacter });
    state.connected = true;
    await loadDiagnostics(false);
    await loadMessages();
  } catch {
    state.providers = [];
    state.providerProfiles = [];
    state.routePricingCatalog = { schema: "route-pricing/v1", snapshots: [], errors: {}, checked_at: null };
    state.routePricingNotice = "";
    state.routePricingBusy = false;
    state.webChatAdapters = [];
    state.webChatProfiles = [];
    state.providerTemplates = [];
    state.ccsManifest = null;
    state.modules = [];
    state.moduleCatalogStatus = "error";
    state.plugins = [];
    state.audioStatus = fallbackAudioStatus;
    state.visionStatus = fallbackVisionStatus;
    state.tasks = [];
    // Keep the last known Agent projection across a transient Core failure;
    // the next successful RPC will replace it with an explicitly stale/live
    // response.  This prevents the task center from flashing empty during a
    // DSH restart.
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
    state.agentStatus = { state: "unavailable", ready: false, reason: "核心未连接" };
    state.agentDiagnostics = null;
    state.agentDiagnosticsBusy = false;
    state.capabilityCatalog = null;
    state.capabilityCatalogNotice = "核心未连接，能力目录暂不可用。";
    state.capabilityCatalogBusy = false;
    state.browserStatus = { state: "unavailable", ready: false };
    state.browserProfiles = [];
    setAgentSessionId(null);
    state.agentSnapshot = null;
    state.agentModels = { current: {}, routable: false, groups: [], failures: [] };
    state.agentWorkspaces = [];
    state.agentWorkspaceId = "";
    state.agentEvents = [];
    state.browserSessions = [];
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

async function openAgentTask(sessionId) {
  const value = String(sessionId || "").trim();
  if (!value) return;
  state.activePage = "Agent";
  workbenchHost.model.view = "workspace";
  render();
  const summary = document.querySelector('[data-workbench-page="Agent"]');
  if (summary) { summary.parentElement.open = true; summary.closest(".wv2-advanced").open = true; }
  await selectAgentSession(value);
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
    await workbenchHost.loadHistory();
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
  if (!state.connected || !hasLlmConnections()) {
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
  const selectedWebProfile = webChatProfileForModule(llm);
  if (selectedWebProfile) {
    if (!webChatReady(selectedWebProfile)) {
      state.sessionNotice = `${selectedWebProfile.name || "网页聊天"} 尚未就绪，请先在模块页登录、检查并授权。`;
      render();
      return;
    }
  } else {
    const selectedProvider = activeProviderProfile() || llm.profile;
    if (!selectedProvider || selectedProvider.status !== "available") {
      state.sessionNotice = `${selectedProvider?.name || "当前 Provider"} 尚未就绪，请先在模块页测试连接。`;
      render();
      return;
    }
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
    const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ client_request_id: crypto.randomUUID(), session_id: sessionId, character_id: state.selectedCharacter, messages: [{ role: "user", content }] }) });
    if (result.work_request) {
      state.composerDraft = content;
      workbenchHost.showRoleApproval(result.work_request, { session_id: sessionId, message: content });
      state.activePage = "Workspace";
      if (companionWindow) await openMainWindow();
    } else if (result.message && state.activeSessionId === sessionId) state.messages.push(result.message);
    else state.sessionNotice = result.reason || "请求等待处理";
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
    const session = await rpc("session.create", { character_id: state.selectedCharacter, purpose: companionWindow ? "chat" : "work" });
    state.sessions = [session, ...state.sessions.filter((item) => item.id !== session.id)];
    state.activeSessionId = session.id;
    invalidateQualityRoutingScope();
    state.messages = [];
    state.activePage = companionWindow ? "Chat" : "Workspace";
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
  invalidateQualityRoutingScope();
  state.activePage = companionWindow ? "Chat" : "Workspace";
  await loadMessages();
}

async function submitCharacterCreation(event) {
  event.preventDefault();
  if (state.characterBusy) return;
  const form = event.currentTarget;
  const formData = new FormData(form);
  const name = String(formData.get("character_name") || "").trim();
  const cardFile = formData.get("character_card");
  const hasCard = cardFile instanceof File && cardFile.size > 0;
  if (!name && !hasCard) {
    state.characterNotice = "请填写角色名称，或选择一张角色卡。";
    render();
    return;
  }
  state.characterBusy = true;
  state.characterNotice = "";
  render();
  try {
    let character;
    if (hasCard) {
      const params = {};
      if (/\.(png|charx)$/i.test(cardFile.name)) {
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = () => reject(new Error("无法读取所选文件"));
          reader.readAsDataURL(cardFile);
        });
        params.card_base64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
      } else {
        params.card_text = await cardFile.text();
      }
      if (name) params.name = name;
      const result = await rpc("character.import_card", params);
      character = result.character;
      const warnings = Array.isArray(result.warnings) ? result.warnings : [];
      state.characterNotice = warnings.length
        ? `${character.name} 已从角色卡导入；注意：${warnings.join("；")}`
        : `${character.name} 已从角色卡导入。`;
    } else {
      const response = await api("/rpc", { method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method: "character.create", params: { name, config: { language: "zh-CN", memory_enabled: false, persona: { identity: "", traits: "", relationship: "", speaking_style: "", behavior: "", boundaries: "", response_length: "balanced", system_prompt: "", greeting: "" }, avatar: { position: "center", opacity: 1, scale: 1, idle_motion: true, auto_rotate: false, rotation_speed: 0.12 } } } }) });
      if (response.error) throw new Error(response.error.message || "创建失败");
      character = response.result;
      state.characterNotice = `${character.name} 已创建；在下方完善人设并绑定 Avatar 模型。`;
    }
    state.characters = state.characters.some((item) => item.id === character.id)
      ? state.characters.map((item) => (item.id === character.id ? character : item))
      : [...state.characters, character];
    state.selectedCharacter = character.id;
    invalidateQualityRoutingScope();
    state.characterCreating = false;
    await loadAvatarState();
  } catch (error) {
    state.characterNotice = `创建失败：${error.message}`;
  } finally {
    state.characterBusy = false;
    render();
  }
}

async function createCharacter() {
  state.characterCreating = !state.characterCreating;
  state.characterNotice = "";
  render();
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
    const theme = { ...(currentCharacter().config?.theme || {}) };
    if (formData.get("theme_accent_reset") === "on") {
      delete theme.accent;
    } else {
      const accent = String(formData.get("theme_accent") || "").toLowerCase();
      if (/^#[0-9a-f]{6}$/.test(accent)) theme.accent = accent;
    }
    const character = await rpc("character.update", {
      character_id: state.selectedCharacter,
      name,
      config: {
        language: String(formData.get("language") || "zh-CN"),
        theme,
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
  socket.addEventListener("open", () => {
    state.connected = true;
    render();
    void syncAgentState({ immediate: true });
  });
  socket.addEventListener("message", (event) => {
    try {
      const value = JSON.parse(event.data);
      if (value.event_type !== "connection.ready") {
        state.events.unshift(value);
        if (String(value.event_type || "").startsWith("agent.") || String(value.event_type || "").startsWith("browser.")) {
          state.agentEvents.unshift(value);
          if (value.event_type === "agent.runtime.health" || value.event_type === "agent.provider.synced" || value.event_type === "browser.session.created" || value.event_type === "browser.session.closed") {
            void loadAgentRuntime(false);
          }
          if (["agent.skill.discovered", "agent.skill.approved", "agent.skill.revoked", "agent.skill.discovery.failed"].includes(value.event_type)) {
            void loadAgentSkills(false);
          }
          if (["agent.mcp.configuration.previewed", "agent.mcp.configuration.applied", "agent.mcp.configuration.failed", "agent.session.preset.selected"].includes(value.event_type)) {
            void loadAgentMcpCatalog(false);
          }
          if (value.event_type === "agent.session.queue" && state.agentSessionId && value.payload?.session_id === state.agentSessionId) {
            void loadAgentQueue(false);
          }
          const agentSessionId = value.payload?.session_id || value.payload?.sessionId;
          if (state.agentSessionId && (!agentSessionId || agentSessionId === state.agentSessionId)) {
            if (["agent.goal.changed", "agent.goal.rejected"].includes(value.event_type)) {
              void loadAgentSnapshot(false, false);
            }
            if (["agent.subagent.prompt.accepted", "agent.subagent.interrupt.accepted", "agent.subagent.changed"].includes(value.event_type)) {
              void loadAgentSubagents(false);
            }
            if (value.event_type === "agent.session.preset.selected") {
              void loadAgentSessions(false);
            }
          }
          const runtimeStatus = value.payload?.status;
          if (value.event_type === "agent.session.event" && state.agentSessionId && !["assistant/chunk", "session/projection"].includes(runtimeStatus)) {
            void loadAgentSnapshot(false, false).then(() => { if (state.activePage === "Agent" && !state.agentBusy) render(); });
          }
          if (state.activePage === "Tasks" && (
            ["turn/start", "turn/end", "approval/requested", "approval/resolved", "question/requested", "question/resolved", "tool/result", "session/title"].includes(runtimeStatus)
            || ["agent.session.created", "agent.approval.decided", "agent.question.answered"].includes(value.event_type)
          )) {
            void loadAgentTaskProjections(true);
          }
          const runtimeEvent = /^agent\.[a-z0-9-]+\.event$/i.test(String(value.event_type || ""));
          if (runtimeEvent || ["agent.approval.requested", "agent.approval.resolved", "agent.question.requested", "agent.question.resolved", "agent.question.cancelled"].includes(value.event_type)) {
            void loadAgentInteractions(false).then(() => { if (state.activePage === "Agent" && !state.agentBusy) render(); });
          }
        }
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
        if (!state.agentBusy) render();
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

function rememberFocusedAgentQueueDraft() {
  const input = document.activeElement;
  if (!(input instanceof HTMLInputElement) || !input.matches("[data-agent-queue-input]")) return;
  const itemId = input.closest("[data-agent-queue-row]")?.dataset.agentQueueRow;
  if (itemId) state.agentQueueDrafts = { ...state.agentQueueDrafts, [itemId]: input.value };
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

const { renderCharacters, renderAvatarAssetAudit } = createCharactersView({
  avatarDriverLabel: avatarDriverLabel,
  avatarPreviewUrl: avatarPreviewUrl,
  currentAvatarModel: currentAvatarModel,
  currentAvatarPresentation: currentAvatarPresentation,
  currentCharacter: currentCharacter,
  currentPersonaConfig: currentPersonaConfig,
  escapeHtml: escapeHtml,
  formatBytes: formatBytes,
  renderPageFrame: renderPageFrame,
  state: state,
});

const { renderModules, renderCapabilityCatalogPanel, renderWebChatProfileRow } = createModulesView({
  activeProviderProfile: activeProviderProfile,
  audioCapabilityLabel: audioCapabilityLabel,
  audioCapabilityStateLabel: audioCapabilityStateLabel,
  audioPermissionLabel: audioPermissionLabel,
  audioPermissionStateLabel: audioPermissionStateLabel,
  capabilityEntryStatusClass: capabilityEntryStatusClass,
  capabilityLocationLabel: capabilityLocationLabel,
  capabilitySourceLabel: capabilitySourceLabel,
  capabilityStatusLabel: capabilityStatusLabel,
  escapeHtml: escapeHtml,
  fallbackAudioStatus: fallbackAudioStatus,
  fallbackVisionStatus: fallbackVisionStatus,
  formatTime: formatTime,
  moduleStatusLabel: moduleStatusLabel,
  pricingCashLabel: pricingCashLabel,
  pricingEvidenceLabel: pricingEvidenceLabel,
  pricingProviderChargeLabel: pricingProviderChargeLabel,
  pricingSourceLabel: pricingSourceLabel,
  providerModelEntries: providerModelEntries,
  providerModelSummary: providerModelSummary,
  providerProfileStatusLabel: providerProfileStatusLabel,
  renderPageFrame: (...args) => renderPageFrame(...args),
  routePricingSnapshotsForProfile: routePricingSnapshotsForProfile,
  state: state,
  visionPermissionLabel: visionPermissionLabel,
  visionPermissionStateLabel: visionPermissionStateLabel,
  visionSourceLabel: visionSourceLabel,
  visionStateLabel: visionStateLabel,
  webChatAdapter: webChatAdapter,
  webChatArrayText: webChatArrayText,
  webChatConfig: webChatConfig,
  webChatProfileForModule: webChatProfileForModule,
  webChatProfileModel: webChatProfileModel,
  webChatReady: webChatReady,
  webChatStatusLabel: webChatStatusLabel,
});

const { renderConsultation } = createConsultationView({
  escapeHtml: escapeHtml,
  state: state,
});

const embeddedView = createEmbeddedBrowserController({
  state, invoke: invokeDesktop, rpc, render, escapeHtml, isDesktop: isDesktopShell,
  showConsultation: openConsultation,
  hideConsultation: () => state.consultation.visible ? changeConsultationVisibility("hide") : Promise.resolve(),
});
window.addEventListener("pagehide", () => embeddedView.dispose(), { once: true });
document.addEventListener("click", (event) => {
  const link = event.target.closest?.('a[href^="https://"]');
  if (!isDesktopShell || !link || link.closest(".embedded-workspace")) return;
  event.preventDefault();
  const url = new URL(link.href);
  const known = portalDefinitions().find((site) => new URL(site.url).hostname === url.hostname);
  void browserLinkSite(link.href, link.textContent.trim().slice(0, 80), known).then((site) => embeddedView.open(site)).catch((error) => {
    state.sessionNotice = error.message;
    render();
  });
});

const benefitsView = createBenefitsController({
  state,
  rpc,
  getScope: () => !state.overlayMode && !document.hidden && workbenchHost.model.view === "settings"
    ? JSON.stringify(["settings", state.selectedCharacter, currentSessionId(), state.qualityRouting.requestGeneration]) : null,
});
window.addEventListener("pagehide", () => benefitsView.dispose(), { once: true });

const { renderQualitySettings, renderQualityWorkbench, renderRoutingEvidence } = createQualityRoutingView({
  includeBenefits: false,
  escapeHtml: escapeHtml,
  renderConsultation: () => '<button class="outline-button" type="button" data-consultation-open>打开网页咨询</button>',
  renderPageFrame: (...args) => renderPageFrame(...args),
  state: state,
});

const { renderGuide, renderSettings } = createSettingsView({
  APPEARANCE_SWATCHES: APPEARANCE_SWATCHES,
  NAV_ITEMS: NAV_ITEMS,
  escapeHtml: escapeHtml,
  formatDate: formatDate,
  glyph: glyph,
  pageLabel: pageLabel,
  readAppearance: readAppearance,
  renderQualitySettings: renderQualitySettings,
  renderPageFrame: (...args) => renderPageFrame(...args),
  snapshotDiffCount: snapshotDiffCount,
  snapshotScopeLabel: snapshotScopeLabel,
  snapshotTableLabel: snapshotTableLabel,
  snapshotTargetOptions: snapshotTargetOptions,
  state: state,
});

const { renderTasks, renderHistory, renderNotifications } = createWorkbenchView({
  escapeHtml: escapeHtml,
  formatAgentContextUsage: formatAgentContextUsage,
  formatAgentTaskUsage: formatAgentTaskUsage,
  formatAgentTokenUsage: formatAgentTokenUsage,
  formatBudget: formatBudget,
  formatDate: formatDate,
  notificationFromEvent: notificationFromEvent,
  renderAgentTurnLedger: (...args) => renderAgentTurnLedger(...args),
  renderQualityWorkbench: renderQualityWorkbench,
  renderPageFrame: (...args) => renderPageFrame(...args),
  state: state,
  taskAutonomyLabel: taskAutonomyLabel,
  taskStatusClass: taskStatusClass,
  taskStatusIcon: taskStatusIcon,
  taskStatusLabel: taskStatusLabel,
});

const { renderAgentMcpCatalogPanel, renderAgentSkillCatalogPanel, renderAgentTurnLedger, renderAgent } = createAgentView({
  AGENT_ROUTING_BUDGETS: AGENT_ROUTING_BUDGETS,
  AGENT_ROUTING_MODES: AGENT_ROUTING_MODES,
  agentMetricValue: agentMetricValue,
  agentPlanModeAvailable: agentPlanModeAvailable,
  agentPromptCanSend: agentPromptCanSend,
  agentRetryState: agentRetryState,
  agentRuntimeLabel: agentRuntimeLabel,
  agentSupports: agentSupports,
  currentAgentSessionWorkspace: currentAgentSessionWorkspace,
  effectiveAgentMode: effectiveAgentMode,
  escapeHtml: escapeHtml,
  formatAgentContextUsage: formatAgentContextUsage,
  formatAgentMetricNumber: formatAgentMetricNumber,
  formatAgentTokenUsage: formatAgentTokenUsage,
  formatBudget: formatBudget,
  formatBytes: formatBytes,
  formatCostRange: formatCostRange,
  formatTime: formatTime,
  mcpCatalogStatusLabel: mcpCatalogStatusLabel,
  modelPolicyCostLabel: modelPolicyCostLabel,
  modelPolicyDecisionLabel: modelPolicyDecisionLabel,
  modelPolicyDecisionSummary: modelPolicyDecisionSummary,
  modelPolicyHealthLabel: modelPolicyHealthLabel,
  modelPolicyLocationLabel: modelPolicyLocationLabel,
  modelPolicyQuotaFor: modelPolicyQuotaFor,
  modelPolicyQuotaLabel: modelPolicyQuotaLabel,
  renderPageFrame: (...args) => renderPageFrame(...args),
  routingBudgetLabel: routingBudgetLabel,
  routingModeLabel: routingModeLabel,
  selectedAgentSession: selectedAgentSession,
  selectedAgentWorkspace: selectedAgentWorkspace,
  skillCatalogStatusLabel: skillCatalogStatusLabel,
  state: state,
  supportedAgentPromptAttachments: supportedAgentPromptAttachments,
  workspaceRuntimePath: workspaceRuntimePath,
  workspaceRuntimeStatusLabel: workspaceRuntimeStatusLabel,
});

const { renderWebWorkbench } = createWebWorkbenchView({
  escapeHtml: escapeHtml,
  formatPricingNumber: formatPricingNumber,
  renderPageFrame: (...args) => renderPageFrame(...args),
  safeWebWorkbenchText: safeWebWorkbenchText,
  state: state,
  webAttemptActive: webAttemptActive,
  webAttemptStatusLabel: webAttemptStatusLabel,
  webConsultationStatusLabel: webConsultationStatusLabel,
  webRouteStatusLabel: webRouteStatusLabel,
  webWorkbenchProfiles: webWorkbenchProfiles,
});

const { renderDeveloper } = createDeveloperView({
  agentRuntimeLabel: agentRuntimeLabel,
  escapeHtml: escapeHtml,
  formatDuration: formatDuration,
  formatTime: formatTime,
  isDesktopShell: isDesktopShell,
  pluginStatusLabel: pluginStatusLabel,
  providerProfileStatusLabel: providerProfileStatusLabel,
  renderAgentMcpCatalogPanel: (...args) => renderAgentMcpCatalogPanel(...args),
  renderAgentSkillCatalogPanel: (...args) => renderAgentSkillCatalogPanel(...args),
  renderAvatarAssetAudit: (...args) => renderAvatarAssetAudit(...args),
  renderCapabilityCatalogPanel: (...args) => renderCapabilityCatalogPanel(...args),
  renderPageFrame: (...args) => renderPageFrame(...args),
  renderWebChatProfileRow: (...args) => renderWebChatProfileRow(...args),
  state: state,
});

const viewState = createViewState(app);
const capabilityPage = createCapabilityPage({ state, escapeHtml, renderRoutingEvidence });
window.addEventListener("keydown", viewState.handleKeydown);
const pageView = createPageView({
  Capabilities: capabilityPage.renderCapabilities,
  Characters: renderCharacters,
  Modules: renderModules,
  Settings: renderSettings,
  Guide: renderGuide,
  Agent: renderAgent,
  WebWorkbench: renderWebWorkbench,
  Tasks: renderTasks,
  History: renderHistory,
  Notifications: renderNotifications,
  Developer: renderDeveloper,
});

let sharedAssistantId = "";
window.addEventListener("storage", (event) => {
  if (event.key !== "sumika:active-assistant:v1" || event.newValue === state.selectedCharacter || !state.characters.some((row) => row.id === event.newValue)) return;
  sharedAssistantId = event.newValue;
  state.selectedCharacter = event.newValue;
  if (state.connected) void ensureConversationPurpose();
});
const workbenchHost = createWorkbenchHost({
  state, rpc, render, selectSession, createSession, navigate: loadWorkbenchPage,
  openResidence: async () => {
    if (isDesktopShell) await invokeDesktop("set_display_mode", { mode: "pet" });
    else window.open(`${location.origin}${location.pathname}?view=companion`, "sumika-companion", "width=480,height=420");
  },
  setInspector: async ({ open, active }) => {
    if (!open || active !== "browser") { if (state.portalPanelOpen) await embeddedView.hide(); return; }
    state.portalPanelOpen = true;
    await embeddedView.list().catch(() => {});
  },
  sendRole: async (content, sessionId) => {
    const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ client_request_id: crypto.randomUUID(), session_id: sessionId || currentSessionId(), character_id: state.selectedCharacter, messages: [{ role: "user", content }] }) });
    if (result.work_request) workbenchHost.showRoleApproval(result.work_request, { session_id: sessionId, message: content });
    else if (result.message) { state.composerDraft = ""; workbenchHost.model.selectedTask = null; await loadMessages(); }
  },
  slots: {
    benefits: () => renderBenefitsSection(state.benefits),
    characters: () => renderCharacters(),
    connections: () => '<p class="wv2-connection-location">' + escapeHtml(state.privacy) + "</p>" + renderModules(),
    diagnostics: () => renderDeveloper(),
    preferences: () => renderSettings() + renderGuide(),
    agent: () => renderAgent(),
    web: () => renderWebWorkbench(),
    tasks: () => renderTasks(),
    history: () => renderHistory() + renderNotifications(),
    browser: () => renderPortalPanel(),
    memory: () => workbenchHost.model.memoryOpen ? `<section><button type="button" id="add-memory">添加记忆</button>${state.memories.map((memory) => `<article><p>${escapeHtml(memory.content)}</p><button type="button" data-memory-delete="${escapeHtml(memory.id)}">删除</button></article>`).join("")}</section>` : "",
  },
});

if (new URLSearchParams(location.search).get("view") === "settings") {
  workbenchHost.model.view = "settings";
  workbenchHost.model.connectionsOpen = new URLSearchParams(location.search).has("connections");
}

const workAuthorizationRpc = createWorkAuthorizationClient({
  transport: transportRpc,
  scope: () => ({ assistant_id: state.selectedCharacter, core_session_id: currentSessionId() }),
  onPending: (request, continuation) => { const advanced = document.querySelector(".wv2-center > .wv2-advanced"); if (advanced) advanced.open = false; workbenchHost.showExternalApproval(request, continuation); render(); },
  onResult: (request, continuation) => workbenchHost.observeExternalRequest(request, continuation),
});

const workbenchStyles = document.createElement("link");
workbenchStyles.rel = "stylesheet";
workbenchStyles.href = WORKBENCH_STYLESHEET;
document.head.append(workbenchStyles);
const companionStyles = document.createElement("style");
companionStyles.textContent = '.cw-companion-controls{position:fixed;top:8px;left:8px;display:flex;gap:4px;z-index:90;opacity:0}.cw-companion-controls:hover,.cw-companion-controls:focus-within{opacity:1}.cw-companion-controls button{background:#fff8ef;border:1px solid #d8ccbb;border-radius:8px;padding:5px;color:#514437}.wv2-host-notice{position:fixed;bottom:8px;left:20px;z-index:99;background:#fff1d8;padding:8px 16px;border-radius:8px;max-width:80vw}.workbench-v2 .page-header{display:none}.workbench-v2 .embedded-browser-panel{position:relative;inset:auto;width:100%;height:calc(100vh - 170px)}';
document.head.append(companionStyles);
companionStyles.sheet.insertRule(".cw-companion-controls { top: 52px; }", companionStyles.sheet.cssRules.length);
const workPoll = setInterval(() => {
  if (state.connected && document.visibilityState === "visible") void workbenchHost.refresh().then(() => {
    if (!state.overlayMode) render();
  });
}, 10000);
window.addEventListener("beforeunload", () => { clearInterval(workPoll); workbenchHost.destroy(); });
if (isDesktopShell) {
  void import("@tauri-apps/api/event").then(async ({ listen }) => {
    await listen("native-render-visibility-changed", ({ payload }) => {
      state.nativeRenderVisible = payload.rendering;
      updateSceneVisibility();
    });
    await listen("companion-window-changed", ({ payload }) => {
      if (!companionWindow) return;
      document.body.dataset.companionSize = payload.mode;
      render();
    });
  }).catch((error) => { state.sessionNotice = `窗口事件连接失败：${error.message}`; });
}

const initialAgentRoutingPreference = readAgentRoutingPreference();
state.agentRoutingMode = initialAgentRoutingPreference.mode;
state.agentRoutingBudgetPolicy = initialAgentRoutingPreference.budget_policy;

window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || event.defaultPrevented) return;
  if (document.querySelector("dialog[open]")) return;
  if (state.providerDrawerOpen) { closeProviderDrawer(); document.querySelector(".provider-picker > summary")?.focus(); }
  else if (state.webChatDrawerOpen) closeWebChatDrawer();
  else if (!state.overlayMode && workbenchHost.model.inspector.open) {
    void workbenchHost.actions.onInspectorChange({ open: false, active: workbenchHost.model.inspector.active });
  } else if (state.portalPanelOpen) {
    void embeddedView.hide();
  } else if (!state.overlayMode && document.activeElement?.closest("details[open]")) {
    const details = document.activeElement.closest("details[open]");
    details.open = false;
    details.querySelector("summary")?.focus();
  } else if (state.overlayMode) {
    void openMainWindow();
  } else if (projectSceneState(state).drawerOpen) {
    state.activePage = scenePageAfterDrawerClose();
    render();
  } else return;
  event.preventDefault();
});

window.addEventListener("focus", () => {
  void syncAgentState({ immediate: true });
});

document.addEventListener("visibilitychange", () => {
  updateSceneVisibility();
  void embeddedView.syncBounds().catch(() => {});
  if (document.visibilityState === "visible") void syncAgentState({ immediate: true });
});

ensureQualityRoutingStylesheet();
ensureConsultationStylesheet();
const embeddedStylesheet = document.createElement("link");
embeddedStylesheet.rel = "stylesheet";
embeddedStylesheet.href = new URL("./src/embedded-browser.css", import.meta.url).href;
document.head.appendChild(embeddedStylesheet);
render();
if (isDesktopShell) {
  void invokeDesktop("get_display_mode").then((mode) => {
    state.overlayMode = companionWindow;
    render();
  }).catch((error) => { state.sessionNotice = `窗口模式读取失败：${error.message}`; render(); });
}
void loadInitialData().finally(() => {
  if (isDesktopShell && !companionWindow) void embeddedView.attach().catch(() => {});
  scheduleAgentStateSync();
  connectEvents();
  if (state.connected) void ensureConversationPurpose();
});

async function ensureConversationPurpose() {
  const purpose = companionWindow ? "chat" : "work";
  const session = state.sessions.find((row) => row.character_id === state.selectedCharacter && row.purpose === purpose && !row.archived);
  if (session) await selectSession(session.id);
  else await createSession();
  await workbenchHost.refresh();
  render();
}
