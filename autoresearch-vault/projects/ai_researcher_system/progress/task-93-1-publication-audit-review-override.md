---
entry_id: task_93_1_publication_audit_review_override
entry_type: project_progress
zone: project
project_id: ai_researcher_system
title: Task 93.1 publication-audit review override
tags:
  - publication-audit
  - review-gate
  - scale-lite
  - completed
keywords:
  - publication-audit
  - llm-review
  - evidence gate
  - review override
source_refs:
  - src/autoresearch/reports/publication_audit.py
  - src/autoresearch/cli/main.py
  - runs/manual-live/publication-audit-task93-review-override/publication-audit.json
related_task_ids:
  - "93.1"
---
# Task 93.1 Publication-Audit Review Override

## Summary

`publication-audit` now accepts an explicit `--review-json` artifact. This lets a historical cycle that skipped review use a later real `llm-review.json` without rerunning the entire cycle.

The override is narrow by design. It can satisfy `llm_evidence_review` and `review_verdict_strength` only. Literature breadth, similarity breadth, source errors, classified novelty coverage, method-effect evidence, manuscript structure, and paper-build/release gates remain independent blockers.

## Real Verification

Command:

```powershell
poetry run airesearcher publication-audit runs\manual-live\autopilot-atomic-source-state-task84\cycle-20260613T030125Z\cycle-summary.json --review-json runs\manual-live\llm-review-task91-with-run-record.json --target ccf-b --output-dir runs\manual-live\publication-audit-task93-review-override --vault runs\manual-live\task93-audit-vault --project-id task93_review_override --no-fail-on-not-publishable
```

Outcome:

- `llm_evidence_review`: pass, evidence ref `runs/manual-live/llm-review-task91-with-run-record.json`
- `review_verdict_strength`: pass, evidence ref `runs/manual-live/llm-review-task91-with-run-record.json`
- Overall publication audit: fail, publishable false, score 0.574
- Remaining blockers: literature query/document breadth, Semantic Scholar source errors, similarity query/finding breadth, classified similarity breadth, unknown-only similarity classifications

## Follow-Up

The next quality frontier is not more prompt repair. It is stronger real online novelty coverage: more query breadth, better source cooldown recovery, classified similar-work evidence, and enough adjacent/direct/contradictory findings to support or reject novelty claims.
