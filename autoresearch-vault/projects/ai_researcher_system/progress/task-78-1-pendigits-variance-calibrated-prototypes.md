# Task 78.1 - Pendigits Variance-Calibrated Prototypes

## Summary

Task `78.1` added an opt-in real public benchmark method-candidate demo:
`pendigits_variance_calibrated_prototypes`.

The demo uses the official UCI Pendigits train/test split, compares a
nearest-centroid baseline, a z-score centroid ablation, and a diagonal
variance-calibrated prototype classifier. It writes
`artifacts/innovation_evidence.json` with a numeric baseline-vs-candidate
effect delta so `method_effect_evidence` can verify empirical-gain support.

## Evidence

- Real run-demo output: `runs/manual-live/pendigits-variance-task78/pendigits-variance-calibrated-prototypes/`
- Metrics: `runs/manual-live/pendigits-variance-task78/pendigits-variance-calibrated-prototypes/metrics.json`
- Innovation evidence: `runs/manual-live/pendigits-variance-task78/pendigits-variance-calibrated-prototypes/artifacts/innovation_evidence.json`
- Autopilot cycle: `runs/manual-live/autopilot-variance-task78/cycle-20260613T015034Z/cycle-summary.json`
- Publication audit: `runs/manual-live/autopilot-variance-task78/cycle-20260613T015034Z/publication-audit.json`

## Result

- Candidate accuracy: `0.823327615780446`
- Baseline accuracy: `0.7775871926815323`
- Delta vs baseline: `0.045740423098913685`
- Z-score centroid accuracy: `0.7850200114351058`
- Delta vs z-score centroid: `0.038307604345340196`
- Test rows: `3498`
- Reproduction check: `passed`

The method candidate has a real positive effect on the official Pendigits test
split. This is a useful candidate signal, but it is not yet a publication-ready
novelty claim.

## Gates

- `run-demo`: passed with validation status `passed`.
- Reproduction rerun inside autopilot: passed.
- `script_data_verification`: passed.
- `method_innovation_evidence`: passed.
- `method_effect_evidence`: passed with recorded delta `0.045740`.
- Publication audit: failed because the verification run intentionally used
  smoke-sized literature/similarity breadth and skipped LLM review.
- Evidence gate: blocked, as expected.

## Follow-Up

- Keep [[P-20260613-016]] open until a full-width, review-enabled cycle passes.
- Cross-check diagonal variance calibration against Gaussian discriminant,
  nearest-centroid, prototype calibration, and handwritten digit literature.
- If novelty remains weak, treat this as a strong baseline/control and search
  for a more distinctive mechanism.
