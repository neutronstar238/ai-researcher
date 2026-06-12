"""System metric computation for local monitoring snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autoresearch.observability.audit import AuditEvent, AuditEventType


@dataclass(frozen=True)
class SystemMetricsInput:
    """Inputs used to compute a local system metric snapshot."""

    runs: tuple[Any, ...] = ()
    validation_reports: tuple[Any, ...] = ()
    citations: tuple[Any, ...] = ()
    evidence_graph: Any | None = None
    audit_events: tuple[AuditEvent, ...] = ()


@dataclass(frozen=True)
class SystemMetricSnapshot:
    """Computed monitoring metrics and supporting counts."""

    task_success_rate: float
    experiment_reproduction_rate: float
    validator_rejection_rate: float
    avg_cost_per_success: float
    avg_human_interventions: float
    agent_loop_depth: float
    rollback_count: int
    citation_error_rate: float
    evidence_coverage: float
    total_tasks: int
    successful_tasks: int
    total_runs: int
    reproduction_runs: int
    successful_reproduction_runs: int
    validation_report_count: int
    rejected_validation_report_count: int
    total_citations: int
    blocked_citations: int
    total_claims: int
    covered_claims: int
    total_cost: float
    human_intervention_count: int

    def to_dict(self) -> dict[str, float | int]:
        """Return a JSON-friendly metric payload."""

        return {
            "task_success_rate": self.task_success_rate,
            "experiment_reproduction_rate": self.experiment_reproduction_rate,
            "validator_rejection_rate": self.validator_rejection_rate,
            "avg_cost_per_success": self.avg_cost_per_success,
            "avg_human_interventions": self.avg_human_interventions,
            "agent_loop_depth": self.agent_loop_depth,
            "rollback_count": self.rollback_count,
            "citation_error_rate": self.citation_error_rate,
            "evidence_coverage": self.evidence_coverage,
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "total_runs": self.total_runs,
            "reproduction_runs": self.reproduction_runs,
            "successful_reproduction_runs": self.successful_reproduction_runs,
            "validation_report_count": self.validation_report_count,
            "rejected_validation_report_count": self.rejected_validation_report_count,
            "total_citations": self.total_citations,
            "blocked_citations": self.blocked_citations,
            "total_claims": self.total_claims,
            "covered_claims": self.covered_claims,
            "total_cost": self.total_cost,
            "human_intervention_count": self.human_intervention_count,
        }


def compute_system_metrics(history: SystemMetricsInput) -> SystemMetricSnapshot:
    """Compute system monitoring metrics from recorded local history."""

    runs = history.runs
    total_runs = len(runs)
    total_tasks, successful_tasks = _task_counts(runs)
    reproduction_runs = tuple(run for run in runs if _is_reproduction_run(run))
    successful_reproduction_runs = sum(
        _status_value(run.status) == "success" for run in reproduction_runs
    )
    rejected_reports = sum(
        _status_value(report.status) == "failed" for report in history.validation_reports
    )
    total_citations = len(history.citations)
    blocked_citations = sum(
        _status_value(citation.status) == "blocked" for citation in history.citations
    )
    total_claims, covered_claims = _evidence_counts(history.evidence_graph)
    total_cost = sum(_run_cost(run) for run in runs)
    human_intervention_count = _human_interventions(runs, history.audit_events)
    loop_depth_values = [
        depth
        for run in runs
        if (depth := _numeric_metadata(run, "agent_loop_depth")) is not None
    ]

    return SystemMetricSnapshot(
        task_success_rate=_rate(successful_tasks, total_tasks),
        experiment_reproduction_rate=_rate(successful_reproduction_runs, len(reproduction_runs)),
        validator_rejection_rate=_rate(rejected_reports, len(history.validation_reports)),
        avg_cost_per_success=_ratio(total_cost, successful_tasks),
        avg_human_interventions=_ratio(float(human_intervention_count), total_runs),
        agent_loop_depth=_ratio(sum(loop_depth_values), len(loop_depth_values)),
        rollback_count=_rollback_count(history.audit_events),
        citation_error_rate=_rate(blocked_citations, total_citations),
        evidence_coverage=_rate(covered_claims, total_claims),
        total_tasks=total_tasks,
        successful_tasks=successful_tasks,
        total_runs=total_runs,
        reproduction_runs=len(reproduction_runs),
        successful_reproduction_runs=successful_reproduction_runs,
        validation_report_count=len(history.validation_reports),
        rejected_validation_report_count=rejected_reports,
        total_citations=total_citations,
        blocked_citations=blocked_citations,
        total_claims=total_claims,
        covered_claims=covered_claims,
        total_cost=round(total_cost, 6),
        human_intervention_count=human_intervention_count,
    )


def _task_counts(runs: tuple[Any, ...]) -> tuple[int, int]:
    task_statuses: dict[str, set[str]] = {}
    for run in runs:
        task_statuses.setdefault(str(run.task_id), set()).add(_status_value(run.status))
    successful_tasks = sum("success" in statuses for statuses in task_statuses.values())
    return len(task_statuses), successful_tasks


def _is_reproduction_run(run: Any) -> bool:
    metadata = _metadata(run)
    return bool(
        metadata.get("is_reproduction")
        or metadata.get("reproduction_of")
        or metadata.get("run_type") == "reproduction"
    )


def _run_cost(run: Any) -> float:
    cost_json = getattr(run, "cost_json", {}) or {}
    for key in ("total_cost_usd", "total_cost", "cost_usd"):
        value = _numeric_value(cost_json.get(key))
        if value is not None:
            return value

    cost_record = getattr(run, "cost_record", None)
    if cost_record is None:
        return 0.0
    return (
        _numeric_attr(cost_record, "network_cost_usd_placeholder")
        + _numeric_attr(cost_record, "gpu_hours")
        + (_numeric_attr(cost_record, "cpu_time_seconds") / 3600.0)
        + (_numeric_attr(cost_record, "storage_artifact_bytes") / 1_000_000_000.0)
    )


def _human_interventions(runs: tuple[Any, ...], audit_events: tuple[AuditEvent, ...]) -> int:
    run_interventions = 0
    for run in runs:
        cost_json = getattr(run, "cost_json", {}) or {}
        cost_record = getattr(run, "cost_record", None)
        run_interventions += int(_numeric_value(cost_json.get("human_approval_count")) or 0)
        if cost_record is not None:
            run_interventions += int(_numeric_attr(cost_record, "human_approval_count"))
        run_interventions += int(_numeric_metadata(run, "human_intervention_count") or 0)

    gate_events = sum(
        event.event_type in {AuditEventType.APPROVAL_GATE, AuditEventType.PUBLICATION_GATE}
        and event.approved is not None
        for event in audit_events
    )
    return run_interventions + gate_events


def _rollback_count(audit_events: tuple[AuditEvent, ...]) -> int:
    count = 0
    for event in audit_events:
        action = event.action.casefold()
        metadata = event.metadata
        if (
            "rollback" in action
            or bool(metadata.get("rollback"))
            or bool(metadata.get("rollback_target"))
        ):
            count += 1
    return count


def _evidence_counts(evidence_graph: Any | None) -> tuple[int, int]:
    if evidence_graph is None:
        return 0, 0
    claims = getattr(evidence_graph, "claims", {})
    total_claims = len(claims)
    covered = 0
    for claim_id in claims:
        try:
            traces = evidence_graph.trace_claim(claim_id)
        except Exception:
            traces = ()
        if any(_trace_supports_claim(trace) for trace in traces):
            covered += 1
    return total_claims, covered


def _trace_supports_claim(trace: Any) -> bool:
    evidence = getattr(trace, "evidence", None)
    supports_claim = bool(getattr(evidence, "supports_claim", False))
    return supports_claim and _status_value(trace.validation_status) in {"passed", "warning"}


def _metadata(run: Any) -> dict[str, Any]:
    metadata = getattr(run, "metadata", {}) or {}
    return dict(metadata) if isinstance(metadata, dict) else {}


def _numeric_metadata(run: Any, key: str) -> float | None:
    return _numeric_value(_metadata(run).get(key))


def _numeric_attr(value: Any, attr: str) -> float:
    return _numeric_value(getattr(value, attr, 0.0)) or 0.0


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _status_value(status: Any) -> str:
    return str(getattr(status, "value", status)).casefold()


def _rate(numerator: int, denominator: int) -> float:
    return _ratio(float(numerator), denominator)


def _ratio(numerator: float, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)
