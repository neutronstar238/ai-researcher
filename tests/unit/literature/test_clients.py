import json
from collections.abc import Mapping
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from autoresearch.literature import (
    ArxivClient,
    CircuitBreakerOpenError,
    RateLimitCircuitBreaker,
    RateLimiter,
    RetryConfig,
    SemanticScholarClient,
    SourceRateLimitError,
)


def test_arxiv_client_parses_mocked_atom_response_with_retry() -> None:
    calls: list[tuple[str, dict[str, str | int]]] = []

    def fake_get(
        url: str,
        params: dict[str, str | int],
        _headers: Mapping[str, str] | None,
    ) -> str:
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
        http_get=lambda _url, _params, _headers: json.dumps(payload),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    papers = client.search("trusted", limit=1)

    assert papers[0].title == "Trusted Research Loops"
    assert papers[0].authors == ["B. Reviewer"]
    assert papers[0].venue == "ExampleConf"
    assert papers[0].citation_count == 7
    assert papers[0].source == "semantic_scholar"


def test_semantic_scholar_client_sends_optional_api_key_header() -> None:
    seen_headers: list[Mapping[str, str] | None] = []

    def fake_get(
        _url: str,
        _params: dict[str, str | int],
        headers: Mapping[str, str] | None,
    ) -> str:
        seen_headers.append(headers)
        return json.dumps({"data": []})

    client = SemanticScholarClient(
        api_key="semantic-key",
        http_get=fake_get,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    assert client.search("trusted", limit=1) == []
    assert seen_headers == [{"x-api-key": "semantic-key"}]


def test_semantic_scholar_client_uses_exponential_backoff_before_success() -> None:
    calls = 0
    sleeps: list[float] = []

    def fake_get(
        _url: str,
        _params: dict[str, str | int],
        _headers: Mapping[str, str] | None,
    ) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise URLError("temporary reset")
        return json.dumps({"data": []})

    client = SemanticScholarClient(
        http_get=fake_get,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=2, backoff_seconds=0.25),
        sleep=sleeps.append,
    )

    assert client.search("trusted", limit=1) == []
    assert calls == 2
    assert sleeps == [0.25]


def test_semantic_scholar_429_opens_circuit_breaker_without_hammering() -> None:
    calls = 0

    def fake_get(
        _url: str,
        _params: dict[str, str | int],
        _headers: Mapping[str, str] | None,
    ) -> str:
        nonlocal calls
        calls += 1
        raise HTTPError(
            url="https://api.semanticscholar.org/graph/v1/paper/search",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "5"},
            fp=BytesIO(b"rate limited"),
        )

    breaker = RateLimitCircuitBreaker(
        reset_after_seconds=30,
        clock=lambda: 100.0,
    )
    client = SemanticScholarClient(
        http_get=fake_get,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=3, backoff_seconds=0),
        circuit_breaker=breaker,
    )

    with pytest.raises(SourceRateLimitError, match="circuit open"):
        client.search("trusted", limit=1)
    with pytest.raises(CircuitBreakerOpenError):
        client.search("trusted", limit=1)

    assert calls == 1
