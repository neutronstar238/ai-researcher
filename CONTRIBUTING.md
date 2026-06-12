# Contributing to AI-Researcher

AI-Researcher is an evidence-first automated research system. Contributions should improve the trusted research loop without overstating what the current implementation can do.

## Required Reading

Before changing files, read:

- [AGENTS.md](AGENTS.md) for repository-wide coding-agent instructions.
- [Agent.md](Agent.md) for the development standard and required change log.
- [Problem.md](Problem.md) for known blockers, risks, and unresolved warnings.
- [.kiro/specs/auto-research-system/tasks.md](.kiro/specs/auto-research-system/tasks.md) for the current executable task plan.
- [AutoResearch_System_Research_Plan.md](AutoResearch_System_Research_Plan.md) and [AutoResearch_System_Execution_Plan.md](AutoResearch_System_Execution_Plan.md) for project direction.

## Development Setup

Prerequisites:

- Python 3.10 or newer.
- Poetry.
- Git.

Install dependencies:

```bash
poetry install
```

Run a quick local health check:

```bash
poetry run autoresearch doctor
```

## Task Workflow

1. Choose one unchecked task or subtask from `.kiro/specs/auto-research-system/tasks.md`.
2. State success criteria before implementation when the task is non-trivial.
3. Make the smallest change that satisfies the task.
4. Keep Obsidian-compatible project memory under `autoresearch-vault/` when the task creates research memory, issue notes, evidence notes, experiment records, skill cards, or strategy cards.
5. Run the narrowest meaningful verification first, then broader gates when the change touches shared behavior.
6. Update `Problem.md` for blockers, failed commands, skipped verification, confusing requirements, or risks that would mislead the next contributor.
7. Append a change entry to `Agent.md`.
8. Mark the task complete only after verification passes.

## Commit Rule

Create one focused git commit for each completed and verified task or subtask.

- Review `git status --short` before staging.
- Stage only files relevant to the completed task.
- Do not batch unrelated tasks into one commit.
- Do not commit blocked or unchecked tasks.
- Use task-oriented commit messages, for example `docs: complete task 36.2 contribution guide`.

## Testing Gates

Use the narrowest gate that proves the change, then broaden when risk justifies it.

Common gates:

```bash
poetry run ruff check src tests
poetry run mypy src
poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents
```

For docs-only changes, verify file existence, required links, and required phrases with `Test-Path` and `rg`.

For package metadata changes, run:

```bash
poetry check
```

For Docker or deployment changes, use real Docker Compose commands when Docker is available:

```bash
docker compose config
docker compose build app
docker compose run --rm app
```

## External Data and LLM Verification

Internet, literature API, repository, package index, or other external data features must be tested against real network responses once the task reaches that surface. Mocked responses are useful for parser tests but do not prove live behavior.

LLM integrations must remain provider-agnostic. Read the base URL, API key, and model name from configuration or `.env`. If a real LLM call is required and credentials are missing, stop and ask the user to populate `.env`; do not bind the code to one vendor or fake success.

## Problem Log

Use `Problem.md` for:

- Failed commands that affect the task.
- Missing files, modules, services, or credentials.
- Verification that cannot run.
- Plan/code contradictions.
- Security, license, publication, or cost risks.
- Warnings that are non-blocking but likely to affect future contributors.

Keep entries factual: source, symptom, impact, root cause when known, next action, status, and verification.

## Code Review Expectations

Review changes for:

- Correctness against the active task.
- Evidence-backed behavior and no fabricated research claims.
- Minimal scope and no unrelated refactors.
- Clear validation, especially for metrics, citations, costs, permissions, and release gates.
- Safe handling of secrets, sandbox boundaries, external network access, and human approval gates.
- Tests that cover the risky behavior rather than only implementation details.

When reviewing, lead with findings ordered by severity and include file/line references where possible.

## Release Discipline

Do not claim production readiness until release gates pass. Public release, publication, full-permission execution, private data access, cloud GPU rental, or paid model calls require explicit human approval.
