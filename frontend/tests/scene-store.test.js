import assert from "node:assert/strict";

import {
  DEFAULT_SCENE_PAGE,
  projectSceneState,
  scenePageAfterDrawerClose,
  scenePageAfterNavigation,
} from "../src/scene-store.js";

const workbench = projectSceneState({
  activePage: "Agent",
  overlayMode: false,
  avatarVisible: false,
  sending: true,
  portalPanelOpen: true,
});

assert.deepEqual({
  activePage: workbench.activePage,
  overlayMode: workbench.overlayMode,
  drawer: workbench.drawer,
  drawerOpen: workbench.drawerOpen,
  drawerPages: workbench.drawerPages,
  avatarVisible: workbench.avatarVisible,
  sending: workbench.sending,
  portalPanelOpen: workbench.portalPanelOpen,
}, {
  activePage: "Agent",
  overlayMode: false,
  drawer: "workbench",
  drawerOpen: true,
  drawerPages: ["Agent", "WebWorkbench", "Tasks", "History", "Notifications"],
  avatarVisible: false,
  sending: true,
  portalPanelOpen: true,
});

const overlay = projectSceneState({ activePage: "Characters", overlayMode: true });
assert.equal(overlay.drawer, null);
assert.equal(overlay.drawerOpen, false);
assert.deepEqual(overlay.drawerPages, []);
assert.equal(projectSceneState({}).activePage, DEFAULT_SCENE_PAGE);
assert.equal(projectSceneState({ activePage: "unknown-page" }).activePage, DEFAULT_SCENE_PAGE);
assert.equal(projectSceneState({ activePage: "Characters" }).avatarVisible, true);
assert.equal(Object.isFrozen(workbench), true);
assert.equal(Object.isFrozen(workbench.drawerPages), true);

assert.equal(scenePageAfterNavigation("Settings"), "Settings");
assert.equal(scenePageAfterNavigation("not-a-page"), DEFAULT_SCENE_PAGE);
assert.equal(scenePageAfterDrawerClose(), DEFAULT_SCENE_PAGE);

console.log("scene-store contract tests passed");
