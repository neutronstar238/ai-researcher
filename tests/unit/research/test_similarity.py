from datetime import datetime, timezone
from pathlib import Path

import pytest

import autoresearch.research.similarity as similarity_module
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.literature import AcademicPaper
from autoresearch.research import (
    SimilarityCheckConfig,
    SimilarityFinding,
    UnsupportedSimilarityClaimError,
    generate_similarity_queries,
    run_project_similarity_check,
    validate_similarity_findings,
)
from autoresearch.schemas import CandidateStatus, ResearchCandidate


class _RateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval_seconds = min_interval_seconds


class _FakeClient:
    def __init__(
        self,
        papers: list[AcademicPaper],
        rate_limit: float,
        *,
        error: Exception | None = None,
    ) -> None:
        self.papers = papers
        self.rate_limiter = _RateLimiter(rate_limit)
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        self.calls.append((query, limit))
        if self.error is not None:
            raise self.error
        return self.papers


def test_generate_similarity_queries_uses_candidate_and_vault_context(tmp_path: Path) -> None:
    candidate = _candidate()
    _write_similarity_context(tmp_path, candidate)

    queries = generate_similarity_queries(
        candidate,
        vault_root=tmp_path,
        config=SimilarityCheckConfig(max_queries=6),
    )

    origins = {query.origin for query in queries}
    assert "candidate_title" in origins
    assert "method_dataset_limitation" in origins
    assert "negative_result_search" in origins
    assert any(query.origin == "vault_failure_case" for query in queries)
    assert any("exploration/topics/candidate_1.md" in query.vault_paths for query in queries)


def test_project_similarity_check_writes_source_backed_obsidian_summary(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    _write_similarity_context(tmp_path, candidate)
    now = datetime(2026, 6, 12, 2, 0, tzinfo=timezone.utc)
    duplicate = AcademicPaper(
        title="Reduce Weak Evidence In Agent On Review",
        abstract="Agent review workflows with weak evidence.",
        doi="10.1234/direct",
        url="https://example.com/direct",
        source="arxiv",
    )
    adjacent = AcademicPaper(
        title="Agent review benchmark still has weak evidence",
        abstract="Agent methods on the review benchmark report limited evidence quality.",
        url="https://example.com/adjacent",
        source="semantic_scholar",
    )
    arxiv = _FakeClient([duplicate], 3.0)
    semantic = _FakeClient([adjacent], 1.0)

    report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "similarity",
        clients={
            "arxiv": arxiv,
            "semantic_scholar": semantic,
            "broken_source": _FakeClient([], 1.0, error=RuntimeError("offline")),
        },
        now=now,
        config=SimilarityCheckConfig(max_queries=1, max_results_per_source=3),
    )
    cached_report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "similarity",
        clients={"arxiv": arxiv, "semantic_scholar": semantic},
        now=now,
        config=SimilarityCheckConfig(max_queries=1, max_results_per_source=3),
        write_summary=False,
    )

    assert arxiv.calls == [(report.queries[0].text, 3)]
    assert semantic.calls == [(report.queries[0].text, 3)]
    assert len(report.findings) == 2
    assert {finding.classification for finding in report.findings} >= {
        "direct_duplicate",
        "adjacent_work",
    }
    assert report.fetches[-1].error == "RuntimeError: offline"
    assert [fetch.cache_hit for fetch in cached_report.fetches] == [True, True]
    assert report.summary_path is not None
    summary = report.summary_path.read_text(encoding="utf-8")
    assert "## Findings" in summary
    assert "pending verification" in summary
    assert "https://example.com/direct" in summary
    assert "RuntimeError: offline" in summary


def test_project_similarity_default_sources_include_openalex_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    _write_similarity_context(tmp_path, candidate)
    paper = AcademicPaper(
        title="OpenAlex agent review evidence",
        abstract="Agent review workflows need evidence.",
        url="https://openalex.org/W456",
        source="openalex",
    )

    monkeypatch.setattr(
        similarity_module,
        "ArxivClient",
        lambda: _FakeClient([], 3.0),
    )
    monkeypatch.setattr(
        similarity_module,
        "SemanticScholarClient",
        lambda: _FakeClient([], 3.0, error=RuntimeError("rate limited")),
    )
    monkeypatch.setattr(
        similarity_module,
        "OpenAlexClient",
        lambda: _FakeClient([paper], 1.0),
    )

    report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "similarity",
        config=SimilarityCheckConfig(max_queries=1, max_results_per_source=2),
    )

    assert [fetch.source for fetch in report.fetches] == [
        "arxiv",
        "semantic_scholar",
        "openalex",
    ]
    assert report.fetches[1].error == "RuntimeError: rate limited"
    assert report.findings[0].source_database == "openalex"
    assert report.summary_path is not None
    assert "openalex" in report.summary_path.read_text(encoding="utf-8")


def test_similarity_findings_reject_unsupported_claims() -> None:
    finding = SimilarityFinding(
        document_id="doc_1",
        title="Unsupported claim",
        source_uri="https://example.com/paper",
        source_database="arxiv",
        query="agent review",
        retrieved_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        classification="direct_duplicate",
        confidence=0.9,
        evidence_refs=("doc_1",),
        classification_basis=("title similarity 0.9",),
        unsupported_claims=("claims benchmark improvement without source metadata",),
    )

    with pytest.raises(UnsupportedSimilarityClaimError):
        validate_similarity_findings((finding,))


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
        status=CandidateStatus.READY_FOR_REVIEW,
        metadata={
            "method": "agent",
            "dataset": "review",
            "limitation": "weak evidence",
        },
    )


def _write_similarity_context(vault_root: Path, candidate: ResearchCandidate) -> None:
    store = MarkdownKnowledgeStore(vault_root)
    store.write_entry(
        "exploration/topics/candidate_1.md",
        KnowledgeEntry(
            entry_id=candidate.id,
            entry_type=KnowledgeEntryType.RESEARCH_CANDIDATE,
            zone=KnowledgeZone.EXPLORATION,
            title=candidate.title,
            tags=["research-candidate", candidate.status.value],
            keywords=["agent", "review", "weak evidence"],
            source_refs=candidate.evidence_refs,
            body=candidate.research_gap,
        ),
    )
    store.write_entry(
        "exploration/failure_patterns/weak-evidence.md",
        KnowledgeEntry(
            entry_id="failure_weak_evidence",
            entry_type=KnowledgeEntryType.FAILURE_CASE,
            zone=KnowledgeZone.EXPLORATION,
            title="Weak Evidence Failure",
            keywords=["agent", "weak evidence"],
            body="Prior local runs produced weak evidence.",
        ),
    )
