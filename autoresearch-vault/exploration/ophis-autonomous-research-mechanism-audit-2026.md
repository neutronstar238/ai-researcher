---
title: OPHIS 与全自动科研：从试错、机制观测到可发表因果证据
date: 2026-08-01
status: evidence-audit-with-autonomous-development-negative
task: "265.2/265.3"
tags:
  - ophis
  - mechanistic-autoresearch
  - autonomous-research
  - causal-intervention
  - adaptive-data-analysis
  - open-science
  - evidence-first
links:
  - task-261-2-generated-mechanism-evidence-survey-2026
  - graph-harness-loop-open-science-2026
  - task-265-1-autonomous-competition-plan
---

# OPHIS 与全自动科研：从试错、机制观测到可发表因果证据

> [!summary]
> OPHIS 最有价值的贡献是把 `Observation → Problem → Hypothesis → Intervention → Speed-up`
> 写成显式研究闭环；它提醒我们，扩大候选搜索并不等于理解机制。但截至 2026-08-01，公开证据主要是
> 团队博客和两个复现实验仓库，完整 observable/intervention 空间尚未公开，Grokking 比较存在预算与
> 分母不等、阈值未完全操作化等限制，NanoGPT 的最佳候选还面临 376 次筛选后的赢家偏差。博客一面称
> “不涉及 LLM”，一面又说明 NanoGPT 系统围绕 coding agent 构建，因此最稳妥的工程结论是采用
> **LLM 执行器 + 确定性机制观测器 + 因果 Harness + 一次性确认集**的混合架构，而不是接受
> “纯非 LLM”或“LLM 自己会研究”中的任何一个口号。本综述只升级研究协议，不产生显著性或投稿结论。

## 1. 冻结研究问题

本次交叉检索在查看 Task 265.3 的任何官方开发结果之前冻结三个问题：

1. **RQ1：**现有自动科研系统究竟自主完成了哪些环节，又使用了什么客观验证？
2. **RQ2：**OPHIS 相对 LLM/coding-agent 试错的机制性主张有多强，哪些部分已公开可复现？
3. **RQ3：**AutoResearch 应采用什么架构和实验设计，才能把自主探索升级为可发表的因果证据？

“可发表”在这里至少要求：问题有新颖性、数据与分析单位有效、比较预算公平、失败完整保留、效应有
不确定性、开发选择与一次性确认隔离、声明逐项绑定证据、第三方能够重建。只生成代码、跑通任务、写出
论文或得到一个漂亮均值都不满足该定义。

## 2. 检索与审计方法

检索日期为 2026-08-01。来源按五个互相制约的分支纳入：

1. LLM 端到端科研系统与搜索策略；
2. OPHIS、机制可解释性和非 LLM/相邻路线；
3. 科研 Agent、计算复现和开放式研究 benchmark；
4. 自适应数据分析、模型选择偏差与多次比较；
5. provenance、Research Object 与可重建工作流标准。

只使用作者项目页、正式预印本/论文页、官方代码仓库或规范站点。博客只支持“团队公开声称了什么”，
不能替代同行评审论文。对每个系统同时寻找支持证据与反证：自主范围、客观 endpoint、独立重复、公开
材料、选择过程和仍依赖的人类环节。数字只在原始页面明确给出时记录，不把不同 benchmark 的分数直接
横向排名。

## 3. 自动科研不是一个等级，而是五条可分离的能力轴

| 系统/证据 | 自主范围 | 主要评价信号 | 支持的结论 | 不能推出的结论 |
|---|---|---|---|---|
| AI Scientist-v2 [S06] | 受限 ML 选题、实验树、写稿 | workshop 审稿与实验结果 | 端到端闭环可以形成完整投稿物 | 一次过审不能证明一般可靠性或结果显著 |
| MLRC-Bench [S07] | 复现/改进 ML 研究挑战 | 隐藏客观指标 | 可测量 Agent 缩小目标差距的程度 | LLM 新颖性评分与客观改进并不等价 |
| Execution-Grounded [S08] | 大量可执行研究尝试 | 实际运行结果 | 搜索策略必须由执行反馈约束 | 更多运行不自动产生机制或有效推断 |
| MARS [S09] | 模块组合、MCTS、跨分支记忆 | 预算内执行回报 | 比较记忆与模块化搜索能提高样本效率 | 历史相关性不能替代因果解释 |
| AI Research Agents [S10] | 搜索 policy/operator/evaluator 联合优化 | MLE-Bench 等任务结果 | scaffold 与搜索耦合会改变能力 | leaderboard 提升不等于科学发现成立 |
| CodeScientist [S11] | 代码驱动的大规模实验与发现候选 | 评审、代码检查、重复 | 数百实验可收敛到少量可审计发现 | 19 个候选中仅少数最低限度可靠，产量不是质量 |
| Agent Laboratory / AI co-scientist [S12][S13] | 文献、实验、报告或假设辩论 | 人类反馈、部分实验验证 | 人机协作能完成多阶段科学工作 | 人类给定目标、反馈或湿实验时不能称零人类自治 |
| Kosmos [S14] | 长程文献—数据循环与结构化 world model | 语句审计、合作者复核 | 持久世界模型有助于长链条溯源 | 语句准确率小于 100%，不能把全部发现当真值 |
| OPHIS [S01–S03] | 内部动态观测到训练干预 | 提前到达阈值、validation BPB | 机制观测可生成有针对性的干预 | 公开材料尚不足以证明通用、纯非 LLM 或无偏发现 |

这些工作共同否定两个常见捷径：第一，论文文字流畅不等于研究完成；第二，Agent 执行成功率不等于
科学结论有效。系统能力至少应分为选题、证据检索、可执行干预、结果裁决和论文证据对齐五条轴，任何
总分都不能补偿关键轴为零。

## 4. OPHIS 的实质贡献

### 4.1 值得采用的部分

OPHIS 把研究对象从“下一个技巧”改为“内部状态发生了什么、为什么、什么干预由此推出”。团队列出的
观测包括参数/激活的范数、熵类量、方差和其他训练统计；Grokking 示例把权重范数动态连接到过拟合—
泛化转变，再导出权重衰减或范数约束。[S01] 这种结构比只保存 `(配置, 分数)` 更适合作为可复用知识：

- Observation 必须是时间对齐、可重算的 telemetry，而不是事后故事；
- Problem 必须指出偏离、转折、分叉或瓶颈，并记录检测规则；
- Hypothesis 必须给出方向性预测和可证伪条件；
- Intervention 必须只改变被假设指向的因素，并有匹配对照；
- Speed-up 必须是带不确定性的预注册 endpoint，而不是“曲线看起来更快”。

这正是 AutoResearch 过去缺失的中层：Graph 保存了来源和结果，Harness 能执行代码，Loop 会继续试验，
但没有强制每次试验从观测推导问题、再从问题推导可区别的干预。

### 4.2 公开结果能支持到哪里

Grokking 博客报告 OPHIS 测试 350 个干预，其中 255 个被判为实质改进、48 个失败；LLM full baseline
只执行了 76 个，44 个实质改进、32 个失败；LLM 的 OPHIS-like 子空间执行 30 个，21 个实质改进、
9 个失败。[S01] 这些数值支持“该实现值得进一步复验”，但比较预算、可执行过滤和分母不相等，
“clearly earlier”的实质改进阈值也未在公开页面完全操作化，因此不能据此估计无偏胜率。

NanoGPT 博客报告固定 2,000 步、单 H200、候选各重复 10 次；从约 6,000 个内部观测中只暴露 13%，
发现 376 个超过 baseline 三个标准差的候选，最佳均值从 `0.9340967` 降到 `0.9318420`。[S01]
公开最佳仓库确认差值 `0.0022547`、seed 42、轨迹正则化对象、系数、lead 和 cutoff，并明确
“mean ± 2 sample SD”只是运行离散度、不是置信区间。[S02] 这提高了结果可重建性，但最佳项是从
大量候选中选择出来的；若没有把完整选择过程纳入推断，`7.43× baseline SD` 不是选择校正后的显著性。

### 4.3 必须保留的反方证据

1. 博客摘要和方法段称 OPHIS 不涉及 LLM，但 NanoGPT 案例又称围绕 coding agent 建立自动迭代系统，
   agent 查看 dashboard、提出机制假设并实现干预。[S01] 因而“框架本体可非 LLM”与“公开复杂案例
   使用 coding agent”应同时记录，不能把后者抹掉。
2. 完整 observables 和 intervention strategies 因 proprietary 原因未公开。[S01] 公开代码可复现最佳
   结果，不等于可复现产生该结果的完整发现算法。
3. 团队承认某些高表现提案不稳定，下一步应把方差纳入 reward。[S01] 这说明当前目标仍偏向均值搜索。
4. “forking”是很好的异常发现线索：训练/验证损失快速分离、约 900 条曲线筛查、定位模块并做组件
   消融。[S01] 但公开材料不足以审计搜索自由度、替代解释和全部消融，因此现阶段应称
   `hypothesis-generating phenomenon`，待前瞻性复验后再升级为机制发现。

## 5. 为什么真实系统仍难产出可发表结论

### 5.1 开放式科研能力仍低

PaperBench、CORE-Bench、REPRO-Bench 与 ReplicatorBench 都表明，从论文恢复环境、代码、数据和结果
仍是主要瓶颈；当前最强 Agent 在困难任务上的完成率远未接近可靠自动化。[S17–S20] SciAgentArena
进一步区分了“明确分析任务”和“需要新颖性、自主定义问题的开放任务”，后者明显更难。[S15]
AutoResearchBench 的 deep/wide literature discovery 最佳重合度约 9%，说明搜到一些相关论文与形成
完整证据图之间仍有数量级差距。[S16]

### 5.2 评价器会奖励错误代理目标

MLRC-Bench 发现语言模型对 innovation 的判断与客观任务改进并不对齐。[S07] 只让 LLM 给想法或论文
打分，会把文风、熟悉度和可叙述性混入科学价值。AutoResearch 因而只允许 LLM 生成候选、诊断和
代码；是否运行成功、是否优于基线、置信区间是否越过门槛必须由确定性 evaluator 决定。

### 5.3 自适应搜索会制造“赢家”

反复查看同一开发集并挑最佳候选，会产生模型选择过拟合；交叉验证本身也会因超参数选择而乐观。
[S22–S24] 报告多次随机种子的均值和标准差仍不够，因为随机性、任务差异和候选选择是不同层级的
不确定性。[S25] 正确做法是把探索限定在 development，完整保留所有候选，再只让一个冻结实现进入
从未读取的一次性 confirmation。

### 5.4 “系统写论文”必须是因果链末端

系统自主写稿只有在稿件从同一 append-only ledger 读取冻结数字、失败、图表和引用时才有意义。
如果人或另一个 Agent 先写结论，再挑运行支持它，文章无论多完整都不是系统自主研究产物。Task 265.5
因此必须由系统从 Task 265.2–265.4 的同一 evidence graph 生成；当前人工文档只是治理协议和文献审计，
不是参赛研究文章。

## 6. 适合 AutoResearch 的混合 OPHIS 架构

```mermaid
flowchart LR
    A["实时一手文献 + 冻结研究 brief"] --> B["LLM：提出可证伪机制与精确代码"]
    B --> C["Harness：静态审查与隔离执行"]
    C --> D["Observation：确定性 telemetry / traceback / metric"]
    D --> E["Problem：异常检测器形成机器可检验问题"]
    E --> F["Hypothesis：方向预测 + 替代解释 + falsifier"]
    F --> G["Intervention：匹配对照、阻断、消融"]
    G --> H["Development：完整分支树与选择校正"]
    H --> I["冻结唯一实现与 search-freeze receipt"]
    I --> J["一次性 sealed confirmation"]
    J --> K["确定性裁决 + 系统自产文章 + RO-Crate"]
    J -. "禁止回流" .-> B
```

角色边界如下：

- **LLM 是提案者和代码执行器，不是证据。** 它可以解释观测、提出替代机制、编写修订，但不能宣布
  自己正确。
- **机制引擎是确定性的观测—问题层。** 它计算时间序列、变化点、分叉、相关滞后、失败 traceback、
  形状和资源指标，并把原始量与检测规则一起哈希。
- **Harness 是干预执行层。** 同一源码字节通过安全、资源、功能、开发实验和消融；传输重试与科学
  修订分账。
- **Evidence Graph 是记忆，不是聊天摘要。** observation、problem、hypothesis、intervention、
  comparator、result、claim 和 artifact 都有不可变 ID、父哈希与支持/反驳边。
- **Open Science 层是发布边界。** PROV-O、RO-Crate 和 Workflow Run RO-Crate 表达来源、Agent、运行、
  结果与负结论的关系；公开视图还必须做权限、许可和秘密清理。[S26–S28]

## 7. Task 265.3 的机制驱动实验协议

### 7.1 开发阶段

1. 执行 Task 265.2 冻结的 8 个首代模型代码；每个失败、超时和静态拒绝都进入 ledger。
2. 按系统、condition 和 seed 做配对/分块；任务/系统是主要推断单位，不能把时间点或 seed 冒充独立
   样本。
3. 在开发数据上最多形成 1–4 个正式机制 cycle。每个 cycle 必须在干预前冻结：
   `observation_id`、检测规则、`problem_id`、方向性预测、替代解释、唯一干预差异、匹配 comparator、
   主要 endpoint、falsifier 和预算。
4. LLM 可以据结构化失败产生 mutation/ablation，但总候选不超过 12、总 generation 不超过 2；
   不得人工补科学代码。
5. development 上所有效应只用于选择和机制诊断，报告全候选分布、失败率、预算与搜索路径，不声称
   confirmatory significance。

### 7.2 机制证据门

一条 cycle 只有同时满足下列条件才可写 `mechanism_supported_on_development`：

- observation 可从原始 telemetry 确定性重算；
- hypothesis 在干预前存在，包含方向预测；
- intervention 与 comparator 除目标因素外匹配；
- 至少一个针对替代解释的负对照或组件消融；
- 多 seed、跨系统的效应和不确定性被报告；
- 没有把 LLM 自评、单条曲线或后验故事登记为支持证据。

任何缺项只允许 `interesting_observation`、`hypothesis_generated` 或 `mechanism_not_supported`。OPHIS
式文字链本身不产生机制 claim。

### 7.3 选择冻结与一次性确认

Pareto/failure-aware policy 只能从完整 development ledger 选一个最终实现。选择后冻结精确代码、
环境、全部 prompt/response、分支树、比较记忆、消融和裁决器，签发 search-freeze receipt。确认执行器
验证 receipt 后才解封 10 ODE + 4 PDE；研究 Agent 永远看不到确认身份或中间结果，也不能二次选择。

主门保持 Task 265.1 的前瞻定义：SNR20 系统级 median derivative-NMSE 相对最强官方基线至少改善
5%，失败感知、全部冻结 cells 进入终态，系统级 bootstrap 95% 下界大于 0。结构、轨迹、复杂度、
鲁棒性、耗时和峰值内存无论好坏全部报告。未通过就形成自主负结果文章，不改阈值、不换 panel、
不再试一次。

## 8. 可发表级别的停止条件

系统只能在下列条件全部成立时标记 `ready_for_human_submission_review`：

1. 新颖性由当前一手文献和相邻工作审计支持，而非模型自称；
2. 数据、许可、分析单位、基线和计算预算有效；
3. development 搜索与 sealed confirmation 完全隔离；
4. confirmation 达到预注册效应与不确定性门；
5. 机制 claim 有前瞻 observation—hypothesis—intervention—ablation 因果链；
6. 独立干净目录能够重建指标、图表、文章和文件哈希；
7. 系统生成稿逐条通过 claim-evidence、citation、figure/table consistency 审计；
8. 作者、许可、伦理、venue fit 和外部投稿仍由人类明确批准。

“能力预检通过”只授权运行 Task 265.3；“开发候选看起来更好”只授权冻结一个实现；“确认显著”也只
授权生成审稿包。任何阶段都不能越级声称录用或科学真理。

## 9. 开放问题

1. 训练内部 observable 数量可达数千时，怎样控制变化点和相关性挖掘的多重比较？
2. 怎样把机制假设的自然语言转为可执行 causal graph，而不让编排器偷偷决定科学内容？
3. 哪些负对照能区分真正机制、一般正则化、计算预算变化和实现副作用？
4. 对慢热方法，低保真 stage racing 会不会系统性误杀；应保留多少 exploration quota？
5. LLM 预训练污染无法完全观测时，“新发现”应采用什么强度的措辞？
6. 机制发现跨模型、数据规模或任务族外推时，需要多少独立系统才足以支持普遍性？
7. 私有 observable/干预空间能否满足竞赛和论文的可复核性要求？

## 10. 结论：逐题回答

**RQ1：**当前系统已经能自动完成文献检索、候选生成、代码执行、搜索和写稿中的很大部分，但公开
benchmark 一致显示复现、开放式新颖性、评价有效性和长程可靠性仍弱。最可信的证据来自客观执行、
独立重复和人类/外部验证，而不是 LLM judge 或论文外观。

**RQ2：**OPHIS 的五步闭环是有价值的研究组织原则，公开案例也提供了值得复验的信号；但其“纯非
LLM”表述与 NanoGPT coding-agent 描述并不完全一致，核心发现空间未公开，比较预算、选择偏差和
置信推断仍有缺口。因此它应作为架构灵感和待复验研究对象，而不是已确立的新范式结论。

**RQ3：**AutoResearch 应采用混合路线：LLM 负责开放式假设和代码，确定性机制引擎负责观测与问题
检测，Harness 负责匹配干预和失败保留，Evidence Graph/RO-Crate 负责同源证据，development 与一次性
confirmation 负责防止自适应过拟合。只有这一整条链通过，系统才有资格自己生成参赛文章。

在本协议冻结时，Task 265.2 的真实 v22 只证明 8 个模型自产分支能够通过来源、安全和五类维度能力门，
官方 development result 与机制 cycle 仍为零。Task 265.3 随后按该协议真实执行并形成自主开发负结果；见
下方 post-execution update。能力包见
[[projects/ai_researcher_system/progress/task-265-2-autonomous-branch-engine|Task 265.2 autonomous branch engine]]。

## 11. 参考文献与规范

- [S01] Yu et al. (2026), [OPHIS: Towards Mechanistic Auto-Research](https://www.meta-circle.com/blog/ophis-a-new-paradigm-for-autoresearch)（团队博客，非同行评审论文）。
- [S02] MetaCircle, [OPHIS Best reproducible snapshot](https://github.com/dyu056/OPHIS_Best).
- [S03] MetaCircle, [OPHIS RSI baseline](https://github.com/dyu056/OPHIS_RSI_baseline).
- [S04] Simon et al. (2026), [There Will Be a Scientific Theory of Deep Learning](https://arxiv.org/abs/2604.21691).
- [S05] Liu, Michaud & Tegmark (2022), [Omnigrok](https://arxiv.org/abs/2210.01117).
- [S06] Yamada et al. (2025), [The AI Scientist-v2](https://arxiv.org/abs/2504.08066).
- [S07] [MLRC-Bench](https://arxiv.org/abs/2504.09702).
- [S08] [Towards Execution-Grounded Automated AI Research](https://arxiv.org/abs/2601.14525).
- [S09] [MARS: Modular Agent with Reflective Search](https://arxiv.org/abs/2602.02660).
- [S10] [AI Research Agents for Machine Learning](https://arxiv.org/abs/2507.02554).
- [S11] [CodeScientist](https://arxiv.org/abs/2503.22708).
- [S12] Schmidgall et al. (2025), [Agent Laboratory](https://arxiv.org/abs/2501.04227).
- [S13] Gottweis et al. (2025), [Towards an AI co-scientist](https://arxiv.org/abs/2502.18864).
- [S14] [Kosmos: An AI Scientist for Autonomous Discovery](https://arxiv.org/abs/2511.02824).
- [S15] [SciAgentArena](https://arxiv.org/abs/2606.12736).
- [S16] [AutoResearchBench](https://arxiv.org/abs/2604.25256).
- [S17] [REPRO-Bench](https://arxiv.org/abs/2507.18901).
- [S18] [ReplicatorBench](https://arxiv.org/abs/2602.11354).
- [S19] Siegel et al., [CORE-Bench](https://arxiv.org/abs/2409.11363).
- [S20] Starace et al., [PaperBench](https://arxiv.org/abs/2504.01848).
- [S21] [Life After Benchmark Saturation](https://arxiv.org/abs/2606.26158).
- [S22] Dwork et al. (2015), [The reusable holdout](https://arxiv.org/abs/1506.02629).
- [S23] Dwork et al. (2014), [Preserving statistical validity in adaptive data analysis](https://arxiv.org/abs/1411.2664).
- [S24] Cawley & Talbot (2010), [On Over-fitting in Model Selection](https://www.jmlr.org/papers/v11/cawley10a.html).
- [S25] Bouthillier et al. (2021), [Accounting for Variance in Machine Learning Benchmarks](https://arxiv.org/abs/2103.03098).
- [S26] W3C, [PROV-O](https://www.w3.org/TR/prov-o/).
- [S27] Research Object community, [RO-Crate 1.3](https://www.researchobject.org/ro-crate/specification/1.3/introduction.html).
- [S28] Research Object community, [Workflow Run RO-Crate](https://www.researchobject.org/workflow-run-crate/).

## 12. 关联证据

- [[task-261-2-generated-mechanism-evidence-survey-2026|模型生成机制与 claim-evidence 综述]]
- [[graph-harness-loop-open-science-2026|Graph/Harness/Loop/Open Science 重构研究]]
- [[projects/ai_researcher_system/progress/task-265-1-autonomous-competition-plan|Task 265.1 结果盲冻结]]

## 13. Post-execution update：Task 265.3 对 OPHIS 合同的实证检验

Task `265.3` package
`8f42cbb684b7b02eee5d4e9287e26f3edaebd49b7215f603d274450a58994576` 已在不读取 confirmation 的条件下完成
348 个候选 development cells、84 个 Operon cells 和 4 个 prospective cycles。系统自产的 cycle-01 在两个匹配系统上
方向一致，但干预只是把训练段平均导数用于所有 query；完整 14-system 面板上反而得到 Operon-relative median
`-4.452492`。最终选择的 `branch-08` 在单 query slice 上做时间有限差分，退化为零导数，full NMSE≈`1`、
train sensitivity=`0`，相对 Operon 为 `-2.796575`。系统按预先冻结规则停止，没有 receipt、confirmation 或稿件。

这个结果支持 OPHIS 的一个强结论，也否定一个弱用法：显式 Observation→Problem→Hypothesis→Intervention 能把失败变成
可审计机制证据；但只冻结自然语言机制链和 matched 两系统仍不足以保证泛化。下一协议必须把“训练数据拟合出具体方程”本身
变成可执行机制：fit once、冻结 terms/coefficients、predict unseen query、known-law recovery、train-shuffle/null degradation，
并分别要求 ODE/PDE strata 通过。相关正式进度见
[[projects/ai_researcher_system/progress/task-265-3-autonomous-development-negative|Task 265.3 autonomous development negative]]。
