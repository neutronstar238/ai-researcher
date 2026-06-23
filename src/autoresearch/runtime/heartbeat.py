"""Heartbeat and stall detection for long-running research loops."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_HEARTBEAT_STALE_AFTER_SECONDS = 900
DEFAULT_HEARTBEAT_STALL_REPETITIONS = 3
DEFAULT_HEARTBEAT_HISTORY_LIMIT = 500
HEARTBEAT_EVIDENCE_POLICY = (
    "Runtime heartbeat reports prove only that a loop stage emitted progress signals "
    "and whether those signals look stale or repeated. They cannot support scientific "
    "results, novelty claims, benchmark metrics, citation validity, tool invocation, "
    "or publication readiness without validated research artifacts."
)


class RuntimeHeartbeatStatus(str, Enum):
    """Watchdog status for one stage heartbeat stream."""

    HEALTHY = "healthy"
    STALE = "stale"
    STALLED = "stalled"


class RuntimeHeartbeatAction(str, Enum):
    """Suggested operator or controller action after heartbeat evaluation."""

    CONTINUE = "continue"
    INSPECT = "inspect"
    REPAIR_OR_PIVOT = "repair_or_pivot"


class RuntimeHeartbeatEvent(BaseModel):
    """One progress signal emitted by a long-running research loop stage."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    progress_signature: str = Field(min_length=1)
    progress_sha256: str
    emitted_at: datetime
    message: str | None = None
    artifact_refs: tuple[str, ...] = ()


class RuntimeHeartbeatStageReport(BaseModel):
    """Watchdog decision for one run/stage heartbeat stream."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    stage: str
    status: RuntimeHeartbeatStatus
    action: RuntimeHeartbeatAction
    latest_at: datetime
    age_seconds: float
    repeated_progress_count: int
    latest_progress_sha256: str
    latest_message: str | None = None
    artifact_refs: tuple[str, ...] = ()
    reason: str


class RuntimeHeartbeatReport(BaseModel):
    """Full watchdog report over the persisted heartbeat state file."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    checked_at: datetime
    stale_after_seconds: int
    stall_repetition_threshold: int
    event_count: int
    stage_count: int
    stale_count: int
    stalled_count: int
    stages: tuple[RuntimeHeartbeatStageReport, ...]
    evidence_policy: str = HEARTBEAT_EVIDENCE_POLICY


def write_runtime_heartbeat(
    *,
    state_path: Path | str,
    run_id: str,
    stage: str,
    progress: str,
    emitted_at: datetime | None = None,
    message: str | None = None,
    artifact_refs: tuple[str, ...] | list[str] = (),
    history_limit: int = DEFAULT_HEARTBEAT_HISTORY_LIMIT,
) -> RuntimeHeartbeatEvent:
    """Append one heartbeat event and keep bounded deterministic history."""

    event = RuntimeHeartbeatEvent(
        run_id=_required_text(run_id, "run_id"),
        stage=_normalize_stage(stage),
        progress_signature=_required_text(progress, "progress"),
        progress_sha256=_progress_hash(progress),
        emitted_at=_normalize_datetime(emitted_at),
        message=message.strip() if message and message.strip() else None,
        artifact_refs=_clean_refs(artifact_refs),
    )
    events = [*load_runtime_heartbeats(state_path), event]
    bounded_limit = max(int(history_limit), 1)
    events = sorted(events, key=lambda item: (item.emitted_at, item.run_id, item.stage))[
        -bounded_limit:
    ]
    _write_runtime_heartbeats(state_path, events)
    return event


def load_runtime_heartbeats(state_path: Path | str) -> list[RuntimeHeartbeatEvent]:
    """Load heartbeat events from a local JSON state file."""

    path = Path(state_path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_events = payload.get("heartbeats") if isinstance(payload, dict) else None
    if not isinstance(raw_events, list):
        return []
    events: list[RuntimeHeartbeatEvent] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        try:
            events.append(RuntimeHeartbeatEvent.model_validate(raw_event))
        except ValueError:
            continue
    return sorted(events, key=lambda item: (item.emitted_at, item.run_id, item.stage))


def evaluate_runtime_heartbeats(
    *,
    state_path: Path | str,
    checked_at: datetime | None = None,
    run_id: str | None = None,
    stale_after_seconds: int = DEFAULT_HEARTBEAT_STALE_AFTER_SECONDS,
    stall_repetition_threshold: int = DEFAULT_HEARTBEAT_STALL_REPETITIONS,
) -> RuntimeHeartbeatReport:
    """Evaluate stale or repeated progress signals in the heartbeat state file."""

    events = load_runtime_heartbeats(state_path)
    if run_id is not None:
        selected_run_id = _required_text(run_id, "run_id")
        events = [event for event in events if event.run_id == selected_run_id]
    now = _normalize_datetime(checked_at)
    stage_reports = tuple(
        _stage_report(
            key,
            stage_events,
            checked_at=now,
            stale_after_seconds=max(int(stale_after_seconds), 0),
            stall_repetition_threshold=max(int(stall_repetition_threshold), 1),
        )
        for key, stage_events in _events_by_run_stage(events)
    )
    stale_count = sum(1 for report in stage_reports if report.status is RuntimeHeartbeatStatus.STALE)
    stalled_count = sum(
        1 for report in stage_reports if report.status is RuntimeHeartbeatStatus.STALLED
    )
    return RuntimeHeartbeatReport(
        passed=stale_count == 0 and stalled_count == 0,
        checked_at=now,
        stale_after_seconds=max(int(stale_after_seconds), 0),
        stall_repetition_threshold=max(int(stall_repetition_threshold), 1),
        event_count=len(events),
        stage_count=len(stage_reports),
        stale_count=stale_count,
        stalled_count=stalled_count,
        stages=stage_reports,
    )


def write_runtime_heartbeat_report(
    report: RuntimeHeartbeatReport,
    path: Path | str,
) -> Path:
    """Persist a watchdog report as JSON."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def _write_runtime_heartbeats(
    state_path: Path | str,
    events: list[RuntimeHeartbeatEvent],
) -> None:
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"heartbeats": [event.model_dump(mode="json") for event in events]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _events_by_run_stage(
    events: list[RuntimeHeartbeatEvent],
) -> tuple[tuple[tuple[str, str], tuple[RuntimeHeartbeatEvent, ...]], ...]:
    grouped: dict[tuple[str, str], list[RuntimeHeartbeatEvent]] = {}
    for event in events:
        grouped.setdefault((event.run_id, event.stage), []).append(event)
    return tuple(
        (key, tuple(sorted(values, key=lambda item: item.emitted_at)))
        for key, values in sorted(grouped.items())
    )


def _stage_report(
    key: tuple[str, str],
    events: tuple[RuntimeHeartbeatEvent, ...],
    *,
    checked_at: datetime,
    stale_after_seconds: int,
    stall_repetition_threshold: int,
) -> RuntimeHeartbeatStageReport:
    latest = events[-1]
    repeated = _repeated_tail_count(events)
    age_seconds = max((checked_at - latest.emitted_at).total_seconds(), 0.0)
    if age_seconds > stale_after_seconds:
        status = RuntimeHeartbeatStatus.STALE
        action = RuntimeHeartbeatAction.INSPECT
        reason = (
            f"latest heartbeat age {age_seconds:.0f}s exceeds stale threshold "
            f"{stale_after_seconds}s"
        )
    elif repeated >= stall_repetition_threshold:
        status = RuntimeHeartbeatStatus.STALLED
        action = RuntimeHeartbeatAction.REPAIR_OR_PIVOT
        reason = (
            f"progress signature repeated {repeated} times; threshold is "
            f"{stall_repetition_threshold}"
        )
    else:
        status = RuntimeHeartbeatStatus.HEALTHY
        action = RuntimeHeartbeatAction.CONTINUE
        reason = "heartbeat is fresh and progress signature is changing"
    return RuntimeHeartbeatStageReport(
        run_id=key[0],
        stage=key[1],
        status=status,
        action=action,
        latest_at=latest.emitted_at,
        age_seconds=age_seconds,
        repeated_progress_count=repeated,
        latest_progress_sha256=latest.progress_sha256,
        latest_message=latest.message,
        artifact_refs=latest.artifact_refs,
        reason=reason,
    )


def _repeated_tail_count(events: tuple[RuntimeHeartbeatEvent, ...]) -> int:
    if not events:
        return 0
    latest_hash = events[-1].progress_sha256
    count = 0
    for event in reversed(events):
        if event.progress_sha256 != latest_hash:
            break
        count += 1
    return count


def _normalize_stage(stage: str) -> str:
    normalized = _required_text(stage, "stage").replace("-", "_").lower()
    if not all(char.isalnum() or char in {"_", ".", ":"} for char in normalized):
        msg = "stage must contain only letters, digits, _, ., :, or -"
        raise ValueError(msg)
    return normalized


def _required_text(value: str, field_name: str) -> str:
    text = value.strip()
    if not text:
        msg = f"{field_name} must be non-empty"
        raise ValueError(msg)
    return text


def _clean_refs(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _progress_hash(progress: str) -> str:
    return hashlib.sha256(progress.strip().encode("utf-8")).hexdigest()


def _normalize_datetime(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)
