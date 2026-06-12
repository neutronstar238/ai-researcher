"""Append-only audit events for local project governance."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


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


def default_audit_log_path(project_root: Path | str = ".") -> Path:
    """Return the MVP-local audit log path for a project."""

    return Path(project_root) / "audit" / "audit.jsonl"


class AuditLog:
    """Append and reload audit events from JSONL."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_audit_log_path()

    def append(self, event: AuditEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(event.model_dump_json())
            handle.write("\n")

    def read_all(self) -> list[AuditEvent]:
        if not self.path.exists():
            return []

        events: list[AuditEvent] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    events.append(AuditEvent.model_validate_json(line))
        return events
