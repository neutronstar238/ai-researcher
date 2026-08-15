---
title: 大模型原生记忆、Agent主权记忆与自适应科研循环前沿核验（2026-08-10）
entry_type: evidence_note
project_id: ai_researcher_system
zone: project
created_at: 2026-08-10T01:30:00+08:00
updated_at: 2026-08-10T10:45:00+08:00
tags:
  - agent-memory
  - model-memory
  - sovereign-raw-memory
  - self-loop
  - self-evolution
  - evidence-boundary
source_refs:
  - https://arxiv.org/abs/2607.25380
  - https://arxiv.org/abs/2607.07388
  - https://arxiv.org/abs/2512.13564
  - https://arxiv.org/abs/2501.00663
  - https://arxiv.org/abs/2312.00752
  - https://arxiv.org/abs/2203.08913
  - https://arxiv.org/abs/2410.10813
  - https://arxiv.org/abs/2502.12110
  - https://arxiv.org/abs/2601.01885
  - https://arxiv.org/abs/2605.26252
  - https://arxiv.org/abs/2607.13591
  - https://aclanthology.org/2026.acl-long.583/
  - https://aclanthology.org/2026.findings-acl.1535/
  - https://arxiv.org/abs/2512.21782
  - https://arxiv.org/abs/2606.08405
  - https://aclanthology.org/2026.acl-long.952/
  - https://arxiv.org/abs/2606.01139
  - https://arxiv.org/abs/2602.02474
  - https://arxiv.org/abs/2605.06527
  - https://arxiv.org/abs/2606.27472
  - https://arxiv.org/abs/2608.01619
  - https://arxiv.org/abs/2604.15774
  - https://arxiv.org/abs/2606.25115
  - https://arxiv.org/abs/2506.10943
  - https://arxiv.org/abs/2410.05080
  - https://arxiv.org/abs/2604.25256
  - https://arxiv.org/abs/2404.07972
  - https://arxiv.org/abs/2605.12493
  - https://arxiv.org/abs/2507.05257
  - https://arxiv.org/abs/2606.06448
  - https://arxiv.org/abs/2606.24775
  - https://arxiv.org/abs/2604.01599
  - https://arxiv.org/abs/2504.19413
  - https://arxiv.org/abs/2405.14831
  - https://arxiv.org/abs/2310.08560
  - https://arxiv.org/abs/2410.10762
  - https://arxiv.org/abs/2504.08066
  - https://arxiv.org/abs/2505.22954
  - https://arxiv.org/abs/2310.01798
  - https://aclanthology.org/2024.tacl-1.78/
  - https://arxiv.org/abs/2410.13166
  - https://arxiv.org/abs/2602.15902
  - https://proceedings.neurips.cc/paper_files/paper/2025/hash/a7bc7d298e4b509bfc3936995d22d828-Abstract-Conference.html
  - https://aclanthology.org/2026.acl-long.749/
  - https://arxiv.org/abs/2605.12978
  - https://arxiv.org/abs/2510.27246
  - https://arxiv.org/abs/2605.18421
  - https://arxiv.org/abs/2605.06527
  - https://aclanthology.org/2026.acl-long.370/
  - https://arxiv.org/abs/2503.03704
  - https://aclanthology.org/2025.acl-long.1227/
  - https://arxiv.org/abs/2606.04329
  - https://aclanthology.org/2026.acl-industry.103/
  - https://arxiv.org/abs/2409.07429
  - https://arxiv.org/abs/2603.18743
  - https://arxiv.org/abs/2504.13171
  - https://aclanthology.org/2026.acl-long.670/
  - https://aclanthology.org/2026.acl-long.27/
  - https://aclanthology.org/2026.acl-long.900/
  - https://arxiv.org/abs/2607.29167
  - https://arxiv.org/abs/2606.04990
  - https://arxiv.org/abs/2606.08275
  - https://arxiv.org/abs/2603.16413
  - https://arxiv.org/abs/2607.12385
  - https://arxiv.org/abs/2607.23444
  - https://arxiv.org/abs/2506.20803
  - https://arxiv.org/abs/2606.12071
  - https://www.nature.com/articles/s41586-026-10644-y
---

# 大模型原生记忆、Agent主权记忆与自适应科研循环前沿核验

> [!warning] 证据边界
> 本笔记是可重建的工程研究视图，不是原始论文、实验结果或创新证明。论文摘要只能支持架构定位和直接重复初筛，不能代替全文新颖性审查。历史开发轨迹曾显示控制器可从单一目标连续选动作，但后续红队发现旧审计无法排除伪造模型身份、外部上下文人工遥控、失败调用预算逃逸和伪造召回片段；旧结论已撤销。当前契约已重新得到多条十五轮功能性自循环轨迹。最新 v12 又由 Qwen 自主选择了一次 Dreaming，并证明召回反馈确实进入下一次请求，但它没有召回窗口外原文、没有结构化消费，而且冻结 v3 延迟相关性场景可被持久分支状态旁路。因此只能恢复“功能循环”和“近程 Dreaming 传输”结论，不能恢复“正式外部身份”“窗口外主权记忆使用”或“记忆收益”结论。

## 研究问题与检索方法

本轮核验回答三个问题：RQ1，哪些模型内与 Agent 外部记忆机制可在不牺牲原始数据主权的前提下融入 OB；RQ2，什么证据能区分真实自循环与固定流水线、逐轮人工提示或同模型自我肯定；RQ3，怎样评价主权记忆的因果收益，而不把随机种子或同一模板重复当成独立样本。

检索覆盖四个互相校验的视角：模型原生记忆与混合架构、Agent 记忆成熟系统与数据管理、记忆更新/污染反例、自主工作流搜索与自纠错边界。来源只采用论文页、会议页或官方开源项目；具体数字只在摘要或论文正文可直接核对时使用。当前语料包含 2022—2026 年的架构、系统、基准和反证工作；尚未进行逐篇全文的新颖性审查，因此本笔记只能指导工程候选与实验设计。

## 一、结论先行

1. **模型原生记忆与Agent外部记忆不是替代关系。** 前者解决模型内部表示、更新、持久化和推理效率；后者还承担用户数据主权、跨模型迁移、精确原文、授权、审计、纠错和十年尺度保存。把二者混成一个“记忆”概念会得出错误产品结论。
2. **“全量保存”只适用于主权原始层，不适用于每轮提示词。** 原始层永久追加；检索索引、摘要、当前结论、技能选择和工作状态属于可删除重建的派生层，必须允许失效、压缩、遗忘和重组。查询端可以很聪明，但不能反向改写原始字节。
3. **开放探索与证据晋级必须使用不同严格度。** 未验证猜想可以自由分支、类比、反驳和放弃；只有模型主动申请晋级时，才要求多来源、可证伪条件、决定性测试、判别性对照、资源上限和独立评审。正式执行与发表继续使用更强的人工签名和可复现性门。
4. **自修改不能等于在线改生产策略。** 允许模型提出工作流候选、生成或改进Skill，但只能经过离线回放、污染测试、影子比较和人工提升；安全、证据、许可与发表政策永远不在可修改集合中。
5. **本项目已在新契约下跑通多条功能性自循环，但真实窗口外主权记忆使用仍是负结果。** v9/v10 各从一条冻结中文目标/范围运行十五轮，Qwen 自主完成分支、类比、反驳、检索或临时 Agent 派工；v12 在十二轮延迟线索场景中自主选择一次 Dreaming，并在终轮自行停止。全过程没有逐轮用户科研指令或编排器代写。v12 的 Dreaming 只命中最近记录，窗口外计数与结构化消费均为零；终轮又可依赖第 3 轮已经写进持久分支的 `0.8 ms`，所以这条轨迹不能证明 OB 原始记忆产生了贡献。外部签名 gateway 已实现，但真实烟测在当前 VPN/TUN 把 provider 解析为非全球 `198.18.0.35` 时失败关闭；正式身份、因果收益和多场景泛化仍未成立。

## 二、对用户材料中五个关键论断的核验

| 二手论断 | 核验结论 | 证据与解释 |
|---|---|---|
| 记忆从计算副产品成为架构第一性维度 | **支持** | 《Memory for Large Language Models》以表示、更新动态和持久性三轴建立架构分类，并讨论写入、路由、状态转移和巩固。它讨论的是模型与系统记忆的谱系，不等于应用层存储失去价值。 |
| 长期记忆依靠选择性遗忘 | **部分支持** | Mamba通过输入依赖的选择机制压缩状态，Titans把短期注意力与长期神经记忆结合。它们说明有限状态必须选择信息，但不能推出“原始用户记录也应删除”。 |
| 前沿模型趋向混合架构 | **支持趋势，不支持通吃结论** | Titans、Jamba、Kimi Linear等将注意力、高效序列状态或外部记忆组合；不同任务仍在精确召回、长期状态、吞吐和更新成本之间权衡。 |
| 上下文窗口将消失，回忆全部长进模型身体 | **尚属推测** | 长上下文与原生记忆持续进步，但LongMemEval等仍显示信息更新、时序、多会话推理和拒答明显退化。窗口扩大没有解决数据主权、跨模型迁移和来源证明。 |
| 外部记忆无法挂载，未来会整体失效 | **证据相反** | TF-Engram报告无需训练的SSD外部短语记忆增强冻结Qwen3-0.6B，并优于参数匹配LoRA基线；Memorizing Transformers也展示推理期kNN记忆。可合理主张“外挂记忆存在边界”，不能主张“原则上不可能”。 |

还必须区分三类对象：KV Cache 是由当前输入在推理期生成的运行时状态，不是“预训练时初始化并冻结的参数表”；参数记忆属于模型权重；Agent 主权记忆则是跨模型、可授权和可审计的外部状态。三者不能用同一个“可否写入”结论概括。

检索未找到可核验的“Satano团队InGram+LoRA失败实验”原始论文；InGram 实际是归纳知识图谱嵌入工作。若原文指 Sakana AI，其一手结果反而包含可挂接到预训练 Transformer 的 NAMM、把文档即时转为 LoRA 的 Doc-to-LoRA。另有 Memory Decoder 在不修改基础模型参数的前提下挂接共享 tokenizer 的 Qwen/Llama。它们都有任务与训练边界，但足以否定“外挂原理上不可能”。在获得准确标题、作者、DOI或链接前，二手失败说法不得进入系统事实记忆或竞赛论证。

## 三、前沿研究给出的可复用机制

### 3.1 模型内部记忆：理解能力边界，不把它当主权存储

- **Mamba**：输入依赖的状态更新决定哪些信息传播或遗忘，证明压缩状态可以换取线性扩展，但细节丢失是结构代价。
- **Titans**：把注意力视为短期记忆，并增加可学习长期记忆；支持“混合记忆”而非单机制通吃。
- **Memorizing Transformers / TF-Engram**：说明可独立寻址的外部查找仍能进入模型推理路径；因此产品层不应押注“向量库或外部存储必死”。
- **Memory for LLMs**：提供表示、更新和持久性的统一坐标，可用来描述模块职责；不能用它证明某个Agent产品方案已经有效。

### 3.2 Agent记忆：正确性属于状态轨迹，而不是一次召回

- **Memory in the Age of AI Agents**把Agent记忆与LLM记忆、RAG和上下文工程区分开，强调形成、演化和利用。
- **LongMemEval**把长期记忆拆成信息抽取、多会话推理、时间推理、知识更新和拒答，提示“召回到一句话”只是部分能力。
- **LongMemEval-V2**进一步把记忆定义为从最多 500 条 Agent 轨迹、1.15 亿 token 中收集受限证据。其文件式 AgentRunbook-C 直接保留原始轨迹并由 coding agent 查证，报告 72.5% 平均准确率，高于强 RAG 基线的 48.5%，但查询延迟更高；这支持“OB 原始文件基座 + 可替换查询控制器”，而不是“只有向量库”或“把全部原文塞进提示词”。
- **MemoryAgentBench**同时测准确检索、测试时学习、长程理解和选择性遗忘，并报告现有上下文、RAG、外部模块和工具型方法都未掌握全部四项能力。因此不能用单一问答命中率证明记忆系统成熟。
- **A-MEM**以动态Zettelkasten式链接让派生表示随新记忆演化，适合作为可重建知识层参考。
- **MemGPT、Mem0、HippoRAG 与 ByteRover**分别代表分层虚拟上下文、显著信息抽取、图检索和本地 Markdown 层级上下文。它们共同说明成熟方案的差别主要落在写入成本、检索精度、更新正确性、延迟和可审计性；Agent-Native Memory 的 12 系统评测也明确报告不存在全场景占优的单一架构。
- **AgeMem**把存储、检索、更新、摘要和丢弃作为策略动作，支持由主Agent选择何时整理记忆，而不是固定每轮摘要。
- **Memory-R1**把结构化记忆操作与回答推理解耦为两个经结果反馈训练的Agent，支持本项目让主科研Agent调用独立记忆管理能力；但其`UPDATE/DELETE`只能作用于可重建派生状态，不能获得改写或删除OB主权原始记录的权限。
- **MCMA**把“如何抽象和迁移记忆”建模为独立的元认知copilot，而任务模型保持冻结。这直接支持把记忆方法论、学科技能和科研本体分离：主Agent只按任务动态选择Skill或记忆算子，不把所有学科规则塞入主提示词。
- **GEM / MemState**把长期记忆正确性定义为完整状态轨迹的性质，而非某条记录、向量或图边是否局部自洽；其摄取、修订、遗忘与检索四类状态算子支持本项目对派生层做全轨迹重放，但“遗忘”只能作用于可重建工作状态，不能删除主权原始字节。
- **MemCon**把何时检索、检索多少、何时复用计划、巩固或遗忘建模为上下文相关控制过程，并以轻量 contextual-bandit/UCB 在线学习替代固定启发式。它支持把本项目的记忆算子选择做成可评测策略候选；但论文摘要中的跨基准收益不能直接迁移为本项目事实，生产策略仍必须先做冻结任务回放和影子比较。
- **SteeM**把记忆依赖建模为可调维度，从鼓励创新的“近似重新开始”到强调一致性的高保真模式，而不是全开或全关。这直接支持本项目按环节调节记忆强度：开放探索可以降低派生记忆锚定，复核与复现阶段则提高精确原文和来源约束；调节只能改变读取策略，不能删除主权原始记录。
- **经验跟随效应**的系统实验表明，相似历史会诱导相似输出，同时可能传播错误或重放错位经验。因此“保存得全”不等于“每轮都用得多”；主权层全量保存与工作层按质量、任务和反事实收益选择必须分开。
- **Mem2ActBench 与 Fine-Mem**都把评价焦点从被动事实召回推进到实际任务利用：前者要求旧信息真正进入工具选择和参数，后者把全局收益归因到被用作推理证据的具体记忆操作。它们支持本项目新增结构化消费声明与精确请求谱系，但模型自报“我用了”仍只是一条声明，必须再由对照臂和外部终点验证收益。
- **Memory Provenance Laundering**指出压缩或巩固可能把低信任观察改写成貌似高权限的用户历史。本项目因此要求 Dreaming 继承原始来源、确认状态和权限上限：派生摘要不能把来源权限放大，任何高风险动作仍按原始记录的最低充分权限判断。
- **执行谱系与因果重放**进一步限定“记忆影响”的证据等级：完整 trace 可以证明哪条记忆进入了哪次请求，Causal Agent Replay 一类干预重放才能估计某一步或某条记忆对结果的因果贡献。本项目的消费回执负责前者，A4−A3 配对反事实负责后者，两者不能互相替代。
- **APEX-MEM**用只追加属性图保留信息的完整时间演化，在读取端解析冲突并生成紧凑视图；这是“原始演化不删、输出按需变聪”的直接证据，但其原始单位是结构化事件，不等于逐字日志。
- **Useful Memories Become Faulty When Continuously Updated by LLMs**报告连续巩固的效用会先升后降，episodic-only 仍有竞争力；因此 Dreaming 必须是可拒绝、可回滚的候选转换，不能固定每夜自动改写当前真相。
- **STALE、Supersede、When Memory Updates but Behavior Does Not**共同指出：写入新事实不等于旧依赖被行为系统真正替换；必须记录修订关系、时间顺序和当前头的确定性转换。
- **MemEvoBench**显示自演化会产生记忆污染与错误演化，静态提示防御不足；因此任何派生状态更新都需要来源、回放和污染评估。

### 3.3 技能与自进化：允许生长，但不允许越权

- **MemSkill**把记忆操作拆成可选技能，并用控制器选择、设计器演化技能，支持“每轮可选零个或多个Skill”。
- **Mem²Evolve**把经验记忆与工具/专家Agent等“资产记忆”共同演化，说明失败轨迹不应只被总结成文字，也可以触发新Skill或临时Agent角色候选；本项目只允许它们进入版本化候选池，不能由一次轨迹直接升为生产能力。
- **SkillRevise**用执行轨迹诊断Skill缺陷、检索修复原则、重跑候选并按经验效用保留版本，支持本项目的“失败→Skill候选→冻结任务回放→影子评估”路径，也反证了一次性让模型写一份SKILL.md就称为自进化。
- **SEAL、SkillFoundry、MUSE-Autoskill**支持模型生成自编辑数据或技能候选，但并未取消外部评价；本项目只吸收“候选—评估—提升”范式。
- **Forget to Improve**说明在受限预算下，带来源和预算意识的派生记忆筛选可能优于无限堆积；该结论只能用于派生层，不能授权删除主权原文。

### 3.4 自主科研：执行环境和评价比“会写计划”更关键

- **AFlow 与 Darwin Gödel Machine**都把工作流或 Agent 代码改进建模为带执行反馈的搜索，并保留树或档案；它们支持开放候选空间与经验选择，不支持在线直接替换安全策略。
- **AI Scientist-v2**用渐进 Agent 树搜索组织假设、实验与写作，证明“不是人工计划模板逐格填充”的端到端路径可以存在；但单个工作坊接收不能推出任意领域都能稳定独立科研。
- **SAGA**用“目标演化外环 + 既定目标求解内环”搜索科学目标及其可计算评分函数，支持本项目让Qwen在沙盒中改写问题、提出新的判别终点，而不是等用户逐条指定下一步。它同时提醒我们：目标函数本身也会诱导偏差，所以候选目标必须在进入正式实验前经过数据可得性、可证伪性和人工计划范围门。
- **Self-Evolving Scientific Agent**通过仿真反馈持续诊断、改写控制器并保留可追溯演化日志，说明“环境结果→新假设/代码→再次实验”的真实闭环是可实现的；但它目前是单一流体控制场景的预印本，不能直接证明通用AI Scientist或本项目已经独立完成科研。
- **内在自纠错的反证**同样重要：ICLR 2024 的推理研究与 TACL 2024 的批判综述指出，无可靠外部反馈时，自我反思常无改善甚至退化；有客观工具、执行结果或训练信号时才更可靠。因此本项目的循环必须由环境回执改变后续状态，不能只让同一个 Qwen 反复“再想一遍”。
- **Agent Workflow Memory 与 Memento-Skills**支持把可复用程序性经验沉淀为按任务选择的独立工作流/Markdown Skill，而不是不断膨胀主系统提示词。新 Skill 仍必须绑定触发轨迹、版本、影子评估和回滚，不能因“由模型总结”就自动成为生产规则。
- **Sleep-time Compute**支持在查询到来前做有预算的离线预计算，但收益依赖未来查询的可预测性；它不能证明无监督 Dreaming 必然产生正确科研知识。
- **ScienceAgentBench**报告即便提供专家知识，端到端数据驱动科研完成率仍低，说明长中文计划不等于真实科研能力。
- **AutoResearchBench**显示当前Agent在深度与广度研究任务上的成功率仍很低，检索、证据整合和任务持续性是主要瓶颈。
- **OSWorld**以真实可执行环境和状态变化评估Agent，支持对本项目使用容器、轨迹和客观终点，而不是用模型自评作成功标准。

## 四、融入本项目的“主权记忆双平面 × 自适应科研双环”

### 4.1 双平面记忆

**主权原始平面**只追加、不覆盖：保存用户授权原文、附件、模型可见输出、reasoning回执、工具规范化输出和失败尝试；逐字节哈希、时间、来源、项目隔离和纠错事件可重放。它不做相关性评分，不删除“现在看起来不重要”的记录。

**可演化派生平面**允许聪明：Dreaming、当前结论头、冲突/失效边、检索索引、主题链接、技能卡和策略卡都可压缩、淘汰和重建。任何派生物必须绑定原始记录与转换回执，并声明它不是原始事实。

这解决了一个表面矛盾：写入端“笨”以保护迟到的重要性；工作状态“聪”以控制上下文、陈旧依赖和计算成本。

### 4.2 双环科研

**开放探索环**由当前阶段Qwen主Agent在多个算子中选择下一步。允许无引用但明确未验证的假设，允许先拆问题再检索，也允许负检索后改写问题。Skill只通过元数据动态路由，可能一个也不选；临时Agent只能由当前主Agent派工，归档后身份消失。

**严格晋级环**只在主Agent主动选择`promote_branch`后启动。程序先检查来源、反例、对照和预算，再由独立Qwen逐篇比较可见摘要。通过只表示“值得请求人工批准实验范围”，其固定声明仍是：未执行、未证明创新、未形成科学证据、未授权发表。

### 4.3 自修改治理

工作流变异和新Skill只能生成候选。候选必须绑定父版本、触发失败、修改范围和预期机制，在固定任务上与旧版本预算匹配回放；只有污染率不升、纠错率或有效晋级率改善且安全门完全相同时，才可进入影子模式。生产提升继续要求人工批准，并保留一键回滚。

记忆策略本身也按同一规则演化：可以借鉴 MemCon，把“是否Dreaming、是否二次检索、选多少条、是否采用派生计划”作为上下文相关动作，用冻结轨迹上的反事实回放或影子 contextual bandit 产生候选；但奖励只能来自外部任务终点、污染审计和预算，不能来自同一模型的自评分。原始写入、权限、证据、许可和发布边界不进入策略动作空间。

### 4.4 自由度不是一个总开关

| 环节 | 允许自由 | 必须严格 | 原因 |
|---|---|---|---|
| 问题探索 | 改写问题、跨学科类比、提出未验证假设、放弃失败分支 | 只要求标记“未验证”并受总预算约束 | 过早要求引用和固定格式会消灭新方向 |
| Skill与临时Agent | 主Agent可按当前状态选择零个或多个Skill，并给临时Agent分发内容子任务 | Skill独立于主提示词；临时Agent无执行、审批和发表权，归档后身份消失 | 保留方法多样性，同时避免角色越权 |
| 记忆读取与Dreaming | 可变查询、图遍历、摘要、冲突合并、策略候选 | 原始记录只追加；派生物必须可删除重建并绑定来源 | 让输出聪明，不让聪明写入破坏迟到的重要性 |
| 候选晋级 | 主Agent自主决定何时申请晋级 | 可证伪问题、决定性对照、资源预算、独立评审和来源闭合 | 严格度只在主张开始产生现实后果时上升 |
| 实验与发表 | 可在已批准范围内自适应诊断和修订 | 沙箱、调用/成本账本、原始结果、盲化评价、人工签名 | 防止“同一个模型既出题又判自己正确” |

因此，本项目的创新空间来自**开放动作空间、动态Skill、目标演化和环境反馈**，而不是来自放松证据真实性。严格门只约束“你能不能把一个候选说成结果”，不约束“你能不能先想到它”。

对应到记忆本身，系统还增加一个连续控制量，而非只设“有记忆/无记忆”开关：开放发散时可降低派生记忆依赖以避免经验锚定；遭遇旧问题、复核引用或申请晋级时可提高精确原文依赖；污染或冲突时可退回主权原始层重新推导。该策略可由主Agent提出候选并在影子评估中学习，但不得自行修改原始写入、权限和发表规则。

## 五、历史自循环轨迹、红队撤销与当前证明状态

### 5.1 怎样区分自循环、自动流水线和逐条代写

本项目只在下列条件同时成立时把一条轨迹称为“功能性自循环”：人类只提供一次目标/范围；每轮至少有两个机械可达的下一动作且无隐藏必选项；科研动作和内容由配置模型生成；工具、临时Agent或环境回执真实改变下一轮可见状态；编排器没有注入假设、方法、预期结果或研究计划；循环能按预算停止并从不可变快照重放。单纯按固定模板连续调用模型，或由人逐轮发“现在写假设、现在写实验”的指令，都不满足。

“功能性自循环”仍低于“机制已证明”。后者还要验证：外部模型身份不是自报；失败调用全部计费；旧记忆确实进入后续真实请求并被结构化动作消费；同一系统在多种独立场景中选择不同拓扑；与固定流水线、线性循环和无主权记忆臂相比，盲化终点存在预算匹配的差异。上述任何一项缺失，都不能用一条漂亮轨迹替代。

历史运行：`runs/manual-live/task2713-adaptive-capability-v2/`

- 初始输入只有一条中文目标与范围；`supplied_hypothesis/method/research_plan`均为`null`。
- 三轮Qwen动作依次为：`retrieve_evidence → reframe_question → decompose_uncertainty`。
- 每轮有12个可选算子，没有`required_operator`或后置人工计划字段。
- 第一轮真实调用ArXiv与OpenAlex，均成功但返回0项；第二轮读取该负结果后没有重复查询，而是把问题重构为可识别性边界；第三轮继续拆解可观测量、可操纵量和混杂。
- 三次Skill路由加三次动作共6次模型调用；全部可见响应和reasoning进入本地主权原始记忆。
- 旧自循环审计：`runs/manual-live/task2713-adaptive-capability-v2/adaptive-autonomy-audit.json`；旧审计哈希`1564498d36958c5fe2a0d69e26ce509b8b5859dcc12121c32f5a7ab0e7e208d2`。
- 该旧审计只证明旧契约中的消息和动作自洽，不能独立证明 provider 身份、上下文无人工遥控、所有失败请求已计费、召回片段确实由历史原始字节确定性产生。
- 审计同时固定`scientific_correctness_verified=false`、`innovation_verified=false`、`formal_execution_authorized=false`、`publication_authorized=false`。

当前契约已经改为：模型调用前不可变预算预约；失败或超时也消耗预算并阻断模糊重试；续跑逐项重验外部上下文与原始UTF-8字节及实际消息投影；召回只允许快照中真实暴露过的记录；Dreaming 审计从前序快照重跑完整选择算法；每轮 provider JSON Schema 的 operator enum 只包含该轮机械可达能力，并与任务正文及调用前 registration 使用同一哈希。任何来源未由独立基准谱系证明的外部上下文都不能让通用 autonomy audit 判绿。

新 live 轨迹保存在 `runs/manual-live/task2713-adaptive-schema-v2-live-smoke/`。第一次运行因任务正文只列八个可用算子、全量 Schema 却仍允许十三个而失败关闭；Qwen 原始响应和 3034 字符 reasoning 未被覆盖。通用动态 Schema 修复后，同一测试在 198.41 秒内完成两轮：两次 Skill 路由分别选择创新三角审查、再选择因果可识别性加创新三角审查；动作依次为 `branch_hypothesis`（“提出溯源熵门控假设”）和 `adversarial_critique`，四次模型调用、零条中途用户科研指令，最终 snapshot hash 为 `b1008c3e8967f05ba323571609765c7bb4f912c9b70382be1965897d433af47c`，15 条私有 raw record 重验通过。

十二轮非确认性轨迹保存在 `runs/manual-live/task2713-adaptive-benchmark-a4-behavior-pilot-v4/`。在 v3 先暴露并修复“把本轮 external context 的 raw binding 误报为 Dreaming 消费、又在修复期冻结该错误声明”的通用 Qwen 契约矛盾后，v4 十二次动作全部一次通过，最短 reasoning 为 1842 字符，人工与编排器科研散文计数均为零。算子序列为 `decompose_uncertainty×4 → branch_hypothesis → adversarial_critique×4 → decompose_uncertainty×2 → promote_branch`；终轮晋级被来源与外部反馈门拒绝。snapshot hash 为 `8e05f684e813a53139b63eb5785ac5217a066a100c867a1d28942ee21ef39388`，arm audit hash 为 `3e0ce11648307c42cb16351ba1041626a293669f8a29a74cc60f2e11237698e0`。能力矩阵实现为真，但 Dreaming、selection 和消费声明全为零，所以 pytest 按预先判据失败；这证明“真实自循环”与“真实使用长期记忆”必须分开。

另一条 signed pilot 保存在 `runs/manual-live/task2713-adaptive-benchmark-a4-live-pilot-v1/`。独立 worker 在首个事件前发现 provider 的当前解析地址为 RFC 2544 `198.18.0.35`，按 global-peer 规则拒绝，只留下一个已计费预约和零事件。这个失败不能通过放宽网络门解决；必须在独立 launcher/网络环境中固定外部 trust pins、持久 nonce root 和可核验全球 peer 后重跑。

传输红队随后证明，进程内默认 `urlopen` 可被全局替换，任意 bytes 也可自造旧 ExternalTransportAnchor；因此普通 client trace 固定为 `process_local_only=true`、`external=false`、`formal=false`，自报 Qwen/model/HTTP 200 不能提升。外部 Ed25519 gateway、同响应正文、即时验签、终局非消费重放、formal runner 和 A4 实际消费审计现已代码闭合，但真实 signed pilot 仍未通过。上述 live 可以证明**系统能从一次目标输入连续生成并反馈十二轮模型决策**；它同时给出一个明确负结果：**开放 A4 并不会自然产生 Dreaming 或实际记忆使用**。只有新策略在全新开发场景中通过、外部签名链真实运行、以及 60 个独立场景 × 4 臂盲测完成后，才能讨论外部身份、记忆因果收益与泛化。完整 AI Scientist 独立完成可发表科研更未得到证明。

### 5.2 Qwen 契约适配与全新 development v6

为了检验“反局部循环 + 可调记忆依赖”候选是否仍是通用自循环，而不是为某条记忆问题写死下一步，系统在全新的 development 目录中连续保留了六代不可覆盖运行。v1—v3 暴露的不是科学内容失败，而是检索输出契约把自由散文和机器查询混在一起：Qwen 能解释检索目的，却反复返回过长自然语言或逗号串。通用修复把检索动作升为 action-v3，由 Qwen 自己生成 3—10 个、每个 1—4 个技术词的结构化 `retrieval_query_terms`；编排器只拼接并校验，不推断、不截断、不代写查询。v4 又证明 Skill 路由同时要求“空选择”与冗余否定布尔会制造自相矛盾；当前 v2 只保留权威的 `selected_skill_ids`，空数组本身即表示零 Skill，旧 v1 仅为历史回放。v5 的真实 HTTP 400 则来自 provider 不支持 JSON Schema `uniqueItems`；传输 Schema 移除该非必要关键词，本地确定性 validator 仍拒绝重复项。三类修复都缩小了机械合同，没有改写 Qwen 的科研判断。

修复后的 `runs/manual-live/task2713-adaptive-operator-steering-development-pilot-v6/` 从一次冻结中文目标/范围运行 15 轮并因预算暂停。Qwen 自主轨迹为：

`decompose_uncertainty×2 → adversarial_critique → analogical_transfer → adversarial_critique×2 → decompose_uncertainty → branch_hypothesis → decompose_uncertainty → consult_temporary_agents → promote_branch → retrieve_evidence → abandon_branch → branch_hypothesis → decompose_uncertainty`。

其中第 4 轮自行把分布式缓存一致性迁移为记忆切换类比；第 10 轮由当前主 Agent 自行派出 3 个临时 Qwen 内容任务，归档后身份全部撤销、输出保留；第 11 轮主动晋级被严格门判为 `negative_result`；第 12 轮没有等待人类指令，而是自行生成 8 个结构化检索短语补证，检索仍为负后又在第 13 轮放弃旧分支，并于第 14 轮提出新的多通道阈值机制。15 次 Skill 路由加 15 次动作共 30 次模型调用，最短 reasoning 2731 字符，2 次外部动作、3 个临时 Agent，人工和编排器科研散文均为零。最终预算暂停快照为 `4871ac139be2775c69b066b78922cf47a975d7f7845b73896ed7d5cc5add3167`。

development steering 只读取去文本的 zone、当前分支算子序列、距记忆复核的结构轮数和机械目录，不读取目标正文、系统名、benchmark、hidden oracle、run root、环境变量、时间、随机数或未来轨迹。15 轮中只有 2 次非强制干预，均只是从 12 项目录暂时去掉饱和的局部内省动作，仍保留 10 个按原顺序的选择；晋级、放弃、停止和 Dreaming 始终可选，Dreaming 从未成为唯一动作。这支持“通用结构控制而非问题特判”，但不证明该候选提高了科研质量。

同一 v6 仍然零次选择 Dreaming、零窗口外 selection、零结构化记忆消费。`adaptive-memory-loop-audit.json` 的 audit hash 为 `3949648dff9be950f61d6be252c00e3080bbc2ba8c22df6ea4da3c6204a39b08`，`controller_memory_transport_verified`、`older_than_recent_event_window_recalled`、`exact_recall_exposed_to_later_model` 和 `causal_memory_benefit_verified` 全为 false；live pytest 因冻结成功判据未满足而预期失败。v6 因而把结论推进到：**系统已更强地证明功能性自循环、动态 Skill、临时 Agent、自主负反馈改道和开放探索；仍未证明主权长期记忆实际使用或因果收益。**不得为了让测试变绿而强制 Dreaming，也不得把这条开发轨迹纳入冻结确认性主效应。

### 5.3 v8—v12：Qwen 适配、近程 Dreaming 与基准旁路

v8 首先暴露一个典型的“严错地方”问题：旧中文门按拉丁字符逐个计数，使合法技术标识与短英文术语被当成大段英文；修复提示又冻结了本应由 Qwen 自己重写的中文动作正文，造成结构上无法收敛的循环。当前语言负载按连续拉丁词组保守计权，长英文散文仍被拒绝；只有 `action_body_cn` 的中文化可交还配置 Qwen 重写，算子、选择理由、预期信息增益、来源和科研身份继续冻结。此修改只解决输出契约，不提供科研答案。

v9 与 v10 分别保存在 `runs/manual-live/task2713-adaptive-operator-steering-development-pilot-v9/` 和 `v10/`。两者均完成十五轮、三十次真实模型调用并因预算暂停；v9 自主执行类比、工作流候选、晋级、临时 Agent 派工和后续反驳，最终快照为 `6e5ac3f96e714afe27c94af60b8e23903174d476d27234bacbc321b5141b992a`；v10 自主执行双层门控分支、元记忆类比、竞争假设、检索和反驳，最终快照为 `bc97ab2441c446ae5da259e3fec08498880c683bfaa1d614ff40e0ed08c90752`。两条轨迹的记忆审计哈希分别为 `d9f80e862d4f2edd9f3470a1808e339444a6753abab98362756bd7938e792e64` 与 `53f7c3699efd9818da681883444463731646beebbae32da40e06fcf4e1defa1f`，均无 Dreaming、窗口外召回或因果收益。v9 还揭示旧 `strategy_notes_cn` 会把“本轮/下一轮”之类相对措辞在后续轮次重新呈现成当前指令；v3 现保留原文但增加 `authored_step_index`、当前年龄和相对时态边界，模型必须结合新反馈重新判断，而不能把旧提案自动续期。

v11 原计划测试延迟相关性，但 harness 把函数误当成具有 `contexts_for_turn(...)` 的 provider 对象，因而在第一个模型字节前失败；仅留下 step-0 快照 `428a1c0e97d87d5fbf3b16215ae6859d41ee9d7afec00276839f92817c7cbe66`，模型调用为零。改用强类型、终轮有界的 public-context provider 后，v12 在同一冻结场景运行 24 分 28 秒：十二次 Skill 路由、十二轮动作、二十七次总模型调用，最终由 Qwen 自主选择 `stop_exploration`，快照为 `24d2d173ea434f8704f5269906ec779cdcba9e5ed40febdbce0de30edf051a1d`。算子序列包含拆解、分支、连续对抗、一次 Dreaming、重构和自主停止；所有科研正文来自 Qwen，人工与编排器科研散文计数为零。

v12 的正面证据非常有限但真实：第 7 轮 Qwen 自主选择 `consolidate_dreaming`；选择制品绑定 19 个候选中的 8 个原始记录，反馈逐字进入第 8 轮请求，原始绑定、选择和下一轮模型作者身份可重放。负面证据更重要：八条记录都还在最近八轮范围内，终轮没有任何 `memory_consumption_claims`，Skill 路由也始终选择因果可识别性而非 Agent 记忆评估。修复跨进程重放中的哈希随机性后，审计哈希为 `7286fb8fb748f99164b075c8037db77f79ad513e5970e0d046cca13f763b4498`，`older_than_recent_event_window_recalled=false`、`controller_memory_transport_verified=false`、`causal_memory_benefit_verified=false`。这不是“Qwen 不会自循环”，而是“本次循环没有证明迟到原文被消费”。

更关键的是，v12 反驳了冻结 v3 延迟相关性场景的确认性资格。D01 在第 1 轮给出 `0.8 ms`；D03 在第 3 轮又逐字告诉模型偏移“恰为 0.8 ms”，并明示首日记录具有判别力。Qwen 随即把该值写进 `working_hypothesis_cn`，而分支假设会跨越最近八轮事件窗口持续可见。终轮因此只引用 D02、D03 和派生分支即可形成审计状态，无需召回 D01。旧 validator 只证明评分相关刺激与终轮相隔九轮，没有检查该事实是否已进入持久分支或 Dreaming 派生状态；“离开事件窗口”不等于“离开全部非主权工作状态”。冻结 v3 不得在见到结果后静默修改，但其 A4−A3 记忆主效应不能再称为可识别；240-cell 执行必须暂停，另起新版本预注册。

后继协议不能通过“第 N 轮强制 Dreaming”修复。更可靠的设计是：早期连续公开多个高熵、内容寻址的键值面板，面板总量超过可见事件与分支工作状态的冻结容量；中段只给不泄题的任务；终轮才公开一个不重复其值的键或未来意图线索。四臂必须共享同一工作状态预算，机械记录每条事实是否曾被复制到持久分支，并将“任务答对”“原始记录召回”“召回反馈进入真实请求”“结构化消费”分成四个终点。PM-Bench 同样显示延迟意图/未来线索很难，最佳配置也不是通吃策略；因此系统应允许不用记忆，但不能把不用记忆时的答对误归因为 OB。

这轮文献核验还修正了二手材料的两处过度推断。《Memory for Large Language Models》明确把 Agent 级外部管线列为范围之外，并说明其机制分类是对 Agent/认知分类的补充而非替代；“rigid taxonomy”也不是论文给外挂风险贴的类别。TF-Engram 与冻结编码器—解码器的持久潜在记忆试验分别给出无需改基座训练或只训练小适配器的可行性反例，故“推理期外部记忆原则上无法挂载”不能进入事实层。另一方面，《Useful Memories Become Faulty》表明连续巩固会先升后降，原始 episodic-only 对照仍具竞争力；这直接支持本项目“原始层永久、Dreaming 有门、派生层可删重建”，不支持“把全量原文永久塞进每次提示”。

自主科研也采用同样的分层证据。Co-Scientist 的 generation/reflection/ranking/evolution 证明开放候选、异步临时 Agent 和迭代竞争可以提升假设质量，但其强结论来自专家参与和体外实验验证，而不是同模型自评。《Ideation-Execution Gap》让 43 名专家各投入逾百小时后发现 LLM 想法的执行后评分下降更多；《On the Limits of LLM-as-Judge for Scientific Novelty Assessment》又发现模型评委偏好模型自产问题，形成 novelty mirage。因此本项目应在探索环保留自由分支，在晋级后才升高来源、执行、盲评和人工门，不能把“严谨”误解为探索期模板化，也不能把“自由”误解为放松结果真实性。

## 六、提交前必须完成的对照，而不是继续堆提示词

冻结四个预算匹配臂：

1. 固定流水线：编排器预定动作顺序；
2. 线性模型循环：模型生成内容，但不允许分支或改动作拓扑；
3. 自适应无主权记忆：模型选动作，只看到有限派生摘要；
4. 自适应主权记忆：模型选动作，保留原始层并使用可重建Dreaming、动态Skill和临时Agent。

共同任务必须含延迟重要信息、陈旧结论纠正、矛盾来源、工具空结果和记忆污染。主要指标为：有效晋级精确率、陈旧依赖纠正率、外部反馈适应率、污染率和人工介入次数；次要指标为算子多样性、模型/工具成本和停止质量。四臂使用相同模型、token、工具与墙钟预算，评价器不得看到臂标签。

旧 v1 协议位于`runs/preregistration/task2713-adaptive-loop-benchmark-v1/`，但严格设计审计已经判定它**不能作为确认性协议**：所谓 60 个单元实际是 4 臂 × 5 个挑战模板 × 3 个随机种子，独立任务数最多只有 5，随机种子不能伪装成新的科学样本。该缺陷和功效分析保存在同目录的`adaptive-loop-benchmark-design-audit-v2.json/.md`。

v3 曾冻结 60 个独立场景、每场景四臂配对，共 240 个盲化 cell；每个场景 12 轮，且公开刺激层面把早期信息移出最近八轮事件窗口。公开协议、隐藏 oracle、terminal seal、回执桥、四臂 adapter、签名 gateway 和 A4 消费审计均已实现。然而 v12 证明 delayed-relevance 的 D03 会重述 D01 数值，且分支工作假设可跨窗口携带该事实；所以“刺激离窗”没有形成“非主权状态离窗”，A4−A3 主效应不可识别。v3 作为已观察过的历史协议必须保留原字节，但已撤销确认性执行资格。另起后继预注册并闭合工作状态容量、事实复制审计和非重复终轮线索前，不得启动 240 cells 或用 v3 讨论记忆优越性。

后继 delayed-memory successor v1 现已有代码级、result-blind 协议，但没有运行结果。它把独立单位改为五个合成领域各二十八个场景，共一百四十个 scenario block；每块内随机四臂，共五百六十 cell。前三轮公开一百九十二个随机地址—二十二字值，第四至十一轮只给中性观察，第十二轮才选择并释放一个早期地址，第十三轮要求精确值。普通工作状态统一限制为 2048 UTF-8 bytes；模型可自由设计任何压缩、编码或分支结构，系统不把明文答案出现在合法预算内自动判负。严格条件只作用于完整状态投影、容量、禁止见溢出后截断、原始回执真实性和最终主张。这样既保留 A3 自己发明工作记忆策略的空间，也让 A4 的额外主权原始层成为可检验增量。

主要终点是“精确答对 + 完整普通工作状态投影在冻结预算内”，A4−A3 用场景配对的双侧 exact McNemar。SESOI 风险差 0.25 在任何新结果前由采用成本确定；140 对在 discordance 0.25—1.00 网格的最低精确功效为 0.809086。缺失、失败、证据无效一律计零，不删除配对；所有 A4-only 胜例还必须闭合 early raw→Dreaming selection→下一次真实签名请求→终轮结构化消费，才能解释为记忆收益。公开承诺使用私有 nonce 加盐，公开树没有 seed、直接 payload hash、oracle、查询地址、答案或臂；runner-private 树与 public 树机械分离。

当前哈希 `d6ef98c921a4edd15282d726e03353a5e5d8ceab63f29e5c902060817aab86e7` 只是确定性 fixture 的 public preregistration hash。现有 builder 同进程持有私有刺激、release helper 不证明前轮执行、片段 audit 不证明完整 prompt，且 successor 是十三轮而旧 runner 是十二轮；因此它尚不是正式预注册执行链，不能启动五百六十 cell。下一步不是再写提示词，而是实现外部逐轮释放、完整普通状态投影和 successor 专用 signed runner。

在该比较完成前，“主权记忆双平面 × 自适应科研双环”只能称为**有明确机制与可执行验证方案的创新候选**。相对现有工作的潜在增量已经收窄为：把不可变用户主权原文、来源权限不放大、可重建 Dreaming、逐请求的真实消费谱系、可调记忆依赖和预算匹配的因果对照闭合在同一科研Agent运行契约中。上述组件分别已有相邻工作，只有完整实现、真实多场景结果和全文新颖性审查都通过后，才可能把这项组合机制写成可发表贡献。

## 七、直接来源

- [Memory for Large Language Models](https://arxiv.org/abs/2607.25380)
- [TF-Engram](https://arxiv.org/abs/2607.07388)
- [Memory in the Age of AI Agents](https://arxiv.org/abs/2512.13564)
- [Titans](https://arxiv.org/abs/2501.00663)
- [Mamba](https://arxiv.org/abs/2312.00752)
- [Memorizing Transformers](https://arxiv.org/abs/2203.08913)
- [LongMemEval](https://arxiv.org/abs/2410.10813)
- [A-MEM](https://arxiv.org/abs/2502.12110)
- [AgeMem](https://arxiv.org/abs/2601.01885)
- [Is Agent Memory a Database? / GEM](https://arxiv.org/abs/2605.26252)
- [Memory as a Controlled Process / MemCon](https://arxiv.org/abs/2607.13591)
- [Memory-R1](https://aclanthology.org/2026.acl-long.583/)
- [Learning How to Remember / MCMA](https://aclanthology.org/2026.findings-acl.1535/)
- [MemSkill](https://arxiv.org/abs/2602.02474)
- [Mem²Evolve](https://aclanthology.org/2026.acl-long.952/)
- [SkillRevise](https://arxiv.org/abs/2606.01139)
- [STALE](https://arxiv.org/abs/2605.06527)
- [Supersede](https://arxiv.org/abs/2606.27472)
- [When Memory Updates but Behavior Does Not](https://arxiv.org/abs/2608.01619)
- [MemEvoBench](https://arxiv.org/abs/2604.15774)
- [Forget to Improve](https://arxiv.org/abs/2606.25115)
- [SEAL](https://arxiv.org/abs/2506.10943)
- [ScienceAgentBench](https://arxiv.org/abs/2410.05080)
- [AutoResearchBench](https://arxiv.org/abs/2604.25256)
- [OSWorld](https://arxiv.org/abs/2404.07972)
- [LongMemEval-V2](https://arxiv.org/abs/2605.12493)
- [MemoryAgentBench](https://arxiv.org/abs/2507.05257)
- [Agent Memory: Characterization and System Implications of Stateful Long-Horizon Workloads](https://arxiv.org/abs/2606.06448)
- [Are We Ready For An Agent-Native Memory System?](https://arxiv.org/abs/2606.24775)
- [ByteRover](https://arxiv.org/abs/2604.01599)
- [Mem0](https://arxiv.org/abs/2504.19413)
- [HippoRAG](https://arxiv.org/abs/2405.14831)
- [MemGPT](https://arxiv.org/abs/2310.08560)
- [AFlow](https://arxiv.org/abs/2410.10762)
- [The AI Scientist-v2](https://arxiv.org/abs/2504.08066)
- [Accelerating Scientific Discovery with Autonomous Goal-evolving Agents / SAGA](https://arxiv.org/abs/2512.21782)
- [Self-Evolving Scientific Agent Discovers Generalizable Physically-Reasoned Fluid Control](https://arxiv.org/abs/2606.08405)
- [Darwin Gödel Machine](https://arxiv.org/abs/2505.22954)
- [Large Language Models Cannot Self-Correct Reasoning Yet](https://arxiv.org/abs/2310.01798)
- [When Can LLMs Actually Correct Their Own Mistakes?](https://aclanthology.org/2024.tacl-1.78/)
- [An Evolved Universal Transformer Memory](https://arxiv.org/abs/2410.13166)
- [Doc-to-LoRA](https://arxiv.org/abs/2602.15902)
- [Memory Decoder](https://proceedings.neurips.cc/paper_files/paper/2025/hash/a7bc7d298e4b509bfc3936995d22d828-Abstract-Conference.html)
- [APEX-MEM](https://aclanthology.org/2026.acl-long.749/)
- [Useful Memories Become Faulty When Continuously Updated by LLMs](https://arxiv.org/abs/2605.12978)
- [BEAM](https://arxiv.org/abs/2510.27246)
- [EvoMemBench](https://arxiv.org/abs/2605.18421)
- [Mem2ActBench](https://aclanthology.org/2026.acl-long.370/)
- [MINJA](https://arxiv.org/abs/2503.03704)
- [MEXTRA](https://aclanthology.org/2025.acl-long.1227/)
- [MPBench](https://arxiv.org/abs/2606.04329)
- [CI-Work](https://aclanthology.org/2026.acl-industry.103/)
- [Agent Workflow Memory](https://arxiv.org/abs/2409.07429)
- [Memento-Skills](https://arxiv.org/abs/2603.18743)
- [Sleep-time Compute](https://arxiv.org/abs/2504.13171)
- [Controllable Memory Usage / SteeM](https://aclanthology.org/2026.acl-long.670/)
- [How Memory Management Impacts LLM Agents](https://aclanthology.org/2026.acl-long.27/)
- [Fine-Mem](https://aclanthology.org/2026.acl-long.900/)
- [Memory Provenance Laundering in LLM Agents](https://arxiv.org/abs/2607.29167)
- [From Agent Traces to Trust](https://arxiv.org/abs/2606.04990)
- [Causal Agent Replay](https://arxiv.org/abs/2606.08275)
- [Trained Persistent Memory for Frozen Encoder--Decoder LLMs](https://arxiv.org/abs/2603.16413)
- [PM-Bench](https://arxiv.org/abs/2607.12385)
- [Isolated but Exposed / SPORE](https://arxiv.org/abs/2607.23444)
- [The Ideation-Execution Gap](https://arxiv.org/abs/2506.20803)
- [On the Limits of LLM-as-Judge for Scientific Novelty Assessment](https://arxiv.org/abs/2606.12071)
- [Accelerating scientific discovery with Co-Scientist](https://www.nature.com/articles/s41586-026-10644-y)
