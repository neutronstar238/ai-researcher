---
title: Task 262.6 W3C PROV-aligned evidence v2 and Vault projections
date: 2026-07-29
status: completed
task: "262.6"
tags:
  - provenance
  - evidence-graph
  - w3c-prov
  - obsidian
  - source-anchored
---

# Task 262.6 W3C PROV-aligned evidence v2 and Vault projections

## Result

`autoresearch.kernel` now exposes a provider-neutral, content-addressed provenance-v2 bundle.
Its domain contracts cover the W3C PROV starting points and qualified relations:

- Entity, Activity, Agent, Usage, Generation, Derivation, Association, and Plan;
- Claim, supporting/limiting Evidence, Counterevidence, Validation, and Decision;
- SourceSnapshot, ToolInvocation, and digest-only ModelInteractionDigest.

Every record carries a stable ID, version, UTC valid time, optional invalidation/supersession, and
event references. The bundle rejects duplicate or orphan IDs, invalid relation times, source
snapshot/hash disagreement, invalid responsibility, broken revision history, non-model interaction
agents, and canonical bundle-hash mismatch. JSON Schema export is available for every public
contract.

This is aligned to the [W3C PROV-O recommendation](https://www.w3.org/TR/prov-o/), the
[PROV data model](https://www.w3.org/TR/prov-dm/), and
[PROV constraints](https://www.w3.org/TR/prov-constraints/). It is a domain projection, not yet a
PROV JSON-LD or RO-Crate export; those public interchange objects belong to task 262.7.

## Fail-closed claim query

`require_claim_trace()` returns a core claim only when it can resolve:

```text
source snapshot / frozen input
  -> qualified Usage
  -> generating Activity
  -> associated software, model, tool, or deterministic-policy Agent
  -> content-addressed artifact
  -> current, non-invalidated Validation
  -> policy Decision and its generated artifact
```

The query checks the bundle hash before traversal. A nested in-memory edit, persisted content edit,
missing source, missing responsible association, missing artifact generation, missing current
validation, or ungrounded decision blocks the claim. Revisions require an invalidated predecessor
and a strictly newer version; current evidence and validation histories exclude superseded records.

## EvidenceGraph v1 compatibility

The existing `EvidenceGraph` v1 implementation and readers were not rewritten. A separate
projection maps current v2 claims, source snapshots, artifacts, validations, and directional
evidence into the v1 shape. Only `supports` becomes `supports_claim=true`; `contradicts` and
`limits` remain visible as non-supporting v1 evidence. Existing v1 coverage gates and round trips
continue to pass.

## Approved Vault projection

Vault writes require an explicit record-ID allow-list. The projector supports literature,
hypotheses, failures, skills, strategies, experiment records, evidence, and decisions. Generated
notes include:

- source URI and artifact hash;
- confidence and validation history;
- version, valid-from/to, invalidation, and supersession;
- event IDs and run ID;
- Obsidian wiki-links among claims, evidence, sources, artifacts, and decisions.

Unapproved and unknown IDs are not projected. The task's real-round projection was written to the
ignored characterization area rather than silently rewriting canonical historical campaign notes.

## Real round characterization

The opt-in smoke called `validate_campaign_directory()` over the existing
`task260-autonomous-ccfb-v1/round-001`. It did not rerun an experiment, call a model, change a
threshold, or reinterpret the scientific endpoint.

The resulting bundle hash is
`a2e54556b3f6e242deeaff3d7c87400ae23e701ef034983fb6964a3c2df4c782`.
The core claim is:

> Round 001 did not pass its frozen contribution gate and the deterministic decision advanced to
> the next round.

Its resolved chain contains:

- frozen protocol and official executor inputs;
- the unseen-evaluation Activity and frozen software Agent;
- unseen-evaluation artifact and source snapshot;
- deterministic contribution-gate Activity and adjudicator Agent;
- validated failed-gate evidence;
- deterministic decision Activity and generated `next_round` artifact.

The original positive hypothesis is retained separately with both `contradicts` and `limits`
evidence. The bundle contains only `campaign://`, digest, and stable-ID references—no repository
absolute paths. It projects to two v1 claims and three v1 evidence edges, and writes 12 explicitly
approved Obsidian notes.

Characterization artifacts are under
`runs/manual-live/task2626-provenance-v2-20260729/`:

- `provenance-bundle.json`;
- `claim-trace.json`;
- `evidence-v1-compatibility.json`;
- `smoke-summary.json`;
- isolated `vault/` projection.

## Verification

- 9 focused provenance/evidence/Vault unit tests passed; `kernel/provenance.py` reached 93% line
  coverage in the focused compatibility matrix.
- One deterministic generated campaign round passed the same v2 builder and v1 coverage gate.
- 43 legacy-v1/new-v2/campaign/Vault tests passed with the real smoke skipped by default.
- The explicit real-round smoke passed and proved nested-tamper and missing-generation blocking.
- Full regression passed with 858 tests and 7 opt-in live tests skipped at 86% coverage.
- Full Ruff passed. Mypy passed for 145 source files.

## Frozen boundaries

- Existing Campaign, Competition, Sprint, EvidenceGraph v1, scientific artifacts, and legacy state
  files remain authoritative and unchanged.
- No dependency version changed and no legacy writer was disabled.
- No public export, external release, or submission authority was added.
- Task 262.7 owns validated Open Science exports; task 262.8 owns parity-gated service migration.

## Links

- [[exploration/graph-harness-loop-open-science-2026|vNext refactor research]]
- [[projects/ai_researcher_system/progress/task-262-5-durable-control-graph|Task 262.5 durable Control Graph]]
- [[projects/ai_researcher_system/index|AI-Researcher System Project]]
