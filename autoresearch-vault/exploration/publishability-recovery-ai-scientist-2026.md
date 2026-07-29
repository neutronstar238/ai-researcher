---
title: AutoResearch 可发表性恢复：从单候选流水线到证据约束的科研组合搜索
date: 2026-07-29
status: accepted-plan
task: "263.1"
tags:
  - ai-scientist
  - publishability
  - portfolio-search
  - multi-fidelity
  - preregistration
  - open-science
---

# AutoResearch 可发表性恢复：从单候选流水线到证据约束的科研组合搜索

> [!summary]
> 当前 AutoResearch 不是“不能真实产出”：Task 260 已形成通过全部确定性论文、证据与独立复现检查的
> 系统论文包，等待人类新颖性、署名、许可和 venue 决策；Task 259、260 Route A 与 261.2 则形成了
> 真实、可复核的科学阴性结果。真正的瓶颈位于科研前端：候选过少、过早承诺、没有功效驱动的机会门、
> 没有预算匹配的组合搜索，也没有把探索阶段的分支证据转化为可归因的策略比较。近期 AI Scientist
> 研究支持树搜索、锦标赛、结构化记忆、客观环境反馈和独立验证，但同时显示 workshop 成功、代码可
> 执行或 LLM 自评都不能推出主会/主刊可发表。下一条主线应是
> **问题证书 → 机会审计 → 强基线复现 → 多样候选组合 → 多保真筛选 → 独立确认 → Open Science**。

## 1. 冻结问题、边界与检索方法

本轮在修改科研路径前冻结三个问题：

1. 为什么现有系统能完成真实执行、证据链、复现包和论文构建，却仍频繁得不到可投稿的科学贡献？
2. 2024—2026 年 AI Scientist、自动实验与科学 Agent 工作中，哪些机制有实证支持，哪些只是宣传、
   预印本或代理指标？
3. 在不回看已揭示 holdout、不降低 Gate A/B、不用 LLM 自评替代科学门禁的前提下，最短的可发表性
   恢复路径是什么？

检索日期为 2026-07-29，覆盖四个独立视角：

- 主流端到端系统与真实实验验证；
- 复现、数据分析、机器学习研究和开放发现 benchmark；
- 统计方法、证伪、独立确认与开放科学；
- 2026 年组合搜索、环境工程、结构化科研证书和神经算子自动发现前沿预印本。

来源优先级为同行评审论文、官方论文页/会议论文集、作者原始预印本和官方代码库。预印本均显式标注，
不把作者系统的自评当作独立复制，也不把 workshop 接收、运行成功或生成 PDF 当成主会/主刊证明。
本轮不执行外部投稿，不租用云 GPU，不修改已揭示科学 panel、阈值或 Gate B。

## 2. 本地事实：系统已经产出，科学贡献门才是失败点

| 研究链 | 实际产物 | 通过的门 | 未通过或仍需人工的门 |
|---|---|---|---|
| Task 259 Gate A 与 recovery | 两个完整、哈希绑定、可恢复的官方矩阵阴性结果 | 执行、复现、失败保留、冻结统计 | 两次均未通过 system-level 科学效果门；Gate B 必须保持关闭 |
| Task 260 Route A | 两个新机制、两轮 240-cell 开发与独立 unseen 评估 | 开发效应、完整执行、无人工科研决策 | 两个 unseen CI 均跨零，不能声称新方法贡献 |
| Task 260 Route B | 210-cell 系统研究矩阵与完整 paper dossier | 系统贡献、证据、复现、论文质量、40/40 live sources | 人类新颖性、作者、许可、venue 和投稿批准 |
| Task 261.1 | 一条模型选题到 PDF 的 bounded-autonomy Sprint | 运行、任务级统计、PDF、自治审计 | 任务级 CI 下界未过零；文献只有一条，不能投稿 |
| Task 261.2 | 模型生成并执行的新机制、独立确认与 51/51 claim audit | 代码安全、开发筛选、确认执行、论文/复现完整性 | coverage `0.5833 < 0.60`，科学提交门为 false |

这组事实排除了三个常见误诊：

1. 不是 PDF、引用格式或 Open Science 包缺失。Task 260 和 261.2 的后端已经能稳定构建。
2. 不是“负结果不真实”。这些阴性结果正是未改阈值、未重复抽样直到通过的证据。
3. 不是再增加一个 Reviewer Agent 就能解决。主要失败发生在客观 unseen 指标和置信区间，而不是文本
   评审措辞。

## 3. 外部证据交叉检索

### 3.1 端到端系统：最强结果仍依赖边界、筛选或实验人类

Nature 2026 的 AI Scientist 研究采用调查、超参数搜索、研究议程和消融组成的树式实验。作者向 ICLR
workshop 提交三篇人工筛选后的论文，按目标 workshop 的历史统计估计达到约 70% 接收概率，但只有一篇
通过首轮 workshop 审查，三篇都未达到 ICLR 主会标准。[S01] AI Scientist-v2 的关键增量是 progressive
agentic tree search、实验管理和视觉反馈，而不是“写得更像论文”。[S02]

Google 的 AI Co-Scientist 使用 generate、debate、evolve、rank、proximity 与 meta-review 组成异步
锦标赛，并展示了生物医学实验验证；科学家仍定义目标、提供约束并解释结果。[S03] Robin 和 Virtual Lab
也在受限生物医学问题上连接了人类实验验证：前者把多 Agent 文献与数据分析接到湿实验，后者由人类提供
高层反馈并验证纳米抗体设计。[S04][S05] 这些工作支持“机器扩大候选空间 + 客观实验压缩空间”，不支持
取消领域专家。

Agent Laboratory 从人类想法开始，显示人类反馈可提高报告质量并降低成本；ResearchAgent 使用学术图和
实体存储生成 problem/method/experiment；Kosmos 用结构化 world model、长时并行 rollout 和逐句
代码/文献引用提高可追溯性。[S06][S07][S08] 但 Kosmos 的独立科学家审计仍只判定 79.4% 语句准确，
说明 traceability 不是 correctness。CodeScientist 进一步把论文审查、代码语义审查和复现实验分开；
19 个候选中只有 6 个通过其最低可靠性与增量新颖性门，超过一半候选发现被代码审查否决。[S24]
Data-to-paper 则把稿件数值反向追到代码和数据；它在简单回顾性问题上较可靠，问题复杂后仍需要人类，
支持把论文视为执行证据的只读视图，而不是研究真相来源。[S25]

### 3.2 从想法到执行：纸面新颖性会在真实实施中消失

2026 年 Ideation–Execution Gap 研究让 43 位专家分别投入约 100 小时执行随机分配的人类或 LLM
研究想法。LLM 想法原有的纸面优势在执行后显著下降，novelty、excitement、effectiveness 和 overall
评价的降幅都更大。[S26] 这与本地 Task 260/261 的“开发看似强、独立确认失败”是同一种结构：
idea/reviewer score 不能代替可执行性、效应和确认。

Execution-Grounded Automated AI Research 把 Implementer、Scheduler、GPU workers 和 measured reward
闭合成实验环境，并用 archive-based evolutionary search 迭代；作者报告它优于直接从执行奖励做 RL，
后者会 mode collapse、提高均值却不提高上界。[S27] FunSearch 在有客观 evaluator 的数学与算法问题上
用 program archive 和 islands 保持多样性，确实产生了新构造，但最困难问题只有少数 run 成功。[S28]
这些证据支持“客观 evaluator + archive + 多样性 + 大量忠实失败”，而不是线性 self-critique。

### 3.3 Benchmark：可执行、可复现、新颖、有效和可发表是不同变量

| Benchmark | 主要结果 | 不能外推的结论 |
|---|---|---|
| PaperBench | 从零复现 20 篇 ICML 论文、8,316 rubric 项；主结果最佳约 21.0%，3-paper 子集 48 小时人类 best@3 为 41.4%、o1 为 26.6% [S09] | 不测新想法；自动 judge 也不是确定性专家 |
| CORE-Bench | 即使作者代码与数据可用，Hard 最佳约 21.48% [S10] | 只覆盖已确认可复现、短时、低资源 CodeOcean 项目 |
| ScienceAgentBench | 102 个论文代码任务；Claude self-debug 32.4%，专家知识 34.3% [S11] | 只测短 Python 任务，不测选题、文献、新颖性和论文 |
| DiscoveryBench | 264 个真实、903 个合成发现任务；最佳约 25% [S12] | 已给数据与目标，仍未解决 p-hacking 和大型多模态工作流 |
| BLADE | GPT-4o 可执行分析可达 96%，但正确统计模型 coverage@10 低于 13% [S13] | “代码能跑”不等于科学分析成立 |
| MLRC-Bench | 7 个前沿 ML 竞赛；最佳只弥合顶尖人类差距的 9.3%；LLM 创新评分与实测效果 Spearman `-0.06` [S14] | LLM 自评不能成为 novelty/effect 门 |
| MLE-bench | 75 个 Kaggle 任务；o1-preview+AIDE medal rate 16.9%，pass@8 34.1% [S15] | problem/data/metric 已给定，不是完整 R&D |
| RE-Bench | Agent 在 2 小时预算可领先人类，但 8/32 小时后人类反超 [S16] | 短时速度不能外推为长时科研控制能力 |
| AIRS-Bench v3 | 20 个无 baseline-code 的 ML 任务中，仅 4 个任务某些运行超过人类 SOTA [S17] | 仍给定 problem/data/metric，且存在 context overflow 与累计调试漂移 |

这些独立结果共同否定一个简单乘法：更多 token、更多 Agent 或更长 loop 并不自动变成更强科学贡献。
发表级结果是合取门：

`Novelty ∧ EmpiricalValidity ∧ Reproducibility ∧ EvidenceCoverage ∧ Robustness ∧ IndependentReview`

任一项为 false，其他项的高分不能补偿。

### 3.4 2026 前沿：可借鉴的是搜索和环境机制，不是未经复制的榜单数字

- MARS 把 Agent 视为成本约束的 MCTS 搜索策略，使用 Design–Decompose–Implement 和跨分支反思记忆；
  这支持预算感知、跨分支学习；当前 arXiv v3 注明已发表于 ICML 2026，但跨分支因果结论仍需独立
  复制。[S18]
- Arbor 使用显式 hypothesis tree、共享记忆和失败信号协调 planner、specialist 与 critic；这支持
  分支可见性，但性能结论仍需独立复制。[S19]
- AI Research Agents for MLE-bench 将 Agent 明确形式化为搜索策略，并比较 greedy、MCTS 和 evolutionary
  operator，说明搜索算子与执行 operator 的交互会改变结果。[S20]
- FirstResearch 提出 Research Question Certificate：primitives、assumptions、mechanism、tension、
  falsifiable hypothesis、minimal decisive test 和 failure update。它非常适合作为前端合同，但实验只含
  少量 Agent 主题、LLM judge 和 prompt-level baseline，不能直接当作科学有效性证明。[S21]
- EurekAgent 强调环境工程：权限、artifact、预算、客观反馈和人机边界；当前为 2026 预印本。[S22]
- 自动神经算子发现社区用 16 个实验室、20 次迭代、三种角色、低保真筛选和全保真 winner 复核，在五个
  问题和三种 seed 上运行 9,623 次模型调用。[S23] 它与本仓库 PDE 路线直接相邻，但仍有单模型、prompt
  偏向、有限 ablation、未全量全保真验证等局限，因此更适合作为“独立复制 + 因果角色消融 + 多保真
  校准”的新研究对象，而不是直接照搬其性能结论。

## 4. 根因分析：后端很强，前端搜索统计学不足

### 4.1 问题选择没有显式的“可判决性”门

现有候选生成主要从文献关键词、局限和数据集做聚类；Competition 再按静态 40/30/30 分数排序并选择
第一个通过 smoke 的候选。它没有在执行前回答：

- 最接近的强基线是否已经可以独立复现？
- 主 claim 的最小有意义效应是多少？
- 可获得的独立单位数能否给出足够功效或有信息量的区间？
- 是否存在真正不重叠的开发集和确认集？
- 预算是否足以探索多个机制族，而不是只跑一个幸运候选？
- 如果结果为阴性，它是否仍能产生有新颖诊断价值的研究贡献？

### 4.2 候选宽度太窄，且从开发成功过早跳到确认

- Task 259 在一次 Gate A 内冻结两个相近机制，recovery 再冻结两个机制；都没有组合层的 diversity、
  branch survival 或低/高保真相关性校准。
- Task 260 Route A 每轮只有一个机制，两个机制都在 development 有大幅正向效果，却在 unseen
  system-level CI 中崩溃。
- Task 261.2 只允许一个模型生成机制。停止而不“抽到通过为止”是正确治理，但这也证明单候选路径的
  科学命中率过低。

### 4.3 独立单位数由方便性决定，而不是由功效和异质性决定

Task 259/260 的系统级 CI 很宽，Task 261.2 只有六个确认任务。种子是任务内重复，不能冒充更多独立
科学单位。当前路径缺少 prospective power/sensitivity analysis，也没有在选题时把数据可获得性和
heterogeneity 纳入 hard gate。

### 4.4 “生成—评审—执行”没有形成可比较的搜索策略实验

当前日志能追踪一次候选为何失败，但还不能回答：

- 多样候选组合是否优于单路径 self-loop？
- 低保真排序与全保真终局是否校准？
- 跨分支记忆是否真的提高成功率，还是只增加 token 和相关错误？
- planner、reviewer、failure memory 和 Research Question Certificate 各自贡献多少？

这使 Harness/Loop 已经可审计，却尚未成为一项可证伪的科研贡献。

### 4.5 写作与 Open Science 只能保真，不能创造效应

论文、claim audit、RO-Crate、PROV 和独立 reproduction 会阻止夸大或篡改，但不能把
`0.5833 < 0.60` 写成通过。它们应继续作为末端硬门，研究资源应从反复润色转向前端机会选择、候选组合、
功效、客观反馈和确认性实验。

## 5. 应借鉴与不应借鉴

| 借鉴机制 | 本项目中的落点 | 不应借鉴的错误外推 |
|---|---|---|
| Research Question Certificate | 在任何代码/模型生成前冻结 mechanism、falsifier、minimal test、failure update | 证书完整不等于假设正确 |
| 异步锦标赛与 proximity 去重 | 候选族多样性、相似候选合并、保留反对证据 | Elo/LLM 排名不作为科学真值 |
| Progressive tree / MCTS / successive halving | 预算匹配的多分支、多保真筛选 | 不允许无限扩树或确认集回流 |
| Objective environment outcome | 指标、基线、统计和门全部由确定性程序计算 | Reviewer 文本或自评不能替代效果 |
| Structured world model / branch memory | 每个分支记录假设、delta、证据、失败、可迁移 lesson | 共享记忆不得包含 sealed holdout |
| Wet-lab/independent validation boundary | 对本项目对应为独立确认 panel 和 clean-room reproduction | 不把开发集、seed 重复当独立验证 |
| Open Science research object | 对所有分支、失败和最终端点生成可验证 package | 元数据互操作不等于科学复现或录用 |

## 6. 新研究路径：Certificate → Replication → Portfolio → Confirmatory

```mermaid
flowchart LR
    A["Time-cut literature map"] --> B["Research Question Certificate"]
    B --> C{"Opportunity hard gate"}
    C -->|fail| N["Negative opportunity record / pivot"]
    C -->|pass| R["Clean-room reproduction of strongest baseline"]
    R -->|fail| N
    R -->|pass| D["Diverse mechanism portfolio"]
    D --> E["Low-fidelity executable screen"]
    E --> F["Budget-aware successive halving / tree search"]
    F --> G["Full-fidelity development replication + ablations"]
    G --> H["Freeze one claim, code, power, panel, and stop rules"]
    H --> I["Independent confirmatory runner"]
    I --> J{"Conjunctive publication gate"}
    J -->|fail| K["Credible negative / new certificate"]
    J -->|pass| L["Clean-room reproduction + claim audit"]
    L --> M["Human novelty / authorship / venue / submission review"]
```

### 6.1 Research Question Certificate

每个候选问题必须在写实现前声明：

- primitives、assumptions、mechanism model 和与最近工作的 tension；
- 一个主 claim、明确的 falsifier 和失败后知识更新；
- 最小判决实验、primary metric、最小有意义效应和强基线；
- 数据、独立单位、功效/敏感性、开发/确认隔离和成本上限；
- 负对照、随机/规则 baseline、必需 ablation；
- 正向方法贡献、系统贡献或有诊断价值的阴性论文三种预注册 endpoint 之一。

### 6.2 机会硬门

只有同时满足以下条件才进入组合搜索：

1. 至少三条已验证的相邻工作，且有 nearest-work 差异矩阵；
2. 强基线可执行、许可清晰、数据可得，并有进入 novelty search 前的 clean-room 复现计划；
3. 客观 primary metric 与不可事后修改的 threshold；
4. 足够的独立单位或明示的区间精度/功效方案；
5. 开发集和确认集不重叠，确认集访问可审计；
6. 预算足以支持至少三个不同机制族和一条 null/rule-based arm；
7. publication endpoint 在结果前冻结；
8. 外部提交和公开发布仍为 false。

### 6.3 Replication-first

机会门通过后，系统先在干净环境复现最接近的强基线。复现包必须绑定论文 claim、代码、数据、环境、
命令、seed、原始预测和 endpoint，并由执行 evaluator 而非叙事 Reviewer 判断。若复现失败，研究任务
转为 reproduction diagnosis，不能在不可靠 baseline 上继续声称新颖提升。对一个新领域，至少完成一条
强 baseline 的 exact/within-tolerance reproduction；在后续扩展阶段再提高到三条。

### 6.4 多样候选组合与多保真搜索

首轮组合建议为 8—16 个候选，至少覆盖三个机制族；它不是 8—16 次独立“抽奖”，而是一棵受预算和
因果审计约束的搜索树：

1. **F0 合法/静态门**：来源、许可、代码安全、可证伪性、资源和数据分割。
2. **F1 最小可执行门**：单小任务、单 seed、低资源；只淘汰不可运行和明显无信号分支。
3. **F2 多任务开发门**：至少三独立开发单位、多个 seed、失败感知指标。
4. **F3 全保真开发门**：完整 baseline、ablation、uncertainty、成本和精确复现。
5. **Freeze**：只允许在事先规定的 survival rule 下选择 0 或 1 个主 claim 进入确认。

每级都保存被淘汰分支，校准低保真排名与后续真实结果。后续论文必须报告完整分支流，而不是只展示
winner。多次探索带来的选择偏差应通过预注册 survival rule、独立确认和必要的多重比较控制处理。

### 6.5 独立确认与 clean-room reproduction

- 确认 runner 不能读取探索 trajectory，只接收冻结代码、方法文档、环境和确认 panel。
- 独立单位数来自任务/系统/数据集，不用 seed 冒充。
- 所有 primary、secondary、negative-control 和 ablation 结果都保留。
- 只有预注册主 claim 可以触发正向 publication endpoint。
- clean-room runner 只根据方法包重建关键 endpoint；不一致时阻断主 claim。

### 6.6 人类角色

人类负责目标、伦理/安全、许可、资源批准、新颖性解释、作者责任、venue 与最终投稿；不得在运行后
偷偷改主 claim、阈值、panel 或科研结果。所有人工干预进入 Event Journal 和 provenance。

## 7. 推荐的可发表研究主线

### 7.1 第一优先：科研搜索策略的因果研究

主问题建议冻结为：

> 在相同预算、相同工具和相同客观 evaluator 下，Research Question Certificate +
> diversity-constrained portfolio + multi-fidelity successive halving，是否比 one-shot 和线性
> self-loop 更高概率产生可独立确认、证据完整的研究结果？

这是对现有 Task 260 系统论文的实质升级，而不是换标题。研究设计至少包含：

- budget-matched `one-shot`、`linear self-loop`、`portfolio`、`portfolio + cross-branch memory`；
- certificate、diversity、multi-fidelity、reviewer、memory 的因果 ablation；
- 多个独立研究任务和全量 failure slice；
- primary endpoint 为任务级 confirmed scientific success，而不是 LLM 分数；
- secondary endpoints 为 reproduction、unsupported claim、成本、低/高保真校准和人工干预；
- prospective power/sensitivity analysis、时间截断文献审计和完全冻结的确认 panel。

这条线复用 vNext Graph/Harness/Loop/PROV/Open Science 基础，计算成本可控，且直接填补当前最清晰的
科学空白。

### 7.2 第二优先：自动神经算子发现的独立复制与因果消融

在第一条主线证明搜索器本身有效后，再对 2026 自动神经算子社区研究做独立复制：

- 复现公开问题和强 baseline；
- 校准低保真筛选对全保真终局的排序偏差；
- factorial 区分 planner、reviewer、shared memory 和 portfolio diversity；
- 加入 rule-based/random/null arms 和未见 PDE families；
- 只在新的 Gate A 通过后讨论 RealPDEBench；绝不重开 Task 259 已揭示 Gate B。

这条线科学价值高，但需要独立 GPU 环境、更多计算和更严格的外部代码/许可审计，不能先于搜索器验证。

### 7.3 立即可交付但不自动投稿：Task 260 系统论文

Task 260 paper dossier 已经达到 `ready_for_human_submission_review`。它不应被误称为“没有产出”，也
不应由系统自行投稿。最短动作是人工做新颖性/venue/作者/许可审查；若审查认为贡献不足，则把本轮
portfolio 因果实验作为新证据，而不是继续润色旧 PDF。

## 8. 实施顺序与不可越过的门

| 任务 | 内容 | 完成判据 |
|---|---|---|
| 263.1 | 本报告、根因审计、来源登记和新任务树 | primary/official URL 实时核验；本地证据与任务图一致 |
| 263.2 | Research Question Certificate、Opportunity 与 Portfolio 合同 | schema、hash、hard gate、tamper、leakage、diversity、budget 测试 |
| 263.3 | 至少三条研究 track 的真实 opportunity tournament | 每条有 nearest-work、baseline smoke、power/cost、独立 panel 方案 |
| 263.4 | 复制强 baseline 并冻结搜索策略因果实验 | clean-room baseline 通过，task suite、预算和 confirmatory panel 未揭示 |
| 263.5 | 运行 budget-matched 多分支开发搜索 | 所有分支/失败/成本保留，低/高保真校准和 ablation 完整 |
| 263.6 | 独立确认与统计裁决 | 无 panel leakage、无事后改门、任务级 CI/功效与 exact reproduction |
| 263.7 | paper/Open Science package 与人工审查 | 合取门全通过或忠实阴性；外部投稿仍需显式人工批准 |

Task 263 不改变 Task 259 的 Gate B 状态，也不把 Task 260/261 已揭示数据重新变成 holdout。

## 9. 反方审查

1. **组合搜索可能只是更昂贵的多次尝试。** 因此必须预算匹配、预注册 survival rule、保留全部分支，
   并以独立确认而非 best development score 评判。
2. **多保真可能淘汰慢热方法。** 必须实测 F1/F2 与 F3 排名相关性，并保留 exploration quota。
3. **跨分支记忆可能传播错误。** lesson 必须绑定原始 branch evidence，sealed holdout 永不进入共享记忆；
   memory 还必须有无记忆 ablation。
4. **更多独立任务可能稀释领域深度。** 任务套件用于研究搜索策略；任何领域方法论文仍需领域特定强
   baseline、理论或机制解释和专门确认。
5. **自动 benchmark 仍可能被污染或游戏化。** 使用时间截断来源、隐藏 evaluator、clean-room runner、
   fault cases 和人工审查；公开 benchmark 分数不能单独解锁投稿。
6. **阴性结果仍可能不可发表。** 只有预先定义、具有新颖诊断价值、充分功效并完整报告的阴性 endpoint
   才能成为论文贡献；普通失败进入 Vault 和后续组合学习，不强行写成论文。

## 10. 结论

- **RQ1：为什么达不到可发表级？** 后端已经能真实执行、审计、复现和构建论文；前端候选宽度、问题可
  判决性、独立单位、功效和探索到确认的统计控制不足，导致开发效果在 unseen 中崩溃。
- **RQ2：近期 AI Scientist 工作真正证明了什么？** 树搜索、锦标赛、结构化记忆、客观环境反馈和人机
  实验边界能改善流程；尚无可靠证据证明完全自主系统能稳定完成自主选题到主会/主刊发表。
- **RQ3：最短恢复路径是什么？** 先把问题和机会变成内容寻址硬合同，再做预算匹配的多样组合和多保真
  搜索，最后用未揭示 panel、clean-room reproduction 和人类终审裁决。第一篇新研究优先检验这套搜索
  策略本身，而不是再次押注一个 PDE 单候选。

## 11. 来源登记

### 端到端 AI Scientist 与真实实验

- [S01] Yamada et al., “Towards end-to-end automation of AI research,” *Nature*, 2026.
  [Nature article](https://www.nature.com/articles/s41586-026-10265-5)
- [S02] Lu et al., “The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic
  Tree Search,” arXiv:2504.08066, 2025. [arXiv](https://arxiv.org/abs/2504.08066)
- [S03] Gottweis et al., “Towards an AI co-scientist,” *Nature*, 2026.
  [Nature article](https://www.nature.com/articles/s41586-026-10644-y)
- [S04] Ghafarollahi and Buehler, “Robin: a multi-agent system for automating scientific discovery,”
  *Nature*, 2026. [Nature article](https://www.nature.com/articles/s41586-026-10652-y)
- [S05] Swanson et al., “The Virtual Lab: AI agents design new SARS-CoV-2 nanobodies with experimental
  validation,” *Nature*, 2025.
  [Nature article](https://www.nature.com/articles/s41586-025-09442-9)
- [S06] Schmidgall et al., “Agent Laboratory: Using LLM Agents as Research Assistants,” Findings of
  EMNLP 2025. [ACL Anthology](https://aclanthology.org/2025.findings-emnlp.320/)
- [S07] Baek et al., “ResearchAgent: Iterative Research Idea Generation over Scientific Literature with
  Large Language Models,” NAACL 2025. [arXiv](https://arxiv.org/abs/2404.07738)
- [S08] Edison Scientific, “Kosmos: An AI Scientist for Autonomous Discovery,” arXiv:2511.02824, 2025.
  [arXiv](https://arxiv.org/abs/2511.02824)

### 复现、科学分析与研究 benchmark

- [S09] Starace et al., “PaperBench: Evaluating AI’s Ability to Replicate AI Research,” ICML 2025.
  [PMLR](https://proceedings.mlr.press/v267/starace25a.html)
- [S10] Siegel et al., “CORE-Bench: Fostering the Credibility of Published Research Through a
  Computational Reproducibility Agent Benchmark,” arXiv:2409.11363, 2024.
  [arXiv](https://arxiv.org/abs/2409.11363)
- [S11] Chen et al., “ScienceAgentBench: Toward Rigorous Assessment of Language Agents for Data-Driven
  Scientific Discovery,” ICLR 2025. [arXiv](https://arxiv.org/abs/2410.05080)
- [S12] Majumder et al., “DiscoveryBench: Towards Data-Driven Discovery with Large Language Models,”
  ICLR 2025. [arXiv](https://arxiv.org/abs/2407.01725)
- [S13] Gu et al., “BLADE: Benchmarking Language Model Agents for Data-Driven Science,” EMNLP 2024.
  [arXiv](https://arxiv.org/abs/2408.09667)
- [S14] Zhang et al., “MLRC-Bench: Can Language Agents Solve Machine Learning Research Challenges?”
  NeurIPS 2025. [arXiv](https://arxiv.org/abs/2504.09702)
- [S15] Shern et al., “MLE-bench: Evaluating Machine Learning Agents on Machine Learning Engineering,”
  ICLR 2025. [arXiv](https://arxiv.org/abs/2410.07095)
- [S16] Wijk et al., “RE-Bench: Evaluating Frontier AI R&D Capabilities of Language Model Agents against
  Human Experts,” arXiv:2411.15114, 2024. [arXiv](https://arxiv.org/abs/2411.15114)
- [S17] Lupidi et al., “AIRS-Bench: a Suite of Tasks for Frontier AI Research Science Agents,”
  arXiv:2602.06855v3, 2026. [arXiv](https://arxiv.org/abs/2602.06855)
- Huang et al., “MLAgentBench: Evaluating Language Agents on Machine Learning Experimentation,”
  ICML 2024. [PMLR](https://proceedings.mlr.press/v235/huang24y.html)
- Si et al., “Can LLMs Generate Novel Research Ideas? A Large-Scale Human Study with 100+ NLP
  Researchers,” arXiv:2409.04109, 2024. [arXiv](https://arxiv.org/abs/2409.04109)
- Liu et al., “ResearchBench: Benchmarking LLMs in Scientific Research Idea Generation,” Findings of
  ACL 2026. [ACL paper](https://aclanthology.org/2026.findings-acl.644.pdf)

### 搜索、方法证书与 2026 前沿

- [S18] Chen et al., “MARS: Modular Agent with Reflective Search for Automated AI Research,”
  arXiv:2602.02660, 2026. [arXiv](https://arxiv.org/abs/2602.02660)
- [S19] “Arbor: A Tree-Structured Multi-Agent Framework for Scientific Discovery,”
  arXiv:2606.12563, 2026. [arXiv](https://arxiv.org/abs/2606.12563)
- [S20] “AI Research Agents for Machine Learning: Search, Exploration, and Generalization in
  MLE-bench,” arXiv:2507.02554, 2025. [arXiv](https://arxiv.org/abs/2507.02554)
- [S21] Wang, “FirstResearch: Auditable Question Formation for LLM Scientific Discovery Agents,”
  arXiv:2607.05682, 2026. [arXiv](https://arxiv.org/abs/2607.05682)
- [S22] “EurekAgent: Environment Engineering for Autonomous Scientific Discovery,”
  arXiv:2606.13662, 2026. [arXiv](https://arxiv.org/abs/2606.13662)
- [S23] “An Agentic AI Scientific Community for Automated Neural Operator Discovery,”
  arXiv:2607.12122, 2026. [arXiv](https://arxiv.org/abs/2607.12122)
- [S24] Jansen et al., “CodeScientist: End-to-End Semi-Automated Scientific Discovery with Code-based
  Experimentation,” Findings of ACL 2025.
  [ACL Anthology](https://aclanthology.org/2025.findings-acl.692/)
- [S25] Ifargan et al., “Data-to-paper: AI-driven research from data to human-verifiable research
  papers,” *NEJM AI*, 2024. [arXiv](https://arxiv.org/abs/2404.17605)
- [S26] Si et al., “The Ideation-Execution Gap: Execution Outcomes of LLM-Generated versus Human
  Research Ideas,” ICLR 2026 poster. [arXiv](https://arxiv.org/abs/2506.20803)
- [S27] Si et al., “Towards Execution-Grounded Automated AI Research,” arXiv:2601.14525, 2026.
  [arXiv](https://arxiv.org/abs/2601.14525)
- [S28] Romera-Paredes et al., “Mathematical discoveries from program search with large language
  models,” *Nature*, 2024. [Nature article](https://www.nature.com/articles/s41586-023-06924-6)
- Huang et al., “Automated Hypothesis Validation with Agentic Sequential Falsifications,” ICML 2025.
  [PMLR](https://proceedings.mlr.press/v267/huang25n.html)
- Buehler, “SciAgents: Automating Scientific Discovery through Multi-Agent Intelligent Graph
  Reasoning,” arXiv:2409.05556, 2024. [arXiv](https://arxiv.org/abs/2409.05556)

### 批评与边界

- Messeri et al., “Risks of AI scientists,” *Nature Communications*, 2025.
  [Nature article](https://www.nature.com/articles/s41467-025-63913-1)
- *Nature* editorial, “Why AI cannot do good science without humans,” 2026.
  [Nature editorial](https://www.nature.com/articles/d41586-026-01551-3)
- Hao et al., “AI tools expand scientists’ impact but contract science’s focus,” *Nature*, 2025.
  [Nature article](https://www.nature.com/articles/s41586-025-09922-y)

## 12. 关联

- 项目：[[projects/ai_researcher_system/index|AI-Researcher System Project]]
- 前序架构计划：[[exploration/graph-harness-loop-open-science-2026|Graph/Harness/Loop/Open Science]]
- 研究计划：`AutoResearch_System_Research_Plan.md`
- 执行计划：`AutoResearch_System_Execution_Plan.md`
- 任务：`.kiro/specs/auto-research-system/tasks.md` 中的 `263.*`
- 问题：`Problem.md` 中的 `P-20260729-048`
