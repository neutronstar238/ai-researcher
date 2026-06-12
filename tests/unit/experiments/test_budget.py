from pathlib import Path

from autoresearch.experiments import (
    BudgetGateStatus,
    evaluate_budget_gate,
)
from autoresearch.observability import AuditEventType, AuditLog
from autoresearch.schemas import CostRecord, ExecutionRun, ExperimentTask


def _task() -> ExperimentTask:
    return ExperimentTask(
        id="task_budget",
        project_id="project-001",
        hypothesis_id="hypothesis_1",
        name="Budgeted task",
        description="Run a budgeted experiment.",
        entrypoint="experiments/hypothesis-1/run.py",
        config_path="experiments/hypothesis-1/config.yaml",
        metrics=["score"],
        resource_budget={
            "cpu_time_seconds": 100,
            "gpu_hours": 2.0,
            "storage_mb": 10,
        },
        timeout_seconds=100,
        expected_outputs=["metrics.json"],
    )


def test_budget_gate_allows_usage_below_threshold() -> None:
    decision = evaluate_budget_gate(
        _task(),
        usage={"cpu_time_seconds": 79, "gpu_hours": 1.0},
    )

    assert decision.status is BudgetGateStatus.APPROVED
    assert decision.approval_required is False
    assert decision.pause_required is False
    assert decision.usage_ratios["cpu_time_seconds"] == 0.79


def test_budget_gate_requires_approval_at_eighty_percent(tmp_path: Path) -> None:
    audit_log = AuditLog(tmp_path / "audit.jsonl")

    decision = evaluate_budget_gate(
        _task(),
        usage={"cpu_time_seconds": 80},
        audit_log=audit_log,
        actor="executor",
    )

    assert decision.status is BudgetGateStatus.APPROVAL_REQUIRED
    assert decision.approval_required is True
    assert decision.pause_required is True
    assert decision.reasons == ("cpu_time_seconds reached 80% of budget",)
    event = audit_log.read_all()[0]
    assert event.event_type is AuditEventType.APPROVAL_GATE
    assert event.approved is False
    assert event.project_id == "project-001"
    assert event.task_id == "task_budget"
    assert event.metadata["usage_ratios"]["cpu_time_seconds"] == 0.8


def test_budget_gate_blocks_usage_at_hard_limit() -> None:
    decision = evaluate_budget_gate(
        _task(),
        usage={"gpu_hours": 2.0},
    )

    assert decision.status is BudgetGateStatus.BLOCKED
    assert decision.approval_required is True
    assert decision.reasons == ("gpu_hours reached 100% of budget",)


def test_budget_gate_reads_run_cost_record_and_storage_bytes() -> None:
    run = ExecutionRun(
        project_id="project-001",
        task_id="task_budget",
        cost_record=CostRecord(
            model_name="local-runner",
            cpu_time_seconds=10,
            storage_artifact_bytes=8 * 1024 * 1024,
        ),
    )

    decision = evaluate_budget_gate(_task(), run=run)

    assert decision.status is BudgetGateStatus.APPROVAL_REQUIRED
    assert decision.usage_ratios["storage_mb"] == 0.8
    assert decision.reasons == ("storage_mb reached 80% of budget",)
