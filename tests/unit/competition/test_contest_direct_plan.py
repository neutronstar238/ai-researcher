"""Tests for the delivery-first one-shot competition research plan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.competition.contest_direct_plan import (
    ContestDirectPlanError,
    ContestDirectScientificPlan,
    build_contest_direct_plan_messages,
    contest_direct_plan_template_payload,
    generate_contest_direct_plan,
    load_contest_direct_plan,
)
from autoresearch.llm.client import LLMClientError, LLMJsonCompletionResult


def _scientific_payload() -> dict[str, Any]:
    return {
        "problem_statement": "宇宙的主要物质组分仍存在暗物质本性不明这一核心问题。",
        "rationale": "联合互补巡天数据检验同一假设，可降低单一观测通道的退化。",
        "technical_details": "构建贝叶斯层次模型，并用模拟数据检验参数可识别性。",
        "datasets": "采用公开巡天数据与可重复生成的模拟观测数据。",
        "source": "数据来自公开档案及具有固定随机种子的模拟流程。",
        "target": "目标是约束暗物质分布参数及其不确定度。",
        "paper_title": "Cross-survey Constraints on Dark Matter",
        "paper_abstract": "本研究提出跨巡天联合约束方法，并预注册可证伪判据。",
        "methods": "先统一选择函数，再进行层次贝叶斯推断和消融分析。",
        "experiments": "依次执行数据质检、模拟校准、主分析、消融和稳健性检验。",
        "baselines": "比较单巡天估计、简单加权合并和不含系统误差项的模型。",
        "metrics": "使用预测对数似然、参数覆盖率、偏差和置信区间宽度评估。",
        "results": "尚未执行预实验；预期以覆盖率改善为支持判据，未改善则否定方案。",
        "references": ["模型不应自行加入这条文献"],
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
        temperature=0.2,
    )


def test_one_call_generates_hashed_json_and_chinese_markdown(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_llm_call(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs)
        return _completion(_scientific_payload())

    literature = (
        "StarWhisper Telescope: an AI framework for automating end-to-end "
        "astronomical observations. https://www.nature.com/articles/s44172-025-00520-4",
    )
    json_path = tmp_path / "research-plan.json"
    markdown_path = tmp_path / "research-plan.md"
    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        literature_context=literature,
        output_path=json_path,
        markdown_path=markdown_path,
        llm_call=fake_llm_call,
    )

    assert len(calls) == 1
    assert calls[0]["temperature"] == 0.2
    assert calls[0]["thinking_mode"] == "enabled"
    assert calls[0]["thinking_budget"] == 4_000
    assert "宇宙由什么构成" in calls[0]["messages"][1]["content"]
    assert "不得新增或猜测" in calls[0]["messages"][2]["content"]
    assert artifact.generation_calls == 1
    assert artifact.plan_id == f"direct-plan-{artifact.input_hash[:16]}"
    assert artifact.status == "research_plan_generated"
    assert artifact.preexperiment_context_status == "not_provided"
    assert artifact.plan.references == literature
    assert artifact.reference_projection is not None
    assert artifact.reference_projection.policy == "locked-catalog-exact-order-v2"
    assert artifact.reference_projection.model_selected_indices == ()
    assert artifact.reference_projection.program_supplemented_indices == (1,)
    assert artifact.plan.paper_title == "Cross-survey Constraints on Dark Matter"
    template_payload = contest_direct_plan_template_payload(artifact)
    assert template_payload["title"] == artifact.plan.paper_title
    assert template_payload["datasets"]["source"] == artifact.plan.source
    assert template_payload["experiments"]["metrics"] == artifact.plan.metrics
    assert load_contest_direct_plan(json_path) == artifact
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "## 待研究问题（Problem Statement）" in markdown
    assert "### 基线（Baselines）" in markdown
    assert "### 评估指标（Metrics）" in markdown
    assert "## 参考论文（References）" in markdown
    assert "StarWhisper Telescope" in markdown


def test_direct_plan_can_disable_thinking_without_changing_the_default() -> None:
    calls: list[dict[str, Any]] = []

    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        thinking_mode="disabled",
        thinking_budget=None,
        llm_call=lambda **kwargs: (calls.append(kwargs) or _completion(_scientific_payload())),
    )

    assert artifact.generation_calls == 1
    assert calls[0]["thinking_mode"] == "disabled"
    assert calls[0]["thinking_budget"] is None


def test_disabled_thinking_rejects_an_unused_budget() -> None:
    with pytest.raises(
        ContestDirectPlanError,
        match="thinking_budget must be None when thinking is disabled",
    ):
        generate_contest_direct_plan(
            scientific_problem="宇宙由什么构成？",
            thinking_mode="disabled",
            thinking_budget=4_000,
            llm_call=lambda **_: _completion(_scientific_payload()),
        )


def test_technical_identifiers_do_not_need_artificial_chinese_wrappers() -> None:
    payload = _scientific_payload()
    payload.update(
        {
            "source": "consecutive_integer_primes",
            "target": "ordered_consecutive_prime_gaps",
            "baselines": "residue_path_conditioned_permutation, iid_order_null",
            "metrics": "tie_aware_normalized_permutation_entropy_m5",
        }
    )

    artifact = generate_contest_direct_plan(
        scientific_problem="素数为什么如此特别？",
        llm_call=lambda **_: _completion(payload),
    )

    assert artifact.plan.source == "consecutive_integer_primes"
    assert artifact.plan.target == "ordered_consecutive_prime_gaps"
    assert artifact.plan.baselines.startswith("residue_path_conditioned_permutation")
    assert artifact.plan.metrics == "tie_aware_normalized_permutation_entropy_m5"


@pytest.mark.parametrize(
    "field",
    (
        "problem_statement",
        "rationale",
        "technical_details",
        "datasets",
        "paper_abstract",
        "methods",
        "experiments",
        "results",
    ),
)
def test_english_only_narrative_fields_remain_rejected(field: str) -> None:
    payload = _scientific_payload()
    payload[field] = "This narrative field contains no Chinese research-plan prose."

    with pytest.raises(ContestDirectPlanError, match="required Chinese"):
        generate_contest_direct_plan(
            scientific_problem="素数为什么如此特别？",
            llm_call=lambda **_: _completion(payload),
        )


def test_empty_reference_selection_backfills_locked_catalog_without_invention() -> None:
    payload = _scientific_payload()
    payload["references"] = []

    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        literature_context=("文献一", "文献二"),
        llm_call=lambda **_: _completion(payload),
    )

    assert artifact.plan.references == ("文献一", "文献二")


def test_all_out_of_range_reference_indices_backfill_locked_catalog() -> None:
    payload = _scientific_payload()
    payload["references"] = [0, 3, "999", "[4]"]

    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        literature_context=("文献一", "文献二"),
        llm_call=lambda **_: _completion(payload),
    )

    assert artifact.plan.references == ("文献一", "文献二")


def test_mixed_reference_selection_keeps_only_valid_catalog_entries() -> None:
    literature = ("文献一", "文献二", "文献三")
    payload = _scientific_payload()
    payload["references"] = [1, 99, "模型虚构文献", "[2]"]

    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        literature_context=literature,
        llm_call=lambda **_: _completion(payload),
    )

    assert artifact.plan.references == literature


def test_duplicate_reference_selections_are_stably_deduplicated() -> None:
    literature = ("文献一", "文献二")
    payload = _scientific_payload()
    payload["references"] = [2, "2", "[2]", literature[1], 2]

    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        literature_context=literature,
        llm_call=lambda **_: _completion(payload),
    )

    assert artifact.plan.references == literature
    assert artifact.reference_projection is not None
    assert artifact.reference_projection.model_selected_indices == (2,)
    assert artifact.reference_projection.program_supplemented_indices == (1,)


def test_model_preferences_are_audited_without_renumbering_the_locked_catalog() -> None:
    literature = tuple(f"真实检索文献{index}" for index in range(1, 8))
    payload = _scientific_payload()
    payload["references"] = [4, 2, "模型虚构文献"]

    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        literature_context=literature,
        llm_call=lambda **_: _completion(payload),
    )

    assert artifact.plan.references == literature
    assert artifact.reference_projection is not None
    assert artifact.reference_projection.model_selected_indices == (4, 2)
    assert artifact.reference_projection.program_supplemented_indices == (1, 3, 5, 6, 7)


def test_locked_bibliography_never_exceeds_ten() -> None:
    literature = tuple(f"真实检索文献{index}" for index in range(1, 13))
    payload = _scientific_payload()
    payload["references"] = list(range(12, 0, -1))

    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        literature_context=literature,
        llm_call=lambda **_: _completion(payload),
    )

    assert artifact.plan.references == literature[:10]
    assert artifact.reference_projection is not None
    assert artifact.reference_projection.model_selected_indices == tuple(range(10, 0, -1))


def test_common_nested_shapes_are_normalized_without_rewriting() -> None:
    payload = _scientific_payload()
    payload["Datasets"] = {
        "description": payload.pop("datasets"),
        "Source": payload.pop("source"),
        "Target": payload.pop("target"),
    }
    payload["Experiments"] = {
        "design": payload.pop("experiments"),
        "Baselines": payload.pop("baselines"),
        "Metrics": payload.pop("metrics"),
    }

    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        llm_call=lambda **_: _completion(payload),
    )

    assert artifact.plan.datasets.startswith("采用公开巡天")
    assert artifact.plan.source.startswith("数据来自")
    assert artifact.plan.baselines.startswith("比较单巡天")
    assert artifact.plan.metrics.startswith("使用预测")


def test_wrapped_bilingual_sections_are_flattened_without_another_model_call() -> None:
    source = _scientific_payload()
    wrapped = {
        "研究计划": {
            "待研究问题（Problem Statement）": source["problem_statement"],
            "解决思路（Rationale）": source["rationale"],
            "必要的技术手段（Technical Details）": source["technical_details"],
            "数据集（Datasets）": {
                "说明": source["datasets"],
                "数据来源（Source）": source["source"],
                "目标特征（Target）": source["target"],
            },
            "标题（Paper Title）": source["paper_title"],
            "摘要（Paper Abstract）": source["paper_abstract"],
            "方法论（Methods）": source["methods"],
            "实验设计（Experiments）": {
                "步骤": source["experiments"],
                "基线（Baselines）": source["baselines"],
                "评估指标（Metrics）": source["metrics"],
            },
            "实验结果（Results）": source["results"],
            "参考文献（References）": [1],
        }
    }
    calls = 0

    def wrapped_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion(wrapped)

    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        literature_context=("真实文献一",),
        llm_call=wrapped_call,
    )

    assert calls == 1
    assert artifact.plan.technical_details == source["technical_details"]
    assert artifact.plan.source == source["source"]
    assert artifact.plan.metrics == source["metrics"]
    assert artifact.plan.references == ("真实文献一",)


def test_invalid_scientific_shape_retains_raw_response_before_failure(
    tmp_path: Path,
) -> None:
    response_payload = {"problem_statement": "仅有一个字段。"}
    response_text = json.dumps(response_payload, ensure_ascii=False)
    output_path = tmp_path / "system-authored-research-plan.json"

    with pytest.raises(ContestDirectPlanError, match="omitted required"):
        generate_contest_direct_plan(
            scientific_problem="宇宙由什么构成？",
            output_path=output_path,
            llm_call=lambda **_: _completion(response_payload),
        )

    retained = list((tmp_path / "responses").glob("direct-plan-*.txt"))
    assert len(retained) == 1
    assert retained[0].read_text(encoding="utf-8") == response_text
    assert not output_path.exists()


def test_one_local_json_repair_does_not_make_a_second_model_call(tmp_path: Path) -> None:
    payload = _scientific_payload()
    broken = json.dumps(payload, ensure_ascii=False)[:-1] + ",}"
    calls = 0

    def malformed_call(**_: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        raise LLMClientError(
            "not valid JSON",
            response_text=f"```json\n{broken}\n```",
        )

    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        config_path=tmp_path / "missing.yaml",
        llm_call=malformed_call,
    )

    assert calls == 1
    assert artifact.json_repair_applied is True
    assert artifact.provider == "openai-compatible"
    assert artifact.model_name == "gpt-4o-mini"
    assert artifact.plan.problem_statement.startswith("宇宙的主要物质组分")


def test_only_nonempty_chinese_prose_is_required() -> None:
    payload = _scientific_payload()
    plan = ContestDirectScientificPlan.model_validate(payload)
    assert plan.paper_title == "Cross-survey Constraints on Dark Matter"

    payload["rationale"] = "Bayesian inference only"
    with pytest.raises(ValidationError, match="must contain Chinese"):
        ContestDirectScientificPlan.model_validate(payload)


def test_preexperiment_context_is_passed_through_without_claiming_verification() -> None:
    captured: list[dict[str, Any]] = []

    def fake_llm_call(**kwargs: Any) -> LLMJsonCompletionResult:
        captured.append(kwargs)
        payload = _scientific_payload()
        payload["results"] = "输入预实验记录显示覆盖率为记录中的数值；本计划不外推正式结论。"
        return _completion(payload)

    artifact = generate_contest_direct_plan(
        scientific_problem="宇宙由什么构成？",
        preexperiment_context={"coverage": 0.91, "scope": "pilot"},
        llm_call=fake_llm_call,
    )

    assert artifact.preexperiment_context_status == "provided_as_input_context"
    assert '"coverage": 0.91' in captured[0]["messages"][2]["content"]
    assert artifact.document_type == "科学假设与研究计划"


def test_domain_skill_is_an_independent_user_message_and_bound_to_input() -> None:
    skill = "---\nname: prime-number-method\n---\n只提供计算数论研究路径。"
    messages = build_contest_direct_plan_messages(
        scientific_problem="素数为何如此特别？",
        method_skills=(skill,),
    )

    assert len(messages) == 4
    assert messages[0]["role"] == "system"
    assert "计算数论" not in messages[0]["content"]
    question_message = json.loads(messages[1]["content"])
    assert question_message["context_kind"] == "research_question_and_delivery_requirements"
    assert question_message["scientific_problem"] == "素数为何如此特别？"
    skill_message = json.loads(messages[2]["content"])
    assert skill_message["context_kind"] == "system_selected_project_method_skills"
    assert skill_message["selected_method_skills"][0]["content"] == skill
    assert "素数为何如此特别" not in messages[3]["content"]


def test_archived_temporary_advice_follows_question_and_selected_skill() -> None:
    skill = "---\nname: prime-number-method\n---\n只提供计算数论研究路径。"
    messages = build_contest_direct_plan_messages(
        scientific_problem="素数为何如此特别？",
        method_skills=(skill,),
        temporary_agent_context={
            "候选假设": "检验有限尺度间隙结构。",
            "实验建议": "使用密度匹配与置换对照。",
        },
    )

    assert len(messages) == 5
    assert json.loads(messages[1]["content"])["context_kind"] == (
        "research_question_and_delivery_requirements"
    )
    assert json.loads(messages[2]["content"])["context_kind"] == (
        "system_selected_project_method_skills"
    )
    temporary_message = json.loads(messages[3]["content"])
    assert temporary_message["context_kind"] == "archived_temporary_agent_advice"
    assert "全部拒绝" in temporary_message["boundary_zh"]
    assert "不要求逐条覆盖" in temporary_message["boundary_zh"]
    assert "检验有限尺度间隙结构" in temporary_message["advice"]
