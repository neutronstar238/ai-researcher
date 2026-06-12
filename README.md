# AI-Researcher

[Simplified Chinese](README.zh-CN.md)

AI-Researcher is an early-stage Python platform for evidence-first automated computational research. The long-term goal is to orchestrate a constrained, auditable research loop: literature search, knowledge modeling, hypothesis generation, experiment design, sandboxed execution, result validation, paper drafting, review simulation, and controlled strategy evolution.

> Status: local MVP scaffold with tested research-loop components. The repository includes the executable task plan, Obsidian vault substrate, provider-agnostic deployment setup, local demo loop, literature/similarity retrieval foundations, validation/reporting modules, and release-preparation checks. It is not yet a production multi-user service.

## Why This Exists

Most automated research demos start with writing. This project starts with evidence. A result should only become a claim when the system can trace it back to a real run, configuration, metric file, source artifact, and validation status.

The core product idea is an Obsidian-compatible unified knowledge base stored under the project-root `autoresearch-vault/` directory. It acts as both human-readable research memory and machine-readable evolution substrate. Literature notes, project progress, issues, experiment records, failures, skills, evidence links, and strategy versions all live in one linked Markdown vault so the system can self-loop and self-improve without hiding its reasoning in an opaque database.

The first usable milestone is not a fully autonomous scientist. It is a minimal trusted research loop that can run a small computational experiment, collect outputs, validate them, and produce a reproducible Markdown report.

## Core Principles

- Evidence before claims.
- Reproducibility before autonomy.
- Human approval before high-cost, high-risk, or public actions.
- Sandboxed execution by default.
- Obsidian-compatible Markdown vault under `autoresearch-vault/` as the shared memory for research, failures, skills, and strategy evolution.
- Online literature and similar-work discovery are required at project start and during scheduled refresh; the vault stores source-backed summaries, not fabricated claims.
- Every experiment records run ID, commit, config hash, data hash, metrics, logs, artifacts, and cost.
- Every agent change is logged in [Agent.md](Agent.md).
- Every discovered blocker or risk is tracked in [Problem.md](Problem.md).

## Target Architecture

```mermaid
flowchart LR
    U["User / Reviewer"] --> CLI["CLI / future dashboard"]
    CLI --> MA["Main Agent"]
    MA --> LR["Literature Retriever"]
    MA --> PA["Project Agent"]
    MA --> VA["Validator Agents"]
    LR --> KB["Obsidian Knowledge Vault"]
    PA --> EXP["Experiment Tasks"]
    EXP --> SB["Sandbox Executor"]
    SB --> RB["Result Bundles"]
    RB --> VA
    VA --> REP["Reports / Paper Drafts"]
    VA --> FL["Failure and Skill Libraries"]
    FL --> EVO["Controlled Strategy Evolution"]
    EVO --> MA
```

## Roadmap

| Phase | Focus | Outcome |
|---|---|---|
| Phase 0 | Governance and engineering baseline | Agent rules, problem log, Obsidian vault contract, schemas, config, logging, smoke tests, minimal CLI |
| Phase 1 | Minimal trusted loop | Obsidian knowledge base, literature search, experiment execution, validation, and Markdown report |
| Phase 2 | Research assistant | Multi-agent workflow, evidence graph, paper draft, citation checks, review simulation |
| Phase 3 | Self-loop platform | Obsidian-backed candidate pool, scheduler, failure library, skill cards, monitoring, rollback |
| Phase 4 | Controlled self-evolution | Obsidian-backed strategy cards, offline replay, golden tests, shadow evaluation, gray release |
| Phase 5 | Product platform | Web dashboard, multi-user permissions, plugin system, deployment, compliance audit |

The executable task plan lives in [.kiro/specs/auto-research-system/tasks.md](.kiro/specs/auto-research-system/tasks.md).

## References and Design Inspirations

AI-Researcher is designed as an evidence-first system rather than a clone of any single project. Important references include:

- [HKUDS AI-Researcher](https://github.com/HKUDS/AI-Researcher) for the end-to-end scientific pipeline ambition and Scientist-Bench-style evaluation pressure. This repository treats it as a conceptual reference only: AI-Researcher focuses on an Obsidian-backed self-loop memory substrate, permissioned always-on operation, evidence graphs, real run records, and publication audits before paper claims.
- Long-horizon auto-research roadmaps and surveys such as [AI for Auto-Research](https://worldbench.github.io/awesome-ai-auto-research/) for evaluation pressure around hallucination, novelty checks, and reproducible artifacts.
- [Horizon](https://github.com/Thysrael/Horizon) and daily literature-update projects such as [agent-arxiv-daily](https://github.com/UltraClr/agent-arxiv-daily) for scheduled source discovery, scoring, digest, and delivery patterns.
- [Microsoft SkillOpt](https://github.com/microsoft/SkillOpt) for treating Markdown skill artifacts as optimizable external agent state with rollout evidence, bounded edits, validation gates, and deployable `best_skill.md` outputs.
- [OpenClaw](https://github.com/openclaw/openclaw) for the operator experience of a self-hosted assistant that is configured once and then runs as an always-on local service.

The license and attribution status for these references is tracked in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). They are design inspirations unless that notice file explicitly says code or assets were incorporated.

This repository's differentiator is the Obsidian-compatible vault as the shared evidence, issue, skill, and strategy substrate for self-looping research. Autonomy is added only where the loop can write auditable evidence and review artifacts.

## Obsidian Vault Setup

Structure the local vault with dashboards, templates, plugin recommendations, and a CSS snippet:

```bash
poetry run airesearcher obsidian-setup --vault autoresearch-vault --project-id autoresearch-system
```

Add `--write-local-snippet` on your own machine to also create `.obsidian/snippets/ai-researcher.css` and enable it in the local Obsidian appearance settings. Third-party Obsidian plugins are not bundled; see `autoresearch-vault/_system/plugins/recommended-plugins.md` after setup for optional manual installs such as Dataview, Tasks, Templater, Periodic Notes, and Omnisearch.

## Repository Layout

```text
.
├── AutoResearch_System_Research_Plan.md
├── AutoResearch_System_Execution_Plan.md
├── AGENTS.md
├── Agent.md
├── autoresearch-vault/
├── Problem.md
├── README.md
├── README.zh-CN.md
├── pyproject.toml
├── src/
│   └── autoresearch/
└── .kiro/
    └── specs/
        └── auto-research-system/
```

## Development Setup

Prerequisites:

- Python 3.10+
- Poetry
- Git

Install dependencies:

```bash
poetry install
```

First-deploy setup:

```bash
poetry run airesearcher deploy-setup
```

The guided setup asks for the LLM provider label, API base URL, model name, API key, and optional WeChat/Feishu channel credentials. API keys and channel secrets are written only to `.env`; `config.yaml` stores non-secret model and channel metadata plus environment variable names. If `.env.example` is missing, the CLI creates it as a public non-secret template.

If you prefer to fill the model configuration manually, copy `.env.example` to `.env` and set `AUTORESEARCH_LLM_BASE_URL`, `AUTORESEARCH_LLM_MODEL_NAME`, and `AUTORESEARCH_LLM_API_KEY`. You can also set `SEMANTIC_SCHOLAR_API_KEY` for higher Semantic Scholar Graph API limits, plus optional `SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS` and `SEMANTIC_SCHOLAR_CIRCUIT_RESET_SECONDS` values when a deployment needs stricter throttling. The root `.env` file is intentionally ignored by git and must never be committed.

For scripted deployment:

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

Project slash command templates:

```bash
poetry run airesearcher slash-commands init
poetry run airesearcher slash-commands list
```

This creates project-scoped TOML templates under `.airesearcher/commands/`, including `/research:refresh-literature`, `/research:similarity-check`, `/research:run-demo`, `/research:autopilot`, `/research:serve`, `/research:publication-audit`, `/research:approve`, `/research:openclaw-channels`, `/research:obsidian-setup`, `/research:issue-followups`, and `/research:status`.

Always-on runtime:

```bash
poetry run airesearcher serve --permission-mode approve-dangerous
```

This is the preferred one-command operator entry point for a 24h local/server deployment. It sits on top of the existing autopilot cycle but queues dangerous actions in `.airesearcher/runtime-approvals.json` before running online discovery, experiments, live review, or vault writes. Trusted single-user deployments can use `--permission-mode allow-all`; safer deployments should keep `approve-dangerous` and approve pending work from a local terminal or a chat-channel adapter:

```bash
poetry run airesearcher runtime list
poetry run airesearcher runtime approve latest --approved-by operator
```

OpenClaw communication channel mounts:

```bash
poetry run airesearcher channels openclaw init
poetry run airesearcher channels openclaw list
```

This writes `integrations/openclaw/channels.json`, a repository runbook for mounting official/common OpenClaw channel plugins onto AI-Researcher. The manifest covers Lark/Feishu (`@larksuite/openclaw-lark`), Weixin/WeChat (`npx -y @tencent-weixin/openclaw-weixin-cli install` / `@tencent-weixin/openclaw-weixin`), WeCom (`@wecom/wecom-openclaw-plugin`), and OpenClaw-documented channels such as Telegram, Discord, Slack, WhatsApp, Microsoft Teams, QQ Bot, Signal, and Zalo. Channel plugins are not vendored here; install them inside an OpenClaw deployment after reviewing upstream permissions and storing secrets outside git.

Chat adapters should map `/approve` to:

```bash
poetry run airesearcher runtime approve latest --state .airesearcher/runtime-approvals.json --approved-by <operator>
```

Autopilot one-command loop:

```bash
poetry run airesearcher autopilot --watch --cycles 0 --interval-seconds 86400
```

After `deploy-setup`, this keeps the local loop running directly. Each cycle performs live literature refresh, source-backed similarity checking, a local ScientistBench-Lite experiment, optional live LLM evidence review, publication-readiness audit, Obsidian review/issue writing, and local follow-up state merging. Use `--no-review` for offline dry runs, or omit `--watch` for a single cycle. The current loop produces a reproducible evidence-backed report and review trail; the publication audit is deliberately strict and will reject toy-data cycles as not CCF-B/Q3-ready.

Skill evolution candidates:

```bash
poetry run airesearcher skill-evolve \
  --parent-skill-id skill_evidence_bound_review \
  --issue-ref projects/autoresearch-system/issues/example_issue \
  --change-summary "Tighten the evidence bundle before live review." \
  --proposed-action "Attach run-record evidence before review." \
  --validation-check "Held-out review has zero unsupported reproduction claims."
```

This is SkillOpt-inspired but conservative: it writes a candidate skill card and rejected-edit buffer under the Obsidian vault. It does not overwrite or promote the parent skill; promotion still needs held-out validation and human review.

Online discovery commands:

```bash
poetry run airesearcher literature-refresh --vault autoresearch-vault --cache .cache/literature --max-queries 1 --max-results-per-source 1
poetry run airesearcher similarity-check --candidate-file candidate.json --vault autoresearch-vault --cache .cache/literature --project-id my_project
```

Both commands use real literature APIs by default, load optional literature API keys from `.env`, apply conservative Semantic Scholar rate limiting with tunable request spacing and 429 circuit breaking, preserve per-source fetch errors, and write guarded Obsidian summaries that keep unsupported outcomes as `unknown` or `pending verification`.

Live LLM smoke and output quality gate:

```bash
poetry run airesearcher llm-smoke --config config.yaml --env-path .env --output runs/llm-smoke/latest.json
```

This calls the configured OpenAI-compatible model, requires structured JSON output, checks evidence-policy language, verifies no API key leakage, and writes a local quality report under `runs/`.

LLM-as-reviewer with local evidence:

```bash
poetry run airesearcher llm-review \
  --subject runs/manual-live/demo/tabular-baseline/report/report.md \
  --evidence runs/manual-live/demo/tabular-baseline/validation/validation-report.json \
  --evidence runs/manual-live/demo/tabular-baseline/evidence/evidence-map.json \
  --config config.yaml \
  --env-path .env \
  --output runs/llm-review/latest.json \
  --max-tokens 4096 \
  --vault autoresearch-vault \
  --project-id demo_project
```

The reviewer can use the configured live model, but the deterministic gate requires every finding to cite provided local evidence IDs such as `evidence_1`; missing or unknown evidence references fail below the quality threshold. Passing reviews can be written back to `autoresearch-vault/projects/<project-id>/review/` as Obsidian `review_note` entries, and actionable warning/blocking findings become stable-fingerprinted `issue_note` entries under `autoresearch-vault/projects/<project-id>/issues/`. Repeated reviews update the same issue note for the same subject and claim instead of polluting the self-loop issue pool with duplicates. `airesearcher issue-followups --state .airesearcher/scheduler-state.json` can persist reviewable local follow-up task records without executing them automatically, and `airesearcher scheduler-state list|complete|remove` lets operators inspect, finish, or clean those records without hand-editing JSON. Reasoning models may need the higher review token budget shown above.

Publication-level quality audit:

```bash
poetry run airesearcher publication-audit runs/autopilot/<cycle-id>/cycle-summary.json \
  --target ccf-b \
  --vault autoresearch-vault \
  --project-id demo_project
```

This is a higher bar than `llm-review`: it checks whether the cycle actually executed script/data artifacts, whether validated data are strong enough, whether cross-source literature and similar-work search are broad enough, whether source failures such as Semantic Scholar 429s reduce novelty coverage, whether the report has paper-level sections, and whether baseline/ablation/statistical sanity evidence exists. `ccf-b` and `q3-journal` targets reject synthetic ScientistBench-Lite toy runs by design. Failed audits write `publication-audit` review and issue notes into the Obsidian project memory so the self-loop can queue follow-up work.

Run the local quality gate:

```bash
python scripts/check.py
```

This mirrors the default CI gates: `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/smoke tests/unit`. The default `test_cli.py` and `test_imports.py` smoke checks are local installation/import checks; only the explicitly named live smoke tests below contact external APIs.

Run live smoke tests after `.env` is configured:

```bash
AUTORESEARCH_LIVE_APIS=1 poetry run pytest tests/smoke/test_llm_live.py tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py tests/smoke/test_similarity_live.py -vv
```

## Documentation

- [Research Plan](AutoResearch_System_Research_Plan.md): research scope, architecture, agent model, verification model, risk matrix, and long-term roadmap.
- [Execution Plan](AutoResearch_System_Execution_Plan.md): phased implementation plan, milestones, schemas, testing strategy, cost model, and release gates.
- [Kiro Requirements](.kiro/specs/auto-research-system/requirements.md): original requirements for the Obsidian knowledge base, agent evolution, knowledge evolution, and project permissions.
- [Kiro Design](.kiro/specs/auto-research-system/design.md): original design details for Obsidian vault structure, knowledge APIs, access control, and implementation priorities.
- [Implementation Tasks](.kiro/specs/auto-research-system/tasks.md): detailed executable task list.
- [Agent Change Log](Agent.md): required change log for every coding agent.
- [Problem Log](Problem.md): issue, blocker, and risk register.
- [Changelog](CHANGELOG.md): unreleased release notes, migration notes, and known problems.
- [Release Gate Checklist](docs/release-gate.md): required checks before release tags, demos, or production-ready claims.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full setup, task workflow, testing, and review guide.

Before changing files:

1. Read [AGENTS.md](AGENTS.md).
2. Check the current task in [.kiro/specs/auto-research-system/tasks.md](.kiro/specs/auto-research-system/tasks.md).
3. Review open items in [Problem.md](Problem.md).
4. Make the smallest change that satisfies the task.
5. Run the relevant verification command.
6. Append your change summary to [Agent.md](Agent.md).

## License

AI-Researcher is licensed under the [Apache License 2.0](LICENSE). The SPDX identifier is `Apache-2.0`. See [NOTICE](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and third-party reference notes.
