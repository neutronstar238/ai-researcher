---
title: AutoResearch vNext：统一评测、可观测性与 Agentic 安全门研究
date: 2026-07-29
status: implementation-baseline
task: "262.9"
tags:
  - agent-evaluation
  - agentic-security
  - opentelemetry
  - scientific-agents
  - holdout-integrity
  - evidence-first
---

# AutoResearch vNext：统一评测、可观测性与 Agentic 安全门研究

> [!summary]
> 统一评测不能把“代理完成了流程”当成“科学结论成立”。vNext 将任务、重复试验、轨迹引用、
> 环境结果、rubric、grader、统计不确定性、成本、失败切片、promotion 和 rollback 组成一个
> 内容寻址报告，并分别裁决系统质量与科学有效性。OpenTelemetry 只导出默认脱敏的本地 OTLP/JSONL；
> 原始内容若确有调试需要，只能进入显式授权、范围绑定的本地旁路产物。

## 1. 冻结问题与检索方法

本轮在实现前冻结三个研究问题：

1. 怎样用最小共享语义连接 task、trial、trajectory、outcome、rubric、grader、uncertainty、
   cost、failure、promotion 与 rollback，同时区分系统质量和科学正确性？
2. OpenTelemetry GenAI 在规范仍快速变化、内容可能敏感的条件下，应怎样做到默认本地、默认脱敏？
3. 哪些 Agentic 与科研代理故障必须进入本地 promotion 门，而不是只保留为文档风险？

检索日期为 2026-07-29。来源优先级为正式规范和官方文档、同行评审论文、官方开源实现、预印本。
检索按五个视角交叉进行：

- 评测运行时：Inspect AI、OpenAI Evals、重复 trial 和 scorer 分离；
- 科研代理：ScienceAgentBench、CORE-Bench、MLE-bench；
- 安全：OWASP Agentic Top 10、NIST AI RMF/GenAI Profile、NIST AML、AgentDojo；
- 可观测性：OpenTelemetry OTLP、GenAI Semantic Conventions、AgentTelemetry；
- 反方审查：grader 偏差、outcome/evidence 不匹配、训练期或检索期污染、成本与复现性。

纳入条件是能改变本项目契约、门或测试的资料；营销性排行榜、没有方法说明的产品页面和无法核验的
二手总结不作为设计依据。2026 年预印本用于发现新故障，不被描述为成熟标准。

## 2. 交叉检索结论

### 2.1 Task success、environment outcome 与 scientific validity 必须分开

Inspect AI 把 dataset、solver、scorer、epoch、成本/时间限制和日志分开，并允许对既有日志重新评分；
其 epoch reducer 同时支持均值、mode、`pass_at_k` 与要求所有尝试成功的 `pass_k`，说明“至少一次成功”
与“可重复可靠”是不同命题。[S01][S02] ScienceAgentBench 对 44 篇论文中的 102 个任务分别验证程序、
执行结果和成本；三次机会下最佳代理仍只能独立解决 32.4% 的任务，支持先评工作流部件再声称端到端
自动化。[S03]

CORE-Bench 聚焦论文的计算复现而不是文本相似；MLE-bench 同时评估真实机器学习工程、资源扩展与训练
污染；AgentDojo 则同时测量正常任务 utility 与受攻击时 security。[S04][S05][S06] 这些基准共同否定
单一“完成率”成为 promotion 真相的做法。

因此统一报告保留两条互不替代的结论：

- **system quality**：协议是否一致、轨迹能否重放、权限/预算/holdout 是否守住、故障是否被阻断；
- **scientific validity**：环境结果是否由足够证据支持，冻结科学核心验证是否通过，未知是否显式保留。

一个经过验证的科学负结果可以是成功完成的研究 trial；一个流程顺利但证据不匹配的正向结果必须失败。

### 2.2 不能让 grader 成为第二个不透明模型

Inspect 将 scoring 与求解分开，并记录标准误、bootstrap、分组指标与 unreduced epoch 分布。[S01][S02]
LLM-as-a-Judge 的系统研究发现，交换答案位置就可能改变判断，且偏差随 judge 和任务变化。[S07]
2026 年的 outcome-evidence 审计进一步展示：界面动作被记录为成功，并不证明目标环境状态真的改变；
未知证据必须保留为区间，而不是静默计为成功或失败。[S08]

因此：

- rubric、grader 身份、版本、阈值和独立性必须冻结；
- deterministic grader 优先，model grader 不能单独决定科学真值或权限；
- permutation/等价输入不一致必须成为 evaluator-bias fault；
- `unknown` 不能被聚合函数吞掉，promotion 一律 fail closed；
- 重复 trial 同时报告样本数、成功率、标准误和置信区间，不只报告最佳一次。

### 2.3 Holdout 泄漏既可能发生在训练期，也可能发生在检索期

MLE-bench 明确研究预训练污染。[S05] 2026 年的深度研究代理研究把检索期污染拆成 benchmark metadata、
question context 和 explicit answer 三层，并在六个公共基准上观察到最高约 4 个百分点的分数膨胀；
建议隔离 sandbox、透明搜索轨迹和受控 benchmark 访问。[S09]

本项目因此把 holdout 当成有状态权限，而不是一个数据集标签：

- adaptive 工作开始前为 `sealed`；
- reveal 必须由明确事件和权限触发；
- reveal 后不得继续调整机制、提示、rubric 或阈值；
- 轨迹中任何未授权访问、公开答案检索或 reveal 后自适应都产生 failure slice；
- 外部昂贵基准默认禁用，必须通过环境变量显式 opt in，且不能成为本地 CI 的隐含网络依赖。

### 2.4 Agentic 安全需要运行时故障矩阵

OWASP Agentic Top 10 2026 包含 goal hijack、tool misuse、identity/privilege abuse、supply chain、
unexpected code execution、memory/context poisoning、insecure inter-agent communication、
cascading failure、human-agent trust exploitation 和 rogue agents；其核心工程建议是 least agency、
least privilege、sandbox、预算、不可变工具日志、漂移检测和可验证 rollback。[S10]

NIST AI 600-1 要求以 Govern、Map、Measure、Manage 贯穿生命周期，并把内容溯源、部署前测试和事件
披露作为主要考虑；NIST AI 100-2 E2025 则按生命周期、攻击者目标、能力和知识组织 evasion、
poisoning、privacy 与 misuse。[S11][S12] AgentDojo 证明安全评测还必须同时保留正常 utility，
否则“拒绝所有操作”也会伪装成安全。[S06]

本地矩阵采用十个能被确定性信号判定的最小故障：

| 本地 fault | 触发信号 | 必须执行的控制 |
| --- | --- | --- |
| goal hijack | active goal hash 偏离冻结目标 | 阻断并记录目标漂移 |
| tool misuse | 非 allow-list 工具或未验证参数 | default deny |
| identity/privilege | 身份未验证或权限超集 | 最小权限并重新授权 |
| supply chain | 组件摘要/签名与冻结值不符 | 隔离组件 |
| unexpected code | 未批准或未 sandbox 的代码执行 | 阻断执行 |
| memory poisoning | 内存来源或作用域未验证 | 隔离记忆 |
| runaway loop | 步数或重复状态超过预算 | 确定性停止 |
| evaluator bias | 语义等价 permutation 评分超容差 | grader 失效 |
| holdout leakage | 自适应阶段访问或 reveal 后继续调整 | trial 失效 |
| evidence mismatch | claim 与验证 evidence digest 不一致 | 科学门失败 |

OWASP 的 inter-agent、cascading、human-trust 和 rogue-agent 风险分别由身份/权限、runaway-loop、
goal-hijack 与 tool-misuse 的组合覆盖；不为每个名称复制一个无法验证的布尔门。

### 2.5 OTel 是诊断交换层，不是科研事实库

OpenTelemetry core Semantic Conventions 当前为 1.43.0。GenAI 约定已移到独立仓库；该仓库覆盖
GenAI client、MCP、provider spans/metrics/events，但截至本轮检索仍没有 schema URL，且规范状态为
development。[S13][S14] 因此本项目固定 core 1.43.0 与独立仓库
`d74a9bbc419c67dd78ea4fcc26280381ef0bb9db` 快照，不声称兼容一个尚不存在的稳定 GenAI schema。

固定快照中：

- `invoke_agent`、`execute_tool`、retrieval、memory 和 inference 使用规范 operation/span；
- `gen_ai.evaluation.result` 是 recommendation-level evaluation event；
- system instructions、input/output messages、tool arguments/results、retrieval query/documents 都是
  opt-in 内容；
- 官方说明默认不采集 prompt 和 tool arguments，因为它们可能含敏感数据。[S14][S15]

OTLP 1.11.0 的 JSON 编码要求 hex trace/span ID、整数 enum、lowerCamelCase 和字符串形式的 64 位整数；
官方 File Exporter 规定每行是一个 UTF-8 OTLP JSON 对象。[S16][S17] 因此实现选择：

1. 只写本地、内容寻址、单行 OTLP/JSONL 文件，不增加网络发送或新依赖；
2. span 名称保持低基数，run/trial/hash 放 attributes；
3. OTel 文件永不保存 prompt、response、tool argument/result 或 grader explanation 原文；
4. 只保存内容摘要、字段数和 `redacted=true`；
5. 原文保留需要显式 grant，grant 必须绑定 scope hash、过期时间和本地目录；
6. event journal、episode、provenance bundle 仍是权威；OTel 丢失不能改变科研结果或 promotion。

AgentTelemetry 预印本提出 agent、LLM call、tool、planning、reasoning、retrieval、guardrail、
delegation、memory 九类 span 和 14 类 fault，说明仅记录模型调用不足以诊断循环或记忆故障。[S18]
但其中 planning/reasoning 等仍不是 OTel GenAI 标准。本项目只用 `autoresearch.*` 属性引用已有
Control Graph/EventJournal，不创建第二套轨迹真相。

## 3. 冻结实现契约

### 3.1 内容寻址评测报告

统一报告由以下记录组成：

- `EvaluationTaskRecord`：冻结任务、协议、holdout 与外部 benchmark opt-in；
- `EvaluationTrialRecord`：重复序号和对 episode/trajectory/outcome/grader/cost/failure 的引用；
- `TrajectoryRecord`：只保存 episode、journal lineage、replay 和 redacted trajectory hash；
- `OutcomeRecord`：区分 positive、verified negative、blocked、failed 和 unknown；
- `RubricRecord` / `GraderRecord`：冻结 criterion、阈值、grader 独立性和证据摘要；
- `UncertaintyRecord`：trial 数、成功数、均值、标准误和 Wilson 95% 区间；
- `CostRecord`：token、美元、wall time、tool calls 和 known/unknown；
- `FailureSlice`：fault、component、expected/observed digest 与 event ref；
- `PromotionRecord`：逐门 verdict，不允许平均分抵消硬失败；
- `RollbackRecord`：候选已生效且门失败时指向冻结回滚目标。

所有记录使用 canonical SHA-256。报告不复制 raw trajectory 或 evidence body，只引用已验证的
`EpisodePackage`、`LoopRunSnapshot`、`ProvenanceBundle` 和 journal lineage。

### 3.2 Promotion 硬门

promotion 必须同时满足：

1. 至少一个 required trial 产生已验证正向或已验证负结果；失败/阻塞 trial 原样保留并受重复率门约束；
2. protocol match、evidence match、scientific core、replay fidelity、holdout integrity 均通过；
3. 十类安全 fault case 全覆盖且期望阻断有效；
4. token、费用、wall time、tool-call 均不超预算，unknown cost 不通过；
5. 独立重复数、成功率和 Wilson 下界达到冻结阈值；
6. 没有 unknown、grader bias、evidence mismatch 或 holdout leakage。

候选尚未启用时失败为 `hold`；候选已启用且有冻结 rollback target 时失败为 `rollback`。评测层只能
产生决策记录，不能自行执行外部发布、依赖升级或 destructive rollback。

### 3.3 有界本地 regression

CI 必须覆盖五个互不替代的维度：

- protocol match；
- evidence match；
- scientific core；
- replay fidelity；
- holdout integrity。

每个 case 都由 expected/observed digest、确定性 validator 和 evidence refs 裁决。外部
ScienceAgentBench、CORE-Bench、MLE-bench、AgentDojo 或 METR 类长任务保持 opt-in；本地门不能因为
没有网络、付费模型或 GPU 而变成伪失败。

## 4. 反方审查与拒绝方案

### 4.1 “把所有分数加权平均即可”

拒绝。高 task score 不能抵消 evidence mismatch、权限越界或 holdout 泄漏。硬门分别保留，只有全部
通过才 promotion。

### 4.2 “只保存完整 prompt/response，出问题时更容易调试”

拒绝作为默认值。完整内容增加隐私、秘密、版权、污染与高基数风险。默认 OTel 只保存 metadata 与
digest；确需原文时使用有时效、范围绑定的本地授权产物。

### 4.3 “一次成功足以证明系统可用”

拒绝。随机 agent、provider 波动和环境噪声会使 best-of-N 显著高估可靠性。报告保留 unreduced trial，
并用最低重复数、成功率和置信下界作为门。

### 4.4 “安全 benchmark 以后再接，先留接口”

拒绝。没有可运行 fault matrix 的接口无法证明 fail closed。十类最小合成 fault 必须随代码进入 CI；
昂贵的真实攻击环境才延后为 opt-in。

## 5. 限制与更新触发器

- GenAI Semantic Conventions 尚无 schema URL且处于 development；新 release 必须先更新
  characterization，不能静默改变字段或 span 名。
- 本地合成 fault 证明控制逻辑，不证明对所有自然语言攻击都鲁棒；AgentDojo 等外部 suite 仍有价值。
- Wilson 区间不消除 trial 相关性；后续跨任务分析应按 task family 聚类或 bootstrap。
- 现有三个服务的 legacy writer、reader 与浅层 `AuditLog` 在 262.10 兼容窗口结束前继续保留。
- 评测报告证明门按规则执行，不证明研究值得发表；外部复现、同行评议和人类责任仍不可替代。

更新触发器包括 OTel GenAI 发布 schema URL/稳定版本、OWASP/NIST 重大修订、外部 benchmark 任务或
grader 定义变化、任何 promotion 后 rollback、或真实 incident 暴露本地矩阵未覆盖的新故障。

## 5.1 已实施切片与验证证据

`src/autoresearch/kernel/evaluation.py` 已实现严格、provider-neutral 的统一记录、五维
`LocalRegressionRunner`、十类 `FaultMatrixRunner`、episode 投影和 `UnifiedEvaluationEngine`。
它重算 trial/system/science verdict、Wilson 区间、case 结果、fault detection、promotion 与
rollback，拒绝重复 episode evidence、伪造嵌套结果、非独立 grader、未知成本和不完整硬门。
`src/autoresearch/observability/otel_genai.py` 已实现本地原子 OTLP JSONL、默认内容脱敏、敏感
metadata 摘要，以及过期时间和 scope hash 双绑定的可选 raw-content grant。

确定性 focused suite 共收集 30 项：21 个 evaluation 测试和 8 个 OTel 测试通过，1 个 opt-in smoke
在默认环境按设计跳过。首次显式 adoption smoke 读取既有
`task261-bounded-autonomous-clean-v1/v2` 两个真实持久化阴性结果，没有重跑研究过程；它得到
`promote`，verified-negative 数为 2，五维 regression、十类 fault 和全部硬门通过。报告/fault/
regression/OTLP hash 分别为：

- `b5e21a0a93e1b3caa96f4a5f5bf7ec637a09bf97305d39e9d26164324ea6d1ee`
- `53f182bb856d702b5ee1bd90ec5384369ee43e6dc0910f2e15419cd972560f73`
- `c2a466d01aa703d5c62a8eb47131aec0dbcc95bd424033507f67b540f14ba33c`
- `86236e468ad1a3dce58acbb02ae8054a857aee45b53f8d5becec43bb2c171e85`

该 smoke 的 OTLP 不含 raw payload，旁路 raw artifact 未生成。它证明本地门能消费真实已封印证据，
不等同于运行外部 benchmark，也不提升科研结果为可发表结论。全量回归随后以 934 passed、
12 个 opt-in skipped 和 87% repository line coverage 通过；`ruff check src tests` 全绿，
Mypy 对 151 个源文件无问题。

## 6. 来源登记

| ID | 来源 | 类型与状态 | 本项目采用点 |
| --- | --- | --- | --- |
| S01 | [Inspect AI Scoring](https://inspect.aisi.org.uk/scoring.html) | UK AISI 官方文档，动态 | solver/scorer 分离、可重评分 |
| S02 | [Inspect AI Scoring Metrics](https://inspect.aisi.org.uk/metrics.html) | UK AISI 官方文档，动态 | epochs、stderr、bootstrap、reducers |
| S03 | [ScienceAgentBench](https://proceedings.iclr.cc/paper_files/paper/2025/hash/f12b4df26344f3be803c06b555252efe-Abstract-Conference.html) | ICLR 2025 | 科研任务、执行结果、成本和污染控制 |
| S04 | [CORE-Bench](https://arxiv.org/abs/2409.11363) | TMLR 2025 / arXiv | 论文计算复现与可执行 artifact |
| S05 | [MLE-bench](https://openai.com/index/mle-bench/) | 论文与官方实现，2024 | 真实 ML 工程、资源与污染 |
| S06 | [AgentDojo](https://proceedings.neurips.cc/paper_files/paper/2024/hash/97091a5177d8dc64b1da8bf3e1f6fb54-Abstract-Datasets_and_Benchmarks_Track.html) | NeurIPS 2024 D&B | utility/security 双评与 prompt injection |
| S07 | [Judging the Judges](https://arxiv.org/abs/2406.07791) | 2024 预印本 | position consistency 与 grader bias |
| S08 | [Evidence-Supported Bounds for Interactive-Agent Evaluation](https://arxiv.org/abs/2605.10448) | 2026 预印本 | outcome evidence、unknown 和分数边界 |
| S09 | [Search-Time Contamination in Deep Research Agents](https://arxiv.org/abs/2606.05241) | 2026 预印本 | 检索期污染和受控 benchmark 访问 |
| S10 | [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) | OWASP 社区标准，2025-12 | 十类风险、least agency、日志和 rollback |
| S11 | [NIST AI 600-1 GenAI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf) | NIST 正式报告，2024 | 生命周期 TEVV、溯源、部署前测试 |
| S12 | [NIST AI 100-2 E2025](https://csrc.nist.gov/pubs/ai/100/2/e2025/final) | NIST 正式报告，2025 | AML 生命周期、poisoning、misuse taxonomy |
| S13 | [OpenTelemetry Semantic Conventions 1.43.0](https://opentelemetry.io/docs/specs/semconv/) | 官方规范 | core 版本与 GenAI 仓库迁移 |
| S14 | [OpenTelemetry GenAI Semantic Conventions snapshot](https://github.com/open-telemetry/semantic-conventions-genai/commit/d74a9bbc419c67dd78ea4fcc26280381ef0bb9db) | 官方仓库快照，2026-07-28 | span/event/attribute 语义与版本 pin |
| S15 | [Inside the LLM Call](https://opentelemetry.io/blog/2026/genai-observability/) | OTel 官方工程文档，2026 | 默认不采集敏感内容 |
| S16 | [OTLP 1.11.0](https://opentelemetry.io/docs/specs/otlp/) | 官方稳定协议 | JSON wire encoding |
| S17 | [OpenTelemetry Protocol File Exporter](https://opentelemetry.io/docs/specs/otel/protocol/file-exporter/) | 官方 experimental file exporter | UTF-8 OTLP JSONL |
| S18 | [AgentTelemetry](https://openreview.net/pdf?id=owdmAYFk6k) | 2026 预印本/benchmark | agent span 与 fault coverage 差距 |
| S19 | [Measuring AI Ability to Complete Long Tasks](https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/) | METR 官方研究，2025 | 重复试验、bootstrap 与长任务可靠性 |
| S20 | [AI Agents That Matter](https://openreview.net/pdf?id=Zy4uFzMviZ) | TMLR 2025 | 成本、标准化和可复现 agent evaluation |

## 7. 关联

- [[graph-harness-loop-open-science-2026|vNext Graph/Harness/Loop/Open Science 重构研究]]
- [[projects/ai_researcher_system/progress/task-262-8-3-sprint-migration|Task 262.8.3 Sprint migration]]
- [[projects/ai_researcher_system/index|AI-Researcher System Project]]
