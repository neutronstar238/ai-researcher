from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.system_plan_component_atoms import (
    SystemPlanComponentAtom,
    SystemPlanComponentAtomArtifact,
    SystemPlanComponentAtomBinding,
    SystemPlanComponentAtomError,
    SystemPlanComponentAtomPortfolio,
    SystemPlanComponentAtomReview,
    SystemPlanComponentAtomReviewPortfolio,
    build_system_plan_component_source_clause_catalog,
    component_atom_review_findings,
    run_system_plan_component_atom_catalog,
)
from autoresearch.competition.system_plan_methodology import (
    AvailableMethodSkill,
    SystemPlanMethodSkillSelection,
    SystemPlanMethodSkillSelectionBinding,
)
from autoresearch.competition.system_plan_opportunity_map import (
    CrossLineageSystemEffectMatrix,
    EvidenceFact,
    ResearchFeasibilityEnvelope,
)
from autoresearch.llm.client import LLMJsonCompletionResult

LINEAGE_A = "signed-lineage-a"
LINEAGE_B = "signed-lineage-b"
FIXED_CLOCK = datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc)


def _method_binding() -> SystemPlanMethodSkillSelectionBinding:
    content = (
        "---\nname: atomic-audit\n---\n"
        "本技能要求先核对完整来源，再进行单组件原子化、适用范围检查和独立复核。"
    )
    skill = AvailableMethodSkill(
        skill_id="atomic-audit",
        description="用于完整来源分句、单组件原子化、适用范围和独立审查的项目方法。",
        source_relative_path="skills/atomic-audit/SKILL.md",
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        content=content,
    )
    selection = SystemPlanMethodSkillSelection(
        task_classification="当前任务只建立候选摘要中的原子组件目录，不产生任何科研结论。",
        selected_skill_ids=(skill.skill_id,),
        rejected_skill_ids=(),
        selection_rationale="该技能明确要求完整来源、单组件边界和独立复核，适合本机械目录阶段。",
        planned_reasoning_stages=(
            "先核对完整候选摘要。",
            "再核对机械来源分句。",
            "随后识别单个技术标识。",
            "接着检查数据类型范围。",
            "然后执行独立逐项复核。",
            "最后冻结非证据绑定。",
        ),
        auditable_reasoning_summary=(
            "完整分句不得截断。",
            "技术标识必须逐字。",
            "范围限定必须保留。",
            "审查顺序必须一致。",
            "目录不授权实验执行。",
        ),
        non_evidence_boundary="技能和推理只约束原子化方法，不构成科研证据、实验结果或机制结论。",
    )
    return SystemPlanMethodSkillSelectionBinding(
        selection_artifact_hash="e" * 64,
        selection=selection,
        selected_skills=(skill,),
    )


def _matrix(*, lineage_b_summary: str | None = None) -> CrossLineageSystemEffectMatrix:
    summaries = {
        LINEAGE_A: (
            "PDE spectral derivative and adaptive threshold; "
            "rational feature library with stability filter; ODE sparse regression."
        ),
        LINEAGE_B: lineage_b_summary
        or (
            "bounded cache policy; PDE Fourier denoiser; ODE polynomial basis; "
            "condition-number guard; residual weighting."
        ),
    }
    candidate_specs = (
        (LINEAGE_A, "a" * 64, "candidate-a"),
        (LINEAGE_B, "b" * 64, "candidate-b"),
    )
    candidates = [
        {
            "lineage_id": lineage_id,
            "package_hash": package_hash,
            "selected_candidate_id": candidate_id,
            "selected_candidate_summary": summaries[lineage_id],
            "plan_hash": "1" * 64,
            "development_panel_hash": "2" * 64,
            "runner_sha256": "3" * 64,
            "runtime_environment_hash": "4" * 64,
            "conditions": ["clean"],
            "search_freeze_receipt_issued": False,
        }
        for lineage_id, package_hash, candidate_id in candidate_specs
    ]
    observations = []
    for index, (lineage_id, package_hash, candidate_id) in enumerate(
        candidate_specs, 1
    ):
        observations.append(
            {
                "lineage_id": lineage_id,
                "package_hash": package_hash,
                "selected_candidate_id": candidate_id,
                "system_name": "system-1",
                "data_type": "ode",
                "candidate_median_loss": 0.1 * index,
                "baseline_median_loss": 1.0,
                "paired_log_effect": 0.01 * index,
                "candidate_cell_count": 3,
                "candidate_success_count": 3,
                "baseline_available": True,
                "fully_observed_pair": True,
            }
        )
    payload: dict[str, Any] = {
        "schema_version": "cross-lineage-system-effect-matrix-v1",
        "candidates": candidates,
        "coverage_ledger": observations,
        "comparable_system_rows": [
            {
                "system_name": "system-1",
                "data_type": "ode",
                "observations": observations,
            }
        ],
        "comparability_rule": (
            "same_plan_panel_runner_runtime_conditions_and_fully_observed_candidate_cells"
        ),
        "candidate_differences_jointly_confounded": True,
        "component_attribution_authorized": False,
        "confirmatory_use_requires_model_authored_component_ablation": True,
    }
    payload["matrix_hash"] = canonical_model_hash(payload)
    return CrossLineageSystemEffectMatrix.model_validate(payload)


def _envelope(*, lineage_b_summary: str | None = None) -> ResearchFeasibilityEnvelope:
    matrix = _matrix(lineage_b_summary=lineage_b_summary)
    facts = [
        EvidenceFact(
            fact_id="E001",
            fact_kind="cross_lineage_effect_matrix",
            scope="retained_selected_candidates_cross_lineage_full_evaluation",
            source_locator="retained.cross_lineage_matrix",
            value=matrix.model_dump(mode="json"),
        )
    ]
    for index in range(2, 6):
        facts.append(
            EvidenceFact(
                fact_id=f"E{index:03d}",
                fact_kind="protocol_constraint",
                scope="current_preregistered_policy",
                source_locator=f"policy.constraint.{index}",
                value={"constraint_index": index},
            )
        )
    payload: dict[str, Any] = {
        "schema_version": "research-feasibility-envelope-v2",
        "source_context_hash": "d" * 64,
        "eligible_systems": [{"system_name": "system-1", "data_type": "ode"}],
        "excluded_systems": [],
        "conditions": ["clean"],
        "seeds": [101],
        "contract_gate": {"network_default_deny": True},
        "estimand": {"independent_unit": "system"},
        "search_budget": {"maximum_seconds_per_cell": 300},
        "stage_breadth": {"pilot_system_count": 1},
        "execution_semantics": {"sandbox_required": True},
        "evidence_facts": [item.model_dump(mode="json") for item in facts],
    }
    payload["envelope_hash"] = canonical_model_hash(payload)
    return ResearchFeasibilityEnvelope.model_validate(payload)


def _author_payload(envelope: ResearchFeasibilityEnvelope) -> dict[str, Any]:
    catalog = build_system_plan_component_source_clause_catalog(envelope)
    identifiers = (
        "spectral derivative",
        "adaptive threshold",
        "rational feature library",
        "stability filter",
        "sparse regression",
        "bounded cache policy",
        "Fourier denoiser",
    )
    labels = ("谱导数", "自适应阈值", "有理特征库", "稳定筛选", "稀疏回归", "有界缓存", "傅里叶去噪")
    atoms = []
    for index, (clause, identifier, label) in enumerate(
        zip(catalog.source_clauses[:7], identifiers, labels, strict=True), 1
    ):
        explicit = list(clause.explicit_data_types)
        atoms.append(
            {
                "atom_id": f"A{index:03d}",
                "source_lineage_id": clause.source_lineage_id,
                "source_summary_sha256": clause.source_summary_sha256,
                "source_clause_id": clause.source_clause_id,
                "source_clause": clause.source_clause,
                "technical_identifier": identifier,
                "label_zh": label,
                "applicable_data_types": explicit or ["ode", "pde"],
                "rationale_zh": (
                    "该记录只把完整来源分句中的一个连续技术标识物化为待审查组件，"
                    "不声明其有效性、因果机制、预期方向或任何实验结果。"
                ),
            }
        )
    return {
        "schema_version": "system-plan-component-atom-portfolio-v1",
        "atoms": atoms,
    }


def _review_payload(author_payload: dict[str, Any]) -> dict[str, Any]:
    portfolio = SystemPlanComponentAtomPortfolio.model_validate(author_payload)
    return {
        "schema_version": "system-plan-component-atom-review-v1",
        "reviews": [
            {
                "atom_id": atom.atom_id,
                "atom_hash": canonical_model_hash(atom),
                "atomic": True,
                "source_bound": True,
                "scope_valid": True,
                "accepted": True,
                "findings_zh": [],
            }
            for atom in portfolio.atoms
        ],
    }


class _StubSequence:
    def __init__(
        self,
        payloads: list[dict[str, Any]],
        *,
        provider: str = "qwen-dashscope",
        model_name: str = "qwen3.7-max",
        reasoning: str | None = None,
    ) -> None:
        self.payloads = [copy.deepcopy(item) for item in payloads]
        self.provider = provider
        self.model_name = model_name
        self.reasoning = reasoning or (
            "先逐项核对完整来源分句和摘要哈希，再检查技术标识是否为大小写敏感的连续子串，"
            "随后检查每个分句是否只对应一个组件、显式数据类型范围是否完整保留，最后核对"
            "所有编号、顺序、独立审查布尔值和中文反馈，且不把过程推理当作科研证据。" * 3
        )
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        return LLMJsonCompletionResult(
            provider=self.provider,
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name=self.model_name,
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=copy.deepcopy(payload),
            usage={"reasoning_tokens": 800},
            temperature=float(kwargs["temperature"]),
            reasoning_text=self.reasoning,
            reasoning_transport="dashscope_enable_thinking",
        )


def _run_valid(tmp_path: Path) -> SystemPlanComponentAtomArtifact:
    envelope = _envelope()
    author_payload = _author_payload(envelope)
    return run_system_plan_component_atom_catalog(
        lineage_id="component-atom-lineage",
        feasibility_envelope=envelope,
        method_skill_selection=_method_binding(),
        output_dir=tmp_path,
        author_completion=_StubSequence([author_payload]),
        reviewer_completion=_StubSequence([_review_payload(author_payload)]),
        max_rounds=1,
        clock=FIXED_CLOCK,
    )


def test_main_and_independent_qwen_create_hash_bound_non_evidence_catalog(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    catalog = build_system_plan_component_source_clause_catalog(envelope)
    assert [item.source_clause for item in catalog.source_clauses[:5]] == [
        "PDE spectral derivative",
        "adaptive threshold",
        "rational feature library",
        "stability filter",
        "ODE sparse regression",
    ]
    assert catalog.source_clauses[1].scope_context == (
        "PDE spectral derivative and adaptive threshold"
    )
    assert catalog.source_clauses[1].explicit_data_types == ("pde",)
    author_payload = _author_payload(envelope)
    author = _StubSequence([author_payload])
    reviewer = _StubSequence([_review_payload(author_payload)])

    artifact = run_system_plan_component_atom_catalog(
        lineage_id="component-atom-lineage",
        feasibility_envelope=envelope,
        method_skill_selection=_method_binding(),
        output_dir=tmp_path,
        author_completion=author,
        reviewer_completion=reviewer,
        max_rounds=1,
        clock=FIXED_CLOCK,
    )

    assert len(artifact.final_portfolio.atoms) == 7
    assert artifact.authored_by_main_qwen is True
    assert artifact.independently_reviewed_by_qwen is True
    assert artifact.is_scientific_evidence is False
    assert artifact.execution_authorized is False
    assert artifact.approval_granted is False
    assert artifact.release_authorized is False
    assert artifact.hand_written_scientific_prose_count == 0
    assert (tmp_path / "system-plan-component-atoms.json").is_file()
    assert len(list((tmp_path / "interactions").glob("*.json"))) == 2
    assert author.calls[0]["thinking_mode"] == "enabled"
    assert author.calls[0]["thinking_budget"] == 4_000
    assert reviewer.calls[0]["thinking_mode"] == "enabled"
    author_system_prompt = author.calls[0]["messages"][0]["content"]
    assert "恰好七个" in author_system_prompt
    assert "不是必须逐条覆盖" in author_system_prompt
    assert "只有‘正确处理’" in author_system_prompt
    reviewer_system_prompt = reviewer.calls[0]["messages"][0]["content"]
    assert "完整 scope_context" in reviewer_system_prompt
    assert "不是只看拆分后的短 source_clause" in reviewer_system_prompt
    for calls in (author.calls, reviewer.calls):
        messages = calls[0]["messages"]
        assert len(messages) == 3
        assert '"$defs"' not in messages[0]["content"]
        assert '"properties"' not in messages[0]["content"]
        assert json.loads(messages[1]["content"])["context_kind"] == (
            "selected_project_method_skills"
        )
    binding = artifact.binding()
    assert binding.is_scientific_evidence is False
    assert binding.execution_authorized is False


def test_compound_clause_disguise_is_rejected_before_review(tmp_path: Path) -> None:
    envelope = _envelope()
    payload = _author_payload(envelope)
    payload["atoms"][0]["source_clause"] = (
        "PDE spectral derivative and adaptive threshold"
    )
    reviewer = _StubSequence([_review_payload(_author_payload(envelope))])

    with pytest.raises(SystemPlanComponentAtomError, match="完整来源分句"):
        run_system_plan_component_atom_catalog(
            lineage_id="compound-disguise",
            feasibility_envelope=envelope,
            method_skill_selection=_method_binding(),
            output_dir=tmp_path,
            author_completion=_StubSequence([payload]),
            reviewer_completion=reviewer,
            max_rounds=1,
            clock=FIXED_CLOCK,
        )

    assert reviewer.calls == []
    assert len(list((tmp_path / "interactions").glob("*.json"))) == 1


def test_portfolio_requires_exactly_seven_selected_atoms() -> None:
    envelope = _envelope()
    payload = _author_payload(envelope)
    eighth = copy.deepcopy(payload["atoms"][-1])
    eighth.update(
        {
            "atom_id": "A008",
            "source_clause_id": "SC008",
            "source_clause": "residual weighting",
            "technical_identifier": "residual weighting",
        }
    )
    payload["atoms"].append(eighth)

    with pytest.raises(ValidationError, match="at most 7"):
        SystemPlanComponentAtomPortfolio.model_validate(payload)


def test_short_identifier_cannot_hide_explicit_pde_scope(tmp_path: Path) -> None:
    envelope = _envelope()
    payload = _author_payload(envelope)
    payload["atoms"][0]["technical_identifier"] = "PDE"
    payload["atoms"][0]["applicable_data_types"] = ["ode", "pde"]

    with pytest.raises(SystemPlanComponentAtomError, match="PDE/ODE"):
        run_system_plan_component_atom_catalog(
            lineage_id="hidden-scope",
            feasibility_envelope=envelope,
            method_skill_selection=_method_binding(),
            output_dir=tmp_path,
            author_completion=_StubSequence([payload]),
            reviewer_completion=_StubSequence([_review_payload(_author_payload(envelope))]),
            max_rounds=1,
            clock=FIXED_CLOCK,
        )


def test_spatial_derivative_phrase_inherits_pde_scope_without_pde_token() -> None:
    envelope = _envelope(
        lineage_b_summary=(
            "bounded cache policy; spatial derivative operator; "
            "ODE polynomial basis; condition-number guard; residual weighting."
        )
    )

    catalog = build_system_plan_component_source_clause_catalog(envelope)
    spatial_clause = next(
        item
        for item in catalog.source_clauses
        if item.source_clause == "spatial derivative operator"
    )

    assert spatial_clause.explicit_data_types == ("pde",)


def test_false_review_requires_chinese_findings() -> None:
    with pytest.raises((ValidationError, SystemPlanComponentAtomError), match="findings"):
        SystemPlanComponentAtomReview(
            atom_id="A001",
            atom_hash="a" * 64,
            atomic=False,
            source_bound=True,
            scope_valid=True,
            accepted=False,
            findings_zh=(),
        )
    with pytest.raises((ValidationError, SystemPlanComponentAtomError), match="不是中文"):
        SystemPlanComponentAtomReview(
            atom_id="A001",
            atom_hash="a" * 64,
            atomic=False,
            source_bound=True,
            scope_valid=True,
            accepted=False,
            findings_zh=("This clause contains two independent operators.",),
        )


def test_reviewer_echoing_json_schema_fails_closed_and_is_retained(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    author_payload = _author_payload(envelope)
    reviewer_schema = SystemPlanComponentAtomReviewPortfolio.model_json_schema()

    with pytest.raises(
        SystemPlanComponentAtomError,
        match="SystemPlanComponentAtomReviewPortfolio",
    ):
        run_system_plan_component_atom_catalog(
            lineage_id="reviewer-schema-echo",
            feasibility_envelope=envelope,
            method_skill_selection=_method_binding(),
            output_dir=tmp_path,
            author_completion=_StubSequence([author_payload]),
            reviewer_completion=_StubSequence([reviewer_schema]),
            max_rounds=1,
            clock=FIXED_CLOCK,
        )

    retained = tmp_path / "interactions" / "system-plan-component-atoms-reviewer-01.json"
    assert retained.is_file()
    receipt = json.loads(retained.read_text(encoding="utf-8"))
    assert "$defs" in receipt["parsed_payload"]
    assert not (tmp_path / "system-plan-component-atoms.json").exists()


@pytest.mark.parametrize("mutation", ["missing", "reordered", "tampered"])
def test_reviewer_cannot_omit_reorder_or_tamper_atoms(mutation: str) -> None:
    envelope = _envelope()
    author = SystemPlanComponentAtomPortfolio.model_validate(_author_payload(envelope))
    payload = _review_payload(author.model_dump(mode="json"))
    if mutation == "missing":
        payload["reviews"] = payload["reviews"][:-1]
    elif mutation == "reordered":
        payload["reviews"][0], payload["reviews"][1] = (
            payload["reviews"][1],
            payload["reviews"][0],
        )
    else:
        payload["reviews"][0]["atom_hash"] = "f" * 64
    review = SystemPlanComponentAtomReviewPortfolio.model_validate(payload)

    assert component_atom_review_findings(review=review, portfolio=author)


def test_non_chinese_author_prose_fails_closed() -> None:
    envelope = _envelope()
    payload = _author_payload(envelope)["atoms"][0]
    payload["label_zh"] = "English component label"
    payload["rationale_zh"] = (
        "This record claims only one component and contains no Chinese prose at all."
    )

    with pytest.raises((ValidationError, SystemPlanComponentAtomError), match="不是中文"):
        SystemPlanComponentAtom.model_validate(payload)


def test_mixed_case_technical_name_is_searchable_but_label_remains_chinese() -> None:
    payload = {
        "atom_id": "A001",
        "source_lineage_id": LINEAGE_A,
        "source_summary_sha256": "a" * 64,
        "source_clause_id": "SC001",
        "source_clause": "STRidge sparse regression",
        "technical_identifier": "STRidge sparse regression",
        "label_zh": "STRidge稀疏回归",
        "applicable_data_types": ["ode", "pde"],
        "rationale_zh": (
            "该记录仅保留可搜索的技术名称，并用中文说明这是一个待独立审查的稀疏回归组件。"
        ),
    }

    atom = SystemPlanComponentAtom.model_validate(payload)
    assert atom.label_zh == "STRidge稀疏回归"

    payload["label_zh"] = "STRidge sparse regression"
    with pytest.raises((ValidationError, SystemPlanComponentAtomError), match="不是中文"):
        SystemPlanComponentAtom.model_validate(payload)


def test_rejected_review_feedback_is_returned_to_author_for_second_round(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    author_payload = _author_payload(envelope)
    rejected = _review_payload(author_payload)
    rejected["reviews"][0].update(
        {
            "atomic": False,
            "accepted": False,
            "findings_zh": ["该完整来源分句仍可能包含两个可独立改变的技术操作，需要重新原子化。"],
        }
    )
    accepted = _review_payload(author_payload)
    author = _StubSequence([author_payload, author_payload])
    reviewer = _StubSequence([rejected, accepted])

    artifact = run_system_plan_component_atom_catalog(
        lineage_id="review-retry",
        feasibility_envelope=envelope,
        method_skill_selection=_method_binding(),
        output_dir=tmp_path,
        author_completion=author,
        reviewer_completion=reviewer,
        max_rounds=2,
        clock=FIXED_CLOCK,
    )

    assert [item.round_index for item in artifact.rounds] == [1, 2]
    assert artifact.rounds[0].accepted is False
    assert artifact.rounds[1].accepted is True
    assert "A001 独立审查未通过" in author.calls[1]["messages"][0]["content"]
    assert "最低修复集而非穷尽清单" in author.calls[1]["messages"][0]["content"]
    assert "重新审计完整的七项组合" in author.calls[1]["messages"][0]["content"]
    assert len(list((tmp_path / "interactions").glob("*.json"))) == 4


def test_mechanical_repair_does_not_consume_review_repair_budget(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    invalid_author = _author_payload(envelope)
    invalid_author["atoms"][0]["technical_identifier"] = "PDE"
    valid_author = _author_payload(envelope)
    rejected_review = _review_payload(valid_author)
    rejected_review["reviews"][0].update(
        {
            "atomic": False,
            "accepted": False,
            "findings_zh": ["该分句仍包含不可独立干预的结果描述，必须改选明确技术组件。"],
        }
    )

    author = _StubSequence([invalid_author, valid_author, valid_author])
    reviewer = _StubSequence([rejected_review, _review_payload(valid_author)])
    artifact = run_system_plan_component_atom_catalog(
        lineage_id="mechanical-then-review-repair",
        feasibility_envelope=envelope,
        method_skill_selection=_method_binding(),
        output_dir=tmp_path,
        author_completion=author,
        reviewer_completion=reviewer,
        max_rounds=3,
        clock=FIXED_CLOCK,
    )

    assert [item.round_index for item in artifact.rounds] == [2, 3]
    assert artifact.rounds[0].accepted is False
    assert artifact.rounds[1].accepted is True
    assert "PDE/ODE" in author.calls[1]["messages"][0]["content"]
    assert "A001 独立审查未通过" in author.calls[2]["messages"][0]["content"]
    assert len(list((tmp_path / "interactions").glob("*.json"))) == 5


def test_qwen_receipt_identity_and_all_hashes_fail_closed(tmp_path: Path) -> None:
    artifact = _run_valid(tmp_path)
    payload = artifact.model_dump(mode="json")
    receipt = payload["rounds"][0]["author_receipt"]
    receipt["provider"] = "generic-provider"
    receipt["model_name"] = "generic-model"
    receipt["receipt_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in receipt.items()
            if key not in {"receipt_hash", "output_path"}
        }
    )
    round_payload = payload["rounds"][0]
    round_payload["round_hash"] = canonical_model_hash(
        {key: value for key, value in round_payload.items() if key != "round_hash"}
    )
    payload["artifact_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"artifact_hash", "output_path"}
        }
    )
    with pytest.raises((ValidationError, SystemPlanComponentAtomError), match="Qwen"):
        SystemPlanComponentAtomArtifact.model_validate(payload)

    binding_payload = artifact.binding().model_dump(mode="json")
    binding_payload["binding_hash"] = "0" * 64
    with pytest.raises((ValidationError, SystemPlanComponentAtomError), match="绑定哈希"):
        SystemPlanComponentAtomBinding.model_validate(binding_payload)


def test_artifact_file_is_immutable(tmp_path: Path) -> None:
    _run_valid(tmp_path)
    output_path = tmp_path / "system-plan-component-atoms.json"
    before = output_path.read_bytes()

    with pytest.raises(SystemPlanComponentAtomError, match="不可变制品"):
        run_system_plan_component_atom_catalog(
            lineage_id="different-lineage",
            feasibility_envelope=_envelope(),
            method_skill_selection=_method_binding(),
            output_dir=tmp_path,
            author_completion=_StubSequence([_author_payload(_envelope())]),
            reviewer_completion=_StubSequence(
                [_review_payload(_author_payload(_envelope()))]
            ),
            max_rounds=1,
            clock=FIXED_CLOCK,
        )
    assert output_path.read_bytes() == before
