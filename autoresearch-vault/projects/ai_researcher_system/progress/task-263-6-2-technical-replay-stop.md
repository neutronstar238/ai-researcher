---
title: Task 263.6.2 consumed-panel technical replay stop decision
date: 2026-07-31
status: completed
task: "263.6.2"
tags:
  - autoresearch
  - confirmation
  - consumed-panel
  - negative-results
  - open-science
  - reproducibility
  - runtime-determinism
  - stop-decision
---

# Task 263.6.2 Consumed-Panel Technical Replay Stop Decision

## Decision

The exact frozen `portfolio_memory` claim was re-executed with the certified
v2 evaluator on the already consumed 60-task panel. Both interpreter matrices
completed, but their scientific projections were not exact. The terminal
class is therefore:

`invalid_technical_replay`.

No formal technical-effect report was generated. A permanently
non-inferential incident object records the mismatch and the diagnostic
stop decision:

`stop_portfolio_memory_claim`.

The next route is:

`return_to_objective_opportunity_tournament`.

Task 263.6.3 is not entered. The old claim may not buy another panel, and the
v1 or v2 results may not be filtered, retuned, or relabeled as fresh
confirmation. Task 263.6 and Task 263.7 remain open/blocked. Public release
and external submission remain unauthorized.

## Frozen repair boundary

The repair freeze was written before repaired outcomes existed. It binds:

- the immutable v1 confirmation freeze, report, result, scientific projection,
  and 69-row measurement-failure signature;
- the Task 263.6.1 evaluator-certificate report and manifest;
- the v1 and v2 controller/runner source hashes;
- the primary and replay execution indexes;
- the exact 12-candidate, nine-policy, 1,620-assignment claim;
- the original thresholds, budgets, randomization, statistical policy, and
  publication route;
- exactly three allowed repairs: lexical classification-label semantics,
  structured failure domains, and the materialized-bundle resume correction;
- a pre-result stop conjunction requiring exact two-interpreter projection,
  zero null integrity failure, complete label isolation, no unexpected
  candidate/input/evaluator/infrastructure failure, both family effects
  nonnegative, corrected risk difference at least `+0.10`, and more favorable
  than unfavorable tasks.

Even if every check had passed, the result could only become
`eligible_for_new_mechanism_review`; it could not itself authorize a new
confirmation or publication.

The repair-freeze hash is:

`6b7f124fab513e8032ff777b2a92926cf5e57836d409ad133700c49946cea22b`.

The two scientific sources remained unchanged after freeze:

- v2 policy controller:
  `f7a561542eb30b18fb4369fdf1d318de0d22ce97b3c2465276ff121465299ced`;
- technical replay orchestrator:
  `924c3e0a7cab8c588870b542956881524e386a85cea3c1baa22049fe00185e65`.

## Formal execution and replay failure

Primary and replay each completed:

| Dimension | Per interpreter |
|---|---:|
| Policy/ablation assignments | 1,620 |
| Null controls | 180 |
| Independent tasks | 60 |
| Within-task seeds | 3 |
| Policies/ablations | 9 |

The controller result hashes are:

- primary:
  `7a37aaf05a8293b365fbe93b454c985bb9d488483eec00a05d6dddaf47b03bc4`;
- replay:
  `b001641278a2324c5c304b49eba9bb299f03101b3c8bc1b4518d104cfbbe466b`.

Their scientific projection hashes differ:

- primary:
  `cfa130e8a66979e3ecb746c8c1a62a6a66c17fbdcbe3d4514b3f5ea8f267b941`;
- replay:
  `a80256df42f0eab0c315adc021ef416fa6f3c9a62ed6c7b7078ebc53a0ce9070`.

Exactly 8/1,620 assignment projections differ, all on
`openml-cc18-task-14970`, seed `3253`, across the eight policies that reached
the shared evaluation. In the primary interpreter, the `xgb-deep` F1
evaluation succeeded with objective score `0.9627079201448745`. The replay
interpreter reached the 60-second runner deadline. The eventual selected
candidate and task-success endpoint remained the same, but candidate-stage
status, score, promotion, memory correction, and downstream trajectory fields
changed. Because the search trajectory is part of the scientific treatment,
the exact-replay gate correctly failed.

All 180 null-control projections match. The mismatch is therefore localized,
not silently erased, and not evidence that the scientific effect replicated.

## Label-boundary evidence

The retained matrices contain 31 incomplete label-access attestations:

| Interpreter | Pre-F3 unavailable | F3 unavailable |
|---|---:|---:|
| Primary | 12 | 3 |
| Replay | 13 | 3 |

The six F3 rows are the random-forest evaluation on
`openml-ctr23-task-361252` for all three seeds in both interpreters. Their
execution configs bind the correct label path and hash, but the subprocesses
time out before returning `labels_accessed` and the runner label hash.

These records are not proof of label leakage. They are proof that the
execution did not produce the attestation required by the frozen conjunction.
The same conservative rule applies to the 25 pre-F3 timeout rows: no label
path was intentionally supplied, but a missing subprocess attestation cannot
be upgraded to positive isolation evidence.

## Non-inferential diagnostic

Because exact replay failed, the following numbers are descriptive incident
diagnostics, not confirmation:

| Measure | Result |
|---|---:|
| `portfolio_memory` task successes | 40/60 |
| `linear_self_loop` task successes | 43/60 |
| Favorable / unfavorable / tied | 2 / 5 / 53 |
| Risk difference | -0.050000 |
| Conservative exact 95% interval | [-0.196505, 0.105569] |
| Exact McNemar p | 0.453125 |
| CC18 risk difference | -0.048780 |
| CTR23 risk difference | -0.052632 |
| Null integrity failures | 0/180 |

The primary repaired matrix retains 225 failed objective evaluations:

- 180 intentional invalid-probe candidate failures;
- 30 unexpected `candidate_fit_or_predict_failure` records;
- 15 infrastructure `runner_timeout` records.

The diagnostic analysis hash is:

`f599ed894e484dae483c25e27364ebea5ceec27f45c925bfc625e16fed0d08b3`.

Only three stop checks pass: complete matrices, zero null-integrity failures,
and unchanged repair scope/route. Both family effects, minimum practical
effect, directional task balance, label attestation, failure cleanliness, and
exact two-interpreter replay fail. The claim would therefore stop even if the
projection mismatch were ignored: its observed direction is unfavorable in
both benchmark families.

## Fail-closed incident research object

The frozen replay intentionally refused to emit
`consumed-panel-technical-report.json`. A separate incident auditor reads the
retained matrices without modifying them and creates:

- a strict content-addressed incident report;
- the eight minimal scientific-projection diffs;
- all label-boundary attestation anomalies;
- the diagnostic stop analysis;
- JSON Schemas with every inference, confirmation, publication, release, and
  submission gate fixed to `false`;
- a recursive SHA-256 inventory over 36,521 artifacts.

Immutable identities:

- incident:
  `f756ab01b1e7291875470e75d63e5fe668bf199a50659c041799e038578f9dd0`;
- incident manifest:
  `79bfb70fa5ded53686ada5deadb1e735450ad442a441867b93eef615a9c30fe6`;
- diagnostic analysis:
  `f599ed894e484dae483c25e27364ebea5ceec27f45c925bfc625e16fed0d08b3`.

The object cannot represent a positive result, credible negative, independent
confirmation, publication evidence, public release, or submission approval.
Its job is to make the failed scientific gate durable and difficult to bypass.

## What this changes in the research path

The result rules out the current publication route. It also reveals a gap
between fixture calibration and workload qualification. The 152-probe
certificate proved cross-format label semantics and small-fixture replay, but
it did not prove that slow real task/candidate combinations stay on the same
side of a hard wall-clock deadline under two full-matrix executions.

The next opportunity tournament must add a result-blind
`WorkloadQualificationCertificate` before any new scientific freeze:

1. sample the slowest representative candidate/task strata using development
   data only;
2. repeat them across both interpreters and planned concurrency levels;
3. separate algorithmic compute budget from orchestration deadline;
4. calibrate deterministic compute/work limits or prospectively justified
   timeout slack;
5. reject a mechanism whose scientific trajectory changes at the runtime
   boundary;
6. freeze telemetry, retry, timeout, and exact-versus-tolerant replay semantics
   before result-bearing execution.

The new question must be mechanism-based and independently testable. Candidate
tracks should compare, rather than assume, ideas from recent automated-science
work:

- structured world models/evidence graphs for long-horizon coherence;
- Socratic causal critics that force constraints, counterexamples, and
  falsification criteria before experiment promotion;
- lab/data/environment-in-the-loop objective feedback with explicit human
  scientific responsibility;
- verification-native harnesses that score unsupported or irreproducible
  claims as failures, not as polished prose.

None of these mechanisms may reuse the consumed v1/v2 panel as development or
confirmation evidence. At least three tracks may all fail the opportunity
gate. Only a new Research Question Certificate, fresh development evidence,
adequate independent units/power, a qualified evaluator/runtime, and a
disjoint zero-result panel can eventually authorize a new one-use
confirmation.

## Verification

- five deterministic incident unit/property tests passed;
- six existing technical-replay tests passed;
- the opt-in retained-artifact incident smoke passed and reconstructed the
  report plus recursive manifest in 74.29 seconds;
- 8/1,620 assignment and 0/180 null projection differences were reconstructed
  exactly;
- all claim/release JSON Schema constants remain `false`;
- both frozen scientific source SHA-256 values remain unchanged;
- canonical full regression passed with 1,077 tests, 26 opt-in live skips, and
  82% coverage;
- repository-wide Ruff passed;
- Mypy passed across 170 source files;
- Poetry validation exited zero with pre-existing metadata deprecation
  warnings;
- diff, task, link, and immutable-source hash audits passed.

## Links

- Parent project: [[../index|AI-Researcher System Project]]
- Invalid v1 diagnosis:
  [[task-263-6-0-invalid-confirmation-diagnosis]]
- Evaluator certificate:
  [[task-263-6-1-evaluator-compatibility-certificate]]
- Publishability recovery:
  [[../../../exploration/publishability-recovery-ai-scientist-2026]]
- Graph/Harness/Open Science research:
  [[../../../exploration/graph-harness-loop-open-science-2026]]
