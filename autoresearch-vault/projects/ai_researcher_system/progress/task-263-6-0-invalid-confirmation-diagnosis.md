---
title: Task 263.6.0 invalid confirmation preservation and diagnosis
date: 2026-07-31
status: completed
task: "263.6.0"
tags:
  - autoresearch
  - confirmation
  - evaluator-integrity
  - negative-results
  - open-science
  - reproducibility
  - search-policy
---

# Task 263.6.0 Invalid Confirmation Preservation and Diagnosis

## Decision

The first one-use Task 263.6 endpoint is:

`invalid_confirmation`.

It is not a positive confirmation and must not be relabeled as a credible
negative. The complete result is retained because the invalidity is itself
reproducible, localized, and important evidence about the research harness.

Task 263.6 remains open. Task 263.7 remains blocked. Public release and
external submission remain unauthorized.

## What completed

The result-blind freeze preceded the ordinal-one reveal. Primary execution and
an isolated clean-room interpreter each completed:

| Dimension | Count |
|---|---:|
| Independent OpenML source groups | 60 |
| Task families | 2 |
| Within-task seeds | 3 |
| Policies and causal ablations | 9 |
| Policy assignments | 1,620 |
| Null-control assignments | 180 |
| Task-policy outcomes | 540 |
| Candidate-stage records | 77,760 |
| Primary unique evaluations | 2,860 |
| Primary logical cache reuses | 11,804 |

The runner had no network access, could not read raw development trajectories
or primary results during replay, cloned the frozen development-terminal
memory separately for each confirmation task, and updated memory only across
that task's three repeated seeds. The two clean baseline environments produced
identical predictions. All 60 data MD5 bindings and task-bundle hashes verify.

The primary and clean-room scientific projections are exactly equal:

`17299042a7f3b851b7e16fdea183e6cd6c9622833bfb678277d001b96d570789`.

## Frozen main comparison

| Measure | Result |
|---|---:|
| `portfolio_memory` task successes | 26/60 |
| `linear_self_loop` task successes | 28/60 |
| Favorable / unfavorable / tied | 1 / 3 / 56 |
| Risk difference | -0.033333 |
| Conservative exact 95% interval | [-0.153229, 0.093699] |
| Paired bootstrap 95% interval | [-0.100000, 0.033333] |
| Domain-block bootstrap 95% interval | [-0.115385, 0.025641] |
| Exact McNemar p | 0.625 |
| Prospective design power | 0.801422 |
| Frozen SESOI | 0.25 |

Both frozen benchmark-family risk differences are negative:

- OpenML CC18: `-0.024390`;
- OpenML CTR23: `-0.052632`.

The observed result therefore fails direction, SESOI, exact interval, exact
McNemar, and both-family nonnegative-effect gates. These values do not support
the development survivor. They are not by themselves a valid negative
endpoint because the validity conjunction also failed.

## Why the endpoint is invalid

The prospective null behavior gate passed: the `null-prior` candidate achieved
0/60 task successes. Its integrity gate failed on 69/180 rows.

The pattern is deterministic:

- exactly 23 classification tasks are affected;
- all three seeds fail on every affected task;
- all 69 failures are `runner_nonzero_exit`;
- all 69 lack a valid artifact, prediction replay, and evaluator-integrity
  result;
- regression null controls do not show this type pattern;
- the clean-room replay reproduces the same scientific projection.

The frozen F3 runner fits `LabelEncoder` on `train.csv`. On the affected tasks,
CSV inference represents target labels as numbers. The separately sealed
`labels.json` represents the same labels as strings. The runner inverse
transforms model predictions back to numeric training labels and passes them
together with string test labels to scikit-learn, which raises:

`ValueError: Mix of label input types (string and number)`.

This is an evaluator/serialization compatibility defect, not valid evidence
that a prior predictor should fail to execute. It also affects main-policy F3
validity on those tasks. The v1 runner and endpoint are frozen and were not
edited after reveal.

## Gate accounting

Passed validity checks include:

- frozen assets, interpreters, and package locks are content addressed;
- source MD5 and task-bundle hashes are valid;
- baseline A/B replay is exact;
- matrix and provenance inventory are complete;
- clean-room scientific projection is exact;
- network and development-trajectory isolation hold;
- task-independent memory cloning holds;
- the reveal was opened once after freeze;
- statistical policy and publication route did not change.

The only failed validity check is:

`null-control-integrity-valid`.

Because validity is conjunctive, the terminal class is invalid even though the
execution and reproduction checks passed.

## Immutable identities

- freeze:
  `7069ae95433cf7f83c86d35993dd3bd88020e919102d01594574c1860b3c8031`;
- reveal:
  `d27e25a450be075476519af052eaf6a1c34939c77376c8df87d32c1283b2fb52`;
- controller result:
  `883c37d0036a065d1dd426a9b17a95c2cfab876dbfcf34c188f0868eb1d15973`;
- analysis:
  `9b391da3181ace68e75e94a1bff35e3fcd7f8748a01ad29a02b5f04a2eb2a427`;
- report:
  `664993d04132dbfcff7aacb7431e499103c0698c2282c5325a6a42000401513a`;
- manifest:
  `c9c7e2993d3be15894579ee50867a7e1511184027d7cd2fcde427dabc2924567`;
- clean-room replay:
  `08c03a2271a31b2f999244914614fd442ec49c769bc3560a216d3ec138f39955`.

## Research-path correction

The 60-task panel is consumed. Neither a runner repair nor a favorable subset
can make it untouched again.

The next sequence is:

1. build a v2 `EvaluatorCompatibilityCertificate` across label dtypes,
   serialization formats, task families, allowed learners, dummy controls,
   label isolation, and prediction replay in both pinned interpreters;
2. fix the next-version already-materialized task-bundle resume path;
3. run a repair-lineage-bound technical replay on the consumed panel, clearly
   labeled exploratory and incapable of satisfying confirmation;
4. apply a frozen stop/advance certificate;
5. stop the `portfolio_memory` publication claim if the corrected effect is
   not directionally positive and practically plausible;
6. only with a new mechanism rationale and new development evidence may a new
   Research Question Certificate, disjoint panel, prospective power analysis,
   and zero-result freeze authorize another one-use confirmation.

This follows the same lesson emphasized by recent automated-research work:
objective execution feedback, traceability, and replication are necessary,
but evaluator semantics and independent confirmation remain
non-compensating scientific gates.

## Verification

- The public report loader recursively reconstructed raw primary results,
  analysis, manifest bindings, and clean-room results.
- The validity-aware opt-in live smoke passed against the completed immutable
  artifact in 178.47 seconds.
- The primary and replay scientific projection hashes are identical.
- Frozen-source hashes remained bound; only the smoke's preordained
  terminal-status assertion was corrected.

## Links

- [[projects/ai_researcher_system/progress/task-263-5-budget-matched-development-search|Task 263.5 development search]]
- [[exploration/publishability-recovery-ai-scientist-2026|Publishability recovery and AI Scientist cross-search]]
- [[exploration/graph-harness-loop-open-science-2026|Graph, Harness, Loop, and Open Science refactor research]]
- `Problem.md`: `P-20260731-026`, `P-20260730-025`, and
  `P-20260729-048`
