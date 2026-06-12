# Agent Development Standard and Change Log

This file defines the project development standard for coding agents and records what each agent changed in this repository. Every agent that edits files must append an entry before handoff.

## Development Standard

### Task Discipline

- Work from `.kiro/specs/auto-research-system/tasks.md`.
- Start one task or subtask at a time.
- State the success criteria before implementing when the task is non-trivial.
- Do not mark a task complete until its verification steps have passed.
- If verification cannot run, keep the task unchecked and record the blocker in `Problem.md`.

### Change Scope

- Make the smallest change that satisfies the active task.
- Do not refactor unrelated code, rename unrelated files, or clean up unrelated dead code.
- Keep implemented behavior aligned with `AutoResearch_System_Research_Plan.md` and `AutoResearch_System_Execution_Plan.md`.
- User-facing claims in docs must distinguish planned capabilities from implemented capabilities.

### Verification

- Prefer narrow checks first, then broader checks when the task touches shared behavior.
- For docs-only changes, verify file existence, links, and key required phrases.
- For code changes, run the relevant unit, integration, lint, type, or smoke checks listed in the task.
- Record all verification in this file.

### Problem Tracking

- Add a `Problem.md` entry for missing modules, failed commands, unclear requirements, skipped verification, security concerns, or any issue likely to affect the next agent.
- Link problem IDs back to the relevant task where possible.

### Git Version Management

- After completing a task or subtask in `tasks.md`, passing its verification, and updating `Agent.md` and `Problem.md`, create one git commit for that completed task or subtask.
- Use a focused commit message that names the task, for example `docs: complete task 0.1 governance baseline`.
- Do not combine unrelated tasks in one commit.
- Do not commit a task whose verification is blocked; leave it unchecked and document the blocker.
- Before committing, review `git status --short` and stage only files relevant to the completed task.

## Entry Template

```markdown
### YYYY-MM-DD HH:mm:ss +TZ - Agent Name - Task

- Request: Short description or task ID.
- Files changed:
  - `path/to/file`
- Summary:
  - What changed and why.
- Verification:
  - Command or check: result.
- Problems:
  - `P-YYYYMMDD-NNN` updated, or `None`.
- Follow-up:
  - Remaining work, or `None`.
```

## Entries

### 2026-06-12 13:09:32 +08:00 - Codex - Task 30.1 strategy evolution report

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `30.1`.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `src/autoresearch/reports/__init__.py`
  - `src/autoresearch/reports/evolution.py`
  - `tests/unit/reports/test_evolution.py`
- Summary:
  - Added structured strategy evolution report context and artifact models.
  - Generated Markdown and JSON reports for strategy changes.
  - Included required sections for strategy cards, reason, evidence, evaluation, reward delta, risks, release history, rollback target, and final decision.
  - Rendered strategy card and evidence references as Obsidian wiki-links.
  - Added a test that verifies required report fields and strategy card links.
  - Marked task `30.1` complete in `tasks.md`.
- Verification:
  - `poetry run ruff check src/autoresearch/reports/evolution.py src/autoresearch/reports/__init__.py tests/unit/reports/test_evolution.py`: passed.
  - `poetry run mypy src`: passed.
  - `poetry run pytest tests/unit/reports/test_evolution.py -vv`: passed, 1 test.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 273 passed and 3 skipped.
- Problems:
  - None.
- Follow-up:
  - Continue with task `30.2` human-readable audit review for maintainers before promotion.

### 2026-06-12 13:06:20 +08:00 - Codex - Task 29.2 automatic strategy rollback

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `29.2`.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/experiments/strategy_rollback.py`
  - `tests/unit/experiments/test_strategy_rollback.py`
- Summary:
  - Added automatic strategy rollback decision models and evaluation logic.
  - Triggered rollback after repeated negative reward or any safety incident.
  - Returned a rolled-back strategy copy, rollback target, strategy family id, frozen-family flag, and review-required flag.
  - Recorded rollback audit events with recent reward history, trigger reasons, freeze status, and rollback target.
  - Added tests for repeated negative reward rollback, no rollback after a single negative reward, and safety incident rollback.
  - Marked task `29.2` and parent task `29` complete in `tasks.md`.
- Verification:
  - `poetry run ruff check src/autoresearch/experiments/strategy_rollback.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_strategy_rollback.py`: passed.
  - `poetry run mypy src`: passed.
  - `poetry run pytest tests/unit/experiments/test_strategy_rollback.py -vv`: passed, 3 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 272 passed and 3 skipped.
- Problems:
  - None.
- Follow-up:
  - Continue with task `30.1` strategy evolution report summary.

### 2026-06-12 13:02:58 +08:00 - Codex - Task 29.1 gray release promotion gate

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `29.1`.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/experiments/promotion.py`
  - `tests/unit/experiments/test_promotion.py`
- Summary:
  - Added a strategy promotion gate for controlled gray release.
  - Required human approval, golden test pass status, no safety regression, and non-decreasing evidence coverage before promotion.
  - Started approved promotions at a default 5 percent gray traffic share and capped configured gray traffic share at 10 percent.
  - Returned an immutable promoted strategy copy with `release_status="gray_release"` while leaving the input strategy unchanged.
  - Wrote an approval-gate audit event for promotion decisions.
  - Added tests for missing approval, missing golden pass, safety/evidence regression, and successful gray release with audit.
  - Marked task `29.1` complete in `tasks.md`.
- Verification:
  - `poetry run ruff check src/autoresearch/experiments/promotion.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_promotion.py`: passed.
  - `poetry run mypy src`: passed.
  - `poetry run pytest tests/unit/experiments/test_promotion.py -vv`: passed, 4 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 269 passed and 3 skipped.
- Problems:
  - None.
- Follow-up:
  - Continue with task `29.2` automatic rollback after negative strategy reward or safety incident.

### 2026-06-12 12:56:56 +08:00 - Codex - Task 28.2 strategy rewards

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `28.2`.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `Problem.md`
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/experiments/reward.py`
  - `tests/unit/experiments/test_reward.py`
- Summary:
  - Added strategy reward input, weight, and result dataclasses for shadow strategy comparison.
  - Added reward calculation components for quality gain, reproducibility, evidence completeness, compute cost increase, human intervention increase, and risk penalty.
  - Exported the reward helpers from `autoresearch.experiments`.
  - Added tests covering quality improvement, cost increase penalty, risk penalty, and human intervention penalty.
  - Marked task `28.2` and parent task `28` complete in `tasks.md`.
- Verification:
  - `poetry run ruff check src/autoresearch/experiments/__init__.py --fix`: passed, fixed one import-order issue.
  - `poetry run ruff check src/autoresearch/experiments/reward.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_reward.py`: passed.
  - `poetry run mypy src`: passed.
  - `poetry run pytest tests/unit/experiments/test_reward.py -vv`: passed, 3 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 265 passed and 3 skipped.
- Problems:
  - Added and resolved `P-20260612-054`.
- Follow-up:
  - Continue with task `29.1` gray release approval and promotion gates.

### 2026-06-12 12:50:57 +08:00 - Codex - Task 28.1 shadow evaluation

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `28.1`; run candidate strategies in shadow mode without affecting production outputs.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `Problem.md`
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/experiments/shadow.py`
  - `tests/unit/experiments/test_shadow.py`
- Summary:
  - Added `ShadowEvaluationRecord` and `ShadowProposal` for isolated candidate-strategy outputs.
  - Added `run_shadow_evaluation()` to pass a deep-copied replay case into the candidate proposal and record shadow output separately from production output.
  - Added `write_shadow_evaluation()` for standalone shadow JSON records.
  - Added a test proving a candidate proposal can mutate its shadow copy while the production replay output remains unchanged.
  - Marked task `28.1` complete; parent task `28` remains open for reward comparison in `28.2`.
- Verification:
  - Initial focused lint exposed `P-20260612-053`; repaired typing imports with ruff autofix.
  - `poetry run ruff check src/autoresearch/experiments/shadow.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_shadow.py`: passed.
  - `poetry run mypy src`: passed.
  - `poetry run pytest tests/unit/experiments/test_shadow.py -vv`: passed, 1 test.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 262 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - `P-20260612-053` added and resolved.
- Follow-up:
  - Task `28.2` should calculate strategy reward from quality gain, reproducibility, evidence completeness, compute cost, human intervention, and risk penalty.

### 2026-06-12 12:47:03 +08:00 - Codex - Task 27.2 golden test set

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `27.2`; create a fixed golden regression suite and verify stable strategies pass before candidate comparison.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/experiments/golden.py`
  - `tests/unit/experiments/test_golden.py`
- Summary:
  - Added golden-suite models for fixed regression cases, observations, per-case results, and suite evaluations.
  - Added default required golden domains for literature retrieval, config parsing, sandbox denial, result validation, citation validation, and report generation.
  - Added `build_default_golden_suite()` and `evaluate_golden_suite()` so only a stable strategy with all required cases passed can serve as the comparison baseline.
  - Added tests for required domain coverage, stable strategy pass, warning/missing failures, and candidate pre-release failure.
  - Marked task `27.2` and parent task `27` complete.
- Verification:
  - `poetry run ruff check src/autoresearch/experiments/golden.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_golden.py`: passed.
  - `poetry run mypy src`: passed.
  - `poetry run pytest tests/unit/experiments/test_golden.py -vv`: passed, 4 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 261 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - None.
- Follow-up:
  - Task `28.1` should run candidate strategies in shadow mode while keeping production output unchanged.

### 2026-06-12 12:42:57 +08:00 - Codex - Task 27.1 replay dataset

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `27.1`; create replay datasets from historical tasks with inputs, outputs, evidence, costs, and validation outcomes.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `Problem.md`
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/experiments/replay.py`
  - `tests/unit/experiments/test_replay.py`
- Summary:
  - Added `ReplayCase` and `ReplayDataset` models for local offline strategy replay fixtures.
  - Added `build_replay_case()` to capture historical task inputs, execution run data, result outputs, evidence edges, cost records, cost JSON, and validation report outcomes.
  - Added deterministic JSON persistence via `write_replay_dataset()` and `load_replay_dataset()`.
  - Added baseline score reproduction from replay cases that passed or warned validation.
  - Added tests for replay fixture baseline reproduction and mismatch/missing-metric rejection.
  - Marked task `27.1` complete; parent task `27` remains open for golden test set creation in `27.2`.
- Verification:
  - Initial focused lint exposed `P-20260612-052`; repaired import ordering with ruff autofix.
  - `poetry run ruff check src/autoresearch/experiments/replay.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_replay.py`: passed.
  - `poetry run mypy src`: passed.
  - `poetry run pytest tests/unit/experiments/test_replay.py -vv`: passed, 3 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 257 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - `P-20260612-052` added and resolved.
- Follow-up:
  - Task `27.2` should define a golden regression suite across literature retrieval, config parsing, sandbox denial, result validation, citation validation, and report generation.

### 2026-06-12 12:38:43 +08:00 - Codex - Task 26.2 strategy versioning

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `26.2`; preserve strategy lineage from parent strategy to candidate strategy.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `src/autoresearch/knowledge/__init__.py`
  - `src/autoresearch/knowledge/versioning.py`
  - `tests/unit/knowledge/test_strategy_cards.py`
- Summary:
  - Added `create_strategy_candidate()` to derive a candidate strategy from a parent strategy with incremented version, parent ID, rollback target, evaluation score, golden test status, shadow status, release status, and inherited/merged context links.
  - Exported the helper from `autoresearch.knowledge`.
  - Added a test that derives a retrieval-policy candidate, writes parent and candidate strategy cards to the Obsidian vault, and verifies lineage fields survive the round trip.
  - Marked task `26.2` and parent task `26` complete.
- Verification:
  - `poetry run ruff check src/autoresearch/knowledge/versioning.py src/autoresearch/knowledge/__init__.py tests/unit/knowledge/test_strategy_cards.py`: passed.
  - `poetry run mypy src`: passed.
  - `poetry run pytest tests/unit/knowledge/test_strategy_cards.py -vv`: passed, 2 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 254 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - None.
- Follow-up:
  - Task `27.1` should create replay datasets from historical tasks with enough inputs, outputs, evidence, costs, and validation outcomes for offline strategy testing.

### 2026-06-12 12:34:32 +08:00 - Codex - Task 26.1 strategy card schema

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `26.1`; define controlled self-evolution strategy card schema and write linkable Obsidian strategy cards.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `Problem.md`
  - `src/autoresearch/knowledge/versioning.py`
  - `src/autoresearch/schemas/__init__.py`
  - `src/autoresearch/schemas/models.py`
  - `tests/unit/knowledge/test_strategy_cards.py`
  - `tests/unit/schemas/test_schema_models.py`
- Summary:
  - Added allowed strategy targets for prompt templates, workflow templates, tool routing policy, retrieval policy, experiment search policy, scheduling policy, and validation policy.
  - Rejected prohibited automatic mutation targets for safety policy, approval gates, license policy, and publication rules.
  - Added strategy link fields for failure patterns, skill cards, replay results, golden tests, shadow evaluations, and rollback targets.
  - Updated Obsidian strategy-card writing so frontmatter source references and Markdown wiki-links carry the strategy's linked evidence and evaluation context.
  - Added tests for allowed/prohibited strategy targets and linkable strategy-card Markdown.
  - Marked task `26.1` complete; parent task `26` remains open for strategy lineage/versioning in `26.2`.
- Verification:
  - Initial focused lint exposed `P-20260612-051`; repaired import ordering with ruff autofix.
  - `poetry run ruff check src/autoresearch/schemas/models.py src/autoresearch/schemas/__init__.py src/autoresearch/knowledge/versioning.py tests/unit/schemas/test_schema_models.py tests/unit/knowledge/test_strategy_cards.py tests/unit/knowledge/test_rollback.py`: passed.
  - `poetry run mypy src`: passed.
  - `poetry run pytest tests/unit/schemas/test_schema_models.py tests/unit/knowledge/test_strategy_cards.py tests/unit/knowledge/test_rollback.py -vv`: passed, 23 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 253 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - `P-20260612-051` added and resolved.
- Follow-up:
  - Task `26.2` should preserve explicit lineage from parent strategy to candidate strategy.

### 2026-06-12 12:28:59 +08:00 - Codex - Task 25.2 rollback audit trail

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `25.2`; record rollback actor, reason, old version, new version, and verification result in audit JSONL.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `src/autoresearch/knowledge/versioning.py`
  - `src/autoresearch/observability/audit.py`
  - `tests/unit/knowledge/test_rollback.py`
- Summary:
  - Added `AuditEventType.ROLLBACK` for explicit rollback audit events.
  - Added optional rollback audit logging to config/prompt/workflow file rollback, knowledge-entry rollback, and strategy-card rollback.
  - Recorded rollback target type, actor, reason, old version, restored/new version, verification result, path, run ID, project ID, and task ID in existing append-only JSONL audit logs.
  - Added a unit test that performs a rollback, reloads `audit/audit.jsonl`, and verifies the expected rollback event fields.
  - Marked task `25.2` and parent task `25` complete.
- Verification:
  - `poetry run ruff check src/autoresearch/knowledge/versioning.py src/autoresearch/observability/audit.py tests/unit/knowledge/test_rollback.py`: passed.
  - `poetry run mypy src`: passed.
  - `poetry run pytest tests/unit/knowledge/test_rollback.py tests/unit/observability/test_audit.py -vv`: passed, 15 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 237 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - None.
- Follow-up:
  - Task `26.1` should model candidate strategies and connect them to failure patterns, skill cards, replay results, golden tests, shadow evaluations, and rollback targets.

### 2026-06-12 12:24:06 +08:00 - Codex - Task 25.1 rollback version foundations

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `25.1`; track versions for prompts, workflow templates, configs, strategy knowledge, and knowledge entries with rollback support.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `Problem.md`
  - `src/autoresearch/knowledge/__init__.py`
  - `src/autoresearch/knowledge/versioning.py`
  - `tests/unit/knowledge/test_rollback.py`
- Summary:
  - Added `VersionedFileStore` for versioned plain-text prompts, workflow templates, and configs.
  - Added rollback result and target-type models for config, prompt, workflow-template, knowledge-entry, and strategy-card rollback targets.
  - Added Obsidian Markdown strategy-card writing with rollback metadata and strategy-linked version history.
  - Added knowledge-entry and strategy-card rollback wrappers backed by `MarkdownKnowledgeStore`.
  - Added tests for rolling back a fixture config, strategy card, and knowledge entry.
  - Marked task `25.1` complete; parent task `25` remains open for rollback audit trail work in `25.2`.
- Verification:
  - Initial focused lint exposed `P-20260612-049`; removed the unused import.
  - Initial type checking exposed `P-20260612-050`; converted parsed version metadata through `str` before `int`.
  - `poetry run ruff check src/autoresearch/knowledge/versioning.py src/autoresearch/knowledge/__init__.py tests/unit/knowledge/test_rollback.py`: passed.
  - `poetry run mypy src`: passed.
  - `poetry run pytest tests/unit/knowledge/test_rollback.py -vv`: passed, 3 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 235 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - `P-20260612-049` added and resolved.
  - `P-20260612-050` added and resolved.
- Follow-up:
  - Task `25.2` should add rollback audit trail JSONL events with actor, reason, old version, new version, and verification result.

### 2026-06-12 12:17:14 +08:00 - Codex - Task 24.2 local dashboard export

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `24.2`; export a local status report from sample metrics without external services.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `src/autoresearch/observability/__init__.py`
  - `src/autoresearch/observability/dashboard.py`
  - `tests/unit/observability/test_dashboard.py`
- Summary:
  - Added `ProjectStatusSummary`, `LocalStatusReport`, and `export_local_status_report()`.
  - Rendered a static Markdown report with system metrics, task failure rate, cost totals, average cost per success, human interventions, evidence coverage, rollback count, and active project state.
  - Supported empty active-project states without requiring any web server or external service.
  - Exported the local report API from `autoresearch.observability`.
  - Added tests for rendered Markdown content and no-project output.
  - Marked task `24.2` and parent task `24` complete.
- Verification:
  - `poetry run ruff check src/autoresearch/observability/dashboard.py src/autoresearch/observability/__init__.py tests/unit/observability/test_dashboard.py`: passed.
  - `poetry run mypy src`: passed with the existing non-failing unused optional dependency override note.
  - `poetry run pytest tests/unit/observability/test_dashboard.py -vv`: passed, 2 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 232 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - None.
- Follow-up:
  - Task `25.1` should add rollback foundations for config, strategy, and knowledge entries.

### 2026-06-12 12:13:26 +08:00 - Codex - Task 24.1 system metrics

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `24.1`; compute monitoring metrics from fixture run history.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `Problem.md`
  - `src/autoresearch/observability/__init__.py`
  - `src/autoresearch/observability/metrics.py`
  - `tests/unit/observability/test_metrics.py`
- Summary:
  - Added `SystemMetricsInput`, `SystemMetricSnapshot`, and `compute_system_metrics()`.
  - Computed task success rate, reproduction rate, validator rejection rate, average cost per success, average human interventions, agent loop depth, rollback count, citation error rate, and evidence coverage.
  - Derived costs from explicit cost JSON first, then cost records, and counted human interventions from runs plus approval/publication gate audit events.
  - Counted rollbacks from audit actions or rollback metadata and evidence coverage from claim traces with passed or warning evidence artifacts.
  - Added fixture-history tests and empty-history denominator checks.
  - Marked task `24.1` complete; parent task `24` remains open for the local dashboard export in `24.2`.
- Verification:
  - Initial focused lint exposed `P-20260612-048`; repaired export ordering with ruff autofix.
  - `poetry run ruff check src/autoresearch/observability/metrics.py src/autoresearch/observability/__init__.py tests/unit/observability/test_metrics.py`: passed.
  - `poetry run mypy src`: passed with the existing non-failing unused optional dependency override note.
  - `poetry run pytest tests/unit/observability/test_metrics.py -vv`: passed, 2 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 230 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - `P-20260612-048` added and resolved.
- Follow-up:
  - Task `24.2` should export a local Markdown or static HTML status report using the computed metrics.

### 2026-06-12 12:06:29 +08:00 - Codex - Task 23.2 skill retrieval

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `23.2`; retrieve skill cards for similar tasks using structured frontmatter and Obsidian links.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `Problem.md`
  - `src/autoresearch/knowledge/__init__.py`
  - `src/autoresearch/knowledge/skills.py`
  - `tests/unit/knowledge/test_skills.py`
  - `tests/property/knowledge/test_skill_retrieval.py`
- Summary:
  - Added `SkillRetrievalQuery`, `SkillMatch`, and `retrieve_relevant_skills()`.
  - Scored skill matches using direct skill IDs, frontmatter tags, frontmatter keywords, task metadata terms, source refs, body terms, Obsidian wiki-links, and computed backlinks.
  - Scanned Obsidian Markdown entries without requiring a database or external service.
  - Added unit coverage for frontmatter plus Obsidian-link matching and invalid retrieval limits.
  - Added property coverage that generated similar task contexts retrieve the expected skill above an unrelated control skill.
  - Marked task `23.2` and parent task `23` complete.
- Verification:
  - Initial focused pytest exposed `P-20260612-047`; renamed the property test file to avoid pytest import mismatch.
  - `poetry run ruff check src/autoresearch/knowledge/skills.py src/autoresearch/knowledge/__init__.py tests/unit/knowledge/test_skills.py tests/property/knowledge/test_skill_retrieval.py`: passed.
  - `poetry run mypy src`: passed with the existing non-failing unused optional dependency override note.
  - `poetry run pytest tests/unit/knowledge/test_skills.py tests/property/knowledge/test_skill_retrieval.py -vv`: passed, 6 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 228 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - `P-20260612-047` added and resolved.
- Follow-up:
  - Task `24.1` should track system metrics such as task success rate, reproduction rate, validator rejection rate, cost per success, interventions, loop depth, rollbacks, citation error rate, and evidence coverage.

### 2026-06-12 11:59:43 +08:00 - Codex - Task 23.1 reusable skill cards

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `23.1`; extract reusable skill cards from repeated successful patterns.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `Problem.md`
  - `src/autoresearch/knowledge/__init__.py`
  - `src/autoresearch/knowledge/skills.py`
  - `tests/unit/knowledge/test_skills.py`
- Summary:
  - Added `SuccessfulPatternExample`, `ExtractedSkillCard`, and `extract_reusable_skill_card()`.
  - Required at least two successful examples before generating a reusable skill card.
  - Wrote skill cards under `autoresearch-vault/exploration/skills/` with trigger conditions, actions, success metrics, project experience links, failure pattern links, tags, keywords, related tasks, and related runs.
  - Exported the skill extraction API from `autoresearch.knowledge`.
  - Added tests for skill-card creation, keyword retrieval, wiki-link extraction, topic-index presence, repeated-example validation, and incomplete-example rejection.
  - Marked task `23.1` complete; parent task `23` remains open for skill retrieval in `23.2`.
- Verification:
  - Initial `mypy` and follow-up focused `ruff` checks exposed `P-20260612-046`; repaired the iterable type annotation and import location.
  - `poetry run ruff check src/autoresearch/knowledge/skills.py src/autoresearch/knowledge/__init__.py tests/unit/knowledge/test_skills.py`: passed.
  - `poetry run mypy src`: passed with the existing non-failing unused optional dependency override note.
  - `poetry run pytest tests/unit/knowledge/test_skills.py -vv`: passed, 3 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 225 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - `P-20260612-046` added and resolved.
- Follow-up:
  - Task `23.2` should retrieve relevant skill cards for similar tasks from frontmatter keywords and Obsidian links.

### 2026-06-12 11:53:22 +08:00 - Codex - Task 22.2 recurring failure classification

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `22.2`; classify recurring failure patterns and feed repeated failures into skill and strategy work.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `Problem.md`
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/experiments/failures.py`
  - `tests/unit/experiments/test_failures.py`
- Summary:
  - Added deterministic failure classification for dependency, data, runtime, metric, citation, permission, cost, validation, and unknown causes.
  - Added recurring failure pattern note generation under `autoresearch-vault/exploration/failure_patterns/` when a category repeats.
  - Included source failure links plus skill extraction and strategy proposal feed sections in recurring pattern notes.
  - Exported the recurring failure APIs from `autoresearch.experiments`.
  - Added focused tests for representative categories and shared recurring pattern note updates.
  - Marked task `22.2` and parent task `22` complete.
- Verification:
  - Initial export patch caused `P-20260612-045`; repaired `src/autoresearch/experiments/__init__.py`.
  - `poetry run ruff check src/autoresearch/experiments/failures.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_failures.py`: passed.
  - `poetry run mypy src`: passed with the existing non-failing unused optional dependency override note.
  - `poetry run pytest tests/unit/experiments/test_failures.py -vv`: passed, 12 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 222 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - `P-20260612-045` resolved.
- Follow-up:
  - Task `23.1` should extract reusable skill cards from repeated successful patterns and failure pattern feeds.

### 2026-06-12 11:46:51 +08:00 - Codex - Task 22.1 failed-run knowledge records

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `22.1`; record failed runs as first-class Obsidian knowledge.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `Problem.md`
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/experiments/failures.py`
  - `tests/unit/experiments/test_failures.py`
- Summary:
  - Added `record_failed_run_as_knowledge()` to persist failed, timed out, cancelled, or blocked runs as Obsidian `failure_case` entries.
  - Wrote global failure pattern notes under `exploration/failure_patterns/` and project-local issue notes under `projects/<project-id>/issues/`.
  - Captured run status, error type, stdout/stderr, log refs, config refs, environment, hypothesis ID, experiment task metadata, evidence status, suspected cause, skill refs, and strategy refs.
  - Added wiki-links from the global failure note to the project issue, run, task, hypothesis, skills, and strategies.
  - Marked task `22.1` complete; parent task `22` remains open for recurring failure classification.
- Verification:
  - Initial focused lint command failed with unused `typing.Any`; recorded as `P-20260612-044` and fixed.
  - `poetry run ruff check src/autoresearch/experiments/failures.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_failures.py`: passed.
  - `poetry run mypy src`: passed with the existing non-failing unused optional dependency override note.
  - `poetry run pytest tests/unit/experiments/test_failures.py -vv`: passed, 2 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 212 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - Added and resolved `P-20260612-044`.
- Follow-up:
  - Task `22.2` should classify recurring failure patterns and update shared failure pattern notes.

### 2026-06-12 11:41:38 +08:00 - Codex - Task 21.4 budget-aware execution gates

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `21.4`; pause or require approval when a task approaches 80 percent of budget.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/experiments/budget.py`
  - `tests/unit/experiments/test_budget.py`
- Summary:
  - Added `evaluate_budget_gate()` with `approved`, `approval_required`, and `blocked` decisions.
  - Added configurable approval and hard-limit thresholds, defaulting to 80 percent and 100 percent of comparable task budget.
  - Supported explicit usage input plus usage read from `ExecutionRun.cost_record` and `cost_json`, including storage bytes compared against `storage_mb`.
  - Added optional `AuditLog` emission as an `approval_gate` event when the budget gate is evaluated.
  - Marked task `21.4` and parent task `21` complete.
- Verification:
  - `poetry run ruff check src/autoresearch/experiments/budget.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_budget.py`: passed.
  - `poetry run mypy src`: passed with the existing non-failing unused optional dependency override note.
  - `poetry run pytest tests/unit/experiments/test_budget.py -vv`: passed, 4 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 210 tests passed and 3 optional live smoke tests skipped by default.
- Problems:
  - None.
- Follow-up:
  - Task `22.1` should record failed runs as first-class Obsidian knowledge entries.

### 2026-06-12 11:36:21 +08:00 - Codex - Task 21.3 project-start online similarity check

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `21.3`; add broad online similarity and novelty cross-checks before candidate approval/project creation, with Obsidian summaries and real live-source testing.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
  - `Problem.md`
  - `src/autoresearch/literature/__init__.py`
  - `src/autoresearch/research/__init__.py`
  - `src/autoresearch/research/approval.py`
  - `src/autoresearch/research/similarity.py`
  - `tests/unit/research/test_approval.py`
  - `tests/unit/research/test_similarity.py`
  - `tests/smoke/test_similarity_live.py`
- Summary:
  - Added `run_project_similarity_check()` to generate candidate-title, research-gap, method/dataset/limitation, baseline, negative-result, and Obsidian-context query variants.
  - Added source-backed similarity findings with explicit classifications: `direct_duplicate`, `adjacent_work`, `supporting_prior_work`, `contradictory_evidence`, `benchmark_gap`, and `unknown`.
  - Persisted pre-approval similarity summaries under `autoresearch-vault/exploration/topics/` with query text, source URL/DOI, source database, retrieval timestamp, evidence refs, confidence, classification basis, and `unknown`/`pending verification` markers.
  - Made project creation require a matching similarity report, then write a project-zone link note under `projects/<project-id>/knowledge/`.
  - Added unsupported-claim validation so findings without provenance or with unsupported claims are rejected instead of being written as facts.
  - Added an opt-in live smoke test that performs real online similarity checks against ArXiv/Semantic Scholar clients.
  - Marked task `21.3` complete; parent task `21` remains open for budget-aware execution gates.
- Verification:
  - `poetry run pytest tests/unit/research/test_similarity.py tests/unit/research/test_approval.py -vv`: passed, 8 tests.
  - Initial focused lint command failed with one `I001` import-order issue in `src/autoresearch/literature/__init__.py`; recorded as `P-20260612-043` and fixed with ruff autofix.
  - `poetry run ruff check src/autoresearch/research/similarity.py src/autoresearch/research/approval.py src/autoresearch/research/__init__.py src/autoresearch/literature/__init__.py tests/unit/research/test_similarity.py tests/unit/research/test_approval.py tests/smoke/test_similarity_live.py`: passed.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with the existing non-failing unused optional dependency override note.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 206 tests passed and 3 optional live smoke tests skipped by default.
  - `$env:AUTORESEARCH_LIVE_LITERATURE='1'; poetry run pytest tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py tests/smoke/test_similarity_live.py -vv`: passed, 3 tests using real network calls.
- Problems:
  - Added and resolved `P-20260612-043`.
- Follow-up:
  - Task `21.4` should add budget-aware execution gates and approval pause behavior.

### 2026-06-12 11:03:17 +08:00 - Codex - Task 21.2 daily online literature refresh

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `21.2`; support online discovery from ArXiv/Semantic Scholar with query optimization, cache reuse, deduplication, rate-limit provenance, and Obsidian summary output.
- Files changed:
  - `AGENTS.md`
  - `pyproject.toml`
  - `poetry.lock`
  - `src/autoresearch/cli/main.py`
  - `src/autoresearch/literature/clients.py`
  - `src/autoresearch/literature/refresh.py`
  - `src/autoresearch/literature/__init__.py`
  - `tests/unit/literature/test_refresh.py`
  - `tests/smoke/test_literature_live.py`
  - `tests/smoke/test_literature_refresh_live.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Updated project agent guidance: external-source features require deterministic mocked tests plus opt-in live smoke tests, and the live smoke must be run before task completion.
  - Added provider-agnostic large-model guidance: integrations must read `base_url`, `api_key`, and `model_name` from configuration or environment; stop for user-provided `.env` values when credentials are needed.
  - Added `generate_literature_queries()` to derive external-search queries from Obsidian research candidates, method cards, dataset cards, failure cases, project experience, and topic index headings.
  - Added `run_daily_literature_refresh()` to fetch from injectable ArXiv/Semantic Scholar clients, use `RetrievalCache`, record cache hit/miss, rate-limit decisions, and per-source errors, deduplicate papers, normalize them into `DocumentRecord` items, and write an Obsidian evidence note.
  - Added explicit `certifi` dependency and made the stdlib urllib client use `certifi.where()` for HTTPS verification rather than disabling TLS checks.
  - Constrained Click to the Typer-compatible `>=8.1,<8.2` range and removed deferred annotations from the CLI entrypoint so locked-environment CLI tests continue to parse options correctly.
  - Declared `autoresearch` as the first-party package for ruff/isort so lint does not rewrite existing local-vs-third-party import groups.
  - Added opt-in live smoke tests for real literature clients and the daily refresh pipeline.
  - Added summary guardrails requiring missing evidence to remain `unknown` or `pending verification`, with no inferred benchmark scores, acceptance status, code availability, or experimental outcomes.
  - Marked task `21.2` complete; parent task `21` remains open for project-start similarity checks and budget gates.
- Verification:
  - `poetry run pytest tests/unit/literature/test_refresh.py tests/unit/literature/test_cache.py tests/property/literature/test_deduplication.py`: passed, 8 tests.
  - `poetry run ruff check src/autoresearch/literature/refresh.py src/autoresearch/literature/__init__.py tests/unit/literature/test_refresh.py`: passed.
  - `poetry run mypy src`: passed with the existing non-failing unused optional dependency override note.
  - First live run, `$env:AUTORESEARCH_LIVE_LITERATURE='1'; poetry run pytest tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py -vv`: failed on TLS certificate verification; recorded as `P-20260612-039`.
  - Second live run after adding `certifi`: reached real services but failed on ArXiv `429 Too Many Requests` and a source timeout; refresh pipeline was updated to record source-level errors and continue.
  - Final live run, `$env:AUTORESEARCH_LIVE_LITERATURE='1'; poetry run pytest tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py -vv`: passed, 2 tests using real network calls.
  - `poetry run pytest tests/unit/cli/test_main.py -vv`: passed, 5 tests after Click constraint and CLI annotation fix.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 202 tests passed and 2 optional live literature tests skipped by default.
- Problems:
  - Added and resolved `P-20260612-039`.
  - Added and resolved `P-20260612-040`.
  - Added and resolved `P-20260612-041`.
  - Added and resolved `P-20260612-042`.
- Follow-up:
  - Task `21.3` should add the project-start online similarity and novelty cross-check before candidate approval.

### 2026-06-12 10:57:58 +08:00 - Codex - Online discovery planning clarification

- Request: Clarify that AI-Researcher must use online literature and similar-direction search at project start and scheduled refresh, not only local Obsidian lookup; summaries must be source-backed and must not fabricate outcomes.
- Files changed:
  - `.kiro/specs/auto-research-system/tasks.md`
  - `AutoResearch_System_Research_Plan.md`
  - `AutoResearch_System_Execution_Plan.md`
  - `README.md`
  - `README.zh-CN.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added a global task-plan rule that Obsidian is the evidence memory layer, not a replacement for external discovery.
  - Added task `21.3` for project-start online similarity and novelty cross-check before candidate approval.
  - Required source URL/DOI, query text, retrieval timestamp, evidence refs, confidence/unsupported markers, and `unknown` or `pending verification` markers when evidence is missing.
  - Updated research and execution plans plus both README files to state that project-start and scheduled refresh workflows must use online discovery.
- Verification:
  - `rg -n "Networked discovery|project-start online similarity|online similarity and novelty|pending verification|not fabricate|不能沉淀虚构|不能只理解为本地知识库" .kiro/specs/auto-research-system/tasks.md AutoResearch_System_Research_Plan.md AutoResearch_System_Execution_Plan.md README.md README.zh-CN.md Problem.md Agent.md`: confirmed required constraints are present.
  - `git diff --check`: passed with only existing Windows line-ending warnings.
- Problems:
  - Added and resolved `P-20260612-038`.
- Follow-up:
  - Implement task `21.2` daily online refresh and task `21.3` project-start online similarity scan with mocked network tests before optional live runs.

### 2026-06-12 10:54:30 +08:00 - Codex - Task 21.1 local scheduler

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `21.1`, while keeping online literature refresh as a separate upcoming task.
- Files changed:
  - `src/autoresearch/scheduler.py`
  - `src/autoresearch/observability/audit.py`
  - `tests/unit/test_scheduler.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added a deterministic local scheduler with daily, weekly, and one-shot queued tasks.
  - Added scheduler audit events so every scheduled run records task ID, status, resource, approval state, and metadata in JSONL.
  - Added `candidate_refresh_action()` to enforce the intended order: literature retrieval first, trend/gap analysis second.
  - Marked task `21.1` complete; parent task `21` remains open for online refresh and budget gates.
- Verification:
  - `poetry run pytest tests/unit/test_scheduler.py tests/unit/observability/test_audit.py`: passed, 14 tests.
  - `poetry run ruff check src/autoresearch/scheduler.py src/autoresearch/observability/audit.py tests/unit/test_scheduler.py`: passed after import sorting fix.
  - `poetry run mypy src`: passed with the existing non-failing unused optional dependency override note.
- Problems:
  - Added and resolved `P-20260612-037`.
- Follow-up:
  - Add the online project-start similarity scan and daily literature refresh pipeline in the next planning/code tasks.

### 2026-06-12 10:48:37 +08:00 - Codex - Task 20.2 trend and gap analyzer

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `20.2`, and record the requirement that AI-Researcher must later fetch online literature daily with Horizon-style pipeline separation.
- Files changed:
  - `src/autoresearch/research/candidates.py`
  - `src/autoresearch/research/__init__.py`
  - `tests/unit/research/test_candidates.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `AutoResearch_System_Execution_Plan.md`
  - `Agent.md`
- Summary:
  - Added deterministic trend/gap analysis that converts recent `DocumentRecord` literature into candidate updates only when source evidence exists.
  - Compared candidate method, dataset, and limitation signals against Obsidian method cards, dataset cards, project experience entries, and topic index coverage.
  - Added `TrendGapUpdate` output with evidence references, matched vault paths, missing vault paths, and gap reasons.
  - Marked task `20.2` and parent task `20` complete.
  - Added task `21.2` for daily online literature refresh from ArXiv/Semantic Scholar with query optimization, cache reuse, deduplication, and source-specific rate limits.
  - Added the Phase 3 execution-plan constraint to use Horizon-style source/fetch/dedup/score/enrich/persist pipeline separation and ArXiv's single-connection, 3-second request interval rule.
- Verification:
  - `poetry run pytest tests/unit/research/test_candidates.py tests/unit/knowledge/test_links.py`: passed, 8 tests.
  - `poetry run ruff check src/autoresearch/research/candidates.py src/autoresearch/research/__init__.py tests/unit/research/test_candidates.py`: passed.
  - `poetry run mypy src`: passed with the existing non-failing unused optional dependency override note.
  - `poetry run ruff check src tests`: passed.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 194 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
- Problems:
  - None.
- Follow-up:
  - Task `21.1` should implement the scheduler; task `21.2` should implement the mocked daily online literature refresh pipeline before enabling real network runs.

### 2026-06-12 10:41:20 +08:00 - Codex - AI-Researcher rename cleanup

- Request: Continue work and ensure the project name is `AI-Researcher`.
- Files changed:
  - `AutoResearch_System_Research_Plan.md`
  - `AutoResearch_System_Execution_Plan.md`
  - `autoresearch-vault/README.md`
  - `autoresearch-vault/projects/autoresearch-system/index.md`
  - `src/autoresearch/__init__.py`
  - `src/autoresearch/cli/main.py`
  - `src/autoresearch/config/__init__.py`
  - `src/autoresearch/literature/clients.py`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Removed user-facing `AutoResearch System` naming from planning headers, vault documentation, CLI help, package/config docstrings, demo scaffold title, and literature client User-Agent.
  - Kept the Python package name `autoresearch` unchanged to avoid a separate import-path migration.
  - Kept historical `Agent.md` entries unchanged.
- Verification:
  - `rg -n "AutoResearch System" AutoResearch_System_Research_Plan.md AutoResearch_System_Execution_Plan.md autoresearch-vault src README.md README.zh-CN.md pyproject.toml .kiro/specs/auto-research-system/tasks.md`: no matches.
  - `poetry run pytest tests/smoke/test_imports.py tests/unit/cli/test_main.py tests/unit/literature`: passed.
- Problems:
  - Added and resolved `P-20260612-036`.
- Follow-up:
  - Continue task `20.2`; treat any future full import-path/package rename as a dedicated migration.

### 2026-06-12 10:37:07 +08:00 - Codex - Task 20.1 candidate lifecycle

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `20.1`.
- Files changed:
  - `src/autoresearch/research/candidates.py`
  - `src/autoresearch/research/__init__.py`
  - `src/autoresearch/knowledge/entries.py`
  - `tests/unit/research/test_candidates.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added legal lifecycle transitions for research candidates from draft through review, approval, active work, completion, rejection, and archival.
  - Added `research_candidate` as a first-class Obsidian knowledge entry type.
  - Added candidate vault persistence under `autoresearch-vault/exploration/topics/<candidate-id>.md` with wiki-links to source papers, topic indexes, prior failures, useful skills, and strategy cards.
  - Ensured candidate entries populate the Obsidian topic index via existing `MarkdownKnowledgeStore` indexing.
  - Marked task `20.1` complete in `tasks.md`; parent task `20` remains open until `20.2` is complete.
- Verification:
  - `poetry run pytest tests/unit/research/test_candidates.py tests/unit/knowledge/test_entries.py`: passed, 18 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 192 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed after import ordering fix.
  - `poetry run mypy src`: passed with no issues in 57 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260612-035` resolved.
- Follow-up:
  - Task `20.2` should analyze recent literature and vault gaps into evidence-backed candidate updates.

### 2026-06-12 10:32:07 +08:00 - Codex - Project rename to AI-Researcher

- Request: Rename the project to `AI-Researcher` and continue implementation.
- Files changed:
  - `README.md`
  - `README.zh-CN.md`
  - `pyproject.toml`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Updated the public project display name to `AI-Researcher` in English and Chinese README files.
  - Updated Poetry package metadata to the normalized package name `ai-researcher` while leaving the Python import package `autoresearch` unchanged.
  - Updated the implementation plan title to `AI-Researcher`.
  - Kept existing planning document filenames unchanged so current links and task references remain stable.
- Verification:
  - `rg -n "AutoResearch System|autoresearch-system" README.md README.zh-CN.md pyproject.toml .kiro/specs/auto-research-system/tasks.md`: no matches.
  - `poetry check`: passed with existing Poetry deprecation warnings for legacy `[tool.poetry]` metadata fields.
  - `poetry run pytest tests/smoke/test_imports.py tests/unit/cli/test_main.py::test_version_command_prints_package_version`: passed, 3 tests.
- Problems:
  - None.
- Follow-up:
  - Continue task `20.1` for the Obsidian-backed candidate lifecycle.

### 2026-06-11 23:05:46 +08:00 - Codex - Task 19.2 package validation

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `19.2`.
- Files changed:
  - `src/autoresearch/reports/reproducibility.py`
  - `src/autoresearch/reports/__init__.py`
  - `src/autoresearch/cli/main.py`
  - `tests/unit/reports/test_reproducibility_package.py`
  - `tests/unit/cli/test_main.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added reproducibility package validation for manifest JSON, included artifact paths, file presence, sha256 matches, and self-contained run command paths.
  - Added structured validation issue/report dataclasses and exported them from `autoresearch.reports`.
  - Added `autoresearch validate-package --manifest <path>` to print pass/fail status and missing artifact details with a failing exit code.
  - Added tests for passing package validation, missing artifact reporting, and CLI failure output.
  - Marked task `19.2` and parent task `19` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports/test_reproducibility_package.py tests/unit/cli/test_main.py`: passed, 7 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 189 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 57 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `20.1` begins the Phase 3 Obsidian-backed self-loop candidate pool.

### 2026-06-11 23:00:14 +08:00 - Codex - Task 19.1 reproducibility package

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `19.1`.
- Files changed:
  - `src/autoresearch/reports/reproducibility.py`
  - `src/autoresearch/reports/__init__.py`
  - `tests/unit/reports/test_reproducibility_package.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added a reproducibility package builder that copies code, config, metrics, reports, evidence maps, validation artifacts, and other declared files into a package directory.
  - Added `manifest.json` generation with artifact role, source path, package path, byte size, and sha256 hash for every included artifact.
  - Added `environment.md` with Python/platform notes, validation status, run commands, and extra environment notes.
  - Added default exclusion for secret-like filenames and large raw data unless explicitly included.
  - Exported reproducibility package helpers from `autoresearch.reports`.
  - Marked task `19.1` complete in `tasks.md`; parent task `19` remains open until `19.2` is complete.
- Verification:
  - `poetry run pytest tests/unit/reports/test_reproducibility_package.py`: passed, 1 test.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 187 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed after fixing import order.
  - `poetry run mypy src`: passed with no issues in 57 source files after the enum return type fix; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-034` resolved.
- Follow-up:
  - Task `19.2` should validate that package commands and paths are self-contained.

### 2026-06-11 22:53:04 +08:00 - Codex - Task 18.3 review findings backlog

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `18.3`.
- Files changed:
  - `src/autoresearch/reports/backlog.py`
  - `src/autoresearch/reports/__init__.py`
  - `tests/unit/reports/test_review_backlog.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added structured review backlog records that convert actionable review findings into follow-up tasks or problem-entry records.
  - Added deterministic priority mapping, stable record IDs, source review metadata, optional project/task links, and problem-entry Markdown for high-severity findings.
  - Added JSON and Markdown backlog artifact writing so later self-loop and Obsidian vault tasks can ingest review feedback without parsing prose.
  - Exported review backlog helpers from `autoresearch.reports`.
  - Marked task `18.3` and parent task `18` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports/test_paper_review.py tests/unit/reports/test_review_criteria.py tests/unit/reports/test_review_backlog.py`: passed, 6 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 186 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 56 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `19.1` should package code, config, metrics, reports, and evidence maps with hashes and validation status.

### 2026-06-11 22:48:21 +08:00 - Codex - Task 18.2 venue criteria configuration

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `18.2`.
- Files changed:
  - `src/autoresearch/reports/review.py`
  - `src/autoresearch/reports/__init__.py`
  - `tests/unit/reports/test_review_criteria.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added review criteria models, built-in generic and CCF-B criteria, and a `load_review_criteria()` helper.
  - Added JSON/YAML/TOML-backed custom venue criteria loading through the existing configuration parser.
  - Added generic fallback when requested venue criteria are missing, while recording fallback status in the review report.
  - Wired criteria thresholds, dimension weights, formatting requirements, and content policies into `simulate_paper_review()`.
  - Marked task `18.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports/test_paper_review.py tests/unit/reports/test_review_criteria.py`: passed, 5 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 185 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 55 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `18.3` should convert actionable review findings into backlog records for the self-loop.

### 2026-06-11 22:42:18 +08:00 - Codex - Task 18.1 review dimensions

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `18.1`.
- Files changed:
  - `src/autoresearch/reports/review.py`
  - `src/autoresearch/reports/__init__.py`
  - `tests/unit/reports/test_paper_review.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added a deterministic conservative paper review simulator across novelty, technical soundness, experimental rigor, reproducibility, writing quality, and compliance.
  - Grounded technical soundness and reproducibility in validated evidence coverage, with missing claim evidence producing actionable findings and lower scores.
  - Added conservative score caps so generated review reports do not default to perfect scores.
  - Exported review helpers from `autoresearch.reports`.
  - Marked task `18.1` complete in `tasks.md`; parent task `18` remains open until `18.2` and `18.3` are complete.
- Verification:
  - `poetry run pytest tests/unit/reports/test_paper_review.py`: passed, 2 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 182 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 55 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-032` resolved.
  - `P-20260611-033` resolved.
- Follow-up:
  - Task `18.2` should add default and venue-specific review criteria configuration.

### 2026-06-11 22:25:20 +08:00 - Codex - Task 17.3 paper draft versioning

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `17.3`.
- Files changed:
  - `src/autoresearch/reports/drafts.py`
  - `src/autoresearch/reports/__init__.py`
  - `tests/unit/reports/test_drafts.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added immutable paper draft version storage under `versions/v0001`, `versions/v0002`, and so on.
  - Copied source LaTeX drafts into versioned directories without overwriting prior versions.
  - Wrote per-version `manifest.json` and a `latest.json` pointer containing draft metadata and source evidence graph schema version.
  - Exported paper draft versioning helpers from `autoresearch.reports`.
  - Marked task `17.3` and parent task `17` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports/test_drafts.py`: passed, 2 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 180 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 54 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `18.1` should add conservative review dimensions without auto-scoring perfect results.

### 2026-06-11 22:19:51 +08:00 - Codex - Task 17.2 BibTeX citations

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `17.2`.
- Files changed:
  - `src/autoresearch/reports/citations.py`
  - `src/autoresearch/reports/__init__.py`
  - `tests/unit/reports/test_citations.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added citation validation for `DocumentRecord` inputs with DOI-first verification, URL fallback, and blocked status for unverifiable citations.
  - Added BibTeX generation for verified DOI/URL citations and blocked comments plus metadata for unverifiable records.
  - Exported citation status, validation, artifact, and generation helpers from `autoresearch.reports`.
  - Marked task `17.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports/test_citations.py`: passed, 3 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 178 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 53 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `17.3` should version paper drafts with timestamps and source evidence graph version.

### 2026-06-11 22:14:04 +08:00 - Codex - Task 17.1 LaTeX skeleton

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `17.1`.
- Files changed:
  - `src/autoresearch/reports/latex.py`
  - `src/autoresearch/reports/__init__.py`
  - `tests/unit/reports/test_latex.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `LatexDraftContext`, `LatexDraftArtifact`, and `generate_latex_skeleton()` for evidence-backed LaTeX paper skeleton generation.
  - Rendered the required abstract, introduction, related work, method, experiments, results, limitations, and conclusion sections.
  - Used only claim statements and validated evidence traces from `EvidenceGraph`; missing sections or unsupported claims receive explicit TODO placeholders.
  - Added optional `pdflatex` compilation and exported LaTeX helpers from `autoresearch.reports`.
  - Marked task `17.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports/test_latex.py`: passed, 2 tests; the demo skeleton compiled with local TeX Live `pdflatex`.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 175 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 52 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `17.2` should generate BibTeX from verified citations and mark unverifiable citations as blocked.

### 2026-06-11 22:07:36 +08:00 - Codex - Task 16.3 figure/table consistency validator

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `16.3`.
- Files changed:
  - `src/autoresearch/reports/lint.py`
  - `src/autoresearch/reports/__init__.py`
  - `tests/unit/reports/test_lint.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Promoted metric consistency checking into explicit public validators: `lint_metric_consistency()` and `assert_metric_consistency()`.
  - Kept report lint using the same consistency path for text, Markdown tables, and figure alt/caption metric values.
  - Added a regression test that injects mismatched text, table, and figure metric values and confirms the validator fails.
  - Exported the consistency validator helpers from `autoresearch.reports`.
  - Marked task `16.3` and parent task `16` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports/test_lint.py`: passed, 7 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 173 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: initially failed on import sorting, then passed after ruff import fix.
  - `poetry run mypy src`: passed with no issues in 51 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-031` added and resolved.
- Follow-up:
  - Task `17.1` should generate a LaTeX skeleton from validated evidence without fabricating missing content.

### 2026-06-11 22:01:47 +08:00 - Codex - Task 16.2 comparison tables

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `16.2`.
- Files changed:
  - `src/autoresearch/reports/tables.py`
  - `src/autoresearch/reports/__init__.py`
  - `tests/unit/reports/test_tables.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added source-backed method comparison and ablation table generation from metrics JSON files.
  - Wrote Markdown tables plus metadata JSON containing run IDs, metric names, source paths, metric values, and evidence IDs.
  - Exported table generation helpers from `autoresearch.reports`.
  - Marked task `16.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports/test_tables.py`: passed, 3 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 172 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 51 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `16.3` should validate consistency across figures, tables, and report text.

### 2026-06-11 21:56:03 +08:00 - Codex - Task 16.1 figure artifacts

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `16.1`.
- Files changed:
  - `src/autoresearch/reports/figures.py`
  - `src/autoresearch/reports/__init__.py`
  - `tests/unit/reports/test_figures.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added source-backed metric bar figure generation from a metrics JSON file.
  - Generated vector PDF artifacts, PNG previews, and metadata JSON without adding external plotting dependencies.
  - Recorded the source metrics path, output artifact paths, metric names, metric values, and consistent style metadata.
  - Exported figure generation helpers from `autoresearch.reports`.
  - Marked task `16.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports/test_figures.py`: passed, 2 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 169 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 50 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `16.2` should generate source-backed comparison and ablation tables with run IDs or evidence IDs in metadata.

### 2026-06-11 21:48:32 +08:00 - Codex - Task 15.3 statistical sanity checks

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `15.3`.
- Files changed:
  - `src/autoresearch/experiments/validation.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_validation.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `StatisticalCheck` inputs and `StatisticalNote` report entries for validation-time statistical sanity checks.
  - Stored simple confidence intervals and repeated-run deltas in JSON and Markdown validation reports without treating those notes as failures.
  - Marked comparisons with sample sizes below their configured minimum as warning-level `statistical_power` issues with explicit "do not overstate significance" wording.
  - Exported statistical validation helpers from `autoresearch.experiments`.
  - Marked task `15.3` and parent task `15` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments/test_validation.py`: passed, 4 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 167 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 49 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `16.1` should generate publication-quality figure artifacts from source result files.

### 2026-06-11 21:40:22 +08:00 - Codex - Task 15.2 ablation planner

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `15.2`.
- Files changed:
  - `src/autoresearch/experiments/planner.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_planner.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `AblationVariable`, `AblationPlanningConfig`, `AblationPlanningError`, and `plan_ablation_matrix()`.
  - Planned one-factor-at-a-time ablation tasks from hypothesis variables instead of generating full factorial combinations.
  - Enforced `max_experiments`, total CPU budget, optional total GPU budget, and per-experiment resource budgets.
  - Added tests for generated ablation task metadata and budget-limited truncation.
  - Exported ablation planning helpers from `autoresearch.experiments`.
  - Marked task `15.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments/test_planner.py`: passed, 4 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 166 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 49 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-030` added and resolved.
- Follow-up:
  - Task `15.3` should add statistical sanity checks.

### 2026-06-11 21:33:47 +08:00 - Codex - Task 15.1 baseline reproducer

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `15.1`.
- Files changed:
  - `src/autoresearch/experiments/baselines.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_baselines.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `reproduce_tabular_baseline()` to generate, execute, collect, validate, and record the deterministic tabular baseline before proposed-method workflows.
  - Added `BaselineReproductionResult` with experiment directory, task, run, result bundle, validation report, and baseline record path.
  - Persisted a JSON baseline record containing baseline config, config hash, run ID, run status, metrics, and validation state.
  - Exported baseline reproduction helpers from `autoresearch.experiments`.
  - Added a demo baseline test that confirms the baseline run is validated and its record is written.
  - Marked task `15.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments/test_baselines.py tests/unit/experiments/test_demos.py tests/unit/experiments/test_validation.py`: passed, 8 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 164 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 49 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `15.2` should add an ablation planner with budget limits.

### 2026-06-11 21:28:46 +08:00 - Codex - Task 14.3 evidence consistency checks

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `14.3`.
- Files changed:
  - `src/autoresearch/reports/generator.py`
  - `src/autoresearch/reports/lint.py`
  - `tests/unit/reports/test_lint.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added report lint metric consistency checks that compare evidence-linked metric values in text, Markdown tables, and figure alt/caption text against the linked metrics JSON source file.
  - Kept consistency checks file-backed and opt-in through `base_dir`, preserving existing structure-only lint behavior when no source directory is available.
  - Added a regression test that catches deliberate text, table, and figure metric mismatches against `metrics.json`.
  - Moved report generator experiment imports away from module import time to avoid aggregate package circular imports.
  - Marked task `14.3` and parent task `14` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports/test_lint.py tests/unit/reports/test_report_generator.py`: passed, 9 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 163 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 48 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-028` added and resolved.
  - `P-20260611-029` added and resolved.
- Follow-up:
  - Task `15.1` should implement a baseline reproducer.

### 2026-06-11 21:20:13 +08:00 - Codex - Task 14.2 evidence coverage gate

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `14.2`.
- Files changed:
  - `src/autoresearch/evidence/__init__.py`
  - `src/autoresearch/evidence/graph.py`
  - `src/autoresearch/reports/generator.py`
  - `tests/unit/evidence/test_graph.py`
  - `tests/unit/reports/test_report_generator.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `ClaimStatus` and `EvidenceCoverageError` to the evidence graph.
  - Added `EvidenceGraph.require_core_claim_coverage()` to mark supported core claims as `supported` and unsupported core claims as `blocked`.
  - Added optional `evidence_graph` and `core_claim_ids` to report generation so reports fail when declared core claims lack validated evidence coverage.
  - Added tests for supported and blocked claim coverage plus report generation failure for an uncovered core claim.
  - Marked task `14.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/evidence/test_graph.py tests/unit/reports/test_report_generator.py tests/unit/experiments/test_evidence.py`: passed, 10 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 162 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 48 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-027` added and resolved.
- Follow-up:
  - Task `14.3` should add evidence consistency checks for table/text metric mismatches.

### 2026-06-11 21:14:41 +08:00 - Codex - Task 14.1 claim-evidence-source graph

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `14.1`.
- Files changed:
  - `src/autoresearch/evidence/__init__.py`
  - `src/autoresearch/evidence/graph.py`
  - `tests/unit/evidence/test_graph.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added a JSON-backed `EvidenceGraph` with `ClaimNode`, `EvidenceNode`, `SourceNode`, `EvidenceArtifact`, and `EvidenceTrace` models.
  - Added graph operations to add claims, sources, artifacts, link evidence, persist/load deterministic JSON, and traverse from a claim to source artifact validation status.
  - Added unit tests for JSON round-trip traversal and rejection of orphaned artifacts.
  - Marked task `14.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/evidence/test_graph.py tests/unit/experiments/test_evidence.py tests/unit/schemas`: passed, 21 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 160 tests passed and 1 optional live literature test skipped; emitted the existing non-failing LangGraph pending-deprecation warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 48 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-026` added and resolved.
- Follow-up:
  - Task `14.2` should enforce evidence coverage for core claims.

### 2026-06-11 21:08:00 +08:00 - Codex - Task 13.3 LangGraph workflow

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `13.3`.
- Files changed:
  - `src/autoresearch/agents/workflow.py`
  - `src/autoresearch/agents/__init__.py`
  - `tests/integration/agents/test_workflow.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added a LangGraph-backed `ResearchWorkflow` with typed stages for literature, hypothesis, experiment, report, and complete.
  - Added `WorkflowCheckpointStore` for JSON checkpoints, plus `start()` and `resume()` paths that persist the latest state after pause or completion.
  - Added an integration test that pauses after the literature stage, reloads the checkpoint, resumes from the hypothesis stage, and verifies completion.
  - Exported the workflow primitives from `autoresearch.agents`.
  - Marked task `13.3` and parent task `13` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/integration/agents/test_workflow.py`: passed, 1 test; emitted a non-failing LangGraph pending-deprecation warning.
  - `poetry run pytest tests/integration/agents/test_workflow.py tests/unit/agents tests/property/agents`: passed, 10 tests; emitted the same non-failing LangGraph warning.
  - `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`: passed, 158 tests passed and 1 optional live literature test skipped; emitted the same non-failing LangGraph warning.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 46 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-024` added and resolved.
  - `P-20260611-025` added and resolved.
- Follow-up:
  - Task `14.1` should implement the claim-evidence-source graph.

### 2026-06-11 20:57:44 +08:00 - Codex - Task 13.2 structured message protocol

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `13.2`.
- Files changed:
  - `src/autoresearch/agents/messages.py`
  - `src/autoresearch/agents/__init__.py`
  - `tests/unit/agents/test_messages.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added strict `AgentMessage` schema with message ID, sender, recipient, task ID, intent, input refs, expected output schema, deadline, budget, risk level, created timestamp, and metadata.
  - Added `MessageRiskLevel` and exported message protocol primitives from `autoresearch.agents`.
  - Added schema tests for valid round-trip messages and rejection of missing intent, missing or empty expected output schema, and free-text-only payloads.
  - Marked task `13.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/agents/test_messages.py tests/property/agents/test_registry.py`: passed, 9 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 157 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 45 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `13.3` should integrate LangGraph for a resumable mock workflow.

### 2026-06-11 20:53:23 +08:00 - Codex - Task 13.1 base Agent and registry

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `13.1`.
- Files changed:
  - `src/autoresearch/agents/base.py`
  - `src/autoresearch/agents/registry.py`
  - `src/autoresearch/agents/__init__.py`
  - `tests/property/agents/test_registry.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added base agent primitives: lifecycle state, task/result schemas, capability error, and `BaseAgent.run_task()` lifecycle/capability enforcement.
  - Added `AgentRegistry` with add, remove, get, list, role filter, capability lookup, and combined query operations.
  - Added property tests for registry add/get/list/remove consistency, duplicate ID rejection, capability query correctness, and base-agent lifecycle behavior.
  - Marked task `13.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/property/agents/test_registry.py`: passed, 4 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 152 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 44 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-023` added and resolved.
- Follow-up:
  - Task `13.2` should add the structured inter-agent message protocol.

### 2026-06-11 20:46:32 +08:00 - Codex - Task 12.4 MVP acceptance run

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `12.4`.
- Files changed:
  - `src/autoresearch/experiments/acceptance.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_acceptance.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `run_mvp_acceptance()` to run all currently available ScientistBench-Lite demos, rerun successful demos, compute full-loop and rerun success rates, and persist JSON plus Markdown acceptance reports.
  - Added failure-note writing under the configured Obsidian-compatible vault failure-patterns directory for failed initial runs or reruns.
  - Added an acceptance test confirming the report includes available demo count, run IDs, rerun IDs, success status, and rerun outcomes.
  - Marked task `12.4` and parent task `12` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments/test_acceptance.py tests/unit/experiments/test_demos.py tests/unit/cli/test_main.py`: passed, 9 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 148 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 41 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-021` added and resolved.
  - `P-20260611-022` added and resolved.
- Follow-up:
  - Task `13.1` should begin the multi-agent runtime with a base Agent class and registry.

### 2026-06-11 20:36:51 +08:00 - Codex - Task 12.3 MVP end-to-end command

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `12.3`.
- Files changed:
  - `src/autoresearch/experiments/demo_workflow.py`
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/cli/main.py`
  - `src/autoresearch/reports/generator.py`
  - `tests/unit/cli/test_main.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `run_scientistbench_demo()` to run a local demo through code generation, sandbox execution, result collection, validation, evidence binding, evidence-map persistence, and Markdown report generation.
  - Added `autoresearch run-demo` CLI command with demo name, output directory, and timeout options.
  - Added CLI test proving the command creates generated code, logs, metrics, validation JSON/Markdown, evidence map JSON, and an evidence-backed Markdown report.
  - Fixed report generator imports to avoid aggregate package cycles.
  - Marked task `12.3` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/cli/test_main.py tests/unit/experiments/test_demos.py`: passed, 8 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 147 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 40 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-020` added and resolved.
- Follow-up:
  - Task `12.4` should establish the MVP acceptance run and record run IDs plus rerun outcomes.

### 2026-06-11 20:24:27 +08:00 - Codex - Task 12.2 text_classifier_stub demo

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `12.2`.
- Files changed:
  - `src/autoresearch/experiments/demos.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_demos.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `create_text_classifier_stub_task()` for the ScientistBench-Lite `text_classifier_stub` local demo contract.
  - Added `generate_text_classifier_stub_demo()` to create a tiny text CSV fixture, config, standard-library keyword stub runner, logs, metrics, summary, predictions, and vocabulary artifact.
  - Added a full-loop test that generates the demo, executes it locally, collects metrics, validates expected metrics/artifacts, and confirms validation report success.
  - Marked task `12.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments/test_demos.py`: passed, 4 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 146 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 39 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `12.3` should add the MVP end-to-end command that creates code, logs, metrics, validation report, evidence map, and Markdown report.

### 2026-06-11 20:18:19 +08:00 - Codex - Task 12.1 tabular_baseline demo

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `12.1`.
- Files changed:
  - `src/autoresearch/experiments/demos.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_demos.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `create_tabular_baseline_task()` for the ScientistBench-Lite `tabular_baseline` local demo contract.
  - Added `generate_tabular_baseline_demo()` to create a tiny synthetic CSV classification fixture, config, standard-library runner, logs, metrics, summary, and predictions artifact.
  - Added an execution test that generates the demo, runs it through the local executor, collects metrics, validates expected metrics/artifacts, and confirms it completes under the configured timeout.
  - Marked task `12.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments/test_demos.py`: passed, 2 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 144 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 39 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-019` added and resolved.
- Follow-up:
  - Task `12.2` should add the local `text_classifier_stub` demo task.

### 2026-06-11 20:11:50 +08:00 - Codex - Task 11.3 reproducibility notes

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `11.3`.
- Files changed:
  - `src/autoresearch/reports/generator.py`
  - `src/autoresearch/reports/lint.py`
  - `tests/unit/reports/test_report_generator.py`
  - `tests/unit/reports/test_lint.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added report context fields for reproduction command, Python version, and dependency lock status.
  - Added a `## Reproducibility` report section containing command, Python version, dependency lock status, run ID, commit SHA, config hash, and data hash.
  - Updated report readability heading checks so the reproducibility section is part of the required generated report order.
  - Marked task `11.3` and parent task `11` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports`: passed, 7 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 142 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 38 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `12.1` should add the local `tabular_baseline` demo task for ScientistBench-Lite MVP checks.

### 2026-06-11 20:07:36 +08:00 - Codex - Task 11.2 report readability checks

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `11.2`.
- Files changed:
  - `src/autoresearch/reports/lint.py`
  - `src/autoresearch/reports/__init__.py`
  - `tests/unit/reports/test_lint.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added deterministic Markdown report lint checks for required heading order, Markdown table formatting, local relative link existence, and quantitative metric lines missing evidence references.
  - Added `assert_report_readable()` and exported the report lint APIs from `autoresearch.reports`.
  - Added focused tests proving valid reports pass and broken evidence links, heading order, table formatting, and missing metric evidence links fail.
  - Marked task `11.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports`: passed, 7 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 142 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 38 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-018` added and resolved.
- Follow-up:
  - Task `11.3` should add reproducibility notes to generated reports.

### 2026-06-11 20:01:14 +08:00 - Codex - Task 11.1 Markdown report generation

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `11.1`.
- Files changed:
  - `src/autoresearch/reports/__init__.py`
  - `src/autoresearch/reports/generator.py`
  - `tests/unit/reports/test_report_generator.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `ReportContext` and `generate_markdown_report()` for MVP Markdown research reports.
  - Generated required sections: question, literature summary, hypothesis, experiment design, run metadata, results, validation, limitations, and next steps.
  - Linked each generated quantitative metric claim to an `EvidenceEdge` ID and source artifact path.
  - Reused the evidence binding gate so reports cannot use metrics without validated evidence edges.
  - Marked task `11.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/reports/test_report_generator.py`: passed, 2 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 137 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 37 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-017` added and resolved.
- Follow-up:
  - Task `11.2` should add deterministic report readability checks.

### 2026-06-11 19:56:47 +08:00 - Codex - Task 10.3 evidence binding

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `10.3`.
- Files changed:
  - `src/autoresearch/experiments/evidence.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_evidence.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `bind_metrics_to_evidence()` to convert validated result metrics into `EvidenceEdge` records.
  - Added `require_evidence_for_metrics()` to block claim/report generation when metrics lack validated evidence edges.
  - Allowed passed and warning validation reports as evidence-bearing statuses while rejecting failed validation reports.
  - Marked task `10.3` and parent task `10` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments/test_evidence.py`: passed, 4 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 135 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 35 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `11.1` should generate the MVP Markdown research report from evidence.

### 2026-06-11 19:52:54 +08:00 - Codex - Task 10.2 validation report

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `10.2`.
- Files changed:
  - `src/autoresearch/experiments/validation.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_validation.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `validate_result_bundle()` plus `ValidationReport` and `ValidationIssue` types.
  - Validated run completion, expected metric presence, metric bounds, artifact existence, config hash match, data hash presence, and cost record presence.
  - Produced deterministic JSON and Markdown reports under `validation/`.
  - Implemented pass, warning, and fail status aggregation.
  - Marked task `10.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments/test_validation.py`: passed, 3 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 131 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 34 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `10.3` should bind validated metrics to `EvidenceEdge` records and block claim generation from unvalidated results.

### 2026-06-11 19:48:10 +08:00 - Codex - Task 10.1 result collector

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `10.1`.
- Files changed:
  - `src/autoresearch/experiments/results.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_results.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `collect_result_bundle()` to parse `metrics.json`, configured CSV metric outputs, logs, and generated artifacts into `ResultBundle`.
  - Supported generated runner payloads with nested `metrics` objects and top-level numeric metric JSON.
  - Rejected successful runs with missing or invalid metric files while allowing explicitly failed, timed-out, or cancelled runs to produce failed result bundles without metrics.
  - Read `artifacts/summary.md` into the bundle summary and recorded logs/artifacts as experiment-relative paths.
  - Enforced sandbox path checks for configured metric and CSV output paths.
  - Marked task `10.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments/test_results.py`: passed, 5 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 128 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed after import-order fix.
  - `poetry run mypy src`: passed with no issues in 33 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-016` added and resolved.
- Follow-up:
  - Task `10.2` should add validation reports for run completion, metrics, artifacts, hashes, and cost records.

### 2026-06-11 19:43:01 +08:00 - Codex - Task 9.3 restricted network policy placeholder

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `9.3`.
- Files changed:
  - `src/autoresearch/experiments/network.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_network.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `RestrictedNetworkPolicy` and default allowed domains for academic APIs, package sources, and repository sources.
  - Added preflight allow/deny decisions for URLs and domains, including subdomain matching.
  - Added blocked-request audit logging with `AuditEventType.SANDBOX_DENIAL`.
  - Documented the MVP boundary with `network_enforcement_note()`: network policy is preflight/audit only and does not install OS-level firewall or proxy enforcement.
  - Marked task `9.3` and parent task `9` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments/test_network.py tests/unit/observability/test_audit.py`: passed, 18 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 123 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed after import-order fix.
  - `poetry run mypy src`: passed with no issues in 32 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-014` added as mitigated.
  - `P-20260611-015` added and resolved.
- Follow-up:
  - Task `10.1` should collect and validate experiment outputs into `ResultBundle` records.

### 2026-06-11 19:38:10 +08:00 - Codex - Task 9.2 sandbox executor runtime limits

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `9.2`.
- Files changed:
  - `src/autoresearch/experiments/executor.py`
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/schemas/models.py`
  - `tests/unit/experiments/test_executor.py`
  - `tests/unit/schemas/test_provenance.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `execute_experiment_task()` for local sandbox subprocess execution.
  - Enforced wall-clock timeout with process cleanup and captured memory-limit violations when process RSS can be observed.
  - Added Unix resource-limit setup for CPU and memory through platform-safe runtime branches.
  - Stored status, exit code, stdout, stderr, start/end time, metrics path, artifact URI, config hash, and limit violations on `ExecutionRun`.
  - Added tests for successful execution, nonzero exit capture, timeout cleanup, and sandbox entrypoint denial.
  - Marked task `9.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments/test_executor.py tests/unit/schemas/test_provenance.py`: passed, 10 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 114 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 31 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - `P-20260611-013` added and resolved.
- Follow-up:
  - Task `9.3` should add the restricted network policy placeholder and audit logging for blocked network requests where enforceable.

### 2026-06-11 19:30:50 +08:00 - Codex - Task 9.1 sandbox path restrictions

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `9.1`.
- Files changed:
  - `src/autoresearch/experiments/sandbox.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/property/experiments/test_sandbox.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `SandboxPathPolicy` for local sandbox filesystem access decisions.
  - Allowed reads and writes only within the experiment directory plus explicitly configured cache and output directories.
  - Resolved relative and absolute paths before checking allowlisted roots, so traversal attempts are blocked after normalization.
  - Added explicit denials for project-root and user-home secret-like paths outside the allowed roots.
  - Rejected unsafe allowed-root configuration such as using the user home or project root as an allowed root.
  - Marked task `9.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/property/experiments/test_sandbox.py`: passed, 7 tests.
  - `poetry run pytest tests/unit tests/property tests/smoke`: passed, 110 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 30 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `9.2` should add runtime limits and execution-run capture around local subprocess execution.

### 2026-06-11 19:25:32 +08:00 - Codex - Task 8.3 generated code review checks

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `8.3`.
- Files changed:
  - `src/autoresearch/experiments/review.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_review.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added static generated-code review results and findings for experiment runners.
  - Blocked representative dangerous command execution, path traversal, secret reads, unrestricted network imports, and missing `metrics.json` writes before execution.
  - Added quarantine support that writes `QUARANTINED` plus `quarantine/review-findings.json` for unsafe generated code.
  - Exported review helpers from `autoresearch.experiments`.
  - Marked task `8.3` and parent task `8` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments`: passed, 12 tests.
  - `poetry run pytest tests/unit/experiments tests/smoke tests/unit`: passed, 99 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 29 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `9.1` should implement local sandbox path restrictions for experiment execution.

### 2026-06-11 19:20:47 +08:00 - Codex - Task 8.2 runnable experiment directories

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `8.2`.
- Files changed:
  - `src/autoresearch/experiments/generator.py`
  - `src/autoresearch/experiments/__init__.py`
  - `tests/unit/experiments/test_generator.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `generate_experiment_directory()` for deterministic MVP experiment directory creation.
  - Generated `README.md`, `config.yaml`, `requirements.txt`, `run.py`, `logs/`, and `artifacts/` from an `ExperimentTask`.
  - Made generated demo experiments write `metrics.json`, `logs/run.log`, and `artifacts/summary.md` on success.
  - Made generated demo experiments write failed `metrics.json` and `logs/run.log` on graceful failure.
  - Kept generated requirements aligned with the YAML-based runner by declaring `pyyaml>=6.0`.
  - Marked task `8.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments tests/smoke tests/unit`: passed, 92 tests passed and 1 optional live literature test skipped.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 28 source files; mypy emitted the existing non-failing unused override-section note.
- Problems:
  - None.
- Follow-up:
  - Task `8.3` should add generated code review checks before execution.

### 2026-06-11 19:14:54 +08:00 - Codex - Task 8.1 experiment task planner

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `8.1`.
- Files changed:
  - `src/autoresearch/experiments/__init__.py`
  - `src/autoresearch/experiments/planner.py`
  - `src/autoresearch/schemas/models.py`
  - `tests/unit/experiments/test_planner.py`
  - `tests/unit/schemas/test_roundtrip.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added deterministic experiment task planning from `Hypothesis` records.
  - Added `ExperimentPlanningConfig` for CPU, memory, GPU, storage, and timeout limits.
  - Generated `ExperimentTask` records with entry point, config path, metrics, resource budget, timeout, expected outputs, dependencies, dataset assumptions, and validation checks.
  - Added schema constraints so experiment task name, description, entry point, config path, and metrics cannot be empty.
  - Added tests for required fields, validation checks, and budget-limit behavior.
  - Marked task `8.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/experiments tests/unit/schemas tests/smoke tests/unit`: passed, 89 tests and 1 skipped optional live smoke test.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 27 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - None.
- Follow-up:
  - Task `8.2` should generate minimal runnable experiment directories.

### 2026-06-11 19:12:24 +08:00 - Codex - Task 7.3 hypothesis generation

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `7.3`.
- Files changed:
  - `src/autoresearch/research/hypotheses.py`
  - `src/autoresearch/research/__init__.py`
  - `src/autoresearch/schemas/models.py`
  - `tests/unit/research/test_hypotheses.py`
  - `tests/unit/schemas/test_roundtrip.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added deterministic hypothesis generation from approved `ResearchCandidate` records.
  - Required candidates to be `APPROVED` before hypothesis generation.
  - Derived metric, baseline, dataset reference, prediction, and evidence references from candidate metadata and evidence.
  - Added schema constraints so hypothesis statement, prediction, metric, and baseline cannot be empty strings.
  - Added tests for approved-candidate hypothesis generation, unapproved-candidate rejection, and schema rejection of empty metric plus missing evidence refs.
  - Marked task `7.3` and parent task `7` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/research tests/unit/schemas tests/smoke tests/unit`: passed, 86 tests and 1 skipped optional live smoke test.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 25 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - None.
- Follow-up:
  - Task `8.1` should convert hypotheses into deterministic experiment task records.

### 2026-06-11 19:09:50 +08:00 - Codex - Task 7.2 human approval gate

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `7.2`.
- Files changed:
  - `src/autoresearch/research/approval.py`
  - `src/autoresearch/research/__init__.py`
  - `tests/unit/research/test_approval.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `ApprovalRecord` with user, timestamp, candidate ID, notes, approval ID, and approval state.
  - Added `ProjectAgentContext` for the project context created after approval.
  - Added `create_project_from_approved_candidate()` to reject missing, rejected, or mismatched approvals before creating a project directory.
  - Reused the Obsidian vault layout creator so approved candidates create project knowledge/progress/issues/experience/experiments/results/evidence/paper directories.
  - Added tests that reject project creation without approval, reject mismatched approval records, require approval metadata, and create a project only after approval.
  - Marked task `7.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/research tests/smoke tests/unit`: passed, 83 tests and 1 skipped optional live smoke test.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 24 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - None.
- Follow-up:
  - Task `7.3` should generate hypotheses from approved candidates with measurable metrics and evidence references.

### 2026-06-11 19:07:15 +08:00 - Codex - Task 7.1 research candidate generation

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `7.1`.
- Files changed:
  - `src/autoresearch/research/__init__.py`
  - `src/autoresearch/research/candidates.py`
  - `tests/unit/research/test_candidates.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added a deterministic research candidate generator from retrieved `DocumentRecord` metadata.
  - Extracted simple method, limitation, and dataset/benchmark signals from paper titles and abstracts.
  - Clustered papers by repeated method/limitation/dataset signals.
  - Scored generated `ResearchCandidate` records for novelty, feasibility, impact, evidence coverage, and estimated cost.
  - Stored evidence coverage, estimated cost, rank score, cluster key, method, dataset, and limitation in candidate metadata.
  - Marked candidates with insufficient evidence as `draft` and evidence-backed candidates as `ready_for_review`.
  - Added deterministic ranking tests and low-evidence draft tests.
  - Marked task `7.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/research tests/smoke tests/unit`: passed, 79 tests and 1 skipped optional live smoke test.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 23 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - `P-20260611-012` added and resolved for dataset phrase normalization and import ordering during candidate generation verification.
- Follow-up:
  - Task `7.2` should add the human approval gate before project creation.

### 2026-06-11 19:02:06 +08:00 - Codex - Task 6.4 store paper notes in knowledge base

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `6.4`.
- Files changed:
  - `src/autoresearch/literature/storage.py`
  - `src/autoresearch/literature/__init__.py`
  - `tests/integration/literature/test_store_papers.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added conversion from `AcademicPaper` metadata to `DocumentRecord`.
  - Added conversion from paper metadata and document records to Obsidian-readable `KnowledgeEntry` paper notes.
  - Added `store_paper_notes()` to write retrieved paper metadata into project or exploration knowledge paths.
  - Included source URL/DOI, retrieval timestamp, authors, venue, publication date, and metadata abstract without generating summaries.
  - Added an integration test that stores mocked retrieved papers and reloads the Markdown knowledge entry.
  - Marked task `6.4` and parent task `6` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/integration/literature tests/unit/literature tests/smoke tests/unit`: passed, 78 tests and 1 skipped optional live smoke test.
  - `poetry run ruff check src tests`: passed after applying ruff's import-order fix.
  - `poetry run mypy src`: passed with no issues in 21 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - `P-20260611-011` added and resolved for the temporary ruff import-order failure.
- Follow-up:
  - Task `7.1` should generate and score research candidates from retrieved literature.

### 2026-06-11 18:59:09 +08:00 - Codex - Task 6.3 retrieval cache

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `6.3`.
- Files changed:
  - `src/autoresearch/literature/cache.py`
  - `src/autoresearch/literature/__init__.py`
  - `tests/unit/literature/test_cache.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `RetrievalCacheRecord` for serialized literature cache payloads.
  - Added stable `retrieval_cache_key()` using query, source, page, limit, and config.
  - Added filesystem-backed `RetrievalCache` with a default 24-hour TTL.
  - Added `get_or_fetch()` so repeated identical requests reuse cached successful responses.
  - Added tests for key sensitivity, identical-query cache reuse, different-query miss, and 24-hour expiry.
  - Marked task `6.3` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/literature tests/smoke tests/unit`: passed, 77 tests and 1 skipped optional live smoke test.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 20 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - None.
- Follow-up:
  - Task `6.4` should store retrieved paper metadata as Obsidian Markdown paper notes without summarization.

### 2026-06-11 18:56:25 +08:00 - Codex - Task 6.2 ArXiv and Semantic Scholar clients

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `6.2`.
- Files changed:
  - `src/autoresearch/literature/clients.py`
  - `src/autoresearch/literature/__init__.py`
  - `tests/unit/literature/test_clients.py`
  - `tests/smoke/test_literature_live.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added injectable `RateLimiter` and `RetryConfig` for literature API clients.
  - Added `ArxivClient` with Atom parsing into `AcademicPaper`.
  - Added `SemanticScholarClient` with Graph API JSON parsing into `AcademicPaper`.
  - Kept CNKI, WanFang, DBLP, and PubMed out of scope as planned later extensions.
  - Added mocked client tests for ArXiv retry/parsing and Semantic Scholar parsing.
  - Added an optional live smoke test gated by `AUTORESEARCH_LIVE_LITERATURE=1`, skipped by default.
  - Marked task `6.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/literature tests/smoke tests/unit`: passed, 74 tests and 1 skipped optional live smoke test.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 19 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - `P-20260611-010` added and resolved for the temporary mypy HTTP helper typing failure.
- Follow-up:
  - Task `6.3` should implement a 24-hour retrieval cache keyed by query, source, page/limit, and config.

### 2026-06-11 18:52:36 +08:00 - Codex - Task 6.1 academic paper model and deduplication

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `6.1`.
- Files changed:
  - `src/autoresearch/literature/__init__.py`
  - `src/autoresearch/literature/models.py`
  - `tests/unit/literature/test_literature_models.py`
  - `tests/property/literature/test_deduplication.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `AcademicPaper` metadata with title, authors, abstract, publication date, venue, DOI, URL, citation count, and source.
  - Added DOI normalization for plain DOI, `doi:` prefix, and doi.org URLs.
  - Added title normalization and high-similarity title comparison.
  - Added `deduplicate_papers()` that removes duplicates by DOI first and title similarity second.
  - Added unit tests for paper metadata validation and normalizers.
  - Added property tests for DOI duplicate removal and high-similarity title duplicate removal.
  - Marked task `6.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/literature tests/property/literature tests/smoke tests/unit`: passed, 74 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 18 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - `P-20260611-009` added and resolved for the temporary pytest test module basename collision.
- Follow-up:
  - Task `6.2` should implement mocked ArXiv and Semantic Scholar clients plus a skipped optional live smoke test.

### 2026-06-11 18:50:03 +08:00 - Codex - Task 5.5 version history backups and rollback

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `5.5`.
- Files changed:
  - `src/autoresearch/knowledge/entries.py`
  - `src/autoresearch/knowledge/__init__.py`
  - `tests/unit/knowledge/test_versioning.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `VersionSnapshot` for inspectable Markdown version history.
  - Updated `MarkdownKnowledgeStore.write_entry()` to preserve the previous Markdown file before overwriting an existing entry.
  - Added `list_versions()` to retrieve saved snapshots plus the current entry as the latest version.
  - Added `rollback()` to restore a selected prior version and rebuild link/topic indexes afterward.
  - Added `backup_if_due()` with a validated 1-26 hour interval and filesystem backup snapshots under `.backups/`.
  - Excluded internal `.versions/` and `.backups/` files from normal knowledge-entry indexing.
  - Added tests for N+1 version retrieval, rollback, backup interval scheduling, and interval validation.
  - Marked task `5.5` and parent task `5` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/knowledge tests/property/knowledge tests/smoke tests/unit`: passed, 71 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 16 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - None.
- Follow-up:
  - Task `6.1` should implement academic paper metadata and deduplication.

### 2026-06-11 18:46:08 +08:00 - Codex - Task 5.4 zone and project permissions

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `5.4`.
- Files changed:
  - `src/autoresearch/knowledge/permissions.py`
  - `src/autoresearch/knowledge/__init__.py`
  - `tests/property/knowledge/test_permissions.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `AgentRole`, `AccessMode`, and `PermissionManager` for local Obsidian vault permissions.
  - Allowed Main and Fixed Agents to read/write inside the vault.
  - Allowed Project Agents to read exploration and read/write only their own project directory.
  - Added Validator Agent read-only behavior for future validation workflows.
  - Added guarded `write_text()` and `read_text()` helpers with path traversal protection.
  - Added audit events for denied writes, preserving target file contents.
  - Added property tests for cross-project denial and Main Agent universal write access.
  - Marked task `5.4` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/property/knowledge tests/unit/knowledge tests/smoke tests/unit`: passed, 67 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 16 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - `P-20260611-008` added and resolved for the temporary Hypothesis fixture health-check failure.
- Follow-up:
  - Task `5.5` should add Obsidian-friendly version history, backups, and rollback.

### 2026-06-11 18:43:06 +08:00 - Codex - Task 5.3 wiki-links and topic index

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `5.3`.
- Files changed:
  - `src/autoresearch/knowledge/entries.py`
  - `src/autoresearch/knowledge/__init__.py`
  - `tests/unit/knowledge/test_links.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added Obsidian wiki-link extraction for `[[entry-id]]` and `[[path|label]]` syntax.
  - Added `links` and `backlinks` frontmatter fields to `KnowledgeEntry`.
  - Updated `MarkdownKnowledgeStore.write_entry()` to rebuild link metadata after writes.
  - Added bidirectional backlink maintenance by resolving targets through entry IDs and Markdown paths.
  - Added topic index generation at `exploration/index.md` and keyword lookup via `find_by_keyword()`.
  - Added tests that link paper, experiment, and skill entries, then verify backlinks and topic-index retrieval.
  - Marked task `5.3` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/knowledge tests/smoke tests/unit`: passed, 65 tests.
  - `poetry run ruff check src tests`: passed after applying ruff's import-order fix.
  - `poetry run mypy src`: passed with no issues in 15 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - `P-20260611-007` added and resolved for the temporary ruff import-order failure.
- Follow-up:
  - Task `5.4` should enforce zone and project permissions and emit audit events for denied writes.

### 2026-06-11 18:40:32 +08:00 - Codex - Task 5.2 Markdown knowledge entry model

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `5.2`.
- Files changed:
  - `src/autoresearch/knowledge/entries.py`
  - `src/autoresearch/knowledge/__init__.py`
  - `tests/unit/knowledge/test_entries.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `KnowledgeEntryType` for paper notes, dataset cards, method cards, experiment records, failure cases, skill cards, strategy cards, evidence notes, project progress, issue notes, and review notes.
  - Added `KnowledgeZone` and `KnowledgeEntry` with stable entry ID, type, zone, project ID, tags, keywords, source refs, created/updated timestamps, related task IDs, related run IDs, and Markdown body.
  - Added YAML frontmatter serialization and parsing while keeping the body as plain Obsidian-readable Markdown.
  - Added `MarkdownKnowledgeStore` for filesystem-based read/write of entries.
  - Added tests that write and read every required entry type while preserving frontmatter and body.
  - Marked task `5.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/knowledge tests/smoke tests/unit`: passed, 63 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 15 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - None.
- Follow-up:
  - Task `5.3` should add Obsidian wiki-links, backlinks, and topic index maintenance.

### 2026-06-11 18:38:14 +08:00 - Codex - Task 5.1 Obsidian vault layout

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `5.1`.
- Files changed:
  - `src/autoresearch/knowledge/__init__.py`
  - `src/autoresearch/knowledge/vault.py`
  - `tests/unit/knowledge/test_vault.py`
  - `autoresearch-vault/exploration/index.md`
  - `autoresearch-vault/exploration/*/.gitkeep`
  - `autoresearch-vault/projects/autoresearch-system/index.md`
  - `autoresearch-vault/projects/autoresearch-system/*/.gitkeep`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `create_vault_layout()` for Obsidian-compatible vault creation in any project root.
  - Defined required exploration directories for topics, skills, methodologies, datasets, failure patterns, and strategy cards.
  - Defined required project directories for knowledge, progress, issues, experience, experiments, results, evidence, and paper drafts.
  - Added path-safe project ID validation and default Markdown index creation for exploration and project zones.
  - Added the actual repository vault skeleton under `autoresearch-vault/`, including the current `projects/autoresearch-system/` layout.
  - Added unit tests that create the full layout in a temp directory and reject unsafe project IDs.
  - Marked task `5.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/knowledge tests/smoke tests/unit`: passed, 50 tests.
  - `poetry run ruff check src tests`: passed after applying ruff's import-order fix.
  - `poetry run mypy src`: passed with no issues in 14 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - `P-20260611-006` added and resolved for the temporary ruff import-order failure.
- Follow-up:
  - Task `5.2` should implement Markdown knowledge entries with YAML frontmatter.

### 2026-06-11 18:35:42 +08:00 - Codex - Task 4.3 release gate checklist

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `4.3`.
- Files changed:
  - `docs/release-gate.md`
  - `README.md`
  - `README.zh-CN.md`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added a release gate checklist for release tags, demos, and production-ready claims.
  - Covered unit/smoke tests, golden-test regression, security checks, docs updates, reversible migrations, changelog/release notes, git tags, and `autoresearch-vault/` provenance continuity.
  - Included Chinese checklist content in the same release-gate document.
  - Linked the release gate from both English and Chinese README files.
  - Marked task `4.3` and parent task `4` complete in `tasks.md`.
- Verification:
  - `Test-Path docs/release-gate.md`: passed.
  - `rg` confirmed release requirements for tests, golden tests, security, docs, reversible migrations, changelog/release notes, git tag, and `autoresearch-vault/`.
  - `rg` confirmed both README files link to `docs/release-gate.md`.
- Problems:
  - None.
- Follow-up:
  - Task `5.1` should implement the Obsidian vault contract and directory layout under `autoresearch-vault/`.

### 2026-06-11 18:33:44 +08:00 - Codex - Task 4.2 local developer check command

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `4.2`.
- Files changed:
  - `scripts/check.py`
  - `README.md`
  - `README.zh-CN.md`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `python scripts/check.py` as the local quality gate command.
  - The script runs the same default gates as CI: `ruff`, `mypy`, and smoke/unit pytest.
  - Updated English and Chinese README setup sections to point contributors to the script.
  - Marked task `4.2` complete in `tasks.md`.
- Verification:
  - `python scripts/check.py`: passed; it ran `ruff`, `mypy`, and 45 smoke/unit tests successfully.
- Problems:
  - None.
- Follow-up:
  - Task `4.3` should add and link the release gate checklist.

### 2026-06-11 18:32:06 +08:00 - Codex - Task 4.1 GitHub Actions workflow

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `4.1`.
- Files changed:
  - `.github/workflows/ci.yml`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added a Python 3.10 GitHub Actions workflow for pushes to `main` and pull requests.
  - Added CI install steps using Poetry.
  - Matched CI quality gates to the local green commands: `ruff`, `mypy`, and smoke/unit pytest.
  - Kept external-network and future integration/property tests out of the default CI path.
  - Marked task `4.1` complete in `tasks.md`.
- Verification:
  - `Test-Path .github/workflows/ci.yml`: passed.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 12 source files; mypy emitted the existing non-failing unused override note for optional integrations.
  - `poetry run pytest tests/smoke tests/unit`: passed, 45 tests.
- Problems:
  - None.
- Follow-up:
  - Task `4.2` should add or document the local developer check command to prevent CI/local command drift.

### 2026-06-11 18:30:33 +08:00 - Codex - Task 3.3 cost record schema

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `3.3`.
- Files changed:
  - `src/autoresearch/schemas/models.py`
  - `src/autoresearch/schemas/__init__.py`
  - `tests/unit/schemas/test_schema_models.py`
  - `tests/unit/schemas/test_roundtrip.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `CostRecord` with required model name, input/output token counts, CPU time, GPU hours, storage artifact bytes, network cost placeholder, and human approval count.
  - Added numeric bounds for cost fields and required non-empty model names.
  - Attached cost records to `ExecutionRun` through an optional `cost_record` field while preserving the existing `cost_json` escape hatch.
  - Exported `CostRecord` from `autoresearch.schemas`.
  - Added round-trip and validation tests for cost records and execution-run attachment.
  - Marked task `3.3` and parent task `3` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/schemas tests/smoke tests/unit`: passed, 45 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 12 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - `P-20260611-005` added and resolved for the temporary schema test assertion failure.
- Follow-up:
  - Task `4.1` should add the GitHub Actions CI workflow.

### 2026-06-11 18:27:08 +08:00 - Codex - Task 3.2 audit event schema

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `3.2`.
- Files changed:
  - `src/autoresearch/observability/audit.py`
  - `src/autoresearch/observability/__init__.py`
  - `tests/unit/observability/test_audit.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added `AuditEventType` for permission checks, sandbox denials, config changes, approval gates, strategy changes, and publication gates.
  - Added the `AuditEvent` Pydantic schema with actor/action/resource context, run/project/task links, approval state, and metadata.
  - Added `AuditLog` append/read helpers that persist JSONL events under a local project audit directory.
  - Exported audit helpers from `autoresearch.observability`.
  - Added unit tests for event type coverage, append/reload losslessness, missing log handling, and default audit path.
  - Marked task `3.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/observability tests/smoke tests/unit`: passed, 44 tests.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 12 source files; mypy emitted the existing non-failing unused override note for optional integrations.
- Problems:
  - `P-20260611-004` added and resolved for the PowerShell commit command separator issue.
- Follow-up:
  - Task `3.3` should add cost records and attach them to execution runs.

### 2026-06-11 19:40:00 +08:00 - Codex - Task 3.1 structured logging

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `3.1`.
- Files changed:
  - `src/autoresearch/observability/__init__.py`
  - `src/autoresearch/observability/logging.py`
  - `tests/unit/observability/test_logging.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added an `observability` package with a structured logging helper.
  - Added `get_logger()` returning a `LoggerAdapter` that attaches `run_id`, component, project ID, and task ID to each log record.
  - Added `configure_logging()` with a human-readable format that still carries structured fields for future JSON logging.
  - Added tests that confirm log records include run context and placeholder defaults.
  - Marked task `3.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/observability tests/smoke tests/unit`: passed, 35 tests with coverage enabled.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 11 source files; mypy emitted a non-failing note about currently unused override modules.
- Problems:
  - None.
- Follow-up:
  - Task `3.2` should define audit event schemas and append-only JSONL storage.

### 2026-06-11 19:25:00 +08:00 - Codex - Task 2.3 schema round-trip tests

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `2.3`.
- Files changed:
  - `src/autoresearch/schemas/models.py`
  - `tests/unit/schemas/test_schema_models.py`
  - `tests/unit/schemas/test_roundtrip.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added JSON round-trip tests for every core lifecycle schema.
  - Added schema validation tests that reject research candidates and hypotheses without evidence references.
  - Added a strict extra-field policy on base lifecycle records while preserving `metadata` as the explicit extension point.
  - Updated existing schema fixtures to include evidence references where now required.
  - Marked task `2.3` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/schemas tests/smoke tests/unit`: passed, 33 tests with coverage enabled.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 9 source files; mypy emitted a non-failing note about currently unused override modules.
- Problems:
  - None.
- Follow-up:
  - Task `3.1` should add structured logging with run context.

### 2026-06-11 19:15:00 +08:00 - Codex - Task 2.2 run ID and provenance helpers

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `2.2`.
- Files changed:
  - `src/autoresearch/schemas/provenance.py`
  - `src/autoresearch/schemas/__init__.py`
  - `tests/unit/schemas/test_provenance.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added provenance helpers for unique run IDs, stable config hashes, inline data hashes, file hashes, and normalized artifact URIs.
  - Exported provenance helpers from `autoresearch.schemas`.
  - Added tests for stable hash generation, unique run ID generation, file hashing, artifact URI construction, and storing provenance fields on `ExecutionRun`.
  - Marked task `2.2` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/schemas tests/smoke tests/unit`: passed, 29 tests with coverage enabled.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 9 source files; mypy emitted a non-failing note about currently unused override modules.
- Problems:
  - None.
- Follow-up:
  - Task `2.3` should add schema round-trip tests and missing-evidence validation expectations.

### 2026-06-11 19:00:00 +08:00 - Codex - Task 2.1 research lifecycle schemas

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `2.1`.
- Files changed:
  - `src/autoresearch/schemas/__init__.py`
  - `src/autoresearch/schemas/models.py`
  - `tests/unit/schemas/test_schema_models.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Added the core Pydantic lifecycle schemas: `DocumentRecord`, `KnowledgeNode`, `ResearchCandidate`, `Hypothesis`, `ExperimentTask`, `ExecutionRun`, `ResultBundle`, `EvidenceEdge`, `PaperDraft`, and `StrategyCard`.
  - Added shared record provenance fields, stable prefixed IDs, UTC timestamps, metadata, status enums, and validation status fields.
  - Kept schema fields MVP-focused and aligned with the Kiro design and execution plan without introducing later helper objects from task `2.2`.
  - Added unit tests that instantiate each core schema and serialize them to JSON.
  - Marked task `2.1` complete in `tasks.md`.
- Verification:
  - `poetry run pytest tests/unit/schemas tests/smoke tests/unit`: passed, 23 tests with coverage enabled.
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 8 source files; mypy emitted a non-failing note about currently unused override modules.
- Problems:
  - None.
- Follow-up:
  - Task `2.2` should add deterministic run IDs, config/data hashes, and artifact reference helpers.

### 2026-06-11 18:45:00 +08:00 - Codex - Task 1.5 repository quality commands

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `1.5`.
- Files changed:
  - `pyproject.toml`
  - `src/autoresearch/config/parser.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Agent.md`
- Summary:
  - Confirmed the repository quality gates for ruff, mypy, and pytest against the current `src` package layout and tests.
  - Added `pythonpath = ["src"]` in task `1.4`, then verified it works with coverage-enabled pytest commands in this task.
  - Migrated ruff settings from deprecated top-level lint keys into `[tool.ruff.lint]` without relaxing any selected rules.
  - Simplified TOML parsing/formatting to use the declared `toml` dependency, which made the parser friendlier to Python 3.10 mypy settings.
  - Marked task `1.5` complete in `tasks.md`.
- Verification:
  - `poetry run ruff check src tests`: passed.
  - `poetry run mypy src`: passed with no issues in 6 source files; mypy emitted a non-failing note about currently unused override modules.
  - `poetry run pytest tests/smoke tests/unit`: passed, 21 tests with coverage enabled.
- Problems:
  - None.
- Follow-up:
  - The mypy override note can be revisited after modules start importing optional external integrations, but it does not block the current quality gate.

### 2026-06-11 18:35:00 +08:00 - Codex - Task 1.4 test scaffold

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `1.4`.
- Files changed:
  - `tests/smoke/test_imports.py`
  - `tests/smoke/test_cli.py`
  - `tests/integration/.gitkeep`
  - `tests/property/.gitkeep`
  - `pyproject.toml`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added smoke tests for importing `autoresearch`, importing `autoresearch.config`, and running the local-only CLI doctor command.
  - Added tracked placeholders for `tests/integration` and `tests/property`.
  - Added `pythonpath = ["src"]` to pytest configuration so tests import the package without manual environment variables.
  - Installed missing local verification tools into the active Python environment: Poetry, pytest-cov, pytest-asyncio, and ruff.
  - Marked task `1.4` complete in `tasks.md`.
- Verification:
  - `poetry --version`: passed, printed `Poetry (version 2.4.1)`.
  - `poetry run pytest tests/smoke tests/unit/config`: passed, 18 tests with coverage enabled.
  - `python -m pytest tests/smoke tests/unit/config`: passed, 18 tests with coverage enabled.
  - `poetry run pytest tests/smoke tests/unit`: passed, 21 tests with coverage enabled.
- Problems:
  - `P-20260611-003` resolved.
- Follow-up:
  - Task `1.5` should run and harden the broader `ruff`, `mypy`, and pytest checks.

### 2026-06-11 18:20:00 +08:00 - Codex - Task 1.3 minimal CLI skeleton

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `1.3`.
- Files changed:
  - `src/autoresearch/cli/__init__.py`
  - `src/autoresearch/cli/main.py`
  - `tests/unit/cli/test_main.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added a minimal Typer CLI app matching the `pyproject.toml` entry point.
  - Added `version`, `doctor`, and `init-demo` commands.
  - Kept `doctor` local-only: it checks Python version, package import, config import, parser availability, project root, and `autoresearch-vault/`.
  - Kept `init-demo` as a scaffold creator only; it does not run a research workflow.
  - Added focused CLI tests using Typer's `CliRunner`.
  - Marked task `1.3` complete in `tasks.md`.
- Verification:
  - `PYTHONPATH=src python -m pytest -o addopts='' tests/unit/cli/test_main.py tests/unit/config/test_models.py tests/unit/config/test_parser.py`: passed, 18 tests.
  - `PYTHONPATH=src python -m autoresearch.cli.main version`: passed, printed `0.1.0`.
  - `PYTHONPATH=src python -m autoresearch.cli.main doctor`: passed, all local scaffold checks reported OK.
  - `poetry run autoresearch version` and `poetry run autoresearch doctor` remain blocked because Poetry is not on PATH; tracked in `P-20260611-003`.
- Problems:
  - `P-20260611-001` resolved.
  - `P-20260611-003` remains open.
- Follow-up:
  - Task `1.4` should formalize smoke test structure, including imports and CLI smoke coverage already started here.

### 2026-06-11 18:10:00 +08:00 - Codex - Task 1.2 config parser

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, task `1.2`.
- Files changed:
  - `src/autoresearch/config/parser.py`
  - `src/autoresearch/config/__init__.py`
  - `tests/unit/config/test_parser.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added `ConfigFormat` and `ConfigParser` for JSON, YAML, and TOML parsing/formatting.
  - Added file read/write helpers, extension-based format detection, schema validation, and descriptive syntax/schema errors.
  - Restored `ConfigParser` and `ConfigFormat` exports from `autoresearch.config`.
  - Used standard-library `tomllib` for TOML reads when available, with Python 3.10 fallback to the declared `toml` package; TOML output is deterministic for the current config model shape.
  - Added parser tests for round-trip behavior, extension detection, syntax errors, schema errors, and file IO.
  - Marked task `1.2` complete in `tasks.md`.
- Verification:
  - `PYTHONPATH=src python -m pytest -o addopts='' tests/unit/config/test_models.py tests/unit/config/test_parser.py`: passed, 15 tests.
  - `PYTHONPATH=src python -c "from autoresearch.config import ConfigFormat, ConfigParser, SystemConfig; parser=ConfigParser(); text=parser.format(SystemConfig(), ConfigFormat.JSON); parser.parse_text(text, config_format=ConfigFormat.JSON); print('config parser ok')"`: passed.
  - `PYTHONPATH=src python -c "from autoresearch.config import ConfigFormat, ConfigParser, SystemConfig; p=ConfigParser(); text=p.format(SystemConfig(), ConfigFormat.TOML); parsed=p.parse_text(text, config_format=ConfigFormat.TOML); assert parsed == SystemConfig(); print(text.splitlines()[0])"`: passed.
  - Broad pytest without `-o addopts=''`, ruff, and Poetry checks remain blocked by `P-20260611-003`.
- Problems:
  - `P-20260611-001` updated; parser portion is resolved and CLI remains pending.
  - `P-20260611-003` remains open.
- Follow-up:
  - Task `1.3` should add the Typer CLI skeleton and finish the remaining CLI part of `P-20260611-001`.

### 2026-06-11 18:00:00 +08:00 - Codex - Task 1.1 config data models

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, starting with task `1.1`.
- Files changed:
  - `src/autoresearch/config/models.py`
  - `src/autoresearch/config/__init__.py`
  - `tests/unit/config/test_models.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added minimal Pydantic configuration models for system, agent, compute, knowledge base, and literature settings.
  - Kept defaults local-first, sandbox-enabled, and aligned with the canonical `autoresearch-vault/` Obsidian vault path.
  - Temporarily narrowed `autoresearch.config` exports to existing model APIs so `SystemConfig` imports honestly before task `1.2` adds the parser.
  - Added focused tests for default values and basic Pydantic bounds.
  - Marked task `1.1` complete in `tasks.md`.
- Verification:
  - `PYTHONPATH=src python -c "from autoresearch.config import SystemConfig; print(SystemConfig().knowledge_base.vault_path)"`: passed, printed `autoresearch-vault`.
  - `PYTHONPATH=src python -c "from autoresearch.config import AgentConfig, ComputeConfig, KnowledgeBaseConfig, LiteratureConfig, SystemConfig; c=SystemConfig(); assert str(c.knowledge_base.vault_path) == 'autoresearch-vault'; assert c.compute.sandbox_enabled; assert c.literature.databases == ['arxiv', 'semantic_scholar']; print('config models ok')"`: passed.
  - `PYTHONPATH=src python -m pytest -o addopts='' tests/unit/config/test_models.py`: passed, 2 tests.
  - `python -m pytest tests/unit/config/test_models.py`: blocked by missing pytest-cov in the active environment.
  - `python -m ruff check src/autoresearch/config tests/unit/config/test_models.py`: blocked because ruff is not installed in the active environment.
  - `poetry --version`: blocked because Poetry is not on PATH.
- Problems:
  - `P-20260611-001` partially resolved.
  - `P-20260611-003` added.
- Follow-up:
  - Task `1.2` should add `ConfigParser` and `ConfigFormat`, then restore parser exports from `autoresearch.config`.

### 2026-06-11 17:36:49 +08:00 - Codex - Documentation planning bootstrap

- Request: Create project planning conventions, a detailed executable task plan, problem logging, and bilingual open-source README pages.
- Files changed:
  - `AGENTS.md`
  - `Agent.md`
  - `Problem.md`
  - `README.md`
  - `README.zh-CN.md`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `autoresearch-vault/README.md`
- Summary:
  - Added repository-wide agent instructions and required change logging rules.
  - Added this agent development standard and change log as the required place for future agents to record file changes and development rules.
  - Added the rule that each completed and verified `tasks.md` task or subtask must be committed as one focused git commit.
  - Added a problem log with the initial scaffold issue discovered during repository inspection.
  - Re-read Kiro requirements and design sections for Obsidian Knowledge Base, Agent evolution, knowledge auto-evolution, permissions, and version history after user review.
  - Re-centered the plan on the Obsidian-compatible `autoresearch-vault/` as the unified self-loop and self-evolution substrate.
  - Reworked the README into an English default open-source landing page with a Chinese version.
  - Rewrote the implementation task plan around the research and execution plans, with detailed executable tasks and verification gates.
  - Added `autoresearch-vault/README.md` so the canonical vault path is present in the repository.
- Verification:
  - Read the two project planning docs, existing Kiro task plan, `pyproject.toml`, and current source skeleton.
  - Read Kiro `requirements.md` and `design.md` sections for Agent evolution, Knowledge Base structure, permissions, knowledge auto-evolution, version history, and Obsidian rationale.
  - `Test-Path` confirmed `AGENTS.md`, `Agent.md`, `Problem.md`, `README.md`, `README.zh-CN.md`, and `.kiro/specs/auto-research-system/tasks.md` exist.
  - `rg` confirmed required terms and links: `Development Standard`, `Git Version Management`, `one focused git commit`, `README.zh-CN`, `Task Dependency Graph`, `P-20260611-001`, `Phase 0`, and `Phase 5`.
  - `rg` confirmed `autoresearch-vault/` is the documented Obsidian vault path and the temporary alternate vault path is no longer referenced.
  - Removed trailing whitespace from the two imported root planning Markdown files so staged whitespace checks can pass.
  - `git diff --check` reported no whitespace errors; Git only warned that LF will be converted to CRLF on future checkout/touch.
- Problems:
  - `P-20260611-001` added.
  - `P-20260611-002` added and resolved.
- Follow-up:
  - Complete Phase 0 implementation tasks before treating `pytest`, `ruff`, `mypy`, or the `autoresearch` CLI as functional project gates.
