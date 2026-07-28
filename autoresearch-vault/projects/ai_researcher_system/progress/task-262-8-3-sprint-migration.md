---
title: Task 262.8.3 Sprint vertical migration
date: 2026-07-29
status: completed
task: "262.8.3"
tags:
  - sprint
  - strangler-migration
  - event-journal
  - control-graph
  - negative-results
  - rollback
---

# Task 262.8.3 Sprint vertical migration

## Result

Sprint is the third and final legacy service moved behind the vNext lifecycle boundary. The existing
topic selection, experiment, task-level adjudication, manuscript, paper build, autonomy audit, Vault
report, artifacts, manifest, autonomy ledger, reader, and compatibility writer remain intact.
Default `AUTORESEARCH_SPRINT_MIGRATION_MODE=legacy` follows the old path and creates no migration
files.

Two explicit modes are available:

- `shadow` keeps the legacy `SprintResult` authoritative and records a verified vNext lifecycle;
- `vnext` returns the result reconstructed from the verified event projection, but cannot gain
  authority until two distinct formal Sprint observations remain independently valid.

The flag is reversible. No dependency, scientific threshold, historical result, Gate B decision,
publication permission, or submission authority changed.

## Sprint-specific characterization

The versioned corpus `tests/fixtures/migrations/sprint-v1.json` freezes six Sprint behaviors:

1. a completed Sprint whose frozen task-level endpoint passes;
2. a completed scientific negative result whose frozen endpoint does not pass;
3. a resumable block during topic selection;
4. an integrity exception that escapes before the legacy resumable-error boundary;
5. a blocked observation followed by a completed child invocation without repeating prior scientific
   calls;
6. repeated observation of the same logical terminal Sprint without another invocation.

A scientific negative result is still `COMPLETED/COMPLETE`; it is not an execution failure. A caught
runtime problem remains legacy `BLOCKED`. An escaped integrity exception becomes digest-only
`FAILED` in the migration lifecycle while preserving the last valid persisted legacy outcome and
stage.

The generated deterministic fixtures characterize migration behavior only. They are not an official
benchmark, a publication-ready result, or evidence of unrestricted autonomous discovery.

## Events, graph, and privacy

Each distinct legacy observation receives an independently sealed `EventJournal`. The projection
includes every existing `AutonomyEvent`, start/terminal semantics, topic selection, experiment,
task-level inference, manuscript, paper, autonomy audit, artifact bindings, gate, intervention
counts, and lifecycle result paths. An acyclic Control Graph makes the persisted stage order and
terminal reachability explicit.

Seven parity dimensions are checked:

- event semantics;
- terminal stage, outcome, and status;
- scientific endpoint;
- task-level, paper, autonomy, and submission gates;
- artifact existence, size, expected digest, and actual SHA-256;
- blocked versus escaped-exception failure semantics;
- prelaunch, post-start manual, fallback, and total intervention counts.

Raw autonomy notes, exception/block messages, model response bodies, and absolute private paths do
not cross the migration boundary. Notes and exception messages are represented by SHA-256 where
identity is required. Reports are reread against journal bytes, event count, lineage, terminal seal,
projection, source fingerprint, Control Graph, and formal-report hashes.

## Resume and terminal idempotency

A blocked or failed observation followed by progress creates a child invocation journal whose first
event is anchored to the previous terminal seal. The parent journal remains sealed.

An unchanged logical terminal state reuses the same source fingerprint. The coordinator validates
the existing journal and emits an idempotency report without appending after its seal or creating a
second invocation. Volatile `updated_at`, `manifest_hash`, and raw failure text are excluded from the
logical manifest fingerprint; scientific, gate, artifact, and intervention fields are not.

## Formal promotion and rollback

Promotion requires two different formal IDs and Sprint IDs. Each observation must be a complete,
non-failed shadow Sprint with either a passing task-level endpoint or a scientific negative result.
Both endpoints still require:

- a compiled paper that passed the frozen paper-quality gate;
- all bounded-autonomy required checks;
- all required legacy, Route A, LLM configuration, paper, audit, and Vault artifacts;
- zero post-start manual research decisions;
- zero local-model fallback;
- no external-submission authorization.

The opt-in adoption run under `runs/manual-live/task262-sprint-migration-live-v1/` did not rerun a
model, literature search, experiment, manuscript, paper build, or submission step. It read two
existing completed real negative-result Sprints as formal shadow evidence:

| Persisted Sprint | Source fingerprint | Lineage hash | Seal hash |
| --- | --- | --- | --- |
| `task261-bounded-autonomous-clean-v1` | `0e9477262ad603d10c422c0c962ef5e962007465cf3c1675f8f08cbc63c18253` | `f6cd3dbe8e333a0eaec1682b683862a0aa2b48a70804cc9ab139de0d27384d08` | `4acf078e79fbc6bf88123e72e9a2e3a0ca442a5f8a524f45759a49d87e1fe519` |
| `task261-bounded-autonomous-clean-v2` | `81a3c70c1d8a34e92d099c40c3b1d7508f4ff76897c59d029a52f35cd2c667cf` | `2ce5316fc8de29d23843ab5e0f514f114bd98ee9cdd5b00b324b99aeac9879bc` | `5e40771aaf6b959a8246e6e7d2da0ba8bb4e6bedb93be3d32ca44012770ecbd9` |

Those records enabled vNext authority over the existing blocked
`task261-bounded-autonomous-live-v1` observation:

- source fingerprint:
  `59e812a02014b0a463df456d23cb5d2a29ce1c721da30eb3119402d8ac241faa`;
- lineage:
  `ebb88bb55667314f8c2794e044e1b8351d6c4f90b5aee61ad711658cc321b23e`;
- terminal seal:
  `5933935189364c95d598bf6f814614791e3cbea5e0b090f1e39c577c23ab4fbf`.

The blocked outcome remained blocked under projection. Switching back to the legacy reader returned
the same lifecycle result; rollback reported equal projection, unchanged journal and seal, and all
compatibility files present. The smoke summary SHA-256 is
`2c43c101ae8212f5860ebdf01f3f765ca6d2857f0620aefb9bc30cee30488599`.

## Verification

- Seven deterministic Sprint migration tests passed.
- The four existing Sprint compatibility tests and all 42 Campaign unit tests passed.
- The opt-in real-evidence adoption smoke passed once; its default CI form remains skipped.
- Full regression passed with 905 tests and 11 opt-in tests skipped at 87% line coverage.
- `ruff check src tests` passed.
- Mypy passed across 149 source files.
- The extra repository-wide Ruff audit found pre-existing issues outside `src/tests`; they remain
  recorded in `Problem.md` and were not folded into this migration commit.

## Next

Task `262.8` and milestone M1 are complete. Task `262.9` must add unified evaluation,
observability, and Agentic security gates. Competition, Campaign, Sprint, `AuditLog`, and all legacy
compatibility writers remain in place until the explicit `262.10` release boundary.

## Links

- [[exploration/graph-harness-loop-open-science-2026|vNext refactor research]]
- [[projects/ai_researcher_system/progress/task-262-8-2-campaign-migration|Task 262.8.2 Campaign migration]]
- [[projects/ai_researcher_system/progress/task-262-5-durable-control-graph|Task 262.5 durable Control Graph]]
- [[projects/ai_researcher_system/index|AI-Researcher System Project]]
