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

This online discovery requirement also applies at project start. Before a candidate becomes an approved project, AI-Researcher must run a broad online similarity and novelty cross-check against adjacent directions, competing methods, datasets, baselines, negative evidence, code availability, and contradictory claims. The Obsidian vault stores the evidence-backed summary and query provenance; it is not the only search source.

Summaries written to Obsidian must distinguish verified source metadata, source-backed claims, model interpretation, and unknowns. The system must not fabricate paper results, benchmark scores, citations, venue status, code availability, or experimental outcomes. Missing evidence must stay marked as `unknown` or `pending verification`.

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

---

## 23. 榜题优先执行增量

实施顺序锁定如下：

1. 先用行为 characterization tests 固定旧链路中“候选/计划与实际 demo 不一致”的失败模式；
2. 建立持久化、幂等、可恢复的 `ResearchCycleService`，接通选题、假设、实验 DAG、沙箱执行和哈希证据门；
3. 用明确标注的 MDBench-shaped 开发夹具验证零人工科研输入、三种子执行、恢复和负向发布门；
4. 预检固定的 MDBench revision、代码/数据许可、归档元数据和容器运行时，真实构建并烟测版本化科学计算镜像；
5. 通过已通过的预检续传官方 MDBench 归档，固定大小/MD5、逐文件 SHA-256 和安全解压清单，然后在该容器中接入基线，真实完成至少 10 ODE、4 PDE、clean/noisy 和三次独立复现；
6. Gate A 未通过时先形成负结果并关闭该冻结周期，不在已揭示未见系统上调参，也不开展完整 RealPDEBench 训练和产品界面扩张；
7. 若继续 Gate A，只允许建立不同假设的新周期：绑定父负结果哈希、换用与旧矩阵完全隔离的新未见系统和新种子，并在执行任何结果前冻结机制、矩阵和停止规则；
8. Gate A 真实通过后再接入 Qwen/DashScope 调用证据和 RealPDEBench Cylinder Gate B。

公共入口为 `competition run/resume/status/export`、`competition access grant` 与
`competition mdbench preflight/prepare/preregister/recover-preregister/execute/evaluate`。默认自动选题；
`seeded` 模式只缩小候选空间。授权范围内不逐实验审批，资源耗尽时保存检查点并停止。所有导出均为
本地产物；外部提交必须有显式权限且同时通过科学证据门、复现门和榜题内部评分门。

本阶段完成标准不是“生成看起来像参赛成果的文本”，而是官方基准运行、不可变 manifest、同链路
claim-evidence、一键复现和透明的负结果边界。开发夹具通过不等于 Gate A 通过。
在正式方法执行前，系统还要写入结果盲的 252 单元预注册矩阵：10 ODE、4 PDE、clean/SNR20、
开发/未见测试系统、64/16/20 不重叠时间切分、三个种子、方法预算、指标和接受门均进入内容哈希；
矩阵冻结本身仍不等于运行过任何一个方法。
正式排空矩阵前先执行 hash-bound runner 烟测：三种方法族在同一官方 ODE 单元均产生有限、
非空的导数/轨迹/复杂度指标，具体 64/16/20 索引互不重叠；再次调用必须复用已验链终态。
烟测通过只授权继续执行余下单元，不授权 Gate A、Gate B 或提交结论。
冻结矩阵现已排空并通过完整恢复复验：252 个单元中 244 成功、8 失败、0 超时，第二次调用
复用全部终态。Gate A 聚合器保留全部失败单元，以开发集覆盖率和误差选择 Operon 基线，完成
固定真实方程的结构评分、未见系统比较和 20,000 次系统级 bootstrap。成功单元点估计有利，
但失败感知 95% CI 为 `[-0.201060, 0.888991]`，全方法复现门也只有 244/252。因此任务 259.4
以可信负结果完成并保持 `gate_b_allowed=false`；Gate B、Qwen 提交证据和产品扩张不启动。
任务 259.7.1 已增加 `recover-preregister`：它先验证父矩阵和负结果报告，再冻结弱形式投影与
bootstrap 支持稳定性两个机制、全新未见系统、种子 13/29/43 及 252 个配置哈希。真实恢复
预注册哈希为 `1331a21f1d49f8330433d1a8b05a49bdbf1028cab39b968b24a92ff89bb76079`，矩阵哈希为
`9dba5411b3ae5244950d8f056008370510009a7b9ba1a1d2fbf60956230cd19e`。任务 259.7.2 已将这两个
机制接入版本化科学容器；镜像内合成 ODE/PDE 自测和四个 development cells 均成功，重复调用
复用全部四条终态。列归一化修复了 clean PDE 的弱积分尺度缺陷，但 SNR20 `advection1d` 仍退化
为零方程。这一 smoke 只授权冻结实现并进入独立的 259.7.3 全矩阵执行；它不等于 Gate A 通过，
六个 recovery unseen cells 在 259.7.2 中仍未执行或查看，也不授权 Gate B。

任务 259.7.3 在未见结果仍封存时先提交了真值注册表、分析策略和裁决器哈希，然后用固定镜像排空
原 252 单元矩阵。正式结果为 241 成功、11 失败、0 超时、0 人工介入、0 权限请求；原命令复跑
复用了全部 252 条唯一结果哈希。Operon 仍是开发集最强基线。候选 clean 未见导数 NMSE 中位数
`0.014638` 优于 Operon 的 `0.091415`，但 SNR20 主指标为 `6.717294`，显著差于基线的
`0.698001`；候选仅 82/84 成功，失败感知六系统中位相对改进为 `-1.704061`，系统级 bootstrap
95% CI 为 `[-4.116249, 0.292912]`。两次裁决生成相同文件哈希并返回 `negative_result`、
`gate_b_allowed=false`。按预注册停止规则，弱形式/支持稳定性机制族关闭，任务 259.5 和 259.6
不启动，也不围绕已揭示恢复未见系统继续调参。

---

## 24. 跨周期自主成果 campaign 增量

任务 260 按以下顺序执行：

1. `260.1` 建立独立 `autoresearch.campaign` 控制层，先解决单周期服务无法自动把负结果变为新
   假设的问题；
2. `260.2` 注册 `campaign start/resume/status/export`，让每轮研究报告、失败报告、实验指标、
   validation、evidence map、loop report 和论文版本成为强制可见产物；
3. `260.3` 以 provider-agnostic OpenAI-compatible 配置接入本地 Ollama `qwen3.5:9b`，并把
   competition 的真实执行/裁决器适配为 campaign round；
4. 若没有至少六个可信未揭示系统，或 72 小时开发门无法产生合格候选，立即进入 `260.4` 的本地
   自主科研系统对比矩阵，不把旧 MDBench 未见结果冒充新方法 holdout；
5. `260.5` 只在真实贡献门通过后构建论文、独立复现包和完整交付索引，外部提交保持人工门禁。

`260.1` 已实现逐阶段原子持久化和恢复。每个 round 记录 parent result、parent round manifest、
design、artifact 和 final decision 哈希；campaign manifest 再对所有 round manifest 建立 lineage
hash。proposal-time context 没有当前 unseen refs；如果 proposal 文本或证据引用泄露当前未见
引用，运行立即失败。负结果之后相同机制族也被拒绝。development 选择、最终 config、代码和
adjudicator 必须匹配冻结证据，未见结果不完整或含科研决策人工介入时不能通过 contribution gate。

`260.2` 已注册四个 campaign CLI，并把每轮 hypothesis、preregistration、experiment manifest、
raw metrics/logs、validation、failure/research/loop report、evidence map、表图、decision 和
manuscript version 写入 round manifest 的哈希链。export 会先复验 campaign 全链，再把内部产物
与 adapter 原始证据复制到带集中 `index.md`、环境锁、复现脚本和文件哈希的 dossier；任何内部
gate 都不会把 `external_submission_authorized` 改为 true。Vault 写入只维护当前 campaign 的
project index，不能重建无关条目。

`260.3` 已完成真实执行。结果盲审计排除历史 official/recovery 面板后找到 49 个未使用 ODE 和
8 个未使用 PDE，并冻结两组互斥的 6-ODE 未见面板。镜像
`autoresearch-mdbench:task260` 通过两个新机制的离线自测；本地 Ollama
`qwen3.5:9b` 通过 OpenAI-compatible JSON 烟测，正式轮次在结构化内容为空时按预注册使用
deterministic fallback，所有数值选择和裁决仍由代码完成。

正式 `task260-autonomous-ccfb-v1` campaign 完成两个各 240-cell 的新轮次，累计科研决策人工介入
为 0。第一轮 `noise_conditioned_ensemble_sindy` 的开发中位改进为 `0.779785`，正式未见系统级
95% CI 为 `[-3.053723, 0.953866]`；第二轮 `spline_group_sparse_sindy` 的开发中位改进为
`0.672083`，未见 CI 为 `[-2.157336, 0.921594]`。两轮的强基线、三种子和幂等复现完成，但 CI
下界均未大于 0，且 frozen ablation cells 分别有 2 和 3 个失败。两轮因此被不可变地关闭为
negative result，campaign 以 `stopped` 终止，lineage hash 为
`72fc5080f1058a095086f8f2c1a6135868d775ce8e1320d112b8618ac3944158`。完整 exporter 收录
1,289 个 manifest 文件并通过 SHA-256 integrity reproduction。

72 小时 Route A 判断已提前得到明确负结论：不重开已揭示面板、不降低置信门、不在同轮调参。
下一执行任务固定为 `260.4` 的 4 UCI + 6 MDBench、one-shot/execute-once/full-loop、三种子与
四项消融系统矩阵。`260.5` 只从真实证据构建论文和独立复现包，不会把上述方法负结果改写为
投稿就绪结论。

`260.4` 已按冻结次序执行。预注册哈希
`db4f372081be8ffb146a6acb133cdf7626618e4f94aae31aa1a4805b7d9e2da2` 绑定四个重新执行的
UCI run records、六个已揭示 MDBench trace summaries、10 项受控 workflow failure、三种模式、
四项消融、种子 211/223/227、evaluator SHA-256 与 20,000 次配对 bootstrap。该设计测量
`source integrity -> execution -> failure diagnosis -> bounded repair -> evidence gate -> report`
的系统行为；MDBench replay 不得进入方法贡献或新未见结果表述。

正式 210 个 primary cells 及其 210 个 deterministic reproduction 均完成。one-shot、
execute-once、full-loop 成功率为 `0.20/0.50/1.00`，full-loop 恢复率 `0.625`、复现率
`1.00`、错误声明 0、科研决策人工介入 0；相对 execute-once 的配对增益为 `0.50`，95% CI
`[0.333333, 0.666667]`。无 Vault、无失败反馈、无预注册、无证据门的成功率分别为
`0.70/0.50/0.00/0.80`，其中无证据门保留 6 个错误声明。三次本地 Qwen policy framing
调用有两次产生有效结构化输出，一次 180 秒超时并使用已冻结 deterministic fallback；所有成功
与 gate 数值均由确定性 evaluator 给出。结果哈希为
`5f69cac379409d1abf5cd682682f54d76d181dc7aaf45c021f525ac50a5830cb`，内部系统贡献门通过，
外部投稿仍为 false。下一任务 `260.5` 必须从全新目录独立复现、完成引用/审稿/表图一致性审计
并编译论文；若任一最终门失败，只能交付标注清楚的负结果或未就绪论文包。

`260.5` 已完成。新增 `campaign paper-build` 与 `campaign paper-status`，从不可变 Route A
lineage 和 Route B result/gate 生成 ACM 双栏正文、附录、五张矢量图、两张结果表、40 条引用、
claim-evidence graph、环境锁、arXiv source archive、完整 dossier 和逐文件哈希。首次 v1
构建因 Windows `pdfinfo.cmd` 包装器把 11 页 PDF 误判为 0 页而诚实返回 `not_ready`，未覆盖；
修正为原生 `pdfinfo.exe` 后，v2 的所有最终门通过。

全新目录复现重新验证冻结输入 SHA-256、复算 paired mean 与固定 seed 的 20,000-resample
bootstrap，并独立编译五张图和 11 页论文。主构建与独立构建的 PDF SHA-256 完全一致：
`9199a1146fce116b0035090dbca3df27dc38a4c740fb1f935f06c587317a4a3b`。包哈希为
`bd4a2b74c271d321c4b859e4f16004f9eb8cd1cc6de6409bb8d6c71eb4c194ac`，3,269 个文件全部
进入哈希清单。内部状态为 `ready_for_human_submission_review`，外部投稿许可仍固定为 false。

---

## 25. bounded-autonomy 冲刺与下一轮机制生成

任务 261.1 使用以下单命令边界关闭任务 260 的来源审计缺口：

```text
live literature
  -> local Qwen topic candidates and selection
  -> selected executable program
  -> frozen task matrix
  -> task-level deterministic inference
  -> local Qwen manuscript fields
  -> deterministic results/limitations/conclusion
  -> automatic ACM PDF
  -> autonomy audit
```

CLI 为：

```powershell
airesearcher campaign sprint-run `
  --sprint-id <id> `
  --brief "<high-level research objective>" `
  --deadline 2026-08-15
airesearcher campaign sprint-status runs/autonomous-sprints/<id>
```

运行使用 provider-agnostic OpenAI-compatible 配置。为避免原始 262K 上下文导致 8GB 工作站
CPU spill 与请求超时，本地 Ollama 别名 `qwen3.5-sprint:9b-8k` 复用同一
`qwen3.5:9b` 权重，只把 context 固定为 8192，并发送 `reasoning_effort=none` 与严格
`json_schema`。topic 与 manuscript 各最多两次调用；失败后 sprint 进入 `blocked`，不存在
deterministic topic/manuscript fallback。systems policy 同样要求 live local Qwen，任何 fallback
都会使自治门失败。

每个程序预先声明 baseline/candidate mode、主 endpoint、方向、最低独立任务数与机制理由。模型
必须从至少三个不同可执行程序生成候选；选中 program ID 后，主分析、统计方向和论文 endpoint
不能再改变。三个 seed 先在每个 task 内取平均，20,000 次 bootstrap 只重采样十个 task。代码
冻结 task 顺序、bootstrap seed、通过门和外部提交 false；LLM 不能解释 CI 是否通过。

自治账本记录八个顺序事件及父哈希，分别标注 `operator_prelaunch`、`local_llm` 与
`deterministic_policy`，并单独统计 prelaunch 选择、runtime manual research decision 和
fallback。只有 live local selection、三个可执行程序、所选程序控制主分析、task-level inference、
同一账本自动 PDF、零运行期人工科研决策和无外部投稿同时成立，才可返回
`bounded_autonomous`。Route A 同次生成与任意实验代码生成当前强制为 false，所以不可能返回
open-ended autonomy。

正式 `task261-bounded-autonomous-clean-v2` 一次命令完成，manifest hash 为
`eb3ac1c5411b4444e6512a5119ecff1afbbedb736ace12e2f7329d3e90c1e33e`，autonomy audit hash 为
`23e8333334f9e8cb01f8a60303a672a992b628fa94bcabb90851f433561cc360`。Qwen 在第二次合规选题
响应中选择 C003，正文一次响应成功，两个 fallback 标志均为 false。task-level endpoint hash
为 `e4535efd50c34c2d104b367dfa1fc3a7ba1dde51081d8b07738d8c68e9c03c52`，均值 `0.20`、
95% CI `[0.00, 0.50]`，贡献门失败。自动 PDF 为六页且物理门通过；这是一份 retained negative
artifact，不是 CCF-B 就绪论文。

下一任务 261.2 不得继续在已揭示十任务面板上挑机制。它必须读取上述 endpoint/parent hash，
由本地模型产生机制级差异和结构化代码变更，经静态安全审查、单测和开发集筛选后冻结实际代码
哈希，再使用新独立任务面板裁决。论文阶段必须为每个 named prior work 和重要方法/实验声明绑定
文献或执行证据。只有该完整因果链成立，才可升级“模型在预置程序中选题”为“模型产生并执行了
新机制”；任何失败保留为报告并进入下一轮，绝不通过改提示、改论文或降门槛制造成功。

Task 261.2.1 已完成可执行前置冻结。最终
`runs/manual-live/task2612-mechanism-foundation-live-v3/` 绑定 clean-v2 父证据、14-source
research brief 和外部投稿 false；foundation manifest、parent evidence、research brief hashes
分别为 `0f5c41b408e4de442874a1f4ea2bef45eedbc6f4f6c42e4e31d25cea57e8b456`、
`6ae565f23c963514d0c0ac7891a81244171749ca18604bcf734d3c704da652d5` 和
`9b9b492dcbb33e5d454f628ed06fe3982970fb8a79057f14f1dba0167dea45b0`。合同会 fail closed
于父哈希漂移、非负父结果、非机制修改、已揭示任务复用、面板重叠、代码审查/测试缺失、
reviewed/executed bytes 不一致、claim/evidence 类型缺失和外部投稿授权。

Task 261.2.2 已完成。配置化本地 `qwen3.5-sprint:9b-8k` 从冻结 brief 生成 parent-bound
诊断和一个 model-authored `structured_expression_v1` 机制程序；版本化编译器只提供固定、
非科研的 JSONL I/O/循环包装，模型表达式拥有全部机制信号、权重组合、阈值与接受规则。每次合法
或非法模型响应均单独留存；传输 schema 适配本地 grammar，但长度仍由本地 Pydantic fail closed，
且没有 code-side repair 或 fallback scientific result。

最终 `task2612-mechanism-development-live-v12` 的 manifest 为
`55c4604474517317114fa88fa389aced28ca5ba96f2eafee6832cfcceb24737e`。精确生成源码在开发
结果出现前通过静态安全、单测、含闭区间数值边界的性质测试、秘密/网络/路径检查和 Harness
sandbox smoke。三项 development tasks 共 24 条声明，接受 18 条且无 unsupported accept，
coverage `0.75`，结论为 `advance_to_preregistration`。六项 confirmatory tasks 的结果仍未
揭示，result artifact count 为 0；本任务没有科学 endpoint、论文或外部投稿授权。
共享执行器的最终防御纵深同时预检实际 `sandbox_runner.py` 和受审 `run.py`；冻结 v12 源码的
最终 replay episode hash 为
`62dce7261cf92c4535d23e24e5002bcdbf350a3286e7e3a83ff3800fff24b1c1`。后续 v13
模型输出虽满足结构 schema，却因极端无支持样本仍被接受而在 development 前被性质门阻断；
该失败被保留，且不通过重复抽样替换权威候选。

Task 261.2.3 已完成。`task2612-mechanism-confirmatory-live-v1` 在揭盲前冻结预注册
`1e499a27da3bbba08be9f7a2e47de06c5c49d216c96230d46388971ad3659464`、环境
`0198b9e7a8c13258d139ce4398162c6c272c491aa64ff3358aa63a06a67b1ea8`、Control Graph
`fe2d9e96b264d86b5ae87602dce4628c72de49019d17a48344cba8051b7fab44`、精确 v12 源码、
六项 source-fingerprint-disjoint 确认任务、20,000 次任务级 percentile bootstrap、coverage
下限 `0.60`、unsupported-risk 上限 `0.10` 和每任务一次的停止规则。所有执行节点均只尝试一次，
无网络、无 secret 环境键、无自适应变化。

六项 Harness 任务全部执行成功，共接受 28/48 条声明并保留 20 次 abstention。unsupported
accept 为 1，点估计 `0.0357`、95% 区间 `[0.00, 0.10]`，风险门通过；coverage 点估计
`0.5833`、区间 `[0.4792, 0.6875]`，低于预注册下限。因此唯一失败门是
`minimum_coverage_met`，终点为不可改写的 `negative_result`，endpoint hash
`d449343654e28a4da877d0ab7a3bd07e334ac8cad310385996c635bacbae165d`。evaluation/security、
provenance-v2 claim trace、Event Journal seal、独立干净目录重算和 pre-reveal rollback rehearsal
全部通过；终态 220 个文件的再次运行为零变化幂等加载。外部投稿仍为 false。

Task 261.2.4 已完成。`campaign mechanism-paper-build --live-sources` 从上述冻结因果链生成
child round report、完整 manuscript、5 个 source-backed figures、1 个六任务表和 PDF；权威
package 与独立重建目录分别为 `task2612-mechanism-paper-live-v1` 和
`task2612-mechanism-paper-reproduction-live-v1`。终态 manifest
`462c428dc1c863407042ae48ad1cb2245a942ba0af93744a0022804eeb26bcc8` 绑定 endpoint
`d449343654e28a4da877d0ab7a3bd07e334ac8cad310385996c635bacbae165d` 与 scientific projection
`fed38ff7a08f12562eae1488bbc951561d3279d1e181f3b89a830e13d2ddf6f9`。

生成器把 51 个材料段落登记为类型化 claims，并用 26 个 evidence records 和 77 条 links 覆盖
全部 named work、方法、实验、结果、限制和 figure descriptions。14 个冻结来源的 live
reachability、inline/reference/named-claim 三重覆盖以及四类 adjacent-work breadth 全部通过；
5 图 1 表的来源、caption、正文引用和 endpoint 数值一致。独立构建逐文件匹配 24 个确定性 source
artifacts；两份 PDF 均为 13 页，主稿含 2,512 words、14 references、0 overfull boxes，且完成
13 页视觉检查。

最终状态是 `negative_result_paper_built`，不是 positive contribution。paper audit 的
`scientific_submission_gate`、`authorship_review`、`license_review` 和
`explicit_human_approval` 仍为 false，因此 submission readiness 与 external submission
继续为 false。同一确认面板永久禁止调参；若未来继续改机制，必须另开新一轮开发集和独立确认面板。
Task 261.2 的工程闭环至此完成。

---

## 26. vNext 渐进重构执行计划

### 26.1 执行策略

本轮不做框架替换式重写。现有 Competition、Campaign、Sprint、EvidenceGraph、AuditLog、
Obsidian Vault、科研负结果和审批门继续工作；新内核先以无调用方的领域契约落地，然后经历
shadow-write、characterization 对比、单 vertical slice 切换和逐服务迁移。

执行顺序固定为：

```text
contracts
  -> append-only journal / replay / fork
  -> HarnessSpec and episode package
  -> LoopSpec and durable Control Graph
  -> provenance/evidence and Vault projections
  -> Open Science exporters
  -> Competition / Campaign / Sprint migration
  -> evaluation, security, dependency upgrade, deprecation
```

所有领域 schema 位于供应商中立的 `autoresearch.kernel`。LangGraph 首先只是 runtime adapter，
不得把其 checkpoint 类型、Agent SDK 类型或模型供应商类型写入科研事件和 Vault。当前
LangGraph/LangChain `^0.2.0` 不直接升级；先冻结 resume、interrupt、subgraph、parallel、
idempotency 和 serialization 的 characterization tests，再单独迁移依赖。

### 26.2 任务与验收门

| 任务 | 交付 | 硬门 |
|---|---|---|
| 262.1 | 交叉检索、差距矩阵、架构决策、任务拆分 | 计划/任务/问题日志一致，引用和 dependency JSON 可验证 |
| 262.2 | `RunEvent` 与四平面 Graph contracts、canonical hash、JSON Schema | 重复/悬空/跨平面/tamper 非法输入 fail closed；全量回归零行为变化 |
| 262.3 | 原子 journal、sequence、幂等、hash-chain、terminal seal、replay/fork | 故障注入、并发、断链、重复副作用和终态追加测试通过 |
| 262.4 | HarnessSpec、provider/tool/context/memory/verification policy、episode package | mock 与 opt-in live smoke；预算、权限、invalid schema 和模型不可用保留真实终态 |
| 262.5 | LoopSpec、Control Graph、approval/retry/compensation/stop/pivot/resume | 崩溃恢复、人工拒绝、预算耗尽、负结果转向和 holdout 阻断通过 |
| 262.6 | W3C PROV/PROV-AGENT/Evidence v2 与 Vault 投影 | 一个真实 round 的 agent/activity/entity/claim 全链查询与篡改阻断通过 |
| 262.7 | RO-Crate/Workflow Run/PROV、CodeMeta/CFF/CRediT/SPDX/SLSA 导出 | profile、离线复现、许可/贡献一致性和敏感信息扫描通过 |
| 262.8 | Competition、Campaign、Sprint 逐一迁移 | 旧/新 endpoint、gate、artifact、failure 一致，旧 scientific hash 不变 |
| 262.9 | task/trial/trajectory/outcome eval、OTel、Agentic security fault matrix | promotion 同时满足 outcome、evidence、security、cost 和重复试验门 |
| 262.10 | LangGraph/LangChain 升级、兼容窗口、旧路径弃用、rollback rehearsal | 两个真实 vertical run、全量质量门、独立复现与回滚演练通过 |

### 26.3 已完成的内核切片：262.2—262.7

`262.2` 只新增纯 Pydantic/标准库契约和测试，不修改现有服务写路径。最小交付包括：

- `GraphPlane`：`control`、`provenance`、`knowledge`、`evaluation_policy`；
- `GraphNode`、`GraphEdge`、`GraphSnapshot`：稳定 ID、类型、plane、属性和引用完整性；
- `RunEvent`：schema version、run/task/event ID、UTC 时间、sequence、actor、type/status/action、
  parent ID/hash、artifact refs、decision/approval、idempotency key、payload 和 canonical hash；
- validators：JSON 可序列化、UTC、唯一 ID、端点存在、边与节点同平面、控制自环/环策略、hash
  round-trip 与 tamper detection；
- JSON Schema 与 deterministic serialization 测试。

`262.3` 在上述契约上增加纯本地 journal，仍不修改 Campaign、EvidenceGraph 或依赖版本。其磁盘
协议使用 `metadata.json`、连续序号事件文件、独占 writer lease、pending 临时目录和确定性
`terminal-seal.json`。提交路径先写新临时文件并 `fsync`，再在同目录原子替换；读取路径逐文件验证
canonical bytes、schema、event hash、sequence、parent hash、幂等键、lineage 与 terminal seal。

recovery 只在持有 lease 时丢弃未提交 pending 文件；若 terminal event 已提交而 seal 尚未写入，则从
已验证 lineage 重建同一 seal。checkpoint/replay 只消费验证后的 prefix；fork 只在新目录创建新 run，
首事件必须引用冻结的父 checkpoint，非终态 fork 需要显式 policy。敏感扫描在任何写入前覆盖完整事件
信封。33 个 focused/fault/property tests、临时文件系统 smoke、811-test regression 和全量
Ruff/Mypy 已通过。旧服务继续权威，shadow adoption 留给 `262.8`。

`262.4` 在 journal 上增加 provider-neutral `HarnessSpec`、adapter/grader protocols、单 trial
`HarnessRunner` 和 content-addressed `EpisodePackage`。task、context、model、tool、memory、state、
permission、verification、observability、failure-attribution、cost、entropy/intervention 与
evaluation policy 全部显式版本化；episode 分离记录 task/spec、trial、trajectory、environment
outcome、grader、cost、intervention、approval、failure、tool call、artifact、terminal event、seal
与 lineage。preflight、model result、grader 和 package 在持久化前做敏感内容扫描；blocked/failed
路径不携带伪造的 structured scientific output。deterministic fixture 与现有 configurable
OpenAI-compatible client 共用同一 domain contract，本地 `qwen3.5-sprint:9b-8k` live smoke 已产生
sealed success episode。31 个 focused tests、1 个真实 live test、824-test regression、全量 Ruff
与 140-file Mypy 已通过；旧服务、依赖和已有状态继续不变。

`262.5` 在同一 journal contract 上增加 content-addressed `LoopSpec`、确定性
`ControlGraphRuntime` 与 content-addressed `LoopRunSnapshot`。node/edge/guard、预算、retry、
approval、compensation、stop/pivot/escalation、holdout visibility 和 terminal status 全部显式
版本化；node side effect 在执行前获得并持久化稳定 idempotency key，resume 只回放 journal，terminal
event 后 seal 前崩溃可重建同一 seal。模型的下一图提案只进入记录，不能替换冻结图、计算 scientific
gate、扩展 permission 或批准 release。

薄 `LangGraphControlAdapter` 只驱动 domain runtime，不能成为第二状态源。当前锁定的 LangGraph
0.2.76/LangChain Core 0.2.43 已通过 checkpoint/resume、static/dynamic interrupt、subgraph、
parallel superstep、idempotency 和 JSON serialization characterization，未升级依赖。一个保留的
development vertical 通过 verified `EpisodePackage` 把 Harness 接入 Control Graph，产生 2-event
sealed episode journal、6-event sealed loop journal 和 content-addressed success snapshot。24 个
focused tests、32-test legacy/new collection compatibility matrix、848-test regression、全量 Ruff
与 142-file Mypy 已通过。Competition、Campaign、Sprint 仍由旧路径权威执行，cutover 留给 `262.8`。

`262.6` 增加 content-addressed `ProvenanceBundle` 与显式的 Entity/Activity/Agent、
Usage/Generation/Derivation/Association/Plan、Claim/Evidence/Counterevidence、Validation/Decision、
ToolInvocation 和 digest-only model-interaction contracts。bundle 对稳定 ID、UTC valid time、version、
revision/invalidation、引用、source snapshot、生成活动、责任 Agent 与 canonical hash fail closed；
`require_claim_trace()` 必须同时解析 source/input、activity、冻结 code/software 或 deterministic
policy Agent、artifact、当前 validation 和生成的 decision artifact。旧 `EvidenceGraph` v1 未改写，
而由兼容投影继续服务现有 reader。Vault 投影必须收到显式批准 ID，只生成带 wiki-link、event ID、
artifact hash、confidence、validity 和 supersession 的 source-anchored Markdown。

确定性 campaign fixture、v1/Vault compatibility matrix 与真实
`task260-autonomous-ccfb-v1/round-001` 查询均已通过。真实 smoke 只验证既有 frozen artifacts，没有
重跑或重解释科学实验；它生成 bundle hash
`a2e54556b3f6e242deeaff3d7c87400ae23e701ef034983fb6964a3c2df4c782`，阻断嵌套篡改和缺失 gate
generation，并在隔离 Vault 中写入 12 条批准投影。全量 858 tests、7 skips、86% coverage、Ruff 与
145-file Mypy 通过。该切片本身没有生成 Open Science research object；后续 `262.7` 独立完成
许可/隐私/public-view 边界，旧服务迁移仍由 `262.8` 负责。

`262.7` 在现有 reproducibility package 旁增加 `reports.open_science`，不替换旧目录或 writer。
exporter 只接受完整校验的 provenance-v2 bundle、显式 artifact policy、统一 metadata 与冻结 JSON
assertions；源 hash 漂移、非法 path、未知 CRediT role、DOI/ORCID/SWHID 不一致、secret-like 内容和
public approval/license/privacy 缺口全部 fail closed。每个 view 生成 RO-Crate 1.3 + WRROC/WROC
兼容 JSON-LD、PROV JSON-LD、workflow、CodeMeta/CFF/CRediT/DataCite、SPDX 3.0.1、unsigned
SLSA-v1、README、export policy、reproduction plan、hash manifest 与 validation report。internal
可以保留 canonical bundle，review 使用确定性 JSON 脱敏，public 必须有 scope-matched 人工批准和
显式开放许可产物；任何导出都不执行 upload、DOI mint、publication 或 submission。

真实 `task260-autonomous-ccfb-v1/round-001` opt-in smoke 保持 bundle hash
`a2e54556b3f6e242deeaff3d7c87400ae23e701ef034983fb6964a3c2df4c782`，校验七个原始 artifact，
在隔离目录重算四个被断言文件并通过六个冻结负结果/决策断言。review 不含内部 bundle 或私有路径，
public 因缺少批准和 public artifact 正确不生成。`rocrate-validator` 0.11.2 对 Workflow RO-Crate
1.0、Process/Workflow/Provenance Run 0.5 的 required checks 全部通过，WROC recommended 也零问题；
其余 recommended 仅剩 packaged workflow 相对文件 ID 与 HTTP-ID 建议冲突的两个 advisory。
validator 尚无 RO-Crate 1.3 profile，因此没有把旧 base-profile 结果冒充 1.3 外部验证；内部 1.3
contract 与官方规范单独校验。官方 CFF 1.2.0 与 SPDX 3.0.1 JSON Schema 均为零错误。8 个
focused tests、1 个真实 smoke、866-test regression、全量 Ruff 与 146-file Mypy 通过；旧服务迁移
仍由 `262.8` 负责。

### 26.4 迁移与回滚

每个旧服务按四步迁移：

1. **characterize**：冻结成功、负结果、blocked、failed、resume 与 terminal-idempotent fixture。
2. **shadow**：旧路径仍执行，新路径只记录标准事件和投影；逐事件/逐终态比较。
3. **vertical cutover**：feature flag 只切换一个完整流程，旧状态文件仍保留。
4. **promote/deprecate**：连续两个正式 run 等价后才停止旧写路径；兼容 reader 保留一个版本窗口。

任何 mismatch 都回滚 feature flag，并在 `Problem.md` 记录 old/new event、终态、artifact 与 gate 差异。
禁止用重跑已揭示 scientific panel、改变阈值或重解释历史结果来制造等价。

`262.8.1` 已按上述四步完成 Competition 切片。冻结 corpus 覆盖 complete、negative-result、
access-blocked、failed-after-plan、blocked-then-resumed 和 terminal-idempotent 六类语义；默认
`legacy` 路径零迁移写入。显式 `shadow`/`vnext` 模式为每个不同 source fingerprint 创建一个封印
`EventJournal` 和一个 acyclic Control Graph，并生成七项 parity checks。恢复调用以 fork anchor
连接前一个 blocked seal，未变化终态不新建 invocation。

切换由 `AUTORESEARCH_COMPETITION_MIGRATION_MODE` 控制。`vnext` 在运行科学代码前要求 promotion
ledger 中已有两个不同 formal ID 和 legacy run ID 的完整等价 shadow vertical，并重验报告 hash、
event lineage、seal、projection 与 graph；旧 compatibility manifest/artifact writer 和 reader
仍保留。真实本地 fixture 的两个 formal run、一个 vNext-authority run 和一次 legacy rollback
全部通过，且明确不代表官方 MDBench Gate A。

`262.8.2` 随后按同一协议完成 Campaign，但重新冻结 Campaign 自己的语义而不复用 Competition
evidence。默认 `legacy` 模式零迁移写入；`shadow`/`vnext` 为每个不同 observation 记录所有持久化
stage、finalized round、aggregate/per-round contribution gate、artifact、终态、intervention 与
digest-only failure，封印 journal 并生成无环 Control Graph。失败后 resume 以绑定旧失败 seal 的
child journal 继续；不变终态只重验原 lineage 并产生 idempotency report。

Campaign promotion 在任何科研执行前要求两个不同 formal ID 和 Campaign ID、完整两轮实验、最终
`CONTRIBUTION_READY` 且七项 parity 全通过，并重新验证 formal report hash、journal lineage/seal、
projection、source fingerprint、graph 及全部 legacy/Vault artifact。两个 formal shadow Campaign、
一个 vNext-authority Campaign 与 legacy rollback 已在 generated local fixture 上通过；该 fixture
只证明迁移，不是官方 benchmark 或 publication-ready result。当前 Campaign executor 不生成
`BLOCKED`，冻结 blocked case 只验证旧 schema/reader 的 hash-valid compatibility state。下一提交只
迁移 Sprint；Competition/Campaign compatibility writer、依赖版本与 submission authority 仍不变。

`262.8.3` 已按相同协议完成 Sprint，但重新冻结 Sprint 自己的 complete、negative-result、blocked、
failed、resumed 与 terminal-idempotent 语义。默认 `legacy` 模式零迁移写入；`shadow`/`vnext` 将每个
既有 autonomy event、topic/experiment/inference/manuscript/paper/audit stage、artifact、gate、
intervention 与终态写入封印 journal 和无环 Control Graph，并在 event、terminal、scientific
endpoint、gate、artifact、failure、intervention 七个维度 fail closed。恢复调用 fork 前一
blocked/failed seal；相同 source fingerprint 只产生 idempotency report。逻辑 manifest fingerprint
只排除 `updated_at`、`manifest_hash` 与原始 failure 文本，避免把时间戳重写误当新科研调用。

切换由 `AUTORESEARCH_SPRINT_MIGRATION_MODE` 控制。两个不同 formal ID/Sprint ID 的完整 shadow
Sprint 才能打开 vNext；科学负结果可以成为正式迁移证据，但必须同时满足论文编译/质量、bounded
autonomy 必需检查、完整 artifact/Vault note、零 fallback、零运行后人工科研决策和禁止外部投稿。
opt-in adoption smoke 只读采用现有 `task261-bounded-autonomous-clean-v1/v2` 两个完成负结果，未重跑
模型、文献、实验或论文；随后以现有 `task261-bounded-autonomous-live-v1` blocked 状态验证 vNext
投影与 legacy rollback。返回值和投影相等、journal 不变、compatibility files 保留、迁移 JSON 无
私有绝对路径。Competition、Campaign、Sprint 均已通过 M1，但三个 legacy writer/reader 继续保留到
`262.10`；本切片没有升级依赖、删除旧状态、重解释科学结果或解锁发布/投稿。

`262.9` 在 M1 的三条可逆迁移路径之后增加一个共享、provider-neutral 的 evaluation plane。
`EvaluationTaskRecord` 冻结 protocol、holdout 和外部 benchmark opt-in；每个 trial 只引用已封印
episode/trajectory、环境 outcome、rubric/grader、cost 和 failure slice。报告分别计算 system
verdict 与 scientific verdict，不把科学阴性结果改写成运行失败，也不让一次最佳结果掩盖重复性。
所有嵌套结果在 promotion 前重新验证 canonical hash、validator 结论、独立 episode、grader
独立性、Wilson 区间和 rollback 条件。

本地门分两组执行：五维 regression 覆盖 protocol match、evidence match、scientific core、
replay fidelity、holdout integrity；十类 fault matrix 覆盖 goal hijack、tool misuse、
identity/privilege、supply chain、unexpected code、memory poisoning、runaway loop、evaluator bias、
holdout leakage 和 evidence mismatch。任何 required case 缺失、`unknown`、成本未知/超限、
holdout 泄漏、grader bias 或 evidence mismatch 都是不可补偿的硬失败。外部
ScienceAgentBench/CORE-Bench/MLE-bench/AgentDojo/METR 类长任务默认禁用，只能显式 opt in。

OpenTelemetry 导出器固定 core semconv 1.43.0、GenAI semconv 提交
`d74a9bbc419c67dd78ea4fcc26280381ef0bb9db` 和 OTLP 1.11.0，只允许本地原子 JSONL。
OTLP 永不写 prompt、response、tool argument/result 或 grader explanation 原文；敏感 metadata
摘要化。原文旁路必须有 scope-bound、带过期时间的显式 grant，并写入独立本地 root。首次 adoption
smoke 只读采用两个既有真实负结果 Sprint，五维 regression、十类 fault 和全部 promotion 门通过，
评测/fault/regression/OTLP hash 分别为 `b5e21a0a93e1b3caa96f4a5f5bf7ec637a09bf97305d39e9d26164324ea6d1ee`、
`53f182bb856d702b5ee1bd90ec5384369ee43e6dc0910f2e15419cd972560f73`、
`c2a466d01aa703d5c62a8eb47131aec0dbcc95bd424033507f67b540f14ba33c` 和
`86236e468ad1a3dce58acbb02ae8054a857aee45b53f8d5becec43bb2c171e85`；没有重跑科研过程或保存
raw payload。

`262.10` 在冻结兼容测试下把 LangGraph 0.2.76/LangChain 0.2.17/Core 0.2.43 升级为
LangGraph 1.2.10/LangChain 1.3.14/Core 1.5.2，并精确审计 checkpoint 4.1.1、prebuilt 1.1.0、
SDK 0.4.2 与 LangSmith 0.10.11。`DependencyLockAudit` 同时比较必需、锁定和安装版本并绑定
`poetry.lock` SHA-256；`VNextReleaseReport` 再把旧/新 characterization、两个不同 formal
vertical、rollback、独立复现、兼容路径、schema 窗口、能力矩阵和人工审批边界组成内容寻址 R1
决策。任何 hash/version/result 漂移、证据复用、reader 提前删除、兼容决策变化或受保护权限打开都
fail closed。

LangGraph 1.x 的 checkpoint/resume、static/dynamic interrupt、subgraph、parallel superstep、
resume idempotency 和 JSON serialization 均通过；MemorySaver 明确禁用 pickle fallback 和自定义
module allowlist。当前没有持久化 LangGraph checkpointer，旧线性 workflow JSON checkpoint 不做
批量迁移且进入弃用兼容窗口。浅 `AuditLog` 的 JSONL 主 writer 被替换为 canonical Event Journal，
首次写入时只读导入旧 JSONL 并保持源文件不变；显式 export 支持隔离 rollback consumer。Competition、
Campaign、Sprint 与 EvidenceGraph v1 writer/reader 因仍承载科学执行或活跃 reader 语义而保留，
schema 政策固定为 current writer / current-plus-one reader。

两个 fresh opt-in smoke 在新目录重新采用两个不同真实负结果 Sprint、验证 sealed journal/parity、
执行 vNext→legacy rollback、审计依赖、重跑 LangGraph characterization，并由独立 `python -I`
干净进程无网络复现 canonical evidence。dependency audit、rollback 和最终 R1 report hash 分别为
`2e31dccf9c69af830bc0dfb8337085138ec633357e525ae0aa401b15af9a6fab`、
`9d456335a4e2218fdc95baaafec801d118c39cc4b3fd09f0a512d564d1a7e01f` 和
`acf73733022a59e3aaca2fd3b0dfd66fe88ba3c140a23a4a4a9a816715f9a638`。全量 946 tests、
13 skips、87% coverage、152-file Mypy 与 repository-wide Ruff 通过；公开发布、投稿、无限制执行
和安全策略自修改仍关闭。

### 26.5 验证命令层级

每个子任务先运行新增模块和 characterization 的 focused tests，再运行：

```powershell
python -m pytest tests -q
python -m ruff check src tests
python -m mypy src\autoresearch
git diff --check
```

涉及 provider、外部数据、RO-Crate validator 或真实 runtime adapter 的任务必须另加 opt-in live smoke；
mock 只能用于 CI，不能代替首次真实验证。真实 smoke 所需 secret 只从用户提供的 `.env` 读取，不写入
事件、Vault、日志或仓库。

### 26.6 里程碑

- **K1（契约，2026-07-28 已通过）**：262.2 的 31 个 focused/property tests、778-test
  regression、全量 Ruff/Mypy 和 schema/import smoke 通过；旧服务、依赖和持久结果零变化。
- **K2（可恢复事件，2026-07-28 已通过）**：262.3 的 33 个 focused/fault/property tests、
  临时文件系统 smoke、811-test regression 和全量 Ruff/Mypy 通过；可确定性 replay/fork，旧服务
  写路径零变化。
- **H1（有界 Harness，2026-07-28 已通过）**：262.4 的版本化 policy、sealed episode、
  deterministic fixture、真实本地 Qwen smoke、824-test regression 与全量质量门通过。
- **L1（持久 Loop，2026-07-29 已通过）**：262.5 的冻结 LoopSpec、journal-only replay、
  idempotent recovery、approval/retry/compensation/pivot/escalation/holdout fault matrix 与
  LangGraph characterization 通过；一个开发 fixture 已在统一 Harness/Control Graph 上完成并双重封印。
- **G1（证据图，2026-07-29 已通过）**：262.6 的 W3C PROV-aligned bundle、EvidenceGraph v1
  compatibility、批准制 Vault projection、真实 round 查询与篡改阻断通过。
- **O1（开放科研对象，2026-07-29 已通过）**：262.7 的真实负结果 round 已导出为经 profile、
  许可、隐私、hash 和独立 assertion replay 验证的 internal/review research objects；public view
  保持审批关闭，G1 的内部 provenance bundle 未被冒充为公开 RO-Crate。
- **M1a（Competition 迁移，2026-07-29 已通过）**：262.8.1 的六类 characterization、
  逐项 parity、两个 formal shadow vertical、vNext authority vertical 与 rollback 已通过；旧
  compatibility writer/reader 仍保留。
- **M1b（Campaign 迁移，2026-07-29 已通过）**：262.8.2 的 Campaign-specific 六类
  characterization、stage/round parity、两个 formal shadow vertical、vNext authority vertical
  与 rollback 已通过；旧 compatibility writer/reader 仍保留。
- **M1c（Sprint 迁移，2026-07-29 已通过）**：262.8.3 的 Sprint-specific 六类
  characterization、全 lifecycle parity、两个真实负结果 formal shadow observation、一个
  vNext-authority blocked projection 与 rollback 已通过；没有重跑或重解释既有科研执行。
- **M1（迁移，2026-07-29 已通过）**：262.8 通过，Competition、Campaign、Sprint 均完成
  可逆等价迁移；legacy writer/reader 保留到 262.10 的兼容窗口。
- **E1（统一评测与安全门，2026-07-29 已通过）**：262.9 的内容寻址评测报告、五维本地
  regression、十类 Agentic fault、独立重复门、科学/系统双结论、默认脱敏本地 OTLP 和真实持久化
  证据 adoption smoke 通过；昂贵外部 benchmark、raw payload 和发布权限仍默认关闭。
- **R1（内部兼容发布，2026-07-29 已通过）**：262.9—262.10 的精确依赖/行为冻结、两次真实
  vertical、独立干净进程复现、rollback rehearsal、current-plus-one reader 窗口和机器化能力矩阵
  通过；公开发布、投稿、无限制执行与安全策略修改权限未解锁。

这些里程碑提升的是可审计性、可恢复性、互操作性和科研因果完整性，不自动升级
`bounded_autonomous` 为开放式自主科学，也不解锁 Gate B、公开发布或外部投稿。

## 27. 可发表性恢复实施计划（Task 263）

### 27.1 目标与判定原则

Task 263 不再把“生成完整论文”作为主循环目标，而把最小产出单位定义为
`Executed Claim Packet`：预注册假设、强 baseline/null、精确 intervention、代码/数据/环境、重复
执行、效应与区间、失败记录、provenance 和独立 replay verdict。稿件只从通过验证的 claim packet
生成只读视图。

可发表性采用不可补偿合取门：

```text
Novelty
AND empirical validity
AND independent confirmatory evidence
AND reproducibility
AND evidence coverage
AND robustness / null controls
AND independent human review
```

LLM reviewer、idea score、总分、workshop 历史接收率、运行成功或 PDF 构建均不能替代其中任何一项。

### 27.2 子任务顺序

| Task | 实施内容 | 硬完成门 |
|---|---|---|
| 263.1 | 交叉检索 AI Scientist/benchmark/方法/Open Science；审计本地失败；冻结恢复路径 | primary/official 来源实时核验；任务、计划、Vault 与 Problem/Agent 同步 |
| 263.2 | 增加 `ResearchQuestionCertificate`、`ResearchOpportunity`、`PortfolioSpec` 与合取门合同 | deterministic schema/hash/tamper/leakage/diversity/budget/publication-boundary tests；全量质量门 |
| 263.3 | 对至少三条独立研究 track 运行真实 opportunity tournament | 每条有 nearest-work matrix、baseline smoke、power/sensitivity、cost、许可和 disjoint-panel 证据；可以全部不通过 |
| 263.4.0 | 在复现前审计 task/evaluator/data/license 与 endpoint-specific exact power | 逐任务客观性与可取得性合取门；配对二元终点精确功效；失败即 reproduction diagnosis，不启动 novelty |
| 263.4.1 | 重建充分功效、完全开放、客观的多来源任务面板 | 当前冻结敏感性要求至少 60 个独立任务、至少两个 family、确定性 evaluator、许可/数据/算力与 disjoint split 全通过 |
| 263.4.2 | 对合格面板 clean-room 复现强 baseline，并冻结搜索策略因果实验 | baseline claim/code/data/env/command/seed/raw prediction/metric/tolerance 一致；四臂、五消融、预算、随机化、stop rule 和 sealed panel 在结果前冻结 |
| 263.5 | 运行 budget-matched 多分支、多保真 development search | 至少 8 个候选、3 个机制族和 1 个 null/rule arm；全分支/失败/成本保留；低/高保真校准与因果 ablation 完整 |
| 263.6 | 运行未揭示 panel 的独立确认与 clean-room replay | 无 leakage/事后改门；任务级效应、区间/功效、多重比较、null 和 reproduction 门由确定性代码裁决 |
| 263.7 | 构建 claim audit、paper 和 Open Science research object | 合取门全通过或忠实阴性；公开发布、署名、许可、venue 与投稿仍需显式人类批准 |

每个子任务单独验证、更新 `Agent.md`/`Problem.md` 并做 focused commit；父任务只有在所有子任务有真实
端点后才能关闭。

### 27.3 263.2 最小实现边界

首个代码切片只增加 provider-neutral、内容寻址的前端科研合同，不调用模型、不运行科学实验，也不修改
Competition/Campaign/Sprint 既有结果：

- `ResearchQuestionCertificate` 冻结一个主 claim、mechanism、falsifier、failure update、minimal test、
  metric/effect、baseline/null/ablation、power、budget、data split、source IDs 和 publication endpoint。
- `ResearchOpportunity` 绑定 verified sources、nearest-work delta、baseline reproduction plan、数据/
  许可/算力、独立单位和 disjoint development/confirmatory IDs。
- `PortfolioSpec` 要求至少三个不同 mechanism families、一个 null/rule arm、分级 fidelity、总预算、
  survival rule、全分支保留、无 sealed evidence visibility 和最多一个 confirmatory claim。
- `OpportunityAssessment` 与 `PortfolioAssessment` 只输出逐项 hard gate 和 blockers；不使用加权平均，
  不让模型或 Reviewer 自行把 false 改成 true。

JSON Schema、canonical hash、加载后重验、嵌套篡改、重复/重叠 task、预算不足、候选同质、null 缺失、
功效缺失、未复现 baseline、confirmatory leakage、事后 publication route 切换和任何
`external_submission_authorized=true` 都必须 fail closed。

`263.2` 已完成。`src/autoresearch/research/portfolio.py` 提供 16 个严格合同/记录类型和确定性 JSON
Schema；schema bundle SHA-256 为
`47cf6a3f5c0a2cd52dfaf5f6427dfbf71efde272671de74464a6aa0e84797629`。`track_selection`
允许 baseline smoke + reproduction plan，但 `novelty_search` 额外要求 clean-room、
independent-runner、within-tolerance 的 reproduction evidence。Portfolio 只有在后者的全部合取门通过
后才能构造，并强制 8—16 branches、三个 mechanism families、null/rule arm、唯一 branch evidence/
delta、F0—F3、非递增 survivor、exploration quota、预算上界、完整 branch retention、单
confirmatory claim 和 sealed-evidence 不可见。

16 个 focused unit/property tests 覆盖 schema/hash/round-trip、输入顺序、disjoint panel、power count、
nested/in-memory tamper、外部权限、机会阶段、source/baseline binding、diversity、null、budget、
fidelity、blocked opportunity、sealed evidence 和结果后 route change。完整 999-test regression、
17 个 opt-in skips、87% coverage、repository-wide Ruff 和 159-file Mypy 通过。该纯合同切片不访问外部
来源，故没有适用的 live smoke；`263.3` 必须运行真实来源、仓库和数据机会审计。

### 27.4 263.3—263.6 实验设计边界

机会 tournament 的至少三条 track 初始建议为：

1. AutoResearch 搜索策略因果研究；
2. 自动神经算子发现独立复制与角色/多保真消融；
3. 一个低成本、客观 evaluator、许可清晰的算法或数据分析 discovery lane。

选择发生在结果前，使用时间截断文献、nearest-work 差异、baseline reproduction feasibility、独立单位、
功效、算力和 publication endpoint。Search-policy track 是当前第一优先，但可以在 opportunity hard
gate 中被否决；不能硬编码成必选结果。

`263.3` 已完成一次不硬编码 winner 的真实 opportunity tournament。新增 8 个内容寻址合同，把
Task 263.2 的机会合同绑定到 source/repository/data/license probes、baseline execution smoke、
prospective power/sensitivity、资源可行性和无加权总分的确定性排序。live smoke 核验 11/11 个论文
主来源、9/9 个仓库/数据/许可端点，并重新执行 Task 260 的 210-cell 系统基线断言。

| Track | Gate | Baseline smoke | Data | License | Compute | Prospective power | 决策 |
|---|---:|---:|---:|---:|---:|---:|---|
| `track.search-policy-causality` | true | true | true | true | true | 0.822982 | 仅进入 263.4 clean-room baseline reproduction |
| `track.neural-operator-replication` | false | false | true | true | false | 0.822982 | 本机 8 GB 级 GPU 不满足发布方 16 GiB/RTX 4080 级预检与约两天完整 campaign |
| `track.sequential-falsification` | false | false | true | false | true | 0.822982 | POPPER 公开仓库未识别到软件许可证，baseline 按 fail-closed 未执行 |

三条 track 均冻结 12 个确认单位；`0.822982` 只是给定预设单位标准差时的结果前设计敏感性，不是经验
功效或贡献证据。报告 hash 为
`de4769b74098650a1ed7a7f92fdd853459f468d5a35e4b6d152f0169779bf0ff`，manifest hash 为
`db810365f362de9fb06d541a7db1fc1634c1bed06d0f5b5b446e8b01a76ca932`，8-schema bundle hash 为
`5609a30f5d4c9900aa8e500bcb61f4f222e7e3de553a9c81ca996239cfffe5d0`。该轮没有进入 novelty search、
揭示确认结果、调用付费模型、租用云 GPU、公开发布或授权投稿。

`263.4.0` 已完成 selected-track 的 endpoint-specific 审计。此前 `0.822982` 是 tournament 阶段的
通用连续近似，不能作为冻结配对二元主终点的功效证明，已由 two-sided exact McNemar 枚举取代：

| p(favorable) | p(unfavorable) | SESOI | n=12 exact power | n for 80% power |
|---:|---:|---:|---:|---:|
| 0.25 | 0.00 | 0.25 | 0.054402 | 31 |
| 0.30 | 0.05 | 0.25 | 0.080152 | 45 |
| 0.35 | 0.10 | 0.25 | 0.095619 | 60 |

独立单位只能是科研任务；seed/trajectory 是单位内重复。确认面板采用冻结敏感性中最保守的
`n>=60`，且不得报告 observed power。

实时 official-source smoke 固定了 102 行 ScienceAgentBench 元数据 CSV
`7f490f17f721a9c7e9415d3608a1a37d1a5315a26862cf556e3096ac4062face`，并审计原先 4+12 个 ID。
确认集精确构成为 9 个图像输出、3 个 CSV/NPY 输出；README 明示图像评测依赖 GPT-4o。GitHub 公开树
只有通用 evaluation harness，没有所选 task-specific evaluator；Hugging Face 公开树只有元数据和
verified Parquet，没有完整 `benchmark_verified.zip`；外部 SharePoint 入口没有向匿名探测返回可下载
数据包。故 16 个任务当前均不能同时证明完整数据、评测器源代码和确定性，baseline 按前置门未执行。

新增 6 个内容寻址合同把 task audit、exact power、完整或 pre-execution baseline binding、feasibility
report、四臂五消融 preregistration 和 artifact manifest 固化为不可补偿合取门。live report 状态为
`blocked_reproduction_diagnosis`，hash
`7c4d06eb82eabb250cf1b509242480bf27f079f65eaec6fbe564593c54b4aa3c`，manifest hash
`1d18b358d9b537ad083095d9897b542d6a1a8870b3b7393e6d017a41a1582a43`。它没有读取 gold/result、执行
baseline、启动 novelty、揭示确认结果或授权 release/submission。

`263.4.1` 必须先构建至少 60 个完全开放、结构化确定性 evaluator、许可清楚且算力有界的独立任务，
覆盖至少两个 benchmark/task family，并按 benchmark/domain blocking。只有该面板逐 family 通过 live
数据、evaluator、许可和 compute smoke，`263.4.2` 才能 clean-room 复现 baseline 并生成真正预注册；
否则停止或重设计 claim。

`263.4.1` 已完成为窄范围、可执行的 OpenML 双 family 面板。metadata-only SHA-256 选择在结果前冻结，
先按原始 source group 去重，再排除模糊或非开放许可证：CC18 保留 45 个 UCI→CC BY 4.0 分类任务，
CTR23 保留 22 个明确 CC/CC0/GPL 且同源去重的回归任务。面板分为 7 个 development 和 60 个
confirmatory 独立任务；确认层是 41 classification + 19 regression，seed/trajectory 仍只是单位内
重复。`Public`、非商业、未注明版本的 `CC BY`、同源 wine/mfeat 和无 source-specific 开放许可证据
均作为带原因的排除记录保留，未用于凑样本量。

本地 evaluator source hash 为
`dfa9c2012d11fa9989ad80ce41818f8e4dc0b691d44047157b2311de0a96191e`，Apache-2.0 license hash 为
`5cb668e80870451ec5797defddfc2bccdfb40e4c49ff4ebf205e984b9be4898f`；分类 balanced accuracy 与
回归 R² 均为结构化确定性评分，task success threshold 留给 `263.4.2` 在 baseline 复制后、确认结果前
冻结。逐 family live smoke 通过，且只下载两个 development 代表，60 个 confirmatory payload 未下载、
OpenML public run 未查询。报告状态 `ready_for_clean_baseline`，hash
`ab4435f059676bcfd11387495947527455734eddf239f77b0e92a1c434e8a3ac`；这不等于 baseline 已复制，
更不等于通用自动科研、创新性或可投稿性。

`263.4.2` 随后完成了 clean-room replay 和 outcome-free causal preregistration。FLAML `2.6.0`
baseline 的源码、命令、seed、单线程/12-trial 限额、14 个 pinned wheel、环境、原始 prediction、
metric 和 tolerance 均内容寻址；两个分别创建的 virtual environment 对全部 7 个 development task
运行独立进程，A/B prediction 与 score 逐任务精确一致。standalone runner 不导入 AutoResearch、
不访问网络，只读取预制匿名输入；60 个 confirmatory payload 和 OpenML public run endpoint 均未
访问。baseline report hash 为
`e8f828c97561e789f523328aa25b82d512a159ab1e6f447f6163a770df4598e5`，但其含义仅是冻结应用在
本面板可重放，不是 FLAML 论文全部 benchmark 的重复验证。

预注册在任何 policy result 产生前固定 60 个 paired-baseline success threshold（balanced accuracy
`+0.005` 或 R² `+0.010`）、四个 arm、五个 one-at-a-time ablation、三个 task 内 seed、客观 evaluator、
exact McNemar 主检验、Holm 次检验、权限和 stop/failure policy。四臂共用 12-candidate F0—F3
successive-halving 预算，最大 240 CPU 秒/task-seed、60,000 model tokens，unused budget 不得重分配。
benchmark/domain blocked schedule 覆盖 67 个 task、3 个 seed 和 4 个 arm，共 804 个 assignment。
preregistration hash 为
`100f8a0054fb1fc69ef77cbdeab5521361ba5b1a514082bac9e78493fcf0e707`，manifest hash 为
`df0324759c6099bdb1cf5764cdc4a3e5db838ae9328db0b8b427de562dc8055a`；状态
`ready_for_development_search`，`result_record_count=0`，所以它是允许开始 `263.5` 的门，不是科学
发现、发表结论或外部动作授权。

开发搜索比较 budget-matched one-shot、linear self-loop、portfolio 和 portfolio + cross-branch
memory。Generator、Implementer 与 Evaluator 权限分离；Evaluator 只读取预注册 rubric、执行产物和
原始指标，不读取作者叙事。Portfolio 使用 F0 静态、F1 最小执行、F2 多任务开发、F3 全保真开发四级
fidelity；每级 survival 数、探索 quota、预算和 stop rule 在执行前冻结。

确认性执行只接受冻结 winner 或无 winner 结论。确认 runner 不读取 development trajectory；任务/系统/
数据集才是独立单位，seed 只是单位内重复。随机/置换 null、强 baseline、关键 ablation、效应量与区间、
必要的 alpha spending/FDR、OOD/temporal holdout 和 exact/within-tolerance reproduction 全部进入
合取门。确认失败产生正式阴性 endpoint，不回流同一 panel 继续搜索。

`263.5` 已执行完成。正式 v2 development freeze 固定 12 candidates、9 policies、7 tasks、3
within-task seeds 和 189 assignments；完整结果保留 9,072 个 F0—F3 candidate-stage row、315 个
unique evaluation 和 1,386 个 cache reuse。v1 首次完整矩阵暴露 numeric-only imputer 无法处理
`openml-ctr23-task-361269` 类别列，故其零 survivor 只作为 evaluator diagnosis，不作科学阴性。
v2 repair lineage 绑定 v1 freeze/report/failure evidence，复用原 candidate initialization/order，
只增加 mixed-type imputation/one-hot，未改变任何科学设计或 confirmation seal。

v2 中 `portfolio_memory` 为 6/7 task success，`linear_self_loop` 为 5/7；risk difference
`0.142857`，paired bootstrap 95% interval `[0.000000, 0.428571]`，exact McNemar `p=1.0`。
F1→F3、F2→F3 task-level Spearman 均为 `0.964286`，五项 frozen survival check 全部通过，唯一
允许晋级的 policy 状态为 `ready_for_confirmation`。这只是 P3 screening gate：主效应未显著，
Holm 校正后的消融也未显著，不能写成已证实优越。21 个失败全部是 reviewer ablation 故意放行的
invalid-schema control；主策略零 artifact/evaluator/replay/budget failure。freeze/report/manifest
hash 分别为 `1120bc27839eafefcf20e042e7b043e344c9d59cc3b2daa657a102c5ff264332`、
`b767a0963d0c4f60a92cbc7c35b835918122028f90bff5bb6b73e43ccecd1123`、
`e423e7cc3f82d083c8a0776f572a550da0cad06fd7b70b79b3d2f213fe71eb49`。60 个 confirmation
payload 仍未下载；`263.6` 只能用冻结的 `portfolio_memory` 做一次性独立裁决。

### 27.5 验证层级

263.2 先运行 focused unit/property/schema tests，再运行：

```powershell
python -m pytest tests -q
python -m ruff check src tests
python -m mypy src\autoresearch
git diff --check
```

263.3 以后凡涉及外部文献、代码仓库、数据、模型或 benchmark，必须同时保留 deterministic mock/fixture
和一次 opt-in live smoke。需要 secret、付费模型或云 GPU 时必须停止并请求用户通过 `.env` 或显式资源
批准提供，不得硬编码供应商或凭据。

### 27.6 里程碑

- **P0（路径冻结）**：263.1 的本地端点审计、四视角交叉检索、反方审查、任务树和 Vault 报告通过。
- **P1（前端合同，2026-07-29 已通过）**：263.2 的 16-contract schema bundle、certificate/
  opportunity/portfolio 合取门、16 个 focused unit/property tests、999-test regression、全量
  Ruff/Mypy 和 fail-closed scientific/external boundaries 通过。
- **P2（机会、面板与复现，2026-07-30 已通过）**：263.3 只允许 search-policy track 进入下一门；
  263.4.0 用 endpoint-specific exact power 和逐任务 live 审计否决原 12-task panel；263.4.1 重建
  7-development/60-confirmatory 的 fully open/objective 双 family 面板；263.4.2 在两个 clean
  environment 精确重放强 baseline，并在 `result_record_count=0` 时冻结四臂、五消融、预算、权限、
  阈值、随机化和 stop rule。P2 只授权开发搜索，不表示已有正向科学结果。
- **P3（组合开发，2026-07-30 已通过）**：263.5 完成预算匹配的 189-assignment 全分支开发
  实验、五个 one-at-a-time ablation、任务级低/高保真校准、精确 resume 和完整失败/成本/谱系审计；
  唯一冻结策略 `portfolio_memory` 只获得进入一次性确认的资格，不构成显著或可发表结论。
- **P4（独立科学端点）**：263.6 在未揭示 panel 上形成不可改写的正向或阴性 endpoint。
- **P5（发表候选）**：263.7 的 claim、reproduction、paper 和 Open Science 合取门通过，并进入人类
  新颖性/作者/许可/venue/投稿审查；系统本身仍不执行投稿。

### 27.7 263.6 首次无效确认与恢复执行门

2026-07-31 的首次 one-use confirmation 已形成不可改写的
`invalid_confirmation`，所以 P4 尚未通过。该状态不是运行未完成：primary 和 clean-room 各完整执行
1,620 assignments、180 null controls、77,760 candidate-stage records；60 个任务、60 个独立 source
group、120 个 A/B baseline、2,860 个 unique evaluation、11,804 次 logical cache reuse 和全部失败/
成本记录均被保留。clean-room scientific projection 与 primary 精确相同：
`17299042a7f3b851b7e16fdea183e6cd6c9622833bfb678277d001b96d570789`。

冻结主比较结果为：

| 端点 | `portfolio_memory` | `linear_self_loop` | 裁决 |
|---|---:|---:|---|
| task success | 26/60 | 28/60 | survivor 未优于 comparator |
| favorable / unfavorable / tied | 1 / 3 / 56 | — | 方向不利 |
| risk difference | -0.033333 | — | 未达到 SESOI 0.25 |
| conservative exact 95% CI | [-0.153229, 0.093699] | — | lower bound 未高于 0 |
| exact McNemar | p=0.625 | — | 未达到 0.05 |
| CC18 / CTR23 risk difference | -0.024390 / -0.052632 | — | 两个 family 均为负 |

这组观察值不支持 frozen claim，但不能被升级为可信阴性，因为 null-control validity 失败。零模型在行为
上为 0/60 task success，却在 23 个 classification task 的全部三个 seed 上产生 69/180 个一致的
nonzero-exit。冻结 runner 在训练侧从 CSV 得到数值标签，在 F3 sealed JSON 得到字符串标签，再将
数值反编码预测与字符串 truth 送入 `balanced_accuracy_score`，触发
`Mix of label input types (string and number)`。primary 与 clean-room 都精确复制该模式；冻结 v1
源码和工件不得修改。

恢复按以下不可越过的顺序执行：

1. **263.6.0（已完成）**：保存并递归验证首次 invalid endpoint；修正 smoke 对合法 terminal status
   的测试假设；记录根因、已消耗 panel 和未通过门，不改科学结果。
2. **263.6.1（evaluator certificate）**：next-version runner 对 label token 做确定性 canonicalization，
   区分 candidate failure 与 evaluator failure；在两套 pinned interpreter 上覆盖 classification/
   regression、numeric/string labels、dense/sparse ARFF、quoted comma、mixed feature、unseen category、
   dummy/prior、所有 allowed learner 和 F3 exact prediction replay。next-version orchestrator 同时修复
   materialized task-bundle resume。
3. **263.6.2（consumed-panel technical replay）**：绑定 v1 freeze/report/failure hashes，只允许
   evaluator repair；结果必须标记为 technical/exploratory，不能满足 independent-confirmation 或
   publication gate。预先冻结 stop/advance certificate；修复后若主效应不具正确方向和实际可行幅度，
   关闭该 claim。
4. **263.6.3（conditional new confirmation）**：只有 stop/advance 通过，才能重新经过 opportunity、
   development、prospective power 和 zero-result freeze，使用全新且与 v1/v2 source group 不重叠的
   panel。否则选择新的客观研究 track，不得 panel shopping。
5. **263.7**：继续阻塞。invalid v1、consumed-panel v2、漂亮子组、未校正 secondary result 或 LLM
   reviewer score 均不能替代有效确认。作者、许可、公开发布、venue 和投稿仍需显式人工批准。

该恢复门把 2025—2026 自动科研文献中的共同限制转成工程约束：AI Scientist 类系统的 workshop/writeup
成功不能替代 main-venue scientific validity；MLR-Bench/PaperBench 暴露的实现与复现错误必须由
artifact-level verifier 拒绝；Co-Scientist/Robin/ERA 的有效部分是外部客观反馈、搜索和留出验证；
POPPER 的证伪思想只用于结果前统计设计；Graph of Trace、Code-as-Harness、PROV-O、RO-Crate 和
Workflow Run Crate 分别承担可检查轨迹、权限执行、因果谱系和开放研究对象，不承担“自动证明新颖性”
的职责。

#### 263.6.1 evaluator compatibility certificate（已完成）

next-version evaluator 已在独立 source 和 run root 中冻结为
`frozen-tabular-confirmation-runner-v2`。它不修改 v1 runner、controller、orchestrator 或任何首次
确认工件。classification train target 以 pandas string dtype 读取，sealed F3 label 必须为 string，
随后 truth 与 prediction 在同一个编码空间内交给 balanced accuracy；regression 继续要求有限浮点。
F2 probe 的工作目录不复制 label file，config 也没有 label path/hash；任何非 F3 label binding 都
fail closed。所有失败都有 `input`、`candidate` 或 `evaluator` domain 以及稳定 code，预期
`invalid_probe` 返回 candidate-domain artifact，而输入/评价器错误返回非零进程码。

certificate matrix 固定为：

- 4 个 36/12 split fixture，覆盖 dense、sparse、numeric-looking/string class、quoted comma、
  mixed-type、unseen category 与 regression；
- 9 个有效代表配置，覆盖 dummy、linear（raw/scaled）、LightGBM、XGBoost、RF、Extra Trees、
  HistGradientBoosting 与 heterogeneous ensemble；
- primary/replay 两套既有 pinned interpreter，每个组合重复两次；
- 144 个有效 F3 probe、4 个 intentional invalid control、4 个 F2 label-isolation probe，共 152 个；
- within-role exact prediction/scientific replay、cross-role exact scientific projection、null-prior
  zero-integrity、package/interpreter/source hash、static network audit、result-free source inventory 和
  materialized-fixture resume 为不可补偿 conjunction。

正式报告 `e3709c8b834bfcc52ed7fb74389278e6c5a3e36d4bf13d32ddad7118f4aa797b`
以 `certified` 结束，15/15 checks 通过，四类非预期 failure count 均为 0；manifest
`4e3251eb2453fffaa37a4f6849251396e3f1fc88f882739faa07a5e8d4dda73c`
递归绑定 1,242 个 artifact。下一步只能进入 `263.6.2`：先冻结 consumed-panel、technical-only、
stop/advance 和 publication-ineligible contract，再把 exact v1 claim 交给 certified v2 evaluator。

### 27.8 Task 263.6.2 停止裁决与下一执行门

`263.6.2` 的正式矩阵已经完成，但合法终点是 `invalid_technical_replay`。primary/replay 各有
1,620 assignments 与 180 null controls；8 个 assignment trajectory 在同一真实 workload deadline
上不一致，0 个 null projection 不一致。冻结编排器没有写 technical-effect report，而由独立 incident
auditor 把差异、31 个不完整 label attestation、诊断分析和全部 release/confirmation/publication
false 常量固化为 36,521-artifact 研究对象。

事故对象：

- repair freeze:
  `6b7f124fab513e8032ff777b2a92926cf5e57836d409ad133700c49946cea22b`;
- incident:
  `f756ab01b1e7291875470e75d63e5fe668bf199a50659c041799e038578f9dd0`;
- diagnostic analysis:
  `f599ed894e484dae483c25e27364ebea5ceec27f45c925bfc625e16fed0d08b3`;
- recursive incident manifest:
  `79bfb70fa5ded53686ada5deadb1e735450ad442a441867b93eef615a9c30fe6`.

冻结裁决是 `stop_portfolio_memory_claim`，下一路线是
`return_to_objective_opportunity_tournament`。不得重跑旧面板直到出现一致结果，不得根据 v2 数值换
指标/子组/阈值，不得进入 263.6.3 给旧 claim 购买新 panel。`263.7` 继续阻塞。

下一执行任务为 `263.6.4`，采用三层资格门：

1. **Instrument calibration**：schema、label token、metric、null behavior、failure domain、prediction
   replay 和权限边界；
2. **Development-only workload qualification**：最慢 task/candidate strata、两解释器、计划并发、
   多次重复、process telemetry、algorithmic compute budget、orchestration deadline/slack、timeout
   origin、retry 与 replay semantics；
3. **Scientific opportunity qualification**：nearest work、strong baseline、客观 effect、独立单位/
   功效、开放许可/数据/代码、预算、falsifier、消融和 disjoint panel 计划。

至少比较 structured world-model/evidence graph、Socratic falsification critic、外部 data/lab/
environment feedback 三条新机制 track。对每条 track：

- 使用新 development evidence；不能读取或复用 v1/v2 consumed panel 做排序；
- 先冻结一个主 claim、SESOI、反证和最小决定性实验；
- 把 Agent 分数只作为探索信号，晋级只依赖客观 evaluator；
- 用 budget-matched ablation 分别测 world model、critic 和 external feedback 的增量；
- 记录全部失败、timeout、人工输入和成本；
- 允许机会门全失败，并在失败时保留 research object；
- 只有通过结果盲 RQ/opportunity/workload certificate 后，才可设计新的 untouched panel。

Kosmos 的 structured world model、Robin/Virtual Lab 的 lab-in-the-loop、AHOIS 的 causal questioning/
constraint/counterexample/falsification critic 均作为可消融假设来源，而不是可直接声明的能力。新任务
必须用独立正确率、错误发现率、实验晋级有效率、重放一致性和成本等客观端点验证；任何人类领域判断、
湿实验、公开发布或投稿仍需显式批准。

### 27.9 Task 263.6.4 实施结果与 263.6.5 执行门

`263.6.4` 已完成，但完成的是 track selection 与 runtime qualification，不是科学效应或论文。实现
新增严格、内容寻址的三轨合同、结果盲审计、exact paired-power sensitivity、
`WorkloadQualificationCertificate`、Markdown/JSON/schema/manifest 输出和 tamper tests。冻结
standalone probe SHA-256 为
`c109d368cd64cd5356cc95304948ed9d6594a823b0bddf00fa4faaa797e6bcca`。

正式 live run 使用 Task 263.4.2 已冻结的 clean interpreter A/B，逐条访问一手论文、GitHub API、
Hugging Face dataset API 与 license evidence。DiscoveryBench 当前 tree 返回 987 个 entry，其中
189 个 depth-four provisional source-group folder；card metadata 声明 `odc-by`，AstaBench license
API 返回 `Apache-2.0`。这只证明数据/参考 harness 可以依法进入 clean-room 设计，不证明自然语言
`gold_hypo` 可以 exact-scored，也不证明 189 个目录已经是统计独立样本。

三条 workload certificate 都通过以下不可补偿检查：

- 两个不同 interpreter installation 与完整 calibration/qualification matrix；
- planned concurrency `1/2`，qualification repeat `3`，每条 track 共 24 observations；
- `20,000` exact algorithmic work units 与独立 `5s` CPU budget；
- calibration 后冻结的 orchestration deadline 与至少 `8×` slack；
- retry `0`、timeout origin、完整 elapsed/CPU/peak-memory/batch/subprocess telemetry；
- runner、input、environment 和 command hash 绑定；
- scientific projection exact replay，telemetry 不进入科学投影。

三条 track 的 scientific projection SHA-256 分别为：

- `structured-world-model`:
  `a8e779052194dd94f520104e235c6ab4c912905648745a433fce99a8d1fcc3d1`;
- `socratic-falsification`:
  `e8dce31df4d24ae1a20f7770875c3e7666e84c613f7741725086191680c316e9`;
- `external-feedback`:
  `953e90fcb01c3221b907548d47f5ab5b4860dafa2b526a7e6e26ae00ade734f4`.

正式 tournament report
`13e31dbe29f2d34ec3924459207610f04618271ed21ce551e13a3d0b7716e72c`
只选择 `socratic-falsification` 进入
`development-only clean-room baseline and evaluator construction`。另外两条路线分别因系统/数据/
客观 evaluator/许可/算力缺失，以及 `2 < 84` 独立环境、许可和 8×H100 级算力失败。选择规则没有
weighted score 或 hardcoded winner，允许全失败；本次 Socratic route 的 189 只是功效可行性上界。

#### 下一执行任务：263.6.5

263.6.5 采用以下 stop-first 顺序：

1. **许可与独立性清单**：对 189 个 provisional folders 绑定来源、派生关系、真实/合成 family、
   answer-key lineage、重复数据和许可证。必须在不读后续科学 outcome 的情况下保留至少
   `30 development + 84 untouched reserve` 个无重叠 source groups；不足即停止。
2. **客观 evaluator fixture**：从允许的数据字段和 gold hypothesis 预冻结 binary
   valid/fault-injected decision；fault 类型至少含 causal inversion、constraint violation、
   counterexample omission 和 unfalsifiable claim。expected label 必须由生成规则确定，主要终点不得
   使用 free-form semantic match、LLM judge 或人工事后裁决。
3. **clean-room strong baseline**：只复用 AstaBench Apache-2.0 接口思想与 DiscoveryBench
   ODC-By 数据库；不复制无 LICENSE 的 POPPER/SciAgentArena code 或 gated data。baseline、model、
   tool、token/call、CPU/wall-clock 与失败预算在任何结果前冻结。
4. **development-only causal matrix**：比较 no-critic、rule/null control、四个单项 critic 和 full
   critic；以 source group 为统计单位，seed/retry 只作技术重复；所有失败、timeout、人工介入、成本和
   trajectory 都保留。
5. **继续/停止证书**：只有 evaluator implementation、baseline reproduction、workload qualification、
   exact replay、null/Type-I、SESOI 可行性、nearest-work delta 和独立人类新颖性复核同时通过，才可
   创建新 Research Question Certificate。不得在 263.6.5 创建或读取 confirmatory panel。

当前 release、submission、paper claim 与 `263.7` 仍为 false/blocked。若 evaluator 无法客观化、
独立 source group 少于功效要求，或 SciAgentArena 已覆盖决定性增量，合法结果是保留诊断 research
object 并再次回到 opportunity tournament，而不是改变指标或调用更多 Agent。

### 27.10 Task 263.6.5 实施结果与 263.6.6 执行门

Task `263.6.5` 按 stop-first 顺序完成在 inventory 层。实现新增：

- `socratic_development_vertical.py`：严格 Pydantic 合同、DiscoveryBench tree/answer-key/license
  获取与绑定、189-folder audit、保守/乐观来源投影、停止证书、Markdown/JSON/schema/manifest 和
  tamper-blocking loader；
- `frozen_discoverybench_inventory_probe_v1.py`：只使用标准库、只接收结果盲 tree/key projection
  的冻结 runner；
- deterministic unit tests：目录/来源计数、raw/processed 与 semantic-tree 聚类、fail-closed
  downstream、重复/tamper、Windows-1252 严格解码、standalone runner parity 和 artifact round trip；
- opt-in live smoke：官方 Hugging Face/GitHub/license/论文 surface、两套冻结 clean interpreter、
  exact replay、零 retry 和 outcome-access=false。

正式 live output 位于
`runs/manual-live/task26365-socratic-inventory-v3/`，核心绑定为：

| Artifact | SHA-256 |
|---|---|
| Report | `a01303685e1aa4ee2d6ef19f75b5ca01cf3694bc58075008d78840d9bab1d75e` |
| Manifest contract | `8253096b08a8c44c6ec99ea9286872efe76b23f376ce63097ebebb561b6e7ed2` |
| Projection | `8ec78def64fcdc4934d69cc8371d9c05a95c21299cde19ad8e00650bc46474f3` |
| Replay certificate | `02af0e8a089104da4f77e65ad9a90055aacc46e6e47d4736ebc08fa8fb2edc9b` |
| Replay input | `01cb2537f55a28a39f6a7174a6b772391ab5f9682a5b1d39bf9698ace54f4545` |
| Frozen runner | `efe05a01434bffae461a2e2facf8afd25b085052c184ba291ebaf13e54131238` |

正式判定为 `stopped-at-inventory`。189 个 provisional folder 在 conservative audit 后只形成 107 个
source group；30 个 development group 之后的 reserve 最大值为 41。即使采用不应作为主分析的
optimistic counting，reserve 上限也只有 81，低于 84。因而实现正确地保持以下状态：

- fault generator / objective evaluator implemented：false；
- evaluator construction / baseline execution authorized：false；
- provider configuration collected：false；
- Research Question Certificate issued：false；
- confirmatory panel created or read：false；
- public content release / release / submission authorized：false。

#### 下一执行任务：263.6.6

`263.6.6` 是 replacement objective-data opportunity tournament，而不是立即实现另一套 Agent。
它按下列次序执行：

1. **冻结候选和构念**：至少比较 AutoSDT-5K repository-group coding、ScienceAgentBench
   publication-group scientific programming、CORE-Bench paper-group reproducibility 和 QRData
   source-sheet statistical/causal reasoning；可以全部失败，不 hardcode winner。
2. **result-blind inventory**：只读取 provenance、license、input/output schema、依赖/资源清单和
   evaluator definition；在任何模型输出前按 repository/publication/shared data/generator template
   聚类。
3. **许可门**：逐 task/source 绑定 SPDX 或许可证原文；无许可证不得凭公开可见或“academic use
   assumed”进入可再分发面板。分别记录 local execution、derivative、software reuse 和 content
   redistribution 权限。
4. **objective label 门**：primary endpoint 必须由可执行程序、数值容差、文件/figure property 或
   冻结规则决定；LLM judge、自由文本 similarity 和事后 human score 只能作 secondary evidence。
5. **独立单位门**：一个候选 coherent construct 必须保留至少 30 个 development 与 84 个完全 sealed
   reserve source groups；seed、attempt、difficulty variant、同 repository 多 task 和 Agent vote
   不是独立单位。
6. **资源门**：在 development-only subset 上估算下载、依赖、CPU/GPU、wall-clock、失败率和 clean
   replay 可行性，但不得运行 candidate model 或读取 reserve outcome。
7. **继续证书**：只有 license、unit、objective endpoint、strong baseline、compute、nearest-work
   与独立 human novelty 全部通过，下一任务才可构建 evaluator/critic。否则写出负面 opportunity
   research object 并回到 track selection。

Task `263.6.3` 仍不得进入；旧 consumed panel 不得复用。`263.7`、论文 claim、公开发布与外部投稿
继续被独立门禁阻止。

### 27.11 Task 263.6.6 实施结果与 263.6.7 执行门

Task `263.6.6` 已完成四候选、无 hardcoded winner 的 result-blind tournament。实现新增：

- `replacement_objective_data_tournament.py`：exact official material fetch、四个专用 lineage
  parser、repository/publication/paper/shared-sheet clustering、四用途 license audit、
  deterministic endpoint/strong-baseline/compute audit、无权重合取投影、双解释器证书、
  Markdown/JSON/schema/manifest 和 tamper-blocking loader；
- `frozen_replacement_objective_data_probe_v1.py`：标准库 frozen runner，只接收 group IDs、
  capacity 和 pre-outcome gate，不接收 prompt、answer、reference/model/judge/reserve values；
- deterministic tests：四 parser 的 pseudoreplication control、敏感结果变更不影响 lineage、
  all-candidate failure、任意第五候选可胜出、duplicate/outcome contamination、scope-specific
  license fail-closed、projection/artifact tamper 和 exact runner parity；
- opt-in live smoke：下载并哈希四个 exact official releases，探测 11 个一手论文页面，在
  `clean-venv-a/b` 中零重试复演同一 projection。

正式 live output 位于：

`runs/manual-live/task26366-replacement-objective-data-tournament-v1/`

| Artifact | SHA-256 |
|---|---|
| Report contract | `292899ec660d38490fd95dd40c832e304f6c816a1dd5f9f401b19f6615eea89a` |
| Report file | `299d7f884e9983b7d72e7c38e3da3b8ca6f7e1307baa539f46342c0bd29e203d` |
| Projection | `265d8c1b1195f6ad488a2d2fe12dd5133afaeadfd18d109fff56edefd11c7491` |
| Decision | `ca0697f34a8b70e81beb67bc2960fa5c121615cba556c372307f9209a7bd9d36` |
| Replay certificate | `40370c725a9450ea3886ce0c72ad658100c27eea5f7a5c5e1a4eafbc08fced99` |
| Replay input | `a78bdecce72a7e28aa6c30f64a11a69c1435815daaacacd98a2659b3b9f1b1df` |
| Frozen runner | `a34a4ab5ec95fa5e37fd3f0b03c64830c18cb1449a9bc10788b5266f0707a396` |
| Manifest contract | `4e4a47495d23f44c3df72cb3005cb4846d5f356f65b606a9677fd1c80013fc9a` |

正式决策为 `all-candidates-rejected`：

- AutoSDT-5K：1,002 labelled-repository capacity，但 source revision、per-source rights、
  packaged scorer、strong baseline、本地 compute 和 reserve seal 失败；
- ScienceAgentBench：publication upper bound 44，potential reserve 14，完整 endpoint 含
  LLM judge/best-of-three，逐来源许可和 seal 失败；
- CORE-Bench：90 paper groups、45 sealed reserve，低于 84；capsule rights 与 privileged/GPU
  workload 失败；
- QRData：190 shared-sheet groups、160 potential reserve，但 source-sheet rights、strong
  baseline 和 reserve seal 失败。

所有 candidate model calls、provider credentials、Research Question issuance、confirmation panel、
heterogeneous post-result combination、publication claim、public release 和 submission 保持 false。

#### 下一执行任务：263.6.7

`263.6.7` 不再开始第五个 dataset/model 实验，而是冻结一项新的 AI-scientist benchmark-validity
systematic mapping protocol：

1. **Protocol before extraction**：先固定数据库/页面、检索式、日期、去重、release-level unit、
   纳入/排除、字段、unknown 语义、冲突处理、分析和停止条件，再提取当前四个 pilot 之外的记录。
2. **Census target**：至少 20 个独立 fixed-revision benchmark release；当前四个只作为 parser/
   codebook calibration，不能充当独立 confirmation。
3. **Benchmark Admission Card**：每个 release 记录 headline task、independent source upper bound、
   compression ratio、local/software/derivative/redistribution rights、primary endpoint、
   LLM/human judge role、strong baseline command、compute、split seal 和 contamination policy。
4. **Human validity boundary**：模糊 license、lineage 与 construct 至少双人独立编码，预设一致性门和
   adjudication；自动系统不能自行给出法律或作者责任结论。
5. **Descriptive endpoint**：报告各 admission gate 通过率、完整合取通过率与 construct/source/year
   sensitivity；不得把 systematic mapping 改写成某个 critic/Agent 有因果效果。
6. **Result-blind downstream**：若发现单一 fresh panel 通过全部门，下一任务仍须先复现 baseline 和
   冻结新 RQ；本任务不运行候选模型、不创建 confirmation panel。
7. **Stop**：少于 20 个 release、关键 evidence 覆盖不足、双人一致性失败或协议后改 endpoint 时，
   保留开放数据/诊断负结果，不生成领域普遍性 claim。

Task 260 Route B 可作为独立 systems-paper candidate 进入 human submission review，但不自动授权
公开或投稿。Task `263.6.3`、mechanism confirmation、`263.7` 和 external submission 继续被各自
门禁阻止。

### 27.12 Task 263.6.7.1 预提取协议实施结果

Task `263.6.7.1` 已实现一套结果盲、内容寻址的 benchmark-validity systematic-mapping 协议，而非
提前运行正式 census：

- `benchmark_validity_protocol.py` 提供严格协议、source/lens/query binding、study/family unit、
  42 字段 Admission Card schema、七种 evidence state、12 个不可补偿 gate、人类编码门、四个描述性
  endpoint、六个 sensitivity、十个 stop rule、结果盲 projection、双解释器 replay certificate、
  Markdown/JSON/schema/manifest 持久化和 tamper-blocking loader；
- `frozen_benchmark_validity_protocol_probe_v1.py` 是仅用标准库的冻结 runner，只接受协议投影，拒绝
  search result、admission card、extracted record、benchmark/model outcome 和任何 downstream
  authorization；
- deterministic tests 覆盖 hash determinism、28 个 query binding、pilot exclusion、evidence state
  语义、人类阈值、12 个 gate、结果污染拒绝、two-interpreter parity、schema/Markdown/manifest 和
  artifact tamper；
- opt-in live smoke 在两套真实 clean Python installation 中执行冻结 runner 和正式包回读，但按
  pre-extraction 设计不访问文献 API，也不产生新 benchmark record。

正式 output 位于：

`runs/manual-live/task263671-benchmark-validity-protocol-freeze-v1/`

| Artifact | SHA-256 |
|---|---|
| Protocol | `ed6088c225d5c7f7710ecb69507659003b5b97e06dc7c0ee005a81ed2712e8ed` |
| Report | `0ed7f637ab10b10cc6b265c60020437255f64cc8d8a7259ad9eae9c9051a9408` |
| Result-free projection | `e8628d484cfd3d5ead9dbb9b0e6610ca4f68adeebda4d0ef463bc3ac1d5e1881` |
| Replay certificate | `85e8ee4da9ea685b32f1896759e5235bec3e47fa59af8b12e0790f9026d9b93a` |
| Replay input | `e0e2c55aed44597be4cd9661b050590bb0ac4924ae5b7f6b642a09a865f5a4df` |
| Frozen runner | `fb7c4f4e535a7168a89c48fc77a28772afd931e0cd61d2df29a6d62a6c8dee6f` |
| Manifest | `9b99c6e4ccb43ea4982c546ebf6e18a34df63ae3f474ace3ed58ee2464a96b77` |

正式状态为 `frozen-pre-extraction`：28 条 query、16 个 recall sentinel、42 个 card field 已冻结；
搜索、non-pilot 提取、outcome access 和 candidate-model call 数均为 0；RQ、confirmation panel、
publication claim、release 和 submission 均为 false。

#### 下一执行任务：263.6.7.2

1. 按冻结请求参数实现 arXiv、OpenAlex、Crossref、DBLP adapter；保存每页原始响应、请求时间、状态、
   retry 和 SHA-256，不修改 query 或日期。
2. 实现 append-only PRISMA-S search log、16 项 known-item recall 和 fail-closed API capability smoke；
   capability smoke 不筛选或提取正式 benchmark record。
3. 实现 paper identity、benchmark family、fixed revision 和 source-overlap dedup；禁止把 task、seed、
   attempt、difficulty 或旧 revision 当作独立 family。
4. 生成不含结论的 screening form 和空 Admission Card evidence packet；不得打开 benchmark outcome，
   不得把四个 pilot 泄漏进 primary cohort。
5. 只有 `263.6.7.2` 的 mocked/live adapter、分页、rate-limit、retry、tamper、dedup 和 exact replay
   全部通过后，才可准备 `263.6.7.3`。

`263.6.7.3` 仍需要两位真实独立 reviewer 与一位不同的 adjudicator。身份、independence attestation、
pre-adjudication agreement 和 coverage 未通过前，不执行正式关键编码，不生成领域普遍性 claim。
