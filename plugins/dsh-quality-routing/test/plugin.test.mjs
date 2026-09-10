import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import { ManagedQualityHelper, helperEnvironment } from "../lib/helper-client.mjs";
import { QUALITY_ROUTING_TOOLS, resolveHelperConfig } from "../lib/policy.mjs";

test("tool surface contains no approval operation", () => {
  assert.deepEqual(QUALITY_ROUTING_TOOLS, [
    "quality_routing_component_status",
    "quality_routing_offline_fixture"
  ]);
  assert.equal(QUALITY_ROUTING_TOOLS.some(name => /approve|confirm|authorize/.test(name)), false);
});

test("enabled helper requires explicit absolute paths", () => {
  assert.deepEqual(resolveHelperConfig({ enabled: false }), { enabled: false });
  assert.throws(() => resolveHelperConfig({ enabled: true }), /pythonExecutable/);
  assert.throws(() => resolveHelperConfig({ enabled: true, pythonExecutable: "python", dataDirectory: "data" }), /absolute/);
});

test("helper environment does not forward provider credentials", () => {
  const previous = process.env.DEEPSEEK_API_KEY;
  process.env.DEEPSEEK_API_KEY = "test-secret-must-not-cross-process-boundary";
  try {
    const environment = helperEnvironment();
    assert.equal(environment.DEEPSEEK_API_KEY, undefined);
    assert.equal(environment.PYTHONPATH, undefined);
  } finally {
    if (previous === undefined) delete process.env.DEEPSEEK_API_KEY;
    else process.env.DEEPSEEK_API_KEY = previous;
  }
});

test("managed helper starts, runs the offline fixture, and stops", { skip: !process.env.QUALITY_ROUTING_TEST_PYTHON }, async () => {
  const directory = await mkdtemp(join(tmpdir(), "quality-routing-dsh-"));
  const client = new ManagedQualityHelper(resolveHelperConfig({
    enabled: true,
    pythonExecutable: resolve(process.env.QUALITY_ROUTING_TEST_PYTHON),
    dataDirectory: directory
  }));
  try {
    const status = await client.call("capabilities");
    assert.equal(status.sumika_core_dependency, false);
    assert.equal(status.real_model_execution.available, false);
    assert.equal(status.model_tool_can_approve, false);
    const fixture = await client.call("offline_fixture");
    assert.equal(fixture.real_model, false);
    assert.deepEqual(fixture.states, ["awaiting-confirmation", "ready", "completed"]);
  } finally {
    await client.close();
  }
  const lifecycle = JSON.parse(await readFile(join(directory, "lifecycle.json"), "utf8"));
  assert.equal(lifecycle.state, "stopped");
  await rm(directory, { recursive: true, force: true });
});

