---
title: Task 263.4.1 open objective task panel
date: 2026-07-30
status: completed
task: "263.4.1"
tags:
  - autoresearch
  - benchmark
  - exact-power
  - objective-evaluation
  - open-science
  - preregistration
---

# Task 263.4.1 Open Objective Task Panel

## Decision

The original ScienceAgentBench panel remains inadmissible, but a new narrow
panel now passes the pre-result data, evaluator, license, independence, compute,
and exact-power gates.

Status: `ready_for_clean_baseline`.

This status authorizes only Task 263.4.2 clean-room baseline reproduction. It
does not mean that the baseline reproduced, the search policy works, the result
is novel, or the system can generally automate science.

## Construct boundary

The panel tests one bounded claim:

> Does a budget-matched portfolio-plus-memory search policy improve objective
> task success over a linear self-loop on tabular machine-learning research
> tasks?

The independent unit is one unique OpenML task/data/source group. Seeds and
trajectories are repeated measurements inside a task. The result must not be
generalized to wet-lab science, unrestricted scientific discovery, arbitrary
software engineering, or publication acceptance.

## Outcome-blind inventory and selection

Selection used only official task/data metadata and the frozen seed
`task-263.4.1-open-objective-panel-v1`. No OpenML run, score, prediction,
task-specific study outcome, or confirmatory payload entered ranking.

| Source suite | Initial tasks | Admitted units | Development | Confirmatory |
|---|---:|---:|---:|---:|
| OpenML-CC18 classification | 72 | 45 | 4 | 41 |
| OpenML-CTR23 regression | 35 | 22 | 3 | 19 |
| Total | 107 | 67 | 7 | 60 |

For CC18, admission required an official metadata path to a UCI source covered
by UCI's CC BY 4.0 policy. Multiple representations from the same Multiple
Features source were one independence group. For CTR23, the registry rejected
ten `Public` labels as legally ambiguous, one noncommercial license, one
version-unspecified `CC BY`, and one of the red/white wine pair as a correlated
source duplicate. All 40 exclusions retain machine-readable reasons.

The registry contains 67 unique OpenML data IDs and 67 unique source groups.
Confirmation contains 41 classification and 19 regression tasks across
multiple domain blocks. Randomization remains blocked by benchmark and domain.

Registry hash:
`6aa348b2014905d582b979dd35183fe9fa722abcbd41a8de9f65c720bafe780e`.

## Objective harness

Each unit binds:

- OpenML suite, task ID, data ID, target, and resampling procedure;
- anonymous data endpoint and MD5;
- official fixed-split endpoint;
- source/data/task/code license evidence;
- instances, features, and a CPU-only dense-memory envelope;
- a task-specific binding to the local deterministic evaluator;
- structured predictions, no model judge, and no observed study result.

Classification uses balanced accuracy; regression uses R². Binary task success
also requires artifact, replay, and budget validity, but its task-specific
numeric threshold is intentionally not frozen until Task 263.4.2 reproduces the
strong baseline.

Evaluator source hash:
`dfa9c2012d11fa9989ad80ce41818f8e4dc0b691d44047157b2311de0a96191e`.

Evaluator Apache-2.0 license hash:
`5cb668e80870451ec5797defddfc2bccdfb40e4c49ff4ebf205e984b9be4898f`.

## Exact power

The frozen two-sided exact McNemar sensitivity remains:

| p(favorable) | p(unfavorable) | n | Exact power | Minimum n for 80% |
|---:|---:|---:|---:|---:|
| 0.25 | 0.00 | 60 | 0.999044 | 31 |
| 0.30 | 0.05 | 60 | 0.918666 | 45 |
| 0.35 | 0.10 | 60 | 0.801422 | 60 |

The conservative scenario therefore passes at exactly 60 independent
confirmatory tasks. No observed power is reported.

## Live evidence

The opt-in official-source smoke:

- checked both active suite inventories and all 67 selected task/data metadata,
  license labels, source references, MD5 values, targets, resampling procedures,
  and compute qualities;
- verified the OpenML benchmark documentation, OpenML research-use terms, and
  UCI CC BY 4.0 policy;
- downloaded only development representatives
  `openml-cc18-task-11` and `openml-ctr23-task-361247`;
- matched their data MD5 values, parsed official split ARFF files, replayed the
  balanced-accuracy/R² evaluators exactly, and stayed inside the compute bounds;
- did not download any of the 60 confirmatory payloads and did not query public
  OpenML runs.

The smoke passed in 49.60 seconds.

- Report hash:
  `ab4435f059676bcfd11387495947527455734eddf239f77b0e92a1c434e8a3ac`.
- Manifest hash:
  `2224147ea065249e10e6ad69642f91611376b0f84ec983b99b0d122028bc4efa`.
- Four-schema bundle hash:
  `20ba62ede420aba6738ffac3f61d3fa4acdac6f792075bab075a85c7c2125cc4`.
- Local ignored artifact root:
  `runs/manual-live/task26341-open-objective-panel-v1/`.

## Remaining publication blockers

Task 263.4.2 must still reproduce the selected strong baseline in a clean
environment and freeze task-specific success thresholds, four policy arms,
five ablations, budgets, randomization, stopping rules, and sealed-runner
permissions before any development search. Public benchmark familiarity and
tabular-only construct validity remain limitations to report, not facts that a
larger task count can erase.

Novelty search, confirmatory execution, public release, and external submission
remain false.

## Related

- [[projects/ai_researcher_system/progress/task-263-4-0-search-policy-feasibility]]
- [[projects/ai_researcher_system/progress/task-263-3-live-opportunity-tournament]]
- [[exploration/publishability-recovery-ai-scientist-2026]]
- [[projects/ai_researcher_system/index]]
