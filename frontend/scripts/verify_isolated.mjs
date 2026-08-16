// 隔离验证 2 个之前在大脚本里因状态互相干扰而超时的交互：审批「拒绝(理由)」、写作「建议生成→接受」
import { chromium } from "@playwright/test";

const BASE = "http://localhost:5173";

async function main() {
  const browser = await chromium.launch({ channel: "chrome" });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  await page.goto(`${BASE}/login`);
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(/\/projects/, { timeout: 30000 });

  const api = page.request;
  const login = await api.post(`${BASE}/api/v1/auth/login`, { data: { email: "owner@airesearcher.local", password: "demo-password" } });
  const token = (await login.json()).access_token;
  const h = { Authorization: `Bearer ${token}` };
  const teams = await api.get(`${BASE}/api/v1/teams`, { headers: h });
  const teamId = (await teams.json())[0].id;
  const projects = await api.get(`${BASE}/api/v1/projects?team_id=${teamId}`, { headers: h });
  const pid = (await projects.json()).find((p) => p.slug === "protein-ligand-multimodal").id;

  // 1. 审批中心：拒绝（理由）
  try {
    await page.goto(`${BASE}/projects/${pid}/approvals`);
    const rej = page.getByRole("button", { name: "拒绝", exact: true }).first();
    await rej.waitFor({ timeout: 15000 });
    await rej.click();
    await page.getByPlaceholder("拒绝理由（必填）").waitFor({ timeout: 10000 });
    await page.getByPlaceholder("拒绝理由（必填）").fill("隔离验证：拒绝理由填写正常");
    await page.getByRole("button", { name: "确认拒绝" }).click();
    await page.getByText("已拒绝").first().waitFor({ timeout: 10000 });
    console.log("[PASS] 审批：拒绝（含理由填写）");
  } catch (e) { console.log("[FAIL] 审批拒绝", String(e).slice(0, 150)); }

  // 2. 写作中心：建议生成 → 接受
  try {
    await page.goto(`${BASE}/projects/${pid}/writing`);
    await page.getByRole("button", { name: "新建", exact: true }).click();
    await page.getByPlaceholder("标题").fill("建议隔离验证");
    await page.getByRole("button", { name: "创建", exact: true }).click();
    await page.getByText("建议隔离验证").first().waitFor({ timeout: 10000 });
    await page.getByRole("button", { name: "新建版本" }).click();
    await page.getByRole("button", { name: "保存版本" }).click();
    await page.waitForTimeout(1000);
    await page.getByRole("button", { name: "写作建议" }).first().click();
    await page.getByRole("button", { name: "生成建议" }).first().click();
    await page.getByText(/pending|待处理/).first().waitFor({ timeout: 90000 });
    await page.getByRole("button", { name: "接受" }).first().click();
    await page.waitForTimeout(2000);
    console.log("[PASS] 写作：建议生成→接受");
  } catch (e) { console.log("[FAIL] 写作建议", String(e).slice(0, 150)); }

  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
