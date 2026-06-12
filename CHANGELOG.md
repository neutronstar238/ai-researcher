# Changelog

All notable user-visible changes to AI-Researcher are tracked here.

This project has not published a public release tag yet. The current unreleased notes describe the repository state for the planned `0.1.0` baseline.

## [Unreleased]

Target version: `0.1.0`.

### Added

- Evidence-first project planning docs, execution plan, and detailed Kiro task plan.
- Repository agent rules in `AGENTS.md`, required change logging in `Agent.md`, and issue tracking in `Problem.md`.
- Bilingual README landing pages with English as the default and Chinese as the linked secondary page.
- Canonical Obsidian-compatible project vault path at `autoresearch-vault/`.
- Python package scaffold for `autoresearch` with CLI smoke commands, config models/parser, schemas, provenance helpers, audit logging, and local health checks.
- Literature client and storage foundations for ArXiv and Semantic Scholar workflows.
- Knowledge-vault entry storage, permissions, backlink/index handling, version history, rollback, failure records, skill cards, and strategy cards.
- Minimal experiment execution, result collection, validation reports, evidence binding, report generation, citation checks, figure/table helpers, and reproducibility package validation.
- ScientistBench-Lite demo acceptance now persists `run/run-record.json` with run metadata, metrics, logs, artifacts, validation report paths, and cost records.
- Local scheduler, daily literature refresh workflow foundations, similarity checks, candidate generation, hypotheses, and approval records.
- Controlled self-evolution foundations: replay datasets, golden tests, shadow evaluation, reward scoring, gray release approval, rollback, and audit review.
- Operational reporting: system metrics, static status reports, dashboard HTML export, project permissions, plugin interfaces, license scanner, project cost management, and service health/SLA reports.
- Deployment and release preparation docs: Docker Compose package, Kubernetes planning document, Apache-2.0 license, contribution guide, and this changelog.
- Apache-2.0 `NOTICE` file and root `.env.example` for first-deploy model/channel configuration.
- First-deploy CLI setup for provider-agnostic model configuration, `.env` secret storage, WeChat/Feishu channel wiring, and project slash command templates.
- Real online discovery CLI entry points for daily literature refresh and project-start similarity checks, including guarded Obsidian summaries and visible per-source fetch errors.
- Live `llm-smoke` CLI for OpenAI-compatible model calls, structured output checks, API-key leak checks, and quality report artifacts.
- Live API smoke tests now cover LLM, literature client retrieval, daily literature refresh, and project-start similarity checks behind `AUTORESEARCH_LIVE_APIS=1`.
- Semantic Scholar online discovery now supports optional `SEMANTIC_SCHOLAR_API_KEY`, conservative unauthenticated rate limiting, exponential backoff, and HTTP 429 circuit breaking.
- `llm-review` CLI for live LLM-as-reviewer checks constrained to local evidence artifacts and deterministic citation quality gates.
- Project-level Obsidian `review/` memory for evidence-constrained LLM review notes.
- Automatic Obsidian `issue_note` creation from actionable evidence-constrained LLM review findings.
- Stable issue fingerprints for LLM review issue notes so repeated or reordered reviewer findings update the same self-loop issue entry.
- Scheduler helper for turning open Obsidian project issue notes into one-shot follow-up queued tasks.
- `airesearcher issue-followups` CLI and `/research:issue-followups` slash template for reviewing self-loop follow-up tasks before execution.
- Optional local scheduler state merge for issue follow-up discovery with duplicate-safe `task_id` updates.
- `airesearcher scheduler-state list`, `complete`, and `remove` commands for inspecting and maintaining local follow-up task records without hand-editing JSON.
- Optional `SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS` and `SEMANTIC_SCHOLAR_CIRCUIT_RESET_SECONDS` deployment settings for Semantic Scholar rate-limit tuning.
- `airesearcher autopilot` one-command loop for live literature refresh, source-backed candidate generation, similarity checking, local experiment execution, optional live LLM evidence review, Obsidian issue writing, and follow-up state merging.
- `/research:autopilot` slash command template for starting the local research loop.
- `airesearcher obsidian-setup` for creating vault dashboards, templates, plugin recommendations, and CSS snippet assets.
- `/research:obsidian-setup` slash command template for structuring the local Obsidian vault.
- Run records now include reproduction command, Python version, dependency lock status, commit, config hash, and data hash as evidence for generated report claims.
- `airesearcher skill-evolve` for creating SkillOpt-inspired bounded skill evolution candidates with issue/failure evidence refs, validation gates, rollback target, and rejected-edit buffer.
- `/research:skill-evolve` slash command template for evidence-linked skill evolution candidates.

### Changed

- Project name normalized to `AI-Researcher`; the Python import package remains `autoresearch`.
- Public CLI command and local operator-state namespace normalized to `airesearcher` and `.airesearcher/`.
- Canonical vault location normalized to `autoresearch-vault/`.
- Docker runtime uses Python 3.12 until the dependency set is compatible with Python 3.13 wheels in the container build path.
- Verification standard now requires real network/API calls for external data features when that surface is being tested; mocked responses only prove parser behavior.
- LLM integration guidance is provider-agnostic: base URL, API key, and model name must come from configuration or `.env`.
- `airesearcher deploy-setup` now ensures `.env.example` exists as a non-secret template while writing real secrets only to `.env`.
- Local `config.yaml` generated by first-deploy setup is treated as ignored deployment state.
- README guidance now distinguishes local installation/import smoke tests from opt-in live API smoke tests.
- LLM reviewer checks now require every finding to cite allowed outer local evidence IDs, and the default review token budget is 2400 for reasoning-token models.
- Re-discovered issue follow-up tasks now preserve completed scheduler-state records instead of reopening them.
- Semantic Scholar throttling now keeps conservative defaults while allowing stricter deployment-specific request spacing and 429 circuit reset windows.
- GitHub Actions CI now uses `actions/checkout@v5` and `actions/setup-python@v6` to avoid the Node 20 deprecation warning.
- README now documents design inspirations from AI-Researcher, long-horizon auto-research roadmaps, daily literature refresh projects, SkillOpt, and OpenClaw-style always-on assistants.
- README now documents the safe Obsidian setup flow and clarifies that third-party Obsidian plugins are recommended manual installs, not bundled runtime dependencies.
- LLM reviewer instructions now distinguish report-internal metric evidence edge IDs from the outer evidence artifact IDs required in reviewer JSON findings.

### Fixed

- GitHub Actions `pytest tests/smoke tests/unit` collection failure on Python 3.10 caused by runtime use of `logging.LoggerAdapter[...]`.
- GitHub Actions `mypy src` failure on Python 3.10/Linux caused by direct access to the Windows-only `subprocess.CREATE_NEW_PROCESS_GROUP` attribute.
- Removed stale mypy override entries that produced unused-config warnings in CI.
- LLM output quality detection now recognizes independent fact-checking language as valid evidence-policy language.
- LLM reviewer quality scoring now treats missing evidence refs, unknown nested refs, secret leakage, and fake URLs as hard failures below the CLI threshold.
- Passing `llm-review` results can now be promoted into project `review_note` entries, while low-quality reviewer outputs remain only in ignored `runs/` artifacts.
- Passing `llm-review --project-id` runs now default to promoting actionable warning/blocking reviewer findings into project issue notes, with `--no-write-issues` available to keep review-only behavior.
- Duplicate actionable LLM reviewer claims in one result are skipped before writing Obsidian `issue_note` entries.
- Closed or invalid project issue notes are skipped when building scheduler follow-up tasks.
- Default slash command templates now include the Obsidian issue follow-up discovery workflow.
- `airesearcher issue-followups --state` keeps generated task records reviewable across sessions without executing them automatically.
- Scheduler-state CLI missing-task failures are covered through the repository's merged Click output stream.

### Migration Notes

- Existing local notes should use `autoresearch-vault/` as the root Obsidian vault path.
- Imports should continue using `autoresearch`, not `ai_researcher` or another package name.
- Generated reproducibility packages should be validated with `airesearcher validate-package --manifest <path>`.
- Docker users should rebuild after the Python 3.12 base image change.
- Public redistribution should use the Apache-2.0 license terms in `LICENSE`.

### Known Problems

- `P-20260612-057`: local Python verification emits a non-failing `RequestsDependencyWarning` about the installed `requests` dependency stack.
- Docker Desktop must be running before Docker Compose verification can access the local engine.
- Some live literature and similarity smoke tests are intentionally skipped unless the live-test environment is configured; live external behavior must be verified before claiming those features are production-ready.
- Poetry reports non-blocking metadata deprecation warnings for the existing `[tool.poetry]` layout; package metadata is still accepted by `poetry check`.

### Verification Snapshot

- Current broad local check after task `41`: `poetry run ruff check src tests` passed.
- Current broad local type check after task `41`: `poetry run mypy src` passed with no issues in 84 source files.
- Current broad local test set after task `41`: `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed with `306 passed, 4 skipped`.
- Python 3.10 CI reproduction after task `42`: `poetry run pytest tests/smoke tests/unit -q` passed with `289 passed, 4 skipped`.
- Python 3.10 quality gates after task `42`: `poetry run ruff check src tests` and `poetry run mypy src` passed.
- Semantic Scholar hardening after task `43`: unit/CLI literature checks passed, and `AUTORESEARCH_LIVE_APIS=1 poetry run pytest tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py tests/smoke/test_similarity_live.py -q` passed with 3 real API tests.
- Evidence-constrained LLM reviewer after task `44`: `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/smoke tests/unit -q` passed with 296 tests and 4 skipped; real DeepSeek `poetry run airesearcher llm-review --subject runs/manual-live/demo/tabular-baseline/report/report.md --evidence runs/manual-live/demo/tabular-baseline/validation/validation-report.json --evidence runs/manual-live/demo/tabular-baseline/evidence/evidence-map.json --config config.yaml --env-path .env --output runs/llm-review/latest.json --min-quality-score 0.85` passed with quality score `1.000` and verdict `needs_revision`.
- Obsidian LLM review memory after task `45`: `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/smoke tests/unit -q` passed with 297 tests and 4 skipped; real DeepSeek `poetry run airesearcher llm-review --subject runs/manual-live/demo/tabular-baseline/report/report.md --evidence runs/manual-live/demo/tabular-baseline/validation/validation-report.json --evidence runs/manual-live/demo/tabular-baseline/evidence/evidence-map.json --config config.yaml --env-path .env --output runs/llm-review/latest-vault.json --min-quality-score 0.85 --vault runs/manual-live/review-vault --project-id deepseek_live_project --source-task-id 45.1 --max-tokens 2400` wrote an Obsidian `review_note`.
- LLM review issue promotion after task `46`: `poetry run pytest tests/unit/llm/test_review_memory.py tests/unit/cli/test_main.py::test_llm_review_command_writes_local_evidence_report -q` passed with 3 tests; real DeepSeek `poetry run airesearcher llm-review --subject runs/manual-live/demo/tabular-baseline/report/report.md --evidence runs/manual-live/demo/tabular-baseline/validation/validation-report.json --evidence runs/manual-live/demo/tabular-baseline/evidence/evidence-map.json --config config.yaml --env-path .env --output runs/llm-review/latest-issues.json --min-quality-score 0.85 --vault runs/manual-live/review-vault-issues --project-id deepseek_live_project --source-task-id 46.1 --max-tokens 2400` wrote one review note and two issue notes.
- LLM review issue deduplication after task `47`: `poetry run pytest tests/unit/llm/test_review_memory.py -q` passed with 3 tests and covered duplicate plus reordered reviewer findings.
- Obsidian issue scheduler adapter after task `48`: `poetry run pytest tests/unit/test_scheduler.py -q` passed and covered open issue-note task creation plus closed issue skips; `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/smoke tests/unit -q` also passed with 300 tests and 4 skipped.
- Issue follow-up CLI after task `49`: `poetry run pytest tests/unit/cli/test_main.py::test_issue_followups_command_lists_open_project_issue_tasks tests/unit/cli/test_main.py::test_slash_commands_init_and_list_project_templates -q` passed and covered JSON output plus slash template creation; `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/smoke tests/unit -q` also passed with 301 tests and 4 skipped.
- Issue follow-up scheduler state after task `50`: `poetry run pytest tests/unit/cli/test_main.py::test_issue_followups_command_lists_open_project_issue_tasks -q` passed and covered duplicate-safe state merging; `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/smoke tests/unit -q` also passed with 301 tests and 4 skipped.
- Scheduler-state management after task `51`: focused scheduler-state CLI tests passed with 3 tests; `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/smoke tests/unit -q` also passed with 303 tests and 4 skipped.
- Semantic Scholar rate tuning after task `52`: `poetry run pytest tests/unit/literature/test_clients.py tests/unit/cli/test_main.py::test_deploy_setup_writes_provider_config_and_env_without_committing_secret -q` passed with 8 tests; `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/smoke tests/unit -q` also passed with 305 tests and 4 skipped.
- Live API smoke after task `41`: `AUTORESEARCH_LIVE_APIS=1 poetry run pytest tests/smoke/test_llm_live.py tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py tests/smoke/test_similarity_live.py -vv` passed with 4 real API tests.
- License task `36.1`: `LICENSE` exists, README files link to it, and `poetry check` passed with non-blocking metadata deprecation warnings.
- Contribution task `36.2`: `CONTRIBUTING.md` exists and links to `AGENTS.md`.
