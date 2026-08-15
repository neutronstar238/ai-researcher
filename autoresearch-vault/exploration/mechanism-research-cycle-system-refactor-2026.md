---
title: 通用机制科研循环系统重构证据审计
date: 2026-08-14
status: architecture-frozen-local-contract-implemented-bridge-pending
task: "272"
tags:
  - autonomous-research
  - mechanism-research-cycle
  - scientific-validity
  - evidence-first
  - open-science
  - provenance
links:
  - graph-harness-loop-open-science-2026
---

# 通用机制科研循环系统重构证据审计

> [!summary]
> 公开研究支持“自动串联科研工序、在客观指标上搜索代码、在专家闭环中形成可测试假设”，不支持
> “通用系统已能稳定、独立地产出可发表发现”。AutoResearch 应补充一个不含任何题目知识的
> Mechanism Research Cycle：Observation → Problem → competing Hypotheses → discriminating
> Intervention → independent Evaluation。它是 Knowledge Graph 的 typed projection，不是第五图平面，
> 也不是新的执行器。LLM、符号程序或人都可成为提案者；确定性执行、独立验证和开放谱系决定证据级别。

## 1. 冻结问题与范围

1. 哪些自动科研能力已有客观、外部或独立证据？
2. 为什么完成工作流、提高 benchmark 或生成论文仍达不到发表级科学证据？
3. 什么样的 provider/topic-neutral 合同能把试错升级为可证伪机制研究？

本审计不分析或优化任何具体科研题目，不选择领域方法，不规定指标、阈值、数据、baseline、null、query、
adapter 或 prompt。任何单题案例最多是架构缺陷样本，不能成为 kernel 设计依据或验收集。

## 2. 证据矩阵

| 证据 | 已支持 | 关键限制 | 架构含义 |
|---|---|---|---|
| [The AI Scientist](https://arxiv.org/abs/2408.06292) / [独立评估](https://arxiv.org/abs/2502.14297) | 模板内想法、代码、实验、图表、写稿可串联 | 执行错误、结果/引用幻觉、自评高估 | generator、executor、verifier、reviewer 必须分权 |
| [AI Scientist-v2](https://arxiv.org/abs/2504.08066) | 无固定模板的并行实验树与复现节点可行 | 人从约 40 个想法和多次运行中筛选；3 篇仅 1 篇过高接收率 workshop，均未达主会 | 保存全分母、meta-selection、seed 与完整分支，不报 best-of-N 成功率 |
| [Agent Laboratory](https://arxiv.org/abs/2501.04227) | 角色化文献—实验—报告协作可运行 | 人评分显著低于自动评分，存在虚构实验与 sandbox 风险 | self-review 只能建议，结果事实必须机器绑定 |
| [AIDE](https://arxiv.org/abs/2502.13138) / [MLE-bench](https://arxiv.org/abs/2410.07095) | 隐藏 objective 下的 code-tree search 可客观比较 | 只测 ML engineering，可能优化代理目标 | Objective Harness 是子门，不是科学发现总分 |
| [PaperBench](https://openai.com/index/paperbench/) / [ResearchGym](https://arxiv.org/abs/2602.15112) | 层级 rubric、容器复现、隐藏 grader 与轨迹审计可测 | 复现/改进率仍低，常见配置错误、cherry-pick 和 fabrication | 分开 capability ceiling 与 reliability，独立复现位于发表门前 |
| [Co-Scientist](https://doi.org/10.1038/s41586-026-10644-y) | 异步多 agent、检索 reflection、debate、proximity 与少量外部实验有效 | Elo 非独立真值，湿实验全部 expert-in-loop 且 preliminary | 同源投票不能替代判别干预或外部验证 |
| [OPHIS 发布](https://www.meta-circle.com/blog/ophis-a-new-paradigm-for-autoresearch) / [最佳](https://github.com/dyu056/OPHIS_Best) / [基线](https://github.com/dyu056/OPHIS_RSI_baseline) | 团队报告从内部动态形成干预，并公开最佳/基线快照 | 非论文、完整空间私有、最佳项经大规模选择、尚无独立复现；复杂案例使用 coding agent | 吸收机制闭环，不照搬团队比例或“无 LLM”口号 |
| [Robot Scientist Adam](https://doi.org/10.1126/science.1165620) / [AutoRA](https://doi.org/10.21105/joss.06839) | 假设—实验—解释循环和模块化 research state 有长期先例 | 编排能力不自动保证一般因果或发表质量 | 新意必须落实为可验证合同、干预、复现与迁移 |

## 3. 证据分级与不可跨越状态

```text
idea
  -> literature_grounded
  -> executable
  -> observed
  -> replicated
  -> independently_validated
  -> publication_eligible
```

论文外观、运行成功、单一分数改进、LLM 自评或团队发布都不能跨级。每级必须绑定前一级内容哈希和新产生
的 Provenance Entity/Activity/Agent、Claim/Evidence/Validation、执行包和独立裁决。负结果、反驳和未定
不降级为工程失败；它们是可发表性判断和后续学习所需的一等科学终态。

## 4. Mechanism Research Cycle 合同

- **Observation**：测量规范、原始/派生结果、不确定性或局限、环境和作者来源；
- **Problem**：由 observation 支撑的待解释偏差与范围，不偷渡因果结论；
- **Hypothesis**：mechanism、prediction、falsifier、竞争/零解释和识别范围；
- **Scientific Intervention**：冻结 protocol、comparator、changed/frozen factors、estimand、metric、decision
  rule、HarnessSpec 和 LoopSpec；
- **Evaluation**：独立报告逐 hypothesis 返回 supported、contradicted 或 inconclusive，并绑定结果、
  不确定性、支持/反驳/限制证据；
- **Snapshot**：内容寻址、引用完整、可形成未完成前缀；首版不得伪造 parent，后续版本必须绑定同一
  cycle 的紧邻父快照，再投影到 Knowledge Graph。

外部 ID/hash 只证明“声明绑定了什么”，不证明对象存在或有效。只读 bridge 必须解析并重验
ProvenanceBundle、EpisodePackage、LoopRunSnapshot 和 EvaluationReport；否则不得升级结论。本地投影
因此只使用 `Declared`、`declared_assessment` 与 `external_validation=unverified`，不把 Harness、Loop、
provenance 或 evaluation-report 外键混入 Knowledge 平面。

## 5. 四平面职责

| 平面/组件 | 负责 | 不负责 |
|---|---|---|
| Control Graph / Loop | 顺序、预算、审批、重试、holdout、恢复、fork | 判断机制真假 |
| Harness / Episode | 冻结环境、执行、失败与资源事实 | 把执行成功解释为假设成立 |
| Provenance & Evidence | 人/模型/工具、活动、实体、主张、证据与验证 | 重复生命周期语义 |
| Evaluation & Policy | 独立 grader、重复试验、promotion、rollback | 替代逐假设解释 |
| Mechanism Research Cycle | 科学阶段关系与逐假设裁决 | 执行实验、验证外部 hash、授权发布 |

## 6. 系统级验证设计

在冻结、隐藏、跨领域任务集上，以相同模型调用、实验、算力和时间预算比较：execution-only/random、
LLM+互联网、LLM+实验历史、无 LLM 机制闭环、LLM+机制闭环；消融独立 verifier、判别性干预、完整谱系
与 rollback。报告全尝试分母、valid-run rate、多 seed 分布、假设校准、竞争解释区分、证伪、效应与
不确定性、复制、迁移、峰值后回归、单位预算有效结论、evidence coverage、provenance completeness、
人工 meta-selection、cherry-pick/fabrication 和所有失败。

## 7. Open Science 与 provider 边界

[W3C PROV-O](https://www.w3.org/TR/prov-o/)表达跨域 provenance；
[RO-Crate 1.3](https://www.researchobject.org/ro-crate/specification/1.3/index.html)和 Workflow Run RO-Crate
封装研究对象与运行；FAIR、DataCite 和不可变 registration/version lineage 管理发现、许可和版本。
这些标准不认证结果正确，独立复现、伦理/许可和人工计划批准仍是合取门。

Provider 能力只属于 transport/context policy。Qwen3.7 Max 的 1,000,000 总上下文、991,808/983,616
输入、131,072 完整输出与 262,144 最大思维链来自
[官方模型页](https://help.aliyun.com/zh/model-studio/qwen3-7-max)；请求使用官方
[`max_completion_tokens`](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)
并预留最多 10 token 误差。任何 provider 数字都不得进入科学机制合同。

## 8. 实施门

1. 272.1：已冻结本证据、架构与题目防火墙；
2. 272.2：本地合同、内容寻址、引用完整性与未验证态 Knowledge Graph 投影已实现并通过独立复审；
3. 272.3：只读解析真实 provenance/harness/loop/evaluation；
4. 272.4：两个以上无关 vertical 的 shadow parity 与冻结因果评测；
5. 272.5：claim 状态、Vault/RO-Crate 和 publication gate。

任一阶段失败都保留旧路径权威并回滚；不得用领域关键词、放宽冻结门、重看 holdout 或只报最佳轨迹修复。

## 9. 关联

- [[graph-harness-loop-open-science-2026|Graph/Harness/Loop/Open Science 重构研究]]
