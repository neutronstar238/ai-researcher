"""Tests for question-first, metadata-only direct-plan Skill routing."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.competition.contest_direct_skill_router import (
    ContestDirectLiteratureEvidenceContext,
    ContestDirectLiteratureEvidenceProvenance,
    ContestDirectLiteratureEvidenceRecord,
    ContestDirectSkillMetadata,
    ContestDirectSkillRoutingError,
    build_contest_direct_skill_routing_messages,
    load_contest_direct_skill_routing,
    route_contest_direct_plan_skills,
)
from autoresearch.competition.contest_direction_literature import (
    retrieve_contest_direction_literature,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.literature.models import AcademicPaper
from autoresearch.llm.client import LLMJsonCompletionResult


def _catalog() -> tuple[ContestDirectSkillMetadata, ...]:
    return (
        ContestDirectSkillMetadata(
            skill_id="generic-causal-review",
            name="通用因果审查",
            description="识别可证伪假设、替代解释和判别性对照。",
            content_sha256="a" * 64,
        ),
        ContestDirectSkillMetadata(
            skill_id="prime-computational-methods",
            name="素数计算研究路径",
            description="为素数结构问题设计可复现的计算数论研究路径。",
            content_sha256="b" * 64,
        ),
    )


def _completion(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="openai-compatible",
        base_url="https://provider.example/v1",
        model_name="qwen-test",
        endpoint="https://provider.example/v1/chat/completions",
        response_text=json.dumps(payload, ensure_ascii=False),
        parsed_json=payload,
        temperature=0.0,
    )


def _evidence_context(
    *,
    abstract: str = "本文比较素数间隙的经验分布与多个保持边际结构的零模型。",
) -> ContestDirectLiteratureEvidenceContext:
    record = ContestDirectLiteratureEvidenceRecord(
        record_id="direction-paper-0123456789abcdef",
        title="Prime gaps and information-theoretic structure",
        abstract=abstract,
        provenance=(
            ContestDirectLiteratureEvidenceProvenance(
                source="OpenAlex",
                query="prime gaps permutation entropy null model",
                retrieved_at="2026-08-12T08:00:00+00:00",
            ),
        ),
        url="https://example.org/papers/prime-gaps",
        record_sha256="c" * 64,
    )
    subset_hash = canonical_model_hash({"records": [record.model_dump(mode="json")]})
    return ContestDirectLiteratureEvidenceContext(
        retrieval_artifact_hash="d" * 64,
        record_ids=(record.record_id,),
        records=(record,),
        subset_hash=subset_hash,
    )


def test_messages_are_generic_then_question_then_metadata_catalog() -> None:
    messages = build_contest_direct_skill_routing_messages(
        question="素数为何如此特别？",
        requirements=("生成高质量中文研究计划。",),
        skill_catalog=_catalog(),
    )

    assert [message["role"] for message in messages] == ["system", "user", "user"]
    assert "素数" not in messages[0]["content"]
    question_payload = json.loads(messages[1]["content"])
    catalog_payload = json.loads(messages[2]["content"])
    assert question_payload["question"] == "素数为何如此特别？"
    assert "skills" not in question_payload
    assert catalog_payload["context_kind"] == "available_method_skill_catalog_metadata"
    assert [item["skill_id"] for item in catalog_payload["skills"]] == [
        "generic-causal-review",
        "prime-computational-methods",
    ]
    assert all("content" not in item for item in catalog_payload["skills"])
    assert "素数为何如此特别" not in messages[2]["content"]


def test_one_model_call_selects_ids_and_program_deduplicates_and_hashes(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_llm_call(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs)
        return _completion(
            {
                "selected_skill_ids": [
                    "prime-computational-methods",
                    "prime-computational-methods",
                ]
            }
        )

    output_path = tmp_path / "skill-routing.json"
    artifact = route_contest_direct_plan_skills(
        question="素数为何如此特别？",
        requirements=("中文输出。", "形成可执行研究计划。"),
        skill_catalog=_catalog(),
        output_path=output_path,
        llm_call=fake_llm_call,
    )

    assert len(calls) == 1
    assert calls[0]["temperature"] == 0.0
    assert calls[0]["response_schema"]["additionalProperties"] is False
    assert "uniqueItems" not in calls[0]["response_schema"]["properties"]["selected_skill_ids"]
    assert artifact.selected_skill_ids == ("prime-computational-methods",)
    assert artifact.selected_skill_hashes == {"prime-computational-methods": "b" * 64}
    assert "先读取题目与交付要求" in artifact.selection_reason
    assert "prime-computational-methods" in artifact.selection_reason
    assert artifact.model_calls == 1
    assert artifact.skill_bodies_visible_to_selector is False
    assert artifact.schema_version == "contest-direct-skill-routing-v1"
    assert len(artifact.messages) == 3
    legacy_payload = artifact.model_dump(mode="json")
    assert "literature_evidence_context" not in legacy_payload
    assert "literature_evidence_canonical_hash" not in legacy_payload
    assert load_contest_direct_skill_routing(output_path) == artifact


@pytest.mark.parametrize(
    "selection",
    ([], ["not-in-catalog"]),
)
def test_empty_or_unknown_model_selection_fails_without_a_rewrite(
    selection: list[str],
) -> None:
    calls = 0

    def fake_llm_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion({"selected_skill_ids": selection})

    with pytest.raises(ContestDirectSkillRoutingError):
        route_contest_direct_plan_skills(
            question="素数为何如此特别？",
            requirements=("中文研究计划。",),
            skill_catalog=_catalog(),
            llm_call=fake_llm_call,
        )

    assert calls == 1


def test_duplicate_catalog_ids_fail_before_calling_the_model() -> None:
    duplicate = (_catalog()[0], _catalog()[0])
    called = False

    def fake_llm_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal called
        called = True
        return _completion({"selected_skill_ids": ["generic-causal-review"]})

    with pytest.raises(ContestDirectSkillRoutingError, match="unique"):
        route_contest_direct_plan_skills(
            question="一个问题",
            requirements=("一项要求",),
            skill_catalog=duplicate,
            llm_call=fake_llm_call,
        )

    assert called is False


def test_router_does_not_preselect_by_catalog_order() -> None:
    artifact = route_contest_direct_plan_skills(
        question="素数为何如此特别？",
        requirements=("中文研究计划。",),
        skill_catalog=_catalog(),
        llm_call=lambda **_: _completion({"selected_skill_ids": ["generic-causal-review"]}),
    )

    assert artifact.selected_skill_ids == ("generic-causal-review",)


def test_evidence_messages_follow_question_and_precede_metadata_without_skill_body() -> None:
    malicious_skill_body = "MALICIOUS_SKILL_BODY_DO_NOT_EXPOSE"
    invalid_record = {
        **_evidence_context().records[0].model_dump(mode="json"),
        "skill_body": malicious_skill_body,
    }
    with pytest.raises(ValidationError, match="skill_body"):
        ContestDirectLiteratureEvidenceRecord.model_validate(invalid_record)

    evidence = _evidence_context()
    messages = build_contest_direct_skill_routing_messages(
        question="素数为何如此特别？",
        requirements=("生成高质量中文研究计划。",),
        skill_catalog=_catalog(),
        literature_evidence_context=evidence,
    )

    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "user",
        "user",
    ]
    question_payload = json.loads(messages[1]["content"])
    evidence_payload = json.loads(messages[2]["content"])
    catalog_payload = json.loads(messages[3]["content"])
    assert question_payload["context_kind"] == ("research_question_and_delivery_requirements")
    assert evidence_payload["context_kind"] == ("program_projected_real_literature_evidence")
    assert evidence_payload["retrieval_artifact_hash"] == "d" * 64
    assert evidence_payload["record_ids"] == ["direction-paper-0123456789abcdef"]
    assert evidence_payload["records"][0]["abstract"] == evidence.records[0].abstract
    assert catalog_payload["context_kind"] == ("available_method_skill_catalog_metadata")
    assert all("content" not in item for item in catalog_payload["skills"])
    assert malicious_skill_body not in json.dumps(messages, ensure_ascii=False)


def test_evidence_changes_input_messages_and_artifact_hashes(tmp_path: Path) -> None:
    first = route_contest_direct_plan_skills(
        question="素数为何如此特别？",
        requirements=("中文研究计划。",),
        skill_catalog=_catalog(),
        literature_evidence_context=_evidence_context(abstract="完整摘要甲。"),
        output_path=tmp_path / "first.json",
        llm_call=lambda **_: _completion({"selected_skill_ids": ["prime-computational-methods"]}),
    )
    second = route_contest_direct_plan_skills(
        question="素数为何如此特别？",
        requirements=("中文研究计划。",),
        skill_catalog=_catalog(),
        literature_evidence_context=_evidence_context(abstract="完整摘要乙。"),
        output_path=tmp_path / "second.json",
        llm_call=lambda **_: _completion({"selected_skill_ids": ["prime-computational-methods"]}),
    )

    assert first.schema_version == "contest-direct-skill-routing-v2"
    assert len(first.messages) == 4
    assert first.literature_retrieval_artifact_hash == "d" * 64
    assert first.literature_evidence_record_ids == ("direction-paper-0123456789abcdef",)
    assert first.literature_evidence_subset_hash != second.literature_evidence_subset_hash
    assert first.literature_evidence_canonical_hash != (second.literature_evidence_canonical_hash)
    assert first.input_hash != second.input_hash
    assert first.messages_hash != second.messages_hash
    assert first.artifact_hash != second.artifact_hash
    assert "真实文献证据" in first.selection_reason
    assert load_contest_direct_skill_routing(tmp_path / "first.json") == first


def test_evidence_budget_rejects_whole_record_instead_of_truncating() -> None:
    exact_abstract = "甲" * 3_000
    context = _evidence_context(abstract=exact_abstract)
    assert context.records[0].abstract == exact_abstract

    with pytest.raises(ValidationError, match="14 KiB UTF-8 routing budget"):
        _evidence_context(abstract="乙" * 5_000)


def test_evidence_context_requires_program_projection_type_before_model_call() -> None:
    called = False

    def fake_llm_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal called
        called = True
        return _completion({"selected_skill_ids": ["generic-causal-review"]})

    with pytest.raises(ContestDirectSkillRoutingError, match="program-projected"):
        route_contest_direct_plan_skills(
            question="素数为何如此特别？",
            requirements=("中文研究计划。",),
            skill_catalog=_catalog(),
            literature_evidence_context=_evidence_context().model_dump(mode="json"),  # type: ignore[arg-type]
            llm_call=fake_llm_call,
        )

    assert called is False


def test_factory_projects_complete_records_from_validated_retrieval_artifact() -> None:
    exact_abstract = "这是从检索制品逐字投影、没有被路由器截断的完整摘要。"
    retrieved_at = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
    retrieval = retrieve_contest_direction_literature(
        direction="研究素数间隙的统计结构",
        searchers={
            "local-index": lambda query, *, limit: [  # noqa: ARG005
                AcademicPaper(
                    title="Prime gaps and information-theoretic structure",
                    authors=["A. Researcher"],
                    abstract=exact_abstract,
                    publication_date=date(2025, 1, 1),
                    venue="Journal of Number Theory",
                    doi="10.1000/prime-gap",
                    url="https://example.org/papers/prime-gap",
                    citation_count=3,
                    source="openalex",
                )
            ]
        },
        retrieved_at=retrieved_at,
        llm_call=lambda **_: _completion(
            {
                "queries": [
                    '("prime gaps" OR "prime spacing") AND (entropy OR structure)',
                    '("information theory" OR "ordinal analysis") AND (definition OR estimation)',
                    '("prime gaps" OR "prime spacing") AND (mechanism OR "null model")',
                    '("prime gaps" OR "prime spacing") AND (limitations OR bias)',
                ]
            }
        ),
    )

    context = ContestDirectLiteratureEvidenceContext.from_retrieval_artifact(
        retrieval,
        record_ids=(retrieval.retrieved_records[0].record_id,),
    )

    assert context.retrieval_artifact_hash == retrieval.artifact_hash
    assert context.record_ids == (retrieval.retrieved_records[0].record_id,)
    assert context.records[0].abstract == exact_abstract
    assert context.records[0].record_sha256 == retrieval.retrieved_records[0].record_hash
    assert context.records[0].provenance[0].source == "local-index"
    assert context.records[0].provenance[0].retrieved_at == retrieved_at.isoformat()
