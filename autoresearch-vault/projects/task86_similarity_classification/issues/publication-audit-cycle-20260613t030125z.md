---
backlinks: []
created_at: '2026-06-13T03:16:54.445014Z'
entry_id: publication_audit_issue_task86_similarity_classification_cycle-20260613t030125z
entry_type: issue_note
keywords:
- publication-audit
- quality-gate
- ccf-b
links:
- publication_audit_task86_similarity_classification_cycle-20260613t030125z
project_id: task86_similarity_classification
related_run_ids: []
related_task_ids:
- publication-audit
source_refs:
- runs/manual-live/publication-audit-task86/publication-audit.json
- runs/manual-live/publication-audit-task86/publication-audit.md
tags:
- open
- publication-audit
- fail
title: Publication audit blockers cycle-20260613t030125z
updated_at: '2026-06-13T03:16:54.445014Z'
zone: project
---

# Publication audit blockers for cycle-20260613T030125Z

- Review note: [[publication_audit_task86_similarity_classification_cycle-20260613t030125z]]
- Target: `CCF-B-level conference target`
- Verdict: `fail`
- Score: `0.523`
- Issue fingerprint: `publication-audit:cycle-20260613T030125Z`

## Failed Checks

### literature_query_breadth

- Severity: `blocking`
- Evidence refs: `cycle_summary.literature.query_count`
- Message: Literature query breadth is 1; target requires at least 4.
- Next action: Expand query variants from title, gap, methods, datasets, baselines, negative evidence, and vault context.

### literature_document_breadth

- Severity: `blocking`
- Evidence refs: `cycle_summary.literature.document_count`
- Message: Retrieved normalized literature documents: 2; target requires at least 20.
- Next action: Run broader ArXiv/Semantic Scholar searches and preserve every source-backed paper before novelty claims.

### literature_source_errors

- Severity: `high`
- Evidence refs: `cycle_summary.literature.fetches`
- Message: Some literature sources failed: semantic_scholar: SourceRateLimitError: Semantic Scholar HTTP 429 rate limited; circuit open for 60.0s
- Next action: Treat failed source coverage as a novelty-risk blocker until rerun with rate limits/API keys.

### similarity_query_breadth

- Severity: `blocking`
- Evidence refs: `cycle_summary.similarity.fetches`
- Message: Similarity-check query breadth is 1; target requires at least 4.
- Next action: Search candidate title, research gap, method/dataset terms, baselines, negative results, and vault context.

### similarity_finding_breadth

- Severity: `blocking`
- Evidence refs: `cycle_summary.similarity.finding_count`
- Message: Similarity findings: 2; target requires at least 10.
- Next action: Collect enough adjacent-work evidence before claiming novelty or cross-validation coverage.

### similarity_source_errors

- Severity: `high`
- Evidence refs: `cycle_summary.similarity.fetches`
- Message: Some similarity-check sources failed: semantic_scholar: CircuitBreakerOpenError: rate-limit circuit is open for 58.7s
- Next action: Rerun cross-search after rate-limit cooldown/API-key setup; do not treat missing sources as negative evidence.

### similarity_classification_coverage

- Severity: `high`
- Evidence refs: `cycle_summary.similarity.summary_path`
- Message: Similarity findings are all unclassified or unknown: unknown=2, classified=0.
- Next action: Resolve unknown similarity classifications into direct_duplicate, adjacent_work, or another supported evidence-backed category before claiming novelty.

### llm_evidence_review

- Severity: `high`
- Evidence refs: `cycle_summary.review`
- Message: LLM evidence review status=skipped, verdict=missing, quality_score=0.000; target requires >= 0.85.
- Next action: Run evidence-constrained LLM review and fix unsupported claims before publication audit.

### review_verdict_strength

- Severity: `high`
- Evidence refs: `cycle_summary.review.verdict`
- Message: Reviewer verdict is `missing`, not publication-ready.
- Next action: Treat fail/missing reviewer verdicts as blockers.
