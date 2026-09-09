import assert from "node:assert/strict";

import {
  DRAWER_GROUPS,
  NAV_ITEMS,
  drawerForPage,
  drawerPages,
  isScenePage,
  pageLabel,
} from "../src/scene-shell.js";

assert.equal(drawerForPage("Chat"), null);
assert.equal(drawerForPage("Agent"), "workbench");
assert.equal(drawerForPage("Developer"), "settings");
assert.equal(drawerForPage("Capabilities"), "modules");
assert.equal(drawerForPage("Modules"), "settings");
assert.equal(drawerForPage("Guide"), "settings");
assert.equal(drawerForPage("Missing"), null);

assert.equal(pageLabel("WebWorkbench"), "网页工作台");
assert.equal(pageLabel("unknown-page"), "unknown-page");
assert.deepEqual(drawerPages("characters"), ["Characters"]);
assert.deepEqual(drawerPages("missing"), []);
assert.equal(isScenePage("Chat"), true);
assert.equal(isScenePage("Characters"), true);
assert.equal(isScenePage("Missing"), false);

for (const [page] of NAV_ITEMS) {
  assert.equal(isScenePage(page), true, page);
}

assert.equal(Object.isFrozen(DRAWER_GROUPS), true);
assert.equal(Object.isFrozen(DRAWER_GROUPS.workbench), true);
assert.equal(Object.isFrozen(NAV_ITEMS), true);
assert.equal(Object.isFrozen(NAV_ITEMS[0]), true);

console.log("scene-shell contract tests passed");
