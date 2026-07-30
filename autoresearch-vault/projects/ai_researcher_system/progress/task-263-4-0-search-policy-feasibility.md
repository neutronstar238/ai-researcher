---
title: Task 263.4.0 search-policy feasibility diagnosis
date: 2026-07-30
status: completed
task: "263.4.0"
tags:
  - autoresearch
  - reproduction
  - exact-power
  - benchmark-audit
  - negative-result
  - open-science
---

# Task 263.4.0 Search-policy Feasibility Diagnosis

## Decision

The selected search-policy track remains scientifically interesting, but its
original 12-task confirmatory panel is not admissible for a publication-grade
causal claim. Baseline execution stopped before any result was generated.

Status: `blocked_reproduction_diagnosis`.

This decision is a pre-result design diagnosis. It is not a negative treatment
effect, a baseline failure, or a scientific result.

## Why the original panel cannot run

The audit used the official
[ScienceAgentBench repository](https://github.com/OSU-NLP-Group/ScienceAgentBench),
[verified metadata](https://huggingface.co/datasets/osunlp/ScienceAgentBench),
and [paper](https://arxiv.org/abs/2410.05080).

- The verified metadata has 102 rows. The frozen CSV SHA-256 is
  `7f490f17f721a9c7e9415d3608a1a37d1a5315a26862cf556e3096ac4062face`.
- Development IDs remain `1`, `2`, `4`, and `5`; confirmatory IDs remain
  `61` through `72`.
- The confirmatory panel contains exactly 9 image outputs and 3 structured
  CSV/NPY outputs. The official README says visualization evaluation uses
  GPT-4o.
- The public GitHub tree includes the generic Docker/evaluation harness but
  not the 16 named task-specific evaluator programs.
- The Hugging Face tree includes metadata CSV/README/verified Parquet but no
  `benchmark_verified.zip`. The README's SharePoint link did not return an
  anonymously downloadable artifact in the bounded live probe.
- The selected IDs avoid the repository's six special-license IDs, but task
  license clearance alone cannot compensate for missing data, evaluator
  source, objective scoring, or power.

No gold program, gold result, evaluation result, confirmation value, or model
review entered the artifact.

## Endpoint-specific exact power

The tournament's `0.822982` normal approximation was a preliminary generic
sensitivity calculation. It does not match the frozen primary endpoint:
paired binary objective task success for `portfolio_memory` versus
`linear_self_loop`.

The replacement is prospective two-sided exact McNemar/sign-test enumeration:

| p(favorable) | p(unfavorable) | SESOI | n=12 power | n for 80% |
|---:|---:|---:|---:|---:|
| 0.25 | 0.00 | 0.25 | 0.054402 | 31 |
| 0.30 | 0.05 | 0.25 | 0.080152 | 45 |
| 0.35 | 0.10 | 0.25 | 0.095619 | 60 |

The design therefore requires at least 60 independent confirmatory research
tasks under the frozen sensitivity set. Seeds and trajectories remain
within-task repeated measurements and never increase the independent sample
size. Observed power is prohibited.

## Implemented gate

`search_policy_study.py` adds six strict, content-addressed contracts:

1. per-task output/evaluator/data/license audit;
2. exact paired-binary power scenario;
3. complete or explicitly blocked baseline binding;
4. conjunctive feasibility report;
5. four-arm, five-ablation preregistration that is impossible before clean
   baseline reproduction;
6. artifact manifest plus deterministic JSON Schemas.

No weighted score or reviewer can override a missing hard gate. The frozen
arms are one-shot, linear self-loop, portfolio, and portfolio+memory. The
frozen ablations are certificate, diversity, multi-fidelity, reviewer, and
memory.

## Live and integrity evidence

- Final opt-in live smoke passed in 39.02 seconds.
- Report hash:
  `7c4d06eb82eabb250cf1b509242480bf27f079f65eaec6fbe564593c54b4aa3c`.
- Manifest hash:
  `1d18b358d9b537ad083095d9897b542d6a1a8870b3b7393e6d017a41a1582a43`.
- Local ignored artifact root:
  `runs/manual-live/task2634-search-policy-diagnosis-v1/`.
- Novelty search: `false`.
- Confirmatory results revealed: `false`.
- Public release / external submission: `false` / `false`.

## Optimized next path

Task 263.4.1 must build a new panel with at least 60 independent tasks, at
least two benchmark/task families, anonymously downloadable data, pinned
task-specific deterministic evaluators, clear data/code/task licenses, and
bounded compute. Randomization must block by benchmark and domain.

Potential sources such as non-visual ScienceAgentBench candidates,
[autoresearch-sab-tasks](https://huggingface.co/datasets/osunlp/autoresearch-sab-tasks),
[ResearchGym](https://github.com/Anikethh/ResearchGym), and
[MLGym](https://github.com/facebookresearch/MLGym) are inputs to an inventory,
not pre-approved units. The inspected `autoresearch-sab-tasks` archive exposes
only a handful of task families, so archive entries or repeated files cannot
be inflated into 60 independent tasks.

Only after the rebuilt panel passes live data/evaluator/license/compute and
exact-power gates may Task 263.4.2 reproduce the strong baseline in a clean
environment and freeze the causal preregistration.

## Related

- [[projects/ai_researcher_system/progress/task-263-3-live-opportunity-tournament]]
- [[projects/ai_researcher_system/progress/task-263-2-research-portfolio-contracts]]
- [[exploration/publishability-recovery-ai-scientist-2026]]
- [[projects/ai_researcher_system/index]]
