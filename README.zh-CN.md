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

如果你想手动填写模型配置，可以把 `.env.example` 复制为 `.env`，然后填写 `AUTORESEARCH_LLM_BASE_URL`、`AUTORESEARCH_LLM_MODEL_NAME` 和 `AUTORESEARCH_LLM_API_KEY`。根目录 `.env` 会被 git 忽略，不能提交真实密钥。

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

默认生成 `.autoresearch/commands/` 下的 TOML 模板，包括 `/research:refresh-literature`、`/research:similarity-check`、`/research:run-demo` 和 `/research:status`。

联网发现命令：

```bash
poetry run autoresearch literature-refresh --vault autoresearch-vault --cache .cache/literature --max-queries 1 --max-results-per-source 1
poetry run autoresearch similarity-check --candidate-file candidate.json --vault autoresearch-vault --cache .cache/literature --project-id my_project
```

这两个命令默认调用真实文献 API，保留每个来源的 fetch 错误，并写入带防虚构说明的 Obsidian 总结；没有证据支撑的结果保持为 `unknown` 或 `pending verification`。

运行本地质量门：

```bash
python scripts/check.py
```

该命令与默认 CI 检查保持一致：`poetry run ruff check src tests`、`poetry run mypy src`、`poetry run pytest tests/smoke tests/unit`。

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
