from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.research import (
    ApprovalRecord,
    ProjectSimilarityReport,
    SimilarityFetchRecord,
    SimilarityFinding,
    SimilarityQuery,
    create_project_from_approved_candidate,
)
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
    similarity_report = _similarity_report(tmp_path, candidate)

    context = create_project_from_approved_candidate(
        candidate=candidate,
        approval=approval,
        similarity_report=similarity_report,
        vault_root=tmp_path,
        project_id="project-001",
    )

    assert context.project_id == "project-001"
    assert context.candidate_id == candidate.id
    assert context.approval_id == approval.approval_id
    assert (tmp_path / "projects" / "project-001" / "knowledge").is_dir()
    assert context.similarity_summary_path.is_file()
    assert "[[exploration/topics/similarity_check_candidate_1234567890]]" in (
        context.similarity_summary_path.read_text(encoding="utf-8")
    )


def test_project_creation_requires_similarity_report_after_approval(tmp_path: Path) -> None:
    candidate = _candidate()
    approval = ApprovalRecord(
        candidate_id=candidate.id,
        approved_by="user",
        approved_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        notes="Approved after review.",
    )

    with pytest.raises(PermissionError, match="similarity report"):
        create_project_from_approved_candidate(
            candidate=candidate,
            approval=approval,
            vault_root=tmp_path,
            project_id="project-001",
        )

    assert not (tmp_path / "projects" / "project-001").exists()


def test_approval_record_requires_user_timestamp_candidate_and_notes() -> None:
    with pytest.raises(ValidationError):
        ApprovalRecord(candidate_id="candidate_1", approved_by="", notes="")


def _similarity_report(tmp_path: Path, candidate: ResearchCandidate) -> ProjectSimilarityReport:
    summary_path = tmp_path / "exploration" / "topics" / f"similarity_check_{candidate.id}.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("# Similarity check\n", encoding="utf-8")
    retrieved_at = datetime(2026, 6, 12, tzinfo=timezone.utc)
    return ProjectSimilarityReport(
        candidate_id=candidate.id,
        queries=(
            SimilarityQuery(
                text="evidence first retrieval",
                origin="candidate_title",
                vault_paths=("exploration/topics/candidate.md",),
            ),
        ),
        fetches=(
            SimilarityFetchRecord(
                source="arxiv",
                query="evidence first retrieval",
                cache_key="cache-key",
                cache_hit=False,
                paper_count=1,
                rate_limit_seconds=3.0,
                vault_paths=("exploration/topics/candidate.md",),
            ),
        ),
        papers=(),
        documents=(),
        findings=(
            SimilarityFinding(
                document_id="doc_1",
                title="Evidence First Retrieval",
                source_uri="https://example.com/doc_1",
                source_database="arxiv",
                query="evidence first retrieval",
                retrieved_at=retrieved_at,
                classification="direct_duplicate",
                confidence=0.9,
                evidence_refs=("doc_1", "https://example.com/doc_1"),
                classification_basis=("title similarity 0.9",),
            ),
        ),
        summary_path=summary_path,
    )
