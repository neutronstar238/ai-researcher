import { defineConfig, devices } from "@playwright/test";

/**
 * E2E + 视觉回归（spec §22.3）：基准视口 1440×900、100% 缩放、Chromium（系统 Chrome）。
 * 后端需在 8000 运行，前端 Vite dev 在 5173（/api、/health 代理到后端）。
 */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    channel: "chrome",
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    locale: "zh-CN",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
