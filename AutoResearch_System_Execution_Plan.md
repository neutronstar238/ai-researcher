# 全自动科研自进化系统实施计划

> 文件名：实施计划.md
> 生成日期：2026-06-11
> 项目名称：AI-Researcher
> 目标：把“全自动科研、自循环、自进化”从研究设想落地为可运行、可测试、可扩展的工程系统

---

## 1. 实施原则

本实施计划采用“先可信、再自动、再自治、最后自进化”的路线。

优先级如下：

```text
P0：最小可信闭环
P1：自动化增强
P2：自循环能力
P3：自进化能力
P4：商用化与多用户平台
```

不要同时铺开所有功能。第一阶段应优先证明系统能够完成一个受限研究项目的端到端闭环，并且结果可重跑、可验证、可审查。

---

## 2. 总体里程碑

| 阶段 | 时间 | 目标 | 核心交付物 |
|---|---:|---|---|
| Phase 0 | 第 0-2 周 | 项目基建与规范 | repo、schema、CI、配置系统、最小 CLI |
| Phase 1 | 第 3-8 周 | 最小可信闭环 | 文献检索、知识库、实验任务、沙箱执行、结果验证 |
| Phase 2 | 第 9-16 周 | 自动化研究助手 | 多 Agent 协作、论文生成、审稿模拟、复现包 |
| Phase 3 | 第 17-24 周 | 自循环平台 | 研究问题池、定时运行、失败库、技能库、监控回滚 |
| Phase 4 | 第 25-36 周 | 自进化试运行 | 策略候选、影子评估、灰度上线、自动回滚 |
| Phase 5 | 第 2-3 年 | 可商用平台 | 多用户、Dashboard、私有化部署、合规审计、插件体系 |

---

## 3. Phase 0：项目基建与工程规范

### 3.1 时间

第 0-2 周。

### 3.2 目标

建立项目结构、核心数据结构、开发规范、测试规范和最小运行入口。

### 3.3 任务清单

| 编号 | 任务 | 负责人 | 产物 | 验收标准 |
|---|---|---|---|---|
| 0.1 | 初始化 Python 项目 | 后端工程 | pyproject.toml、src/、tests/ | `pytest` 可运行 |
| 0.2 | 定义核心 schema | 架构负责人 | pydantic/dataclass schemas | 6 类核心对象定义完成 |
| 0.3 | 建立配置系统 | 后端工程 | config.yaml、loader、validator | JSON/YAML/TOML 可解析 |
| 0.4 | 建立日志系统 | MLOps | structured logging | 每次运行有 run_id |
| 0.5 | 建立 CI | MLOps | GitHub Actions | push 自动测试 |
| 0.6 | 建立最小 CLI | 后端工程 | `autoresearch` 命令 | 可启动 demo run |

### 3.4 核心目录结构

```text
autoresearch/
├── src/autoresearch/
│   ├── agents/
│   ├── workflows/
│   ├── knowledge/
│   ├── evidence/
│   ├── experiments/
│   ├── validation/
│   ├── scheduler/
│   ├── paper/
│   ├── evolution/
│   ├── security/
│   └── cli/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── property/
│   └── regression/
├── docs/
├── configs/
├── scripts/
└── examples/
```

### 3.5 核心 schema

必须优先实现以下对象：

1. `DocumentRecord`
2. `KnowledgeNode`
3. `ResearchCandidate`
4. `Hypothesis`
5. `ExperimentTask`
6. `ExecutionRun`
7. `ResultBundle`
8. `EvidenceEdge`
9. `PaperDraft`
10. `StrategyCard`

---

## 4. Phase 1：最小可信闭环

### 4.1 时间

第 3-8 周。

### 4.2 目标

完成一个受限研究任务的最小闭环：

```text
输入研究方向 → 检索文献 → 生成假设 → 设计实验 → 生成代码 → 沙箱执行 → 收集结果 → 验证结果 → 输出报告
```

### 4.3 任务清单

| 编号 | 任务 | 产物 | 验收标准 |
|---|---|---|---|
| 1.1 | Literature Retriever MVP | arXiv/Semantic Scholar 检索 | 能返回结构化论文列表 |
| 1.2 | Knowledge Base MVP | Markdown vault + index | 文献与实验记录可写入 |
| 1.3 | Project Agent MVP | 单项目 Agent | 能维护项目状态 |
| 1.4 | Hypothesis Generator MVP | 假设列表 | 每个假设可转实验 |
| 1.5 | Experiment Designer MVP | ExperimentTask | 任务包含代码、数据、指标、预算 |
| 1.6 | Code Generator MVP | Python 实验目录 | 代码可运行，有日志与结果文件 |
| 1.7 | Sandbox Executor MVP | 本地沙箱执行 | 限制目录访问与运行时间 |
| 1.8 | Result Collector MVP | ResultBundle | 自动解析 metrics.json/csv/log |
| 1.9 | Validator MVP | 验证报告 | 检查运行、指标、产物是否完整 |
| 1.10 | Research Report MVP | Markdown 报告 | 输出完整实验报告 |

### 4.4 MVP 验收

选择 5-10 个小型机器学习任务作为测试集，例如分类、回归、文本分类、小模型调参。

通过标准：

1. 至少 60% 任务能完整跑通；
2. 每次运行都有 run_id、commit、配置、日志、指标；
3. 至少 80% 成功任务可以重跑；
4. 所有结论必须能追溯到结果文件；
5. 不允许无运行结果直接生成结论。

---

## 5. Phase 2：自动化研究助手

### 5.1 时间

第 9-16 周。

### 5.2 目标

从“能跑通”升级到“能辅助完成高质量研究初稿”。

### 5.3 任务清单

| 编号 | 任务 | 产物 | 验收标准 |
|---|---|---|---|
| 2.1 | 多 Agent 工作流 | Main/Fixed/Project Agents | Agent 之间结构化通信 |
| 2.2 | Evidence Graph | claim-evidence-source 结构 | 每个 claim 可追溯 |
| 2.3 | Baseline Reproducer | baseline 复现实验 | 至少可复现 1 个 baseline |
| 2.4 | Ablation Designer | 消融实验任务 | 自动生成关键 ablation |
| 2.5 | Figure Generator | PDF/PNG 图表 | 图表数据来自结果文件 |
| 2.6 | Paper Generator | LaTeX 初稿 | 可编译 PDF |
| 2.7 | Citation Validator | 引用校验报告 | DOI/URL 可验证 |
| 2.8 | Review Simulator | 审稿意见 | 至少 5 个维度评分 |
| 2.9 | Repro Package Builder | 复现包 | 包含代码、配置、README |

### 5.4 验收标准

1. 论文初稿可以从实验结果生成，而不是凭空生成；
2. LaTeX 编译成功率 ≥90%；
3. 引用校验错误率 <5%；
4. 表格、图、正文指标一致率 ≥95%；
5. 每个核心 claim 至少绑定一个 evidence。

---

## 6. Phase 3：自循环平台

### 6.1 时间

第 17-24 周。

### 6.2 目标

系统能够周期性运行，持续产生候选研究方向，并把每一轮运行结果沉淀为知识。

### 6.3 任务清单

| 编号 | 任务 | 产物 | 验收标准 |
|---|---|---|---|
| 3.1 | Research Candidate Pool | 候选方向池 | 每日/每周自动更新 |
| 3.2 | Trend Analyzer | 趋势分析报告 | 基于最新文献生成 |
| 3.3 | Gap Analyzer | 研究 gap 列表 | 每个 gap 有证据来源 |
| 3.4 | Task Scheduler | 周期任务调度 | 支持定时运行 |
| 3.5 | Failure Library | 失败库 | 每次失败自动分类 |
| 3.6 | Skill Library | 技能卡 | 成功模式可复用 |
| 3.7 | Monitoring | 指标面板 | 可看成本、失败率、成功率 |
| 3.8 | Rollback System | 回滚机制 | 可回滚配置、策略、知识条目 |

### 6.4 验收标准

1. 连续运行 14 天不中断；
2. 每天自动生成候选方向；
3. 每个失败任务都有失败分类；
4. 至少生成 10 张 Skill Card；
5. 至少支持一次配置或策略回滚。

### 6.5 Online literature refresh constraint

The self-loop candidate pool must be fed by a daily online literature refresh pipeline. The first implementation should follow the same pipeline separation used by Horizon-style news radar systems: configured sources, fetch, deduplicate, score/filter, enrich, summarize or persist. For AI-Researcher this means ArXiv and Semantic Scholar first, search-query generation from Obsidian topics/methods/datasets/failures, source-specific rate limits, retrieval cache reuse, and evidence-backed `DocumentRecord` output before trend/gap analysis.

ArXiv access must respect the official legacy API constraint of a single connection and no more than one request every three seconds. Search prompts and query templates are evolvable retrieval policies, but they must be versioned and evaluated before promotion.

---

## 7. Phase 4：自进化试运行

### 7.1 时间

第 25-36 周。

### 7.2 目标

让系统能够提出并验证自己的改进策略，但不能直接无审查修改生产系统。

### 7.3 任务清单

| 编号 | 任务 | 产物 | 验收标准 |
|---|---|---|---|
| 4.1 | Strategy Library | 策略库 | prompt/workflow/tool policy 可版本化 |
| 4.2 | Offline Replay | 离线回放器 | 历史任务可重放 |
| 4.3 | Golden Test Set | 金集 | 固定回归测试集 |
| 4.4 | Shadow Evaluation | 影子评估环境 | 新策略不影响生产结果 |
| 4.5 | Strategy Proposer | 策略候选生成器 | 能基于失败模式提出改进 |
| 4.6 | Gray Release | 灰度发布 | 支持小流量上线 |
| 4.7 | Auto Rollback | 自动回滚 | 负收益自动撤回 |
| 4.8 | Evolution Report | 进化报告 | 记录策略收益与风险 |

### 7.4 自进化上线门槛

新策略必须同时满足：

1. 金集测试不退化；
2. 主指标提升或成本下降；
3. 安全指标不下降；
4. 可复现率不下降；
5. 人工干预次数不增加；
6. 影子运行至少覆盖 20 个任务；
7. 灰度期无严重事故。

---

## 8. Phase 5：可商用平台

### 8.1 时间

第 2-3 年。

### 8.2 目标

从内部科研工具升级为可部署、可审计、可扩展的科研自动化平台。

### 8.3 任务清单

| 模块 | 功能 |
|---|---|
| 多用户系统 | 账号、角色、项目权限、团队空间 |
| Web Dashboard | 项目状态、实验图表、成本、审稿意见 |
| 插件系统 | 文献源、实验框架、计算资源、通知渠道 |
| 私有化部署 | Docker Compose、K8s Helm Chart |
| 合规审计 | 数据、许可证、隐私、AI 使用声明 |
| 成本管理 | 项目预算、GPU 小时、API 成本、告警 |
| SLA 与监控 | 健康检查、失败恢复、性能指标 |
| API 服务 | 对外提供研究工作流接口 |

---

## 9. 技术栈建议

| 层级 | 推荐技术 | 说明 |
|---|---|---|
| Agent Runtime | LangGraph | 适合状态化、多轮、可恢复工作流 |
| LLM 接入 | OpenAI/Anthropic/本地模型抽象层 | 统一模型路由和成本记录 |
| 配置 | YAML/TOML + Pydantic | 可验证、可类型化 |
| 知识库 | Markdown/Obsidian + PostgreSQL + pgvector | 人类可读 + 结构化检索 |
| 实验追踪 | MLflow | run、参数、指标、artifact 记录 |
| 数据版本 | DVC | 数据和模型版本控制 |
| 调度 | 本地队列 + Airflow/Argo 可选 | 从简单到复杂扩展 |
| 执行 | Docker + SSH + Sandbox | 安全隔离 |
| HPO | Optuna/Ray Tune | 预算受控搜索 |
| 监控 | Prometheus + Grafana + Loki | 指标、日志、告警 |
| 文档 | LaTeX + Markdown | 论文和报告生成 |
| CI/CD | GitHub Actions | 测试、构建、发布 |

---

## 10. 人力配置

### 10.1 最小团队

| 角色 | 人数 | 职责 |
|---|---:|---|
| 技术负责人/架构师 | 1 | 总体架构、模块边界、关键决策 |
| Agent/LLM 工程师 | 1-2 | Agent 工作流、prompt、模型路由 |
| 后端/MLOps 工程师 | 1 | 执行、调度、MLflow、DVC、CI |
| 数据与评测工程师 | 1 | benchmark、验证器、测试集、指标 |
| 科研领域顾问 | 0.5-1 | 选题质量、实验合理性、论文审查 |

### 10.2 单人推进版本

如果只有 1 人开发，建议只做：

1. 文献检索；
2. 单 Project Agent；
3. 本地沙箱执行；
4. 结果验证；
5. Markdown 报告生成；
6. 简单失败库。

不要第一版就做 AutoDL、移动端、Web Dashboard、多用户、自进化。

---

## 11. 算力与成本预算

### 11.1 原型阶段

| 资源 | 建议配置 |
|---|---|
| 开发机 | 16-32GB RAM，普通 CPU 即可 |
| GPU | 可选，1 张 24GB GPU 更好 |
| 存储 | 200GB 起 |
| API | 小规模调用，重点记录 token 成本 |
| 云 GPU | 非必要，按任务临时租用 |

### 11.2 标准研究阶段

| 资源 | 建议配置 |
|---|---|
| 本地/远程 GPU | 1-4 张 24GB/48GB GPU |
| 存储 | 1-2TB，含数据、模型、artifact |
| Tracking Server | MLflow + PostgreSQL + artifact storage |
| 并发任务 | 3-10 个实验任务 |
| 月度预算 | 根据 GPU 小时和 API 调用量参数化计算 |

### 11.3 成本公式

```text
TotalCost = LLM_API_Cost
          + GPU_Hours × GPU_Unit_Price
          + CPU_Hours × CPU_Unit_Price
          + Storage_GB_Month × Storage_Price
          + Network_Cost
          + Human_Review_Hours × Human_Cost
```

每个 `ExecutionRun` 必须记录：

1. token 输入输出；
2. 模型名称；
3. GPU 小时；
4. CPU 时间；
5. 存储 artifact 大小；
6. 人工审批/修改次数。

---

## 12. 数据库与表设计建议

### 12.1 核心表

```text
projects
research_candidates
hypotheses
documents
knowledge_nodes
evidence_edges
experiment_tasks
execution_runs
result_bundles
paper_drafts
validation_reports
failure_cases
skill_cards
strategy_cards
audit_logs
```

### 12.2 关键字段

`execution_runs`：

```sql
run_id
project_id
task_id
status
start_time
end_time
commit_sha
data_hash
config_hash
metrics_json
artifact_uri
cost_json
validator_status
error_type
```

`strategy_cards`：

```sql
strategy_id
strategy_type
version
content
parent_strategy_id
evaluation_score
golden_test_status
shadow_status
release_status
rollback_target
```

---

## 13. API 与模块接口

### 13.1 Project API

```python
create_project(research_direction: str) -> Project
run_investigation(project_id: str) -> InvestigationReport
generate_hypotheses(project_id: str) -> list[Hypothesis]
select_hypothesis(project_id: str, hypothesis_id: str) -> None
```

### 13.2 Experiment API

```python
design_experiments(hypothesis_id: str) -> list[ExperimentTask]
generate_code(task_id: str) -> CodeBundle
run_experiment(task_id: str, mode: str = "sandbox") -> ExecutionRun
collect_results(run_id: str) -> ResultBundle
validate_results(run_id: str) -> ValidationReport
```

### 13.3 Paper API

```python
generate_claims(project_id: str) -> list[Claim]
build_evidence_map(project_id: str) -> EvidenceMap
generate_paper(project_id: str, template: str) -> PaperDraft
run_review(paper_id: str) -> ReviewReport
build_repro_package(project_id: str) -> ReproPackage
```

### 13.4 Evolution API

```python
record_failure(run_id: str) -> FailureCase
extract_skill(project_id: str) -> SkillCard
propose_strategy_update(scope: str) -> StrategyCard
run_shadow_eval(strategy_id: str) -> EvaluationReport
promote_strategy(strategy_id: str) -> ReleaseResult
rollback_strategy(strategy_id: str) -> RollbackResult
```

---

## 14. 测试计划

### 14.1 测试分层

| 测试类型 | 目标 | 覆盖对象 |
|---|---|---|
| Unit Tests | 单函数正确性 | parser、validator、scheduler |
| Property Tests | 通用性质正确性 | 配置 round-trip、权限、去重 |
| Integration Tests | 模块协作 | 文献检索、实验执行、MLflow |
| Regression Tests | 防止策略退化 | golden task set |
| End-to-End Tests | 闭环能力 | 从选题到报告 |
| Security Tests | 权限与沙箱 | 越权、危险命令、凭证泄露 |

### 14.2 必测性质

1. 配置 parse-format-parse 等价；
2. Project Agent 不能写其他项目目录；
3. 沙箱不能访问实验目录外文件；
4. 文献去重后 DOI 唯一；
5. 每个结果必须能追溯到 run；
6. 每个 claim 必须绑定 evidence；
7. 新策略不能绕过审批门；
8. 回滚后旧策略恢复可用。

### 14.3 E2E 测试任务

建议建立 `ScientistBench-Lite`：

| 任务 | 类型 | 验收 |
|---|---|---|
| tabular_baseline | 表格分类 | 复现 baseline 并生成报告 |
| text_classifier | 文本分类 | 对比 2 个方法并画图 |
| small_hpo | 超参搜索 | Optuna 搜索并早停 |
| ablation_demo | 消融实验 | 自动生成 ablation 表 |
| paper_draft_demo | 论文生成 | LaTeX 可编译 |

---

## 15. 监控指标

### 15.1 系统指标

| 指标 | 含义 |
|---|---|
| task_success_rate | 任务成功率 |
| experiment_reproduction_rate | 实验复现率 |
| validator_rejection_rate | 验证器拒绝率 |
| avg_cost_per_success | 单成功任务成本 |
| avg_human_interventions | 平均人工干预次数 |
| agent_loop_depth | Agent 循环深度 |
| rollback_count | 回滚次数 |
| citation_error_rate | 引用错误率 |
| evidence_coverage | claim 证据覆盖率 |

### 15.2 告警规则

| 告警 | 条件 | 动作 |
|---|---|---|
| 成本告警 | 单任务成本超过预算 80% | 暂停任务并请求审批 |
| 失败率告警 | 最近 20 个任务失败率 >40% | 冻结自循环 |
| 引用告警 | 引用错误率 >5% | 禁止生成正式论文 |
| 安全告警 | 出现越权或危险命令 | 立即中止运行 |
| 退化告警 | 新策略 reward 连续下降 | 自动回滚 |

---

## 16. 发布与版本管理

### 16.1 版本路线

| 版本 | 定位 | 功能 |
|---|---|---|
| v0.1 | 本地 demo | 文献→实验→报告 |
| v0.2 | 可信闭环 | 结果验证、证据链 |
| v0.3 | 论文初稿 | LaTeX、图表、引用校验 |
| v0.4 | 多 Agent | Main/Fixed/Project 协作 |
| v0.5 | 自循环 | 任务池、失败库、技能库 |
| v0.6 | 自进化 beta | 影子评估、灰度、回滚 |
| v1.0 | 稳定研究助手 | 可长期内部使用 |
| v2.0 | 团队平台 | 多用户、Dashboard、权限 |
| v3.0 | 商用系统 | 私有化、审计、SLA、插件 |

### 16.2 发布门槛

每次发布必须满足：

1. 所有 unit tests 通过；
2. golden tests 不退化；
3. 安全测试通过；
4. 文档更新；
5. 迁移脚本可回滚；
6. 版本 tag 与 changelog 完整。

---

## 17. 安全与权限实施

### 17.1 默认安全策略

1. 所有实验默认沙箱执行；
2. 所有凭证加密存储；
3. Agent 只能访问被授权工具；
4. Project Agent 不能写其他项目；
5. Full permission mode 必须人工确认；
6. 对外发布必须人工确认。

### 17.2 危险操作拦截

禁止或审批以下操作：

```text
rm -rf /
dd if=...
mkfs
sudo systemctl
修改 ~/.ssh
读取 .env 或 key 文件
访问未授权网络域名
批量删除项目数据
```

---

## 18. 交付物清单

### 18.1 MVP 交付物

1. 可运行源码；
2. CLI；
3. 配置文件示例；
4. 文献检索模块；
5. 知识库模块；
6. 单项目 Agent；
7. 沙箱执行器；
8. 结果验证器；
9. Markdown 报告生成器；
10. 示例任务。

### 18.2 稳定版交付物

1. 多 Agent 工作流；
2. Evidence Graph；
3. MLflow + DVC 集成；
4. LaTeX Paper Generator；
5. Review Simulator；
6. Repro Package Builder；
7. Monitoring Dashboard；
8. Failure Library；
9. Skill Library；
10. Strategy Library。

### 18.3 商用版交付物

1. Web Dashboard；
2. 多用户权限；
3. 插件系统；
4. 私有化部署方案；
5. 合规审计；
6. 成本管理；
7. API 文档；
8. SLA 监控；
9. 管理后台；
10. 企业部署手册。

---

## 19. 每周推进计划

### 第 1-4 周

- 完成项目结构；
- 完成 schema；
- 完成配置系统；
- 完成最小知识库；
- 完成文献检索 demo。

### 第 5-8 周

- 完成单项目 Agent；
- 完成实验任务生成；
- 完成本地沙箱执行；
- 完成结果收集；
- 完成第一次 E2E demo。

### 第 9-12 周

- 增加 evidence graph；
- 接入 MLflow；
- 接入 DVC；
- 完成 baseline reproduction；
- 完成基础论文生成。

### 第 13-16 周

- 完成审稿模拟；
- 完成引用校验；
- 完成图表校验；
- 完成复现包；
- 完成 v0.3 发布。

### 第 17-20 周

- 完成研究方向池；
- 完成定时运行；
- 完成失败库；
- 完成技能库；
- 完成监控告警。

### 第 21-24 周

- 连续运行测试；
- 修复稳定性问题；
- 完成回滚系统；
- 完成 v0.5 发布。

### 第 25-36 周

- 完成策略库；
- 完成离线回放；
- 完成影子评估；
- 完成灰度上线；
- 完成自进化 beta。

---

## 20. 关键决策建议

### 20.1 第一版不要做的事

1. 不要做全自动投稿；
2. 不要做真实实验室设备控制；
3. 不要做多用户复杂权限；
4. 不要做完整 Web 平台；
5. 不要让系统自动修改安全策略；
6. 不要把论文文本质量当唯一目标。

### 20.2 第一版必须做好的事

1. 每个实验必须真实运行；
2. 每个结果必须可追溯；
3. 每个 claim 必须有 evidence；
4. 每次失败必须入库；
5. 每次运行必须有成本记录；
6. 每个策略变更必须可回滚。

---

## 21. 最小可落地版本定义

一个真正可交付的 MVP 应满足以下定义：

输入：一个明确的机器学习研究方向。
输出：一个包含代码、配置、结果、图表、验证报告、Markdown 研究报告的项目目录。

项目目录示例：

```text
project_demo/
├── README.md
├── literature/
├── hypotheses/
├── experiments/
│   ├── exp_001/
│   │   ├── code/
│   │   ├── config.yaml
│   │   ├── logs/
│   │   ├── metrics.json
│   │   └── validation_report.md
├── results/
├── evidence_map.json
├── report.md
└── repro_package/
```

如果这个 MVP 能稳定运行，再继续做论文生成、多 Agent、自循环、自进化。

---

## 22. 最终落地判断

该项目应按工程系统而非单次论文实验推进。最关键的不是一次性展示“AI 写出论文”，而是建立一套长期稳定运行的科研自动化基础设施。

推荐落地顺序：

```text
1. 最小可信闭环
2. 证据图谱与结果验证
3. 论文初稿与复现包
4. 多 Agent 协作
5. 自循环任务池
6. 失败库与技能库
7. 策略库与影子评估
8. 灰度自进化
9. 多用户平台
10. 商用化部署
```

只要严格遵守“可验证、可追溯、可回滚”的原则，这个系统就具备从研究原型发展为真正科研操作系统的可行性。
