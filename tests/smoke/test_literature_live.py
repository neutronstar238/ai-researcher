import os

import pytest

from autoresearch.literature import ArxivClient, SemanticScholarClient


@pytest.mark.skipif(
    os.getenv("AUTORESEARCH_LIVE_LITERATURE") != "1",
    reason="Set AUTORESEARCH_LIVE_LITERATURE=1 to run optional live literature API smoke tests.",
)
def test_optional_live_literature_clients_return_results() -> None:
    arxiv_results = ArxivClient().search("machine learning", limit=1)
    semantic_results = SemanticScholarClient().search("machine learning", limit=1)

    assert arxiv_results
    assert semantic_results
