---
title: Task 263.4.2 clean baseline and causal preregistration
date: 2026-07-30
status: completed
task: "263.4.2"
tags:
  - autoresearch
  - baseline-reproduction
  - causal-inference
  - open-science
  - preregistration
  - search-policy
---

# Task 263.4.2 Clean Baseline and Causal Preregistration

## Decision

The selected FLAML application reproduced exactly across two separately
created environments on all seven development tasks, and the causal study was
frozen before any policy result existed.

Status: `ready_for_development_search`.

This status authorizes only Task 263.5 development execution. It is not a
positive scientific result, a novelty result, a confirmation result, a
general autonomous-science claim, or publication authorization.

## Why the earlier path could not publish

The system back end could execute experiments and build reproducibility
packages, but the scientific front end did not yet establish:

- a reliable strong comparator in a clean environment;
- result-free task-level success thresholds;
- budget-equivalent causal arms and one-at-a-time ablations;
- enough objective independent confirmation tasks;
- a frozen separation between development search and confirmation.

Without those properties, more loops or better prose could still produce a
selected development story rather than an identifiable, adequately powered
effect.

## Literature mechanisms operationalized

The study borrows testable mechanisms, not brand names, from the cross-search
in [[exploration/publishability-recovery-ai-scientist-2026]]:

- PaperBench motivates artifact-level replay instead of accepting a paper-like
  narrative as reproduction.
- AI Research Agents motivates separating search policy, operator grammar, and
  objective evaluator so the policy comparison is identifiable.
- MARS motivates fixed-budget branching and comparative cross-branch memory.
- MLRC-Bench motivates objective execution metrics rather than LLM innovation
  scores as the primary endpoint.
- AI Scientist studies motivate a narrow claim boundary: success on one
  executable domain does not imply general autonomous science.

## Clean baseline

The comparator is a bounded FLAML `2.6.0` application with:

- estimators `lgbm`, `xgboost`, `rf`, and `extra_tree`;
- one thread, seed `263420001`, and exactly 12 trials per task;
- a standalone runner that imports no AutoResearch code and has no network
  path;
- opaque task IDs and prepared local train/test inputs;
- raw prediction, trial-log, command, source, environment, data, split, metric,
  tolerance, and process evidence.

Official PyPI metadata fixed 14 wheel versions and SHA-256 values. Two virtual
environments were created independently from the same verified wheelhouse.
Each of seven development tasks then ran in distinct A/B runner processes.
Every task had exact A/B raw-prediction and objective-score agreement, with 12
record-bearing trials per run.

The replay proves only that this frozen FLAML application is repeatable on this
development panel. It does not reproduce all headline experiments in the FLAML
paper.

## Frozen causal design

### Primary estimand

At the task level, compare `portfolio_memory` with `linear_loop` on the
probability of valid task success. The two-sided exact McNemar test is primary;
secondary arm/ablation comparisons use Holm correction. Seeds are within-task
repeats, never independent units.

### Result-free thresholds

All 60 confirmatory units have a formula bound to their paired FLAML score:

| Family | Objective metric | Required minimum gain |
|---|---|---:|
| Tabular classification | balanced accuracy | `+0.005` |
| Tabular regression | R² | `+0.010` |

Success also requires valid artifacts, exact prediction replay, budget
compliance, and evaluator integrity. Neither baseline confirmation scores nor
policy scores were observed while these thresholds were created.

### Arms and ablations

The four matched arms are:

1. one-shot batch;
2. linear self-loop;
3. branching portfolio;
4. branching portfolio plus comparative memory.

The five one-at-a-time ablations remove certificate, diversity,
multi-fidelity, reviewer, or memory from the full arm.

### Shared budget

| Stage | Candidates | Training fraction | Max seconds each | Survivors |
|---|---:|---:|---:|---:|
| F0 | 12 | 0.125 | 5 | 6 |
| F1 | 6 | 0.25 | 10 | 3 |
| F2 | 3 | 0.50 | 20 | 1 |
| F3 | 1 | 1.00 | 60 | 1 |

Every arm is capped at 240 CPU seconds per task-seed and 60,000 model tokens.
Unused budget cannot be transferred across arms. The within-task seeds are
`1729`, `3253`, and `7919`.

Blocking by benchmark and domain produced 804 frozen assignments:
67 tasks × 3 seeds × 4 arms. Confirmatory labels/results are withheld; the
sealed runner cannot access network, public benchmark runs, development
trajectories, or author narratives.

## Live evidence

The final opt-in official-source and clean-install smoke passed in 150.93
seconds:

- 14 official wheel hashes verified;
- two separate virtual environments installed;
- seven development payloads prepared from official task/split sources;
- 14 independent A/B task runs completed;
- every raw prediction and objective score replayed exactly;
- every run recorded exactly 12 trials;
- no confirmatory payload or OpenML public run was requested;
- 60 thresholds and 804 assignments were frozen with
  `result_record_count=0`.

Content identities:

- baseline report:
  `e8f828c97561e789f523328aa25b82d512a159ab1e6f447f6163a770df4598e5`;
- preregistration:
  `100f8a0054fb1fc69ef77cbdeab5521361ba5b1a514082bac9e78493fcf0e707`;
- manifest:
  `df0324759c6099bdb1cf5764cdc4a3e5db838ae9328db0b8b427de562dc8055a`;
- dependency lock:
  `e03b61f59bbfeba0b6cab33d9c56611158b91913a754b61f667ecca2e77f8a51`;
- runner source:
  `1d7cb87d0c70887b122b5fb6bd83952562cb18d6c30c1b425d723f719116174a`;
- randomization schedule:
  `0e078296a7ca7b3d115f15bae8e9c3ef3d0e281a22dec9b48d2dd8e58d0ac588`;
- eight-schema bundle:
  `126bd2d2a840fdf2b6a6d63a487d5b6bb79d3fdc65a88d398ce7a914925c9dcb`.

The ignored evidence root is
`runs/manual-live/task26342-clean-baseline-preregistration-v2/`.

## Remaining publication blockers

There is still no portfolio-search result. Task 263.5 must execute all arms
under the frozen budget, measure low/high-fidelity calibration, retain failed
branches, run the key ablations, and produce either a frozen winner or a valid
no-winner development endpoint. Task 263.6 must then evaluate the frozen
decision once on the untouched 60-task panel.

Only a confirmed task-level effect with intervals, multiplicity control,
independent reproduction, ablation support, and a defensible nearest-work delta
can become a publication candidate. The construct remains bounded tabular-ML
search policy even if all later gates pass.

Public release and external submission remain human-gated and false.

## Related

- [[projects/ai_researcher_system/progress/task-263-4-1-open-objective-task-panel]]
- [[projects/ai_researcher_system/progress/task-263-4-0-search-policy-feasibility]]
- [[exploration/publishability-recovery-ai-scientist-2026]]
- [[projects/ai_researcher_system/index]]
