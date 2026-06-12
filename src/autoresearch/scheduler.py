"""Local deterministic scheduler for recurring AI-Researcher work."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from autoresearch.observability import AuditEvent, AuditEventType, AuditLog
from autoresearch.schemas import DocumentRecord


class ScheduleInterval(str, Enum):
    """Supported local schedule intervals."""

    DAILY = "daily"
    WEEKLY = "weekly"
    ONCE = "once"


class ScheduledRunStatus(str, Enum):
    """Outcome of one scheduled task attempt."""

    SUCCESS = "success"
    FAILED = "failed"


ScheduleAction = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class ScheduledTask:
    """A task registered with the local scheduler."""

    task_id: str
    name: str
    interval: ScheduleInterval
    next_run_at: datetime
    action: ScheduleAction


@dataclass(frozen=True)
class ScheduledRun:
    """Result of one scheduled task execution."""

    task_id: str
    name: str
    status: ScheduledRunStatus
    ran_at: datetime
    metadata: dict[str, Any]


class LocalScheduler:
    """Run due local tasks and write audit events without external orchestration."""

    def __init__(
        self,
        *,
        audit_log: AuditLog | None = None,
        actor: str = "local-scheduler",
    ) -> None:
        self.audit_log = audit_log or AuditLog()
        self.actor = actor
        self._tasks: dict[str, ScheduledTask] = {}

    def add_task(self, task: ScheduledTask) -> None:
        """Register or replace a scheduled task."""

        self._tasks[task.task_id] = task

    def due_tasks(self, *, now: datetime | None = None) -> list[ScheduledTask]:
        """Return tasks due at or before `now`."""

        timestamp = _normalize_datetime(now)
        return sorted(
            (task for task in self._tasks.values() if task.next_run_at <= timestamp),
            key=lambda task: (task.next_run_at, task.task_id),
        )

    def run_due(self, *, now: datetime | None = None) -> list[ScheduledRun]:
        """Run due tasks once each and reschedule recurring tasks."""

        timestamp = _normalize_datetime(now)
        runs = [self._run_task(task, timestamp) for task in self.due_tasks(now=timestamp)]
        return runs

    def list_tasks(self) -> list[ScheduledTask]:
        """Return all registered tasks in deterministic order."""

        return [self._tasks[key] for key in sorted(self._tasks)]

    def _run_task(self, task: ScheduledTask, timestamp: datetime) -> ScheduledRun:
        try:
            metadata = task.action()
            status = ScheduledRunStatus.SUCCESS
        except Exception as exc:  # noqa: BLE001 - scheduler boundary must audit failures.
            metadata = {"error": str(exc), "error_type": type(exc).__name__}
            status = ScheduledRunStatus.FAILED

        run = ScheduledRun(
            task_id=task.task_id,
            name=task.name,
            status=status,
            ran_at=timestamp,
            metadata=metadata,
        )
        self._record_audit(run)
        self._reschedule(task, timestamp)
        return run

    def _record_audit(self, run: ScheduledRun) -> None:
        self.audit_log.append(
            AuditEvent(
                event_type=AuditEventType.SCHEDULER_RUN,
                actor=self.actor,
                action=f"ran scheduled task: {run.status.value}",
                resource=run.name,
                task_id=run.task_id,
                approved=run.status is ScheduledRunStatus.SUCCESS,
                metadata=run.metadata,
            )
        )

    def _reschedule(self, task: ScheduledTask, timestamp: datetime) -> None:
        if task.interval is ScheduleInterval.ONCE:
            self._tasks.pop(task.task_id, None)
            return

        next_run_at = task.next_run_at
        interval = _interval_delta(task.interval)
        while next_run_at <= timestamp:
            next_run_at += interval
        self._tasks[task.task_id] = replace(task, next_run_at=next_run_at)


def scheduled_task(
    *,
    task_id: str,
    name: str,
    interval: ScheduleInterval,
    next_run_at: datetime,
    action: ScheduleAction,
) -> ScheduledTask:
    """Create a scheduled task with an explicit interval."""

    return ScheduledTask(
        task_id=task_id,
        name=name,
        interval=interval,
        next_run_at=_normalize_datetime(next_run_at),
        action=action,
    )


def queued_task(
    *,
    task_id: str,
    name: str,
    queued_at: datetime,
    action: ScheduleAction,
) -> ScheduledTask:
    """Create a one-shot queued task."""

    return scheduled_task(
        task_id=task_id,
        name=name,
        interval=ScheduleInterval.ONCE,
        next_run_at=queued_at,
        action=action,
    )


def candidate_refresh_action(
    *,
    retrieve_literature: Callable[[], list[DocumentRecord]],
    analyze_gaps: Callable[[list[DocumentRecord]], Sequence[object]],
) -> ScheduleAction:
    """Return an action that fetches literature before trend/gap analysis."""

    def action() -> dict[str, Any]:
        documents = retrieve_literature()
        updates = analyze_gaps(documents)
        return {
            "pipeline": ["literature_retrieval", "trend_gap_analysis"],
            "document_count": len(documents),
            "update_count": len(updates),
        }

    return action


def _interval_delta(interval: ScheduleInterval) -> timedelta:
    if interval is ScheduleInterval.DAILY:
        return timedelta(days=1)
    if interval is ScheduleInterval.WEEKLY:
        return timedelta(days=7)
    msg = f"interval {interval.value} is not recurring"
    raise ValueError(msg)


def _normalize_datetime(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)
