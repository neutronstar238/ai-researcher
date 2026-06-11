"""Bind validated metrics to evidence edges."""

from __future__ import annotations

from autoresearch.experiments.validation import ValidationReport
from autoresearch.schemas import EvidenceEdge, ResultBundle, ValidationStatus


class EvidenceBindingError(RuntimeError):
    """Raised when metrics are used without validated evidence binding."""


VALID_EVIDENCE_STATUSES = {ValidationStatus.PASSED, ValidationStatus.WARNING}


def bind_metrics_to_evidence(
    bundle: ResultBundle,
    report: ValidationReport,
    *,
    claim_id: str,
    source_artifact: str = "metrics.json",
) -> list[EvidenceEdge]:
    """Convert validated result metrics into evidence edges."""

    if report.status not in VALID_EVIDENCE_STATUSES:
        msg = f"cannot bind metrics from validation status {report.status.value}"
        raise EvidenceBindingError(msg)

    return [
        EvidenceEdge(
            claim_id=claim_id,
            evidence_ref=f"{bundle.run_id}:{metric_name}",
            source_artifact=source_artifact,
            source_run_id=bundle.run_id,
            metric_name=metric_name,
            supports_claim=True,
            validation_status=report.status,
        )
        for metric_name in sorted(bundle.metrics)
    ]


def require_evidence_for_metrics(
    bundle: ResultBundle,
    evidence_edges: list[EvidenceEdge],
    *,
    metric_names: list[str] | None = None,
) -> None:
    """Block claim/report generation if metrics lack validated evidence edges."""

    required_metrics = set(metric_names or bundle.metrics)
    bound_metrics = {
        edge.metric_name
        for edge in evidence_edges
        if edge.source_run_id == bundle.run_id
        and edge.metric_name is not None
        and edge.validation_status in VALID_EVIDENCE_STATUSES
    }
    missing = sorted(required_metrics - bound_metrics)
    if missing:
        msg = "metrics lack validated evidence binding: " + ", ".join(missing)
        raise EvidenceBindingError(msg)
