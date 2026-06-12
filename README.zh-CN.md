# AI-Researcher

[English](README.md)

AI-Researcher 是一个证据优先的自动化计算科研平台。目标不是做“会写论文的聊天机器人”，而是构建一个受控、可审计、可复现的科研闭环：文献检索、知识建模、假设生成、实验设计、沙箱执行、结果验证、报告/论文草稿、复盘，以及受控策略进化。

> 当前状态：本地 MVP 脚手架和核心研究闭环组件已具备测试覆盖。仓库包含可执行任务计划、Obsidian 知识库底座、供应商无关的首次部署配置、本地 demo 闭环、文献/相似工作检索基础、验证/报告模块和发布准备检查。它还不是生产级多用户服务。

## 核心原则

- 先证据，后结论。
- 先可复现，后自动化。
- 高成本、高风险、公开发布动作必须人工审批。
- 默认沙箱执行。
- `autoresearch-vault/` 是项目根目录下固定的 Obsidian 兼容知识库，用于研究记忆、失败库、技能库、证据链接和策略进化。
- 项目启动和定时刷新都必须联网检索文献与相近工作；vault 只沉淀有来源支撑的总结，不虚构成果。
- 每个实验记录 run ID、commit、配置 hash、数据 hash、指标、日志、产物和成本。
- 每个 Agent 改动必须写入 [Agent.md](Agent.md)。
- 每个发现的问题、阻塞或风险必须写入 [Problem.md](Problem.md)。

## 参考与设计启发

AI-Researcher 不是复刻某一个项目，而是在证据优先的约束下吸收多个开源方向的经验：

- [HKUDS AI-Researcher](https://github.com/HKUDS/AI-Researcher)：端到端科研流水线目标和 Scientist-Bench 式评测压力。本仓库只把它作为概念参考；AI-Researcher 的重点是 Obsidian 驱动的自循环记忆底座、带权限审批的常驻运行、证据图、真实运行记录，以及在论文声明前先通过发表级审计。
- [AutoResearchClaw](https://github.com/aiming-lab/AutoResearchClaw)：可参考其 MIT 许可下的一句话启动/OpenClaw 式操作者体验、23 阶段科研流水线、human-in-the-loop 模式、多源文献检索、claim verification 和 skill-learning 方向。本项目的差异点是把 Obsidian 兼容 vault 固定为可审计记忆底座，在论文声明前先用更硬的发表级审计阻断不充分证据，并保持 provider-agnostic 本地部署和权限化常驻运行。
- [AI for Auto-Research](https://worldbench.github.io/awesome-ai-auto-research/) 等长程自动科研路线图：强调幻觉、创新性检验、可复现产物和评估压力。
- [Horizon](https://github.com/Thysrael/Horizon) 和 [agent-arxiv-daily](https://github.com/UltraClr/agent-arxiv-daily) 等每日更新项目：启发定时联网抓取、来源评分、摘要分发和论文更新机制。
- [Microsoft SkillOpt](https://github.com/microsoft/SkillOpt)：把 Markdown skill 当作可优化的外部 Agent 状态，通过 rollout 证据、有界编辑、验证门和 `best_skill.md` 产物来稳定进化技能。
- [OpenClaw](https://github.com/openclaw/openclaw)：启发“配置一次、本地常驻”的操作者体验。

这些参考项目的许可证和署名状态记录在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。除非该文件明确写明已纳入代码或资产，否则它们只是设计启发，不是本仓库复制或 vendored 的第三方代码。

本项目的核心差异是把 Obsidian 兼容 vault 作为证据、问题、技能和策略的统一底座。自动化只在能写出可审计证据和评审产物时推进。

## Obsidian 知识库设置

用一条命令生成本地 vault 的首页、dashboard、模板、插件推荐清单和 CSS snippet：

```bash
poetry run airesearcher obsidian-setup --vault autoresearch-vault --project-id autoresearch-system
```

如果是在自己的机器上使用 Obsidian，可以额外加 `--write-local-snippet`，它会写入 `.obsidian/snippets/ai-researcher.css` 并在本地外观配置中启用。第三方 Obsidian 插件不会随仓库打包；运行后可查看 `autoresearch-vault/_system/plugins/recommended-plugins.md`，按需手动安装 Dataview、Tasks、Templater、Periodic Notes、Omnisearch 等插件。

## 开发环境

前置条件：

- Python 3.10+
- Poetry
- Git

安装依赖：

```bash
poetry install
```

首次部署配置：

```bash
poetry run airesearcher deploy-setup
```

该命令会引导输入 LLM provider 标签、API base URL、model name、API key，以及可选的微信/飞书通道参数。API key 和通道密钥只写入 `.env`；`config.yaml` 只保存非密钥模型配置、通道元数据和环境变量名。如果 `.env.example` 缺失，CLI 会创建一个公开的非密钥模板。

如果你想手动填写模型配置，可以把 `.env.example` 复制为 `.env`，然后填写 `AUTORESEARCH_LLM_BASE_URL`、`AUTORESEARCH_LLM_MODEL_NAME` 和 `AUTORESEARCH_LLM_API_KEY`。也可以填写 `SEMANTIC_SCHOLAR_API_KEY` 以获得更高的 Semantic Scholar Graph API 限额；如果部署环境需要更严格限频，还可以填写可选的 `SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS` 和 `SEMANTIC_SCHOLAR_CIRCUIT_RESET_SECONDS`。OpenAlex 默认可以无 key 小规模使用；较大的部署可以填写 `OPENALEX_API_KEY`、`OPENALEX_MAILTO`、`OPENALEX_MIN_INTERVAL_SECONDS` 和 `OPENALEX_CIRCUIT_RESET_SECONDS`，让来源 fallback 更稳定也更礼貌。根目录 `.env` 会被 git 忽略，不能提交真实密钥。

脚本化部署示例：

```bash
poetry run airesearcher deploy-setup \
  --config config.yaml \
  --env-path .env \
  --provider openai-compatible \
  --base-url https://api.example.com/v1 \
  --model-name your-model-name \
  --api-key your-api-key \
  --wechat --wechat-webhook-url https://wechat.example/hook \
  --feishu --feishu-webhook-url https://feishu.example/hook \
  --non-interactive
```

初始化项目级斜杠命令模板：

```bash
poetry run airesearcher slash-commands init
poetry run airesearcher slash-commands list
```

默认生成 `.airesearcher/commands/` 下的 TOML 模板，包括 `/research:refresh-literature`、`/research:similarity-check`、`/research:run-demo`、`/research:autopilot`、`/research:serve`、`/research:publication-audit`、`/research:approve`、`/research:openclaw-channels`、`/research:obsidian-setup`、`/research:issue-followups` 和 `/research:status`。

常驻运行入口：

```bash
poetry run airesearcher serve --permission-mode approve-dangerous
```

这是推荐的 24h 本地/服务器运行入口。它复用已有 autopilot 循环，但在执行联网发现、实验、真实 LLM review 或写入 vault/state 前，会把危险动作写入 `.airesearcher/runtime-approvals.json` 等待人工批准。可信单用户部署可以使用 `--permission-mode allow-all`；更安全的部署应保留 `approve-dangerous`，通过本地终端或通信软件适配器批准：

```bash
poetry run airesearcher runtime list
poetry run airesearcher runtime approve latest --approved-by operator
```

OpenClaw 通信通道挂载清单：

```bash
poetry run airesearcher channels openclaw init
poetry run airesearcher channels openclaw list
```

该命令会写入 `integrations/openclaw/channels.json`，作为把官方/常见 OpenClaw 通信插件挂到 AI-Researcher 运行时上的仓库 runbook。清单覆盖飞书/Lark（`@larksuite/openclaw-lark`）、微信（`npx -y @tencent-weixin/openclaw-weixin-cli install` / `@tencent-weixin/openclaw-weixin`）、企业微信（`@wecom/wecom-openclaw-plugin`），以及 OpenClaw 文档中的 Telegram、Discord、Slack、WhatsApp、Microsoft Teams、QQ Bot、Signal 和 Zalo 等通道。第三方通道插件不会被 vendor 到本仓库；请在 OpenClaw 部署内安装，并把密钥保存在 OpenClaw 凭据、`.env` 或平台密钥管理中。

通信软件中的 `/approve` 应映射到：

```bash
poetry run airesearcher runtime approve latest --state .airesearcher/runtime-approvals.json --approved-by <operator>
```

Autopilot 一条命令常驻循环：

```bash
poetry run airesearcher autopilot --watch --cycles 0 --interval-seconds 86400
```

完成 `deploy-setup` 后，该命令可直接让本地循环持续运行。每一轮会执行真实文献刷新、来源支撑的相似工作检查、本地 demo 或公开 benchmark 实验、可选真实 LLM 证据评审、发表级质量审计、Obsidian review/issue 写入，以及本地 follow-up state 合并。离线演练可加 `--no-review`，只跑一轮则不要加 `--watch`。当前循环能产出可复现、带证据和评审轨迹的报告；发表级审计会刻意严格地拦截玩具数据循环，不允许把它声称为 CCF-B/三区期刊可发表成果。

真实 benchmark 可选运行：

```bash
poetry run airesearcher run-demo --demo pendigits_centroid_baseline --timeout-seconds 60
poetry run airesearcher serve --once --permission-mode allow-all --demo pendigits_centroid_baseline --review --max-queries 4 --max-results-per-source 5 --timeout-seconds 60
```

`pendigits_centroid_baseline` 会在运行时下载 UCI Pen-Based Recognition of Handwritten Digits 的官方 train/test 文件，在 `runs/` 下写入本地合并 CSV，运行 nearest-centroid baseline 和 first-8-features ablation，并记录来源 URL、数据 hash、指标、置信区间和验证产物。它比玩具 demo 更接近真实证据检查，但仍只是一个 baseline benchmark；只有当文献广度、相似工作广度、论文结构和评审门也通过后，系统才允许发表级声明。

Skill evolution 候选：

```bash
poetry run airesearcher skill-evolve \
  --parent-skill-id skill_evidence_bound_review \
  --issue-ref projects/autoresearch-system/issues/example_issue \
  --change-summary "Tighten the evidence bundle before live review." \
  --proposed-action "Attach run-record evidence before review." \
  --validation-check "Held-out review has zero unsupported reproduction claims."
```

这一步受 SkillOpt 启发，但实现上保持保守：它只会在 Obsidian vault 中写入候选 skill card 和 rejected-edit buffer，不会覆盖或提升父 skill。真正 promotion 仍需要 held-out validation 和人工审阅。

联网发现命令：

```bash
poetry run airesearcher literature-refresh --vault autoresearch-vault --cache .cache/literature --max-queries 1 --max-results-per-source 1
poetry run airesearcher similarity-check --candidate-file candidate.json --vault autoresearch-vault --cache .cache/literature --project-id my_project
```

这两个命令默认调用真实文献 API：ArXiv、Semantic Scholar 和 OpenAlex。它们会从 `.env` 读取可选文献 API key，对不同来源使用保守且可调的请求间隔、429 circuit breaker 和可见错误记录，并写入带防虚构说明的 Obsidian 总结；没有证据支撑的结果保持为 `unknown` 或 `pending verification`。OpenAlex 作为免费公开元数据来源参与默认检索，避免 Semantic Scholar 限流时来源广度退化为只有 ArXiv。`.env.example` 提供可选的 `OPENALEX_API_KEY`、`OPENALEX_MAILTO`、`OPENALEX_MIN_INTERVAL_SECONDS` 和 `OPENALEX_CIRCUIT_RESET_SECONDS`。

真实 LLM smoke 与输出质量门：

```bash
poetry run airesearcher llm-smoke --config config.yaml --env-path .env --output runs/llm-smoke/latest.json
```

该命令会调用当前配置的 OpenAI-compatible 模型，要求结构化 JSON 输出，检查证据策略语言、API key 泄露风险，并把质量报告写入 `runs/`。

基于本地证据的 LLM-as-reviewer：

```bash
poetry run airesearcher llm-review `
  --subject runs/manual-live/demo/tabular-baseline/report/report.md `
  --evidence runs/manual-live/demo/tabular-baseline/validation/validation-report.json `
  --evidence runs/manual-live/demo/tabular-baseline/evidence/evidence-map.json `
  --config config.yaml `
  --env-path .env `
  --output runs/llm-review/latest.json `
  --max-tokens 4096 `
  --vault autoresearch-vault `
  --project-id demo_project
```

该评审可以调用当前配置的真实模型，但确定性质量门要求每条 finding 引用提供的本地证据 ID，例如 `evidence_1`；缺少证据引用或引用未知证据都会低于质量阈值。通过质量门的评审可以写回 `autoresearch-vault/projects/<project-id>/review/`，成为 Obsidian `review_note`；其中 warning/blocking finding 会继续写入 `autoresearch-vault/projects/<project-id>/issues/` 作为带稳定指纹的 `issue_note`。同一 subject 与 claim 的重复评审会更新同一条 issue note，而不是污染自循环问题池。`airesearcher issue-followups --state .airesearcher/scheduler-state.json` 可以持久化可审阅的本地后续任务记录，但不会自动执行它们；`airesearcher scheduler-state list|complete|remove` 允许操作者查看、完成或清理这些记录，不需要手动编辑 JSON。推理型模型可能需要示例里的较高 review token 预算。

发表级质量审计：

```bash
poetry run airesearcher publication-audit runs/autopilot/<cycle-id>/cycle-summary.json `
  --target ccf-b `
  --vault autoresearch-vault `
  --project-id demo_project
```

这比 `llm-review` 更严格：它检查脚本是否真的执行、数据哈希和指标是否能追溯、验证数据规模是否足够、联网文献与相似工作检索是否足够宽、Semantic Scholar 429 等来源失败是否削弱 novelty 覆盖、报告是否具备论文级章节，以及 baseline、ablation、统计 sanity 是否有证据。`ccf-b` 和 `q3-journal` 目标会默认拒绝合成 ScientistBench-Lite 玩具实验；即使是真实 benchmark，如果 novelty 检索、论文结构或证据广度不足，也会继续被拒绝。失败审计会写入 Obsidian 的 `publication-audit` review/issue note，供自循环任务池继续处理。

运行本地质量门：

```bash
python scripts/check.py
```

该命令与默认 CI 检查保持一致：`poetry run ruff check src tests`、`poetry run mypy src`、`poetry run pytest tests/smoke tests/unit`。默认的 `test_cli.py` 和 `test_imports.py` smoke 只检查本地安装与导入；只有下面显式列出的 live smoke 会访问外部 API。

配置 `.env` 后运行真实 API smoke：

```bash
$env:AUTORESEARCH_LIVE_APIS='1'
poetry run pytest tests/smoke/test_llm_live.py tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py tests/smoke/test_similarity_live.py -vv
```

## 常用命令

```bash
poetry run airesearcher doctor
poetry run airesearcher run-demo --demo tabular_baseline
poetry run airesearcher run-demo --demo pendigits_centroid_baseline --timeout-seconds 60
poetry run airesearcher validate-package --manifest <path>
```

启用真实联网文献/相似工作 smoke test：

```bash
$env:AUTORESEARCH_LIVE_LITERATURE='1'
poetry run pytest tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py tests/smoke/test_similarity_live.py -vv
```

## 文档

- [研究计划](AutoResearch_System_Research_Plan.md)：研究范围、架构、Agent 模型、验证机制、风险矩阵和长期路线。
- [实施计划](AutoResearch_System_Execution_Plan.md)：阶段计划、里程碑、schema、测试策略、成本模型和发布门槛。
- [Kiro 需求](.kiro/specs/auto-research-system/requirements.md)：Obsidian 知识库、Agent 进化、知识演化和项目权限的原始需求。
- [Kiro 设计](.kiro/specs/auto-research-system/design.md)：Obsidian vault 结构、知识 API、访问控制和实现优先级。
- [实现任务](.kiro/specs/auto-research-system/tasks.md)：详细可执行任务清单。
- [Agent 改动日志](Agent.md)：所有编码 Agent 必须更新的变更日志。
- [问题日志](Problem.md)：问题、阻塞和风险记录。
- [变更日志](CHANGELOG.md)：未发布版本说明、迁移说明和已知问题。
- [发布门槛清单](docs/release-gate.md)：创建发布标签、演示或生产可用声明前必须完成的检查。

## 贡献方式

完整开发流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

修改文件前：

1. 阅读 [AGENTS.md](AGENTS.md)。
2. 查看 [.kiro/specs/auto-research-system/tasks.md](.kiro/specs/auto-research-system/tasks.md) 中的当前任务。
3. 检查 [Problem.md](Problem.md) 中的未关闭问题。
4. 用最小改动完成任务。
5. 运行相关验证命令。
6. 将改动摘要追加到 [Agent.md](Agent.md)。

## 许可证

AI-Researcher 使用 [Apache License 2.0](LICENSE) 发布。SPDX 标识为 `Apache-2.0`。署名信息和第三方参考声明见 [NOTICE](NOTICE) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
