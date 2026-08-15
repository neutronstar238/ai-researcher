---
title: 可调记忆依赖与反局部循环策略候选
entry_type: strategy_candidate
project_id: ai_researcher_system
status: shadow_only
created_at: 2026-08-10T05:38:35+08:00
updated_at: 2026-08-10T11:11:00+08:00
promotion_authorized: false
production_enabled: false
scientific_result: false
innovation_verified: false
source_refs:
  - https://aclanthology.org/2026.acl-long.670/
  - https://arxiv.org/abs/2607.13591
  - https://aclanthology.org/2026.acl-long.27/
  - https://aclanthology.org/2026.acl-long.370/
  - https://aclanthology.org/2026.acl-long.900/
  - https://arxiv.org/abs/2605.12978
  - https://arxiv.org/abs/2607.12385
evidence_refs:
  - runs/manual-live/task2713-adaptive-benchmark-a4-behavior-pilot-v4/loop/snapshots/step-0012-8e05f684e813a53139b63eb5785ac5217a066a100c867a1d28942ee21ef39388.json
  - "[[projects/ai_researcher_system/knowledge/frontier/agent-memory-self-loop-frontier-2026-08-10]]"
  - runs/manual-live/task2713-adaptive-operator-steering-development-pilot-v9/loop/snapshots/step-0015-6e5ac3f96e714afe27c94af60b8e23903174d476d27234bacbc321b5141b992a.json
  - runs/manual-live/task2713-adaptive-operator-steering-development-pilot-v10/loop/snapshots/step-0015-bc97ab2441c446ae5da259e3fec08498880c683bfaa1d614ff40e0ed08c90752.json
  - runs/manual-live/task2713-adaptive-operator-steering-delayed-relevance-pilot-v12/adaptive-memory-loop-audit.json
---

# 可调记忆依赖与反局部循环策略候选

> [!warning] 只允许影子评估
> 本条目是由失败轨迹触发的策略候选，不是生产规则、科研结论或创新证明。它不得覆盖已经冻结的 Task 271.3 v3 四臂协议，也不得在线修改原始记忆、权限、证据、许可、实验或发表政策。
>
> 本候选只能读取上方精确绑定的终态快照或由可信导出器产生的去文本结构投影，不得读取整个 v4 运行目录。该目录含有 `protocol/runner-only/` 下的隐藏 oracle；将整个目录交给候选会破坏盲化并引入潜在泄题。

## 触发证据

真实 `qwen3.7-max` v4 pilot 从一次冻结目标/范围自主完成十二轮，十二次调用均一次通过，人工和编排器科研散文均为零。模型连续使用拆解与反方批判，最终主动申请晋级；系统又以来源不可追溯、无真实外部反馈正确拒绝。该轨迹证明功能性循环，却零次选择 Dreaming、零主权召回 selection、零结构化消费声明。

这说明当前缺口不是“有没有记忆模块”，而是**主 Agent 的策略是否知道何时降低短期反思惯性、何时提高长期原文依赖**。强制写死“第几轮必须 Dreaming”会把自主研究退化成测试专用流水线；完全不干预又可能形成局部算子循环。

## 候选机制

候选控制量不是“记忆开/关”，而是可审计的记忆依赖档位：

1. **低依赖发散**：新问题或跨学科探索时，只提供必要边界和少量可选历史，降低相似经验锚定；允许分支、类比、重构和放弃。
2. **平衡探索**：机械公开近期算子使用、外部反馈、新信息增量和长时记忆欠账；主 Agent仍从至少多个可达算子中自行选择。连续使用同一局部推理家族只产生非强制“多样性债务”，不能指定唯一下一步。
3. **高保真复核**：纠错、引用核验、复现和晋级前，提高精确原文、来源、冲突和时序约束；任何 Dreaming 摘要必须回到主权原始记录重放。
4. **污染回退**：出现来源冲突、权限不明或连续巩固漂移时，停用相关派生视图，回到原始平面重新推导；不删除原文。

主 Agent可以提出档位切换或工作流变异候选，但不能自行提升到生产。临时 Agent和学科方法仍由主 Agent按当前任务动态选择，Skill正文保持独立消息，不进入本体系统提示。

## 与现有工作的边界

- SteeM支持把记忆依赖当作连续可控维度，不支持本候选已经有效。
- MemCon支持上下文相关的记忆控制与轻量在线策略，但其报告收益不能直接迁移到本项目。
- 经验跟随研究提示相似历史会传播错误，因此“全量保存”不能推导为“每轮全量使用”。
- Mem2ActBench与Fine-Mem要求评价实际动作利用和结果归因，不能用召回命中或模型自报代替。

本项目可能的组合增量，是把可调依赖与不可变用户主权原文、来源权限不放大、可重建 Dreaming、逐请求消费谱系和预算匹配因果对照放进同一运行契约。各组件都有相邻工作，当前只能称为组合创新候选。

## 影子评估合同

先使用已经冻结的 v2—v4 负轨迹做离线诊断，再使用**全新开发场景**比较现有开放策略与本候选；不得重用或窥视 v3 隐藏 oracle，也不得修改 v3 arm。

必须预算匹配记录：

- 完成轮数与所有成功/失败模型调用；
- 可达算子数、算子家族熵、连续重复长度与主动停止质量；
- Dreaming 是否被选择、是否选中窗口外原始记录、是否进入后续真实请求、是否在终态结构化消费；
- 外部任务终点、陈旧依赖纠正、污染、虚假来源、成本和人工介入。

只有同时满足下列条件，才允许请求另起预注册：实际记忆消费增加；外部任务终点不下降并出现可重复改善；污染、虚假来源和权限放大不增加；模型/工具/临时 Agent总预算一致；改动不涉及安全、证据、许可和发表门。仅让 Dreaming 次数上升而没有终态使用或任务改善，应判为策略失败。

## 当前决定

`shadow_only`。不接生产默认，不修改冻结 benchmark，不启动 240-cell，不声称效果、创新或可发表性。

## 全新 development v6 观察

候选通过 `DevelopmentAdaptiveOperatorCatalogProvider` 接入全新的
`task2713-adaptive-operator-steering-development-pilot-v6`，没有回写冻结 v3 benchmark。控制器 15 轮
只发生 2 次结构性干预：暂时移除已饱和的局部内省动作，但仍按原顺序保留 10 个选项；Dreaming、
类比、分支、检索、临时 Agent、晋级、放弃和停止均未被指定为唯一动作。Qwen 随后自主选择跨域类比、
派出 3 个临时 Qwen、申请晋级、根据拒绝转向检索、在负检索后放弃旧分支并建立新分支。最终快照
`4871ac139be2775c69b066b78922cf47a975d7f7845b73896ed7d5cc5add3167` 因 30 次模型调用预算暂停。

该观察支持候选打破单一反思家族局部循环的**机制可行性**，但不是效果证明：没有无候选的同场景预算
匹配对照，外部终点没有改善证据，而且 Dreaming、窗口外召回与结构化消费仍全部为零。因此状态继续
保持 `shadow_only`，不得因算子更多样就提升生产。下一步若继续，只能把“算子家族多样性”和“实际
记忆消费”分成两个终点，在全新开发场景做预算匹配影子比较；仅增加 Dreaming 次数不构成成功。

## v9—v12 影子观察与策略更正

v9 与 v10 进一步证明本候选没有把系统改造成“按轮次调用记忆”的固定流水线。两条新鲜轨迹都运行十五轮、三十次模型调用，并由 Qwen 自主完成多种拓扑；v9 还由当前主 Agent 派出三个临时 Qwen，v10 主动检索一次。两条轨迹仍然零 Dreaming、零窗口外召回、零消费，因此策略不能因为算子更多样就被判成功。它们说明“反局部循环”和“长期记忆使用”是两个独立终点。

v9 同时发现一个危险的伪记忆机制：历史工作流提案中的“本轮/下一轮”会在未来消息里看起来像当前指令。生产 v3 现把每条保留提案投影为带 `authored_step_index`、`age_in_turns` 和相对时态边界的历史对象；旧文字不删除，但模型被明确告知它只是当时提案，必须结合最新反馈保留、修改、搁置或推翻。这不是摘要遗忘，而是把时间语义从散文中剥离成可重放结构。

v12 首次观察到一次非强制 Dreaming。结构 steering 只在两轮移除已经饱和的拆解/对抗动作，每次仍留下八个动作与多个家族，Dreaming 从未成为唯一继续动作。Qwen 在第 7 轮自行选择 Dreaming；其精确选择和反馈进入第 8 轮请求。然而这次召回只覆盖最近记录，终轮没有结构化消费声明，审计 `7286fb8fb748f99164b075c8037db77f79ad513e5970e0d046cca13f763b4498` 保持阴性。结论是：候选可能改变算子分布，但尚未证明提高“迟到原文的实际利用”。

v12 还使冻结 v3 delayed-relevance 设计失去确认性资格：第 3 轮公开刺激重述第 1 轮数值，并明确早期记录具有判别力；模型把该值写进跨窗口持久的分支假设后，无需回到 OB 原文即可在第 12 轮停止。后继协议必须另起版本，使用超过冻结工作状态容量的高熵早期面板和不重复数值的终轮键，并机械记录事实是否已被复制进持久状态。不得把“强制选择 agent-memory-evaluation Skill”或“第 N 轮强制 Dreaming”当修复，因为动态 Skill 合法地允许零选择，记忆动作也必须由主 Agent 根据任务自行决定。

## 更新后的提升条件

本候选继续为 `shadow_only`，且 v3 的 240-cell 不得启动。只有新的、在任何 live 结果前冻结的协议同时证明以下四件事，才允许请求生产提升：

1. 在工作状态预算相同的条件下，窗口外原始记录被确定性召回；
2. 召回反馈进入下一次真实、可验证的模型请求；
3. 后续原始动作给出精确绑定的结构化消费，而不是正文碰巧复述；
4. 盲化任务终点相对无主权记忆臂改善，且污染、成本和人工介入不升。

Useful Memories 的结果还要求 Dreaming 保持有门：连续巩固可能先改善后退化，原始 episodic 轨迹必须始终可用。PM-Bench 则说明没有单一 prospective-memory 策略对所有模型占优。因此生产策略的目标不是最大化 Dreaming 次数，而是学会何时不召回、何时回到原始层，并为错误巩固保留可逆路径。

## successor v1 对本策略的约束

后继记忆协议不会强制本候选提高 Dreaming 频率，也不会把普通工作记忆中的压缩视为作弊。A3 与 A4 都可在相同的 2048-byte 普通状态预算内自由压缩、编码、分支或停止；唯一预注册干预是 A4 可从主权原始层做可重放 Dreaming。只有 A4−A3 的盲化任务终点达到显著性和 0.25 SESOI，且每个 A4-only 胜例都有窗口外 raw→selection→signed request→结构化消费回执，才允许讨论本策略是否提高了迟到信息利用。

该协议目前只有 result-blind schema、哈希和测试，没有 13-turn 外部释放服务或真实 Qwen 结果，所以不会把本条目的 `shadow_only` 改为 development/production。后续正式 runner 也不得读取整个 successor bundle 或 runner-private root，只能逐轮接收已承诺的单个 public stimulus；否则隐藏 query、oracle 或 assignment 泄漏会使比较失效。
