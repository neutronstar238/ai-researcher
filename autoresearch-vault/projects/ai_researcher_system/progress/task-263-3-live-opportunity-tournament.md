---
title: Task 263.3 live opportunity tournament
date: 2026-07-29
status: completed
task: "263.3"
tags:
  - autoresearch
  - opportunity-gate
  - replication
  - power
  - open-science
---

# Task 263.3 Live Opportunity Tournament

## Decision

The tournament compared three research tracks without a weighted score, an LLM
override, or a hard-coded winner. It allowed the valid outcome that no track
would pass.

| Track | Admitted | Hard blockers | Next state |
|---|---:|---|---|
| `track.search-policy-causality` | yes | none at track-selection stage | Task 263.4 clean-room baseline reproduction only |
| `track.neural-operator-replication` | no | `baseline_smoke_passed`, `compute_feasible` | Retain as a negative opportunity |
| `track.sequential-falsification` | no | `baseline_smoke_passed`, `license_clear` | Retain as a negative opportunity |

No track entered novelty search. Confirmatory evidence remained sealed, and
public release and external submission remained unauthorized.

## Why only search-policy causality advanced

The live run reached all four primary nearest-work sources, the official
ScienceAgentBench repository, dataset metadata, and license. Its local baseline
smoke revalidated the immutable Task 260 system artifact with 210 completed
cells and a passing gate. The verified ScienceAgentBench metadata reports 102
records under CC BY 4.0 and the repository is MIT licensed.

The prospective design reserves development IDs `1`, `2`, `4`, and `5` and
confirmation IDs `61` through `72`. Dataset records with special-license IDs
`3`, `32`, `46`, `53`, `54`, and `84` are excluded. Task 263.4 must still prove
that the selected tasks have non-visual deterministic evaluators, that their
complete data and reuse rights are available, and that the strong baseline can
be reproduced in a clean environment.

## Why the other tracks stopped

The neural-operator track reached its four primary sources and the released
AI-SC MIT repository. The release describes a full campaign of roughly two days
on an RTX 4080-class GPU, while its preflight expects CUDA/PyTorch and 16 GiB.
The audited host exposes an NVIDIA GeForce RTX 5060 Laptop GPU with 8151 MiB;
the executable preflight therefore failed and compute feasibility was false.
No cloud GPU was rented.

The sequential-falsification track reached the peer-reviewed POPPER paper,
DiscoveryBench, Safe Testing, and the public POPPER repository. GitHub metadata
reported no SPDX license and the repository tree exposed no recognizable
license file. The tournament therefore did not execute the code. Publication
status and low cost cannot compensate for an unresolved software-reuse license.

## Power interpretation

Every track froze 12 independent confirmation units. Under each track's
prospective minimum-effect and unit-standard-deviation assumptions, the
two-sided normal approximation gives power `0.822982`. This is a design
sensitivity calculation, not observed power, empirical assurance, novelty, or
a publishable contribution. Task 263.4 must review the variance assumption
before preregistration.

## Live and integrity evidence

- Opt-in live command: `$env:AUTORESEARCH_OPPORTUNITY_TOURNAMENT_LIVE='1'; poetry run python -m pytest tests/smoke/test_opportunity_tournament_live.py -q --no-cov`
- Live result: 1 passed in 239.04 seconds; 11/11 primary literature URLs and
  9/9 repository/data/license endpoints reached; the 210-cell local baseline
  assertion passed.
- Report hash: `de4769b74098650a1ed7a7f92fdd853459f468d5a35e4b6d152f0169779bf0ff`
- Manifest hash: `db810365f362de9fb06d541a7db1fc1634c1bed06d0f5b5b446e8b01a76ca932`
- JSON file SHA-256: `8b00ac9d9adf0115908c79a3239081dd5d5e15364b895f74f867e9399371cbf8`
- Markdown file SHA-256: `773ea6d7e8c0f527cd9c16dc0b907eb1db5c826b6fcaf3aad04d1fdc13e099f3`
- Eight-schema bundle hash: `5609a30f5d4c9900aa8e500bcb61f4f222e7e3de553a9c81ca996239cfffe5d0`
- Local artifact root: `runs/manual-live/task263-opportunity-tournament-v1/`

The local artifact root is intentionally ignored run output; this Vault note
and the task/agent logs retain the reviewed decisions and content hashes.

## Next action

Task 263.4 may operate only on `track.search-policy-causality`. It must perform
an independent clean-room baseline reproduction and freeze a budget-matched
causal comparison before reading development outcomes. If baseline,
evaluator, data/license, split, variance, or power evidence fails, convert the
track to a reproduction diagnosis and do not start novelty search.

## Related

- [[exploration/publishability-recovery-ai-scientist-2026]]
- [[projects/ai_researcher_system/progress/task-263-2-research-portfolio-contracts]]
- [[projects/ai_researcher_system/index]]
