import os
from urllib.error import HTTPError, URLError

import pytest

from autoresearch.literature import ArxivClient, RetryConfig, SemanticScholarClient


@pytest.mark.skipif(
    os.getenv("AUTORESEARCH_LIVE_APIS") != "1"
    and os.getenv("AUTORESEARCH_LIVE_LITERATURE") != "1",
    reason="Set AUTORESEARCH_LIVE_APIS=1 to run live literature API smoke tests.",
)
def test_optional_live_literature_clients_return_results() -> None:
    clients = {
        "arxiv": ArxivClient(retry=RetryConfig(max_attempts=1, backoff_seconds=0)),
        "semantic_scholar": SemanticScholarClient(
            retry=RetryConfig(max_attempts=1, backoff_seconds=0)
        ),
    }
    results: dict[str, int] = {}
    errors: dict[str, str] = {}
    for source, client in clients.items():
        try:
            results[source] = len(client.search("machine learning", limit=1))
        except (HTTPError, TimeoutError, URLError) as exc:
            errors[source] = f"{type(exc).__name__}: {exc}"

    assert any(count > 0 for count in results.values()), errors
