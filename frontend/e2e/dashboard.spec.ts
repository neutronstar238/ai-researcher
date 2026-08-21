import { expect, test, type APIResponse, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const ROUTES = [
  ["/", "研究总览"],
  ["/projects", "项目空间"],
  ["/literature", "文献库"],
  ["/experiments", "实验管理"],
  ["/assets", "数据资产"],
  ["/knowledge", "知识图谱"],
  ["/writing", "写作中心"],
  ["/reflections", "复盘洞察"],
  ["/agents", "智能体中心"],
  ["/approvals", "审批中心"],
  ["/settings", "系统设置"],
] as const;

const ALLOWED_API_PATHS = [
  /^\/api\/health$/,
  /^\/api\/runs(?:\/[^/]+(?:\/(?:stages|artifacts|skills|resume|cancel|evolution))?)?$/,
  /^\/api\/batches(?:\/[^/]+)?$/,
  /^\/api\/skills\/candidates$/,
];

interface RuntimeEvidence {
  apiPaths: string[];
  consoleErrors: Array<{ message: string; url: string }>;
  failedRequests: string[];
  httpErrors: Array<{ path: string; status: number }>;
  pageErrors: string[];
}

function monitorRuntime(page: Page): RuntimeEvidence {
  const evidence: RuntimeEvidence = {
    apiPaths: [],
    consoleErrors: [],
    failedRequests: [],
    httpErrors: [],
    pageErrors: [],
  };
  page.on("pageerror", (error) => evidence.pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") {
      evidence.consoleErrors.push({ message: message.text(), url: message.location().url });
    }
  });
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) evidence.apiPaths.push(url.pathname);
  });
  page.on("requestfailed", (request) => {
    evidence.failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? "unknown"}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      evidence.httpErrors.push({ path: new URL(response.url()).pathname, status: response.status() });
    }
  });
  return evidence;
}

async function expectRuntimeClean(
  page: Page,
  evidence: RuntimeEvidence,
  allowedHttpErrors: Array<{ path: string; status: number }> = [],
): Promise<void> {
  await expect(page.locator("vite-error-overlay, #webpack-dev-server-client-overlay, nextjs-portal")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("Unexpected Application Error!");
  expect(evidence.pageErrors).toEqual([]);
  const browserLoadErrors = evidence.consoleErrors.filter(({ message }) => message.startsWith("Failed to load resource:"));
  expect(browserLoadErrors).toEqual(allowedHttpErrors.map(({ path }) => ({
    message: "Failed to load resource: the server responded with a status of 500 (Internal Server Error)",
    url: `http://127.0.0.1:4173${path}`,
  })));
  expect(evidence.consoleErrors.filter((entry) => !browserLoadErrors.includes(entry))).toEqual([]);
  expect(evidence.failedRequests).toEqual([]);
  expect(evidence.httpErrors).toEqual(allowedHttpErrors);
  expect(evidence.apiPaths.filter((path) => !ALLOWED_API_PATHS.some((pattern) => pattern.test(path)))).toEqual([]);
}

async function responseJson(response: APIResponse): Promise<Record<string, unknown>> {
  expect(response.headers()["content-type"]).toContain("application/json");
  return await response.json() as Record<string, unknown>;
}

function expectPublicRun(payload: Record<string, unknown>, status: string): void {
  expect(payload.schema_version).toBe("autoresearch-api-run-v1");
  expect(payload.status).toBe(status);
  expect(payload).not.toHaveProperty("stages");
  expect(payload).not.toHaveProperty("artifacts");
}

async function expectFixedHeaderDate(page: Page): Promise<void> {
  expect(await page.evaluate(() => ({
    colorScheme: matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark",
    locale: navigator.language,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  }))).toEqual({ colorScheme: "light", locale: "zh-CN", timezone: "Asia/Shanghai" });
  const headerTime = page.locator("header time.header-date");
  await expect(headerTime).toHaveAttribute("datetime", "2026-08-20");
  await expect(headerTime).toHaveText("2026年8月20日周四");
}

async function expectNoPageOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => ({
    body: document.body.scrollWidth - document.body.clientWidth,
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  }));
  expect(overflow.body).toBeLessThanOrEqual(1);
  expect(overflow.document).toBeLessThanOrEqual(1);
}

async function waitForDashboard(page: Page): Promise<void> {
  await page.goto("/");
  const dashboard = page.locator(".dashboard-page");
  await expect(dashboard).toHaveAttribute("data-loading", "false");
  await expect(page.getByRole("button", { name: "打开正在执行的测试研究" }).first()).toBeVisible();
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise<void>((resolveAnimation) => requestAnimationFrame(() => requestAnimationFrame(() => resolveAnimation())));
  });
}

async function saveScreenshot(page: Page, name: string): Promise<void> {
  const outputDirectory = resolve(process.cwd(), "test-results");
  await mkdir(outputDirectory, { recursive: true });
  await page.screenshot({ path: resolve(outputDirectory, name), animations: "disabled" });
}

test.describe.serial("AI-Researcher command center", () => {
  test.beforeEach(async ({ page }) => {
    await page.clock.install({ time: new Date("2026-08-20T04:00:00.000Z") });
    await page.emulateMedia({ colorScheme: "light" });
  });

  test("matches production read contracts without leaking run details", async ({ request }) => {
    const listResponse = await request.get("/api/runs");
    expect(listResponse.status()).toBe(200);
    const listPayload = await responseJson(listResponse);
    const listedRuns = listPayload.runs as Array<Record<string, unknown>>;
    expect(listedRuns).toHaveLength(3);
    for (const run of listedRuns) {
      expectPublicRun(run, String(run.status));
      expect(run.execution_boundary).toEqual({
        formal_experiment_enabled: false,
        result_paper_enabled: false,
        self_evolution_execution_enabled: false,
        api_owns_scientific_logic: false,
      });
    }

    const healthResponse = await request.get("/api/health");
    expect(healthResponse.status()).toBe(200);
    expect(await responseJson(healthResponse)).toEqual({
      status: "ok",
      service: "autoresearch-local-api",
      deployment_scope: "local_single_user",
      authentication_enabled: false,
      formal_experiment_enabled: false,
      result_paper_enabled: false,
      self_evolution_execution_enabled: true,
      self_evolution_service_configured: true,
      automatic_skill_activation_enabled: false,
      batch_execution_configured: true,
    });

    const detailResponse = await request.get("/api/runs/run-e2e-completed");
    expect(detailResponse.status()).toBe(200);
    const detail = await responseJson(detailResponse);
    expect(detail.schema_version).toBe("autoresearch-api-run-v1");
    expect(detail.stages).toHaveLength(12);
    expect(detail.artifacts).toHaveLength(4);

    const runningEvolution = await responseJson(await request.get("/api/runs/run-e2e-running/evolution"));
    const failedEvolution = await responseJson(await request.get("/api/runs/run-e2e-failed/evolution"));
    for (const status of [runningEvolution, failedEvolution]) {
      expect(status.execution_enabled).toBe(true);
      expect(status.mode).toBe("frozen_service_available");
      expect(status.promotion_authorized).toBe(false);
    }

    const candidatesResponse = await request.get("/api/skills/candidates");
    expect(candidatesResponse.status()).toBe(200);
    const candidates = await responseJson(candidatesResponse);
    expect(candidates.mode).toBe("query_only");
    expect(candidates.promotion_authorized).toBe(false);
    expect(candidates.candidates).toEqual([
      expect.objectContaining({
        candidate_skill_id: "candidate-e2e-001",
        relative_path: "exploration/skills/candidates/candidate-e2e-001.md",
        promotion_authorized: false,
      }),
    ]);

    const batchesResponse = await request.get("/api/batches");
    expect(batchesResponse.status()).toBe(200);
    const listedBatches = (await responseJson(batchesResponse)).batches as Array<Record<string, unknown>>;
    expect(listedBatches[0]).toMatchObject({
      schema_version: "autoresearch-api-batch-preview-v1",
      status: "dry_run",
      dry_run: true,
      batch_service_configured: false,
      provider_calls: 0,
    });
    expect(listedBatches[0]).not.toHaveProperty("batch_service_receipt");
  });

  test("captures the four stable accepted states", async ({ page }) => {
    const runtime = monitorRuntime(page);

    await page.setViewportSize({ width: 1440, height: 900 });
    await waitForDashboard(page);
    await expectFixedHeaderDate(page);
    await saveScreenshot(page, "dashboard-1440x900.png");

    await page.setViewportSize({ width: 1280, height: 900 });
    await waitForDashboard(page);
    await saveScreenshot(page, "dashboard-1280x900.png");

    await page.setViewportSize({ width: 900, height: 1000 });
    await waitForDashboard(page);
    await saveScreenshot(page, "dashboard-900x1000.png");

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/projects?run=run-e2e-running");
    await expect(page.getByRole("dialog", { name: "运行详情" })).toContainText("正在执行的测试研究");
    await saveScreenshot(page, "projects-run-details-1440x900.png");

    const stageRows = page.locator(".run-stage-list li");
    await expect(stageRows).toHaveCount(12);
    const stageGeometry = await stageRows.evaluateAll((rows) => rows.map((row) => {
      const rowRect = row.getBoundingClientRect();
      const children = [...row.children].map((child) => {
        const rect = child.getBoundingClientRect();
        const style = getComputedStyle(child);
        return {
          bottom: rect.bottom,
          height: rect.height,
          left: rect.left,
          lineHeight: Number.parseFloat(style.lineHeight),
          right: rect.right,
          top: rect.top,
          whiteSpace: style.whiteSpace,
        };
      });
      return {
        children,
        clientWidth: row.clientWidth,
        row: { bottom: rowRect.bottom, left: rowRect.left, right: rowRect.right, top: rowRect.top },
        scrollWidth: row.scrollWidth,
      };
    }));
    for (const row of stageGeometry) {
      expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth + 1);
      for (const child of row.children) {
        expect(child.left).toBeGreaterThanOrEqual(row.row.left - 1);
        expect(child.right).toBeLessThanOrEqual(row.row.right + 1);
        expect(child.top).toBeGreaterThanOrEqual(row.row.top - 1);
        expect(child.bottom).toBeLessThanOrEqual(row.row.bottom + 1);
      }
      for (const child of row.children.slice(1)) expect(child.whiteSpace).toBe("nowrap");
    }

    await expectNoPageOverflow(page);
    await expectRuntimeClean(page, runtime);
  });

  test("renders a production-shaped dashboard without runtime or overflow failures", async ({ page }) => {
    const runtime = monitorRuntime(page);
    await waitForDashboard(page);
    await expectFixedHeaderDate(page);

    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).toHaveText("研究总览");
    await expect(page.getByRole("list", { name: "研究生命周期" })).toBeVisible();
    await expect(page.getByRole("table", { name: "近期研究" })).toBeVisible();
    await expect(page.getByRole("table", { name: "研究证据覆盖趋势数据" })).toBeAttached();
    await expect(page.getByText("批量执行已配置", { exact: true })).toBeVisible();
    await expect(page.locator("img.brand-logo")).toHaveJSProperty("complete", true);
    expect(await page.locator("img.brand-logo").evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);

    await expectNoPageOverflow(page);
    await expectRuntimeClean(page, runtime);
  });

  test("loads all eleven destinations directly, through navigation, and after reload", async ({ page }) => {
    const runtime = monitorRuntime(page);

    for (const [path, heading] of ROUTES) {
      await page.goto(path);
      await expect(page.locator("h1")).toHaveCount(1);
      await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toHaveCount(1);
      await page.reload();
      await expect(page.locator("h1")).toHaveCount(1);
      await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toHaveCount(1);

      if (path !== "/") {
        await page.getByRole("link", { name: "研究总览", exact: true }).click();
        await expect(page).toHaveURL("/");
        await expect(page.getByRole("heading", { level: 1, name: "研究总览", exact: true })).toHaveCount(1);
        await page.getByRole("link", { name: heading, exact: true }).click();
        await expect(page).toHaveURL(new RegExp(`${path.replace("/", "\\/")}$`));
        await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toHaveCount(1);
      }
    }

    await expectRuntimeClean(page, runtime);
  });

  test("creates a deterministic run and opens its real detail drawer", async ({ page }) => {
    const runtime = monitorRuntime(page);
    await waitForDashboard(page);
    await page.getByRole("link", { name: "项目空间", exact: true }).click();
    await page.getByRole("button", { name: "新建研究" }).click();
    const createDrawer = page.getByRole("dialog", { name: "新建研究" });
    await createDrawer.getByLabel("科学问题", { exact: true }).fill("浏览器端新研究");
    const createResponsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/runs");
    await createDrawer.getByRole("button", { name: "开始研究" }).click();
    const createResponse = await createResponsePromise;
    expect(createResponse.status()).toBe(201);
    expectPublicRun(await createResponse.json() as Record<string, unknown>, "queued");

    await expect(page.locator(".toast-region")).toContainText("研究运行已创建");
    await expect(page).toHaveURL(/\/projects\?run=run-e2e-created-001$/);
    expect(new URL(page.url()).searchParams.get("run")).toBe("run-e2e-created-001");
    const drawer = page.getByRole("dialog", { name: "运行详情" });
    await expect(drawer).toContainText("浏览器端新研究");
    await expect(drawer).toContainText("run-e2e-created-001");

    const detailResponse = await page.request.get("/api/runs/run-e2e-created-001");
    expect(detailResponse.status()).toBe(200);
    const detail = await responseJson(detailResponse);
    expect(detail).toHaveProperty("stages");
    expect(detail).toHaveProperty("artifacts");

    const queuedCancelResponse = await page.request.post("/api/runs/run-e2e-created-001/cancel");
    expect(queuedCancelResponse.status()).toBe(202);
    expectPublicRun(await responseJson(queuedCancelResponse), "canceled");

    await expectRuntimeClean(page, runtime);
  });

  test("confirms cancellation, traps focus, and updates only the selected run", async ({ page }) => {
    const runtime = monitorRuntime(page);
    await page.goto("/projects");
    await page.getByRole("button", { name: "查看正在执行的测试研究" }).click();
    const runDrawer = page.getByRole("dialog", { name: "运行详情" });
    expect(await page.locator("body").evaluate((body) => getComputedStyle(body).overflow)).toBe("hidden");
    await expect(runDrawer).toContainText("running");
    await runDrawer.getByRole("button", { name: "请求取消" }).click();

    const confirmation = page.getByRole("dialog", { name: "取消运行" });
    expect(await page.locator("body").evaluate((body) => getComputedStyle(body).overflow)).toBe("hidden");
    const cancelButton = confirmation.getByRole("button", { name: "取消", exact: true });
    const confirmButton = confirmation.getByRole("button", { name: "确认取消", exact: true });
    await expect(cancelButton).toBeFocused();
    await cancelButton.press("Shift+Tab");
    await expect(confirmButton).toBeFocused();
    await confirmButton.press("Tab");
    await expect(cancelButton).toBeFocused();
    const cancelResponsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/runs/run-e2e-running/cancel");
    await confirmButton.click();
    const cancelResponse = await cancelResponsePromise;
    expect(cancelResponse.status()).toBe(202);
    expectPublicRun(await cancelResponse.json() as Record<string, unknown>, "cancel_requested");

    await expect(confirmation).toBeHidden();
    expect(await page.locator("body").evaluate((body) => getComputedStyle(body).overflow)).toBe("hidden");
    await expect(runDrawer).toContainText("cancel_requested");
    await expect(page.locator(".toast-region")).toContainText("取消请求已提交");
    expect(await runDrawer.evaluate((drawer) => drawer.contains(document.activeElement))).toBe(true);
    await runDrawer.getByRole("button", { name: "关闭" }).click();
    await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");

    const completedRow = page.getByRole("row", { name: /已完成的测试研究/ });
    await expect(completedRow).toContainText("completed");
    const canceledRow = page.getByRole("row", { name: /正在执行的测试研究/ });
    await expect(canceledRow).toContainText("cancel_requested");
    await expectRuntimeClean(page, runtime);
  });

  test("resumes a failed run and limits evolution to completed runs", async ({ page }) => {
    const runtime = monitorRuntime(page);
    await page.goto("/projects");
    await page.getByRole("button", { name: "查看失败的测试研究" }).click();
    const failedDrawer = page.getByRole("dialog", { name: "运行详情" });
    await expect(failedDrawer).toContainText("测试科学门阻断");
    await expect(failedDrawer.getByRole("button", { name: "发起进化" })).toHaveCount(0);
    const resumeResponsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/runs/run-e2e-failed/resume");
    await failedDrawer.getByRole("button", { name: "恢复运行" }).click();
    const resumeResponse = await resumeResponsePromise;
    expect(resumeResponse.status()).toBe(202);
    expectPublicRun(await resumeResponse.json() as Record<string, unknown>, "queued");
    await expect(page.locator(".toast-region")).toContainText("研究运行已恢复");
    await expect(failedDrawer).toContainText("queued");
    await failedDrawer.getByRole("button", { name: "关闭" }).click();

    await page.getByRole("button", { name: "查看已完成的测试研究" }).click();
    const completedDrawer = page.getByRole("dialog", { name: "运行详情" });
    await expect(completedDrawer.getByRole("button", { name: "发起进化" })).toBeVisible();
    const evolutionResponsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/runs/run-e2e-completed/evolution");
    await completedDrawer.getByRole("button", { name: "发起进化" }).click();
    const evolutionResponse = await evolutionResponsePromise;
    expect(evolutionResponse.status()).toBe(201);
    expect(await evolutionResponse.json()).toMatchObject({
      schema_version: "autoresearch-api-skill-evolution-receipt-v1",
      run_id: "run-e2e-completed",
      status: "shadow_validated",
      promotion_authorized: false,
    });
    await expect(page.locator(".toast-region")).toContainText("进化候选任务已发起");
    await expectRuntimeClean(page, runtime);
  });

  test("keeps batch errors and receipts accessible and keyboard contained", async ({ page }) => {
    const runtime = monitorRuntime(page);
    await page.goto("/projects");
    const trigger = page.getByRole("button", { name: "批量任务", exact: true });
    await trigger.click();
    const drawer = page.getByRole("dialog", { name: "批量任务" });
    const postsBeforeClientError = runtime.apiPaths.filter((path) => path === "/api/batches").length;
    await drawer.getByRole("button", { name: "创建批量任务" }).click();
    const pathInput = drawer.getByLabel("服务器 PDF 路径");
    await expect(pathInput).toHaveAttribute("aria-invalid", "true");
    await expect(drawer.getByRole("alert")).toHaveText("请输入服务器 PDF 路径");
    expect(runtime.apiPaths.filter((path) => path === "/api/batches")).toHaveLength(postsBeforeClientError);
    await expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(await drawer.evaluate((element) => element.contains(document.activeElement))).toBe(true);

    await drawer.getByLabel("服务器 PDF 路径").fill("server-error.pdf");
    const serverErrorResponsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/batches");
    await drawer.getByRole("button", { name: "创建批量任务" }).click();
    const serverErrorResponse = await serverErrorResponsePromise;
    expect(serverErrorResponse.status()).toBe(500);
    await expect(drawer.getByRole("alert")).toHaveText("确定性批量服务错误");
    await expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(await drawer.evaluate((element) => element.contains(document.activeElement))).toBe(true);

    await drawer.getByLabel("服务器 PDF 路径").fill("questions.pdf");
    const batchResponsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/batches");
    await drawer.getByRole("button", { name: "创建批量任务" }).click();
    const batchResponse = await batchResponsePromise;
    expect(batchResponse.status()).toBe(201);
    expect(await batchResponse.json()).toMatchObject({
      schema_version: "autoresearch-api-batch-submission-v1",
      status: "dry_run",
      dry_run: true,
      question_count: 125,
      batch_service_receipt: {
        schema_version: "science125-batch-report-v2",
        literature_protocol: "two_stage_literature_v5",
        status: "dry_run",
        question_count: 125,
        provider_calls: 0,
      },
    });
    const receipt = drawer.getByLabel("批量任务创建回执");
    const receiptHeading = receipt.getByRole("heading", { name: "批量任务创建回执" });
    await expect(receiptHeading).toBeFocused();
    await expect(receipt).toContainText("batch-e2e-created-001");
    await receiptHeading.press("Shift+Tab");
    expect(await drawer.evaluate((element) => element.contains(document.activeElement))).toBe(true);
    await page.keyboard.press("Tab");
    expect(await drawer.evaluate((element) => element.contains(document.activeElement))).toBe(true);
    await drawer.getByRole("button", { name: "关闭" }).click();
    await expect(trigger).toBeFocused();
    await expectRuntimeClean(page, runtime, [{ path: "/api/batches", status: 500 }]);
  });

  test("preserves artifact URLs, capability boundaries, health facts, and theme state", async ({ page }) => {
    const runtime = monitorRuntime(page);
    const artifactUrl = "/api/runs/run-e2e-completed/artifacts/literature/survey%20v1.json?download=1&signature=fixed%2Btoken";

    for (const path of ["/literature", "/experiments", "/assets", "/writing"]) {
      await page.goto(path);
      await page.getByLabel("研究运行").selectOption("run-e2e-completed");
      if (path === "/literature") await expect(page.locator(`a[href="${artifactUrl}"]`)).toHaveCount(1);
      await expect(page.locator(".resource-list a").first()).toHaveAttribute("href", /^\/api\/runs\/run-e2e-completed\/artifacts\//);
    }

    const apiCountBeforeBoundaries = runtime.apiPaths.length;
    await page.goto("/knowledge");
    await expect(page.getByRole("status", { name: "能力边界" })).toContainText("当前服务未提供知识图谱查询接口");
    await page.goto("/approvals");
    await expect(page.getByRole("status", { name: "能力边界" })).toContainText("当前服务未提供审批队列接口");
    expect(runtime.apiPaths.slice(apiCountBeforeBoundaries).filter((path) => /knowledge|approval/.test(path))).toEqual([]);

    await page.goto("/settings");
    await expect(page.getByRole("table", { name: "服务能力" })).toContainText("批量执行配置");
    await page.getByRole("radio", { name: "深色" }).check();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.getByRole("radio", { name: "浅色" }).check();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expectRuntimeClean(page, runtime);
  });

  test("keeps responsive pages, tables, and mobile navigation inside the viewport", async ({ page }) => {
    const runtime = monitorRuntime(page);
    await page.setViewportSize({ width: 900, height: 1000 });
    await waitForDashboard(page);
    await expect(page.getByRole("button", { name: "打开导航菜单" })).toBeVisible();
    await expectNoPageOverflow(page);

    await page.getByRole("button", { name: "打开导航菜单" }).click();
    const navigationDrawer = page.getByRole("dialog", { name: "导航菜单" });
    await expect(navigationDrawer).toBeVisible();
    expect(await page.locator("body").evaluate((body) => getComputedStyle(body).overflow)).toBe("hidden");
    const drawerBox = await navigationDrawer.boundingBox();
    expect(drawerBox).not.toBeNull();
    expect(drawerBox!.x).toBeGreaterThanOrEqual(0);
    expect(drawerBox!.x + drawerBox!.width).toBeLessThanOrEqual(901);
    await navigationDrawer.getByRole("link", { name: "项目空间" }).click();
    await expect(navigationDrawer).toBeHidden();
    await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");
    await expectNoPageOverflow(page);

    const tableScroll = page.getByRole("table", { name: "研究运行" }).locator("..");
    const tableGeometry = await tableScroll.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        clientWidth: element.clientWidth,
        left: rect.left,
        right: rect.right,
        scrollWidth: element.scrollWidth,
      };
    });
    expect(tableGeometry.left).toBeGreaterThanOrEqual(0);
    expect(tableGeometry.right).toBeLessThanOrEqual(901);
    expect(tableGeometry.scrollWidth).toBeGreaterThan(tableGeometry.clientWidth);
    await tableScroll.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
    expect(await tableScroll.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
    await tableScroll.evaluate((element) => { element.scrollLeft = 0; });

    await page.getByRole("button", { name: "查看正在执行的测试研究" }).click();
    const runDrawer = page.getByRole("dialog", { name: "运行详情" });
    const drawerGeometry = await runDrawer.evaluate((drawer) => {
      const drawerRect = drawer.getBoundingClientRect();
      const stageRows = [...drawer.querySelectorAll(".run-stage-list li")];
      return {
        drawer: { bottom: drawerRect.bottom, left: drawerRect.left, right: drawerRect.right, top: drawerRect.top },
        rows: stageRows.map((row) => {
          const rowRect = row.getBoundingClientRect();
          const children = [...row.children].map((child) => {
            const rect = child.getBoundingClientRect();
            return { bottom: rect.bottom, left: rect.left, right: rect.right, top: rect.top };
          });
          const overlaps = children.flatMap((first, firstIndex) =>
            children.slice(firstIndex + 1).map((second) =>
              Math.min(first.right, second.right) - Math.max(first.left, second.left) > 1
              && Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top) > 1));
          return {
            bottom: rowRect.bottom,
            clientWidth: row.clientWidth,
            left: rowRect.left,
            overlaps,
            right: rowRect.right,
            scrollWidth: row.scrollWidth,
            top: rowRect.top,
          };
        }),
      };
    });
    expect(drawerGeometry.drawer.left).toBeGreaterThanOrEqual(0);
    expect(drawerGeometry.drawer.right).toBeLessThanOrEqual(901);
    expect(drawerGeometry.drawer.top).toBeGreaterThanOrEqual(0);
    expect(drawerGeometry.drawer.bottom).toBeLessThanOrEqual(1001);
    for (const row of drawerGeometry.rows) {
      expect(row.left).toBeGreaterThanOrEqual(drawerGeometry.drawer.left);
      expect(row.right).toBeLessThanOrEqual(drawerGeometry.drawer.right);
      expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth + 1);
      expect(row.overlaps).not.toContain(true);
    }
    await runDrawer.getByRole("button", { name: "关闭" }).click();
    await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");

    await expectRuntimeClean(page, runtime);
  });
});
