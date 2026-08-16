// 界面全交互走查（§23.1）：通过 UI 真实点击关键按钮，覆盖新建/运行/上传/建议/审批/采纳等
// 每步 PASS/FAIL，失败不中断。前置：后端 8000 + Vite 5173 + Celery worker。
// 用法：node scripts/ui_interactions.mjs

import { chromium } from "@playwright/test";
import { writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const BASE = "http://localhost:5173";
const EMAIL = "owner@airesearcher.local";
const PASSWORD = "demo-password";

let pass = 0;
let total = 0;
function step(name, ok, detail = "") {
  total += 1;
  if (ok) pass += 1;
  console.log(`[${ok ? "PASS" : "FAIL"}] ${name} ${detail}`);
}

async function main() {
  const browser = await chromium.launch({ channel: "chrome" });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));

  // 登录
  await page.goto(`${BASE}/login`);
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(/\/projects/, { timeout: 30000 });
  step("登录", true);

  // API 拿 pid
  const api = page.request;
  const login = await api.post(`${BASE}/api/v1/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  const token = (await login.json()).access_token;
  const h = { Authorization: `Bearer ${token}` };
  const teams = await api.get(`${BASE}/api/v1/teams`, { headers: h });
  const teamId = (await teams.json())[0].id;
  const projects = await api.get(`${BASE}/api/v1/projects?team_id=${teamId}`, { headers: h });
  const pid = (await projects.json()).find((p) => p.slug === "protein-ligand-multimodal").id;

  // 1. 项目空间：新建项目
  try {
    await page.goto(`${BASE}/projects`);
    await page.getByRole("button", { name: "新建项目" }).click();
    await page.getByPlaceholder("项目名称").fill("UI交互冒烟项目");
    await page.getByPlaceholder("slug（留空自动生成）").fill("ui-smoke-" + Date.now());
    await page.getByRole("button", { name: "创建", exact: true }).click();
    await page.getByText("UI交互冒烟项目").first().waitFor({ timeout: 10000 });
    step("项目空间：新建项目", true);
  } catch (e) { step("项目空间：新建项目", false, String(e).slice(0, 120)); }

  // 2. 文献库：异步检索 + 加入项目
  try {
    await page.goto(`${BASE}/projects/${pid}/literature`);
    await page.getByPlaceholder("检索 arXiv 文献…").fill("protein docking");
    await page.getByRole("button", { name: "检索" }).click();
    await page.getByText("加入项目").first().waitFor({ timeout: 90000 });
    const before = (await page.getByText("加入项目").count());
    await page.getByText("加入项目").first().click();
    await page.waitForTimeout(1500);
    step("文献库：检索→加入项目", before > 0);
  } catch (e) { step("文献库：检索→加入项目", false, String(e).slice(0, 120)); }

  // 3. 实验管理：新建 + 运行
  try {
    await page.goto(`${BASE}/projects/${pid}/experiments`);
    await page.getByRole("button", { name: "新建实验" }).click();
    await page.getByPlaceholder("code（如 E2）").fill("UISMK");
    await page.getByPlaceholder("实验名称").fill("UI交互实验");
    await page.getByRole("button", { name: "创建", exact: true }).click();
    await page.getByText("UI交互实验").waitFor({ timeout: 10000 });
    await page.getByRole("button", { name: "运行" }).first().click();
    await page.getByText(/succeeded|failed/).first().waitFor({ timeout: 60000 });
    step("实验管理：新建→运行", true);
  } catch (e) { step("实验管理：新建→运行", false, String(e).slice(0, 120)); }

  // 4. 数据资产：上传文件
  try {
    const dir = mkdtempSync(join(tmpdir(), "uiupload-"));
    const file = join(dir, "hello.txt");
    writeFileSync(file, "UI 交互上传内容");
    await page.goto(`${BASE}/projects/${pid}/assets`);
    await page.setInputFiles('input[type="file"]', file);
    await page.getByText("hello.txt").waitFor({ timeout: 30000 });
    step("数据资产：上传文件", true);
  } catch (e) { step("数据资产：上传文件", false, String(e).slice(0, 120)); }

  // 5. 写作中心：新建文档 + 版本 + 建议
  try {
    await page.goto(`${BASE}/projects/${pid}/writing`);
    await page.getByRole("button", { name: "新建", exact: true }).click();
    await page.getByPlaceholder("标题").fill("UI交互文档");
    await page.getByRole("button", { name: "创建", exact: true }).click();
    await page.getByText("UI交互文档").first().waitFor({ timeout: 10000 });
    await page.getByRole("button", { name: "新建版本" }).click();
    await page.getByRole("button", { name: "保存版本" }).click();
    await page.getByText(/v1/).first().waitFor({ timeout: 10000 });
    step("写作中心：新建文档+版本", true);
  } catch (e) { step("写作中心：新建文档+版本", false, String(e).slice(0, 120)); }

  // 6. 复盘洞察：生成复盘
  try {
    await page.goto(`${BASE}/projects/${pid}/reflections`);
    await page.getByRole("button", { name: "生成复盘" }).click();
    await page.getByText("目标完成率").first().waitFor({ timeout: 30000 });
    step("复盘洞察：生成复盘", true);
  } catch (e) { step("复盘洞察：生成复盘", false, String(e).slice(0, 120)); }

  // 7. 智能体中心：启动 + 运行
  try {
    await page.goto(`${BASE}/projects/${pid}/agents`);
    await page.getByRole("button", { name: "启动" }).waitFor({ timeout: 10000 });
    await page.locator("select").first().selectOption({ index: 1 });
    await page.getByRole("button", { name: "启动" }).click();
    await page.getByRole("button", { name: "运行" }).first().waitFor({ timeout: 15000 });
    await page.getByRole("button", { name: "运行" }).first().click();
    await page.getByText(/成功|等待审批|失败/).first().waitFor({ timeout: 120000 });
    step("智能体中心：启动→运行(LLM)", true);
  } catch (e) { step("智能体中心：启动→运行(LLM)", false, String(e).slice(0, 120)); }

  // 8. 审批中心：批准
  try {
    await page.goto(`${BASE}/projects/${pid}/approvals`);
    await page.getByRole("button", { name: "批准" }).first().waitFor({ timeout: 10000 });
    await page.getByRole("button", { name: "批准" }).first().click();
    await page.waitForTimeout(1500);
    step("审批中心：批准", true);
  } catch (e) { step("审批中心：批准", false, String(e).slice(0, 120)); }

  // 9. 研究总览：采纳选题
  try {
    await page.goto(`${BASE}/projects/${pid}/overview`);
    await page.getByRole("button", { name: "采纳" }).first().waitFor({ timeout: 15000 });
    await page.getByRole("button", { name: "采纳" }).first().click();
    await page.waitForTimeout(1500);
    step("研究总览：采纳选题", true);
  } catch (e) { step("研究总览：采纳选题", false, String(e).slice(0, 120)); }

  // 全程控制台错误汇总
  const realErrors = errors.filter((e) => !e.includes("favicon") && !e.includes("404"));
  step("全程无控制台错误", realErrors.length === 0, realErrors.slice(0, 3).join(" | "));

  console.log(`\n界面全交互：${pass}/${total} 通过`);
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
