# §23 验收清单（最终签字式核对）

> 依据 spec §23。✅=已实现并验证；⚠️=部分实现/降级；❌=未实现。
> 本清单如实记录，不把 ⚠️/❌ 伪装成 ✅（spec §23.4）。

## 23.1 UI 验收

| 项 | 状态 | 说明 |
|---|---|---|
| Dashboard/Workspace 1440×900 坐标/尺寸/视觉令牌 | ✅ | Playwright + 系统 Chrome 建立两张基准页 1440×900 视觉基线（Dashboard 两列 / Evidence Workspace 三栏 260+860+320），`toHaveScreenshot` 差异 ≤1% 通过（spec §22.3） |
| 所有菜单有真实路由和页面 | ✅ | 11 个菜单（研究总览/项目空间/文献库/实验管理/数据资产/知识图谱/写作中心/复盘洞察/智能体中心/审批中心/系统设置）均为真实页面，接真实 API |
| 所有按钮 Hover/Focus/Disabled/Loading/Success/Error | ✅ | 全局统一：键盘焦点环（`:focus-visible` 主色 outline）、禁用态（cursor+opacity）、Hover 过渡；各页按钮有 `disabled:`/`isPending` loading/error 反馈（§23.1） |
| 表格/图表/Timeline/Graph 数据均来自 API | ✅ | 六卡片、时间线、证据图、文献/实验/审批均接真实 API |
| 刷新后持久业务状态恢复 | ✅ | PostgreSQL 权威源，seed 幂等 |
| 无权限/空/未配置有准确界面 | ✅ | 403/empty/未配置（LLM/Embedding 降级）均有明确状态 |

## 23.2 功能验收

| 项 | 状态 | 说明 |
|---|---|---|
| 选题→进化完整研究周期 | ✅ | 8 阶段状态机+门禁完整；采纳选题已联动（落审计 + 生成下一步文献调研行动 + **topic 阶段 ready→running→completed 自动完成** + 六卡片统计真实 COUNT），后续阶段经生命周期 API 顺序推进（直播冒烟验证） |
| 文献搜索/上传/解析/OCR/Embedding/证据抽取 | ✅ | 检索异步化（202+Job）+保存+统计；PDF 解析/chunk/embedding + 扫描件 OCR（RapidOCR）+ **LLM 自动证据抽取**（主张→证据节点，直播抽取 2 条 claim） |
| Evidence Graph 编辑/溯源/支持反驳 | ✅ | 节点/边 CRUD+关系矩阵+矛盾投影+Neo4j 投影+React Flow 工作台 |
| 实验隔离运行/日志/指标/产物/复现 | ✅ | 定义+状态机+**隔离容器执行（Docker 隔离）**+真实子进程 dev 回退+**实时日志流（WebSocket 逐行推送）**+指标+产物+复现清单完成 |
| Agent 真实执行工具/预算/权限/审批重试 | ✅ | 数据模型+任务生命周期+工具风险分级+审批门禁+预算+Memory 完成；真实 LLM 编排 + **Orchestrator DAG（多轮工具调用回环）**：`project.read`/`evidence.propose` 真实执行、`evidence.write` 高风险→审批门禁暂停（直播验证 3 次工具调用） |
| 写作建议不覆盖正式内容/引用主张完整性 | ✅ | 文档/版本不可变/主张↔证据/引用/完整性检查完成；`document_suggestions`（Agent Diff）实现：确定性 diff + patch/preview + 接受时事务内创建新版本不覆盖基准 + 拒绝/过期（superseded） |
| 文件/数据/代码/模型/导出物版本+SHA-256 | ✅ | 资产/数据集版本/文档版本 SHA-256 完成；**代码 Hash 与实验运行绑定**（本地入口 SHA-256 → `code_sha256`，容器镜像 digest → `image_digest`）+ 复现清单 |
| Owner/Researcher/Reviewer/Guest 权限矩阵 | ✅ | §1.2 矩阵单元测试+集成（guest 写 403）验证 |

## 23.3 工程验收

| 项 | 状态 | 说明 |
|---|---|---|
| 一条命令启动核心 Compose | ✅ | `docker compose up -d postgres redis minio neo4j etcd milvus` |
| Migration/Seed/测试/构建命令有 README | ✅ | README + Makefile + docs |
| OpenAPI/前端类型/DB 模型与接口一致 | ✅ | `openapi-typescript` 从运行实例 `/api/openapi.json` 生成 `src/api/generated.ts`（`npm run generate:types`），`tsc --noEmit` 通过；DB 模型与 Alembic 迁移一致 |
| CI 跑 lint/typecheck/unit/integration/E2E/visual | ⚠️ | `.github/workflows/ci.yml` 已配置后端 ruff/mypy/unit/integration + 前端 typecheck/build/test + 独立 `e2e` job（全栈 compose + migrate/seed + uvicorn + Playwright 2 基线页 1440×900）；本地 `npm run test:e2e` 已验证 2 passed；本环境未实际跑 GitHub Actions（配置未在 CI 执行验证） |
| 未提交 Secret/签名 URL/全文/敏感数据 | ✅ | `.env` gitignored、`.env.example` 无真实值、脱敏过滤器 |
| 日志/指标/Trace/审计能定位失败 | ✅ | 结构化日志+Request-ID+trace_id；Prometheus `/metrics`（HTTP 计数/延迟直方图 + 业务计数器 `ar_audit_events_total`/`ar_experiment_runs_total`，路径按路由模板归一化）；OTel trace 管线（FastAPI instrumentor → OTLP）已接，需 `OTEL_EXPORTER_OTLP_ENDPOINT` 导出（未配置时 no-op）；审计日志全面接线 + 查询 API |
| 备份/恢复/投影重建说明 | ✅ | `docs/runbook-backup-restore.md`（PG `pg_dump`/`psql` + MinIO `mc mirror` + Neo4j/Milvus 投影重建 + 恢复顺序 + 完整性校验 + 演练）；Neo4j 重建命令 `dispatcher --rebuild` |

## 23.4 不可接受的「伪完成」（全部应避免）

| 项 | 状态 | 说明 |
|---|---|---|
| 按钮只 Toast 成功后端无状态变化 | ✅ 避免 | 所有写操作真实落库 |
| 图表/统计/任务状态写死组件 | ✅ 避免 | 全部来自 API（papers 统计为真实 COUNT） |
| 实验运行只是定时器模拟 | ✅ 避免 | 真实 `create_subprocess_shell` 执行 entrypoint，捕获 exit code/日志 |
| Agent 返回静态字符串/不验证引用 | ✅ 避免 | 未接 LLM 时明确 `PROVIDER_NOT_CONFIGURED`，不伪造；工具调用只做审计记录不假执行 |
| 上传文件仅存浏览器/临时目录 | ✅ 避免 | MinIO 直传 + 服务端 SHA-256 |
| 权限只前端隐藏 | ✅ 避免 | 服务端 `require_project_role` 逐请求校验 |
| Neo4j/Milvus 失败静默丢数据 | ✅ 避免 | 投影失败不回滚业务事实（§3.4.3）；dispatcher 有重建命令 |
| 接口 200 但内部任务已失败 | ✅ 避免 | 实验运行同步返回真实 exit code |
| production 路径存在 TODO/空函数/假 Provider | ✅ 避免 | 无 TODO 空函数；**真实语义 embedding 已接**（`openai-compatible` → DashScope `text-embedding-v3` 1024 维，直播验证），hash-dev 仅作离线 dev/test 回退 |

## 结论

**Phase 0–3 完整、Phase 4–6 完整、Phase 7 基本完成。** 平台已是一个可运行、可演示、以真实 PostgreSQL/Neo4j/Milvus/MinIO/Redis/Celery 为后端的单团队科研平台：11 个真实前端页面、8 阶段生命周期、证据图、文献（异步 202+Job + PDF 解析/OCR/嵌入/证据抽取）、资产（分片上传 + 恶意扫描）、实验（隔离容器 + 实时日志 + 复现）、Agent（真实 LLM 编排 + Orchestrator DAG）、写作/复盘/建议（含 LaTeX/DOCX/PDF 导出）、审计、指标/Trace、WebSocket Job 推送、E2E/视觉回归、性能基线、备份 runbook、HttpOnly Cookie+CSRF、真实语义 embedding 均已落地并验证。**§23.2 功能、§23.1 UI、§23.4 伪完成全部 ✅**，仅剩 2 项环境/非核心项未勾选：

- §23.3 CI 在 GitHub Actions 实际执行（本环境无法跑 GitHub Actions；`.github/workflows/ci.yml` 已配置 lint/typecheck/unit/integration/E2E/visual/secret-scan）
- Zip Slip 防护（当前无解压功能，无暴露面）
