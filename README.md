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

## 快速开始

```bash
cp .env.example .env          # 填入真实密钥
docker compose up -d postgres redis minio neo4j etcd milvus
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
alembic upgrade head          # 迁移（Phase 0 已含 users 表）
cd ../frontend && npm install && npm run dev
```

API 文档：<http://127.0.0.1:8000/api/docs>；健康检查：`/health/live`、`/health/ready`。

## 开发阶段（spec §24）

> 完整实现状态见 [docs/status.md](docs/status.md)；架构见 [docs/architecture.md](docs/architecture.md)；API 见 [docs/api.md](docs/api.md)；安全见 [docs/security.md](docs/security.md)；备份恢复见 [docs/runbook-backup-restore.md](docs/runbook-backup-restore.md)；性能基线见 [docs/performance-baseline.md](docs/performance-baseline.md)；§23 验收清单见 [docs/acceptance.md](docs/acceptance.md)。

| Phase | 内容 | 状态 |
|---|---|---|
| 0 | 工程基线：Monorepo / Compose / 健康检查 / 迁移 | 完成 |
| 1 | 身份、团队、项目与 UI Shell | 完成 |
| 2 | Dashboard 与生命周期状态机 | 完成 |
| 3 | 文献、资产与 Evidence Graph | 完成（证据图/React Flow/Neo4j 投影/文献检索/资产 MinIO/向量 Milvus） |
| 4 | 实验系统 | 主线完成（实验定义/运行状态机/子进程执行/Celery 就绪/数据集版本/指标/复现清单完成；隔离容器 Runner、实时日志流待做） |
| 5 | Agent 系统 | 主线完成（Agent 定义/版本、任务生命周期、工具风险分级+审批门禁、预算纯函数、Memory 检索完成；真实 LLM 编排/Orchestrator DAG 待做） |
| 6 | 写作、复盘与导出 | 主线完成（文档/版本（不可变+SHA256）/主张↔证据/引用/完整性检查/复盘/建议采纳/`document_suggestions`(Agent Diff)/Markdown 导出完成；LaTeX/PDF 导出待做） |
| 7 | 加固与发布 | 进行中（安全头/限流/懒加载/审计日志/CI 配置完成；E2E/visual、OTel、隔离 Runner 待做） |

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
