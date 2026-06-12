from datetime import datetime, timezone
from pathlib import Path

from autoresearch.observability import AuditEventType, AuditLog
from autoresearch.scheduler import (
    LocalScheduler,
    ScheduledRunStatus,
    ScheduleInterval,
    candidate_refresh_action,
    queued_task,
    scheduled_task,
)
from autoresearch.schemas import DocumentRecord


def test_scheduler_runs_daily_task_and_records_audit_log(tmp_path: Path) -> None:
    calls: list[str] = []
    now = datetime(2026, 6, 12, 8, tzinfo=timezone.utc)
    scheduler = LocalScheduler(audit_log=AuditLog(tmp_path / "audit.jsonl"))
    scheduler.add_task(
        scheduled_task(
            task_id="candidate-refresh",
            name="candidate refresh",
            interval=ScheduleInterval.DAILY,
            next_run_at=datetime(2026, 6, 12, 7, tzinfo=timezone.utc),
            action=lambda: calls.append("refresh") or {"kind": "candidate_refresh"},
        )
    )

    runs = scheduler.run_due(now=now)
    events = scheduler.audit_log.read_all()

    assert calls == ["refresh"]
    assert len(runs) == 1
    assert runs[0].status is ScheduledRunStatus.SUCCESS
    assert scheduler.list_tasks()[0].next_run_at == datetime(2026, 6, 13, 7, tzinfo=timezone.utc)
    assert events[0].event_type is AuditEventType.SCHEDULER_RUN
    assert events[0].task_id == "candidate-refresh"
    assert events[0].metadata == {"kind": "candidate_refresh"}


def test_scheduler_runs_queued_task_once(tmp_path: Path) -> None:
    now = datetime(2026, 6, 12, 8, tzinfo=timezone.utc)
    scheduler = LocalScheduler(audit_log=AuditLog(tmp_path / "audit.jsonl"))
    scheduler.add_task(
        queued_task(
            task_id="experiment-check",
            name="queued experiment check",
            queued_at=now,
            action=lambda: {"kind": "experiment_check"},
        )
    )

    first_runs = scheduler.run_due(now=now)
    second_runs = scheduler.run_due(now=now)

    assert [run.task_id for run in first_runs] == ["experiment-check"]
    assert second_runs == []
    assert scheduler.list_tasks() == []


def test_candidate_refresh_action_calls_literature_before_gap_analysis() -> None:
    calls: list[str] = []
    document = DocumentRecord(
        id="doc_1",
        title="Evidence-first agents",
        source_uri="https://example.com/doc_1",
        abstract="Agent workflows need stronger evidence.",
    )

    def retrieve_literature() -> list[DocumentRecord]:
        calls.append("literature")
        return [document]

    def analyze_gaps(documents: list[DocumentRecord]) -> list[str]:
        calls.append(f"analysis:{documents[0].id}")
        return ["update_1"]

    action = candidate_refresh_action(
        retrieve_literature=retrieve_literature,
        analyze_gaps=analyze_gaps,
    )

    metadata = action()

    assert calls == ["literature", "analysis:doc_1"]
    assert metadata == {
        "pipeline": ["literature_retrieval", "trend_gap_analysis"],
        "document_count": 1,
        "update_count": 1,
    }


def test_scheduler_audits_failed_task_without_stopping(tmp_path: Path) -> None:
    scheduler = LocalScheduler(audit_log=AuditLog(tmp_path / "audit.jsonl"))
    now = datetime(2026, 6, 12, 8, tzinfo=timezone.utc)

    def fail() -> dict[str, object]:
        raise RuntimeError("network disabled")

    scheduler.add_task(
        scheduled_task(
            task_id="daily-refresh",
            name="daily refresh",
            interval=ScheduleInterval.DAILY,
            next_run_at=now,
            action=fail,
        )
    )

    runs = scheduler.run_due(now=now)
    events = scheduler.audit_log.read_all()

    assert runs[0].status is ScheduledRunStatus.FAILED
    assert runs[0].metadata == {"error": "network disabled", "error_type": "RuntimeError"}
    assert events[0].approved is False
