# AI-Researcher 架构说明

> 依据 `AI-Researcher_Platform_Engineering_Specification.md`（spec）。本文记录**当前已实现**的架构，未实现部分见 [status.md](status.md)。

## 运行时拓扑

```text
Browser (React 18 + TS + Vite)
  └─ /api/*, /health/* → FastAPI (模块化单体)
       ├─ PostgreSQL  权威业务状态（Alembic 迁移，8 张核心域表 + outbox）
       ├─ Redis       缓存/未来 Broker（当前仅健康探测）
       ├─ MinIO       二进制对象（签名上传/下载，服务端 SHA-256）
       ├─ Neo4j       证据图投影（Outbox dispatcher 同步）
       └─ Milvus      向量索引（chunk embedding）
```

## 技术栈（已落地）

- **前端**：React 18 + TypeScript 5 + Vite；TanStack Query 5、Zustand、React Router 6、Tailwind + CSS 变量（§4.2 令牌）、ECharts 5、React Flow 12（@xyflow/react 12.3.5）、lucide-react。
- **后端**：Python 3.11（spec 要求 3.12，本机 3.11 兼容）、FastAPI、Pydantic 2、SQLAlchemy 2（async）、Alembic、PyJWT + Argon2id、httpx、boto3、neo4j、pymilvus 2.5。
- **数据**：PostgreSQL 16、Redis 7、MinIO、Neo4j 5、Milvus 2.5（Docker Compose）。

## 模块地图（spec §10.1）

| 域 | 已实现 | 关键文件 |
|---|---|---|
| 认证 | JWT access + 旋转 refresh、Argon2id、family 重放撤销 | `domains/auth` |
| 团队/项目/周期 | CRUD + RBAC（§1.2 矩阵）、周期 → 8 阶段初始化 | `domains/teams`, `domains/projects` |
| 生命周期 | 8 阶段状态机 + 退出门禁 + 转换事件审计 | `domains/lifecycle`, `core/lifecycle.py` |
| Dashboard | 聚合（项目/统计/生命周期/下一步）+ 审批/候选/覆盖趋势 | `domains/projects/dashboard.py` |
| 审批 | 列表/批准/拒绝（拒绝必填原因，重复决定 409） | `domains/approvals` |
| 证据图 | 节点/边 CRUD + 关系矩阵 + 矛盾投影 + Outbox | `domains/evidence`, `core/evidence.py` |
| 文献 | arXiv 真实检索 + 项目论文保存/列表/去重 | `domains/literature`, `integrations/literature` |
| 资产 | MinIO 签名上传 + 服务端 SHA-256 | `domains/assets`, `integrations/object_storage` |
| 向量 | embedding + Milvus 存储/检索（project 过滤） | `domains/vector`, `integrations/vector_store`, `integrations/embeddings` |
| 图投影 | Neo4j 客户端 + Outbox dispatcher + 重建命令 | `integrations/graph`, `workers/dispatcher.py` |

## 一致性（§3.4）

证据节点/边的写操作与 `outbox_events` 同事务提交；`python -m app.workers.dispatcher --dispatch` 幂等投影到 Neo4j，`--rebuild <project_id>` 全量重建。Neo4j/Milvus 失败不回滚已提交业务事实。

## 启动（本地开发）

```bash
cp .env.example .env            # 本机 5432/6379 被占，.env 已映射 5433/6380
docker compose up -d postgres redis neo4j minio etcd milvus
cd backend && python -m venv .venv && pip install -r requirements.txt
alembic upgrade head && python -m app.seed --profile demo
uvicorn app.main:app --reload --port 8000
cd ../frontend && npm install && npm run dev   # http://localhost:5173
```

登录（seed）：`owner@airesearcher.local / demo-password`。
