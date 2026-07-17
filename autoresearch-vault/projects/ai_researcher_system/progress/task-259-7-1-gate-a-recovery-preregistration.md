---
entry_type: project_progress
zone: project
project_id: ai_researcher_system
title: "Task 259.7.1 Gate A recovery preregistration"
tags:
  - competition
  - mdbench
  - negative-result-recovery
  - preregistration
---

# Task 259.7.1 - Gate A Recovery Preregistration

## Status

- Task: `259.7.1`
- Status: completed
- Completed at: 2026-07-17 23:54:17 +08:00
- Parent decision: `negative_result`
- Gate B allowed: `false`

## Parent Evidence

- Parent matrix hash: `77fd4376bff5fcffa4445da049071a8498dd76d274a2e3bc24686c52f3adaf04`
- Parent report hash: `3381083f1d1390eb18f54e29855eb6e2ecd5ace567e20babef56e48479e4cf99`
- Parent report: `runs/manual-live/task259-mdbench-official-v1/gate-a-v3/gate-a-adjudication.json`
- Boundary: the parent unseen systems and their revealed results cannot be used for recovery tuning.

## Recovery Hypothesis

Weak-form projection should reduce sensitivity to pointwise derivative noise, while bootstrap
support stability should reduce sparse-support variance across systems and fresh random seeds.
These are the only two mechanisms in this recovery candidate.

The hypothesis is falsified unless the candidate improves unseen noisy derivative NMSE by at
least 5% over the strongest frozen baseline and the system-level bootstrap 95% confidence lower
bound is greater than zero. Failure closes this mechanism family as another negative result.

## Frozen Matrix

- Recovery hash: `1331a21f1d49f8330433d1a8b05a49bdbf1028cab39b968b24a92ff89bb76079`
- Matrix hash: `9dba5411b3ae5244950d8f056008370510009a7b9ba1a1d2fbf60956230cd19e`
- Matrix cells: `252`
- Conditions: `clean`, `snr_20`
- Seeds: `13`, `29`, `43`
- Candidate: `weak_stability_sindy`
- Baselines: unchanged `sindy_or_pdefind`, `operon_gp`
- Artifacts: `runs/manual-live/task259-mdbench-recovery-v1/`

Recovery unseen systems are `chen-lee-attractor`, `lorenz-equations-complex-periodic`,
`apoptosis-model`, `binocular-rivalry-adaptation`, `heat_soil_uniform_1d_p1`, and `nls`.
None appears anywhere in the parent matrix. Every parent unseen system is excluded from the full
recovery matrix. Only parent-development `advection1d` and `burgers` are reused, and both remain
development controls.

## Source And License Boundary

- WENDy and weak-form latent-dynamics papers provide mechanism rationale.
- Ensemble-SINDy provides the support-stability rationale.
- PySINDy v1.7.5 commit `4c32d2603cbf1aa476efae72bc78436cb1e6fc75` is the only software dependency added by the contract; its MIT license hash is recorded.
- WSINDy ODE/PDE repositories are revision-pinned but have no detected license file. They are `reference_only`; no code may be copied or vendored.

## Evidence Boundary And Next Action

The contract was generated twice with identical hashes. No recovery experiment result has run,
so this note proves preregistration only—not candidate correctness, improvement, Gate A passage,
Qwen evidence, RealPDEBench readiness, submission readiness, or award potential.

Next, task `259.7.2` may implement and smoke the candidate on development systems only. Recovery
unseen-test cells must remain unopened until the implementation and development checks are frozen.
