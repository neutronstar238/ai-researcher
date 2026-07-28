---
title: Task 262.10 vNext runtime and compatibility release boundary
date: 2026-07-29
status: implemented
task: "262.10"
tags:
  - langgraph
  - compatibility
  - migration
  - rollback
  - release-gate
  - evidence-first
---

# Task 262.10 vNext runtime and compatibility release boundary

## Outcome

AutoResearch has closed the internal R1 compatibility boundary. LangGraph/LangChain were upgraded
only after the old behavior report was frozen, and the upgraded environment repeated checkpoint/
resume, static and dynamic interrupts, subgraphs, parallel supersteps, resume idempotency, and JSON
serialization successfully.

R1 means the shared Event Journal, Harness, Control Graph, provenance, Open Science, migration, and
evaluation layers now have one machine-verifiable compatibility decision. It does **not** grant
public release, external submission, unrestricted execution, or safety-policy self-modification.

## Dependency and runtime evidence

- LangGraph: `0.2.76` -> `1.2.10`
- LangChain: `0.2.17` -> `1.3.14`
- LangChain Core: `0.2.43` -> `1.5.2`
- checkpoint package: `4.1.1`
- SDK: `0.4.2`
- prebuilt package: `1.1.0`
- LangSmith: `0.10.11`
- Poetry lock SHA-256:
  `9e1894adecae09877114222fded4251113618dd9fe967668201153559573bbad`
- dependency-audit hash:
  `2e31dccf9c69af830bc0dfb8337085138ec633357e525ae0aa401b15af9a6fab`
- pre-upgrade characterization:
  `92983004c099b14799cd4102b644072013016541ae3da659e7380161b448fb3e`
- upgraded characterization:
  `dd62c3faef638b905755dbc26f6761957e5657175de7a3b641b6e5c718ebebd3`

The adapter uses in-memory checkpoints with an explicit JSON-plus serializer, pickle fallback
disabled, and empty custom JSON/MessagePack module allowlists. Repository inspection found no
persistent LangGraph checkpoint store, so no checkpoint bytes were migrated. The project-owned
Event Journal remains the durable domain truth.

## Compatibility decisions

- New governance audit writes now go only to the atomic, hash-chained Event Journal.
- A legacy audit JSONL is imported once without modification and remains a read-only compatibility
  input. An operator can create a separate validated JSONL rollback snapshot explicitly; continuous
  dual writes are not restored.
- The early linear `ResearchWorkflow` is deprecated and retained for one reader window because its
  standalone JSON checkpoints still need a compatibility reader. It is not production authority.
- Competition, Campaign, Sprint, and EvidenceGraph v1 writers/readers remain. They still carry
  scientific-engine or active-reader semantics that the formal Sprint lifecycle evidence does not
  prove safe to delete.
- Writers support the current schema; readers support current plus one prior generation under the
  named `vnext-plus-one-release` window. Historical artifacts are never bulk rewritten.

## Fresh R1 evidence

The first opt-in smoke created a fresh migration root from two different persisted real negative-
result Sprints:

- `task262-sprint-formal-1` / `task261-bounded-autonomous-clean-v1`
  - parity report `c83845580c8586a29cbc53ce2f931e2800ec8ee6832008ee3d6e20404b2a0ed4`
  - lineage `f6cd3dbe8e333a0eaec1682b683862a0aa2b48a70804cc9ab139de0d27384d08`
  - seal `4acf078e79fbc6bf88123e72e9a2e3a0ca442a5f8a524f45759a49d87e1fe519`
- `task262-sprint-formal-2` / `task261-bounded-autonomous-clean-v2`
  - parity report `ed3cff7959da062b38e708ae41d6bc89fe7c272b99bad1cd552322fe94407e5b`
  - lineage `2ce5316fc8de29d23843ab5e0f514f114bd98ee9cdd5b00b324b99aeac9879bc`
  - seal `5e40771aaf6b959a8246e6e7d2da0ba8bb4e6bedb93be3d32ca44012770ecbd9`

The same smoke projected the persisted blocked Sprint under vNext authority and returned it to
`AUTORESEARCH_SPRINT_MIGRATION_MODE=legacy`. The rollback report hash is
`9d456335a4e2218fdc95baaafec801d118c39cc4b3fd09f0a512d564d1a7e01f`;
result, projection, journal, and compatibility-file checks all passed.

The second smoke audited the installed/locked dependency graph, reran the upgraded characterization,
reopened both formal journals, and launched a separate `python -I` process in a clean directory. The
process reproduced the canonical evidence digest
`44136e7f210185516f652e18efca7029f7b338ba426dfe4ca03748671e96eb33`
without network access. The final internal release-report hash is
`acf73733022a59e3aaca2fd3b0dfd66fe88ba3c140a23a4a4a9a816715f9a638`.

No model, literature search, experiment, manuscript, paper build, public upload, DOI mint,
publication, or submission was rerun or performed by these adoption checks.

## Verification

- Focused runtime/audit/workflow matrix: `32 passed`.
- Unit release-boundary matrix: `8 passed`.
- Fresh Sprint migration opt-in smoke: `1 passed`.
- Fresh vNext R1 opt-in smoke: `1 passed`.
- Full regression: `946 passed`, `13 skipped`, `87%` line coverage.
- Full source typing: Mypy passed for `152` source files.
- Repository-wide Ruff: passed after closing the tracked deployment/helper-script debt.
- `poetry check --lock`: passed; Poetry's legacy metadata deprecation notices are tracked separately
  and do not change the audited dependency solution.

## Links

- [[exploration/graph-harness-loop-open-science-2026|vNext cross-search and refactor plan]]
- [[projects/ai_researcher_system/progress/task-262-9-unified-evaluation-security|Unified evaluation and security gate]]
- [[projects/ai_researcher_system/progress/task-262-8-3-sprint-migration|Sprint migration evidence]]
- [[projects/ai_researcher_system/progress/task-262-7-open-science-research-object|Open Science research objects]]
- [Compatibility and migration guide](../../../../docs/vnext-compatibility-migration.md)
