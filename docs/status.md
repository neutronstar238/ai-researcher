# AI-Researcher 实现状态与遗留清单

> 依据 `AI-Researcher_Platform_Engineering_Specification.md`（spec v1.0）。本文件如实记录当前完成度，不把未实现项伪装为完成（spec §23.4）。

## 一、总体结论

**Phase 0–3 完整、Phase 4–6 主线完整（各留需外部依赖的尾巴）、Phase 7 完成大半。** 当前交付物是一个可运行、可演示的单团队科研平台骨架：身份/RBAC、项目/周期、8 阶段生命周期状态机、Dashboard、审批、证据图（含 Neo4j 投影）、文献检索、资产上传、向量索引均已接真实 PostgreSQL/Neo4j/MinIO/Milvus/Redis，前端为 React+TS+Vite 双 Shell。**尚未达到 spec §23 的完整验收标准**（隔离容器 Runner、真实 LLM 编排、PDF/LaTeX 导出、E2E/visual/CI、OTel 指标/Trace 均缺）。

## 二、已完成（Phase 0–3）

| 域 | 内容 | 验证 |
|---|---|---|
| 工程基线 | Monorepo、Compose（6 容器）、FastAPI、健康检查、Alembic、错误信封、结构化日志 | ✅ 迁移 0001–0007、`/health/live|ready` |
| 身份/RBAC | JWT 旋转、Argon2id、§1.2 权限矩阵、团队/项目/周期 CRUD | ✅ 集成测试（guest 写 403） |
| 生命周期 | 8 阶段状态机 + 门禁 + 转换事件 | ✅ 非法转换 409、门禁失败 422 |
| Dashboard | 聚合 + 生命周期时间线 + 六卡片接真实 API | ✅ 前端 build + OCR 渲染验证 |
| 审批 | 列表/批准/拒绝 | ✅ 集成测试 |
| 证据图 | 节点/边/关系矩阵/矛盾 + React Flow 工作台 + Neo4j 投影 | ✅ 47+ 测试、Neo4j cypher 验证 |
| 文献 | arXiv 真实检索 + 论文保存/列表 + 统计 | ✅ 真实 arXiv 200 返回 |
| 资产 | MinIO 签名上传 + 服务端 SHA-256 | ✅ E2E 上传/下载 |
| 向量 | hash-dev embedding + Milvus 存储/检索（project 过滤） | ✅ store/search 集成测试 |

**测试**：后端 73 单元 + 36 集成（真实 PG/Neo4j/MinIO/Milvus/Redis，全量 **109 passed + 2 skipped**，exit 0）全过；`ruff check app tests` 通过；前端 2 组件测试 + `tsc && vite build` 通过 + Playwright E2E 2 passed。

## 三、未完成（Phase 4–7）与遗留

### Phase 4 — 实验系统（进行中）
- ✅ 实验定义 CRUD + 运行状态机（queued→running→succeeded/failed/cancelled）+ 真实子进程执行（exit code/日志捕获/60s 超时/结构化错误）+ seed 实验 E1。
- ✅ 代码/模型 Hash 绑定（§15.5 复现）：本地入口 SHA-256 → `code_sha256`、容器镜像 digest → `image_digest`，纳入复现清单。
- ✅ Celery 应用 + `experiment.run`/`outbox.dispatch` 任务（broker=Redis，已验证：worker 真实消费 `outbox.dispatch` 返回 12）。
- ✅ `datasets` + `dataset_versions`（版本不可变、manifest_sha256 唯一）+ `experiment_metrics`（记录/列表）+ 复现清单端点（§15.5：run/experiment/参数/种子/指标/产物哈希/数据集 manifest）。
- ✅ `experiment_run_datasets`（run↔dataset version 绑定，mount_path 唯一）+ `experiment_artifacts`（run↔asset 绑定）。
- ⏳ `create_run` 尚未接入 Celery（TestClient 下 kombu `.delay()` 与异步事件循环存在 Windows 交互问题；celery broker 用 `127.0.0.1` 而非 `localhost` 修复了 IPv6 挂起）。
- ✅ 隔离容器 Runner（§15.3）：`integrations/execution/container_runner.py`（Docker `--network=none`/内存/CPU/no-new-privileges/非 root）；实验配置 `container_image` 时走容器执行，否则本地子进程 dev 回退；直播 alpine 冒烟 succeeded。
- ✅ 实时日志流（§15）：`_run_local_streaming` 逐行读 stdout 并经 WebSocket 推送 `log` 事件（`GET /api/v1/ws/projects/{id}/jobs`）；直播冒烟收到 line1/line2/line3。

### Phase 5 — Agent 系统（进行中）
- ✅ `agent_definitions`/`agent_versions`/`agent_tasks`/`agent_task_steps`/`agent_tool_calls`/`agent_memories` 模型 + 迁移 0011。
- ✅ 工具注册表 + 风险分级（read/write_low/write_high/external_side_effect）+ 审批门禁（高风险工具 → 创建 Approval + waiting_approval）+ 预算纯函数（80% 告警 / 100% 终止）。
- ✅ 任务状态机 + create/cancel/retry + 工具调用审计（记录风险等级与审批关联）+ LLM Provider 抽象（未配置 → `PROVIDER_NOT_CONFIGURED`）。
- ✅ Agent Memory：写入（embedding 入库 Milvus `agent_memories` collection）+ 语义检索（project+agent 过滤）+ 列表/删除。
- ✅ seed 6 个 Agent（§16.1）。
- ✅ 真实 LLM 编排（§16）：`integrations/llm/openai_compatible.py`（provider-agnostic：base_url/api_key/model 从配置读，OpenAI/DeepSeek/DashScope/Ollama/vLLM 兼容）+ `AgentService.run_task`（单轮真实 LLM 调用 → output/token_usage，`POST /agent-tasks/{id}:run`）+ 单元测试 6 项 + 直播冒烟（DashScope `qwen3.7-max` succeeded，真实 token usage）。
- ✅ Agent Orchestrator DAG（§16 多轮工具调用回环）：LLM 决策循环（tool_call/done）+ 工具真实执行（`project.read` 读项目、`evidence.propose` 写草稿证据节点）+ 高风险工具（`evidence.write`）→ 审批门禁暂停 + 预算（max_turns + token 累计）；直播验证 3 次工具调用（read→propose→write 审批）。

### Phase 6 — 写作/复盘/导出（进行中）
- ✅ `documents`/`document_versions`（版本不可变 + content_sha256）/`document_claims`（主张↔证据节点关联）+ 迁移 0012。
- ✅ 完整性检查（§17.2）：每主张证据节点有效、未解决占位文本告警、引用键唯一/论文缺失/年份缺失检查。
- ✅ `citations`（引用键唯一）+ Markdown 导出（解析引用 → 存 MinIO Asset → 签名下载 URL + manifest）。
- ✅ Reflection（§17.5）：确定性指标（完成率/阶段/失败运行/证据/矛盾）+ 建议 + 存 Document(type='reflection') + 建议采纳 → research_action。
- ✅ `document_suggestions`（§17.4 Agent Diff）：`document_suggestions` 表 + 迁移 0015 + 确定性 diff（additions/deletions/ops + preview）+ 接受时事务内创建新版本不覆盖基准 + 拒绝 + superseded + 单元/集成测试。
- ✅ LaTeX/DOCX/PDF 导出（§17.1）：`export_document(format=markdown|latex|docx|pdf)`，pandoc 3.10 + **xelatex + xeCJK（Microsoft YaHei）支持中文 PDF**；直播冒烟 4 种格式全部生成真实 SHA-256 + 下载 URL。

### Phase 7 — 加固与发布（进行中）
- ✅ 选题采纳联动（§6.2/§13.6）：采纳 → 审计 `topic.candidate.accepted` + 生成下一步文献调研行动（`research_action`，priority=1）+ **topic 阶段自动完成（ready→running→completed）**；Dashboard 六卡片统计改为真实 COUNT（实验运行/数据集/图表，不再写死 0）。
- ✅ 安全头（§19.3）：X-Content-Type-Options/X-Frame-Options/Referrer-Policy + 生产 HSTS/CSP。
- ✅ 登录限流（§19.3）：Redis 固定窗口，每 IP 每分钟 20 次，超限 429。
- ✅ 前端路由级懒加载（§9.9）：主壳 1.5MB → 260KB，ECharts（Dashboard）与 React Flow（Workspace）拆为按需 chunk。
- ✅ ECharts tree-shaking（echarts/core + LineChart）：Dashboard chunk 1048KB → 478KB。
- ✅ 前端 11 个菜单页面全部落地（研究总览/项目空间/文献库/实验管理/数据资产/知识图谱/写作中心/复盘洞察/智能体中心/审批中心/系统设置），接真实 API（上传/审批/写作版本/复盘/Agent 任务/证据图/健康检查）。
- ✅ 文档：`docs/api.md`、`docs/security.md`。
- ✅ 审计日志（§19.6）：`audit_logs` 表 + 迁移 0014 + 全面接线（审批决定/阶段完成/实验运行与取消/Agent 任务与高风险工具/资产上传/项目归档与恢复/成员增删）+ 查询 API（`GET /projects/{id}/audit-logs`）+ 集成测试。
- ✅ CI（§22.3）：`.github/workflows/ci.yml`（后端 ruff/mypy/unit/integration + 前端 typecheck/build/test）；`ruff check app tests` 本地通过；`requirements-dev.txt`。
- ✅ Celery beat 定时 outbox 消费（默认 30s，`OUTBOX_DISPATCH_INTERVAL` 可调；已验证 beat 每 3s 触发 `outbox.dispatch`）+ 手动 CLI 重建（`dispatcher --rebuild`）。
- ✅ OpenAPI 生成前端类型（§9.4）：`openapi-typescript` 从运行实例 `/api/openapi.json` 生成 `src/api/generated.ts`（`npm run generate:types`）。
- ✅ 备份/恢复 runbook（§22.5）：`docs/runbook-backup-restore.md`（PG `pg_dump` + MinIO `mc mirror` + Neo4j/Milvus 投影重建 + 恢复顺序 + 演练）。
- ✅ Playwright E2E + 视觉回归（§22.3）：`playwright.config.ts` + `tests/e2e/smoke.spec.ts`，系统 Chrome 1440×900 两张基准页（Dashboard/Evidence Workspace）`toHaveScreenshot` 基线，本地 2 passed。
- ✅ 指标/Trace（§19.7/§22.3）：Prometheus `/metrics`（HTTP 计数/延迟直方图 + 业务计数器）+ OTel trace 管线（FastAPI instrumentor → OTLP，按 `OTEL_EXPORTER_OTLP_ENDPOINT` 启用）。
- ✅ 资产多分片上传（§9.7）：initiate(part_count) → create_multipart_upload + 每片签名 URL → 直传 → complete(etags) + 服务端 SHA-256/大小校验 + 失败 abort；前端 ≥5MiB 自动分片 + 进度条；集成测试（2 片 6MiB）通过。
- ✅ 性能基线（§22.6）：`backend/scripts/benchmark_api.py` + `backend/scripts/benchmark_graph.py` + `docs/performance-baseline.md`；实测 Dashboard P95 36ms、列表 P95 33ms、子图 P95 37ms（seed 规模）、**500 节点/1,500 边子图 P95 173ms**，均达标。
- ✅ refresh token 改 HttpOnly Cookie + CSRF（§18.3/§19.3）：`ar_refresh` HttpOnly/SameSite=Lax/生产 Secure Cookie，前端不再存 localStorage；refresh/logout 读 Cookie（回退 body）；Origin 白名单 CSRF 校验；直播验证（login→Set-Cookie、refresh 200、logout 204、跨站 Origin 403）。
- ✅ 文献检索异步化（§3.3 202+Job）：`literature_search_runs` 表 + 迁移 0016 + `POST /literature-search-runs`（202+run_id）+ Celery `literature.search`（路由 default 队列）+ `GET .../{run_id}` 轮询 + 前端轮询 UI；直播冒烟（worker 消费 → arXiv 命中 5 篇 succeeded）+ 集成测试 2 项。
- ✅ WebSocket Job 状态推送（§13.x/§22.6）：`GET /api/v1/ws/projects/{id}/jobs`（Redis pub/sub 桥接）+ 文献/实验 Job 状态事件发布 + 前端 `useJobSocket`（退避重连 + REST 兜底）；直播冒烟收到 running→succeeded。
- ✅ 文件安全（§19.4）：Magic Bytes 校验（PDF/PNG/JPEG/GIF/ZIP/GZIP）+ 大小上限 `max_upload_bytes`（默认 500MiB），`MAGIC_BYTES_MISMATCH`/`FILE_TOO_LARGE` 拒绝 + 单元/直播验证。

### 遗留（需外部依赖 / 重基建）

- ✅ 恶意扫描 quarantine（§19.4）：ClamAV `clamscan` 扫描 + Asset `status`=ready/quarantined + `scan_status`；缺 ClamAV 时 `not_scanned` 诚实降级；单元测试 5 项。
- ✅ PDF 解析/chunk/embedding（§13.x）：pymupdf 抽文本 → 500 字分块 → hash-dev 嵌入 → PG `paper_chunks`（迁移 0017）+ Milvus；`POST /papers/{id}:ingest-pdf`；直播冒烟（上传 PDF → asset 扫描 clean → ingest chunks=1）。
- ✅ 扫描件 PDF OCR（§13.x）：无文本层时 RapidOCR 渲染页面识别（直播 OCR 冒烟识别英文文本）；缺 OCR 引擎时返回空串诚实降级。
- ✅ 自动证据抽取（§13.x）：`POST /papers/{id}:extract-evidence` 用 LLM 从文献 chunk/摘要抽取主张 → EvidenceNode（claim/evidence/hypothesis）；直播冒烟抽取 2 条 claim。
- ✅ 真实语义 embedding（§11.10/§26.3）：`openai-compatible` 提供者（DashScope `text-embedding-v3` 1024 维，直播验证）+ Milvus 维度不匹配自动重建集合；hash-dev 仅离线回退。
- Zip Slip 防护（解压隔离）、Secret 扫描。

## 四、如何继续

自包含切片已全部完成；剩余项均需外部依赖（见上「遗留」）。继续路径：

1. 用户提供任一外部依赖 → 解锁对应切片（如 pandoc/pdflatex → LaTeX/PDF 导出；ClamAV → quarantine；docreader → PDF/OCR 流水线；runner 端点 → 隔离容器 Runner）。
2. Agent Orchestrator DAG（工具调用回环）为最后一个可自包含项，可继续实现。
3. §23 清单逐项签字式核对（`docs/acceptance.md` 已维护）。

每个切片请：写测试 → 实现 → 跑最窄相关测试 → 更新本文件与 `README.md`。
