from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.experiments import EvidenceBindingError, ValidationReport
from autoresearch.reports import ReportContext, generate_markdown_report
from autoresearch.schemas import (
    EvidenceEdge,
    ExecutionRun,
    ExecutionStatus,
    ResultBundle,
    ValidationStatus,
)


def test_generate_markdown_report_contains_required_sections_and_evidence_links(
    tmp_path: Path,
) -> None:
    context = _context()
    output_path = tmp_path / "paper" / "report.md"

    markdown = generate_markdown_report(context, output_path=output_path)

    for heading in [
        "## Question",
        "## Literature Summary",
        "## Hypothesis",
        "## Experiment Design",
        "## Run Metadata",
        "## Results",
        "## Validation",
        "## Limitations",
        "## Next Steps",
    ]:
        assert heading in markdown
    assert "`accuracy` = `0.9` ([evidence `evidence_accuracy`](metrics.json))" in markdown
    assert "`loss` = `0.1` ([evidence `evidence_loss`](metrics.json))" in markdown
    assert "- Run ID: `run_001`" in markdown
    assert output_path.read_text(encoding="utf-8") == markdown


def test_generate_markdown_report_blocks_unbound_quantitative_metrics() -> None:
    context = _context()
    context = ReportContext(
        title=context.title,
        question=context.question,
        literature_summary=context.literature_summary,
        hypothesis=context.hypothesis,
        experiment_design=context.experiment_design,
        run=context.run,
        results=context.results,
        validation=context.validation,
        evidence_edges=context.evidence_edges[:1],
        limitations=context.limitations,
        next_steps=context.next_steps,
    )

    with pytest.raises(EvidenceBindingError, match="loss"):
        generate_markdown_report(context)


def _context() -> ReportContext:
    run = ExecutionRun(
        id="run_001",
        project_id="project-001",
        task_id="task-001",
        status=ExecutionStatus.SUCCESS,
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        commit_sha="abc123",
        config_hash="config-hash",
        data_hash="data-hash",
    )
    results = ResultBundle(
        run_id="run_001",
        metrics={"accuracy": 0.9, "loss": 0.1},
        artifacts=["metrics.json"],
        validation_status=ValidationStatus.PASSED,
    )
    validation = ValidationReport(
        run_id="run_001",
        status=ValidationStatus.PASSED,
        issues=(),
        json_path="validation/validation-report.json",
        markdown_path="validation/validation-report.md",
    )
    evidence_edges = [
        EvidenceEdge(
            id="evidence_accuracy",
            claim_id="claim_001",
            evidence_ref="run_001:accuracy",
            source_artifact="metrics.json",
            source_run_id="run_001",
            metric_name="accuracy",
            validation_status=ValidationStatus.PASSED,
        ),
        EvidenceEdge(
            id="evidence_loss",
            claim_id="claim_001",
            evidence_ref="run_001:loss",
            source_artifact="metrics.json",
            source_run_id="run_001",
            metric_name="loss",
            validation_status=ValidationStatus.PASSED,
        ),
    ]
    return ReportContext(
        title="Demo Research Report",
        question="Can the demo method improve the metric?",
        literature_summary="Prior work suggests a small deterministic baseline is enough.",
        hypothesis="The demo method improves accuracy over baseline.",
        experiment_design="Run the generated MVP experiment and collect metrics.",
        run=run,
        results=results,
        validation=validation,
        evidence_edges=evidence_edges,
        limitations=["Synthetic demo only."],
        next_steps=["Run on a real benchmark."],
    )
