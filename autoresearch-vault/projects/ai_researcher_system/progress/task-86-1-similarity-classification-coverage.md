---
entry_id: progress_task_86_1_similarity_classification_coverage
entry_type: project_progress
zone: project
project_id: ai_researcher_system
title: Task 86.1 similarity classification coverage gate
tags:
  - progress
  - publication-audit
  - novelty
  - scale-lite
keywords:
  - similarity_classification_coverage
  - unknown
  - novelty
  - evidence gate
source_refs:
  - .kiro/specs/auto-research-system/tasks.md
  - src/autoresearch/reports/publication_audit.py
  - runs/manual-live/publication-audit-task86/publication-audit.json
related_task_ids:
  - "86.1"
related_run_ids: []
links:
  - publication_audit_task86_similarity_classification_cycle-20260613t030125z
backlinks: []
created_at: "2026-06-13T03:19:51Z"
updated_at: "2026-06-13T03:19:51Z"
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
