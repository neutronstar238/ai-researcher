---
backlinks: []
created_at: '2026-06-13T03:56:00Z'
entry_id: progress_task_90_1_llm_quality_retry_gate
entry_type: project_progress
keywords:
- structured output gate
- repair retry
- live DeepSeek smoke
- evidence not prompt discipline
links: []
project_id: ai_researcher_system
related_run_ids: []
related_task_ids:
- '90.1'
source_refs:
- .kiro/specs/auto-research-system/tasks.md
- src/autoresearch/llm/client.py
- runs/manual-live/llm-smoke-task90-retry.json
tags:
- progress
- llm
- quality-gate
- scale-lite
title: Task 90.1 LLM quality retry gate
updated_at: '2026-06-13T03:56:00Z'
zone: project
---

# Task 90.1 LLM Quality Retry Gate

## Change

The live LLM smoke gate now treats critical structured-output failures as hard failures. Malformed JSON, missing required fields, quoted arrays, fake URLs, secret leakage, and weak core review structure are capped below the default quality threshold.

`llm-smoke` is allowed one deterministic repair retry when the first response fails critical local checks. The final artifact records `attempts`; the local quality checks remain the final authority.

## Evidence

- Unit tests cover stringified `next_steps` being capped below threshold.
- Unit tests cover the one-shot smoke repair path and `attempts=2`.
- A real DeepSeek strict smoke run failed on malformed JSON, proving prompt-only discipline was insufficient.
- A real DeepSeek retry run wrote `runs/manual-live/llm-smoke-task90-retry.json` with `attempts=2`, quality score `1.000`, valid JSON, no secret leak, and no fake URLs.

## Follow-up

Keep repair bounded. The next quality step should apply the same hard-evidence pattern to full LLM reviewer outputs and paper sections, especially when reviewer JSON is truncated or contains uncited claims.
