from pathlib import Path

import pytest

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

    assert log.path.exists()
    assert log.read_all() == [first, second]


def test_audit_log_returns_empty_list_for_missing_file(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit" / "missing.jsonl")

    assert log.read_all() == []


def test_default_audit_log_path_uses_local_project_audit_directory() -> None:
    assert default_audit_log_path("project") == Path("project") / "audit" / "audit.jsonl"
