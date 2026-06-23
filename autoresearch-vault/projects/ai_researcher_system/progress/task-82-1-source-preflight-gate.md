---
backlinks: []
created_at: '2026-06-13T02:38:32Z'
entry_id: task_82_1_source_preflight_gate
entry_type: project_progress
keywords:
- source preflight
- Semantic Scholar
- SCALE-lite
- cooldown
links: []
project_id: ai_researcher_system
related_run_ids:
- cycle-20260613T023832Z
related_task_ids:
- '82.1'
source_refs:
- src/autoresearch/cli/main.py
- src/autoresearch/literature/clients.py
- tests/unit/cli/test_main.py
- tests/unit/literature/test_clients.py
tags:
- source-preflight
- evidence-gate
- rate-limit
- completed
title: Task 82.1 source cooldown preflight gate
updated_at: '2026-06-13T02:38:32Z'
zone: project
---

# Task 82.1 Source Cooldown Preflight Gate

## What Changed

- Added a SCALE-lite source preflight gate before costly `autopilot` and `serve` cycle work.
- The gate reads existing persisted source cooldown state without making new network calls.
- If a source is still cooling down, the cycle writes `source-preflight.json` and `source-preflight.md`, writes an Obsidian `issue_note`, merges that issue into scheduler follow-up state, and skips literature refresh, experiment execution, LLM review, publication audit, paper build, and evidence gate for that cycle.
- Normal cycles still record `source_preflight.verdict=pass` in `cycle-summary.json`.
- Persistent source cooldown state is now read with `utf-8-sig` so operator-written JSON files with a UTF-8 BOM do not silently bypass the gate.

## Real Verification

- Focused tests:
  - `poetry run pytest tests\unit\literature\test_clients.py tests\unit\cli\test_main.py -q`
  - `poetry run ruff check src\autoresearch\literature\clients.py src\autoresearch\cli\main.py tests\unit\literature\test_clients.py tests\unit\cli\test_main.py`
  - `poetry run mypy src\autoresearch\literature\clients.py src\autoresearch\cli\main.py`
- Real CLI blocked run:
  - `poetry run airesearcher autopilot --vault runs\manual-live\task82-preflight-vault-bom --cache runs\manual-live\task82-preflight-cache-bom --output-dir runs\manual-live\autopilot-source-preflight-task82-bom --state runs\manual-live\autopilot-source-preflight-task82-bom\scheduler-state.json --project-id task82_source_preflight_bom --demo pendigits_variance_calibrated_prototypes --max-queries 4 --max-results-per-source 1 --timeout-seconds 60 --no-review`
  - Result: `[BLOCKED] source_preflight: blocked`.
  - Evidence summary: `runs/manual-live/autopilot-source-preflight-task82-bom/cycle-20260613T023832Z/cycle-summary.json`.
  - The summary recorded `semantic_scholar` as `cooling_down`, skipped review, and queued one issue follow-up.

## Publication Status

This task improves governance and API politeness. It does not make the Pendigits variance-calibrated prototype result publishable. The remaining publication blocker is still broad, failure-free novelty coverage plus a review-enabled aligned cycle.
