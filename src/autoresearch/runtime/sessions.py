"""Lightweight agent session coordination for overlapping file edits."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AgentSessionStatus(str, Enum):
    """Lifecycle state for a local agent session claim."""

    ACTIVE = "active"
    RELEASED = "released"


class AgentSessionConflict(BaseModel):
    """One overlapping path conflict with another active session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    agent_name: str
    task_id: str
    claimed_path: str
    conflicting_path: str


class AgentSession(BaseModel):
    """A local session and the file paths it currently claims."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(default_factory=lambda: f"agent_session_{uuid4().hex}")
    agent_name: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    claimed_paths: tuple[str, ...] = Field(min_length=1)
    status: AgentSessionStatus = AgentSessionStatus.ACTIVE
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    released_at: datetime | None = None


class AgentSessionClaim(BaseModel):
    """Result of trying to claim a session path set."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    session: AgentSession | None
    conflicts: tuple[AgentSessionConflict, ...]
    message: str


class AgentSessionError(ValueError):
    """Raised when a session state transition is invalid."""


def claim_agent_session(
    *,
    state_path: Path | str,
    agent_name: str,
    task_id: str,
    claimed_paths: tuple[str, ...] | list[str],
    session_id: str | None = None,
    claimed_at: datetime | None = None,
) -> AgentSessionClaim:
    """Claim file paths for an active agent session, blocking overlapping sessions."""

    normalized_paths = _normalise_claimed_paths(claimed_paths)
    sessions = load_agent_sessions(state_path, include_released=True)
    resolved_session_id = session_id or f"agent_session_{uuid4().hex}"
    now = _normalise_datetime(claimed_at)
    conflicts = _find_conflicts(
        sessions,
        session_id=resolved_session_id,
        claimed_paths=normalized_paths,
    )
    if conflicts:
        return AgentSessionClaim(
            allowed=False,
            session=None,
            conflicts=tuple(conflicts),
            message="claimed paths overlap with active agent sessions",
        )

    existing_index = _find_session_index(sessions, resolved_session_id)
    if existing_index is None:
        session = AgentSession(
            session_id=resolved_session_id,
            agent_name=agent_name.strip(),
            task_id=task_id.strip(),
            claimed_paths=normalized_paths,
            started_at=now,
            updated_at=now,
        )
        sessions.append(session)
    else:
        previous = sessions[existing_index]
        session = previous.model_copy(
            update={
                "agent_name": agent_name.strip(),
                "task_id": task_id.strip(),
                "claimed_paths": normalized_paths,
                "status": AgentSessionStatus.ACTIVE,
                "updated_at": now,
                "released_at": None,
            }
        )
        sessions[existing_index] = session
    write_agent_sessions(state_path, sessions)
    return AgentSessionClaim(
        allowed=True,
        session=session,
        conflicts=(),
        message="session claim accepted",
    )


def release_agent_session(
    state_path: Path | str,
    session_id: str,
    *,
    released_at: datetime | None = None,
) -> AgentSession:
    """Mark an agent session as released so its claimed paths stop blocking others."""

    sessions = load_agent_sessions(state_path, include_released=True)
    index = _find_session_index(sessions, session_id)
    if index is None:
        msg = f"agent session not found: {session_id}"
        raise AgentSessionError(msg)
    session = sessions[index]
    if session.status is AgentSessionStatus.RELEASED:
        return session
    now = _normalise_datetime(released_at)
    released = session.model_copy(
        update={
            "status": AgentSessionStatus.RELEASED,
            "updated_at": now,
            "released_at": now,
        }
    )
    sessions[index] = released
    write_agent_sessions(state_path, sessions)
    return released


def list_agent_sessions(
    state_path: Path | str,
    *,
    include_released: bool = False,
) -> list[AgentSession]:
    """List active agent sessions by default."""

    sessions = load_agent_sessions(state_path, include_released=True)
    if include_released:
        return sessions
    return [session for session in sessions if session.status is AgentSessionStatus.ACTIVE]


def load_agent_sessions(
    state_path: Path | str,
    *,
    include_released: bool = False,
) -> list[AgentSession]:
    """Load local agent session state from disk."""

    path = Path(state_path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_sessions = payload.get("sessions") if isinstance(payload, dict) else None
    if not isinstance(raw_sessions, list):
        return []
    sessions: list[AgentSession] = []
    for raw_session in raw_sessions:
        if not isinstance(raw_session, dict):
            continue
        try:
            session = AgentSession.model_validate(raw_session)
        except ValueError:
            continue
        if include_released or session.status is AgentSessionStatus.ACTIVE:
            sessions.append(session)
    return sorted(sessions, key=lambda session: (session.started_at, session.session_id))


def write_agent_sessions(
    state_path: Path | str,
    sessions: list[AgentSession],
) -> None:
    """Persist local session coordination state as deterministic JSON."""

    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(sessions, key=lambda session: (session.started_at, session.session_id))
    path.write_text(
        json.dumps(
            {"sessions": [session.model_dump(mode="json") for session in ordered]},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _find_conflicts(
    sessions: list[AgentSession],
    *,
    session_id: str,
    claimed_paths: tuple[str, ...],
) -> list[AgentSessionConflict]:
    conflicts: list[AgentSessionConflict] = []
    for session in sessions:
        if session.session_id == session_id or session.status is not AgentSessionStatus.ACTIVE:
            continue
        for claimed_path in claimed_paths:
            for existing_path in session.claimed_paths:
                if _paths_overlap(claimed_path, existing_path):
                    conflicts.append(
                        AgentSessionConflict(
                            session_id=session.session_id,
                            agent_name=session.agent_name,
                            task_id=session.task_id,
                            claimed_path=claimed_path,
                            conflicting_path=existing_path,
                        )
                    )
    return conflicts


def _paths_overlap(left: str, right: str) -> bool:
    if left == "." or right == ".":
        return True
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _normalise_claimed_paths(paths: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(_normalise_path(path) for path in paths if str(path).strip())
    )
    if not normalized:
        msg = "at least one claimed path is required"
        raise AgentSessionError(msg)
    return normalized


def _normalise_path(path: str) -> str:
    text = path.replace("\\", "/").strip()
    text = re.sub(r"/+", "/", text)
    while text.startswith("./"):
        text = text[2:]
    text = text.strip("/")
    return text.casefold() or "."


def _find_session_index(
    sessions: list[AgentSession],
    session_id: str,
) -> int | None:
    for index, session in enumerate(sessions):
        if session.session_id == session_id:
            return index
    return None


def _normalise_datetime(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)
