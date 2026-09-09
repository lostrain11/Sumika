import assert from "node:assert/strict";
import test from "node:test";
import { displayMode, readDisplayPreferences, writeDisplayPreferences } from "../src/display-state.js";
import { AvatarRenderLoop } from "../src/vrm-viewer.js";
import { capabilityStatus } from "../src/capability-layout.js";

test("only the two authorized display modes are valid", () => {
  assert.equal(displayMode("pet"), "pet");
  assert.equal(displayMode("workspace"), "workspace");
  assert.throws(() => displayMode("wallpaper"));
  assert.deepEqual(readDisplayPreferences({ getItem: () => "null" }), { theme: null, transparent: false });
  assert.equal(writeDisplayPreferences({ setItem: () => { throw Error("storage denied"); } }, {}), false);
});

test("suspended renderer has no scheduled frame and resumes without time jump", () => {
  const pending = new Map();
  let sequence = 0;
  const deltas = [];
  const scheduler = { requestAnimationFrame: (callback) => { pending.set(++sequence, callback); return sequence; }, cancelAnimationFrame: (id) => pending.delete(id) };
  const loop = new AvatarRenderLoop((delta) => deltas.push(delta), scheduler);
  const step = (time) => { const [id, callback] = pending.entries().next().value; pending.delete(id); callback(time); };
  loop.setActive(true);
  loop.setActive(true);
  assert.equal(pending.size, 1);
  step(1000);
  step(1100);
  assert.deepEqual(deltas, [0, .05]);
  loop.setActive(false);
  assert.equal(pending.size, 0);
  loop.setActive(true);
  step(500000);
  assert.equal(deltas.at(-1), 0);
  loop.destroy();
  loop.setActive(true);
  assert.equal(pending.size, 0);
});

test("permission evidence cannot leak across capabilities or hide missing grants", () => {
  const state = { audioStatus: { permissions: [{ permission_id: "microphone", state: "granted" }] } };
  const camera = { id: "camera", permissions: ["camera.read"] };
  assert.equal(capabilityStatus(state, camera).permissions.authorization, "未知");
  const mixed = { id: "asr", permissions: ["microphone", "audio_output"] };
  assert.equal(capabilityStatus(state, mixed).permissions.authorization, "未知");
  assert.equal(capabilityStatus(state, { ...mixed, permissions: ["microphone"] }).permissions.authorization, "已授权");
});
