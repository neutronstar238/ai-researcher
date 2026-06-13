# Task 75.1 Method Innovation Gate

- Date: 2026-06-13 +08:00
- Task: `75.1`
- Status: completed
- Problem log: `P-20260613-013` and `P-20260613-004` in root `Problem.md`

## Result

Publication audit now includes `method_innovation_evidence` for CCF-B and Q3-journal targets.

The gate requires both:

- structured task metadata describing a proposed mechanism or method contribution
- an existing artifact whose path indicates innovation, mechanism, or contribution evidence

Baseline-only cycles are not considered publishable just because they have real data, ablation, statistics, broad literature search, and paper-style sections.

## Why This Matters

Earlier gates proved that the system could execute experiments, rerun them, compile a PDF, and check source breadth. That still leaves a core research-quality risk: a baseline benchmark can look like a paper while contributing no new method.

This gate keeps the system honest. It does not prove a method is truly novel by itself, but it prevents the weakest failure mode: packaging a baseline-only result as a publication-level contribution.

## Real Verification

A real audit used:

```bash
poetry run airesearcher publication-audit runs\manual-live\autopilot-reproduction-gate-task74\cycle-20260613T010218Z\cycle-summary.json --target ccf-b --output-dir runs\manual-live\publication-audit-task75 --vault runs\manual-live\task75-vault --project-id task75_innovation_gate --no-fail-on-not-publishable
```

Result:

| Evidence | Result |
| --- | --- |
| Audit JSON | `runs/manual-live/publication-audit-task75/publication-audit.json` |
| Verdict | `fail` |
| Publishable | `false` |
| Score | `0.2742` |
| Method gate | `method_innovation_evidence` failed |
| Message | `File-backed method innovation evidence is missing or baseline-only.` |
| Next action | Record proposed mechanism/contribution metadata and preserve innovation/mechanism artifact |

Focused tests also verify that a paper-style real benchmark baseline remains `needs_revision`, while a fixture with contribution metadata plus `artifacts/innovation_evidence.json` can pass the innovation gate.

## Follow-Up

The next research-producing task should generate a real method candidate and an honest innovation evidence artifact only if the code actually implements a mechanism beyond a baseline. Literature cross-checking still needs to evaluate whether that mechanism is new relative to retrieved adjacent work.
