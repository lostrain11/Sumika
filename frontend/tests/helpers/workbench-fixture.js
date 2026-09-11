import { expect } from "@playwright/test";

export const baseUrl = process.env.SUMIKA_BASE_URL || "http://127.0.0.1:8770/";

export async function installWorkbenchFixture(context) {
  if (process.env.SUMIKA_TEST_ISOLATED !== "1") throw new Error("Workbench E2E requires the isolated Core runner");
  const calls = [];
  const handlers = {};
  await context.exposeFunction("fixtureNativeConfirmation", async ({ method, params }) => {
    expect(["work.authorization.confirm", "quality.task.confirm", "quality.task.budget", "schedule.create", "schedule.update", "schedule.pause", "agent.approval.respond"]).toContain(method);
    if (!handlers[method]) throw new Error("Missing native confirmation fixture: " + method);
    calls.push({ method, params, transport: "native-fixture" });
    return handlers[method](params);
  });
  await context.addInitScript((endpoint) => {
    window.__TAURI_INTERNALS__ = { invoke: async (command, params) => {
      if (command === "host_confirm") return window.fixtureNativeConfirmation(params);
      if (command === "show_main_window") { window.open(endpoint, "sumika-main-fixture"); return {}; }
      if (command === "get_display_mode") return location.search.includes("companion") ? "pet" : "workspace";
      if (command === "core_status") return { running: true, host: "127.0.0.1", port: Number(new URL(endpoint).port) };
      return [];
    } };
  }, baseUrl);
  const candidates = ["free-role", "paid-leader"].map((id, index) => ({
    candidate_id: id, label: "隔离模型 " + id, model_id: id, channel: "fixture",
    authorized: true, available: true, reasoning_effort: index ? "high" : "medium",
    cost_quote: { free: !index, effective_cost_cny: index ? "2" : "0" },
  }));
  let settings = { assistant_id: "sumika", selection_mode: { leader: "auto", role: "auto" }, candidate_pool: candidates.map(row => row.candidate_id) };
  let request = null;
  const profile = { id: "host-fixture", name: "显式离线模型 fixture", adapter_id: "openai-compatible", status: "available", active: true,
    processing_location: "local", resolved_processing_location: "local", has_secrets: false,
    config: { model: "offline-fixture", active_base_url: "http://127.0.0.1:1/v1", base_urls: ["http://127.0.0.1:1/v1"] } };
  await context.route("**/api/provider-profiles*", route => route.fulfill({ json: [profile] }));
  await context.route("**/api/modules", route => route.fulfill({ json: [{
    id: "llm", name: "隔离模型", capability: "llm", enabled: true, status: "ready",
    implementation_id: "openai-compatible", implementation: { id: "openai-compatible", status: "ready" },
    implementations: [], config: {}, config_schema: {}, permissions: [],
  }] }));
  await context.route("**/api/chat", async route => {
    const params = route.request().postDataJSON();
    calls.push({ method: "fixture.chat", params });
    if (!handlers.chat) return route.fulfill({ status: 409, json: { error: { message: "No explicit chat fixture" } } });
    await route.fulfill({ json: await handlers.chat(params) });
  });
  await context.route("**/rpc", async route => {
    const body = route.request().postDataJSON();
    calls.push(body);
    const { method, params = {} } = body;
    if (method === "host.confirmation.digest") return route.fulfill({ json: { jsonrpc: "2.0", id: body.id, result: { digest: "fixture-only" } } });
    expect(["work.authorization.confirm", "quality.task.confirm", "quality.task.budget"]).not.toContain(method);
    let result;
    if (handlers[method]) result = await handlers[method](params);
    else if (method === "quality.catalog") result = { candidates };
    else if (method === "quality.settings.get") result = settings;
    else if (method === "quality.settings.set") {
      settings = { ...settings, ...params, selection_mode: { ...settings.selection_mode, ...params.selection_mode } };
      result = settings;
    } else if (method === "quality.bindings.select") {
      const binding = purpose => {
        const id = settings.selection_mode[purpose] === "fixed" ? settings[purpose + "_candidate_id"] : purpose === "leader" ? "paid-leader" : "free-role";
        const available = candidates.find(row => row.candidate_id === id)?.available;
        return { candidate_id: available ? id : null, reason: available ? "fixture-quality-evidence" : "fixed-candidate-unavailable" };
      };
      result = { bindings: { leader: binding("leader"), role: binding("role") } };
    } else if (method === "work.task.list") result = { tasks: request ? [request] : [] };
    else if (method === "work.task.get") result = request;
    else if (method.startsWith("work.")) {
      return route.fulfill({ json: { jsonrpc: "2.0", id: body.id, error: { code: -32000, message: "Unexpected fixture execution: " + method } } });
    } else return route.continue();
    await route.fulfill({ json: { jsonrpc: "2.0", id: body.id, result } });
  });
  return { calls, handlers, candidates, get settings() { return settings; }, get request() { return request; }, set request(value) { request = value; } };
}

export function quotedRequest(params, source = "workbench", limitEnforced = true) {
  return {
    request_id: params.request_id || params.client_request_id, assistant_id: params.assistant_id || "sumika",
    revision: 7, status: "awaiting-confirmation", goal: params.goal || params.text || params.question,
    request: { source, session_id: params.session_id || params.core_session_id, project_id: params.project_id || null, goal: params.goal || params.text || params.question },
    classification: { complexity: "complex", reason: "fixture complex request" },
    quote: { low_cny: "0", typical_cny: "1", high_cny: limitEnforced ? "2" : null },
    funding: { funding_kind: "cash" }, binding: { candidate_id: "paid-leader" },
    ...(source !== "workbench" && source !== "role" ? { external: { source, limit_enforced: limitEnforced } } : {}),
    status_detail: limitEnforced ? "隔离 fixture 尚未派发" : "宿主无法承诺硬上限；费用未知，暂不派发",
  };
}

export function confirmFixture(fixture) {
  fixture.handlers["work.authorization.confirm"] = params => {
    expect(params).toEqual(expect.objectContaining({ request_id: fixture.request.request_id, assistant_id: "sumika", revision: 7, max_cny: "2" }));
    expect(params.approved).toBeUndefined();
    fixture.request = { ...fixture.request, status: "ready", authorization: { revision: 7, max_cny: "2" } };
    return fixture.request;
  };
}
