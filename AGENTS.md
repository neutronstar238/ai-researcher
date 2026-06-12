# AGENTS.md

Project-specific instructions for coding agents working in this repository.

## Scope

- These instructions apply to the entire `E:\AIResearch` repository.
- Follow higher-priority user, system, and developer instructions first.
- Keep changes surgical. Every changed line should map to the current request or the active task.

## Required Reading

Before any non-trivial edit, read or refresh:

1. `AutoResearch_System_Research_Plan.md`
2. `AutoResearch_System_Execution_Plan.md`
3. `.kiro/specs/auto-research-system/tasks.md`
4. `Problem.md`
5. `Agent.md`

## Project Direction

Build AutoResearch as an evidence-first automated research system, not as a paper-writing chatbot.

The Obsidian-compatible knowledge vault is a core innovation and must be treated as the shared memory substrate for self-looping and self-evolution. Its canonical project-root path is `autoresearch-vault/`. Literature notes, topic indexes, project progress, issues, experiment records, failure cases, skill cards, strategy cards, evidence links, and version history should flow through this vault unless a task explicitly justifies another store.

Priority order:

1. Obsidian unified knowledge base and permissioned project memory.
2. Minimal trusted research loop.
3. Evidence graph and result validation.
4. Paper draft and reproducibility package.
5. Multi-agent automation.
6. Obsidian-backed self-loop task pool.
7. Failure and skill libraries.
8. Controlled strategy evolution with shadow evaluation and rollback.
9. Product and deployment surfaces.

Do not move fully autonomous submission, unrestricted execution, multi-user product complexity, or self-modifying production strategy into the MVP.

## Agent Change Logging

Every agent that changes files must follow the development standard in `Agent.md` and append an entry to `Agent.md` before handoff.

Each entry must include:

- Date and timezone.
- Agent name or tool identity.
- User request or active task ID.
- Files changed.
- Summary of what changed.
- Verification performed, including commands and outcomes.
- Problems added or updated in `Problem.md`.
- Follow-up work, if any.

Do not edit another agent's completed entry except to fix a clear typo while preserving the original meaning.

## Git Version Management

- After completing a task or subtask from `.kiro/specs/auto-research-system/tasks.md`, passing its verification, and updating `Agent.md` plus `Problem.md`, create one focused git commit for that completed task or subtask.
- Do not batch unrelated tasks into one commit.
- Do not commit an unchecked or blocked task.
- Review `git status --short` before staging.
- Stage only files relevant to the completed task.
- Use clear task-oriented commit messages, for example `docs: complete task 0.1 governance baseline`.

## Problem Logging

Use `Problem.md` for blockers, defects, risks, confusing requirements, failed commands, and partially verified assumptions.

Add or update a problem when:

- A command fails and affects the task.
- A file or module referenced by the plan is missing.
- Current code contradicts the documented plan.
- Verification is skipped for a real reason.
- A risk could mislead the next agent if left undocumented.

Keep problem entries factual. Include evidence and next action.

## Implementation Discipline

- Prefer the smallest implementation that satisfies the task.
- Treat work as task-driven work: choose one task from `.kiro/specs/auto-research-system/tasks.md`, verify it, then log and commit it before moving on.
- Match existing project style and documented architecture.
- Do not refactor unrelated code.
- Do not mark a task complete unless its acceptance checks have actually passed.
- When adding abstractions, first confirm they are reused or explicitly requested by the task.
- Use structured schemas for agent messages, experiment records, evidence, and validation output.
- Keep Obsidian Markdown entries under `autoresearch-vault/`, human-readable, git-friendly, linkable with wiki-links, and recoverable through version history.

## Verification Expectations

For code changes, run the narrowest meaningful check first, then broader checks when risk justifies it.

For features that depend on external data sources, mocked tests are not enough to mark the task complete. Add deterministic mocked tests for CI, add an opt-in live smoke test, and run the live smoke test once before completing the task. Record the real command and result in `Agent.md`. If the live test needs secrets or paid model credentials, stop and ask the user to provide them through `.env`.

Large-model integrations must be provider-agnostic. Do not hard-code one vendor. Read `base_url`, `api_key`, and `model_name` from configuration or environment, and test against the user-provided values when credentials are required.

Expected gates by phase:

- Phase 0: import smoke tests, config parser tests, `pytest`, `ruff`, and `mypy` once modules exist.
- Phase 1: end-to-end demo on a small local benchmark with run ID, logs, metrics, validation report, and Markdown report.
- Phase 2+: evidence coverage checks, citation validation, figure/table consistency, reproducibility package checks.

If a check cannot run because the repository is not ready, say so in `Agent.md` and, when useful, record the blocker in `Problem.md`.

## Documentation Rules

- `README.md` is the default English landing page.
- `README.zh-CN.md` is the Chinese landing page and must be linked from `README.md`.
- Planning docs may be Chinese, English, or bilingual, but user-facing claims must not overstate implemented features.
- Keep `.kiro/specs/auto-research-system/tasks.md` detailed, executable, and traceable to the research and execution plans.

## Safety Rules

- Sandbox execution is the default for experiments.
- Full-permission execution, cloud GPU rental, private data access, and public release require explicit human approval.
- Never store secrets in the repository.
- Never let self-evolution modify safety policy, approval gates, license policy, or publication rules without human review.
