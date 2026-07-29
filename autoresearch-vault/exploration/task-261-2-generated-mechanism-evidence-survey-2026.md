---
title: Task 261.2：模型生成机制、选择性事实性与声明证据综述
date: 2026-07-29
status: frozen-foundation
task: "261.2.1"
tags:
  - selective-factuality
  - scientific-agent-evaluation
  - generated-code-security
  - claim-evidence-alignment
  - bounded-autonomy
  - evidence-first
links:
  - graph-harness-loop-open-science-2026
  - unified-evaluation-observability-security-2026
  - task-261-2-1-mechanism-foundation
---

# Task 261.2：模型生成机制、选择性事实性与声明证据综述

> [!summary]
> 本综述只冻结 Task 261.2 的研究问题、来源边界和可证伪设计空间，不产生新机制结果。
> 现有 clean-v2 父 Sprint 的科学终点仍是负结果。只有后续模型诊断、模型生成的精确代码字节、
> 安全审查、Harness 执行、开发筛选、新预注册和未揭示确认面板形成同一条内容寻址因果链，
> 才能讨论“模型生成并执行了新机制”。本文不能授权投稿，也不能把设计证据写成实验成功。

## 1. 研究边界与冻结问题

父证据是 `task261-bounded-autonomous-clean-v2`。其 manifest、task-level endpoint 和 autonomy
audit 分别固定为：

- manifest hash：
  `eb3ac1c5411b4444e6512a5119ecff1afbbedb736ace12e2f7329d3e90c1e33e`；
- endpoint hash：
  `e4535efd50c34c2d104b367dfa1fc3a7ba1dde51081d8b07738d8c68e9c03c52`；
- autonomy audit hash：
  `23e8333334f9e8cb01f8a60303a672a992b628fa94bcabb90851f433561cc360`。

父轮以 10 个独立任务为统计单位，主门因
`bootstrap_ci_lower_above_zero=false` 而关闭。那 10 个任务已经揭示，不能用于下一机制的选择、
调参或确认。围绕这一负结果，检索前冻结三个问题：

1. 怎样把二元“有证据/无证据”门升级为显式表达接受、弃答、覆盖率和残余风险的可检验机制？
2. 怎样证明模型提案、受审代码、沙箱执行和科学结果确实来自同一份生成代码，而不是事后拼接？
3. 怎样用结果盲的独立面板和逐项 claim-evidence 规则，阻止已揭示任务调优和论文过度声明？

## 2. 检索方法

检索日期为 2026-07-29。查询覆盖五种互相制约的视角：

1. **主流机制视角**：abstention、selective prediction、semantic uncertainty、long-form
   factuality；
2. **批判与反例视角**：accuracy incentive、risk-control impossibility、分布漂移和评价器误差；
3. **科研 Agent 方法视角**：可执行科学任务、计算复现、污染控制和 bounded discovery；
4. **相邻安全视角**：生成代码的功能性、安全性、静态/动态 oracle、软件开发框架；
5. **论文证据视角**：paper-code alignment、citation attribution、claim overstatement 和
   claim-level evaluation。

纳入规则是：原始研究论文的出版社/会议/官方预印本页，或 NIST 等正式标准；题名、作者、年份、
venue、DOI/arXiv/OpenReview 标识必须在正式页面逐项核对；正文只采用摘要或标准条款可支持的结论。
排除二手博客、聚合站、无法确认题录的页面，以及把某一 benchmark 的数值直接外推到本项目的说法。

最终冻结 14 个来源：11 个同行评审论文、2 个明确标注的预印本、1 个官方标准。四个主题各至少
3 个来源，交叉主题论文可以同时计入两个分支。v3 联网烟测对 14 个正式 locator 全部得到
HTTP 200；这只证明当时可达和题录可核验，不证明论文结论必然正确。

## 3. 证据分类

| 分支 | 典型分析单位 | 可用信号 | 可审计输出 | 对 Task 261.2 的贡献 | 仍缺什么 |
|---|---|---|---|---|---|
| 选择性事实性 | 单条事实或结构化输出 | 语义不确定性、外部支持、校准风险 | accept/abstain、coverage、risk | 把“猜答案”改成显式选择性决策 | 科学任务上的风险定义与分布漂移保证 |
| 外部证据核验 | 原子事实—来源对 | 检索证据、归因一致性 | 支持/反驳/未知、citation precision/recall | 让每个接受声明可追溯 | 来源本身真实性与复杂科学蕴含 |
| 科研 Agent 评价 | 可执行工作流任务 | 程序、执行结果、成本、复现 | task-level outcome 与完整 trajectory | 要求以执行和任务为评价单位 | 新发现、机制创新与开放世界有效性 |
| 生成代码安全 | 同一份生成代码 | 单测、静态分析、动态 oracle、sandbox | 功能×安全联合结论 | 阻止“能跑但不安全”或“安全但无功能” | oracle 漏报、语言迁移与科学正确性 |
| 声明—证据对齐 | 论文 claim、代码、图表 | 检索、paper-code QA、过度声明评分 | typed claim-evidence map | 阻止 named work、方法、结果和图注无证据 | 自动 entailment 的误判与作者责任 |

## 4. 选择性事实性：从猜测奖励转向风险—覆盖率契约

Kalai 等人的分析说明，准确率式评分会奖励模型在不知道时猜测；若错误和弃答没有公开、非对称的
代价，单纯要求“更准确”反而可能增加幻觉。[S01] 这直接支持把接受与弃答写成正式决策，而不是
隐藏在自然语言中。

Semantic entropy 表明，按意义而非表面 token 聚合生成差异，可以识别一类 confabulation，并在拒绝
高不确定输出时改善准确率—覆盖率权衡。[S02] 但它只利用模型内在采样分歧，不能验证外部证据，
也可能对稳定但错误的回答给出低不确定性。

结构化生成上的 conformal risk control 进一步指出：严格风险目标可能根本不可行，保证依赖
exchangeability、损失定义和校准分布；分布漂移后仍会出现残余失败。[S03] 因此本项目不能只记录
“风险低于阈值”，还必须记录目标是否可行、覆盖率是否达到最低值，以及在新任务族上的失配。

SAFE 将长文本拆成原子事实、检索外部证据，再在 precision 与响应覆盖之间平衡。[S04] 这为
claim-level 检验提供了工程形状，却仍依赖 LLM evaluator 和开放检索。对科学论文来说，“搜索结果
看起来支持”不能替代数据、代码、统计裁决和负结果证据。

综合而言，候选机制至少应输出：

- 每条 claim 的 `accept` 或 `abstain`；
- 接受集合的 unsupported-claim risk；
- 总 coverage 与预注册最低 coverage；
- 外部证据状态与失败原因；
- 不可行、分布外或证据冲突时的 fail-closed 终态。

这些是测试要求，不是对某个具体算法的提前选定。

## 5. 科研 Agent 评价：执行能力不等于自主发现

ScienceAgentBench 把 102 个任务统一为独立 Python 程序，并同时评价生成程序、执行结果和成本；
其任务来自 44 篇同行评审论文并经过领域专家验证。[S05] 这支持“科学 Agent 必须交付可执行物”，
但 benchmark 自身明确要求先严格评价工作流中的单项任务，不能据此声称端到端发现已经可靠。

CORE-Bench 以论文代码与数据的计算复现为任务，显示即使范围比 replication 更窄，环境恢复和结果
提取仍然困难。[S06] 它为 Harness、任务级 outcome 和可恢复执行提供证据，却不能证明一个 Agent
能原创并证伪新机制。

AI Scientist-v2 展示了在受限机器学习环境中进行 template-free 实验生成和迭代管理的可能性。[S07]
但其 workshop-level 目标、有限样本与预印本状态，不足以建立一般科学可靠性、安全性或未污染评价。

因此 Task 261.2 必须把“模型写出一段代码”“代码能运行”“开发集表现可接受”“独立面板支持新
科学结论”分为四个不同门。任何前一门通过都不能替代后一门。

## 6. 生成代码安全：功能、静态与动态证据必须同源

SecureVibeBench 在真实漏洞引入情境中同时使用功能测试、静态和动态安全 oracle；结果显示当前
代码 Agent 难以同时生成正确且安全的代码。[S08] ICSE 2026 的系统研究也发现，只在不同数据集上
分别评价功能和安全、或只依赖单个静态分析器，会高估安全代码生成；某些方法甚至通过删除功能代码
获得表面安全提升。[S09]

NIST SSDF 要求检查人类可读代码、测试可执行代码，并保留软件组件来源信息。[S10] 它是结果导向
框架，不给出本项目的具体实现，但支持以下最低组合：

1. 对模型生成的**精确 UTF-8 字节**计算 SHA-256；
2. 静态审查危险导入、路径越界、秘密、网络、子进程和资源滥用；
3. 同一字节通过单元测试与性质测试；
4. 同一字节在禁网、限时、限资源 Harness/sandbox 中执行；
5. 将 proposal、source、review、test、HarnessSpec、episode 和结果哈希串成单一 lineage。

静态或动态任一门缺失、执行代码与审查代码哈希不同、或运行使用网络，都只能产生 blocked/failed
证据，不能产生替代性的“fallback 科学结果”。

## 7. 声明—证据对齐：论文审计必须是类型化的

SCICOQA 说明论文—代码差异尤其容易出现在省略细节、长上下文和训练分布外论文中。[S11]
CiteGuard 说明 citation attribution 需要检索感知的对齐验证，不能只依赖无 grounding 的 LLM
judge。[S12] RIGOURATE 则把“声明强度超过论文内部证据”操作化为 evidence retrieval 与
overstatement scoring。[S13] ALCE 更早明确区分答案正确性、citation recall 与 citation
precision，提醒我们“有引用格式”不等于“引用支持该说法”。[S14]

这些工作共同支持逐项类型门，而不是整篇论文一个总分：

- named prior work → verified literature；
- method → exact generated code + preregistered protocol；
- experiment → preregistration + execution artifact；
- result → metric + deterministic adjudication；
- limitation → failure/uncertainty evidence；
- figure description → figure artifact + underlying metric。

审计应报告每个缺失 evidence kind 和 unsupported claim ID。即使覆盖率完整，也不能自动授权作者、
许可、venue fit 或外部投稿。

## 8. 从综述导出的候选测试设计

下列设计是给 Task 261.2.2 的**候选约束空间**，不是已经选定或已经有效的机制：

1. 从 parent evidence hash 和失败码生成原因诊断，明确禁止 prompt-only、paper-only、
   threshold-only 和 revealed-panel rerun。
2. 模型必须引用冻结来源提出机制级 delta、至少两个可证伪条件，以及可执行
   `evaluate_claims` 实现；代码生成失败时终态为 blocked。
3. proposal hash 绑定 diagnosis、research brief、model interaction 和精确 source SHA-256。
4. 只有静态审查、单测、性质测试、禁网 sandbox smoke 全部通过，代码才可进入 development。
5. development 至少 3 个任务，confirmatory 至少 6 个任务；两者互斥，且均不得复用父轮 10 个
   已揭示任务。确认集状态保持 `sealed-until-code-freeze`。
6. 主指标预注册为 minimum coverage 下的 unsupported-claim rate，同时冻结风险上限、coverage
   下限、bootstrap 次数/种子和停止规则；代码冻结后不得改阈值。
7. 确认结果揭示前，冻结 proposal→code evidence→panel 的完整 hash；只有此时才允许合同记录
   `open_ended_experiment_code_generation=true`，它仍不等于科学终点通过。
8. 论文由冻结证据生成，逐项 claim-evidence audit 不得改写确定性 scientific verdict。

可能的机制族包括 risk-selective gate、verifier ensemble 和 external-feedback controller，但具体
选择必须由后续 provider-neutral 模型根据父失败和文献作出；本综述不能成为代码作者预置机制的
伪装。

## 9. 反方审查与局限

最强反对意见不是“这些方向无用”，而是“把若干局部评价方法拼起来仍然不构成科学发现保证”。
这一反对意见成立，具体限制如下：

- 14/14 URL 可达只证明来源页面存在；内容哈希提供 tamper evidence，不提供外部真实性。
- Semantic entropy 主要识别 sampled generations 的意义分歧，不能捕获稳定、系统性的错误。[S02]
- SAFE 依赖 LLM 与搜索结果，对复杂科学蕴含和来源质量没有完备保证。[S04]
- Conformal risk 的保证依赖交换性与可实现目标；严格目标可能没有非空接受集。[S03]
- ScienceAgentBench、CORE-Bench 和 AI Scientist-v2 分别覆盖科学工作流任务、计算复现和受限 ML
  实验，不能直接证明开放式新发现。[S05][S06][S07]
- SecureVibeBench 偏向 C/C++ 内存安全，ICSE 研究依赖有限分析器；其漏洞率不能转移为本项目的
  Python 科学插件风险。[S08][S09]
- 静态分析器和动态测试都不完备；“没有发现问题”不是“安全”或“科学正确”。
- SCICOQA、CiteGuard、RIGOURATE 都使用自动模型或检索组件，可能漏掉隐含、跨段或强度细微变化
  的过度声明。[S11][S12][S13]
- Task 261.2.1 尚未调用模型生成新机制、尚未执行 development，更未揭示 confirmatory 结果；
  任何正面科学结论现在都属于越界。

因此合理结论只能是：这些来源足以定义一个更难伪造、可失败、可审计的实验协议；它们不足以预告
该协议会得到正结果。

## 10. 开放问题

1. unsupported claim 的独立标注单位应是原子事实、整条结论还是 claim—evidence 对？
2. 在任务族漂移下，怎样同时报告 calibration、coverage 和有限样本不确定性？
3. 至少 3/6 个 development/confirmatory 任务只是合同下限；什么规模和任务族多样性才足以支撑
   论文级外推？
4. 怎样证明任务、来源和模型预训练数据之间不存在不可见污染？
5. 哪些静态和动态 oracle 对生成的 Python 科学代码具有足够互补性？
6. 负结果、abstention 和运行失败怎样在 manuscript audit 中避免被错误折叠？
7. 完成技术证据后，作者贡献、许可、伦理、venue fit 和投稿批准仍应由谁承担？

## 11. 结论

对 RQ1，现有证据支持把二元 evidence gate 改造成显式的 accept/abstain、minimum coverage、
residual risk 和 feasibility 契约；但风险信号必须结合外部证据和分布漂移限制。

对 RQ2，可信因果链必须以精确生成代码字节为中心，依次绑定模型交互、提案、静态审查、单元/性质
测试、HarnessSpec、禁网 sandbox episode、预注册和结果。任一哈希不一致都应 fail closed。

对 RQ3，开发与确认面板必须与父轮及彼此互斥，确认结果在 code freeze 前不可见；论文层必须对
named work、方法、实验、结果、限制和图注分别施加 typed evidence requirement。

这三个答案足以冻结下一轮的研究基础，但没有产生新机制结果。下一合法步骤是 Task 261.2.2：
让配置化本地模型生成一个父绑定机制，对其精确代码做安全与 Harness 审查，并且只查看 development
分区。

## 12. 参考文献

[S01] Kalai, A. T., Nachum, O., Vempala, S. S., & Zhang, E. (2026).
Evaluating large language models for accuracy incentivizes hallucinations. *Nature*, 653,
1047–1051. doi:10.1038/s41586-026-10549-w.

[S02] Farquhar, S., Kossen, J., Kuhn, L., & Gal, Y. (2024). Detecting hallucinations in large
language models using semantic entropy. *Nature*, 630, 625–630.
doi:10.1038/s41586-024-07421-0.

[S03] Kotte, V. (2026). When Can Conformal Risk Control Certify LLM Outputs? Bounds,
Impossibility, and Adaptation for Structured Generation. *arXiv preprint*,
arXiv:2606.29054.

[S04] Wei, J., Yang, C., Song, X., et al. (2024). Long-form factuality in large language models.
*Advances in Neural Information Processing Systems 37*. doi:10.52202/079017-2567.

[S05] Chen, Z., Chen, S., Ning, Y., et al. (2025). ScienceAgentBench: Toward Rigorous
Assessment of Language Agents for Data-Driven Scientific Discovery. *ICLR 2025*.
OpenReview:6z4YKr0GK6.

[S06] Siegel, Z. S., Kapoor, S., Nadgir, N., Stroebl, B., & Narayanan, A. (2025).
CORE-Bench: Fostering the Credibility of Published Research Through a Computational
Reproducibility Agent Benchmark. *Transactions on Machine Learning Research*.
OpenReview:BsMMc4MEGS.

[S07] Yamada, Y., Lange, R. T., Lu, C., et al. (2025). The AI Scientist-v2: Workshop-Level
Automated Scientific Discovery via Agentic Tree Search. *arXiv preprint*,
arXiv:2504.08066.

[S08] Chen, J., Huang, H., Lyu, Y., et al. (2026). SecureVibeBench: Benchmarking Secure
Vibe Coding of AI Agents via Reconstructing Vulnerability-Introducing Scenarios.
*ACL 2026*. doi:10.18653/v1/2026.acl-long.1107.

[S09] Dai, S.-C., Xu, J., & Tao, G. (2026). Rethinking the Evaluation of Secure Code
Generation. *ICSE 2026 Research Track*. arXiv:2503.15554.

[S10] Souppaya, M., Scarfone, K., & Dodson, D. (2022). Secure Software Development
Framework (SSDF) Version 1.1. *NIST Special Publication 800-218*.
doi:10.6028/NIST.SP.800-218.

[S11] Baumgärtner, T., & Gurevych, I. (2026). SCICOQA: Quality Assurance for Scientific
Paper-Code Alignment. *ACL 2026*. doi:10.18653/v1/2026.acl-long.1795.

[S12] Choi, Y. M., Guo, X., Fung, Y. R., & Wang, Q. (2026). CiteGuard: Faithful Citation
Attribution for LLMs via Retrieval-Augmented Validation. *ACL 2026*.
doi:10.18653/v1/2026.acl-long.282.

[S13] James, J., Xiao, C., Li, Y., Moosavi, N. S., & Lin, C. (2026). RIGOURATE:
Quantifying Scientific Exaggeration with Evidence-Aligned Claim Evaluation.
*Findings of ACL 2026*. doi:10.18653/v1/2026.findings-acl.1699.

[S14] Gao, T., Yen, H., Yu, J., & Chen, D. (2023). Enabling Large Language Models to
Generate Text with Citations. *EMNLP 2023*. doi:10.18653/v1/2023.emnlp-main.398.

## 13. 本地证据与关联笔记

- 最终 foundation：
  `runs/manual-live/task2612-mechanism-foundation-live-v3/`
- foundation manifest hash：
  `0f5c41b408e4de442874a1f4ea2bef45eedbc6f4f6c42e4e31d25cea57e8b456`
- parent evidence hash：
  `6ae565f23c963514d0c0ac7891a81244171749ca18604bcf734d3c704da652d5`
- research brief hash：
  `9b9b492dcbb33e5d454f628ed06fe3982970fb8a79057f14f1dba0167dea45b0`
- [[task-261-2-1-mechanism-foundation|Task 261.2.1 mechanism foundation]]
- [[graph-harness-loop-open-science-2026|vNext Graph/Harness/Loop/Open Science research]]
- [[unified-evaluation-observability-security-2026|vNext evaluation and Agentic security research]]
