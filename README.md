# AI-Researcher

[简体中文](README.zh-CN.md)

AI-Researcher is a V1.0 local/server research operator for evidence-first automated
computational research. It is designed to stay online, discover real sources, collect
inspiration, run bounded experiments, validate results, build LaTeX/PDF artifacts, and write
all durable memory back to an Obsidian-compatible Markdown vault.

It is not a paper-writing chatbot. The product goal is a governed research loop:
real retrieval, reproducible execution, evidence gates, review gates, publication-quality
artifacts, and controlled self-evolution.

![AI-Researcher operator console](docs/assets/readme/cli-monitor.svg)

## V1.0 Scope

V1.0 is a single-operator local/server release. It can run continuously on a workstation or
server after one guided setup. It is not a hosted multi-user SaaS, and it does not submit papers
automatically.

| Area | V1.0 behavior |
| --- | --- |
| Guided setup | `airesearcher setup` asks for model provider, base URL, model name, API key, WeChat QR or Feishu App credentials, optional real channel self-test, vault path, integration manifests, and slash templates. |
| Always-on loop | `airesearcher serve` and `airesearcher autopilot --watch` run a daily loop with online literature search, inspiration refresh, experiments, review, audit, paper build, and follow-up tasks. |
| Inspiration push | `--push-inspiration` sends a compact digest through setup-configured WeChat/Feishu channels. Missing delivery state is recorded as `skipped`, not faked. |
| Obsidian memory | `autoresearch-vault/` stores literature notes, inspiration notes, experiment records, evidence, issues, failures, skills, strategy cards, and paper summaries as Markdown. |
| Research-plan gate | After a user confirms a direction, `airesearcher research-plan` writes an execution-ready Markdown plan into the vault and a LaTeX/PDF plan under `outputs/<project-id>/research-plan/` before code-agent experiments start. |
| Paper artifacts | Markdown experience records stay in the vault; publication bundles and PDFs are copied to `outputs/<project-id>/`. |
| Code agent backend | OpenCode is supported as an external code-writing backend contract. AI-Researcher keeps validation, approval, commit, and rollback authority. |
| Communication adapters | OpenClaw-style channel metadata is kept as a runbook only. Third-party channel plugins are not vendored into this repository. |
| Publication gates | CCF-B/Q3-style claims are blocked unless source evidence, experiment records, reproduction checks, audit, paper build, and evidence gate all pass on real artifacts. |

## Install

Prerequisites:

- Python 3.10+
- Node.js 20+
- Git
- Optional: Obsidian for browsing the vault
- Optional: OpenCode for external code-generation tasks

```bash
git clone <your-repo-url>
cd AIResearch
python -m pip install -e .
npm install
npm run doctor
```

The Python CLI and the npm launcher call the same application:

```bash
airesearcher version
node ./bin/airesearcher.mjs version
```

## First Deployment

Run the guided setup wizard:

```bash
npm run setup
# or
airesearcher setup
```

The wizard walks through:

1. Choose a provider preset such as DeepSeek, OpenAI-compatible, SiliconFlow, or custom.
2. Confirm `AUTORESEARCH_LLM_BASE_URL`.
3. Enter `AUTORESEARCH_LLM_MODEL_NAME`.
4. Enter `AUTORESEARCH_LLM_API_KEY`.
5. Optionally configure WeChat by QR adapter onboarding, or Feishu/Lark with App ID and App Secret.
6. If a channel is enabled, choose whether setup should send a real delivery self-test immediately.
7. Initialize `autoresearch-vault/`.
8. Write integration runbooks under `integrations/`.
9. Write local slash command templates under `.airesearcher/commands/`.

The wizard writes local secrets and channel state to `.env`; users do not need to hand-edit that
file. Public examples live in `.env.example`. Never commit real API keys, webhook URLs, app
secrets, chat IDs, sessions, or tokens.

Recommended channel setup:

- Feishu/Lark: choose the App ID + App Secret mode in `airesearcher setup`. Add a home chat ID
  during setup if you already have it; otherwise message the bot and bind the home channel later
  through the adapter/gateway flow. When the channel is complete, the wizard can send a real
  self-test before it exits.
- WeChat/Weixin: choose QR setup. In the interactive wizard, AI-Researcher starts the QR adapter
  setup command immediately after writing config and waits for the scan/login result. If you know
  the OpenClaw message target, enter it during setup; otherwise bind it after pairing with
  `airesearcher channels bind-target --channel wechat --target <target>`. Non-interactive scripts record the setup state without
  blocking unless `--run-wechat-qr-setup` is passed. Once the QR login and target are ready, setup
  can send the same real self-test used by the 24h push gate.
- Webhook URLs remain available as a fallback for environments that already use incoming webhooks.

The guided wizard asks whether to send the channel delivery self-test during setup. For scripted
deployments, pass `--run-channel-test` to fail closed unless every enabled channel reports `sent`,
or `--skip-channel-test` to defer it. If you defer, run the same test before leaving the service
unattended:

```bash
npm run channel:test -- --channel feishu --require-sent
# or
airesearcher channels test --channel feishu --require-sent
# WeChat QR deployments can test real delivery after pairing a target:
airesearcher channels test --channel wechat --require-sent
```

Then run the strict prelaunch gate:

```bash
npm run prelaunch
# or
airesearcher readiness --push-inspiration --require-channel-config --require-channel-sent
```

This writes `.airesearcher/readiness/report.json` and confirms the daily loop, vault, output
path, model API, operator-channel configuration, and latest channel self-test delivery evidence
are ready. When a check is missing, the report includes `next_actions` with executable repair
commands.
The planned daily command uses the approval-gated `serve` runtime, not the lower-level direct
`autopilot` entry point.

Non-interactive setup is also supported:

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

## Start The 24h Operator

Recommended V1.0 command:

```bash
npm run serve
```

This is equivalent to:

```bash
airesearcher serve --permission-mode approve-dangerous --push-inspiration
```

`serve` stays alive by default. It checks the approval queue, runs approved cycles, waits
`86400` seconds between cycles, and records push status for the broad-inspiration digest.
In `approve-dangerous` mode, each cycle attempt gets its own approval request; use
`allow-all` only when you intentionally want unattended cycles without per-cycle approval.
The waiting output and `runtime list` show the per-cycle `action_id`, so operators can
see exactly which cycle is being approved.

The always-on research loop defaults to `pendigits_variance_calibrated_prototypes`, a real
UCI Pendigits public benchmark path with method-aligned literature queries and at least
1,000 validation rows. Use `--demo tabular_baseline` only for tiny local smoke runs.

In another terminal, approve the first dangerous cycle:

```bash
airesearcher runtime list
airesearcher runtime approve latest --approved-by operator
```

For a fully automatic trusted machine, use:

```bash
airesearcher serve --permission-mode allow-all --push-inspiration
```

Use `allow-all` only on a machine and project where online retrieval, local experiment execution,
LLM review, vault writes, and output writes are acceptable without per-cycle approval.

## Daily Retrieval And Inspiration Push

Use the daily autopilot loop directly when you do not need the approval service wrapper:

```bash
airesearcher autopilot --watch --cycles 0 --interval-seconds 86400 --push-inspiration
```

`autopilot` uses the same default public benchmark as `serve`; pass `--demo <id>` to choose
another benchmark or `--demo tabular_baseline` for the fast toy fixture.

Each cycle can run:

1. Source preflight and cooldown checks.
2. ArXiv and OpenAlex literature refresh. Semantic Scholar is optional and lower priority.
3. Source-backed similar-work and novelty checks.
4. Research-plan generation after the user confirms a direction.
5. Hugging Face and Hacker News broad inspiration refresh.
6. Local demo or public benchmark experiment.
7. Command-line reproduction check.
8. Optional live LLM evidence review.
9. Publication audit.
10. LaTeX paper build.
11. Physical evidence gate.
12. Obsidian review, issue, skill, and strategy updates.
13. Scheduler follow-up merge.
14. Optional WeChat/Feishu inspiration digest push.

V1.0 keeps broad inspiration API-first for reproducibility. PageAgent-style browser acquisition is
tracked as a future adapter for public pages without stable APIs, but it must pass robots/ToS,
rate-limit, isolated-browser-profile, snapshot evidence, action-log, and approval gates before
runtime enablement.

Single inspiration refresh with push:

```bash
airesearcher inspiration-refresh \
  --query "autonomous research agents datasets" \
  --vault autoresearch-vault \
  --output runs/inspiration/latest.json \
  --push \
  --push-channel feishu
```

If the selected channel lacks the required delivery state, the command records `skipped` in the JSON
output and does not claim delivery. Feishu App credentials can send directly when a home chat ID is
configured. WeChat QR setup writes `.airesearcher/channels/wechat/setup-status.json`; delivery
still depends on the QR adapter session being active.

## Operator Monitor

```bash
npm run monitor
# or
airesearcher monitor
```

The monitor shows recent agent messages, active file claims, release-critical cycle stages,
approval queue, open follow-up tasks, git changes, and output previews. Its flow table surfaces
source preflight, literature refresh, research plan, novelty/similarity, related work, citations,
experiment, reproduction, review, publication audit, paper build, evidence gate, follow-ups, and
deliverables with stage-specific artifact paths and paper-quality status. Useful options:

| Option | Purpose |
| --- | --- |
| `--watch` | Refresh the console continuously. |
| `--refresh-seconds <n>` | Refresh interval for watch mode. |
| `--no-diff` | Hide git diff preview for a clean status display. |
| `--cycle-summary <path>` | Inspect one specific cycle summary. |
| `--outputs-dir <path>` | Preview a custom output directory. |

## Slash Commands

Run once after setup if templates need to be regenerated:

```bash
airesearcher slash-commands init
airesearcher slash-commands list
```

The text after a slash command is passed into that template as `{{args}}`.

| Slash command | Typical args | Runs |
| --- | --- | --- |
| `/research:serve` | none | `airesearcher serve --permission-mode approve-dangerous --push-inspiration` |
| `/research:approve` | `latest` or `<request-id>` | Approves a queued dangerous action. |
| `/research:autopilot` | optional notes | Starts the daily autonomous loop with evidence gates. |
| `/research:refresh-literature` | optional topic | Runs real ArXiv/OpenAlex literature refresh. |
| `/research:inspiration-refresh` | query text | Searches broad inspiration sources and can push a digest. |
| `/research:similarity-check` | candidate context | Cross-checks a candidate against adjacent online work. |
| `/research:research-plan` | candidate JSON + project id | Writes the post-direction research plan to Obsidian and `outputs/`. |
| `/research:run-demo` | demo id | Runs a local demo or public benchmark. |
| `/research:publication-audit` | cycle summary path | Audits publication readiness. |
| `/research:publication-stability` | multiple cycle summaries | Checks stability across cycles/templates/datasets. |
| `/research:paper-build` | report path or template id | Builds LaTeX/PDF artifacts. |
| `/research:evidence-gate` | cycle summary path | Runs the physical release gate. |
| `/research:issue-followups` | project id | Lists open vault issues as scheduler tasks. |
| `/research:session-claim` | task/path info | Coordinates concurrent agent file claims. |
| `/research:obsidian-setup` | project id | Refreshes safe vault assets. |
| `/research:skill-evolve` | skill evidence | Creates bounded skill-evolution candidates. |
| `/research:skill-polish-audit` | skill id | Audits skill cards before promotion. |
| `/research:skill-watchlist` | none | Writes external research-skill candidates into the Obsidian quarantine watchlist. |
| `/research:channel-adapters` | none | Writes optional messaging adapter runbooks. |
| `/research:channel-test` | `wechat` or `feishu` | Sends a setup-channel self-test message. |
| `/research:readiness` | none | Writes the deployment readiness report before 24h operation. |
| `/research:code-agent-backends` | none | Writes OpenCode backend integration contracts. |
| `/research:scansci-pdf` | none | Writes OA-first PDF retrieval manifest. |
| `/research:status` | none | Shows local operator status guidance. |

## Key CLI Parameters

Common npm shortcuts:

| Script | Meaning |
| --- | --- |
| `npm run setup` | Guided first deployment. |
| `npm run channel:test -- --channel feishu --require-sent` | Real delivery self-test for a configured channel. |
| `npm run readiness -- --no-push-inspiration` | Local readiness report without requiring operator push. |
| `npm run prelaunch` | Strict prelaunch gate: model, vault, daily loop, channel config, and sent evidence. |
| `npm run serve` | Start the 24h operator with approval gates and inspiration push. |
| `npm run monitor` | Show the operator console. |

| Command | Parameter | Meaning |
| --- | --- | --- |
| `setup` | `--provider`, `--base-url`, `--model-name`, `--api-key` | Provider-agnostic LLM configuration. |
| `setup` | `--wechat --wechat-qr` | WeChat/Weixin QR adapter onboarding; interactive setup starts the scan flow, while non-interactive scripts can add `--run-wechat-qr-setup`. |
| `setup` | `--wechat-openclaw-target` | Optional OpenClaw WeChat message target used by real QR-mode self-tests and digest delivery. |
| `setup` | `--feishu --feishu-app-id --feishu-app-secret` | Feishu/Lark App credential setup; `--feishu-home-chat-id` enables direct digest delivery. |
| `setup` | `--wechat-webhook-url`, `--feishu-webhook-url` | Fallback incoming-webhook setup for existing deployments. |
| `setup` | `--run-channel-test`, `--skip-channel-test`, `--channel-test-output` | Send or defer the setup delivery self-test; a failed send writes JSON evidence before exiting nonzero. |
| `channels bind-target` | `--channel wechat [--target <target>]` | Bind the OpenClaw WeChat target after QR pairing without editing `.env`; prompts when `--target` is omitted. |
| `channels bind-target` | `--channel feishu [--target <chat-id>]` | Bind a Feishu/Lark home chat ID after the bot conversation creates one; prompts when `--target` is omitted. |
| `serve` | `--permission-mode approve-dangerous|allow-all` | Require approval for dangerous cycles or allow all. |
| `serve` | `--approval-poll-seconds 30` | Poll interval while waiting for dangerous-cycle approval; separate from the daily cycle interval. |
| `serve` / `autopilot` | `--demo pendigits_variance_calibrated_prototypes` | Default public benchmark for research cycles; use `tabular_baseline` only for smoke runs. |
| `serve` / `autopilot` | `--interval-seconds 86400` | Daily loop interval. |
| `serve` / `autopilot` | `--cycles 0` | Run forever when combined with watch mode. |
| `serve` / `autopilot` | `--push-inspiration` | Send the broad-inspiration digest to setup-configured operator channels. |
| `serve` / `autopilot` | `--max-queries`, `--max-results-per-source` | Search breadth. Lower only for smoke runs. |
| `serve` / `autopilot` | `--max-tokens` | Optional LLM reviewer cap. Omitted by default for long-context models. |
| `inspiration-refresh` | `--env-path .env` | Loads setup-written channel credentials for one-shot push. |
| `inspiration-refresh` | `--push`, `--push-channel`, `--push-timeout-seconds` | One-shot inspiration digest push. |
| `channels test` | `--channel`, `--require-sent`, `--output` | Sends a setup-channel self-test and records `sent`, `failed`, or `skipped`. |
| `readiness` | `--push-inspiration`, `--require-channel-config`, `--require-channel-sent`, `--output` | Writes the preflight report for unattended daily operation. |
| `research-plan` | `--candidate-file`, `--project-id`, `--vault`, `--output-dir` | Generates the Markdown/TEX/PDF research plan after direction approval. |
| `research-plan` | `--no-compile-pdf` | CI-friendly structural check; normal operator runs should compile the PDF. |
| `paper-build` | `--template-id` | Selects a registered LaTeX template. |
| `runtime approve` | `latest` or request id | Approves queued dangerous work. |

## Outputs And Repository Hygiene

Local runtime artifacts are intentionally ignored by git:

- `.env`
- `.airesearcher/`
- `.cache/`
- `runs/`
- `artifacts/`
- `outputs/`

The tracked repository should contain source code, tests, docs, integration manifests, templates,
license notices, and the safe Obsidian vault scaffold. Generated PDFs and large run bundles stay
local under `outputs/` unless a release process explicitly publishes them elsewhere.

## Obsidian Vault

`autoresearch-vault/` is the system memory substrate, not decoration. It stores:

- literature and source summaries;
- inspiration notes from non-scholarly sources;
- project progress and experiment records;
- evidence maps and validation summaries;
- review findings and follow-up issues;
- failure patterns;
- reusable skill cards;
- strategy cards with shadow-evaluation and rollback notes;
- paper-build summaries and archive Markdown.

Future cycles read the same vault before proposing new work, so self-looping and self-evolution
are grounded in durable Markdown rather than prompt-only memory.

## Publication Artifacts

Markdown records and project archive notes stay in `autoresearch-vault/`. Publication-targeted
artifacts are copied to:

```text
outputs/<project-id>/
```

A passing cycle can include:

- `research-plan/research-plan.md` in the vault
- `research-plan/research-plan.tex`
- `research-plan/research-plan.pdf`
- `research-plan/research-plan.json`
- `<project-id>-<cycle-id>.pdf`
- generated `.tex`
- `paper-build.json`
- `publication-audit.json`
- `evidence-gate.json`
- `cycle-summary.json`
- manifest `.json` and `.md`

Do not claim a paper is publication-ready just because a PDF exists. The release claim requires
the publication audit and evidence gate to pass on the same cycle artifacts.

## External References And Licenses

AI-Researcher references several open-source projects as design inspiration or optional ecosystem
integration points, including HKUDS AI-Researcher, AutoResearch, Horizon-style daily refreshers,
AutoResearchClaw, SkillOpt, OpenClaw channel plugins, OpenCode, Hermes Agent, Luban Skill style
guides, SimpleMem/Omni-SimpleMem, SkillClaw, Auto-Empirical Research Skills, paper-craft-skills,
oh-my-openagent/LazyCodex, PageAgent, citation-management, and Deep-Research-skills. External
skill and source-adapter ideas are first recorded with `airesearcher skill-watchlist` as
quarantined Obsidian candidates; they
are not installed, copied, or promoted until license, security, live-evidence, and rollback gates
pass.

Their license and incorporation status are tracked in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). This repository does not vendor OpenClaw,
OpenCode, Hermes Agent, AutoResearchClaw, oh-my-openagent/LazyCodex, PageAgent, channel plugin
source code, or third-party skill content.

## Development

Before changing code, read [AGENTS.md](AGENTS.md). The current executable plan is in
[.kiro/specs/auto-research-system/tasks.md](.kiro/specs/auto-research-system/tasks.md).

Useful checks:

```bash
python -m ruff check src tests
python -m mypy src/autoresearch
python -m pytest tests/smoke tests/unit -q
```

## Documentation

- [Research Plan](AutoResearch_System_Research_Plan.md)
- [Execution Plan](AutoResearch_System_Execution_Plan.md)
- [Implementation Tasks](.kiro/specs/auto-research-system/tasks.md)
- [Release Gate Checklist](docs/release-gate.md)
- [Agent Change Log](Agent.md)
- [Problem Log](Problem.md)
- [Third-Party Notices](THIRD_PARTY_NOTICES.md)

## License

AI-Researcher is licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and third-party reference notes.
