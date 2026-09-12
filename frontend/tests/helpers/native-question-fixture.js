import { expect } from "@playwright/test";

export async function installNativeQuestionFixture(page, endpoint, respond) {
  return installNativeConfirmationFixture(page, endpoint, "agent.question.respond", respond);
}

export async function installNativeConfirmationFixture(page, endpoint, method, respond) {
  if (process.env.SUMIKA_TEST_ISOLATED !== "1") throw new Error("Native fixture requires isolated Core");
  await page.exposeFunction("fixtureQuestionConfirmation", request => {
    expect(Array.isArray(method) ? method : [method]).toContain(request.method);
    return respond(request);
  });
  await page.addInitScript((endpoint) => {
    window.__TAURI_INTERNALS__ = { invoke: async (command, params) => {
      if (command === "host_confirm") return window.fixtureQuestionConfirmation(params);
      if (command === "get_display_mode") return "workspace";
      if (command === "core_status") return { running: true, host: "127.0.0.1", port: Number(new URL(endpoint).port) };
      return [];
    } };
  }, endpoint);
}
