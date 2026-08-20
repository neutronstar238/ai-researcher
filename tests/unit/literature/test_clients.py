import json
import os
from collections.abc import Mapping
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from autoresearch.literature import (
    AcademicPaper,
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
from autoresearch.literature.clients import (
    OPENALEX_TITLE_ABSTRACT_FILTER_PREFIX,
    SourceHTTPAttemptEvent,
    bind_source_http_attempt_observer,
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
    assert papers[0].repository_doi == "10.48550/arXiv.2606.00001"
    assert papers[0].citation_count is None
    assert papers[0].citation_count_source is None
    assert papers[0].citation_count_as_of is None
    assert papers[0].publication_status == "preprint"
    assert papers[0].status_source == "arxiv_atom"
    assert papers[0].status_as_of == date.today()
    assert papers[0].source == "arxiv"


def test_source_http_attempt_observer_sees_each_physical_retry_without_credentials() -> None:
    events: list[SourceHTTPAttemptEvent] = []
    calls = 0

    def fake_get(
        _url: str,
        params: dict[str, str | int],
        _headers: Mapping[str, str] | None,
    ) -> str:
        nonlocal calls
        calls += 1
        assert params["api_key"] == "test-secret-key"
        if calls == 1:
            raise URLError("first physical attempt failed")
        return '{"results": []}'

    client = OpenAlexClient(
        http_get=fake_get,
        api_key="test-secret-key",
        mailto="private@example.org",
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=2, backoff_seconds=0),
        sleep=lambda _seconds: None,
    )

    with bind_source_http_attempt_observer(events.append):
        assert client.search("topic-neutral mechanism", limit=2) == []

    assert calls == 2
    assert [(item.phase, item.attempt_index) for item in events] == [
        ("reservation", 1),
        ("failed", 1),
        ("reservation", 2),
        ("completed", 2),
    ]
    assert all(item.source == "openalex" for item in events)
    assert all(item.operation == "literature_search" for item in events)
    assert all("api_key" not in item.public_params for item in events)
    assert all("mailto" not in item.public_params for item in events)
    assert all("test-secret-key" not in repr(item) for item in events)
    assert all("private@example.org" not in repr(item) for item in events)


def test_nested_source_http_attempt_observers_fan_out_once_each() -> None:
    outer: list[tuple[str, int]] = []
    inner: list[tuple[str, int]] = []
    client = OpenAlexClient(
        http_get=lambda _url, _params, _headers: '{"results": []}',
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    with (
        bind_source_http_attempt_observer(
            lambda event: outer.append((event.phase, event.attempt_index))
        ),
        bind_source_http_attempt_observer(
            lambda event: inner.append((event.phase, event.attempt_index))
        ),
    ):
        assert client.search("topic-neutral nested observer", limit=1) == []

    expected = [("reservation", 1), ("completed", 1)]
    assert outer == expected
    assert inner == expected


def test_arxiv_repository_doi_is_separate_from_publication_doi() -> None:
    atom = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>https://arxiv.org/abs/hep-th/9901001v2</id>
        <title>Repository-only preprint</title>
        <published>1999-01-01T00:00:00Z</published>
        <arxiv:comment>The analysis is not strong enough to prove the conjecture</arxiv:comment>
      </entry>
    </feed>"""
    client = ArxivClient(
        http_get=lambda _url, _params, _headers: atom,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    paper = client.search("repository", limit=1)[0]

    assert paper.doi is None
    assert paper.repository_doi == "10.48550/arXiv.hep-th/9901001"
    assert paper.publication_status == "preprint"


def test_arxiv_status_verification_is_explicit_and_rate_limited() -> None:
    calls: list[str] = []

    def fake_get(
        url: str,
        _params: dict[str, str | int],
        _headers: Mapping[str, str] | None,
    ) -> str:
        calls.append(url)
        return '<span class="error">This paper has been withdrawn by its author</span>'

    client = ArxivClient(
        http_get=fake_get,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )
    paper = client.verify_status(
        AcademicPaper(
            title="A withdrawn preprint",
            url="https://arxiv.org/abs/2110.15271v2",
            publication_status="preprint",
            source="arxiv",
        )
    )

    assert calls == ["https://arxiv.org/abs/2110.15271v2"]
    assert paper.publication_status == "withdrawn"
    assert paper.status_source == "arxiv_abs"
    assert paper.status_as_of == date.today()


def test_arxiv_status_verification_ignores_generic_withdrawal_policy_text() -> None:
    client = ArxivClient(
        http_get=lambda _url, _params, _headers: (
            "<main>Active preprint</main><footer>Read our withdrawal policy</footer>"
        ),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )
    original = AcademicPaper(
        title="Active preprint",
        url="https://arxiv.org/abs/2606.00001",
        publication_status="preprint",
        status_source="arxiv_atom",
        source="arxiv",
    )

    verified = client.verify_status(original)

    assert verified is original
    assert verified.publication_status == "preprint"
    assert verified.status_source == "arxiv_atom"


def test_arxiv_429_opens_circuit_breaker_without_hammering() -> None:
    breaker = RateLimitCircuitBreaker(failure_threshold=1, reset_after_seconds=60.0)
    calls = 0

    def fake_get(
        url: str,
        _params: dict[str, str | int],
        _headers: Mapping[str, str] | None,
    ) -> str:
        nonlocal calls
        calls += 1
        raise HTTPError(url, 429, "Too Many Requests", {"Retry-After": "30"}, None)

    client = ArxivClient(
        http_get=fake_get,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=3, backoff_seconds=0),
        circuit_breaker=breaker,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SourceRateLimitError, match="429"):
        client.search("prime gaps", limit=1)
    with pytest.raises(CircuitBreakerOpenError):
        client.search("prime gaps", limit=1)

    # One physical attempt opens the circuit; the second search is refused before
    # any further HTTP request is made.
    assert calls == 1
    assert breaker.remaining_seconds() > 0


def test_arxiv_429_honors_retry_after_cooldown() -> None:
    breaker = RateLimitCircuitBreaker(failure_threshold=1, reset_after_seconds=60.0)

    def fake_get(
        url: str,
        _params: dict[str, str | int],
        _headers: Mapping[str, str] | None,
    ) -> str:
        raise HTTPError(url, 429, "Too Many Requests", {"Retry-After": "120"}, None)

    client = ArxivClient(
        http_get=fake_get,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
        circuit_breaker=breaker,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SourceRateLimitError):
        client.search("prime gaps", limit=1)

    assert breaker.remaining_seconds() > 60.0


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
    assert papers[0].citation_count_source == "semantic_scholar"
    assert papers[0].citation_count_as_of == date.today()
    assert papers[0].source == "semantic_scholar"


def test_semantic_scholar_missing_citation_count_remains_unknown() -> None:
    payload = {"data": [{"title": "Uncounted paper"}]}
    client = SemanticScholarClient(
        http_get=lambda _url, _params, _headers: json.dumps(payload),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    paper = client.search("uncounted", limit=1)[0]

    assert paper.citation_count is None
    assert paper.citation_count_source is None
    assert paper.citation_count_as_of is None


def test_semantic_scholar_separates_arxiv_repository_doi() -> None:
    payload = {
        "data": [
            {
                "title": "Repository-only preprint",
                "externalIds": {"DOI": "10.48550/ArXiV.2110.15271"},
            }
        ]
    }
    client = SemanticScholarClient(
        http_get=lambda _url, _params, _headers: json.dumps(payload),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    paper = client.search("repository", limit=1)[0]

    assert paper.doi is None
    assert paper.repository_doi == "10.48550/arxiv.2110.15271"


def test_semantic_scholar_separates_zenodo_repository_doi() -> None:
    payload = {
        "data": [
            {
                "title": "Archived technical record",
                "externalIds": {"DOI": "https://doi.org/10.5281/ZENODO.1234567"},
            }
        ]
    }
    client = SemanticScholarClient(
        http_get=lambda _url, _params, _headers: json.dumps(payload),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    paper = client.search("archived record", limit=1)[0]

    assert paper.doi is None
    assert paper.repository_doi == "10.5281/zenodo.1234567"


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
                "type": "article",
                "is_retracted": False,
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
    assert papers[0].citation_count_source == "openalex"
    assert papers[0].citation_count_as_of == date.today()
    assert papers[0].publication_status == "published"
    assert papers[0].status_source == "openalex"
    assert papers[0].status_as_of == date.today()
    assert papers[0].source == "openalex"


def test_openalex_skips_blank_titles_without_discarding_valid_siblings() -> None:
    payload = {
        "results": [
            {"id": "https://openalex.org/W1", "display_name": "First valid work"},
            {"id": "https://openalex.org/W2", "display_name": ""},
            {"id": "https://openalex.org/W3", "display_name": " \t\n "},
            {"id": "https://openalex.org/W4", "display_name": "  Second valid work  "},
        ]
    }
    client = OpenAlexClient(
        http_get=lambda _url, _params, _headers: json.dumps(payload),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    papers = client.search("valid works", limit=4)

    assert [paper.title for paper in papers] == ["First valid work", "Second valid work"]


def test_openalex_reported_zero_is_distinct_from_missing_citation_count() -> None:
    payload = {
        "results": [
            {"display_name": "Reported zero", "cited_by_count": 0},
            {"display_name": "Unknown count", "type": "preprint"},
        ]
    }
    client = OpenAlexClient(
        http_get=lambda _url, _params, _headers: json.dumps(payload),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    reported_zero, unknown = client.search("counts", limit=2)

    assert reported_zero.citation_count == 0
    assert reported_zero.citation_count_source == "openalex"
    assert reported_zero.citation_count_as_of == date.today()
    assert unknown.citation_count is None
    assert unknown.citation_count_source is None
    assert unknown.citation_count_as_of is None
    assert unknown.publication_status == "preprint"
    assert unknown.status_source == "openalex"


def test_openalex_separates_arxiv_repository_doi_from_publication_doi() -> None:
    payload = {
        "results": [
            {
                "display_name": "An information-theoretic upper bound on prime gaps",
                "doi": "https://doi.org/10.48550/arXiv.2110.15271",
                "type": "preprint",
            }
        ]
    }
    client = OpenAlexClient(
        http_get=lambda _url, _params, _headers: json.dumps(payload),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    paper = client.search("prime gaps", limit=1)[0]

    assert paper.doi is None
    assert paper.repository_doi == "10.48550/arxiv.2110.15271"


def test_openalex_retraction_status_overrides_work_type() -> None:
    payload = {
        "results": [
            {
                "display_name": "Retracted article",
                "type": "article",
                "is_retracted": True,
            }
        ]
    }
    client = OpenAlexClient(
        http_get=lambda _url, _params, _headers: json.dumps(payload),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    paper = client.search("retracted", limit=1)[0]

    assert paper.publication_status == "retracted"
    assert paper.status_source == "openalex"
    assert paper.status_as_of == date.today()


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


def test_openalex_client_converts_versioned_title_abstract_query_to_exact_filter() -> None:
    seen_params: list[dict[str, str | int]] = []
    compiled_query = (
        f"{OPENALEX_TITLE_ABSTRACT_FILTER_PREFIX}"
        '("aurelia cells" OR "aurelia devices") AND '
        '("phase drift" OR "state drift")'
    )

    def fake_get(
        _url: str,
        params: dict[str, str | int],
        _headers: Mapping[str, str] | None,
    ) -> str:
        seen_params.append(params)
        return json.dumps({"results": []})

    client = OpenAlexClient(
        http_get=fake_get,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )

    assert client.search(compiled_query, limit=20) == []
    assert seen_params[0]["filter"] == compiled_query
    assert "search" not in seen_params[0]
    assert seen_params[0]["per_page"] == 20


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
        if self.name.startswith(f".{state_path.name}.") and Path(target) == state_path:
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

    assert json.loads(state_path.read_text(encoding="utf-8")) == {"semantic_scholar": 9999.0}
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
