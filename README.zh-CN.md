# AI-Researcher

[English](README.md)

AI-Researcher 是一个 V1.0 本地/服务器端的证据优先自动科研操作系统。它可以长期运行，自动发现真实资料，抓取灵感，执行有边界的实验，验证结果，构建 LaTeX/PDF 论文产物，并把长期记忆写回 Obsidian 兼容的 Markdown 知识库。

它不是“让大模型写一篇像论文的文章”的聊天机器人。它的核心是一个可审计科研闭环：真实检索、可复现实验、证据门禁、评审门禁、论文级产物和受控自进化。

![AI-Researcher 操作台](docs/assets/readme/cli-monitor.svg)

## V1.0 范围

V1.0 是单操作者的本地/服务器版本，可以在部署后挂在工作站或服务器上持续运行。它还不是多用户 SaaS，也不会自动投稿。

| 模块 | V1.0 行为 |
| --- | --- |
| 引导式部署 | `airesearcher setup` 会引导选择模型供应商、base URL、模型名、API key、微信扫码或飞书 App 凭据、vault 路径、集成 manifest 和 slash 模板。 |
| 常驻自循环 | `airesearcher serve` 和 `airesearcher autopilot --watch` 支持每日循环：联网文献、灵感抓取、实验、评审、审计、论文构建和 follow-up。 |
| 灵感推送 | `--push-inspiration` 会通过 setup 配好的微信/飞书通道推送灵感摘要；缺少可送达状态时记录为 `skipped`，不会假装成功。 |
| Obsidian 记忆 | `autoresearch-vault/` 存储文献、灵感、实验、证据、issue、失败、skill、strategy 和论文摘要。 |
| 论文产物 | Markdown 经验与归档在 vault 中；PDF、TeX、manifest 等发布产物在 `outputs/<project-id>/` 中。 |
| 代码 Agent | 支持把 OpenCode 作为外部代码起草后端，但验证、审批、提交和回滚权仍在 AI-Researcher。 |
| 通信适配器 | OpenClaw 风格通道只作为 runbook 元数据保留，不把第三方插件源码混进仓库。 |
| 发表门禁 | CCF-B/三区级别声明必须绑定真实来源、实验记录、复现检查、审计、PDF 构建和 evidence gate。 |

## 安装

准备环境：

- Python 3.10+
- Node.js 20+
- Git
- 可选：Obsidian，用于可视化浏览知识库
- 可选：OpenCode，用于外部代码生成任务

```bash
git clone <your-repo-url>
cd AIResearch
python -m pip install -e .
npm install
npm run doctor
```

Python CLI 和 npm 启动器调用的是同一个系统：

```bash
airesearcher version
node ./bin/airesearcher.mjs version
```

## 首次部署

运行引导式配置：

```bash
npm run setup
# 或
airesearcher setup
```

向导会依次引导：

1. 选择 DeepSeek、OpenAI-compatible、SiliconFlow 或自定义供应商。
2. 确认 `AUTORESEARCH_LLM_BASE_URL`。
3. 填写 `AUTORESEARCH_LLM_MODEL_NAME`。
4. 填写 `AUTORESEARCH_LLM_API_KEY`。
5. 可选配置微信扫码通道，或用 App ID/App Secret 配置飞书/Lark。
6. 初始化 `autoresearch-vault/`。
7. 写入 `integrations/` 下的集成 runbook。
8. 写入 `.airesearcher/commands/` 下的本地 slash command 模板。

向导会把本地密钥和通道状态写入 `.env`，用户不需要手动编辑这个文件。公开模板在 `.env.example`。不要提交真实 API key、webhook URL、app secret、chat ID、会话或 token。

推荐通道配置：

- 飞书/Lark：在 `airesearcher setup` 中选择 App ID + App Secret 模式。如果已经知道 home chat ID，可以在 setup 阶段填写；否则后续通过 adapter/gateway 与机器人对话后再绑定 home channel。
- 微信/Weixin：选择 QR setup。交互式向导会在写完配置后立刻启动二维码适配器 setup 命令并等待扫码/登录结果；非交互脚本默认只记录配置状态，除非额外传入 `--run-wechat-qr-setup`。
- Webhook URL 仍作为已有 incoming webhook 部署的兼容 fallback。

也可以非交互式部署：

```bash
airesearcher setup \
  --provider openai-compatible \
  --base-url https://api.example.com/v1 \
  --model-name your-model \
  --api-key sk-... \
  --no-wechat \
  --no-feishu \
  --non-interactive
```

## 启动 24h 常驻系统

V1.0 推荐入口：

```bash
npm run serve
```

等价于：

```bash
airesearcher serve --permission-mode approve-dangerous --push-inspiration
```

`serve` 默认持续运行。它会检查审批队列，执行已批准的 cycle，每次 cycle 间隔默认 `86400` 秒，并记录灵感摘要推送状态。

另开一个终端审批第一轮危险动作：

```bash
airesearcher runtime list
airesearcher runtime approve latest --approved-by operator
```

如果这是完全可信的本地机器，也可以使用：

```bash
airesearcher serve --permission-mode allow-all --push-inspiration
```

只有当你确认联网检索、本地实验、LLM 评审、vault 写入和 output 写入都可以无需逐轮审批时，才使用 `allow-all`。

## 每日抓取和灵感推送

不需要审批服务包装时，可以直接启动每日 autopilot：

```bash
airesearcher autopilot --watch --cycles 0 --interval-seconds 86400 --push-inspiration
```

每一轮 cycle 可以执行：

1. 来源冷却和 preflight 检查。
2. ArXiv 和 OpenAlex 文献刷新，Semantic Scholar 作为可选低优先级来源。
3. 有来源支撑的相似工作和创新性检查。
4. Hugging Face 和 Hacker News 灵感抓取。
5. 本地 demo 或真实公开 benchmark 实验。
6. 命令行复现实验检查。
7. 可选真实 LLM 证据评审。
8. publication audit。
9. LaTeX 论文构建。
10. physical evidence gate。
11. Obsidian review、issue、skill、strategy 写入。
12. scheduler follow-up 合并。
13. 可选微信/飞书灵感摘要推送。

单次灵感抓取并推送：

```bash
airesearcher inspiration-refresh \
  --query "autonomous research agents datasets" \
  --vault autoresearch-vault \
  --output runs/inspiration/latest.json \
  --push \
  --push-channel feishu
```

如果所选通道缺少送达所需状态，JSON 输出会记录 `skipped`，不会声称已经送达。飞书 App 凭据在配置 home chat ID 后可以直接发送摘要；微信扫码送达依赖 QR adapter 会话处于可用状态。

## 操作台监控

```bash
npm run monitor
# 或
airesearcher monitor
```

监控台会显示最近 Agent 消息、活跃文件声明、研究流程状态、审批队列、follow-up 任务、git diff 和 output 预览。

| 参数 | 作用 |
| --- | --- |
| `--watch` | 持续刷新操作台。 |
| `--refresh-seconds <n>` | 设置刷新间隔。 |
| `--no-diff` | 隐藏 diff 预览，保持监控界面干净。 |
| `--cycle-summary <path>` | 指定查看某个 cycle summary。 |
| `--outputs-dir <path>` | 预览自定义输出目录。 |

## Slash Commands

如果需要重新生成模板：

```bash
airesearcher slash-commands init
airesearcher slash-commands list
```

slash 命令后面的文本会作为 `{{args}}` 传入模板。

| Slash 命令 | 常见参数 | 执行动作 |
| --- | --- | --- |
| `/research:serve` | 无 | 启动 `approve-dangerous` 常驻服务并开启灵感推送。 |
| `/research:approve` | `latest` 或 `<request-id>` | 审批队列中的危险动作。 |
| `/research:autopilot` | 可选说明 | 启动带证据门禁的每日自循环。 |
| `/research:refresh-literature` | 可选主题 | 联网刷新 ArXiv/OpenAlex 文献。 |
| `/research:inspiration-refresh` | 查询文本 | 抓取非学术灵感来源并可推送摘要。 |
| `/research:similarity-check` | candidate 上下文 | 对候选课题做相近工作交叉检索。 |
| `/research:run-demo` | demo id | 执行本地 demo 或公开 benchmark。 |
| `/research:publication-audit` | cycle summary 路径 | 审计发表准备度。 |
| `/research:publication-stability` | 多个 cycle summary | 检查跨 cycle、模板和数据集的稳定性。 |
| `/research:paper-build` | 报告路径或模板 id | 构建 LaTeX/PDF 论文产物。 |
| `/research:evidence-gate` | cycle summary 路径 | 运行物理证据门禁。 |
| `/research:issue-followups` | project id | 把 vault 中开放 issue 列成 scheduler 任务。 |
| `/research:session-claim` | task/path 信息 | 协调多个 Agent 的文件声明。 |
| `/research:obsidian-setup` | project id | 刷新安全的 vault 资产。 |
| `/research:skill-evolve` | skill 证据 | 创建受控 skill 进化候选。 |
| `/research:skill-polish-audit` | skill id | 在 promotion 前审计 skill card。 |
| `/research:skill-watchlist` | 无 | 将外部科研 skill 候选写入 Obsidian 隔离观察清单。 |
| `/research:channel-adapters` | 无 | 写入可选通信 adapter runbook。 |
| `/research:code-agent-backends` | 无 | 写入 OpenCode 后端集成契约。 |
| `/research:scansci-pdf` | 无 | 写入 OA-first PDF 获取 manifest。 |
| `/research:status` | 无 | 查看本地 operator 状态提示。 |

## 常用 CLI 参数

| 命令 | 参数 | 含义 |
| --- | --- | --- |
| `setup` | `--provider`, `--base-url`, `--model-name`, `--api-key` | 供应商无关的大模型配置。 |
| `setup` | `--wechat --wechat-qr` | 微信/Weixin 扫码适配器配置；交互式 setup 会启动扫码流程，非交互脚本可额外使用 `--run-wechat-qr-setup`。 |
| `setup` | `--feishu --feishu-app-id --feishu-app-secret` | 飞书/Lark App 凭据配置；`--feishu-home-chat-id` 可开启直接摘要推送。 |
| `setup` | `--wechat-webhook-url`, `--feishu-webhook-url` | 给已有 incoming webhook 部署使用的 fallback。 |
| `serve` | `--permission-mode approve-dangerous|allow-all` | 危险动作审批或全自动运行。 |
| `serve` / `autopilot` | `--interval-seconds 86400` | 每日循环间隔。 |
| `serve` / `autopilot` | `--cycles 0` | watch 模式下无限运行。 |
| `serve` / `autopilot` | `--push-inspiration` | 把灵感摘要推送到 setup 配好的操作者通道。 |
| `serve` / `autopilot` | `--max-queries`, `--max-results-per-source` | 检索广度。仅 smoke 时降低。 |
| `serve` / `autopilot` | `--max-tokens` | 可选 LLM reviewer 输出上限。默认不设置，适配长上下文模型。 |
| `inspiration-refresh` | `--env-path .env` | 单次推送时加载 setup 写入的通道凭据。 |
| `inspiration-refresh` | `--push`, `--push-channel`, `--push-timeout-seconds` | 单次灵感摘要推送。 |
| `paper-build` | `--template-id` | 选择注册的 LaTeX 模板。 |
| `runtime approve` | `latest` 或 request id | 审批等待中的危险动作。 |

## 输出和仓库卫生

以下本地运行产物默认被 git 忽略：

- `.env`
- `.airesearcher/`
- `.cache/`
- `runs/`
- `artifacts/`
- `outputs/`

仓库应该只保留源码、测试、文档、集成 manifest、模板、许可证声明和安全的 Obsidian vault 脚手架。生成的 PDF 和大型运行包留在本地 `outputs/`，除非发布流程明确复制到其它地方。

## Obsidian 知识库

`autoresearch-vault/` 是系统的记忆底座，不是装饰目录。它存储：

- 文献和来源摘要；
- 非学术来源灵感笔记；
- 项目进展和实验记录；
- evidence map 和验证摘要；
- review findings 和 follow-up issue；
- failure patterns；
- 可复用 skill card；
- 带 shadow evaluation 和 rollback 的 strategy card；
- paper-build 摘要和 Markdown 归档。

后续 cycle 会先读取同一个 vault，再提出新任务。因此自循环和自进化不是靠 prompt 记忆，而是靠可审计、可版本管理的 Markdown 记忆。

## 论文产物

Markdown 记录和项目归档留在 `autoresearch-vault/`。面向发表的产物会复制到：

```text
outputs/<project-id>/
```

通过门禁的 cycle 可以包含：

- `<project-id>-<cycle-id>.pdf`
- 生成的 `.tex`
- `paper-build.json`
- `publication-audit.json`
- `evidence-gate.json`
- `cycle-summary.json`
- manifest `.json` 和 `.md`

不能因为 PDF 存在就声称论文可发表。发表级声明必须来自同一 cycle 的 publication audit 和 evidence gate 通过结果。

## 外部参考与许可证

AI-Researcher 参考了多个开源项目的设计思路或生态集成方式，包括 HKUDS AI-Researcher、AutoResearch、Horizon 风格每日刷新、AutoResearchClaw、SkillOpt、OpenClaw 通道插件、OpenCode、Hermes Agent、Luban Skill 风格指南、SimpleMem/Omni-SimpleMem、SkillClaw、Auto-Empirical Research Skills、paper-craft-skills、citation-management 和 Deep-Research-skills。外部 skill 线索会先通过 `airesearcher skill-watchlist` 进入 Obsidian 隔离观察清单；在许可证、安全、真实证据和回滚门禁通过之前，不会安装、复制或 promotion。

这些项目的许可证和是否纳入源码的状态记录在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本仓库不 vendor OpenClaw、OpenCode、Hermes Agent、AutoResearchClaw、任何第三方通道插件源码或第三方 skill 内容。

## 开发

改代码前请先读 [AGENTS.md](AGENTS.md)。当前可执行任务计划在 [.kiro/specs/auto-research-system/tasks.md](.kiro/specs/auto-research-system/tasks.md)。

常用检查：

```bash
python -m ruff check src tests
python -m mypy src/autoresearch
python -m pytest tests/smoke tests/unit -q
```

## 文档

- [研究计划](AutoResearch_System_Research_Plan.md)
- [实施计划](AutoResearch_System_Execution_Plan.md)
- [实现任务](.kiro/specs/auto-research-system/tasks.md)
- [发布门禁清单](docs/release-gate.md)
- [Agent 改动日志](Agent.md)
- [问题日志](Problem.md)
- [第三方声明](THIRD_PARTY_NOTICES.md)

## 许可证

AI-Researcher 使用 [Apache License 2.0](LICENSE)。署名信息和第三方参考说明见 [NOTICE](NOTICE) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
