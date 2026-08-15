"""Tests for two-stage literature merging and Skill-routing evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition import (
    contest_direction_merged_literature as merged_literature_module,
)
from autoresearch.competition.contest_direct_skill_router import (
    ContestDirectLiteratureEvidenceContext,
    ContestDirectSkillMetadata,
    ContestDirectSkillRoutingError,
    build_contest_direct_skill_routing_messages,
    load_contest_direct_skill_routing,
    route_contest_direct_plan_skills,
)
from autoresearch.competition.contest_direction_focus_literature import (
    ContestDirectionFocusError,
    run_contest_direction_focus_selection,
    run_contest_direction_targeted_retrieval,
)
from autoresearch.competition.contest_direction_literature import (
    ContestDirectionLiteratureArtifact,
    retrieve_contest_direction_literature,
)
from autoresearch.competition.contest_direction_merged_literature import (
    ContestDirectionMergedLiteratureArtifact,
    ContestDirectionMergedLiteratureError,
    load_contest_direction_merged_literature,
    merge_contest_direction_literature,
)
from autoresearch.competition.contest_direction_plan_cli import _retrieval_sources
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.literature.models import AcademicPaper
from autoresearch.llm.client import LLMJsonCompletionResult

NOW = datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc)


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


def _v4_query_plan(
    *,
    object_terms: tuple[str, str],
    direct_terms: tuple[str, str],
    method_terms: tuple[str, str] = ("comparative analysis", "record linkage"),
    method_focus_terms: tuple[str, str] = ("definition", "validation"),
    mechanism_terms: tuple[str, str] = ("baseline", "mechanism"),
) -> list[str]:
    def group(terms: tuple[str, str]) -> str:
        return f"({json.dumps(terms[0])} OR {json.dumps(terms[1])})"

    object_group = group(object_terms)
    return [
        f"{object_group} AND {group(direct_terms)}",
        f"{group(method_terms)} AND {group(method_focus_terms)}",
        f"{object_group} AND {group(mechanism_terms)}",
        f'{object_group} AND ("limitations" OR "artifacts")',
    ]


def _broad_literature(*, searcher_name: str = "openalex") -> ContestDirectionLiteratureArtifact:
    papers = [
        AcademicPaper(
            title="Permutation entropy in consecutive prime gap transitions",
            authors=["A. Author"],
            abstract=(
                "We compare consecutive prime gap transitions with residue-aware "
                "permutation null models and report finite-interval uncertainty."
            ),
            publication_date=date(2024, 1, 1),
            venue="Journal of Number Theory",
            doi="10.1000/shared-prime-gap",
            url="https://example.org/shared-prime-gap",
            citation_count=11,
            citation_count_source="openalex",
            citation_count_as_of=date(2026, 8, 12),
            publication_status="published",
            status_source="crossref",
            status_as_of=date(2026, 8, 13),
            source="openalex",
        ),
        AcademicPaper(
            title="Retracted stationarity claim for local prime spacings",
            authors=["B. Author"],
            abstract=(
                "This withdrawn analysis studied prime gap stationarity and local null "
                "models; it is retained only as provenance, not positive evidence."
            ),
            publication_date=date(2021, 1, 1),
            venue="Example Mathematics",
            doi="10.1000/retracted-prime-gap",
            url="https://example.org/retracted-prime-gap",
            citation_count=None,
            publication_status="retracted",
            status_source="crossref",
            status_as_of=date(2026, 8, 13),
            source="openalex",
        ),
        AcademicPaper(
            title="Finite interval heterogeneity of ordered prime gaps",
            authors=["C. Author"],
            abstract=(
                "Finite interval prime gap samples are tested with block resampling, "
                "heterogeneity diagnostics, and competing arithmetic baselines."
            ),
            publication_date=date(2025, 1, 1),
            venue="Mathematics of Computation",
            doi="10.1000/prime-heterogeneity",
            url="https://example.org/prime-heterogeneity",
            citation_count=None,
            publication_status="unknown",
            source="openalex",
        ),
    ]
    return retrieve_contest_direction_literature(
        direction="研究连续素数间隔的局部统计结构",
        requirements=("先做宽检索核对",),
        selected_method_skills={},
        searchers={searcher_name: lambda query, *, limit: papers[:limit]},  # noqa: ARG005
        retrieved_at=NOW,
        llm_call=lambda **_: _completion(
            {
                "queries": _v4_query_plan(
                    object_terms=("consecutive prime gaps", "prime gap transitions"),
                    direct_terms=("permutation entropy", "finite interval heterogeneity"),
                    method_terms=("permutation analysis", "heterogeneity analysis"),
                    mechanism_terms=("null model", "residue mechanism"),
                )
            }
        ),
    )


def _brainstorm() -> dict[str, Any]:
    return {
        "candidates": [
            {
                "title_cn": "模类条件化转移",
                "focused_direction_cn": "检验模类条件化后连续素数间隔转移是否仍偏离零模型。",
                "problem_gap_cn": "宽检索证据尚未区分模类约束与序列依赖。",
                "falsifiable_objective_cn": "若条件化效应消失则否定序列依赖解释。",
                "evidence_rationale_cn": "证据一提供了相邻间隔与置换比较。",
                "nearest_work_queries": ["prime gap residue transition nearest work"],
                "methods_baselines_queries": ["conditional permutation prime gaps"],
                "counterevidence_queries": ["prime gap residue null result"],
                "evidence_indices": [1],
            },
            {
                "title_cn": "有限区间稳健性",
                "focused_direction_cn": "检验连续素数间隔效应能否跨固定区间保持方向稳定。",
                "problem_gap_cn": "局部波动可能被误写成总体规律。",
                "falsifiable_objective_cn": "若区间异质性主导则否定统一效应。",
                "evidence_rationale_cn": "证据一和二支持比较局部效应与重采样不确定性。",
                "nearest_work_queries": ["prime gap finite interval nearest work"],
                "methods_baselines_queries": ["block resampling prime gap baseline"],
                "counterevidence_queries": ["prime gap finite sample artifact"],
                "evidence_indices": [1, 2],
            },
        ]
    }


def _selection() -> dict[str, Any]:
    return {
        "selected_candidate_number": 2,
        "selection_rationale_cn": "该方向可先排除有限样本伪效应并适合低成本预实验。",
    }


def _build_lineage(
    tmp_path: Path,
    *,
    executable_adapter_capabilities: Sequence[Mapping[str, Any]] = (),
    broad_source: str = "openalex",
    targeted_source: str = "openalex",
) -> tuple[
    ContestDirectionLiteratureArtifact,
    Any,
    Any,
    ContestDirectionLiteratureArtifact,
]:
    broad = _broad_literature(searcher_name=broad_source)
    write_json_model(tmp_path / "broad-literature.json", broad)
    responses = iter((_brainstorm(), _selection()))
    focus = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        executable_adapter_capabilities=executable_adapter_capabilities,
        completion=lambda **_: _completion(next(responses)),
    )

    targeted_papers = [
        AcademicPaper(
            title="Permutation entropy for consecutive prime gap transitions",
            authors=["A. Author"],
            abstract=(
                "A direction-targeted record of the same work with a complete abstract "
                "on residue-aware permutation null models and finite intervals."
            ),
            publication_date=date(2024, 1, 1),
            venue="Journal of Number Theory",
            doi="https://doi.org/10.1000/shared-prime-gap",
            url="https://example.org/shared-prime-gap",
            citation_count=12,
            citation_count_source="openalex",
            citation_count_as_of=date(2026, 8, 13),
            publication_status="published",
            status_source="openalex",
            status_as_of=date(2026, 8, 13),
            source="openalex",
        ),
        AcademicPaper(
            title="Block-resampled null models for ordered prime spacings",
            authors=["D. Author"],
            abstract=(
                "We compare block-resampled and residue-conditioned null models for "
                "ordered prime spacings with explicit failure diagnostics."
            ),
            publication_date=date(2026, 1, 1),
            venue="Experimental Mathematics",
            doi="10.1000/targeted-block-null",
            url="https://example.org/targeted-block-null",
            citation_count=None,
            publication_status="unknown",
            source="openalex",
        ),
    ]
    binding = run_contest_direction_targeted_retrieval(
        focus=focus,
        output_dir=tmp_path,
        searchers={
            targeted_source: lambda query, *, limit: targeted_papers[:limit]  # noqa: ARG005
        },
        completion=lambda **_: _completion(
            {
                "queries": _v4_query_plan(
                    object_terms=("consecutive prime gaps", "prime gap transitions"),
                    direct_terms=("finite interval", "nearest work"),
                    method_terms=("block resampling", "conditional permutation"),
                    mechanism_terms=("finite sample baseline", "null model"),
                )
            }
        ),
    )
    targeted = ContestDirectionLiteratureArtifact.model_validate_json(
        (tmp_path / "targeted-literature.json").read_text(encoding="utf-8")
    )
    return broad, focus, binding, targeted


def _skills() -> tuple[ContestDirectSkillMetadata, ...]:
    return (
        ContestDirectSkillMetadata(
            skill_id="experimental-design",
            name="实验设计",
            description="设计可证伪比较、对照和评价指标。",
            content_sha256="a" * 64,
        ),
        ContestDirectSkillMetadata(
            skill_id="statistical-analysis",
            name="统计分析",
            description="分析不确定性、异质性和稳健性。",
            content_sha256="b" * 64,
        ),
    )


def _adapter_capability() -> dict[str, Any]:
    return {
        "adapter_id": "prime-gap-permutation-pilot",
        "scientific_object": "consecutive_integer_primes",
        "observable": "ordered_consecutive_prime_gaps",
        "supported_metrics": ["tie_aware_normalized_permutation_entropy_m5"],
        "supported_nulls": ["global_permutation", "local_block_permutation"],
        "execution_boundary_zh": "只执行冻结整数区间上的连续素数间隔探索性预实验。",
        "description": "比较真实序列与两个已注册置换零模型。",
    }


def test_merge_keeps_two_searches_and_deduplicates_without_quality_filters(
    tmp_path: Path,
) -> None:
    broad, focus, binding, targeted = _build_lineage(tmp_path)
    output = tmp_path / "merged-literature.json"
    merged = merge_contest_direction_literature(
        broad_literature=broad,
        focus=focus,
        targeted_binding=binding,
        targeted_literature=targeted,
        output_path=output,
    )

    assert merged.retrieval_semantics == "two_distinct_searches_not_one_retrieval"
    assert merged.broad_record_count == 3
    assert merged.targeted_record_count == 2
    assert merged.merged_record_count == 4
    assert merged.cross_stage_deduplicated_count == 1
    shared = next(item for item in merged.records if len(item.source_stages) == 2)
    assert shared.source_stages == ("targeted_direction", "broad_discovery")
    assert {item.stage for item in shared.retrievals} == {
        "targeted_direction",
        "broad_discovery",
    }
    assert all(item.fetch_hash for item in shared.retrievals)
    assert any(item.publication_status == "retracted" for item in merged.records)
    assert any(item.citation_count is None for item in merged.records)
    selector_catalog = merged.objective_retrieval_catalog()
    human_catalog = merged.objective_literature_catalog()
    assert len(selector_catalog) == len(human_catalog) == merged.merged_record_count
    shared_selector = next(
        item for item in selector_catalog if item["record_id"] == shared.record_id
    )
    assert shared_selector["retrieved_from"] == "openalex"
    assert shared_selector["retrieval_stage_sources"] == [
        "targeted_direction:openalex",
        "broad_discovery:openalex",
    ]
    assert shared_selector["retrieved_at"].endswith("+00:00")
    assert shared_selector["citation_count"] == 12
    assert shared_selector["citation_count_source"] == "openalex"
    assert shared_selector["citation_count_as_of"] == "2026-08-13"
    assert shared_selector["status_source"] == "openalex"
    assert shared_selector["source_stages"] == [
        "targeted_direction",
        "broad_discovery",
    ]
    shared_context = human_catalog[merged.record_ids.index(shared.record_id)]
    assert "两阶段原始记录" in shared_context
    assert "两阶段真实检索谱系" in shared_context
    assert "fetch_sha256=" in shared_context
    assert broad.artifact_hash in shared_context
    assert targeted.artifact_hash in shared_context
    assert (
        load_contest_direction_merged_literature(
            output,
            broad_literature_path=tmp_path / "broad-literature.json",
            focus_path=tmp_path / "direction-focus.json",
            targeted_binding_path=tmp_path / "direction-targeted-retrieval.json",
            targeted_literature_path=tmp_path / "targeted-literature.json",
        )
        == merged
    )


def test_merged_loader_rederives_instead_of_trusting_a_self_consistent_view(
    tmp_path: Path,
) -> None:
    broad, focus, binding, targeted = _build_lineage(tmp_path)
    output = tmp_path / "merged-literature.json"
    merged = merge_contest_direction_literature(
        broad_literature=broad,
        focus=focus,
        targeted_binding=binding,
        targeted_literature=targeted,
        output_path=output,
    )
    payload = merged.model_dump(mode="json", exclude={"artifact_hash"})
    payload["focused_direction_cn"] = "一段未绑定方向选择回执的替换文本"
    payload["artifact_hash"] = canonical_model_hash(payload)
    alternate = ContestDirectionMergedLiteratureArtifact.model_validate(payload)
    write_json_model(output, alternate)

    with pytest.raises(ContestDirectionMergedLiteratureError, match="reloaded"):
        load_contest_direction_merged_literature(
            output,
            broad_literature_path=tmp_path / "broad-literature.json",
            focus_path=tmp_path / "direction-focus.json",
            targeted_binding_path=tmp_path / "direction-targeted-retrieval.json",
            targeted_literature_path=tmp_path / "targeted-literature.json",
        )


def test_merged_loader_replays_the_same_focus_adapter_capability(
    tmp_path: Path,
) -> None:
    adapter = _adapter_capability()
    broad, focus, binding, targeted = _build_lineage(
        tmp_path,
        executable_adapter_capabilities=(adapter,),
    )
    output = tmp_path / "merged-literature.json"
    merged = merge_contest_direction_literature(
        broad_literature=broad,
        focus=focus,
        targeted_binding=binding,
        targeted_literature=targeted,
        output_path=output,
    )

    with pytest.raises(ContestDirectionFocusError, match="adapter-capability input changed"):
        load_contest_direction_merged_literature(
            output,
            broad_literature_path=tmp_path / "broad-literature.json",
            focus_path=tmp_path / "direction-focus.json",
            targeted_binding_path=tmp_path / "direction-targeted-retrieval.json",
            targeted_literature_path=tmp_path / "targeted-literature.json",
        )
    assert (
        load_contest_direction_merged_literature(
            output,
            broad_literature_path=tmp_path / "broad-literature.json",
            focus_path=tmp_path / "direction-focus.json",
            targeted_binding_path=tmp_path / "direction-targeted-retrieval.json",
            targeted_literature_path=tmp_path / "targeted-literature.json",
            executable_adapter_capabilities=(adapter,),
        )
        == merged
    )


def test_planning_projection_keeps_plain_sources_for_arxiv_finalist_verification(
    tmp_path: Path,
) -> None:
    broad, focus, binding, targeted = _build_lineage(
        tmp_path,
        broad_source="ArXiv",
        targeted_source="OpenAlex",
    )
    merged = merge_contest_direction_literature(
        broad_literature=broad,
        focus=focus,
        targeted_binding=binding,
        targeted_literature=targeted,
    )
    shared = next(
        item for item in merged.objective_retrieval_catalog() if len(item["source_stages"]) == 2
    )

    assert _retrieval_sources(shared) == {"arxiv", "openalex"}
    assert shared["retrieved_from"] == "OpenAlex,ArXiv"
    assert shared["retrieval_stage_sources"] == [
        "targeted_direction:OpenAlex",
        "broad_discovery:ArXiv",
    ]


def test_program_selected_merged_subset_drives_v3_skill_routing(tmp_path: Path) -> None:
    broad, focus, binding, targeted = _build_lineage(tmp_path)
    merged = merge_contest_direction_literature(
        broad_literature=broad,
        focus=focus,
        targeted_binding=binding,
        targeted_literature=targeted,
    )
    selected_ids = tuple(item.record_id for item in merged.records[:2])
    evidence = ContestDirectLiteratureEvidenceContext.from_two_stage_artifact(
        merged,
        record_ids=selected_ids,
    )

    assert evidence.retrieval_artifact_hash is None
    assert evidence.evidence_source_kind == "two_stage_merged"
    assert evidence.record_ids == selected_ids
    assert evidence.merged_literature_artifact_hash == merged.artifact_hash
    assert evidence.focus_artifact_hash == focus.artifact_hash
    assert any(
        pointer.retrieval_stage == "targeted_direction"
        for record in evidence.records
        for pointer in record.provenance
    )
    messages = build_contest_direct_skill_routing_messages(
        question=focus.focused_direction_cn,
        requirements=("生成中文研究计划",),
        skill_catalog=_skills(),
        literature_evidence_context=evidence,
    )
    evidence_payload = json.loads(messages[2]["content"])
    assert evidence_payload["context_kind"] == (
        "program_selected_two_stage_real_literature_evidence"
    )
    assert "retrieval_artifact_hash" not in evidence_payload
    assert evidence_payload["merged_literature_artifact_hash"] == merged.artifact_hash

    output = tmp_path / "skill-routing-v3.json"
    routing = route_contest_direct_plan_skills(
        question=focus.focused_direction_cn,
        requirements=("生成中文研究计划",),
        skill_catalog=_skills(),
        literature_evidence_context=evidence,
        output_path=output,
        llm_call=lambda **_: _completion(
            {"selected_skill_ids": ["experimental-design", "statistical-analysis"]}
        ),
    )
    dumped = routing.model_dump(mode="json")
    assert routing.schema_version == "contest-direct-skill-routing-v3"
    assert routing.literature_retrieval_artifact_hash is None
    assert "literature_retrieval_artifact_hash" not in dumped
    assert routing.literature_evidence_record_ids == selected_ids
    assert routing.literature_evidence_subset_hash == evidence.subset_hash
    assert routing.literature_evidence_canonical_hash == canonical_model_hash(
        evidence.model_dump(mode="json")
    )
    assert routing.broad_literature_artifact_hash == broad.artifact_hash
    assert routing.targeted_literature_artifact_hash == targeted.artifact_hash
    assert routing.merged_literature_artifact_hash == merged.artifact_hash
    assert load_contest_direct_skill_routing(output) == routing


def test_two_stage_projection_requires_explicit_known_program_selection(
    tmp_path: Path,
) -> None:
    broad, focus, binding, targeted = _build_lineage(tmp_path)
    merged = merge_contest_direction_literature(
        broad_literature=broad,
        focus=focus,
        targeted_binding=binding,
        targeted_literature=targeted,
    )

    with pytest.raises(ContestDirectSkillRoutingError, match="at least one"):
        ContestDirectLiteratureEvidenceContext.from_two_stage_artifact(
            merged,
            record_ids=(),
        )
    with pytest.raises(ContestDirectSkillRoutingError, match="unknown"):
        ContestDirectLiteratureEvidenceContext.from_two_stage_artifact(
            merged,
            record_ids=("merged-direction-paper-0000000000000000",),
        )


def test_dedup_never_merges_conflicting_dois_even_with_near_identical_titles(
    tmp_path: Path,
) -> None:
    broad, focus, binding, targeted = _build_lineage(tmp_path)
    targeted_payload = targeted.model_dump(mode="json")
    first = targeted_payload["retrieved_records"][0]
    first["doi"] = "10.1000/different-work"
    # Rebuilding a whole upstream artifact is intentionally outside this unit; use
    # a second real retrieval so all paper/record/fetch/artifact hashes are genuine.
    conflicting = retrieve_contest_direction_literature(
        direction=targeted.direction,
        requirements=targeted.requirements,
        selected_method_skills={},
        searchers={
            "openalex": lambda query, *, limit: [  # noqa: ARG005
                AcademicPaper(
                    title="Permutation entropy in consecutive prime gap transitions",
                    authors=["A. Author"],
                    abstract="A different paper with a deliberately conflicting DOI.",
                    publication_date=date(2026, 1, 1),
                    venue="Another Journal",
                    doi="10.1000/different-work",
                    url="https://example.org/different-work",
                    source="openalex",
                )
            ]
        },
        retrieved_at=NOW,
        llm_call=lambda **_: _completion(
            {
                "queries": _v4_query_plan(
                    object_terms=("consecutive prime gaps", "prime gap transitions"),
                    direct_terms=("finite interval", "nearest work"),
                )
            }
        ),
    )
    binding_payload = binding.model_dump(mode="json", exclude={"artifact_hash"})
    binding_payload["targeted_literature_artifact_hash"] = conflicting.artifact_hash
    binding_payload["targeted_literature_catalog_hash"] = conflicting.literature_catalog_hash
    binding_payload["targeted_search_context"] = conflicting.direction
    binding_payload["targeted_search_context_hash"] = canonical_model_hash(
        {"targeted_search_context": conflicting.direction}
    )
    binding_payload["artifact_hash"] = canonical_model_hash(binding_payload)
    altered_binding = type(binding).model_validate(binding_payload)

    merged = merge_contest_direction_literature(
        broad_literature=broad,
        focus=focus,
        targeted_binding=altered_binding,
        targeted_literature=conflicting,
    )
    assert merged.merged_record_count == len(broad.retrieved_records) + 1
    assert merged.cross_stage_deduplicated_count == 0


def test_cross_namespace_equal_doi_never_merges_records(tmp_path: Path) -> None:
    broad, focus, binding, _targeted = _build_lineage(tmp_path)
    broad_record = broad.retrieved_records[0]
    assert broad_record.doi is not None
    cross_namespace = retrieve_contest_direction_literature(
        direction=binding.targeted_search_context,
        selected_method_skills={},
        searchers={
            "arxiv": lambda query, *, limit: [  # noqa: ARG005
                AcademicPaper(
                    title=broad_record.title,
                    authors=list(broad_record.authors),
                    abstract="A different record whose repository identifier collides cross-namespace.",
                    publication_date=date(2026, 1, 2),
                    repository_doi=broad_record.doi,
                    url="https://example.org/cross-namespace-record",
                    source="arxiv",
                )
            ]
        },
        retrieved_at=NOW,
        llm_call=lambda **_: _completion(
            {
                "queries": _v4_query_plan(
                    object_terms=("bibliographic records", "literature works"),
                    direct_terms=("cross namespace", "identifier collision"),
                )
            }
        ),
    )
    binding_payload = binding.model_dump(mode="json", exclude={"artifact_hash"})
    binding_payload["targeted_literature_artifact_hash"] = cross_namespace.artifact_hash
    binding_payload["targeted_literature_catalog_hash"] = cross_namespace.literature_catalog_hash
    binding_payload["targeted_search_context"] = cross_namespace.direction
    binding_payload["targeted_search_context_hash"] = canonical_model_hash(
        {"targeted_search_context": cross_namespace.direction}
    )
    binding_payload["artifact_hash"] = canonical_model_hash(binding_payload)
    altered_binding = type(binding).model_validate(binding_payload)

    merged = merge_contest_direction_literature(
        broad_literature=broad,
        focus=focus,
        targeted_binding=altered_binding,
        targeted_literature=cross_namespace,
    )

    assert merged.merged_record_count == len(broad.retrieved_records) + 1
    assert merged.cross_stage_deduplicated_count == 0


def test_identifier_matching_is_same_namespace_and_conflict_conservative() -> None:
    def one_record(
        *,
        title: str,
        doi: str | None = None,
        repository_doi: str | None = None,
    ) -> Any:
        artifact = retrieve_contest_direction_literature(
            direction="检索文献身份",
            searchers={
                "local": lambda query, *, limit: [  # noqa: ARG005
                    AcademicPaper(
                        title=title,
                        authors=["Shared Author"],
                        abstract="Complete identity test abstract.",
                        doi=doi,
                        repository_doi=repository_doi,
                        url="https://example.org/identity-test",
                        source="local",
                    )
                ]
            },
            retrieved_at=NOW,
            llm_call=lambda **_: _completion(
                {
                    "queries": _v4_query_plan(
                        object_terms=("bibliographic records", "literature works"),
                        direct_terms=("bibliographic identity", "identifier matching"),
                    )
                }
            ),
        )
        return artifact.retrieved_records[0]

    publication_a = one_record(title="Publication title A", doi="10.1000/same")
    publication_b = one_record(title="Publication title B", doi="DOI:10.1000/SAME")
    repository_a = one_record(
        title="Repository title A",
        repository_doi="10.48550/arxiv.2401.00001",
    )
    repository_b = one_record(
        title="Repository title B",
        repository_doi="DOI:10.48550/ARXIV.2401.00001",
    )
    repository_conflict = one_record(
        title="Repository title A",
        repository_doi="10.48550/arxiv.2401.00002",
    )

    assert merged_literature_module._same_work(  # noqa: SLF001
        publication_a,
        publication_b,
    )
    assert merged_literature_module._same_work(repository_a, repository_b)  # noqa: SLF001
    assert not merged_literature_module._same_work(  # noqa: SLF001
        repository_a,
        repository_conflict,
    )


def test_metadata_merge_uses_longest_abstract_and_preserves_citation_provenance(
    tmp_path: Path,
) -> None:
    broad, focus, binding, targeted = _build_lineage(tmp_path)
    merged = merge_contest_direction_literature(
        broad_literature=broad,
        focus=focus,
        targeted_binding=binding,
        targeted_literature=targeted,
    )
    shared = next(item for item in merged.records if len(item.source_stages) == 2)

    assert shared.abstract == max(
        (
            item.abstract
            for artifact in (broad, targeted)
            for item in artifact.retrieved_records
            if item.doi and "shared-prime-gap" in item.doi and item.abstract
        ),
        key=len,
    )
    assert shared.citation_count == 12
    assert shared.citation_count_source == "openalex"
    assert shared.citation_count_as_of == date(2026, 8, 13)
    assert shared.publication_status == "published"
    assert shared.status_source == "openalex"
    assert shared.status_as_of == date(2026, 8, 13)


def test_title_only_dedup_requires_author_overlap_when_doi_is_unavailable() -> None:
    def one_record(author: str, *, title: str = "Identical title without DOI") -> Any:
        artifact = retrieve_contest_direction_literature(
            direction="检索一个无DOI的同题名工作",
            searchers={
                "local": lambda query, *, limit: [  # noqa: ARG005
                    AcademicPaper(
                        title=title,
                        authors=[author],
                        abstract="Complete abstract for conservative identity matching.",
                        url=f"https://example.org/{author.replace(' ', '-').lower()}",
                        source="local",
                    )
                ]
            },
            retrieved_at=NOW,
            llm_call=lambda **_: _completion(
                {
                    "queries": _v4_query_plan(
                        object_terms=("bibliographic records", "literature works"),
                        direct_terms=("identical titles", "author overlap"),
                    )
                }
            ),
        )
        return artifact.retrieved_records[0]

    first = one_record("A. Researcher")
    different_author = one_record("B. Researcher")
    same_author = one_record("A. Researcher")
    assert not merged_literature_module._same_work(first, different_author)  # noqa: SLF001
    assert merged_literature_module._same_work(first, same_author)  # noqa: SLF001
    chinese_first = one_record("张三", title="素数间隔的有限区间异质性")
    chinese_same = one_record("张三", title="素数间隔的有限区间异质性")
    chinese_different = one_record("张三", title="自动望远镜的观测反馈闭环")
    assert merged_literature_module._same_work(chinese_first, chinese_same)  # noqa: SLF001
    assert not merged_literature_module._same_work(  # noqa: SLF001
        chinese_first,
        chinese_different,
    )
