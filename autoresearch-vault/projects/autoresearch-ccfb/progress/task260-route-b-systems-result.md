---
title: Task 260 Route B systems result
entry_id: task260-route-b-systems-result
entry_type: project_progress
project_id: autoresearch-ccfb
created_at: 2026-07-23T15:59:00Z
updated_at: 2026-07-23T15:59:00Z
tags:
  - autonomous-campaign
  - route-b
  - systems-paper
  - contribution-gate
related_run_ids:
  - task260-autonomous-systems-v1
links:
  - task260-route-a-decision
---

# Task 260 Route B systems result

The frozen Route B benchmark completed 210 primary cells and an exact deterministic
reproduction for every cell.

| Mode | Task success | Negative-result recovery | Exact reproduction | Unsupported claims |
|---|---:|---:|---:|---:|
| one-shot | 0.20 | 0.00 | 1.00 | 9 |
| execute-once | 0.50 | 0.00 | 1.00 | 6 |
| full loop | 1.00 | 0.625 | 1.00 | 0 |
| no Vault | 0.70 | 0.25 | 1.00 | 0 |
| no failure feedback | 0.50 | 0.00 | 1.00 | 6 |
| no preregistration | 0.00 | 0.00 | 1.00 | 0 |
| no evidence gate | 0.80 | 0.375 | 1.00 | 6 |

The full-loop paired task-success gain over execute-once is `0.50`; the frozen
20,000-resample bootstrap 95% CI is `[0.333333, 0.666667]`. Research-decision human
interventions and external API cost are both zero.

- Preregistration hash:
  `db4f372081be8ffb146a6acb133cdf7626618e4f94aae31aa1a4805b7d9e2da2`
- Result hash:
  `5f69cac379409d1abf5cd682682f54d76d181dc7aaf45c021f525ac50a5830cb`
- Gate hash:
  `1257ba5b721748539cd3846dd7f0df78237614f98fec417fda48b4f0b5b2e6a7`

## Evidence boundary

Four UCI sources were freshly executed. Six MDBench tasks replay already revealed real
traces for system-behaviour evaluation only; they are not new method holdouts. The internal
systems gate passed, but independent paper reproduction and review remain task `260.5`.
External submission is not authorized.

## Local evidence

- `runs/manual-live/task260-autonomous-systems-v1/preregistration.json`
- `runs/manual-live/task260-autonomous-systems-v1/systems-research-report.md`
- `runs/manual-live/task260-autonomous-systems-v1/contribution-gate.json`
- `runs/manual-live/task260-autonomous-systems-v1/evidence-map.json`
