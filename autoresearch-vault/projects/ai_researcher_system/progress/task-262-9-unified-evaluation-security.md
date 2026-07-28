---
title: Task 262.9 unified evaluation, observability, and Agentic security gates
date: 2026-07-29
status: implemented
task: "262.9"
tags:
  - evaluation
  - observability
  - agentic-security
  - opentelemetry
  - holdout-integrity
  - evidence-first
---

# Task 262.9 unified evaluation, observability, and Agentic security gates

## Outcome

AutoResearch now has one provider-neutral evaluation plane over sealed episode, journal, Control Graph, provenance,
and migration evidence. It does not replace the scientific executor or legacy compatibility writers. The evaluation
report keeps two conclusions separate:

- **system quality**: protocol, replay, permissions, budget, holdout, security, and repeated-trial reliability;
- **scientific validity**: whether the environment outcome is supported by matching frozen evidence.

A verified negative result can therefore complete a research trial. A smooth trajectory with mismatched evidence,
unknown cost, grader bias, holdout leakage, or missing hard-gate coverage cannot promote.

## Implemented contracts

- Task, trial, trajectory, outcome, rubric, grader, uncertainty, cost, failure slice, promotion, rollback, regression,
  and fault records are strict and content addressed.
- Trial and report verdicts are recomputed from their nested records. Two nominal repeats cannot reuse the same
  episode evidence.
- Five independent local regressions cover protocol match, evidence match, scientific core, replay fidelity, and
  holdout integrity.
- Ten deterministic fault cases cover goal hijack, tool misuse, identity/privilege abuse, supply-chain mismatch,
  unexpected code, memory poisoning, runaway loops, evaluator bias, holdout leakage, and evidence mismatch.
- Hard gates are non-compensating. A candidate already active can fail only to a hash-bound rollback target; otherwise
  evaluation rejects the inconsistent report.
- External long-running benchmark suites remain explicit opt-ins and are not hidden CI network dependencies.

## Observability boundary

The local exporter pins OpenTelemetry core Semantic Conventions 1.43.0, the GenAI semantic-conventions repository at
commit `d74a9bbc419c67dd78ea4fcc26280381ef0bb9db`, and OTLP 1.11.0. It writes atomic, content-addressed,
single-line local OTLP JSON:

- prompt, response, tool arguments/results, grader explanations, secrets, and private paths are absent;
- content is represented only by digest, field count, and a redaction marker;
- sensitive custom metadata is hashed;
- optional raw content requires an unexpired, scope-bound grant and a separate local root;
- Event Journal, episode, and provenance remain authoritative; OTel is diagnostic exchange only.

## Real adoption evidence

The opt-in smoke read the two existing completed Sprints
`task261-bounded-autonomous-clean-v1` and `task261-bounded-autonomous-clean-v2`. Both are scientifically negative,
fully persisted observations. No model, literature search, experiment, manuscript, paper build, or submission was
rerun.

- decision: `promote`
- verified-negative trials: `2`
- evaluation report: `b5e21a0a93e1b3caa96f4a5f5bf7ec637a09bf97305d39e9d26164324ea6d1ee`
- fault matrix: `53f182bb856d702b5ee1bd90ec5384369ee43e6dc0910f2e15419cd972560f73`
- five-dimension regression: `c2a466d01aa703d5c62a8eb47131aec0dbcc95bd424033507f67b540f14ba33c`
- redacted OTLP: `86236e468ad1a3dce58acbb02ae8054a857aee45b53f8d5becec43bb2c171e85`
- raw sensitive artifact persisted: `false`
- source fingerprints:
  `0e9477262ad603d10c422c0c962ef5e962007465cf3c1675f8f08cbc63c18253`,
  `81a3c70c1d8a34e92d099c40c3b1d7508f4ff76897c59d029a52f35cd2c667cf`

The deterministic focused matrix collected 30 items: 21 evaluation tests and 8 OTel tests passed; the opt-in smoke
skipped by default. This adoption proves the new gates consume real sealed evidence. It is not an external benchmark
score or a publication claim. Full regression then passed with 934 tests and 12 opt-in tests skipped at 87% line
coverage; `ruff check src tests` passed, and Mypy reported no issues in 151 source files.

## Limits and next step

Competition, Campaign, Sprint compatibility writers, the shallow legacy `AuditLog`, and current dependency pins remain
in place. Task `262.10` must perform the dependency characterization, compatibility-window closure, independent
reproduction, and rollback rehearsal before any duplicate path is retired. Gate B, public release, unrestricted
execution, and external submission remain human-approved actions.

## Links

- [[exploration/unified-evaluation-observability-security-2026|Cross-search and frozen design baseline]]
- [[projects/ai_researcher_system/progress/task-262-8-3-sprint-migration|Sprint migration evidence]]
- [[projects/ai_researcher_system/progress/task-262-6-prov-evidence-v2|Provenance and evidence v2]]
- [[projects/ai_researcher_system/progress/task-262-7-open-science-research-object|Open Science research objects]]
