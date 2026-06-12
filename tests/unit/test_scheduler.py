from datetime import datetime, timezone
from pathlib import Path

from autoresearch.knowledge import KnowledgeEntry, KnowledgeEntryType, KnowledgeZone
from autoresearch.observability import AuditEventType, AuditLog
from autoresearch.scheduler import (
    LocalScheduler,
    ScheduledRunStatus,
    ScheduleInterval,
    candidate_refresh_action,
    queued_issue_followups_from_vault,
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


def test_scheduler_builds_queued_followups_from_open_issue_notes(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"
    issue_dir = vault_root / "projects" / "project_1" / "issues"
    issue_dir.mkdir(parents=True)
    open_issue = KnowledgeEntry(
        entry_id="llm_review_issue_project_1_abc",
        entry_type=KnowledgeEntryType.ISSUE_NOTE,
        zone=KnowledgeZone.PROJECT,
        title="LLM review issue: missing evidence",
        project_id="project_1",
        related_task_ids=["47.1"],
        body="\n".join(
            [
                "# LLM Review Follow-Up",
                "",
                "- Status: Open",
                "- Issue fingerprint: `abc123def4567890`",
                "",
                "## Claim",
                "",
                "The evidence is missing.",
            ]
        ),
    )
    closed_issue = KnowledgeEntry(
        entry_id="closed_issue",
        entry_type=KnowledgeEntryType.ISSUE_NOTE,
        zone=KnowledgeZone.PROJECT,
        title="Closed issue",
        project_id="project_1",
        body="- Status: Closed\n",
    )
    (issue_dir / "open.md").write_text(open_issue.to_markdown(), encoding="utf-8")
    (issue_dir / "closed.md").write_text(closed_issue.to_markdown(), encoding="utf-8")

    tasks = queued_issue_followups_from_vault(
        vault_root=vault_root,
        project_id="project_1",
        queued_at=datetime(2026, 6, 12, 8, tzinfo=timezone.utc),
    )

    assert len(tasks) == 1
    assert tasks[0].task_id == "issue-follow-up-project_1-abc123def4567890"
    assert tasks[0].name == "issue follow-up: LLM review issue: missing evidence"
    assert tasks[0].action() == {
        "kind": "issue_followup",
        "issue_id": "llm_review_issue_project_1_abc",
        "issue_title": "LLM review issue: missing evidence",
        "issue_path": "projects/project_1/issues/open.md",
        "project_id": "project_1",
        "related_task_ids": ["47.1"],
    }
