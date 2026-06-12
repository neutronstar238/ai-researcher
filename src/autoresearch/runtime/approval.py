"""Local runtime approval queue for always-on AI-Researcher actions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class RuntimePermissionMode(str, Enum):
    """Operator permission modes for the always-on runtime."""

    ALLOW_ALL = "allow-all"
    APPROVE_DANGEROUS = "approve-dangerous"


class RuntimeActionRisk(str, Enum):
    """Risk level for a runtime action."""

    SAFE = "safe"
    DANGEROUS = "dangerous"


class RuntimeApprovalStatus(str, Enum):
    """State of one runtime approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RuntimeApprovalRequest(BaseModel):
    """A local approval request for a dangerous runtime action."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: f"runtime_approval_{uuid4().hex}")
    action_id: str = Field(min_length=1)
    command: str = Field(min_length=1)
    risk: RuntimeActionRisk
    reason: str = Field(min_length=1)
    status: RuntimeApprovalStatus = RuntimeApprovalStatus.PENDING
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class RuntimeApprovalDecision(BaseModel):
    """Decision returned before a runtime action runs."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    mode: RuntimePermissionMode
    request: RuntimeApprovalRequest | None = None
    message: str


class RuntimeApprovalError(ValueError):
    """Raised when an approval state transition is invalid."""


def ensure_runtime_approval(
    *,
    state_path: Path | str,
    mode: RuntimePermissionMode | str,
    action_id: str,
    command: str,
    risk: RuntimeActionRisk | str,
    reason: str,
    requested_at: datetime | None = None,
) -> RuntimeApprovalDecision:
    """Return whether an action may run, creating a pending request if needed."""

    permission_mode = _coerce_permission_mode(mode)
    action_risk = _coerce_action_risk(risk)
    if permission_mode is RuntimePermissionMode.ALLOW_ALL:
        return RuntimeApprovalDecision(
            allowed=True,
            mode=permission_mode,
            message="allowed by allow-all permission mode",
        )
    if action_risk is RuntimeActionRisk.SAFE:
        return RuntimeApprovalDecision(
            allowed=True,
            mode=permission_mode,
            message="safe action allowed by approve-dangerous permission mode",
        )

    approvals = load_runtime_approval_requests(state_path)
    approved = _latest_request(
        approvals,
        action_id=action_id,
        status=RuntimeApprovalStatus.APPROVED,
    )
    if approved is not None:
        return RuntimeApprovalDecision(
            allowed=True,
            mode=permission_mode,
            request=approved,
            message="dangerous action already approved",
        )

    pending = _latest_request(
        approvals,
        action_id=action_id,
        status=RuntimeApprovalStatus.PENDING,
    )
    if pending is not None:
        return RuntimeApprovalDecision(
            allowed=False,
            mode=permission_mode,
            request=pending,
            message="dangerous action is waiting for approval",
        )

    request = RuntimeApprovalRequest(
        action_id=action_id,
        command=command,
        risk=action_risk,
        reason=reason,
        requested_at=_normalise_datetime(requested_at),
    )
    approvals.append(request)
    write_runtime_approval_requests(state_path, approvals)
    return RuntimeApprovalDecision(
        allowed=False,
        mode=permission_mode,
        request=request,
        message="created runtime approval request",
    )


def approve_runtime_request(
    state_path: Path | str,
    request_id: str,
    *,
    approved_by: str,
    approved_at: datetime | None = None,
) -> RuntimeApprovalRequest:
    """Approve a pending runtime request by ID, or use `latest` for newest pending."""

    approvals = load_runtime_approval_requests(state_path)
    request = _select_request_for_approval(approvals, request_id)
    if request.status is RuntimeApprovalStatus.REJECTED:
        msg = f"approval request is rejected: {request.request_id}"
        raise RuntimeApprovalError(msg)
    if request.status is RuntimeApprovalStatus.APPROVED:
        return request
    request.status = RuntimeApprovalStatus.APPROVED
    request.resolved_at = _normalise_datetime(approved_at)
    request.resolved_by = approved_by
    write_runtime_approval_requests(state_path, approvals)
    return request


def list_runtime_approval_requests(
    state_path: Path | str,
    *,
    include_completed: bool = False,
) -> list[RuntimeApprovalRequest]:
    """List runtime approval requests, pending-only by default."""

    approvals = load_runtime_approval_requests(state_path)
    if include_completed:
        return approvals
    return [request for request in approvals if request.status is RuntimeApprovalStatus.PENDING]


def load_runtime_approval_requests(state_path: Path | str) -> list[RuntimeApprovalRequest]:
    """Load runtime approval state from disk."""

    path = Path(state_path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_requests = payload.get("requests") if isinstance(payload, dict) else None
    if not isinstance(raw_requests, list):
        return []
    requests: list[RuntimeApprovalRequest] = []
    for raw_request in raw_requests:
        if not isinstance(raw_request, dict):
            continue
        try:
            requests.append(RuntimeApprovalRequest.model_validate(raw_request))
        except ValueError:
            continue
    return sorted(requests, key=lambda request: (request.requested_at, request.request_id))


def write_runtime_approval_requests(
    state_path: Path | str,
    requests: list[RuntimeApprovalRequest],
) -> None:
    """Persist runtime approval state as deterministic JSON."""

    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(requests, key=lambda request: (request.requested_at, request.request_id))
    path.write_text(
        json.dumps(
            {"requests": [request.model_dump(mode="json") for request in ordered]},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _select_request_for_approval(
    requests: list[RuntimeApprovalRequest],
    request_id: str,
) -> RuntimeApprovalRequest:
    if request_id == "latest":
        pending = [
            request
            for request in requests
            if request.status is RuntimeApprovalStatus.PENDING
        ]
        if not pending:
            msg = "no pending runtime approval requests"
            raise RuntimeApprovalError(msg)
        return max(pending, key=lambda request: (request.requested_at, request.request_id))
    for request in requests:
        if request.request_id == request_id:
            return request
    msg = f"runtime approval request not found: {request_id}"
    raise RuntimeApprovalError(msg)


def _latest_request(
    requests: list[RuntimeApprovalRequest],
    *,
    action_id: str,
    status: RuntimeApprovalStatus,
) -> RuntimeApprovalRequest | None:
    matching = [
        request
        for request in requests
        if request.action_id == action_id and request.status is status
    ]
    if not matching:
        return None
    return max(matching, key=lambda request: (request.requested_at, request.request_id))


def _coerce_permission_mode(mode: RuntimePermissionMode | str) -> RuntimePermissionMode:
    if isinstance(mode, RuntimePermissionMode):
        return mode
    return RuntimePermissionMode(mode)


def _coerce_action_risk(risk: RuntimeActionRisk | str) -> RuntimeActionRisk:
    if isinstance(risk, RuntimeActionRisk):
        return risk
    return RuntimeActionRisk(risk)


def _normalise_datetime(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)
