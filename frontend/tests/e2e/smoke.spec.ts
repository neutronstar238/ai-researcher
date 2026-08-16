import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * 两条基准页的 E2E 冒烟 + 视觉回归基线（spec §22.3）：
 *  - Dashboard（两列，1440×900）
 *  - Evidence Workspace（三栏 260/860/320）
 * 固定 seed 数据（owner@airesearcher.local / demo-password，项目 protein-ligand-multimodal）。
 */

const EMAIL = "owner@airesearcher.local";
const PASSWORD = "demo-password";
const PROJECT_SLUG = "protein-ligand-multimodal";

async function loginViaUi(page: Page): Promise<void> {
  await page.goto("/login");
  // 登录页已预填邮箱/密码；直接提交。
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(/\/projects(\/|$)/, { timeout: 30_000 });
}

async function resolveProjectAndCycle(request: APIRequestContext): Promise<{ projectId: string; cycleId: string }> {
  const login = await request.post("/api/v1/auth/login", {
    data: { email: EMAIL, password: PASSWORD },
  });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token as string;

  const teams = await request.get("/api/v1/teams", { headers: { Authorization: `Bearer ${token}` } });
  const teamId = (await teams.json())[0].id as string;
  const projects = await request.get(`/api/v1/projects?team_id=${teamId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const project = (await projects.json()).find((p: { slug: string }) => p.slug === PROJECT_SLUG);
  const projectId = project.id as string;
  const cycles = await request.get(`/api/v1/projects/${projectId}/cycles`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const cycleId = (await cycles.json()).at(-1).id as string;
  return { projectId, cycleId };
}

test("dashboard 1440×900 visual baseline", async ({ page }) => {
  await loginViaUi(page);

  // 项目卡片 → 研究总览
  const card = page.locator("button", { hasText: PROJECT_SLUG }).first();
  await card.click();
  await page.waitForURL(/\/projects\/[0-9a-f-]+\/overview/);

  await expect(page.getByRole("heading", { name: "科研生命周期" })).toBeVisible();
  await expect(page.getByText("当前项目")).toBeVisible();

  await expect(page).toHaveScreenshot("dashboard-1440x900.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.01,
  });
});

test("evidence workspace 1440×900 visual baseline", async ({ page, request }) => {
  await loginViaUi(page);
  const { projectId, cycleId } = await resolveProjectAndCycle(request);

  await page.goto(`/projects/${projectId}/cycles/${cycleId}/evidence`);
  await expect(page.getByText("科研证据链").first()).toBeVisible({ timeout: 30_000 });

  await expect(page).toHaveScreenshot("evidence-workspace-1440x900.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.01,
  });
});
