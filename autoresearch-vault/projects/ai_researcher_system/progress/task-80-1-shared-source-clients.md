---
entry_id: task_80_1_shared_source_clients
entry_type: project_progress
zone: project
project_id: ai_researcher_system
tags:
  - task-80-1
  - semantic-scholar
  - rate-limit
  - circuit-breaker
  - autopilot
keywords:
  - shared-source-clients
  - 429-circuit
  - literature-refresh
  - similarity-check
source_refs:
  - runs/manual-live/autopilot-shared-sources-task80/cycle-20260613T021650Z/cycle-summary.json
related_task_ids:
  - "80.1"
related_run_ids:
  - cycle-20260613T021650Z
created_at: "2026-06-13T10:18:00+08:00"
updated_at: "2026-06-13T10:18:00+08:00"
---

# Task 80.1 Shared Source Clients

## What Changed

- `autopilot` now creates one source-client mapping per cycle.
- The same ArXiv, Semantic Scholar, and OpenAlex clients are passed to literature refresh and similarity check.
- Semantic Scholar rate limiter and 429 circuit state therefore persist across both retrieval phases.

## Real Verification

Cycle: `runs/manual-live/autopilot-shared-sources-task80/cycle-20260613T021650Z/cycle-summary.json`

- Demo: `pendigits_variance_calibrated_prototypes`
- Literature query count: `4`
- Candidate title: `Variance-calibrated prototype classifiers for UCI Pendigits`
- Literature Semantic Scholar errors:
  - First error: `SourceRateLimitError: Semantic Scholar HTTP 429 rate limited; circuit open for 120.0s`
  - Later literature errors: `CircuitBreakerOpenError`
- Similarity Semantic Scholar errors:
  - All observed Semantic Scholar similarity errors were `CircuitBreakerOpenError`, showing the similarity phase inherited the open circuit instead of opening a new client and producing another immediate 429.

## Quality Interpretation

This fixes in-cycle source politeness. It does not make the result publishable: Semantic Scholar source coverage is still failed, the verification run intentionally skipped LLM review, and the publication audit stayed blocked.

## Next Loop

- Add a Semantic Scholar API key or use a longer deployment cooldown before the next review-enabled aligned publication cycle.
- Consider a durable on-disk source cooldown if multi-process or multi-cycle deployments keep hitting 429 across process boundaries.
