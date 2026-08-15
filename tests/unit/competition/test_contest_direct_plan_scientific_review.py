"""Tests for the one-shot independent review of a final contest plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.contest_direct_plan import generate_contest_direct_plan
from autoresearch.competition.contest_direct_plan_scientific_review import (
    ContestDirectPlanScientificReviewError,
    load_contest_direct_plan_scientific_review,
    review_contest_direct_plan_science,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.llm.client import LLMJsonCompletionResult


def _completion(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    response = json.dumps(payload, ensure_ascii=False)
    return LLMJsonCompletionResult(
        provider="openai-compatible",
        base_url="https://provider.example/v1",
        model_name="qwen-test",
        endpoint="https://provider.example/v1/chat/completions",
        response_text=response,
        parsed_json=payload,
        usage={"prompt_tokens": 120, "completion_tokens": 240},
        temperature=0.2,
    )


def _plan_payload() -> dict[str, Any]:
    return {
        "problem_statement": "有限尺度素数间隙是否存在超越模算术约束的顺序结构？",
        "rationale": "通过逐层增强零模型区分边际分布、局部密度与模约束。",
        "technical_details": "使用并列感知排列熵，并分别报告四类零模型。",
        "datasets": "使用五个固定且不相交的有限数值区间。",
        "source": "由确定性筛法生成素数并保存原始间隙。",
        "target": "检验残基路径条件置换后是否仍有残余顺序差异。",
        "paper_title": "有限尺度素数间隙顺序结构的分层零模型检验",
        "paper_abstract": "本计划依据探索性预实验收窄假设，并规划后续正式实验。",
        "methods": "计算排列熵并分别比较全局、局部、残基路径和 wheel 零模型。",
        "experiments": "后续正式实验将扩大固定区间并冻结分析协议。",
        "baselines": "四类零模型分别回答不同问题，不合并解释。",
        "metrics": "报告熵差、经验p值、Holm校正及区间重采样范围。",
        "results": "预实验观察到强约束零模型下效应收缩，不能作为正式结论。",
        "references": ["Bandt & Pompe (2002)", "Gallagher (1976)"],
    }


def _final_plan() -> Any:
    return generate_contest_direct_plan(
        scientific_problem="素数为何如此特别？",
        literature_context=("Bandt & Pompe (2002)", "Gallagher (1976)"),
        preexperiment_context={"status": "exploratory_pilot"},
        llm_call=lambda **_: _completion(_plan_payload()),
    )


def _review_payload() -> dict[str, Any]:
    return {
        "recommendation": "大修",
        "problem_restatement": "问题是有限区间内的残余顺序结构能否超越已控制的模算术约束。",
        "strongest_counterevidence": "强条件零模型下效应大幅缩小，差异可能主要来自筛结构。",
        "summary": "计划边界诚实且证据可追溯，但正式实验前仍需解决分析单位与外推问题。",
        "hypothesis_evidence_assessment": "预实验支持收窄而非确认原强假设。",
        "null_controls_assessment": "四类零模型应分别解释，残基路径与wheel不能互换。",
        "analysis_unit_assessment": "五个固定区间是描述性分析块，不是数轴总体的随机样本。",
        "statistics_assessment": "经验p值与固定区间重采样范围不能称为总体推断。",
        "overclaim_assessment": "计划没有声称证明开放猜想，但摘要仍需保持有限尺度措辞。",
        "reproducibility_assessment": "原始间隙、零模型抽样、参数、日志和哈希足以支持重放。",
        "references_assessment": "目录覆盖排列熵与短区间素数背景，但需明确各文献支持的具体环节。",
        "strengths": ["真实预实验与计划逐项绑定", "主动报告强零模型下的效应收缩"],
        "major_issues": ["正式实验必须先冻结分析单位与跨区间外推目标。"],
        "minor_issues": ["建议在指标定义旁明确区间重采样范围的解释。"],
        "reference_indices": [1, 2],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pilot(tmp_path: Path) -> tuple[Path, Path, Path]:
    pilot_root = tmp_path / "pilot"
    pilot_root.mkdir()
    metrics_path = pilot_root / "metrics.json"
    stdout_path = pilot_root / "stdout.log"
    raw_path = pilot_root / "raw-gaps.csv"
    metrics_path.write_text(
        json.dumps(
            {
                "observed_mean_entropy": 0.929353,
                "residue_path_delta": -0.00115344,
                "local_block_delta": -0.0245798,
                "holm_adjusted_p": 0.02,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stdout_path.write_text(
        "program_status=completed; four null models executed separately\n",
        encoding="utf-8",
    )
    raw_path.write_text("gap\n2\n4\n2\n", encoding="utf-8")
    files = [
        {
            "relative_path": metrics_path.name,
            "sha256": _sha256(metrics_path),
            "bytes": metrics_path.stat().st_size,
            "kind": "metrics",
        },
        {
            "relative_path": stdout_path.name,
            "sha256": _sha256(stdout_path),
            "bytes": stdout_path.stat().st_size,
            "kind": "stdout_log",
        },
        {
            "relative_path": raw_path.name,
            "sha256": _sha256(raw_path),
            "bytes": raw_path.stat().st_size,
            "kind": "raw_prime_gaps",
        },
    ]
    manifest: dict[str, Any] = {
        "schema_version": "contest-prime-preexperiment-manifest-v1",
        "program_status": "completed",
        "run_id": "pilot-test",
        "integrity_scope": "sha256_tamper_evident_not_externally_signed",
        "files": files,
    }
    manifest["manifest_hash"] = canonical_model_hash(manifest)
    manifest_path = pilot_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    artifact: dict[str, Any] = {
        "schema_version": "contest-prime-preexperiment-artifact-v1",
        "status": "completed",
        "study_phase": "exploratory_pilot",
        "formal_experiment_executed": False,
        "mathematical_proof_claimed": False,
        "run_id": "pilot-test",
        "scientific_question": "素数为何如此特别？",
        "aggregate_results": [
            {"null_model": "local_block_permutation", "delta": -0.0245798},
            {"null_model": "residue_path_conditioned_permutation", "delta": -0.00115344},
        ],
        "metrics_relative_path": metrics_path.name,
        "metrics_sha256": _sha256(metrics_path),
        "stdout_log_relative_path": stdout_path.name,
        "stdout_log_sha256": _sha256(stdout_path),
        "manifest_relative_path": manifest_path.name,
        "manifest_sha256": _sha256(manifest_path),
        "manifest_hash": manifest["manifest_hash"],
        "evidence_files": files,
    }
    artifact["artifact_hash"] = canonical_model_hash(artifact)
    artifact_path = pilot_root / "prime-preexperiment.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    return artifact_path, metrics_path, raw_path


def test_one_call_independent_messages_and_hash_bound_artifacts(tmp_path: Path) -> None:
    artifact_path, metrics_path, raw_path = _pilot(tmp_path)
    final_plan = _final_plan().model_dump(mode="json")
    final_plan["previous_audit"] = {
        "verdict": "秘密旧结论必须通过",
        "delivery_status": "success",
    }
    captured: list[dict[str, Any]] = []

    def fake_call(**kwargs: Any) -> LLMJsonCompletionResult:
        captured.append(kwargs)
        return _completion(_review_payload())

    output_root = tmp_path / "review"
    memory_context = {
        "context_kind": "optional_rebuildable_dreaming_navigation",
        "recall_hash": "a" * 64,
        "epistemic_boundary_zh": (
            "Dreaming 只是可删除、可重建的导航上下文，不是文献、实验结果或科学证据；"
            "任何科学陈述仍须读取并核验所绑定的原始制品。"
        ),
        "derived_context_is_evidence": False,
        "model_consumption_proven_by_this_receipt": False,
        "projections": [{"source_stage": "render-plan", "summary": "只用于导航"}],
    }
    result = review_contest_direct_plan_science(
        final_plan=final_plan,
        preexperiment_artifact=artifact_path,
        preexperiment_metrics=metrics_path,
        evidence_file_bindings=(
            {"path": raw_path.name, "sha256": _sha256(raw_path), "role": "raw_prime_gaps"},
        ),
        reference_catalog=("Bandt & Pompe (2002)", "Gallagher (1976)"),
        selected_skill_contexts=(
            {"name": "number-theory", "content": "区分有限计算与一般定理。"},
            {"name": "statistics", "content": "区分探索性与确认性推断。"},
        ),
        derived_memory_context=memory_context,
        output_dir=output_root,
        require_exact_reference_catalog=True,
        llm_call=fake_call,
    )

    assert len(captured) == 1
    assert captured[0]["thinking_mode"] == "disabled"
    assert captured[0]["thinking_budget"] is None
    messages = captured[0]["messages"]
    assert [message["role"] for message in messages] == ["system"] + ["user"] * 8
    assert "素数" not in messages[0]["content"]
    contexts = [json.loads(message["content"])["context_kind"] for message in messages[1:]]
    assert contexts == [
        "original_scientific_question_and_review_requirements",
        "locked_real_reference_catalog",
        "verified_exploratory_preexperiment_evidence",
        "final_research_plan_for_independent_review",
        "system_selected_project_method_skill",
        "system_selected_project_method_skill",
        "optional_rebuildable_dreaming_navigation",
        "single_independent_scientific_review_contract",
    ]
    recalled = json.loads(messages[-2]["content"])
    assert recalled["derived_context_is_evidence"] is False
    assert recalled["scientific_claims_require_exact_source_artifact"] is True
    serialized_messages = json.dumps(messages, ensure_ascii=False)
    assert "不可变的引用身份空间" in serialized_messages
    assert "supported/partial/unsupported" in serialized_messages
    assert "较弱定量结果" in serialized_messages
    assert "秘密旧结论必须通过" not in serialized_messages
    assert '"delivery_status"' not in serialized_messages
    plan_message = json.loads(messages[4]["content"])
    assert "status" not in plan_message["scientific_plan"]
    evidence_message = json.loads(messages[3]["content"])
    files_by_role = {item["role"]: item for item in evidence_message["verified_files"]}
    assert files_by_role["stdout_log"]["verified_text"].startswith("program_status")
    assert files_by_role["raw_prime_gaps"]["verified_text"] is None

    assert result.generation_calls == 1
    assert result.review.recommendation == "major_revision"
    assert result.evidence_scope == "exploratory_preexperiment"
    assert result.independence_scope == "fresh_interaction_not_model_family_independence"
    assert result.formal_experiment_executed is False
    assert result.paper_claimed is False
    assert result.prior_audit_context_supplied is False
    assert result.required_audit_findings_sha256 is None
    assert result.reference_catalog_binding_policy == "locked-catalog-exact-order-v2"
    assert result.plan_rewrite_performed is False
    assert (output_root / "system-plan-scientific-review.json").is_file()
    assert "required_audit_findings_sha256" not in json.loads(
        (output_root / "system-plan-scientific-review.json").read_text(encoding="utf-8")
    )
    assert (output_root / result.markdown_relative_path).is_file()
    assert (output_root / result.raw_response_relative_path).is_file()
    assert (output_root / result.authorship_receipt_relative_path).is_file()
    loaded = load_contest_direct_plan_scientific_review(
        output_root / "system-plan-scientific-review.json"
    )
    assert loaded.artifact_hash == result.artifact_hash
    markdown = (output_root / result.markdown_relative_path).read_text(encoding="utf-8")
    assert "最强反证或替代解释" in markdown
    assert "正式实验已执行：否" in markdown


def test_optional_red_team_findings_are_full_and_hash_bound(
    tmp_path: Path,
) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    payload = _review_payload()
    payload["statistics_assessment"] = (
        "RT-01：100 次抽样与多重比较门槛不相容，正式方案必须提高抽样次数。"
    )
    payload["major_issues"] = [
        "RT-02：预实验按固定整数区间分析，正式计划按每块素数个数分析，必须区分。"
    ]
    captured: list[dict[str, Any]] = []

    def fake_call(**kwargs: Any) -> LLMJsonCompletionResult:
        captured.append(kwargs)
        return _completion(payload)

    findings = (
        {
            "finding_id": "RT-02",
            "finding": "预实验和正式实验的分析单位可能混淆。",
            "evidence": {"pilot_unit": "整数区间", "formal_unit": "每块素数个数"},
        },
        "RT-01: Monte Carlo 抽样次数不足以达到校正后的显著性门槛。",
    )
    output_root = tmp_path / "review"
    result = review_contest_direct_plan_science(
        final_plan=_final_plan(),
        preexperiment_artifact=artifact_path,
        reference_catalog=("Bandt & Pompe (2002)", "Gallagher (1976)"),
        required_audit_findings=findings,
        output_dir=output_root,
        llm_call=fake_call,
    )

    assert len(captured) == 1
    messages = captured[0]["messages"]
    contexts = [json.loads(message["content"])["context_kind"] for message in messages[1:]]
    assert contexts[-2:] == [
        "required_red_team_audit_findings",
        "single_independent_scientific_review_contract",
    ]
    assert "全新的独立交互" in messages[0]["content"]
    audit_message = json.loads(messages[-2]["content"])
    assert [item["finding_id"] for item in audit_message["required_audit_findings"]] == [
        "RT-01",
        "RT-02",
    ]
    assert audit_message["required_audit_findings"][0]["finding"].endswith("显著性门槛。")
    assert audit_message["required_audit_findings"][1]["evidence"] == {
        "formal_unit": "每块素数个数",
        "pilot_unit": "整数区间",
    }
    expected_findings_hash = canonical_model_hash(
        {"required_audit_findings": audit_message["required_audit_findings"]}
    )
    assert audit_message["required_audit_findings_sha256"] == expected_findings_hash
    contract_message = json.loads(messages[-1]["content"])
    assert contract_message["required_audit_finding_ids"] == ["RT-01", "RT-02"]
    question_message = json.loads(messages[1]["content"])
    assert question_message["independence_boundary"]["prior_audit_context_supplied"] is True

    assert result.prior_audit_context_supplied is True
    assert result.required_audit_findings_sha256 == expected_findings_hash
    artifact_payload = json.loads(
        (output_root / "system-plan-scientific-review.json").read_text(encoding="utf-8")
    )
    assert artifact_payload["required_audit_findings_sha256"] == expected_findings_hash
    assert (
        load_contest_direct_plan_scientific_review(
            output_root / "system-plan-scientific-review.json"
        ).artifact_hash
        == result.artifact_hash
    )


def test_free_chinese_review_without_audit_ids_still_materializes_after_one_call(
    tmp_path: Path,
) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    output_root = tmp_path / "review"
    calls = 0

    def free_chinese_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion(_review_payload())

    result = review_contest_direct_plan_science(
        final_plan=_final_plan(),
        preexperiment_artifact=artifact_path,
        reference_catalog=("Bandt & Pompe (2002)", "Gallagher (1976)"),
        required_audit_findings=({"finding_id": "RT-01", "finding": "复核抽样门槛是否可达。"},),
        output_dir=output_root,
        llm_call=free_chinese_call,
    )

    assert calls == 1
    assert len(tuple((output_root / "responses").glob("*.txt"))) == 1
    assert len(tuple((output_root / "interactions").glob("*.json"))) == 1
    assert result.prior_audit_context_supplied is True
    assert result.required_audit_findings_sha256 is not None
    assert "RT-01" not in json.dumps(result.review.model_dump(mode="json"), ensure_ascii=False)
    assert (output_root / "scientific-review.md").is_file()
    assert (output_root / "system-plan-scientific-review.json").is_file()


def test_common_aliases_nested_dimensions_and_issue_objects_are_normalized(
    tmp_path: Path,
) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    alias_payload = {
        "评审": {
            "结论": "建议小修",
            "问题重述": "检验有限区间残余结构是否超越条件零模型。",
            "最强反证": "效应可由未控制的高阶筛结构解释。",
            "总体评价": "研究边界清楚，但若干报告细节需修订 [2]。",
            "分项评估": {
                "假设与证据": "证据仅支持收窄假设。",
                "零模型与对照": "四类零模型没有被混为同一证据。",
                "分析单位": "固定区间不是总体随机样本。",
                "统计方法": "应保持描述性解释。",
                "结论边界": "没有一般定理外推。",
                "可复现性": "文件绑定足够。",
                "文献评估": "目录范围与方法相符 [1]。",
            },
            "优势": "诚实报告效应收缩。",
            "主要问题": [],
            "小修问题": [{"问题": "术语不一致", "依据": "两处命名不同", "建议": "统一命名"}],
            "参考文献编号": ["[2]", {"reference_index": 2}],
        }
    }

    result = review_contest_direct_plan_science(
        final_plan=_final_plan(),
        preexperiment_artifact=artifact_path,
        reference_catalog=("Bandt & Pompe (2002)", "Gallagher (1976)"),
        output_dir=tmp_path / "review",
        llm_call=lambda **_: _completion(alias_payload),
    )

    assert result.review.recommendation == "minor_revision"
    assert result.review.reference_indices == (1, 2)
    assert result.review.major_issues == ()
    assert result.review.minor_issues == ("术语不一致；两处命名不同；统一命名",)
    assert result.mechanical_normalization_applied is True


def test_body_and_structured_reference_indices_are_union_sorted_and_materialized(
    tmp_path: Path,
) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    payload = _review_payload()
    payload["recommendation"] = "major_revision"
    payload["recommendation_text"] = "major_revision"
    payload["summary"] = "总体判断分别依据目录项 [4] 与 [2]，其中 [4] 被重复提及 [4]。"
    payload["minor_issues"] = ["中文问题字段补充指向 [2]。"]
    payload["reference_indices"] = [3, 1, 3]
    output_root = tmp_path / "review"

    result = review_contest_direct_plan_science(
        final_plan=_final_plan(),
        preexperiment_artifact=artifact_path,
        reference_catalog=("Reference A", "Reference B", "Reference C", "Reference D"),
        output_dir=output_root,
        llm_call=lambda **_: _completion(payload),
    )

    assert result.review.reference_indices == (1, 2, 3, 4)
    assert result.mechanical_normalization_applied is True
    assert result.reference_index_integrity_status == "verified_exact_union"
    artifact_payload = json.loads(
        (output_root / "system-plan-scientific-review.json").read_text(encoding="utf-8")
    )
    assert artifact_payload["review"]["reference_indices"] == [1, 2, 3, 4]
    hash_payload = {key: value for key, value in artifact_payload.items() if key != "artifact_hash"}
    hash_payload.pop("derived_memory_context_sha256", None)
    assert artifact_payload["artifact_hash"] == canonical_model_hash(hash_payload)
    markdown = (output_root / result.markdown_relative_path).read_text(encoding="utf-8")
    assert "[1], [2], [3], [4]" in markdown
    assert _sha256(output_root / result.markdown_relative_path) == result.markdown_sha256


def test_omitted_and_empty_reference_indices_are_handled_deterministically(
    tmp_path: Path,
) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    inferred_payload = _review_payload()
    inferred_payload["recommendation"] = "major_revision"
    inferred_payload["recommendation_text"] = "major_revision"
    inferred_payload["references_assessment"] = "中文评估明确引用目录项 [2]。"
    inferred_payload.pop("reference_indices")

    inferred = review_contest_direct_plan_science(
        final_plan=_final_plan(),
        preexperiment_artifact=artifact_path,
        reference_catalog=("Reference A", "Reference B"),
        output_dir=tmp_path / "inferred-review",
        llm_call=lambda **_: _completion(inferred_payload),
    )

    assert inferred.review.reference_indices == (2,)
    assert inferred.mechanical_normalization_applied is True

    empty_payload = _review_payload()
    empty_payload["recommendation"] = "major_revision"
    empty_payload["recommendation_text"] = "major_revision"
    empty_payload["reference_indices"] = []
    empty = review_contest_direct_plan_science(
        final_plan=_final_plan(),
        preexperiment_artifact=artifact_path,
        reference_catalog=("Reference A", "Reference B"),
        output_dir=tmp_path / "empty-review",
        llm_call=lambda **_: _completion(empty_payload),
    )

    assert empty.review.reference_indices == ()
    assert empty.mechanical_normalization_applied is False
    assert empty.reference_index_integrity_status == "verified_exact_union"


def test_materialized_final_plan_bytes_and_corrected_fields_are_reviewed(
    tmp_path: Path,
) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    materialized = {
        "document_type": "含真实预实验结果的科学假设与研究计划",
        "status": "evidence_corrected_after_qwen_revision",
        "question": {"question_zh": "物化后的首题问题", "question_en": "Materialized question"},
        "title": "最终物化标题",
        "abstract": "这是经过证据校正后交付给评审器的最终摘要。",
        "problem_statement": "这是最终物化的问题陈述。",
        "rationale": "这是最终物化的研究理由与主假设。",
        "technical_details": "CORRECTED_FINAL_TECHNICAL_DETAILS：标准化量仅是零模型诊断。",
        "datasets": {
            "description": "最终物化数据说明。",
            "source": "最终物化数据来源。",
            "target": "最终物化目标特征。",
        },
        "methods": "最终物化方法。",
        "experiments": {
            "steps": "最终物化实验步骤。",
            "baselines": "最终物化基线。",
            "metrics": "最终物化指标。",
        },
        "results": "最终物化预实验结果与局限。",
        "references": ["Bandt & Pompe (2002)"],
        "generation": {
            "raw_revision_text": "RAW_REVISION_MUST_NOT_BE_REVIEWED",
            "editorial_correction_artifact_hash": "a" * 64,
        },
    }
    materialized_path = tmp_path / "research-plan.json"
    materialized_path.write_text(
        json.dumps(materialized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    captured: list[dict[str, Any]] = []

    def fake_call(**kwargs: Any) -> LLMJsonCompletionResult:
        captured.append(kwargs)
        return _completion(_review_payload())

    result = review_contest_direct_plan_science(
        final_plan=materialized_path,
        preexperiment_artifact=artifact_path,
        reference_catalog=("Bandt & Pompe (2002)", "Gallagher (1976)"),
        output_dir=tmp_path / "review",
        llm_call=fake_call,
    )

    expected_payload_hash = canonical_model_hash(materialized)
    assert result.final_plan_source_kind == "materialized_final_plan"
    assert result.final_plan_artifact_hash == expected_payload_hash
    assert result.final_plan_payload_sha256 == expected_payload_hash
    assert result.final_plan_source_file_sha256 == _sha256(materialized_path)
    messages = captured[0]["messages"]
    question_message = json.loads(messages[1]["content"])
    assert question_message["scientific_problem"] == "物化后的首题问题"
    plan_message = json.loads(messages[4]["content"])
    assert plan_message["final_plan_source_kind"] == "materialized_final_plan"
    assert plan_message["final_plan_payload_sha256"] == expected_payload_hash
    assert plan_message["final_plan_source_file_sha256"] == _sha256(materialized_path)
    assert (
        plan_message["scientific_plan"]["technical_details"]
        == "CORRECTED_FINAL_TECHNICAL_DETAILS：标准化量仅是零模型诊断。"
    )
    serialized = json.dumps(messages, ensure_ascii=False)
    assert "RAW_REVISION_MUST_NOT_BE_REVIEWED" not in serialized
    assert '"status": "evidence_corrected_after_qwen_revision"' not in serialized


def test_invalid_content_retains_raw_response_and_receipt_without_retry(
    tmp_path: Path,
) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    payload = _review_payload()
    payload.pop("statistics_assessment")
    calls = 0
    output_root = tmp_path / "review"

    def incomplete_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion(payload)

    with pytest.raises(
        ContestDirectPlanScientificReviewError,
        match="omitted required scientific assessments",
    ):
        review_contest_direct_plan_science(
            final_plan=_final_plan(),
            preexperiment_artifact=artifact_path,
            reference_catalog=("Bandt & Pompe (2002)",),
            output_dir=output_root,
            llm_call=incomplete_call,
        )

    assert calls == 1
    assert len(tuple((output_root / "responses").glob("*.txt"))) == 1
    assert len(tuple((output_root / "interactions").glob("*.json"))) == 1
    assert not (output_root / "scientific-review.md").exists()
    assert not (output_root / "system-plan-scientific-review.json").exists()


def test_review_rejects_reordered_bibliography_before_provider_call(tmp_path: Path) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    final_plan = _final_plan().model_dump(mode="json")
    final_plan["plan"]["references"] = list(reversed(final_plan["plan"]["references"]))
    final_plan["artifact_hash"] = canonical_model_hash(
        {key: value for key, value in final_plan.items() if key != "artifact_hash"}
    )
    calls = 0

    def fake_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion(_review_payload())

    with pytest.raises(
        ContestDirectPlanScientificReviewError,
        match="locked reference identity/order",
    ):
        review_contest_direct_plan_science(
            final_plan=final_plan,
            preexperiment_artifact=artifact_path,
            reference_catalog=("Bandt & Pompe (2002)", "Gallagher (1976)"),
            output_dir=tmp_path / "review",
            require_exact_reference_catalog=True,
            llm_call=fake_call,
        )

    assert calls == 0


def test_review_requires_claim_level_check_for_every_plan_citation(tmp_path: Path) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    final_plan = _final_plan().model_dump(mode="json")
    final_plan["plan"]["rationale"] += " 已有工作支持这一归因[1]。"
    final_plan["artifact_hash"] = canonical_model_hash(
        {key: value for key, value in final_plan.items() if key != "artifact_hash"}
    )
    calls = 0

    def fake_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion(_review_payload())

    with pytest.raises(
        ContestDirectPlanScientificReviewError,
        match="omitted claim-level source checks.*1",
    ):
        review_contest_direct_plan_science(
            final_plan=final_plan,
            preexperiment_artifact=artifact_path,
            reference_catalog=("Bandt & Pompe (2002)", "Gallagher (1976)"),
            output_dir=tmp_path / "review",
            llm_call=fake_call,
        )

    assert calls == 1


def test_out_of_catalog_reference_is_rejected_after_response_is_retained(
    tmp_path: Path,
) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    payload = _review_payload()
    payload["reference_indices"] = [1, 9]
    output_root = tmp_path / "review"

    with pytest.raises(
        ContestDirectPlanScientificReviewError,
        match="outside the locked catalog",
    ):
        review_contest_direct_plan_science(
            final_plan=_final_plan(),
            preexperiment_artifact=artifact_path,
            reference_catalog=("Bandt & Pompe (2002)",),
            output_dir=output_root,
            llm_call=lambda **_: _completion(payload),
        )

    assert len(tuple((output_root / "responses").glob("*.txt"))) == 1
    assert len(tuple((output_root / "interactions").glob("*.json"))) == 1


def test_out_of_catalog_reference_in_natural_language_is_rejected(
    tmp_path: Path,
) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    payload = _review_payload()
    payload["summary"] = "该判断引用了锁定目录之外的编号 [3]。"
    payload["reference_indices"] = []
    output_root = tmp_path / "review"

    with pytest.raises(
        ContestDirectPlanScientificReviewError,
        match="outside the locked catalog",
    ):
        review_contest_direct_plan_science(
            final_plan=_final_plan(),
            preexperiment_artifact=artifact_path,
            reference_catalog=("Reference A", "Reference B"),
            output_dir=output_root,
            llm_call=lambda **_: _completion(payload),
        )

    assert len(tuple((output_root / "responses").glob("*.txt"))) == 1
    assert len(tuple((output_root / "interactions").glob("*.json"))) == 1


def test_tampered_preexperiment_file_fails_before_model_call(tmp_path: Path) -> None:
    artifact_path, metrics_path, _ = _pilot(tmp_path)
    metrics_path.write_text('{"tampered": true}', encoding="utf-8")
    calls = 0

    def forbidden_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion(_review_payload())

    with pytest.raises(ContestDirectPlanScientificReviewError, match="metrics file hash mismatch"):
        review_contest_direct_plan_science(
            final_plan=_final_plan(),
            preexperiment_artifact=artifact_path,
            reference_catalog=("Bandt & Pompe (2002)",),
            output_dir=tmp_path / "review",
            llm_call=forbidden_call,
        )
    assert calls == 0


def test_loader_detects_markdown_tampering(tmp_path: Path) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    output_root = tmp_path / "review"
    result = review_contest_direct_plan_science(
        final_plan=_final_plan(),
        preexperiment_artifact=artifact_path,
        reference_catalog=("Bandt & Pompe (2002)", "Gallagher (1976)"),
        output_dir=output_root,
        llm_call=lambda **_: _completion(_review_payload()),
    )
    markdown_path = output_root / result.markdown_relative_path
    markdown_path.write_text("tampered", encoding="utf-8")

    with pytest.raises(
        ContestDirectPlanScientificReviewError,
        match="Markdown hash mismatch",
    ):
        load_contest_direct_plan_scientific_review(
            output_root / "system-plan-scientific-review.json"
        )


def test_loader_replays_reference_normalization_from_authorship_receipt(
    tmp_path: Path,
) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    output_root = tmp_path / "review"
    result = review_contest_direct_plan_science(
        final_plan=_final_plan(),
        preexperiment_artifact=artifact_path,
        reference_catalog=("Reference A", "Reference B", "Reference C"),
        output_dir=output_root,
        llm_call=lambda **_: _completion(_review_payload()),
    )
    artifact_file = output_root / "system-plan-scientific-review.json"
    tampered = json.loads(artifact_file.read_text(encoding="utf-8"))
    tampered["review"]["reference_indices"] = [1, 2, 3]
    tampered["artifact_hash"] = canonical_model_hash(
        {key: value for key, value in tampered.items() if key != "artifact_hash"}
    )
    artifact_file.write_text(
        json.dumps(tampered, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(
        ContestDirectPlanScientificReviewError,
        match="differs from the retained authorship receipt",
    ):
        load_contest_direct_plan_scientific_review(artifact_file)

    assert result.reference_index_integrity_status == "verified_exact_union"


def test_legacy_artifact_remains_loadable_with_explicit_unverified_status(
    tmp_path: Path,
) -> None:
    artifact_path, _, _ = _pilot(tmp_path)
    output_root = tmp_path / "review"
    result = review_contest_direct_plan_science(
        final_plan=_final_plan(),
        preexperiment_artifact=artifact_path,
        reference_catalog=("Reference A", "Reference B"),
        output_dir=output_root,
        llm_call=lambda **_: _completion(_review_payload()),
    )
    artifact_file = output_root / "system-plan-scientific-review.json"
    legacy = json.loads(artifact_file.read_text(encoding="utf-8"))
    legacy.pop("reference_index_integrity_status")
    legacy["artifact_hash"] = canonical_model_hash(
        {key: value for key, value in legacy.items() if key != "artifact_hash"}
    )
    artifact_file.write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    loaded = load_contest_direct_plan_scientific_review(artifact_file)

    assert result.reference_index_integrity_status == "verified_exact_union"
    assert loaded.reference_index_integrity_status == "legacy_unverified_against_review_prose"
