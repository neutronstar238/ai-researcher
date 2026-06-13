---
entry_id: task_81_1_persistent_source_cooldowns
entry_type: project_progress
zone: project
project_id: ai_researcher_system
tags:
  - task-81-1
  - semantic-scholar
  - persistent-cooldown
  - rate-limit
  - autopilot
keywords:
  - source-circuit-breakers
  - cooldown
  - 429
  - long-running-loop
source_refs:
  - runs/manual-live/autopilot-persistent-task81-a/cycle-20260613T022556Z/cycle-summary.json
  - runs/manual-live/autopilot-persistent-task81-b/cycle-20260613T022616Z/cycle-summary.json
  - runs/manual-live/task81-persistent-cache/source-circuit-breakers.json
related_task_ids:
  - "81.1"
related_run_ids:
  - cycle-20260613T022556Z
  - cycle-20260613T022616Z
created_at: "2026-06-13T10:27:00+08:00"
updated_at: "2026-06-13T10:27:00+08:00"
---

# Task 81.1 Persistent Source Cooldowns

## What Changed

- `RateLimitCircuitBreaker` can optionally persist open circuit state to a JSON file using wall-clock expiry times.
- Semantic Scholar and OpenAlex clients accept an optional circuit-state path.
- `autopilot` and `serve` store source circuit state under `<cache-root>/source-circuit-breakers.json`.

## Real Verification

Shared cache root: `runs/manual-live/task81-persistent-cache`

First cycle: `runs/manual-live/autopilot-persistent-task81-a/cycle-20260613T022556Z/cycle-summary.json`

- Literature Semantic Scholar error: `SourceRateLimitError: Semantic Scholar HTTP 429 rate limited; circuit open for 300.0s`
- Similarity Semantic Scholar error: `CircuitBreakerOpenError: rate-limit circuit is open for 297.8s`

Second cycle: `runs/manual-live/autopilot-persistent-task81-b/cycle-20260613T022616Z/cycle-summary.json`

- Literature Semantic Scholar error: `CircuitBreakerOpenError: rate-limit circuit is open for 281.0s`
- Similarity Semantic Scholar error: `CircuitBreakerOpenError: rate-limit circuit is open for 280.4s`
- State file existed: `runs/manual-live/task81-persistent-cache/source-circuit-breakers.json`

## Quality Interpretation

The second cycle did not need a fresh Semantic Scholar 429 to learn that the source was still cooling down. This improves 24h loop behavior and source politeness. Publication readiness is still blocked: a persistent cooldown is an access-control mechanism, not successful source coverage.

## Next Loop

- Use `SEMANTIC_SCHOLAR_API_KEY` or a longer scheduled interval before attempting another review-enabled aligned publication cycle.
- Consider per-source query budgeting if persistent cooldown still produces too many blocked source checks in long runs.
