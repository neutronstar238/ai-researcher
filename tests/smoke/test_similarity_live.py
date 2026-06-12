import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.literature import ArxivClient, RetryConfig, SemanticScholarClient
from autoresearch.research import SimilarityCheckConfig, run_project_similarity_check
from autoresearch.schemas import CandidateStatus, ResearchCandidate


@pytest.mark.skipif(
    os.getenv("AUTORESEARCH_LIVE_LITERATURE") != "1",
    reason="Set AUTORESEARCH_LIVE_LITERATURE=1 to run live online similarity checks.",
)
def test_live_project_similarity_check_returns_source_backed_findings(tmp_path: Path) -> None:
    candidate = ResearchCandidate(
        id="candidate_live_similarity",
        title="Machine Learning Benchmark Evidence",
        description="Check adjacent work on machine learning benchmark evidence.",
        research_gap="Machine learning benchmark papers need source-backed evidence checks.",
        novelty_score=0.6,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["live_seed"],
        status=CandidateStatus.READY_FOR_REVIEW,
        metadata={
            "method": "machine learning",
            "dataset": "benchmark",
            "limitation": "evidence",
        },
    )

    report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path / "vault",
        cache_root=tmp_path / "cache",
        clients={
            "arxiv": ArxivClient(retry=RetryConfig(max_attempts=1, backoff_seconds=0)),
            "semantic_scholar": SemanticScholarClient(
                retry=RetryConfig(max_attempts=1, backoff_seconds=0)
            ),
        },
        now=datetime(2026, 6, 12, 0, 0, tzinfo=timezone.utc),
        config=SimilarityCheckConfig(max_queries=1, max_results_per_source=1),
    )

    assert {"arxiv", "semantic_scholar"} <= {fetch.source for fetch in report.fetches}
    assert report.findings, {fetch.source: fetch.error for fetch in report.fetches}
    assert report.summary_path is not None
    summary = report.summary_path.read_text(encoding="utf-8")
    assert "pending verification" in summary
    assert "Source URL/DOI" in summary
    assert any(finding.source_uri.startswith(("http://", "https://", "doi:")) for finding in report.findings)
