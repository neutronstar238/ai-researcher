from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.research import ApprovalRecord, create_project_from_approved_candidate
from autoresearch.schemas import ResearchCandidate


def _candidate() -> ResearchCandidate:
    return ResearchCandidate(
        id="candidate_1234567890",
        title="Evidence First Retrieval",
        description="A candidate.",
        research_gap="A gap.",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["doc_1"],
    )


def test_project_creation_rejects_missing_approval_record(tmp_path: Path) -> None:
    candidate = _candidate()

    with pytest.raises(PermissionError):
        create_project_from_approved_candidate(
            candidate=candidate,
            approval=None,
            vault_root=tmp_path,
            project_id="project-001",
        )

    assert not (tmp_path / "projects" / "project-001").exists()


def test_project_creation_requires_matching_approval_record(tmp_path: Path) -> None:
    candidate = _candidate()
    approval = ApprovalRecord(
        candidate_id="candidate_other",
        approved_by="user",
        approved_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        notes="Looks useful.",
    )

    with pytest.raises(ValueError):
        create_project_from_approved_candidate(
            candidate=candidate,
            approval=approval,
            vault_root=tmp_path,
            project_id="project-001",
        )

    assert not (tmp_path / "projects" / "project-001").exists()


def test_project_creation_creates_project_context_after_approval(tmp_path: Path) -> None:
    candidate = _candidate()
    approval = ApprovalRecord(
        candidate_id=candidate.id,
        approved_by="user",
        approved_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        notes="Approved for a small trusted-loop experiment.",
    )

    context = create_project_from_approved_candidate(
        candidate=candidate,
        approval=approval,
        vault_root=tmp_path,
        project_id="project-001",
    )

    assert context.project_id == "project-001"
    assert context.candidate_id == candidate.id
    assert context.approval_id == approval.approval_id
    assert (tmp_path / "projects" / "project-001" / "knowledge").is_dir()


def test_approval_record_requires_user_timestamp_candidate_and_notes() -> None:
    with pytest.raises(ValidationError):
        ApprovalRecord(candidate_id="candidate_1", approved_by="", notes="")
