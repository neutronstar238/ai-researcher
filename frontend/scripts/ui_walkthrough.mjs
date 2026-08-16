// 界面全链路走查（§23.1）：登录 → 遍历 11 个页面 → 检查关键内容渲染 + 控制台错误 + 关键交互
// 用法：node scripts/ui_walkthrough.mjs  （前置：后端 8000 + Vite 5173）

import { chromium } from "@playwright/test";

const BASE = "http://localhost:5173";
const EMAIL = "owner@airesearcher.local";
const PASSWORD = "demo-password";

const PAGES = [
  { path: (pid) => `/projects/${pid}/overview`, label: "研究总览", key: "科研生命周期" },
  { path: () => `/projects`, label: "项目空间", key: "项目空间" },
  { path: (pid) => `/projects/${pid}/literature`, label: "文献库", key: "文献检索" },
  { path: (pid) => `/projects/${pid}/experiments`, label: "实验管理", key: "实验管理" },
  { path: (pid) => `/projects/${pid}/assets`, label: "数据资产", key: "数据资产" },
  { path: (pid) => `/projects/${pid}/knowledge-graph`, label: "知识图谱", key: "知识图谱" },
  { path: (pid) => `/projects/${pid}/writing`, label: "写作中心", key: "文档" },
  { path: (pid) => `/projects/${pid}/reflections`, label: "复盘洞察", key: "复盘洞察" },
  { path: (pid) => `/projects/${pid}/agents`, label: "智能体中心", key: "智能体中心" },
  { path: (pid) => `/projects/${pid}/approvals`, label: "审批中心", key: "审批中心" },
  { path: () => `/settings`, label: "系统设置", key: "系统设置" },
];

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
  console.log("[PASS] 登录 → 项目空间");

  // 用 API 拿项目 id
  const api = page.request;
  const login = await api.post(`${BASE}/api/v1/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  const token = (await login.json()).access_token;
  const teams = await api.get(`${BASE}/api/v1/teams`, { headers: { Authorization: `Bearer ${token}` } });
  const teamId = (await teams.json())[0].id;
  const projects = await api.get(`${BASE}/api/v1/projects?team_id=${teamId}`, { headers: { Authorization: `Bearer ${token}` } });
  const pid = (await projects.json()).find((p) => p.slug === "protein-ligand-multimodal").id;

  let pass = 1;
  for (const p of PAGES) {
    const errStart = errors.length;
    let ok = true;
    let detail = "";
    try {
      await page.goto(`${BASE}${p.path(pid)}`);
      await page.getByText(p.key, { exact: false }).first().waitFor({ state: "visible", timeout: 15000 });
    } catch {
      ok = false;
      detail = "关键内容未渲染";
    }
    const newErrs = errors.slice(errStart);
    if (newErrs.length) {
      ok = false;
      detail += (detail ? " | " : "") + "控制台错误: " + newErrs.join("; ").slice(0, 250);
    }
    if (ok) pass += 1;
    console.log(`[${ok ? "PASS" : "FAIL"}] ${p.label} ${detail}`);
  }

  // 关键交互：文献检索（异步）→ 结果渲染
  try {
    await page.goto(`${BASE}/projects/${pid}/literature`);
    await page.getByPlaceholder("检索 arXiv 文献…").fill("graph neural network");
    await page.getByRole("button", { name: "检索" }).click();
    await page.getByText("异步检索 Job 运行中", { exact: false }).first().waitFor({ timeout: 10000 }).catch(() => {});
    await page.getByText("加入项目", { exact: false }).first().waitFor({ timeout: 60000 });
    console.log("[PASS] 文献异步检索 → 结果渲染");
    pass += 1;
  } catch {
    console.log("[FAIL] 文献异步检索交互");
  }

  console.log(`\n界面走查：${pass}/${PAGES.length + 2} 项通过`);
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
