from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.research import (
    CandidateGenerationConfig,
    CandidateLifecycleError,
    CandidateVaultLinks,
    TrendGapAnalysisConfig,
    analyze_trends_and_gaps,
    generate_research_candidates,
    store_candidate_lifecycle_entry,
    transition_candidate_status,
)
from autoresearch.schemas import CandidateStatus, DocumentRecord, ResearchCandidate


def _doc(doc_id: str, title: str, abstract: str) -> DocumentRecord:
    return DocumentRecord(
        id=doc_id,
        title=title,
        source_uri=f"https://example.com/{doc_id}",
        abstract=abstract,
        publication_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        tags=["arxiv"],
    )


def test_candidate_generator_ranks_sample_candidates_deterministically() -> None:
    documents = [
        _doc(
            "doc_1",
            "Evidence graph retrieval with limited reproducibility",
            "Transformer retrieval systems on the AutoResearch benchmark show limited reproducibility.",
        ),
        _doc(
            "doc_2",
            "Transformer retrieval for weak evidence",
            "Retrieval with transformer methods on the AutoResearch benchmark faces limited reproducibility.",
        ),
        _doc(
            "doc_3",
            "Diffusion planning with high cost",
            "Diffusion agents using the Planning benchmark report high cost and latency.",
        ),
    ]

    candidates = generate_research_candidates(
        documents,
        config=CandidateGenerationConfig(max_candidates=3, min_ready_evidence_refs=2),
    )

    assert [candidate.metadata["cluster_key"] for candidate in candidates] == [
        "transformer|limited reproducibility|autoresearch",
        "diffusion|high cost|planning",
    ]
    assert candidates[0].status is CandidateStatus.READY_FOR_REVIEW
    assert candidates[0].evidence_refs == ["doc_1", "doc_2"]
    assert candidates[0].metadata["evidence_coverage"] == 0.6667
    assert candidates[1].status is CandidateStatus.DRAFT
    assert candidates[1].evidence_refs == ["doc_3"]


def test_candidate_generator_marks_low_evidence_candidates_as_draft() -> None:
    candidates = generate_research_candidates(
        [
            _doc(
                "doc_1",
                "Agent evaluation with weak evidence",
                "Agent workflows using the Review benchmark report weak evidence.",
            )
        ],
        config=CandidateGenerationConfig(min_ready_evidence_refs=2),
    )

    assert len(candidates) == 1
    assert candidates[0].status is CandidateStatus.DRAFT
    assert candidates[0].evidence_refs == ["doc_1"]


def test_candidate_lifecycle_allows_only_legal_status_transitions() -> None:
    candidate = _candidate()

    ready = transition_candidate_status(candidate, CandidateStatus.READY_FOR_REVIEW)
    approved = transition_candidate_status(ready, CandidateStatus.APPROVED)
    active = transition_candidate_status(approved, CandidateStatus.ACTIVE)
    completed = transition_candidate_status(active, CandidateStatus.COMPLETED)
    archived = transition_candidate_status(completed, CandidateStatus.ARCHIVED)

    assert archived.status is CandidateStatus.ARCHIVED
    assert archived.metadata["status_history"] == [
        {"from": "draft", "to": "ready_for_review"},
        {"from": "ready_for_review", "to": "approved"},
        {"from": "approved", "to": "active"},
        {"from": "active", "to": "completed"},
        {"from": "completed", "to": "archived"},
    ]
    with pytest.raises(CandidateLifecycleError, match="draft -> active"):
        transition_candidate_status(candidate, CandidateStatus.ACTIVE)


def test_store_candidate_lifecycle_entry_writes_obsidian_links(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    path = store_candidate_lifecycle_entry(
        candidate,
        vault_root=tmp_path,
        links=CandidateVaultLinks(
            source_papers=("doc_2",),
            topic_index_entries=("exploration/index",),
            prior_failures=("failure_case_1",),
            useful_skills=("skill_baseline_first",),
            strategy_cards=("strategy_card_1",),
        ),
    )

    markdown = path.read_text(encoding="utf-8")
    entry = MarkdownKnowledgeStore(tmp_path).read_entry(
        Path("exploration") / "topics" / "candidate_1.md"
    )
    index = (tmp_path / "exploration" / "index.md").read_text(encoding="utf-8")

    assert path == tmp_path / "exploration" / "topics" / "candidate_1.md"
    assert entry.entry_type.value == "research_candidate"
    assert "[[doc_1]]" in markdown
    assert "[[doc_2]]" in markdown
    assert "[[failure_case_1]]" in markdown
    assert "[[skill_baseline_first]]" in markdown
    assert "[[strategy_card_1]]" in markdown
    assert "[[candidate_1|Reduce Weak Evidence In Agent On Review]]" in index


def test_analyze_trends_and_gaps_compares_literature_with_vault_paths(
    tmp_path: Path,
) -> None:
    store = MarkdownKnowledgeStore(tmp_path)
    store.write_entry(
        "exploration/methodologies/agent.md",
        KnowledgeEntry(
            entry_id="method_agent",
            entry_type=KnowledgeEntryType.METHOD_CARD,
            zone=KnowledgeZone.EXPLORATION,
            title="Agent Method",
            keywords=["agent"],
            body="Agent workflows for evidence collection.",
        ),
    )
    store.write_entry(
        "projects/project-1/experience/review.md",
        KnowledgeEntry(
            entry_id="experience_review",
            entry_type=KnowledgeEntryType.PROJECT_PROGRESS,
            zone=KnowledgeZone.PROJECT,
            project_id="project-1",
            title="Review Experience",
            keywords=["weak evidence"],
            body="Prior project experience found weak evidence in agent review workflows.",
        ),
    )

    updates = analyze_trends_and_gaps(
        [
            _doc(
                "doc_1",
                "Agent evaluation with weak evidence",
                "Agent workflows using the Review benchmark report weak evidence.",
            ),
            _doc(
                "doc_2",
                "Agent review benchmark has weak evidence",
                "Agent systems on the Review benchmark still report weak evidence.",
            ),
        ],
        vault_root=tmp_path,
        config=TrendGapAnalysisConfig(max_updates=2, min_ready_evidence_refs=2),
    )

    assert len(updates) == 1
    update = updates[0]
    assert update.evidence_refs == ("doc_1", "doc_2")
    assert "exploration/index.md" in update.vault_paths
    assert "exploration/methodologies/agent.md" in update.vault_paths
    assert "projects/project-1/experience/review.md" in update.vault_paths
    assert update.gap_reasons == ("missing dataset card for review",)
    assert update.missing_vault_paths == ("exploration/datasets/review.md",)
    assert update.candidate.metadata["gap_analysis"]["evidence_refs"] == ["doc_1", "doc_2"]
    assert update.candidate.metadata["gap_analysis"]["vault_paths"]


def test_analyze_trends_and_gaps_skips_candidates_without_source_evidence(
    tmp_path: Path,
) -> None:
    updates = analyze_trends_and_gaps([], vault_root=tmp_path)

    assert updates == []


def _candidate() -> ResearchCandidate:
    return ResearchCandidate(
        id="candidate_1",
        title="Reduce Weak Evidence In Agent On Review",
        description="Explore stronger evidence capture for agent review workflows.",
        research_gap="Agent review workflows still produce weak evidence.",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["doc_1"],
        related_document_ids=["doc_1"],
        status=CandidateStatus.DRAFT,
        metadata={
            "method": "agent",
            "dataset": "review",
            "limitation": "weak evidence",
        },
    )
