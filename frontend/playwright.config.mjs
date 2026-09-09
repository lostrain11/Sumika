import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.js",
  workers: 1,
  outputDir: process.env.SUMIKA_TEST_OUTPUT || join(tmpdir(), "sumika-ui-tests", String(Date.now())),
});
