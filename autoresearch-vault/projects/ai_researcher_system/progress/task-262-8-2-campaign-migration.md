---
title: Task 262.8.2 Campaign vertical migration
date: 2026-07-29
status: completed
task: "262.8.2"
tags:
  - campaign
  - strangler-migration
  - event-journal
  - control-graph
  - rollback
---

# Task 262.8.2 Campaign vertical migration

## Result

Campaign is the second legacy service moved behind the vNext lifecycle boundary. The existing
scientific executor, round and campaign manifests, research/failure/loop reports, artifacts, Vault
records, reader, and compatibility writer remain intact. Default
`AUTORESEARCH_CAMPAIGN_MIGRATION_MODE=legacy` preserves the old return path and creates no migration
files.

Two explicit modes are available:

- `shadow` keeps the legacy Campaign result authoritative and records a verified vNext lifecycle;
- `vnext` returns the lifecycle result reconstructed from the verified event projection, but cannot
  start scientific work until two different formal Campaigns have earned promotion.

This is a strangler boundary, not a scientific-engine rewrite. The authority flag can be returned to
`legacy`, and compatibility state remains available for at least one release window.

## Campaign-specific characterization

The versioned corpus `tests/fixtures/migrations/campaign-v1.json` freezes six service-specific
behaviors:

1. a complete, two-round, contribution-ready Campaign;
2. a stopped Campaign whose scientific endpoint is a negative result;
3. a hash-valid retained `BLOCKED` manifest accepted by the legacy schema and reader;
4. an execution exception that preserves the last valid stage and becomes failed;
5. a failed observation followed by a resumed child invocation;
6. repeated observation of an unchanged terminal Campaign without a new journal.

The retained blocked case is a compatibility characterization. The current Campaign executor does
not itself generate `CampaignOutcome.BLOCKED`; the corpus does not claim otherwise.

The generated complete fixture proves lifecycle migration only. It is neither an official benchmark
run nor a publication-ready research result.

## Event and graph projection

Each distinct legacy observation receives an independently sealed `EventJournal`. The projection
records every persisted Campaign stage, every finalized experimental round, the terminal snapshot,
round decisions, contribution gates, artifacts, intervention counts, and failure identity. An
acyclic Control Graph makes stage order and terminal reachability explicit.

Failures retain the last valid legacy stage and outcome. Raw exception text is never persisted:
only the exception type and SHA-256 of its message cross the migration boundary.

Seven parity dimensions are checked independently:

- complete event-history semantics;
- terminal Campaign stage, outcome, and event status;
- normalized scientific endpoint and round counts;
- aggregate and per-round contribution gates;
- complete artifact inventory, paths, existence, size, and SHA-256;
- redacted failure semantics;
- access and human-intervention counts.

Every parity report is reread against journal bytes, event count, lineage, terminal seal, source
fingerprint, endpoint projection, and Control Graph. A report or artifact mismatch fails closed.

## Resume and idempotency

A resumable failed Campaign creates a child invocation journal whose first event is anchored to the
previous failed terminal checkpoint. The parent journal remains sealed and unchanged.

If the Campaign remains at the same terminal source fingerprint, the coordinator validates the old
journal and writes only an idempotency report. It does not append after the seal or create a second
invocation.

## Formal promotion and rollback evidence

Promotion requires two records with distinct formal IDs and distinct Campaign IDs. Each must be a
complete, non-failed, two-round `CONTRIBUTION_READY` legacy-authority shadow run with all declared
artifacts present. Before vNext execution, the ledger revalidates every formal report hash, source
fingerprint, journal lineage and seal, projection, parity check, and Control Graph.

The opt-in local run under `runs/manual-live/task262-campaign-migration-v1/` produced:

| Run | Source fingerprint | Lineage hash | Seal hash |
| --- | --- | --- | --- |
| `task262-campaign-formal-1` | `817546eb1d1c40a402dfdfe411369861ac8d2643a23ecee9266d1e8c2c4b0eb3` | `5f9e22547dc5cac13e9ea2f059c1389606ced372ccadc131e17ee7d9d10e1a68` | `e1b7a37f64cd078a37d39cfc0a3e8d92ba8331aad9250eb386abaa2eab1d0564` |
| `task262-campaign-formal-2` | `6910ed3de9b4a8b2a172a081f56a2a1a07db0a1b59b3ad3dc7b90c5cca37b9e7` | `c79a79e823804c09cc1e8d77321add8bfd35d017598e9ab65a67441507e8d732` | `01652700ab784e5f4206b2af8412125af8c3f25a851643927536b62faca137c3` |

Those records enabled a separate vNext-authority Campaign:

- source fingerprint:
  `c3849eeb2f951d0f7b9f643f9d52742df75f0c08942f48c71c5dde66a70bb355`;
- lineage:
  `09e83935bfc86f45c959d21cea7466791dfbad7ba02190a8ca7043c6a34e0c88`;
- terminal seal:
  `ebccb674f9a140d6040132444dc56fa7e36c8398a97e7eaa42087c104586aac4`.

Switching the completed Campaign back to `legacy` returned the same lifecycle result. Rollback
verification reported equal projection, unchanged journal and seal, and all compatibility files
present.

## Verification

- Seven deterministic Campaign migration tests passed.
- All 35 Campaign unit tests passed.
- The opt-in local vertical completed two formal shadow Campaigns, one vNext cutover, and rollback.
- Full regression passed with 898 tests and 10 opt-in tests skipped.
- Full Ruff and Mypy passed; exact commands are recorded in `Agent.md`.

## Next slice

Task `262.8.3` must independently characterize and migrate Sprint. Neither Competition nor Campaign
evidence can waive Sprint parity, formal-promotion, or rollback gates.

## Links

- [[exploration/graph-harness-loop-open-science-2026|vNext refactor research]]
- [[projects/ai_researcher_system/progress/task-262-8-1-competition-migration|Task 262.8.1 Competition migration]]
- [[projects/ai_researcher_system/progress/task-262-5-durable-control-graph|Task 262.5 durable Control Graph]]
- [[projects/ai_researcher_system/index|AI-Researcher System Project]]
