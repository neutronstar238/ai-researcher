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

- [HKUDS AI-Researcher](https://github.com/HKUDS/AI-Researcher)：端到端科研流水线目标，包括文献综述、假设生成、实现、论文写作和评估。
- [AI for Auto-Research](https://worldbench.github.io/awesome-ai-auto-research/) 等长程自动科研路线图：强调幻觉、创新性检验、可复现产物和评估压力。
- [agent-arxiv-daily](https://github.com/UltraClr/agent-arxiv-daily) 等每日论文更新项目：启发定时联网抓取和论文更新机制。
- [Microsoft SkillOpt](https://github.com/microsoft/SkillOpt)：把 Markdown skill 当作可优化的外部 Agent 状态，通过 rollout 证据、有界编辑、验证门和 `best_skill.md` 产物来稳定进化技能。
- [OpenClaw](https://github.com/openclaw/openclaw)：启发“配置一次、本地常驻”的操作者体验。

本项目的核心差异是把 Obsidian 兼容 vault 作为证据、问题、技能和策略的统一底座。自动化只在能写出可审计证据和评审产物时推进。

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
poetry run autoresearch deploy-setup
```

该命令会引导输入 LLM provider 标签、API base URL、model name、API key，以及可选的微信/飞书通道参数。API key 和通道密钥只写入 `.env`；`config.yaml` 只保存非密钥模型配置、通道元数据和环境变量名。如果 `.env.example` 缺失，CLI 会创建一个公开的非密钥模板。

如果你想手动填写模型配置，可以把 `.env.example` 复制为 `.env`，然后填写 `AUTORESEARCH_LLM_BASE_URL`、`AUTORESEARCH_LLM_MODEL_NAME` 和 `AUTORESEARCH_LLM_API_KEY`。也可以填写 `SEMANTIC_SCHOLAR_API_KEY` 以获得更高的 Semantic Scholar Graph API 限额；如果部署环境需要更严格限频，还可以填写可选的 `SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS` 和 `SEMANTIC_SCHOLAR_CIRCUIT_RESET_SECONDS`。根目录 `.env` 会被 git 忽略，不能提交真实密钥。

脚本化部署示例：

```bash
poetry run autoresearch deploy-setup \
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
poetry run autoresearch slash-commands init
poetry run autoresearch slash-commands list
```

默认生成 `.autoresearch/commands/` 下的 TOML 模板，包括 `/research:refresh-literature`、`/research:similarity-check`、`/research:run-demo`、`/research:autopilot`、`/research:issue-followups` 和 `/research:status`。

Autopilot 一条命令常驻循环：

```bash
poetry run autoresearch autopilot --watch --cycles 0 --interval-seconds 86400
```

完成 `deploy-setup` 后，该命令会让本地循环持续运行。每一轮会执行真实文献刷新、来源支撑的相似工作检查、本地 ScientistBench-Lite 实验、可选真实 LLM 证据评审、Obsidian review/issue 写入，以及本地 follow-up state 合并。离线演练可加 `--no-review`，只跑一轮则不要加 `--watch`。当前循环能产出可复现、带证据和评审轨迹的报告；真正可发表论文仍需要更强领域实验和人工审阅。

联网发现命令：

```bash
poetry run autoresearch literature-refresh --vault autoresearch-vault --cache .cache/literature --max-queries 1 --max-results-per-source 1
poetry run autoresearch similarity-check --candidate-file candidate.json --vault autoresearch-vault --cache .cache/literature --project-id my_project
```

这两个命令默认调用真实文献 API，会从 `.env` 读取可选文献 API key，对 Semantic Scholar 使用更保守且可调的请求间隔、429 circuit breaker 和可见错误记录，并写入带防虚构说明的 Obsidian 总结；没有证据支撑的结果保持为 `unknown` 或 `pending verification`。

真实 LLM smoke 与输出质量门：

```bash
poetry run autoresearch llm-smoke --config config.yaml --env-path .env --output runs/llm-smoke/latest.json
```

该命令会调用当前配置的 OpenAI-compatible 模型，要求结构化 JSON 输出，检查证据策略语言、API key 泄露风险，并把质量报告写入 `runs/`。

基于本地证据的 LLM-as-reviewer：

```bash
poetry run autoresearch llm-review `
  --subject runs/manual-live/demo/tabular-baseline/report/report.md `
  --evidence runs/manual-live/demo/tabular-baseline/validation/validation-report.json `
  --evidence runs/manual-live/demo/tabular-baseline/evidence/evidence-map.json `
  --config config.yaml `
  --env-path .env `
  --output runs/llm-review/latest.json `
  --max-tokens 2400 `
  --vault autoresearch-vault `
  --project-id demo_project
```

该评审可以调用当前配置的真实模型，但确定性质量门要求每条 finding 引用提供的本地证据 ID，例如 `evidence_1`；缺少证据引用或引用未知证据都会低于质量阈值。通过质量门的评审可以写回 `autoresearch-vault/projects/<project-id>/review/`，成为 Obsidian `review_note`；其中 warning/blocking finding 会继续写入 `autoresearch-vault/projects/<project-id>/issues/` 作为带稳定指纹的 `issue_note`。同一 subject 与 claim 的重复评审会更新同一条 issue note，而不是污染自循环问题池。`autoresearch issue-followups --state .autoresearch/scheduler-state.json` 可以持久化可审阅的本地后续任务记录，但不会自动执行它们；`autoresearch scheduler-state list|complete|remove` 允许操作者查看、完成或清理这些记录，不需要手动编辑 JSON。推理型模型可能需要示例里的较高 review token 预算。

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
poetry run autoresearch doctor
poetry run autoresearch run-demo --demo tabular_baseline
poetry run autoresearch validate-package --manifest <path>
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

AI-Researcher 使用 [Apache License 2.0](LICENSE) 发布。SPDX 标识为 `Apache-2.0`。署名信息见 [NOTICE](NOTICE)。
