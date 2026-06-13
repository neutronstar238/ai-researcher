---
entry_id: progress_task_88_1_classified_similarity_breadth
entry_type: project_progress
zone: project
project_id: ai_researcher_system
title: Task 88.1 classified similarity breadth gate
tags:
  - progress
  - publication-audit
  - novelty
  - evidence-gate
keywords:
  - similarity_classified_finding_breadth
  - classified findings
  - novelty
  - publication audit
source_refs:
  - .kiro/specs/auto-research-system/tasks.md
  - src/autoresearch/reports/publication_audit.py
  - runs/manual-live/publication-audit-task88/publication-audit.json
related_task_ids:
  - "88.1"
related_run_ids: []
links: []
backlinks: []
created_at: "2026-06-13T03:35:00Z"
updated_at: "2026-06-13T03:35:00Z"
---

# Task 88.1 Classified Similarity Breadth Gate

## Change

Publication audit now separates raw retrieval volume from evidence-classified similar-work breadth. CCF-B/Q3-style targets require enough non-`unknown` similarity classifications through `similarity_classified_finding_breadth`.

## Why

A pile of unclassified search hits should not count as novelty evidence. The system must classify enough findings as direct duplicate, adjacent work, supporting prior work, contradictory evidence, benchmark gap, or another supported non-unknown class before using them for novelty positioning.

## Evidence

- Focused publication-audit tests now cover unknown-only and sparse-classified cases.
- A real audit over `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/cycle-summary.json` wrote `similarity_classified_finding_breadth=fail` with `0/10` classified findings.
- The same real audit remains non-publishable, as expected, rather than smoothing over missing novelty evidence.

## Follow-up

Improve live query relevance and conservative classification recall. Do not relax this gate to make weak cycles look publishable.
