from datetime import datetime, timezone

from autoresearch.research import CandidateGenerationConfig, generate_research_candidates
from autoresearch.schemas import CandidateStatus, DocumentRecord


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
