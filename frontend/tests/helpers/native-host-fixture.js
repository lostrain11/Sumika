import { requiresHostConfirmation } from "../../src/host-confirmation.js";

export async function hostRpc(endpoint, method, params = {}) {
  if (process.env.SUMIKA_TEST_ISOLATED !== "1" || !process.env.SUMIKA_TEST_HOST_SECRET) {
    throw new Error("Native host fixture requires its own bootstrapped isolated Core");
  }
  const base = endpoint.replace(/\/$/, "");
  const post = async (path, body, headers = {}) => {
    const response = await fetch(`${base}${path}`, { method: "POST",
      headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
    const value = await response.json();
    if (value.error) throw new Error(value.error.message);
    return value.result;
  };
  if (!requiresHostConfirmation(method, params)) {
    return post("/rpc", { jsonrpc: "2.0", id: "fixture", method, params });
  }
  const preview = await post("/rpc", { jsonrpc: "2.0", id: "fixture-preview",
    method: "host.confirmation.digest", params: { method, params } });
  return post("/internal/host-confirm/v1", { method, params, digest: preview.digest },
    { "X-Sumika-Host": process.env.SUMIKA_TEST_HOST_SECRET });
}

export async function installNativeHostFixture(page, endpoint, { confirm } = {}) {
  if (process.env.SUMIKA_TEST_ISOLATED !== "1") throw new Error("Native fixture requires isolated Core");
  await page.exposeFunction("fixtureNativeHost", async ({ method, params }) => {
    if (!requiresHostConfirmation(method, params)) throw new Error("Unexpected native fixture action");
    return confirm ? confirm({ method, params }) : hostRpc(endpoint, method, params);
  });
  await page.addInitScript((endpoint) => {
    window.__TAURI_INTERNALS__ = { invoke: async (command, params) => {
      if (command === "host_confirm") return window.fixtureNativeHost(params);
      if (command === "get_display_mode") return "workspace";
      if (command === "core_status") return { running: true, host: "127.0.0.1", port: Number(new URL(endpoint).port) };
      return [];
    } };
  }, endpoint);
}
