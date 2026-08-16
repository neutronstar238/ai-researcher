// 界面「全按钮」走查：逐个点击每个页面的每个按钮/交互，验证可用（无报错 + 预期结果）
// 用法：node scripts/ui_all_buttons.mjs （前置：后端 8000 + Vite 5173 + Celery worker）

import { chromium } from "@playwright/test";
import { writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const BASE = "http://localhost:5173";
const EMAIL = "owner@airesearcher.local";
const PASSWORD = "demo-password";

let pass = 0, total = 0;
function step(name, ok, detail = "") {
  total += 1;
  if (ok) pass += 1;
  console.log(`[${ok ? "PASS" : "FAIL"}] ${name} ${detail}`);
}

async function main() {
  const browser = await chromium.launch({ channel: "chrome" });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));

  // 登录
  await page.goto(`${BASE}/login`);
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(/\/projects/, { timeout: 30000 });
  step("登录", true);

  // API pid
  const api = page.request;
  const login = await api.post(`${BASE}/api/v1/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  const token = (await login.json()).access_token;
  const h = { Authorization: `Bearer ${token}` };
  const teams = await api.get(`${BASE}/api/v1/teams`, { headers: h });
  const teamId = (await teams.json())[0].id;
  const projects = await api.get(`${BASE}/api/v1/projects?team_id=${teamId}`, { headers: h });
  const pid = (await projects.json()).find((p) => p.slug === "protein-ligand-multimodal").id;

  // ===== 通用：头部按钮 =====
  try {
    await page.getByRole("button", { name: "收起导航" }).click();
    await page.getByRole("button", { name: "通知" }).click();
    await page.getByRole("button", { name: "帮助" }).click();
    step("头部：收起导航/通知/帮助", true);
  } catch (e) { step("头部：收起导航/通知/帮助", false, String(e).slice(0, 100)); }

  // ===== 研究总览 Dashboard =====
  try {
    await page.goto(`${BASE}/projects/${pid}/overview`);
    await page.getByText("科研生命周期").waitFor({ timeout: 15000 });
    const before = errors.length;
    // 查看全部（发现表）
    const v = page.getByRole("button", { name: "查看全部" }).first();
    if (await v.count()) await v.click();
    // 采纳（选题候选）
    const ac = page.getByRole("button", { name: "采纳" }).first();
    if (await ac.count()) { await ac.click(); await page.waitForTimeout(1000); }
    // 待审批：批准/拒绝
    const ap = page.getByRole("button", { name: "批准" }).first();
    if (await ap.count()) { await ap.click(); await page.waitForTimeout(1000); }
    step("研究总览：查看全部/采纳/批准", errors.length === before);
  } catch (e) { step("研究总览：查看全部/采纳/批准", false, String(e).slice(0, 100)); }

  // ===== 项目空间 =====
  try {
    await page.goto(`${BASE}/projects`);
    await page.getByRole("button", { name: "新建项目" }).click();
    await page.getByRole("button", { name: "取消" }).click(); // 取消表单
    step("项目空间：新建→取消", true);
  } catch (e) { step("项目空间：新建→取消", false, String(e).slice(0, 100)); }

  // ===== 实验管理：新建→取消 + 运行 =====
  try {
    await page.goto(`${BASE}/projects/${pid}/experiments`);
    await page.getByRole("button", { name: "新建实验" }).click();
    await page.getByRole("button", { name: "取消" }).click();
    // 运行第一个实验
    await page.getByRole("button", { name: "运行" }).first().click();
    await page.getByText(/succeeded|failed/).first().waitFor({ timeout: 60000 });
    step("实验管理：新建取消+运行", true);
  } catch (e) { step("实验管理：新建取消+运行", false, String(e).slice(0, 100)); }

  // ===== 数据资产：上传 + 下载 =====
  try {
    const dir = mkdtempSync(join(tmpdir(), "uiupload-"));
    const file = join(dir, "dl.txt");
    writeFileSync(file, "download test");
    await page.goto(`${BASE}/projects/${pid}/assets`);
    await page.setInputFiles('input[type="file"]', file);
    await page.getByText("dl.txt").waitFor({ timeout: 30000 });
    // 下载：监听新标签页
    const popupPromise = ctx.waitForEvent("page", { timeout: 30000 }).catch(() => null);
    await page.getByRole("button", { name: "下载" }).first().click();
    const popup = await popupPromise;
    step("数据资产：上传+下载", Boolean(popup));
    if (popup) await popup.close();
  } catch (e) { step("数据资产：上传+下载", false, String(e).slice(0, 100)); }

  // ===== 知识图谱：选周期 + 点节点 =====
  try {
    await page.goto(`${BASE}/projects/${pid}/knowledge-graph`);
    await page.getByText("知识图谱").waitFor({ timeout: 15000 });
    const select = page.locator("select").first();
    if (await select.count()) await select.selectOption({ index: 0 });
    await page.waitForTimeout(1500);
    step("知识图谱：选周期+渲染图", true);
  } catch (e) { step("知识图谱：选周期+渲染图", false, String(e).slice(0, 100)); }

  // ===== 写作中心：完整性检查 + 导出 + 建议(生成→接受) =====
  try {
    await page.goto(`${BASE}/projects/${pid}/writing`);
    // 新建文档
    await page.getByRole("button", { name: "新建", exact: true }).click();
    await page.getByPlaceholder("标题").fill("全按钮文档");
    await page.getByRole("button", { name: "创建", exact: true }).click();
    await page.getByText("全按钮文档").first().waitFor({ timeout: 10000 });
    // 新建版本
    await page.getByRole("button", { name: "新建版本" }).click();
    await page.getByRole("button", { name: "保存版本" }).click();
    await page.waitForTimeout(1000);
    // 完整性检查
    await page.getByRole("button", { name: "完整性检查" }).click();
    await page.getByText(/完整性检查/).first().waitFor({ timeout: 10000 });
    // 导出（新标签页）
    const dlPopup = ctx.waitForEvent("page", { timeout: 60000 }).catch(() => null);
    await page.getByRole("button", { name: "导出" }).first().click();
    const dl = await dlPopup;
    if (dl) await dl.close();
    step("写作中心：检查+导出", Boolean(dl));
    // 写作建议：生成 → 接受
    await page.getByRole("button", { name: "写作建议" }).first().click();
    await page.getByRole("button", { name: "生成建议" }).first().click();
    await page.getByText(/pending|待处理/).first().waitFor({ timeout: 60000 }).catch(() => {});
    await page.getByRole("button", { name: "接受" }).first().click();
    await page.waitForTimeout(2000);
    step("写作中心：建议生成→接受", true);
  } catch (e) { step("写作中心：检查/导出/建议", false, String(e).slice(0, 100)); }

  // ===== 复盘洞察：生成复盘 + 采纳为行动 =====
  try {
    await page.goto(`${BASE}/projects/${pid}/reflections`);
    await page.getByRole("button", { name: "生成复盘" }).click();
    await page.getByText("目标完成率").first().waitFor({ timeout: 30000 });
    const acc = page.getByRole("button", { name: "采纳为行动" }).first();
    if (await acc.count()) { await acc.click(); await page.waitForTimeout(1000); }
    step("复盘洞察：生成+采纳为行动", true);
  } catch (e) { step("复盘洞察：生成+采纳为行动", false, String(e).slice(0, 100)); }

  // ===== 智能体中心：启动 + 运行 + 取消/重试 =====
  try {
    await page.goto(`${BASE}/projects/${pid}/agents`);
    await page.locator("select").first().selectOption({ index: 1 });
    await page.getByRole("button", { name: "启动" }).click();
    await page.getByRole("button", { name: "运行" }).first().waitFor({ timeout: 15000 });
    await page.getByRole("button", { name: "运行" }).first().click();
    await page.getByText(/成功|等待审批|失败/).first().waitFor({ timeout: 120000 });
    step("智能体中心：启动+运行", true);
  } catch (e) { step("智能体中心：启动+运行", false, String(e).slice(0, 100)); }

  // ===== 审批中心：筛选 + 批准 + 拒绝(理由) =====
  try {
    await page.goto(`${BASE}/projects/${pid}/approvals`);
    for (const label of ["已批准", "已拒绝", "全部", "待审批"]) {
      const b = page.getByRole("button", { name: label, exact: false }).first();
      if (await b.count()) { await b.click(); await page.waitForTimeout(500); }
    }
    // 拒绝（有理由）
    const rej = page.getByRole("button", { name: "拒绝" }).first();
    if (await rej.count()) {
      await rej.click();
      await page.getByPlaceholder("拒绝理由（必填）").fill("UI 全按钮冒烟拒绝");
      await page.getByRole("button", { name: "确认拒绝" }).click();
      await page.waitForTimeout(1000);
    } else {
      const ap = page.getByRole("button", { name: "批准" }).first();
      if (await ap.count()) await ap.click();
    }
    step("审批中心：筛选+批准/拒绝", true);
  } catch (e) { step("审批中心：筛选+批准/拒绝", false, String(e).slice(0, 100)); }

  // ===== 系统设置 =====
  try {
    await page.goto(`${BASE}/settings`);
    await page.waitForLoadState("domcontentloaded");
    await page.getByRole("heading", { name: "系统设置" }).waitFor({ timeout: 15000 });
    step("系统设置：渲染", true);
  } catch (e) { step("系统设置：渲染", false, String(e).slice(0, 120)); }

  // ===== 退出登录 =====
  try {
    await page.goto(`${BASE}/settings`);
    await page.evaluate(() => window.dispatchEvent(new Event("ar:session-expired")));
    await page.waitForTimeout(500);
    step("退出（会话过期事件）", true);
  } catch (e) { step("退出（会话过期事件）", false, String(e).slice(0, 100)); }

  const realErrors = errors.filter((e) => !e.includes("favicon"));
  step("全程无控制台错误", realErrors.length === 0, realErrors.slice(0, 3).join(" | "));

  console.log(`\n界面全按钮走查：${pass}/${total} 通过`);
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
