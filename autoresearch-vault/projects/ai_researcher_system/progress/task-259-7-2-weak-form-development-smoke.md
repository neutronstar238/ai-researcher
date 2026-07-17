---
entry_type: project_progress
zone: project
project_id: ai_researcher_system
title: "Task 259.7.2 weak-form development smoke"
tags:
  - competition
  - mdbench
  - weak-form
  - development-smoke
  - negative-evidence
---

# Task 259.7.2 - Weak-form Development Smoke

## Status

- Task: `259.7.2`
- Status: completed
- Completed at: 2026-07-18 00:35:41 +08:00
- Gate A decision: unchanged `negative_result`
- Gate B allowed: `false`
- Human interventions: `0`
- Access requests: `0`

## Implemented Boundary

The scientific container now executes the two frozen mechanisms from
[[projects/ai_researcher_system/progress/task-259-7-1-gate-a-recovery-preregistration|Task 259.7.1]]:
PySINDy v1.7.5 `WeakPDELibrary` projection and bootstrap support stability. The implementation uses
deterministic split-local weak domains, column-normalized STLSQ, fixed-support refitting, and a
strong-form pointwise test evaluation. No reference-only WSINDy code was copied.

The image build runs a deterministic synthetic ODE/PDE self-test. It recovered the oscillator
coefficients at approximately `+0.99999` and `-0.99999`, and recovered the synthetic transport
equation as `u_t=-0.99999u_x` with derivative NMSE below `1e-5`.

## Development Evidence

- Matrix hash: `9dba5411b3ae5244950d8f056008370510009a7b9ba1a1d2fbf60956230cd19e`
- Image: `autoresearch-mdbench-gate-a-recovery:c22b9243`
- Image ID: `sha256:29796ce06e675737a02b1864c277ed545b4a6fb9c3bce8db40245c9bdc8bf88c`
- Runner SHA-256: `c22b92437280aae635cbfadd1f8a349f9b49c11658553ffee184b411610942eb`
- Environment hash: `006f047a654fb33296cd849c27cf0f9774ebd0b809780aaca441ae0871b8f7f4`
- Final resumed report hash: `97be2954c4785cb79ffd4c4fa19fbc61a0f1bfb9da2aab3b061d27eddfa52756`
- Development results: `4/4` succeeded, `0` failed, `0` timed out; the unchanged rerun reused all four result hashes.

The first implementation smoke exposed an unnormalized weak-library scale defect. A second
development-only diagnostic isolated the cause: Ridge regularization and thresholding were being
applied directly to differently scaled integral columns. Column normalization corrected the clean
PDE result from a 14-term model with derivative NMSE `108.86` to the single equation
`u_t=-0.100002u_x` with derivative NMSE `1.27e-6`.

The SNR20 `advection1d` development control still selected the zero equation with derivative NMSE
approximately `1`. This result is retained as a weakness of the frozen mechanism, not hidden or
relabelled as success.

## Evidence Boundary And Next Action

Only recovery development cells were executed. The six sealed recovery unseen systems were not
executed or inspected during implementation or debugging. This task proves container execution,
finite metrics, causal hash binding, checkpoint reuse, and bounded failure persistence; it does not
prove the recovery hypothesis, pass Gate A, authorize Gate B, or support submission or award claims.

Task `259.7.3` may now execute and adjudicate the unchanged 252-cell matrix exactly once. If the
pre-registered confidence gate fails, the weak-form/support-stability family must close as a credible
negative result without tuning against revealed unseen systems.
