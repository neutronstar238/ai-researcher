---
entry_id: task_85_1_source_state_mutation_lock
entry_type: project_progress
zone: project
title: Task 85.1 source state mutation lock
project_id: ai_researcher_system
tags:
  - source-preflight
  - circuit-breaker
  - state-lock
  - concurrency
  - completed
keywords:
  - source-circuit-breakers.json.lock
  - state_locked
  - read-modify-write
  - SCALE-lite
source_refs:
  - src/autoresearch/literature/clients.py
  - src/autoresearch/cli/main.py
  - tests/unit/literature/test_clients.py
  - tests/unit/cli/test_main.py
related_task_ids:
  - "85.1"
related_run_ids:
  - cycle-20260613T030942Z
created_at: "2026-06-13T03:09:42Z"
updated_at: "2026-06-13T03:09:42Z"
links: []
backlinks: []
---

# Task 85.1 Source State Mutation Lock

## What Changed

- Persisted source cooldown read-modify-write updates now use an exclusive same-directory `.lock` file.
- Active locks raise `SourceCircuitStateLockError` instead of silently racing writes.
- Stale locks are cleared before mutation so a crashed worker does not permanently block source-state updates.
- `autopilot` and `serve` preflight map active locks to `state_locked` blockers with JSON/Markdown evidence and Obsidian issue notes.

## Real Verification

- Focused checks:
  - `poetry run pytest tests\unit\literature\test_clients.py -q`
  - `poetry run pytest tests\unit\literature\test_clients.py tests\unit\cli\test_main.py -q`
  - `poetry run ruff check src\autoresearch\literature\clients.py src\autoresearch\literature\__init__.py src\autoresearch\cli\main.py tests\unit\literature\test_clients.py tests\unit\cli\test_main.py`
  - `poetry run mypy src\autoresearch\literature\clients.py src\autoresearch\literature\__init__.py src\autoresearch\cli\main.py`
- Broad checks:
  - `poetry run ruff check src tests`
  - `poetry run mypy src`
  - `git diff --check`
  - `poetry run pytest tests\smoke tests\unit -q`
- Real CLI locked-state run:
  - `poetry run airesearcher autopilot --vault runs\manual-live\task85-locked-state-vault --cache runs\manual-live\task85-locked-state-cache --output-dir runs\manual-live\autopilot-locked-source-state-task85 --state runs\manual-live\autopilot-locked-source-state-task85\scheduler-state.json --project-id task85_locked_state --demo pendigits_variance_calibrated_prototypes --max-queries 4 --max-results-per-source 1 --timeout-seconds 60 --no-review`
  - Result: `[BLOCKED] source_preflight: blocked`.
  - Evidence summary: `runs/manual-live/autopilot-locked-source-state-task85/cycle-20260613T030942Z/cycle-summary.json`.
  - The summary recorded `state_locked` for Semantic Scholar and OpenAlex, skipped review, queued one follow-up, and wrote an Obsidian issue note containing related task `85.1`.

## Remaining Boundary

This serializes workers that share one source-state file. It does not make locked source state healthy; repeated `state_locked` blockers should be treated as a stuck-worker or shared-cache operations issue.
