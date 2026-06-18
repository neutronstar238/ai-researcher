---
backlinks: []
created_at: '2026-06-13T03:19:51Z'
entry_id: progress_task_86_1_similarity_classification_coverage
entry_type: project_progress
keywords:
- similarity_classification_coverage
- unknown
- novelty
- evidence gate
links: []
project_id: ai_researcher_system
related_run_ids: []
related_task_ids:
- '86.1'
source_refs:
- .kiro/specs/auto-research-system/tasks.md
- src/autoresearch/reports/publication_audit.py
- runs/manual-live/publication-audit-task86/publication-audit.json
tags:
- progress
- publication-audit
- novelty
- scale-lite
title: Task 86.1 similarity classification coverage gate
updated_at: '2026-06-13T03:19:51Z'
zone: project
---

# Task 86.1 Similarity Classification Coverage Gate

## Change

Publication audit now includes `similarity_classification_coverage` for CCF-B/Q3-style targets. If similarity search returns findings but every finding is still `unknown` or unclassified, the audit fails with high severity.

## Why

Raw similarity finding count is not enough to support novelty. The system must know whether those findings are direct duplicates, adjacent work, or another evidence-backed category before it can claim a method is novel.

## Evidence

- Focused publication-audit tests passed for the new unknown-only blocker.
- A real audit over `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/cycle-summary.json` produced `similarity_classification_coverage=fail`.
- The failed audit wrote review and issue notes under `autoresearch-vault/projects/task86_similarity_classification/`.

## Follow-up

Improve the similarity summarizer so it can turn source-backed abstracts and metadata into conservative classifications instead of leaving all findings as `unknown`.
