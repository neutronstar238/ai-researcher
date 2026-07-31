---
title: Task 263.6.7.1 benchmark-validity protocol freeze
date: 2026-07-31
status: completed
task: "263.6.7.1"
tags:
  - ai-scientist
  - benchmark-validity
  - systematic-mapping
  - preregistration
  - open-science
---

# Task 263.6.7.1 benchmark-validity protocol freeze

## Request and outcome

The request was to explain why real automated-research execution still does not
reach publication grade, cross-search current automated-science research, and
optimize the research route before continuing implementation.

The completed outcome is a prospective, result-free systematic-mapping
protocol. It changes the next research object from another post-hoc benchmark
experiment to a falsifiable question about whether AI-scientist benchmarks
provide the independent units, rights, objective measurement, baseline,
compute, seal, and contamination controls required for defensible claims.

Status is `frozen-pre-extraction`. No formal database query, non-pilot record
extraction, benchmark outcome, candidate-model call, Research Question
Certificate, or confirmation panel was created.

## What was frozen

- Four open scholarly indexes: arXiv, OpenAlex, Crossref, and DBLP.
- Seven construct lenses and 28 exact source-specific query bindings covering
  2023-01-01 through 2026-07-31.
- One backward and one forward citation round, 16 known-item recall sentinels,
  and a minimum recall of 0.90.
- A fixed-revision release as the study unit and a unique benchmark family as
  the independent unit. Tasks, seeds, attempts, difficulty variants, votes,
  and repeated revisions remain nested observations.
- AutoSDT-5K, ScienceAgentBench, CORE-Bench, and QRData as protocol-development
  pilots excluded from the primary cohort.
- At least 20 additional non-pilot benchmark families for the primary map.
- A 42-field Benchmark Admission Card, seven explicit evidence states, and 12
  non-compensating admission gates. Only `verified-pass` satisfies a gate.
- Four descriptive endpoints, six sensitivity analyses, 10 stop rules, Wilson
  intervals, and a 10,000-replicate family-level bootstrap with seed `2636071`.
- A diagnostic-negative/open-resource endpoint when sample, recall, agreement,
  coverage, integrity, or human-role gates fail. No causal Agent or critic claim
  is permitted by this protocol.

## Human validity boundary

Formal screening and critical coding require two real independent human
reviewers and a distinct human adjudicator. The protocol freezes 100-percent
dual screening and coding, pre-adjudication exact agreement at least 0.90,
Cohen kappa at least 0.80 when estimable, overall critical-evidence coverage at
least 0.90, and per-field coverage at least 0.85. Current human identities are
deliberately unset, so the automated system cannot manufacture agreement or
make legal, authorship, release, or submission decisions.

Task `263.6.7.2` may build result-blind adapters, raw-response logs, family
deduplication, and empty evidence packets. Task `263.6.7.3` remains blocked
until the three real human roles are assigned.

## Architecture impact

- Graph Engineering separates claim evidence, scientific family/source
  lineage, immutable artifacts, and control/adjudication state. Graph node
  counts never become statistical sample sizes.
- Harness Engineering versions search adapters, raw-response hashes, PRISMA-S
  logs, deduplication, Admission Cards, scorer/baseline commands, compute
  envelopes, and explicit failure states.
- Loop Engineering fixes search, screening, coding, adjudication, analysis,
  promotion, and stop transitions. Citation chaining is bounded to one round
  in each direction and confirmation never flows back into development.
- Open Science packages protocol, queries, responses, revisions, cards,
  disagreements, failures, environments, and human decisions with PROV and
  RO-Crate lineage, while release remains permissioned.

## Formal evidence

Formal package:

`runs/manual-live/task263671-benchmark-validity-protocol-freeze-v1/`

- protocol: `ed6088c225d5c7f7710ecb69507659003b5b97e06dc7c0ee005a81ed2712e8ed`;
- report: `0ed7f637ab10b10cc6b265c60020437255f64cc8d8a7259ad9eae9c9051a9408`;
- result-free projection:
  `e8628d484cfd3d5ead9dbb9b0e6610ca4f68adeebda4d0ef463bc3ac1d5e1881`;
- replay certificate:
  `85e8ee4da9ea685b32f1896759e5235bec3e47fa59af8b12e0790f9026d9b93a`;
- replay input:
  `e0e2c55aed44597be4cd9661b050590bb0ac4924ae5b7f6b642a09a865f5a4df`;
- frozen standard-library runner:
  `fb7c4f4e535a7168a89c48fc77a28772afd931e0cd61d2df29a6d62a6c8dee6f`;
- manifest:
  `9b99c6e4ccb43ea4982c546ebf6e18a34df63ae3f474ace3ed58ee2464a96b77`.

Two distinct clean Python environments reproduced the exact result-free
projection with zero retry. The formal loader rejected protocol or artifact
tampering.

## Verification

- Seven focused deterministic tests passed.
- One opt-in live smoke passed against two real clean Python installations.
- Ruff passed for the new module, runner, exports, and tests.
- Mypy passed for all 23 research source files.
- Formal artifact persistence, recursive load, schema export, Markdown report,
  tamper rejection, and result-bearing payload rejection passed.

The live smoke intentionally made no external search request: this subtask is
the timestamped protocol freeze that must precede Task `263.6.7.2` capability
checks and Task `263.6.7.3` census execution.

## Next task

Implement Task `263.6.7.2` without changing the frozen protocol: deterministic
source adapters, raw-response hashing, append-only search logs, known-item
recall, paper/family/revision deduplication, frozen screening forms, and empty
evidence packets. Do not extract benchmark outcomes or use the four pilots in
the primary cohort.

## Related notes

- [[../../../exploration/benchmark-validity-systematic-mapping-protocol-2026]]
- [[../../../exploration/replacement-objective-data-tournament-2026]]
- [[task-263-6-6-replacement-objective-data-tournament]]
- [[../index]]
