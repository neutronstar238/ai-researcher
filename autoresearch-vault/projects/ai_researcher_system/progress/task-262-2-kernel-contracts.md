---
title: Task 262.2 canonical event and four-plane graph contracts
date: 2026-07-28
status: completed
task: "262.2"
tags:
  - kernel
  - graph-engineering
  - provenance
  - event-lineage
---

# Task 262.2 canonical event and four-plane graph contracts

## Result

`autoresearch.kernel` now provides the first provider- and runtime-neutral vNext implementation slice.
It changes no Competition, Campaign, Sprint, EvidenceGraph, AuditLog, dependency, or persisted-result
behavior.

Public contracts:

- `EventActor` distinguishes operator, scheduler, Agent, model, tool, deterministic policy, and system
  responsibility.
- `RunEvent` records run/task/event identity, positive sequence, UTC occurrence time, actor, type,
  status, action, parent/fork identity, artifact references, decision/approval references, idempotency
  key, JSON payload, and canonical SHA-256.
- `GraphNode`, `GraphEdge`, and `GraphSnapshot` isolate control, provenance, knowledge, and
  evaluation-policy planes.
- `contract_json_schemas()` exports deterministic JSON Schema for all five public models.

## Frozen invariants

- Unknown fields, invalid IDs, non-UTC timestamps, non-JSON values, NaN/Infinity, duplicate artifact
  references, incomplete parents, and inconsistent fork parents fail validation.
- Loading an event whose content no longer matches `event_hash` fails closed; a caller can also run
  `verify_integrity()` after in-memory nested data access.
- Graph nodes and edges belong to exactly one snapshot plane. Duplicate IDs, dangling endpoints,
  plane mismatches, and self-loops fail validation.
- Control graphs must explicitly choose `acyclic` or `explicit_boundaries`. In the latter, removing
  marked boundary edges must leave a DAG, so every intentional loop is visible.
- Node, edge, artifact, and object-key ordering is normalized or canonically serialized so equivalent
  inputs produce the same digest.
- A sequence-1 event has no parent unless it is the first event of a fork and names a different parent
  run; later events require a parent event.

## Verification

- Focused: 31 unit/property tests passed; `src/autoresearch/kernel/contracts.py` reached 100% line
  coverage.
- Regression: 778 tests passed and 5 opt-in live tests were skipped.
- Quality: full Ruff passed; Poetry-environment Mypy passed for 137 source files.
- Interop smoke: Poetry imported `RunEvent` and `GraphSnapshot` and exported five JSON Schema
  documents.
- No external data or model call applies to this pure contract task.

## Boundary and next task

This task defines valid records; it does not persist them, prove a chain is contiguous, redact secrets,
or migrate a legacy service. Task 262.3 must add atomic append, contiguous sequence enforcement,
idempotency, parent-hash validation, terminal seals, deterministic replay, fork, corruption handling,
and sensitive-field rejection while legacy state files remain authoritative.

## Links

- [[exploration/graph-harness-loop-open-science-2026|vNext refactor research]]
- [[projects/ai_researcher_system/index|AI-Researcher System Project]]
