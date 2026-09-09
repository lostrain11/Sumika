import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { collectPricingRows } from "./zhipu-pricing-dom.mjs";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
let browser;
try {
  const { chromium } = require("@playwright/test");
  browser = await chromium.launch({ headless: true, timeout: 10000 });
  const context = await browser.newContext({ permissions: [], serviceWorkers: "block" });
  const page = await context.newPage();
  await page.goto("https://bigmodel.cn/pricing", { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector(".el-table__body-wrapper .name-box", { timeout: 5000 });
  const rows = await page.evaluate(collectPricingRows);
  if (!rows.length || rows.length > 512 || new Set(rows.map((row) => row.model_id)).size !== rows.length) throw new Error("ambiguous pricing scope");
  const sourceVersion = createHash("sha256").update(JSON.stringify(rows)).digest("hex");
  const observedAt = new Date().toISOString();
  console.log(JSON.stringify(rows.map((row) => ({ ...row, provider_id: "zhipu-official", source_url: "https://bigmodel.cn/pricing", source_version: sourceVersion, observed_at: observedAt, availability_state: "observed" }))));
} catch {
  console.error("Public pricing DOM unavailable; needs-review");
  process.exitCode = 2;
} finally {
  await browser?.close();
}
