---
title: Task 262.8.1 Competition vertical migration
date: 2026-07-29
status: completed
task: "262.8.1"
tags:
  - competition
  - strangler-migration
  - event-journal
  - control-graph
  - rollback
---

# Task 262.8.1 Competition vertical migration

## Result

Competition is the first legacy service moved behind the vNext lifecycle boundary. Its scientific
execution engine, `cycle-manifest.json`, evidence gate, artifacts, Vault record, CLI reader, and
compatibility writer are retained. The default `legacy` mode is behavior-identical and writes no
migration files.

Two opt-in modes are selected by
`AUTORESEARCH_COMPETITION_MIGRATION_MODE=shadow|vnext`:

- `shadow` keeps the legacy lifecycle authoritative, writes a sealed standard-event journal and an
  acyclic Control Graph, then compares the projection with the legacy endpoint;
- `vnext` returns the verified projection as lifecycle authority, but is rejected before scientific
  execution unless two distinct complete formal shadow runs have earned promotion.

The feature flag is reversible. Existing legacy state and readers are kept for at least one
compatibility release.

## Frozen characterization

The versioned corpus `tests/fixtures/migrations/competition-v1.json` freezes six behaviors:

1. complete generated-characterization execution;
2. scientific negative result when no feasibility probe passes;
3. `ACCESS_REQUIRED` as a blocked endpoint;
4. an adapter exception as failed execution at the last valid persisted stage;
5. blocked execution resumed after the exact capability grant is supplied;
6. repeated observation of an unchanged terminal state without a new journal.

These distinctions are not interchangeable. In particular, an execution exception is not rewritten
as a scientific negative result, and an access request does not increment human-intervention count.

## Event and projection boundary

Every distinct legacy manifest/failure fingerprint receives one invocation journal. Events record
topic selection, selected topic, hypothesis, frozen plan, persisted attempts, evidence gate, and
terminal lifecycle meaning. The terminal event carries a normalized endpoint with logical artifact
paths and SHA-256 values; raw exception text is omitted and only its type and message digest remain.

Parity independently covers:

- normalized event semantics;
- terminal stage, outcome, and event status;
- scientific endpoint, attempt count, and release eligibility;
- evidence-gate decision;
- artifact roles, logical paths, existence, hashes, and sizes;
- redacted failure semantics;
- access-request and human-intervention counts.

Reports are revalidated against event bytes, lineage, terminal seal, projected endpoint, Control
Graph, and source fingerprint whenever they are read. Promotion records additionally bind each
formal parity report by file hash and seal hash. Altered promotion evidence blocks vNext before a
cycle directory is created.

## Resume and idempotency

The event journal treats blocked as terminal, while the legacy Competition service allows a later
capability grant to resume the same scientific cycle. The adapter preserves both meanings by
creating a child invocation journal whose first event is anchored to the blocked journal's terminal
checkpoint.

If `resume` sees an unchanged blocked or complete manifest, it reopens and validates the existing
journal and writes a terminal-idempotency observation. It does not append after a terminal seal or
create a second invocation.

## Formal vertical evidence

The opt-in local run under `runs/manual-live/task262-competition-migration-v1/` executed two
independently identified formal shadow verticals:

| Run | Source fingerprint | Lineage hash | Seal hash |
| --- | --- | --- | --- |
| `task262-competition-formal-1` | `e1b9341ba1070aec041be1b0aa305becef574b2949163ba4eeafa60d8a737e81` | `6ea971dea552a0c518fb5dfaaa50de3fbb5576a38cc3b2d8b01006b8c6d54cfb` | `9ea12c7db4d7ebc09c47b88e3fde10a1144535332163847462e249f22cc69bea` |
| `task262-competition-formal-2` | `9ea9dd5d80b128818e357203e562c496386a6eec873adcdbd2df4b5a8c2bebd6` | `7bd676c919de2fada851f489078524b82a40f262da01b6f5892600d971d918d9` | `c97312525d296df4d01611c02be8a01c9ab1a3956ef1b8060fb0134b4e4235ea` |

Both were complete, equivalent, legacy-authority runs. They enabled a separate vNext-authority
vertical:

- run: `task262-competition-vnext-cutover`;
- source fingerprint:
  `27f3fc286f1c667b97afa5573dc506c16b114de9742adb340a2316659024dc4d`;
- lineage:
  `511065dbfd129fb8625e1325962d26c2e5e9768e735d9f25b456bf276401bd13`;
- terminal seal:
  `42ee10bba0b8543e609a47a73e68c52e95ae5f842f6f5e383e97de0f87e8192a`.

Switching the same completed cycle back to `legacy` returned the identical lifecycle result. The
rollback report confirmed an equal projection, unchanged journal and seal, and all compatibility
files present.

## Scientific boundary

The three complete verticals executed the existing local generated logistic-system characterization
fixture. They validate migration and recovery semantics only. They do not rerun or reinterpret the
revealed official MDBench panel, do not change Gate A thresholds, and do not claim an official
MDBench result.

No dependency was upgraded. No legacy artifact was deleted. No public release or submission
authority changed.

## Verification

- Seven deterministic migration tests passed with the six-case corpus.
- All 61 Competition unit tests passed.
- The opt-in local vertical completed two formal runs, vNext cutover, and rollback.
- Full repository regression, Ruff, Mypy, and diff checks are recorded in `Agent.md`.

## Next slice

Task `262.8.2` must characterize and migrate Campaign in its own commit. Competition evidence cannot
be reused to waive Campaign's six outcomes, two formal runs, parity checks, or rollback rehearsal.

## Links

- [[exploration/graph-harness-loop-open-science-2026|vNext refactor research]]
- [[projects/ai_researcher_system/progress/task-262-5-durable-control-graph|Task 262.5 durable Control Graph]]
- [[projects/ai_researcher_system/progress/task-262-7-open-science-research-object|Task 262.7 Open Science research objects]]
- [[projects/ai_researcher_system/index|AI-Researcher System Project]]
