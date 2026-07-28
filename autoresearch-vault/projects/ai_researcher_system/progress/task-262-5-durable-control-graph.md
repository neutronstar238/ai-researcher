---
title: Task 262.5 durable LoopSpec and Control Graph
date: 2026-07-29
status: completed
task: "262.5"
tags:
  - kernel
  - loop-engineering
  - control-graph
  - crash-recovery
  - langgraph-characterization
---

# Task 262.5 durable LoopSpec and Control Graph

## Result

`autoresearch.kernel` now has a content-addressed `LoopSpec` and a deterministic
`ControlGraphRuntime`. The graph freezes versioned nodes, edges, deterministic guards, resource
budgets, retry boundaries, approvals, compensation, stop/pivot/escalation transitions, holdout
visibility, and terminal states. `EventJournal` is the only canonical per-run state; runtime
snapshots are derived from its validated event lineage.

The executor receives a stable idempotency key only after `loop.node.started` is durable. A crash
after an external side effect and before completion therefore reuses the same key instead of
silently repeating the effect. A terminal event committed before its seal is recovered from the
same validated lineage. State replay rejects rewritten approvals, proposals, completed nodes,
artifacts, budgets, usage, holdout visibility, or non-contiguous revisions.

## Scientific and permission boundary

- A model may return a non-executable proposal for a later graph version.
- It cannot mutate the frozen current graph, add permissions, compute a scientific gate, or
  authorize release.
- A negative result may follow an explicit pivot edge only when the mechanism family changes.
- Revealing a protected holdout prevents later adaptive nodes unless the frozen policy explicitly
  permits them.
- Failed side-effecting nodes can enter compensation only when a side effect was actually
  committed.
- Budget exhaustion, human rejection, missing permission, exhausted retry, and unsafe persisted
  content remain truthful blocked/failed/terminal outcomes.

## Harness and LangGraph boundary

`loop_result_from_episode()` verifies a content-addressed `EpisodePackage` and projects its
environment outcome, cost ledger, final artifact references, journal lineage, and seal into
provider-neutral node semantics. It does not treat model prose as a scientific conclusion.

`LangGraphControlAdapter` is a thin orchestration boundary around the canonical domain runtime.
The installed LangGraph 0.2.76 and LangChain Core 0.2.43 behavior was characterized before any
upgrade. Checkpoint/resume, static and dynamic interrupts, child subgraphs, parallel supersteps,
idempotent continuation, and checkpoint JSON serialization all passed. The characterization report
hash is `92983004c099b14799cd4102b644072013016541ae3da659e7380161b448fb3e`.

## Development vertical

The production public APIs were executed under
`runs/manual-live/task2625-control-vertical-20260728/`:

- episode hash: `0665caa73930a6b89533549e8b207742773b7116742e354333aa92a132eb98cc`;
- episode journal: 2 events, lineage
  `6452f122726b94ab6af5b5601d1cf6302d852af109368ca640899e09b52a6f1c`, seal
  `5cbf5270c7f8119150608c0a09f76dd2187ab7d6e19f12d74b6fcd10ff31abec`;
- LoopSpec hash: `904ec34c037b9089041ec83cefea565a178622437665745f9e6e1b8625c887cb`;
- loop snapshot hash: `a3a1c3ee1763e2f956ff9c070ad94b73a73cafcd1d46c573cf01a8c4027fa0a9`;
- loop journal: 6 events, lineage
  `56717d750f5dba32a6d2074191766925e896afd5aa203491881d8dda6d8ed5bb`, seal
  `7c473a9f026b03f9db90bf1b8241efd46539efbbf90a51242c420000bba440ea`;
- final status: `succeeded`, with 7 normalized tokens charged.

This is a deterministic development characterization of persistence and control semantics. It is
not a scientific result, model-quality result, legacy-service cutover, or release authorization.

## Verification

- 24 focused lifecycle/property/fault/adapter/vertical tests passed; `loop.py` reached 86% and the
  LangGraph adapter 97% line coverage.
- A 32-test matrix collected and passed both the legacy experiment-loop module and the new
  Control Graph module.
- Full regression passed with 848 tests and 6 opt-in live tests skipped; repository coverage was
  86%.
- Full Ruff passed. Mypy passed for 142 source files.

## Frozen boundaries

- Competition, Campaign, Sprint, EvidenceGraph, AuditLog, existing scientific artifacts, and
  existing state files remain authoritative and unchanged.
- No dependency version changed and no legacy writer was disabled.
- Task 262.6 must add W3C PROV-aligned evidence and Vault projections on this event spine; task
  262.8 owns parity-gated service migration.

## Links

- [[exploration/graph-harness-loop-open-science-2026|vNext refactor research]]
- [[projects/ai_researcher_system/progress/task-262-4-bounded-harness|Task 262.4 bounded Harness]]
- [[projects/ai_researcher_system/index|AI-Researcher System Project]]
