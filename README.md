# AI-Researcher 自动科研平台

从零实现的可运行自动科研平台。本仓库遵循
`AI-Researcher_Platform_Engineering_Specification.md`，采用前后端分离：

- **前端**：React 18 + TypeScript 5 + Vite + TanStack Query + Zustand + Tailwind CSS + ECharts + React Flow（见 `frontend/`）
- **后端**：Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic + Celery（见 `backend/`）
- **数据**：PostgreSQL（权威事实源）、Redis、MinIO、Neo4j（图投影）、Milvus（向量索引）

> 原则：每一个数字都有查询来源、每一个状态都有状态机、每一个按钮都有权限/接口/结果。禁止静态 HTML、前端 Mock、假成功接口。

## 前置条件

- Docker 24+ / Docker Compose v2
- Node.js 20+、npm 10+
- Python 3.12

## 快速开始（本地开发）

```bash
cp .env.example .env          # 填入真实密钥
docker compose up -d postgres redis minio neo4j etcd milvus
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
alembic upgrade head && python -m app.seed --profile demo
cd ../frontend && npm install && npm run dev
```

## 一键部署（Docker）

```bash
cp .env.example .env
docker compose up -d --build   # 全栈（含 API + 前端 nginx）
```

登录 `owner@airesearcher.local / demo-password`。详见 [docs/deployment.md](docs/deployment.md)。

API 文档：<http://127.0.0.1:8000/api/docs>；健康检查：`/health/live`、`/health/ready`。

## 文献源（6 个）

文献检索支持 6 个真实来源，检索页下拉可单选，也可选「全部（自动）」并发聚合：

| 源 | 需 Key | `.env` 配置 |
|---|---|---|
| arXiv | 否 | — |
| OpenAlex | 否（mailto polite pool） | `LITERATURE_OPENALEX_API_KEY`（可选） |
| Crossref | 否（mailto polite pool） | `LITERATURE_CROSSREF_API_KEY`（可选） |
| PubMed | 是（NCBI E-utilities） | `LITERATURE_PUBMED_API_KEY` |
| Semantic Scholar | 是（Academic Graph API） | `LITERATURE_SEMANTIC_SCHOLAR_API_KEY` |
| Any-research（AnySearch 学术域） | 是 | `LITERATURE_ANYRESEARCH_API_KEY` |

- PubMed 仅在**医药相关问题**时生效（领域门控，非医药问题自动跳过并提示）。
- Semantic Scholar 遵守官方 1 req/s 限流 + 429 指数退避重试。
- OpenAlex/Crossref 的 polite pool 邮箱用 `LITERATURE_MAILTO`。

## 开发阶段（spec §24）

> 完整实现状态见 [docs/status.md](docs/status.md)；架构见 [docs/architecture.md](docs/architecture.md)；API 见 [docs/api.md](docs/api.md)；安全见 [docs/security.md](docs/security.md)；备份恢复见 [docs/runbook-backup-restore.md](docs/runbook-backup-restore.md)；性能基线见 [docs/performance-baseline.md](docs/performance-baseline.md)；§23 验收清单见 [docs/acceptance.md](docs/acceptance.md)。

| Phase | 内容 | 状态 |
|---|---|---|
| 0 | 工程基线：Monorepo / Compose / 健康检查 / 迁移 | 完成 |
| 1 | 身份、团队、项目与 UI Shell | 完成 |
| 2 | Dashboard 与生命周期状态机 | 完成 |
| 3 | 文献、资产与 Evidence Graph | 完成（6 文献源异步 202+Job / PDF 解析/OCR/嵌入 / 证据图 / React Flow / Neo4j / 资产 MinIO / Milvus） |
| 4 | 实验系统 | 完成（状态机 / 隔离容器 Runner / 实时日志流 WebSocket / 指标 / 产物 / 复现 + 代码/镜像 Hash） |
| 5 | Agent 系统 | 完成（任务生命周期 / 工具风险分级+审批门禁 / 预算 / Memory / 真实 LLM 编排 + Orchestrator DAG） |
| 6 | 写作、复盘与导出 | 完成（文档版本不可变 / 主张↔证据 / 引用 / 完整性检查 / 复盘 / 建议 Agent Diff / Markdown+LaTeX+DOCX+PDF 导出） |
| 7 | 加固与发布 | 完成（安全头 / 限流 / 懒加载 / 审计日志 / HttpOnly Cookie+CSRF / 恶意扫描 / 指标+Trace / WebSocket / E2E+视觉回归 / 性能基线 / 备份 runbook / CI 配置） |

## 目录结构

```
ai-researcher/
  frontend/   React 前端
  backend/    FastAPI 后端 + Celery Worker
  infra/      compose/nginx/observability
  docs/       架构、API、安全、Runbook
  scripts/    辅助脚本
  docker-compose.yml
  .env.example
  Makefile
```

## 测试 / 质量

```bash
cd backend && pip install -r requirements-dev.txt && ruff check app tests && mypy app && pytest -q
cd frontend && npm run test && npm run build && npm run test:e2e   # e2e 需后端 8000 + Vite 5173 运行
```

CI：`.github/workflows/ci.yml`（push/PR 自动跑 lint/typecheck/单元/集成 + 前端构建）。

详见 `docs/` 与规格文档第 22–23 节验收标准。
