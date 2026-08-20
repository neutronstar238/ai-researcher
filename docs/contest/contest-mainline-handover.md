# 榜题主线交接文档（开发报告）

> 生成日期：2026-08-16
> 适用榜题：方向 A-1「科学实验任务规划与反馈迭代」——《Science》125 问第 1 题（素数为何如此特别？）
> 主线定义版本：v2（本次修正：预实验为必做硬步骤，链 2 CLI 已舍弃并由新主线编排取代）

---

## 1. 主线定义（v2，本次修正后）

**主链 = 一条命令：输入题目 → 中文研究计划 → 真实预实验（必做）→ 反馈修订 → 最终 PDF。**

```text
题目 PDF（sjtu-booklet.pdf，Science 125 第 1 题）
  → 首题确定性提取（绑定页码/SHA-256）
  → Skill 目录扫描（只取 name/description/content_sha256 元数据）
  → Qwen 元数据路由（只返回 Skill ID，不读正文）
  → 3 个不记名临时子 Agent 并行（可证伪假设 / 方法桥接+最小预实验 / 反方挑战）
  → 独立评审 Agent 从候选中选定/综合研究目标
  → 主 Qwen 一次生成中文研究计划
  → 真实素数间隙预实验（固定区间、四零模型对照、199 次重采样；不可跳过）
  → 主 Qwen 读取已核验预实验结果修订计划一次（数字守卫：正文不得出现证据外数字）
  → 确定性渲染最终 JSON / Markdown / TeX / PDF（≤20 页检查 + pdftotext 文本核验）
```

**主链入口（v2 新增）**：`src/autoresearch/competition/contest_mainline_cli.py`
`run_contest_mainline_delivery` 一条命令跑完整主线；`--plan-source-dir` /
`--preexperiment-source-dir` 支持复用已完成阶段（仍全量验证哈希）重跑修订与渲染，
用于修订被数字守卫拒绝后的自迭代，无需重跑全链。

**已舍弃**：链 2 CLI（`contest_prime_feedback_cli`）不再作为主线；其底层组件
（预实验 runner、修订器、证据嵌入、渲染器）由新主线编排直接复用。

**保留但标注「开发中」：自主搜索灵感线（`contest_direction_research_loop_cli`，12 阶段方向循环）。**
该线仍在迭代（fresh-v2…v10 连续失败关闭，最新阻塞见 `Problem.md` `P-20260815-021`），
不作为当前交付依赖。在技术方案中需如实说明该线处于开发状态。

---

## 2. 主线当前代码已验证（2026-08-16 新目录隔离复现）

**链 1（题目→计划，已跑通）**：输出目录 `runs/contest-delivery/mainline-verify-20260816-plan/`：

| 检查项 | 结果 |
|---|---|
| 总状态 | `completed` |
| 模型调用 | 6 次（skill 路由 1 + 临时 Agent 3 + 目标评审 1 + 计划生成 1） |
| 选中 Skill | `prime-structure-computational-number-theory`（路由哈希与历史交付一致） |
| 目标阶段 | `degraded`（3 个临时 Agent 中 2 个成功，1 个失败但降级继续，身份全部归档移除） |
| 渲染产物 | `plan/research-plan.{json,md,tex,pdf}` + manifest，5 页，`pdf_text_verified=true` |
| 合规标记 | `formal_experiment_executed=false`、`paper_claimed=false` |

**完整主线（题目→计划→预实验→修订→PDF）**：`runs/contest-delivery/mainline-live-20260816-r2/`
（首次 r1 在修订阶段被数字守卫正确拒绝——模型引入验证输入中不存在的 2310；
新增数字边界修订要求后 r2 复用 r1 的 01-plan/02-preexperiment 重跑修订与渲染）。

**当前代码（HEAD `298e426` + 主线修正提交）即可产出完整计划；历史 `preexperiment-feedback-final` 里的"科学编辑修正层"（`scientific-editorial-corrections.json` / `final_scientific_audit`）在当前代码中已不存在**，属于旧代码遗留产物，不要以它为准判断当前主线。

---

## 3. 各环节代码位置

### 3.1 主链各环节

| 环节 | 文件 | 关键函数 |
|---|---|---|
| **主线编排 CLI（v2 新增）** | `src/autoresearch/competition/contest_mainline_cli.py` | `run_contest_mainline_delivery`（一条命令：题目→计划→预实验→修订→PDF；`--plan-source-dir`/`--preexperiment-source-dir` 断点续跑） |
| CLI 入口 / 链 1 编排 | `src/autoresearch/competition/contest_direct_plan_cli.py` | `run_contest_question_one_delivery` |
| 题目确定性提取 | `src/autoresearch/competition/contest_question_input.py` | `extract_first_science_125_question`（绑定 PDF 源路径、页码、原文 SHA-256，中文翻译只允许仓库已核验的第 1 题） |
| Skill 目录发现 | `contest_direct_plan_cli.py` | `discover_contest_method_skills`（扫描 `skills/*/SKILL.md`，只解析 frontmatter 的 name/description + 内容 SHA-256） |
| Skill 元数据路由 | `src/autoresearch/competition/contest_direct_skill_router.py` | `route_contest_direct_plan_skills`（题目→元数据目录→只返回 ID；**该模块故意没有读 Skill 正文的 API**） |
| 不记名临时子 Agent 池 | `src/autoresearch/competition/temporary_qwen_pool.py` | `run_temporary_qwen_content_batch`（并行派发、逐任务归档、运行时身份移除、失败降级） |
| 研究目标阶段（3 角色 + 独立评审） | `src/autoresearch/competition/contest_research_objective_stage.py` | `run_contest_research_objective_stage`（`specified_question` 模式；角色：`falsifiable_hypothesis_explorer` / `method_bridge_explorer` / `assumption_challenger`） |
| 计划生成（核心提示词） | `src/autoresearch/competition/contest_direct_plan.py` | `generate_contest_direct_plan` + `build_contest_direct_plan_messages` |
| 渲染（LaTeX 模板所在地） | `src/autoresearch/competition/contest_direct_plan_render.py` | `materialize_contest_direct_plan`、`render_contest_plan_tex`、`validate_contest_plan_payload` |
| 锁定文献目录 | `contest_direct_plan_cli.py` | `default_question_one_reference_catalog`（18 条真实文献，带 URL）；`contest_reference_policy.py`（引用投影/相关性排序，只允许选目录内编号，禁止虚构） |
| 计划修订器（自迭代基础件） | `src/autoresearch/competition/contest_direct_plan_revision.py` | `revise_contest_direct_plan`（内置 `_guard_observed_numbers` 数字守卫：修订正文只能出现已验证输入中的数字） |
| 真实预实验（主线硬步骤） | `src/autoresearch/competition/contest_prime_preexperiment.py` | `run_contest_prime_preexperiment`（素数间隙排列熵 + 4 零模型；历史 run_id `prime-pilot-c9dfaac70c007592`） |
| 预实验证据嵌入 | `src/autoresearch/competition/contest_plan_embedded_evidence.py` | `build_contest_plan_embedded_evidence`（从 metrics 派生证据表图并绑定 manifest 哈希） |
| **技术方案 PDF（v2 新增）** | `src/autoresearch/competition/contest_technical_proposal.py` | `materialize_technical_proposal`（从主线交付确定性生成 ≤20 页技术方案，超页数失败关闭） |

### 3.2 Dream / 记忆 / 进化 / 自迭代环节

| 环节 | 文件 | 关键点 |
|---|---|---|
| 原始记忆 + Dreaming 投影 | `src/autoresearch/knowledge/raw_memory.py` | `RawMemoryStore`（本地私有、只追加、内容寻址、逐条绑定 payload SHA-256、Windows ACL 仅属主可读）；`DreamingMemoryProjection`（声明 derived/rebuildable，区分 supported/contradicted/extrapolated/unverified） |
| 方向循环记忆桥 | `src/autoresearch/competition/contest_direction_memory.py` | 把已完成阶段产物镜像进 RawMemoryStore + `RecalledDreamingProjection` 导航召回；**Dreaming 不是科学证据**，记忆失败不阻断交付 |
| Skill 自进化 | `src/autoresearch/competition/contest_direction_skill_evolution.py` | `run_evidence_to_skill_evolution`（证据→Skill 草稿→留出集验证→`activate_validated_evolved_skill` / `rollback_activated_evolved_skill`） |
| 科学修正（红队迭代） | `src/autoresearch/competition/contest_direction_scientific_amendment_cli.py` | `run_contest_direction_scientific_amendment`（红队 findings RT-01…RT-07 → 1 次模型修订 → 1 次独立评审 → 确定性审计，v2/v3 版本化，最多两版） |
| 独立科学评审 | `src/autoresearch/competition/contest_direct_plan_scientific_review.py` | `review_contest_direct_plan_science`（逐字段证据核对 + 参考文献一致性） |
| 定向科学修复 | `src/autoresearch/competition/contest_direction_targeted_scientific_repair_cli.py` | 只修复指定 finding，保留其余已通过修正 |
| 通用自纠正循环 | `src/autoresearch/competition/route_p2_self_correction.py`、`frozen_protocol_contradiction.py` | observe → diagnose → 模型提案（封闭选项集）→ 确定性守卫审计 |
| 自适应科研双环（长期能力，开发中） | `src/autoresearch/research/adaptive_sovereign_loop.py` | `run_adaptive_research_loop`（模型自选 13 种算子 + 晋级门） |
| 专业提示词（Skill 库） | `skills/prime-structure-computational-number-theory/SKILL.md` | 领域方法只落在 Skill 文件，不写进通用 system prompt |

---

## 4. 核心构思

### 4.1 核心提示词通用化 + 专业提示词 Skill 化（题目后按需选择）

- **system prompt 只含通用方法论**（`contest_direct_plan.py` 259 行附近）：证据优先、区分事实/推断/假设/观察、围绕一个可证伪主假设、明确结局/对照/失败判据/复现路径、不堆砌方法。
- **专业方法论在 `skills/*/SKILL.md`**，且采用**题目后两段路由**：Qwen 先只看到 `skill_id/name/description/content_sha256` 元数据做选择（`contest_direct_skill_router.py`），返回 ID 后程序才重新读取并校验选中文件的正文 SHA-256，作为独立 user 消息注入计划作者。路由阶段读不到正文，正文哈希与文件哈希双绑定防篡改。
- **消息顺序固定**（`build_contest_direct_plan_messages`）：
  1. system：通用方法论；
  2. user：题目 + 交付要求（中文计划、研究计划而非论文、可证伪主假设、禁捏造数值/证明）；
  3. user：选中的 Skill 正文（独立消息，声明"方法不是答案/事实/结论"）；
  4. user：归档的临时子 Agent 建议（声明可全部拒绝，非证据非审批）；
  5. user：锁定真实文献目录 + 输出 JSON 契约（13 个科学字段 + references 只能选目录编号）。

### 4.2 不记名临时子 Agent

- 三个角色并行（可证伪假设探索 / 方法桥接+最小预实验 / 反方挑战），各自只返回中文内容 memo。
- **程序生成所有 ID、哈希、状态、归档**；模型不生成 ID/状态。批次完成后运行时身份全部移除（`all_runtime_identities_removed`），内容与作者回执保留。
- 部分失败降级（如本次验证 2/3 成功仍继续）；主 Qwen 可自由采纳、改写或全部拒绝其建议。

### 4.3 证据优先与反虚构

- 参考文献只能从**锁定真实目录**逐项选编号；模型只选编号，程序投影书目，目录外文献零容忍。
- 无预实验时：Results 首行强制"尚未执行预实验"，摘要用计划语气，禁止"已经发现/验证/结果表明"，禁止臆造效应量与 p 值。
- 所有渲染产物绑定生成回执（provider/model/input_hash/response_hash/artifact_hash）。

### 4.4 Dream 与主权记忆（构思，供技术方案撰写）

- 双层：**原始层**（`RawMemoryStore`，本地 Git 忽略、只追加、内容寻址、精确字节哈希）与**派生层**（Dreaming 投影，可删除可重建，带事实/解释/外推/矛盾/未知标签）。
- 纠错只追加 `supersedes` 记录，永不回写原始字节；凭据/私钥类内容在入口即失败关闭。
- Dreaming 召回是导航上下文，**不是科学证据**；任何科学陈述仍须读原始制品核验。

### 4.5 Skill 自进化（构思）

- 证据（论文 + 预实验）→ 生成 Skill 草稿 → 留出集案例评估 → 只有验证通过才 `activate`，带 `rollback` 回执。
- 进化只发生在派生层；原始证据与旧 Skill 版本不可变。

---

## 5. 效果不好时的反复自我迭代机制

1. **单次修订**（最小件）：`contest_direct_plan_revision.py::revise_contest_direct_plan`——原计划 + 证据（预实验/文献/评审发现）→ 一次完整修订，绑定 `original_plan_id` 与证据哈希。
2. **数字守卫内置重试（v2 主线已内置）**：`contest_mainline_cli.py` 在修订阶段自动重试——数字守卫拒绝（`ContestDirectPlanNumberGuardError`）时，把上次拒绝原因追加为一条新要求、按 `0.2→0.4→0.6` 抖动温度重跑（默认 3 次，`--revision-attempts` 可调）。历史 live 六连败（r1-r6 同提示词、输出趋同）已通过该机制与提示词负例加固（禁派生比值/轮筛周期积/改写数量级）缓解；证据绑定类失败不进入重试、直接失败关闭。
3. **科学修正（推荐对主链计划用）**：`contest_direction_scientific_amendment_cli.py`——确定性红队生成 RT-01…RT-07 findings（含参考文献真实性、预实验边界、统计解释等）→ 模型按 findings 修订 1 次 → 独立评审（`review_contest_direct_plan_science`）1 次 → 确定性审计；失败可再走一次 v3（带 prior 失败证据），超过即停止，不无限重试。
   - ⚠️ 当前该 CLI 的 source 契约要求 `contest-direction-research-loop-delivery-v1` 格式，与主链（`contest-question-one-delivery-v1`）产物**格式不匹配**；接入主链需要写一个薄适配或调整 source 校验（见 §6 遗留事项 2）。
4. **定向修复**：`contest_direction_targeted_scientific_repair_cli.py`——只修指定 finding，保留其余已通过项。
5. **通用自纠正**（工程/协议层）：observe → 确定性诊断 → 模型在封闭选项集中提案 → 守卫审计拒绝危险路线（如伪造效应、削弱基线），用于协议矛盾而非科学内容。
6. **原则**：所有迭代都是"新版本 + 绑定父哈希"，不回改已揭示证据；格式失败不触发科学重写；达到版本上限即停止并保留负结果。

---

## 6. 遗留事项（下一步）

1. ✅ **预实验回接（已完成）**：v2 主线把真实预实验设为必做硬步骤；修订数字守卫（`_guard_observed_numbers`）拒绝正文出现证据外数字；首次 r1 因此被拒（模型引入 2310），新增数字边界修订要求后用 `--plan-source-dir`/`--preexperiment-source-dir` 断点重跑修订。
2. ⏭ **科学修正 CLI 适配（后续计划）**：把 `contest_direction_scientific_amendment_cli` 的 source 校验扩展到主链 delivery 格式（或新增薄 CLI），使 RT-01…07 修正可用在主链计划上。
3. ✅ **技术方案 PDF（已完成生成器）**：`contest_technical_proposal.py` 从主线交付确定性生成 ≤20 页技术方案（问题与方法、多智能体/Skills 架构、真实案例、源码说明），超页数失败关闭；主线交付完成后即可运行。**另需人工提供脱敏的阿里云百炼调用截图**（`P-20260809-108`）。
4. **自主搜索灵感线**：`contest_direction_research_loop_cli` 标注"开发中"；其最新阻塞是 OpenAlex 认证恢复（`.env` 已配置 key，bounded source-recovery 未实现，见 `P-20260815-021`）。
