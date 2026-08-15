"""System-authored divergent research directions before full-plan authoring.

One repair loop tends to stay inside the first method family it mentions.  This
module forces a result-blind divergent phase first, then gives a separate model
interaction veto power over every direction.  The orchestration supplies creative
*lenses* and scientific standards, never a hypothesis, method, title, or expected
result.  Every scientific sentence remains byte-bound to a model-authorship receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, ValidationError, model_validator

from autoresearch.competition.language_guard import non_chinese_prose_fields
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.model_authorship import (
    ModelAuthorshipReceipt,
    record_model_authorship_receipt,
)
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.system_plan_methodology import (
    SystemPlanMethodSkillSelectionBinding,
)
from autoresearch.competition.system_plan_opportunity_map import (
    ResearchOpportunityMapBinding,
)
from autoresearch.competition.system_plan_prospective_atoms import (
    ComponentExperimentBindingV2,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_DIRECTION_COUNT = 5
_MAX_IDEATION_ATTEMPTS = 6
_MAX_PORTFOLIO_REPAIR_ATTEMPTS = 2
_MAX_REVIEW_REPAIR_ATTEMPTS = 2
_ARTIFACT_NAME = "system-plan-ideation.json"
_SYNTHETIC_SENTINEL_SCOPE_TOKENS = (
    "maximum_fit_seconds_per_sentinel",
    "maximum_predict_seconds_per_query",
    "fit_call_count",
    "fit_calls_during_prediction",
    "free_symbol_count_maximum",
    "concrete_numeric_equations_required",
    "term_support_f1",
    "coefficient_relative_error_maximum",
    "prediction_nmse_maximum",
    "equation_prediction_max_abs_delta",
    "clean_prediction_nmse_maximum",
    "clean_coefficient_relative_error_maximum",
    "sentinel",
    "20 秒",
    "20秒",
    "512 MB",
)
_TOKEN_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*$")
_HYPHENATED_SYSTEM_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?![A-Za-z0-9])"
)
_CITATION_TITLE_PATTERN = re.compile(
    r"(?P<label>文献\s*\d+\s*)[（(][^）)\r\n]{1,300}[）)]"
)
_DIRECTION_REVIEW_GATE_FIELDS = (
    "mechanism_plausible",
    "evidence_traceable_without_fabrication",
    "falsifiable_and_identifiable",
    "confounding_and_controls_valid",
    "analysis_unit_and_result_blind_rule_valid",
    "executable_under_frozen_contract",
    "substantive_novelty",
    "more_than_component_composition",
    "generalizable_scientific_contribution",
)
_PROSECUTION_GATE_FIELDS = (
    "construct_operationally_defined",
    "evidence_claims_traceable_without_guessing",
    "mechanism_identifiable_against_alternatives",
    "confounding_and_control_design_valid",
    "analysis_unit_and_result_blind_rule_valid",
    "decisive_test_scientifically_valid",
    "execution_and_statistics_feasible",
    "substantive_novelty_against_catalog",
    "generalizable_beyond_local_evaluator",
)


def _citation_language_projection(value: str) -> str:
    """Exclude an explicitly labelled bibliographic title from prose scoring.

    A review remains bound by ``reference_index``.  Qwen may additionally quote the
    original English title after a Chinese ``文献N`` label; that title is provenance,
    not authored English reasoning.  Only this narrow labelled span is projected for
    the language ratio.  The stored review remains byte-for-byte unchanged.
    """

    return _CITATION_TITLE_PATTERN.sub(
        lambda match: f"{match.group('label')}（文献题名）",
        value,
    )
MethodToken = Annotated[
    str,
    StringConstraints(
        min_length=2,
        max_length=32,
        pattern=r"^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*$",
    ),
]
EvidenceFactId = Annotated[
    str,
    StringConstraints(pattern=r"^E[0-9]{3}$"),
]

IdeationLens = Literal[
    "假设反转",
    "机制替代",
    "跨域类比",
    "矛盾消解",
    "尺度转换",
]
_REQUIRED_LENSES = {
    "假设反转",
    "机制替代",
    "跨域类比",
    "矛盾消解",
    "尺度转换",
}


class SystemPlanIdeationError(RuntimeError):
    """Raised when no independently reviewed direction survives."""


def _is_cjk_ideograph(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2EBEF
        or 0x2F800 <= codepoint <= 0x2FA1F
        or 0x30000 <= codepoint <= 0x323AF
    )


def _missing_required_chinese_prose(
    fields: Mapping[str, str | Sequence[str]],
) -> tuple[str, ...]:
    """Reject blank or non-Chinese prose without imposing stylistic length quotas."""

    failed: list[str] = []
    for name, value in fields.items():
        items = (value,) if isinstance(value, str) else tuple(value)
        for index, item in enumerate(items):
            text = str(item).strip()
            if not text or not any(_is_cjk_ideograph(char) for char in text):
                failed.append(name if isinstance(value, str) else f"{name}[{index}]")
    return tuple(failed)


class ResearchDirectionCandidate(StrictFrozenModel):
    """One model-authored, compact and falsifiable research direction."""

    schema_version: Literal["research-direction-candidate-v2"]
    lens: IdeationLens
    opportunity_cell_id: str = Field(pattern=r"^O0[1-7]$")
    prospective_atom_id: str = Field(pattern=r"^P00[1-3]$")
    prospective_atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prospective_intervention_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prospective_origin_kind: Literal["prospective_literature_derived"] = (
        "prospective_literature_derived"
    )
    target_systems: tuple[str, ...] = Field(min_length=1)
    evidence_fact_ids: tuple[EvidenceFactId, ...] = Field(min_length=2)
    title: str = Field(min_length=1)
    scientific_gap: str = Field(min_length=1)
    challenged_assumption: str = Field(min_length=1)
    core_mechanism: str = Field(min_length=1)
    falsifiable_hypothesis: str = Field(min_length=1)
    alternative_explanation: str = Field(min_length=1)
    decisive_test: str = Field(min_length=1)
    negative_control: str = Field(min_length=1)
    sensitivity_control: str = Field(min_length=1)
    orthogonal_diagnostic: str = Field(min_length=1)
    independent_analysis_unit: str = Field(min_length=1)
    result_blind_decision_rule: str = Field(min_length=1)
    # A prospective atom may have one exact motivating paper; independent review
    # still compares every selected abstract, so requiring two here only forces a
    # fabricated extra citation.
    nearest_work_indices: tuple[int, ...] = Field(min_length=1)
    substantive_difference: str = Field(min_length=1)
    execution_fit: str = Field(min_length=1)
    failure_modes: tuple[str, ...] = Field(min_length=2)
    method_tokens: tuple[MethodToken, ...] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def _validate_candidate(self) -> ResearchDirectionCandidate:
        if len(set(self.nearest_work_indices)) != len(self.nearest_work_indices):
            raise SystemPlanIdeationError("研究方向的近邻文献编号不得重复")
        if len(set(self.target_systems)) != len(self.target_systems):
            raise SystemPlanIdeationError("研究方向的目标系统不得重复")
        if len(set(self.evidence_fact_ids)) != len(self.evidence_fact_ids):
            raise SystemPlanIdeationError("研究方向的证据事实编号不得重复")
        if len({token.lower() for token in self.method_tokens}) != len(self.method_tokens):
            raise SystemPlanIdeationError("研究方向的方法 token 不得重复")
        invalid_tokens = [
            token for token in self.method_tokens if not _TOKEN_PATTERN.fullmatch(token)
        ]
        if invalid_tokens:
            raise SystemPlanIdeationError(
                f"研究方向的方法 token 不是单个 ASCII 标识符：{invalid_tokens}"
            )
        analysis_unit_system_ids = set(
            _HYPHENATED_SYSTEM_IDENTIFIER_PATTERN.findall(
                self.independent_analysis_unit.casefold()
            )
        )
        unbound_analysis_unit_system_ids = sorted(
            analysis_unit_system_ids
            - {identifier.casefold() for identifier in self.target_systems}
        )
        if unbound_analysis_unit_system_ids:
            raise SystemPlanIdeationError(
                "独立分析单位引用了 target_systems 之外的系统标识："
                f"{unbound_analysis_unit_system_ids}"
            )
        def language_projection(value: str | tuple[str, ...]) -> str | tuple[str, ...]:
            """Do not count already-bound system IDs as free English prose.

            Target identifiers are selected in the structured ``target_systems``
            field and are later checked against the prospective atom allowlist.  A
            Chinese experimental sentence must be allowed to quote those exact IDs
            without translating them into an ambiguous nickname.  Only those bound
            identifiers are projected away for the language ratio; arbitrary English
            text remains visible to the guard.
            """

            def project(text: str) -> str:
                projected = text
                for identifier in sorted(self.target_systems, key=len, reverse=True):
                    projected = projected.replace(identifier, "目标系统")
                # Negative and sensitivity controls may deliberately name a frozen
                # machine-readable system outside the treatment targets.  Such
                # lowercase hyphenated IDs are searchable coordinates, not English
                # prose.  They are projected only for language scoring; the original
                # sentence remains unchanged for scientific review.
                return _HYPHENATED_SYSTEM_IDENTIFIER_PATTERN.sub(
                    "系统标识",
                    projected,
                )

            if isinstance(value, tuple):
                return tuple(project(item) for item in value)
            return project(value)

        required_prose: dict[str, str | tuple[str, ...]] = {
            "title": self.title,
            "scientific_gap": self.scientific_gap,
            "challenged_assumption": self.challenged_assumption,
            "core_mechanism": self.core_mechanism,
            "falsifiable_hypothesis": self.falsifiable_hypothesis,
            "alternative_explanation": self.alternative_explanation,
            "decisive_test": self.decisive_test,
            "negative_control": self.negative_control,
            "sensitivity_control": self.sensitivity_control,
            "orthogonal_diagnostic": self.orthogonal_diagnostic,
            "independent_analysis_unit": self.independent_analysis_unit,
            "result_blind_decision_rule": self.result_blind_decision_rule,
            "substantive_difference": self.substantive_difference,
            "execution_fit": self.execution_fit,
            "failure_modes": self.failure_modes,
        }
        language_failures = _missing_required_chinese_prose(required_prose)
        primary_prose = {
            "title": self.title,
            "scientific_gap": self.scientific_gap,
            "challenged_assumption": self.challenged_assumption,
            "core_mechanism": self.core_mechanism,
            "falsifiable_hypothesis": self.falsifiable_hypothesis,
            "alternative_explanation": self.alternative_explanation,
            "substantive_difference": self.substantive_difference,
        }
        language_failures += non_chinese_prose_fields(
            {
                field_name: language_projection(value)
                for field_name, value in primary_prose.items()
            }
        ) + non_chinese_prose_fields(
            {
                "decisive_test": language_projection(self.decisive_test),
                "negative_control": language_projection(self.negative_control),
                "sensitivity_control": language_projection(self.sensitivity_control),
                "orthogonal_diagnostic": language_projection(self.orthogonal_diagnostic),
                "independent_analysis_unit": language_projection(
                    self.independent_analysis_unit
                ),
                "result_blind_decision_rule": language_projection(
                    self.result_blind_decision_rule
                ),
                "execution_fit": language_projection(self.execution_fit),
                "failure_modes": language_projection(self.failure_modes),
            },
            # Experimental descriptions legitimately contain exact system, metric,
            # and method identifiers.  Half-Chinese still rejects English prose while
            # keeping searchable machine tokens intact.
            minimum_ratio=0.50,
        )
        if language_failures:
            raise SystemPlanIdeationError(f"研究方向不是中文：{list(language_failures)}")
        return self


class ResearchDirectionPortfolio(StrictFrozenModel):
    """Five deliberately divergent system-authored directions."""

    directions: tuple[ResearchDirectionCandidate, ...] = Field(
        min_length=_DIRECTION_COUNT,
        max_length=_DIRECTION_COUNT,
    )

    @model_validator(mode="after")
    def _validate_portfolio(self) -> ResearchDirectionPortfolio:
        lenses = {item.lens for item in self.directions}
        if lenses != _REQUIRED_LENSES:
            raise SystemPlanIdeationError(
                f"研究方向必须逐一覆盖五种发散视角：{sorted(_REQUIRED_LENSES)}"
            )
        normalized_titles = {item.title.casefold().strip() for item in self.directions}
        if len(normalized_titles) != _DIRECTION_COUNT:
            raise SystemPlanIdeationError("五个研究方向标题必须互不相同")
        for left_index, left in enumerate(self.directions):
            left_tokens = {token.lower() for token in left.method_tokens}
            for right in self.directions[left_index + 1 :]:
                right_tokens = {token.lower() for token in right.method_tokens}
                union = left_tokens | right_tokens
                similarity = len(left_tokens & right_tokens) / len(union)
                if similarity > 0.5:
                    raise SystemPlanIdeationError(
                        "研究方向的方法 token 重叠过高，未形成真正发散的候选集"
                    )
        return self


def _prospective_direction_binding_findings(
    *,
    direction: ResearchDirectionCandidate,
    component_experiment_binding: ComponentExperimentBindingV2,
    selected_to_retrieved_reference: Mapping[int, int] | None,
    eligible_systems: set[str] | None,
    evidence_fact_ids: set[str] | None,
) -> tuple[str, ...]:
    """Prove that one direction is an exact projection of one accepted future atom."""

    prospective = component_experiment_binding.prospective_components
    atoms = {item.atom_id: item for item in prospective.atoms}
    identities = {item.atom_id: item for item in prospective.intervention_identities}
    aliases = {item.target_key: item for item in prospective.target_aliases}
    atom = atoms.get(direction.prospective_atom_id)
    identity = identities.get(direction.prospective_atom_id)
    if atom is None or identity is None:
        return (f"引用了未被独立接受的前瞻组件 {direction.prospective_atom_id}",)

    findings: list[str] = []
    atom_hash = canonical_model_hash(atom)
    if direction.prospective_atom_hash != atom_hash:
        findings.append(f"{atom.atom_id} 的 atom hash 未逐字继承")
    if direction.prospective_intervention_hash != identity.intervention_hash:
        findings.append(f"{atom.atom_id} 的 intervention hash 未逐字继承")
    if direction.prospective_origin_kind != identity.origin_kind:
        findings.append(f"{atom.atom_id} 的 prospective origin 未逐字继承")

    unknown_target_keys = [key for key in atom.target_keys if key not in aliases]
    if unknown_target_keys:
        findings.append(f"{atom.atom_id} 引用了未知匿名目标：{unknown_target_keys}")
        expected_targets: tuple[str, ...] = ()
    else:
        expected_targets = tuple(aliases[key].system_name for key in atom.target_keys)
        if direction.target_systems != expected_targets:
            findings.append(
                f"{atom.atom_id} 的 target_systems 必须逐字等于前瞻允许集合："
                f"expected={list(expected_targets)}, current={list(direction.target_systems)}"
            )
    if eligible_systems is not None:
        outside = sorted(set(expected_targets) - eligible_systems)
        if outside:
            findings.append(f"{atom.atom_id} 的目标超出冻结可研究系统：{outside}")

    expected_facts = atom.supporting_fact_ids
    if direction.evidence_fact_ids != expected_facts:
        findings.append(
            f"{atom.atom_id} 的 evidence_fact_ids 必须逐字等于前瞻允许集合："
            f"expected={list(expected_facts)}, current={list(direction.evidence_fact_ids)}"
        )
    if evidence_fact_ids is not None:
        outside_facts = sorted(set(expected_facts) - evidence_fact_ids)
        if outside_facts:
            findings.append(f"{atom.atom_id} 的证据事实不在冻结边界：{outside_facts}")

    # ``retrieval_index`` is frozen into every literature support by the
    # prospective-atom artifact after an exact selected↔catalog join.  Therefore
    # the canonical full-catalog reference number is always available here, even
    # when an artifact is reloaded without the original survey objects.  Do not
    # make this gate optional: otherwise a retained artifact can silently swap the
    # selected-reference domain (1..n) back in for the full catalog domain.
    expected_references = tuple(
        item.retrieval_index + 1 for item in atom.literature_supports
    )
    if direction.nearest_work_indices != expected_references:
        findings.append(
            f"{atom.atom_id} 的 nearest_work_indices 必须逐字等于前瞻文献"
            "在完整目录中的 reference_index："
            f"expected={list(expected_references)}, "
            f"current={list(direction.nearest_work_indices)}"
        )

    if selected_to_retrieved_reference is not None:
        unknown_selected = sorted(
            {
                item.reference_index
                for item in atom.literature_supports
                if item.reference_index not in selected_to_retrieved_reference
            }
        )
        if unknown_selected:
            findings.append(f"{atom.atom_id} 引用了未知入选文献顺序：{unknown_selected}")
        else:
            mapped_references = tuple(
                selected_to_retrieved_reference[item.reference_index]
                for item in atom.literature_supports
            )
            if mapped_references != expected_references:
                findings.append(
                    f"{atom.atom_id} 的文献支持内部 retrieval_index 与"
                    " selected_to_retrieved 映射不一致："
                    f"atom={list(expected_references)}, "
                    f"survey={list(mapped_references)}"
                )
    return tuple(findings)


def _component_experiment_binding_findings(
    *,
    component_experiment_binding: ComponentExperimentBindingV2,
    opportunity_map: ResearchOpportunityMapBinding,
    literature_identity_map: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Join the stable prospective binding back to the exact ideation inputs."""

    observed = component_experiment_binding.observed_components
    prospective = component_experiment_binding.prospective_components
    envelope = opportunity_map.feasibility_envelope
    findings: list[str] = []
    for label, actual in (
        ("observed", observed.feasibility_envelope_hash),
        ("prospective", prospective.feasibility_envelope_hash),
    ):
        if actual != envelope.envelope_hash:
            findings.append(f"{label} 组件未绑定当前 feasibility envelope")
    method_selection = opportunity_map.method_skill_selection
    if method_selection is None:
        findings.append("前瞻方向要求机会图携带已选方法技能绑定")
    else:
        expected_method_hash = method_selection.selection_artifact_hash
        if observed.method_skill_selection_artifact_hash != expected_method_hash:
            findings.append("observed 组件与当前方法技能选择不一致")
        if prospective.method_skill_selection_artifact_hash != expected_method_hash:
            findings.append("prospective 组件与当前方法技能选择不一致")

    observed_atoms = {item.atom_id: item for item in observed.atoms}
    aliases = {item.target_key: item for item in prospective.target_aliases}
    if len(aliases) != len(prospective.target_aliases):
        findings.append("前瞻目标 alias 重复")
    if len({item.system_name for item in prospective.target_aliases}) != len(
        prospective.target_aliases
    ):
        findings.append("前瞻目标 alias 重复映射同一系统")
    eligible_system_types = {
        item.system_name: item.data_type for item in envelope.eligible_systems
    }
    eligible_systems = set(eligible_system_types)
    known_facts = {item.fact_id for item in envelope.evidence_facts}
    identity_by_selected = {
        int(item["selected_reference_index"]): item for item in literature_identity_map
    }
    catalog_by_reference = dict(enumerate(retrieved_catalog, 1))
    for alias in prospective.target_aliases:
        if alias.system_name not in eligible_systems:
            findings.append(f"{alias.target_key} 映射到冻结边界外系统")
        elif alias.data_type != eligible_system_types[alias.system_name]:
            findings.append(f"{alias.target_key} 的数据类型与冻结边界不一致")
        unknown_facts = sorted(set(alias.required_fact_ids) - known_facts)
        if unknown_facts:
            findings.append(f"{alias.target_key} 引用了未知事实：{unknown_facts}")
    for atom in prospective.atoms:
        baseline = observed_atoms.get(atom.baseline_observed_atom_id)
        if baseline is None or canonical_model_hash(baseline) != atom.baseline_observed_atom_hash:
            findings.append(f"{atom.atom_id} 的 observed baseline 身份不符")
        unknown_target_keys = [key for key in atom.target_keys if key not in aliases]
        if unknown_target_keys:
            findings.append(f"{atom.atom_id} 引用了未知目标 alias")
        else:
            expected_facts = tuple(
                sorted(
                    {
                        fact_id
                        for target_key in atom.target_keys
                        for fact_id in aliases[target_key].required_fact_ids
                    }
                )
            )
            if atom.supporting_fact_ids != expected_facts:
                findings.append(
                    f"{atom.atom_id} 的支持事实不是所选目标必需事实的稳定并集"
                )
            expected_types = tuple(
                sorted({aliases[target_key].data_type for target_key in atom.target_keys})
            )
            if atom.applicable_data_types != expected_types:
                findings.append(f"{atom.atom_id} 的目标类型与目标 alias 不一致")
            if baseline is not None and not set(expected_types).issubset(
                baseline.applicable_data_types
            ):
                findings.append(
                    f"{atom.atom_id} 的 observed baseline 不支持所选目标类型"
                )
        unknown_facts = sorted(set(atom.supporting_fact_ids) - known_facts)
        if unknown_facts:
            findings.append(f"{atom.atom_id} 引用了未知冻结事实：{unknown_facts}")
        for support in atom.literature_supports:
            identity = identity_by_selected.get(support.reference_index)
            if identity is None:
                findings.append(
                    f"{atom.atom_id} 引用了未知入选文献顺序 {support.reference_index}"
                )
                continue
            catalog_reference = int(identity["retrieved_catalog_reference_index"])
            catalog_item = catalog_by_reference[catalog_reference]
            abstract = str(catalog_item.get("abstract") or "")
            support_span_hash = hashlib.sha256(
                support.exact_support_span.encode("utf-8")
            ).hexdigest()
            if (
                support.retrieval_index != identity["retrieval_index"]
                or support.source_record_hash != identity["source_record_hash"]
                or not abstract
                or support.abstract_sha256
                != hashlib.sha256(abstract.encode("utf-8")).hexdigest()
                or support.exact_support_span not in abstract
                or support.support_span_sha256 != support_span_hash
            ):
                findings.append(
                    f"{atom.atom_id} 的文献支持 {support.reference_index} "
                    "未逐字绑定完整目录身份与摘要"
                )
    return tuple(findings)


def _prospective_direction_allowlist(
    *,
    component_experiment_binding: ComponentExperimentBindingV2,
    selected_to_retrieved_reference: Mapping[int, int],
) -> list[dict[str, Any]]:
    """Resolve each accepted anonymous prospective atom to exact direction fields."""

    prospective = component_experiment_binding.prospective_components
    aliases = {item.target_key: item for item in prospective.target_aliases}
    identities = {item.atom_id: item for item in prospective.intervention_identities}
    return [
        {
            "prospective_atom_id": atom.atom_id,
            "prospective_atom_hash": canonical_model_hash(atom),
            "prospective_intervention_hash": identities[atom.atom_id].intervention_hash,
            "prospective_origin_kind": identities[atom.atom_id].origin_kind,
            "target_systems": [aliases[key].system_name for key in atom.target_keys],
            "evidence_fact_ids": list(atom.supporting_fact_ids),
            "nearest_work_indices": [
                selected_to_retrieved_reference[item.reference_index]
                for item in atom.literature_supports
            ],
            "prospective_atom": atom.model_dump(mode="json"),
            "intervention_identity": identities[atom.atom_id].model_dump(mode="json"),
        }
        for atom in prospective.atoms
    ]


def _ideation_feasibility_projection(
    *,
    opportunity_map: ResearchOpportunityMapBinding,
    component_experiment_binding: ComponentExperimentBindingV2,
) -> dict[str, Any]:
    """Project the full envelope to facts that a prospective atom may cite.

    The canonical envelope hash remains present, while facts outside every
    independently accepted prospective atom are omitted from model-visible text.
    This removes dead context without expanding the scientific evidence boundary.
    """

    required_fact_ids = {
        fact_id
        for atom in component_experiment_binding.prospective_components.atoms
        for fact_id in atom.supporting_fact_ids
    }
    envelope = opportunity_map.feasibility_envelope
    payload = envelope.model_dump(mode="json")
    full_facts = tuple(envelope.evidence_facts)
    projected_facts = tuple(
        fact for fact in full_facts if fact.fact_id in required_fact_ids
    )
    projected_ids = {fact.fact_id for fact in projected_facts}
    if projected_ids != required_fact_ids:
        raise SystemPlanIdeationError(
            "前瞻原子引用了 feasibility envelope 中不存在的证据事实："
            f"{sorted(required_fact_ids - projected_ids)}"
        )
    payload["evidence_facts"] = [
        fact.model_dump(mode="json") for fact in projected_facts
    ]
    payload["evidence_projection"] = {
        "projection_kind": "prospective_atom_required_facts_only",
        "full_envelope_hash": envelope.envelope_hash,
        "full_evidence_fact_count": len(full_facts),
        "projected_evidence_fact_count": len(projected_facts),
        "projected_fact_ids": [fact.fact_id for fact in projected_facts],
    }
    return payload


class DirectionPriorWorkComparison(StrictFrozenModel):
    """Reviewer-authored comparison to one actually retrieved work."""

    reference_index: int = Field(ge=1)
    overlap: str = Field(min_length=1)
    difference: str = Field(min_length=1)
    residual_novelty_risk: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_chinese_prose(self) -> DirectionPriorWorkComparison:
        prose = {
            "overlap": self.overlap,
            "difference": self.difference,
            "residual_novelty_risk": self.residual_novelty_risk,
        }
        failures = _missing_required_chinese_prose(prose)
        failures += non_chinese_prose_fields(
            {
                name: _citation_language_projection(value)
                for name, value in prose.items()
            }
        )
        if failures:
            raise SystemPlanIdeationError(f"近邻工作比较不是中文：{list(failures)}")
        return self


class ResearchDirectionAssessment(StrictFrozenModel):
    """Independent verdict for one portfolio entry."""

    direction_index: int = Field(ge=1, le=_DIRECTION_COUNT)
    prior_work_comparisons: tuple[DirectionPriorWorkComparison, ...] = Field(min_length=3)
    mechanism_plausible: bool
    evidence_traceable_without_fabrication: bool
    falsifiable_and_identifiable: bool
    confounding_and_controls_valid: bool
    analysis_unit_and_result_blind_rule_valid: bool
    executable_under_frozen_contract: bool
    substantive_novelty: bool
    more_than_component_composition: bool
    generalizable_scientific_contribution: bool
    critical_findings: tuple[str, ...] = Field(
        description=(
            "只填写尚未解决且足以否决方向的缺陷；九项布尔门全部为 true 时必须为空，"
            "正面评价不得写入此字段。"
        )
    )

    @model_validator(mode="after")
    def _validate_gate_findings(self) -> ResearchDirectionAssessment:
        reference_indices = tuple(
            comparison.reference_index for comparison in self.prior_work_comparisons
        )
        if len(set(reference_indices)) != len(reference_indices):
            raise SystemPlanIdeationError(
                f"方向{self.direction_index}必须比较至少三篇 reference_index " "互不相同的文献"
            )
        gates = (
            self.mechanism_plausible,
            self.evidence_traceable_without_fabrication,
            self.falsifiable_and_identifiable,
            self.confounding_and_controls_valid,
            self.analysis_unit_and_result_blind_rule_valid,
            self.executable_under_frozen_contract,
            self.substantive_novelty,
            self.more_than_component_composition,
            self.generalizable_scientific_contribution,
        )
        if all(gates) and self.critical_findings:
            raise SystemPlanIdeationError(
                f"方向{self.direction_index}九项门禁全通过时 critical_findings 必须为空"
            )
        if not all(gates) and not self.critical_findings:
            raise SystemPlanIdeationError(
                f"方向{self.direction_index}存在未通过门禁时必须给出 critical finding"
            )
        return self

    def qualifies(self) -> bool:
        return (
            self.mechanism_plausible
            and self.evidence_traceable_without_fabrication
            and self.falsifiable_and_identifiable
            and self.confounding_and_controls_valid
            and self.analysis_unit_and_result_blind_rule_valid
            and self.executable_under_frozen_contract
            and self.substantive_novelty
            and self.more_than_component_composition
            and self.generalizable_scientific_contribution
            and not self.critical_findings
        )


class ResearchDirectionDecision(StrictFrozenModel):
    """Fail-closed tournament decision; no weighted score can hide a red gate."""

    schema_version: Literal["research-direction-decision-v2"] = "research-direction-decision-v2"
    assessments: tuple[ResearchDirectionAssessment, ...] = Field(
        min_length=_DIRECTION_COUNT,
        max_length=_DIRECTION_COUNT,
    )
    selected_direction_index: int | None = Field(
        default=None,
        ge=1,
        le=_DIRECTION_COUNT,
    )
    selection_rationale: str = Field(min_length=1)
    portfolio_ready: bool

    @model_validator(mode="after")
    def _validate_decision(self) -> ResearchDirectionDecision:
        indices = sorted(item.direction_index for item in self.assessments)
        if indices != list(range(1, _DIRECTION_COUNT + 1)):
            raise SystemPlanIdeationError("方向评审必须恰好覆盖 direction_index 1..5")
        qualifying = {item.direction_index for item in self.assessments if item.qualifies()}
        expected_ready = self.selected_direction_index is not None
        if self.portfolio_ready != expected_ready:
            raise SystemPlanIdeationError("方向竞赛 ready 状态与入选编号矛盾")
        if self.selected_direction_index is not None:
            if self.selected_direction_index not in qualifying:
                raise SystemPlanIdeationError("入选方向没有通过全部九项门禁")
        elif qualifying:
            raise SystemPlanIdeationError("存在全门禁合格方向却未选择")
        prose: dict[str, str | tuple[str, ...]] = {
            "selection_rationale": self.selection_rationale,
            "critical_findings": tuple(
                finding for item in self.assessments for finding in item.critical_findings
            ),
            "prior_work.overlap": tuple(
                comparison.overlap
                for item in self.assessments
                for comparison in item.prior_work_comparisons
            ),
            "prior_work.difference": tuple(
                comparison.difference
                for item in self.assessments
                for comparison in item.prior_work_comparisons
            ),
            "prior_work.residual_novelty_risk": tuple(
                comparison.residual_novelty_risk
                for item in self.assessments
                for comparison in item.prior_work_comparisons
            ),
        }
        language_failures = _missing_required_chinese_prose(prose)
        comparison_fields = {
            name: tuple(_citation_language_projection(item) for item in value)
            for name, value in prose.items()
            if name.startswith("prior_work.") and isinstance(value, tuple)
        }
        narrative_fields = {
            name: value
            for name, value in prose.items()
            if not name.startswith("prior_work.")
        }
        language_failures += non_chinese_prose_fields(narrative_fields)
        language_failures += non_chinese_prose_fields(comparison_fields)
        if language_failures:
            raise SystemPlanIdeationError(f"方向评审不是中文：{list(language_failures)}")
        return self

    def feedback(self) -> tuple[str, ...]:
        """Preserve exact reviewer findings for the next divergent attempt."""

        return tuple(
            dict.fromkeys(
                (
                    self.selection_rationale,
                    *(
                        f"方向{item.direction_index}：{finding}"
                        for item in self.assessments
                        for finding in item.critical_findings
                    ),
                )
            )
        )


class SelectedDirectionProsecution(StrictFrozenModel):
    """Independent red-team verdict for the one direction a tournament selected."""

    schema_version: Literal["selected-direction-prosecution-v2"] = (
        "selected-direction-prosecution-v2"
    )
    selected_direction_index: int = Field(ge=1, le=_DIRECTION_COUNT)
    overall_assessment: str = Field(min_length=1)
    closest_prior_work: tuple[DirectionPriorWorkComparison, ...] = Field(min_length=3)
    construct_operationally_defined: bool
    evidence_claims_traceable_without_guessing: bool
    mechanism_identifiable_against_alternatives: bool
    confounding_and_control_design_valid: bool
    analysis_unit_and_result_blind_rule_valid: bool
    decisive_test_scientifically_valid: bool
    execution_and_statistics_feasible: bool
    substantive_novelty_against_catalog: bool
    generalizable_beyond_local_evaluator: bool
    critical_findings: tuple[str, ...]
    required_revisions: tuple[str, ...]
    survives_adversarial_review: bool

    @model_validator(mode="after")
    def _validate_prosecution(self) -> SelectedDirectionProsecution:
        reference_indices = tuple(
            comparison.reference_index for comparison in self.closest_prior_work
        )
        if len(set(reference_indices)) != len(reference_indices):
            raise SystemPlanIdeationError(
                "入选方向反方审查必须比较至少三篇 reference_index 互不相同的文献"
            )
        expected_ready = (
            self.construct_operationally_defined
            and self.evidence_claims_traceable_without_guessing
            and self.mechanism_identifiable_against_alternatives
            and self.confounding_and_control_design_valid
            and self.analysis_unit_and_result_blind_rule_valid
            and self.decisive_test_scientifically_valid
            and self.execution_and_statistics_feasible
            and self.substantive_novelty_against_catalog
            and self.generalizable_beyond_local_evaluator
            and not self.critical_findings
            and not self.required_revisions
        )
        if self.survives_adversarial_review != expected_ready:
            raise SystemPlanIdeationError("入选方向反方审查状态与布尔门禁或发现矛盾")
        if not expected_ready and not (self.critical_findings or self.required_revisions):
            raise SystemPlanIdeationError("被否决的入选方向必须给出中文可操作理由")
        prose: dict[str, str | tuple[str, ...]] = {
            "overall_assessment": self.overall_assessment,
            "critical_findings": self.critical_findings,
            "required_revisions": self.required_revisions,
            "closest_prior_work.overlap": tuple(item.overlap for item in self.closest_prior_work),
            "closest_prior_work.difference": tuple(
                item.difference for item in self.closest_prior_work
            ),
            "closest_prior_work.residual_novelty_risk": tuple(
                item.residual_novelty_risk for item in self.closest_prior_work
            ),
        }
        language_failures = _missing_required_chinese_prose(prose)
        comparison_fields = {
            name: tuple(_citation_language_projection(item) for item in value)
            for name, value in prose.items()
            if name.startswith("closest_prior_work.") and isinstance(value, tuple)
        }
        narrative_fields = {
            name: value
            for name, value in prose.items()
            if not name.startswith("closest_prior_work.")
        }
        language_failures += non_chinese_prose_fields(narrative_fields)
        language_failures += non_chinese_prose_fields(comparison_fields)
        if language_failures:
            raise SystemPlanIdeationError(f"入选方向反方审查不是中文：{list(language_failures)}")
        return self

    def feedback(self) -> tuple[str, ...]:
        """Return only exact model-authored veto findings to the next author call."""

        return tuple(dict.fromkeys((*self.critical_findings, *self.required_revisions)))


_DIRECTION_MACHINE_FIELDS = (
    "schema_version",
    "prospective_atom_hash",
    "prospective_intervention_hash",
    "prospective_origin_kind",
    "target_systems",
    "evidence_fact_ids",
    "nearest_work_indices",
)


def _drop_schema_properties(
    schema: dict[str, Any],
    field_names: Sequence[str],
) -> None:
    """Remove orchestrator-owned fields from one JSON-schema object in place."""

    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise SystemPlanIdeationError("Qwen 响应 schema 不是可投影的对象")
    for field_name in field_names:
        properties.pop(field_name, None)
    schema["required"] = [
        field_name for field_name in required if field_name not in field_names
    ]


def _portfolio_response_schema() -> dict[str, Any]:
    """Expose only scientific choices and prose to the direction author."""

    schema: dict[str, Any] = json.loads(
        json.dumps(ResearchDirectionPortfolio.model_json_schema())
    )
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        raise SystemPlanIdeationError("方向组合 schema 缺少候选定义")
    candidate_schema = definitions.get("ResearchDirectionCandidate")
    if not isinstance(candidate_schema, dict):
        raise SystemPlanIdeationError("方向组合 schema 缺少候选对象")
    _drop_schema_properties(candidate_schema, _DIRECTION_MACHINE_FIELDS)
    return schema


def _project_portfolio_payload(
    payload: Any,
    *,
    prospective_allowlist: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind each Qwen-chosen atom ID to its exact machine-owned identity fields."""

    if not isinstance(payload, Mapping):
        raise SystemPlanIdeationError("方向组合响应必须为 JSON 对象")
    raw_directions = payload.get("directions")
    if not isinstance(raw_directions, list | tuple):
        raise SystemPlanIdeationError("方向组合 directions 必须为 JSON 数组")
    canonical_by_atom: dict[str, Mapping[str, Any]] = {}
    for item in prospective_allowlist:
        atom_id = item.get("prospective_atom_id")
        if not isinstance(atom_id, str) or atom_id in canonical_by_atom:
            raise SystemPlanIdeationError("前瞻方向允许集合含未知或重复 atom identity")
        if any(field_name not in item for field_name in _DIRECTION_MACHINE_FIELDS[1:]):
            raise SystemPlanIdeationError(f"{atom_id} 的前瞻方向允许集合不完整")
        canonical_by_atom[atom_id] = item

    projected_directions: list[dict[str, Any]] = []
    for direction_index, raw_direction in enumerate(raw_directions, 1):
        if not isinstance(raw_direction, Mapping):
            raise SystemPlanIdeationError(
                f"方向{direction_index}必须为 JSON 对象"
            )
        atom_id = raw_direction.get("prospective_atom_id")
        if not isinstance(atom_id, str) or atom_id not in canonical_by_atom:
            raise SystemPlanIdeationError(
                f"方向{direction_index}引用了未知前瞻 atom identity：{atom_id}"
            )
        canonical = canonical_by_atom[atom_id]
        direction = dict(raw_direction)
        direction["schema_version"] = "research-direction-candidate-v2"
        for field_name in _DIRECTION_MACHINE_FIELDS[1:]:
            direction[field_name] = canonical[field_name]
        projected_directions.append(direction)
    projected = dict(payload)
    projected["directions"] = projected_directions
    return projected


def _review_response_schema() -> dict[str, Any]:
    """Hide positional and logically derived review fields from Qwen."""

    schema: dict[str, Any] = json.loads(
        json.dumps(ResearchDirectionDecision.model_json_schema())
    )
    _drop_schema_properties(schema, ("schema_version", "portfolio_ready"))
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        raise SystemPlanIdeationError("方向评审 schema 缺少 assessment 定义")
    assessment_schema = definitions.get("ResearchDirectionAssessment")
    if not isinstance(assessment_schema, dict):
        raise SystemPlanIdeationError("方向评审 schema 缺少 assessment 对象")
    _drop_schema_properties(assessment_schema, ("direction_index",))
    return schema


def _project_review_payload(payload: Any) -> dict[str, Any]:
    """Attach stable positions and derive readiness without changing any gate."""

    if not isinstance(payload, Mapping):
        raise SystemPlanIdeationError("方向评审响应必须为 JSON 对象")
    raw_assessments = payload.get("assessments")
    if not isinstance(raw_assessments, list | tuple):
        raise SystemPlanIdeationError("方向评审 assessments 必须为 JSON 数组")
    assessments: list[dict[str, Any]] = []
    for direction_index, raw_assessment in enumerate(raw_assessments, 1):
        if not isinstance(raw_assessment, Mapping):
            raise SystemPlanIdeationError(
                f"方向{direction_index}评审必须为 JSON 对象"
            )
        assessment = dict(raw_assessment)
        assessment["direction_index"] = direction_index
        assessments.append(assessment)
    projected = dict(payload)
    projected["schema_version"] = "research-direction-decision-v2"
    projected["assessments"] = assessments
    projected["portfolio_ready"] = projected.get("selected_direction_index") is not None
    return projected


def _prosecution_response_schema() -> dict[str, Any]:
    """Hide route identity and the deterministic final conjunction from Qwen."""

    schema: dict[str, Any] = json.loads(
        json.dumps(SelectedDirectionProsecution.model_json_schema())
    )
    _drop_schema_properties(
        schema,
        (
            "schema_version",
            "selected_direction_index",
            "survives_adversarial_review",
        ),
    )
    return schema


def _project_prosecution_payload(
    payload: Any,
    *,
    selected_direction_index: int,
) -> dict[str, Any]:
    """Bind the reviewed direction and derive the final veto conjunction."""

    if not isinstance(payload, Mapping):
        raise SystemPlanIdeationError("反方审查响应必须为 JSON 对象")
    projected = dict(payload)
    projected["schema_version"] = "selected-direction-prosecution-v2"
    projected["selected_direction_index"] = selected_direction_index
    projected["survives_adversarial_review"] = (
        all(projected.get(field_name) is True for field_name in _PROSECUTION_GATE_FIELDS)
        and projected.get("critical_findings") in ([], ())
        and projected.get("required_revisions") in ([], ())
    )
    return projected


class SystemPlanIdeationArtifact(StrictFrozenModel):
    """Accepted portfolio decision plus exact author/reviewer interactions."""

    schema_version: Literal["system-plan-ideation-v4"]
    lineage_id: str = Field(min_length=1)
    opportunity_map_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_experiment_binding: ComponentExperimentBindingV2
    component_experiment_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authoring_attempt: int = Field(ge=1)
    portfolio: ResearchDirectionPortfolio
    decision: ResearchDirectionDecision
    selected_direction: ResearchDirectionCandidate
    selected_direction_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    portfolio_authorship_receipt_relative_path: str
    portfolio_authorship_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_authorship_receipt_relative_path: str
    review_authorship_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prosecution: SelectedDirectionProsecution
    prosecution_authorship_receipt_relative_path: str
    prosecution_authorship_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    portfolio_model_name: str = Field(min_length=1)
    review_model_name: str = Field(min_length=1)
    prosecution_model_name: str = Field(min_length=1)
    authored_by_model: Literal[True] = True
    hand_written_scientific_prose_count: Literal[0] = 0
    execution_authorized: Literal[False] = False
    is_scientific_evidence: Literal[False] = False
    created_at: datetime
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_artifact(self) -> SystemPlanIdeationArtifact:
        if (
            self.component_experiment_binding_hash
            != self.component_experiment_binding.binding_hash
        ):
            raise SystemPlanIdeationError("方向竞赛制品的组件实验绑定哈希不符")
        selected_index = self.decision.selected_direction_index
        if selected_index is None:
            raise SystemPlanIdeationError("规范方向竞赛制品必须包含入选方向")
        if self.selected_direction != self.portfolio.directions[selected_index - 1]:
            raise SystemPlanIdeationError("入选方向与竞赛编号不一致")
        if self.prosecution.selected_direction_index != selected_index:
            raise SystemPlanIdeationError("入选方向与反方审查编号不一致")
        if not self.prosecution.survives_adversarial_review:
            raise SystemPlanIdeationError("规范方向竞赛制品不得包含反方审查已否决方向")
        expected_direction_hash = canonical_model_hash(
            self.selected_direction.model_dump(mode="json")
        )
        if self.selected_direction_hash != expected_direction_hash:
            raise SystemPlanIdeationError("入选方向哈希不符")
        binding_findings = tuple(
            f"方向{index}：{finding}"
            for index, direction in enumerate(self.portfolio.directions, 1)
            for finding in _prospective_direction_binding_findings(
                direction=direction,
                component_experiment_binding=self.component_experiment_binding,
                selected_to_retrieved_reference=None,
                eligible_systems=None,
                evidence_fact_ids=None,
            )
        )
        if binding_findings:
            raise SystemPlanIdeationError(
                "入选方向没有逐字绑定前瞻干预：" + "；".join(binding_findings)
            )
        expected_artifact_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash", "output_path"})
        )
        if self.artifact_hash != expected_artifact_hash:
            raise SystemPlanIdeationError("方向竞赛制品哈希不符")
        return self


def _direction_scientific_signature(
    direction: ResearchDirectionCandidate,
) -> str:
    """Hash scientific content while ignoring titles and citation bookkeeping."""

    return canonical_model_hash(
        {
            "lens": direction.lens,
            "opportunity_cell_id": direction.opportunity_cell_id,
            "prospective_atom_id": direction.prospective_atom_id,
            "prospective_atom_hash": direction.prospective_atom_hash,
            "prospective_intervention_hash": direction.prospective_intervention_hash,
            "prospective_origin_kind": direction.prospective_origin_kind,
            "target_systems": list(direction.target_systems),
            "evidence_fact_ids": list(direction.evidence_fact_ids),
            "scientific_gap": direction.scientific_gap,
            "challenged_assumption": direction.challenged_assumption,
            "core_mechanism": direction.core_mechanism,
            "falsifiable_hypothesis": direction.falsifiable_hypothesis,
            "alternative_explanation": direction.alternative_explanation,
            "decisive_test": direction.decisive_test,
            "negative_control": direction.negative_control,
            "sensitivity_control": direction.sensitivity_control,
            "orthogonal_diagnostic": direction.orthogonal_diagnostic,
            "independent_analysis_unit": direction.independent_analysis_unit,
            "result_blind_decision_rule": direction.result_blind_decision_rule,
            "substantive_difference": direction.substantive_difference,
            "failure_modes": list(direction.failure_modes),
            "method_tokens": list(direction.method_tokens),
        }
    )


def _rejected_direction_summary(
    direction: ResearchDirectionCandidate,
) -> dict[str, Any]:
    """Expose only a model-derived anti-repetition fingerprint, not old prose."""

    return {
        "scientific_signature": _direction_scientific_signature(direction),
        "title": direction.title,
        "method_tokens": list(direction.method_tokens),
        "core_mechanism_sha256": canonical_model_hash({"core_mechanism": direction.core_mechanism}),
    }


def _failed_gate_feedback(
    decision: ResearchDirectionDecision,
) -> tuple[str, ...]:
    """Expose reviewer booleans to the next model without adding science."""

    gate_labels = (
        ("mechanism_plausible", "机制符合科学原理"),
        (
            "evidence_traceable_without_fabrication",
            "证据主张可逐项追溯且无属性臆测",
        ),
        ("falsifiable_and_identifiable", "可证伪且机制可识别"),
        ("confounding_and_controls_valid", "混杂分析与对照设计有效"),
        (
            "analysis_unit_and_result_blind_rule_valid",
            "分析单位与结果盲判定规则有效",
        ),
        ("executable_under_frozen_contract", "冻结边界内可执行"),
        ("substantive_novelty", "相对真实近邻具有实质新颖性"),
        ("more_than_component_composition", "超越已有组件拼接"),
        (
            "generalizable_scientific_contribution",
            "可推广到本仓库与本评估器之外",
        ),
    )
    feedback: list[str] = []
    for assessment in decision.assessments:
        failed = [label for field, label in gate_labels if not bool(getattr(assessment, field))]
        if failed:
            feedback.append(f"方向{assessment.direction_index}未通过硬门禁：" + "、".join(failed))
    return tuple(feedback)


def _merge_feedback(existing: Sequence[str], *additional: str) -> tuple[str, ...]:
    """Append diagnostics without erasing an earlier scientific veto."""

    return tuple(dict.fromkeys((*existing, *(item for item in additional if item))))


def _invalid_scope_sentences(sentences: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        sentence
        for sentence in sentences
        if any(token in sentence for token in _SYNTHETIC_SENTINEL_SCOPE_TOKENS)
    )


def _raw_string_items(
    payload: Mapping[str, Any],
    field_name: str,
) -> tuple[str, ...]:
    raw_items = payload.get(field_name)
    if not isinstance(raw_items, list | tuple):
        return ()
    return tuple(item for item in raw_items if isinstance(item, str) and item)


def _nonmechanical_review_findings(
    raw_assessment: Mapping[str, Any],
) -> tuple[str, ...]:
    raw_findings = _raw_string_items(raw_assessment, "critical_findings")
    return tuple(
        finding
        for finding in raw_findings
        if not _invalid_scope_sentences((finding,))
        and not _is_obvious_positive_non_finding(finding)
    )


def _is_obvious_positive_non_finding(finding: str) -> bool:
    positive_markers = (
        "清楚",
        "可执行",
        "已通过",
        "符合全部",
        "具有明确的正交诊断",
    )
    negative_markers = (
        "不足",
        "缺少",
        "无法",
        "不能",
        "不可",
        "冲突",
        "不成立",
        "未解决",
        "风险",
    )
    return sum(marker in finding for marker in positive_markers) >= 2 and not any(
        marker in finding for marker in negative_markers
    )


def _finding_is_already_chinese(finding: str) -> bool:
    return not non_chinese_prose_fields({"critical_finding": finding})


def _raw_review_scientific_feedback(
    payload: Mapping[str, Any],
) -> tuple[str, ...]:
    feedback: list[str] = []
    raw_assessments = payload.get("assessments")
    if not isinstance(raw_assessments, list | tuple):
        return ()
    for raw_assessment in raw_assessments:
        if not isinstance(raw_assessment, Mapping):
            continue
        direction_index = raw_assessment.get("direction_index")
        label = (
            f"方向{direction_index}"
            if isinstance(direction_index, int) and not isinstance(direction_index, bool)
            else "未知方向"
        )
        failed_gates = [
            field_name
            for field_name in _DIRECTION_REVIEW_GATE_FIELDS
            if raw_assessment.get(field_name) is False
        ]
        if failed_gates:
            feedback.append(f"{label}既有 false 科学门禁：{failed_gates}")
        feedback.extend(
            f"{label}既有科学否决：{finding}"
            for finding in _nonmechanical_review_findings(raw_assessment)
        )
    return tuple(dict.fromkeys(feedback))


def _review_repair_monotonic_findings(
    *,
    prior_reviews: Sequence[Mapping[str, Any]],
    candidate: ResearchDirectionDecision,
) -> tuple[str, ...]:
    """Forbid one review JSON repair from weakening prior scientific judgment."""

    candidate_by_index = {
        assessment.direction_index: assessment for assessment in candidate.assessments
    }
    findings: list[str] = []
    for repair_index, prior in enumerate(prior_reviews, 1):
        if prior.get("portfolio_ready") is False and candidate.portfolio_ready:
            findings.append(
                f"第{repair_index}份待修评审已判 portfolio_ready=false，" "机器修复不得改成 true"
            )
        if "selected_direction_index" in prior:
            prior_selected = prior.get("selected_direction_index")
            if prior_selected is None and candidate.selected_direction_index is not None:
                findings.append(
                    f"第{repair_index}份待修评审未选择任何方向，" "机器修复不得新增入选方向"
                )
            elif (
                isinstance(prior_selected, int)
                and not isinstance(prior_selected, bool)
                and candidate.selected_direction_index not in {None, prior_selected}
            ):
                findings.append(
                    f"第{repair_index}份待修评审只选择方向{prior_selected}，"
                    "机器修复不得改选此前未选择的方向"
                )
        raw_assessments = prior.get("assessments")
        if not isinstance(raw_assessments, list | tuple):
            continue
        for raw_assessment in raw_assessments:
            if not isinstance(raw_assessment, Mapping):
                continue
            direction_index = raw_assessment.get("direction_index")
            if (
                not isinstance(direction_index, int)
                or isinstance(direction_index, bool)
                or direction_index not in candidate_by_index
            ):
                continue
            candidate_assessment = candidate_by_index[direction_index]
            for field_name in _DIRECTION_REVIEW_GATE_FIELDS:
                if raw_assessment.get(field_name) is False and getattr(
                    candidate_assessment, field_name
                ):
                    findings.append(
                        f"方向{direction_index}.{field_name} 已被第{repair_index}份"
                        "评审否决，机器修复不得从 false 改为 true"
                    )
            required_findings = set(_nonmechanical_review_findings(raw_assessment))
            candidate_findings = {
                finding
                for finding in candidate_assessment.critical_findings
                if not _invalid_scope_sentences((finding,))
            }
            exact_required = {
                finding for finding in required_findings if _finding_is_already_chinese(finding)
            }
            removed = sorted(exact_required - candidate_findings)
            if removed:
                findings.append(
                    f"方向{direction_index}的机器修复删除了既有中文科学否决理由：" f"{removed}"
                )
            if len(candidate_findings) < len(required_findings):
                findings.append(
                    f"方向{direction_index}的机器修复减少了非机械 critical finding；"
                    "非中文理由可翻译，但不得删除"
                )
            prior_rejected = any(
                raw_assessment.get(field_name) is False
                for field_name in _DIRECTION_REVIEW_GATE_FIELDS
            ) or bool(required_findings)
            if prior_rejected and candidate_assessment.qualifies():
                findings.append(
                    f"方向{direction_index}已被第{repair_index}份评审拒绝，"
                    "同一 JSON 修复不得改成通过"
                )
    return tuple(dict.fromkeys(findings))


def _nonmechanical_prosecution_items(
    payload: Mapping[str, Any],
    field_name: str,
) -> tuple[str, ...]:
    return tuple(
        finding
        for finding in _raw_string_items(payload, field_name)
        if not _invalid_scope_sentences((finding,))
    )


def _raw_prosecution_scientific_feedback(
    payload: Mapping[str, Any],
) -> tuple[str, ...]:
    feedback = [
        f"反方既有 false 科学门禁：{field_name}"
        for field_name in _PROSECUTION_GATE_FIELDS
        if payload.get(field_name) is False
    ]
    feedback.extend(
        f"反方既有科学否决：{finding}"
        for field_name in ("critical_findings", "required_revisions")
        for finding in _nonmechanical_prosecution_items(payload, field_name)
    )
    if payload.get("survives_adversarial_review") is False:
        feedback.append("反方既有最终判定：survives_adversarial_review=false")
    return tuple(dict.fromkeys(feedback))


def _prosecution_repair_monotonic_findings(
    *,
    prior_prosecutions: Sequence[Mapping[str, Any]],
    candidate: SelectedDirectionProsecution,
) -> tuple[str, ...]:
    """Forbid one prosecution JSON repair from reversing a prior veto."""

    findings: list[str] = []
    for repair_index, prior in enumerate(prior_prosecutions, 1):
        if (
            prior.get("survives_adversarial_review") is False
            and candidate.survives_adversarial_review
        ):
            findings.append(
                f"第{repair_index}份待修反方审查已判 survives_adversarial_review="
                "false，机器修复不得改成 true"
            )
        for field_name in _PROSECUTION_GATE_FIELDS:
            if prior.get(field_name) is False and getattr(candidate, field_name):
                findings.append(
                    f"反方门禁 {field_name} 已被第{repair_index}份审查否决，"
                    "机器修复不得从 false 改为 true"
                )
        for field_name, candidate_items in (
            ("critical_findings", candidate.critical_findings),
            ("required_revisions", candidate.required_revisions),
        ):
            required_items = set(_nonmechanical_prosecution_items(prior, field_name))
            current_items = {
                finding for finding in candidate_items if not _invalid_scope_sentences((finding,))
            }
            exact_required = {
                finding for finding in required_items if _finding_is_already_chinese(finding)
            }
            removed = sorted(exact_required - current_items)
            if removed:
                findings.append(f"反方机器修复删除了既有中文 {field_name}：{removed}")
            if len(current_items) < len(required_items):
                findings.append(
                    f"反方机器修复减少了非机械 {field_name}；" "非中文理由可翻译，但不得删除"
                )
    return tuple(dict.fromkeys(findings))


def _decision_scope_findings(
    decision: ResearchDirectionDecision,
) -> tuple[str, ...]:
    findings: list[str] = []
    for assessment in decision.assessments:
        invalid = _invalid_scope_sentences(assessment.critical_findings)
        if invalid:
            findings.append(
                f"方向{assessment.direction_index}错把合成 sentinel 契约用于否决"
                "正式开发方向；删除对应整句，仅用 official development cell 的"
                " 300 秒/4096 MB 预算评估方向可行性。内部确定性计算或多阶段优化"
                "仍可封装在一次公开 fit 调用内，不能据此臆造多次 fit 调用。"
            )
    return tuple(findings)


def _prosecution_scope_findings(
    prosecution: SelectedDirectionProsecution,
) -> tuple[str, ...]:
    invalid = _invalid_scope_sentences(
        (*prosecution.critical_findings, *prosecution.required_revisions)
    )
    if not invalid:
        return ()
    return (
        "反方审查错把合成 sentinel 契约用于否决正式开发方向；删除对应整句，"
        "仅用 official development cell 的 300 秒/4096 MB 预算评估可行性，"
        "且不得把一次公开 fit 内的内部阶段臆算为多次 fit 调用。",
    )


def _literature_identity_map(
    *,
    literature: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Join selected-reference positions to the one full-catalog identity domain.

    Opportunity workers use a compact one-based selected-reference position, while
    ideation novelty checks use a one-based full-catalog reference index.  Keeping
    those integers implicit caused the same number to name two different papers in
    the v30 live lineage.  This map makes the translation explicit and hash-bound.
    """

    catalog_by_retrieval_index: dict[int, tuple[int, Mapping[str, Any]]] = {}
    for reference_index, item in enumerate(retrieved_catalog, 1):
        retrieval_index = item.get("retrieval_index")
        if (
            not isinstance(retrieval_index, int)
            or isinstance(retrieval_index, bool)
            or retrieval_index in catalog_by_retrieval_index
        ):
            raise SystemPlanIdeationError("完整检索目录的 retrieval_index 必须为唯一整数")
        catalog_by_retrieval_index[retrieval_index] = (reference_index, item)

    identities: list[dict[str, Any]] = []
    seen_retrieval_indices: set[int] = set()
    for selected_reference_index, selected in enumerate(literature, 1):
        retrieval_index = selected.get("retrieval_index")
        if (
            not isinstance(retrieval_index, int)
            or isinstance(retrieval_index, bool)
            or retrieval_index in seen_retrieval_indices
            or retrieval_index not in catalog_by_retrieval_index
        ):
            raise SystemPlanIdeationError("入选文献的 retrieval_index 重复或不在完整检索目录中")
        reference_index, source = catalog_by_retrieval_index[retrieval_index]
        for field_name in ("title", "doi", "url"):
            if selected.get(field_name) != source.get(field_name):
                raise SystemPlanIdeationError(
                    f"入选文献 {selected_reference_index} 的 {field_name} "
                    "与完整检索目录身份不一致"
                )
        seen_retrieval_indices.add(retrieval_index)
        identities.append(
            {
                "selected_reference_index": selected_reference_index,
                "retrieval_index": retrieval_index,
                "retrieved_catalog_reference_index": reference_index,
                "source_record_hash": canonical_model_hash(dict(source)),
                "title": source.get("title"),
            }
        )
    return tuple(identities)


def _selected_literature_payload(
    literature: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    identities = _literature_identity_map(
        literature=literature,
        retrieved_catalog=retrieved_catalog,
    )
    return [
        {
            **identity,
            "authors": list(item.get("authors") or [])[:6],
            "venue": item.get("venue"),
            "publication_date": item.get("publication_date"),
            "doi": item.get("doi"),
            "url": item.get("url"),
            "relevance_to_plan": item.get("relevance_to_plan"),
        }
        for identity, item in zip(identities, literature, strict=True)
    ]


def _method_skill_context_message(
    selection: SystemPlanMethodSkillSelectionBinding,
) -> dict[str, str]:
    """Materialize selected project skills as a separate hash-bound message."""

    return {
        "role": "user",
        "content": json.dumps(
            {
                "context_kind": "system_selected_project_method_skills",
                "selection_artifact_hash": selection.selection_artifact_hash,
                "system_authored_skill_selection": (selection.selection.model_dump(mode="json")),
                "selected_method_skills": [
                    item.model_dump(mode="json") for item in selection.selected_skills
                ],
                "use_boundary": ("技能只约束推理方法，不是事实、文献、假设、计划或实验结果。"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def _adaptive_creativity_context_message(*, rejected_count: int) -> dict[str, str]:
    """Add a generic escape strategy after scientific vetoes, outside the system prompt.

    This is research methodology rather than a hypothesis: it never names a target
    system, result direction, threshold, or preferred atom.  Qwen must still invent
    and defend the concrete scientific content from the frozen evidence.
    """

    return {
        "role": "user",
        "content": json.dumps(
            {
                "context_kind": "adaptive_creativity_methodology",
                "trigger": (
                    "prior_scientific_vetoes"
                    if rejected_count
                    else "initial_portfolio_search"
                ),
                "rejected_direction_count": rejected_count,
                "method_boundary": (
                    "这是发散方法，不是事实、假设、创新主张、实验结果或指定答案。"
                ),
                "workflow_zh": [
                    "若冻结干预本身是成熟方法，不得再把组件替换或性能提升写成创新；"
                    "只能把该干预当作实验探针。",
                    "从冻结证据中自主寻找可测量且可预注册的调节量，并提出跨至少三个"
                    "独立系统成立的失效边界、方向翻转边界、机制相变或反例；不得从"
                    "系统名称猜测调节量。",
                    "决定性实验仍须保持唯一组件干预；调节量只能来自冻结条件或揭盲前"
                    "固定的有限敏感性设计，禁止开放式调参。",
                    "创新主张必须落在可推广的边界规律或反例，而不是成熟算法名称；"
                    "若当前证据无法定义可测调节量，应主动放弃该方向。",
                    "逐篇说明最近工作是否已经研究同一边界规律，并预注册支持、反驳和"
                    "无法判定三种结果。",
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def _method_skill_selection_from_receipt(
    receipt: ModelAuthorshipReceipt,
) -> SystemPlanMethodSkillSelectionBinding | None:
    """Recover and validate the distinct method-skill message from a receipt."""

    selections: list[SystemPlanMethodSkillSelectionBinding] = []
    for message in receipt.messages:
        try:
            payload = json.loads(message.get("content", ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, Mapping) or payload.get("context_kind") != (
            "system_selected_project_method_skills"
        ):
            continue
        try:
            selection = SystemPlanMethodSkillSelectionBinding.model_validate(
                {
                    "selection_artifact_hash": payload["selection_artifact_hash"],
                    "selection": payload["system_authored_skill_selection"],
                    "selected_skills": payload["selected_method_skills"],
                }
            )
        except (KeyError, TypeError, ValidationError, ValueError, RuntimeError) as exc:
            raise SystemPlanIdeationError("回执中的方法技能绑定无效") from exc
        if dict(message) != _method_skill_context_message(selection):
            raise SystemPlanIdeationError("回执中的方法技能消息角色、边界或规范字节不一致")
        for skill in selection.selected_skills:
            actual_hash = hashlib.sha256(skill.content.encode("utf-8")).hexdigest()
            if actual_hash != skill.content_sha256:
                raise SystemPlanIdeationError(f"回执中的方法技能内容哈希不符：{skill.skill_id}")
        selections.append(selection)
    if not selections:
        return None
    if len(selections) != 1:
        raise SystemPlanIdeationError("同一回执包含重复的方法技能绑定")
    return selections[0]


def _shared_receipt_method_skill_selection(
    *,
    portfolio_receipt: ModelAuthorshipReceipt,
    review_receipt: ModelAuthorshipReceipt,
) -> SystemPlanMethodSkillSelectionBinding | None:
    portfolio_selection = _method_skill_selection_from_receipt(portfolio_receipt)
    review_selection = _method_skill_selection_from_receipt(review_receipt)
    if portfolio_selection != review_selection:
        raise SystemPlanIdeationError("方向作者与评审回执的方法技能绑定不一致")
    if portfolio_selection is not None:
        for label, receipt in (
            ("方向作者", portfolio_receipt),
            ("方向评审", review_receipt),
        ):
            if not str(receipt.reasoning_content or "").strip():
                raise SystemPlanIdeationError(
                    f"{label}回执缺少非空 Qwen reasoning_content"
                )
    return portfolio_selection


def _method_aware_messages(
    *,
    instruction: str,
    payload: Mapping[str, Any],
    opportunity_map: ResearchOpportunityMapBinding,
    adaptive_creativity_rejected_count: int | None = None,
) -> list[dict[str, str]]:
    """Keep full project skills separate from the stage's core machine prompt."""

    messages = [{"role": "system", "content": instruction}]
    selection = opportunity_map.method_skill_selection
    if selection is not None:
        messages.append(_method_skill_context_message(selection))
    if adaptive_creativity_rejected_count is not None:
        messages.append(
            _adaptive_creativity_context_message(
                rejected_count=adaptive_creativity_rejected_count
            )
        )
    messages.append(
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        }
    )
    return messages


def _orchestrator_feedback_trace(
    *,
    stage: str,
    prior_feedback: Sequence[str],
    previous_output: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Bind repair feedback into the model-visible task payload.

    The exact retained prompt must be reconstructable without trusting free-form
    text appended to a receipt.  A missing trace means that no feedback was
    supplied.  When feedback exists, its stage, ordered strings, and the previous
    model output (if any) are all hash-bound so the official loader can rebuild the
    complete system/skill/user message sequence and require byte-for-byte equality.
    """

    feedback = tuple(str(item) for item in prior_feedback)
    if not feedback:
        return None
    if any(not item.strip() for item in feedback):
        raise SystemPlanIdeationError("编排器反馈不得包含空字符串")
    previous_output_hash = (
        canonical_model_hash(dict(previous_output))
        if previous_output is not None
        else None
    )
    binding = {
        "stage": stage,
        "feedback": list(feedback),
        "previous_output_hash": previous_output_hash,
    }
    return {
        "schema_version": "system-plan-ideation-feedback-trace-v1",
        **binding,
        "trace_hash": canonical_model_hash(binding),
    }


def _feedback_from_task_payload(
    *,
    payload: Mapping[str, Any],
    stage: str,
    previous_output_field: str,
) -> tuple[str, ...]:
    """Validate and recover the bounded feedback used to build one prompt."""

    raw_trace = payload.get("orchestrator_feedback_trace")
    previous_output = payload.get(previous_output_field)
    if raw_trace is None:
        if previous_output is not None:
            raise SystemPlanIdeationError(
                "存在待修模型输出时必须同时保存编排器反馈轨迹"
            )
        return ()
    if not isinstance(raw_trace, Mapping):
        raise SystemPlanIdeationError("编排器反馈轨迹必须为对象")
    feedback_value = raw_trace.get("feedback")
    if not isinstance(feedback_value, list) or not feedback_value:
        raise SystemPlanIdeationError("编排器反馈轨迹必须包含非空有序列表")
    if any(not isinstance(item, str) or not item.strip() for item in feedback_value):
        raise SystemPlanIdeationError("编排器反馈轨迹含空值或非字符串")
    if previous_output is not None and not isinstance(previous_output, Mapping):
        raise SystemPlanIdeationError("待修模型输出必须为对象")
    expected_previous_hash = (
        canonical_model_hash(dict(previous_output))
        if isinstance(previous_output, Mapping)
        else None
    )
    binding = {
        "stage": stage,
        "feedback": list(feedback_value),
        "previous_output_hash": expected_previous_hash,
    }
    if (
        raw_trace.get("schema_version")
        != "system-plan-ideation-feedback-trace-v1"
        or raw_trace.get("stage") != stage
        or raw_trace.get("previous_output_hash") != expected_previous_hash
        or raw_trace.get("trace_hash") != canonical_model_hash(binding)
        or set(raw_trace) != {
            "schema_version",
            "stage",
            "feedback",
            "previous_output_hash",
            "trace_hash",
        }
    ):
        raise SystemPlanIdeationError("编排器反馈轨迹与待修输出或阶段不一致")
    return tuple(feedback_value)


def _portfolio_messages(
    *,
    frozen_evidence_context: Mapping[str, Any],
    opportunity_map: ResearchOpportunityMapBinding,
    component_experiment_binding: ComponentExperimentBindingV2,
    literature: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
    prior_portfolio: Mapping[str, Any] | None,
    prior_feedback: Sequence[str],
    retained_receipt_hashes: Mapping[str, str] | None = None,
    rejected_direction_summaries: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, str]]:
    accepted_cell_count = len(opportunity_map.accepted_cells)
    target_whitelist = {
        item.cell_id: list(item.eligible_target_systems) for item in opportunity_map.accepted_cells
    }
    literature_identities = _literature_identity_map(
        literature=literature,
        retrieved_catalog=retrieved_catalog,
    )
    selected_to_retrieved_reference = {
        int(item["selected_reference_index"]): int(item["retrieved_catalog_reference_index"])
        for item in literature_identities
    }
    prospective_allowlist = _prospective_direction_allowlist(
        component_experiment_binding=component_experiment_binding,
        selected_to_retrieved_reference=selected_to_retrieved_reference,
    )
    opportunity_assignment_rule = (
        "五个方向必须分别绑定五个不同的 accepted_cells。"
        if accepted_cell_count >= _DIRECTION_COUNT
        else (
            "accepted_cells 少于五格；五个方向必须覆盖全部 accepted_cells，允许重复绑定，"
            "但即使绑定同一机会格，也必须提出不同的可操纵机制、替代解释与决定性实验。"
        )
    )
    reasoning_instruction = (
        "必须在 reasoning_content 中遵循独立消息内已选 SKILL.md 的阶段，先比较证据与"
        "替代解释，再形成候选；程序会拒绝空的 reasoning_content。"
        "reasoning 只用于过程审计，不是科学证据。\n\n"
        if opportunity_map.method_skill_selection is not None
        else ""
    )
    instruction = (
        "你是自主科研系统的发散研究方向生成器。不要写完整研究计划，也不要接受人类给定的"
        "假设；请只依据用户消息中已通过独立审查的研究机会、冻结原始证据与真实检索文献，"
        "自主产生五个相互独立的"
        "候选研究方向。所有科研散文必须为简体中文，代码标识和原始论文题名可保留英文。\n\n"
        + reasoning_instruction
        + "五个方向必须分别采用 lens=假设反转、机制替代、跨域类比、矛盾消解、尺度转换。"
        "每个方向必须填写 opportunity_cell_id，但机会格只作为未解决问题的动机，不是"
        "处理变量或历史组件身份。"
        + opportunity_assignment_rule
        + "每个方向只能从 prospective_direction_allowlist 选择一个已经独立审查接受的"
        " prospective_atom_id。只返回这个科研选择，不要返回 schema_version、hash、origin、"
        "target_systems、evidence_fact_ids 或 nearest_work_indices；编排器会根据所选 atom "
        "从冻结 allowlist 原样投影这些机械字段，未知 atom 会直接失败。不得选 "
        "observed_components 中的 A 编号。完整 atom 与 intervention identity 已在用户消息中"
        "哈希绑定。不得使用可行性边界中的 excluded_systems。不得从系统名称"
        "推断方程、系数符号、周期性、混沌性、Lyapunov"
        "性质、边界条件或物理机制。nearest_work_indices 已由系统通过"
        " selected_to_retrieved_literature_identity_map 从入选文献顺序精确换域为完整"
        "检索目录 reference_index；绝不能把两个编号域中的同一个整数当成同一篇论文。"
        "视角只是创造过程，不是科学答案。每个方向必须提出不同的因果机制、可反驳假设和"
        "决定性实验；不得只是把现有库、优化器、交叉验证、滤波器或集成器换一种组合。"
        "若所谓差异只是参数调优、实现提速、已有 API 拼接或给已知方法改名，应主动抛弃。\n\n"
        "创新构造硬规则：prospective atom 只冻结一个可操纵的实验探针，本身绝不自动构成"
        "创新。不得把『方法甲替代方法乙』『把成熟方法用于本基准』『误差更低』作为题目、"
        "科学缺口或核心贡献。每个方向必须由模型自主提出一个可跨至少三个独立系统检验的"
        "失效边界、效应方向翻转、机制相变或反例；必须给出来自冻结证据的可测调节量，"
        "并说明正、负和无法判定三种结果。若当前证据无法定义这种调节量，应放弃该 atom，"
        "不得虚构条件数、相关系数、维度或阈值。五个方向中任一个仍以成熟组件替换本身为"
        "创新，整组都应视为无效并重新发散。\n\n"
        "必须分别填写 alternative_explanation、negative_control、sensitivity_control、"
        "orthogonal_diagnostic、independent_analysis_unit 和 result_blind_decision_rule。"
        "决定性实验必须能区分目标机制与至少一个替代解释；负对照检查特异性，"
        "敏感性对照检查"
        "检验确实有能力发现预注册变化，正交诊断必须使用不同观测或分析路径。独立分析单位"
        "不得把同一轨迹内相关时间点或空间格点伪装成独立样本；结果盲规则必须在看到新实验"
        "结果前写明正、负、零三类结果分别反驳或保留什么主张。由于后续预实验只运行所选"
        "prospective atom 机械投影的 target_systems，independent_analysis_unit 不得写入"
        "这些 target_systems 之外的机器系统标识；负对照必须使用目标系统内的冻结条件或"
        "配置对照，若只作概念性外部对照则不得声称本轮会执行，也不要写进分析单位。"
        "不能事后调阈值。"
        "failure_modes 中每一项都必须同时说明预注册诊断、对结论的影响和预算内的有界控制；"
        "只承认弱点却不给可解释的检验与控制，等于方案不完整。科学假设可能被推翻不是缺陷，"
        "但无论得到正、负还是零结果都无法区分机制，就是致命设计缺陷。\n\n"
        "先把用户消息中的完整 retrieved_prior_work_catalog 当作负向新颖性检索空间，主动"
        "淘汰其中已经出现的机制、成熟算法迁移和等价组件组合。每个方向必须用 "
        "prospective atom 逐字给定的 nearest_work_indices 声明作者采用的直接支持文献；"
        "独立评审仍必须对照完整检索目录中至少三篇编号互不相同的真实文献，明确实质"
        "差异和剩余风险，不得虚构文献。"
        "method_tokens 必须是2到8个互异的单词式 ASCII 标识符。"
        "每个 token 必须逐字匹配 ^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*$，"
        "长度为二至三十二字符：允许 ir、tv、sde 和 snake_case 等科学标识，但严禁"
        "单字符、连续或首尾下划线、连字符、"
        "空格和短语。请把方法拆成可在 Python 函数名中核验的独立术语，例如必须写成 "
        '["chebyshev", "galerkin", "modal"]，绝不能写成 '
        '["chebyshev_projection", "spectral_galerkin"]。'
        "五个方向的方法 token 集合不得高度重合。不得声称尚未执行的结果已经发生。"
        "必须在冻结数据、接口、资源和审批边界内可测试。只返回严格 JSON："
        + json.dumps(
            _portfolio_response_schema(),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    instruction += (
        "\n\n预算 scope 硬规则：maximum_fit_seconds_per_sentinel、合成精度阈值和"
        " 20 秒/512 MB 仅用于小型 synthetic sentinel 接口门；本阶段正式公开开发格"
        "使用 maximum_seconds_per_cell=300 与 maximum_memory_mb_per_cell=4096（即"
        " 300 秒/4096 MB）。"
        "fit_call_count 表示公开 estimator.fit 接口的调用次数；一次 fit 内部的确定性统计、"
        "多阶段优化或求解步骤不自动构成多次 fit 调用。不得据此虚构预算冲突。任何变量"
        "变换或干预必须说明如何保持动力系统生成关系、物理单位和方程可逆回映射；任意常数"
        "不得来自反复试探已知失败系统。"
        "profile_effect_association 仅是未做多重比较校正的探索性关联，并明确总体数据类型"
        "混杂未排除；若引用它，必须核对 within_data_type_associations，且把新预注册对照"
        "实验作为因果识别来源，绝不能把相关系数本身写成已证实机制。"
    )
    instruction += (
        "\n\nE125、cross_lineage_effect_matrix 或历史候选差异的 jointly confounded"
        " 标记，只能说明历史观察不能归因到单一组件，并构成提出问题的动机；不得据此"
        "否决 prospective_direction_allowlist 中已经冻结全部其余维度的未来单因素对照。"
        "只有候选没有逐字继承 prospective atom、处理与对照实际同时改变其他组件、或"
        "frozen_dimensions 未保持时，才可判定该前瞻实验不可识别。"
    )
    if prior_feedback:
        instruction += (
            "\n\n你上一份系统输出未获接受，用户消息包含你自己的原文。若精确反馈仅涉及"
            "缺字段、JSON 形状、语言或 method_tokens 语法，必须保留科研判断，只修复机器"
            "契约；若反馈来自科学评审，则不要修饰或重组被判为不新颖的组件，必须从五种"
            "发散视角重新开辟不同机制。唯一例外是：某方向九个布尔门均已通过，仅有明确且"
            "可通过新增正交诊断或负对照消除的 critical finding；此时可以保留核心机制，但"
            "必须在决定性实验和 failure_modes 中逐条实质解决，不能只删除或改写批评。"
            "精确反馈：" + json.dumps(list(prior_feedback), ensure_ascii=False)
        )
    if rejected_direction_summaries:
        instruction += (
            "\n\n用户消息中的 mechanically_forbidden_rejected_directions 是从"
            "哈希有效模型回执机械提取的禁用清单。不得复用其中被否决的科学主张、"
            "核心机制，不得只换标题、阈值或近邻引用。method_tokens 只是识别方法族的"
            "线索，不是禁用词表；若冻结 allowlist"
            " 迫使你再次使用同一成熟干预，只能把它当作探针，自主研究尚未解决且可推广的"
            "失效边界、方向翻转、机制相变或反例，并明确承认组件本身不是创新；任何新方向"
            "的科学签名都不得与清单重复。清单不提供新假设。"
        )
    payload: dict[str, Any] = {
        "frozen_evidence_context_hash": canonical_model_hash(dict(frozen_evidence_context)),
        "independently_accepted_research_opportunities": [
            item.model_dump(mode="json") for item in opportunity_map.accepted_cells
        ],
        "research_opportunity_map_hash": opportunity_map.opportunity_map_hash,
        "opportunity_motivation_targets_by_cell": target_whitelist,
        "component_experiment_binding": component_experiment_binding.model_dump(mode="json"),
        "component_experiment_binding_hash": component_experiment_binding.binding_hash,
        "prospective_direction_allowlist": prospective_allowlist,
        "frozen_feasibility_envelope": _ideation_feasibility_projection(
            opportunity_map=opportunity_map,
            component_experiment_binding=component_experiment_binding,
        ),
        "selected_literature_for_plan_citations": _selected_literature_payload(
            literature,
            retrieved_catalog,
        ),
        "selected_to_retrieved_literature_identity_map": list(
            _literature_identity_map(
                literature=literature,
                retrieved_catalog=retrieved_catalog,
            )
        ),
        "retrieved_prior_work_catalog": _catalog_payload_for_portfolio(retrieved_catalog),
    }
    if prior_portfolio is not None:
        payload["previous_system_authored_portfolio"] = dict(prior_portfolio)
        payload["mechanical_repair_patch"] = {
            "errors": list(prior_feedback),
            "preserve_all_unmentioned_scientific_fields_verbatim": True,
            "may_change_scientific_judgment": False,
        }
    feedback_trace = _orchestrator_feedback_trace(
        stage="portfolio",
        prior_feedback=prior_feedback,
        previous_output=prior_portfolio,
    )
    if feedback_trace is not None:
        payload["orchestrator_feedback_trace"] = feedback_trace
    if retained_receipt_hashes is not None:
        payload["retained_model_receipt_hashes"] = dict(retained_receipt_hashes)
    if rejected_direction_summaries:
        payload["mechanically_forbidden_rejected_directions"] = [
            dict(item) for item in rejected_direction_summaries
        ]
    return _method_aware_messages(
        instruction=instruction,
        payload=payload,
        opportunity_map=opportunity_map,
        adaptive_creativity_rejected_count=len(rejected_direction_summaries),
    )


def _review_messages(
    *,
    portfolio: ResearchDirectionPortfolio,
    opportunity_map: ResearchOpportunityMapBinding,
    component_experiment_binding: ComponentExperimentBindingV2,
    literature: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
    previous_review: Mapping[str, Any] | None = None,
    prior_feedback: Sequence[str] = (),
) -> list[dict[str, str]]:
    catalog = _catalog_payload_for_review(retrieved_catalog)
    reasoning_instruction = (
        "必须在 reasoning_content 中逐方向应用独立消息内已选 SKILL.md 的否决条件；"
        "程序会拒绝空的 reasoning_content。reasoning 只用于过程审计，"
        "不是科学证据。\n\n"
        if opportunity_map.method_skill_selection is not None
        else ""
    )
    instruction = (
        "语言硬门禁：selection_rationale、critical_findings 以及每一条文献比较的 overlap、"
        "difference、residual_novelty_risk 必须全部用简体中文书写；论文原题和代码标识符"
        "可保留原文。任何整句英文都会使本次评审作废。\n\n"
        + reasoning_instruction
        + "你是独立的科研方向淘汰评审器，只评审，不替作者写新方向。对五个候选逐一用最"
        "严标准检查：机制是否符合科学原理；假设和实验是否可证伪且能识别该机制；是否在"
        "冻结接口与资源内可执行；相对真实检索近邻是否有实质新颖性；是否超越已有组件拼接。"
        "还必须检查它是否会产生可推广到本仓库、本评估器和字段契约之外的新科学或方法学知识。"
        "只修复字段名、字符串等价、日志、超时、内存、接口契约或本地评分器行为的方向，不论"
        "成功率提升多少，都不是可发表科研方向。每个方向必须对照至少三条 "
        "reference_index 互不相同的 retrieved_catalog。"
        "逐项核对 evidence_fact_ids 是否真的支撑方向，不得从系统名补写未观测的方程、系数"
        "符号、周期性、混沌性或其他属性。还要检查具体替代解释、负对照、敏感性对照、正交"
        "诊断、独立分析单位与结果盲规则是否共同排除伪重复、数据类型混杂、后验挑选和无效"
        "检验；探索性 profile_effect_association 的总体相关不能越权作为因果证据。"
        "任何一项失败或存在 critical_findings，"
        "该方向都不合格。不得为了必须选一个而放宽；可以五个全部拒绝。若存在全门禁合格"
        "方向，选择其中科学差异最清楚且最小决定性实验可执行者。所有评审散文用简体中文。"
        "critical finding 仅指会使结果不可解释、机制不可识别、执行越界或创新主张被先前"
        "工作实质覆盖的未解决缺陷。不要把『假设可能被数据推翻』本身列为缺陷：若候选已"
        "预注册正交诊断、对照、失败解释与预算内控制，科学不确定性正是应当实验的问题；"
        "反之，只有风险名称而没有诊断或控制，仍应判为 critical。还必须核对方向是否忠实"
        "绑定一个独立接受的 prospective atom，atom id/hash、intervention hash、origin、"
        "目标、事实和直接支持文献是否逐字等于允许集合，且没有偷偷改变构念、替代解释或"
        "识别逻辑；任何脱钩都属于 critical finding。opportunity_cell_id 只标记问题动机，"
        "不是前瞻干预身份。"
        "本阶段位于真实预实验之前，不得要求作者预先证明处理一定产生非零效应，也不得把"
        "『两臂可能得到相同结果』本身当成否决理由；只要零、正、负三种结果都能按预注册"
        "诊断形成可推广的边界知识，该不确定性应留给预实验裁决。成熟干预可以作为实验探针，"
        "但创新主张必须落在新的可测失效边界、方向翻转、相变或反例，而不能落在成熟干预本身。"
        "多个方向共享同一 prospective atom 或 intervention hash 也不自动构成重复：只有它们"
        "的可操作调节量、核心机制、决定性检验和结果盲判据实质相同，才应以重复否决；若这些"
        "科学构件不同且均由冻结事实或预算内预实验定义，则应分别评审。"
        "critical_findings 只能写未解决且足以否决的缺陷，绝不能写正面评价。九项布尔门全为"
        "true 时该数组必须为空；任一布尔门为 false 时至少写一条对应缺陷。assessments 按"
        "候选原顺序返回，不要返回 direction_index、schema_version 或 portfolio_ready；"
        "编排器会附加稳定位置，并由 selected_direction_index 是否为 null 推导 ready 状态。"
        "五个都不合格时 selected_direction_index 必须为 null。"
        "只返回严格 JSON："
        + json.dumps(
            _review_response_schema(),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    instruction += (
        "\n\n预算 scope 硬规则：不得使用 maximum_fit_seconds_per_sentinel、"
        "合成 sentinel 精度阈值、20 秒/512 MB 或 fit_call_count 原始字段来否决正式"
        "开发方向。正式格按 300 秒/4096 MB 审查；一次公开 fit 内部允许确定性统计和"
        "多阶段求解，它们不等于重复调用 fit。若方向确实要求在同一格重复调用公开 fit，"
        "必须用这一具体事实说明，而不能从内部步骤数量推断。"
    )
    instruction += (
        "\n\nE125、cross_lineage_effect_matrix 或历史候选差异的 jointly confounded"
        " 标记，只能否定对历史联合变化的单组件归因，不能否决未来严格冻结其他组件的"
        "单因素 prospective 对照。只有候选未逐字继承前瞻 atom、对照没有冻结其余维度、"
        "或处理同时改变多个因素时，才可据此将可识别性或对照门判为 false。其他九项"
        "科学门禁不得放宽。"
    )
    if prior_feedback:
        instruction += (
            "\n\n你上一份评审未通过机器校验。保留原有科学判断，只修复语言、结构或引用"
            "编号；不得借修复之名放宽门禁。任何已经为 false 的科学门必须保持 false，"
            "此前未选择或已拒绝的方向不得改成通过，非机械 critical finding 不得删除；"
            "程序会逐字段核对全部待修响应，而不是只相信本轮自述。精确错误："
            + json.dumps(list(prior_feedback), ensure_ascii=False)
        )
    payload = {
        "portfolio": portfolio.model_dump(mode="json"),
        "accepted_research_opportunities": [
            item.model_dump(mode="json") for item in opportunity_map.accepted_cells
        ],
        "research_opportunity_map_hash": opportunity_map.opportunity_map_hash,
        "component_experiment_binding": component_experiment_binding.model_dump(mode="json"),
        "component_experiment_binding_hash": component_experiment_binding.binding_hash,
        "retrieved_catalog": catalog,
        "selected_to_retrieved_literature_identity_map": list(
            _literature_identity_map(
                literature=literature,
                retrieved_catalog=retrieved_catalog,
            )
        ),
        "frozen_feasibility_envelope": _ideation_feasibility_projection(
            opportunity_map=opportunity_map,
            component_experiment_binding=component_experiment_binding,
        ),
    }
    if previous_review is not None:
        payload["previous_system_authored_review"] = dict(previous_review)
    feedback_trace = _orchestrator_feedback_trace(
        stage="review",
        prior_feedback=prior_feedback,
        previous_output=previous_review,
    )
    if feedback_trace is not None:
        payload["orchestrator_feedback_trace"] = feedback_trace
    return _method_aware_messages(
        instruction=instruction,
        payload=payload,
        opportunity_map=opportunity_map,
    )


def _prosecution_messages(
    *,
    selected_direction_index: int,
    selected_direction: ResearchDirectionCandidate,
    decision: ResearchDirectionDecision,
    opportunity_map: ResearchOpportunityMapBinding,
    component_experiment_binding: ComponentExperimentBindingV2,
    literature: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
    previous_prosecution: Mapping[str, Any] | None = None,
    prior_feedback: Sequence[str] = (),
) -> list[dict[str, str]]:
    catalog = _catalog_payload_for_review(retrieved_catalog)

    reasoning_instruction = (
        "必须在 reasoning_content 中按独立消息内已选 SKILL.md 主动寻找反例；程序会拒绝"
        "缺失或为空的 reasoning_content。reasoning 只用于过程审计，不是科学证据。\n\n"
        if opportunity_map.method_skill_selection is not None
        else ""
    )
    instruction = (
        "你是独立于方向作者和五方向初审器的反方科研审查员。只审查已入选方向，只有否决权，"
        "不得替作者补写假设、机制或实验。你的任务是主动寻找一个足以让完整计划失败的反例。"
        "所有评审散文必须为简体中文；论文原题、方法名和代码标识符可保留原文。\n\n"
        + reasoning_instruction
        + "用以下不可加权的硬门禁审查：第一，新构念必须有可操作定义，不得只是把投影残差、"
        "条件数、不确定性、正则化或其他既有量重新命名；第二，目标机制必须能与至少一个具体"
        "替代解释识别开，决定性实验的干预或对照不得破坏原数据生成关系后再冒充机制证据；"
        "第三，evidence_fact_ids 必须逐项支持主张，不得从系统名称猜测方程、系数、周期性、"
        "混沌性或物理性质；探索性总体相关在数据类型混杂未排除时不得用作因果证据；第四，"
        "负对照、敏感性对照与正交诊断必须保持生成语义并能发现失效检验；第五，实验方向性"
        "预测、独立分析单位、阈值来源和停止逻辑必须能够在后续计划中无结果依赖地冻结，不得"
        "依靠任意常数、伪重复或循环选择已知失败案例；第六，冻结数据、系统数、预算、接口和"
        "审批边界足以执行所声称的推断；第七，必须逐项对照至少三篇 reference_index "
        "互不相同的真实目录文献，排除"
        "标准诊断、成熟算法迁移、组件拼接和术语改名；第八，正、负或零结果都必须产生可推广"
        "到本仓库、本评估器和字段契约之外的新科学或方法学知识。字段规范化、字符串等价、"
        "错误处理、超时调度、内存裁剪、日志或评分器适配本身一律不满足第六门。摘要不足时"
        "必须保留新颖性风险，不得猜测。\n\n"
        "方向阶段不要求完整计划的每个实现参数，但核心构念、可识别逻辑或最小决定性实验若"
        "必须到写计划时才能发明，则本方向不合格。任何一个布尔门为 false，或仍有 critical "
        "finding / required revision，最终状态必然为否决。不要返回 schema_version、"
        "selected_direction_index 或 survives_adversarial_review；编排器会绑定当前入选方向，"
        "并从九个科学门、critical_findings 与 required_revisions 的严格合取中推导最终状态。"
        "不得因为五方向初审已经选择它而放宽。只返回严格 JSON："
        + json.dumps(
            _prosecution_response_schema(),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    instruction += (
        "\n\n预算 scope 硬规则：不得用 synthetic sentinel 的 20 秒/512 MB、"
        "合成精度阈值或 fit_call_count 字段否决正式开发方向；正式格使用 300 秒/4096 MB。"
        "一次公开 fit 内部的确定性统计、多阶段优化或求解步骤不自动构成多次 fit 调用。"
    )
    instruction += (
        "\n\nE125、cross_lineage_effect_matrix 或历史候选差异的 jointly confounded"
        " 标记，只能作为问题动机并否定历史联合变化的单组件归因；如果本方向逐字绑定"
        "一个已独立接受的 prospective atom，且处理/对照冻结其他全部组件，就不得仅凭"
        "该历史混杂标记否决未来单因素对照。只有前瞻 atom 未冻结、候选脱离其精确绑定或"
        "干预不纯时，才可判不可识别。其他反方硬门不得放宽。"
    )
    instruction += (
        "\n\n阶段边界硬规则：这是预实验之前的反方审查，不是结果验收。不得要求候选先"
        "提供处理必然非零、两种方法必然选出不同支撑集或方向预测已经成立的结果证据；这些"
        "正是随后真实预实验要检验的对象。若零结果也能依预注册规则定位失效边界，零结果不是"
        "致命缺陷。成熟算法只能作为探针，不能把算法迁移本身写成创新；但围绕该探针提出的"
        "新可测边界、方向翻转、相变或反例可独立形成科学贡献。不得仅因另一个候选共享同一"
        "prospective atom/intervention hash 就判本方向重复；必须证明二者的可操作调节量、"
        "核心机制、决定性检验和结果盲判据实质相同。"
    )
    if prior_feedback:
        instruction += (
            "\n\n你上一份反方审查未通过机器结构、语言或引用校验。必须保留科学判断，只修复"
            "机器契约，绝不能把否决改成通过。任何 false 科学门都必须保持 false，"
            "非机械 critical finding "
            "和 required revision 不得删除；程序会逐字段核对全部待修响应。精确错误："
            + json.dumps(list(prior_feedback), ensure_ascii=False)
        )
    payload: dict[str, Any] = {
        "selected_direction_index": selected_direction_index,
        "selected_direction": selected_direction.model_dump(mode="json"),
        "tournament_decision": decision.model_dump(mode="json"),
        "accepted_research_opportunities": [
            item.model_dump(mode="json") for item in opportunity_map.accepted_cells
        ],
        "research_opportunity_map_hash": opportunity_map.opportunity_map_hash,
        "component_experiment_binding": component_experiment_binding.model_dump(mode="json"),
        "component_experiment_binding_hash": component_experiment_binding.binding_hash,
        "retrieved_catalog": catalog,
        "selected_to_retrieved_literature_identity_map": list(
            _literature_identity_map(
                literature=literature,
                retrieved_catalog=retrieved_catalog,
            )
        ),
        "frozen_feasibility_envelope": _ideation_feasibility_projection(
            opportunity_map=opportunity_map,
            component_experiment_binding=component_experiment_binding,
        ),
    }
    if previous_prosecution is not None:
        payload["previous_system_authored_prosecution"] = dict(previous_prosecution)
    feedback_trace = _orchestrator_feedback_trace(
        stage="prosecution",
        prior_feedback=prior_feedback,
        previous_output=previous_prosecution,
    )
    if feedback_trace is not None:
        payload["orchestrator_feedback_trace"] = feedback_trace
    return _method_aware_messages(
        instruction=instruction,
        payload=payload,
        opportunity_map=opportunity_map,
    )


def _retained_task_payload(
    *,
    messages: Sequence[Mapping[str, str]],
    opportunity_map: ResearchOpportunityMapBinding,
) -> dict[str, Any]:
    """Extract the sole task payload after enforcing the canonical role topology."""

    normalized = [dict(message) for message in messages]
    if (
        len(normalized) < 2
        or normalized[0].get("role") != "system"
        or any(message.get("role") != "user" for message in normalized[1:])
    ):
        raise SystemPlanIdeationError(
            "方向阶段模型回执消息数量、顺序或角色不符合唯一规范"
        )
    if any(set(message) != {"role", "content"} for message in normalized):
        raise SystemPlanIdeationError("方向阶段模型回执消息含未授权字段")
    intermediate_context_kinds: list[str] = []
    for message in normalized[1:-1]:
        try:
            intermediate = json.loads(message["content"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SystemPlanIdeationError("方向阶段上下文消息不是规范 JSON 对象") from exc
        if not isinstance(intermediate, dict):
            raise SystemPlanIdeationError("方向阶段上下文消息必须为 JSON 对象")
        intermediate_context_kinds.append(str(intermediate.get("context_kind") or ""))
    expected_prefix = (
        ["system_selected_project_method_skills"]
        if opportunity_map.method_skill_selection is not None
        else []
    )
    allowed_context_kinds = (
        expected_prefix,
        [*expected_prefix, "adaptive_creativity_methodology"],
    )
    if intermediate_context_kinds not in allowed_context_kinds:
        raise SystemPlanIdeationError(
            "方向阶段上下文消息数量、顺序或类型不符合唯一规范"
        )
    try:
        payload = json.loads(normalized[-1]["content"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SystemPlanIdeationError("方向阶段任务消息不是规范 JSON 对象") from exc
    if not isinstance(payload, dict):
        raise SystemPlanIdeationError("方向阶段任务消息必须为 JSON 对象")
    return payload


def _require_exact_retained_messages(
    *,
    retained_messages: Sequence[Mapping[str, str]],
    expected_messages: Sequence[Mapping[str, str]],
    stage: str,
) -> list[dict[str, str]]:
    normalized = [dict(message) for message in retained_messages]
    expected = [dict(message) for message in expected_messages]
    if normalized != expected:
        raise SystemPlanIdeationError(
            f"retained {stage} 回执并非编排器根据冻结输入生成的完整精确消息"
        )
    return expected


def _rebuild_exact_portfolio_messages(
    *,
    retained_messages: Sequence[Mapping[str, str]],
    frozen_evidence_context: Mapping[str, Any],
    opportunity_map: ResearchOpportunityMapBinding,
    component_experiment_binding: ComponentExperimentBindingV2,
    literature: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Rebuild and compare the complete accepted portfolio prompt."""

    payload = _retained_task_payload(
        messages=retained_messages,
        opportunity_map=opportunity_map,
    )
    raw_previous = payload.get("previous_system_authored_portfolio")
    if raw_previous is not None and not isinstance(raw_previous, Mapping):
        raise SystemPlanIdeationError("待修方向组合必须为对象")
    previous = dict(raw_previous) if isinstance(raw_previous, Mapping) else None
    feedback = _feedback_from_task_payload(
        payload=payload,
        stage="portfolio",
        previous_output_field="previous_system_authored_portfolio",
    )
    raw_receipt_hashes = payload.get("retained_model_receipt_hashes")
    if raw_receipt_hashes is not None and not isinstance(
        raw_receipt_hashes, Mapping
    ):
        raise SystemPlanIdeationError("保留模型回执哈希必须为对象")
    retained_hashes = (
        {str(key): str(value) for key, value in raw_receipt_hashes.items()}
        if isinstance(raw_receipt_hashes, Mapping)
        else None
    )
    raw_rejected = payload.get("mechanically_forbidden_rejected_directions", [])
    if not isinstance(raw_rejected, list) or any(
        not isinstance(item, Mapping) for item in raw_rejected
    ):
        raise SystemPlanIdeationError("已否决方向清单必须为对象数组")
    expected = _portfolio_messages(
        frozen_evidence_context=frozen_evidence_context,
        opportunity_map=opportunity_map,
        component_experiment_binding=component_experiment_binding,
        literature=literature,
        retrieved_catalog=retrieved_catalog,
        prior_portfolio=previous,
        prior_feedback=feedback,
        retained_receipt_hashes=retained_hashes,
        rejected_direction_summaries=tuple(dict(item) for item in raw_rejected),
    )
    return _require_exact_retained_messages(
        retained_messages=retained_messages,
        expected_messages=expected,
        stage="portfolio",
    )


def _rebuild_exact_review_messages(
    *,
    retained_messages: Sequence[Mapping[str, str]],
    portfolio: ResearchDirectionPortfolio,
    opportunity_map: ResearchOpportunityMapBinding,
    component_experiment_binding: ComponentExperimentBindingV2,
    literature: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Rebuild and compare the complete accepted independent-review prompt."""

    payload = _retained_task_payload(
        messages=retained_messages,
        opportunity_map=opportunity_map,
    )
    raw_previous = payload.get("previous_system_authored_review")
    if raw_previous is not None and not isinstance(raw_previous, Mapping):
        raise SystemPlanIdeationError("待修方向评审必须为对象")
    previous = dict(raw_previous) if isinstance(raw_previous, Mapping) else None
    feedback = _feedback_from_task_payload(
        payload=payload,
        stage="review",
        previous_output_field="previous_system_authored_review",
    )
    expected = _review_messages(
        portfolio=portfolio,
        opportunity_map=opportunity_map,
        component_experiment_binding=component_experiment_binding,
        literature=literature,
        retrieved_catalog=retrieved_catalog,
        previous_review=previous,
        prior_feedback=feedback,
    )
    return _require_exact_retained_messages(
        retained_messages=retained_messages,
        expected_messages=expected,
        stage="review",
    )


def _rebuild_exact_prosecution_messages(
    *,
    retained_messages: Sequence[Mapping[str, str]],
    selected_direction_index: int,
    selected_direction: ResearchDirectionCandidate,
    decision: ResearchDirectionDecision,
    opportunity_map: ResearchOpportunityMapBinding,
    component_experiment_binding: ComponentExperimentBindingV2,
    literature: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Rebuild and compare the complete accepted adversarial prompt."""

    payload = _retained_task_payload(
        messages=retained_messages,
        opportunity_map=opportunity_map,
    )
    raw_previous = payload.get("previous_system_authored_prosecution")
    if raw_previous is not None and not isinstance(raw_previous, Mapping):
        raise SystemPlanIdeationError("待修反方审查必须为对象")
    previous = dict(raw_previous) if isinstance(raw_previous, Mapping) else None
    feedback = _feedback_from_task_payload(
        payload=payload,
        stage="prosecution",
        previous_output_field="previous_system_authored_prosecution",
    )
    expected = _prosecution_messages(
        selected_direction_index=selected_direction_index,
        selected_direction=selected_direction,
        decision=decision,
        opportunity_map=opportunity_map,
        component_experiment_binding=component_experiment_binding,
        literature=literature,
        retrieved_catalog=retrieved_catalog,
        previous_prosecution=previous,
        prior_feedback=feedback,
    )
    return _require_exact_retained_messages(
        retained_messages=retained_messages,
        expected_messages=expected,
        stage="prosecution",
    )


def _catalog_payload_for_portfolio(
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "retrieval_index": item.get("retrieval_index"),
            "source_record_hash": canonical_model_hash(dict(item)),
            "title": item.get("title"),
            "publication_date": item.get("publication_date"),
            "doi": item.get("doi"),
            "url": item.get("url"),
            "abstract": str(item.get("abstract") or "")[:1_200],
        }
        for index, item in enumerate(retrieved_catalog, 1)
    ]


def _catalog_payload_for_review(
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            **dict(item),
            "reference_index": index,
            "source_record_hash": canonical_model_hash(dict(item)),
        }
        for index, item in enumerate(retrieved_catalog, 1)
    ]


def _load_rejected_ideation_receipts(
    *,
    portfolio_receipt_path: Path | str,
    review_receipt_path: Path | str,
    frozen_evidence_context: Mapping[str, Any],
    opportunity_map: ResearchOpportunityMapBinding,
    component_experiment_binding: ComponentExperimentBindingV2,
    literature: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> tuple[
    None,
    tuple[str, ...],
    set[str],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    """Resume only from hash-valid, exactly bound, all-rejected model receipts."""

    portfolio_receipt = ModelAuthorshipReceipt.model_validate_json(
        Path(portfolio_receipt_path).read_text(encoding="utf-8")
    )
    review_receipt = ModelAuthorshipReceipt.model_validate_json(
        Path(review_receipt_path).read_text(encoding="utf-8")
    )
    if portfolio_receipt.artifact_kind != "plan_ideation":
        raise SystemPlanIdeationError("续跑作者回执类型不是研究方向组合")
    if review_receipt.artifact_kind != "plan_ideation_review":
        raise SystemPlanIdeationError("续跑评审回执类型不是研究方向评审")
    receipt_method_skill_selection = _shared_receipt_method_skill_selection(
        portfolio_receipt=portfolio_receipt,
        review_receipt=review_receipt,
    )
    if receipt_method_skill_selection != opportunity_map.method_skill_selection:
        raise SystemPlanIdeationError("续跑回执与当前方法技能选择不一致")
    try:
        portfolio_input = json.loads(portfolio_receipt.messages[-1]["content"])
        review_input = json.loads(review_receipt.messages[-1]["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemPlanIdeationError("续跑回执缺少可验证的结构化输入") from exc

    expected_opportunities = [
        item.model_dump(mode="json") for item in opportunity_map.accepted_cells
    ]
    expected_envelope = _ideation_feasibility_projection(
        opportunity_map=opportunity_map,
        component_experiment_binding=component_experiment_binding,
    )
    literature_identities = _literature_identity_map(
        literature=literature,
        retrieved_catalog=retrieved_catalog,
    )
    selected_to_retrieved_reference = {
        int(item["selected_reference_index"]): int(
            item["retrieved_catalog_reference_index"]
        )
        for item in literature_identities
    }
    prospective_allowlist = _prospective_direction_allowlist(
        component_experiment_binding=component_experiment_binding,
        selected_to_retrieved_reference=selected_to_retrieved_reference,
    )
    expected_portfolio_catalog = _catalog_payload_for_portfolio(retrieved_catalog)
    expected_review_catalog = _catalog_payload_for_review(retrieved_catalog)
    if (
        portfolio_input.get("frozen_evidence_context_hash")
        != canonical_model_hash(dict(frozen_evidence_context))
        or portfolio_input.get("independently_accepted_research_opportunities")
        != expected_opportunities
        or portfolio_input.get("research_opportunity_map_hash")
        != opportunity_map.opportunity_map_hash
        or portfolio_input.get("component_experiment_binding")
        != component_experiment_binding.model_dump(mode="json")
        or portfolio_input.get("component_experiment_binding_hash")
        != component_experiment_binding.binding_hash
        or portfolio_input.get("frozen_feasibility_envelope") != expected_envelope
        or portfolio_input.get("selected_literature_for_plan_citations")
        != _selected_literature_payload(literature, retrieved_catalog)
        or portfolio_input.get("selected_to_retrieved_literature_identity_map")
        != list(
            _literature_identity_map(
                literature=literature,
                retrieved_catalog=retrieved_catalog,
            )
        )
        or portfolio_input.get("retrieved_prior_work_catalog") != expected_portfolio_catalog
    ):
        raise SystemPlanIdeationError("续跑方向作者回执与当前冻结证据、机会图或真实文献不一致")

    portfolio = ResearchDirectionPortfolio.model_validate(
        _project_portfolio_payload(
            portfolio_receipt.parsed_payload,
            prospective_allowlist=prospective_allowlist,
        )
    )
    if (
        review_input.get("portfolio") != portfolio.model_dump(mode="json")
        or review_input.get("accepted_research_opportunities") != expected_opportunities
        or review_input.get("research_opportunity_map_hash") != opportunity_map.opportunity_map_hash
        or review_input.get("component_experiment_binding")
        != component_experiment_binding.model_dump(mode="json")
        or review_input.get("component_experiment_binding_hash")
        != component_experiment_binding.binding_hash
        or review_input.get("retrieved_catalog") != expected_review_catalog
        or review_input.get("selected_to_retrieved_literature_identity_map")
        != list(
            _literature_identity_map(
                literature=literature,
                retrieved_catalog=retrieved_catalog,
            )
        )
        or review_input.get("frozen_feasibility_envelope") != expected_envelope
    ):
        raise SystemPlanIdeationError("续跑方向评审回执未绑定对应组合、机会图或真实文献")
    decision = ResearchDirectionDecision.model_validate(
        _project_review_payload(review_receipt.parsed_payload)
    )
    if decision.selected_direction_index is not None:
        raise SystemPlanIdeationError("续跑仅接受独立评审已否决全部方向的回执")

    feedback: list[str] = []
    if not _invalid_scope_sentences((decision.selection_rationale,)):
        feedback.append(decision.selection_rationale)
    for assessment in decision.assessments:
        feedback.extend(
            f"方向{assessment.direction_index}：{finding}"
            for finding in assessment.critical_findings
            if not _invalid_scope_sentences((finding,))
        )
    feedback.extend(_failed_gate_feedback(decision))
    rejected_signatures = {
        _direction_scientific_signature(portfolio.directions[index])
        for index, assessment in enumerate(decision.assessments)
        if not assessment.qualifies()
    }
    rejected_summaries = {
        signature: _rejected_direction_summary(portfolio.directions[index])
        for index, assessment in enumerate(decision.assessments)
        if not assessment.qualifies()
        for signature in (_direction_scientific_signature(portfolio.directions[index]),)
    }
    inherited_summaries = portfolio_input.get("mechanically_forbidden_rejected_directions") or []
    if not isinstance(inherited_summaries, list):
        raise SystemPlanIdeationError("续跑禁用方向清单不是 JSON 数组")
    for raw_summary in inherited_summaries:
        if not isinstance(raw_summary, Mapping):
            raise SystemPlanIdeationError("续跑禁用方向清单包含非对象条目")
        summary = dict(raw_summary)
        signature = str(summary.get("scientific_signature") or "")
        core_hash = str(summary.get("core_mechanism_sha256") or "")
        title = summary.get("title")
        tokens = summary.get("method_tokens")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", signature)
            or not re.fullmatch(r"[0-9a-f]{64}", core_hash)
            or not isinstance(title, str)
            or not title
            or not isinstance(tokens, list)
            or not tokens
            or not all(isinstance(token, str) for token in tokens)
        ):
            raise SystemPlanIdeationError("续跑禁用方向清单条目结构无效")
        existing = rejected_summaries.get(signature)
        if existing is not None and existing != summary:
            raise SystemPlanIdeationError("续跑禁用方向签名对应内容不一致")
        rejected_summaries[signature] = summary
        rejected_signatures.add(signature)
    return (
        None,
        tuple(dict.fromkeys(feedback)),
        rejected_signatures,
        rejected_summaries,
        {
            "rejected_portfolio_receipt_hash": portfolio_receipt.receipt_hash,
            "rejected_review_receipt_hash": review_receipt.receipt_hash,
        },
    )


def run_system_plan_ideation(
    *,
    lineage_id: str,
    frozen_evidence_context: Mapping[str, Any],
    opportunity_map: ResearchOpportunityMapBinding,
    component_experiment_binding: ComponentExperimentBindingV2,
    literature: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    review_completion: Callable[..., LLMJsonCompletionResult] | None = None,
    prosecution_completion: Callable[..., LLMJsonCompletionResult] | None = None,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    resume_portfolio_receipt_path: Path | str | None = None,
    resume_review_receipt_path: Path | str | None = None,
    max_attempts: int = _MAX_IDEATION_ATTEMPTS,
    clock: datetime | None = None,
) -> SystemPlanIdeationArtifact:
    """Diverge, independently review, and return one accepted system direction."""

    if len(literature) < 3 or len(retrieved_catalog) < 3:
        raise SystemPlanIdeationError("方向竞赛至少需要三篇真实检索文献")
    literature_identity_map = _literature_identity_map(
        literature=literature,
        retrieved_catalog=retrieved_catalog,
    )
    selected_to_retrieved_reference = {
        int(item["selected_reference_index"]): int(item["retrieved_catalog_reference_index"])
        for item in literature_identity_map
    }
    prospective_allowlist = _prospective_direction_allowlist(
        component_experiment_binding=component_experiment_binding,
        selected_to_retrieved_reference=selected_to_retrieved_reference,
    )
    expected_context_hash = canonical_model_hash(dict(frozen_evidence_context))
    if opportunity_map.feasibility_envelope.source_context_hash != expected_context_hash:
        raise SystemPlanIdeationError("研究机会图与当前冻结证据上下文哈希不一致")
    component_binding_findings = _component_experiment_binding_findings(
        component_experiment_binding=component_experiment_binding,
        opportunity_map=opportunity_map,
        literature_identity_map=literature_identity_map,
        retrieved_catalog=retrieved_catalog,
    )
    if component_binding_findings:
        raise SystemPlanIdeationError(
            "组件实验绑定与当前方向输入不一致：" + "；".join(component_binding_findings)
        )
    if not opportunity_map.accepted_cells:
        raise SystemPlanIdeationError("方向竞赛至少需要一个独立评审通过的研究机会")
    if max_attempts < 1:
        raise SystemPlanIdeationError("方向竞赛尝试次数必须为正数")
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    reviewer = review_completion or completion
    prosecutor = prosecution_completion or reviewer
    if (resume_portfolio_receipt_path is None) != (resume_review_receipt_path is None):
        raise SystemPlanIdeationError("续跑必须同时提供方向作者回执与方向评审回执")
    previous_portfolio: dict[str, Any] | None
    feedback: tuple[str, ...]
    rejected_direction_signatures: set[str]
    rejected_direction_summaries: dict[str, dict[str, Any]]
    retained_receipt_hashes: dict[str, str] | None = None
    if resume_portfolio_receipt_path is not None and resume_review_receipt_path is not None:
        (
            previous_portfolio,
            feedback,
            rejected_direction_signatures,
            rejected_direction_summaries,
            retained_receipt_hashes,
        ) = _load_rejected_ideation_receipts(
            portfolio_receipt_path=resume_portfolio_receipt_path,
            review_receipt_path=resume_review_receipt_path,
            frozen_evidence_context=frozen_evidence_context,
            opportunity_map=opportunity_map,
            component_experiment_binding=component_experiment_binding,
            literature=literature,
            retrieved_catalog=retrieved_catalog,
        )
    else:
        previous_portfolio = None
        feedback = ()
        rejected_direction_signatures = set()
        rejected_direction_summaries = {}

    no_progress_state: dict[str, str | None] = {
        "payload_hash": None,
        "findings_hash": None,
    }

    def record_invalid_portfolio_progress(
        payload: Any,
        findings: Sequence[str],
    ) -> None:
        """Stop only when Qwen repeats the same invalid scientific draft.

        A later divergent draft may legitimately hit the same mechanical contract
        error (for example, opportunity-cell coverage) while still representing
        scientific progress.  The outer attempt budget already bounds that case.
        Treating an equal error string as an equal draft prematurely kills the
        autonomous loop.
        """

        if not isinstance(payload, Mapping):
            return
        payload_hash = canonical_model_hash(dict(payload))
        findings_hash = canonical_model_hash({"mechanical_findings": list(findings)})
        if no_progress_state["payload_hash"] == payload_hash:
            details = "；".join(findings)
            raise SystemPlanIdeationError(
                "方向生成连续两次返回相同无效内容，已停止确定性"
                f"无进展循环：{details}"
            )
        no_progress_state["payload_hash"] = payload_hash
        no_progress_state["findings_hash"] = findings_hash

    for attempt in range(1, max_attempts + 1):
        portfolio_draft = previous_portfolio
        portfolio_feedback = feedback
        portfolio: ResearchDirectionPortfolio | None = None
        accepted_portfolio_result: LLMJsonCompletionResult | None = None
        accepted_portfolio_receipt: ModelAuthorshipReceipt | None = None
        for repair_attempt in range(1, _MAX_PORTFOLIO_REPAIR_ATTEMPTS + 1):
            messages = _portfolio_messages(
                frozen_evidence_context=frozen_evidence_context,
                opportunity_map=opportunity_map,
                component_experiment_binding=component_experiment_binding,
                literature=literature,
                retrieved_catalog=retrieved_catalog,
                prior_portfolio=portfolio_draft,
                prior_feedback=portfolio_feedback,
                retained_receipt_hashes=retained_receipt_hashes,
                rejected_direction_summaries=tuple(rejected_direction_summaries.values()),
            )
            try:
                result = completion(
                    messages=messages,
                    config_path=config_path,
                    env_path=env_path,
                    timeout_seconds=300,
                    max_tokens=8_000,
                    # Divergence needs sampling; copying a closed mechanical patch
                    # does not.  Keeping repair at the creative temperature caused
                    # Qwen to resend an unchanged identity mismatch.
                    temperature=0.0 if repair_attempt > 1 else 0.6,
                    thinking_mode="enabled",
                    thinking_budget=4_000,
                    response_schema=None,
                    response_schema_name="research_direction_portfolio",
                )
            except (OSError, RuntimeError, ValueError) as exc:
                portfolio_feedback = _merge_feedback(
                    portfolio_feedback,
                    "方向组合模型调用或 JSON 解析失败：" f"{type(exc).__name__}: {exc}",
                )
                continue
            interaction_id = f"system-plan-ideation-attempt-{attempt:02d}"
            if repair_attempt > 1:
                interaction_id += f"-repair-{repair_attempt:02d}"
            portfolio_receipt = record_model_authorship_receipt(
                artifact_kind="plan_ideation",
                interaction_id=interaction_id,
                attempt=repair_attempt,
                messages=messages,
                completion=result,
                output_dir=output_root,
            )
            if isinstance(result.parsed_json, Mapping):
                portfolio_draft = dict(result.parsed_json)
            if (
                opportunity_map.method_skill_selection is not None
                and not str(result.reasoning_text or "").strip()
            ):
                portfolio_feedback = _merge_feedback(
                    portfolio_feedback,
                    "Qwen 未返回非空 reasoning_content，方向生成方法链不可审计",
                )
                record_invalid_portfolio_progress(
                    result.parsed_json,
                    portfolio_feedback,
                )
                continue
            try:
                projected_portfolio = _project_portfolio_payload(
                    result.parsed_json,
                    prospective_allowlist=prospective_allowlist,
                )
                candidate_portfolio = ResearchDirectionPortfolio.model_validate(
                    projected_portfolio
                )
            except (ValidationError, SystemPlanIdeationError, ValueError) as exc:
                portfolio_feedback = _merge_feedback(
                    portfolio_feedback,
                    f"方向组合结构或语言校验失败：{exc}",
                )
                record_invalid_portfolio_progress(
                    result.parsed_json,
                    portfolio_feedback,
                )
                continue
            invalid_selected_indices = sorted(
                {
                    index
                    for direction in candidate_portfolio.directions
                    for index in direction.nearest_work_indices
                    if not (1 <= index <= len(retrieved_catalog))
                }
            )
            if invalid_selected_indices:
                portfolio_feedback = _merge_feedback(
                    portfolio_feedback,
                    "方向引用了不存在的 retrieved catalog 编号：" f"{invalid_selected_indices}",
                )
                record_invalid_portfolio_progress(
                    result.parsed_json,
                    portfolio_feedback,
                )
                continue
            accepted_cells = {item.cell_id: item for item in opportunity_map.accepted_cells}
            eligible_systems = {
                item.system_name for item in opportunity_map.feasibility_envelope.eligible_systems
            }
            evidence_fact_ids = {
                item.fact_id for item in opportunity_map.feasibility_envelope.evidence_facts
            }
            binding_findings: list[str] = []
            bound_cell_ids = {
                direction.opportunity_cell_id for direction in candidate_portfolio.directions
            }
            accepted_cell_ids = set(accepted_cells)
            if len(accepted_cell_ids) >= _DIRECTION_COUNT:
                if len(bound_cell_ids) != _DIRECTION_COUNT:
                    binding_findings.append("存在至少五个合格机会时，五方向必须绑定五个不同机会格")
            elif bound_cell_ids != accepted_cell_ids:
                binding_findings.append(
                    "合格机会少于五个时，五方向必须至少覆盖每一个合格机会格："
                    f"missing={sorted(accepted_cell_ids - bound_cell_ids)}, "
                    f"extra={sorted(bound_cell_ids - accepted_cell_ids)}"
                )
            for direction_index, direction in enumerate(
                candidate_portfolio.directions,
                1,
            ):
                cell = accepted_cells.get(direction.opportunity_cell_id)
                if cell is None:
                    binding_findings.append(
                        f"方向绑定了未通过评审的机会格：{direction.opportunity_cell_id}"
                    )
                    continue
                binding_findings.extend(
                    f"方向{direction_index}：{finding}"
                    for finding in _prospective_direction_binding_findings(
                        direction=direction,
                        component_experiment_binding=component_experiment_binding,
                        selected_to_retrieved_reference=(
                            selected_to_retrieved_reference
                        ),
                        eligible_systems=eligible_systems,
                        evidence_fact_ids=evidence_fact_ids,
                    )
                )
            if binding_findings:
                # This is a mechanical patch to the current system-authored draft.
                # Do not drown it in the prior round's long scientific veto history.
                portfolio_feedback = tuple(dict.fromkeys(binding_findings))
                record_invalid_portfolio_progress(
                    result.parsed_json,
                    portfolio_feedback,
                )
                continue
            repeated_direction_indices = [
                index
                for index, direction in enumerate(
                    candidate_portfolio.directions,
                    1,
                )
                if _direction_scientific_signature(direction) in rejected_direction_signatures
            ]
            if repeated_direction_indices:
                portfolio_draft = None
                portfolio_feedback = _merge_feedback(
                    portfolio_feedback,
                    "这些方向与已被科学评审否决的前轮方向在科学缺口、核心机制、"
                    "可证伪假设、决定性实验、失败模式和方法 token 上逐字相同："
                    f"{repeated_direction_indices}；改标题或补文献编号不算新方向，"
                    "必须由系统自主提出新的可识别机制。",
                )
                record_invalid_portfolio_progress(
                    result.parsed_json,
                    portfolio_feedback,
                )
                continue
            portfolio = candidate_portfolio
            accepted_portfolio_result = result
            accepted_portfolio_receipt = portfolio_receipt
            previous_portfolio = portfolio.model_dump(mode="json")
            break
        if (
            portfolio is None
            or accepted_portfolio_result is None
            or accepted_portfolio_receipt is None
        ):
            previous_portfolio = portfolio_draft
            feedback = portfolio_feedback
            continue

        previous_review: dict[str, Any] | None = None
        review_judgment_history: list[dict[str, Any]] = []
        review_feedback: tuple[str, ...] = ()
        decision: ResearchDirectionDecision | None = None
        accepted_review_result: LLMJsonCompletionResult | None = None
        accepted_review_receipt: ModelAuthorshipReceipt | None = None
        for review_attempt in range(1, _MAX_REVIEW_REPAIR_ATTEMPTS + 1):
            review_messages = _review_messages(
                portfolio=portfolio,
                opportunity_map=opportunity_map,
                component_experiment_binding=component_experiment_binding,
                literature=literature,
                retrieved_catalog=retrieved_catalog,
                previous_review=previous_review,
                prior_feedback=review_feedback,
            )
            try:
                review_result = reviewer(
                    messages=review_messages,
                    config_path=config_path,
                    env_path=env_path,
                    timeout_seconds=300,
                    max_tokens=8_000,
                    temperature=0.0,
                    thinking_mode="enabled",
                    thinking_budget=4_000,
                    response_schema=None,
                    response_schema_name="research_direction_decision",
                )
            except (OSError, RuntimeError, ValueError) as exc:
                review_feedback = _merge_feedback(
                    review_feedback,
                    "方向评审模型调用或 JSON 解析失败：" f"{type(exc).__name__}: {exc}",
                )
                continue
            interaction_id = f"system-plan-ideation-review-attempt-{attempt:02d}"
            if review_attempt > 1:
                interaction_id += f"-repair-{review_attempt:02d}"
            review_receipt = record_model_authorship_receipt(
                artifact_kind="plan_ideation_review",
                interaction_id=interaction_id,
                attempt=review_attempt,
                messages=review_messages,
                completion=review_result,
                output_dir=output_root,
            )
            prior_reviews = tuple(review_judgment_history)
            if isinstance(review_result.parsed_json, Mapping):
                previous_review = dict(review_result.parsed_json)
            try:
                projected_review = _project_review_payload(review_result.parsed_json)
            except (SystemPlanIdeationError, ValueError) as exc:
                review_feedback = _merge_feedback(
                    review_feedback,
                    f"方向竞赛评审结构或投影失败：{exc}",
                )
                continue
            review_judgment_history.append(projected_review)
            review_feedback = _merge_feedback(
                review_feedback,
                *_raw_review_scientific_feedback(projected_review),
            )
            if (
                opportunity_map.method_skill_selection is not None
                and not str(review_result.reasoning_text or "").strip()
            ):
                review_feedback = _merge_feedback(
                    review_feedback,
                    "Qwen 评审未返回非空 reasoning_content，方向审查方法链不可审计",
                )
                continue
            try:
                candidate_decision = ResearchDirectionDecision.model_validate(
                    projected_review
                )
            except (ValidationError, SystemPlanIdeationError, ValueError) as exc:
                review_feedback = _merge_feedback(
                    review_feedback,
                    f"方向竞赛评审结构或逻辑校验失败：{exc}",
                )
                continue
            monotonic_findings = _review_repair_monotonic_findings(
                prior_reviews=prior_reviews,
                candidate=candidate_decision,
            )
            if monotonic_findings:
                review_feedback = _merge_feedback(review_feedback, *monotonic_findings)
                continue
            invalid_catalog_indices = sorted(
                {
                    comparison.reference_index
                    for assessment in candidate_decision.assessments
                    for comparison in assessment.prior_work_comparisons
                    if comparison.reference_index > len(retrieved_catalog)
                }
            )
            if invalid_catalog_indices:
                review_feedback = _merge_feedback(
                    review_feedback,
                    "方向评审引用了不存在的检索目录编号：" f"{invalid_catalog_indices}",
                )
                continue
            review_scope_findings = _decision_scope_findings(candidate_decision)
            if review_scope_findings:
                review_feedback = _merge_feedback(review_feedback, *review_scope_findings)
                continue
            decision = candidate_decision
            accepted_review_result = review_result
            accepted_review_receipt = review_receipt
            break
        if decision is None or accepted_review_result is None or accepted_review_receipt is None:
            feedback = review_feedback
            continue
        if decision.selected_direction_index is None:
            for index, assessment in enumerate(decision.assessments):
                if assessment.qualifies():
                    continue
                direction = portfolio.directions[index]
                signature = _direction_scientific_signature(direction)
                rejected_direction_signatures.add(signature)
                rejected_direction_summaries[signature] = _rejected_direction_summary(direction)
            previous_portfolio = None
            feedback = _merge_feedback(
                review_feedback,
                *decision.feedback(),
                *_failed_gate_feedback(decision),
            )
            continue

        selected = portfolio.directions[decision.selected_direction_index - 1]
        previous_prosecution: dict[str, Any] | None = None
        prosecution_judgment_history: list[dict[str, Any]] = []
        prosecution_feedback = review_feedback
        prosecution: SelectedDirectionProsecution | None = None
        accepted_prosecution_result: LLMJsonCompletionResult | None = None
        accepted_prosecution_receipt: ModelAuthorshipReceipt | None = None
        for prosecution_attempt in range(1, _MAX_REVIEW_REPAIR_ATTEMPTS + 1):
            prosecution_messages = _prosecution_messages(
                selected_direction_index=decision.selected_direction_index,
                selected_direction=selected,
                decision=decision,
                opportunity_map=opportunity_map,
                component_experiment_binding=component_experiment_binding,
                literature=literature,
                retrieved_catalog=retrieved_catalog,
                previous_prosecution=previous_prosecution,
                prior_feedback=prosecution_feedback,
            )
            try:
                prosecution_result = prosecutor(
                    messages=prosecution_messages,
                    config_path=config_path,
                    env_path=env_path,
                    timeout_seconds=300,
                    max_tokens=6_000,
                    temperature=0.0,
                    thinking_mode="enabled",
                    thinking_budget=4_000,
                    response_schema=None,
                    response_schema_name="selected_direction_prosecution",
                )
            except (OSError, RuntimeError, ValueError) as exc:
                prosecution_feedback = _merge_feedback(
                    prosecution_feedback,
                    "入选方向反方审查模型调用或 JSON 解析失败：" f"{type(exc).__name__}: {exc}",
                )
                continue
            interaction_id = f"system-plan-ideation-prosecution-attempt-{attempt:02d}"
            if prosecution_attempt > 1:
                interaction_id += f"-repair-{prosecution_attempt:02d}"
            prosecution_receipt = record_model_authorship_receipt(
                artifact_kind="plan_ideation_prosecution",
                interaction_id=interaction_id,
                attempt=prosecution_attempt,
                messages=prosecution_messages,
                completion=prosecution_result,
                output_dir=output_root,
            )
            prior_prosecutions = tuple(prosecution_judgment_history)
            if isinstance(prosecution_result.parsed_json, Mapping):
                previous_prosecution = dict(prosecution_result.parsed_json)
            try:
                projected_prosecution = _project_prosecution_payload(
                    prosecution_result.parsed_json,
                    selected_direction_index=decision.selected_direction_index,
                )
            except (SystemPlanIdeationError, ValueError) as exc:
                prosecution_feedback = _merge_feedback(
                    prosecution_feedback,
                    f"入选方向反方审查结构或投影失败：{exc}",
                )
                continue
            prosecution_judgment_history.append(projected_prosecution)
            prosecution_feedback = _merge_feedback(
                prosecution_feedback,
                *_raw_prosecution_scientific_feedback(projected_prosecution),
            )
            if (
                opportunity_map.method_skill_selection is not None
                and not str(prosecution_result.reasoning_text or "").strip()
            ):
                prosecution_feedback = _merge_feedback(
                    prosecution_feedback,
                    "Qwen 反方审查未返回非空 reasoning_content，反方方法链不可审计",
                )
                continue
            try:
                candidate_prosecution = SelectedDirectionProsecution.model_validate(
                    projected_prosecution
                )
            except (ValidationError, SystemPlanIdeationError, ValueError) as exc:
                prosecution_feedback = _merge_feedback(
                    prosecution_feedback,
                    f"入选方向反方审查结构或逻辑校验失败：{exc}",
                )
                continue
            monotonic_findings = _prosecution_repair_monotonic_findings(
                prior_prosecutions=prior_prosecutions,
                candidate=candidate_prosecution,
            )
            if monotonic_findings:
                prosecution_feedback = _merge_feedback(prosecution_feedback, *monotonic_findings)
                continue
            invalid_catalog_indices = sorted(
                {
                    comparison.reference_index
                    for comparison in candidate_prosecution.closest_prior_work
                    if comparison.reference_index > len(retrieved_catalog)
                }
            )
            if invalid_catalog_indices:
                prosecution_feedback = _merge_feedback(
                    prosecution_feedback,
                    "入选方向反方审查引用了不存在的检索目录编号：" f"{invalid_catalog_indices}",
                )
                continue
            prosecution_scope_findings = _prosecution_scope_findings(candidate_prosecution)
            if prosecution_scope_findings:
                prosecution_feedback = _merge_feedback(
                    prosecution_feedback, *prosecution_scope_findings
                )
                continue
            prosecution = candidate_prosecution
            accepted_prosecution_result = prosecution_result
            accepted_prosecution_receipt = prosecution_receipt
            break
        if (
            prosecution is None
            or accepted_prosecution_result is None
            or accepted_prosecution_receipt is None
        ):
            raw_scientific_veto = any(
                _raw_prosecution_scientific_feedback(raw_payload)
                for raw_payload in prosecution_judgment_history
            )
            if raw_scientific_veto:
                # A structurally contradictory response can still contain an
                # unmistakable scientific veto (false gate, critical finding, or
                # required revision).  Preserve that veto conservatively instead of
                # letting a mistaken ``survives=true`` make the same direction
                # eligible for immediate resubmission.
                selected_signature = _direction_scientific_signature(selected)
                rejected_direction_signatures.add(selected_signature)
                rejected_direction_summaries[selected_signature] = (
                    _rejected_direction_summary(selected)
                )
                previous_portfolio = None
            feedback = prosecution_feedback
            continue
        if not prosecution.survives_adversarial_review:
            selected_signature = _direction_scientific_signature(selected)
            rejected_direction_signatures.add(selected_signature)
            rejected_direction_summaries[selected_signature] = _rejected_direction_summary(selected)
            previous_portfolio = None
            feedback = _merge_feedback(prosecution_feedback, *prosecution.feedback())
            continue

        payload: dict[str, Any] = {
            "schema_version": "system-plan-ideation-v4",
            "lineage_id": lineage_id,
            "opportunity_map_hash": opportunity_map.opportunity_map_hash,
            "component_experiment_binding": (
                component_experiment_binding.model_dump(mode="json")
            ),
            "component_experiment_binding_hash": (
                component_experiment_binding.binding_hash
            ),
            "authoring_attempt": attempt,
            "portfolio": portfolio.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
            "selected_direction": selected.model_dump(mode="json"),
            "selected_direction_hash": canonical_model_hash(selected.model_dump(mode="json")),
            "portfolio_authorship_receipt_relative_path": Path(
                accepted_portfolio_receipt.output_path
            )
            .resolve()
            .relative_to(output_root)
            .as_posix(),
            "portfolio_authorship_receipt_hash": accepted_portfolio_receipt.receipt_hash,
            "review_authorship_receipt_relative_path": Path(accepted_review_receipt.output_path)
            .resolve()
            .relative_to(output_root)
            .as_posix(),
            "review_authorship_receipt_hash": accepted_review_receipt.receipt_hash,
            "prosecution": prosecution.model_dump(mode="json"),
            "prosecution_authorship_receipt_relative_path": Path(
                accepted_prosecution_receipt.output_path
            )
            .resolve()
            .relative_to(output_root)
            .as_posix(),
            "prosecution_authorship_receipt_hash": (accepted_prosecution_receipt.receipt_hash),
            "portfolio_model_name": accepted_portfolio_result.model_name,
            "review_model_name": accepted_review_result.model_name,
            "prosecution_model_name": accepted_prosecution_result.model_name,
            "authored_by_model": True,
            "hand_written_scientific_prose_count": 0,
            "execution_authorized": False,
            "is_scientific_evidence": False,
            "created_at": (clock or datetime.now(timezone.utc))
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        payload["artifact_hash"] = canonical_model_hash(payload)
        output_path = output_root / _ARTIFACT_NAME
        payload["output_path"] = output_path.as_posix()
        artifact = SystemPlanIdeationArtifact.model_validate(payload)
        write_json_model(output_path, artifact)
        return artifact

    raise SystemPlanIdeationError(
        "系统未能在发散方向竞赛中产生全门禁合格方向；最终反馈：" f"{list(feedback)}"
    )
