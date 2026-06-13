# Task 77.1 - Method-Effect Publication Gate

## Summary

Task `77.1` added a publication-audit check named
`method_effect_evidence`.

The prior `method_innovation_evidence` gate proved that a method mechanism and
artifact existed. It did not prove that the method candidate improved over the
baseline. This task closes that gap by reading file-backed innovation artifacts
and requiring a positive baseline-vs-candidate effect delta for CCF-B/Q3-style
empirical-gain claims.

## Gate Behavior

- `mvp-demo`: passes this check because method-effect claims are not required.
- `ccf-b` and `q3-journal`: read innovation/mechanism/contribution artifacts.
- Positive delta: pass.
- Zero or negative delta: fail and preserve the result as negative evidence.
- Missing delta: fail and request explicit candidate/baseline metrics or a
  numeric delta such as `accuracy_delta_vs_baseline`.

## Real Verification

Real audit command:

```powershell
poetry run airesearcher publication-audit runs\manual-live\autopilot-shrinkage-task76\cycle-20260613T012402Z\cycle-summary.json --target ccf-b --output-dir runs\manual-live\publication-audit-task77 --vault runs\manual-live\task77-vault --project-id task77_method_effect_gate --no-fail-on-not-publishable
```

Observed checks:

- `method_innovation_evidence`: `pass`
- `method_effect_evidence`: `fail`
- Message: `Method candidate underperformed the baseline with recorded delta=-0.001144.`
- Verdict: `fail`
- Publishable: `false`

## Why It Matters

This is the lightweight SCALE-style lesson applied to research quality: the
agent cannot rely on prompt self-discipline to avoid overclaiming. A physical
gate parses the actual evidence file and blocks the publication claim.

## Follow-Up

- Keep [[P-20260613-014]] open as a real negative-result research issue.
- Add a separate target only if the project later wants to publish negative
  results under explicit negative-result criteria.
- Continue searching for a stronger method candidate with real benchmark
  evidence and broad literature cross-checks.
