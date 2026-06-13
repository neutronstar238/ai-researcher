# Task 94.1 Review Artifact Binding

type: progress_note
project: ai_researcher_system
task: 94.1
date: 2026-06-13
timezone: Asia/Shanghai
status: completed

## Summary

Standalone `llm-review.json` artifacts can now be used by `publication-audit` and `evidence-gate` only when they physically bind to the audited cycle.

The binding gate checks:

- Review subject hash or path matches `cycle_summary.demo.report_path`.
- Review evidence bundle covers `cycle_summary.demo.validation_json_path`.
- Review evidence bundle covers `cycle_summary.demo.evidence_map_path`.
- A passing review from another cycle fails `review_artifact_binding`.

This keeps post-hoc review useful for historical cycles while preventing review substitution.

## Real Verification

Publication audit command:

```powershell
poetry run airesearcher publication-audit runs\manual-live\autopilot-atomic-source-state-task84\cycle-20260613T030125Z\cycle-summary.json --review-json runs\manual-live\llm-review-task91-with-run-record.json --target ccf-b --output-dir runs\manual-live\publication-audit-task94-review-binding --vault runs\manual-live\task94-audit-vault --project-id task94_review_binding --no-fail-on-not-publishable
```

Result:

- Exit code: 0 with `--no-fail-on-not-publishable`.
- `publication_audit`: `fail`.
- `publishable`: `false`.
- `score`: `0.597`.
- `llm_evidence_review`: `pass`.
- `review_verdict_strength`: `pass`.
- `review_artifact_binding`: `pass`, `subject_match=true`, `covered_required_evidence=2/2`.

Evidence gate command:

```powershell
poetry run airesearcher evidence-gate runs\manual-live\autopilot-atomic-source-state-task84\cycle-20260613T030125Z\cycle-summary.json --review-json runs\manual-live\llm-review-task91-with-run-record.json --publication-audit runs\manual-live\publication-audit-task94-review-binding\publication-audit.json --paper-build-json runs\manual-live\autopilot-atomic-source-state-task84\cycle-20260613T030125Z\paper-build\paper-build.json --output-dir runs\manual-live\evidence-gate-task94-review-binding --vault runs\manual-live\task94-evidence-vault --project-id task94_review_binding --no-fail-on-blocked
```

Result:

- Exit code: 0 with `--no-fail-on-blocked`.
- `evidence_gate`: `blocked`.
- `release_allowed`: `false`.
- `review_gate`: `pass`.
- `review_artifact`: `pass`.
- `review_artifact_binding`: `pass`, `subject_match=true`, `covered_required_evidence=2/2`.
- Remaining release blocker: `publication_release_gate`, because the publication audit is still not publishable.

## Remaining Quality Blockers

The real historical cycle still fails CCF-B/Q3-level publication readiness for evidence breadth and novelty coverage:

- `literature_query_breadth`
- `literature_document_breadth`
- `literature_source_errors`
- `similarity_query_breadth`
- `similarity_finding_breadth`
- `similarity_source_errors`
- `similarity_classified_finding_breadth`
- `similarity_classification_coverage`

## Follow-Up

The next useful self-loop tasks should improve real online literature breadth, Semantic Scholar/OpenAlex cooldown recovery, and evidence-backed similarity classifications. Do not weaken the publication gate to make the existing cycle pass.
