---
entry_id: progress_task_87_1_similarity_token_overlap_classifier
entry_type: project_progress
zone: project
project_id: ai_researcher_system
title: Task 87.1 similarity token-overlap classifier
tags:
  - progress
  - similarity-check
  - novelty
  - evidence
keywords:
  - similarity classification
  - token overlap
  - adjacent work
  - unknown
source_refs:
  - .kiro/specs/auto-research-system/tasks.md
  - src/autoresearch/research/similarity.py
  - runs/manual-live/task87-similarity-vault/exploration/topics/similarity_check_autopilot_task84_atomic_state_20260613030125.md
related_task_ids:
  - "87.1"
related_run_ids: []
links: []
backlinks: []
created_at: "2026-06-13T03:30:00Z"
updated_at: "2026-06-13T03:30:00Z"
---

# Task 87.1 Similarity Token-Overlap Classifier

## Change

Similarity classification now has a conservative token-overlap path. When source metadata includes enough method tokens and dataset tokens from the candidate, the finding can be classified as `adjacent_work`; method-only evidence can become `supporting_prior_work`. The matched tokens are written into the classification basis.

## Guardrail

Weak evidence stays `unknown`. The real live check for the variance-calibrated Pendigits candidate returned two low-relevance online findings from ArXiv/OpenAlex, and both remained `unknown` because the titles/metadata did not support a stronger classification.

## Verification

- First focused test run exposed a priority bug where `benchmark_gap` masked the more specific method+dataset token-overlap classification.
- The priority was fixed and focused similarity tests passed.
- A real `similarity-check` CLI run wrote `runs/manual-live/task87-similarity-vault/exploration/topics/similarity_check_autopilot_task84_atomic_state_20260613030125.md`.

## Follow-up

The next quality step is to improve source result relevance through better query generation and possibly abstract-aware reranking, while preserving the rule that weak live hits must remain `unknown`.
