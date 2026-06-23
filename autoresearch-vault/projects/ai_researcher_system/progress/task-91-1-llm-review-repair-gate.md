---
backlinks: []
created_at: '2026-06-13T04:04:00Z'
entry_id: progress_task_91_1_llm_review_repair_gate
entry_type: project_progress
keywords:
- local evidence review
- bounded repair
- attempts
- allowed evidence refs
links: []
project_id: ai_researcher_system
related_run_ids: []
related_task_ids:
- '91.1'
source_refs:
- .kiro/specs/auto-research-system/tasks.md
- src/autoresearch/llm/client.py
- runs/manual-live/llm-review-task91-with-run-record.json
tags:
- progress
- llm-review
- quality-gate
- evidence-gate
title: Task 91.1 LLM review repair gate
updated_at: '2026-06-13T04:04:00Z'
zone: project
---

# Task 91.1 LLM Review Repair Gate

## Change

`llm-review` now records `attempts` and can perform one deterministic repair attempt when critical local-evidence review checks fail. The repair instructions are constrained to allowed outer evidence IDs and cannot override local gates for missing refs, unknown refs, fake URLs, or secret leakage.

## Evidence

- Focused LLM/CLI tests cover the one-shot review repair path.
- The first test fixture failed when it tried to pass with empty findings; this was kept as a useful strictness signal and fixed by requiring a valid cited finding.
- A real DeepSeek review with only validation/evidence-map artifacts passed structural quality but returned `needs_revision` and six Obsidian issue notes because reproducibility metadata was unsupported by the provided evidence.
- A second real DeepSeek review with validation, evidence map, run record, and metrics passed with `attempts=1`, quality score `1.000`, `verdict=pass`, and zero issue notes.

## Follow-up

Keep complete evidence bundles in automated review paths. If a future full-cycle review omits run-record or metrics evidence, the correct behavior is to block or write issues rather than relax reviewer gates.
