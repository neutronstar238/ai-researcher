---
title: Task 260 Route A hard decision
entry_id: task260-route-a-decision
entry_type: project_progress
project_id: autoresearch-ccfb
created_at: 2026-07-23T15:22:10Z
updated_at: 2026-07-23T15:22:10Z
tags:
  - autonomous-campaign
  - route-a
  - negative-result
  - route-b-pivot
related_run_ids:
  - task260-autonomous-ccfb-v1
links:
  - task260-autonomous-ccfb-v1-round-001
  - task260-autonomous-ccfb-v1-round-002
---

# Task 260 Route A hard decision

Campaign `task260-autonomous-ccfb-v1` completed two genuinely new, parent-linked experimental
rounds with zero research-decision human interventions. Both mechanisms passed the frozen
development screen and failed the frozen unseen contribution gate.

| Round | Mechanism | Development median improvement | Unseen system-level bootstrap 95% CI | Decision |
|---|---|---:|---:|---|
| 001 | noise-conditioned derivative + coefficient ensemble | 0.779785 | [-3.053723, 0.953866] | negative result |
| 002 | smoothing-spline derivative + group-sparse projection | 0.672083 | [-2.157336, 0.921594] | negative result |

The campaign lineage hash is
`72fc5080f1058a095086f8f2c1a6135868d775ce8e1320d112b8618ac3944158`.
The full local export contains 1,289 manifest-listed files and passed SHA-256 integrity
reproduction. External submission remains blocked.

## Binding next action

Do not tune either mechanism on its revealed holdout, replace a revealed system, reopen the
weak-form/support-stability family, or lower the confidence gate. Proceed to task `260.4`: the
frozen autonomous-research systems-paper comparison across 4 UCI and 6 MDBench tasks.

## Evidence

- [[task260-autonomous-ccfb-v1-round-001]]
- [[task260-autonomous-ccfb-v1-round-002]]
- `runs/manual-live/task260-autonomous-ccfb-v1/campaign-manifest.json`
- `outputs/task260-autonomous-ccfb-v1/task260-autonomous-ccfb-v1/deliverables/index.md`
