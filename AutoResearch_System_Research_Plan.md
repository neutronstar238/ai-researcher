# 全自动科研自进化系统研究计划

> 文件名：研究计划.md
> 生成日期：2026-06-11
> 项目名称：AI-Researcher
> 定位：面向计算实验型科研的全自动、自循环、自进化科研操作系统

---

## 1. 研究背景与核心判断

本项目目标不是做一个“会写论文的聊天机器人”，而是构建一个能够在受限科研域内长期运行的科研操作系统。系统应当能够自动发现研究问题、检索并整理文献、提出假设、设计实验、执行实验、验证结果、生成论文草稿、沉淀经验，并基于运行结果持续优化自己的策略。

当前自动科研系统已经具备一定可行性，但不能直接追求完全无人值守的开放世界科研。更可落地的路线是：

**受限研究域自治 + 强验证机制 + 人机审批门 + 阶段性自进化。**

首阶段应聚焦机器学习、算法实验、公开 benchmark、可脚本化实验、可自动重跑验证的研究场景。等系统在封闭任务中稳定后，再逐步扩展到更开放的研究方向。

---

## 2. 总体研究目标

### 2.1 总目标

构建一个能够完成“选题—调研—假设—实验—验证—写作—复盘—进化”闭环的全自动科研系统，使其在指定研究域内持续产生可复现、可审查、可扩展的研究成果。

### 2.2 可验证目标

| 目标维度 | 定义 | MVP 阶段目标 | 1 年目标 | 3 年目标 |
|---|---|---:|---:|---:|
| 自动化率 | 从任务启动到论文初稿中无需人工修改的步骤比例 | ≥60% | ≥80% | ≥90% |
| 可复现率 | 同一代码、数据、环境下重跑成功率 | ≥90% | ≥95% | ≥97% |
| 结果可信度 | 引用错误、表图不一致、伪造结果、未验证结论比例 | <5% | <1% | <0.5% |
| 成本效率 | 单个有效研究循环的算力/时间/人工成本 | 建立基线 | 较基线下降 30% | 较基线下降 60% |
| 研究增益 | 相比基线方法的主指标提升 | ≥3% | ≥5% | ≥8% |
| 自进化收益 | 新策略上线后相对旧策略的综合收益 | 建立评估 | 稳定正收益 | 长期可控正收益 |

---

## 3. 研究范围与边界

### 3.1 首阶段适用范围

系统首阶段建议只覆盖以下科研类型：

1. 机器学习模型改进实验；
2. 算法与系统优化实验；
3. 公开数据集与公开 benchmark 上的实验；
4. 可通过脚本自动复现实验结果的研究；
5. 可由指标、日志、图表和统计检验验证结论的研究。

### 3.2 暂不纳入首阶段的范围

以下场景不建议作为第一版目标：

1. 需要真实物理实验室设备且存在安全风险的湿实验；
2. 无法自动验证结果真伪的开放探索型研究；
3. 涉及敏感数据、隐私数据、医疗数据、未授权商业数据的研究；
4. 完全无人审批的自动投稿、自动署名、自动对外发布。

### 3.3 人机边界

系统可以自动完成大部分工程与分析任务，但以下节点必须设置人工审批门：

| 审批节点 | 原因 |
|---|---|
| 新研究方向立项 | 防止无价值或高风险方向进入执行链 |
| 高成本算力租用 | 防止预算失控 |
| 完全权限执行 | 防止安全风险 |
| 私有数据接入 | 防止隐私与合规风险 |
| 对外发布/投稿 | 防止学术诚信与署名风险 |
| 自进化策略正式上线 | 防止系统退化或奖励黑客 |

---

## 4. 总体架构设计

系统建议采用“双链路、四层、六中心”的总体架构。

### 4.1 双链路

#### 研究执行链

研究执行链负责把科研任务真正做出来：

```text
研究问题池 → 文献检索 → 知识建模 → 假设生成 → 实验设计 → 代码生成 → 实验执行 → 结果验证 → 论文生成
```

#### 治理进化链

治理进化链负责保证系统长期可靠运行：

```text
运行记录 → 失败分析 → 技能抽象 → 策略候选 → 影子评估 → 灰度上线 → 监控回滚 → 新基线
```

### 4.2 四层架构

| 层级 | 职责 | 核心组件 |
|---|---|---|
| Interface Layer | 用户交互、CLI、Web、移动通知 | CLI、Dashboard、Feishu/WeChat Bot |
| Agent Layer | 多 Agent 协作、任务规划、执行决策 | Main Agent、Fixed Agents、Project Agents、Meta Controller |
| Verification Layer | 证据校验、实验校验、引用校验、质量评估 | Evidence Graph、Result Validator、Review Simulator |
| Resource & Memory Layer | 知识库、实验追踪、数据版本、算力调度 | Obsidian/Markdown、PostgreSQL/pgvector、MLflow、DVC、Compute Scheduler |

### 4.3 六个核心中心

1. **研究问题中心**：维护候选方向、研究 gap、创新假设、优先级。
2. **证据知识中心**：管理文献、代码、数据、网页、引用、证据链。
3. **实验执行中心**：负责任务拆解、代码生成、沙箱执行、结果收集。
4. **质量验证中心**：负责指标 sanity check、重跑验证、统计检验、引用验证。
5. **论文交付中心**：负责 LaTeX 论文、图表、复现包、演示材料生成。
6. **自进化中心**：负责经验沉淀、策略更新、技能迁移、灰度发布、回滚。

---

## 5. Agent 体系设计

### 5.1 Agent 分层

| Agent 类型 | 数量 | 主要职责 | 权限范围 |
|---|---:|---|---|
| Main Agent | 1 | 总控、任务分解、调度、审批请求、状态管理 | 全局读写，但关键动作需审批 |
| Fixed Agents | 多个 | 文献、摘要、代码、实验、审稿、知识管理等固定职责 | 按功能授予工具权限 |
| Project Agent | 每项目 1 个 | 负责单个研究项目的全流程推进 | 只能写入本项目目录 |
| Meta Controller | 1 | 评估系统表现，生成策略更新候选 | 不能直接改生产策略 |
| Validator Agents | 多个 | 结果验证、引用验证、安全验证、复现验证 | 对执行链有否决权 |

### 5.2 推荐 Fixed Agents

| Agent | 职责 |
|---|---|
| Literature Retriever | 多源文献检索、去重、元数据抽取 |
| Paper Summarizer | 摘要、创新点、方法、数据集、指标抽取 |
| Gap Analyzer | 识别研究空白与可攻击点 |
| Hypothesis Generator | 生成可检验假设 |
| Experiment Designer | 将假设转成可执行实验设计 |
| Code Generator | 生成实验代码、配置、README、requirements |
| Compute Executor | 调度算力并运行实验 |
| Result Analyzer | 提取指标、画图、统计检验 |
| Evidence Verifier | 校验证据链、引用、DOI、URL、表图一致性 |
| Review Simulator | 模拟审稿，给出质量评分与修改建议 |
| Knowledge Manager | 维护知识库、技能库、失败库、版本历史 |
| Safety Auditor | 检查权限、隐私、许可证、危险操作 |

### 5.3 Agent 通信协议

所有 Agent 间消息必须结构化，禁止只传自然语言。建议统一采用如下字段：

```json
{
  "message_id": "msg_xxx",
  "from_agent": "planner_agent",
  "to_agent": "experiment_designer",
  "task_id": "task_001",
  "intent": "design_experiment",
  "input_refs": ["hypothesis_07", "paper_102"],
  "expected_output_schema": "ExperimentTask",
  "deadline": "2026-06-15T12:00:00Z",
  "budget": {"max_tokens": 8000, "max_gpu_hours": 2},
  "risk_level": "medium"
}
```

---

## 6. 知识与证据系统设计

### 6.1 知识库分区

```text
autoresearch-vault/
├── exploration/              # 跨项目知识
│   ├── topics/
│   ├── skills/
│   ├── methods/
│   ├── datasets/
│   └── failure_patterns/
├── projects/                 # 项目知识
│   └── project_xxx/
│       ├── literature/
│       ├── hypotheses/
│       ├── experiments/
│       ├── results/
│       ├── paper/
│       └── review/
├── evidence_graph/           # 结构化证据图谱
├── strategy_library/         # 策略、prompt、工作流模板
└── audit_logs/               # 审计记录
```

### 6.2 证据图谱

为了避免论文生成阶段出现“看起来像真的但无法追溯”的内容，每一个核心结论都必须绑定证据。

```text
Claim → Evidence → Source → Artifact → Validation Status
```

示例：

```json
{
  "claim_id": "claim_018",
  "claim": "Method A improves macro-F1 by 5.2% over baseline B.",
  "evidence": ["run_20260611_003", "table_2", "metric_macro_f1"],
  "source_artifacts": ["results.csv", "train.log", "config.yaml", "commit_sha"],
  "validation_status": "reproduced_once",
  "validator": "result_validator_agent"
}
```

### 6.3 知识条目类型

| 类型 | 内容 | 是否可复用 |
|---|---|---|
| Paper Note | 文献摘要、方法、贡献、局限 | 是 |
| Dataset Card | 数据来源、许可证、任务、指标 | 是 |
| Method Card | 方法原理、适用场景、失败条件 | 是 |
| Experiment Record | 配置、代码、指标、日志、产物 | 项目内为主 |
| Failure Case | 失败原因、触发条件、修复方案 | 是 |
| Skill Card | 可迁移经验、使用条件、示例 | 是 |
| Strategy Card | Agent 策略、prompt、工具链组合 | 是 |

---

## 7. 实验验证体系

### 7.1 三层验证机制

| 层级 | 验证对象 | 通过条件 |
|---|---|---|
| 运行验证 | 代码是否真的运行、产物是否存在 | 无崩溃、有日志、有指标、有输出文件 |
| 结果验证 | 指标是否合理、表图是否一致、能否重跑 | 指标解析正确，重跑偏差在阈值内 |
| 论文验证 | 结论、引用、图表、实验描述是否一致 | 每个核心 claim 都有证据链 |

### 7.2 验证器清单

| 验证器 | 检查内容 |
|---|---|
| Config Validator | 配置是否完整，超参是否在合理范围 |
| Dependency Validator | 依赖是否可安装，版本是否锁定 |
| Runtime Validator | 是否真实执行、是否超时、是否异常退出 |
| Metric Validator | 指标是否存在、是否数值合理、是否优于基线 |
| Reproduction Validator | 是否能在相同环境下重跑 |
| Citation Validator | DOI/URL 是否存在，引用是否支持对应 claim |
| Figure/Table Validator | 表格、图、正文数字是否一致 |
| License Validator | 数据、代码、模型是否允许使用与发布 |
| Safety Validator | 是否存在危险命令、越权访问、泄露凭证 |

---

## 8. 自循环机制

系统每一轮科研循环由以下步骤构成：

```text
1. 读取研究方向池与最新文献
2. 生成候选问题
3. 评分并排序
4. 创建项目 Agent
5. 深度调研并生成假设
6. 拆解实验任务
7. 生成代码并执行
8. 收集并验证结果
9. 生成论文初稿和复现包
10. 模拟审稿并修复
11. 沉淀知识、技能、失败模式
12. 更新策略候选
13. 进入下一轮循环
```

这里的“最新文献”不能只理解为本地知识库。项目启动、候选审批、每日/每周候选刷新都必须触发外部联网检索，并把 ArXiv、Semantic Scholar 等免费公开来源中的相近方向、重复工作、相邻方法、数据集、baseline、负面结果和矛盾证据纳入交叉检验。Obsidian vault 是长期记忆和证据落盘层，不是外部检索的替代品。

写入 Obsidian 的调研总结必须区分四类内容：来源元数据、来源明确支持的事实、模型基于证据的解释、未知或待验证事项。系统不得虚构论文结果、benchmark 分数、引用、录用状态、代码可用性或实验结论；缺证据时只能记录为 `unknown` 或 `pending verification`。

### 8.1 循环终止条件

一个研究项目应在以下条件下终止：

1. 达到预设指标并通过验证；
2. 连续 N 次实验无显著提升；
3. 成本超过预算；
4. 发现数据、许可证或伦理风险；
5. 审稿模拟持续低分且无改进方向；
6. 人工终止。

### 8.2 循环评分函数

建议定义综合奖励：

```text
Reward = α × QualityGain
       + β × Reproducibility
       + γ × EvidenceCompleteness
       - δ × ComputeCost
       - ε × HumanIntervention
       - ζ × RiskPenalty
```

其中：

| 变量 | 含义 |
|---|---|
| QualityGain | 研究指标提升或审稿评分提升 |
| Reproducibility | 重跑成功率与结果稳定性 |
| EvidenceCompleteness | 证据链完整度 |
| ComputeCost | 算力、存储、API 成本 |
| HumanIntervention | 人工修改次数与审批次数 |
| RiskPenalty | 安全、隐私、许可证、学术诚信风险 |

---

## 9. 自进化机制

### 9.1 自进化对象

系统不能随意修改所有内容。可进化对象应限制在以下范围：

| 可进化对象 | 示例 |
|---|---|
| Prompt 模板 | 文献总结 prompt、实验设计 prompt、审稿 prompt |
| Workflow 模板 | 先检索再假设，还是先假设再检索 |
| 工具选择策略 | 何时调用强模型、何时用弱模型、何时重试 |
| 检索策略 | 查询扩展、文献排序、去重阈值 |
| 实验搜索策略 | HPO 算法、早停策略、baseline 选择 |
| 调度策略 | local-first、GPU 队列、云租用触发 |
| 验证策略 | 重跑次数、显著性检验方法、异常检测规则 |

不可自动进化对象：

1. 权限系统；
2. 安全规则；
3. 许可证策略；
4. 人工审批门；
5. 对外发布规则。

### 9.2 策略更新流程

```text
运行数据收集 → 失败模式归因 → 生成候选策略 → 离线回放评估 → 金集测试 → 影子运行 → 灰度上线 → 监控 → 晋升或回滚
```

### 9.3 技能抽象

当多个项目反复出现相似成功模式时，系统应抽象为 Skill Card。

```yaml
skill_id: skill_baseline_first_experiment
name: Baseline-first experiment design
trigger_condition:
  - new method idea
  - public benchmark exists
  - no verified baseline in project
action:
  - reproduce 1-2 strong baselines first
  - lock environment and dataset hash
  - only then run proposed method
success_metric:
  - reproduction_success_rate > 0.9
  - later experiment failure rate decreases
examples:
  - project_001
  - project_008
```

### 9.4 防退化机制

自进化必须有硬性护栏：

1. 所有新策略必须先在影子环境中评估；
2. 必须通过固定金集回归测试；
3. 不能降低安全、可复现、证据完整度指标；
4. 灰度上线比例从 5% 开始；
5. 连续两个周期负收益自动回滚；
6. 所有策略变更必须记录版本、原因、评估结果。

---

## 10. 论文生成与质量控制

### 10.1 论文生成原则

论文不能从“写作”开始，而必须从“证据”开始。推荐顺序是：

```text
证据链 → 实验结果 → 图表 → Claim 列表 → 论文大纲 → 分节写作 → 引用校验 → 审稿模拟 → 修改
```

### 10.2 论文结构

```text
paper/
├── main.tex
├── sections/
│   ├── abstract.tex
│   ├── introduction.tex
│   ├── related_work.tex
│   ├── method.tex
│   ├── experiments.tex
│   ├── results.tex
│   └── conclusion.tex
├── figures/
├── tables/
├── references.bib
├── reproducibility_checklist.md
└── evidence_map.json
```

### 10.3 质量评分维度

| 维度 | 权重 | 检查内容 |
|---|---:|---|
| Novelty | 20% | 是否有明确新意，是否区别于已有工作 |
| Technical Soundness | 25% | 方法是否正确，实验是否支持结论 |
| Experimental Rigor | 25% | baseline、ablation、统计检验是否充分 |
| Reproducibility | 15% | 代码、数据、配置、环境是否可重跑 |
| Writing Quality | 10% | 结构、表达、图表、逻辑是否清晰 |
| Compliance | 5% | 许可证、伦理、AI 使用声明是否完整 |

---

## 11. 风险矩阵

| 风险 | 严重度 | 概率 | 触发场景 | 缓解措施 |
|---|---|---|---|---|
| 伪造或无效实验结果 | 高 | 高 | 代码未真实运行但生成了结果文本 | 强制日志、产物、指标、重跑验证 |
| 引用幻觉 | 高 | 中 | 论文中引用不存在或不支持 claim | DOI/URL 校验，claim-evidence 绑定 |
| 自进化退化 | 高 | 中 | 新 prompt 表现更差但被上线 | 金集测试、影子评估、灰度、回滚 |
| 成本失控 | 中 | 中 | HPO 或云 GPU 长时间运行 | 每任务预算、早停、成本告警 |
| 安全越权 | 高 | 低-中 | 实验代码访问系统目录或凭证 | 默认沙箱、最小权限、审计日志 |
| 学术诚信风险 | 极高 | 中 | 未经人工确认自动投稿 | 投稿前人工签字与 AI 使用披露 |
| 许可证风险 | 高 | 中 | 使用无授权代码或数据 | License scanner、准入白名单 |
| 知识库污染 | 中 | 中 | 错误总结进入长期记忆 | 置信度、来源标记、版本回滚 |
| 多 Agent 失控循环 | 中 | 中 | Agents 互相调用导致死循环 | 最大深度、预算、状态机、熔断 |

---

## 12. 失败场景推演

### 场景 A：系统生成了看似优秀但无法复现实验结果

处理流程：

1. Result Validator 标记为 failed_reproduction；
2. 阻止 Paper Generator 使用该结果；
3. 保存失败日志和配置；
4. Failure Analyzer 归因；
5. 生成修复任务；
6. 若连续失败，终止项目或退回实验设计阶段。

### 场景 B：系统引用了一篇不存在或不相关论文

处理流程：

1. Citation Validator 查询 DOI/URL；
2. 若不存在，删除引用并标记幻觉；
3. 若存在但不支持 claim，要求重新检索证据；
4. 将该错误写入失败库；
5. 降低对应 Summarizer/Writer 策略权重。

### 场景 C：自进化策略上线后整体表现变差

处理流程：

1. 监控发现综合 reward 连续下降；
2. 自动切回上一稳定版本；
3. 冻结该策略族；
4. 生成回归分析报告；
5. 只有通过人工审批后才能再次进入灰度。

---

## 13. 三年路线图

### 第 0-6 个月：实验室级 MVP

目标：完成最小可信闭环。

交付物：

1. 文献检索与知识库；
2. 单研究项目 Project Agent；
3. 实验代码生成与沙箱执行；
4. 结果收集与基础验证；
5. LaTeX 论文初稿生成；
6. 最小复现包；
7. 基础失败库。

验收：10 个封闭 benchmark 任务中，至少 6 个能完成从假设到论文初稿的闭环。

### 第 6-12 个月：稳定研究助手

目标：提升自动化率和复现率。

交付物：

1. 多 Agent 协作稳定化；
2. MLflow + DVC + Git 全链路追踪；
3. 引用验证与 claim-evidence map；
4. 模拟审稿与自动修改；
5. Compute Scheduler 与并发实验；
6. 策略库与技能库初版。

验收：自动化率 ≥80%，可复现率 ≥95%，引用错误率 <1%。

### 第 12-24 个月：自循环科研平台

目标：系统能持续运行并周期性生成候选研究。

交付物：

1. 研究方向池；
2. 定时文献趋势分析；
3. 自主项目创建；
4. 长期运行监控；
5. 影子评估环境；
6. 灰度发布与回滚机制。

验收：系统可连续运行 30 天，稳定产生候选方向、实验报告和论文草稿，无严重安全或学术诚信事故。

### 第 24-36 个月：可商用级科研操作系统

目标：从内部平台走向可部署产品。

交付物：

1. 多用户权限与团队协作；
2. Web Dashboard；
3. 插件市场；
4. 企业/高校私有化部署；
5. 合规审计模块；
6. 成本管理与 SLA；
7. 可商用 API。

验收：支持多个团队并发使用，具备权限隔离、审计、监控、计费、私有化部署能力。

---

## 14. 研究创新点

1. **从 Agent 编排升级为科研操作系统**：不仅生成内容，而是管理研究生命周期。
2. **证据优先的论文生成机制**：每个结论绑定可追溯证据链。
3. **可回滚自进化**：自进化不是自由修改，而是影子评估、灰度、回滚。
4. **知识—实验—论文统一 provenance**：代码、数据、指标、图表、claim 全链路绑定。
5. **面向科研质量的综合 reward**：同时优化质量、复现、成本、风险和人工干预。
6. **失败库驱动的持续改进**：把失败作为一等知识资产。

---

## 15. 最终判断

该系统具有较强研究价值和工程价值，但必须避免一开始就追求“完全无人化”。最可落地的路径是：

```text
最小可信闭环 → 高自动化研究助手 → 长期自循环平台 → 可控自进化系统 → 可商用科研操作系统
```

第一阶段的核心不是“写出一篇看起来像论文的文本”，而是证明系统能够稳定地产生：

1. 可执行实验；
2. 可验证结果；
3. 可追溯证据；
4. 可复现产物；
5. 可审查论文草稿；
6. 可迁移经验。

只有这六项成立，后续的全自动科研、自循环、自进化才有真正基础。

---

## 16. 2026-07 榜题优先补充：科学机器学习与数学建模

当前垂直冠军方向固定为“科学机器学习 × 数学建模 × 动力系统发现”。这不是取消证据优先、
Vault、沙箱、复现、发布和回滚门，而是先用可精确评分的科学任务检验它们是否真正连成同一条
执行因果链。

采用两级门禁：Gate A 使用 MDBench 方程发现验证自动选题、假设编译、代码执行、结构恢复、
噪声鲁棒性和跨随机种子复现；Gate B 仅在 Gate A 真实通过后，使用 RealPDEBench Cylinder
sim-to-real 预测形成主参赛案例。Gate A 开发夹具只能验证工程生命周期，不能替代官方数据、
基线和 10 ODE/4 PDE clean/noisy 矩阵。

官方 Gate A 路径必须先经过独立预检：固定上游 revision、代码许可、Zenodo 数据许可、归档
大小/校验和及容器运行时均形成机器可读证据。公开下载地址不等同于许可；缺失许可或运行时
时只产生最小范围 `AccessRequest`。预检和容器 CLI 烟测通过也不等于执行过 MDBench。
通过预检后的数据准备还必须支持断点续传、固定大小/MD5、逐文件 SHA-256、安全原子解压和
幂等复核。真实清单确认系统与噪声覆盖只能证明官方数据已就绪，不能替代方法执行、复现和结论门。
方法执行前必须进行结果盲预注册：系统、开发/未见测试边界、噪声条件、时间切分、种子、方法预算、
指标和接受标准共同形成内容哈希；加载时重新计算该哈希，禁止事后更换更容易的数据或指标。
执行适配器必须把归一化时间边界物化为互不重叠的具体索引，以只读方式挂载单个数据文件，并在
禁网、限 CPU/内存/时间的一次性容器中运行。成功、失败和超时都写成终态证据；恢复前重新验证
矩阵、数据、配置、spec、runner、宿主编排器、镜像、日志和结果哈希。冻结矩阵现已形成
252/252 个终态：244 成功、8 失败、0 超时，且完整恢复调用复用了全部 252 条已验链结果。
这证明官方执行与恢复路径成立。正式聚合器随后验证了矩阵、执行、spec、结果、日志、环境和
真实方程来源的哈希，保留 6 个稀疏基线失败与 2 个 Operon 失败，并完成结构 F1、导数误差、
轨迹外推、复杂度、噪声鲁棒性和成本分析。候选方法 84/84 成功，成功单元的导数 NMSE 中位
相对改进为 82.89%，失败感知的未见系统中位改进为 37.15%；但 20,000 次系统级 bootstrap
95% CI 为 `[-0.201060, 0.888991]`，且全方法仅 244/252 成功。因此 Gate A 诚实关闭为
`negative_result`，`gate_b_allowed=false`；有利点估计不授权 Gate B、提交或获奖结论。

负结果之后不允许在已揭示的未见系统上继续调参。恢复周期必须绑定父矩阵和负结果报告哈希，
采用不同且可证伪的机制，并重新冻结与父周期完全隔离的未见系统。本轮恢复假设仅包含两个机制：
弱形式投影降低逐点导数噪声敏感性，bootstrap 支持稳定性降低跨系统稀疏结构方差。新矩阵沿用
同一官方归档和两种基线，使用新种子 13/29/43；旧周期所有未见系统在恢复矩阵中一律禁用，
恢复周期的六个未见系统也不得出现在旧矩阵任一 split，只有旧开发集 `advection1d` 与 `burgers`
继续作为开发控制项。实现依赖固定到 MIT 许可的 PySINDy v1.7.5；未检测到许可文件的 WSINDy
仓库只作思路参考，不复制或 vendoring 代码。候选实现现已在镜像内通过合成 ODE/PDE 自测，并只在
四个 development cells 上完成 4/4 有限结果与幂等恢复。列归一化 STLSQ 修复后，clean
`advection1d` 恢复为 `u_t=-0.100002u_x`，导数 NMSE 为 `1.27e-6`；SNR20 development 控制
仍选择零方程、NMSE 约为 1。这是有价值的负面开发信号，不是恢复 Gate A 的通过证据；六个新
未见系统在该开发阶段仍未执行或查看。

冻结实现与真值评分提交后，恢复矩阵已在同一镜像中完整排空：252 个单元全部进入终态，
241 成功、11 失败、0 超时，人工介入和权限请求均为 0；相同命令复跑时 252/252 条唯一结果哈希
全部通过验证并复用，没有重算。裁决器仍使用结果揭示前固定的真值注册表哈希
`38d549143207b177b6a2c9430e5b68cdd89e4dd80b41eaf04d082f5b255b04dd`、分析策略哈希
`ef60d9a245a7a0937b99361d71ed31d2c79116b25ff45098d9f39c554d9cbd9f` 和源码哈希
`b2037a1c765aa8274205da85c59c35958405abbea81ee5498a515ef8796b7d31`。候选在 clean 未见系统上的
导数 NMSE 中位数为 `0.014638`，优于 Operon 的 `0.091415`，但在主评价 SNR20 未见系统上退化为
`6.717294`，而 Operon 为 `0.698001`；候选成功 82/84，全部方法成功 241/252。失败感知的六系统
中位相对改进为 `-1.704061`，20,000 次系统级 bootstrap 95% CI 为
`[-4.116249, 0.292912]`。因此恢复周期同样关闭为 `negative_result`，
`gate_b_allowed=false`；弱形式/支持稳定性机制族停止，不在已揭示系统上修补、调参或启动 Gate B。

默认 `topic_mode=auto`。用户题目、论文和指导仅是可选的 `seeded` 约束，不能绕过数据许可、
资源、重复风险、可证伪性和可复现性硬筛选。科研选择不等待人工审批；只有 API 凭据、数据许可、
网络/GPU/存储/费用或外部提交权限缺失时，系统才生成最小范围 `AccessRequest`。

每项结论必须由 `CycleManifest` 绑定 `topic_id`、`hypothesis_id`、`plan_hash`、`code_hash`、
数据哈希、模型版本、随机种子、指标、费用和父节点。候选与实际实验不一致、只有文件没有执行、
常数指标或复现失败时直接阻断。最高奖项不作保证；系统的承诺是自动完成或诚实停止、结果可信、
差距透明，以及未达到实证和评分门时不提交。

---

## 17. 2026-07-23 自主成果循环：从单周期证据链到跨周期科研因果链

任务 260 不把“检查别人论文是否真实”当作循环目标，而是要求系统把本轮失败转化为下一轮不同、
可证伪的原创机制，再执行新冻结实验并更新研究报告和论文。新增
`AutonomousResearchCampaign` 位于旧 competition 与 autopilot 之上，状态顺序固定为
`observe -> diagnose -> propose -> screen -> preregister -> develop -> freeze ->
unseen evaluate -> adjudicate -> report`。负结果只能进入新的 result-blind round；已揭示未见结果
不得回流到同轮提案或开发选择。

任务 260.1 已建立严格的 campaign/round manifest、父结果与父轮哈希、逐阶段原子产物、顶层 lineage
hash、截止时间与最小新实验轮数门。提案适配器只接收历史证据和本轮开发数据引用，当前未见引用
被结构性隔离；预注册提前冻结候选空间、停止规则、实现族和 adjudicator，开发后只允许冻结所选
代码与配置。负结果子轮必须改变机制族，重启只复用已验链阶段，内容篡改直接阻断。每轮终态由
runtime 写入 `autoresearch-vault/`，但 Obsidian 记录本身不等于科学贡献或投稿许可。

任务 260.2 已把该控制面注册为 `campaign start/resume/status/export`，并将 hypothesis、
preregistration、experiment manifest、原始指标/日志、validation、failure/research/loop report、
evidence map、图表、round decision 和逐轮 manuscript 设为强制产物。exporter 先复验完整父子哈希
链，再复制 campaign 与 adapter 原始证据，生成集中索引、环境锁、复现入口和文件哈希清单；内部
contribution gate 永远不会自动变成外部投稿许可。运行期 Vault 写入只更新本 campaign 的 project
索引，不重建或改写无关知识条目。

任务 260.3 已用真实 MDBench adapter 取代默认 fixture。元数据审计在排除两轮历史面板后确认还有
49 个未使用 ODE 与 8 个未使用 PDE，并在结果揭示前冻结两组互斥的六系统 ODE holdout。正式
campaign `task260-autonomous-ccfb-v1` 独立完成两个新实验轮次，每轮 240 个 frozen cells、
clean/SNR20、三个新种子、Operon 强基线与三项消融，科研决策人工介入为 0。

第一轮 noise-conditioned Savitzky--Golay + coefficient-bootstrap ensemble 的开发中位相对改进为
`0.779785`，但未见系统级 bootstrap 95% CI 为 `[-3.053723, 0.953866]`；第二轮 smoothing
spline analytic derivative + cross-output group-sparse projection 的开发中位相对改进为
`0.672083`，未见 CI 为 `[-2.157336, 0.921594]`。两轮点估计都不能抵消跨系统异质性与负下界，
且各有一项消融在部分 frozen cells 失败，因此确定性贡献门均返回 negative result。系统保留完整
报告、原始指标、图表、日志、父子哈希与逐轮 manuscript，终态重启不产生新科研调用。Route A
据此关闭并强制转入任务 260.4 的 systems-paper matrix；这两个负结果不能被描述为 CCF-B 方法
贡献通过。外部投稿始终需要人工批准。

任务 260.4 已把 Route B 实现为预注册、可重复执行的系统行为 benchmark，而不是让模型自评。
四个 UCI 任务在预注册前重新执行并生成真实 run record、validation、evidence map 和数据哈希；
六个 MDBench 任务只回放任务 260.3 已揭示的真实 trace，明确禁止作为新方法 holdout。冻结合同
包含 10 个任务、种子 211/223/227、one-shot、execute-once、full-loop、四项消融、受控失败、
源证据哈希、evaluator 字节哈希和 20,000 次配对 bootstrap。每个 cell 独立输出研究报告、
evidence map、科研结果哈希和同种子 reproduction hash。

正式 210-cell 结果中 one-shot、execute-once 和 full-loop 的任务成功率分别为 `0.20`、`0.50`
和 `1.00`；完整循环的负结果恢复率为 `0.625`，精确复现率为 `1.00`，错误科研声明与科研决策
人工介入均为 0。相对 execute-once 的配对成功率增益为 `0.50`，bootstrap 95% CI 为
`[0.333333, 0.666667]`。无 Vault、无失败反馈、无预注册、无证据门成功率依次为 `0.70`、
`0.50`、`0.00`、`0.80`；无证据门留下 6 个错误声明。内部 systems contribution gate 因此
通过，但它只授权任务 260.5 构建和独立审查论文证据，不等于 CCF-B 就绪或外部投稿许可。

任务 260.5 已把两条不可变证据链合并为论文包
`task260-final-paper-v2`。论文题为 *Evidence-Bound Self-Iteration for Autonomous Research:
A Preregistered Local Systems Study*，使用 ACM `sigconf` 双栏格式，共 11 页、40 条正文实际引用
且在线来源审计 40/40 通过。正文明确区分 Route A 的两个真实方法负结果与 Route B 的受控系统
行为贡献，并披露受控故障、确定性转移策略、种子非独立、已揭示 MDBench trace 仅用于行为评测
等有效性限制。

独立复现从全新目录重新读取冻结输入、复算 20,000 次 bootstrap、编译五张矢量图和完整论文；
主目录与复现目录 PDF 的 SHA-256 均为
`9199a1146fce116b0035090dbca3df27dc38a4c740fb1f935f06c587317a4a3b`。最终哈希清单覆盖
3,269 个文件，包括两条完整 campaign dossier；claim-evidence、citation、LaTeX reference、
表图、页数、布局、严格审稿和复现门全部通过。包级结论只为
`ready_for_human_submission_review`，不是 CCF-B 录用保证；作者、创新性、venue fit、许可和任何
外部投稿仍必须由人类明确批准。

---

## 18. 2026-07-24 自主来源审计：从“人选机制后自动跑”到可验证的 bounded autonomy

任务 260 证明了跨轮状态、真实实验、失败保留和论文包可以连通，但它没有证明选题与机制由同一
运行时独立产生：Route A 两个机制与 Route B 程序均在启动前由人写入代码，正式 Qwen 调用还曾
使用确定性回退，论文构建是后续单独命令。因此，任务 261 将“科学结果是否可靠”和“科学选择
是否由运行时产生”拆成两条都必须审计的因果链。

任务 261.1 新增 `AutonomousResearchSprint`。一个 `campaign sprint-run` 从高层目标出发，实时
获取文献快照，让本地 `qwen3.5:9b` 在至少三个已经可执行的研究程序之间提出候选并选择主问题，
随后在同一进程和哈希账本内执行所选程序、以 task 而不是 seed 为独立统计单位、生成论文正文并
自动编译 PDF。选题和正文最多允许两次严格 JSON-schema 请求；模型不可用或仍不合规时必须停止，
不能用代码模板伪装成自主选择。确定性代码继续拥有数值、bootstrap、贡献门、图表、引用绑定、
结果解释和 PDF 质量门。

clean-v2 正式运行从空目录一次完成。Qwen 选择 `C003` 与
`systems-evidence-gate-claims-task-v2`，topic/manuscript fallback 均为 false，启动后的人工科研
决策为 0。10 个独立任务、每任务三个重复的配对结果均值为 `0.20`，但 95% bootstrap CI 为
`[0.00, 0.50]`，所以科学贡献门返回负结果。系统仍自动生成并编译六页 ACM PDF，物理质量门
通过。该结果的正确表述是：证明了一个可恢复、无运行期人工科研选择的一命令 bounded-autonomy
管线；没有证明证据门带来可靠改进，更没有证明开放式独立选题、任意新机制代码生成或 CCF-B
创新度。

自治审计固定区分启动前和启动后。高层 brief、截止时间、算力边界、导入的 Route A 证据、
三个程序及其实现仍是人工预置，因此审计只能返回 `bounded_autonomous`。clean-v2 论文的正文
只有一条实际参考文献，且模型对受控故障夹具的概括仍可能被读成一般 Agent 行为；这虽然不影响
任务级负结果和哈希有效性，却阻断投稿就绪与高创新度结论。

任务 261.2 必须从 clean-v2 的负结果哈希出发，形成“原因诊断 -> 新机制提案 -> 受审查的新代码
-> 开发筛选 -> 新预注册 -> 未揭示任务裁决”的新科研轮。只有模型提出的机制、实际执行代码和
结果共享可验证因果哈希，才允许把 `open_ended_experiment_code_generation` 置为 true。同时加入
逐项 claim-evidence 与 named-work 引用门；提示词修改、论文重写、门槛降低或在已揭示十任务
面板上重跑都不算新的科研迭代。

Task 261.2.1 已冻结这条新科研轮的证据基础，但尚未产生机制或结果。实现会重新验证 clean-v2
manifest、负 endpoint、autonomy audit、topic selection 和 10 个已揭示任务，再生成可移植的
parent evidence hash。交叉检索保留 14 个经正式页面核对的来源，覆盖选择性事实性/弃答、科研
Agent 评价、生成代码安全和 claim-evidence 对齐；最终 research brief hash 为
`9b9b492dcbb33e5d454f628ed06fe3982970fb8a79057f14f1dba0167dea45b0`。来源可达烟测 14/14
通过，但“页面可达”不等于论文结论正确。

新的内容寻址合同把 diagnosis、模型交互、proposal、精确生成代码字节、静态审查、单测/性质测试、
Harness sandbox episode、development/confirmatory 分区、round freeze 和 typed manuscript claim
串成可验证因果链。新面板不得复用父轮任务，开发与确认分区不得重叠，确认结果在 code freeze 前
保持 sealed。只有 exact code 通过全部审查且 proposal/code/execution hashes 一致时，未来的 child
freeze 才能记录 `open_ended_experiment_code_generation=true`；Task 261.2.1 自身没有创建该
freeze。综述与反方审查保存在
`autoresearch-vault/exploration/task-261-2-generated-mechanism-evidence-survey-2026.md`。

Task 261.2.2 已把上述合同落成一次真实、受限且可追溯的机制开发。最终本地模型
`qwen3.5-sprint:9b-8k` 生成 `Multi-Signal Degradation Gate with Source Counting`：模型拥有
五信号风险表达式、接受表达式和 reason codes，固定的 `safe-expression-compiler-v1` 只提供
JSONL I/O、逐项循环和输出序列化，不提供权重、阈值或科学判断，也不在失败时修补代码或制造
fallback 结果。这里的 `open_ended_experiment_code_generation=true` 仅表示模型机制程序、
精确编译源码和执行证据形成了完整因果链，不表示任意语言代码、无限制工具使用或独立选题。

权威证据保存在 `runs/manual-live/task2612-mechanism-development-live-v12/`。manifest、proposal、
mechanism program、generated source、generated-code evidence、round freeze 和 development
screen hashes 分别为
`55c4604474517317114fa88fa389aced28ca5ba96f2eafee6832cfcceb24737e`、
`550515c2838b45f37b7536837e5afbafced123a03f5c176e73eaa93f6f782f2e`、
`e0b4d9b7ce3ea29a5fe370c5edec8f8ff1830a763cf7a034e41ef2cf4f60d57d`、
`7b4961c62a7b8a253eb44d1e656dde3abc30dc1d6c1fc4e25b17745eca137025`、
`10102c8a087ee2604e4fc3f27c1a87988bab4032da8c080db9204c73a8f8d439`、
`9db3ade055f721bcc54f6330843b7431354442b1403e9ad04ab19ec0f035424d` 和
`a3e11132d6e48950a927e062a590b1943e09644e0f72d5312635afd64cfc16fc`。
精确源码通过静态安全、单元、性质、秘密/网络/路径和 Harness gates；开发集接受 18/24 条声明，
coverage 为 `0.75`，unsupported-accept rate 为 `0.0`，因此只进入
`advance_to_preregistration`。确认结果仍未揭示、确认结果工件数为 0、scientific result 为
false、external submission 为 false。v11 曾通过旧性质集却在闭区间数值边界发生除零，因此新增
0/1 边界探针后被 v12 取代；v1-v11 全部作为失败或被取代证据保留。
最终执行器审计又要求实际启动包装器与受审机制源码同时通过基线预检；冻结 v12 源码在该最终
路径上的 replay episode hash 为
`62dce7261cf92c4535d23e24e5002bcdbf350a3286e7e3a83ff3800fff24b1c1`。一次新的 v13
模型诊断则因 `extreme_unsupported_abstains=false` 被性质门阻断；为避免反复采样直至成功，
不再生成替代候选，v13 仅保留为 fail-closed 诊断证据。

Task 261.2.3 已在任何确认结果出现前冻结 v12 的精确源码、依赖锁、Python 可执行文件、实现文件、
环境、独立面板、任务级 bootstrap、coverage/unsupported-risk 门和单次停止规则。预注册、环境与
Control Graph hashes 分别为
`1e499a27da3bbba08be9f7a2e47de06c5c49d216c96230d46388971ad3659464`、
`0198b9e7a8c13258d139ce4398162c6c272c491aa64ff3358aa63a06a67b1ea8` 和
`fe2d9e96b264d86b5ae87602dce4628c72de49019d17a48344cba8051b7fab44`。三个开发任务与六个
确认任务不仅 task ID 不重叠，source fingerprint 也各自唯一且分区互斥。

权威一次性运行保存在
`runs/manual-live/task2612-mechanism-confirmatory-live-v1/`。六项任务全部在无网络 Harness 中
一次成功，共评估 48 条声明、接受 28 条、其中 1 条为 unsupported accept。未支持率
`0.0357` 的任务级 bootstrap 95% 区间为 `[0.00, 0.10]`，满足冻结上限；coverage `0.5833`
的区间为 `[0.4792, 0.6875]`，点估计低于冻结下限 `0.60`。因此唯一失败门是
`minimum_coverage_met`，科学 endpoint 必须并已经封存为 `negative_result`，hash 为
`d449343654e28a4da877d0ab7a3bd07e334ac8cad310385996c635bacbae165d`。这一结果说明机制在该
面板上控制了已接受声明的残余风险，却过度弃答，不能作为正贡献或投稿就绪证据。

Event Journal、provenance-v2、evaluation/security、干净目录独立重算和非破坏 rollback 演练均
通过；220 个终态文件的幂等复载没有新增、删除或改写文件。不得用已揭示的这六项任务修改表达式、
阈值或源码。Task 261.2.4 只能忠实构建负结果论文与 claim-evidence audit；任何后续机制改进都
必须重新进入开发筛选并冻结新的独立确认面板。外部投稿授权仍为 false。

Task 261.2.4 已把该不可改写的负 endpoint 建成
`runs/manual-live/task2612-mechanism-paper-live-v1/`，并在独立空目录
`runs/manual-live/task2612-mechanism-paper-reproduction-live-v1/` 完成第二次构建。论文不是自由
改写的模型长文：51 个 material paragraphs 全部登记为 named prior work、method、experiment、
result、limitation 或 figure description，解析到 26 个类型化证据记录和 77 条支持边；逐段
exact-occurrence、evidence-kind、artifact hash 与 frozen-source entailment 均通过，没有未登记
材料段落或 unsupported claim。

14 个冻结的一手/官方来源均在正文中各有 named-work claim、inline source token 和 reference
条目；live reachability 再检查得到 14 个 HTTP 200 且每个响应至少 1,000 bytes。四类相邻工作
覆盖为 selective factuality 4、scientific-agent evaluation 3、generated-code security 3、
claim-evidence alignment 5。五张图和一张六任务表均由冻结 JSON 或结果合同生成，caption、正文
描述、文件 digest、任务计数与 endpoint metric 一致。

主稿与独立重建的 24 个确定性 source artifacts 全部逐文件相同，并各自编译成 13 页 PDF。主稿
2,512 words、16 个 technical terms、5 figures、1 table、14 references、0 overfull boxes；逐页
PNG 视觉检查未发现裁切、重叠、不可读图表或未解析引用。paper package、manuscript 和 PDF hashes
分别为 `462c428dc1c863407042ae48ad1cb2245a942ba0af93744a0022804eeb26bcc8`、
`c33b915bb762a4d3d1dabe44bf4be5a13fc100d1ad63d6c45e3e6b67fd964b30` 和
`e3d2ae122d096e960ae78bac5d045974399790c175190740599278cf2b38e22e`。

最终 paper audit 忠实保留 `negative_result`：unsupported-risk 门通过并不能抵消 coverage
`0.5833 < 0.60`。`scientific_submission_gate`、`authorship_review`、`license_review` 和
`explicit_human_approval` 明确失败，因此 positive contribution、submission readiness 与
external submission 全为 false。Task 261.2 至此完成的是一条可复核的负结果科研因果链，而不是
投稿许可；任何新机制必须开启新的开发分区和独立确认面板。

---

## 19. 2026-07-28 vNext 架构升级：Graph、Harness、Loop 与 Open Science

### 19.1 研究判断

对 2025—2026 年原始论文、官方运行时文档与开放科学规范的交叉检索表明，AutoResearch 当前的
主要问题不是功能缺失，而是语义碎片化：`agents/workflow.py`、competition、campaign、sprint、
audit、evidence graph 与 Obsidian Vault 分别实现了部分图、循环、恢复、证据与记忆能力，却没有
共享的事件、节点、边、决策、审批、产物和终态契约。继续在每个服务内增加状态机只会扩大验证面。

vNext 因此采用“一条内容寻址事件脊柱、四个独立图平面”的架构：

1. Control Graph 表达执行依赖、并行、预算、审批、重试、补偿、停止、恢复和 fork。
2. Provenance & Evidence Graph 以 W3C PROV 的 Entity、Activity、Agent 为基础，扩展 claim、
   counterevidence、decision、validation、model/tool interaction 与 artifact。
3. Knowledge & Context Graph 组织来源锚定的论文、概念、方法、数据、假设、失败、技能和策略。
4. Evaluation & Policy Graph 组织 task、trial、trajectory、outcome、rubric、grader、权限、
   promotion、shadow 与 rollback。

四个平面引用稳定 ID，但不得合并为单一“万能图”。Control Graph 需要终止与恢复约束，Evidence
Graph 需要方向和验证状态，Knowledge Graph 允许不完整和时效变化，Policy Graph 必须 fail closed。
完整论证、差距矩阵、反方审查与来源登记保存在
`autoresearch-vault/exploration/graph-harness-loop-open-science-2026.md`。

### 19.2 Vault 与运行历史的双层真相

`autoresearch-vault/` 继续是权限化项目记忆和人类可审阅知识的 canonical substrate。文献笔记、
假设、失败、技能、策略、项目状态与决策说明必须进入 Vault。新的 append-only event journal 只作为
“一次运行实际发生了什么”的 canonical runtime history；它通过顺序、父哈希、actor、输入/输出
artifact、decision 和 approval 生成机器可重放的事实链。

运行事件可以生成 Vault 投影，但不能覆盖人工审阅；Vault 中可执行的任务或策略必须反向引用事件与
产物哈希。哈希只提供 tamper evidence，不证明外部事实或科学结论正确，真实性仍由 source snapshot、
真实执行、独立复现、统计门和人类责任建立。

### 19.3 Harness 与 Loop 的研究契约

Harness 不再等同于 prompt。它必须版本化任务说明、上下文选择、模型策略、工具与 sandbox、项目记忆、
任务状态、权限、验证、可观察性、失败归因、费用和干预记录。每次 harness 修改都要声明预测、作用范围
和回滚点，并由后续 task-level outcome 验证，不能只比较最终文本。

Loop 必须声明状态、允许转移、幂等键、前置条件、输出证据、预算、停止/转向/升级规则和 holdout
可见性。模型可以提出候选，确定性代码拥有统计、门、权限、外部发布和结果解释边界。一次冻结执行中
不得静默修改图；开放探索通过生成带 parent hash 的下一图版本实现。

### 19.4 Open Science 互操作目标

现有 reproducibility package 和 hash manifest 保留，并逐步附加 RO-Crate 1.3、
Workflow/Provenance Run RO-Crate 0.5 与 W3C PROV JSON-LD。软件、数据、workflow、环境、贡献、
引用、许可与供应链分别对齐 FAIR4RS、CodeMeta、CITATION.cff、CRediT、DataCite、SWHID、SPDX
和 SLSA provenance。OpenTelemetry GenAI 只作为脱敏、默认本地的可观察性导出。

开放遵循 “as open as possible, as closed as necessary”。内部完整包、审稿/复现包和公开包采用不同
视图；任何公开数据、私有来源、模型轨迹或外部投稿仍需要许可、隐私检查和人类批准。标准合规只证明
可交换性，不等同于结果已复现或论文可录用。

### 19.5 验证假设

vNext 的核心可证伪假设是：统一事件与图契约能在不改变现有 scientific endpoint 的情况下，减少重复
恢复逻辑，使一个真实 campaign round 可回答“谁在何时用什么输入、代码与策略生成了哪项结果，并支持
或反驳哪条声明”。如果 shadow-write 与旧路径的终态、gate、artifact 或 failure 语义不一致，新内核
不得 promotion。

任务 `262.1` 冻结本计划；`262.2` 从零行为变化的事件与图契约开始。随后依次实现 journal/replay、
HarnessSpec、LoopSpec/Control Graph、PROV/Vault 投影、Open Science 导出、纵向服务迁移与安全评测。
LangGraph 主版本升级、图数据库和旧状态机弃用都延后到 characterization 与两个真实 vertical run
通过之后。

`262.2` 已在 2026-07-28 完成第一项可证伪实现：`autoresearch.kernel` 提供严格的 v1 `RunEvent`、
`EventActor` 与四平面 `GraphNode/GraphEdge/GraphSnapshot`。事件内容经 UTC/JSON 规范化后计算并验证
canonical SHA-256；图快照拒绝重复、悬空、跨平面、自环和未显式标记的控制循环，并稳定导出 JSON
Schema。31 个 focused/property tests 覆盖全部 contract 代码，全量回归通过。该任务没有写 journal、
没有迁移旧服务，也没有改变依赖或历史结果；链连续性、原子持久化、敏感字段拒绝、replay 与 fork
由 `262.3` 继续验证。

`262.3` 已在同日完成可恢复事件层：每个事件以连续序号命名的独立 canonical JSON 文件提交，经临时
文件 `fsync` 后原子替换；独占 writer lease、expected-lineage、幂等键、parent hash、run lineage 与
terminal seal 共同阻断并发覆盖、重复副作用、断链和终态追加。journal 可在验证全部已提交字节后选择
checkpoint、确定性 replay，并创建首事件绑定不可变父 checkpoint 的新 run；非终态 fork 必须显式
批准。故障注入覆盖 pending/event/seal 间断、stale writer、corruption 与 crash/resume，事件全信封在
持久化前拒绝 secret-like 内容和直接 email 标识。33 个 focused/fault/property tests、临时文件系统
smoke、811-test regression 及全量 Ruff/Mypy 均通过；`journal.py` 行覆盖率为 89%。该实现仍未接入
Competition、Campaign、Sprint 或 AuditLog，旧状态文件继续权威，下一切片由 `262.4` 定义
`HarnessSpec` 与 episode package。

`262.4` 现已完成 provider-neutral Harness 层。content-addressed `HarnessSpec` 冻结并交叉校验 task、
context、model、tool、memory、state、permission、verification、observability、failure-attribution、
cost、entropy/intervention 与 evaluation policy；`HarnessRunner` 在 task `262.3` journal 上执行一个
有界 trial，并把 task/spec、trial、全 trajectory、environment outcome、grader、cost、intervention、
approval、failure、tool call、artifact、terminal event、seal 与 lineage 分离绑定到
content-addressed `EpisodePackage`。缺模型/工具/审批和预算耗尽进入 `blocked`，无效结构输出、工具/
grader/configuration 错误进入 `failed`，执行有效但未过冻结 grader 的结果进入 `negative_result`，
只有通过 evaluation policy 才进入 `succeeded`；失败路径不生成伪科研输出。31 个 deterministic
focused tests、真实本地 `qwen3.5-sprint:9b-8k` opt-in smoke、824-test regression、全量 Ruff 与
140-file Mypy 均通过。该 smoke 只证明 provider adapter 与 sealed episode，不是模型质量或科研结果；
多节点 retry/pivot/resume 必须由 `262.5` 的 LoopSpec/Control Graph 实现，不能藏进 Harness。

`262.5` 随后完成持久 Control Graph。content-addressed `LoopSpec` 显式冻结 node、edge、guard、预算、
retry、approval、compensation、stop、pivot、escalation、holdout 可见性与 terminal status；确定性
`ControlGraphRuntime` 只从 `EventJournal` 回放状态，在执行副作用前持久化稳定 idempotency key，并在
terminal event 与 seal 之间崩溃时恢复同一终态。模型只能提交下一 graph version 的非执行提案，不能
改写当前图、计算 scientific gate、扩权或批准发布。薄 `LangGraphControlAdapter` 位于 domain contract
之外；在不升级依赖的情况下，已冻结已安装 LangGraph 0.2.76/LangChain Core 0.2.43 的 checkpoint/
resume、静态与动态 interrupt、subgraph、parallel superstep、幂等和 JSON serialization 行为。一个
development vertical 将 sealed `EpisodePackage` 投影为 provider-neutral node result，并生成独立封印
的 Harness 与 Control Graph journals；这只证明控制/恢复链，不是科研结果或旧服务 migration。24 个
focused tests、848-test regression、全量 Ruff 与 142-file Mypy 均通过；`262.6` 将在此 event spine
上增加 W3C PROV-aligned evidence v2 与 source-anchored Vault projection。

`262.6` 已于 2026-07-29 完成可交换证据内核的第一半。新的 content-addressed
`ProvenanceBundle` 以 W3C PROV 的 Entity、Activity、Agent、Usage、Generation、Derivation、
Association 与 Plan 为基础，并加入 Claim、support/contradict/limit Evidence、Counterevidence、
Validation、Decision、ToolInvocation 和只保存摘要哈希的 model interaction。每条记录都有稳定 ID、
UTC valid time、version、invalidation、supersession 与 event refs；bundle 在读取和查询时验证引用、
时序、责任、source snapshot、生成关系和 canonical hash。`require_claim_trace()` 只有在来源/输入、
生成活动、冻结代码或策略 Agent、产物、当前有效验证与生成的决策产物全部存在时才返回，任何嵌套篡改
或关键 generation 缺失都会 fail closed。

现有 `EvidenceGraph` v1 实现未改变；v2 可把当前有效记录投影为 v1 reader 所需的 claim/source/
artifact/evidence 结构，其中只有 `supports` 映射为 `supports_claim=true`。Vault 投影使用显式批准
allow-list，能把文献、假设、失败、技能、策略、实验记录、证据和决策写成带 wiki-link、event ID、
artifact hash、confidence、validity 与 supersession 的 Markdown。真实
`task260-autonomous-ccfb-v1/round-001` 已在不重跑科学实验的情况下形成
`a2e54556b3f6e242deeaff3d7c87400ae23e701ef034983fb6964a3c2df4c782` bundle：核心负结果从冻结协议
和代码，经 unseen evaluation、确定性 contribution gate 与当前验证到 `next_round` 决策；原正向
假设同时保留 contradictory 和 limiting evidence。该任务没有改变历史 endpoint、旧 writer、依赖、
公开导出或投稿权限；RO-Crate/JSON-LD 与公开视图仍属于 `262.7`。

`262.7` 已于 2026-07-29 完成开放科研互操作切片。新的 exporter 在验证
`ProvenanceBundle` 后，以旁路目录生成 RO-Crate 1.3、Workflow RO-Crate 1.0、Process/Workflow/
Provenance Run RO-Crate 0.5、W3C PROV JSON-LD、CodeMeta 3.1、CFF 1.2、CRediT、DataCite 4.7
draft、SPDX 3.0.1 与 SLSA provenance-v1。Workflow Run 0.5 仍正式继承 RO-Crate 1.1，因此
descriptor 同时声明 1.3 当前 profile 与 1.1/Workflow RO-Crate 兼容 profile；这两个版本层被明确
区分，不把旧 profile 验证冒充为 1.3 外部认证。无真实 DOI 时 DataCite draft 固定
`depositReady=false` 且不生成 identifier；SWHID 只允许与 Git commit 相等的 revision intrinsic ID，
不声称已经归档。SLSA 只描述本地导出构建，明确 unsigned、无 level、无 trusted builder 与无科研
真值 attestation。

每次导出分为 internal-complete、review-reproduction 与审批后才可能出现的 public view。review
对 JSON 私有路径和敏感字段做确定性脱敏，不携带内部 provenance bundle；public 还必须同时通过
scope-matched 人工批准、显式 public artifact、许可与源文件敏感扫描。独立 clean-directory verifier
只在 `python -I` 下重算声明的 SHA-256 与冻结 JSON pointer 断言，不重跑科研实验。真实
`task260-autonomous-ccfb-v1/round-001` 的七个源产物和 provenance bundle hash 未变，六个负结果/
决策断言在新目录通过，public view 因无批准和无公开许可产物保持关闭。四个 WRROC/WROC 必需 profile
和 WROC 推荐 profile 均由外部 validator 通过，CFF 1.2.0 与 SPDX 3.0.1 官方 JSON Schema
均为零错误；Run-Crate
推荐层只保留“本地 workflow 文件应使用 HTTP ID”的两个重复 advisory，因为把已打包文件改成远程
资源会破坏 RO-Crate 数据实体语义。该任务没有替换旧 reproducibility package、修改科研结果、升级
依赖或执行公开发布；旧服务迁移仍属于 `262.8`。

`262.8.1` 已于 2026-07-29 完成第一个服务纵向迁移。Competition 保留原科学执行核心、
`cycle-manifest.json`、全部既有 artifact 和 reader；默认 `legacy` 模式不产生迁移副作用。
`shadow` 模式把每个不同的旧终态投影到独立封印的标准事件 journal 与无环 Control Graph，并逐项比较
event、终态、scientific endpoint、evidence gate、artifact hash、脱敏 failure semantics 及访问/人工
干预次数。`ACCESS_REQUIRED` 仍是可恢复 blocked，后续恢复使用绑定前一封印 checkpoint 的子 journal；
旧终态未变化时只生成 idempotency observation，不追加第二条 lineage。实验异常保留最后有效 manifest
阶段并映射为 failed，不会被误写成 scientific negative result。

`AUTORESEARCH_COMPETITION_MIGRATION_MODE=legacy|shadow|vnext` 是可逆 authority flag。`vnext`
在任何科研执行开始前验证两个不同 run ID、不同 formal ID、完整成功且 parity 等价的 shadow run；
promotion ledger 还重新校验 parity 文件 hash、journal seal、Control Graph 与投影，篡改即 fail
closed。真实本地 characterization 已完成两个 formal shadow vertical、一个 vNext-authority
vertical 和一次切回 legacy 的 rollback；返回 endpoint、投影、文件与封印 lineage 保持一致。
这些 run 只覆盖 generated characterization fixture，不是官方 MDBench Gate A。旧 compatibility
writer 和 reader 至少保留一个版本窗口。

`262.8.2` 已于同日完成 Campaign 纵向迁移。默认
`AUTORESEARCH_CAMPAIGN_MIGRATION_MODE=legacy` 不产生迁移副作用，原 Campaign scientific executor、
round manifest、研究/失败/循环报告、artifact、reader 与 writer 保持不变。显式 `shadow`/`vnext`
模式把每个不同的 Campaign observation 逐 stage、逐 finalized round 写入独立封印 journal 与无环
Control Graph，再比较 event history、终态、scientific endpoint、aggregate/per-round contribution
gate、artifact hash、脱敏 failure semantics 和 intervention count 七类 parity。失败记录最后一个有效
legacy stage，只保留异常类型与 message SHA-256；后续恢复使用绑定失败 seal 的子 journal，未变化终态
只产生 idempotency report。

Campaign 的正式 promotion 要求两个不同 formal ID、不同 Campaign ID、完整两轮实验且最终
`CONTRIBUTION_READY` 的 shadow run；ledger 在任何 vNext 科研执行前重新验证 report hash、journal
lineage/seal、projection、source fingerprint 与 graph，篡改或缺失 Vault/legacy artifact 均 fail
closed。真实本地 characterization 已完成两个 formal shadow Campaign、一个 projection-authority
Campaign 和一次 legacy rollback，生命周期、投影、文件与 journal 均保持一致。完整 fixture 是本地
generated migration fixture，不是官方 benchmark 或可投稿科研结果；`BLOCKED` corpus 项只冻结旧
schema/reader 能接受的 hash-valid 状态，当前 executor 本身不生成该终态。Competition 与 Campaign
compatibility writer 均至少保留一个版本窗口。

`262.8.3` 随后完成 Sprint 纵向迁移并关闭 M1。默认
`AUTORESEARCH_SPRINT_MIGRATION_MODE=legacy` 继续走原 topic selection、experiment、task-level
adjudication、manuscript、paper build、autonomy audit、Vault 与 status reader，不生成迁移文件。
显式 `shadow`/`vnext` 模式把既有 `AutonomyEvent`、artifact binding、scientific endpoint、paper/
autonomy gate、intervention 和终态投影到独立封印 journal 与无环 Control Graph，再逐项比较 event、
terminal、endpoint、gate、artifact、failure 和 intervention 七类语义。恢复从前一 blocked/failed
seal 创建 child journal；相同逻辑终态只写 idempotency observation，不向已封印 lineage 追加事件。

Sprint 的科学阴性结果仍是 `COMPLETED/COMPLETE`，不是运行失败。被旧执行器捕获的问题仍是可恢复
`BLOCKED`；在旧 try 边界之前逃逸的完整性异常只在迁移投影中记录异常类型和消息 SHA-256，并保留
最后有效 legacy outcome/stage。正式 promotion 可以接受正向 task-level gate 或经过完整论文、自治、
artifact、零 fallback、零运行后人工科研决策验证的负结果，但必须来自两个不同 formal ID 和 Sprint
ID。真实 adoption smoke 没有重跑模型、文献、实验、论文或投稿：它只读采用两个现有完成的真实负
结果 Sprint 作为 formal shadow evidence，再以一个现有 blocked Sprint 验证 vNext authority 和
legacy rollback。结果、投影、journal seal 与 compatibility files 均保持一致，迁移 JSON 不含私有
绝对路径。Competition、Campaign、Sprint writer 和旧 reader 仍保留到 `262.10` 的兼容窗口；依赖、
Gate B、公开发布与外部投稿权限均未改变。

`262.9` 在上述迁移层之上补齐统一评测、可观测性和 Agentic 安全门。交叉检索基线记录于
`autoresearch-vault/exploration/unified-evaluation-observability-security-2026.md`，覆盖 Inspect AI、
ScienceAgentBench、CORE-Bench、MLE-bench、AgentDojo、METR、OWASP Agentic Top 10、NIST AI
600-1/100-2、OpenTelemetry GenAI 与 grader/holdout 污染研究。设计冻结两条不可互相替代的结论：
系统协议/重放/权限是否可靠，以及科学结果是否有匹配证据；经过验证的科学阴性结果可以是成功研究
trial，流程成功但证据不匹配必须失败，`unknown` 一律 fail closed。

统一评测报告把 task、trial、trajectory、outcome、rubric、grader、uncertainty、cost、failure
slice、promotion 和 rollback 组成内容寻址记录。五个本地 regression 维度分别验证 protocol、
evidence、scientific core、replay 和 holdout；十类确定性 fault 覆盖 goal hijack、tool misuse、
identity/privilege、supply chain、unexpected code、memory poisoning、runaway loop、evaluator bias、
holdout leakage 与 evidence mismatch。硬门不可由平均分补偿，重复 trial 必须来自不同 episode
evidence，报告会重算 trial verdict、Wilson 区间、回归/fault 结果和 promotion 决策，伪造嵌套结果
或候选生效后缺少 rollback target 均被拒绝。

可观测层固定 OpenTelemetry core Semantic Conventions 1.43.0、GenAI 独立仓库提交
`d74a9bbc419c67dd78ea4fcc26280381ef0bb9db` 与 OTLP 1.11.0。它只在本地写原子、
内容寻址的 OTLP JSONL，默认只导出低基数 span、摘要、字段数和 `redacted=true`；prompt、
response、tool argument/result 与 grader explanation 不进入 OTLP。原文只有在显式 grant 未过期、
scope hash 匹配且目标是独立本地目录时才写入旁路产物。Event Journal、episode 和 provenance
仍是科研事实来源，OTel 只用于诊断。

首次 opt-in adoption smoke 只读采用两个既有真实、已完成的 Sprint 阴性结果，没有重跑模型、检索、
实验、论文或投稿。五维 regression、十类 fault、安全/成本/重复门全部通过，promotion 为
`promote`；统一评测、fault matrix、regression 与 OTLP 摘要 hash 分别为
`b5e21a0a93e1b3caa96f4a5f5bf7ec637a09bf97305d39e9d26164324ea6d1ee`、
`53f182bb856d702b5ee1bd90ec5384369ee43e6dc0910f2e15419cd972560f73`、
`c2a466d01aa703d5c62a8eb47131aec0dbcc95bd424033507f67b540f14ba33c` 和
`86236e468ad1a3dce58acbb02ae8054a857aee45b53f8d5becec43bb2c171e85`，且 raw payload
未持久化。外部昂贵 benchmark、依赖升级、legacy writer 删除、Gate B 和公开/投稿权限仍保持关闭；
这些属于后续显式任务和人工审批。

`262.10` 随后在冻结行为门下完成 LangGraph/LangChain 1.x 升级并关闭内部 R1 兼容边界。依赖精确
固定为 LangGraph 1.2.10、LangChain 1.3.14、Core 1.5.2 及其 checkpoint/SDK/prebuilt/LangSmith
传递版本；锁文件、安装环境和行为报告同时匹配才通过。0.2 基线与 1.x 目标分别产生
`92983004c099b14799cd4102b644072013016541ae3da659e7380161b448fb3e` 和
`dd62c3faef638b905755dbc26f6761957e5657175de7a3b641b6e5c718ebebd3`，七项 checkpoint、
interrupt、subgraph、parallel、幂等和序列化行为均保持。运行时只使用严格、无 pickle fallback 的
内存 checkpoint；仓库没有持久化 LangGraph checkpoint，因此没有静默重写旧 checkpoint，durable
domain truth 仍是 Event Journal。

审计主写路径从浅 JSONL 收敛到原子、连续、哈希链 Event Journal。已有 JSONL 只读导入且原文件不
改变；显式 rollback export 可以生成一个新的验证后 JSONL 快照，但不恢复持续双写。早期线性
`ResearchWorkflow` 标记为兼容期弃用。Competition、Campaign、Sprint 和 EvidenceGraph v1
writer/reader 则因科学执行器或活跃 reader 仍依赖而保留，避免把 Sprint lifecycle 证据错误外推为
所有科学写语义已迁移。schema 政策是 writer 只写 current、reader 读 current + one prior，命名窗口
为 `vnext-plus-one-release`，历史研究产物不做 bulk rewrite。

R1 用全新输出目录重跑两个正式 Sprint adoption vertical 和一次 vNext→legacy rollback，再由第二个
opt-in smoke 审计锁、重放两条 journal、运行升级后 characterization，并在独立 `python -I` 干净目录
中无网络复现 canonical evidence。最终 release report hash 为
`acf73733022a59e3aaca2fd3b0dfd66fe88ba3c140a23a4a4a9a816715f9a638`。该报告只表示内部兼容边界
通过；无限制执行、公开发布、外部投稿、安全策略自修改仍全部为 `false` 且必须显式人工批准。

## 27. 从系统闭环转向可发表性恢复（Task 263）

Task 259—261 的真实证据表明，AutoResearch 的运行、证据、复现和论文后端已经能够忠实产出；连续
阴性结果主要来自科学前端，而不是输出器。Task 260 的系统论文包通过了确定性论文、证据、引用和独立
复现检查，状态为 `ready_for_human_submission_review`；Task 259、Task 260 Route A 和 Task 261.2
则分别在未改变阈值和已揭示 panel 的情况下保留了真实阴性结果。因此“真实不可产出”的准确表述是：
系统不能稳定地产生通过独立科学贡献门的正向结果，而不是不能生成真实科研对象。

2024—2026 年 AI Scientist、Co-Scientist、Robin、Virtual Lab、Agent Laboratory、CodeScientist、
PaperBench、CORE-Bench、ScienceAgentBench、DiscoveryBench、BLADE、MLRC-Bench、MLE-bench、
execution-grounded research、FunSearch、FirstResearch、MARS 与自动神经算子发现工作的交叉检索
记录于
`autoresearch-vault/exploration/publishability-recovery-ai-scientist-2026.md`。证据共同支持：

1. 树搜索、锦标赛、archive、多样性和客观环境反馈优于单链自我反思；
2. workshop 接收、代码可运行、LLM 创新分数或 narrative review 都不能推出主会/主刊可发表；
3. 最强真实发现仍依赖专家设题、客观计算/湿实验反馈和人类责任边界；
4. 既有论文复现成功率仍低，故 novelty search 必须以强基线 clean-room reproduction 为前置门；
5. Open Science/provenance 能保真和复核，不能把未过阈值的效应改写为贡献。

Task 263 把科研主循环改为：

`Research Question Certificate → Opportunity Gate → Baseline Reproduction → Diverse Portfolio →`
`Multi-fidelity Search → Frozen Confirmatory Test → Clean-room Replay → Human Publication Review`

每个 Research Question Certificate 必须冻结 primitives、assumptions、mechanism、nearest-work
tension、一个主 claim、falsifier、failure update、minimal decisive test、primary metric、最小有
意义效应、强 baseline、null/control、ablation、独立单位、功效/敏感性、预算、开发/确认隔离和预注册
publication endpoint。Opportunity Gate 是不可补偿的合取门；缺 verified adjacent work、可复现
baseline、客观 evaluator、功效/区间方案、独立 panel、许可/数据/算力、至少三个机制族或 null arm 时，
只能写负机会记录或转向。

通过机会门后先复现强 baseline，再以 8—16 个候选、至少三个机制族构建受预算约束的 portfolio。
F0—F3 多保真层依次检查合法性、最小可执行性、多任务开发信号和全保真 development
replication/ablation；successive halving、MCTS 或 evolutionary operator 只能在冻结 survival rule
下分配预算。所有淘汰分支、失败、成本和低/高保真校准必须保留，不能只报告 winner，也不能让共享
memory 读取 sealed confirmatory evidence。

首篇新增研究优先检验搜索策略本身：在相同预算、工具和客观 evaluator 下，比较 one-shot、linear
self-loop、diversity-constrained portfolio 与 portfolio + cross-branch memory，并对 certificate、
diversity、multi-fidelity、reviewer 和 memory 做因果消融。主 endpoint 是独立任务级
confirmed scientific success，不是 LLM review score；secondary endpoints 包括复现、unsupported
claim、成本、低/高保真校准和人工干预。只有这一搜索器在独立确认中成立后，才进入自动神经算子发现
的外部复制与因果消融；Task 259 已揭示 Gate B 不因本计划重开。

人类继续负责选题价值、伦理/安全、许可、外部资源、作者责任、venue、新颖性解释和最终投稿。Task 263
不开放无限制执行、云资源、公开发布或自动投稿，也不允许用已揭示 Task 259—261 panel 重新调参或
制造新 holdout。

`263.2` 已于 2026-07-29 完成上述前端合同切片。新的
`ResearchQuestionCertificate` 把一个主 claim、文献截止日、primitives、assumptions、mechanism、
nearest-work tension、falsifier、failure update、minimal test、客观 metric/meaningful effect、强
baseline、null/control、ablation、prospective power、disjoint panel、budget 和结果盲
publication endpoint 组成内容寻址记录。`ResearchOpportunity` 再绑定 verified source、nearest-work
delta、objective evaluator、clean-room baseline plan/evidence 与 data/license/compute/source 状态。

机会门明确分为 `track_selection` 和 `novelty_search`：前者允许有 baseline smoke 与复现计划的方向
进入比较，后者必须额外拥有独立 clean-room、within-tolerance 的 baseline reproduction。任何 false
check 都成为 blocker；weighted score 和 LLM override 永远为 false。只有 novelty-search assessment
全通过，才能创建 8—16 branch、至少三个 mechanism family、至少一个 null/rule arm、F0—F3 有序
fidelity、非递增 survivor、exploration quota、总预算和最多一个 confirmatory claim 的
`PortfolioSpec`。nested/load-time 与 in-memory mutation 都由 canonical hash 阻断，sealed evidence、
结果后改 route、external submission/public release 继续 fail closed。该任务没有运行真实文献、模型或
科学实验；真实三 track opportunity tournament 属于 `263.3`。

`263.3` 已于 2026-07-29 完成真实机会赛。新
`opportunity_tournament.py` 将 Task 263.2 的机会合同绑定到有界 HTTP source/repository/data/license
probe、可执行 baseline smoke、prospective power/sensitivity、许可/数据/算力审计和不使用加权分数的
确定性排序。真实轮核验 11/11 个论文主来源、9/9 个资源端点，并重新读取和校验 Task 260 的 210-cell
系统基线；没有调用付费模型、下载确认数据、租用云 GPU 或授权外部动作。

三条 track 只有 `track.search-policy-causality` 通过 `track_selection`，因此它只获得进入 `263.4`
clean-room baseline reproduction 的资格。`track.neural-operator-replication` 的 MIT 代码和结果可达，
但官方完整 campaign 预计需 RTX 4080 级 GPU 约两天；本机 RTX 5060 Laptop 仅 8151 MiB，PyTorch/
显存预检失败，故由 `baseline_smoke_passed=false AND compute_feasible=false` 阻断。
`track.sequential-falsification` 的 POPPER 论文和 DiscoveryBench 数据可达，但 POPPER GitHub
元数据/仓库树没有可识别软件许可证，故代码未执行，并由
`baseline_smoke_passed=false AND license_clear=false` 阻断。两条方向保留为带证据的负机会记录，不被
“低成本”或“论文已发表”补偿过门。

三条 track 均冻结 12 个独立确认单位和前瞻敏感性表；在各自预设单位标准差下，最小有意义效应对应
normal-approximation power `0.822982`。该数值是结果前的设计敏感性，不是经验功效或贡献证据。
`263.4` 必须在不读取确认结果的条件下复现 search-policy 强基线、核对所选 ScienceAgentBench
任务的确定性 evaluator/许可证/数据可取得性并审查方差假设；若失败则把赛道转为 reproduction
diagnosis，不进入 novelty search。

`263.4.0` 于 2026-07-30 完成 endpoint-specific 前置诊断，并推翻了把上述通用正态近似用于当前
主终点的做法。冻结主终点是同一独立任务上 `portfolio+memory` 相对 `linear self-loop` 的配对二元
成功差，故应使用前瞻性 two-sided exact McNemar/sign-test 枚举，而不是假设连续单位标准差。对
SESOI `0.25`、alpha `0.05`、target power `0.80`，在不利 discordance 概率
`p01={0.00,0.05,0.10}` 下，现有 `n=12` 的精确功效分别仅为
`0.054402`、`0.080152`、`0.095619`，最小独立任务数分别为 `31`、`45`、`60`。因此后续面板采用
敏感性集合中最保守的 `n>=60`；不得用 observed power、seed 数或 trajectory 数补足样本量。

官方 ScienceAgentBench 2026-04-30 verified 元数据含 102 行，CSV SHA-256 为
`7f490f17f721a9c7e9415d3608a1a37d1a5315a26862cf556e3096ac4062face`。对 Task 263.3 冻结的
4 个 development 和 12 个 confirmatory ID 逐项审计后，confirmatory panel 中 9 个输出是图像、
3 个是 CSV/NPY 结构化产物；官方评测说明图像由 GPT-4o judge。公开 GitHub 树包含通用 harness，
但不含这 16 个 task-specific evaluator；Hugging Face 树只含元数据 CSV、README 和 verified
Parquet，不含 `benchmark_verified.zip`。README 指向的 SharePoint 包在匿名探测中没有返回可下载
工件。因此不能证明数据、评测器和客观确定性，baseline 未执行，状态依法转为
`blocked_reproduction_diagnosis`。这不是科学结果，也没有读取 gold program/result、启动 novelty
search、揭示确认结果或授权外部动作。

接下来的研究路径不是在这 12 个任务上降阈值，而是先执行 `263.4.1`：从完全匿名可下载、许可清楚、
task-specific evaluator 可固定、主终点不依赖模型 judge、算力可承受的任务中构建至少 60 个独立单位，
并跨至少两个 benchmark/task family 按 benchmark/domain 分层随机。ScienceAgentBench 的非图像
元数据候选、`autoresearch-sab-tasks`、ResearchGym、MLGym 等只能作为面板来源候选；任何单一来源
都不能仅凭任务/文件条目数被宣称满足独立单位和功效。只有完整面板通过 live 数据/评测器/许可/算力
审计，才允许 `263.4.2` clean-room 复现强 baseline 并冻结四臂、五消融、预算、随机化、停止规则和
sealed confirmatory panel。
