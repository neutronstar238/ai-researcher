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
| Guided setup | `airesearcher setup` asks for model provider, base URL, model name, API key, WeChat QR or Feishu App credentials, default-on real channel self-test, vault path, integration manifests, slash templates, and the default editable Agent team bundle. |
| Always-on loop | `airesearcher serve` and `airesearcher autopilot --watch` run a daily loop with online literature search, inspiration refresh, experiments, review, audit, paper build, and follow-up tasks. |
| Inspiration push | `--push-inspiration` sends a compact digest through setup-configured WeChat/Feishu channels. Missing delivery state is recorded as `skipped`, not faked. |
| Obsidian memory | `autoresearch-vault/` stores literature notes, inspiration notes, experiment records, evidence, issues, failures, skills, strategy cards, and paper summaries as Markdown. |
| Research-plan gate | After a user confirms a direction, `airesearcher research-plan` writes an execution-ready Markdown plan into the vault and a LaTeX/PDF plan under `outputs/<project-id>/research-plan/` before code-agent experiments start. |
| Closed-loop campaign | Each approved direction becomes a protocol-as-code campaign with measurable goals, budget, candidates, baselines, stop criteria, DOE/evidence-gain candidate selection, loop metrics, and rollback-aware quality gates. |
| Paper artifacts | Markdown experience records stay in the vault; publication bundles and PDFs are copied to `outputs/<project-id>/`. |
| Code agent backend | OpenCode is supported as an external code-writing backend contract. AI-Researcher keeps validation, approval, commit, and rollback authority. |
| Agent profiles | `airesearcher agents profile write`, `agents profile import`, `agents profile import-set`, `agents profile team-attach`, `agents profile inspect-set`, and `agents profile team-template` bind custom skills and MCP servers to named agents; `serve` and `autopilot` load either per-agent profiles with repeatable `--agent-profile <json>` or a reusable team bundle with `--agent-profile-set-bundle <team.yaml>`, then record the materialized profile evidence in each cycle. |
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
6. If a channel is enabled, confirm the default real delivery self-test or explicitly skip it.
7. Initialize `autoresearch-vault/`.
8. Write integration runbooks under `integrations/`.
9. Write local slash command templates under `.airesearcher/commands/`.
10. Write the editable default Agent team bundle under `.airesearcher/agents/ccfb-team.yaml`.

The wizard writes local secrets and channel state to `.env`; users do not need to hand-edit that
file. Public examples live in `.env.example`. Never commit real API keys, webhook URLs, app
secrets, chat IDs, sessions, or tokens.

After setup, `npm run serve` auto-loads the generated bundle when no explicit Agent profile or
team bundle is supplied, and it turns on the profile-set coverage gate for that default team. Pass
`--skip-agent-team` during setup only when a deployment already has a reviewed custom team bundle.
Run `npm run agent-team:inspect` before the first unattended start to preview the generated
skills, MCP contracts, readiness, and stage coverage.

Recommended channel setup:

- Feishu/Lark: choose the App ID + App Secret mode in `airesearcher setup`. Add a home chat ID
  during setup if you already have it; otherwise message the bot and bind the home channel later
  through the adapter/gateway flow. When the channel is complete, the wizard defaults to sending a
  real self-test before it exits.
- WeChat/Weixin: choose QR setup. In the interactive wizard, AI-Researcher starts the QR adapter
  setup command immediately after writing config and waits for the scan/login result. If you know
  the OpenClaw message target, enter it during setup; otherwise bind it after pairing with
  `airesearcher channels bind-target --channel wechat --target <target>`. Non-interactive scripts record the setup state without
  blocking unless `--run-wechat-qr-setup` is passed. Once the QR login and target are ready, setup
  defaults to sending the same real self-test used by the 24h push gate.
- Webhook URLs remain available as a fallback for environments that already use incoming webhooks.

The guided wizard asks whether to send the channel delivery self-test during setup and defaults to
Yes when a channel is enabled. For scripted deployments, pass `--run-channel-test` to fail closed
unless every enabled channel reports `sent`, or `--skip-channel-test` to defer it. If you defer,
run the same test before leaving the service unattended. If the self-test finds a missing WeChat
OpenClaw target or Feishu home chat ID, the CLI prints the matching `channels bind-target` command
so the operator can finish setup without editing `.env` by hand:

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
path, model API, setup-generated Agent team, operator-channel configuration, and latest channel
self-test delivery evidence are ready. When a check is missing, the report includes `next_actions`
with executable repair commands.
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

`serve` and `autopilot` automatically emit stage heartbeats into a local state file and
embed the watchdog report in each cycle summary and review evidence bundle. Operators can
inspect one cycle with `airesearcher runtime heartbeat check --run-id <cycle-id>`. The
heartbeat watchdog detects stale stages and repeated progress signatures, then recommends
inspection or repair/pivot before the loop keeps spending budget. Heartbeat reports are
runtime health evidence only; they do not prove scientific results, citations, tool calls,
novelty, or publication readiness.

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

Per-agent custom skill and MCP profiles can be attached to either runtime entry point:

```bash
airesearcher agents profile write \
  --agent-id literature-agent \
  --role project_agent \
  --stage literature \
  --stage similarity \
  --skill source-tracing=autoresearch-vault/_system/templates/skill-card.md \
  --skill-policy source-tracing:approved_runtime \
  --mcp "page-agent=npx -y page-agent" \
  --mcp-tool page-agent:browser.search \
  --mcp-tool page-agent:browser.open \
  --mcp-approval page-agent:approve_dangerous \
  --mcp-env-key page-agent:PAGE_AGENT_TOKEN \
  --output .airesearcher/agents/literature-agent.json

airesearcher agents profile validate \
  .airesearcher/agents/literature-agent.json \
  --env-path .env \
  --output .airesearcher/agents/literature-agent-readiness.json

airesearcher serve \
  --agent-profile .airesearcher/agents/literature-agent.json \
  --agent-profile .airesearcher/agents/reviewer-agent.json
```

For repeatable team deployments, the same profile can be imported from a JSON/YAML/TOML bundle:

```yaml
agent_id: literature-agent
role: project_agent
thinking_mode: scientific
publication_target: ccf-b-or-sci-q2
assigned_stages: [literature, similarity, research_plan]
thinking_contract_additions:
  - Prefer falsifiable research claims over software architecture metaphors.
skills:
  - skill_id: source-tracing
    source: autoresearch-vault/_system/templates/skill-card.md
    import_policy: approved_runtime
mcp_servers:
  - server_id: page-agent
    command: npx -y page-agent
    allowed_tools: [browser.search, browser.open]
    approval_policy: approve_dangerous
    env_keys: [PAGE_AGENT_TOKEN]
```

```bash
airesearcher agents profile import literature-agent.yaml \
  --output .airesearcher/agents/literature-agent.json
```

Loaded profiles are written into `cycle-summary.json`, `review-evidence-context.json`, and the
operator monitor. Optional `--stage` values bind one profile to loop stages such as `literature`,
`similarity`, `research_plan`, `loop_campaign`, `experiment`, `review`, `publication_audit`, and
`evidence_gate`, so audit records show which agent carried which scientific responsibility.
`cycle-summary.json` also includes `stage_runtime_contexts`, and `review-evidence-context.json`
includes `stage_agent_contexts`, so downstream stage workers can consume only the bounded skill/MCP
context assigned to that stage. Profiles still provide method/tool context only; publication claims
require the normal evidence, reproduction, review, paper-build, and release gates. The LLM reviewer
is instructed to treat profile and stage context as process metadata, not as proof of scientific
results, tool invocation, novelty, or publication readiness; the local reviewer quality gate also
blocks findings that try to use profile context for those claims. Runtime profile contexts carry
`context_kind=agent_profile_process_metadata` plus a machine-readable evidence policy so later
stages do not have to infer this boundary from prose.

Use `--skill-policy <skill_id>:read_only_context|shadow_evaluation|approved_runtime` to
declare how a bound skill may affect an agent, and use
`--mcp-approval <server_id>:read_only|approve_dangerous|allow_all` plus
`--mcp-env-key <server_id>:ENV_KEY` to declare per-server approval and required environment
variable names. These flags must reference skills or MCP servers bound in the same command.
`--mcp-env-key` stores only uppercase environment variable names, never secret values.
Run `agents profile validate` before unattended runtime use to check local skill source paths and
required MCP environment variable names. The readiness report is written into runtime profile
contexts, `cycle-summary.json`, `review-evidence-context.json`, monitor rows, and CLI status. It
checks profile inputs only; it does not prove that an MCP tool was invoked, that external skill
content was safe, or that a scientific claim is supported.

For multi-agent deployments, run `agents profile set-validate <profiles...>` before `serve` or
`autopilot`. It builds a stage coverage matrix for the CCF-B/Q2 research loop, checks each
profile's readiness report, blocks missing literature/plan/experiment/reproduction/citation/review
responsibility, and warns about `allow_all` MCP bindings or unassigned profiles. This is a team
configuration gate only; it still cannot prove scientific claims or publication readiness.

If a deployment should be shared as one team file, use
`agents profile import-set <team.yaml> --output-dir .airesearcher/agents`. The bundle reuses the
single-Agent import schema under `profiles:`, writes one standard profile JSON per agent, writes
`profile-set-validation.json`, and exits nonzero by default when the bundle's required stages are
not fully covered. Use `--allow-incomplete` only for debugging or partial rollout dry runs.
To bootstrap a complete editable team file, run
`agents profile team-template --output .airesearcher/agents/ccfb-team.yaml`. It writes a default
three-Agent CCF-B/Q2 team plus local skill Markdown files for source tracing, experiment protocol,
and evidence review.
Before importing or starting the runtime, run
`agents profile inspect-set .airesearcher/agents/ccfb-team.yaml --materialize-skills --require-complete`
to preview every Agent's bounded skill context, MCP runtime contract, readiness result, and stage
coverage directly from the reusable bundle.
To assign a new skill or MCP server to a specific team member without hand-editing YAML, run
`agents profile team-attach .airesearcher/agents/ccfb-team.yaml --agent-id experiment-agent --skill research-architect=skills/research-architect.md`
and then inspect the bundle again. `team-attach` supports the same `--skill`, `--skill-policy`,
`--stage`, `--mcp`, `--mcp-tool`, `--mcp-approval`, and `--mcp-env-key` grammar as single-Agent
profiles.
For unattended runs, `serve` and `autopilot` can also load the same reusable team file directly
with repeatable `--agent-profile-set-bundle <team.yaml>` flags. Each cycle materializes the bundle
into `agent-profile-bundles/`, resolves relative local skill paths against the bundle file location,
then runs the same readiness, stage coverage, context packet, review evidence, and optional
`--require-agent-profile-set` gates as ordinary `--agent-profile` inputs. This materialization is
process metadata only; it proves responsibility routing, not scientific validity.

When a loaded profile points at a local skill file or a directory containing `SKILL.md`, the runtime
materializes a bounded skill excerpt into stage contexts with `status`, `sha256`, byte/character
counts, `max_chars`, and a truncation flag. The compact profile summary records only provenance and
status, while `stage_runtime_contexts` and `stage_agent_contexts` carry the bounded content for the
assigned worker. Non-local sources stay as references, and secret-like local files are marked
`blocked` without copying their content into artifacts. To preview exactly what an agent would
receive, run `agents profile inspect --materialize-skills --base-dir . <profile.json>`.
During `serve` and `autopilot`, AI-Researcher also writes portable packet files under each cycle's
`agent-stage-contexts/` directory. Each packet contains only the agents assigned to that stage, the
bounded skill excerpts, MCP contracts, readiness summary, and an explicit process-metadata evidence
policy.
The same directory now includes `assignment-manifest.json`, a compact cross-stage manifest that
lists each stage's assigned Agent IDs, skill IDs, materialized skill hashes, MCP server IDs, and MCP
contract hashes without copying skill content. It is designed for review and publication gates to
audit responsibility routing; it still cannot prove that a tool was invoked or that a scientific
claim is true.
The same cycle also writes `agent-profile-set/agent-profile-set-validation.json` so publication
reviewers can see whether the loaded Agent team covers the default CCF-B/Q2 research-stage matrix.
Use `--require-agent-profile-set` to stop a cycle before online retrieval when that matrix is
incomplete.

MCP bindings also emit `mcp_runtime_contracts`. A contract records the command hash, allowed tools,
approval policy, required env-key names, and whether runtime approval or isolated operator approval
is required. It never records env values and it is still process metadata: an MCP contract proves
what the agent was allowed to use, not that a tool was actually invoked or that a result is true.

When an MCP-backed worker actually calls a tool, record a separate JSONL ledger entry with
`agents mcp-evidence add`. The ledger stores hashed request/response artifact refs, status,
approval linkage, and a short non-secret result summary. It deliberately does not inline raw tool
payloads, and `agents mcp-evidence validate` checks every record against the owning profile's MCP
allowlist before the record can be used as process evidence.

Each cycle can run:

1. Source preflight and cooldown checks.
2. ArXiv and OpenAlex literature refresh. Semantic Scholar is optional and lower priority.
3. Source-backed similar-work and novelty checks.
4. Research-plan generation after the user confirms a direction.
5. Closed-loop campaign initialization and DOE/active-learning candidate selection.
6. Hugging Face and Hacker News broad inspiration refresh.
7. Local demo or public benchmark experiment.
8. Command-line reproduction check.
9. Optional live LLM evidence review.
10. Loop report generation with AF, EF, reproduction delta, metadata completeness, failure recovery, and evidence coverage.
11. Publication audit.
12. LaTeX paper build.
13. Physical evidence gate.
14. Obsidian review, issue, skill, and strategy updates.
15. Scheduler follow-up merge.
16. Optional WeChat/Feishu inspiration digest push.

The campaign artifact is treated as protocol-as-code. `loop-campaign.json` records the data
sources, baselines, protocol artifacts, candidate arms, selected optimizer policy, optimizer state,
metrics, quality gate, `contract_validation`, and a deterministic `stop_decision`.
`contract_validation` checks that the campaign declares its objective, metric, budget, data sources,
baselines, protocol artifacts, candidate space, stop criteria, approval policy, evidence
requirements, and the rule that LLM proposals cannot bypass or override gates. The first iteration is
a DOE baseline; later iterations write an active-learning/UCB-like score table with exploitation,
uncertainty, cost, risk, frozen-dimension penalties, and `llm_override_allowed=false`. A failed loop
is not allowed to retry indefinitely: if metadata, evidence, reproduction, budget, approval,
protocol-contract, or repeated-failure checks block the next step, the report records the frozen
dimensions and the repair action required before another candidate can run. Release and publication
gates require `contract_validation.passed=true` in addition to loop metrics and evidence coverage.
Strategy promotion uses the same Loop Engineering metrics: AF, EF, metadata completeness,
reproduction delta, failure recovery, and evidence coverage must not regress before a shadow
strategy can enter gray release.

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

The monitor shows recent agent messages, active file claims, loaded agent profiles, release-critical
cycle stages, approval queue, open follow-up tasks, git changes, and output previews. Its flow table surfaces
source preflight, literature refresh, research plan, closed-loop campaign, novelty/similarity,
related work, citations, experiment, reproduction, review, publication audit, paper build,
evidence gate, follow-ups, and deliverables with stage-specific artifact paths and paper-quality
status. Useful options:

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
| `/research:similarity-check` | candidate context | Cross-checks a candidate against adjacent online work and writes the novelty breadth matrix. |
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
| `/research:agent-profile` | agent id + skill/MCP refs | Creates a bounded per-agent profile for custom skills and MCP tools. |
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
| `npm run agent-team:inspect` | Preview the setup-generated Agent team bundle before the first unattended run. |
| `npm run channel:test -- --channel feishu --require-sent` | Real delivery self-test for a configured channel. |
| `npm run readiness -- --no-push-inspiration` | Local readiness report without requiring operator push. |
| `npm run prelaunch` | Strict prelaunch gate: model, vault, daily loop, setup Agent team, channel config, and sent evidence. |
| `npm run serve` | Start the 24h operator with approval gates, inspiration push, and auto-loading of the setup-generated Agent team when present. |
| `npm run monitor` | Show the operator console. |

| Command | Parameter | Meaning |
| --- | --- | --- |
| `setup` | `--provider`, `--base-url`, `--model-name`, `--api-key` | Provider-agnostic LLM configuration. |
| `setup` | `--wechat --wechat-qr` | WeChat/Weixin QR adapter onboarding; interactive setup starts the scan flow, while non-interactive scripts can add `--run-wechat-qr-setup`. |
| `setup` | `--wechat-openclaw-target` | Optional OpenClaw WeChat message target used by real QR-mode self-tests and digest delivery. |
| `setup` | `--feishu --feishu-app-id --feishu-app-secret` | Feishu/Lark App credential setup; `--feishu-home-chat-id` enables direct digest delivery. |
| `setup` | `--wechat-webhook-url`, `--feishu-webhook-url` | Fallback incoming-webhook setup for existing deployments. |
| `setup` | `--run-channel-test`, `--skip-channel-test`, `--channel-test-output` | Send or defer the setup delivery self-test; interactive setup defaults to sending it, and a failed send writes JSON evidence before exiting nonzero. |
| `setup` | `--agent-team-bundle`, `--skip-agent-team`, `--overwrite-agent-team` | Write, skip, or refresh the default editable Agent team bundle that setup wires into the recommended `serve` command. |
| `channels bind-target` | `--channel wechat [--target <target>]` | Bind the OpenClaw WeChat target after QR pairing without editing `.env`; prompts when `--target` is omitted. |
| `channels bind-target` | `--channel feishu [--target <chat-id>]` | Bind a Feishu/Lark home chat ID after the bot conversation creates one; prompts when `--target` is omitted. |
| `serve` | `--permission-mode approve-dangerous|allow-all` | Require approval for dangerous cycles or allow all. |
| `serve` | `--approval-poll-seconds 30` | Poll interval while waiting for dangerous-cycle approval; separate from the daily cycle interval. |
| `serve` / `autopilot` | `--demo pendigits_variance_calibrated_prototypes` | Default public benchmark for research cycles; use `tabular_baseline` only for smoke runs. |
| `serve` / `autopilot` | `--interval-seconds 86400` | Daily loop interval. |
| `serve` / `autopilot` | `--cycles 0` | Run forever when combined with watch mode. |
| `serve` / `autopilot` | `--push-inspiration` | Send the broad-inspiration digest to setup-configured operator channels. |
| `serve` / `autopilot` | `--max-queries`, `--max-results-per-source` | Search breadth for literature, similarity, and novelty-breadth artifacts. Lower only for smoke runs. |
| `serve` / `autopilot` | automatic novelty-breadth stage | Runs broad inspiration refresh before research planning, then records query/source/finding breadth in `cycle-summary.json` and the cycle artifact directory. |
| `similarity-check` | `--max-queries`, `--max-results-per-source` | Controls project-start novelty search breadth; outputs Obsidian Markdown plus `*_novelty_breadth.json`. |
| `serve` / `autopilot` | `--max-tokens` | Optional LLM reviewer cap. Omitted by default for long-context models. |
| `serve` / `autopilot` | `--heartbeat-state` | Override the automatically written runtime heartbeat state path. |
| `serve` / `autopilot` | `--agent-profile <profile.json>` | Load one validated per-agent skill/MCP profile into the cycle summary, review evidence, monitor, profile-set validation, and per-cycle `agent-stage-contexts/` packet artifacts. Repeat for multiple agents. |
| `serve` / `autopilot` | `--agent-profile-set-bundle <team.yaml>` | Materialize one reusable multi-Agent team bundle into per-cycle profile JSON artifacts, then load them through the same readiness, profile-set validation, stage-context packet, and review-evidence path. Repeat for multiple bundles. |
| `serve` / `autopilot` | `--default-agent-team`, `--no-default-agent-team` | Auto-load `.airesearcher/agents/ccfb-team.yaml` when no explicit Agent profiles or bundles are supplied, or disable that setup-generated default. |
| `serve` / `autopilot` | `--require-agent-profile-set` | Blocks the cycle before online retrieval unless loaded Agent profiles cover the default CCF-B/Q2 stage matrix. Without this flag, the validation report is still written as audit metadata. |
| `inspiration-refresh` | `--env-path .env` | Loads setup-written channel credentials for one-shot push. |
| `inspiration-refresh` | `--push`, `--push-channel`, `--push-timeout-seconds` | One-shot inspiration digest push. |
| `channels test` | `--channel`, `--require-sent`, `--output` | Sends a setup-channel self-test and records `sent`, `failed`, or `skipped`. |
| `readiness` | `--push-inspiration`, `--require-channel-config`, `--require-channel-sent`, `--require-agent-team`, `--output` | Writes the preflight report for unattended daily operation, including the setup-generated Agent team gate when required. |
| `agents profile write` | `--agent-id`, `--stage`, `--skill`, `--skill-policy`, `--mcp`, `--mcp-tool`, `--mcp-approval`, `--mcp-env-key`, `--vault`, `--project-id` | Binds custom skills, MCP servers, optional loop-stage responsibility, and per-agent tool policy to one agent. MCP tools must be explicitly allowlisted and secrets stay in env vars. |
| `agents profile import` | bundle `.json/.yaml/.toml`, `--output`, `--vault`, `--project-id` | Converts a reusable declarative Agent bundle into the same profile JSON used by `validate`, `inspect`, `serve`, and `autopilot`. The default scientific thinking contract is preserved and bundle additions are appended. |
| `agents profile import-set` | profile-set bundle `.json/.yaml/.toml`, `--output-dir`, `--validation-output`, `--base-dir`, `--vault`, `--project-id`, `--allow-incomplete` | Converts a reusable multi-Agent bundle into one profile JSON per agent plus a profile-set validation report; exits nonzero by default when required research stages are missing or readiness fails. |
| `agents profile team-attach` | profile-set bundle, `--agent-id`, `--skill`, `--skill-policy`, `--stage`, `--mcp`, `--mcp-tool`, `--mcp-approval`, `--mcp-env-key`, `--output`, `--replace-existing` | Adds custom skill, MCP, or stage bindings to one named Agent inside a reusable team bundle, then validates readiness and stage coverage. |
| `agents profile inspect-set` | profile-set bundle `.json/.yaml/.toml`, `--materialize-skills`, `--base-dir`, `--env-path`, `--output`, `--require-complete` | Previews a reusable multi-Agent team bundle without importing it; reports each Agent runtime context, bounded local skill hashes, MCP contracts, readiness, and stage coverage. |
| `agents profile team-template` | `--output`, `--skill-dir`, `--profile-set-id`, `--overwrite` | Writes an editable default three-Agent CCF-B/Q2 team bundle and local skill Markdown files that can be loaded directly with `--agent-profile-set-bundle`. |
| `agents profile validate` | profile JSON path, `--env-path`, `--base-dir`, `--output` | Checks local skill source paths and required MCP environment variable names; writes readiness JSON and exits nonzero on missing required inputs. |
| `agents profile set-validate` | profile JSON paths, `--required-stage`, `--env-path`, `--base-dir`, `--output` | Validates a multi-Agent skill/MCP profile set as a research-stage coverage matrix before unattended runs; exits nonzero on missing required stages, duplicate agents, readiness failures, or non-research/evidence-first thinking contracts. |
| `agents profile inspect` | profile JSON path, `--materialize-skills`, `--base-dir`, `--max-skill-chars` | Prints the runtime context that will be attached to that agent, including MCP runtime contracts; optionally includes bounded local skill content with hashes and truncation metadata. |
| `agents profile export-stage-context` | profile JSON paths, `--stage`, `--base-dir`, `--output`, `--project-id`, `--cycle-id` | Exports the bounded skills/MCP context packet for agents assigned to one loop stage; defaults to failing when no agent is assigned or readiness fails. |
| `agents mcp-evidence add/list/validate` | `--profile`, `--ledger`, `--project-id`, `--cycle-id`, `--server-id`, `--tool-name`, request/response artifact refs | Records and validates hashed MCP tool invocation evidence. This proves a named agent recorded a named tool call, not that scientific claims are true. |
| `research-plan` | `--candidate-file`, `--project-id`, `--vault`, `--output-dir` | Generates the Markdown/TEX/PDF research plan after direction approval. |
| `research-plan` | `--no-compile-pdf` | CI-friendly structural check; normal operator runs should compile the PDF. |
| `paper-build` | `--template-id` | Selects a registered LaTeX template. |
| `runtime approve` | `latest` or request id | Approves queued dangerous work. |
| `runtime heartbeat write` | `--run-id`, `--stage`, `--progress`, `--artifact-ref`, `--state` | Records one stage progress signal for long-running loop watchdogs. |
| `runtime heartbeat check` | `--state`, `--run-id`, `--stale-after-seconds`, `--stall-repetition-threshold`, `--output` | Writes a heartbeat watchdog report and exits nonzero when a loop stage is stale or stalled. |

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
- per-agent custom skill and MCP profiles;
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
- `loop-campaign/loop-campaign.json`
- `loop-campaign/loop-report.md`
- `<project-id>-<cycle-id>.pdf`
- generated `.tex`
- `paper-build.json`
- `publication-audit.json`
- `evidence-gate.json`
- `cycle-summary.json`
- manifest `.json` and `.md`

Do not claim a paper is publication-ready just because a PDF exists. The release claim requires
the loop campaign quality gate, publication audit, and evidence gate to pass on the same cycle
artifacts.

## External References And Licenses

AI-Researcher references several open-source projects as design inspiration or optional ecosystem
integration points, including HKUDS AI-Researcher, AutoResearch, Horizon-style daily refreshers,
AutoResearchClaw, SkillOpt, OpenClaw channel plugins, OpenCode, Hermes Agent, Luban Skill style
guides, SimpleMem/Omni-SimpleMem, SkillClaw, LightAgent/LightFlow, Auto-Empirical Research Skills,
paper-craft-skills, Meta-Harness, oh-my-openagent/LazyCodex, PageAgent, citation-management, and
Deep-Research-skills.
External skill, harness-search, and source-adapter ideas are first recorded with
`airesearcher skill-watchlist` as
quarantined Obsidian candidates; they
are not installed, copied, or promoted until license, security, live-evidence, and rollback gates
pass.

Meta-Harness-style ideas are limited to controlled self-evolution: define a domain spec first,
freeze the base model and tool surface, archive candidate source/scores/traces, keep search and
held-out evaluation separate, and promote only through AI-Researcher's existing shadow-evaluation,
evidence-gate, and rollback workflow.

LightAgent-style ideas are limited to lightweight orchestration and diagnostics: explicit
step dependencies, step-local retries, opt-in trace events, and strict separation between trace
records, project memory, reflection memory, and delegation state before anything enters the
Obsidian vault.

Their license and incorporation status are tracked in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). This repository does not vendor OpenClaw,
OpenCode, Hermes Agent, AutoResearchClaw, Meta-Harness, LightAgent, oh-my-openagent/LazyCodex,
PageAgent, channel plugin source code, or third-party skill content.

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
