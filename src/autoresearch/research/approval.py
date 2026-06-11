"""Human approval gate for candidate selection and project creation."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from autoresearch.knowledge import VaultLayout, create_vault_layout
from autoresearch.schemas import ResearchCandidate


class ApprovalRecord(BaseModel):
    """Human approval record for a research candidate."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(default_factory=lambda: f"approval_{uuid4().hex}")
    candidate_id: str
    approved_by: str = Field(min_length=1)
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str = Field(min_length=1)
    approved: bool = True


class ProjectAgentContext(BaseModel):
    """Project context created only after candidate approval."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    candidate_id: str
    approval_id: str
    project_path: Path


def create_project_from_approved_candidate(
    *,
    candidate: ResearchCandidate,
    approval: ApprovalRecord | None,
    vault_root: Path | str,
    project_id: str | None = None,
) -> ProjectAgentContext:
    """Create a project directory and Project Agent context only after approval."""

    if approval is None:
        msg = "approval record is required before project creation"
        raise PermissionError(msg)
    if not approval.approved:
        msg = "approval record must be approved before project creation"
        raise PermissionError(msg)
    if approval.candidate_id != candidate.id:
        msg = "approval record candidate_id does not match candidate"
        raise ValueError(msg)

    resolved_project_id = project_id or _project_id_from_candidate(candidate)
    layout: VaultLayout = create_vault_layout(vault_root, resolved_project_id)
    return ProjectAgentContext(
        project_id=resolved_project_id,
        candidate_id=candidate.id,
        approval_id=approval.approval_id,
        project_path=layout.project,
    )


def _project_id_from_candidate(candidate: ResearchCandidate) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", candidate.title.casefold()).strip("-")
    short_id = candidate.id.split("_")[-1][:8]
    return f"{slug or 'project'}-{short_id}"
