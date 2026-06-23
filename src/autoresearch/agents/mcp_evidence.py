"""Evidence ledger for real MCP tool invocations by assigned agents."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from autoresearch.agents.profiles import AgentProfile, McpApprovalPolicy

MCP_INVOCATION_EVIDENCE_KIND = "mcp_tool_invocation_evidence"
MCP_INVOCATION_EVIDENCE_POLICY = (
    "MCP invocation evidence proves only that the named agent recorded a call to the "
    "named MCP server/tool with hashed request and result artifacts. Scientific claims, "
    "citation validity, benchmark metrics, novelty, and publication readiness still require "
    "validated source, experiment, or review evidence."
)


class McpInvocationStatus(str, Enum):
    """Outcome of one MCP tool invocation attempt."""

    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    APPROVAL_REQUIRED = "approval_required"


class AgentMcpInvocationEvidence(BaseModel):
    """Independent evidence that a bound MCP tool was invoked or blocked."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(default_factory=lambda: f"mcp_invocation_{uuid4().hex}")
    evidence_kind: str = MCP_INVOCATION_EVIDENCE_KIND
    agent_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    cycle_id: str = Field(min_length=1)
    server_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    status: McpInvocationStatus
    request_artifact_ref: str = Field(min_length=1)
    request_sha256: str = Field(min_length=64, max_length=64)
    response_artifact_ref: str | None = None
    response_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    runtime_approval_request_id: str | None = Field(default=None, min_length=1)
    approved_by: str | None = Field(default=None, min_length=1)
    result_summary: str = Field(min_length=1)
    error_type: str | None = Field(default=None, min_length=1)
    artifact_refs: tuple[str, ...] = ()
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_policy: str = MCP_INVOCATION_EVIDENCE_POLICY


class McpInvocationEvidenceValidation(BaseModel):
    """Validation result for one MCP invocation evidence record."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    passed: bool
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence_policy: str = MCP_INVOCATION_EVIDENCE_POLICY


def build_mcp_invocation_evidence(
    *,
    profile: AgentProfile,
    project_id: str,
    cycle_id: str,
    server_id: str,
    tool_name: str,
    status: McpInvocationStatus,
    request_artifact: Path | str,
    response_artifact: Path | str | None = None,
    base_dir: Path | str = Path("."),
    runtime_approval_request_id: str | None = None,
    approved_by: str | None = None,
    result_summary: str = "MCP tool invocation recorded.",
    error_type: str | None = None,
    artifact_refs: Iterable[str] = (),
) -> AgentMcpInvocationEvidence:
    """Build a non-secret MCP invocation evidence record from artifact files."""

    root = Path(base_dir)
    request_path = _resolve_existing_path(request_artifact, root)
    request_ref = _artifact_ref(request_path, root)
    if request_ref is None:
        msg = "request artifact ref could not be resolved"
        raise ValueError(msg)
    response_path = (
        _resolve_existing_path(response_artifact, root)
        if response_artifact is not None
        else None
    )
    evidence = AgentMcpInvocationEvidence(
        agent_id=profile.agent_id,
        project_id=project_id,
        cycle_id=cycle_id,
        server_id=server_id,
        tool_name=tool_name,
        status=status,
        request_artifact_ref=request_ref,
        request_sha256=_sha256_file(request_path),
        response_artifact_ref=_artifact_ref(response_path, root)
        if response_path is not None
        else None,
        response_sha256=_sha256_file(response_path) if response_path is not None else None,
        runtime_approval_request_id=runtime_approval_request_id,
        approved_by=approved_by,
        result_summary=result_summary,
        error_type=error_type,
        artifact_refs=tuple(str(ref) for ref in artifact_refs if str(ref)),
    )
    validation = validate_mcp_invocation_evidence(evidence, profile)
    if not validation.passed:
        issues = "; ".join(validation.issues)
        msg = f"MCP invocation evidence failed validation: {issues}"
        raise ValueError(msg)
    return evidence


def validate_mcp_invocation_evidence(
    evidence: AgentMcpInvocationEvidence,
    profile: AgentProfile,
) -> McpInvocationEvidenceValidation:
    """Validate invocation evidence against one agent profile's MCP contract."""

    issues: list[str] = []
    warnings: list[str] = []
    if evidence.agent_id != profile.agent_id:
        issues.append("evidence agent_id does not match profile agent_id")
    server = next(
        (item for item in profile.mcp_servers if item.server_id == evidence.server_id),
        None,
    )
    if server is None:
        issues.append("evidence server_id is not bound to this profile")
    else:
        if evidence.tool_name not in server.allowed_tools:
            issues.append("evidence tool_name is not in the profile MCP allowlist")
        if (
            server.approval_policy is McpApprovalPolicy.ALLOW_ALL
            and not evidence.runtime_approval_request_id
            and not evidence.approved_by
        ):
            issues.append("allow_all MCP evidence requires approval or operator identity")
        if (
            server.approval_policy is McpApprovalPolicy.APPROVE_DANGEROUS
            and evidence.status is McpInvocationStatus.APPROVAL_REQUIRED
            and not evidence.runtime_approval_request_id
        ):
            issues.append("approval_required evidence requires a runtime approval request id")
        if (
            server.approval_policy is McpApprovalPolicy.APPROVE_DANGEROUS
            and evidence.status is McpInvocationStatus.SUCCESS
            and not evidence.runtime_approval_request_id
        ):
            warnings.append("successful approve_dangerous MCP evidence has no approval request id")

    if evidence.status is McpInvocationStatus.SUCCESS and not evidence.response_sha256:
        issues.append("successful MCP invocation evidence requires a response artifact hash")
    if evidence.status is McpInvocationStatus.FAILED and not evidence.error_type:
        warnings.append("failed MCP invocation evidence should include error_type")
    return McpInvocationEvidenceValidation(
        evidence_id=evidence.evidence_id,
        passed=not issues,
        issues=tuple(dict.fromkeys(issues)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def append_mcp_invocation_evidence(
    ledger_path: Path | str,
    evidence: AgentMcpInvocationEvidence,
) -> Path:
    """Append one invocation evidence record to a JSONL ledger."""

    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence.model_dump(mode="json"), sort_keys=True))
        handle.write("\n")
    return path


def load_mcp_invocation_evidence(
    ledger_path: Path | str,
) -> tuple[AgentMcpInvocationEvidence, ...]:
    """Load invocation evidence records from a JSONL ledger."""

    path = Path(ledger_path)
    if not path.exists():
        return ()
    records: list[AgentMcpInvocationEvidence] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        records.append(AgentMcpInvocationEvidence.model_validate_json(stripped))
    return tuple(records)


def write_mcp_invocation_validation_report(
    path: Path | str,
    validations: Iterable[McpInvocationEvidenceValidation],
) -> Path:
    """Write a deterministic validation report for invocation evidence."""

    records = tuple(validations)
    payload = {
        "passed": all(record.passed for record in records),
        "record_count": len(records),
        "failed_count": sum(1 for record in records if not record.passed),
        "warning_count": sum(len(record.warnings) for record in records),
        "validations": [record.model_dump(mode="json") for record in records],
        "evidence_policy": MCP_INVOCATION_EVIDENCE_POLICY,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def _resolve_existing_path(path_value: Path | str, base_dir: Path) -> Path:
    path = Path(path_value)
    candidates = [path] if path.is_absolute() else [base_dir / path, Path.cwd() / path]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    msg = f"artifact file does not exist: {path_value}"
    raise FileNotFoundError(msg)


def _artifact_ref(path: Path | None, base_dir: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.relative_to(base_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
