// 前端 Web Vitals 测量（spec §22.6「首次可交互 < 2s」）。
// 用系统 Chrome 登录 → 进入 Dashboard，测量 FCP/LCP/加载时间/主内容可见时间。
// 前置：后端 8000 + Vite dev 5173 运行。用法：node scripts/measure-web-vitals.mjs

import { chromium } from "@playwright/test";

const BASE = process.env.BASE_URL || "http://localhost:5173";
const EMAIL = "owner@airesearcher.local";
const PASSWORD = "demo-password";

function metricsFrom(page) {
  return page.evaluate(() => {
    const nav = performance.getEntriesByType("navigation")[0];
    const paint = performance.getEntriesByType("paint");
    const fcp = paint.find((p) => p.name === "first-contentful-paint");
    return {
      domContentLoaded: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
      loadEventEnd: nav ? Math.round(nav.loadEventEnd) : null,
      fcp: fcp ? Math.round(fcp.startTime) : null,
    };
  });
}

async function main() {
  const browser = await chromium.launch({ channel: "chrome" });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const loginStart = Date.now();
  await page.goto(`${BASE}/login`);
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(/\/projects(\/|$)/, { timeout: 30000 });
  const loginMs = Date.now() - loginStart;

  // 进入 Dashboard，测量主内容可见时间
  const navStart = Date.now();
  await page.locator("button", { hasText: "protein-ligand-multimodal" }).first().click();
  await page.waitForURL(/\/projects\/[0-9a-f-]+\/overview/);
  await page.getByRole("heading", { name: "科研生命周期" }).waitFor({ state: "visible", timeout: 30000 });
  const headingVisibleMs = Date.now() - navStart;

  const navMetrics = await metricsFrom(page);

  // LCP 通过 PerformanceObserver 采集
  const lcp = await page.evaluate(async () => {
    return new Promise((resolve) => {
      const observer = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        if (entries.length) resolve(Math.round(entries[entries.length - 1].startTime));
        observer.disconnect();
      });
      observer.observe({ type: "largest-contentful-paint", buffered: true });
      setTimeout(() => resolve(null), 5000);
    });
  });

  console.log(`login→/projects: ${loginMs}ms`);
  console.log(`dashboard 主内容可见: ${headingVisibleMs}ms`);
  console.log(`FCP: ${navMetrics.fcp ?? "n/a"}ms`);
  console.log(`LCP: ${lcp ?? "n/a"}ms`);
  console.log(`DOMContentLoaded: ${navMetrics.domContentLoaded ?? "n/a"}ms`);
  console.log(`loadEventEnd: ${navMetrics.loadEventEnd ?? "n/a"}ms`);

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
