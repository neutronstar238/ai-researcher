---
title: Task 263.5 budget-matched development search
date: 2026-07-30
status: completed
task: "263.5"
tags:
  - autoresearch
  - causal-inference
  - development-search
  - multi-fidelity
  - open-science
  - reproducibility
  - search-policy
---

# Task 263.5 Budget-Matched Development Search

## Decision

The complete, repaired development matrix admits exactly one prospectively
named policy, `portfolio_memory`, to untouched confirmation.

Status: `ready_for_confirmation`.

This is a development-screening decision. It is not a statistically
significant treatment effect, an independently confirmed result, a general
autonomous-science claim, a publication decision, or release/submission
authorization.

## What was executed

The frozen catalogue contains 12 declarative candidates across nine mechanism
families:

- linear raw and scaled models;
- shallow and wide LightGBM;
- shallow and deep XGBoost;
- random forest and extra trees;
- histogram gradient boosting;
- a heterogeneous tree ensemble;
- a null prior/mean control;
- an intentional invalid-schema control.

A single local `qwen3.5:9b` call ordered the fixed catalogue before any
development result was visible. It used 753 prompt, 239 completion, and 992
total tokens. No assignment used a proposal, reviewer, or reflection model
call, and unused budget was not transferred.

The complete matrix contains:

| Dimension | Count |
|---|---:|
| Independent development tasks | 7 |
| Within-task seeds | 3 |
| Primary arms | 4 |
| One-component ablations | 5 |
| Task-seed-policy assignments | 189 |
| Candidate-stage records | 9,072 |
| Unique objective evaluations | 315 |
| Logical evaluation-cache reuses | 1,386 |

Every assignment retains all 12 candidates at each logical F0—F3 stage,
including rejects, non-promotions, failures, objective values, memory
corrections, intervention status, cost, and lineage. OpenML task is the
independent analysis unit; seeds are repeated measurements.

Every policy with multi-fidelity enabled executed F2 evidence on all seven
independent tasks, exceeding the frozen study-level minimum of three; the
`ablation-multi_fidelity` arm records zero F1/F2 executions by construction.
At F1, every enabled assignment retained three survivors and the branching
policies reserved the frozen one-slot mechanism-diversity exploration quota.

## Why the first complete matrix was not a scientific negative

The first complete v1 run ended in `negative_development`, but its failure audit
identified an evaluator defect rather than evidence against the search policy.
`openml-ctr23-task-361269` contains string-valued categorical features. The v1
runner routed every feature through a numeric median imputer, so multiple valid
mechanism families failed at F1 with:

`Cannot use median strategy with non-numeric data`.

All four main policies therefore had invalid assignments on that task. A zero
survivor decision contaminated by a shared evaluator incompatibility cannot be
interpreted as a valid scientific null.

The diagnostic artifacts remain retained:

- v1 freeze:
  `e7d3ba9a24f18be05f51188b90eb83fa6b7977393bba1751cd5d1bbf6d2cb4fc`;
- v1 report:
  `5956384a2b748c92b8bc7c40712d4a6f78de16e19ed43c686a0863e87bd05ac4`;
- v1 manifest:
  `3175b4be95f64a6fec9d08c2f116ad0ce355e770747882ea43bc5fb22cdf4d30`.

## Result-aware repair boundary

The v2 repair adds only a frozen mixed-type feature transformer:

- median imputation for numeric columns;
- most-frequent imputation and unknown-safe one-hot encoding for categorical
  columns;
- numeric scaling only where the original candidate requested it.

The immutable v1 runner remains a pinned dependency. The v2 wrapper verifies
its SHA-256 before use. `DevelopmentRepairLineage` additionally requires:

- a complete, exact-resume predecessor matrix;
- a content-valid predecessor freeze and report;
- confirmation still sealed;
- the same mixed-type failure across at least three mechanism families and all
  three repeated seeds;
- exact reuse of the prospective initialization and candidate order;
- no change to candidate definitions, policies, budgets, thresholds,
  randomization, survival rules, or the confirmation panel.

Relevant identities:

- reused initialization:
  `ed932c8622abe903e6bd5bfccfd81f9933d0116171881b3a316493b4d9955327`;
- repair lineage:
  `5fd59d9ef00ea924c3fb1f9b50385d07eabf961d960e0ac2a4fdd2b274662715`;
- mixed-type failure evidence:
  `e49a7c8aced7a37c27e9a64bef76f7c477072029e1b56cce944263d6bcf1a64e`;
- v2 runner:
  `6bffee04762d864a8719b650da105e917d825a5e9fc3cbbcb5876637d2e67126`;
- immutable v1 dependency:
  `f7db15037f401be87b9428346802a14707f0d4036e452b3551d492e226cb303c`.

A clean-interpreter probe on the failed task found seven categorical columns
and produced 20/20 finite predictions, including an injected unseen category.

## Development results

### Policy outcomes

| Policy | Successful tasks | Rate | Invalid assignments |
|---|---:|---:|---:|
| `one_shot` | 5/7 | 0.714 | 0 |
| `linear_self_loop` | 5/7 | 0.714 | 0 |
| `portfolio` | 5/7 | 0.714 | 0 |
| `portfolio_memory` | 6/7 | 0.857 | 0 |
| `ablation-certificate` | 1/7 | 0.143 | 0 |
| `ablation-diversity` | 6/7 | 0.857 | 0 |
| `ablation-memory` | 5/7 | 0.714 | 0 |
| `ablation-multi_fidelity` | 1/7 | 0.143 | 0 |
| `ablation-reviewer` | 0/7 | 0.000 | 21 |

All 21 evaluation failures are the intentional invalid-schema candidate
executed only when the reviewer gate is ablated. No main policy has an
artifact, evaluator, prediction-replay, memory, or budget failure. Maximum
observed assignment CPU was 23.5 seconds against 180 reserved seconds, and
maximum peak RSS was 282.614 MiB against 4,096 MiB.

### Frozen primary comparison

`portfolio_memory` minus `linear_self_loop`:

- task-level risk difference: `+0.142857` (`+1/7`);
- paired task-bootstrap 95% interval: `[0.000000, 0.428571]`;
- exact two-sided McNemar: `p=1.0`;
- favorable/tied/unfavorable tasks: `1/6/0`.

The point estimate satisfies the nonnegative development survival rule, but it
does not establish superiority. The exact test is uninformative at seven
development tasks by design; inferential power belongs to the untouched
60-task confirmation panel.

All ten secondary arm/ablation comparisons were handled as one Holm family.
None is significant after correction. The apparent losses from removing the
certificate, reviewer, or multi-fidelity component are therefore development
signals, not confirmed component effects.

### Low-to-high fidelity calibration

For `portfolio_memory`, aggregation is by independent task after taking the
median across the three repeated seeds:

| Pair | Tasks | Spearman | MAE |
|---|---:|---:|---:|
| F1 → F3 | 7 | 0.964286 | 0.028987 |
| F2 → F3 | 7 | 0.964286 | 0.021896 |

Both exceed the prospectively frozen minimum `0.20`.

### Survival conjunction

All five checks pass:

- at least four successful development tasks: pass (`6/7`);
- F1→F3 task-level calibration: pass;
- F2→F3 task-level calibration: pass;
- nonnegative primary task-risk difference: pass;
- zero main-policy integrity or budget failures: pass.

No alternative policy may be selected post hoc. The only allowed survivor is
the preregistered `portfolio_memory` policy.

## Reproducibility and Open Science evidence

Formal v2 identities:

- freeze:
  `1120bc27839eafefcf20e042e7b043e344c9d59cc3b2daa657a102c5ff264332`;
- report:
  `b767a0963d0c4f60a92cbc7c35b835918122028f90bff5bb6b73e43ccecd1123`;
- manifest:
  `e423e7cc3f82d083c8a0776f572a550da0cad06fd7b70b79b3d2f213fe71eb49`;
- schema bundle:
  `eeacc3189646a4bcc1bbba3436b2c73a2761963fdcc5a1f51e054cf15152b78e`.

The evidence root is
`runs/manual-live/task2635-development-search-v2/`.

Recursive `verify`, a second `run`, and a second `verify` preserved the report
and manifest hashes exactly. The opt-in live smoke passed. The final repository
gate passed 1,046 tests with 22 opt-in skips and 86% line coverage; repository
Ruff and Mypy over 166 source files passed.

The development-label audit records 14 development resource URLs, zero
confirmatory URLs, no redistributed raw payload, and
`confirmatory_payloads_downloaded=false`. LLM reviewer scores are not
scientific evidence. Public release and external submission remain false.

## Remaining publication blockers

Task 263.5 removes the “no real portfolio experiment” blocker. It does not
remove:

- independent confirmation of the primary task-level effect;
- confirmatory confidence interval and exact test;
- independently adjudicated null and component findings;
- final nearest-work/novelty review;
- claim-evidence/counterevidence graph and clean reproduction package;
- human authorship, license, venue, release, and submission approval.

Task 263.6 must execute the frozen `portfolio_memory` implementation once on
the untouched 60-task panel. It may yield a positive or negative endpoint. It
must not retune on that panel, substitute another arm, or return to development
after reveal.

## Related

- [[projects/ai_researcher_system/progress/task-263-4-2-clean-baseline-preregistration]]
- [[projects/ai_researcher_system/progress/task-263-4-1-open-objective-task-panel]]
- [[exploration/publishability-recovery-ai-scientist-2026]]
- [[projects/ai_researcher_system/index]]
