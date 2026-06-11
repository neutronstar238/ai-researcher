import json

from autoresearch.literature import ArxivClient, RateLimiter, RetryConfig, SemanticScholarClient


def test_arxiv_client_parses_mocked_atom_response_with_retry() -> None:
    calls: list[tuple[str, dict[str, str | int]]] = []

    def fake_get(url: str, params: dict[str, str | int]) -> str:
        calls.append((url, params))
        if len(calls) == 1:
            raise RuntimeError("temporary")
        return """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>https://arxiv.org/abs/2606.00001</id>
            <title> Evidence First Research </title>
            <summary> A useful abstract. </summary>
            <published>2026-06-11T00:00:00Z</published>
            <author><name>A. Researcher</name></author>
            <arxiv:doi>10.1234/example</arxiv:doi>
          </entry>
        </feed>"""

    client = ArxivClient(
        http_get=fake_get,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=2, backoff_seconds=0),
    )

    papers = client.search("evidence", limit=1)

    assert len(calls) == 2
    assert papers[0].title == "Evidence First Research"
    assert papers[0].authors == ["A. Researcher"]
    assert papers[0].doi == "10.1234/example"
    assert papers[0].source == "arxiv"


def test_semantic_scholar_client_parses_mocked_response() -> None:
    payload = {
        "data": [
            {
                "title": "Trusted Research Loops",
                "authors": [{"name": "B. Reviewer"}],
                "abstract": "A paper.",
                "year": 2026,
                "venue": "ExampleConf",
                "url": "https://example.com/semantic",
                "citationCount": 7,
                "externalIds": {"DOI": "10.5555/semantic"},
            }
        ]
    }

    client = SemanticScholarClient(
        http_get=lambda _url, _params: json.dumps(payload),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    papers = client.search("trusted", limit=1)

    assert papers[0].title == "Trusted Research Loops"
    assert papers[0].authors == ["B. Reviewer"]
    assert papers[0].venue == "ExampleConf"
    assert papers[0].citation_count == 7
    assert papers[0].source == "semantic_scholar"
