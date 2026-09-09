import { drawerForPage, drawerPages, isScenePage } from "./scene-shell.js";

export const DEFAULT_SCENE_PAGE = "Chat";

export function projectSceneState(source = {}) {
  const activePage = isScenePage(source.activePage)
    ? source.activePage
    : DEFAULT_SCENE_PAGE;
  const overlayMode = source.overlayMode === true;
  const drawer = overlayMode ? null : drawerForPage(activePage);
  return Object.freeze({
    activePage,
    overlayMode,
    drawer,
    drawerOpen: drawer !== null,
    drawerPages: Object.freeze(drawerPages(drawer).slice()),
    avatarVisible: source.avatarVisible !== false,
    sending: source.sending === true,
    portalPanelOpen: source.portalPanelOpen === true,
  });
}

export function scenePageAfterNavigation(page) {
  return isScenePage(page) ? page : DEFAULT_SCENE_PAGE;
}

export function scenePageAfterDrawerClose() {
  return DEFAULT_SCENE_PAGE;
}
