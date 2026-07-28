from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.kernel import JournalCorruptionError
from autoresearch.observability import (
    AuditEvent,
    AuditEventType,
    AuditLog,
    default_audit_log_path,
)


@pytest.mark.parametrize("event_type", list(AuditEventType))
def test_audit_event_types_cover_governance_events(event_type: AuditEventType) -> None:
    event = AuditEvent(
        event_type=event_type,
        actor="agent",
        action="record",
        resource="research-loop",
    )

    assert event.event_type == event_type
    assert event.event_id.startswith("audit_")


def test_audit_log_appends_and_reloads_events_without_loss(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit" / "audit.jsonl")
    first = AuditEvent(
        event_type=AuditEventType.PERMISSION_CHECK,
        actor="planner",
        action="checked vault write",
        resource="autoresearch-vault",
        run_id="run_1",
        project_id="project_1",
        task_id="task_1",
        approved=True,
        metadata={"permission": "write"},
    )
    second = AuditEvent(
        event_type=AuditEventType.STRATEGY_CHANGE,
        actor="evolution-agent",
        action="accepted new strategy card",
        resource="strategy/self-loop",
        run_id="run_1",
        approved=None,
        metadata={"source": "reflection"},
    )

    log.append(first)
    log.append(second)

    assert log.journal_root.is_dir()
    assert not log.path.exists()
    assert log.read_all() == [first, second]


def test_audit_log_returns_empty_list_for_missing_file(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit" / "missing.jsonl")

    assert log.read_all() == []


def test_default_audit_log_path_uses_local_project_audit_directory() -> None:
    assert default_audit_log_path("project") == Path("project") / "audit" / "audit.jsonl"


def test_audit_log_imports_legacy_jsonl_once_then_uses_only_journal(
    tmp_path: Path,
) -> None:
    path = tmp_path / "audit" / "audit.jsonl"
    path.parent.mkdir(parents=True)
    legacy = AuditEvent(
        event_type=AuditEventType.SCHEDULER_RUN,
        actor="legacy-scheduler",
        action="scheduled one bounded run",
    )
    path.write_text(legacy.model_dump_json() + "\n", encoding="utf-8")
    log = AuditLog(path)
    current = AuditEvent(
        event_type=AuditEventType.PERMISSION_CHECK,
        actor="permission-policy",
        action="checked local write",
        approved=True,
    )

    log.append(current)

    assert path.read_text(encoding="utf-8") == legacy.model_dump_json() + "\n"
    assert log.read_all() == [legacy, current]


def test_audit_log_exports_explicit_read_only_rollback_snapshot(
    tmp_path: Path,
) -> None:
    log = AuditLog(tmp_path / "audit" / "audit.jsonl")
    event = AuditEvent(
        event_type=AuditEventType.CONFIG_CHANGE,
        actor="configuration-policy",
        action="changed one bounded setting",
    )
    log.append(event)
    destination = tmp_path / "rollback" / "audit.jsonl"

    exported = log.export_legacy_snapshot(destination)

    assert exported == destination
    assert AuditLog(destination).read_all() == [event]
    assert not AuditLog(destination).journal_root.exists()
    with pytest.raises(FileExistsError, match="already exists"):
        log.export_legacy_snapshot(destination)


def test_audit_log_rejects_tampered_journal_event(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    event = AuditEvent(
        event_type=AuditEventType.APPROVAL_GATE,
        actor="approval-policy",
        action="kept release closed",
        approved=False,
    )
    log.append(event)
    event_path = next((log.journal_root / "events").glob("*.json"))
    raw = event_path.read_text(encoding="utf-8")
    event_path.write_text(raw.replace("kept release closed", "opened release"), encoding="utf-8")

    with pytest.raises(JournalCorruptionError, match="canonical JSON|hash mismatch"):
        log.read_all()


def test_audit_event_requires_utc_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        AuditEvent(
            event_type=AuditEventType.CONFIG_CHANGE,
            timestamp=datetime(2026, 7, 29),
            actor="configuration-policy",
            action="changed config",
        )
