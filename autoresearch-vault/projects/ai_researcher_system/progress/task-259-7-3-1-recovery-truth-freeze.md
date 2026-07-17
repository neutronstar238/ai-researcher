---
entry_type: project_progress
zone: project
project_id: ai_researcher_system
title: "Task 259.7.3.1 recovery truth freeze"
tags:
  - competition
  - mdbench
  - preregistration
  - truth-registry
  - sealed-evaluation
---

# Task 259.7.3.1 - Recovery Truth Freeze

## Status

- Task: `259.7.3.1`
- Status: completed
- Completed at: 2026-07-18 00:50:31 +08:00
- Recovery unseen results opened: `false`
- Gate A decision: unchanged `negative_result`
- Gate B allowed: `false`

## Frozen Scoring Inputs

Before executing any recovery unseen cell, the Gate A adjudicator was extended to cover all 14
systems in the recovery matrix. ODE supports come from pinned
`scripts/strogatz_ode.py`; NLS comes from the pinned README; the exact zero-source uniform-soil heat
equation is additionally bound to `scripts/fenics_heat_soil_uniform.py` SHA-256
`f5c9ebd62048de1a62afaf3b57d3ce87954c86564a86185116852b67ae829fdc`.

The adjudicator now resolves the single generated candidate and required seeds from the immutable
matrix. This preserves the parent `stability_sindy`/11-23-37 behavior while allowing the recovery
`weak_stability_sindy`/13-29-43 contract without a post-result code change.

- Truth registry hash: `38d549143207b177b6a2c9430e5b68cdd89e4dd80b41eaf04d082f5b255b04dd`
- Recovery analysis-policy hash: `ef60d9a245a7a0937b99361d71ed31d2c79116b25ff45098d9f39c554d9cbd9f`
- Adjudicator SHA-256: `b2037a1c765aa8274205da85c59c35958405abbea81ee5498a515ef8796b7d31`
- Registered official and recovery systems: `26`

## Verification And Boundary

Fifteen focused adjudicator tests passed. Twelve new exact-source equation cases each score structure
F1 `1.0`, including rational/activation ODEs and the two recovery PDEs. Ruff and focused Mypy also
passed. The source hashes were recomputed inside the pinned, network-disabled MDBench image.

No full recovery execution report or recovery unseen result existed when these hashes were frozen.
Task `259.7.3.2` must use this committed scoring policy unchanged, drain all 252 cells, retain every
failure, and close as a negative result if any preregistered mandatory gate fails.
