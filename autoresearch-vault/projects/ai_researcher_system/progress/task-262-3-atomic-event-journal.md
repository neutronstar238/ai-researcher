---
title: Task 262.3 atomic event journal, replay, and fork
date: 2026-07-28
status: completed
task: "262.3"
tags:
  - kernel
  - event-journal
  - replay
  - lineage
  - fault-injection
---

# Task 262.3 atomic event journal, replay, and fork

## Result

`autoresearch.kernel.EventJournal` now provides a local, provider-neutral event journal on top of the
task 262.2 contracts. Each committed event is a separate, immutable, canonically serialized file
named by its contiguous sequence. A temporary file is flushed before atomic replacement; directories
are also flushed on platforms that expose directory `fsync`.

The journal adds:

- an exclusive writer lease and caller-supplied expected-lineage check;
- exact idempotent retry and conflicting-key rejection;
- parent-ID/hash chain validation and a run-specific folded lineage hash;
- a deterministic terminal seal that prevents later appends and can be rebuilt after a crash between
  event commit and seal commit;
- validated checkpoints and reducer-based deterministic replay;
- child-run fork metadata bound to one immutable parent checkpoint, with explicit approval required
  for a non-terminal fork;
- full-envelope rejection of secret-like values and direct email identifiers before persistence.

## On-disk protocol

```text
<journal>/
  metadata.json
  events/
    0000000001.json
    0000000002.json
  .pending/
  .writer.lock
  terminal-seal.json
```

`metadata.json`, committed events, and `terminal-seal.json` are content-addressed and must contain the
exact canonical bytes expected by their schemas. Missing sequence files, unexpected entries,
non-canonical or partial JSON, altered hashes, broken parents, duplicate event IDs or idempotency
keys, and a mismatched terminal seal fail closed.

An interrupted pending write is discarded only while holding the writer lease. If the event file was
committed before interruption, retry returns that same event rather than repeating its side effect.
A committed terminal event without its seal is reported as recovery-required and receives the same
deterministic seal during explicit recovery or an idempotent retry.

## Frozen boundaries

- Existing Competition, Campaign, Sprint, AuditLog, and persisted state files remain authoritative.
  Task 262.3 does not shadow-write or migrate any service.
- The journal uses the standard library and the existing Pydantic contracts; it adds no runtime,
  database, cloud, or model-provider dependency.
- A fork creates new history and references its parent; it never rewrites or copies parent events.
- Breaking a stale writer lease is explicit, age-gated, and allowed only after the recorded process is
  no longer alive.
- The scanner blocks likely secrets and direct email identifiers; broader policy-aware redaction and
  public/private export views remain later tasks.

## Verification

- Focused: 33 unit, fault-injection, and Hypothesis property tests passed; `journal.py` reached 89%
  line coverage.
- Fault cases cover pending-write interruption, event-commit interruption, missing terminal seal,
  duplicate submission, stale lineage, active/dead writer leases, partial/non-canonical/corrupt
  records, sequence gaps, metadata/seal tampering, terminal append, replay, and terminal/non-terminal
  fork policy.
- Filesystem smoke created, appended, sealed, reopened, and replayed a real temporary-directory
  journal successfully.
- Regression: 811 tests passed and 5 opt-in live tests were skipped.
- Quality: full Ruff passed; Mypy passed for 138 source files.
- No external data or model call applies to this local persistence slice.

## Boundary and next task

Task 262.3 makes event history durable but does not yet define the execution environment that produces
an episode. Task 262.4 must add versioned `HarnessSpec`, bounded execution policies, truthful failure
attribution, and episode packages while keeping model and tool providers behind domain-neutral
contracts.

## Links

- [[exploration/graph-harness-loop-open-science-2026|vNext refactor research]]
- [[projects/ai_researcher_system/progress/task-262-2-kernel-contracts|Task 262.2 kernel contracts]]
- [[projects/ai_researcher_system/index|AI-Researcher System Project]]
