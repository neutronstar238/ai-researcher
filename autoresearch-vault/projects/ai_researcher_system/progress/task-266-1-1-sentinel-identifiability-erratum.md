---
title: Task 266.1.1 sentinel-identifiability erratum
date: 2026-08-01
status: completed-result-blind-erratum-confirmation-sealed
task: "266.1.1"
tags:
  - autonomous-research
  - competition
  - mdbench
  - equation-discovery
  - identifiability
  - experimental-design
  - evidence-first
---

# Task 266.1.1 sentinel-identifiability erratum

## Outcome

A candidate-neutral pre-implementation audit found that one frozen synthetic
question could not support its intended term-recovery claim. The original 2D
advection-diffusion fixture used only equal x/y wave-number pairs. Therefore
`u_xx = u_yy` over its complete training matrix, although the expected equation
named only `u_yy`.

The original Task 266.1 plan remains immutable at
`764f851f58302e5507ad6f5c3da2f0d6457f91f5eb90e4515c74e3a9e16095a3`.
This erratum is an additive overlay with hash
`4ce5c07ea5fc6af1269a77ae94c582e20891c57236c106ec0e09fee81b38fd07`.
It changes no official panel, baseline, budget, estimand, threshold,
confirmation commitment, or candidate method.

## Exact diagnosis

The offline NumPy probe constructs a generic feature universe containing an
intercept, every state field, and first/second derivatives on every spatial
axis. For each expected target it checks null-space participation, the best
target reconstruction after deleting each active term, exact-support
coefficient replay, residual NMSE, and condition number.

| 2D fixture | Active-null component | Leave-`u_yy`-out NMSE | Verdict |
|---|---:|---:|---|
| original equal wave numbers | `0.7071067811865479` | `6.961005703984873e-30` | non-identifiable |
| corrected independent wave numbers | `0` | `0.045592207027804796` | identifiable |

The original failure is exact, not a numerical tolerance effect: deleting the
named diffusion term leaves an equivalent second-derivative column. The other
five original fixtures pass the same audit.

## Minimal correction

Only `pde-advection-diffusion-2d` changes. Its modal stimulus now uses
`(kx,ky)=(1,1),(2,1),(1,2),(3,2)`, which varies x and y curvature
independently. The speed and diffusivity coefficients, expected equations,
coordinate axes, training/query times, tensor shape, derivative shuffle,
alternate-training contract, and every threshold remain unchanged.

The corrected 2D fixture hash is
`ba4ff906a1e30c3942b6aed40f05e3786dd57a0b579cf0e868d264f8f9c4fc8a`;
its parent hash was
`5deec747a99f413a6753878c512a477bfd3e4cb3fb7d55d6bc98b0b399b53a2e`.
All other five fixture hashes are byte-identical to Task 266.1.

## Evidence and boundary

- probe hash:
  `77835000bd5df2f836cc739345f017b868cdce5bb333f9d54f424fcbfe9bc2a3`;
- corrected registry hash:
  `25085c7803aca04cd4b9ef3c4f317cd03539150d944ef84460744e4895353231`;
- exact probe runner hash:
  `c8d5fcc03cfc8011844983d6be2aed42cf4bdeef688dc6bf591bb47211ac3e2a`;
- pinned image ID:
  `sha256:6c8928e967cc4ff2995626c90ef57771df603028ddd6e17dbc60894ffa017c78`;
- network use and official artifact reads: `false / 0`;
- new official results, candidates, model interactions, confirmation identity
  reads, and confirmation results: `0/0/0/0/0`.

This correction makes the future synthetic gate fair; it is not evidence that
any candidate works or that any competition effect is significant. Only Task
266.2 synthetic Harness implementation is authorized.

## Related

- [[task-266-1-scientific-contract-recovery-plan]]
- [[task-265-3-autonomous-development-negative]]
- [[../../../exploration/ophis-autonomous-research-mechanism-audit-2026]]
