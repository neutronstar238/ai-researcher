---
entry_id: task_79_1_demo_aligned_autopilot_search
entry_type: project_progress
zone: project
project_id: ai_researcher_system
tags:
  - task-79-1
  - autopilot
  - literature-search
  - novelty-check
  - evidence-gate
keywords:
  - demo-aligned-search
  - pendigits
  - seed-queries
  - publication-audit
source_refs:
  - runs/manual-live/autopilot-variance-full-task79/cycle-20260613T020221Z/cycle-summary.json
  - runs/manual-live/autopilot-aligned-task79/cycle-20260613T020855Z/cycle-summary.json
related_task_ids:
  - "79.1"
related_run_ids:
  - cycle-20260613T020221Z
  - cycle-20260613T020855Z
created_at: "2026-06-13T10:10:00+08:00"
updated_at: "2026-06-13T10:10:00+08:00"
---

# Task 79.1 Demo-Aligned Autopilot Search

## What Changed

- Added a literature query floor and optional seed-query contract to daily literature refresh.
- Added deterministic Pendigits seed queries for the baseline, prototype-shrinkage, and variance-calibrated prototype demos.
- Made autopilot candidates for known Pendigits demos carry method, dataset, benchmark, baseline, limitation, and demo metadata.
- Preserved the generic evidence-bound research-loop candidate for generic/default demos only.

## Real Verification

- Review-enabled pre-fix cycle: `runs/manual-live/autopilot-variance-full-task79/cycle-20260613T020221Z/cycle-summary.json`
  - `review.status=passed`
  - `paper_build.status=compiled`
  - `publication_audit.verdict=fail`
  - `literature.query_count=1`
  - Finding: search topic and executed Pendigits method were not aligned.
- Post-fix aligned no-review cycle: `runs/manual-live/autopilot-aligned-task79/cycle-20260613T020855Z/cycle-summary.json`
  - `literature.query_count=4`
  - `candidate.title=Variance-calibrated prototype classifiers for UCI Pendigits`
  - `candidate.metadata.method=diagonal variance-calibrated prototypes with variance shrinkage`
  - `candidate.metadata.dataset=UCI Pen-Based Recognition of Handwritten Digits`
  - `similarity.finding_count=14`
  - `publication_audit.verdict=needs_revision`
  - `evidence_gate.verdict=blocked`

## Quality Interpretation

The query breadth and candidate/experiment alignment issue is fixed for known Pendigits demos. The result is still not publishable: Semantic Scholar returned 429 and the aligned verification intentionally skipped review, so the physical evidence gate stayed blocked. This is the correct outcome; OpenAlex and ArXiv fallback evidence cannot erase a failed source when making novelty claims.

## Next Loop

- Configure a Semantic Scholar API key or longer cooldown and rerun the aligned cycle with review enabled.
- Compare retrieved adjacent work against Gaussian, Mahalanobis, prototype, and metric-learning classifiers before claiming novelty.
- Add demo-specific seed-query contracts for every future real benchmark demo.
