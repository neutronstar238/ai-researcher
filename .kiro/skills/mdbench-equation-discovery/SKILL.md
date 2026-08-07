---
name: mdbench-equation-discovery
description: Domain knowledge for running sparse-regression equation discovery on the MDBench ODE/PDE panel inside the pinned container. Use when working with MDBench systems, the pysindy baseline, or the ODE/PDE stratification. Pairs with the domain-agnostic preregistered-lineage-methodology skill.
---

# MDBench equation discovery

This is the DOMAIN half. The general rules about preregistration, budgets, promotion
gates, and honest negatives live in `preregistered-lineage-methodology` and must not be
duplicated here. Everything below is specific to this panel, this baseline, and this
container, and none of it belongs in a methodology module.

## Panel shape

14 systems: 10 ODE and 4 PDE. Conditions `clean` and `snr_20`. Seeds `101, 211, 307`.

The PDE stratum is small enough that it dominates any aggregate. Two systems cannot
produce a pinned baseline loss at all under the frozen configuration grid:

* **`heat_laser`** — pysindy `1.7.5` `FiniteDifference` needs `d + order` samples along
  the differentiated axis. The `z` axis physically has 3 samples, and `d=2` with default
  `order=2` needs 4, so the forward-boundary stencil indexes element 3 of a 3-element
  vector. `d=1` on the same axis succeeds. Not a transport defect.
* **`heat_soil_uniform_2d_p1`** — time spacing is `300` and `mean|du/dt|` is `1.96e-3`,
  so the unthresholded solution has `max|coef| = 1.72e-4`. The frozen thresholds `0.01`
  and `0.1` are two to three orders of magnitude above that, so STLSQ zeroes every
  coefficient. `Estimator.to_str()` then emits `'u0_t = '`, and `str_to_sympy` turns its
  own parse failure into `None`, which raises `SympifyError: None`.

Excluding both leaves a **2-system PDE stratum**, which means any reported PDE median is
the mean of two numbers. Say so whenever you report it.

**Never give a system with an all-zero baseline paired handling.** Scoring a candidate
against a zero-null manufactures a positive effect from a library limitation. Make this
unrepresentable in the model rather than discouraged in prose.

## The pinned container

`autoresearch-mdbench:task260`, with `numpy 1.26.4`, `sympy 1.13.3`, `pysindy 1.7.5`.

The host Poetry environment deliberately does NOT carry the scientific stack. Four
harness tests fail locally because of this and that is by design, not a defect. Verify
with `docker run --rm autoresearch-mdbench:task260 python -c "import numpy, pysindy"`
before concluding anything about a numeric failure.

## Failure signatures seen in real runs

Deterministic and identical across seeds means a code defect, not a data-dependent one.

| Signature | Meaning |
| --- | --- |
| `IndexError: index N is out of bounds for axis 1 with size N` | Off-by-one on a grid axis in the candidate's PDE handling |
| `ContractError: equation factor names an unknown state field` | Candidate's reported equation references a field the evaluator lacks for that system |
| `ContractError: equation factor contains an unsupported derivative axis` | Candidate emitted a derivative along an axis the contract does not carry |
| `ContractError: equation repeats an identical term support` | Duplicate basis terms |
| `container wall-time budget exceeded` | Performance, not a crash. Common when a candidate builds a large PDE library |
| `equation returned 0 terms` | Sparse selection collapsed to the empty set on that system's scaling |
| `TypeError: can't multiply sequence by non-int` | Python-level defect; static review cannot catch it because it checks structure, not types |

Static review checks structure only: no lambda, no `dir`/`locals`, no dynamic
execution, required interface present. It will pass code that crashes at runtime. Only
execution evidence catches that.

## Empirical results across four lineages

All four reproduced `72/72` baseline cells after the exclusion bound correctly, against
`72/84` before it. Zero-term failures reached 0 once the contract required non-empty
support.

| Lineage | Selected | Cells | ODE median | Overall | Wins |
| --- | --- | --- | --- | --- | --- |
| task2693 | official-02-r2 | 11/72 | -26.57 | -27.78 | 0/12 |
| task2694 | official-08-r2 | 66/72 | -0.0553 | -0.2829 | 5/12 |
| task2695 | official-05-r2 | 60/72 | -0.0452 | -0.6753 | 5/12 |
| task2696 | official-07-r2 | **72/72** | -0.6557 | -0.8449 | 3/12 |

Read this carefully, because the naive reading is wrong. The better ODE medians in
`task2694` and `task2695` were NOT failure-loss artifacts: both fully executed all 10
ODE systems with zero capped cells. The difference is a **capability trade-off**. Those
candidates could not run PDE at all, while `task2696`'s candidate runs both strata and
is a weaker ODE fitter. Per system, it turns `driven-pendulum-quadratic-damping` from
`-7.79` into `+0.93` and improves `population-growth-naive` from `-5.29` to `-1.03`,
while losing `binocular-rivalry-model` from `+2.36` to `-1.22`.

**Different candidates win different systems and none dominates.** Three independent
candidates fully executing the same 10 ODE systems gave medians `-0.0553`, `-0.0452`,
`-0.6557` with wins `5, 5, 3`. That is a stable null, not a trend to push further.

## Practical guidance

* Carry each round's REAL failure reasons into the next lineage's plan, derived from
  retained cells rather than hand-written. The loop measurably improves on defects it
  is told about: two candidates reached `10/10` in a pilot after this, against a
  previous best of `8/10`.
* Expect a repaired defect to reveal a different one. Budget for several lineages.
* The PDE stratum is where candidates fail. Cover it in the smoke wave explicitly, or a
  candidate will pass on ODE and then fail every PDE unit.
* A candidate reporting NMSE exactly `1.0` on every unit is usually predicting a
  constant, not fitting. Check term counts and the shuffled-target control.
