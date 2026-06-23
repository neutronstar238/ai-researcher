import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.literature import LiteratureRefreshConfig, run_daily_literature_refresh


@pytest.mark.skipif(
    os.getenv("AUTORESEARCH_LIVE_APIS") != "1"
    and os.getenv("AUTORESEARCH_LIVE_LITERATURE") != "1",
    reason="Set AUTORESEARCH_LIVE_APIS=1 to run live literature refresh tests.",
)
def test_live_daily_literature_refresh_returns_real_documents(tmp_path: Path) -> None:
    store = MarkdownKnowledgeStore(tmp_path / "vault")
    store.write_entry(
        "exploration/topics/live-candidate.md",
        KnowledgeEntry(
            entry_id="live_candidate",
            entry_type=KnowledgeEntryType.RESEARCH_CANDIDATE,
            zone=KnowledgeZone.EXPLORATION,
            title="Machine Learning Benchmark Evidence",
            tags=["research-candidate", "ready_for_review"],
            keywords=["machine learning", "benchmark", "evidence"],
            body="Search for real machine learning benchmark papers with evidence metadata.",
        ),
    )

    report = run_daily_literature_refresh(
        vault_root=tmp_path / "vault",
        cache_root=tmp_path / "cache",
        now=datetime(2026, 6, 12, 0, 0, tzinfo=timezone.utc),
        config=LiteratureRefreshConfig(max_queries=1, max_results_per_source=1),
    )

    sources = {fetch.source for fetch in report.fetches}
    document_sources = {tag for document in report.documents for tag in document.tags}

    assert {"arxiv", "openalex"} <= sources
    assert report.documents, {fetch.source: fetch.error for fetch in report.fetches}
    assert {"arxiv", "openalex"} & document_sources
    assert report.summary_path is not None
    assert "pending verification" in report.summary_path.read_text(encoding="utf-8")
