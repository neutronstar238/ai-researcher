# Task 74.1 Reproduction Rerun Gate

- Date: 2026-06-13 +08:00
- Task: `74.1`
- Status: completed
- Problem log: `P-20260613-012` and `P-20260613-004` in root `Problem.md`

## Result

Each `autopilot` or `serve` cycle now runs a second command-line reproduction check after the first experiment run and before paper-level release gating.

The reproduction check writes:

- `reproduction-check/reproduction-check.json`
- `reproduction-check/reproduction-check.md`
- a fresh rerun `run/run-record.json`
- a fresh rerun `validation/validation-report.json`

The cycle summary stores this as `reproduction_check`. The physical evidence gate treats the rerun as blocking evidence: release is not allowed unless the rerun exits with code `0` and the fresh run record plus validation report exist.

## Why This Matters

The earlier gate proved that a cycle had evidence artifacts from the first run. It did not prove that the experiment could be invoked again from the CLI after the cycle completed. This task narrows the gap between "the agent says the script ran" and "the system has a second executable run with file-backed evidence."

This is a lightweight SCALE-style governance rule. It adds a concrete test/review gate without adopting a full heavyweight lifecycle for every small change.

## Real Verification

A real local single-cycle run used:

```bash
poetry run airesearcher autopilot --vault runs\manual-live\task74-vault --cache .cache\literature --output-dir runs\manual-live\autopilot-reproduction-gate-task74 --state runs\manual-live\autopilot-reproduction-gate-task74\scheduler-state.json --project-id task74_reproduction_gate --demo tabular_baseline --max-queries 1 --max-results-per-source 1 --timeout-seconds 30 --no-review
```

Result:

| Evidence | Result |
| --- | --- |
| Cycle summary | `runs/manual-live/autopilot-reproduction-gate-task74/cycle-20260613T010218Z/cycle-summary.json` |
| Reproduction status | `passed` |
| Reproduction exit code | `0` |
| Reproduction run records | `1` |
| Reproduction validation reports | `1` |
| Reproduction report | `runs/manual-live/autopilot-reproduction-gate-task74/cycle-20260613T010218Z/reproduction-check/reproduction-check.json` exists |
| Evidence gate reproduction check | `reproduction_rerun_gate` passed |
| Paper build status | `compiled` |
| Evidence gate verdict | `blocked` |
| Release allowed | `false` |

The blocked release verdict is expected: the run used `--no-review` and the toy baseline is not publication-ready. The important task result is that the stricter release gate now sees and verifies the second command-line rerun.

## Follow-Up

This improves reproducibility proof, not research novelty. The next quality work remains stronger methods, broader live novelty checks, more stable Semantic Scholar access, and publication-level experiments on real benchmarks.
