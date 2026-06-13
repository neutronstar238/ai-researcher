import json
import os
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from autoresearch.literature import (
    ArxivClient,
    CircuitBreakerOpenError,
    OpenAlexClient,
    RateLimitCircuitBreaker,
    RateLimiter,
    RetryConfig,
    SemanticScholarClient,
    SourceCircuitStateLockError,
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


def test_openalex_client_parses_mocked_works_response() -> None:
    payload = {
        "results": [
            {
                "id": "https://openalex.org/W123",
                "display_name": "Evidence Bound Research Agents",
                "doi": "https://doi.org/10.1234/openalex",
                "publication_date": "2026-06-01",
                "authorships": [
                    {"author": {"display_name": "C. Analyst"}},
                    {"author": {"display_name": "D. Verifier"}},
                ],
                "abstract_inverted_index": {
                    "Evidence": [0],
                    "bound": [1],
                    "agents": [2],
                },
                "primary_location": {
                    "landing_page_url": "https://doi.org/10.1234/openalex",
                    "source": {"display_name": "Example Journal"},
                },
                "cited_by_count": 11,
            }
        ]
    }

    client = OpenAlexClient(
        http_get=lambda _url, _params, _headers: json.dumps(payload),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    papers = client.search("evidence bound agents", limit=1)

    assert papers[0].title == "Evidence Bound Research Agents"
    assert papers[0].authors == ["C. Analyst", "D. Verifier"]
    assert papers[0].abstract == "Evidence bound agents"
    assert papers[0].venue == "Example Journal"
    assert papers[0].doi == "https://doi.org/10.1234/openalex"
    assert papers[0].url == "https://doi.org/10.1234/openalex"
    assert papers[0].citation_count == 11
    assert papers[0].source == "openalex"


def test_openalex_client_sends_optional_api_key_and_mailto_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_params: list[dict[str, str | int]] = []
    monkeypatch.setenv("OPENALEX_API_KEY", "openalex-key")
    monkeypatch.setenv("OPENALEX_MAILTO", "researcher@example.com")
    monkeypatch.setenv("OPENALEX_MIN_INTERVAL_SECONDS", "2.5")

    def fake_get(
        _url: str,
        params: dict[str, str | int],
        _headers: Mapping[str, str] | None,
    ) -> str:
        seen_params.append(params)
        return json.dumps({"results": []})

    client = OpenAlexClient(
        http_get=fake_get,
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    assert client.search("trusted", limit=250) == []
    assert seen_params[0]["api_key"] == "openalex-key"
    assert seen_params[0]["mailto"] == "researcher@example.com"
    assert seen_params[0]["per_page"] == 100
    assert client.rate_limiter.min_interval_seconds == 2.5


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


def test_semantic_scholar_client_reads_rate_policy_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS", "4.5")
    monkeypatch.setenv("SEMANTIC_SCHOLAR_CIRCUIT_RESET_SECONDS", "12")

    client = SemanticScholarClient(
        api_key="",
        http_get=lambda _url, _params, _headers: json.dumps({"data": []}),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    assert client.rate_limiter.min_interval_seconds == 4.5
    assert client.circuit_breaker.reset_after_seconds == 12.0
    assert client.search("trusted", limit=1) == []


def test_semantic_scholar_client_rejects_invalid_rate_policy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS", "fast")

    with pytest.raises(ValueError, match="SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS"):
        SemanticScholarClient(
            api_key="",
            http_get=lambda _url, _params, _headers: json.dumps({"data": []}),
            retry=RetryConfig(max_attempts=1, backoff_seconds=0),
        )


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


def test_rate_limit_circuit_breaker_persists_open_state(tmp_path) -> None:
    state_path = tmp_path / "source-circuit-breakers.json"
    breaker = RateLimitCircuitBreaker(
        reset_after_seconds=30,
        clock=lambda: 100.0,
        wall_clock=lambda: 1000.0,
        state_path=state_path,
        state_key="semantic_scholar",
    )

    breaker.record_rate_limit(retry_after_seconds=5)

    reopened = RateLimitCircuitBreaker(
        reset_after_seconds=30,
        clock=lambda: 200.0,
        wall_clock=lambda: 1010.0,
        state_path=state_path,
        state_key="semantic_scholar",
    )
    with pytest.raises(CircuitBreakerOpenError, match="20.0s"):
        reopened.raise_if_open()

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(payload) == {"semantic_scholar"}
    assert list(tmp_path.glob(".source-circuit-breakers.json.*.tmp")) == []
    assert not state_path.with_name(f"{state_path.name}.lock").exists()


def test_rate_limit_circuit_breaker_keeps_previous_state_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "source-circuit-breakers.json"
    state_path.write_text('{"semantic_scholar": 9999.0}', encoding="utf-8")
    original_replace = Path.replace

    def fail_state_replace(self: Path, target: str | Path) -> Path:
        if (
            self.name.startswith(f".{state_path.name}.")
            and Path(target) == state_path
        ):
            raise OSError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_state_replace)
    breaker = RateLimitCircuitBreaker(
        reset_after_seconds=30,
        wall_clock=lambda: 1000.0,
        state_path=state_path,
        state_key="semantic_scholar",
    )

    with pytest.raises(OSError, match="replace failed"):
        breaker.record_rate_limit(retry_after_seconds=5)

    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "semantic_scholar": 9999.0
    }
    assert list(tmp_path.glob(".source-circuit-breakers.json.*.tmp")) == []


def test_rate_limit_circuit_breaker_reads_bom_state_file(tmp_path) -> None:
    state_path = tmp_path / "source-circuit-breakers.json"
    state_path.write_text('{"semantic_scholar": 1030.0}', encoding="utf-8-sig")

    breaker = RateLimitCircuitBreaker(
        reset_after_seconds=30,
        wall_clock=lambda: 1000.0,
        state_path=state_path,
        state_key="semantic_scholar",
    )

    with pytest.raises(CircuitBreakerOpenError, match="30.0s"):
        breaker.raise_if_open()


def test_rate_limit_circuit_breaker_blocks_when_state_lock_is_active(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "source-circuit-breakers.json"
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("active lock", encoding="utf-8")
    breaker = RateLimitCircuitBreaker(
        reset_after_seconds=30,
        wall_clock=lambda: 1000.0,
        state_path=state_path,
        state_key="semantic_scholar",
        state_lock_timeout_seconds=0.0,
    )

    with pytest.raises(SourceCircuitStateLockError, match="source circuit state is locked"):
        breaker.record_rate_limit(retry_after_seconds=5)

    assert lock_path.exists()
    assert not state_path.exists()


def test_rate_limit_circuit_breaker_clears_stale_state_lock(tmp_path: Path) -> None:
    state_path = tmp_path / "source-circuit-breakers.json"
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("stale lock", encoding="utf-8")
    os.utime(lock_path, (1.0, 1.0))
    breaker = RateLimitCircuitBreaker(
        reset_after_seconds=30,
        wall_clock=lambda: 1000.0,
        state_path=state_path,
        state_key="semantic_scholar",
        state_stale_lock_seconds=10.0,
    )

    breaker.record_rate_limit(retry_after_seconds=5)

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(payload) == {"semantic_scholar"}
    assert not lock_path.exists()
