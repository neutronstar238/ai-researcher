"""Governance audit events backed by the canonical atomic event journal."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from autoresearch.kernel import (
    ActorKind,
    EventActor,
    EventJournal,
    EventStatus,
    RunEvent,
)


class AuditEventType(str, Enum):
    """Governance events that must be traceable during self-evolution loops."""

    PERMISSION_CHECK = "permission_check"
    SANDBOX_DENIAL = "sandbox_denial"
    CONFIG_CHANGE = "config_change"
    APPROVAL_GATE = "approval_gate"
    SCHEDULER_RUN = "scheduler_run"
    STRATEGY_CHANGE = "strategy_change"
    ROLLBACK = "rollback"
    PUBLICATION_GATE = "publication_gate"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuditEvent(BaseModel):
    """A single append-only audit event."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: f"audit_{uuid4().hex}")
    event_type: AuditEventType
    timestamp: datetime = Field(default_factory=_utc_now)
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    resource: str | None = None
    run_id: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    approved: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("audit timestamps must be timezone-aware UTC")
        return value.astimezone(timezone.utc)


def default_audit_log_path(project_root: Path | str = ".") -> Path:
    """Return the retained legacy JSONL location used to derive the v2 journal."""

    return Path(project_root) / "audit" / "audit.jsonl"


class AuditLog:
    """Write one canonical journal while retaining a read-only JSONL importer."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_audit_log_path()
        self.journal_root = self.path.with_suffix(".journal")

    def append(self, event: AuditEvent) -> None:
        journal = self._open_or_create_journal()
        snapshot = journal.snapshot(require_complete_terminal=False)
        parent = snapshot.events[-1] if snapshot.events else None
        payload = event.model_dump(mode="json")
        envelope = RunEvent.create(
            event_id=event.event_id,
            run_id=journal.metadata.run_id,
            sequence=len(snapshot.events) + 1,
            occurred_at=event.timestamp,
            actor=EventActor(
                actor_id=_actor_id(event.actor),
                kind=ActorKind.SYSTEM,
            ),
            event_type=f"audit.{event.event_type.value}",
            status=EventStatus.STARTED,
            action=f"record {event.event_type.value}",
            idempotency_key=f"audit.{event.event_id}",
            parent_event_id=parent.event_id if parent is not None else None,
            parent_event_hash=parent.event_hash if parent is not None else None,
            payload={"audit_event": payload},
        )
        journal.append(
            envelope,
            expected_lineage_hash=snapshot.lineage_hash,
        )

    def read_all(self) -> list[AuditEvent]:
        if self.journal_root.is_dir():
            snapshot = EventJournal.open(self.journal_root).snapshot(
                require_complete_terminal=False
            )
            return [_audit_event_from_envelope(event) for event in snapshot.events]
        return self._read_legacy_jsonl()

    def export_legacy_snapshot(self, destination: Path | str) -> Path:
        """Export a validated rollback snapshot without restoring dual writes."""

        target = Path(destination)
        if target.exists():
            raise FileExistsError(f"legacy audit export already exists: {target}")
        text = "".join(event.model_dump_json() + "\n" for event in self.read_all())
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return target

    def _read_legacy_jsonl(self) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        events: list[AuditEvent] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    events.append(AuditEvent.model_validate_json(line))
        return events

    def _open_or_create_journal(self) -> EventJournal:
        if self.journal_root.exists():
            return EventJournal.open(self.journal_root)

        legacy_events = self._read_legacy_jsonl()
        created_at = legacy_events[0].timestamp if legacy_events else _utc_now()
        journal = EventJournal.create(
            self.journal_root,
            run_id=_journal_run_id(self.path),
            created_at=created_at,
        )
        for event in legacy_events:
            self.append(event)
        return journal


def _journal_run_id(path: Path) -> str:
    normalized = path.resolve().as_posix().casefold().encode("utf-8")
    return f"audit.local.{hashlib.sha256(normalized).hexdigest()[:24]}"


def _actor_id(actor: str) -> str:
    digest = hashlib.sha256(actor.encode("utf-8")).hexdigest()[:24]
    return f"audit.actor.{digest}"


def _audit_event_from_envelope(event: RunEvent) -> AuditEvent:
    raw = event.payload.get("audit_event")
    if not isinstance(raw, dict):
        raise ValueError(f"audit envelope {event.event_id} has no audit_event object")
    parsed = AuditEvent.model_validate(raw)
    if parsed.event_id != event.event_id:
        raise ValueError(f"audit envelope {event.event_id} changes its logical event ID")
    expected_type = f"audit.{parsed.event_type.value}"
    if event.event_type != expected_type:
        raise ValueError(
            f"audit envelope {event.event_id} changes event type "
            f"{expected_type} to {event.event_type}"
        )
    json.dumps(parsed.model_dump(mode="json"), sort_keys=True)
    return parsed
