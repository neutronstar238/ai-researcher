# Task 95.1 Structured Similarity Queries

type: progress_note
project: ai_researcher_system
task: 95.1
date: 2026-06-13
timezone: Asia/Shanghai
status: completed
problem: P-20260613-030

## Summary

Project-start similarity search now prioritizes concise structured novelty-stress queries before long prose prompts.

Default top-four similarity queries now prefer:

- Candidate title.
- Method plus benchmark.
- Baseline plus benchmark.
- Adjacent-risk technique plus benchmark.

Long research-gap prose, negative-result search, and vault-context queries remain available as breadth/fallback queries when the query budget is larger.

## Why

The real baseline cycle showed that long paragraph-like academic search prompts can retrieve many weakly related records. The publication gate correctly rejected the cycle because every similarity finding remained `unknown`.

## Real Baseline Before Change

Command:

```powershell
poetry run airesearcher autopilot --demo pendigits_variance_calibrated_prototypes --max-queries 4 --max-results-per-source 10 --timeout-seconds 120 --output-dir runs\manual-live\autopilot-task95-real-cycle --vault runs\manual-live\task95-vault --cache runs\manual-live\task95-literature-cache --project-id task95_real_cycle --cycles 1
```

Result:

- `source_preflight`: `pass`.
- `review_status`: `passed`.
- `publication_audit`: `fail`.
- `evidence_gate`: `blocked`.
- Literature query breadth: `4/4`, document breadth: `71`.
- Similarity findings: `36`.
- Classified similarity findings: `0`.
- `similarity_classification_coverage`: `fail`.
- Semantic Scholar recorded HTTP 429/circuit-breaker errors.

## Real Verification After Change

Command:

```powershell
poetry run airesearcher autopilot --demo pendigits_variance_calibrated_prototypes --max-queries 4 --max-results-per-source 10 --timeout-seconds 120 --output-dir runs\manual-live\autopilot-task95-structured-queries --vault runs\manual-live\task95-structured-vault --cache runs\manual-live\task95-structured-literature-cache --project-id task95_structured_queries --cycles 1
```

Result:

- `source_preflight`: `pass`.
- `review_status`: `passed`.
- `publication_audit`: `fail`.
- `evidence_gate`: `blocked`.
- Similarity queries:
  - `variance-calibrated prototype classifiers for uci pendigits`
  - `diagonal variance-calibrated prototypes variance shrinkage uci pendigits`
  - `nearest centroid classifier z-score ablation uci pendigits`
  - `mahalanobis distance metric gaussian prototype classifiers uci pendigits`
- Similarity findings: `57`.
- Classified similarity findings: `1`.
- `similarity_classification_coverage`: `pass`.
- `similarity_classified_finding_breadth`: `fail`, because target requires at least `10` evidence-classified findings.
- Semantic Scholar still recorded HTTP 429/circuit-breaker errors.

## Interpretation

The search prompt quality improved, but the system still correctly refuses publication/release claims. This is the intended behavior: better retrieval and one classified prior-work signal are not enough for CCF-B/Q3-level novelty evidence.

## Follow-Up

- Improve evidence-backed classification for retrieved abstracts and metadata.
- Add more adjacent-work query templates without weakening unknown-finding handling.
- Configure Semantic Scholar API key/rate settings before treating source coverage as complete.
- Keep `similarity_classified_finding_breadth` strict; do not count raw findings as novelty proof.
