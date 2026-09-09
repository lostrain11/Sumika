import assert from "node:assert/strict";
import { projectModules } from "../src/module-selector.js";
import { createPageView } from "../src/page-view.js";

const modules = Object.freeze([
  Object.freeze({ id: "llm", enabled: false }),
  Object.freeze({ id: "asr", enabled: true, status: "error" }),
  Object.freeze({ id: "vision", enabled: "false" }),
  Object.freeze({ id: "tools", enabled: false }),
]);
const projection = projectModules({ modules, moduleCatalogStatus: "ready" });
assert.deepEqual(projection.enabled.map((module) => module.id), ["asr"]);
assert.deepEqual(projection.available.map((module) => module.id), ["llm", "vision", "tools"]);
assert.equal(projection.audioVisible, true);
assert.equal(projection.visionVisible, false);
assert.equal(projection.toolsVisible, false);
assert.equal(projection.enabled[0].status, "error");
assert.equal(Object.isFrozen(projection.enabled), true);
assert.equal(Object.isFrozen(projection.available), true);
assert.equal(Object.isFrozen(projection), true);
assert.equal(projectModules({ moduleCatalogStatus: "loading" }).loading, true);
assert.equal(projectModules({ moduleCatalogStatus: "error" }).failed, true);
assert.deepEqual(projectModules().enabled, []);

let calls = 0;
const pages = { Characters: () => { calls += 1; return "character view"; } };
const render = createPageView(pages);
pages.Characters = () => "replacement";
assert.equal(render("Characters"), "character view");
assert.equal(render("Chat"), "");
assert.equal(render("Missing"), "");
assert.equal(render("constructor"), "");
assert.equal(calls, 1);
console.log("module-selector and page-view contract tests passed");
