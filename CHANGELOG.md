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
- First-deploy CLI setup for provider-agnostic model configuration, `.env` secret storage, WeChat/Feishu channel wiring, and project slash command templates.
- Real online discovery CLI entry points for daily literature refresh and project-start similarity checks, including guarded Obsidian summaries and visible per-source fetch errors.

### Changed

- Project name normalized to `AI-Researcher`; the Python import package remains `autoresearch`.
- Canonical vault location normalized to `autoresearch-vault/`.
- Docker runtime uses Python 3.12 until the dependency set is compatible with Python 3.13 wheels in the container build path.
- Verification standard now requires real network/API calls for external data features when that surface is being tested; mocked responses only prove parser behavior.
- LLM integration guidance is provider-agnostic: base URL, API key, and model name must come from configuration or `.env`.

### Migration Notes

- Existing local notes should use `autoresearch-vault/` as the root Obsidian vault path.
- Imports should continue using `autoresearch`, not `ai_researcher` or another package name.
- Generated reproducibility packages should be validated with `autoresearch validate-package --manifest <path>`.
- Docker users should rebuild after the Python 3.12 base image change.
- Public redistribution should use the Apache-2.0 license terms in `LICENSE`.

### Known Problems

- `P-20260612-057`: local Python verification emits a non-failing `RequestsDependencyWarning` about the installed `requests` dependency stack.
- Docker Desktop must be running before Docker Compose verification can access the local engine.
- Some live literature and similarity smoke tests are intentionally skipped unless the live-test environment is configured; live external behavior must be verified before claiming those features are production-ready.
- Poetry reports non-blocking metadata deprecation warnings for the existing `[tool.poetry]` layout; package metadata is still accepted by `poetry check`.

### Verification Snapshot

- Current broad local check after task `35.3`: `poetry run ruff check src tests` passed.
- Current broad local test set after task `35.3`: `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed with `295 passed, 3 skipped`.
- License task `36.1`: `LICENSE` exists, README files link to it, and `poetry check` passed with non-blocking metadata deprecation warnings.
- Contribution task `36.2`: `CONTRIBUTING.md` exists and links to `AGENTS.md`.
