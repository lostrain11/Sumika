import assert from "node:assert/strict";
import test from "node:test";
import { changeCapabilityLayout, projectCapabilityLayout, readCapabilityLayout, writeCapabilityLayout } from "../src/capability-layout.js";
import { createCapabilityPage } from "../src/capability-page.js";

function memoryStorage(initial) {
  const values = new Map(initial ? [["sumika.capability-page.v1", initial]] : []);
  return { getItem: (key) => values.get(key) || null, setItem: (key, value) => values.set(key, value), values };
}

const state = {
  moduleCatalogStatus: "ready",
  modules: [
    { id: "asr", name: "语音识别", description: "真实语音模块", enabled: true, status: "unconfigured", permissions: ["microphone"] },
    { id: "tools", name: "外部工具", enabled: false, status: "disabled", permissions: ["process"] },
  ],
  audioStatus: { permissions: [{ permission_id: "microphone", state: "unknown" }], capabilities: [{ id: "asr", state: "disabled" }] },
};

test("布局首次投影已启用模块，移除后不会自动加回", () => {
  const storage = memoryStorage();
  const first = projectCapabilityLayout({ state, storage });
  assert.deepEqual(first.added.map((item) => item.id), ["asr"]);
  const removed = changeCapabilityLayout(first.persisted, "remove", "asr");
  writeCapabilityLayout(removed, storage);
  const after = projectCapabilityLayout({ state, storage });
  assert.deepEqual(after.added.map((item) => item.id), []);
  assert.equal(after.library.some((item) => item.id === "asr"), true);
});

test("添加、排序和移除只改变安全布局数据", () => {
  const layout = { version: 1, order: ["asr", "tools"], removed: [] };
  assert.deepEqual(changeCapabilityLayout(layout, "move-down", "asr").order, ["tools", "asr"]);
  assert.deepEqual(changeCapabilityLayout(layout, "add", "music"), { version: 1, order: ["asr", "tools", "music"], removed: [] });
  assert.deepEqual(changeCapabilityLayout(layout, "remove", "tools"), { version: 1, order: ["asr"], removed: ["tools"] });
});

test("损坏 localStorage 安全降级，未登记能力仅作为不可启用库项", () => {
  const storage = memoryStorage("{not-json");
  assert.deepEqual(readCapabilityLayout(storage), { version: 1, order: [], removed: [] });
  const page = createCapabilityPage({ state: { modules: [], moduleCatalogStatus: "error" }, storage, escapeHtml: (value) => String(value) });
  const html = page.renderCapabilities();
  assert.match(html, /模块目录读取失败；未生成替代运行数据/);
  assert.match(html, /data-capability-add="ocr"/);
  assert.match(html, /待实现，不可启用/);
  assert.doesNotMatch(html, /data-capability-card data-module-id="ocr"/);
});

test("页面接口暴露清晰的 render 和 bind 方法", () => {
  const page = createCapabilityPage({ state, storage: memoryStorage(), escapeHtml: (value) => String(value) });
  assert.equal(typeof page.renderCapabilities, "function");
  assert.equal(typeof page.bindCapabilities, "function");
  assert.match(page.renderCapabilities(), /capability-page/);
  assert.match(page.renderCapabilities(), /capability-tabs/);
  assert.match(page.renderCapabilities(), /capability-library/);
});
