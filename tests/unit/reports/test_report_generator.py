from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.evidence import ClaimNode, ClaimStatus, EvidenceCoverageError, EvidenceGraph
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
        "## Abstract",
        "## Introduction",
        "## Related Work",
        "## Question",
        "## Literature Summary",
        "## Hypothesis",
        "## Method",
        "## Experiment Design",
        "## Experiments",
        "## Run Metadata",
        "## Reproducibility",
        "## Results",
        "## Validation",
        "## Limitations",
        "## Conclusion",
        "## References",
        "## Next Steps",
    ]:
        assert heading in markdown
    assert "`accuracy` = `0.9` ([evidence `evidence_accuracy`](metrics.json))" in markdown
    assert "`loss` = `0.1` ([evidence `evidence_loss`](metrics.json))" in markdown
    assert "- Run ID: `run_001`" in markdown
    assert "- Command: `python experiment.py --config config.yaml`" in markdown
    assert "- Python version: `3.13.13`" in markdown
    assert "- Dependency lock: `poetry.lock present`" in markdown
    assert "- Commit SHA: `abc123`" in markdown
    assert "- Config hash: `config-hash`" in markdown
    assert "- Data hash: `data-hash`" in markdown
    assert "- Validation report: `validation/validation-report.json`" in markdown
    assert "- Evidence `evidence_accuracy`: `metrics.json`" in markdown
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
        reproduction_command=context.reproduction_command,
        python_version=context.python_version,
        dependency_lock_status=context.dependency_lock_status,
        limitations=context.limitations,
        next_steps=context.next_steps,
    )

    with pytest.raises(EvidenceBindingError, match="loss"):
        generate_markdown_report(context)


def test_generate_markdown_report_blocks_core_claim_without_evidence() -> None:
    context = _context()
    graph = EvidenceGraph()
    graph.add_claim(
        ClaimNode(
            id="claim_001",
            statement="The demo method improves accuracy over baseline.",
        )
    )
    context = replace(
        context,
        evidence_graph=graph,
        core_claim_ids=["claim_001"],
    )

    with pytest.raises(EvidenceCoverageError, match="claim_001"):
        generate_markdown_report(context)

    assert graph.claims["claim_001"].status is ClaimStatus.BLOCKED


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
        reproduction_command="python experiment.py --config config.yaml",
        python_version="3.13.13",
        dependency_lock_status="poetry.lock present",
        limitations=["Synthetic demo only."],
        next_steps=["Run on a real benchmark."],
    )
