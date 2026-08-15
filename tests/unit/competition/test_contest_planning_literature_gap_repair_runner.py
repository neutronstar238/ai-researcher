"""Tests for the single-call, evidence-bound gap-query repair runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.competition.contest_planning_literature_coverage import (
    PlanningLiteratureCandidate,
    PlanningLiteratureRole,
    role_query_from_boolean,
    select_planning_literature,
)
from autoresearch.competition.contest_planning_literature_gap_repair import (
    PlanningLiteratureGapRepairEvidenceInput,
    diagnose_planning_literature_gap,
)
from autoresearch.competition.contest_planning_literature_gap_repair_runner import (
    PlanningLiteratureGapRepairResponseError,
    build_planning_literature_gap_repair_messages,
    load_planning_literature_gap_repair_response,
    run_planning_literature_gap_repair_query,
)
from autoresearch.llm.client import LLMJsonCompletionResult


def _failed_coverage():  # type: ignore[no-untyped-def]
    object_group = '("aurora arrays" OR "borealis arrays")'
    raw_queries = (
        f'{object_group} AND ("phase response" OR "ordered response")',
        '("rank measures" OR "ordinal measures") AND ' "(estimation OR validation)",
        f'{object_group} AND ("drift mechanism" OR "null mechanism")',
        f"{object_group} AND (limitations OR bias)",
    )
    roles = (
        PlanningLiteratureRole.DIRECT_CORE,
        PlanningLiteratureRole.METHOD_FOUNDATION,
        PlanningLiteratureRole.MECHANISM_OR_NULL,
        PlanningLiteratureRole.COUNTEREVIDENCE,
    )
    queries = tuple(
        role_query_from_boolean(role, f"query-{index}", raw)
        for index, (role, raw) in enumerate(zip(roles, raw_queries, strict=True), start=1)
    )

    def candidate(
        record_id: str,
        role: PlanningLiteratureRole,
        title: str,
        abstract: str,
    ) -> PlanningLiteratureCandidate:
        query = next(item for item in queries if item.role is role)
        return PlanningLiteratureCandidate(
            record_id=record_id,
            title=title,
            abstract=abstract,
            retrieval_queries=(query.raw_query,),
            source_stages=("targeted_direction",),
            quality_score=0.8,
        )

    candidates = (
        candidate(
            "direct-repository-only",
            PlanningLiteratureRole.DIRECT_CORE,
            "Aurora arrays and phase response",
            "Ordered response was reported.",
        ),
        candidate(
            "method-anchor",
            PlanningLiteratureRole.METHOD_FOUNDATION,
            "Rank measures for aurora arrays estimation",
            "Ordinal measures require validation.",
        ),
        candidate(
            "mechanism-anchor",
            PlanningLiteratureRole.MECHANISM_OR_NULL,
            "Drift mechanism in aurora arrays",
            "A null mechanism is compared in borealis arrays.",
        ),
        candidate(
            "counter-anchor",
            PlanningLiteratureRole.COUNTEREVIDENCE,
            "Limitations of aurora arrays",
            "Bias affects borealis arrays.",
        ),
    )
    return select_planning_literature(
        candidates,
        queries,
        maximum_records=8,
        required_anchor_eligible_record_ids=(
            "method-anchor",
            "mechanism-anchor",
            "counter-anchor",
        ),
    )


def _evidence() -> tuple[PlanningLiteratureGapRepairEvidenceInput, ...]:
    return (
        PlanningLiteratureGapRepairEvidenceInput.create(
            source_scope="focus",
            source_artifact_hash="a" * 64,
            record_id="focus-1",
            title="Bounded oscillations in replicated aurora arrays",
            abstract="Independent studies report normalized transitions.",
        ),
        PlanningLiteratureGapRepairEvidenceInput.create(
            source_scope="focus",
            source_artifact_hash="a" * 64,
            record_id="focus-2",
            title="Normalized transitions under fixed sampling",
            abstract="Bounded oscillations remain measurable.",
        ),
    )


def _completion(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="test-provider",
        base_url="https://provider.example/v1",
        model_name="test-model",
        endpoint="https://provider.example/v1/chat/completions",
        response_text=json.dumps(payload, ensure_ascii=False),
        parsed_json=payload,
        temperature=0.2,
    )


def _valid_payload() -> dict[str, Any]:
    evidence = _evidence()
    return {
        "repairs": [
            {
                "role": "direct_core",
                "replacement_terms": [
                    {
                        "term": "bounded oscillations",
                        "evidence_hash": evidence[0].evidence_hash,
                        "matched_field": "title",
                    },
                    {
                        "term": "normalized transitions",
                        "evidence_hash": evidence[1].evidence_hash,
                        "matched_field": "title",
                    },
                ],
            }
        ]
    }


def test_messages_expose_only_failed_coverage_and_bound_evidence() -> None:
    diagnosis = diagnose_planning_literature_gap(_failed_coverage())

    messages = build_planning_literature_gap_repair_messages(diagnosis, _evidence())

    assert len(messages) == 3
    assert "不得回答研究问题" in messages[0]["content"]
    assert diagnosis.diagnosis_hash in messages[1]["content"]
    assert _evidence()[0].evidence_hash in messages[2]["content"]
    assert "prime" not in json.dumps(messages, ensure_ascii=False).casefold()


def test_runner_uses_minimal_strict_schema_and_disabled_thinking() -> None:
    diagnosis = diagnose_planning_literature_gap(_failed_coverage())
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs)
        return _completion(_valid_payload())

    run_planning_literature_gap_repair_query(
        diagnosis=diagnosis,
        evidence_inputs=_evidence(),
        completion=completion,
    )

    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 768
    assert calls[0]["thinking_mode"] == "disabled"
    assert calls[0]["thinking_budget"] is None
    assert calls[0]["response_schema_name"] == ("contest_planning_literature_gap_repair")
    assert calls[0]["response_schema"] == {
        "type": "object",
        "properties": {
            "repairs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "replacement_terms": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "term": {"type": "string"},
                                    "evidence_hash": {"type": "string"},
                                    "matched_field": {"type": "string"},
                                },
                                "required": [
                                    "term",
                                    "evidence_hash",
                                    "matched_field",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["role", "replacement_terms"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["repairs"],
        "additionalProperties": False,
    }
    forbidden_keywords = {"$defs", "$ref", "anyOf", "minItems", "maxItems"}

    def collect_keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for child in value.values() for key in collect_keys(child)}
        if isinstance(value, list):
            return {key for child in value for key in collect_keys(child)}
        return set()

    assert collect_keys(calls[0]["response_schema"]).isdisjoint(forbidden_keywords)


def test_runner_calls_model_once_persists_and_replays_without_a_second_call(
    tmp_path: Path,
) -> None:
    diagnosis = diagnose_planning_literature_gap(_failed_coverage())
    calls: list[tuple[dict[str, str], ...]] = []
    output = tmp_path / "gap-query-response.json"

    def completion(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(tuple(kwargs["messages"]))
        return _completion(_valid_payload())

    first = run_planning_literature_gap_repair_query(
        diagnosis=diagnosis,
        evidence_inputs=_evidence(),
        completion=completion,
        output_path=output,
    )
    replay = run_planning_literature_gap_repair_query(
        diagnosis=diagnosis,
        evidence_inputs=_evidence(),
        completion=lambda **_kwargs: pytest.fail("persisted response must replay locally"),
        output_path=output,
    )

    assert first == replay == load_planning_literature_gap_repair_response(output)
    assert len(calls) == 1
    assert first.model_calls == 1
    assert first.provider == "test-provider"
    assert first.projection.diagnosis_hash == diagnosis.diagnosis_hash
    repaired = first.projection.r2_role_queries[0]
    assert repaired.query_id.endswith("-r2")
    assert repaired.must_groups[1] == (
        "bounded oscillations",
        "normalized transitions",
    )
    assert tuple(item.raw_query for item in first.projection.r2_role_queries[1:]) == tuple(
        item.raw_query for item in diagnosis.coverage_receipt.role_queries[1:]
    )


def test_runner_rejects_invented_terms_and_does_not_persist(tmp_path: Path) -> None:
    diagnosis = diagnose_planning_literature_gap(_failed_coverage())
    payload = _valid_payload()
    payload["repairs"][0]["replacement_terms"][0]["term"] = "invented descriptor"
    output = tmp_path / "gap-query-response.json"

    with pytest.raises(PlanningLiteratureGapRepairResponseError, match="does not occur"):
        run_planning_literature_gap_repair_query(
            diagnosis=diagnosis,
            evidence_inputs=_evidence(),
            completion=lambda **_kwargs: _completion(payload),
            output_path=output,
        )

    assert not output.exists()


def test_runner_rejects_extra_response_fields() -> None:
    diagnosis = diagnose_planning_literature_gap(_failed_coverage())
    payload = {**_valid_payload(), "answer": "not allowed"}

    with pytest.raises(PlanningLiteratureGapRepairResponseError, match="response contract"):
        run_planning_literature_gap_repair_query(
            diagnosis=diagnosis,
            evidence_inputs=_evidence(),
            completion=lambda **_kwargs: _completion(payload),
        )


def test_tampered_response_receipt_fails_replay(tmp_path: Path) -> None:
    diagnosis = diagnose_planning_literature_gap(_failed_coverage())
    output = tmp_path / "gap-query-response.json"
    run_planning_literature_gap_repair_query(
        diagnosis=diagnosis,
        evidence_inputs=_evidence(),
        completion=lambda **_kwargs: _completion(_valid_payload()),
        output_path=output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["messages"][0]["content"] = "rewritten"
    output.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises((ValidationError, ValueError), match="messages|hash"):
        load_planning_literature_gap_repair_response(output)
