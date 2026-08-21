import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  reporter: "line",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  workers: 1,
  outputDir: "../.cache/task-10-playwright",
  use: {
    baseURL: "http://127.0.0.1:4173",
    channel: "chrome",
    colorScheme: "light",
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    {
      command: "node e2e/fixtures/api-server.mjs",
      url: "http://127.0.0.1:4174/api/health",
      reuseExistingServer: false,
      timeout: 15_000,
    },
    {
      command: "cross-env VITE_API_PROXY=http://127.0.0.1:4174 vite --base / --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: false,
      timeout: 15_000,
    },
  ],
});
