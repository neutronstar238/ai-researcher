---
backlinks:
- publication_audit_issue_task86_similarity_classification_cycle-20260613t030125z
created_at: '2026-06-13T03:16:54.445014Z'
entry_id: publication_audit_task86_similarity_classification_cycle-20260613t030125z
entry_type: review_note
keywords:
- publication-audit
- ccf-b
- fail
links: []
project_id: task86_similarity_classification
related_run_ids: []
related_task_ids:
- publication-audit
source_refs:
- runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/cycle-summary.json
- runs/manual-live/publication-audit-task86/publication-audit.json
- runs/manual-live/publication-audit-task86/publication-audit.md
tags:
- publication-audit
- fail
title: Publication audit cycle-20260613t030125z
updated_at: '2026-06-13T03:16:54.445014Z'
zone: project
---

# Publication Quality Audit

- Target: `CCF-B-level conference target`
- Verdict: `fail`
- Publishable: `false`
- Score: `0.523`
- Cycle summary: `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/cycle-summary.json`
- JSON: `runs/manual-live/publication-audit-task86/publication-audit.json`
- Vault review: `not written`
- Vault issue: `not written`

## Target Gates

- Minimum score: `0.82`
- Literature: `4` queries, `20` documents, `2` successful sources
- Similarity: `4` queries, `10` findings, `2` successful sources
- Data: at least `1000` validated test rows; real dataset required: `true`
- Experiment: baseline `True`, ablation `True`, statistical sanity `True`

## Checks

| Check | Status | Severity | Evidence | Message | Next action |
| --- | --- | --- | --- | --- | --- |
| `literature_query_breadth` | `fail` | `blocking` | `cycle_summary.literature.query_count` | Literature query breadth is 1; target requires at least 4. | Expand query variants from title, gap, methods, datasets, baselines, negative evidence, and vault context. |
| `literature_document_breadth` | `fail` | `blocking` | `cycle_summary.literature.document_count` | Retrieved normalized literature documents: 2; target requires at least 20. | Run broader ArXiv/Semantic Scholar searches and preserve every source-backed paper before novelty claims. |
| `literature_source_breadth` | `pass` | `blocking` | `cycle_summary.literature.fetches` | Successful literature sources: arxiv, openalex; target requires 2. | None |
| `literature_source_errors` | `fail` | `high` | `cycle_summary.literature.fetches` | Some literature sources failed: semantic_scholar: SourceRateLimitError: Semantic Scholar HTTP 429 rate limited; circuit open for 60.0s | Treat failed source coverage as a novelty-risk blocker until rerun with rate limits/API keys. |
| `similarity_query_breadth` | `fail` | `blocking` | `cycle_summary.similarity.fetches` | Similarity-check query breadth is 1; target requires at least 4. | Search candidate title, research gap, method/dataset terms, baselines, negative results, and vault context. |
| `similarity_finding_breadth` | `fail` | `blocking` | `cycle_summary.similarity.finding_count` | Similarity findings: 2; target requires at least 10. | Collect enough adjacent-work evidence before claiming novelty or cross-validation coverage. |
| `similarity_source_breadth` | `pass` | `blocking` | `cycle_summary.similarity.fetches` | Successful similarity-check sources: arxiv, openalex; target requires 2. | None |
| `similarity_source_errors` | `fail` | `high` | `cycle_summary.similarity.fetches` | Some similarity-check sources failed: semantic_scholar: CircuitBreakerOpenError: rate-limit circuit is open for 58.7s | Rerun cross-search after rate-limit cooldown/API-key setup; do not treat missing sources as negative evidence. |
| `similarity_classification_coverage` | `fail` | `high` | `cycle_summary.similarity.summary_path` | Similarity findings are all unclassified or unknown: unknown=2, classified=0. | Resolve unknown similarity classifications into direct_duplicate, adjacent_work, or another supported evidence-backed category before claiming novelty. |
| `similarity_duplicate_risk` | `pass` | `info` | `cycle_summary.similarity.summary_path` | No direct duplicate was detected in the current similarity metadata. | None |
| `script_data_verification` | `pass` | `blocking` | `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/run/run-record.json`, `E:/AIResearch/runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/run.py`, `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/data/pendigits_variance_calibrated_prototypes.csv`, `E:/AIResearch/runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/metrics.json` | Execution record confirms run.py existed, data hash matched the local data file, metrics were written, artifacts/logs existed, exit_code was 0, and validation passed. | None |
| `data_strength` | `pass` | `blocking` | `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/run/run-record.json` | Validated test rows: 3498; target requires at least 1000. | None |
| `dataset_realism` | `pass` | `info` | `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/run/run-record.json` | Dataset realism requirement is satisfied for this target. | None |
| `baseline_reproduction` | `pass` | `high` | `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/run/run-record.json` | Baseline reproduction evidence is present. | None |
| `ablation_coverage` | `pass` | `high` | `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/run/run-record.json` | Ablation evidence is present. | None |
| `statistical_sanity` | `pass` | `high` | `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/run/run-record.json` | Statistical sanity checks are present. | None |
| `method_innovation_evidence` | `pass` | `high` | `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/run/run-record.json` | File-backed method innovation evidence is present. | None |
| `method_effect_evidence` | `pass` | `high` | `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/run/run-record.json`, `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/artifacts/innovation_evidence.json` | Method candidate improved over baseline with recorded delta=0.045740. | None |
| `llm_evidence_review` | `fail` | `high` | `cycle_summary.review` | LLM evidence review status=skipped, verdict=missing, quality_score=0.000; target requires >= 0.85. | Run evidence-constrained LLM review and fix unsupported claims before publication audit. |
| `review_verdict_strength` | `fail` | `high` | `cycle_summary.review.verdict` | Reviewer verdict is `missing`, not publication-ready. | Treat fail/missing reviewer verdicts as blockers. |
| `manuscript_structure` | `pass` | `info` | `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/demo/pendigits-variance-calibrated-prototypes/report/report.md` | All required manuscript sections are present. | None |

## Interpretation

- `pass` means this audit did not find publication-readiness blockers for the configured target.
- `needs_revision` means the cycle is evidence-bearing but not ready for submission.
- `fail` means the system must not describe the output as CCF-B/Q3-publication-level.
