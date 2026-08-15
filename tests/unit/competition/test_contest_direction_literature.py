"""Tests for direction-first, real-search-only contest literature retrieval."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import autoresearch.competition.contest_direction_literature as literature_module
from autoresearch.competition.contest_direction_literature import (
    ContestDirectionLiteratureArtifact,
    ContestDirectionLiteratureError,
    ContestDirectionLiteratureRecord,
    _build_legacy_contest_direction_literature_messages,
    _build_quality_expansion_v1_messages,
    _build_source_query_compiler_v1_messages,
    _build_source_query_compiler_v2_messages,
    _build_source_query_compiler_v3_messages,
    build_contest_direction_literature_messages,
    retrieve_contest_direction_literature,
)
from autoresearch.competition.contest_research_objective_stage import (
    _normalize_literature_catalog,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.literature.models import AcademicPaper
from autoresearch.llm.client import LLMJsonCompletionResult

NOW = datetime(2026, 8, 11, 10, 30, tzinfo=timezone.utc)
SKILL = "---\nname: computational-number-theory\n---\n先构造可证伪的计算检验。\n"
ATTEMPT_002_STYLE_QUERY = (
    '("prime gap*" OR "consecutive primes") AND '
    '("permutation entropy" OR "ordinal pattern*") AND '
    '("surrogate data" OR "null model?") AND NOT "ecological time series~"'
)
V2_LOGICAL_QUERY = '("aurelia cells" OR "aurelia devices") AND ("phase drift" OR "state drift")'
V3_QUERY_PLAN = (
    '("lumen arrays" OR "lumen devices") AND ("phase drift" OR "state drift")',
    '("rank analysis" OR "ordinal analysis") AND (definition OR validation)',
    '("lumen arrays" OR "lumen devices") AND ("null model" OR mechanism)',
    '("lumen arrays" OR "lumen devices") AND (limitations OR "failure modes" OR artifacts OR bias)',
)


def _completion(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="openai-compatible",
        base_url="https://provider.example/v1",
        model_name="qwen-test",
        endpoint="https://provider.example/v1/chat/completions",
        response_text=json.dumps(payload, ensure_ascii=False),
        parsed_json=payload,
        temperature=0.2,
    )


def _paper(*, abstract: str, source: str = "openalex") -> AcademicPaper:
    return AcademicPaper(
        title="Prime number races and zeros of L-functions",
        authors=["A. Researcher", "B. Scholar"],
        abstract=abstract,
        publication_date=date(2024, 5, 1),
        venue="Journal of Number Theory",
        doi="https://doi.org/10.1000/prime.2024.1",
        url="https://example.org/prime-races",
        citation_count=7,
        source=source,
    )


def _use_historical_v3_query_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        literature_module,
        "_QUERY_COMPILER_VERSION",
        "source-query-compiler-v3",
    )


def test_messages_are_generic_then_direction_then_selected_skill_content() -> None:
    messages = build_contest_direction_literature_messages(
        direction="研究素数局部统计结构",
        requirements=("后续生成中文研究目标",),
        selected_method_skills={"number-theory": SKILL},
    )

    assert [item["role"] for item in messages] == ["system", "user", "user"]
    assert "素数" not in messages[0]["content"]
    direction_payload = json.loads(messages[1]["content"])
    skill_payload = json.loads(messages[2]["content"])
    assert direction_payload["direction"] == "研究素数局部统计结构"
    assert "selected_method_skills" not in direction_payload
    assert skill_payload["context_kind"] == "main_agent_selected_method_skills"
    assert all(
        marker in messages[0]["content"] for marker in ("直接现象", "方法基础", "理论基线", "反证")
    )
    assert "必须恰好输出四条" in messages[0]["content"]
    assert "方法族" in messages[0]["content"]
    assert "定义、估计、偏差或验证" in messages[0]["content"]
    assert "不得强制包含具体研究对象" in messages[0]["content"]
    assert "拟议的专用零模型" in messages[0]["content"]
    assert "短而常用" in messages[0]["content"]
    assert "每个 OR 组的不同术语数量上限固定为4个" in messages[0]["content"]
    assert "第5个术语会使整个查询计划失效" in messages[0]["content"]
    assert "不会截断、放宽上限或自动重试" in messages[0]["content"]
    assert "不得使用字段语法" in messages[0]["content"]
    assert "通配符" in messages[0]["content"]
    assert "不得另加文献类型标签" in messages[0]["content"]
    assert "第1、3、4条必须逐字复用完全相同的核心研究对象 OR 组" in messages[0]["content"]
    assert "generic model、system、method" in messages[0]["content"]
    assert all(
        marker in messages[0]["content"]
        for marker in ("limitations", "failure modes", "artifacts", "bias")
    )
    assert all(
        marker in messages[0]["content"]
        for marker in ("anomalies", "deviations", "counterexamples", "irregularities")
    )
    assert skill_payload["output_contract"]["queries"] == [
        "核心对象OR组 AND 直接现象检索式",
        "方法族OR组 AND 定义、估计、偏差或验证OR组检索式",
        "同一核心对象OR组 AND 机制、理论基线或零模型检索式",
        "同一核心对象OR组 AND 真正反证概念OR组检索式",
    ]
    assert len(skill_payload["output_contract"]["queries"]) == 4
    assert skill_payload["output_contract"]["query_shape"] == {
        "top_level_must_groups_per_query": 2,
        "minimum_alternatives_per_group": 2,
        "maximum_alternatives_per_group": 4,
        "over_limit_policy": "reject_entire_plan_before_search_no_truncation_or_retry",
    }
    assert skill_payload["selected_method_skills"] == [
        {
            "skill_id": "number-theory",
            "content": SKILL.strip(),
            "content_sha256": hashlib.sha256(SKILL.strip().encode()).hexdigest(),
        }
    ]


def test_query_generation_uses_minimal_strict_schema_and_disabled_thinking() -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs)
        return _completion({"queries": list(V3_QUERY_PLAN)})

    retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={
            "source": lambda query, *, limit: [_paper(abstract=query)]  # noqa: ARG005
        },
        retrieved_at=NOW,
        llm_call=completion,
    )

    assert len(calls) == 1
    assert calls[0]["thinking_mode"] == "disabled"
    assert calls[0]["thinking_budget"] is None
    assert calls[0]["response_schema_name"] == "contest_direction_query_list"
    assert calls[0]["response_schema"] == {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["queries"],
        "additionalProperties": False,
    }
    assert set(calls[0]["response_schema"]) == {
        "type",
        "properties",
        "required",
        "additionalProperties",
    }
    assert set(calls[0]["response_schema"]["properties"]["queries"]) == {
        "type",
        "items",
    }


def test_real_search_boundary_degrades_one_source_and_deduplicates_full_abstract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    model_calls: list[dict[str, Any]] = []
    search_calls: list[tuple[str, str, int]] = []

    def llm_call(**kwargs: Any) -> LLMJsonCompletionResult:
        model_calls.append(kwargs)
        return _completion(
            {
                "queries": ["prime number race local statistics", "L-function zero bias"],
                # This fabricated citation must never enter the bibliography.
                "references": [{"title": "Qwen invented paper"}],
            }
        )

    def failed_search(query: str, *, limit: int) -> list[AcademicPaper]:
        search_calls.append(("failed-source", query, limit))
        raise TimeoutError("source unavailable")

    def real_search(query: str, *, limit: int) -> list[AcademicPaper]:
        search_calls.append(("real-source", query, limit))
        abstract = (
            "A complete abstract retained without truncation for the second query."
            if query.startswith("L-function")
            else "Short abstract."
        )
        return [_paper(abstract=abstract)]

    output = tmp_path / "direction-literature.json"
    artifact = retrieve_contest_direction_literature(
        direction="研究素数局部统计结构",
        requirements=("形成可检验研究目标",),
        selected_method_skills={"number-theory": SKILL},
        searchers={"failed-source": failed_search, "real-source": real_search},
        output_path=output,
        retrieved_at=NOW,
        max_results_per_search=6,
        llm_call=llm_call,
    )

    assert len(model_calls) == 1
    assert [item["role"] for item in model_calls[0]["messages"]] == [
        "system",
        "user",
        "user",
    ]
    assert len(search_calls) == 4
    assert all(call[2] == 6 for call in search_calls)
    assert artifact.queries == (
        "prime number race local statistics",
        "L-function zero bias",
    )
    assert len(artifact.fetches) == 4
    assert sum(item.status == "failed" for item in artifact.fetches) == 2
    assert all(item.error for item in artifact.fetches if item.status == "failed")
    assert artifact.raw_hit_count == 2
    assert artifact.deduplicated_count == 1
    assert len(artifact.retrieved_records) == 1
    record = artifact.retrieved_records[0]
    assert record.abstract == (
        "A complete abstract retained without truncation for the second query."
    )
    assert record.doi == "10.1000/prime.2024.1"
    assert len(record.retrievals) == 2
    assert "Qwen invented paper" not in output.read_text(encoding="utf-8")
    assert artifact.qwen_authored_literature is False
    assert artifact.literature_entry_boundary == "injected_search_callables_only"
    assert len(record.record_hash) == 64
    assert (
        ContestDirectionLiteratureArtifact.model_validate_json(output.read_text(encoding="utf-8"))
        == artifact
    )


def test_v3_compiles_logical_query_for_each_source_and_records_executed_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search_calls: list[tuple[str, str]] = []

    def search(source: str) -> Any:
        def run(query: str, *, limit: int) -> list[AcademicPaper]:  # noqa: ARG001
            search_calls.append((source, query))
            return [_paper(abstract=f"real abstract from {source}", source=source)]

        return run

    monkeypatch.setattr(
        literature_module,
        "_QUERY_COMPILER_VERSION",
        "source-query-compiler-v3",
    )
    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={"arxiv": search("arxiv"), "openalex": search("openalex")},
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": [V2_LOGICAL_QUERY]}),
    )

    expected_arxiv = (
        '(all:"aurelia cells" OR all:"aurelia devices") AND '
        '(all:"phase drift" OR all:"state drift")'
    )
    expected_openalex = (
        'title_and_abstract.search:("aurelia cells" OR "aurelia devices") AND '
        '("phase drift" OR "state drift")'
    )
    assert artifact.schema_version == "contest-direction-literature-v2"
    assert artifact.query_compiler_version == "source-query-compiler-v3"
    assert artifact.queries == (V2_LOGICAL_QUERY,)
    assert search_calls == [
        ("arxiv", expected_arxiv),
        ("openalex", expected_openalex),
    ]
    assert [(item.source, item.query) for item in artifact.fetches] == search_calls
    assert all("*" not in item.query for item in artifact.fetches)
    assert "?" not in artifact.fetches[1].query
    assert "~" not in artifact.fetches[1].query
    assert len(artifact.fetches[1].query) <= 1_200
    assert {
        (pointer.source, pointer.query)
        for record in artifact.retrieved_records
        for pointer in record.retrievals
    } == set(search_calls)


@pytest.mark.parametrize(
    ("logical_query", "error_match"),
    [
        (
            '("aurelia cells" OR "aurelia devices" OR "aurelia films" OR '
            '"aurelia layers" OR "aurelia arrays") AND '
            '("phase drift" OR "state drift")',
            "too many alternatives",
        ),
        (
            '("aurelia cells" OR "aurelia devices") AND NOT "phase drift"',
            "not a legal source-neutral Boolean expression",
        ),
    ],
)
def test_v2_openalex_compiler_rejects_unbounded_or_illegal_queries_before_search(
    logical_query: str,
    error_match: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    search_calls: list[str] = []

    def search(query: str, *, limit: int) -> list[AcademicPaper]:  # noqa: ARG001
        search_calls.append(query)
        return [_paper(abstract="This search must never run.")]

    with pytest.raises(ContestDirectionLiteratureError, match=error_match):
        retrieve_contest_direction_literature(
            direction="一个开放研究方向",
            searchers={"openalex": search},
            retrieved_at=NOW,
            llm_call=lambda **_: _completion({"queries": [logical_query]}),
        )

    assert search_calls == []


def test_source_query_compiler_v1_prompt_and_execution_replay_after_v2_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search_calls: list[str] = []

    def search(query: str, *, limit: int) -> list[AcademicPaper]:  # noqa: ARG001
        search_calls.append(query)
        return [_paper(abstract="Historical compiler response.")]

    monkeypatch.setattr(
        literature_module,
        "_QUERY_COMPILER_VERSION",
        "source-query-compiler-v1",
    )
    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={"openalex": search},
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": [ATTEMPT_002_STYLE_QUERY]}),
    )

    assert artifact.query_compiler_version == "source-query-compiler-v1"
    assert artifact.messages == tuple(
        _build_source_query_compiler_v1_messages(direction="一个开放研究方向")
    )
    assert search_calls == [
        "prime gap permutation entropy surrogate data consecutive primes ordinal pattern null model"
    ]
    assert (
        ContestDirectionLiteratureArtifact.model_validate(artifact.model_dump(mode="json"))
        == artifact
    )


def test_source_query_compiler_v2_prompt_replays_after_v3_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        literature_module,
        "_QUERY_COMPILER_VERSION",
        "source-query-compiler-v2",
    )
    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={
            "source": lambda query, *, limit: [_paper(abstract=query)]  # noqa: ARG005
        },
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": [V2_LOGICAL_QUERY]}),
    )

    assert artifact.query_compiler_version == "source-query-compiler-v2"
    assert artifact.messages == tuple(
        _build_source_query_compiler_v2_messages(direction="一个开放研究方向")
    )
    assert (
        ContestDirectionLiteratureArtifact.model_validate(artifact.model_dump(mode="json"))
        == artifact
    )


def test_v4_counterevidence_validator_rejects_weak_concept_group_before_search() -> None:
    search_calls: list[str] = []
    weak_plan = (
        *V3_QUERY_PLAN[:3],
        '("lumen arrays" OR "lumen devices") AND '
        "(anomalies OR deviations OR counterexamples OR irregularities)",
    )

    with pytest.raises(ContestDirectionLiteratureError, match="counterevidence"):
        retrieve_contest_direction_literature(
            direction="一个开放研究方向",
            searchers={
                "source": lambda query, *, limit: search_calls.append(query) or []  # noqa: ARG005
            },
            retrieved_at=NOW,
            llm_call=lambda **_: _completion({"queries": list(weak_plan)}),
        )

    assert search_calls == []


def test_v4_query_plan_accepts_exact_four_alternatives_per_group_without_loss() -> None:
    search_calls: list[tuple[str, str]] = []
    object_group = '("lumen arrays" OR "lumen devices" OR "lumen films" OR "lumen layers")'
    plan = (
        f'{object_group} AND ("phase drift" OR "state drift" OR noise OR hysteresis)',
        '("rank analysis" OR "ordinal analysis" OR "order statistics" OR "rank statistics") '
        "AND (definition OR estimation OR bias OR validation)",
        f'{object_group} AND ("null model" OR mechanism OR baseline OR theory)',
        f'{object_group} AND (limitations OR "failure modes" OR artifacts OR bias)',
    )

    def search(source: str) -> Any:
        def run(query: str, *, limit: int) -> list[AcademicPaper]:  # noqa: ARG001
            search_calls.append((source, query))
            return [_paper(abstract=query, source=source)]

        return run

    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={"arxiv": search("arxiv"), "openalex": search("openalex")},
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": list(plan)}),
    )

    assert artifact.queries == plan
    assert artifact.query_compiler_version == "source-query-compiler-v4"
    assert len(search_calls) == 8
    assert all(query.count(" OR ") == 6 for _source, query in search_calls)
    for term in ("lumen arrays", "lumen devices", "lumen films", "lumen layers"):
        assert all(term in query for _source, query in search_calls if "rank analysis" not in query)


def test_v4_query_plan_rejects_fifth_alternative_before_search_without_retry() -> None:
    search_calls: list[tuple[str, str]] = []
    model_calls = 0
    object_group = (
        '("lumen arrays" OR "lumen devices" OR "lumen films" OR "lumen layers" OR "lumen sheets")'
    )
    plan = (
        f'{object_group} AND ("phase drift" OR "state drift")',
        '("rank analysis" OR "ordinal analysis") AND (definition OR validation)',
        f'{object_group} AND ("null model" OR mechanism)',
        f'{object_group} AND (limitations OR "failure modes")',
    )

    def completion(**_: Any) -> LLMJsonCompletionResult:
        nonlocal model_calls
        model_calls += 1
        return _completion({"queries": list(plan)})

    def search(source: str) -> Any:
        def run(query: str, *, limit: int) -> list[AcademicPaper]:  # noqa: ARG001
            search_calls.append((source, query))
            return []

        return run

    with pytest.raises(
        ContestDirectionLiteratureError,
        match=r"query 1 group 1 has 5 alternatives; minimum is 2 and maximum is 4",
    ):
        retrieve_contest_direction_literature(
            direction="一个开放研究方向",
            searchers={
                "arxiv": search("arxiv"),
                "openalex": search("openalex"),
            },
            retrieved_at=NOW,
            llm_call=completion,
        )

    assert model_calls == 1
    assert search_calls == []


@pytest.mark.parametrize(
    "queries",
    [V3_QUERY_PLAN[:3], (*V3_QUERY_PLAN, "(extra OR surplus) AND (query OR phrase)")],
)
def test_v4_query_plan_rejects_non_exact_query_count_before_search(
    queries: tuple[str, ...],
) -> None:
    search_calls: list[str] = []

    with pytest.raises(ContestDirectionLiteratureError, match="requires exactly 4 queries"):
        retrieve_contest_direction_literature(
            direction="一个开放研究方向",
            searchers={
                "source": lambda query, *, limit: search_calls.append(query) or []  # noqa: ARG005
            },
            retrieved_at=NOW,
            llm_call=lambda **_: _completion({"queries": list(queries)}),
        )

    assert search_calls == []


def test_v4_query_plan_rejects_single_alternative_group_before_search() -> None:
    search_calls: list[str] = []
    plan = (
        V3_QUERY_PLAN[0],
        '("rank analysis") AND (definition OR validation)',
        V3_QUERY_PLAN[2],
        V3_QUERY_PLAN[3],
    )

    with pytest.raises(
        ContestDirectionLiteratureError,
        match=r"query 2 group 1 has 1 alternatives; minimum is 2 and maximum is 4",
    ):
        retrieve_contest_direction_literature(
            direction="一个开放研究方向",
            searchers={
                "source": lambda query, *, limit: search_calls.append(query) or []  # noqa: ARG005
            },
            retrieved_at=NOW,
            llm_call=lambda **_: _completion({"queries": list(plan)}),
        )

    assert search_calls == []


def test_all_queries_and_sources_compile_before_any_searcher_call() -> None:
    search_calls: list[tuple[str, str]] = []
    long_terms = tuple(f"{letter}{'x' * 68}" for letter in "abcdefgh")
    method_query = (
        f'("{long_terms[0]}" OR "{long_terms[1]}" OR "{long_terms[2]}" OR '
        f'"{long_terms[3]}") AND ("{long_terms[4]}" OR "{long_terms[5]}" OR '
        f'"{long_terms[6]}" OR "{long_terms[7]}")'
    )
    queries = (
        V3_QUERY_PLAN[0],
        method_query,
        V3_QUERY_PLAN[2],
        V3_QUERY_PLAN[3],
    )

    def search(source: str) -> Any:
        def run(query: str, *, limit: int) -> list[AcademicPaper]:  # noqa: ARG001
            search_calls.append((source, query))
            return [_paper(abstract=query, source=source)]

        return run

    with pytest.raises(
        ContestDirectionLiteratureError,
        match=r"query 2 for source 'arxiv'.*arXiv query exceeds",
    ):
        retrieve_contest_direction_literature(
            direction="一个开放研究方向",
            searchers={"openalex": search("openalex"), "arxiv": search("arxiv")},
            retrieved_at=NOW,
            llm_call=lambda **_: _completion({"queries": list(queries)}),
        )

    assert search_calls == []


def test_historical_v3_prompt_replays_after_v4_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        literature_module,
        "_QUERY_COMPILER_VERSION",
        "source-query-compiler-v3",
    )
    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={
            "source": lambda query, *, limit: [_paper(abstract=query)]  # noqa: ARG005
        },
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": list(V3_QUERY_PLAN)}),
    )
    expected_messages = _build_source_query_compiler_v3_messages(
        direction=artifact.direction,
        requirements=artifact.requirements,
        selected_method_skills=None,
    )
    replayed = ContestDirectionLiteratureArtifact.model_validate(artifact.model_dump(mode="json"))

    assert replayed.query_compiler_version == "source-query-compiler-v3"
    assert replayed.messages == tuple(expected_messages)


@pytest.mark.parametrize(
    "historical_message_builder",
    [
        _build_quality_expansion_v1_messages,
        _build_legacy_contest_direction_literature_messages,
    ],
)
def test_v1_artifact_replays_without_silent_schema_upgrade(
    historical_message_builder: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    current = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={
            "legacy-source": lambda query, *, limit: [_paper(abstract=query)]  # noqa: ARG005
        },
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": ["legacy logical query"]}),
    )
    payload = current.model_dump(mode="json")
    payload["schema_version"] = "contest-direction-literature-v1"
    payload.pop("query_compiler_version")
    payload["messages"] = historical_message_builder(
        direction=payload["direction"],
        requirements=payload["requirements"],
        selected_method_skills=None,
    )
    payload["messages_hash"] = canonical_model_hash({"messages": payload["messages"]})
    payload["query_plan_hash"] = canonical_model_hash(
        {
            "input_hash": payload["input_hash"],
            "queries": payload["queries"],
            "query_model_response_hash": payload["query_model_response_hash"],
        }
    )
    payload_without_hash = {key: value for key, value in payload.items() if key != "artifact_hash"}
    payload["artifact_hash"] = canonical_model_hash(payload_without_hash)

    replayed = ContestDirectionLiteratureArtifact.model_validate(payload)
    replayed_again = ContestDirectionLiteratureArtifact.model_validate(
        replayed.model_dump(mode="json")
    )

    assert replayed.schema_version == "contest-direction-literature-v1"
    assert replayed.query_compiler_version is None
    assert replayed.fetches[0].query == replayed.queries[0]
    assert replayed_again == replayed
    assert replayed_again.schema_version == "contest-direction-literature-v1"


def test_v2_rejects_historical_v1_query_prompt_even_when_rehashed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={
            "source": lambda query, *, limit: [_paper(abstract=query)]  # noqa: ARG005
        },
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": ["one query"]}),
    )
    tampered = artifact.model_dump(mode="json")
    tampered["messages"] = _build_quality_expansion_v1_messages(
        direction=tampered["direction"],
        requirements=tampered["requirements"],
        selected_method_skills=None,
    )
    tampered["messages_hash"] = canonical_model_hash({"messages": tampered["messages"]})
    tampered["artifact_hash"] = canonical_model_hash(
        {key: value for key, value in tampered.items() if key != "artifact_hash"}
    )

    with pytest.raises(ValidationError, match="messages mismatch"):
        ContestDirectionLiteratureArtifact.model_validate(tampered)


def test_v2_rejects_rehashed_fetch_query_that_does_not_match_compiler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={
            "arxiv": lambda query, *, limit: [_paper(abstract=query, source="arxiv")]  # noqa: ARG005
        },
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": [V2_LOGICAL_QUERY]}),
    )
    tampered = artifact.model_dump(mode="json")
    fetch = tampered["fetches"][0]
    fetch["query"] = 'all:"tampered but internally rehashed"'
    fetch["fetch_id"] = (
        "direction-fetch-"
        + canonical_model_hash(
            {
                "source": fetch["source"],
                "query": fetch["query"],
                "query_index": fetch["query_index"],
                "retrieved_at": fetch["retrieved_at"],
            }
        )[:16]
    )
    fetch["fetch_hash"] = canonical_model_hash(
        {key: value for key, value in fetch.items() if key != "fetch_hash"}
    )

    with pytest.raises(ValidationError, match="compiled source query"):
        ContestDirectionLiteratureArtifact.model_validate(tampered)


def test_stage_deduplication_never_mixes_metadata_across_conflicting_dois(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    first = AcademicPaper(
        title="Identical title with distinct publications",
        authors=["Shared Author"],
        abstract="First work abstract.",
        publication_date=date(2021, 1, 1),
        doi="10.1000/distinct-a",
        url="https://example.org/distinct-a",
        citation_count=500,
        citation_count_source="openalex",
        citation_count_as_of=NOW.date(),
        publication_status="published",
        status_source="openalex",
        status_as_of=NOW.date(),
        source="openalex",
    )
    second = AcademicPaper(
        title="Identical title with distinct publications",
        authors=["Shared Author"],
        abstract="Second work abstract.",
        publication_date=date(2022, 1, 1),
        doi="10.1000/distinct-b",
        url="https://example.org/distinct-b",
        citation_count=1,
        citation_count_source="openalex",
        citation_count_as_of=NOW.date(),
        publication_status="retracted",
        status_source="openalex",
        status_as_of=NOW.date(),
        source="openalex",
    )
    artifact = retrieve_contest_direction_literature(
        direction="检索同题但身份不同的研究",
        searchers={"openalex": lambda _query, *, limit: [first, second][:limit]},
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": ["distinct publication identity"]}),
    )

    assert artifact.raw_hit_count == 2
    assert artifact.deduplicated_count == 0
    assert len(artifact.retrieved_records) == 2
    by_doi = {record.doi: record for record in artifact.retrieved_records}
    assert by_doi["10.1000/distinct-a"].abstract == "First work abstract."
    assert by_doi["10.1000/distinct-a"].citation_count == 500
    assert by_doi["10.1000/distinct-a"].publication_status == "published"
    assert by_doi["10.1000/distinct-b"].abstract == "Second work abstract."
    assert by_doi["10.1000/distinct-b"].citation_count == 1
    assert by_doi["10.1000/distinct-b"].publication_status == "retracted"


def test_objective_projections_preserve_full_text_and_match_mapping_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    artifact = retrieve_contest_direction_literature(
        direction="研究素数局部统计结构",
        selected_method_skills={"number-theory": SKILL},
        searchers={
            "openalex": lambda query, *, limit: [_paper(abstract="完整摘要原文")]  # noqa: ARG005
        },
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"search_queries": "prime distribution bias"}),
    )

    text_catalog = artifact.objective_literature_catalog()
    mapping_catalog = artifact.objective_literature_record_catalog()
    assert len(text_catalog) == len(mapping_catalog) == 1
    assert "完整摘要：完整摘要原文" in text_catalog[0]
    assert mapping_catalog[0]["title"] == artifact.retrieved_records[0].title
    assert mapping_catalog[0]["abstract"] == "完整摘要原文"
    assert mapping_catalog[0]["retrieved_from"] == "openalex"
    assert mapping_catalog[0]["retrieved_at"] == NOW.isoformat()
    assert mapping_catalog[0]["source_url"] == "https://example.org/prime-races"
    normalized_for_objective = _normalize_literature_catalog(mapping_catalog)
    assert normalized_for_objective[0].title == artifact.retrieved_records[0].title
    assert normalized_for_objective[0].source_url == "https://example.org/prime-races"


def test_projection_distinguishes_unknown_citations_and_repository_doi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    paper = _paper(abstract="真实预印本摘要", source="arxiv").model_copy(
        update={
            "doi": None,
            "repository_doi": "10.48550/arXiv.2405.00001",
            "citation_count": None,
            "citation_count_source": None,
            "citation_count_as_of": None,
            "publication_status": "preprint",
            "status_source": "arxiv_atom",
            "status_as_of": NOW.date(),
        }
    )
    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={"arxiv": lambda query, *, limit: [paper]},  # noqa: ARG005
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": ["mechanism evidence"]}),
    )

    text = artifact.objective_literature_catalog()[0]
    projected = artifact.objective_retrieval_catalog()[0]
    assert "仓储DOI：10.48550/arxiv.2405.00001" in text
    assert "被引次数：未知（上游来源未提供；不得解释为0）" in text
    assert "期刊影响因子：未知" in text
    assert projected["publication_doi"] is None
    assert projected["repository_doi"] == "10.48550/arxiv.2405.00001"
    assert projected["citation_count"] is None
    assert projected["publication_status"] == "preprint"


def test_default_candidate_pool_expands_without_adding_search_calls() -> None:
    calls: list[tuple[str, int]] = []

    def search(query: str, *, limit: int) -> list[AcademicPaper]:
        calls.append((query, limit))
        return [_paper(abstract="真实摘要")]

    retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={"source": search},
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": list(V3_QUERY_PLAN)}),
    )

    assert len(calls) == 4
    assert {limit for _query, limit in calls} == {20}


def test_objective_projection_does_not_fabricate_missing_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    paper_without_url = _paper(abstract="real abstract").model_copy(
        update={"url": None, "doi": None}
    )
    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={
            "source": lambda query, *, limit: [paper_without_url]  # noqa: ARG005
        },
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": ["one search query"]}),
    )

    assert artifact.retrieved_records[0].url is None
    assert artifact.retrieved_records[0].doi is None
    with pytest.raises(ContestDirectionLiteratureError, match="no real URL or DOI"):
        artifact.objective_retrieval_catalog()


def test_all_sources_empty_fails_after_preserving_every_fetch_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)

    def empty_search(query: str, *, limit: int) -> list[AcademicPaper]:  # noqa: ARG001
        return []

    with pytest.raises(ContestDirectionLiteratureError, match="returned no papers") as exc:
        retrieve_contest_direction_literature(
            direction="一个开放研究方向",
            searchers={"arxiv": empty_search, "openalex": empty_search},
            retrieved_at=NOW,
            llm_call=lambda **_: _completion({"queries": ["query one", "query two"]}),
        )

    assert len(exc.value.fetches) == 4
    assert all(item.status == "succeeded" for item in exc.value.fetches)
    assert all(item.returned_count == 0 for item in exc.value.fetches)
    assert all(item.result_hash for item in exc.value.fetches)


def test_query_shape_is_tolerant_but_search_scope_is_bounded_to_four(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    seen: list[str] = []

    def real_search(query: str, *, limit: int) -> list[AcademicPaper]:  # noqa: ARG001
        seen.append(query)
        return [_paper(abstract=f"abstract for {query}")]

    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={"source": real_search},
        retrieved_at=NOW,
        llm_call=lambda **_: _completion(
            {
                "search_queries": [
                    f"1. {V3_QUERY_PLAN[0]}",
                    f"- {V3_QUERY_PLAN[1]}",
                    V3_QUERY_PLAN[1],
                    V3_QUERY_PLAN[2],
                    V3_QUERY_PLAN[3],
                    "fifth query",
                ]
            }
        ),
    )

    assert artifact.queries == V3_QUERY_PLAN
    assert seen == list(artifact.queries)


def test_program_ids_and_hashes_reject_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={
            "source": lambda query, *, limit: [_paper(abstract="real abstract")]  # noqa: ARG005
        },
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": ["one search query"]}),
    )

    assert artifact.retrieved_records[0].record_id.startswith("direction-paper-")
    assert len(artifact.artifact_hash) == 64
    tampered = artifact.model_dump(mode="json")
    tampered["retrieved_records"][0]["abstract"] = "tampered abstract"
    with pytest.raises(ValidationError, match="hash mismatch"):
        ContestDirectionLiteratureArtifact.model_validate(tampered)


def test_legacy_record_hash_replays_after_model_dump_adds_new_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_historical_v3_query_contract(monkeypatch)
    artifact = retrieve_contest_direction_literature(
        direction="一个开放研究方向",
        searchers={
            "source": lambda query, *, limit: [_paper(abstract="real abstract")]  # noqa: ARG005
        },
        retrieved_at=NOW,
        llm_call=lambda **_: _completion({"queries": ["one search query"]}),
    )
    record_payload = artifact.retrieved_records[0].model_dump(mode="json")
    for field in (
        "repository_doi",
        "citation_count_source",
        "citation_count_as_of",
        "publication_status",
        "status_source",
        "status_as_of",
    ):
        record_payload.pop(field)
    paper_payload = {
        "title": record_payload["title"],
        "authors": record_payload["authors"],
        "abstract": record_payload["abstract"],
        "publication_date": record_payload["publication_date"],
        "venue": record_payload["venue"],
        "doi": record_payload["doi"],
        "url": record_payload["url"],
        "citation_count": record_payload["citation_count"],
        "source": record_payload["paper_source"],
    }
    paper_hash = canonical_model_hash(paper_payload)
    record_payload["paper_hash"] = paper_hash
    record_payload["record_id"] = f"direction-paper-{paper_hash[:16]}"
    record_payload["record_hash"] = canonical_model_hash(
        {key: value for key, value in record_payload.items() if key != "record_hash"}
    )

    legacy = ContestDirectionLiteratureRecord.model_validate(record_payload)
    replayed = ContestDirectionLiteratureRecord.model_validate(legacy.model_dump(mode="json"))

    assert replayed == legacy
    assert replayed.repository_doi is None
    assert replayed.publication_status == "unknown"
