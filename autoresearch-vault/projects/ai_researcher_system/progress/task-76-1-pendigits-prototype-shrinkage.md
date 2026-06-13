# Task 76.1 - Pendigits Prototype Shrinkage Candidate

## Summary

Task `76.1` added an opt-in real public benchmark method-candidate demo:
`pendigits_prototype_shrinkage`.

The demo uses the official UCI Pendigits train/test split, evaluates a
nearest-centroid full-feature baseline, a first-8-feature ablation, and a
class-prototype shrinkage candidate. It writes a file-backed
`artifacts/innovation_evidence.json` so publication audit can verify that a
method mechanism was implemented rather than inferred from prose.

## Evidence

- Real run-demo output: `runs/manual-live/pendigits-shrinkage-task76/pendigits-prototype-shrinkage/`
- Metrics: `runs/manual-live/pendigits-shrinkage-task76/pendigits-prototype-shrinkage/metrics.json`
- Innovation evidence: `runs/manual-live/pendigits-shrinkage-task76/pendigits-prototype-shrinkage/artifacts/innovation_evidence.json`
- Autopilot cycle: `runs/manual-live/autopilot-shrinkage-task76/cycle-20260613T012402Z/cycle-summary.json`
- Publication audit: `runs/manual-live/autopilot-shrinkage-task76/cycle-20260613T012402Z/publication-audit.json`

## Result

- Candidate accuracy: `0.7764436821040595`
- Baseline accuracy: `0.7775871926815323`
- Delta vs baseline: `-0.0011435105774728616`
- First-8-feature ablation accuracy: `0.6240708976558034`
- Prototype shift mean L2: `8.904184619456233`

The method candidate underperformed the baseline in this run. This is valid
negative evidence. It must not be described as an empirical gain or as a
publishable result.

## Gates

- `run-demo`: passed with validation status `passed`.
- Reproduction rerun inside autopilot: passed.
- `method_innovation_evidence`: passed because a real file-backed method
  artifact exists.
- Publication audit: failed because the smoke run used only one query, retrieved
  too few documents/findings, Semantic Scholar returned 429/circuit errors, and
  LLM review was skipped.
- Evidence gate: blocked, as expected, because review and publication audit did
  not pass.

## Follow-Up

- Treat this as a negative-result issue linked to [[P-20260613-014]].
- Search adjacent prototype-calibration and nearest-centroid literature before
  claiming novelty.
- Explore stronger method candidates on real public datasets, with ablations,
  reruns, and cross-literature duplicate checks.
