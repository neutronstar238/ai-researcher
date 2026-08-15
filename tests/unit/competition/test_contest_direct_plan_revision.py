"""Tests for one-shot direct-plan revision from verified pilot evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.contest_direct_plan import generate_contest_direct_plan
from autoresearch.competition.contest_direct_plan_render import validate_contest_plan_payload
from autoresearch.competition.contest_direct_plan_revision import (
    ContestDirectPlanRevisionError,
    revise_contest_direct_plan,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.llm.client import LLMJsonCompletionResult


def _original_payload() -> dict[str, Any]:
    return {
        "problem_statement": "有限尺度素数间隙是否呈现超越边际分布的顺序结构？",
        "rationale": "比较真实序列与多个零模型，以检验局部顺序结构。",
        "technical_details": "计算排列熵与块熵，并报告不确定度。",
        "datasets": "使用不超过一百万的素数间隙序列。",
        "source": "由确定性筛法在本地生成。",
        "target": "目标是检验真实序列相对零模型的熵差。",
        "paper_title": "有限尺度素数间隙顺序结构检验",
        "paper_abstract": "本研究计划比较真实素数间隙与置换对照。",
        "methods": "计算序列统计量并与零模型比较。",
        "experiments": "生成数据、运行对照并执行稳健性分析。",
        "baselines": "使用全局置换和 wheel null。",
        "metrics": "主要指标为标准化排列熵差。",
        "results": "尚未执行预实验；结果将按预注册判据解释。",
        "references": [1],
    }


def _revised_payload() -> dict[str, Any]:
    return {
        "problem_statement": "有限尺度素数间隙的弱全局差异能否经受局部分块置换对照？",
        "rationale": "预实验观察到全局置换差异为0.12，但局部分块置换差异为0.01，故收窄原解释。",
        "technical_details": "分别实现全局置换、局部分块置换与wheel null，并保持其条件结构。",
        "datasets": "使用预实验同源素数间隙，并在正式实验扩大区间。",
        "source": "预实验数据由本地确定性筛法生成，正式实验沿用可复现流程。",
        "target": "区分边际频率效应与局部顺序依赖。",
        "paper_title": "素数间隙弱顺序结构的分层零模型检验",
        "paper_abstract": "探索性预实验显示0.12的全局差异在更强对照下缩小为0.01，因此计划检验更窄假设。",
        "main_hypothesis": "原强假设暂不支持；收窄为仅检验超出局部条件结构的残余顺序依赖。",
        "methods": "分别估计三种零模型，不把wheel null与permutation null合并。",
        "experiments": "正式实验将扩大样本并独立重复局部分块置换检验。",
        "baselines": "分别报告wheel null、全局permutation null与局部分块permutation null。",
        "metrics": "报告标准化熵差、区间估计与零模型间敏感性。",
        "results": "预实验真实观察为全局差异0.12、局部分块差异0.01；替代解释是边际结构造成弱差异。",
        "limitations": "本次预实验规模有限且为探索性protocol amendment，不能替代正式实验。",
        "references": [1, 2],
    }


def _completion(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    response = json.dumps(payload, ensure_ascii=False)
    return LLMJsonCompletionResult(
        provider="openai-compatible",
        base_url="https://provider.example/v1",
        model_name="qwen-test",
        endpoint="https://provider.example/v1/chat/completions",
        response_text=response,
        parsed_json=payload,
        usage={"prompt_tokens": 100, "completion_tokens": 200},
        temperature=0.2,
    )


def _original_plan() -> Any:
    return generate_contest_direct_plan(
        scientific_problem="素数为何如此特别？",
        literature_context=("Bandt & Pompe (2002)",),
        llm_call=lambda **_: _completion(_original_payload()),
    )


def _pilot(tmp_path: Path) -> tuple[Path, Path, tuple[dict[str, str], ...]]:
    metrics_path = tmp_path / "metrics.json"
    log_path = tmp_path / "pilot.log"
    metrics = {
        "global_permutation_gap": 0.12,
        "local_block_gap": 0.01,
        "fine_delta": -0.00115344,
        "residue_conditioned_variable_position_fraction": 0.929353,
        "standardized_effect_a": -7.526,
        "standardized_effect_b": -85.149,
        "standardized_effect_c": -30.946,
        "standardized_effect_truncation_case": -7.465853262881276,
        "fixed_interval_resampling_delta_ci95": [-0.0024, 0.0001],
        "primary_metric": "tie_aware_normalized_permutation_entropy_m5",
        "intervals": [
            [1_000_000, 2_000_000],
            [5_000_000, 6_000_000],
            [10_000_000, 11_000_000],
            [20_000_000, 21_000_000],
            [50_000_000, 51_000_000],
        ],
    }
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False),
        encoding="utf-8",
    )
    log_path.write_text(
        "pilot completed; wheel null and permutation null were run separately\n",
        encoding="utf-8",
    )
    bindings = (
        {
            "role": "metrics",
            "path": metrics_path.name,
            "sha256": hashlib.sha256(metrics_path.read_bytes()).hexdigest(),
        },
        {
            "role": "execution_log",
            "path": log_path.name,
            "sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        },
    )
    artifact: dict[str, Any] = {
        "schema_version": "prime-pilot-v1",
        "metrics": metrics,
        "raw_file_bindings": list(bindings),
        "preliminary_only": True,
        "output_path": (tmp_path / "pilot.json").as_posix(),
    }
    artifact["artifact_hash"] = canonical_model_hash(artifact)
    artifact_path = tmp_path / "pilot.json"
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    return artifact_path, metrics_path, bindings


def test_one_call_verifies_files_orders_messages_and_retains_receipt(tmp_path: Path) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    calls: list[dict[str, Any]] = []

    def fake_call(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs)
        return _completion(_revised_payload())

    references = (
        "Bandt & Pompe (2002), Permutation Entropy.",
        "Gallagher (1976), On the distribution of primes in short intervals.",
    )
    memory_context = {
        "context_kind": "optional_rebuildable_dreaming_navigation",
        "recall_hash": "a" * 64,
        "epistemic_boundary_zh": (
            "Dreaming 只是可删除、可重建的导航上下文，不是文献、实验结果或科学证据；"
            "任何科学陈述仍须读取并核验所绑定的原始制品。"
        ),
        "derived_context_is_evidence": False,
        "model_consumption_proven_by_this_receipt": False,
        "projections": [{"source_stage": "real-pilot", "summary": "只用于导航"}],
    }
    result = revise_contest_direct_plan(
        original_plan=_original_plan().model_dump(mode="json"),
        scientific_problem="素数为何如此特别？",
        requirements=("中文研究计划", "基于真实预实验修订"),
        selected_skill_contexts=({"name": "prime-method", "content": "只提供计算数论实验方法。"},),
        reference_catalog=references,
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        derived_memory_context=memory_context,
        output_dir=tmp_path / "revision",
        llm_call=fake_call,
    )

    assert len(calls) == 1
    messages = calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert json.loads(messages[1]["content"])["context_kind"] == (
        "research_question_requirements_and_locked_references"
    )
    assert json.loads(messages[2]["content"])["context_kind"] == (
        "system_selected_project_method_skill"
    )
    assert json.loads(messages[3]["content"])["context_kind"] == ("original_complete_research_plan")
    evidence = json.loads(messages[4]["content"])
    assert evidence["context_kind"] == "program_verified_exploratory_preexperiment"
    assert "global_permutation_gap" in evidence["verified_files"][0]["verified_text"]
    recalled = json.loads(messages[5]["content"])
    assert recalled["context_kind"] == "optional_rebuildable_dreaming_navigation"
    assert recalled["derived_context_is_evidence"] is False
    assert recalled["scientific_claims_require_exact_source_artifact"] is True
    assert "wheel null" in messages[6]["content"]
    assert "收窄、反转或放弃" in messages[6]["content"]
    assert result.generation_calls == 1
    assert result.plan.main_hypothesis.startswith("原强假设暂不支持")
    assert result.plan.references == references
    assert result.reference_projection is not None
    assert result.reference_projection.policy == "locked-catalog-exact-order-v2"
    assert result.reference_projection.model_selected_indices == (1, 2)
    assert result.reference_projection.program_supplemented_indices == tuple(
        range(3, len(references) + 1)
    )
    assert (tmp_path / "revision" / result.raw_response_relative_path).is_file()
    receipt_path = tmp_path / "revision" / result.authorship_receipt_relative_path
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["response_text"] == json.dumps(_revised_payload(), ensure_ascii=False)
    validate_contest_plan_payload(result.flat_payload())


def test_versioned_revision_accepts_prior_revision_and_binds_verified_context(
    tmp_path: Path,
) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    references = ("Bandt & Pompe (2002), Permutation Entropy.",)
    first = revise_contest_direct_plan(
        original_plan=_original_plan(),
        scientific_problem="素数为何如此特别？",
        requirements="第一次证据修订",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=references,
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        output_dir=tmp_path / "revision-v1",
        llm_call=lambda **_: _completion(_revised_payload()),
    )
    captured: list[dict[str, Any]] = []
    payload = _revised_payload()
    payload["technical_details"] += "弱序秩模式总数为Fubini(5)=541。"
    verified_context = {
        "amendment": "只修正方法定义，不新增观察",
        "ordered_bell_number_m5": 541,
    }

    def second_call(**kwargs: Any) -> LLMJsonCompletionResult:
        captured.append(kwargs)
        return _completion(payload)

    second = revise_contest_direct_plan(
        original_plan=first,
        scientific_problem="素数为何如此特别？",
        requirements="版本化科学修订",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=references,
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        verified_revision_context=verified_context,
        output_dir=tmp_path / "revision-v2",
        llm_call=second_call,
    )

    assert second.original_plan_id == first.revision_id
    assert second.original_plan_artifact_hash == first.artifact_hash
    assert second.verified_revision_context_sha256 == canonical_model_hash(verified_context)
    context_messages = [
        json.loads(item["content"])
        for item in captured[0]["messages"]
        if item["content"].startswith("{")
        and "program_verified_revision_context" in item["content"]
    ]
    assert context_messages[0]["context"]["ordered_bell_number_m5"] == 541


def test_hash_mismatch_fails_before_model_call(tmp_path: Path) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    log_path = tmp_path / "pilot.log"
    log_path.write_text("tampered\n", encoding="utf-8")
    calls = 0

    def should_not_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion(_revised_payload())

    with pytest.raises(ContestDirectPlanRevisionError, match="SHA-256 mismatch"):
        revise_contest_direct_plan(
            original_plan=_original_plan(),
            scientific_problem="素数为何如此特别？",
            requirements="中文研究计划",
            selected_skill_contexts=("计算数论方法。",),
            reference_catalog=("Bandt & Pompe (2002)",),
            preexperiment_artifact=payload,
            preexperiment_root=tmp_path,
            output_dir=tmp_path / "revision",
            llm_call=should_not_call,
        )
    assert calls == 0


def test_metrics_path_must_be_bound_by_manifest_or_explicit_binding(tmp_path: Path) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    unbound = tmp_path / "unbound-metrics.json"
    unbound.write_text('{"effect": 0.12}', encoding="utf-8")
    with pytest.raises(ContestDirectPlanRevisionError, match="metrics file is not covered"):
        revise_contest_direct_plan(
            original_plan=_original_plan(),
            scientific_problem="素数为何如此特别？",
            requirements="中文研究计划",
            selected_skill_contexts=("计算数论方法。",),
            reference_catalog=("Bandt & Pompe (2002)",),
            preexperiment_artifact=artifact_path,
            preexperiment_metrics=unbound,
            output_dir=tmp_path / "revision",
            llm_call=lambda **_: _completion(_revised_payload()),
        )


def test_conflicting_duplicate_file_binding_is_rejected(tmp_path: Path) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    with pytest.raises(ContestDirectPlanRevisionError, match="conflicting SHA-256"):
        revise_contest_direct_plan(
            original_plan=_original_plan(),
            scientific_problem="素数为何如此特别？",
            requirements="中文研究计划",
            selected_skill_contexts=("计算数论方法。",),
            reference_catalog=("Bandt & Pompe (2002)",),
            preexperiment_artifact=artifact_path,
            preexperiment_metrics=metrics_path,
            raw_file_bindings=({"path": metrics_path.name, "sha256": "0" * 64, "role": "metrics"},),
            output_dir=tmp_path / "revision",
            llm_call=lambda **_: _completion(_revised_payload()),
        )


def test_invented_observed_number_is_rejected_without_retry(tmp_path: Path) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] += "，并观察到0.99的额外效应。"
    calls = 0

    def one_bad_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion(payload)

    revision_root = tmp_path / "revision"
    with pytest.raises(
        ContestDirectPlanRevisionError,
        match="absent from verified preexperiment evidence",
    ):
        revise_contest_direct_plan(
            original_plan=_original_plan(),
            scientific_problem="素数为何如此特别？",
            requirements="中文研究计划",
            selected_skill_contexts=("计算数论方法。",),
            reference_catalog=("Bandt & Pompe (2002)",),
            preexperiment_artifact=artifact_path,
            preexperiment_metrics=metrics_path,
            output_dir=revision_root,
            llm_call=one_bad_call,
        )
    assert calls == 1
    assert len(tuple((revision_root / "responses").glob("*.txt"))) == 1
    assert len(tuple((revision_root / "interactions").glob("*.json"))) == 1


def test_verified_rounding_percent_ci_and_model_labels_are_accepted(
    tmp_path: Path,
) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] = (
        "预实验的细粒度差异约为-0.0012，条件化可变位置比例为0.9294（亦即92.94%），"
        "两项标准化效应约为-7.5和-85；同时报告95% CI与m=5指标。"
        "替代解释是筛结构和局部条件造成表面差异。"
    )

    result = revise_contest_direct_plan(
        original_plan=_original_plan(),
        scientific_problem="素数为何如此特别？",
        requirements="中文研究计划",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=("Bandt & Pompe (2002)",),
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        output_dir=tmp_path / "revision",
        llm_call=lambda **_: _completion(payload),
    )

    assert "-0.0012" in result.plan.results
    assert "-85" in result.plan.results
    assert "92.94%" in result.plan.results
    assert "95% CI" in result.plan.results


def test_verified_decimal_truncation_is_accepted_but_adjacent_bin_is_not(
    tmp_path: Path,
) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] = "预实验标准化效应为-7.4；替代解释是筛结构和局部条件造成表面差异。"

    result = revise_contest_direct_plan(
        original_plan=_original_plan(),
        scientific_problem="素数为何如此特别？",
        requirements="中文研究计划",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=("Bandt & Pompe (2002)",),
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        output_dir=tmp_path / "accepted-truncation-revision",
        llm_call=lambda **_: _completion(payload),
    )
    assert "-7.4" in result.plan.results

    payload["results"] = "预实验标准化效应为-7.3；替代解释是筛结构和局部条件造成表面差异。"
    with pytest.raises(
        ContestDirectPlanRevisionError,
        match="absent from verified preexperiment evidence",
    ):
        revise_contest_direct_plan(
            original_plan=_original_plan(),
            scientific_problem="素数为何如此特别？",
            requirements="中文研究计划",
            selected_skill_contexts=("计算数论方法。",),
            reference_catalog=("Bandt & Pompe (2002)",),
            preexperiment_artifact=artifact_path,
            preexperiment_metrics=metrics_path,
            output_dir=tmp_path / "rejected-adjacent-bin-revision",
            llm_call=lambda **_: _completion(payload),
        )


def test_coarse_trailing_zero_range_endpoint_is_accepted_but_distant_one_is_not(
    tmp_path: Path,
) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] = "预实验观察到标准化效应约为-85至-30；替代解释是筛结构造成表面差异。"

    result = revise_contest_direct_plan(
        original_plan=_original_plan(),
        scientific_problem="素数为何如此特别？",
        requirements="中文研究计划",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=("Bandt & Pompe (2002)",),
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        output_dir=tmp_path / "accepted-revision",
        llm_call=lambda **_: _completion(payload),
    )
    assert "-85至-30" in result.plan.results

    payload["results"] = "预实验观察到标准化效应约为-85至-20；替代解释是筛结构造成表面差异。"
    with pytest.raises(
        ContestDirectPlanRevisionError,
        match="absent from verified preexperiment evidence",
    ):
        revise_contest_direct_plan(
            original_plan=_original_plan(),
            scientific_problem="素数为何如此特别？",
            requirements="中文研究计划",
            selected_skill_contexts=("计算数论方法。",),
            reference_catalog=("Bandt & Pompe (2002)",),
            preexperiment_artifact=artifact_path,
            preexperiment_metrics=metrics_path,
            output_dir=tmp_path / "rejected-revision",
            llm_call=lambda **_: _completion(payload),
        )


def test_future_plan_and_unexcluded_candidate_numbers_are_not_observed_claims(
    tmp_path: Path,
) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] = (
        "预实验观察到全局置换差异0.12。替代解释是现有筛结构。"
        "【后续正式实验计划】建议新增模2310候选对照，并运行1000次敏感性分析。"
    )
    payload["limitations"] = "本次预实验仍有边界；不能排除更高阶筛效应（例如模2310约束）。"

    result = revise_contest_direct_plan(
        original_plan=_original_plan(),
        scientific_problem="素数为何如此特别？",
        requirements="中文研究计划",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=("Bandt & Pompe (2002)",),
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        output_dir=tmp_path / "revision",
        llm_call=lambda **_: _completion(payload),
    )

    assert "模2310候选对照" in result.plan.results
    assert "运行1000次" in result.plan.results
    assert "例如模2310约束" in result.plan.limitations


def test_numeric_alternative_cause_is_not_relabelled_as_observed(
    tmp_path: Path,
) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] = "预实验观察到差异0.12；替代解释是现有筛结构。"
    payload["limitations"] = "本次预实验仍有边界；残差信号可能源于更深层模约束（如模2310）。"

    result = revise_contest_direct_plan(
        original_plan=_original_plan(),
        scientific_problem="素数为何如此特别？",
        requirements="中文研究计划",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=("Bandt & Pompe (2002)",),
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        output_dir=tmp_path / "revision",
        llm_call=lambda **_: _completion(payload),
    )

    assert "可能源于更深层模约束" in result.plan.limitations


def test_unverified_number_in_observed_clause_is_still_rejected(tmp_path: Path) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] = "预实验观察到模2310约束下的差异为0.12；替代解释是现有筛结构。"

    with pytest.raises(
        ContestDirectPlanRevisionError,
        match="absent from verified preexperiment evidence",
    ):
        revise_contest_direct_plan(
            original_plan=_original_plan(),
            scientific_problem="素数为何如此特别？",
            requirements="中文研究计划",
            selected_skill_contexts=("计算数论方法。",),
            reference_catalog=("Bandt & Pompe (2002)",),
            preexperiment_artifact=artifact_path,
            preexperiment_metrics=metrics_path,
            output_dir=tmp_path / "revision",
            llm_call=lambda **_: _completion(payload),
        )


def test_multiplication_scientific_notation_matches_integer_evidence(
    tmp_path: Path,
) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] = (
        "预实验覆盖区间[1.0×10^7,1.1×10^7)、[2.0*10^7,2.1*10^7)与"
        "[5.0·10^7,5.1·10^7)，并以1.0e7作为首个下界；观察差异为0.12。"
        "替代解释是筛结构造成表面差异。"
    )

    result = revise_contest_direct_plan(
        original_plan=_original_plan(),
        scientific_problem="素数为何如此特别？",
        requirements="中文研究计划",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=("Bandt & Pompe (2002)",),
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        output_dir=tmp_path / "revision",
        llm_call=lambda **_: _completion(payload),
    )

    assert "1.1×10^7" in result.plan.results
    assert "5.1·10^7" in result.plan.results


def test_latex_scientific_notation_matches_integer_evidence(tmp_path: Path) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] = (
        "预实验覆盖$5.1\times10^7$"
        r"与$2.1\cdot 10^{7}$边界，并观察差异0.12；"
        "替代解释是筛结构造成表面差异。"
    )

    result = revise_contest_direct_plan(
        original_plan=_original_plan(),
        scientific_problem="素数为何如此特别？",
        requirements="中文研究计划",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=("Bandt & Pompe (2002)",),
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        output_dir=tmp_path / "revision",
        llm_call=lambda **_: _completion(payload),
    )

    assert "5.1\times10^7" in result.plan.results
    assert r"2.1\cdot 10^{7}" in result.plan.results


def test_non_equivalent_scientific_mantissa_is_rejected(tmp_path: Path) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] = (
        "预实验覆盖了[1.2×10^7,1.3×10^7)并观察差异0.12；" "替代解释是筛结构造成表面差异。"
    )

    with pytest.raises(
        ContestDirectPlanRevisionError,
        match="absent from verified preexperiment evidence",
    ):
        revise_contest_direct_plan(
            original_plan=_original_plan(),
            scientific_problem="素数为何如此特别？",
            requirements="中文研究计划",
            selected_skill_contexts=("计算数论方法。",),
            reference_catalog=("Bandt & Pompe (2002)",),
            preexperiment_artifact=artifact_path,
            preexperiment_metrics=metrics_path,
            output_dir=tmp_path / "revision",
            llm_call=lambda **_: _completion(payload),
        )


def test_million_suffix_and_power_of_ten_match_integer_evidence(tmp_path: Path) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] = (
        "预实验覆盖[1M,2M)、[5 million,6 million)、[20百万,21百万)与"
        "[50M,51M)，各区间宽度为10^6；观察差异为0.12。"
        "替代解释是筛结构造成表面差异。"
    )

    result = revise_contest_direct_plan(
        original_plan=_original_plan(),
        scientific_problem="素数为何如此特别？",
        requirements="中文研究计划",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=("Bandt & Pompe (2002)",),
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        output_dir=tmp_path / "revision",
        llm_call=lambda **_: _completion(payload),
    )

    assert "[50M,51M)" in result.plan.results
    assert "10^6" in result.plan.results


def test_unverified_million_suffix_remains_rejected(tmp_path: Path) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["results"] = "预实验覆盖[50M,52M)并观察差异0.12；替代解释是筛结构造成表面差异。"

    with pytest.raises(
        ContestDirectPlanRevisionError,
        match="absent from verified preexperiment evidence",
    ):
        revise_contest_direct_plan(
            original_plan=_original_plan(),
            scientific_problem="素数为何如此特别？",
            requirements="中文研究计划",
            selected_skill_contexts=("计算数论方法。",),
            reference_catalog=("Bandt & Pompe (2002)",),
            preexperiment_artifact=artifact_path,
            preexperiment_metrics=metrics_path,
            output_dir=tmp_path / "revision",
            llm_call=lambda **_: _completion(payload),
        )


def test_nested_and_chinese_keys_are_normalized_locally(tmp_path: Path) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    payload = _revised_payload()
    payload["数据集"] = {
        "description": payload.pop("datasets"),
        "Source": payload.pop("source"),
        "Target": payload.pop("target"),
    }
    payload["实验设计"] = {
        "steps": payload.pop("experiments"),
        "Baselines": payload.pop("baselines"),
        "Metrics": payload.pop("metrics"),
    }
    result = revise_contest_direct_plan(
        original_plan=_original_plan().model_dump_json(),
        scientific_problem="素数为何如此特别？",
        requirements="中文研究计划",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=("Bandt & Pompe (2002)",),
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        output_dir=tmp_path / "revision",
        llm_call=lambda **_: _completion(payload),
    )
    assert result.plan.source.startswith("预实验数据")
    assert result.plan.experiments.startswith("正式实验")


def test_prime_artifact_relative_manifest_schema_is_consumed_without_adapter(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "metrics.json"
    stdout_path = tmp_path / "stdout.log"
    raw_path = tmp_path / "interval-01.csv"
    metrics_path.write_text(
        json.dumps(
            {"global_permutation_gap": 0.12, "local_block_gap": 0.01},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stdout_path.write_text("program_status=completed\n", encoding="utf-8")
    raw_path.write_text("gap\n2\n4\n", encoding="utf-8")

    evidence_files = [
        {
            "relative_path": metrics_path.name,
            "sha256": hashlib.sha256(metrics_path.read_bytes()).hexdigest(),
            "bytes": metrics_path.stat().st_size,
            "kind": "metrics",
        },
        {
            "relative_path": stdout_path.name,
            "sha256": hashlib.sha256(stdout_path.read_bytes()).hexdigest(),
            "bytes": stdout_path.stat().st_size,
            "kind": "stdout_log",
        },
        {
            "relative_path": raw_path.name,
            "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "bytes": raw_path.stat().st_size,
            "kind": "raw_prime_gaps",
        },
    ]
    manifest = {
        "schema_version": "contest-prime-preexperiment-manifest-v1",
        "program_status": "completed",
        "files": evidence_files,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    artifact: dict[str, Any] = {
        "schema_version": "contest-prime-preexperiment-artifact-v1",
        "status": "completed",
        "study_phase": "exploratory_pilot",
        "protocol_status": "protocol_amended_before_execution",
        "aggregate_results": [
            {"null_model": "global_permutation", "delta": 0.12},
            {"null_model": "local_block_permutation", "delta": 0.01},
        ],
        "metrics_relative_path": metrics_path.name,
        "metrics_sha256": evidence_files[0]["sha256"],
        "stdout_log_relative_path": stdout_path.name,
        "stdout_log_sha256": evidence_files[1]["sha256"],
        "manifest_relative_path": manifest_path.name,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "evidence_files": evidence_files,
    }
    artifact["artifact_hash"] = canonical_model_hash(artifact)
    artifact_path = tmp_path / "prime-preexperiment.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    captured: list[dict[str, Any]] = []

    def fake_call(**kwargs: Any) -> LLMJsonCompletionResult:
        captured.append(kwargs)
        return _completion(_revised_payload())

    result = revise_contest_direct_plan(
        original_plan=_original_plan(),
        scientific_problem="素数为何如此特别？",
        requirements="中文研究计划",
        selected_skill_contexts=("计算数论方法。",),
        reference_catalog=("Bandt & Pompe (2002)",),
        preexperiment_artifact=artifact_path,
        output_dir=tmp_path / "revision",
        llm_call=fake_call,
    )

    by_name = {Path(item.path).name: item for item in result.verified_files}
    assert by_name["metrics.json"].text_supplied_to_model is True
    assert by_name["stdout.log"].text_supplied_to_model is True
    assert by_name["interval-01.csv"].text_supplied_to_model is False
    evidence_message = json.loads(captured[0]["messages"][-2]["content"])
    assert evidence_message["metrics"]["global_permutation_gap"] == 0.12
    assert any(
        item["verified_text"] == "program_status=completed\n"
        for item in evidence_message["verified_files"]
    )
