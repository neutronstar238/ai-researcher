import { expect, test, type Page } from "@playwright/test";

async function waitForDashboard(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.locator(".dashboard-page")).toHaveAttribute("data-loading", "false");
  await expect(page.getByRole("button", { name: "打开正在执行的测试研究" }).first()).toBeVisible();
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise<void>((resolveAnimation) => requestAnimationFrame(() => requestAnimationFrame(resolveAnimation)));
  });
}

async function installFiveRunList(page: Page): Promise<void> {
  const listResponse = await page.request.get("/api/runs");
  expect(listResponse.ok()).toBe(true);
  const listPayload = await listResponse.json() as { runs: Array<Record<string, unknown>> };
  expect(listPayload.runs).toHaveLength(3);

  const completed = structuredClone(listPayload.runs.find((run) => run.run_id === "run-e2e-completed"));
  const failed = structuredClone(listPayload.runs.find((run) => run.run_id === "run-e2e-failed"));
  expect(completed).toBeDefined();
  expect(failed).toBeDefined();

  const completedStagesResponse = await page.request.get("/api/runs/run-e2e-completed/stages");
  const failedStagesResponse = await page.request.get("/api/runs/run-e2e-failed/stages");
  expect(completedStagesResponse.ok()).toBe(true);
  expect(failedStagesResponse.ok()).toBe(true);
  const completedStages = await completedStagesResponse.json() as { stages: unknown[] };
  const failedStages = await failedStagesResponse.json() as { stages: unknown[] };

  const extras = [
    {
      ...completed!,
      run_id: "run-repair-completed",
      direction: "复核用已完成研究",
      output_dir: "runs/e2e/run-repair-completed",
      created_at: "2026-08-20T04:00:00Z",
      started_at: "2026-08-20T04:01:00Z",
      finished_at: "2026-08-20T04:20:00Z",
    },
    {
      ...failed!,
      run_id: "run-repair-failed",
      direction: "复核用失败研究",
      output_dir: "runs/e2e/run-repair-failed",
      created_at: "2026-08-20T03:00:00Z",
      started_at: "2026-08-20T03:01:00Z",
      finished_at: "2026-08-20T03:20:00Z",
    },
  ];

  await page.route("**/api/runs", async (route) => {
    await route.fulfill({ json: { runs: [...listPayload.runs, ...extras] } });
  });
  await page.route("**/api/runs/run-repair-completed/stages", async (route) => {
    await route.fulfill({ json: { run_id: "run-repair-completed", stages: completedStages.stages } });
  });
  await page.route("**/api/runs/run-repair-failed/stages", async (route) => {
    await route.fulfill({ json: { run_id: "run-repair-failed", stages: failedStages.stages } });
  });
}

test.describe("Task 11 rendered fidelity geometry", () => {
  test.beforeEach(async ({ page }) => {
    await page.clock.install({ time: new Date("2026-08-20T04:00:00.000Z") });
    await page.emulateMedia({ colorScheme: "light" });
  });

  test("renders the measured canonical grid, regions, brand, and lifecycle connectors", async ({ page }) => {
    await page.setViewportSize({ width: 1487, height: 1058 });
    await waitForDashboard(page);

    const geometry = await page.evaluate(() => {
      const rect = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) throw new Error(`Missing ${selector}`);
        const box = element.getBoundingClientRect();
        return { bottom: box.bottom, height: box.height, left: box.left, right: box.right, top: box.top, width: box.width };
      };
      const grid = (testId: string) => {
        const element = document.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
        if (!element) throw new Error(`Missing ${testId}`);
        const box = element.getBoundingClientRect();
        const children = [...element.children].map((child) => child.getBoundingClientRect().width);
        return { gap: Number.parseFloat(getComputedStyle(element).columnGap), width: box.width, children };
      };
      const stages = [...document.querySelectorAll<HTMLElement>(".lifecycle-stage")].map((stage) => {
        const stageRect = stage.getBoundingClientRect();
        const iconRect = stage.querySelector<HTMLElement>(".lifecycle-icon")!.getBoundingClientRect();
        const connector = getComputedStyle(stage, "::after");
        const connectorLeft = Number.parseFloat(connector.left);
        const connectorWidth = Number.parseFloat(connector.width);
        return {
          connector: {
            backgroundColor: connector.backgroundColor,
            content: connector.content,
            display: connector.display,
            height: Number.parseFloat(connector.height),
            left: stageRect.left + connectorLeft,
            right: stageRect.left + connectorLeft + connectorWidth,
            width: connectorWidth,
          },
          icon: { left: iconRect.left, right: iconRect.right },
          left: stageRect.left,
          top: stageRect.top,
        };
      });
      return {
        logo: rect(".brand-logo"),
        primary: grid("dashboard-primary-grid"),
        primaryCards: [...document.querySelectorAll<HTMLElement>(".dashboard-primary-card")].map((card) => card.getBoundingClientRect().height),
        secondary: grid("dashboard-secondary-grid"),
        secondaryCards: [...document.querySelectorAll<HTMLElement>(".dashboard-secondary-card")].map((card) => card.getBoundingClientRect().height),
        stages,
        systemHealth: rect(".system-health-bar"),
        titleFontSize: Number.parseFloat(getComputedStyle(document.querySelector<HTMLElement>(".header-title")!).fontSize),
      };
    });

    for (const grid of [geometry.primary, geometry.secondary]) {
      expect(grid.children).toHaveLength(2);
      expect(grid.gap).toBeCloseTo(8, 0);
      const usableWidth = grid.width - grid.gap;
      expect(grid.children[0] / usableWidth).toBeGreaterThanOrEqual(0.455);
      expect(grid.children[0] / usableWidth).toBeLessThanOrEqual(0.465);
      expect(grid.children[1] / usableWidth).toBeGreaterThanOrEqual(0.535);
      expect(grid.children[1] / usableWidth).toBeLessThanOrEqual(0.545);
    }
    for (const height of geometry.primaryCards) expect(height).toBeCloseTo(310, 0);
    for (const height of geometry.secondaryCards) expect(height).toBeCloseTo(268, 0);
    expect(geometry.systemHealth.height).toBeCloseTo(88, 0);
    expect(geometry.logo.width).toBeCloseTo(108, 0);
    expect(geometry.logo.height).toBeCloseTo(108, 0);
    expect(geometry.titleFontSize).toBeCloseTo(27, 0);

    expect(geometry.stages).toHaveLength(8);
    for (const stage of geometry.stages) expect(stage.top).toBeCloseTo(geometry.stages[0].top, 0);
    for (let index = 0; index < geometry.stages.length - 1; index += 1) {
      const stage = geometry.stages[index];
      const next = geometry.stages[index + 1];
      expect(stage.connector.content).not.toBe("none");
      expect(stage.connector.display).not.toBe("none");
      expect(stage.connector.width).toBeGreaterThan(1);
      expect(stage.connector.height).toBeGreaterThanOrEqual(1);
      expect(stage.connector.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
      expect(stage.connector.left).toBeLessThanOrEqual(stage.icon.right + 1);
      expect(stage.connector.right).toBeGreaterThanOrEqual(next.icon.left - 1);
    }
  });

  test("fills three and five truthful research rows and preserves the 900px lifecycle and table", async ({ page }) => {
    await page.setViewportSize({ width: 1487, height: 1058 });
    await waitForDashboard(page);

    const threeRowGeometry = await page.locator(".recent-research-card").evaluate((card) => {
      const cardRect = card.getBoundingClientRect();
      const rows = [...card.querySelectorAll("tbody tr")];
      const lastRowRect = rows.at(-1)!.getBoundingClientRect();
      return {
        bottomGap: cardRect.bottom - lastRowRect.bottom,
        cardClientHeight: card.clientHeight,
        cardScrollHeight: card.scrollHeight,
        rowCount: rows.length,
      };
    });
    expect(threeRowGeometry.rowCount).toBe(3);
    expect(threeRowGeometry.bottomGap).toBeLessThanOrEqual(24);
    expect(threeRowGeometry.cardScrollHeight).toBeLessThanOrEqual(threeRowGeometry.cardClientHeight + 1);

    await installFiveRunList(page);
    await waitForDashboard(page);
    const fiveRowGeometry = await page.locator(".recent-research-card").evaluate((card) => {
      const cardRect = card.getBoundingClientRect();
      const tableRect = card.querySelector("table")!.getBoundingClientRect();
      const rows = [...card.querySelectorAll("tbody tr")];
      return {
        bottomGap: cardRect.bottom - tableRect.bottom,
        cardClientHeight: card.clientHeight,
        cardScrollHeight: card.scrollHeight,
        rowCount: rows.length,
        tableTop: tableRect.top,
        tableBottom: tableRect.bottom,
      };
    });
    expect(fiveRowGeometry.rowCount).toBe(5);
    expect(fiveRowGeometry.bottomGap).toBeLessThanOrEqual(24);
    expect(fiveRowGeometry.cardScrollHeight).toBeLessThanOrEqual(fiveRowGeometry.cardClientHeight + 1);
    expect(fiveRowGeometry.tableBottom).toBeGreaterThan(fiveRowGeometry.tableTop);

    await page.setViewportSize({ width: 900, height: 1000 });
    await waitForDashboard(page);
    const responsive = await page.evaluate(() => {
      const stages = [...document.querySelectorAll<HTMLElement>(".lifecycle-stage")].map((stage) => {
        const box = stage.getBoundingClientRect();
        const connector = getComputedStyle(stage, "::after");
        return { connectorDisplay: connector.display, left: box.left, top: box.top };
      });
      const scroll = document.querySelector<HTMLElement>(".recent-research-card .table-scroll")!;
      const scrollRect = scroll.getBoundingClientRect();
      const headers = [...scroll.querySelectorAll<HTMLElement>("thead th")].map((header) => ({
        height: header.getBoundingClientRect().height,
        whiteSpace: getComputedStyle(header).whiteSpace,
      }));
      scroll.scrollLeft = scroll.scrollWidth;
      return {
        headers,
        scroll: {
          clientWidth: scroll.clientWidth,
          left: scrollRect.left,
          overflowX: getComputedStyle(scroll).overflowX,
          right: scrollRect.right,
          scrollLeft: scroll.scrollLeft,
          scrollWidth: scroll.scrollWidth,
        },
        stages,
      };
    });

    const rowTops = [...new Set(responsive.stages.map((stage) => Math.round(stage.top)))];
    const columnLefts = [...new Set(responsive.stages.map((stage) => Math.round(stage.left)))];
    expect(rowTops).toHaveLength(2);
    expect(columnLefts).toHaveLength(4);
    expect(responsive.stages[3].connectorDisplay).toBe("none");
    expect(responsive.stages[0].connectorDisplay).not.toBe("none");
    expect(responsive.stages[4].connectorDisplay).not.toBe("none");
    expect(responsive.scroll.left).toBeGreaterThanOrEqual(0);
    expect(responsive.scroll.right).toBeLessThanOrEqual(901);
    expect(responsive.scroll.overflowX).toBe("auto");
    expect(responsive.scroll.scrollWidth).toBeGreaterThan(responsive.scroll.clientWidth);
    expect(responsive.scroll.scrollLeft).toBeGreaterThan(0);
    for (const header of responsive.headers) {
      expect(header.whiteSpace).toBe("nowrap");
      expect(header.height).toBeLessThanOrEqual(56);
    }
  });
});
