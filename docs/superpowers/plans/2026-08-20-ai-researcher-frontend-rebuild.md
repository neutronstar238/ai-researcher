# AI-Researcher Frontend Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 React 完整替换现有 Web 前端，交付一个与参考截图同构、接入现有真实 API、可测试且可由当前 aiohttp 服务托管的研究指挥中心。

**Architecture:** `frontend/` 保存 React + TypeScript 源码和测试，Vite 将固定名称的生产资源构建到 `web/`，同步脚本再更新 Python 包内静态回退。前端通过带类型的 API 客户端读取现有研究运行、阶段、产物、批量任务、健康状态和 Skill 数据；领域适配器负责把十二个后端阶段稳定映射为八个产品阶段。

**Tech Stack:** Node 22.23.2、npm 10.9.8、React 19.2.8、React Router 7.18.2、TanStack Query 5.101.4、TypeScript 7.0.2、Vite 8.2.2、Vitest 4.1.11、Testing Library、ECharts 6.1.0、Lucide React 1.33.0、Playwright 1.62.1、Python aiohttp API。

**Spec:** `docs/superpowers/specs/2026-08-20-ai-researcher-frontend-rebuild-design.md`

## Global Constraints

- 基准视口固定为 `1440 × 900`，浏览器缩放 100%。
- 桌面左栏宽 `220px`；主区按 `1220px` 基准组织。
- 旧默认前端不再作为入口；`web/legacy-dashboard/` 不被路由引用，但默认不物理删除。
- 现有 Python 科研引擎、研究数据和 API 行为保持不变；只允许为 SPA 托管做最小路由修改。
- 生产业务数据只能来自现有 API；测试固定数据仅存在于测试夹具。
- 审批和知识图谱没有后端端点时显示明确能力边界，不创建假批准、假拒绝或假图谱。
- 取消必须确认；恢复、取消、进化和创建操作等待服务端结果后才更新成功状态。
- 前端不得读取、显示或持久化 API key、环境变量和服务端私有路径。
- API 合同保持 `GET /api/health`、`GET/POST /api/runs`、`GET/POST /api/batches` 和现有 run 子资源端点。
- Vite 生产输出固定为 `web/index.html`、`web/app.js`、`web/styles.css`。
- 当前工作副本没有 `.git`。不得擅自运行 `git init`；每个任务先检查 Git，可用时按计划提交，不可用时记录文件哈希并关联 `P-20260819-060`。
- 开始实现前读取并遵循 `product-design:image-to-code`；交付前读取并遵循 `superpowers:verification-before-completion`。

---

## Planned File Map

### Build and runtime

- `frontend/package.json`：前端依赖和脚本。
- `frontend/package-lock.json`：npm 精确锁文件。
- `frontend/tsconfig.json`：TypeScript 严格配置。
- `frontend/vite.config.ts`：固定产物名、API 代理、Vitest 配置。
- `frontend/index.html`：Vite HTML 入口。
- `frontend/scripts/sync-static.mjs`：把 `web/` 生产文件同步到包内静态回退。
- `package.json`：根级 `dev`、`frontend:*` 代理脚本。

### Application foundation

- `frontend/src/main.tsx`：React 挂载和全局样式导入。
- `frontend/src/app/App.tsx`：应用 Provider 和 Router 出口。
- `frontend/src/app/router.tsx`：唯一的路由表。
- `frontend/src/app/queryClient.ts`：TanStack Query 默认策略。
- `frontend/src/test/setup.ts`：Vitest DOM、matchMedia 和 ResizeObserver 设置。
- `frontend/src/test/fixtures.ts`：完整 API 测试对象工厂。
- `frontend/src/test/render.tsx`：带 QueryClient 和内存路由的组件渲染器。

### API and domain

- `frontend/src/lib/api/types.ts`：API 请求和响应类型。
- `frontend/src/lib/api/client.ts`：fetch 封装、错误解码、所有端点函数。
- `frontend/src/lib/domain/lifecycle.ts`：十二阶段到八阶段映射。
- `frontend/src/lib/domain/selectors.ts`：当前运行、趋势和状态选择器。
- `frontend/src/lib/domain/artifacts.ts`：产物分类和页面过滤规则。

### Shell and shared UI

- `frontend/src/assets/ai-researcher-logo.png`：独立品牌图像。
- `frontend/src/components/shell/AppShell.tsx`：应用壳层。
- `frontend/src/components/shell/Sidebar.tsx`：导航和折叠。
- `frontend/src/components/shell/Header.tsx`：标题、日期和用户操作。
- `frontend/src/components/ui/AsyncState.tsx`：加载、空数据和错误状态。
- `frontend/src/components/ui/ConfirmDialog.tsx`：危险操作确认。
- `frontend/src/components/ui/Drawer.tsx`：表单和详情抽屉。
- `frontend/src/components/ui/ToastRegion.tsx`：操作反馈。
- `frontend/src/styles/tokens.css`：颜色、尺寸、字体和阴影令牌。
- `frontend/src/styles/global.css`：重置、壳层、响应式和可访问性样式。

### Features

- `frontend/src/features/dashboard/DashboardPage.tsx`：总览查询编排。
- `frontend/src/features/dashboard/LifecycleTimeline.tsx`：八阶段生命周期。
- `frontend/src/features/dashboard/CurrentProjectCard.tsx`：当前研究任务。
- `frontend/src/features/dashboard/RecentResearchCard.tsx`：近期研究表。
- `frontend/src/features/dashboard/CoverageChart.tsx`：ECharts 趋势。
- `frontend/src/features/dashboard/SystemHealthBar.tsx`：真实健康状态。
- `frontend/src/features/projects/ProjectsPage.tsx`：运行列表和筛选。
- `frontend/src/features/projects/CreateRunDrawer.tsx`：创建研究。
- `frontend/src/features/projects/RunDetailsDrawer.tsx`：详情、阶段、产物和动作。
- `frontend/src/features/batches/BatchDrawer.tsx`：批量任务表单和回执。
- `frontend/src/features/resources/ArtifactWorkspacePage.tsx`：文献、实验、数据和写作产物视图。
- `frontend/src/features/reflections/ReflectionsPage.tsx`：失败、验证和恢复视图。
- `frontend/src/features/agents/AgentsPage.tsx`：Skill 候选和进化状态。
- `frontend/src/features/capabilities/CapabilityPage.tsx`：知识图谱和审批能力边界。
- `frontend/src/features/settings/SettingsPage.tsx`：健康、主题和显示设置。

### Integration and verification

- `src/autoresearch/api/app.py`：SPA 深链接回退，API 和静态未知路径保持 404。
- `tests/unit/api/test_research_api.py`：静态构建和 SPA 路由回归。
- `frontend/playwright.config.ts`：E2E 服务配置。
- `frontend/e2e/fixtures/api-server.mjs`：隔离的确定性 API 测试夹具。
- `frontend/e2e/dashboard.spec.ts`：主流程和截图验收。
- `design-qa.md`：参考图与实现的阻断式视觉 QA 报告。
- `Agent.md`：实现和验证记录。

---

### Task 1: Establish the React build and test contract

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/scripts/sync-static.mjs`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/App.test.tsx`
- Create: `frontend/src/app/queryClient.ts`
- Create: `frontend/src/test/setup.ts`
- Modify: `package.json`
- Generate: `frontend/package-lock.json`

**Interfaces:**
- Consumes: existing root npm scripts and the static file contract `/static/app.js`, `/static/styles.css`.
- Produces: `App(): JSX.Element`, `queryClient: QueryClient`, root commands `npm run dev`, `npm run frontend:build`, `npm run frontend:test`.

- [ ] **Step 1: Create the exact frontend package manifest and root script bridge**

```json
{
  "name": "ai-researcher-frontend",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build && node scripts/sync-static.mjs",
    "test": "vitest run",
    "test:watch": "vitest",
    "e2e": "playwright test"
  },
  "dependencies": {
    "@tanstack/react-query": "5.101.4",
    "echarts": "6.1.0",
    "lucide-react": "1.33.0",
    "react": "19.2.8",
    "react-dom": "19.2.8",
    "react-router-dom": "7.18.2"
  },
  "devDependencies": {
    "@playwright/test": "1.62.1",
    "@testing-library/jest-dom": "7.0.1",
    "@testing-library/react": "16.3.2",
    "@testing-library/user-event": "14.6.5",
    "@types/node": "26.2.0",
    "@types/react": "19.2.18",
    "@types/react-dom": "19.2.4",
    "@vitejs/plugin-react": "6.1.0",
    "jsdom": "30.0.1",
    "typescript": "7.0.2",
    "vite": "8.2.2",
    "vitest": "4.1.11"
  }
}
```

Add these root scripts without changing the existing CLI scripts:

```json
"dev": "npm --prefix frontend run dev --",
"frontend:build": "npm --prefix frontend run build",
"frontend:test": "npm --prefix frontend run test",
"frontend:e2e": "npm --prefix frontend run e2e"
```

- [ ] **Step 2: Install exact dependencies and produce the lock file**

Run: `npm --prefix frontend install`

Expected: exit 0; `frontend/package-lock.json` exists; `npm --prefix frontend ls --depth=0` reports the exact versions above.

- [ ] **Step 3: Configure Vite, TypeScript, test setup, and static synchronization**

```ts
// frontend/vite.config.ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/static/",
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
    proxy: { "/api": process.env.VITE_API_PROXY ?? "http://127.0.0.1:8765" },
  },
  build: {
    outDir: "../web",
    emptyOutDir: false,
    assetsInlineLimit: 1_000_000,
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        assetFileNames: "styles.css",
      },
    },
  },
  test: { environment: "jsdom", setupFiles: "./src/test/setup.ts", globals: true },
});
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "allowImportingTsExtensions": false,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "types": ["node", "vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "vite.config.ts", "playwright.config.ts"]
}
```

```html
<!-- frontend/index.html -->
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="theme-color" content="#f5f8fc" />
    <title>研启智链 / AI-Researcher - 研究指挥中心</title>
  </head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
```

```ts
// frontend/src/test/setup.ts
import "@testing-library/jest-dom/vitest";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false, media: query, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  })),
});

class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
vi.stubGlobal("ResizeObserver", ResizeObserverStub);
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
```

```js
// frontend/scripts/sync-static.mjs
import { copyFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const source = resolve(root, "web");
const target = resolve(root, "src/autoresearch/api/static");
await mkdir(target, { recursive: true });
for (const name of ["index.html", "app.js", "styles.css"]) {
  await copyFile(resolve(source, name), resolve(target, name));
}
```

- [ ] **Step 4: Write the failing application smoke test**

```tsx
// frontend/src/app/App.test.tsx
import { render, screen } from "@testing-library/react";
import { App } from "./App";

test("renders the research command center root", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "研究总览" })).toBeInTheDocument();
});
```

- [ ] **Step 5: Run the test and verify the expected failure**

Run: `npm --prefix frontend run test -- src/app/App.test.tsx`

Expected: FAIL because `App` or the `研究总览` heading does not exist.

- [ ] **Step 6: Implement the smallest mountable app and query client**

```tsx
// frontend/src/app/App.tsx
export function App() {
  return <main><h1>研究总览</h1></main>;
}
```

```tsx
// frontend/src/main.tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
```

```ts
// frontend/src/app/queryClient.ts
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } },
});
```

- [ ] **Step 7: Verify smoke test and production artifact names**

Run: `npm --prefix frontend run test -- src/app/App.test.tsx`

Expected: PASS.

Run: `npm run frontend:build`

Expected: exit 0; the three files exist in both `web/` and `src/autoresearch/api/static/`; `web/legacy-dashboard/` still exists.

- [ ] **Step 8: Create a task checkpoint**

Run: `git rev-parse --is-inside-work-tree`

If Git is restored, run:

```powershell
git add package.json frontend web/index.html web/app.js web/styles.css src/autoresearch/api/static
git commit -m "build: establish React frontend toolchain"
```

If Git remains unavailable, run `Get-FileHash package.json,frontend/package.json,frontend/package-lock.json,web/index.html,web/app.js,web/styles.css` and retain the output for `Agent.md`; do not initialize a repository.

---

### Task 2: Add the typed API client and error contract

**Files:**
- Create: `frontend/src/lib/api/types.ts`
- Create: `frontend/src/lib/api/client.ts`
- Create: `frontend/src/lib/api/client.test.ts`
- Create: `frontend/src/test/fixtures.ts`

**Interfaces:**
- Consumes: browser `fetch` and the current `/api/*` JSON shapes.
- Produces: `apiClient`, `ApiError`, `RunRecord`, `StageRecord`, `ArtifactRecord`, `HealthResponse`, `BatchRecord`, `SkillCandidate`, `EvolutionStatus`.

- [ ] **Step 1: Define the exact public API types**

```ts
export type RunStatus = "queued" | "running" | "cancel_requested" | "canceled" | "completed" | "failed" | "interrupted" | "dry_run";
export type StageStatus = "completed" | "pending" | "invalid";

export interface StageRecord {
  ordinal: number;
  stage_name: string;
  label_zh: string;
  status: StageStatus;
  artifact_count: number;
  checkpoint_hash: string | null;
}

export interface ArtifactRecord {
  relative_path: string;
  category: string;
  bytes: number;
  sha256: string;
  media_type: string;
  url: string;
}

export interface RunRecord {
  run_id: string;
  kind: "single";
  direction: string;
  status: RunStatus;
  dry_run: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  resume_count: number;
  cancel_requested: boolean;
  error: { type: string; message: string } | null;
  result: Record<string, unknown> | null;
  delivery_validation: Record<string, unknown> | null;
  stages?: StageRecord[];
  artifacts?: ArtifactRecord[];
}

export interface RunCreateInput {
  direction: string;
  dry_run: boolean;
  preexperiment_policy?: "required" | "if_supported";
  dreaming_recall_enabled?: boolean;
}

export interface HealthResponse {
  status: "ok";
  service: string;
  deployment_scope: string;
  authentication_enabled: boolean;
  formal_experiment_enabled: boolean;
  result_paper_enabled: boolean;
  self_evolution_execution_enabled: boolean;
  self_evolution_service_configured: boolean;
  automatic_skill_activation_enabled: boolean;
  batch_execution_configured: boolean;
}

export interface BatchCreateInput {
  question_pdf: string;
  start: number;
  limit: number;
  include_question_ids: number[];
  resume: boolean;
  dry_run: boolean;
  preexperiment_policy?: "required" | "plan_only_on_unsupported";
  dreaming_recall_enabled?: boolean;
}

export interface BatchRecord {
  batch_id: string;
  status: string;
  dry_run: boolean;
  question_count: number;
  created_at: string;
  items?: unknown[];
  batch_service_configured?: boolean;
}

export interface SkillCandidate {
  candidate_skill_id: string;
  parent_skill: string | null;
  candidate_status: string;
  relative_path: string;
  promotion_authorized: false;
  promotion_boundary: string;
}

export interface EvolutionStatus {
  run_id: string;
  execution_enabled: boolean;
  mode: "frozen_service_available" | "query_only";
  selected_skills: { run_id: string; source_artifact: string | null; selection: unknown; skill_content_is_scientific_evidence: false };
  skill_candidates: SkillCandidate[];
  run_evolution_receipt: Record<string, unknown> | null;
  promotion_authorized: false;
  boundary: string;
}

export interface EvolutionReceipt {
  schema_version: string;
  run_id: string;
  status: string;
  result: Record<string, unknown>;
  promotion_authorized: false;
  created_at: string;
}

export interface SelectedSkillsResponse {
  run_id: string;
  source_artifact: string | null;
  selection: unknown;
  skill_content_is_scientific_evidence: false;
}
```

- [ ] **Step 2: Write failing tests for success and service-error decoding**

```ts
import { apiClient, ApiError } from "./client";

test("lists runs from the response envelope", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ runs: [{ run_id: "run-12345678", direction: "问题", status: "queued" }] }), { status: 200 })));
  await expect(apiClient.listRuns()).resolves.toHaveLength(1);
});

test("preserves the backend message and status", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: "service_error", message: "run cannot resume" }), { status: 409 })));
  await expect(apiClient.resumeRun("run-12345678")).rejects.toMatchObject({ status: 409, message: "run cannot resume" });
});
```

- [ ] **Step 3: Run the focused tests and verify failure**

Run: `npm --prefix frontend run test -- src/lib/api/client.test.ts`

Expected: FAIL because `apiClient` and `ApiError` are absent.

- [ ] **Step 4: Implement one request primitive and all endpoint methods**

```ts
export class ApiError extends Error {
  constructor(public readonly status: number, message: string, public readonly code = "request_failed") {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, String(payload.message ?? response.statusText), String(payload.error ?? "request_failed"));
  return payload as T;
}

export const apiClient = {
  health: () => request<HealthResponse>("/api/health"),
  listRuns: async () => (await request<{ runs: RunRecord[] }>("/api/runs")).runs,
  getRun: (id: string) => request<RunRecord>(`/api/runs/${encodeURIComponent(id)}`),
  getStages: async (id: string) => (await request<{ run_id: string; stages: StageRecord[] }>(`/api/runs/${encodeURIComponent(id)}/stages`)).stages,
  getArtifacts: async (id: string) => (await request<{ run_id: string; artifacts: ArtifactRecord[] }>(`/api/runs/${encodeURIComponent(id)}/artifacts`)).artifacts,
  selectedSkills: (id: string) => request<SelectedSkillsResponse>(`/api/runs/${encodeURIComponent(id)}/skills`),
  createRun: (input: RunCreateInput) => request<RunRecord>("/api/runs", { method: "POST", body: JSON.stringify(input) }),
  resumeRun: (id: string) => request<RunRecord>(`/api/runs/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  cancelRun: (id: string) => request<RunRecord>(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  listBatches: async () => (await request<{ batches: BatchRecord[] }>("/api/batches")).batches,
  getBatch: (id: string) => request<BatchRecord>(`/api/batches/${encodeURIComponent(id)}`),
  createBatch: (input: BatchCreateInput) => request<BatchRecord>("/api/batches", { method: "POST", body: JSON.stringify(input) }),
  skillCandidates: async () => (await request<{ candidates: SkillCandidate[] }>("/api/skills/candidates")).candidates,
  evolution: (id: string) => request<EvolutionStatus>(`/api/runs/${encodeURIComponent(id)}/evolution`),
  startEvolution: (id: string) => request<EvolutionReceipt>(`/api/runs/${encodeURIComponent(id)}/evolution`, { method: "POST" }),
};
```

- [ ] **Step 5: Add complete reusable API fixtures**

```ts
// frontend/src/test/fixtures.ts
export const BACKEND_STAGE_NAMES = [
  "broad-literature-query", "focus-selection", "targeted-literature-query",
  "planning-literature-lock", "skill-routing", "hypothesis-brainstorm",
  "provisional-plan", "real-pilot", "postpilot-objective-review",
  "final-plan-revision", "render-plan", "independent-scientific-review",
] as const;

export function stageFixtures(completed = 0): StageRecord[] {
  return BACKEND_STAGE_NAMES.map((stage_name, index) => ({
    ordinal: index + 1, stage_name, label_zh: stage_name,
    status: index < completed ? "completed" : "pending",
    artifact_count: index < completed ? 1 : 0,
    checkpoint_hash: index < completed ? String(index + 1).repeat(64).slice(0, 64) : null,
  }));
}

export function runFixture(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    run_id: "run-fixture123", kind: "single", direction: "测试研究",
    status: "completed", dry_run: false, created_at: "2026-08-20T06:00:00Z",
    started_at: "2026-08-20T06:01:00Z", finished_at: "2026-08-20T06:20:00Z",
    resume_count: 0, cancel_requested: false, error: null, result: { status: "completed" },
    delivery_validation: { status: "passed" }, stages: stageFixtures(12), artifacts: [],
    ...overrides,
  };
}

export function healthFixture(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    status: "ok", service: "autoresearch-local-api", deployment_scope: "local_single_user",
    authentication_enabled: false, formal_experiment_enabled: false,
    result_paper_enabled: false, self_evolution_execution_enabled: false,
    self_evolution_service_configured: false, automatic_skill_activation_enabled: false,
    batch_execution_configured: true, ...overrides,
  };
}

export function artifactFixtures(): ArtifactRecord[] {
  return [
    { relative_path: "literature/broad/source.json", category: "literature", bytes: 640, sha256: "a".repeat(64), media_type: "application/json", url: "/api/runs/run-fixture123/artifacts/literature/broad/source.json" },
    { relative_path: "pilot/metrics.json", category: "experiment", bytes: 512, sha256: "b".repeat(64), media_type: "application/json", url: "/api/runs/run-fixture123/artifacts/pilot/metrics.json" },
    { relative_path: "plan/research-plan.pdf", category: "plan", bytes: 4096, sha256: "c".repeat(64), media_type: "application/pdf", url: "/api/runs/run-fixture123/artifacts/plan/research-plan.pdf" },
  ];
}
```

- [ ] **Step 6: Verify all client tests and TypeScript**

Run: `npm --prefix frontend run test -- src/lib/api/client.test.ts`

Expected: PASS.

Run: `npm --prefix frontend exec tsc -- --noEmit`

Expected: exit 0.

- [ ] **Step 7: Create a task checkpoint**

If Git is available, commit with `git add frontend/src/lib/api && git commit -m "feat: add typed research API client"`. Otherwise hash the three files and retain the output for the final log.

---

### Task 3: Implement deterministic lifecycle and resource selectors

**Files:**
- Create: `frontend/src/lib/domain/lifecycle.ts`
- Create: `frontend/src/lib/domain/lifecycle.test.ts`
- Create: `frontend/src/lib/domain/selectors.ts`
- Create: `frontend/src/lib/domain/selectors.test.ts`
- Create: `frontend/src/lib/domain/artifacts.ts`
- Create: `frontend/src/lib/domain/artifacts.test.ts`

**Interfaces:**
- Consumes: `RunRecord`, `StageRecord`, `ArtifactRecord`, `EvolutionStatus`.
- Produces: `toProductLifecycle(stages, runStatus, evolution)`, `selectCurrentRun(runs)`, `coveragePercent(stages)`, `filterArtifacts(artifacts, workspace)`.

- [ ] **Step 1: Write failing lifecycle mapping tests**

```ts
test("maps twelve backend stages into eight ordered product stages", () => {
  const stages = BACKEND_STAGE_NAMES.map((stage_name, index) => ({ ordinal: index + 1, stage_name, label_zh: stage_name, status: index < 4 ? "completed" : "pending", artifact_count: 0, checkpoint_hash: null }));
  const result = toProductLifecycle(stages, "running", null);
  expect(result.map((item) => item.label)).toEqual(["选题", "文献", "假设", "实验", "验证", "写作", "复盘", "进化"]);
  expect(result[0].state).toBe("completed");
  expect(result[1].state).toBe("completed");
  expect(result[2].state).toBe("active");
});

test("marks a product stage blocked when one checkpoint is invalid", () => {
  expect(toProductLifecycle([{ ordinal: 1, stage_name: "broad-literature-query", label_zh: "检索", status: "invalid", artifact_count: 0, checkpoint_hash: null }], "failed", null)[0].state).toBe("blocked");
});
```

- [ ] **Step 2: Run selectors tests and verify failure**

Run: `npm --prefix frontend run test -- src/lib/domain`

Expected: FAIL because selectors are absent.

- [ ] **Step 3: Implement the explicit stage map and state reduction**

```ts
const PRODUCT_STAGE_GROUPS = [
  { key: "topic", label: "选题", backend: ["broad-literature-query", "focus-selection"] },
  { key: "literature", label: "文献", backend: ["targeted-literature-query", "planning-literature-lock"] },
  { key: "hypothesis", label: "假设", backend: ["skill-routing", "hypothesis-brainstorm"] },
  { key: "experiment", label: "实验", backend: ["provisional-plan", "real-pilot"] },
  { key: "validation", label: "验证", backend: ["postpilot-objective-review"] },
  { key: "writing", label: "写作", backend: ["final-plan-revision", "render-plan"] },
  { key: "reflection", label: "复盘", backend: ["independent-scientific-review"] },
  { key: "evolution", label: "进化", backend: [] },
] as const;

export type ProductStageState = "completed" | "active" | "pending" | "blocked";
export interface ProductStage { key: string; label: string; state: ProductStageState; completed: number; total: number; }

export function toProductLifecycle(stages: StageRecord[], runStatus: RunStatus, evolution: EvolutionStatus | null): ProductStage[] {
  let activeAssigned = false;
  return PRODUCT_STAGE_GROUPS.map((group) => {
    if (group.key === "evolution") {
      return { key: group.key, label: group.label, state: evolution?.run_evolution_receipt ? "completed" : "pending", completed: evolution?.run_evolution_receipt ? 1 : 0, total: 1 };
    }
    const members = group.backend.map((name) => stages.find((stage) => stage.stage_name === name)).filter((stage): stage is StageRecord => Boolean(stage));
    const completed = members.filter((stage) => stage.status === "completed").length;
    let state: ProductStageState = members.some((stage) => stage.status === "invalid") ? "blocked" : members.length === group.backend.length && completed === members.length ? "completed" : "pending";
    if (state === "pending" && !activeAssigned && ["queued", "running", "cancel_requested"].includes(runStatus)) { state = "active"; activeAssigned = true; }
    return { key: group.key, label: group.label, state, completed, total: group.backend.length };
  });
}
```

For each non-evolution group: `invalid -> blocked`, all completed -> `completed`, first unfinished group while run is queued/running/cancel_requested -> `active`, otherwise `pending`. Evolution is completed only when `run_evolution_receipt` exists, active only while a start-evolution mutation is pending, otherwise pending.

- [ ] **Step 4: Implement run, coverage, and artifact selectors**

```ts
const ACTIVE = new Set(["running", "queued", "cancel_requested"]);

export function selectCurrentRun(runs: RunRecord[]) {
  return runs.find((run) => ACTIVE.has(run.status)) ?? [...runs].sort((a, b) => Date.parse(b.finished_at ?? b.created_at) - Date.parse(a.finished_at ?? a.created_at))[0] ?? null;
}

export function coveragePercent(stages: StageRecord[]) {
  return stages.length === 0 ? null : Math.round(stages.filter((stage) => stage.status === "completed").length / stages.length * 100);
}

export const WORKSPACE_CATEGORIES = {
  literature: ["literature", "source"],
  experiments: ["experiment", "pilot", "metrics"],
  assets: ["plan", "review", "internal", "evolution"],
  writing: ["plan", "review"],
} as const;

export function filterArtifacts(artifacts: ArtifactRecord[], workspace: keyof typeof WORKSPACE_CATEGORIES) {
  if (workspace === "assets") return artifacts;
  const tokens = WORKSPACE_CATEGORIES[workspace];
  return artifacts.filter((artifact) => tokens.some((token) => artifact.category.includes(token) || artifact.relative_path.toLowerCase().includes(token)));
}
```

- [ ] **Step 5: Verify selector tests**

Run: `npm --prefix frontend run test -- src/lib/domain`

Expected: PASS with tests covering active precedence, empty runs, null coverage, PDF/TeX/Markdown writing filters, and unknown category retention in the all-assets view.

- [ ] **Step 6: Create a task checkpoint**

If Git is available, commit with `git add frontend/src/lib/domain && git commit -m "feat: map research lifecycle and artifacts"`. Otherwise hash the six files.

---

### Task 4: Build the responsive application shell and route table

**Files:**
- Create: `frontend/src/assets/ai-researcher-logo.png`
- Create: `frontend/src/app/router.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/main.tsx`
- Create: `frontend/src/components/shell/AppShell.tsx`
- Create: `frontend/src/components/shell/Sidebar.tsx`
- Create: `frontend/src/components/shell/Header.tsx`
- Create: `frontend/src/components/ui/AsyncState.tsx`
- Create: `frontend/src/components/ui/Drawer.tsx`
- Create: `frontend/src/components/ui/ConfirmDialog.tsx`
- Create: `frontend/src/components/ui/ToastRegion.tsx`
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/global.css`
- Create: `frontend/src/components/shell/AppShell.test.tsx`
- Create: `frontend/src/test/render.tsx`

**Interfaces:**
- Consumes: React Router, Lucide icons, QueryClient, product routes.
- Produces: `AppShell`, `NAV_ITEMS`, `Drawer`, `ConfirmDialog`, `AsyncState`, `ToastProvider`, all route outlets.

- [ ] **Step 1: Generate and inspect the brand asset**

Use Image Gen with this exact prompt and save the accepted output as `frontend/src/assets/ai-researcher-logo.png`:

```text
Create a clean square app logo on a transparent-looking plain white background for a Chinese AI research command center. Central mark: an abstract human brain made from navy blue and teal connected nodes and curved neural pathways, with a small gold lightbulb/spark at the center and an open-book arc at the bottom. Symmetrical, institutional scientific software branding, crisp vector-like edges, no words, no letters, no watermark, palette #0B3B82 #159EAE #F4B740. Designed to remain legible at 96 by 96 pixels.
```

Inspect the generated image before use. Reject any output containing text, watermark, photographic texture, or unrelated objects.

- [ ] **Step 2: Write the failing route and shell test**

```tsx
test("navigates through all command-center sections", async () => {
  renderAppAt("/");
  expect(screen.getByRole("navigation", { name: "主导航" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("link", { name: /项目空间/ }));
  expect(await screen.findByRole("heading", { name: "项目空间" })).toBeInTheDocument();
  expect(within(screen.getByRole("navigation", { name: "主导航" })).getAllByRole("link")).toHaveLength(11);
});
```

- [ ] **Step 3: Run the shell test and verify failure**

Run: `npm --prefix frontend run test -- src/components/shell/AppShell.test.tsx`

Expected: FAIL because the shell and routes are absent.

- [ ] **Step 4: Implement the route table and provider composition**

```tsx
export const NAV_ITEMS = [
  ["/", "研究总览", LayoutDashboard],
  ["/projects", "项目空间", FolderOpen],
  ["/literature", "文献库", BookOpen],
  ["/experiments", "实验管理", FlaskConical],
  ["/assets", "数据资产", Database],
  ["/knowledge", "知识图谱", Network],
  ["/writing", "写作中心", FileText],
  ["/reflections", "复盘洞察", RefreshCcw],
  ["/agents", "智能体中心", Bot],
  ["/approvals", "审批中心", ClipboardCheck],
  ["/settings", "系统设置", Settings],
] as const;
```

Use `createBrowserRouter` with `AppShell` as the root element and one explicit child route for each item. Use temporary semantic page components with the exact route heading until feature tasks replace them.

```tsx
export const appRoutes: RouteObject[] = [{
  path: "/",
  element: <AppShell />,
  children: [
    { index: true, element: <PageHeading title="研究总览" /> },
    ...NAV_ITEMS.slice(1).map(([path, label]) => ({ path: path.slice(1), element: <PageHeading title={label} /> })),
  ],
}];

export const router = createBrowserRouter(appRoutes);
```

Create `renderAppAt(path)` in `frontend/src/test/render.tsx`. It uses `createMemoryRouter`, a fresh `QueryClient` with retries disabled, `QueryClientProvider`, and `RouterProvider`; it returns Testing Library's render result plus `{ queryClient, router }`, where `router.state.location` is available for navigation assertions.

```tsx
export function renderAppAt(path = "/") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  return {
    ...render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>),
    queryClient,
    router,
  };
}
```

- [ ] **Step 5: Implement baseline visual tokens and shell dimensions**

```css
:root {
  --sidebar-width: 220px;
  --color-brand: #0b3b82;
  --color-action: #165dff;
  --color-success: #13a88a;
  --color-warning: #f59e0b;
  --color-danger: #e11d48;
  --color-text: #1f2a44;
  --color-muted: #667085;
  --color-border: #dce3ed;
  --color-page: #f5f8fc;
  --color-surface: #ffffff;
  --radius-card: 12px;
  --shadow-card: 0 8px 24px rgb(15 45 85 / 6%);
  font-family: Inter, "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
}

.app-shell { min-height: 100vh; background: var(--color-page); }
.sidebar { position: fixed; inset: 0 auto 0 0; width: var(--sidebar-width); }
.app-main { margin-left: var(--sidebar-width); min-width: 0; }
.page-content { width: min(100%, 1220px); margin: 0 auto; padding: 28px 24px 10px; }
@media (max-width: 1279px) { .app-shell[data-sidebar="collapsed"] { --sidebar-width: 76px; } }
@media (max-width: 1023px) { .app-main { margin-left: 0; } .sidebar { transform: translateX(-100%); } }
```

- [ ] **Step 6: Implement accessible drawer, dialog, async state, and toast primitives**

`Drawer` uses `role="dialog"`, `aria-modal="true"`, a labelled heading, body scroll lock, initial focus, and Escape close. `ConfirmDialog` accepts `{ title, description, confirmLabel, danger, onConfirm }`; danger actions cannot close through backdrop. `AsyncState` accepts `{ loading, error, empty, onRetry, children }`. `ToastProvider` exposes `notify({ tone, message })` and renders an `aria-live="polite"` region.

```tsx
export interface DrawerProps { open: boolean; title: string; onClose(): void; children: ReactNode; }
export interface ConfirmDialogProps { open: boolean; title: string; description: string; confirmLabel: string; danger?: boolean; onConfirm(): void | Promise<void>; onClose(): void; }
export interface AsyncStateProps { loading: boolean; error: Error | null; empty: boolean; onRetry(): void; children: ReactNode; }

export function Drawer({ open, title, onClose, children }: DrawerProps) {
  if (!open) return null;
  return <div className="dialog-backdrop"><section role="dialog" aria-modal="true" aria-labelledby="drawer-title" className="drawer"><h2 id="drawer-title">{title}</h2><button aria-label="关闭" onClick={onClose}><X /></button>{children}</section></div>;
}
```

- [ ] **Step 7: Verify shell behavior and production build**

Run: `npm --prefix frontend run test -- src/components/shell/AppShell.test.tsx`

Expected: PASS, including active link, sidebar collapse persistence, Escape drawer close, and visible focus styles.

Run: `npm run frontend:build`

Expected: exit 0.

- [ ] **Step 8: Create a task checkpoint**

If Git is available, commit with `git add frontend/src && git commit -m "feat: build research command center shell"`. Otherwise hash the created source and logo files.

---

### Task 5: Implement the data-backed research overview dashboard

**Files:**
- Create: `frontend/src/features/dashboard/DashboardPage.tsx`
- Create: `frontend/src/features/dashboard/DashboardPage.test.tsx`
- Create: `frontend/src/features/dashboard/LifecycleTimeline.tsx`
- Create: `frontend/src/features/dashboard/CurrentProjectCard.tsx`
- Create: `frontend/src/features/dashboard/RecentResearchCard.tsx`
- Create: `frontend/src/features/dashboard/CoverageChart.tsx`
- Create: `frontend/src/features/dashboard/SystemHealthBar.tsx`
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Consumes: `apiClient`, `selectCurrentRun`, `toProductLifecycle`, `coveragePercent`, `AsyncState`.
- Produces: `DashboardPage`, `LifecycleTimeline`, `onOpenRun(runId)`, `onCreateRun()`.

- [ ] **Step 1: Write failing Dashboard tests using mocked API modules**

```tsx
test("renders backend run data without screenshot seed values", async () => {
  vi.mocked(apiClient.listRuns).mockResolvedValue([runFixture({ direction: "真实蛋白质研究", status: "running" })]);
  vi.mocked(apiClient.health).mockResolvedValue(healthFixture());
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ stages: stageFixtures(5) }));
  renderAppAt("/");
  expect(await screen.findByText("真实蛋白质研究")).toBeInTheDocument();
  expect(screen.getByText("42%")) .toBeInTheDocument();
  expect(screen.queryByText("532")).not.toBeInTheDocument();
});

test("shows an honest create state when no runs exist", async () => {
  vi.mocked(apiClient.listRuns).mockResolvedValue([]);
  renderAppAt("/");
  expect(await screen.findByRole("button", { name: "新建研究" })).toBeInTheDocument();
  expect(screen.getByText("还没有研究运行")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the Dashboard tests and verify failure**

Run: `npm --prefix frontend run test -- src/features/dashboard/DashboardPage.test.tsx`

Expected: FAIL because Dashboard components are absent.

- [ ] **Step 3: Implement query orchestration**

```tsx
const runsQuery = useQuery({ queryKey: ["runs"], queryFn: apiClient.listRuns, refetchInterval: 15_000 });
const healthQuery = useQuery({ queryKey: ["health"], queryFn: apiClient.health, refetchInterval: 30_000 });
const currentRun = selectCurrentRun(runsQuery.data ?? []);
const detailQuery = useQuery({
  queryKey: ["run", currentRun?.run_id],
  queryFn: () => apiClient.getRun(currentRun!.run_id),
  enabled: Boolean(currentRun),
  refetchInterval: currentRun && ["queued", "running", "cancel_requested"].includes(currentRun.status) ? 5_000 : false,
});
```

Do not issue a detail request when there is no run. Keep the last successful data visible during refetch.

- [ ] **Step 4: Build the screenshot-ordered Dashboard sections**

Render in this exact DOM order: page header, lifecycle, current-project/recent-research grid, coverage/capability grid, health bar. The approval card title remains `待审批`; its body reads `当前服务未提供审批队列接口` and contains no approve/reject buttons.

```tsx
return <div className="dashboard-page" data-loading={runsQuery.isPending || healthQuery.isPending}>
  <Header title="研究总览" />
  <LifecycleTimeline stages={lifecycle} />
  <div className="dashboard-grid"><CurrentProjectCard run={detail} /><RecentResearchCard runs={runs} /></div>
  <div className="dashboard-grid"><CoverageChart runs={runs} /><CapabilityCard title="待审批" message="当前服务未提供审批队列接口" /></div>
  <SystemHealthBar health={healthQuery.data} />
</div>;
```

Define `CapabilityCard` as a local presentational function in `DashboardPage.tsx` returning a titled `<section className="dashboard-card">` and the provided message; it accepts no action callback.

Use ECharts with categories derived from the last six real runs and values derived from `coveragePercent`; if fewer than two points exist, render the empty text `积累至少两个运行后显示趋势`.

- [ ] **Step 5: Add the 1440px layout CSS**

```css
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
.lifecycle-card { min-height: 174px; }
.dashboard-primary-card { min-height: 274px; }
.dashboard-secondary-card { min-height: 236px; }
.system-health-bar { min-height: 72px; }
@media (max-width: 1023px) { .dashboard-grid { grid-template-columns: 1fr; } }
```

- [ ] **Step 6: Verify Dashboard tests and no hard-coded screenshot data**

Run: `npm --prefix frontend run test -- src/features/dashboard`

Expected: PASS.

Run: `rg -n "532|128 篇|2\.1 TB|2/4 空闲" frontend/src`

Expected: no matches.

- [ ] **Step 7: Create a task checkpoint**

If Git is available, commit with `git add frontend/src/features/dashboard frontend/src/app/router.tsx frontend/src/styles/global.css && git commit -m "feat: add data-backed research overview"`. Otherwise hash the modified files.

---

### Task 6: Implement projects, run creation, details, and guarded actions

**Files:**
- Create: `frontend/src/features/projects/ProjectsPage.tsx`
- Create: `frontend/src/features/projects/ProjectsPage.test.tsx`
- Create: `frontend/src/features/projects/CreateRunDrawer.tsx`
- Create: `frontend/src/features/projects/CreateRunDrawer.test.tsx`
- Create: `frontend/src/features/projects/RunDetailsDrawer.tsx`
- Create: `frontend/src/features/projects/RunDetailsDrawer.test.tsx`
- Modify: `frontend/src/features/dashboard/DashboardPage.tsx`
- Modify: `frontend/src/app/router.tsx`

**Interfaces:**
- Consumes: `apiClient.createRun`, `getRun`, `resumeRun`, `cancelRun`, `startEvolution`, QueryClient, shared dialogs.
- Produces: `ProjectsPage`, `CreateRunDrawer`, `RunDetailsDrawer`, URL search parameter `run` for selected detail.

- [ ] **Step 1: Write failing mutation tests**

```tsx
test("creates a run and selects the server result", async () => {
  vi.mocked(apiClient.createRun).mockResolvedValue(runFixture({ run_id: "run-new12345", direction: "新问题", status: "queued" }));
  const { router } = renderAppAt("/projects");
  await userEvent.click(screen.getByRole("button", { name: "新建研究" }));
  await userEvent.type(screen.getByLabelText("科学问题"), "新问题");
  await userEvent.click(screen.getByRole("button", { name: "开始研究" }));
  expect(apiClient.createRun).toHaveBeenCalledWith({ direction: "新问题", dry_run: false });
  expect(router.state.location.search).toBe("?run=run-new12345");
});

test("requires confirmation before cancel", async () => {
  vi.mocked(apiClient.listRuns).mockResolvedValue([runFixture({ status: "running" })]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ status: "running" }));
  renderAppAt("/projects?run=run-fixture123");
  await screen.findByRole("heading", { name: "运行详情" });
  await userEvent.click(screen.getByRole("button", { name: "请求取消" }));
  expect(apiClient.cancelRun).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "确认取消" }));
  expect(apiClient.cancelRun).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 2: Run project tests and verify failure**

Run: `npm --prefix frontend run test -- src/features/projects`

Expected: FAIL because feature components are absent.

- [ ] **Step 3: Implement the project list and URL-backed selection**

`ProjectsPage` renders search, status filter, create button, batch button, and a table with direction/status/progress/created time/actions. Selection writes `?run=<encoded id>`; closing details removes only the `run` parameter.

```tsx
const [searchParams, setSearchParams] = useSearchParams();
const selectedRunId = searchParams.get("run");
function selectRun(runId: string) { setSearchParams((current) => { current.set("run", runId); return current; }); }
function closeRun() { setSearchParams((current) => { current.delete("run"); return current; }); }
```

- [ ] **Step 4: Implement create, resume, cancel, and evolution mutations**

```tsx
const createMutation = useMutation({
  mutationFn: apiClient.createRun,
  onSuccess: async (run) => {
    await queryClient.invalidateQueries({ queryKey: ["runs"] });
    notify({ tone: "success", message: "研究运行已创建" });
    navigate(`/projects?run=${encodeURIComponent(run.run_id)}`);
  },
});
```

Resume invalidates `["runs"]` and `["run", runId]`. Cancel opens a danger confirmation, then invalidates the same keys. Start evolution is shown only for completed runs and invalidates `["evolution", runId]` and `["skills"]`. Each mutation displays `ApiError.message` inline and does not clear the user's form on failure.

- [ ] **Step 5: Render twelve backend stages and public artifacts in details**

Show all stage labels, status, artifact count, and short checkpoint hash. Artifact anchors use the server-provided `url` directly with `target="_blank"` and `rel="noreferrer"`; never rebuild a path from `relative_path`.

```tsx
{run.stages?.map((stage) => <li key={stage.stage_name}><span>{stage.ordinal}. {stage.label_zh}</span><span data-status={stage.status}>{stage.status}</span><span>{stage.artifact_count} 个产物</span><code>{stage.checkpoint_hash?.slice(0, 10) ?? "无检查点"}</code></li>)}
{run.artifacts?.map((artifact) => <a key={artifact.url} href={artifact.url} target="_blank" rel="noreferrer">{artifact.relative_path}</a>)}
```

- [ ] **Step 6: Verify project tests and keyboard behavior**

Run: `npm --prefix frontend run test -- src/features/projects`

Expected: PASS for successful create, preserved input on 409, cancel confirmation, resume invalidation, evolution boundary, Escape close, and artifact URL use.

- [ ] **Step 7: Create a task checkpoint**

If Git is available, commit with `git add frontend/src/features/projects frontend/src/features/dashboard frontend/src/app/router.tsx && git commit -m "feat: add project and run workflows"`. Otherwise hash the feature files.

---

### Task 7: Add the batch workflow

**Files:**
- Create: `frontend/src/features/batches/BatchDrawer.tsx`
- Create: `frontend/src/features/batches/BatchDrawer.test.tsx`
- Modify: `frontend/src/features/projects/ProjectsPage.tsx`

**Interfaces:**
- Consumes: `apiClient.createBatch`, `apiClient.listBatches`, `BatchCreateInput`, shared drawer and toast.
- Produces: `BatchDrawer`, batch list section in `ProjectsPage`.

- [ ] **Step 1: Write failing batch form tests**

```tsx
test("submits a server-visible PDF path and keeps backend errors inline", async () => {
  vi.mocked(apiClient.createBatch).mockRejectedValue(new ApiError(409, "question_pdf must be an existing local PDF file"));
  renderAppAt("/projects");
  await userEvent.click(screen.getByRole("button", { name: "批量任务" }));
  await userEvent.type(screen.getByLabelText("服务器 PDF 路径"), "D:/missing.pdf");
  await userEvent.click(screen.getByRole("button", { name: "创建批量任务" }));
  expect(await screen.findByText("question_pdf must be an existing local PDF file")).toBeInTheDocument();
  expect(screen.getByLabelText("服务器 PDF 路径")).toHaveValue("D:/missing.pdf");
});
```

- [ ] **Step 2: Run batch tests and verify failure**

Run: `npm --prefix frontend run test -- src/features/batches/BatchDrawer.test.tsx`

Expected: FAIL because `BatchDrawer` is absent.

- [ ] **Step 3: Implement validated fields and request mapping**

Fields are `question_pdf`, `start` (1–125), `limit` (1–125), comma-separated `include_question_ids`, `dry_run`, and `resume`. Convert IDs with `split(",").map(Number).filter(Number.isInteger)` and reject values outside 1–125 before calling the API.

```ts
export function parseQuestionIds(value: string): number[] {
  if (!value.trim()) return [];
  const ids = value.split(",").map((part) => Number(part.trim()));
  if (ids.some((id) => !Number.isInteger(id) || id < 1 || id > 125)) throw new Error("题号必须是 1 到 125 的整数");
  if (new Set(ids).size !== ids.length) throw new Error("题号不能重复");
  return [...ids].sort((a, b) => a - b);
}
```

On success, invalidate `["batches"]`, render `batch_id`, `status`, `question_count`, and `created_at`, then leave the receipt visible until the user closes the drawer.

- [ ] **Step 4: Add a real batch list to ProjectsPage**

Use `useQuery({ queryKey: ["batches"], queryFn: apiClient.listBatches })`. Render a compact list beneath the run table, with an empty state if no receipts exist. Do not infer per-question completion when `items` is empty.

```tsx
const batchesQuery = useQuery({ queryKey: ["batches"], queryFn: apiClient.listBatches });
const batchRows = batchesQuery.data ?? [];
return batchRows.length === 0 ? <p>尚无批量任务</p> : <table><tbody>{batchRows.map((batch) => <tr key={batch.batch_id}><td>{batch.batch_id}</td><td>{batch.status}</td><td>{batch.question_count}</td></tr>)}</tbody></table>;
```

- [ ] **Step 5: Verify batch tests**

Run: `npm --prefix frontend run test -- src/features/batches src/features/projects`

Expected: PASS for validation, dry-run mapping, service error, success receipt, and empty list.

- [ ] **Step 6: Create a task checkpoint**

If Git is available, commit with `git add frontend/src/features/batches frontend/src/features/projects && git commit -m "feat: add batch research workflow"`. Otherwise hash the modified files.

---

### Task 8: Implement resource, reflection, agent, capability, and settings pages

**Files:**
- Create: `frontend/src/features/resources/ArtifactWorkspacePage.tsx`
- Create: `frontend/src/features/resources/ArtifactWorkspacePage.test.tsx`
- Create: `frontend/src/features/reflections/ReflectionsPage.tsx`
- Create: `frontend/src/features/reflections/ReflectionsPage.test.tsx`
- Create: `frontend/src/features/agents/AgentsPage.tsx`
- Create: `frontend/src/features/agents/AgentsPage.test.tsx`
- Create: `frontend/src/features/capabilities/CapabilityPage.tsx`
- Create: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/app/router.tsx`

**Interfaces:**
- Consumes: selected run query, artifact filters, skill candidates, evolution status, health response.
- Produces: all remaining navigation destinations with real content or explicit API capability boundaries.

- [ ] **Step 1: Write failing route-content tests**

```tsx
test.each([
  ["/literature", "文献库"],
  ["/experiments", "实验管理"],
  ["/assets", "数据资产"],
  ["/writing", "写作中心"],
])("filters artifacts for %s", async (path, heading) => {
  vi.mocked(apiClient.listRuns).mockResolvedValue([runFixture({ artifacts: artifactFixtures() })]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ artifacts: artifactFixtures() }));
  renderAppAt(path);
  expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: /下载|预览/ }).length).toBeGreaterThan(0);
});

test("does not expose fake approval actions", () => {
  renderAppAt("/approvals");
  expect(screen.getByText("当前服务未提供审批队列接口")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /批准|拒绝/ })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run feature-page tests and verify failure**

Run: `npm --prefix frontend run test -- src/features/resources src/features/reflections src/features/agents`

Expected: FAIL because pages are absent.

- [ ] **Step 3: Implement the shared artifact workspace**

`ArtifactWorkspacePage` accepts `{ workspace: "literature" | "experiments" | "assets" | "writing", title: string }`. It loads runs, allows run selection, loads the selected run detail, applies `filterArtifacts`, and renders file name, category, bytes, media type, SHA-256 prefix, and server URL. Empty filters state the exact selected domain and offer a link to project details.

```tsx
export function ArtifactWorkspacePage({ workspace, title }: ArtifactWorkspacePageProps) {
  const runs = useQuery({ queryKey: ["runs"], queryFn: apiClient.listRuns });
  const current = selectCurrentRun(runs.data ?? []);
  const detail = useQuery({ queryKey: ["run", current?.run_id], queryFn: () => apiClient.getRun(current!.run_id), enabled: Boolean(current) });
  const artifacts = filterArtifacts(detail.data?.artifacts ?? [], workspace);
  return <section><h1>{title}</h1><label>研究运行<select defaultValue={current?.run_id}>{(runs.data ?? []).map((run) => <option key={run.run_id} value={run.run_id}>{run.direction}</option>)}</select></label>{artifacts.length === 0 ? <p>{title}暂无可用产物</p> : <ul>{artifacts.map((artifact) => <li key={artifact.url}><a href={artifact.url} target="_blank" rel="noreferrer">{artifact.relative_path}</a><span>{artifact.category} · {artifact.bytes} bytes · {artifact.sha256.slice(0, 12)}</span></li>)}</ul>}</section>;
}
```

- [ ] **Step 4: Implement reflections and agents with real boundaries**

`ReflectionsPage` lists failed/interrupted runs first, displays `error.type`, `error.message`, validation status and resume action. `AgentsPage` loads `/api/skills/candidates`, displays `candidate_status`, `parent_skill`, `relative_path`, and the mandatory `promotion_authorized: false` boundary. When a completed run is selected, show its evolution status and start button only if `execution_enabled` is true.

```tsx
const reviewRuns = (runs.data ?? []).filter((run) => ["failed", "interrupted"].includes(run.status));
const candidates = useQuery({ queryKey: ["skills"], queryFn: apiClient.skillCandidates });
const canStartEvolution = selectedRun?.status === "completed" && evolution.data?.execution_enabled === true;
```

- [ ] **Step 5: Implement capability and settings pages**

`CapabilityPage` has fixed props `{ kind, title, description }`. Knowledge uses `当前服务未提供知识图谱查询接口`; approvals use `当前服务未提供审批队列接口`. Settings loads health, shows each boolean capability exactly, provides light/dark/system theme radio buttons, and stores only `ai-researcher-theme`.

```tsx
export function CapabilityPage({ kind, title, description }: CapabilityPageProps) {
  return <section data-capability={kind}><h1>{title}</h1><div role="status" className="info-banner">{description}</div></section>;
}

function setTheme(theme: "light" | "dark" | "system") {
  localStorage.setItem("ai-researcher-theme", theme);
  document.documentElement.dataset.theme = theme;
}
```

- [ ] **Step 6: Replace every temporary route component**

Route mapping must be:

```tsx
{ path: "literature", element: <ArtifactWorkspacePage workspace="literature" title="文献库" /> },
{ path: "experiments", element: <ArtifactWorkspacePage workspace="experiments" title="实验管理" /> },
{ path: "assets", element: <ArtifactWorkspacePage workspace="assets" title="数据资产" /> },
{ path: "writing", element: <ArtifactWorkspacePage workspace="writing" title="写作中心" /> },
{ path: "reflections", element: <ReflectionsPage /> },
{ path: "agents", element: <AgentsPage /> },
{ path: "knowledge", element: <CapabilityPage kind="knowledge" title="知识图谱" description="当前服务未提供知识图谱查询接口" /> },
{ path: "approvals", element: <CapabilityPage kind="approvals" title="审批中心" description="当前服务未提供审批队列接口" /> },
{ path: "settings", element: <SettingsPage /> },
```

- [ ] **Step 7: Verify all feature-page tests and route coverage**

Run: `npm --prefix frontend run test -- src/features src/components/shell`

Expected: PASS; all 11 navigation destinations have a semantic heading and no link targets `#`.

- [ ] **Step 8: Create a task checkpoint**

If Git is available, commit with `git add frontend/src/features frontend/src/app/router.tsx && git commit -m "feat: complete research command center modules"`. Otherwise hash the feature tree.

---

### Task 9: Integrate the production SPA with aiohttp safely

**Files:**
- Modify: `src/autoresearch/api/app.py`
- Modify: `tests/unit/api/test_research_api.py`
- Regenerate: `web/index.html`
- Regenerate: `web/app.js`
- Regenerate: `web/styles.css`
- Regenerate: `src/autoresearch/api/static/index.html`
- Regenerate: `src/autoresearch/api/static/app.js`
- Regenerate: `src/autoresearch/api/static/styles.css`

**Interfaces:**
- Consumes: Vite fixed production output.
- Produces: root and non-API deep links return the SPA; unknown API and unknown static assets return 404.

- [ ] **Step 1: Write failing server routing tests**

```python
async def test_frontend_spa_deep_links_and_api_404(tmp_path: Path) -> None:
    client = TestClient(TestServer(create_app(service=ResearchApiService(work_root=tmp_path))))
    await client.start_server()
    try:
        assert (await client.get("/projects")).status == 200
        assert "root" in await (await client.get("/projects")).text()
        assert (await client.get("/api/does-not-exist")).status == 404
        assert (await client.get("/static/does-not-exist.js")).status == 404
    finally:
        await client.close()
```

- [ ] **Step 2: Run the focused API test and verify failure**

Run: `python -m pytest tests/unit/api/test_research_api.py::test_frontend_spa_deep_links_and_api_404 -q`

Expected: FAIL because `/projects` has no route.

- [ ] **Step 3: Add a guarded SPA fallback after every API route**

```python
web.get("/{tail:.*}", _spa_index),
```

```python
async def _spa_index(request: web.Request) -> web.StreamResponse:
    tail = request.match_info.get("tail", "")
    if tail == "api" or tail.startswith("api/") or tail == "static" or tail.startswith("static/"):
        raise web.HTTPNotFound()
    return web.FileResponse(_STATIC_ROOT / "index.html")
```

Register the wildcard last so existing endpoints retain precedence.

- [ ] **Step 4: Build and synchronize production files**

Run: `npm run frontend:build`

Expected: exit 0. Verify matching SHA-256 pairs between `web/<name>` and `src/autoresearch/api/static/<name>` for all three files.

- [ ] **Step 5: Run API and frontend regression tests**

Run: `python -m pytest tests/unit/api/test_research_api.py -q`

Expected: all tests PASS.

Run: `npm run frontend:test`

Expected: all tests PASS.

- [ ] **Step 6: Create a task checkpoint**

If Git is available, commit with `git add src/autoresearch/api/app.py tests/unit/api/test_research_api.py web src/autoresearch/api/static && git commit -m "feat: serve the React command center"`. Otherwise hash all changed server and build files.

---

### Task 10: Add deterministic E2E coverage and interaction verification

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/fixtures/api-server.mjs`
- Create: `frontend/e2e/dashboard.spec.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

**Interfaces:**
- Consumes: Vite dev server, deterministic test API, browser routes.
- Produces: repeatable 1440 × 900 E2E tests and local screenshots.

- [ ] **Step 1: Create the isolated API fixture**

The fixture server listens on `127.0.0.1:4174`, serves only the current API paths, and stores mutations in memory for the process lifetime. Seed exactly three runs: one completed, one running, one failed; include twelve stages, public artifacts, one Skill candidate, health booleans, and no approval/knowledge endpoints. POST create returns a new queued run; cancel and resume update only the matching fixture run.

The fixture response shapes must import no production source and must include a top-of-file comment: `Browser-test fixture only; never imported by production code.`

```js
// Browser-test fixture only; never imported by production code.
import { createServer } from "node:http";

const stageNames = ["broad-literature-query", "focus-selection", "targeted-literature-query", "planning-literature-lock", "skill-routing", "hypothesis-brainstorm", "provisional-plan", "real-pilot", "postpilot-objective-review", "final-plan-revision", "render-plan", "independent-scientific-review"];
const stages = (completed) => stageNames.map((stage_name, index) => ({ ordinal: index + 1, stage_name, label_zh: stage_name, status: index < completed ? "completed" : "pending", artifact_count: index < completed ? 1 : 0, checkpoint_hash: index < completed ? "a".repeat(64) : null }));
const makeRun = (run_id, direction, status, completed, error = null) => ({ run_id, kind: "single", direction, status, dry_run: false, created_at: "2026-08-20T06:00:00Z", started_at: "2026-08-20T06:01:00Z", finished_at: status === "running" ? null : "2026-08-20T06:20:00Z", resume_count: 0, cancel_requested: false, error, result: status === "completed" ? { status: "completed" } : null, delivery_validation: status === "completed" ? { status: "passed" } : null, stages: stages(completed), artifacts: [{ relative_path: "plan/research-plan.pdf", category: "plan", bytes: 4096, sha256: "c".repeat(64), media_type: "application/pdf", url: `/api/runs/${run_id}/artifacts/plan/research-plan.pdf` }] });
const completedRun = makeRun("run-e2e-completed", "已完成的测试研究", "completed", 12);
const runningRun = makeRun("run-e2e-running", "正在执行的测试研究", "running", 5);
const failedRun = makeRun("run-e2e-failed", "失败的测试研究", "failed", 3, { type: "ResearchApiError", message: "测试科学门阻断" });
const runs = [completedRun, runningRun, failedRun];
const health = { status: "ok", service: "autoresearch-local-api", deployment_scope: "local_single_user", authentication_enabled: false, formal_experiment_enabled: false, result_paper_enabled: false, self_evolution_execution_enabled: true, self_evolution_service_configured: true, automatic_skill_activation_enabled: false, batch_execution_configured: true };
const json = (response, status, payload) => { response.writeHead(status, { "content-type": "application/json" }); response.end(JSON.stringify(payload)); };
const readJson = async (request) => { const chunks = []; for await (const chunk of request) chunks.push(chunk); return JSON.parse(Buffer.concat(chunks).toString("utf8")); };
const makeQueuedRun = (run_id, direction) => makeRun(run_id, direction, "queued", 0);

function routeRunSubresources(request, response, url, rows) {
  const match = url.pathname.match(/^\/api\/runs\/([^/]+)(?:\/(resume|cancel|evolution))?$/);
  if (!match) return json(response, 404, { error: "not_found", message: "not found" });
  const run = rows.find((item) => item.run_id === match[1]);
  if (!run) return json(response, 404, { error: "not_found", message: "run not found" });
  if (request.method === "GET" && !match[2]) return json(response, 200, run);
  if (request.method === "POST" && match[2] === "cancel") { run.status = "cancel_requested"; return json(response, 202, run); }
  if (request.method === "POST" && match[2] === "resume") { run.status = "queued"; run.resume_count += 1; return json(response, 202, run); }
  if (request.method === "GET" && match[2] === "evolution") return json(response, 200, { run_id: run.run_id, execution_enabled: true, mode: "frozen_service_available", selected_skills: { run_id: run.run_id, source_artifact: null, selection: null, skill_content_is_scientific_evidence: false }, skill_candidates: [], run_evolution_receipt: null, promotion_authorized: false, boundary: "shadow only" });
  return json(response, 404, { error: "not_found", message: "not found" });
}

createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1:4174");
  if (request.method === "GET" && url.pathname === "/api/health") return json(response, 200, health);
  if (request.method === "GET" && url.pathname === "/api/runs") return json(response, 200, { runs });
  if (request.method === "POST" && url.pathname === "/api/runs") {
    const input = await readJson(request);
    const run = makeQueuedRun(`run-e2e-${Date.now()}`, input.direction);
    runs.unshift(run);
    return json(response, 201, run);
  }
  return routeRunSubresources(request, response, url, runs);
}).listen(4174, "127.0.0.1");
```

- [ ] **Step 2: Configure Playwright services and viewport**

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://127.0.0.1:4173", viewport: { width: 1440, height: 900 }, trace: "retain-on-failure" },
  webServer: [
    { command: "node e2e/fixtures/api-server.mjs", port: 4174, reuseExistingServer: false },
    { command: "cross-env VITE_API_PROXY=http://127.0.0.1:4174 vite --host 127.0.0.1 --port 4173 --strictPort", port: 4173, reuseExistingServer: false },
  ],
});
```

Add exact dev dependency with `npm --prefix frontend install --save-dev --save-exact cross-env@10.1.0`; verify both `package.json` and `package-lock.json` record `10.1.0`.

Run: `npm --prefix frontend exec playwright install chromium`

Expected: Chromium is available to Playwright without modifying project source.

- [ ] **Step 3: Write the failing primary-flow E2E test**

```ts
test("runs the command-center primary flow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "研究总览" })).toBeVisible();
  await expect(page.getByText("正在执行的测试研究")).toBeVisible();
  await page.getByRole("link", { name: /项目空间/ }).click();
  await page.getByRole("button", { name: "新建研究" }).click();
  await page.getByLabel("科学问题").fill("浏览器端新研究");
  await page.getByRole("button", { name: "开始研究" }).click();
  await expect(page.getByText("研究运行已创建")).toBeVisible();
  await expect(page).toHaveURL(/run=run-e2e-/);
});
```

- [ ] **Step 4: Run E2E and fix only product defects it reveals**

Run: `npm run frontend:e2e`

Expected: PASS for the primary flow, deep-link refresh, all 11 navigation links, empty capability pages, cancel confirmation, batch error rendering, artifact URL, and zero page errors collected through `page.on("pageerror")`.

- [ ] **Step 5: Capture stable screenshots**

Capture:

- `frontend/test-results/dashboard-1440x900.png`
- `frontend/test-results/dashboard-1280x900.png`
- `frontend/test-results/dashboard-900x1000.png`
- `frontend/test-results/projects-run-details-1440x900.png`

The test must wait for `[data-loading="false"]` and chart animation completion before capture.

- [ ] **Step 6: Create a task checkpoint**

If Git is available, commit with `git add frontend/playwright.config.ts frontend/e2e frontend/package.json frontend/package-lock.json && git commit -m "test: cover frontend primary journeys"`. Do not stage generated Playwright traces or screenshots unless repository policy already tracks visual baselines. If Git is unavailable, hash the E2E source files.

---

### Task 11: Run blocking design QA, final verification, and project logging

**Files:**
- Create: `design-qa.md`
- Modify: frontend source files needed to fix QA findings
- Regenerate: `web/index.html`
- Regenerate: `web/app.js`
- Regenerate: `web/styles.css`
- Regenerate: package static fallback files
- Modify: `Agent.md`
- Modify: `Problem.md` only if a new defect or blocked verification exists

**Interfaces:**
- Consumes: user reference image, same-state prototype captures, all automated tests.
- Produces: `design-qa.md` with `final result: passed`, final production build, audit log.

- [ ] **Step 1: Invoke the required completion and design QA skills**

Read and follow `product-design:image-to-code` design-qa instructions and `superpowers:verification-before-completion`. Open both the user reference image and the 1440 × 900 prototype screenshot before grading.

- [ ] **Step 2: Write the first QA report with severity and evidence**

`design-qa.md` must contain:

```markdown
# Design QA

- Reference viewport: 1440 × 900
- Prototype viewport: 1440 × 900
- Reference state: research overview
- Prototype state: deterministic browser fixture overview

## Findings

| Severity | Area | Evidence | Required correction |
|---|---|---|---|

## Iteration notes

## Final result

final result: blocked
```

Populate every observed P0–P3 difference. P0–P2 findings block completion; P3 findings may remain only as explicit iteration notes.

- [ ] **Step 3: Fix P0, P1, and P2 findings and repeat capture**

For each iteration: modify only files tied to listed findings, run focused component tests, run `npm run frontend:build`, capture the same viewport and state, then update the report. Stop when no P0–P2 finding remains and set exactly `final result: passed`.

- [ ] **Step 4: Run the complete fresh verification suite**

Run in this order:

```powershell
npm run frontend:test
npm run frontend:build
npm run frontend:e2e
python -m pytest tests/unit/api/test_research_api.py -q
node --check web/app.js
rg -n "href=\"#\"|当前服务未提供.*接口.*批准|532|2\.1 TB|2/4 空闲" frontend/src web/index.html
```

Expected: test/build/E2E/API commands exit 0; JavaScript syntax check exits 0; final search returns no fake navigation, fake approval control, or screenshot seed values.

- [ ] **Step 5: Verify production static parity**

Run SHA-256 comparison for `index.html`, `app.js`, and `styles.css` between `web/` and `src/autoresearch/api/static/`.

Expected: all three pairs match exactly.

- [ ] **Step 6: Append the required Agent.md entry**

Record date/timezone, user request, every changed file group, implementation summary, exact verification commands and counts, `design-qa.md` result, problems added or updated, and follow-up. If Git is unavailable, cite `P-20260819-060` and include final file hashes.

- [ ] **Step 7: Create the final checkpoint**

Run: `git status --short`

If Git is restored, stage only files in this plan and commit:

```powershell
git add package.json frontend web src/autoresearch/api/app.py src/autoresearch/api/static tests/unit/api/test_research_api.py design-qa.md Agent.md Problem.md
git commit -m "feat: rebuild AI-Researcher command center"
```

If Git remains unavailable, do not initialize it. Report that implementation is verified but uncommitted because the provided workspace lacks `.git`.

---

## Plan Self-Review Result

- Spec coverage: all sixteen design sections map to Tasks 1–11; no uncovered requirement was found.
- Placeholder scan: no forbidden marker or vague deferred implementation phrase was found.
- Type consistency: API response types, lifecycle states, test fixture factories, route objects, query keys and mutation return types use one declared name throughout the plan.
- Scope check: the plan changes one frontend subsystem plus the minimum SPA static fallback; research algorithms, model transport and scientific gates remain outside the change set.
- Environment check: current `.git` absence is handled explicitly without creating a new repository.

## Final Acceptance Checklist

- [ ] React application is the only default frontend entry.
- [ ] 1440 × 900 overview is structurally faithful to the reference.
- [ ] All 11 navigation destinations are reachable and semantic.
- [ ] Health, runs, stages, artifacts, batches, skills, resume, cancel, and evolution use real API calls.
- [ ] Approval and knowledge pages expose no fake mutation.
- [ ] Loading, empty, error, success, blocked, and confirmation states are covered.
- [ ] Production files are synchronized to both static roots.
- [ ] Frontend unit/component tests pass.
- [ ] Playwright primary journeys pass with no page errors.
- [ ] Python API regression tests pass.
- [ ] `design-qa.md` says `final result: passed`.
- [ ] `Agent.md` contains the final evidence and Git limitation if it remains.
