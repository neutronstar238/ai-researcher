from autoresearch.evidence import (
    ClaimNode,
    EvidenceArtifact,
    EvidenceGraph,
    EvidenceNode,
    SourceNode,
)
from autoresearch.experiments import ValidationIssue, ValidationReport
from autoresearch.observability import (
    AuditEvent,
    AuditEventType,
    SystemMetricsInput,
    compute_system_metrics,
)
from autoresearch.reports import CitationStatus, CitationValidation
from autoresearch.schemas import CostRecord, ExecutionRun, ExecutionStatus, ValidationStatus


def test_compute_system_metrics_from_fixture_run_history() -> None:
    runs = (
        ExecutionRun(
            id="run_1",
            project_id="project_1",
            task_id="task_1",
            status=ExecutionStatus.SUCCESS,
            cost_record=CostRecord(model_name="local", human_approval_count=1),
            cost_json={"total_cost_usd": 10.0},
            metadata={"agent_loop_depth": 2},
        ),
        ExecutionRun(
            id="run_2",
            project_id="project_1",
            task_id="task_2",
            status=ExecutionStatus.FAILED,
            cost_json={"total_cost_usd": 4.0},
            metadata={"agent_loop_depth": 4},
        ),
        ExecutionRun(
            id="run_3",
            project_id="project_1",
            task_id="task_3",
            status=ExecutionStatus.SUCCESS,
            cost_json={"total_cost_usd": 6.0, "human_approval_count": 1},
            metadata={
                "agent_loop_depth": 3,
                "is_reproduction": True,
                "human_intervention_count": 1,
            },
        ),
    )
    history = SystemMetricsInput(
        runs=runs,
        validation_reports=(
            _validation_report("run_1", ValidationStatus.PASSED),
            _validation_report("run_2", ValidationStatus.FAILED),
            _validation_report("run_3", ValidationStatus.WARNING),
        ),
        citations=(
            CitationValidation(
                document_id="doc_1",
                title="Verified",
                status=CitationStatus.VERIFIED_DOI,
                bibtex_key="verified2026",
            ),
            CitationValidation(
                document_id="doc_2",
                title="Blocked",
                status=CitationStatus.BLOCKED,
                bibtex_key=None,
                reason="citation lacks DOI or URL",
            ),
        ),
        evidence_graph=_evidence_graph(),
        audit_events=(
            AuditEvent(
                event_type=AuditEventType.APPROVAL_GATE,
                actor="budget-gate",
                action="requested human approval",
                approved=True,
            ),
            AuditEvent(
                event_type=AuditEventType.STRATEGY_CHANGE,
                actor="safety-auditor",
                action="rollback strategy after shadow regression",
                metadata={"rollback_target": "strategy_v1"},
            ),
        ),
    )

    metrics = compute_system_metrics(history)

    assert metrics.task_success_rate == 0.666667
    assert metrics.experiment_reproduction_rate == 1.0
    assert metrics.validator_rejection_rate == 0.333333
    assert metrics.avg_cost_per_success == 10.0
    assert metrics.avg_human_interventions == 1.333333
    assert metrics.agent_loop_depth == 3.0
    assert metrics.rollback_count == 1
    assert metrics.citation_error_rate == 0.5
    assert metrics.evidence_coverage == 0.5
    assert metrics.total_cost == 20.0
    assert metrics.human_intervention_count == 4
    assert metrics.to_dict()["task_success_rate"] == 0.666667


def test_compute_system_metrics_handles_empty_history() -> None:
    metrics = compute_system_metrics(SystemMetricsInput())

    assert metrics.task_success_rate == 0.0
    assert metrics.experiment_reproduction_rate == 0.0
    assert metrics.avg_cost_per_success == 0.0
    assert metrics.evidence_coverage == 0.0


def _validation_report(run_id: str, status: ValidationStatus) -> ValidationReport:
    issues = ()
    if status is ValidationStatus.FAILED:
        issues = (
            ValidationIssue(
                severity=ValidationStatus.FAILED,
                check="metric_presence",
                message="missing metric macro_f1",
            ),
        )
    return ValidationReport(
        run_id=run_id,
        status=status,
        issues=issues,
        json_path=f"{run_id}/validation.json",
        markdown_path=f"{run_id}/validation.md",
    )


def _evidence_graph() -> EvidenceGraph:
    graph = EvidenceGraph()
    graph.add_claim(ClaimNode(id="claim_1", statement="Metric improved."))
    graph.add_claim(ClaimNode(id="claim_2", statement="Unverified claim."))
    graph.add_source(
        SourceNode(
            id="source_1",
            title="Run 1",
            uri="runs/run_1",
        )
    )
    graph.add_artifact(
        EvidenceArtifact(
            id="artifact_1",
            source_id="source_1",
            uri="metrics.json",
            validation_status=ValidationStatus.PASSED,
        )
    )
    graph.link_evidence(
        EvidenceNode(
            id="evidence_1",
            claim_id="claim_1",
            source_id="source_1",
            artifact_id="artifact_1",
            summary="metric source",
        )
    )
    return graph
