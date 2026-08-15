"""Tests for broad-evidence focus selection and direction-targeted retrieval."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pytest

from autoresearch.competition.contest_direction_focus_literature import (
    ContestDirectionFocusError,
    ContestDirectionFocusStatusReceipt,
    build_contest_direction_focus_brainstorm_messages,
    load_contest_direction_focus_selection,
    load_contest_direction_targeted_retrieval,
    run_contest_direction_focus_selection,
    run_contest_direction_targeted_retrieval,
)
from autoresearch.competition.contest_direction_literature import (
    ContestDirectionLiteratureArtifact,
    retrieve_contest_direction_literature,
)
from autoresearch.literature.models import AcademicPaper
from autoresearch.llm.client import LLMJsonCompletionResult

NOW = datetime(2026, 8, 13, 9, 30, tzinfo=timezone.utc)


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


def _v4_query_plan(
    *,
    object_terms: tuple[str, str],
    direct_terms: tuple[str, str],
    method_terms: tuple[str, str],
    mechanism_terms: tuple[str, str],
) -> list[str]:
    def group(terms: tuple[str, str]) -> str:
        return f"({json.dumps(terms[0])} OR {json.dumps(terms[1])})"

    object_group = group(object_terms)
    return [
        f"{object_group} AND {group(direct_terms)}",
        f'{group(method_terms)} AND ("definition" OR "validation")',
        f"{object_group} AND {group(mechanism_terms)}",
        f'{object_group} AND ("limitations" OR "artifacts")',
    ]


def _broad_artifact() -> ContestDirectionLiteratureArtifact:
    titles = (
        "Consecutive prime gap transition graphs modulo primorials",
        "Permutation entropy for ordered prime spacing sequences",
        "Finite interval heterogeneity in prime gap statistics",
        "Residue class constraints on neighboring prime differences",
        "Block bootstrap uncertainty for arithmetic point processes",
        "Counterexamples to stationary models of local prime spacing",
        "Computational baselines for Hardy Littlewood tuple predictions",
    )
    papers = [
        AcademicPaper(
            title=titles[index - 1],
            authors=[f"Researcher {index}"],
            abstract=(
                "We study consecutive prime gaps, residue transitions, permutation null "
                f"models, and finite-sample uncertainty in experiment family {index}."
            ),
            publication_date=date(2020 + index % 5, 1, 1),
            venue="Journal of Number Theory",
            doi=f"10.1000/prime.focus.{index}",
            url=f"https://example.org/prime-focus-{index}",
            citation_count=10 * index,
            source="openalex",
        )
        for index in range(1, 8)
    ]
    return retrieve_contest_direction_literature(
        direction="研究连续素数间隔的局部结构与可证伪统计规律",
        requirements=("先广泛核对原始文献",),
        selected_method_skills={},
        searchers={"openalex": lambda query, *, limit: papers[:limit]},  # noqa: ARG005
        retrieved_at=NOW,
        llm_call=lambda **_: _completion(
            {
                "queries": _v4_query_plan(
                    object_terms=("consecutive prime gaps", "prime gap transitions"),
                    direct_terms=("residue transitions", "local structure"),
                    method_terms=("permutation entropy", "block resampling"),
                    mechanism_terms=("null model", "arithmetic baseline"),
                )
            }
        ),
    )


def _arxiv_broad_artifact(
    *,
    publication_status: Literal["unknown", "preprint"] = "preprint",
) -> ContestDirectionLiteratureArtifact:
    papers = [
        AcademicPaper(
            title=f"Prime gap shortlist family {index:02d} residue transition analysis",
            authors=[f"Arxiv Researcher {index}"],
            abstract=(
                "We study consecutive prime gaps, residue transitions, permutation null "
                f"models, and finite-sample uncertainty in arxiv family {index}."
            ),
            publication_date=date(2024, (index - 1) % 12 + 1, 1),
            repository_doi=f"10.48550/arXiv.24{index:02d}.{index:05d}",
            url=f"https://arxiv.org/abs/24{index:02d}.{index:05d}",
            citation_count=200 - index,
            publication_status=publication_status,
            status_source=("arxiv_atom" if publication_status != "unknown" else None),
            status_as_of=(NOW.date() if publication_status != "unknown" else None),
            source="arxiv",
        )
        for index in range(1, 19)
    ]
    return retrieve_contest_direction_literature(
        direction="研究连续素数间隔的局部结构与可证伪统计规律",
        selected_method_skills={},
        searchers={"arxiv": lambda query, *, limit: papers[:limit]},  # noqa: ARG005
        retrieved_at=NOW,
        llm_call=lambda **_: _completion(
            {
                "queries": _v4_query_plan(
                    object_terms=("consecutive prime gaps", "prime gap transitions"),
                    direct_terms=("residue transitions", "permutation entropy"),
                    method_terms=("permutation analysis", "finite sample analysis"),
                    mechanism_terms=("null model", "residue mechanism"),
                )
            }
        ),
    )


def _brainstorm_payload() -> dict[str, Any]:
    return {
        # Alias is intentional: projection should be tolerant without a retry.
        "focus_candidates": [
            {
                "title": "模类转移与局部间隔耦合",
                "gap": "现有研究尚未区分模类约束与局部转移依赖。",
                "objective": "检验条件化模类后相邻间隔转移是否仍偏离置换零模型。",
                "evidence_chain": "证据1和2提供了间隔与置换方法，但没有完成该条件比较。",
                "search_queries": {
                    "nearest": "consecutive prime gaps residue transition; prime gap Markov",
                    "methods": ["conditional permutation test prime gaps"],
                    "failures": ["prime residue transition null result"],
                },
                "references": "[1], [2]",
            },
            {
                "title_cn": "多尺度区间稳定性与伪效应诊断",
                "problem_gap_cn": "有限区间波动可能被误写成总体结构。",
                "falsifiable_objective_cn": "比较固定区间效应方向与区间异质性是否稳定。",
                "evidence_rationale_cn": "证据2和3提示需要有限样本与替代解释核对。",
                "nearest_work_queries": ["prime gap finite interval heterogeneity"],
                "methods_baselines_queries": ["block permutation uncertainty prime gaps"],
                "counterevidence_queries": ["prime gap finite sample artifact"],
                "evidence_indices": [2, 3],
            },
        ]
    }


def _selection_payload() -> dict[str, Any]:
    return {
        "choice": "候选2",
        "reason": "候选2能先排除有限区间伪效应，并可由低成本预实验直接否定。",
    }


def test_brainstorm_messages_are_skill_free_and_preserve_soft_quality_boundary(
    tmp_path: Path,
) -> None:
    broad = _broad_artifact()
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs)
        return _completion(_brainstorm_payload() if len(calls) == 1 else _selection_payload())

    artifact = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        completion=completion,
    )
    messages = build_contest_direction_focus_brainstorm_messages(
        direction=artifact.direction,
        requirements=artifact.requirements,
        evidence=artifact.focus_evidence,
    )

    joined = json.dumps(messages, ensure_ascii=False)
    assert "Skill内容" in joined
    assert "selected_method_skills" not in joined
    assert "只是软信息" in joined
    assert "创新性已经证实" in joined
    assert all("content_sha256" not in item["content"] for item in messages)


def test_focus_selection_is_two_call_resumable_and_hash_bound(tmp_path: Path) -> None:
    broad = _broad_artifact()
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs)
        return _completion(_brainstorm_payload() if len(calls) == 1 else _selection_payload())

    artifact = run_contest_direction_focus_selection(
        direction=broad.direction,
        requirements=("优先可证伪且可做预实验",),
        broad_literature=broad,
        output_dir=tmp_path,
        completion=completion,
    )

    assert len(calls) == 2
    assert artifact.model_call_count_at_creation == 2
    assert artifact.selected_candidate_number == 2
    assert artifact.selected_candidate.title_cn == "多尺度区间稳定性与伪效应诊断"
    assert artifact.skills_available_to_focus_models is False
    assert artifact.novelty_status == "unverified_until_targeted_nearest_work_search"
    assert artifact.focus_evidence_role == "broad_discovery_only_not_final_bibliography"
    assert (
        artifact.broad_publication_status_verification
        == "upstream_provenance_retained_status_not_rechecked"
    )
    assert all(
        item.publication_status_verification == "upstream_provenance_retained_status_not_rechecked"
        for item in artifact.focus_evidence
    )
    assert artifact.focused_direction_cn.startswith("多尺度区间稳定性")
    assert len(artifact.candidates) == 2
    assert all(
        item.candidate_id.startswith("direction-focus-candidate-") for item in artifact.candidates
    )
    assert (tmp_path / "direction-focus-brainstorm-response.json").is_file()
    assert (tmp_path / "direction-focus-selection-response.json").is_file()
    assert (
        load_contest_direction_focus_selection(
            tmp_path / "direction-focus.json", broad_literature=broad
        )
        == artifact
    )

    def forbidden(**_: Any) -> LLMJsonCompletionResult:
        raise AssertionError("completed focus stage must not call the provider")

    resumed = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        requirements=("优先可证伪且可做预实验",),
        completion=forbidden,
    )
    assert resumed == artifact

    receipt = tmp_path / "direction-focus-selection-response.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["provider"] = "tampered"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((ContestDirectionFocusError, ValueError)):
        load_contest_direction_focus_selection(
            tmp_path / "direction-focus.json", broad_literature=broad
        )


def test_focus_projection_recovers_only_literal_inline_evidence_indices(
    tmp_path: Path,
) -> None:
    broad = _broad_artifact()
    brainstorm = _brainstorm_payload()
    first, second = brainstorm["focus_candidates"]
    first.pop("references")
    first["evidence_chain"] = "证据[1]与文献【2】支持该缺口；2024不是证据编号。"
    second.pop("evidence_indices")
    second["evidence_rationale_cn"] = "参考[2]和证据[3]支持有限样本核对。"
    responses = iter((brainstorm, _selection_payload()))

    artifact = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        completion=lambda **_: _completion(next(responses)),
    )

    assert artifact.candidates[0].evidence_indices == (1, 2)
    assert artifact.candidates[1].evidence_indices == (2, 3)


def test_partial_focus_resume_reuses_first_raw_response(tmp_path: Path) -> None:
    broad = _broad_artifact()
    first_calls = 0

    def interrupted(**_: Any) -> LLMJsonCompletionResult:
        nonlocal first_calls
        first_calls += 1
        if first_calls == 1:
            return _completion(_brainstorm_payload())
        raise TimeoutError("selection provider unavailable")

    with pytest.raises(TimeoutError):
        run_contest_direction_focus_selection(
            direction=broad.direction,
            broad_literature=broad,
            output_dir=tmp_path,
            completion=interrupted,
        )
    assert first_calls == 2
    assert (tmp_path / "direction-focus-brainstorm-response.json").is_file()
    assert not (tmp_path / "direction-focus-selection-response.json").exists()

    resumed_calls = 0

    def selection_only(**_: Any) -> LLMJsonCompletionResult:
        nonlocal resumed_calls
        resumed_calls += 1
        return _completion(_selection_payload())

    artifact = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        completion=selection_only,
    )
    assert resumed_calls == 1
    assert artifact.selected_candidate_number == 2


def test_targeted_retrieval_uses_selected_focus_without_skill_and_replays(
    tmp_path: Path,
) -> None:
    broad = _broad_artifact()
    focus_responses = iter((_brainstorm_payload(), _selection_payload()))
    focus = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        completion=lambda **_: _completion(next(focus_responses)),
    )
    query_calls: list[dict[str, Any]] = []
    search_calls: list[tuple[str, int]] = []

    def query_completion(**kwargs: Any) -> LLMJsonCompletionResult:
        query_calls.append(kwargs)
        return _completion(
            {
                "queries": _v4_query_plan(
                    object_terms=("consecutive prime gaps", "prime gap transitions"),
                    direct_terms=("finite interval", "heterogeneity"),
                    method_terms=("block permutation", "uncertainty analysis"),
                    mechanism_terms=("baseline", "null model"),
                )
            }
        )

    def search(query: str, *, limit: int) -> list[AcademicPaper]:
        search_calls.append((query, limit))
        index = len(search_calls)
        return [
            AcademicPaper(
                title=f"Targeted prime gap study {index}",
                authors=["Targeted Author"],
                abstract=f"Targeted evidence for query {query}.",
                publication_date=date(2025, 1, index),
                venue="Mathematics of Computation",
                doi=f"10.1000/targeted.{index}",
                url=f"https://example.org/targeted-{index}",
                citation_count=None,
                source="openalex",
            )
        ]

    binding = run_contest_direction_targeted_retrieval(
        focus=focus,
        output_dir=tmp_path,
        searchers={"openalex": search},
        completion=query_completion,
        max_results_per_search=7,
    )

    assert len(query_calls) == 1
    assert query_calls[0]["thinking_mode"] == "disabled"
    assert query_calls[0]["thinking_budget"] is None
    assert query_calls[0]["response_schema_name"] == "contest_direction_query_list"
    assert query_calls[0]["response_schema"] == {
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
    assert len(search_calls) == 4
    assert {limit for _query, limit in search_calls} == {7}
    assert focus.selected_candidate.title_cn in binding.targeted_search_context
    assert binding.selected_method_skills == ()
    assert binding.skills_available_to_targeted_query_model is False
    assert binding.retrieval_execution == "serial_existing_retriever_rate_limits"
    assert (
        binding.searcher_lifecycle == "caller_injected_reuse_required_for_cross_stage_rate_limits"
    )
    targeted = ContestDirectionLiteratureArtifact.model_validate_json(
        (tmp_path / "targeted-literature.json").read_text(encoding="utf-8")
    )
    assert targeted.method_skills == ()
    assert targeted.direction == binding.targeted_search_context
    prompt_payload = json.loads(query_calls[0]["messages"][2]["content"])
    prompt_text = json.dumps(query_calls[0]["messages"], ensure_ascii=False)
    assert prompt_payload["selected_method_skills"] == []
    assert "多尺度区间稳定性" in prompt_text
    assert (
        load_contest_direction_targeted_retrieval(
            tmp_path / "direction-targeted-retrieval.json", focus=focus
        )
        == binding
    )

    def forbidden(**_: Any) -> LLMJsonCompletionResult:
        raise AssertionError("completed targeted stage must not call the provider")

    resumed = run_contest_direction_targeted_retrieval(
        focus=focus,
        output_dir=tmp_path,
        searchers={
            "openalex": lambda _query, *, limit: (_ for _ in ()).throw(  # noqa: ARG005
                AssertionError()
            )
        },
        completion=forbidden,
    )
    assert resumed == binding


def test_incomplete_focus_candidates_fail_without_format_retry(tmp_path: Path) -> None:
    broad = _broad_artifact()
    calls = 0

    def completion(**_: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion(
            {
                "candidates": [
                    {
                        "title": "缺少证据与检索分组的候选",
                        "objective": "无法形成完整定向检索",
                    }
                ]
            }
        )

    with pytest.raises(ContestDirectionFocusError, match="fewer than two"):
        run_contest_direction_focus_selection(
            direction=broad.direction,
            broad_literature=broad,
            output_dir=tmp_path,
            completion=completion,
        )
    assert calls == 1


def test_pilot_capability_is_safe_feasibility_context_not_a_forced_direction(
    tmp_path: Path,
) -> None:
    broad = _broad_artifact()
    adapter = {
        "adapter_id": "prime-gap-permutation-pilot",
        "scientific_object": "consecutive_integer_primes",
        "observable": "ordered_consecutive_prime_gaps",
        "supported_metrics": ["tie_aware_normalized_permutation_entropy_m5"],
        "supported_nulls": ["global_permutation", "local_block_permutation"],
        "execution_boundary_zh": "只执行冻结整数区间上的连续素数间隔探索性预实验。",
        "description": "可比较真实序列与两个已注册置换零模型。",
        # These implementation/method fields must be discarded before prompting.
        "runner": "private.module.run_secret_adapter",
        "study_phase": "exploratory_pilot",
        "skill_body": "DO_NOT_LEAK_SKILL_BODY",
    }
    brainstorm = json.loads(json.dumps(_brainstorm_payload(), ensure_ascii=False))
    brainstorm["focus_candidates"][0].update(
        {
            "pilot_adapter_id": "prime-gap-permutation-pilot",
            "pilot_feasibility_cn": "该方向落在已声明的素数间隔预实验边界内。",
        }
    )
    brainstorm["focus_candidates"][1].update(
        {
            "pilot_adapter_id": "no_adapter",
            "pilot_feasibility_cn": "该多尺度方向当前没有能够完整执行的真实预实验适配器。",
        }
    )
    selection = {
        "selected_candidate_number": 2,
        "selection_rationale_cn": (
            "候选2的反例价值更高，但当前系统没有对应adapter，不能立即运行真实pilot；"
            "选择它仅表示继续定向检索，不表示已具备实验能力。"
        ),
    }
    responses = iter((brainstorm, selection))
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs)
        return _completion(next(responses))

    artifact = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        executable_adapter_capabilities=(adapter,),
        completion=completion,
    )

    assert len(calls) == 2
    for call in calls:
        prompt = json.dumps(call["messages"], ensure_ascii=False)
        assert "prime-gap-permutation-pilot" in prompt
        assert "只用于可行性判断" in prompt
        assert "不是事实证据" in prompt
        assert "DO_NOT_LEAK_SKILL_BODY" not in prompt
        assert "private.module.run_secret_adapter" not in prompt
        user_payload = json.loads(call["messages"][1]["content"])
        capability = user_payload["executable_pilot_capabilities"][0]
        assert set(capability) == {
            "adapter_id",
            "scientific_object",
            "observable",
            "supported_metrics",
            "supported_nulls",
            "execution_boundary_zh",
            "description",
        }
    assert artifact.selected_candidate.pilot_adapter_id == "no_adapter"
    assert "不能立即运行真实pilot" in artifact.selection_rationale_cn
    assert artifact.candidates[0].pilot_adapter_id == "prime-gap-permutation-pilot"
    assert artifact.candidates[1].title_cn == "多尺度区间稳定性与伪效应诊断"
    assert artifact.executable_adapter_capabilities[0].adapter_id == ("prime-gap-permutation-pilot")
    assert artifact.adapter_capability_boundary == (
        "feasibility_only_not_evidence_method_answer_or_forced_choice"
    )
    raw_artifact = (tmp_path / "direction-focus.json").read_text(encoding="utf-8")
    assert "private.module.run_secret_adapter" not in raw_artifact
    assert "DO_NOT_LEAK_SKILL_BODY" not in raw_artifact
    assert (
        load_contest_direction_focus_selection(
            tmp_path / "direction-focus.json",
            broad_literature=broad,
            executable_adapter_capabilities=(adapter,),
        )
        == artifact
    )


def test_focus_semantic_gate_downgrades_derived_prime_signature_gap(
    tmp_path: Path,
) -> None:
    broad = _broad_artifact()
    adapter = {
        "adapter_id": "prime-gap-information-theory-v1",
        "scientific_object": "consecutive_integer_primes",
        "observable": "ordered_consecutive_prime_gaps",
        "supported_metrics": ["tie_aware_normalized_permutation_entropy_m5"],
        "supported_nulls": ["local_block_permutation"],
        "execution_boundary_zh": (
            "只生成整数连续素数并计算相邻素数的普通算术差；不构造素数签名或其他度量空间。"
        ),
    }
    brainstorm = json.loads(json.dumps(_brainstorm_payload(), ensure_ascii=False))
    brainstorm["focus_candidates"][0].update(
        {
            "focused_direction_cn": (
                "构造素数签名，并以签名之间的ℓ∞度量诱导相邻素数间隙，再计算排列熵。"
            ),
            "pilot_adapter_id": "prime-gap-information-theory-v1",
            "pilot_feasibility_cn": "题面含有素数、间隙和排列熵，因此声称可执行。",
        }
    )
    selection = {
        "selected_candidate_number": 1,
        "selection_rationale_cn": "选择候选1，但遵守程序给出的可执行性边界。",
    }
    responses = iter((brainstorm, selection))

    artifact = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        executable_adapter_capabilities=(adapter,),
        completion=lambda **_: _completion(next(responses)),
    )

    candidate = artifact.candidates[0]
    assert candidate.pilot_adapter_id == "no_adapter"
    assert "程序语义兼容性门拒绝" in candidate.pilot_feasibility_cn
    assert "linfinity_metric" in candidate.pilot_feasibility_cn


def test_withdrawn_arxiv_shortlist_record_is_excluded_and_refilled(
    tmp_path: Path,
) -> None:
    broad = _arxiv_broad_artifact()
    verifier_calls: list[str] = []
    seen_prompts: list[str] = []
    responses = iter((_brainstorm_payload(), _selection_payload()))

    def verify(paper: AcademicPaper) -> AcademicPaper:
        verifier_calls.append(str(paper.url))
        if len(verifier_calls) == 1:
            return paper.model_copy(
                update={
                    "publication_status": "withdrawn",
                    "status_source": "arxiv_abs",
                    "status_as_of": NOW.date(),
                }
            )
        return paper.model_copy(
            update={
                "publication_status": "preprint",
                "status_source": "arxiv_abs",
                "status_as_of": NOW.date(),
            }
        )

    def completion(**kwargs: Any) -> LLMJsonCompletionResult:
        seen_prompts.append(json.dumps(kwargs["messages"], ensure_ascii=False))
        return _completion(next(responses))

    artifact = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        publication_status_verifier=verify,
        completion=completion,
    )
    receipt = ContestDirectionFocusStatusReceipt.model_validate_json(
        (tmp_path / "direction-focus-status-verification.json").read_text(encoding="utf-8")
    )

    withdrawn_record_id = str(receipt.candidate_pool[0]["record_id"])
    withdrawn_title = next(
        item.title for item in broad.retrieved_records if item.record_id == withdrawn_record_id
    )
    assert receipt.checks[0].record_id == withdrawn_record_id
    assert receipt.checks[0].outcome == "verified_withdrawn_excluded"
    assert receipt.target_evidence_count == receipt.retained_count == 16
    assert len(receipt.checks) == len(verifier_calls) == 17
    assert withdrawn_record_id not in receipt.retained_record_ids
    assert tuple(item.record_id for item in artifact.focus_evidence) == (
        receipt.retained_record_ids
    )
    assert str(receipt.candidate_pool[16]["record_id"]) in receipt.retained_record_ids
    assert all(withdrawn_title not in prompt for prompt in seen_prompts)
    assert all(item.publication_status != "withdrawn" for item in artifact.focus_evidence)
    assert artifact.broad_publication_status_verification == (
        "shortlisted_arxiv_status_rechecked_complete"
    )


def test_status_verifier_failure_preserves_upstream_unknown_as_degraded(
    tmp_path: Path,
) -> None:
    broad = _arxiv_broad_artifact(publication_status="unknown")
    responses = iter((_brainstorm_payload(), _selection_payload()))

    def fail_verify(paper: AcademicPaper) -> AcademicPaper:
        raise TimeoutError(f"cannot verify {paper.url}")

    artifact = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        publication_status_verifier=fail_verify,
        completion=lambda **_: _completion(next(responses)),
    )
    receipt = ContestDirectionFocusStatusReceipt.model_validate_json(
        (tmp_path / "direction-focus-status-verification.json").read_text(encoding="utf-8")
    )

    assert receipt.verification_state == "degraded"
    assert receipt.degraded_count == len(receipt.checks) == 16
    assert all(
        item.outcome == "verification_failed_preserved_upstream_degraded" for item in receipt.checks
    )
    assert all(item.original_status == "unknown" for item in receipt.checks)
    assert all(item.verified_status == "unknown" for item in receipt.checks)
    assert all(item.retained_for_focus for item in receipt.checks)
    assert artifact.broad_publication_status_verification == (
        "shortlisted_arxiv_status_rechecked_degraded"
    )
    assert all(
        item.publication_status_verification
        == "verification_failed_preserved_upstream_status_degraded"
        for item in artifact.focus_evidence
    )


def test_status_receipt_resume_is_zero_network_and_tamper_rejected(
    tmp_path: Path,
) -> None:
    broad = _arxiv_broad_artifact()
    responses = iter((_brainstorm_payload(), _selection_payload()))
    verifier_calls = 0

    def verify(paper: AcademicPaper) -> AcademicPaper:
        nonlocal verifier_calls
        verifier_calls += 1
        return paper.model_copy(
            update={
                "status_source": "arxiv_abs",
                "status_as_of": NOW.date(),
            }
        )

    artifact = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        publication_status_verifier=verify,
        completion=lambda **_: _completion(next(responses)),
    )
    assert verifier_calls == 16

    def forbidden_verify(_: AcademicPaper) -> AcademicPaper:
        raise AssertionError("resume must not call status verifier")

    resumed = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path,
        publication_status_verifier=forbidden_verify,
        completion=lambda **_: (_ for _ in ()).throw(AssertionError("no model replay")),
    )
    assert resumed == artifact

    status_path = tmp_path / "direction-focus-status-verification.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    payload["checks"][0]["verified_status"] = "withdrawn"
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((ContestDirectionFocusError, ValueError)):
        load_contest_direction_focus_selection(
            tmp_path / "direction-focus.json",
            broad_literature=broad,
            require_publication_status_verification=True,
        )
