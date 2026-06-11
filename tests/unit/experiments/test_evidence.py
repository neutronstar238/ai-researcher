import pytest

from autoresearch.experiments import (
    EvidenceBindingError,
    ValidationReport,
    bind_metrics_to_evidence,
    require_evidence_for_metrics,
)
from autoresearch.schemas import EvidenceEdge, ResultBundle, ValidationStatus


def test_bind_metrics_to_evidence_creates_edges_for_validated_metrics() -> None:
    bundle = ResultBundle(run_id="run_001", metrics={"loss": 0.1, "accuracy": 0.9})
    report = _report(ValidationStatus.PASSED)

    edges = bind_metrics_to_evidence(
        bundle,
        report,
        claim_id="claim_001",
        source_artifact="metrics.json",
    )

    assert [edge.metric_name for edge in edges] == ["accuracy", "loss"]
    assert {edge.claim_id for edge in edges} == {"claim_001"}
    assert {edge.source_run_id for edge in edges} == {"run_001"}
    assert {edge.validation_status for edge in edges} == {ValidationStatus.PASSED}
    assert edges[0].evidence_ref == "run_001:accuracy"


def test_bind_metrics_to_evidence_rejects_failed_validation() -> None:
    bundle = ResultBundle(run_id="run_001", metrics={"accuracy": 0.9})

    with pytest.raises(EvidenceBindingError, match="cannot bind"):
        bind_metrics_to_evidence(
            bundle,
            _report(ValidationStatus.FAILED),
            claim_id="claim_001",
        )


def test_require_evidence_for_metrics_blocks_unbound_metrics() -> None:
    bundle = ResultBundle(run_id="run_001", metrics={"accuracy": 0.9, "loss": 0.1})
    edges = [
        EvidenceEdge(
            claim_id="claim_001",
            evidence_ref="run_001:accuracy",
            source_artifact="metrics.json",
            source_run_id="run_001",
            metric_name="accuracy",
            validation_status=ValidationStatus.PASSED,
        )
    ]

    with pytest.raises(EvidenceBindingError, match="loss"):
        require_evidence_for_metrics(bundle, edges)


def test_require_evidence_for_metrics_allows_warning_edges() -> None:
    bundle = ResultBundle(run_id="run_001", metrics={"accuracy": 0.9})
    edges = bind_metrics_to_evidence(
        bundle,
        _report(ValidationStatus.WARNING),
        claim_id="claim_001",
    )

    require_evidence_for_metrics(bundle, edges)


def _report(status: ValidationStatus) -> ValidationReport:
    return ValidationReport(
        run_id="run_001",
        status=status,
        issues=(),
        json_path="validation/validation-report.json",
        markdown_path="validation/validation-report.md",
    )
