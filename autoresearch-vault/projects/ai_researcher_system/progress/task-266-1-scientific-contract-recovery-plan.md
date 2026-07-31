---
title: Task 266.1 result-blind scientific-contract recovery plan
date: 2026-08-01
status: completed-result-blind-plan-confirmation-sealed
task: "266.1"
tags:
  - autonomous-research
  - competition
  - mdbench
  - equation-discovery
  - fit-freeze-predict
  - evidence-first
  - negative-result-recovery
---

# Task 266.1 result-blind scientific-contract recovery plan

## Outcome

Task 266.1 froze the next scientific contract before observing any new official
development outcome. The formal plan hash is
`764f851f58302e5507ad6f5c3da2f0d6457f91f5eb90e4515c74e3a9e16095a3`.
It immutably binds the Task 265.3 autonomous negative package
`8f42cbb684b7b02eee5d4e9287e26f3edaebd49b7215f603d274450a58994576`
and does not mutate its source, adapter, cells, summaries, decision, or absent
receipt.

New official development results, candidate answers, model interactions,
confirmation identity reads, and confirmation results remain `0/0/0/0/0`.
Only the synthetic Harness implementation in Task 266.2 is authorized.
Official development execution, confirmation, manuscript generation, public
release, and submission remain false.

## Frozen scientific contract

The contract is `fit once → freeze concrete learned equations → predict many`:

1. a train-only fit request contains states, coordinates, shapes, and field
   names but no validation/test target;
2. fit returns a serializable, hash-bound artifact with concrete terms, numeric
   coefficients, scaling, diagnostics, and training-data identity;
3. every single-slice query contains only state and coordinates and may read
   only the frozen artifact;
4. the Harness independently evaluates the equations and requires exact
   agreement with returned numeric predictions.

The schema registry hash is
`ff23cdc7b1ab53362cb00c1258b538a42d52615fd5ab897cef4aece167d17903`.
Free coefficients, fit-after-query, target derivatives in query payloads,
query-only finite differences, constant/zero-null equivalence, absent training
dependence, equation/prediction disagreement, unsupported shapes, and artifact
tamper all fail closed.

## Analytic sentinels

Six deterministic fixtures cover a two-field linear ODE, 1D advection, 1D
diffusion, 2D advection-diffusion, 3D heat, and 1D two-field diffusion. Every
fixture includes primary and alternate training contexts, a fixed derivative
shuffle, three target-free one-slice queries, analytic derivatives, equations,
and thresholds. Sentinel registry hash:
`59f21f4f9b37a25daebf91be4f220c1de2a68c055b9c8cb634271d07299afe92`.

Required clean gates include prediction NMSE `≤1e-6`, exact term-support F1,
coefficient relative error `≤0.05`, equation/prediction maximum absolute delta
`≤1e-9`, at least fivefold shuffle degradation, at least `0.5` improvement
over the zero null, one fit, at least three predictions, and zero fits during
prediction.

## Source and baseline evidence

Nine live primary snapshots bind the MDBench paper and fixed implementation
interface/license, the PySINDy paper/license/WeakPDELibrary source, and
PyOperon v0.5.0 implementation/license/PyPI metadata. Source registry hash:
`595bf406a608282a13a669008dd3b42a5b3fd7dbbf0fa2b6a987c038eeec238a`.

The domain policy routes ODE systems to Operon and PDE systems to official
MDBench PDE-FIND/PySINDy. A required baseline failure blocks a receipt; it can
never create candidate advantage. Baseline registry hash:
`667d450931bb5dbb099bb01ba75b3e6e55d9acb3583315ce79311b8bee2548fa`.

The exact offline probe ran in pinned image
`sha256:6c8928e967cc4ff2995626c90ef57771df603028ddd6e17dbc60894ffa017c78`
with Python 3.9.23 and no network or official-artifact read. Probe hash:
`d46f4fe9bc83e41a3c2baa3fd06fa58ef3428d744fad8292f3dc9f493c453553`.

| Probe | Synthetic NMSE | Result |
|---|---:|---|
| Operon ODE | `0.0005562015925350986` | passed |
| PDE-FIND 2D | `1.3980779783672217e-31` | passed |
| PDE-FIND 3D | `2.034461901247889e-32` | passed |

These probes establish executable installed implementations and dimensional
fit/predict support. They do not substitute for exact spatial-term recovery,
which belongs to the independent sentinel Harness.

## Budget and inference boundary

The frozen search allows eight initial and at most twelve total candidates,
two generations, four mechanism cycles, 96 pilot candidate cells, 32 matched
mechanism cells, 252 full candidate cells, and 84 domain-baseline cells. The
candidate maximum is 380 cells and the all-in maximum is 464. Every cell has a
300-second, two-CPU, 4096-MB cap.

The paired effect is
`log(baseline_nmse_clipped / candidate_nmse_clipped)`. Condition and seed cells
are repeated measures within a system; the independent unit is the system.
Receipt requires the overall system median to exceed the original five-percent
gate, a positive exploratory bootstrap lower bound, positive ODE and PDE
stratum medians, all scientific-contract gates, and success of every required
candidate and domain-baseline full cell.

The panel has ten ODE but only four PDE systems. The exact power audit records
that even if each PDE system has a `0.9` probability of a positive direction,
the probability that all four are positive is only `0.6561`. The PDE stratum is
therefore a directional qualification gate, not a standalone PDE significance
claim. Development intervals remain exploratory selection evidence and cannot
establish publication significance.

## Next gate

Task 266.2 must implement the provider-neutral model-source Harness and pass all
synthetic recovery, null, leakage, shape, resource, security, and tamper tests
without reading a new official score. Only then may Task 266.3 execute the
bounded development recovery. Confirmation remains one-use and sealed.

## Related

- [[task-265-3-autonomous-development-negative]]
- [[../../../exploration/ophis-autonomous-research-mechanism-audit-2026]]
- [[../../../exploration/graph-harness-loop-open-science-2026]]
