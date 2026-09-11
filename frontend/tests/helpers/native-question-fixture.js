import { expect } from "@playwright/test";

export async function installNativeQuestionFixture(page, endpoint, respond) {
  if (process.env.SUMIKA_TEST_ISOLATED !== "1") throw new Error("Native fixture requires isolated Core");
  await page.exposeFunction("fixtureQuestionConfirmation", ({ method, params }) => {
    expect(method).toBe("agent.question.respond");
    return respond({ method, params });
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
